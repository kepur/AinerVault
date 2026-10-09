"""标准定妆照（画布 op=sheet）：一张人物照片 → 16 格 → 拼成一张「角色定妆照」设定拼版。

标准照着用户给的那张设定图来（浅灰底、左上大标题、三个分区并排）：

    角色全景前后侧三视图   前视图 / 后视图 / 侧视图（全身）
    角色面部多视角特写     正面特写 / 左侧特写 / 右侧特写 / 后脑特写（2×2）
    九宫格表情特写         喜 怒 哀 / 乐 惊 恐 / 思 厌 疑（3×3）

quick 预设只出 前视图 / 后视图 / 侧视图 / 正面特写 4 格（下游出分镜真正要用的就这几张）。

## 为什么每一格都是「编辑」而不是「文生图」

文生图每张都是新的一个人。这里全部走本机 FLUX.2-klein 编辑（image.image_to_image）：
前视图从人物照片改出来；后视图、侧视图从前视图改（同一身衣服转个身）；正面特写以人物照片为底图
（脸最像）、前视图当第二张参考（发型服装跟定妆照走）；其余面部角度和九个表情都从正面特写改。
按依赖分三批交：前视图 → 后/侧/正脸 → 其余 12 张。同一批一次全交给网关排队，省掉一张一张来回问的空档。

## 提示词

一律英文、photoreal、写「the same person as in the reference image」。**不写 character sheet / turnaround
这类词**：klein 一看到它们就往动漫设定稿上滑。种子按格固定递增（base + 序号）：同样的输入再跑一次
命中能力层的幂等键，已出好的格直接复用（中途失败重跑只补没出成的那几格）；要换一版就换 seed 或 force。

## 拼版

本地用 PIL 拼（compose_sheet，纯函数），一次模型调用都不花；
各格按画面里人物的位置裁（浅灰无缝背景上找主体），留白才匀。
存成 PNG Asset，返回同源 /media 地址。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import logging
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

if TYPE_CHECKING:                                      # 只给类型检查用：模块加载不连库
    from app.models import GenTask

log = logging.getLogger("ainer-core")

IMAGE_MODEL = "flux2-klein-4b-edit"
#: klein 编辑的合法尺寸里唯一的竖幅；面部、表情也按它出，拼版时再裁成近方形
PANEL_SIZE = (512, 768)
STYLE = "photoreal"
#: 参考图分辨率直接决定速度（0.4 约 25 秒/张，1.0 约 48 秒），输出本来就只有 0.4MP
REF_MEGAPIXELS = 0.4
DEFAULT_SEED = 7100
#: 一批的等待上限：15 分钟 + 每多一张多给 40 秒（一批最多 12 张排在同一块 GPU 上，前面可能还有 LTX 在跑）
TASK_TIMEOUT_S = 15 * 60
PER_TASK_S = 40
POLL_S = 4.0
REF_KIND = "char_sheet"
#: gen_tasks.ref_id 是 varchar(32)
REF_ID_MAX = 32
#: 人物照片给 data: 时的上限（正常应先上传成 /media）
MAX_DATA_BYTES = 20 * 1024 * 1024
PRESETS = ("standard", "quick")


class SheetError(RuntimeError):
    """出不了定妆照。消息直接给人看。"""


class SheetCancelled(SheetError):
    """调用方叫停（cancelled() 返回 True）。"""


# ── 规格：16 格、分区、标签 ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Section:
    key: str
    #: 拼版上的分区标题（和用户给的标准图一字不差）
    title: str
    #: 进度里用的短名：「三视图 2/3」
    short: str
    keys: tuple[str, ...]
    cols: int


EXPR_KEYS: tuple[str, ...] = (
    "expr_joy", "expr_anger", "expr_sorrow",
    "expr_happy", "expr_surprise", "expr_fear",
    "expr_think", "expr_disgust", "expr_doubt",
)

SECTIONS: tuple[Section, ...] = (
    Section("body", "角色全景前后侧三视图", "三视图", ("body_front", "body_back", "body_side"), 3),
    Section("face", "角色面部多视角特写", "面部特写", ("face_front", "face_left", "face_right", "face_back"), 2),
    Section("expr", "九宫格表情特写", "表情", EXPR_KEYS, 3),
)

LABELS: dict[str, str] = {
    "body_front": "前视图", "body_back": "后视图", "body_side": "侧视图",
    "face_front": "正面特写", "face_left": "左侧特写", "face_right": "右侧特写", "face_back": "后脑特写",
    "expr_joy": "喜", "expr_anger": "怒", "expr_sorrow": "哀",
    "expr_happy": "乐", "expr_surprise": "惊", "expr_fear": "恐",
    "expr_think": "思", "expr_disgust": "厌", "expr_doubt": "疑",
}
_KEY_BY_LABEL = {v: k for k, v in LABELS.items()}

PANEL_KEYS_STANDARD: list[str] = [k for s in SECTIONS for k in s.keys]
#: 快速版：下游出分镜真正会引用的几格（identity_panels 挑的就是它们）
PANEL_KEYS_QUICK: list[str] = ["body_front", "body_back", "body_side", "face_front"]

#: 每格从哪儿改：(底图, 附加身份参考)。"person" = 人物照片，其余是别的格。
#: 底图管构图和身份；附加参考在网关那边要标 identity 才送得进去（见 _edit_payload）
SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "body_front": ("person", ()),
    "body_back": ("body_front", ()),
    "body_side": ("body_front", ()),
    # 脸以人物照片为底图最像本人；发型、领口跟前视图（定妆后的造型）走
    "face_front": ("person", ("body_front",)),
    "face_left": ("face_front", ()),
    "face_right": ("face_front", ()),
    "face_back": ("face_front", ()),
    **{k: ("face_front", ()) for k in EXPR_KEYS},
}

#: 九宫格每格的表情（写成模型看得懂的面部动作，不写抽象情绪词）
EXPRESSIONS: dict[str, str] = {
    "expr_joy": "a joyful happy smile showing the teeth, bright cheerful eyes",
    "expr_anger": "anger: deeply furrowed brows, glaring eyes, clenched teeth",
    "expr_sorrow": "sorrow: eyes welling up with tears, the corners of the mouth turned down",
    "expr_happy": "a big hearty laugh with the eyes squeezed into happy crescents and the mouth wide open",
    "expr_surprise": "surprise: eyes wide open, eyebrows raised high, mouth open",
    "expr_fear": "fear: shrinking back, eyebrows raised and drawn together, frightened wide eyes",
    "expr_think": "deep in thought: one hand resting on the chin, eyes looking off to one side",
    "expr_disgust": "disgust: wrinkled nose, upper lip curled, pulling the head back slightly",
    "expr_doubt": "doubt: head tilted to one side, one eyebrow raised, a skeptical look",
}

_SAME = "the same person as in the reference image"
_STUDIO = ("Plain light grey seamless studio background, soft even studio lighting, photorealistic photo. "
           "One single person, no text, no watermark.")


def panel_keys(preset: str) -> list[str]:
    return list(PANEL_KEYS_QUICK if preset == "quick" else PANEL_KEYS_STANDARD)


def panel_prompt(key: str, look: str = "") -> str:
    """这一格的英文提示词。klein 编辑要祈使句指令，不要画面描述。"""
    look = " ".join((look or "").split())[:400]
    if key == "body_front":
        wear = f" Outfit and hairstyle: {look.rstrip('.')}." if look else " Keep the same outfit."
        return (f"Make a full-body studio photo of {_SAME}. Keep the face, hairstyle, skin tone and body shape "
                f"exactly.{wear} Standing straight and facing the camera directly, arms relaxed at the sides, "
                f"the whole body visible from head to shoes, centered in the frame. {_STUDIO}")
    if key == "body_back":
        return (f"Turn {_SAME} around to show the back view: standing straight with the back to the camera, "
                "arms relaxed at the sides, the whole body visible from head to shoes, centered in the frame. "
                "Same outfit, colours, hairstyle and proportions seen from behind; the face is not visible. "
                f"{_STUDIO}")
    if key == "body_side":
        return (f"Show {_SAME} in an exact side profile facing left: standing straight, arms relaxed at the "
                "sides, the whole body visible from head to shoes, centered in the frame. Same face, outfit, "
                f"colours and hairstyle. {_STUDIO}")
    if key == "face_front":
        return (f"Make a head-and-shoulders close-up portrait of {_SAME}, facing the camera directly, eyes "
                "looking into the lens, calm neutral expression. Keep the face exactly as in the first image; "
                f"hairstyle and outfit as in the second image. {_STUDIO}")
    if key in ("face_left", "face_right"):
        side = "left" if key == "face_left" else "right"
        return (f"Turn the head of {_SAME} toward the {side} side of the frame, between a three-quarter view "
                "and a profile; head-and-shoulders close-up, calm neutral expression. Same face, hairstyle and "
                f"outfit. {_STUDIO}")
    if key == "face_back":
        return (f"Show the back of the head of {_SAME}: head-and-shoulders close-up seen from directly behind, "
                "the hairstyle clearly visible, the face not visible. Same hair colour and outfit. "
                f"{_STUDIO}")
    if key in EXPRESSIONS:
        return (f"Change only the facial expression of {_SAME} to {EXPRESSIONS[key]}. Keep the same face, "
                "hairstyle, outfit, head-and-shoulders framing facing the camera, and lighting. "
                f"{_STUDIO}")
    raise KeyError(key)


def plan_layers(keys: Sequence[str]) -> list[list[str]]:
    """按依赖分批：同一批的底图和参考都已在前面的批里出好。

    依赖不在 keys 里（quick 只要正脸时）不能悄悄删掉 —— 那一格就没有底图了，直接报错。
    """
    wanted = list(dict.fromkeys(keys))
    for k in wanted:
        if k not in SOURCES:
            raise KeyError(k)
        base, refs = SOURCES[k]
        for dep in (base, *refs):
            if dep != "person" and dep not in wanted:
                raise ValueError(f"{k} 依赖 {dep}，但 {dep} 不在要出的格里")
    layers: list[list[str]] = []
    placed: set[str] = set()
    while len(placed) < len(wanted):
        layer = [k for k in wanted if k not in placed
                 and all(d == "person" or d in placed for d in (SOURCES[k][0], *SOURCES[k][1]))]
        if not layer:                                  # SOURCES 写出环才会到这里
            raise ValueError("定妆照的格之间有循环依赖")
        layers.append(layer)
        placed.update(layer)
    return layers


def panel_seed(base: int, key: str) -> int:
    """固定种子：同一 base 下每格各自递增，保证可复现、互相不撞。"""
    return int(base) + PANEL_KEYS_STANDARD.index(key)


def panel_key(p: Mapping[str, Any]) -> str | None:
    """面板 dict → 格的 key。

    两种形状都认：generate_sheet 返回的 {key, label: 中文}，和执行器存进 run.extra 的
    {label: key, media}（前端按 key 查中文）。label 写中文也认。
    """
    for field in ("key", "label"):
        v = p.get(field)
        if isinstance(v, str):
            if v in LABELS:
                return v
            if v in _KEY_BY_LABEL:
                return _KEY_BY_LABEL[v]
    return None


#: 当「身份」引用时给哪几格：全身正面管衣服身形、正脸管长相、侧面管轮廓。
#: 刚好 3 张 —— klein 编辑最多 4 张图，底图（场景）占一张
CHARACTER_PANELS = ("body_front", "face_front", "body_side")
#: 当底图 / 其他角色只要一张：全身正面最能代表「这个人穿成这样」；没有就往后退
SINGLE_PANELS = ("body_front", "face_front", "body_side", "body_back")


def identity_panels(panels: Sequence[Mapping[str, Any]] | None, want: str) -> list[dict[str, Any]]:
    """下游引用定妆照时挑哪几格（原样返回传入的面板 dict）。

    want=character → [body_front, face_front, body_side]（有哪个给哪个）；
    want=base（以及 first_frame / reference / style 等只要一张的角色）→ [body_front]，没有就退到下一格。
    """
    by_key: dict[str, dict[str, Any]] = {}
    for p in panels or []:
        if isinstance(p, Mapping):
            k = panel_key(p)
            if k and k not in by_key:
                by_key[k] = dict(p)
    if want == "character":
        return [by_key[k] for k in CHARACTER_PANELS if k in by_key]
    for k in SINGLE_PANELS:
        if k in by_key:
            return [by_key[k]]
    return []


# ── 本库媒体地址 ────────────────────────────────────────────────────────────

def media_name(url: str | None) -> str | None:
    """「/media/<文件名>」或「http://任意主机/media/<文件名>」→ 文件名；别的形状 → None。

    同 generic.media_name（这里抄一份：那个文件这一轮有人在改，定妆照不该被它牵连）。
    只认一层文件名，挡住 ../ 之类。
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


def same_origin(url: str) -> str:
    """库里的 Asset.url 写死了 public_base_url；给画布、给外部的一律是同源 /media/…（同 canvas.same_origin）。"""
    i = url.find("/media/")
    return url[i:] if i >= 0 else url


def _media_file(url: str | None) -> Path | None:
    """本库 /media 地址 → 本地文件（同 frame_select._media_path：core 的工作目录不对时退到包内 var/media）。"""
    from app.capability.mediastore import media_root

    name = media_name(url)
    if not name:
        return None
    p = Path(media_root()) / name
    if p.is_file():
        return p
    fallback = Path(__file__).resolve().parents[2] / "var" / "media" / name
    return fallback if fallback.is_file() else None


def resolve_person(url: str) -> str:
    """人物照片 → 网关取得到的绝对地址（public_base_url/media/…，和库里 Asset.url 同一个形状）。

    网关在另一个进程里，同源路径 /media/x.png 它取不到；外部 http 地址不转 ——
    那等于让调用方指挥网关去下载任意 URL。data: 先落进本库媒体再给地址。
    """
    from app.capability.mediastore import store_bytes
    from app.config import get_settings

    url = (url or "").strip()
    if not url:
        raise SheetError("要一张人物照片")
    base = get_settings().public_base_url.rstrip("/")
    if url.startswith("data:image/"):
        try:
            raw = base64.b64decode(url.split(",", 1)[1], validate=False)
        except (IndexError, binascii.Error) as exc:
            raise SheetError("人物照片的 data: 地址解不开") from exc
        if not raw or len(raw) > MAX_DATA_BYTES:
            raise SheetError(f"人物照片为空或超过 {MAX_DATA_BYTES // (1024 * 1024)}MB，先上传")
        stored = store_bytes(raw, mime="image/png")
        name = media_name(str(stored["url"]))
        return f"{base}/media/{name}"
    name = media_name(url)
    if not name:
        raise SheetError("人物照片要先上传到本库（/media/…），外部地址不收")
    if _media_file(url) is None:
        raise SheetError(f"本库媒体里找不到人物照片 {name}")
    return f"{base}/media/{name}"


# ── 能力调用 ────────────────────────────────────────────────────────────────

def _edit_payload(prompt: str, base_url: str, refs: Sequence[str], seed: int) -> dict[str, Any]:
    """klein 编辑的请求。尺寸必须显式给：不给就跟随底图，人物照片是什么比例出来就是什么比例。"""
    return {
        "image": {"url": base_url}, "prompt": prompt,
        "width": PANEL_SIZE[0], "height": PANEL_SIZE[1],
        "style": STYLE, "strength": 0.9,
        # 网关只收 identity=true 的附加参考，并跳过和底图相同的那张
        "reference_images": [{"ref": {"url": u}, "role": "character", "identity": True, "tag": f"person {i + 2}"}
                             for i, u in enumerate(refs) if u and u != base_url],
        "params": {"seed": seed, "style": STYLE, "ref_megapixels": REF_MEGAPIXELS},
    }


def _short_ref_id(ref_id: str | None) -> str | None:
    """gen_tasks.ref_id 只有 32 位；画布节点 id 常超长，超长的存稳定哈希（同 generic.canvas_ref_id）。"""
    if not ref_id or len(ref_id) <= REF_ID_MAX:
        return ref_id
    return "h:" + hashlib.sha1(ref_id.encode("utf-8")).hexdigest()[:REF_ID_MAX - 2]


def _route(db):
    """按模型名取本机路由（keyframe._route 的写法：本机端点不过付费闸）。"""
    from app.capability.schemas import Capability
    from app.pipelines.keyframe import _route as route_for_model

    route, _local, blocked = route_for_model(db, Capability.image_i2i.value, IMAGE_MODEL)
    if route is None or blocked:
        raise SheetError(f"{IMAGE_MODEL} 不能用：{blocked or '没有找到路由'}（本机网关开着吗？）")
    return route


def _submit(db, route, payload: dict[str, Any], *, ref_kind: str, ref_id: str | None, force: bool) -> str:
    from app.capability.schemas import Capability
    from app.capability.service import submit_task

    task = submit_task(db, Capability.image_i2i, payload, purpose="char_sheet", ref_kind=ref_kind,
                       ref_id=_short_ref_id(ref_id), route=route, force=force)
    db.commit()
    return task.id


def _cancel(db, task_ids: Sequence[str]) -> None:
    """叫停时把还没出完的任务在网关上也取消（本机 GPU 队列里排着的不取消就一直占着卡）。"""
    from app.capability.service import cancel_task
    from app.models import GenTask

    for tid in task_ids:
        try:
            t = db.get(GenTask, tid)
            if t is not None:
                cancel_task(db, t)
            db.commit()
        except Exception as exc:                       # noqa: BLE001 —— 取消是尽力而为
            db.rollback()
            log.warning("char_sheet 取消任务 %s 失败：%s", tid, exc)


def _await(db, task_ids: Sequence[str], *, on_done: Callable[[str, "GenTask | None"], None],
           cancelled: Callable[[], bool] | None) -> list[str]:
    """等一批任务都结束（主动问网关）。每结束一张回调一次；返回超时没出完的 id。"""
    from app.capability.service import poll_task
    from app.models import GenTask, TaskStatus

    final = (TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled)
    deadline = time.time() + TASK_TIMEOUT_S + PER_TASK_S * max(0, len(task_ids) - 1)
    left = list(task_ids)
    while left:
        if cancelled is not None and cancelled():
            _cancel(db, left)
            raise SheetCancelled("已停止")
        if time.time() > deadline:
            return left
        for tid in list(left):
            # populate_existing：回调可能在别的会话里把任务写成了成功；只刷这一行，不 expire 调用方的对象
            t = db.get(GenTask, tid, populate_existing=True)
            if t is not None and t.status not in final:
                try:
                    t = poll_task(db, t)
                    db.commit()
                except Exception:                     # noqa: BLE001 —— 网关一时连不上：下一轮再问
                    db.rollback()
            if t is None or t.status in final:
                left.remove(tid)
                on_done(tid, t)
        if left:
            time.sleep(POLL_S)
    return []


def _asset_of(db, task: "GenTask | None") -> tuple[str, str]:
    """成功任务 → (asset_id, 库里的绝对 url)；失败抛 SheetError（消息给人看）。"""
    from sqlalchemy import select

    from app.models import Asset, AssetKind, TaskStatus

    if task is None or task.status != TaskStatus.succeeded:
        err = task.error_json if task is not None and isinstance(task.error_json, dict) else {}
        raise SheetError(str(err.get("message") or (task.status.value if task is not None else "任务不见了"))[:200])
    a = db.execute(select(Asset).where(Asset.gen_task_id == task.id, Asset.kind == AssetKind.image)).scalars().first()
    if a is None:
        raise SheetError("任务成功了但没有产物")
    return a.id, a.url


def _load_image(url: str) -> Image.Image | None:
    p = _media_file(url)
    if p is None:
        return None
    try:
        with Image.open(p) as im:
            return im.convert("RGB")
    except Exception as exc:                           # noqa: BLE001 —— 一张坏图不该让整张拼版失败
        log.warning("char_sheet 打不开 %s：%s", p, exc)
        return None


def _store_sheet(db, img: Image.Image, meta: dict[str, Any]) -> tuple[str, str]:
    """拼版存 PNG Asset（按内容去重：同样的格拼出来是同一张），返回 (asset_id, 库里的绝对 url)。"""
    from sqlalchemy import select

    from app.capability.mediastore import store_bytes
    from app.ids import new_id
    from app.models import Asset, AssetKind, AssetSource

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    item = store_bytes(buf.getvalue(), mime="image/png")
    a = db.execute(select(Asset).where(Asset.sha256 == item["sha256"])).scalars().first()
    if a is None:
        a = Asset(id=new_id("as"), kind=AssetKind.image, url=str(item["url"]), sha256=str(item["sha256"]),
                  mime=str(item["mime"]), bytes=int(item["bytes"]),  # type: ignore[arg-type]
                  source=AssetSource.generated, meta_json={"composed": "char_sheet", **meta})
        db.add(a)
    db.commit()
    return a.id, a.url


# ── 主流程 ──────────────────────────────────────────────────────────────────

def _section_of(key: str) -> Section:
    return next(s for s in SECTIONS if key in s.keys)


def generate_sheet(db, *, person_url: str, name: str = "", look: str = "", preset: str = "standard",
                   on_progress: Callable[[int, str], None] | None = None,
                   cancelled: Callable[[], bool] | None = None,
                   seed: int | None = None, force: bool = False,
                   ref_kind: str = REF_KIND, ref_id: str | None = None) -> dict[str, Any]:
    """阻塞执行，返回 {"sheet": {"asset_id", "url"}, "panels": [{"key", "label", "asset_id", "url"}, ...]}；
    url 一律是同源 /media/…。on_progress(百分比, "三视图 2/3")。

    另带 "missing": [{"key", "label", "error"}]（没出成的格，拼版上画成「未生成」）、"seed"、"preset"。
    前视图没出成直接 SheetError（其余格都从它派生）；别的格失败不挡拼版。

    扩展参数（都可不给）：seed = 种子基数（默认固定，见文件头）；force = 绕开幂等复用必定重出；
    ref_kind/ref_id = 记在 gen_tasks 上的来源（执行器传 canvas_node 和「画布:节点」）。
    """
    preset = preset if preset in PRESETS else "standard"
    keys = panel_keys(preset)
    base_seed = DEFAULT_SEED if seed is None else int(seed)
    person = resolve_person(person_url)
    route = _route(db)

    def report(pct: int, step: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(max(0, min(100, int(pct))), step)
        except Exception as exc:                       # noqa: BLE001 —— 进度写不进去不该让出图失败
            log.warning("char_sheet 进度回调失败：%s", exc)

    sec_total = {s.key: sum(1 for k in s.keys if k in keys) for s in SECTIONS}
    sec_done = dict.fromkeys(sec_total, 0)
    made: dict[str, tuple[str, str]] = {}               # key → (asset_id, 绝对 url)
    missing: dict[str, str] = {}
    first = _section_of(keys[0])
    report(0, f"{first.short} 0/{sec_total[first.key]}")

    def finished(key: str) -> None:
        sec = _section_of(key)
        sec_done[sec.key] += 1
        count = len(made) + len(missing)
        report(round(count * 95 / len(keys)), f"{sec.short} {sec_done[sec.key]}/{sec_total[sec.key]}")

    for layer in plan_layers(keys):
        if cancelled is not None and cancelled():
            raise SheetCancelled("已停止")
        submitted: dict[str, str] = {}                   # task_id → key
        for key in layer:
            base_key, ref_keys = SOURCES[key]
            deps = [d for d in (base_key, *ref_keys) if d != "person"]
            bad = next((d for d in deps if d not in made), None)
            if bad is not None:
                missing[key] = f"上游「{LABELS[bad]}」没出成"
                finished(key)
                continue
            src = {"person": person, **{k: v[1] for k, v in made.items()}}
            payload = _edit_payload(panel_prompt(key, look), src[base_key], [src[r] for r in ref_keys],
                                    panel_seed(base_seed, key))
            try:
                submitted[_submit(db, route, payload, ref_kind=ref_kind, ref_id=ref_id, force=force)] = key
            except Exception as exc:                   # noqa: BLE001 —— 一格交不上记下来，别的照出
                db.rollback()
                missing[key] = f"提交失败：{exc}"[:200]
                finished(key)

        def done(tid: str, task: "GenTask | None") -> None:
            key = submitted[tid]
            try:
                made[key] = _asset_of(db, task)
            except SheetError as exc:
                missing[key] = str(exc)
            finished(key)

        for tid in _await(db, list(submitted), on_done=done, cancelled=cancelled):
            missing[submitted[tid]] = f"超过 {TASK_TIMEOUT_S // 60} 分钟没出完"
        if "body_front" in missing:
            raise SheetError(f"前视图没出成：{missing['body_front']}")

    report(96, "拼版")
    images = {k: im for k, (_aid, url) in made.items() if (im := _load_image(url)) is not None}
    for k in made:
        if k not in images:
            missing[k] = "图出了但本地读不到"
    sheet = compose_sheet(images, name, preset)
    sheet_id, sheet_url = _store_sheet(db, sheet, {
        "preset": preset, "name": name[:40], "seed": base_seed,
        "panels": {k: aid for k, (aid, _u) in made.items()},
    })
    report(100, "完成")
    return {
        "sheet": {"asset_id": sheet_id, "url": same_origin(sheet_url)},
        "panels": [{"key": k, "view_key": {"expr_sorrow": "expr_sad", "expr_happy": "expr_laugh"}.get(k, k),
                    "label": LABELS[k], "asset_id": made[k][0], "url": same_origin(made[k][1])}
                   for k in keys if k in made and k in images],
        "missing": [{"key": k, "label": LABELS[k], "error": missing[k]} for k in keys if k in missing],
        "seed": base_seed, "preset": preset,
    }


# ── 拼版（纯函数） ───────────────────────────────────────────────────────────

BG = (238, 240, 243)                 # #EEF0F3：参考图的浅灰底
INK = (27, 31, 39)                   # 标题
SUB = (110, 118, 132)                # 名字、页眉右侧
LABEL = (62, 69, 83)                 # 图下标签
ACCENT = (63, 99, 214)               # 分区编号
RULE = (210, 215, 222)               # 页眉横线、分区竖线
FRAME = (214, 219, 226)              # 图块描边
EMPTY = (226, 229, 234)              # 没出成的格
EMPTY_INK = (150, 157, 168)

MARGIN = 64
TARGET_W = 2400
COL_GAP = 20
ROW_GAP = 22
LABEL_H = 48                          # 图下标签区（含与图的间距）
SECTION_PAD = 48                      # 分区竖线两侧的留白
TITLE_SIZE = 54
SECTION_SIZE = 30
LABEL_SIZE = 24
EXPR_LABEL_SIZE = 27
RADIUS = 12
#: 图块宽高比：全身裁窄（人站着只占画面中间一条），脸和表情裁成近方形
BODY_ASPECT = 0.46
FACE_ASPECT = 0.86

#: 中文字体：(文件, 想要的字重)。字体集（.ttc）里按名字挑字重，挑不到用第 0 个
_FONT_FILES: tuple[str, ...] = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)
#: 新版 macOS 的苹方不在 /System/Library/Fonts，在按需下载的字体资源里
_FONT_GLOBS: tuple[str, ...] = ("/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData/PingFang.ttc",)
_BOLD_STYLES = ("Semibold", "Medium", "W6", "Bold")
_REGULAR_STYLES = ("Regular", "W3", "Light")


def _font_paths() -> list[str]:
    import glob

    paths = list(_FONT_FILES)
    for pattern in _FONT_GLOBS:
        paths[1:1] = sorted(glob.glob(pattern))          # 系统目录的苹方没有时，下载资源里的排第二
    return paths


@lru_cache(maxsize=32)
def _font(size: int, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """能写中文的字体。都找不到退 PIL 默认字体（测试机、容器里没有系统字体也得拼得出来）。"""
    styles = _BOLD_STYLES if bold else _REGULAR_STYLES
    for path in _font_paths():
        try:
            fallback = ImageFont.truetype(path, size)
        except Exception:                              # noqa: BLE001 —— 字体缺失不该让拼版失败
            continue
        best: tuple[int, ImageFont.FreeTypeFont] | None = None
        for index in range(32):
            try:
                f = ImageFont.truetype(path, size, index=index)
            except Exception:                          # noqa: BLE001 —— 超出字体集的范围
                break
            family, style = f.getname()
            if family and family.startswith("."):      # 「.Hiragino Sans GB Interface」这类系统界面字体
                continue
            simplified = 0 if family and ("SC" in family or "GB" in family) else 1
            rank = (styles.index(style) if style in styles else len(styles)) * 2 + simplified
            if best is None or rank < best[0]:
                best = (rank, f)
        return best[1] if best is not None else fallback
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                  # 老 Pillow 的默认字体不能调大小
        return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int, int]:
    """(宽, 高, 顶部偏移)。用 textbbox 而不是 anchor：PIL 默认的点阵字体不支持 anchor。"""
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
    except UnicodeEncodeError:                         # 点阵默认字体只认 latin-1
        l, t, r, b = draw.textbbox((0, 0), text.encode("ascii", "replace").decode(), font=font)
    return r - l, b - t, t


def _draw_text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill) -> None:
    try:
        draw.text(xy, text, font=font, fill=fill)
    except UnicodeEncodeError:
        draw.text(xy, text.encode("ascii", "replace").decode(), font=font, fill=fill)


def _subject_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """浅灰无缝背景上的人在哪（原图坐标）。背景不干净、找不到就返回 None（退回居中裁）。"""
    small = img.convert("RGB")
    small.thumbnail((128, 128))
    w, h = small.size
    if w < 8 or h < 8:
        return None
    # 背景色取上沿和两侧中段的中位数：脚下可能有影子，人可能顶到画面下沿
    probes = [small.getpixel(p) for p in ((1, 1), (w - 2, 1), (w // 2, 1), (1, h // 2), (w - 2, h // 2))]
    bg = tuple(sorted(int(c[i]) for c in probes)[len(probes) // 2] for i in range(3))  # type: ignore[index]
    # 按通道取最大差而不是转灰度：浅肤色在浅灰底上亮度差很小（转灰度会把整颗头当背景、特写把头切掉），
    # 色相差却很明显
    r, g, b = ImageChops.difference(small, Image.new("RGB", small.size, bg)).split()
    diff = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = diff.point(lambda v: 255 if v > 26 else 0).filter(ImageFilter.MedianFilter(3))
    box = mask.getbbox()
    if box is None:
        return None
    l, t, r, b = box
    if (r - l) > 0.97 * w and (b - t) > 0.97 * h:       # 满画面都是「主体」= 背景不干净，不可信
        return None
    sx, sy = img.width / w, img.height / h
    return round(l * sx), round(t * sy), round(r * sx), round(b * sy)


def _fit(img: Image.Image, size: tuple[int, int], *, head: bool) -> Image.Image:
    """按目标宽高比裁出最大的一块再缩放。水平以人为中心；head=True 时从头顶上方一点开始（特写别把头切掉）。"""
    tw, th = size
    iw, ih = img.size
    aspect = tw / th
    cw, ch = (iw, round(iw / aspect)) if iw / ih < aspect else (round(ih * aspect), ih)
    box = _subject_box(img)
    cx = (box[0] + box[2]) / 2 if box else iw / 2
    left = round(min(max(cx - cw / 2, 0), iw - cw))
    if head and box:
        top = round(min(max(box[1] - 0.07 * ch, 0), ih - ch))
    elif box:
        top = round(min(max((box[1] + box[3]) / 2 - ch / 2, 0), ih - ch))
    else:
        top = (ih - ch) // 2
    return img.crop((left, top, left + cw, top + ch)).resize((tw, th), Image.LANCZOS)


@dataclass(frozen=True)
class _Grid:
    title: str
    keys: tuple[str, ...]
    cols: int
    aspect: float
    head: bool
    label_size: int
    label_bold: bool

    @property
    def rows(self) -> int:
        return -(-len(self.keys) // self.cols)

    def tile(self, gh: float) -> tuple[int, int]:
        """网格总高 gh（含标签）下一个图块的宽高。"""
        h = (gh - self.rows * LABEL_H - (self.rows - 1) * ROW_GAP) / self.rows
        return max(1, round(h * self.aspect)), max(1, round(h))

    def width(self, gh: float) -> int:
        return self.cols * self.tile(gh)[0] + (self.cols - 1) * COL_GAP


def _grids(preset: str) -> list[_Grid]:
    body, face, expr = SECTIONS
    out = [_Grid(body.title, body.keys, 3, BODY_ASPECT, False, LABEL_SIZE, False)]
    if preset == "quick":
        out.append(_Grid("角色正面特写", ("face_front",), 1, FACE_ASPECT, True, LABEL_SIZE, False))
    else:
        out.append(_Grid(face.title, face.keys, 2, FACE_ASPECT, True, LABEL_SIZE, False))
        out.append(_Grid(expr.title, expr.keys, 3, FACE_ASPECT, True, EXPR_LABEL_SIZE, True))
    return out


def _grid_height() -> int:
    """三个分区等高、整张约 TARGET_W 宽时的网格高度。

    宽度对网格高度是线性的（每格高随它线性变，宽 = 高 × 宽高比），两点定一条线直接解。
    quick 用同一个高度：和标准版并排放时上下对齐，只是更窄。
    """
    grids = _grids("standard")

    def total(gh: float) -> float:
        return 2 * MARGIN + sum(g.width(gh) for g in grids) + (len(grids) - 1) * (2 * SECTION_PAD + 1)

    lo, hi = 600.0, 1200.0
    k = (total(hi) - total(lo)) / (hi - lo)
    return round(lo + (TARGET_W - total(lo)) / k)


def compose_sheet(panels: Mapping[str, Image.Image], name: str = "", preset: str = "standard") -> Image.Image:
    """把各格拼成一张「角色定妆照」（纯函数，不读盘不连库）。

    缺的格画成「未生成」占位，版式不变 —— 一眼看出哪格要重出。
    """
    preset = preset if preset in PRESETS else "standard"
    grids = _grids(preset)
    gh = _grid_height()

    f_title, f_name = _font(TITLE_SIZE, True), _font(TITLE_SIZE - 10, False)
    f_section, f_num = _font(SECTION_SIZE, True), _font(SECTION_SIZE - 4, True)
    f_meta, f_empty = _font(22, False), _font(22, False)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    widths = [g.width(gh) for g in grids]
    W = 2 * MARGIN + sum(widths) + (len(grids) - 1) * (2 * SECTION_PAD + 1)
    _tw, title_h, _t = _text_size(probe, "角色定妆照", f_title)
    rule_y = MARGIN + title_h + 30
    sec_top = rule_y + 40
    _sw, sec_h, _st = _text_size(probe, "角色", f_section)
    grid_top = sec_top + sec_h + 30
    H = grid_top + gh + MARGIN

    sheet = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(sheet)

    # 页眉：大标题（+ 名字），右侧小字写版本，下面一条细线
    tw, th, tt = _text_size(draw, "角色定妆照", f_title)
    _draw_text(draw, (MARGIN, MARGIN - tt), "角色定妆照", f_title, INK)
    name = " ".join((name or "").split())[:24]
    if name:
        nw, nh, nt = _text_size(draw, f"·  {name}", f_name)
        # 名字和标题底边对齐（字号不同，按各自字形的底对齐）
        _draw_text(draw, (MARGIN + tw + 22, MARGIN + th - nh - nt), f"·  {name}", f_name, SUB)
    meta = "标准版 · 16 格" if preset == "standard" else "快速版 · 4 格"
    mw, mh, mt = _text_size(draw, meta, f_meta)
    _draw_text(draw, (W - MARGIN - mw, MARGIN + th - mh - mt), meta, f_meta, SUB)
    draw.line([(MARGIN, rule_y), (W - MARGIN, rule_y)], fill=RULE, width=2)

    # 先在一层上画所有图块的投影，模糊后一次铺上：浅灰底上白描边的图块才「浮」得起来
    shadow = Image.new("L", (W, H), 0)
    sdraw = ImageDraw.Draw(shadow)
    tiles: list[tuple[int, int, int, int, str, _Grid]] = []
    x = MARGIN
    for gi, (g, gw) in enumerate(zip(grids, widths)):
        # 分区标题：蓝色编号 + 粗黑标题
        num = f"{gi + 1:02d}"
        nw, nh, nt = _text_size(draw, num, f_num)
        sw, sh, st = _text_size(draw, g.title, f_section)
        _draw_text(draw, (x, sec_top + sh - nh - nt), num, f_num, ACCENT)
        _draw_text(draw, (x + nw + 14, sec_top - st), g.title, f_section, INK)

        tw_, th_ = g.tile(gh)
        # 网格在分区里水平居中（取整误差摊到两边），竖直方向从网格顶开始
        used = g.cols * tw_ + (g.cols - 1) * COL_GAP
        gx = x + (gw - used) // 2
        for i, key in enumerate(g.keys):
            r, c = divmod(i, g.cols)
            tx = gx + c * (tw_ + COL_GAP)
            ty = grid_top + r * (th_ + LABEL_H + ROW_GAP)
            tiles.append((tx, ty, tw_, th_, key, g))
            sdraw.rounded_rectangle([tx, ty + 4, tx + tw_, ty + th_ + 4], radius=RADIUS, fill=46)
        x += gw
        if gi < len(grids) - 1:
            lx = x + SECTION_PAD
            draw.line([(lx, sec_top), (lx, grid_top + gh)], fill=RULE, width=1)
            x = lx + 1 + SECTION_PAD

    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    sheet.paste(Image.new("RGB", (W, H), (150, 158, 172)), (0, 0), shadow)
    draw = ImageDraw.Draw(sheet)

    masks: dict[tuple[int, int], Image.Image] = {}
    for tx, ty, tw_, th_, key, g in tiles:
        mask = masks.get((tw_, th_))
        if mask is None:
            mask = Image.new("L", (tw_, th_), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw_ - 1, th_ - 1], radius=RADIUS, fill=255)
            masks[(tw_, th_)] = mask
        img = panels.get(key)
        if img is not None:
            sheet.paste(_fit(img.convert("RGB"), (tw_, th_), head=g.head), (tx, ty), mask)
            draw.rounded_rectangle([tx, ty, tx + tw_ - 1, ty + th_ - 1], radius=RADIUS, outline=FRAME, width=1)
        else:
            draw.rounded_rectangle([tx, ty, tx + tw_ - 1, ty + th_ - 1], radius=RADIUS, fill=EMPTY, outline=FRAME)
            ew, eh, et = _text_size(draw, "未生成", f_empty)
            _draw_text(draw, (tx + (tw_ - ew) / 2, ty + (th_ - eh) / 2 - et), "未生成", f_empty, EMPTY_INK)
        label = LABELS.get(key, key)
        f_label = _font(g.label_size, g.label_bold)
        lw, lh, lt = _text_size(draw, label, f_label)
        # 标签在图块正下方居中，竖直方向落在标签区中间偏上（离图近、离下一行远，分组才清楚）
        _draw_text(draw, (tx + (tw_ - lw) / 2, ty + th_ + (LABEL_H - lh) * 0.45 - lt), label, f_label, LABEL)
    return sheet


# ── 后台任务（给 /api/v2/studio/char-sheets 用；画布走执行器，不走这里） ───────

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
#: 内存里最多留几条（老的、已结束的先丢）
MAX_JOBS = 200


def job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        j = _JOBS.get(job_id)
        return {k: v for k, v in j.items() if not k.startswith("_")} if j else None


def _set(job_id: str, **kw: Any) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(kw)


def _prune() -> None:
    """调用方须持有 _LOCK。"""
    if len(_JOBS) < MAX_JOBS:
        return
    done = sorted((j.get("finished_at") or 0, jid) for jid, j in _JOBS.items() if j.get("state") != "running")
    for _ts, jid in done[: len(_JOBS) - MAX_JOBS + 1]:
        _JOBS.pop(jid, None)


def start(spec: dict[str, Any]) -> dict[str, Any]:
    """后台出一张定妆照。spec = generate_sheet 的关键字参数（person_url 必给）。状态只在内存（core 重启就没了，
    已出的格都已落库；同样的参数再交一次命中幂等，出好的格直接复用）。"""
    from app.ids import new_id

    jid = new_id("csheet")
    with _LOCK:
        _prune()
        _JOBS[jid] = {"id": jid, "state": "running", "progress": 0, "step": "排队", "error": None,
                      "sheet": None, "panels": [], "missing": [], "preset": spec.get("preset") or "standard",
                      "started_at": time.time(), "finished_at": None}
    threading.Thread(target=_run_job, args=(jid, dict(spec)), name=f"char-sheet-{jid}", daemon=True).start()
    return job(jid) or {}


def _run_job(jid: str, spec: dict[str, Any]) -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        binding = spec.pop("canonical_binding", None)
        res = generate_sheet(db, **spec, on_progress=lambda pct, step: _set(jid, progress=pct, step=step))
        if binding:
            from sqlalchemy import select
            from app.models import AssetEpoch, WorldEntity
            from app.production import service as production
            from app.production.schema import PackBinding
            # Preserve generated outputs even if the canonical pack changed during generation.
            _set(jid, progress=98, step="写入角色标准素材", sheet=res["sheet"], panels=res["panels"],
                 missing=res.get("missing") or [])
            ent = production.get(db, WorldEntity, binding["entity_id"])
            epoch = db.scalar(select(AssetEpoch).where(AssetEpoch.id == binding["epoch_id"],
                AssetEpoch.subject_key == ent.id, AssetEpoch.workspace_id == ent.workspace_id)
                .with_for_update().execution_options(populate_existing=True))
            if epoch is None:
                raise SheetError("造型时期已不存在，已生成的素材保留在媒体库")
            production.choose_epoch(db, ent, epoch.world_profile_id, epoch.id)
            production.bind_pack(db, ent, epoch, PackBinding(epoch_id=epoch.id,
                base_revision=binding["base_revision"],
                views={p["view_key"]: p["asset_id"] for p in res["panels"] if p.get("view_key") and p.get("asset_id")},
                sheet_asset_id=(res.get("sheet") or {}).get("asset_id")))
            db.commit()
        _set(jid, state="done", progress=100, step="完成", sheet=res["sheet"], panels=res["panels"],
             missing=res.get("missing") or [], finished_at=time.time())
    except Exception as exc:                           # noqa: BLE001 —— 后台线程：错误放进状态给调用方看
        db.rollback()
        log.warning("char_sheet %s failed: %s", jid, exc)
        msg = str(exc) if isinstance(exc, SheetError) else f"出错了：{exc}"
        _set(jid, state="failed", error=msg[:400], finished_at=time.time())
    finally:
        db.close()
