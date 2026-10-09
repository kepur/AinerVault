"""画布「自由生成」：提示词 + 参考 + 模型 + 参数 → N 个产物。

能力层（service.submit_task）本来就能调任意能力、交任意 payload，缺的只有三件事，
这里只补这三件，其余一律复用：

  1. **选能力**：按参考的角色定 t2i / i2i / i2v。能力枚举里没有 video.text_to_video ——
     文生视频就是 video.image_to_video 不给首帧，只有自描述里写了
     supports.text_to_video 的模型（LTX-2.5）认这种请求，别的模型必须有首帧。
  2. **夹参数**：画幅、分辨率、时长、条数、参考张数按模型自描述的 limits 夹到合法值，
     夹过的都写进 warnings —— 面板上「按 1024×576 出」就是这里给的。
  3. **交任务**：count 次循环，第 i 次 seed+i。幂等键是 input 的哈希，
     seed 一样的两条会被合成同一个任务，用户要两条却只拿到一条。

产物不回挂：ref_kind="canvas_node" 是 _attach_to_ref 不认识的 kind，它对未知 kind
什么都不做（不报错，见 tests/test_canvas_gen.py）。画布按 task id 自己来取，
取的时候只给已经落进本库 /media 的地址 —— 网关给的是它暂存目录的地址，会被清。
"""
from __future__ import annotations

import hashlib
import logging
import math
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.errors import CapabilityError
from app.capability.router import ResolvedRoute, resolve_routes
from app.capability.schemas import Capability
from app.capability.service import poll_task, route_blocked, submit_task
from app.config import get_settings
from app.models import (
    Asset, AssetKind, CapabilityEndpoint, CapabilityRoute, GenTask, TaskStatus,
)
from app.pipelines.base import as_items

log = logging.getLogger(__name__)

#: 路由用途。运维可以单给画布配一条路由（purpose=canvas），没配就回落到 (*, *)
PURPOSE = "canvas"
REF_KIND = "canvas_node"
#: 一次最多几条。视频模型都没有 n，条数靠循环提交；本机一块 GPU，四条已经排很久
MAX_COUNT = 4
DEFAULT_VIDEO_MS = 5_000
MIN_VIDEO_MS = 1_000
FPS = 24
#: data: 参考只有演示/离线时才会出现，网关要整段 base64 收下，给个上限
DATA_URL_MAX = 10 * 1024 * 1024
#: gen_tasks.ref_id 是 varchar(32)
REF_ID_MAX = 32

T2I = Capability.image_t2i.value
I2I = Capability.image_i2i.value
I2V = Capability.video_i2v.value
CAPS_BY_MEDIA: dict[str, tuple[str, ...]] = {"image": (T2I, I2I), "video": (I2V,)}

#: 前端 RefRole（F/src/canvas/model.ts）
KNOWN_ROLES = frozenset({
    "character", "first_frame", "last_frame", "style", "scene",
    "reference_sheet", "control_video", "base", "reference",
})
#: 对图片来说「首帧」就是「从这张图出发」。生成面板的角色下拉里没有「底图」，
#: 只认 base 的话图生图在画布上永远走不到
BASE_ROLES = ("base", "first_frame")
IDENTITY_ROLES = ("reference_sheet", "character")
CONTROL_TAGS = ("depth", "pose", "canny")
#: 前端角色 → 契约 RefRole（schemas.RefRole 只有这四个）
_CORE_ROLE = {
    "character": "character", "reference_sheet": "character",
    "style": "style", "scene": "scene", "reference": "scene",
    "control_video": "composition",
}


# ── 请求与错误 ───────────────────────────────────────────────────────────────

from app.production.schema import ResourceRef


class RefIn(BaseModel):
    """一条参考。url 只认本库 /media/… 或 data:（铁律：网关临时地址不当长期链接）。"""

    node_id: str = ""
    production_ref: ResourceRef | None = None
    url: str = ""
    asset_id: str | None = None
    kind: Literal["image", "video", "audio"] = "image"
    role: str = "reference"
    tag: str | None = None

    @property
    def label(self) -> str:
        return self.tag or self.node_id or "未命名参考"


class TargetIn(BaseModel):
    board_id: str | None = None
    plan_id: str | None = None
    node_id: str


class GenerateIn(BaseModel):
    """字段与前端 GenerateBody（F/src/canvas/model.ts）一一对应，另加 confirm_cost。"""

    media: Literal["image", "video"]
    endpoint_id: str | None = None
    model: str | None = None
    prompt: str = ""
    negative_prompt: str | None = None
    refs: list[RefIn] = Field(default_factory=list)
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    duration_ms: int | None = None
    count: int = 1
    seed: int | None = None
    target: TargetIn | None = None
    confirm_cost: bool = False


class GenerateError(Exception):
    """能预见的拒绝：带 HTTP 状态和机器可读的 code，路由层原样转成 detail。"""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


# ── 模型目录 ─────────────────────────────────────────────────────────────────

@dataclass
class ModelInfo:
    """一个端点上、一项能力下的一个模型（取自端点的 caps_cache_json）。"""

    endpoint_id: str
    endpoint_name: str
    model: str
    label: str
    capability: str
    ready: bool = True
    local: bool = False
    is_default: bool = False
    cost: float | None = None
    currency: str = "USD"
    estimated_ms: int | None = None
    sizes: list[tuple[int, int]] = field(default_factory=list)
    size_multiple: int | None = None
    max_duration_ms: int | None = None
    max_ref_images: int | None = None
    max_prompt_chars: int | None = None
    supports: dict[str, Any] = field(default_factory=dict)
    #: 能跑哪些控制视频（v2v/depth/pose/canny/union）。没声明 = 不支持
    control_types: list[str] = field(default_factory=list)


_SIZE = re.compile(r"^\s*(\d+)\s*[x×*X]\s*(\d+)\s*$")
_LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def parse_sizes(raw: Any) -> list[tuple[int, int]]:
    """limits.sizes → [(w, h)]。网关写 "1024x576"，百炼写 "W*H"，也容忍 [w, h] 与 {width, height}。"""
    out: list[tuple[int, int]] = []
    for item in raw or []:
        w: Any = None
        h: Any = None
        if isinstance(item, str):
            m = _SIZE.match(item)
            if m:
                w, h = m.group(1), m.group(2)
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            w, h = item
        elif isinstance(item, dict):
            w, h = item.get("width"), item.get("height")
        try:
            size = (int(w), int(h))
        except (TypeError, ValueError):
            continue
        if size[0] > 0 and size[1] > 0 and size not in out:
            out.append(size)
    return out


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def is_local_endpoint(base_url: str | None) -> bool:
    """「本机」小标：只看端点地址是不是回环。局域网的显卡机不算本机。"""
    host = (urlsplit(base_url or "").hostname or "").lower()
    return host in _LOOPBACK or host.startswith("127.")


def catalog_models(ep: Any, caps: Sequence[str]) -> list[ModelInfo]:
    """端点缓存的能力目录里、属于 caps 的模型。

    直接读 JSON，不过 CapabilityCatalog 校验：枚举里没有的能力（video.lip_sync 之类）
    出现在缓存里时，校验会让整个模型列表 500，而我们只关心其中几项。
    """
    raw = getattr(ep, "caps_cache_json", None) or {}
    out: list[ModelInfo] = []
    for entry in as_items(raw, "capabilities"):
        if entry.get("capability") not in caps:
            continue
        models = [m for m in entry.get("models") or [] if isinstance(m, dict) and m.get("id")]
        default_id = next((m["id"] for m in models if m.get("default")), models[0]["id"] if models else None)
        for m in models:
            limits = m.get("limits") or {}
            pricing = m.get("pricing") or {}
            supports = dict(m.get("supports") or {})
            out.append(ModelInfo(
                endpoint_id=ep.id, endpoint_name=getattr(ep, "name", "") or "",
                model=str(m["id"]), label=str(m.get("display_name") or m["id"]),
                capability=str(entry["capability"]),
                # 网关对没装齐的模型写 ready:false（LTX-2.5 缺权重时）；没写的按就绪
                ready=m.get("ready") is not False,
                local=is_local_endpoint(getattr(ep, "base_url", None)),
                is_default=m["id"] == default_id,
                cost=pricing.get("cost") if isinstance(pricing.get("cost"), (int, float)) else None,
                currency=str(pricing.get("currency") or "USD"),
                estimated_ms=_int_or_none(m.get("estimated_ms")),
                sizes=parse_sizes(limits.get("sizes")),
                size_multiple=_int_or_none(limits.get("size_multiple")),
                max_duration_ms=_int_or_none(limits.get("max_duration_ms")),
                max_ref_images=_int_or_none(limits.get("max_ref_images")),
                max_prompt_chars=_int_or_none(limits.get("max_prompt_chars")),
                supports=supports,
                control_types=[str(t) for t in m.get("control_types") or []],
            ))
    return out


def _enabled_routes(db: Session) -> list[CapabilityRoute]:
    return list(db.execute(
        select(CapabilityRoute).where(CapabilityRoute.enabled.is_(True))
    ).scalars())


def route_for(info: ModelInfo, ep: CapabilityEndpoint,
              routes: Sequence[CapabilityRoute]) -> tuple[ResolvedRoute, bool]:
    """用户点名的模型 → 一条可以交给 submit_task 的路由 + 它有没有配进路由表。

    **付费闸的依据在路由上，不在模型上**（default_params.billing / approved / free_quota），
    所以点名的模型也得找回它的路由，否则连本机免费的 FLUX 都会按「未标注 = 付费」拦掉。
    找的顺序：画布用途（canvas）或通用（*）的路由原样用；只有别的用途配了它时，
    只借 billing 和 free_quota —— 那是模型本身的属性；approved 是「这个用途批准花钱」，
    不能借给画布。一条都没有就是空参数，route_blocked 会按「未标注」处置。
    """
    rows = [r for r in routes
            if r.capability == info.capability and r.endpoint_id == ep.id
            and (r.model == info.model or (r.model is None and info.is_default))]
    own = sorted((r for r in rows if r.purpose in (PURPOSE, "*")),
                 key=lambda r: (r.purpose != PURPOSE, r.priority))
    params: dict[str, Any] = {}
    priority, tier = 0, "*"
    if own:
        params = dict(own[0].default_params or {})
        priority, tier = own[0].priority, own[0].tier
    elif rows:
        other = min(rows, key=lambda r: r.priority)
        params = {k: v for k, v in (other.default_params or {}).items()
                  if k in ("billing", "free_quota")}
    route = ResolvedRoute(endpoint=ep, capability=Capability(info.capability), model=info.model,
                          default_params=params, priority=priority, tier=tier)
    return route, bool(rows)


#: 跑在本机、却按张收钱的方言（本机混元网关 0.2 元/张，见 dialects.DIALECT_HUNYUAN）：本机豁免不包括它
PAID_LOCAL_DIALECTS = frozenset({"hunyuan_image"})


def local_free(route: ResolvedRoute) -> bool:
    """本机端点上的免费模型：不过付费闸。

    付费闸的依据在路由上（billing / approved），而本机网关的模型多半没配进路由表 ——
    点名 flux2-klein-4b-edit 时 route_for 找不到路由，billing 是 unknown，按「不确定就当它要钱」拦下，
    于是画布执行器、生成面板连本机自己的显卡都用不了（keyframe._route 早就绕开了这一层）。
    但**跑在本地不等于免费**：混元网关地址是 127.0.0.1、照样按张收费。所以只放
    「回环地址 + 不是收费方言 + 模型自报价格不大于 0（没报价的本机模型按免费）」。
    """
    ep = route.endpoint
    if not is_local_endpoint(getattr(ep, "base_url", None)):
        return False
    if (getattr(ep, "dialect", None) or "") in PAID_LOCAL_DIALECTS:
        return False
    info = _info_for_route(route)
    return not (info is not None and info.cost is not None and info.cost > 0)


def blocked_reason(db: Session, route: ResolvedRoute, routed: bool) -> str | None:
    if local_free(route):
        return None
    why = route_blocked(db, route)
    if why and not routed:
        return f"这个模型没有配进能力路由（设置 › 能力路由），{why}"
    return why


def _short_block(why: str) -> str:
    if "额度" in why:
        return "免费额度用尽"
    if "没有配进能力路由" in why:
        return "未配路由"
    return "付费·未批准"


def to_option(info: ModelInfo, media: str, *, billing: str, blocked: str | None,
              routed: bool) -> dict[str, Any]:
    """ModelInfo → 前端 ModelOption。

    cost：有标价用标价；没标价但路由标了免费记 0；都没有给 null（不能把「不知道」写成 0，
    面板会显示成「免费」）。
    """
    cost = info.cost if info.cost is not None else (0.0 if billing == "free" else None)
    label = info.label + (f"（{_short_block(blocked)}）" if blocked else "")
    return {
        "endpoint_id": info.endpoint_id,
        "model": info.model,
        "label": label,
        "capability": info.capability,
        "media": media,
        "ready": info.ready and blocked is None,
        "local": info.local,
        "cost": cost,
        "estimated_ms": info.estimated_ms,
        "limits": {
            "sizes": [list(s) for s in info.sizes],
            "max_duration_ms": info.max_duration_ms,
            "max_ref_images": info.max_ref_images,
            "max_count": MAX_COUNT,
        },
        "supports": {
            **info.supports,
            "control_types": info.control_types,
            "billing": billing,
            "routed": routed,
            "blocked": blocked,
            "endpoint_name": info.endpoint_name,
            "currency": info.currency,
        },
    }


def list_models(db: Session, media: str) -> list[dict[str, Any]]:
    """所有启用端点上、这类媒体能用的模型（同 GET /settings/capabilities 那份目录）。

    被付费闸拦着的也列出来但 ready=false，标题后面注明原因 —— 藏起来的话，
    人会以为没接这个模型，而不是没批准。
    """
    caps = CAPS_BY_MEDIA.get(media)
    if not caps:
        return []
    endpoints = list(db.execute(
        select(CapabilityEndpoint).where(CapabilityEndpoint.enabled.is_(True))
        .order_by(CapabilityEndpoint.name)
    ).scalars())
    routes = _enabled_routes(db)
    rows: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for ep in endpoints:
        for i, info in enumerate(catalog_models(ep, caps)):
            route, routed = route_for(info, ep, routes)
            blocked = blocked_reason(db, route, routed)
            # 本机免费模型（见 local_free）面板上标「免费」，不是「未标价」
            billing = "free" if local_free(route) else route.billing
            opt = to_option(info, media, billing=billing, blocked=blocked, routed=routed)
            # 视频把能文生视频的排前面：画布上的自由生成多半没有首帧，
            # 默认选中一个必须有首帧的模型，第一次点发送就会被拒
            t2v_first = media == "video" and not info.supports.get("text_to_video")
            rows.append(((not opt["ready"], t2v_first, not routed, ep.name, i), opt))
    rows.sort(key=lambda r: r[0])
    return [opt for _, opt in rows]


# ── 选能力、夹参数（纯函数）──────────────────────────────────────────────────

def pick_capability(media: str, refs: Sequence[RefIn]) -> str:
    """图片：有底图（base / 首帧）→ 图生图，否则文生图；视频：只有 image_to_video 一项。"""
    if media == "image":
        has_base = any(r.kind == "image" and r.role in BASE_ROLES for r in refs)
        return I2I if has_base else T2I
    # 枚举里没有 video.text_to_video；不给首帧的 i2v 就是文生视频（看模型认不认）
    return I2V


_AR_SAME = 0.02     # 画幅差在 2% 以内算同一个画幅
_AR_SLACK = 0.07    # 和最接近的画幅差不超过这么多，就按面积挑（5:3 对 16:9 约 6.4%）


def _parse_aspect(aspect: str, warnings: list[str]) -> tuple[int, int]:
    m = re.match(r"^\s*(\d+)\s*[:：/xX]\s*(\d+)\s*$", aspect or "")
    if m and int(m.group(1)) > 0 and int(m.group(2)) > 0:
        return int(m.group(1)), int(m.group(2))
    warnings.append(f"认不出画幅「{aspect}」，按 16:9 出")
    return 16, 9


def _parse_resolution(resolution: str, warnings: list[str]) -> int:
    m = re.match(r"^\s*(\d{3,4})\s*[pP]?\s*$", resolution or "")
    if m:
        return int(m.group(1))
    warnings.append(f"认不出分辨率「{resolution}」，按 720p 出")
    return 720


def _align(v: float, m: int) -> int:
    return max(m, int(round(v / m)) * m)


def clamp_size(aspect: str, resolution: str, sizes: Any = None,
               multiple: int | None = None) -> tuple[int, int, list[str]]:
    """画幅 + 分辨率 → 模型认的宽高。

    模型列了 sizes（本机模型都列了）就只能从里面挑：先挑画幅最接近的一组，
    组里再挑面积最接近的 —— 只看画幅的话 480p 也会被拉到 1024×576，慢一倍。
    没列 sizes 就按短边算，再对齐到 size_multiple。
    """
    warnings: list[str] = []
    aw, ah = _parse_aspect(aspect, warnings)
    short = _parse_resolution(resolution, warnings)
    if aw >= ah:
        tw, th = round(short * aw / ah), short
    else:
        tw, th = short, round(short * ah / aw)
    cands = parse_sizes(sizes)
    if not cands:
        m = multiple if multiple and multiple > 0 else 8
        return _align(tw, m), _align(th, m), warnings

    target = tw / th

    def gap(s: tuple[int, int]) -> float:
        return abs(math.log((s[0] / s[1]) / target))

    best = min(gap(s) for s in cands)
    close = [s for s in cands if gap(s) <= best + _AR_SLACK]
    area = tw * th
    w, h = min(close, key=lambda s: (abs(math.log(s[0] * s[1] / area)), gap(s)))
    if (w, h) != (tw, th):
        if best > _AR_SAME:
            warnings.append(f"该模型没有 {aspect} 画幅，按最接近的 {w}×{h} 出")
        elif gap((w, h)) > _AR_SAME:
            warnings.append(f"按 {w}×{h} 出（{resolution} 下最接近的尺寸，画幅略有出入）")
        elif w * h < area and w * h == max(s[0] * s[1] for s in close):
            warnings.append(f"该模型最大 {w}×{h}，按此出")
        else:
            warnings.append(f"该模型没有 {tw}×{th}，按 {w}×{h} 出")
    return w, h, warnings


def clamp_duration(ms: int | None, max_ms: int | None) -> tuple[int, list[str]]:
    warnings: list[str] = []
    out = DEFAULT_VIDEO_MS if ms is None else int(ms)
    if out < MIN_VIDEO_MS:
        warnings.append(f"时长太短，按 {MIN_VIDEO_MS / 1000:g}s 出")
        out = MIN_VIDEO_MS
    if max_ms and out > max_ms:
        warnings.append(f"该模型最长 {max_ms / 1000:g}s，按 {max_ms / 1000:g}s 出")
        out = int(max_ms)
    return out, warnings


def clamp_count(n: int | None, max_count: int | None = MAX_COUNT) -> tuple[int, list[str]]:
    warnings: list[str] = []
    out = max(1, int(n or 1))
    cap = max_count or MAX_COUNT
    if out > cap:
        warnings.append(f"一次最多出 {cap} 条，按 {cap} 条出")
        out = cap
    return out, warnings


def fit_refs(capability: str, refs: Sequence[RefIn],
             info: ModelInfo | None = None) -> tuple[list[RefIn], list[str]]:
    """把参考整理成这项能力、这个模型收得下的样子；收不下的丢掉并写明原因。

    整理完每条参考的 role 就是它在 payload 里的位置（build_payload 照着摆）：
      图生图   base 一张 + 其余进 reference_images（底图也占 max_ref_images 的名额）
      文生图   全进 reference_images
      图生视频 first_frame / last_frame / reference_sheet 各一张，control_video 一条，
              其余图进 reference_images
    """
    warnings: list[str] = []
    usable: list[RefIn] = []
    for r in refs:
        role = r.role if r.role in KNOWN_ROLES else "reference"
        if r.kind == "audio":
            warnings.append(f"参考「{r.label}」是音频，画布生成还用不上，已跳过")
            continue
        if capability.startswith("image.") and r.kind != "image":
            warnings.append(f"出图用不上视频参考「{r.label}」，已跳过")
            continue
        usable.append(r.model_copy(update={"role": role}))

    def cap_refs(items: list[RefIn], limit: int | None) -> list[RefIn]:
        if limit is None or len(items) <= limit:
            return items
        # 身份参考优先留：多出来的往往是风格图，丢它比丢脸代价小
        ranked = sorted(items, key=lambda r: r.role not in IDENTITY_ROLES)
        kept, dropped = ranked[:max(limit, 0)], ranked[max(limit, 0):]
        name = f"「{info.label}」" if info else "所选模型"
        if limit <= 0:
            warnings.append(f"{name}不吃参考图，{len(dropped)} 张参考没用上"
                            f"（要保脸：给一张底图并选图像编辑模型）")
        else:
            warnings.append(f"{name}最多收 {limit} 张参考，"
                            f"{'、'.join(r.label for r in dropped)} 没用上")
        return kept

    max_refs = info.max_ref_images if info else None
    if capability == I2I:
        base = next((r for r in usable if r.role in BASE_ROLES), None)
        rest = [r for r in usable if r is not base]
        extra_bases = [r for r in rest if r.role in BASE_ROLES]
        if extra_bases:
            warnings.append(f"只能有一张底图，{'、'.join(r.label for r in extra_bases)} 改当一般参考")
            rest = [r.model_copy(update={"role": "reference"}) if r.role in BASE_ROLES else r for r in rest]
        rest = cap_refs(rest, None if max_refs is None else max_refs - 1)
        return ([base.model_copy(update={"role": "base"})] if base else []) + rest, warnings

    if capability == T2I:
        # 文生图没有底图和首尾帧这些位置，降成一般参考；图片控制（深度图之类）仍按构图参考送
        plain = [r.model_copy(update={"role": "reference"}) if r.role in BASE_ROLES
                 or r.role == "last_frame" else r for r in usable]
        return cap_refs(plain, max_refs), warnings

    # ── 图生视频 ──
    images =[r for r in usable if r.kind == "image"]
    videos = [r for r in usable if r.kind == "video"]

    def take_one(pool: list[RefIn], roles: Sequence[str], as_role: str, what: str) -> RefIn | None:
        hits = [r for r in pool if r.role in roles]
        hits.sort(key=lambda r: roles.index(r.role))
        for r in hits:
            pool.remove(r)
        if len(hits) > 1:
            warnings.append(f"{what}只收一张，{'、'.join(r.label for r in hits[1:])} 没用上")
        return hits[0].model_copy(update={"role": as_role}) if hits else None

    first = take_one(images, BASE_ROLES, "first_frame", "首帧")
    last = take_one(images, ("last_frame",), "last_frame", "尾帧")
    # 身份：设定图优先，否则拿第一张定妆照当设定图（LTX-2.5 的 Ingredients 只收一张）
    sheet = take_one(images, IDENTITY_ROLES, "reference_sheet", "身份参考")

    control: RefIn | None = None
    for r in videos:
        if r.role != "control_video":
            warnings.append(f"视频参考「{r.label}」只能当控制视频用（把它的角色设为「控制」），这次没用上")
            continue
        if control is not None:
            warnings.append(f"控制视频只收一条，「{r.label}」没用上")
            continue
        want = r.tag if r.tag in CONTROL_TAGS else "v2v"
        types = info.control_types if info else None
        if types is not None and want not in types:
            name = f"「{info.label}」" if info else "所选模型"
            warnings.append(f"{name}跑不了「{want}」控制视频（它能跑的：{'、'.join(types) or '无'}），"
                            f"控制参考「{r.label}」没用上")
            continue
        control = r.model_copy(update={"role": "control_video", "tag": want})

    if control and sheet:
        # LTX-2.5 两个 IC-LoRA 的参考缩放不同，引擎不许同一次混用；白模控制是人刻意连的，留它
        warnings.append(f"控制视频和身份设定图不能同一次用，这次只用控制视频，「{sheet.label}」没用上")
        sheet = None

    if images:
        warnings.append("视频模型多半不读风格/一般参考图（LTX-2.5 明确忽略）；"
                        "要定开头画面把角色设为「首帧」，要保脸设为「身份」")
    out = [r for r in (first, last, sheet, control) if r is not None] + cap_refs(images, max_refs)
    return out, warnings


def _src(r: RefIn) -> dict[str, Any]:
    """参考 → 契约 AssetRefIn。data: 拆成 b64 + mime；其余是网关能取的绝对地址。

    **不传 asset_id**：网关把 asset_id 当成它自己输出目录里的文件名，
    传 Core 的资产 id 过去只会得到「asset_id 不存在」。
    """
    if r.url.startswith("data:"):
        head, _, data = r.url.partition(",")
        mime = head[5:].split(";", 1)[0] or "application/octet-stream"
        return {"b64": data, "mime": mime}
    return {"url": r.url}


def _ref_image(r: RefIn) -> dict[str, Any]:
    item: dict[str, Any] = {"ref": _src(r), "role": _CORE_ROLE.get(r.role, "scene"), "weight": 0.8}
    if r.tag:
        item["tag"] = r.tag
    if r.role in IDENTITY_ROLES:
        # 网关的图像编辑只按 identity=true 挑人脸，不按顺序 —— 按顺序会挑到风格图
        item["identity"] = True
    return item


def build_payload(capability: str, body: GenerateIn, w: int, h: int,
                  duration_ms: int | None, seed: int | None) -> dict[str, Any]:
    """按契约 input 形状（schemas.T2IInput / I2IInput / I2VInput）摆好。refs 须已过 fit_refs。"""
    payload: dict[str, Any] = {"prompt": body.prompt, "width": w, "height": h,
                               "params": {"seed": seed} if seed is not None else {}}
    if body.negative_prompt:
        payload["negative_prompt"] = body.negative_prompt
    refs = list(body.refs)

    if capability == I2I:
        base = next((r for r in refs if r.role == "base"), None)
        if base is not None:
            payload["image"] = _src(base)
        others = [_ref_image(r) for r in refs if r is not base and r.kind == "image"]
        if others:
            payload["reference_images"] = others
        return payload

    if capability == T2I:
        payload["n"] = 1   # 条数靠循环；百炼认 n，别让路由默认参数把一条变成好几张
        images = [_ref_image(r) for r in refs if r.kind == "image"]
        if images:
            payload["reference_images"] = images
        return payload

    payload["fps"] = FPS
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    rest: list[dict[str, Any]] = []
    for r in refs:
        if r.role == "first_frame":
            payload["first_frame"] = _src(r)
        elif r.role == "last_frame":
            payload["last_frame"] = _src(r)
        elif r.role == "reference_sheet":
            payload["reference_sheet"] = _src(r)
        elif r.role == "control_video" and r.kind == "video":
            payload["control"] = {"type": r.tag or "v2v", "video": _src(r)}
        elif r.kind == "image":
            rest.append(_ref_image(r))
    if rest:
        payload["reference_images"] = rest
    return payload


def canvas_ref_id(node_id: str | None) -> str | None:
    """画布节点 id → gen_tasks.ref_id（varchar 32）。

    派生节点 id 是「shot:sh_<26 位>」「entity:<id>:three_quarter_left」，常常超长。
    短的原样存（后台按 ref_id 一眼认得出），长的存稳定哈希。回挂不靠它 ——
    画布按 task id 自己取产物。
    """
    if not node_id:
        return None
    if len(node_id) <= REF_ID_MAX:
        return node_id
    return "h:" + hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:REF_ID_MAX - 2]


# ── 本库媒体地址 ─────────────────────────────────────────────────────────────

def media_name(url: str | None) -> str | None:
    """「/media/<文件名>」或「http://任意主机/media/<文件名>」→ 文件名；别的形状 → None。

    只解析路径，不认主机：public_base_url 改过的话，老资产的主机名对不上，
    但文件还在本库里。是不是真在本库由调用方查文件（_stored）。
    """
    if not url or url.startswith("data:"):
        return None
    parts = urlsplit(url)
    if parts.query or not parts.path.startswith("/media/"):
        return None
    name = parts.path[len("/media/"):]
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    return name


def _stored(name: str) -> bool:
    from app.capability.mediastore import media_root

    return (media_root() / name).is_file()


def local_media_url(url: str | None) -> str | None:
    """本库里真有这个文件 → 同源路径 /media/<文件名>；否则 None（网关临时地址必然落在这里）。"""
    name = media_name(url)
    return f"/media/{name}" if name and _stored(name) else None


def resolve_refs(db: Session, refs: Sequence[RefIn]) -> tuple[list[RefIn], list[str]]:
    """参考地址 → 网关取得到的绝对地址。只认本库 /media 文件和 data:，别的丢掉并说明。

    前端给的是同源路径 /media/x.png（过了 media()），网关在另一个进程里，
    要的是 public_base_url 打头的完整地址 —— 和库里 Asset.url 同一个形状。
    外部地址不转：网关会照着去下载，等于让画布能指挥网关去取任意 URL。
    """
    base = get_settings().public_base_url.rstrip("/")
    out: list[RefIn] = []
    warnings: list[str] = []
    for r in refs:
        name = None
        if r.asset_id:
            a = db.get(Asset, r.asset_id)
            name = media_name(a.url) if a is not None else None
        name = name or media_name(r.url)
        if name and _stored(name):
            out.append(r.model_copy(update={"url": f"{base}/media/{name}"}))
        elif r.url.startswith("data:") and len(r.url) <= DATA_URL_MAX:
            out.append(r)
        else:
            if r.production_ref:
                raise GenerateError(422, "RESOURCE_MEDIA_MISSING", f"参考「{r.label}」的源素材文件已不可用")
            warnings.append(f"参考「{r.label}」不在本库媒体里（只认 /media/… 或 data:），没用上")
    return out, warnings


# ── 提交 ─────────────────────────────────────────────────────────────────────

_STATUS = {
    TaskStatus.queued: "queued", TaskStatus.submitted: "queued", TaskStatus.running: "running",
    TaskStatus.succeeded: "succeeded", TaskStatus.failed: "failed", TaskStatus.cancelled: "cancelled",
}
_TERMINAL = {TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled}


def _plan_scope(db: Session, plan_id: str | None) -> tuple[str | None, str | None]:
    """计划 → (novel_id, chapter_id)。任务记上小说，产物就会出现在资产管理的「媒体」里。"""
    if not plan_id:
        return None, None
    from app.models import Chapter, ScriptDoc, ShotPlan

    plan = db.get(ShotPlan, plan_id)
    doc = db.get(ScriptDoc, plan.script_doc_id) if plan else None
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    return (chapter.novel_id, chapter.id) if chapter else (None, None)


def _info_for_route(route: ResolvedRoute) -> ModelInfo | None:
    infos = catalog_models(route.endpoint, (route.capability.value,))
    if route.model:
        return next((i for i in infos if i.model == route.model), None)
    return next((i for i in infos if i.is_default), None)


def _default_route(db: Session, cap: str) -> ResolvedRoute:
    """没点名模型时 submit_task 大概会用哪条路由 —— 只拿来读 limits、估价。

    规则照 submit_task：首选能用就用首选，否则下一条明确免费且没被拦的。
    最终用哪条仍由 submit_task 决定（不点名就保留它的故障转移）。
    """
    routes = resolve_routes(db, cap, PURPOSE)
    if not routes:
        raise GenerateError(
            422, "NO_ROUTE",
            f"还没有给 {cap} 配能力路由（设置 › 能力路由），也可以在面板里直接点选一个模型")
    if route_blocked(db, routes[0]) is None:
        return routes[0]
    return next((r for r in routes[1:] if r.billing == "free" and route_blocked(db, r) is None),
                routes[0])


def _picked(db: Session, body: GenerateIn, wanted: str,
            warnings: list[str]) -> tuple[str, ModelInfo, ResolvedRoute, bool]:
    """用户点名了模型：找到它、定能力、找回它的路由（付费闸要用）。"""
    caps = CAPS_BY_MEDIA[body.media]
    if body.endpoint_id:
        ep = db.get(CapabilityEndpoint, body.endpoint_id)
        if ep is None or not ep.enabled:
            raise GenerateError(422, "BAD_MODEL", "所选模型的端点不存在或已停用，刷新一下模型列表")
        endpoints = [ep]
    else:
        endpoints = list(db.execute(
            select(CapabilityEndpoint).where(CapabilityEndpoint.enabled.is_(True))
            .order_by(CapabilityEndpoint.name)
        ).scalars())
    by_cap: dict[str, tuple[ModelInfo, CapabilityEndpoint]] = {}
    for ep in endpoints:
        for info in catalog_models(ep, caps):
            hit = info.model == body.model if body.model else info.is_default
            if hit and info.capability not in by_cap:
                by_cap[info.capability] = (info, ep)
    if not by_cap:
        raise GenerateError(422, "BAD_MODEL",
                            f"没有找到{'图片' if body.media == 'image' else '视频'}模型"
                            f" {body.model or ''}，刷新一下模型列表")

    if wanted in by_cap:
        cap = wanted
    elif wanted == I2I and T2I in by_cap:
        cap = T2I
        warnings.append(f"「{by_cap[T2I][0].label}」只会文生图，底图没用上；要改图请选图像编辑模型")
    elif wanted == T2I and I2I in by_cap:
        raise GenerateError(422, "NEEDS_BASE_IMAGE",
                            f"「{by_cap[I2I][0].label}」是图像编辑模型，要一张底图："
                            f"把一张参考图的角色设为「首帧」")
    else:
        raise GenerateError(422, "BAD_MODEL", f"「{body.model}」不能做这项生成（{wanted}）")
    info, ep = by_cap[cap]
    route, routed = route_for(info, ep, _enabled_routes(db))
    return cap, info, route, routed


def submit(db: Session, body: GenerateIn) -> dict[str, Any]:
    """交 count 条任务，返回前端 GenerateResult。拦下时抛 GenerateError。"""
    warnings: list[str] = []
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise GenerateError(422, "EMPTY_PROMPT", "提示词是空的")

    from app.production.canvas_controls import stage_inputs, MESSAGE
    from app.production import service as production
    if body.target and body.target.board_id:
        try:
            control_board = production.board(db, body.target.board_id)
        except production.ProductionError as exc:
            raise GenerateError(exc.status, exc.code, str(exc)) from exc
        if stage_inputs(control_board.doc_json, body.target.node_id):
            raise GenerateError(422, "stage_control_not_supported", MESSAGE)
    if any(r.production_ref and r.production_ref.kind in {"stage", "coverage"} for r in body.refs):
        raise GenerateError(422, "stage_control_not_supported", MESSAGE)

    source_refs = body.refs
    source_context = None
    if any(r.production_ref is not None for r in body.refs):
        from app.production import service as production
        try:
            if not body.target or not body.target.board_id:
                raise production.ProductionError("board_required", "标准素材引用需要目标画布")
            board = production.board(db, body.target.board_id)
            source_context, _issues = production.context_for(db, board)
            if body.target.plan_id and body.target.plan_id != source_context.plan_id:
                raise production.ProductionError("context_mismatch", "生成目标与当前画布的分镜来源不一致")
            source_refs = []
            for r in body.refs:
                if r.production_ref is None:
                    source_refs.append(r)
                    continue
                if not r.production_ref.revision:
                    raise production.ProductionError("revision_required", "标准素材引用缺少版本")
                item = production.resolve_one(db, board, source_context, r.production_ref)
                resource = item["resource"]
                media = resource.get("media")
                if not media or resource.get("kind") not in {"image", "video", "audio"}:
                    raise production.ProductionError("media_required", f"{r.label} 没有可消费的媒体")
                source_refs.append(r.model_copy(update={"url": media["url"], "asset_id": media["asset_id"],
                                                       "kind": resource["kind"]}))
        except production.ProductionError as exc:
            raise GenerateError(exc.status, exc.code, str(exc)) from exc
    refs, w = resolve_refs(db, source_refs)
    warnings += w
    wanted = pick_capability(body.media, refs)

    pinned: ResolvedRoute | None
    info: ModelInfo | None
    if body.model or body.endpoint_id:
        cap, info, route, routed = _picked(db, body, wanted, warnings)
        # **点名的路由 submit_task 不过付费闸**（service.py：pinned 时跳过 route_blocked），
        # 所以这里必须自己拦 —— 否则在画布上点一下付费模型就直接花钱
        why = blocked_reason(db, route, routed)
        if why:
            raise GenerateError(409, "MODEL_BLOCKED", why)
        unit = info.cost if info else None
        pinned = route
    else:
        cap = wanted
        route = _default_route(db, cap)
        info = _info_for_route(route)
        # 不用 route.unit_cost()：它走 CapabilityCatalog 严格校验，缓存里多一项未知能力就抛
        unit = info.cost if info else None
        pinned = None

    if info is not None and not info.ready:
        # 网关自报没装齐（LTX-2.5 缺权重时 ready:false）：交上去也是在网关那头报错，
        # 而那时画布上已经长出一个永远转圈后变红的节点
        raise GenerateError(422, "MODEL_NOT_READY",
                            f"「{info.label}」在能力网关上还没就绪（缺权重或没装），换一个模型")

    refs, w = fit_refs(cap, refs, info)
    warnings += w
    if cap == I2I and not any(r.role == "base" for r in refs):
        raise GenerateError(422, "NEEDS_BASE_IMAGE", "图生图要一张底图（参考角色设为「首帧」）")
    if cap == I2V and not any(r.role == "first_frame" for r in refs) \
            and info is not None and not info.supports.get("text_to_video"):
        raise GenerateError(
            422, "NEEDS_FIRST_FRAME",
            f"「{info.label}」必须有首帧：把一张图的参考角色设为「首帧」，"
            f"或换一个支持文生视频的模型（如 LTX-2.5）")

    width, height, w = clamp_size(body.aspect_ratio, body.resolution,
                                  info.sizes if info else None, info.size_multiple if info else None)
    warnings += w
    duration_ms: int | None = None
    if cap == I2V:
        duration_ms, w = clamp_duration(body.duration_ms, info.max_duration_ms if info else None)
        warnings += w
    count, w = clamp_count(body.count, MAX_COUNT)
    warnings += w
    if info and info.max_prompt_chars and len(prompt) > info.max_prompt_chars:
        warnings.append(f"提示词超过该模型上限 {info.max_prompt_chars} 字，后面的截掉了")
        prompt = prompt[:info.max_prompt_chars]

    estimated = round(unit * count, 6) if unit is not None else None
    threshold = get_settings().cost_confirm_threshold
    if estimated is not None and estimated > threshold and not body.confirm_cost:
        raise GenerateError(
            409, "COST_CONFIRM_REQUIRED",
            f"这次 {count} 条预估要花 {estimated:g}{' ' + info.currency if info else ''}，确认后再出",
            estimated_cost=estimated, count=count)
    if unit is None and route.billing != "free":
        warnings.append("这个模型没有标价，实际花费以供应商账单为准")

    novel_id, chapter_id = ((source_context.novel_id, source_context.chapter_id) if source_context else
                            _plan_scope(db, body.target.plan_id if body.target else None))
    ref_id = canvas_ref_id(body.target.node_id if body.target else None)
    # 不给 seed 就随机起一个：同样的提示词再点一次是「再出一批」，不该命中上一批的幂等键
    base_seed = body.seed if body.seed is not None else random.randint(0, 2**31 - 1 - MAX_COUNT)
    filled = body.model_copy(update={"prompt": prompt, "refs": refs})

    tasks: list[GenTask] = []
    for i in range(count):
        payload = build_payload(cap, filled, width, height, duration_ms, base_seed + i)
        try:
            task = submit_task(db, cap, payload, purpose=PURPOSE, ref_kind=REF_KIND, ref_id=ref_id,
                               novel_id=novel_id, chapter_id=chapter_id, route=pinned)
        except CapabilityError as exc:
            if not tasks:
                raise
            warnings.append(f"第 {i + 1} 条没交上：{exc.message}")
            break
        # 每交一条就落库：本机网关跑得快时，回调会比这个请求先到，
        # 而回调按 provider_task_id 找不到行就直接丢掉，只能等兜底轮询
        db.commit()
        tasks.append(task)

    first = tasks[0]
    return {
        "tasks": [{"id": t.id, "status": _STATUS.get(t.status, "running")} for t in tasks],
        "resolved": {"endpoint_id": first.endpoint_id, "model": first.model or (info.model if info else ""),
                     "width": width, "height": height, "duration_ms": duration_ms},
        "warnings": list(dict.fromkeys(warnings)),
        "estimated_cost": estimated or 0.0,
        "requires_confirm": False,
    }


# ── 查询 ─────────────────────────────────────────────────────────────────────

#: 同一个任务多久最多向网关查一次。画布 4 秒轮一次，同一张画布开在两个标签页就是 2 秒 ——
#: 并发的两次 poll 会各自落一遍产物（_materialize_assets 只在本会话里去重）
_POLL_EVERY_SEC = 3.0
_RELOCALIZE_EVERY_SEC = 30.0
_last_touch: dict[str, float] = {}


def _due(key: str, every: float) -> bool:
    now = time.monotonic()
    if now - _last_touch.get(key, 0.0) < every:
        return False
    if len(_last_touch) > 4000:
        _last_touch.clear()
    _last_touch[key] = now
    return True


def _primary_kind(capability: str | None) -> str | None:
    """画布只要主产物：视频任务还会登记尾帧（图）和 LTX-2.5 的分离音轨，都不该长成节点。"""
    head = (capability or "").split(".", 1)[0]
    return head if head in ("image", "video", "audio") else None


def _assets_of(db: Session, task_id: str, kind: str | None) -> tuple[list[dict[str, Any]], list[Asset]]:
    rows = db.execute(
        select(Asset).where(Asset.gen_task_id == task_id).order_by(Asset.created_at, Asset.id)
    ).scalars()
    local: list[dict[str, Any]] = []
    foreign: list[Asset] = []
    for a in rows:
        k = a.kind.value if isinstance(a.kind, AssetKind) else str(a.kind)
        if k not in ("image", "video", "audio") or (kind and k != kind):
            continue
        url = local_media_url(a.url)
        if url:
            local.append({"asset_id": a.id, "url": url, "kind": k, "mime": a.mime})
        else:
            foreign.append(a)
    return local, foreign


def _relocalize(db: Session, assets: Sequence[Asset]) -> None:
    """产物落地时没取回来（service._localize 失败会先挂上游地址）的，再取一次。

    不复用 _localize：它超时 120 秒，放在画布每 4 秒一次的轮询里会把请求挂住。
    """
    from app.capability.mediastore import store_bytes

    fallback = {"image": "image/png", "video": "video/mp4", "audio": "audio/wav"}
    for a in assets:
        kind = a.kind.value if isinstance(a.kind, AssetKind) else str(a.kind)
        try:
            with httpx.Client(follow_redirects=True, timeout=20) as client:
                resp = client.get(a.url)
                resp.raise_for_status()
            stored = store_bytes(resp.content, mime=a.mime or fallback.get(kind, "application/octet-stream"))
        except Exception as exc:          # noqa: BLE001 —— 取不回就保持原样，由调用方报失败
            log.warning("画布产物再取回失败 asset=%s url=%s：%s", a.id, a.url, exc)
            continue
        meta = dict(a.meta_json or {})
        meta.setdefault("source_url", a.url)
        a.url = str(stored["url"])
        a.sha256 = str(stored["sha256"])
        a.mime = str(stored["mime"])
        a.bytes = int(str(stored["bytes"]))
        a.meta_json = meta
    db.flush()


def task_state(db: Session, task_id: str) -> dict[str, Any] | None:
    """前端 GenTaskState。没找到返回 None。

    没结束的先向网关查一次（同 POST /gen-tasks/{id}:poll 用的 poll_task）——
    回调要是丢了，后台兜底轮询要等「预计时长 × 3」之后才查，画布上就一直转圈。

    progress：网关按步上报进度，但 apply_task_result 没存（表里没有这一列），
    这里拿不到真进度就给 null，不编一个按时间推的数。
    """
    t = db.get(GenTask, task_id)
    if t is None:
        return None
    if t.status not in _TERMINAL and _due(t.id, _POLL_EVERY_SEC):
        try:
            t = poll_task(db, t)
        except Exception:                 # noqa: BLE001 —— 查不到就照旧报当前状态，别让画布的轮询 500
            log.exception("画布任务查询失败 task=%s", t.id)

    kind = _primary_kind(t.capability)
    local, foreign = _assets_of(db, t.id, kind)
    status = _STATUS.get(t.status, "running")
    err = t.error_json or {}
    error = str(err.get("message") or err.get("code") or "")[:300] or None
    if status == "succeeded" and not local:
        if foreign and _due("loc:" + t.id, _RELOCALIZE_EVERY_SEC):
            _relocalize(db, foreign)
            local, foreign = _assets_of(db, t.id, kind)
        if not local:
            # 对画布来说拿不到本库地址就等于没出来：网关临时地址不能进画布文档
            status = "failed"
            error = ("任务成功了，但产物还没取回本库（网关临时地址不能给画布用），稍后重出一次"
                     if foreign else "任务成功了，但没有可用的产物")
    return {
        "id": t.id,
        "status": status,
        "progress": 1.0 if status == "succeeded" else None,
        "error": error if status in ("failed", "cancelled") else None,
        "assets": local,
    }
