"""画布服务端执行器：按节点的生成配方（纳逗式）在后端出图、出视频、出标准定妆照、取尾帧、拼接。

纳逗式画布上每个生成节点都带配方（前端 model.ts 的 Recipe：提示词 + @引用 + 参考角色 + 模型参数）。
为什么放在后端跑、不让浏览器一个个交：
  - 一张「想法画布」是 定妆照 → 换装 → 场景图 → 分镜 1..N → 视频 1..N → 成片 一串依赖，跑完要半小时以上，
    浏览器一关、电脑一睡，前端的循环就断了；后端照跑。
  - 依赖顺序（拓扑序）只有知道整张图才排得对：分镜图要等定妆照出完，视频要等分镜图出完。

怎么跑：
  execute(db, board_id, opts) 读库里那份画布文档（调用前前端先存盘），挑出要跑的节点、补上没产物的上游、拓扑排序，
  每个节点建一行 queued 的 StudioNodeRun，把画布排进**进程内唯一的执行队列**：
  本机一块 GPU，全局只有一个工作线程，画布之间先来先跑，画布内按拓扑序一个节点一个节点跑。
  每个节点开跑时再从库里取一次文档（排队期间改了配方，跑的是新的那版），结果写进 run 行，前端轮询 node-runs 填回节点。

节点的「当前产物」：它最近一次成功 run 的 media（文档里的 data.media 可能还没被前端合进去）；
但前端「换回」过旧图（那次 run 的图进了 data.history）就以文档为准。

生成都走现有能力层（service.submit_task，点名模型的路由照 keyframe._route 的写法找，本机模型不过付费闸），
产物地址一律给同源 /media/…（网关临时地址不进画布，铁律 2）。

状态：run 行在库里；队列只在内存（core 重启后第一次用执行器时，把库里排队/在跑的 run 标成失败，让人点重跑）。
"""
from __future__ import annotations

import hashlib
import heapq
import io
import json
import logging
import random
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.errors import CapabilityError
from app.capability.schemas import Capability
from app.db import SessionLocal
from app.ids import new_id
from app.models import (
    Asset, AssetKind, AssetSource, CapabilityEndpoint, CapabilityRoute, GenTask, StudioBoard, StudioNodeRun,
    TaskStatus, utcnow,
)

log = logging.getLogger(__name__)

OPS = ("image", "video", "sheet", "concat", "last_frame", "one_take")
#: 还没结束的 run（库里）；waiting 只是给人看的「等上游」，库里存的是 queued
ACTIVE_RUN = ("queued", "waiting", "running")
#: 执行器（一张画布）还在跑
ACTIVE_EXEC = ("queued", "running")

T2I = Capability.image_t2i.value
I2I = Capability.image_i2i.value
I2V = Capability.video_i2v.value
#: 本机默认模型（同 quick_film / keyframe 的 local 引擎）
EDIT_MODEL = "flux2-klein-4b-edit"
T2I_MODEL = "flux2-klein-4b"
VIDEO_MODEL = "ltx-2.5-22b-distilled"
#: FLUX.2-klein 编辑档：底图也占一个名额
MAX_EDIT_REFS = 4
#: 分镜图默认尺寸（klein 编辑档只有 800×480 / 512×768 / 1536×768）
IMAGE_SIZE = (800, 480)
#: LTX 2.5 本机最快的一档（768×448 Q8 流式）；拼接也统一到它
VIDEO_SIZE = (768, 448)
FPS = 24
MIN_VIDEO_MS, MAX_VIDEO_MS, DEFAULT_VIDEO_MS = 2_000, 20_000, 5_000
#: LTX 2.5 一次最多 481 帧（20 秒），一次成片留点余量
MAX_TAKE_MS = 19_000
MAX_COUNT = 4
IMAGE_TIMEOUT_S = 15 * 60
VIDEO_TIMEOUT_S = 60 * 60
POLL_S = 5.0
#: 产物落地时没取回本库（网关临时地址）：隔 30 秒再取，最多几次
RELOCALIZE_TRIES = 3
PURPOSE = "canvas"
REF_KIND = "canvas_node"
#: 对图片来说「首帧」就是「从这张图出发」（同 generic.BASE_ROLES）
BASE_ROLES = ("base", "first_frame")
IDENTITY_ROLES = ("character", "reference_sheet")
#: 前端 RefRole → 契约 RefRole（同 generic._CORE_ROLE；那个是私有的，这里抄一份）
CORE_ROLE = {"character": "character", "reference_sheet": "character", "style": "style", "scene": "scene",
             "reference": "scene", "control_video": "composition"}
#: 现取内容的派生节点（剧本、镜头、角色视角、白模）：本轮执行器不支持当参考
LIVE_REF_KINDS = frozenset({"story", "scene", "shot", "entity_view", "box_project"})
_VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v")
HISTORY_KEEP = 12


class ExecError(RuntimeError):
    """这个节点跑不了 / 跑失败了。消息直接给人看。"""


class Skip(RuntimeError):
    """上游失败，这个节点不跑（status=skipped）。"""


class Cancelled(RuntimeError):
    """人点了停止。"""


class BoardNotFound(LookupError):
    pass


class CycleError(ValueError):
    """配方引用成环：A 引用 B、B 又引用 A，排不出先后。"""

    def __init__(self, nodes: list[str], titles: Mapping[str, str] | None = None) -> None:
        self.nodes = nodes
        names = [(titles or {}).get(n) or n for n in nodes]
        super().__init__("这几个节点的配方互相引用成了环，排不出先后：" + " → ".join(names + names[:1]))


# ── 文档（纯函数）────────────────────────────────────────────────────────

def doc_nodes(doc: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """文档里的节点，按 id；保持文档里的顺序（拓扑序同层时按它排，结果稳定）。"""
    out: dict[str, dict[str, Any]] = {}
    for n in (doc or {}).get("nodes") or []:
        if isinstance(n, dict) and isinstance(n.get("id"), str) and n["id"] not in out:
            out[n["id"]] = n
    return out


def data_of(node: Mapping[str, Any] | None) -> dict[str, Any]:
    d = (node or {}).get("data")
    return d if isinstance(d, dict) else {}


def recipe_of(node: Mapping[str, Any] | None) -> dict[str, Any] | None:
    r = data_of(node).get("recipe")
    return r if isinstance(r, dict) and r.get("op") in OPS else None


def title_of(node: Mapping[str, Any] | None, fallback: str = "") -> str:
    t = data_of(node).get("title")
    return str(t).strip() if isinstance(t, str) and t.strip() else (str((node or {}).get("id") or fallback))


def media_url(node: Mapping[str, Any] | None) -> str | None:
    m = data_of(node).get("media")
    url = m.get("url") if isinstance(m, dict) else None
    return url if isinstance(url, str) and url else None


def _canon(v: Any) -> Any:
    """哈希前的规范形：键排序、去掉空值和 chip 的 label。

    label 只是 chip 上显示的节点标题 —— 改个节点名不该让下游全部判成「配方改过、要重跑」；
    前端有时写 model: null、有时不写这个键，两者也该是同一份配方。
    """
    if isinstance(v, dict):
        out = {}
        for k in sorted(v):
            x = _canon(v[k])
            if k == "label" or x is None or x == "" or x == [] or x == {}:
                continue
            out[k] = x
        return out
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return v


def recipe_hash(recipe: Mapping[str, Any] | None) -> str:
    """配方的稳定哈希（64 位 hex）：同一份配方不管键顺序、空值写法都一样。"""
    raw = json.dumps(_canon(dict(recipe or {})), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ref_nodes(recipe: Mapping[str, Any] | None) -> list[str]:
    """配方引用的节点 id（refs 再加 one_take 的 segments），按出现顺序去重。"""
    out: list[str] = []
    for r in (recipe or {}).get("refs") or []:
        if isinstance(r, dict) and isinstance(r.get("node"), str):
            out.append(r["node"])
    for s in (recipe or {}).get("segments") or []:
        if isinstance(s, dict) and isinstance(s.get("node"), str):
            out.append(s["node"])
    return list(dict.fromkeys(out))


def _pos(node: Mapping[str, Any]) -> tuple[float, float]:
    p = node.get("position") or {}
    try:
        return float(p.get("x") or 0), float(p.get("y") or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0


def children_of(nodes: Mapping[str, Mapping[str, Any]], group_id: str) -> list[str]:
    """分组里的图片节点，从左到右（同一列从上到下）：@分组 = 组里所有图。"""
    kids = [n for n in nodes.values() if n.get("parentId") == group_id and n.get("type") == "image"]
    return [str(n["id"]) for n in sorted(kids, key=_pos)]


def dep_ids(nodes: Mapping[str, Mapping[str, Any]], recipe: Mapping[str, Any] | None) -> list[str]:
    """配方实际依赖的节点：分组展开成组里的图。"""
    out: list[str] = []
    for nid in ref_nodes(recipe):
        n = nodes.get(nid)
        if n is not None and n.get("type") == "group":
            out += children_of(nodes, nid)
        else:
            out.append(nid)
    return list(dict.fromkeys(out))


def recipe_graph(nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    """配方节点 → 它依赖的配方节点。引用自己不算依赖（「以本图为底图再改一版」用的是它当前的图）。"""
    rec = {nid for nid, n in nodes.items() if recipe_of(n)}
    return {nid: [d for d in dep_ids(nodes, recipe_of(nodes[nid])) if d in rec and d != nid] for nid in rec}


def topo_order(targets: Iterable[str], graph: Mapping[str, Sequence[str]],
               rank: Mapping[str, int] | None = None, titles: Mapping[str, str] | None = None) -> list[str]:
    """targets 按依赖排先后（上游在前）；同一层按 rank（文档顺序）。成环抛 CycleError，带环上的节点。

    只看 targets 之间的依赖：不在这次要跑的上游已经有产物，直接用。
    """
    todo = list(dict.fromkeys(targets))
    want = set(todo)
    rank = rank or {}
    deps = {n: [d for d in graph.get(n, ()) if d in want] for n in todo}
    indeg = {n: len(set(deps[n])) for n in todo}
    users: dict[str, list[str]] = {n: [] for n in todo}
    for n in todo:
        for d in set(deps[n]):
            users[d].append(n)
    key = {n: (rank.get(n, 10**9), i) for i, n in enumerate(todo)}
    ready = [(key[n], n) for n in todo if indeg[n] == 0]
    heapq.heapify(ready)
    out: list[str] = []
    while ready:
        _k, n = heapq.heappop(ready)
        out.append(n)
        for u in users[n]:
            indeg[u] -= 1
            if indeg[u] == 0:
                heapq.heappush(ready, (key[u], u))
    if len(out) < len(todo):
        left = {n for n in todo if indeg[n] > 0}
        raise CycleError(_find_cycle(left, deps), titles)
    return out


def _find_cycle(left: set[str], deps: Mapping[str, Sequence[str]]) -> list[str]:
    """剩下的节点里找出一个环（报错时只列环上的，不列被它卡住的下游）。"""
    start = min(left)
    path: list[str] = []
    seen: dict[str, int] = {}
    n = start
    while n not in seen:
        seen[n] = len(path)
        path.append(n)
        nxt = next((d for d in deps.get(n, ()) if d in left), None)
        if nxt is None:            # 理论上走不到：剩下的每个点都还有没排掉的上游
            return sorted(left)
        n = nxt
    return path[seen[n]:]


@dataclass
class Done:
    """一个节点最近一次成功 run 的结果。"""

    hash: str | None
    media: dict[str, Any] | None
    extra: list[dict[str, Any]] = field(default_factory=list)


def has_output(node: Mapping[str, Any], done: Done | None) -> bool:
    return bool(media_url(node)) or bool(done is not None and done.media and done.media.get("url"))


def node_recipe_hash(node: Mapping[str, Any], nodes: Mapping[str, Mapping[str, Any]]) -> str:
    """Production source revisions participate in derived-result caching, transitively through groups/recipes."""
    selected: dict[str, Any] = {}
    visited: set[str] = set()
    def visit(nid: str):
        if nid in visited:
            return
        visited.add(nid)
        current = nodes.get(nid)
        if current is None:
            return
        ref = data_of(current).get("ref") or {}
        if isinstance(ref, dict) and ref.get("mode") == "reference":
            selected[nid] = ref
        if current.get("type") == "group":
            for child in children_of(nodes, nid):
                visit(child)
        for upstream in ref_nodes(recipe_of(current)):
            visit(upstream)
    for nid in ref_nodes(recipe_of(node)):
        visit(nid)
    recipe = recipe_of(node)
    return recipe_hash({"recipe": recipe, "source_refs": selected}) if selected else recipe_hash(recipe)


def is_stale(node: Mapping[str, Any], done: Done | None, nodes: Mapping[str, Mapping[str, Any]] | None = None) -> bool:
    """该不该跑：没出过（也没有现成的图）、或最近一次成功跑的不是现在这版配方。"""
    if done is None:
        return not media_url(node)
    return done.hash != (node_recipe_hash(node, nodes) if nodes is not None else recipe_hash(recipe_of(node)))


def select_targets(nodes: Mapping[str, Mapping[str, Any]], done: Mapping[str, Done], *,
                   node_ids: Sequence[str] | None = None, downstream: bool = False,
                   force: bool = False) -> list[str]:
    """这次要跑哪些节点（未排序；调用方再拓扑排序）。

    node_ids 不给 = 整张画布里该跑的（没出过、或配方改过）；给了 = 这几个（force 才重跑已经出过的）。
    downstream = 再加上配方（传递地）引用它们的节点 —— 上游要换了，下游一律重跑。
    最后补依赖：目标引用的上游配方节点如果还没产物，也排进来（不然目标一跑就缺图）。
    """
    graph = recipe_graph(nodes)
    if node_ids is None:
        base = [n for n in graph if is_stale(nodes[n], done.get(n), nodes)]
    else:
        given = [n for n in dict.fromkeys(node_ids) if n in graph]
        base = given if force else [n for n in given if is_stale(nodes[n], done.get(n), nodes)]
    targets = set(base)
    if downstream and targets:
        users: dict[str, list[str]] = {n: [] for n in graph}
        for n, deps in graph.items():
            for d in deps:
                users[d].append(n)
        stack = list(targets)
        while stack:
            for u in users.get(stack.pop(), ()):
                if u not in targets:
                    targets.add(u)
                    stack.append(u)
    stack = list(targets)
    while stack:
        for d in graph.get(stack.pop(), ()):
            if d not in targets and (not has_output(nodes[d], done.get(d)) or is_stale(nodes[d], done.get(d), nodes)):
                targets.add(d)
                stack.append(d)
    rank = {n: i for i, n in enumerate(nodes)}
    return sorted(targets, key=lambda n: rank.get(n, 10**9))


# ── 媒体地址（纯函数）──────────────────────────────────────────────────

def same_origin(url: str | None) -> str:
    """库里的 Asset.url 写死了 public_base_url（http://localhost:8100/media/x）；给前端的一律是 /media/x。"""
    u = str(url or "")
    if u.startswith("data:"):
        return u
    i = u.find("/media/")
    return u[i:].split("#", 1)[0] if i >= 0 else u


def _kind_of(url: str, mime: Any = None, node_type: Any = None) -> str:
    if node_type == "audio" or (isinstance(mime, str) and mime.startswith("audio/")):
        return "audio"
    if node_type == "video":
        return "video"
    if isinstance(mime, str) and mime.startswith("video/"):
        return "video"
    if url.startswith("data:video/"):
        return "video"
    path = url.split("?", 1)[0].lower()
    return "video" if path.endswith(_VIDEO_EXT) else "image"


@dataclass
class Media:
    """解析出来的一张参考图 / 一条参考视频。"""

    node: str
    url: str                  # 同源 /media/… 或 data:
    asset_id: str | None
    kind: str                 # image | video
    label: str                # 给人看：节点标题（定妆照面板加面板名）
    role: str = "reference"


def current_media(node: Mapping[str, Any], done: Done | None) -> dict[str, Any] | None:
    """节点现在的产物：最近一次成功 run 的优先（前端可能还没合进文档）；
    但那张图已经进了 data.history（前端「换回」了旧图）就以文档为准。"""
    doc = data_of(node).get("media")
    doc = doc if isinstance(doc, dict) and doc.get("url") else None
    run = done.media if done is not None and done.media and done.media.get("url") else None
    if run is None:
        return doc
    history = {h.get("url") for h in data_of(node).get("history") or [] if isinstance(h, dict)}
    if doc is not None and run["url"] in history:
        return doc
    return run


def panels_of(done: Done | None) -> list[dict[str, Any]]:
    """sheet 节点 run.extra → char_sheet.identity_panels 吃的面板形状。"""
    out = []
    for e in (done.extra if done else []) or []:
        m = e.get("media") if isinstance(e, dict) else None
        if isinstance(m, dict) and m.get("url"):
            key = str(e.get("label") or "")
            out.append({"key": key, "label": key, "asset_id": m.get("asset_id"), "url": m["url"]})
    return out


def panel_want(role: str) -> str:
    """引用定妆照时按角色挑格：底图 / 首帧要一张正面全身，其余当身份参考要三视图 + 正脸。"""
    return "base" if role in (*BASE_ROLES, "last_frame") else "character"


PanelPicker = Callable[[list[dict[str, Any]], str], list[dict[str, Any]]]
AssetUrl = Callable[[str], str | None]
ResourceMedia = Callable[[Mapping[str, Any]], dict[str, Any] | None]


def _sheet_picker(panels: list[dict[str, Any]], want: str) -> list[dict[str, Any]]:
    from app.pipelines import char_sheet

    return list(char_sheet.identity_panels(panels, want))


def resolve_node(nodes: Mapping[str, Mapping[str, Any]], done: Mapping[str, Done],
                 status: Mapping[str, str], nid: str, *, role: str = "reference", panel: str | None = None,
                 self_id: str | None = None, pick_panels: PanelPicker | None = None,
                 asset_url: AssetUrl | None = None, resource_media: ResourceMedia | None = None) -> list[Media]:
    """一个被引用的节点 → 它当前的媒体（分组展开成组里的图；定妆照展开成几格面板）。

    文字节点不出媒体（返回空）。上游配方节点失败过 → Skip；派生节点（剧本、镜头…）→ ExecError。
    """
    node = nodes.get(nid)
    if node is None:
        raise ExecError(f"参考的节点已经不在画布上了（{nid}）")
    title = title_of(node)
    ntype = node.get("type")
    if ntype == "text":
        return []
    if ntype == "group":
        out: list[Media] = []
        for cid in children_of(nodes, nid):
            child = nodes[cid]
            if not has_output(child, done.get(cid)) and not (resource_media and (data_of(child).get("ref") or {}).get("mode") == "reference"):
                if recipe_of(child) and status.get(cid) in ("failed", "skipped", "cancelled"):
                    raise Skip(f"上游「{title_of(child)}」失败")
                continue
            out += resolve_node(nodes, done, status, cid, role=role, self_id=self_id,
                                pick_panels=pick_panels, asset_url=asset_url, resource_media=resource_media)
        if not out:
            raise ExecError(f"分组「{title}」里还没有图")
        return out

    d = done.get(nid)
    rec = recipe_of(node)
    if rec and rec.get("op") == "sheet":
        panels = panels_of(d)
        if panels:
            chosen = [p for p in panels if panel and p["key"] == panel]
            if not chosen:
                chosen = (pick_panels or _sheet_picker)(panels, panel_want(role))
            if chosen:
                return [Media(node=nid, url=same_origin(p["url"]), asset_id=p.get("asset_id"), kind="image",
                              label=f"{title}·{p['key']}", role=role) for p in chosen]

    ref = data_of(node).get("ref") or {}
    # Resolve before reading any cached URL: source revisions and bindings are authoritative.
    if isinstance(ref, dict) and ref.get("mode") == "reference":
        if resource_media is None:
            raise ExecError(f"「{title}」需要生产资源解析器，不能直接使用缓存地址")
        m = resource_media(ref)
        if m is None:
            raise ExecError(f"「{title}」尚无可用媒体")
    else:
        m = current_media(node, d)
    if m is None:
        ref = data_of(node).get("ref") or {}
        if isinstance(ref, dict) and ref.get("kind") == "asset" and ref.get("id") and asset_url is not None:
            url = asset_url(str(ref["id"]))
            if url:
                m = {"url": url, "asset_id": ref["id"]}
    if m is not None:
        url = same_origin(m["url"])
        return [Media(node=nid, url=url, asset_id=m.get("asset_id"), kind=_kind_of(url, m.get("mime"), ntype),
                      label=title, role=role)]
    ref = data_of(node).get("ref") or {}
    if isinstance(ref, dict) and ref.get("kind") in LIVE_REF_KINDS:
        raise ExecError(f"「{title}」这类节点（剧本、镜头、角色视角）还不能当参考：先把图拿出来成一张图片节点")
    if nid == self_id:
        raise ExecError("配方参考了节点自己，但它还没有图")
    if rec:
        if status.get(nid) in ("failed", "skipped", "cancelled"):
            raise Skip(f"上游「{title}」失败")
        raise ExecError(f"上游「{title}」还没出结果")
    raise ExecError(f"参考「{title}」没有图")


# ── 提示词与尺寸（纯函数）──────────────────────────────────────────────

def _images_phrase(idx: Sequence[int]) -> str:
    if len(idx) == 1:
        return f"image {idx[0]}"
    head = ", ".join(str(i) for i in idx[:-1])
    return f"images {head} and {idx[-1]}"


def prompt_text(prompt: Any, index: Mapping[str, Sequence[int]] | None = None,
                texts: Mapping[str, str] | None = None) -> str:
    """PromptSeg[] → 发给模型的一段文字。

    @引用 chip 只是标签（铁律 5：引用只引用），真正的参考图在 payload 里；chip 换成它在 payload 里的位置
    「image 2」（底图是 image 1，其余参考按顺序往后）—— 模型认得序号，认不得「图片 15」这种画布标题。
    引用的是文字节点就换成它的正文；没送进 payload 的（视频提示词里的图、被裁掉的参考）就去掉。
    """
    index = index or {}
    texts = texts or {}
    if isinstance(prompt, str):
        return re.sub(r"[ \t]{2,}", " ", prompt).strip()
    parts: list[str] = []
    for seg in prompt or []:
        if not isinstance(seg, dict):
            continue
        if seg.get("t") == "text":
            parts.append(str(seg.get("text") or ""))
        elif seg.get("t") == "ref":
            nid = str(seg.get("node") or "")
            if index.get(nid):
                parts.append(_images_phrase(index[nid]))
            elif texts.get(nid):
                parts.append(texts[nid])
    text = "".join(parts)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fit_size(w: int, h: int, sizes: Sequence[tuple[int, int]] | None) -> tuple[int, int]:
    """显式宽高夹到模型认的尺寸：先挑画幅最接近的，再挑面积最接近的（同 generic.clamp_size 的挑法）。"""
    import math

    if not sizes or (w, h) in sizes or w <= 0 or h <= 0:
        return w, h
    target = w / h
    gap = {s: abs(math.log((s[0] / s[1]) / target)) for s in sizes}
    best = min(gap.values())
    close = [s for s in sizes if gap[s] <= best + 0.07]
    return min(close, key=lambda s: (abs(math.log(s[0] * s[1] / (w * h))), gap[s]))


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def clamp_ms(ms: Any, max_ms: int | None = None) -> int:
    out = _int(ms) or DEFAULT_VIDEO_MS
    hi = min(MAX_VIDEO_MS, max_ms) if max_ms else MAX_VIDEO_MS
    return max(MIN_VIDEO_MS, min(hi, out))


def take_spans(at_ms: Sequence[int], total_ms: int | None = None,
               max_ms: int = MAX_TAKE_MS) -> list[tuple[int, int]]:
    """一次成片的分段：每段 (start_ms, end_ms)，段尾 = 下一段开头；总长不给就按平均段长补最后一段。
    超过 LTX 上限就按比例整体压缩（各段相对节奏不变）。"""
    starts = sorted(max(0, int(a)) for a in at_ms)
    if not starts:
        return []
    starts[0] = 0                                   # 第一张分镜钉第 0 帧
    if total_ms is None or total_ms <= starts[-1]:
        avg = starts[-1] / (len(starts) - 1) if len(starts) > 1 else 4000
        total_ms = int(starts[-1] + max(2000, avg))
    k = min(1.0, max_ms / total_ms) if total_ms else 1.0
    ends = starts[1:] + [total_ms]
    return [(int(round(a * k)), int(round(b * k))) for a, b in zip(starts, ends)]


def one_take_payload(frames: Sequence[str], motions: Sequence[str], spans: Sequence[tuple[int, int]],
                     prompt: str, audio: str, size: tuple[int, int], seed: int | None,
                     strength: float = 0.9) -> dict[str, Any]:
    """几张分镜钉在一次 LTX 2.5 生成里（照 quick_film.one_take_payload 的形状，自己写一份）：
    第一张钉第 0 帧，其余钉在各自那段开始的帧；segments 按时间给每段的动作。frames 是网关取得到的地址。"""
    total = spans[-1][1]
    nframes = int(round(total / 1000 * FPS)) + 1
    keys = []
    for (start, _end), url in list(zip(spans, frames))[1:]:
        idx = min(nframes - 2, max(1, int(round(start / 1000 * FPS))))
        keys.append({"image": _src(url), "frame_idx": idx, "strength": strength})
    lead = prompt or " ".join(m for m in motions if m)
    return {
        "prompt": video_prompt(lead[:1500], audio),
        "first_frame": _src(frames[0]), "keyframes": keys,
        "segments": [{"prompt": m, "start_ms": a, "end_ms": b} for m, (a, b) in zip(motions, spans)],
        "duration_ms": total, "width": size[0], "height": size[1], "fps": FPS, "quality": "final",
        "audio": {"mode": "generate"}, "params": {"seed": seed} if seed is not None else {},
    }


def video_prompt(text: str, audio: str | None) -> str:
    """LTX 2.5 的提示词 = 配方文字 + 声音一行（它自带同步音轨，不写就容易出人声乱语）。"""
    sound = (audio or "").strip().rstrip(".")
    line = f"Audio: {sound}." if sound else "Audio: natural ambient sound of the scene. No dialogue."
    return f"{text.strip()}\n\n{line}" if text.strip() else line


def _src(url: str) -> dict[str, Any]:
    """参考 → 契约 AssetRefIn：data: 拆成 b64 + mime，其余是网关取得到的绝对地址（同 generic._src）。"""
    if url.startswith("data:"):
        head, _, data = url.partition(",")
        return {"b64": data, "mime": head[5:].split(";", 1)[0] or "application/octet-stream"}
    return {"url": url}


# ── 进程内执行队列 ──────────────────────────────────────────────────────

@dataclass
class _Exec:
    board_id: str
    queue: list[str] = field(default_factory=list)
    #: 节点 → 这一轮给它建的 run id
    runs: dict[str, str] = field(default_factory=dict)
    running: str | None = None
    running_hash: str | None = None
    done: int = 0
    failed: int = 0
    total: int = 0
    status: str = "queued"
    error: str | None = None
    stop: bool = False
    #: 给 node-runs 算「等上游：分镜 1」用
    deps: dict[str, list[str]] = field(default_factory=dict)
    titles: dict[str, str] = field(default_factory=dict)


_LOCK = threading.RLock()
#: 串行化 execute / stop 调用：两个请求同时给同一节点建 run 会重复排
_CALL_LOCK = threading.Lock()
_WAKE = threading.Event()
_WORKER: threading.Thread | None = None
#: 画布 → 执行状态；插入顺序 = 先来先跑
_EXECS: dict[str, _Exec] = {}
_RECOVER_LOCK = threading.Lock()
_RECOVERED = False
#: 内存里最多留多少张画布的执行状态（结束了的只为了给前端报最后一次结果）
_KEEP_FINISHED = 200


def state_of(ex: _Exec) -> dict[str, Any]:
    """前端 ExecuteState。done = 已经结束的节点数（成功、失败、跳过都算，进度条才走得到头），failed 是其中失败/跳过的。"""
    return {"board_id": ex.board_id, "status": ex.status, "queued": list(ex.queue), "running": ex.running,
            "done": ex.done, "failed": ex.failed, "total": ex.total, "error": ex.error}


def idle_state(board_id: str) -> dict[str, Any]:
    return {"board_id": board_id, "status": "idle", "queued": [], "running": None,
            "done": 0, "failed": 0, "total": 0, "error": None}


def exec_state(board_id: str) -> dict[str, Any] | None:
    with _LOCK:
        ex = _EXECS.get(board_id)
        return state_of(ex) if ex else None


def _recover_once() -> None:
    """core 重启后第一次用执行器时：上个进程留下的排队/在跑的 run 都没人管了，标失败让人点重跑。

    放在第一次使用时而不是模块加载时：import 不该写库（测试、alembic、脚本都会 import 到这里）。
    锁住整个过程：另一个线程这时建的新 run 不能被当成残留标掉。
    """
    global _RECOVERED
    with _RECOVER_LOCK:
        if _RECOVERED:
            return
        try:
            with SessionLocal() as db:
                rows = list(db.execute(select(StudioNodeRun).where(StudioNodeRun.status.in_(ACTIVE_RUN))).scalars())
                for r in rows:
                    r.status, r.error, r.finished_at = "failed", "core 重启过，点重跑", utcnow()
                db.commit()
                if rows:
                    log.info("画布执行器：上个进程留下 %d 个没跑完的节点，已标失败", len(rows))
        except Exception:                             # noqa: BLE001 —— 表还没迁移等：不挡执行器本身
            log.exception("画布执行器恢复失败")
        _RECOVERED = True


def _latest(db: Session, board_id: str) -> tuple[dict[str, Done], dict[str, str], dict[str, StudioNodeRun]]:
    """这张画布每个节点：最近一次成功的结果、最近一次的状态、最近一次的 run 行。"""
    rows = db.execute(select(StudioNodeRun).where(StudioNodeRun.board_id == board_id)
                      .order_by(StudioNodeRun.created_at.desc(), StudioNodeRun.id.desc())).scalars()
    done: dict[str, Done] = {}
    status: dict[str, str] = {}
    latest: dict[str, StudioNodeRun] = {}
    for r in rows:
        if r.node_id not in latest:
            latest[r.node_id] = r
            status[r.node_id] = r.status
        if r.status == "succeeded" and r.node_id not in done and r.media_json:
            done[r.node_id] = Done(hash=r.recipe_hash, media=dict(r.media_json), extra=list(r.extra_json or []))
    return done, status, latest


def execute(db: Session, board_id: str, opts: Mapping[str, Any] | Any | None = None) -> dict[str, Any]:
    """按配方跑这张画布（读库里的文档；前端调用前先存盘）。返回 ExecuteState。

    同一张画布已经在跑：新目标并进去（同一个节点不重复排；在跑的那个配方改过才再排一次）。
    """
    o = opts if isinstance(opts, Mapping) else (opts.model_dump() if hasattr(opts, "model_dump") else {})
    node_ids = o.get("node_ids")
    downstream, force = bool(o.get("downstream")), bool(o.get("force"))
    _recover_once()
    with _CALL_LOCK:
        board = db.get(StudioBoard, board_id)
        if board is None:
            raise BoardNotFound(board_id)
        nodes = doc_nodes(board.doc_json)
        from app.production.canvas_controls import stage_inputs, MESSAGE
        candidates = node_ids if node_ids is not None else [n for n in nodes if recipe_of(nodes[n])]
        if any(stage_inputs(board.doc_json, n) for n in candidates):
            raise ExecError("stage_control_not_supported: " + MESSAGE)
        done, _status, _rows = _latest(db, board_id)
        targets = select_targets(nodes, done, node_ids=list(node_ids) if node_ids is not None else None,
                                 downstream=downstream, force=force)
        with _LOCK:
            ex = _EXECS.get(board_id)
            active = ex is not None and ex.status in ACTIVE_EXEC
            queued = list(ex.queue) if active and ex else []
            running = ex.running if active and ex else None
            running_hash = ex.running_hash if active and ex else None
        hashes = {n: node_recipe_hash(nodes[n], nodes) for n in targets}
        new = [n for n in targets if n not in queued and not (n == running and hashes[n] == running_hash)]
        if not new:
            return exec_state(board_id) if active else idle_state(board_id)
        graph = recipe_graph(nodes)
        titles = {n: title_of(nodes[n]) for n in nodes}
        rank = {n: i for i, n in enumerate(nodes)}
        order = topo_order([*queued, *new], graph, rank, titles)
        run_ids: dict[str, str] = {}
        for n in new:
            rec = recipe_of(nodes[n]) or {}
            row = StudioNodeRun(id=new_id("nrun"), board_id=board_id, node_id=n, op=str(rec.get("op")),
                                status="queued", recipe_hash=hashes[n], recipe_json=rec, task_ids=[],
                                extra_json=[], step="排队中")
            db.add(row)
            run_ids[n] = row.id
        db.commit()
        with _LOCK:
            ex = _EXECS.get(board_id)
            if ex is None or ex.status not in ACTIVE_EXEC:
                _EXECS.pop(board_id, None)            # 重新排到队尾：画布之间先来先跑
                ex = _Exec(board_id=board_id)
                _EXECS[board_id] = ex
                _prune()
            keep = set(ex.queue) | set(new)
            ex.queue = [n for n in order if n in keep and n != ex.running]
            ex.runs.update(run_ids)
            ex.total += len(new)
            ex.stop = False
            ex.status = "running" if ex.running else "queued"
            ex.deps.update({n: list(graph.get(n, ())) for n in new})
            ex.titles.update(titles)
            out = state_of(ex)
    _kick()
    return out


def _prune() -> None:
    if len(_EXECS) <= _KEEP_FINISHED:
        return
    for bid in [b for b, e in _EXECS.items() if e.status not in ACTIVE_EXEC][: len(_EXECS) - _KEEP_FINISHED]:
        _EXECS.pop(bid, None)


def stop(db: Session, board_id: str) -> dict[str, Any]:
    """停止：排队的标 cancelled；在跑的那个跑完就停（网关任务取消不了就让它跑完，结果照样记上）。"""
    _recover_once()
    with _CALL_LOCK:
        if db.get(StudioBoard, board_id) is None:
            raise BoardNotFound(board_id)
        with _LOCK:
            ex = _EXECS.get(board_id)
            dropped = []
            if ex is not None and ex.status in ACTIVE_EXEC:
                dropped = [ex.runs[n] for n in ex.queue if n in ex.runs]
                ex.queue = []
                ex.stop = True
                if ex.running is None:
                    ex.status = "cancelled"
        # 内存里没有的（别的路径漏下的）排队行也一起收掉；在跑的不动
        rows = db.execute(select(StudioNodeRun).where(StudioNodeRun.board_id == board_id,
                                                      StudioNodeRun.status.in_(("queued", "waiting")))).scalars()
        for r in rows:
            if r.id in dropped or ex is None or r.id not in ex.runs.values() or r.node_id != ex.running:
                r.status, r.step, r.error, r.finished_at = "cancelled", "已停止", "已停止", utcnow()
        db.commit()
        return exec_state(board_id) or idle_state(board_id)


def _stopping(board_id: str) -> bool:
    with _LOCK:
        ex = _EXECS.get(board_id)
        return bool(ex and ex.stop)


def run_out(r: StudioNodeRun) -> dict[str, Any]:
    """前端 NodeRun。"""
    return {
        "id": r.id, "node_id": r.node_id, "status": r.status, "op": r.op,
        "progress": r.progress, "step": r.step, "error": r.error,
        "media": dict(r.media_json) if r.media_json else None,
        "extra": list(r.extra_json or []), "recipe_hash": r.recipe_hash,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def overlay_waiting(out: list[dict[str, Any]], st: dict[str, Any] | None, deps: Mapping[str, Sequence[str]],
                    titles: Mapping[str, str], behind: bool = False) -> list[dict[str, Any]]:
    """排队的节点给人看「等上游：分镜 1」（status=waiting）或「排队中」。只改输出，不写库。"""
    if not st or st.get("status") not in ACTIVE_EXEC:
        return out
    pending = set(st.get("queued") or []) | ({st["running"]} if st.get("running") else set())
    for r in out:
        if r["status"] != "queued" or r["node_id"] not in pending:
            continue
        up = [d for d in deps.get(r["node_id"], ()) if d in pending]
        if up:
            r["status"], r["step"] = "waiting", f"等上游：{titles.get(up[0]) or up[0]}"
        elif behind:
            r["step"] = "排在别的画布后面"
    return out


def node_runs(db: Session, board_id: str) -> dict[str, Any]:
    """每个节点最近一次 run + 执行器状态（前端轮询用）。"""
    _recover_once()
    if db.get(StudioBoard, board_id) is None:
        raise BoardNotFound(board_id)
    _done, _status, latest = _latest(db, board_id)
    out = [run_out(r) for r in latest.values()]
    with _LOCK:
        ex = _EXECS.get(board_id)
        st = state_of(ex) if ex else None
        deps = dict(ex.deps) if ex else {}
        titles = dict(ex.titles) if ex else {}
        first = next((b for b, e in _EXECS.items() if e.status in ACTIVE_EXEC), None)
    return {"runs": overlay_waiting(out, st, deps, titles, behind=bool(first and first != board_id)), "exec": st}


# ── 后台线程 ──────────────────────────────────────────────────────────

def _take() -> tuple[str, str, str] | None:
    """下一个要跑的 (画布, 节点, run)：最早排进来的那张画布的队首。"""
    with _LOCK:
        for ex in _EXECS.values():
            if ex.status not in ACTIVE_EXEC or ex.running:
                continue
            while ex.queue and ex.queue[0] not in ex.runs:
                ex.queue.pop(0)
            if not ex.queue:
                _settle(ex)
                continue
            node = ex.queue.pop(0)
            ex.running, ex.running_hash, ex.status = node, None, "running"
            return ex.board_id, node, ex.runs[node]
    return None


def _settle(ex: _Exec) -> None:
    if ex.running is None and not ex.queue and ex.status in ACTIVE_EXEC:
        ex.status = "cancelled" if ex.stop else ("failed" if ex.failed else "succeeded")


def _finish(board_id: str, node_id: str, outcome: str, error: str | None) -> None:
    with _LOCK:
        ex = _EXECS.get(board_id)
        if ex is None:
            return
        if ex.running == node_id:
            ex.running = ex.running_hash = None
        ex.done += 1
        if outcome in ("failed", "skipped"):
            ex.failed += 1
            if outcome == "failed" and ex.error is None and error:
                ex.error = f"「{ex.titles.get(node_id) or node_id}」{error}"[:500]
        _settle(ex)


def _loop() -> None:
    _recover_once()
    while True:
        job = _take()
        if job is None:
            # 闲着就睡；execute() 排了新活会 _kick() 叫醒
            _WAKE.wait(30)
            _WAKE.clear()
            continue
        board_id, node_id, run_id = job
        outcome, error = "failed", None
        try:
            outcome, error = _run_node(board_id, node_id, run_id)
        except Exception as exc:                      # noqa: BLE001 —— 一个节点出错不能让工作线程死掉
            log.exception("画布执行器：节点 %s/%s 出错", board_id, node_id)
            error = str(exc)[:300]
        _finish(board_id, node_id, outcome, error)


def _kick() -> None:
    global _WORKER
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_loop, daemon=True, name="canvas-exec")
            _WORKER.start()
    _WAKE.set()


# ── 执行一个节点 ──────────────────────────────────────────────────────

class _Ctx:
    """跑一个节点时的上下文：库、画布文档、这次的 run 行、各节点的现有结果。"""

    def __init__(self, db: Session, board: StudioBoard, nodes: dict[str, dict[str, Any]], node_id: str,
                 run: StudioNodeRun) -> None:
        self.db = db
        self.board = board
        self.board_id = board.id
        self.nodes = nodes
        self.node_id = node_id
        self.run_id = run.id
        self.notes: list[str] = []
        self.done, self.status, _ = _latest(db, board.id)

    @property
    def run(self) -> StudioNodeRun:
        r = self.db.get(StudioNodeRun, self.run_id)
        if r is None:
            raise Cancelled("运行记录不见了（画布删了？）")
        return r

    def progress(self, pct: int | float | None, step: str | None) -> None:
        r = self.run
        r.progress = None if pct is None else max(0, min(100, int(pct)))
        if step:
            r.step = str(step)[:200]
        self.db.commit()

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def stopping(self) -> bool:
        return _stopping(self.board_id)

    def asset_url(self, asset_id: str) -> str | None:
        a = self.db.get(Asset, asset_id)
        return same_origin(a.url) if a is not None and a.url else None

    def resource_media(self, ref: Mapping[str, Any]) -> dict[str, Any] | None:
        from pydantic import ValidationError
        from app.production import service as production
        from app.production.schema import ResourceRef
        try:
            parsed = ResourceRef.model_validate(ref)
            if not parsed.revision:
                raise ExecError("资源引用缺少 revision，请从素材库重新选择")
            context, _issues = production.context_for(self.db, self.board)
            resolved = production.resolve_one(self.db, self.board, context, parsed)
            resource = resolved["resource"]
            if parsed.kind in {"stage", "coverage"}:
                raise ExecError("stage_control_not_supported: 当前媒体生成器尚未消费共享舞台控制，请先导出镜头预演控制，不能把舞台当参考图忽略")
            return resource.get("media")
        except (production.ProductionError, ValidationError) as exc:
            code = getattr(exc, "code", "reference_invalid")
            raise ExecError(f"{code}: {exc}") from exc

    def refs(self, recipe: Mapping[str, Any]) -> list[Media]:
        """配方的参考 → 媒体，按 refs 顺序；文字节点不出媒体。"""
        from app.pipelines.base import as_items
        out: list[Media] = []
        for r in as_items(recipe, "refs"):
            if not isinstance(r.get("node"), str):
                continue
            out += resolve_node(self.nodes, self.done, self.status, r["node"],
                                role=str(r.get("role") or "reference"), panel=r.get("panel") or None,
                                self_id=self.node_id, asset_url=self.asset_url, resource_media=self.resource_media)
        return out

    def texts(self) -> dict[str, str]:
        return {nid: str(data_of(n).get("text") or "")[:800] for nid, n in self.nodes.items()
                if n.get("type") == "text" and data_of(n).get("text")}


def _run_node(board_id: str, node_id: str, run_id: str) -> tuple[str, str | None]:
    """跑一个节点，返回 (结局, 失败原因)。结局 = succeeded / failed / skipped / cancelled。"""
    with SessionLocal() as db:
        run = db.get(StudioNodeRun, run_id)
        if run is None:
            return "cancelled", None
        if run.status not in ("queued", "waiting"):
            return run.status, run.error
        board = db.get(StudioBoard, board_id)
        nodes = doc_nodes(board.doc_json if board is not None else None)
        node = nodes.get(node_id)
        recipe = recipe_of(node)
        if node is None or recipe is None:
            run.status = "cancelled" if node is None else "skipped"
            run.error = "节点已经从画布上删掉了" if node is None else "节点没有配方了"
            run.finished_at = utcnow()
            db.commit()
            return run.status, run.error
        assert board is not None
        run.status, run.started_at, run.progress, run.step = "running", utcnow(), None, "准备"
        run.recipe_json, run.recipe_hash, run.op = recipe, node_recipe_hash(node, nodes), str(recipe.get("op"))
        db.commit()
        with _LOCK:
            ex = _EXECS.get(board_id)
            if ex is not None and ex.running == node_id:
                ex.running_hash = run.recipe_hash
        ctx = _Ctx(db, board, nodes, node_id, run)
        try:
            from app.production.canvas_controls import stage_inputs, MESSAGE
            if stage_inputs(board.doc_json, node_id):
                raise ExecError("stage_control_not_supported: " + MESSAGE)
            media, extra = _dispatch(ctx, recipe)
            run = ctx.run
            run.status, run.media_json, run.extra_json = "succeeded", media, extra
            run.progress, run.error = 100, None
            run.step = ("完成；" + "；".join(ctx.notes))[:200] if ctx.notes else "完成"
        except Skip as exc:
            db.rollback()
            run = ctx.run
            run.status, run.error, run.step = "skipped", str(exc)[:500], "跳过"
        except Cancelled as exc:
            db.rollback()
            run = ctx.run
            run.status, run.error, run.step = "cancelled", str(exc)[:500], "已停止"
        except Exception as exc:                      # noqa: BLE001 —— 失败原因写进 run 给人看
            db.rollback()
            if not isinstance(exc, (ExecError, CapabilityError)):
                log.exception("画布执行器：节点 %s 失败", node_id)
            run = ctx.run
            msg = exc.message if isinstance(exc, CapabilityError) else str(exc)
            run.status, run.error, run.step = "failed", (msg or type(exc).__name__)[:500], "失败"
        run.finished_at = utcnow()
        db.commit()
        return run.status, run.error


def _dispatch(ctx: _Ctx, recipe: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    op = recipe.get("op")
    if op == "image":
        return _op_image(ctx, recipe)
    if op == "video":
        return _op_video(ctx, recipe)
    if op == "sheet":
        return _op_sheet(ctx, recipe)
    if op == "last_frame":
        return _op_last_frame(ctx, recipe)
    if op == "concat":
        return _op_concat(ctx, recipe)
    if op == "one_take":
        return _op_one_take(ctx, recipe)
    raise ExecError(f"认不出的配方动作 {op}")


# ── 能力调用 ──────────────────────────────────────────────────────────

def gateway_url(url: str) -> str:
    """同源 /media/x → 网关取得到的绝对地址（网关在另一个进程，要 public_base_url 打头）；data: 原样。

    只认本库媒体：外部地址不转，否则等于让画布指挥网关去下载任意 URL（同 generic.resolve_refs）。
    """
    from app.capability.generic import DATA_URL_MAX, local_media_url
    from app.config import get_settings

    if url.startswith("data:"):
        if len(url) > DATA_URL_MAX:
            raise ExecError("data: 参考太大，先上传成 /media 地址")
        return url
    local = local_media_url(url)
    if not local:
        raise ExecError(f"参考不在本库媒体里（只认 /media/… 或 data:）：{url[:80]}")
    return get_settings().public_base_url.rstrip("/") + local


def _routes(db: Session) -> list[CapabilityRoute]:
    return list(db.execute(select(CapabilityRoute).where(CapabilityRoute.enabled.is_(True))).scalars())


def _find_model(db: Session, caps: Sequence[str], model: str, endpoint_id: str | None) -> tuple[str, Any, Any] | None:
    """按模型名找 (能力, 路由, 模型信息)（照 keyframe._route 的写法：在启用的端点能力目录里找）。"""
    from app.capability.generic import blocked_reason, catalog_models, route_for

    if endpoint_id:
        ep = db.get(CapabilityEndpoint, endpoint_id)
        endpoints = [ep] if ep is not None and ep.enabled else []
    else:
        endpoints = list(db.execute(select(CapabilityEndpoint).where(CapabilityEndpoint.enabled.is_(True))
                                    .order_by(CapabilityEndpoint.name)).scalars())
    for cap in caps:
        for ep in endpoints:
            for info in catalog_models(ep, (cap,)):
                if info.model != model:
                    continue
                route, routed = route_for(info, ep, _routes(db))
                # 本机免费模型不过付费闸（generic.local_free）；别的照旧拦
                why = blocked_reason(db, route, routed)
                if why:
                    raise ExecError(f"「{info.label}」不能用：{why}")
                if not info.ready:
                    raise ExecError(f"「{info.label}」在能力网关上还没就绪（缺权重或没装）")
                return cap, route, info
    return None


def _need_model(db: Session, caps: Sequence[str], model: str, endpoint_id: str | None) -> tuple[str, Any, Any]:
    hit = _find_model(db, caps, model, endpoint_id)
    if hit is None:
        raise ExecError(f"没有找到模型 {model}（本机能力网关没开，或后台没接这个模型）")
    return hit


def _submit(ctx: _Ctx, cap: str, route: Any, payload: dict[str, Any]) -> str:
    from app.capability.generic import canvas_ref_id
    from app.capability.service import submit_task

    # force：执行器只在要出新结果时才交，不该被幂等键挡回上一次的任务（同 keyframe / quick_film）
    task = submit_task(ctx.db, Capability(cap), payload, purpose=PURPOSE, ref_kind=REF_KIND,
                       ref_id=canvas_ref_id(f"{ctx.board_id}:{ctx.node_id}"),
                       novel_id=ctx.board.novel_id, chapter_id=ctx.board.chapter_id, route=route, force=True)
    ctx.db.commit()
    run = ctx.run
    run.task_ids = [*(run.task_ids or []), task.id]
    ctx.db.commit()
    return task.id


_TERMINAL = (TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled)


def _wait(ctx: _Ctx, task_ids: Sequence[str], timeout_s: int, what: str) -> None:
    """等一批任务都结束（主动问网关，回调丢了也推得动；抄 quick_film._wait 的思路）。进度按完成条数写进 run。"""
    from app.capability.service import poll_task

    started = time.time()
    left = list(task_ids)
    n = len(task_ids)
    while left:
        for tid in list(left):
            ctx.db.expire_all()
            t = ctx.db.get(GenTask, tid)
            if t is not None and t.status not in _TERMINAL:
                try:
                    t = poll_task(ctx.db, t)
                    ctx.db.commit()
                except Exception:                     # noqa: BLE001 —— 网关一时连不上：下一轮再问
                    ctx.db.rollback()
            if t is None or t.status in _TERMINAL:
                left.remove(tid)
        if not left:
            break
        waited = int(time.time() - started)
        if waited > timeout_s:
            raise ExecError(f"{what}超过 {timeout_s // 60} 分钟没出完")
        finished = n - len(left)
        if n > 1:
            ctx.progress(finished * 100 // n, f"{what} {finished}/{n} · 已 {waited} 秒")
        else:
            ctx.progress(None, f"{what}中 · 已 {waited} 秒")
        time.sleep(POLL_S)


def _collect(ctx: _Ctx, task_ids: Sequence[str], meta: Mapping[str, Any]) -> list[dict[str, Any]]:
    """任务产物 → MediaRef（同源 /media 地址，用 generic.task_state 那套拿本地化后的地址）。全失败抛 ExecError。"""
    from app.capability.generic import task_state

    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for tid in task_ids:
        st = task_state(ctx.db, tid)
        tries = 0
        while st and st["status"] == "failed" and "还没取回本库" in str(st.get("error") or "") \
                and tries < RELOCALIZE_TRIES:
            # 网关临时地址还没取回本库：task_state 每 30 秒最多重取一次
            ctx.db.commit()
            time.sleep(31)
            st = task_state(ctx.db, tid)
            tries += 1
        ctx.db.commit()
        if st and st["status"] == "succeeded" and st.get("assets"):
            a = st["assets"][0]
            out.append({"url": same_origin(a["url"]), "asset_id": a.get("asset_id"), "mime": a.get("mime"), **meta})
        else:
            errors.append(str((st or {}).get("error") or "任务失败"))
    if not out:
        raise ExecError(errors[0] if errors else "没有产物")
    if errors:
        ctx.note(f"{len(task_ids)} 条里 {len(errors)} 条没出成：{errors[0][:60]}")
    return out


def _split(outs: list[dict[str, Any]], unit: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """第一个填进本节点，其余在旁边长兄弟节点（前端按 extra 长）。"""
    return outs[0], [{"label": f"第 {i + 2} {unit}", "media": m} for i, m in enumerate(outs[1:])]


def _seeds(recipe: Mapping[str, Any]) -> list[int]:
    n = max(1, min(MAX_COUNT, _int(recipe.get("count")) or 1))
    # 不给 seed 就随机起一个：重新生成就是要一张新的，同 seed 会命中上一张
    base = _int(recipe.get("seed"))
    base = base if base is not None else random.randint(0, 2**31 - 1 - MAX_COUNT)
    return [base + i for i in range(n)]


def _image_size(recipe: Mapping[str, Any], info: Any, default: tuple[int, int]) -> tuple[int, int]:
    from app.capability.generic import clamp_size

    sizes = list(getattr(info, "sizes", None) or [])
    w, h = _int(recipe.get("width")), _int(recipe.get("height"))
    if w and h:
        return fit_size(w, h, sizes)
    if recipe.get("aspect_ratio") or recipe.get("resolution"):
        cw, ch, _warn = clamp_size(str(recipe.get("aspect_ratio") or "16:9"), str(recipe.get("resolution") or "480p"),
                                   sizes or None, getattr(info, "size_multiple", None))
        return cw, ch
    return fit_size(default[0], default[1], sizes)


def _cap_refs(items: list[Media], limit: int) -> tuple[list[Media], list[Media]]:
    """参考超过模型上限：身份参考优先留（多出来的往往是风格图，丢它比丢脸代价小）。"""
    if len(items) <= limit:
        return items, []
    ranked = sorted(items, key=lambda m: m.role not in IDENTITY_ROLES)
    keep = set(id(m) for m in ranked[:max(limit, 0)])
    return [m for m in items if id(m) in keep], [m for m in items if id(m) not in keep]


def _op_image(ctx: _Ctx, recipe: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    refs = ctx.refs(recipe)
    images = [m for m in refs if m.kind == "image"]
    if len(images) < len(refs):
        ctx.note("出图用不上视频参考，已跳过")
    base = next((m for m in images if m.role in BASE_ROLES), None)
    model = str(recipe.get("model") or "")
    endpoint_id = recipe.get("endpoint_id") or None
    if not model:
        cap, route, info = _need_model(ctx.db, [I2I if base else T2I], EDIT_MODEL if base else T2I_MODEL, endpoint_id)
    else:
        hit = _find_model(ctx.db, [I2I, T2I] if base else [T2I, I2I], model, endpoint_id)
        if hit is None:
            raise ExecError(f"没有找到图片模型 {model}（本机能力网关没开，或后台没接这个模型）")
        cap, route, info = hit
        if cap == I2I and base is None:
            raise ExecError(f"「{info.label}」是图像编辑模型，要一张底图：把一张参考的角色设为「底图」")
        if cap == T2I and base is not None:
            ctx.note(f"「{info.label}」只会文生图，底图没用上")
            base = None

    seen = {base.url} if base else set()
    rest: list[Media] = []
    for m in images:
        if m is base or m.url in seen:
            continue                                   # 网关会跳过和底图相同的那张，序号就对不上了
        seen.add(m.url)
        rest.append(m.__class__(**{**m.__dict__, "role": "reference" if m.role in BASE_ROLES else m.role}))
    limit = info.max_ref_images if info.max_ref_images is not None else (MAX_EDIT_REFS if cap == I2I else 0)
    if cap == I2I:
        limit = max(0, min(limit, MAX_EDIT_REFS) - 1)  # 底图也占一个名额
    rest, dropped = _cap_refs(rest, limit)
    if dropped:
        ctx.note(f"「{info.label}」参考图最多 {limit + (1 if base else 0)} 张，"
                 f"{'、'.join(m.label for m in dropped)} 没用上")

    ordered = ([base] if base else []) + rest
    index: dict[str, list[int]] = {}
    for i, m in enumerate(ordered):
        index.setdefault(m.node, []).append(i + 1)
    text = prompt_text(recipe.get("prompt"), index, ctx.texts())
    if not text:
        raise ExecError("提示词是空的：在生成面板写一句要画什么")
    w, h = _image_size(recipe, info, IMAGE_SIZE)
    prompt = f"{text}\n\nOne single image, no text, no captions, no watermark."
    payloads = []
    for seed in _seeds(recipe):
        p: dict[str, Any] = {"prompt": prompt, "width": w, "height": h, "style": "photoreal", "params": {"seed": seed}}
        if cap == I2I and base is not None:
            # 网关（klein 编辑）只收 identity=true 的参考图：服装、道具参考也得标上才送得进去（quick_film._ref 的坑）
            p.update(image=_src(gateway_url(base.url)), strength=0.9,
                     reference_images=[{"ref": _src(gateway_url(m.url)), "role": CORE_ROLE.get(m.role, "scene"),
                                        "identity": True, "tag": f"image {i + 2}"} for i, m in enumerate(rest)])
        elif rest:
            p["reference_images"] = [{"ref": _src(gateway_url(m.url)), "role": CORE_ROLE.get(m.role, "scene"),
                                      "identity": m.role in IDENTITY_ROLES} for m in rest]
        payloads.append(p)
    ctx.progress(None, "交给本机出图" if info.local else f"交给 {info.label} 出图")
    tids = [_submit(ctx, cap, route, p) for p in payloads]
    _wait(ctx, tids, IMAGE_TIMEOUT_S, "出图")
    return _split(_collect(ctx, tids, {"w": w, "h": h}), "张")


def _op_video(ctx: _Ctx, recipe: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    refs = ctx.refs(recipe)
    images = [m for m in refs if m.kind == "image"]
    first = next((m for m in images if m.role == "first_frame"), None) or \
        next((m for m in images if m.role == "base"), None)
    last = next((m for m in images if m.role == "last_frame" and m is not first), None)
    if any(m is not first and m is not last for m in refs):
        # LTX 2.5 不读一般参考图；人像靠首帧钉住（纳逗也是先出分镜图再动起来）
        ctx.note("视频模型只用首帧/尾帧，其余参考没用上")
    model = str(recipe.get("model") or VIDEO_MODEL)
    cap, route, info = _need_model(ctx.db, [I2V], model, recipe.get("endpoint_id") or None)
    if first is None and not (info.supports or {}).get("text_to_video"):
        raise ExecError(f"「{info.label}」必须有首帧：把一张图连进来，角色设为「首帧」")
    w, h = _int(recipe.get("width")), _int(recipe.get("height"))
    if not (w and h):
        if recipe.get("aspect_ratio") or recipe.get("resolution"):
            w, h = _image_size(recipe, info, VIDEO_SIZE)
        else:
            w, h = VIDEO_SIZE
    duration = clamp_ms(recipe.get("duration_ms"), info.max_duration_ms)
    text = prompt_text(recipe.get("prompt"), {}, ctx.texts())
    if not text and first is None:
        raise ExecError("提示词是空的：写一句画面里发生什么")
    payloads = []
    for seed in _seeds(recipe):
        p: dict[str, Any] = {"prompt": video_prompt(text, recipe.get("audio")), "width": w, "height": h,
                             "fps": FPS, "quality": "final", "duration_ms": duration,
                             "audio": {"mode": "generate"}, "params": {"seed": seed}}
        if first is not None:
            p["first_frame"] = _src(gateway_url(first.url))
        if last is not None:
            p["last_frame"] = _src(gateway_url(last.url))
        payloads.append(p)
    ctx.progress(None, "交给本机出视频" if info.local else f"交给 {info.label} 出视频")
    tids = [_submit(ctx, cap, route, p) for p in payloads]
    _wait(ctx, tids, VIDEO_TIMEOUT_S, "出视频")
    return _split(_collect(ctx, tids, {"w": w, "h": h, "duration": duration / 1000, "mime": "video/mp4"}), "条")


def _op_sheet(ctx: _Ctx, recipe: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from app.pipelines import char_sheet

    images = [m for m in ctx.refs(recipe) if m.kind == "image"]
    person = next((m for m in images if m.role in BASE_ROLES), None) or (images[0] if images else None)
    if person is None:
        raise ExecError("定妆照要一张人物照片：把人物照片连进来（角色选「底图」）")
    sheet = recipe.get("sheet") if isinstance(recipe.get("sheet"), dict) else {}
    preset = sheet.get("preset") if sheet.get("preset") in ("standard", "quick") else "standard"
    ctx.progress(0, "定妆照：准备")
    try:
        res = char_sheet.generate_sheet(ctx.db, person_url=gateway_url(person.url), name=str(sheet.get("name") or ""),
                                        look=str(sheet.get("look") or ""), preset=preset,
                                        on_progress=lambda pct, step: ctx.progress(pct, step),
                                        cancelled=ctx.stopping)
    except char_sheet.SheetError as exc:
        if ctx.stopping():
            raise Cancelled("已停止（定妆照没出完）") from exc
        raise ExecError(str(exc)) from exc
    main = res.get("sheet") or {}
    if not main.get("url"):
        raise ExecError("定妆照拼版没出来")
    media = {"url": same_origin(main["url"]), "asset_id": main.get("asset_id"), "mime": "image/png"}
    extra = [{"label": str(p.get("key")), "media": {"url": same_origin(p["url"]), "asset_id": p.get("asset_id"),
                                                    "mime": "image/png"}}
             for p in res.get("panels") or [] if isinstance(p, dict) and p.get("url") and p.get("key")]
    return media, extra


# ── ffmpeg：尾帧、拼接 ──────────────────────────────────────────────────

def _local_path(url: str) -> Path:
    from app.capability.generic import media_name
    from app.capability.mediastore import media_root

    name = media_name(url)
    p = media_root() / name if name else None
    if p is None or not p.is_file():
        raise ExecError("视频不在本库媒体目录里，ffmpeg 取不到")
    return p


def _ffmpeg(args: Sequence[str], timeout: int) -> None:
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=timeout,
                       capture_output=True)
    except FileNotFoundError as exc:
        raise ExecError("本机没装 ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise ExecError(f"ffmpeg 失败：{(err[-1] if err else exc)}"[:300]) from exc
    except subprocess.TimeoutExpired as exc:
        raise ExecError("ffmpeg 超时") from exc


def _has_audio(path: Path) -> bool:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                              "-of", "csv=p=0", str(path)], capture_output=True, timeout=30, text=True)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(out.stdout.strip())


def _duration_s(path: Path) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(path)], capture_output=True, timeout=30, text=True)
        return round(float(out.stdout.strip()), 3)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _store(ctx: _Ctx, raw: bytes, mime: str, kind: AssetKind, meta: dict[str, Any]) -> tuple[str, str]:
    """字节存进本库媒体 + 建 Asset（同内容复用，同 canvas.upload）。返回 (asset_id, 同源地址)。"""
    from app.capability.mediastore import store_bytes

    item = store_bytes(raw, mime=mime)
    asset = ctx.db.execute(select(Asset).where(Asset.sha256 == item["sha256"])).scalars().first()
    if asset is None:
        asset = Asset(id=new_id("as"), kind=kind, url=str(item["url"]), sha256=str(item["sha256"]),
                      mime=str(item["mime"]), bytes=int(str(item["bytes"])), source=AssetSource.generated,
                      novel_id=ctx.board.novel_id,
                      meta_json={"canvas_exec": {"board": ctx.board_id, "node": ctx.node_id, **meta}})
        ctx.db.add(asset)
    ctx.db.commit()
    return asset.id, same_origin(asset.url)


def _op_last_frame(ctx: _Ctx, recipe: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    video = next((m for m in ctx.refs(recipe) if m.kind == "video"), None)
    if video is None:
        raise ExecError("取尾帧要连一条视频进来")
    src = _local_path(video.url)
    ctx.progress(None, "取尾帧")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "last.png"
        _ffmpeg(["-sseof", "-0.1", "-i", str(src), "-frames:v", "1", str(out)], 60)
        if not out.exists() or out.stat().st_size == 0:
            # 片子太短或末尾 0.1 秒里没有完整帧：往前多解一点，留最后一帧（quick_film 的兜底写法）
            _ffmpeg(["-sseof", "-1", "-i", str(src), "-update", "1", "-q:v", "2", str(out)], 60)
        if not out.exists() or out.stat().st_size == 0:
            raise ExecError("取不到尾帧")
        raw = out.read_bytes()
    w = h = None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            w, h = im.size
    except Exception:                                 # noqa: BLE001 —— 量不出尺寸不影响用
        pass
    asset_id, url = _store(ctx, raw, "image/png", AssetKind.image, {"op": "last_frame", "from": video.url})
    return {"url": url, "asset_id": asset_id, "mime": "image/png", "w": w, "h": h}, []


def _op_concat(ctx: _Ctx, recipe: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    videos = [m for m in ctx.refs(recipe) if m.kind == "video"]
    if not videos:
        raise ExecError("拼接要连视频进来（按参考的先后顺序拼）")
    paths = [_local_path(m.url) for m in videos]
    w, h = VIDEO_SIZE
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={FPS}"
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
    with tempfile.TemporaryDirectory() as d:
        parts = []
        for i, p in enumerate(paths):
            ctx.progress(i * 90 // len(paths), f"统一格式 {i + 1}/{len(paths)}")
            out = Path(d) / f"part{i}.mp4"
            # 先统一 768×448 / 24fps / aac：几条片子编码参数不一样，直接接会花屏或丢声；没声音的补一条静音
            if _has_audio(p):
                _ffmpeg(["-i", str(p), "-vf", vf, "-map", "0:v:0", "-map", "0:a:0", *enc, str(out)], 600)
            else:
                _ffmpeg(["-i", str(p), "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                         "-vf", vf, "-map", "0:v:0", "-map", "1:a:0", "-shortest", *enc, str(out)], 600)
            parts.append(out)
        ctx.progress(92, "拼接")
        listing = Path(d) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        film = Path(d) / "film.mp4"
        try:
            _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart",
                     str(film)], 600)
        except ExecError:
            _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), *enc, str(film)], 900)
        dur = _duration_s(film)
        raw = film.read_bytes()
    asset_id, url = _store(ctx, raw, "video/mp4", AssetKind.video, {"op": "concat", "parts": [m.url for m in videos]})
    return {"url": url, "asset_id": asset_id, "mime": "video/mp4", "w": w, "h": h, "duration": dur}, []


def _op_one_take(ctx: _Ctx, recipe: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    segs = [s for s in recipe.get("segments") or [] if isinstance(s, dict) and isinstance(s.get("node"), str)]
    if not segs:
        # 没写 segments：按 refs 里的首帧图平均分，每段 3 秒
        segs = [{"node": r["node"], "at_ms": 3000 * i, "motion": ""}
                for i, r in enumerate(m for m in recipe.get("refs") or []
                                      if isinstance(m, dict) and m.get("role") in (*BASE_ROLES, "reference"))]
    if not segs:
        raise ExecError("一次成片要至少一张分镜图（segments 或首帧参考）")
    segs = sorted(segs, key=lambda s: _int(s.get("at_ms")) or 0)
    frames: list[str] = []
    for s in segs:
        got = [m for m in resolve_node(ctx.nodes, ctx.done, ctx.status, s["node"], role="first_frame",
                                       self_id=ctx.node_id, asset_url=ctx.asset_url) if m.kind == "image"]
        if not got:
            raise ExecError(f"「{title_of(ctx.nodes.get(s['node']))}」没有图，钉不进一次成片")
        frames.append(gateway_url(got[0].url))
    model = str(recipe.get("model") or VIDEO_MODEL)
    cap, route, info = _need_model(ctx.db, [I2V], model, recipe.get("endpoint_id") or None)
    spans = take_spans([_int(s.get("at_ms")) or 0 for s in segs], _int(recipe.get("duration_ms")),
                       min(MAX_TAKE_MS, info.max_duration_ms or MAX_TAKE_MS))
    motions = [str(s.get("motion") or "") for s in segs]
    w, h = _int(recipe.get("width")) or VIDEO_SIZE[0], _int(recipe.get("height")) or VIDEO_SIZE[1]
    text = prompt_text(recipe.get("prompt"), {}, ctx.texts())
    payload = one_take_payload(frames, motions, spans, text, str(recipe.get("audio") or ""), (w, h),
                               _seeds({"seed": recipe.get("seed")})[0])
    ctx.progress(None, "交给本机一次成片" if info.local else f"交给 {info.label} 一次成片")
    tid = _submit(ctx, cap, route, payload)
    _wait(ctx, [tid], VIDEO_TIMEOUT_S, "一次成片")
    outs = _collect(ctx, [tid], {"w": w, "h": h, "duration": spans[-1][1] / 1000, "mime": "video/mp4"})
    return outs[0], []
