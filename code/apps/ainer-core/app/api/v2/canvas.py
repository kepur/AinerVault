"""创作画布（ainer-studio ?view=flow）的后端。

- 一章多张画布：整章总览（一份分镜一张）+ 按场次自动分的（长场次切段）+ 自建的（任意镜头 / 空白画布）。
  /chapters/{id}/canvases 第一次打开时自动分；/shots/{id}/canvas 给分镜画布「进入创作画布」用。
- 画布文档读写：按画布 id，乐观锁（base_version 对不上 → 409）。
  文档只存布局与引用 —— 派生节点的内容（场次、镜头、定妆照、白模）每次现取，
  这里在写入时把派生节点 data 里多出来的字段剥掉，防止有人把 board/cast 复制进来。
- 换计划搬画布（:adopt）：分镜重编译后 Shot 都是新行（HANDOVER §4.44），
  旧画布上的镜头引用全部失效；按场次与场内次序把旧布局搬到新计划上。
- 按计划取剧本：/chapters/{id}/script 只认激活剧本，画布看的可能是旧版本计划。
- 3D-BOX 轻量信息：画布上几十个白模节点只要海报和机位，doc 按需带。
- 上传：画布「上传」按钮，落成 Asset(source=uploaded)，返回同源 /media 地址。
"""
from __future__ import annotations

import json
import math
import mimetypes
import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal, NamedTuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v2 import script as script_api
from app.capability.mediastore import sniff, store_bytes
from app.db import get_db
from app.ids import new_id
from app.models import (
    Asset, AssetKind, AssetSource, Chapter, Scene, SceneProject, ScriptDoc, Shot, ShotPerformance, ShotPlan,
    StudioBoard, VoiceCasting, WorldTransform,
)
from app.pipelines import canvas_exec
from app.pipelines.base import as_items
from app.scene3d import agent
from app.worldview.voice import VoiceSpec

router = APIRouter(prefix="/api/v2/studio", tags=["studio-canvas"])

DOC_SCHEMA = "ainer.board/v1"
MAX_NODES = 5000
MAX_EDGES = 20000
MAX_DOC_BYTES = 4 * 1024 * 1024
#: data: 地址只给演示产物、小缩略图用；大图必须走上传落成 /media，否则文档几次就撑到上限
MAX_DATA_URL_BYTES = 512 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

#: 内容每次从后端现取的引用（场次、镜头、角色视角图、3D-BOX 项目）。
#: director_output 虽然也是派生的，但画布没有按 job+kind 现取产物的接口，前端靠 data.media 显示，
#: 所以不在这里；asset / free 的内容本来就在文档里
LIVE_REF_KINDS = frozenset({"story", "scene", "shot", "entity_view", "box_project"})
#: 现取节点 data 里只许留的视图状态（见前端 model.ts 的 CNodeData）。
#: 其余都是能现取的内容，存了就成了第二份数据源，后端一改画布就显示旧的
DERIVED_DATA_KEYS = frozenset({"ref", "title", "role", "camera", "pinned", "live"})
#: 运行时算出的状态，任何节点都不进库
RUNTIME_DATA_KEYS = frozenset({"orphan"})

#: 同源媒体路径。/media/{name} 只认一层文件名（main.media_file），这里同样只放一层，
#: 文件名不许以点开头（挡住 ..）
_MEDIA_PATH = re.compile(r"^/media/[A-Za-z0-9_\-][A-Za-z0-9_.\-]*(\?[^\s#]*)?$")
_DATA_URL = re.compile(r"^data:(image|video|audio)/[A-Za-z0-9.+\-]+[;,]")


class CanvasDocError(ValueError):
    """画布文档不合法。消息直接给人看（前端 toast）。"""


# ── 纯函数：校验、版本、映射 ────────────────────────────────────────────────

def check_media_url(url: Any) -> None:
    """铁律 2：文档里只许 /media 同源地址或 data:。

    网关临时地址（run.first_frame_url、GenTask.result 里的签名 URL）过几小时就失效，
    存进画布 = 过几天整张画布一片「图挂了」。http://localhost:8100/media/… 这种
    写死主机的也不收 —— 前端过一遍 media() 就是同源路径，换部署地址也不坏。
    """
    if not isinstance(url, str) or not url:
        raise CanvasDocError("媒体地址必须是非空字符串")
    if url.startswith("data:"):
        if not _DATA_URL.match(url):
            raise CanvasDocError("data: 地址只收图片、视频、音频")
        if len(url.encode("utf-8")) > MAX_DATA_URL_BYTES:
            raise CanvasDocError(
                f"data: 地址超过 {MAX_DATA_URL_BYTES // 1024}KB：大文件先上传，存 /media 地址")
        return
    if not _MEDIA_PATH.match(url):
        raise CanvasDocError(
            f"媒体地址只能是 /media/… 同源路径或 data:，收到「{url[:120]}」"
            "（网关临时地址会过期；前端先过 media()）")


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_doc(doc: Any) -> dict[str, Any]:
    """校验画布文档并返回要落库的那份（派生节点 data 剥成白名单、derived 边去掉）。

    不合法抛 CanvasDocError。不改入参。
    剥字段而不是拒收：前端多带一个字段不该让整次保存失败、用户的布局丢掉。
    """
    if not isinstance(doc, dict):
        raise CanvasDocError("doc 必须是对象")
    if doc.get("schema") != DOC_SCHEMA:
        raise CanvasDocError(f"doc.schema 必须是 {DOC_SCHEMA}，收到 {doc.get('schema')!r}")
    nodes, edges, hidden = doc.get("nodes"), doc.get("edges"), doc.get("hidden", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise CanvasDocError("doc.nodes 与 doc.edges 必须是数组")
    if len(nodes) > MAX_NODES:
        raise CanvasDocError(f"节点 {len(nodes)} 个，超过上限 {MAX_NODES}")
    if len(edges) > MAX_EDGES:
        raise CanvasDocError(f"连线 {len(edges)} 条，超过上限 {MAX_EDGES}")
    if hidden is None:
        hidden = []
    if not isinstance(hidden, list) or not all(isinstance(h, str) for h in hidden):
        raise CanvasDocError("doc.hidden 必须是字符串数组")
    viewport = doc.get("viewport")
    if viewport is not None and not (
            isinstance(viewport, dict) and all(_number(viewport.get(k)) for k in ("x", "y", "zoom"))):
        raise CanvasDocError("doc.viewport 必须是 {x, y, zoom} 数字")

    out_nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in nodes:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not n["id"]:
            raise CanvasDocError("每个节点都要有字符串 id")
        nid = n["id"]
        if nid in seen:
            raise CanvasDocError(f"节点 id 重复：{nid}")
        seen.add(nid)
        if not isinstance(n.get("type"), str) or not n["type"]:
            raise CanvasDocError(f"节点 {nid} 缺 type")
        pos = n.get("position")
        if not isinstance(pos, dict) or not (_number(pos.get("x")) and _number(pos.get("y"))):
            raise CanvasDocError(f"节点 {nid} 的 position 必须是 {{x, y}} 数字")
        data = n.get("data")
        if not isinstance(data, dict):
            raise CanvasDocError(f"节点 {nid} 缺 data")
        ref = data.get("ref")
        if not isinstance(ref, dict) or not isinstance(ref.get("kind"), str) or not isinstance(ref.get("id"), str):
            raise CanvasDocError(f"节点 {nid} 的 data.ref 必须是 {{kind, id}}")
        if (ref.get("mode") == "reference" and ref.get("revision")) or ref["kind"] in {"entity", "variant", "canonical_pack", "canonical_view", "audio", "event", "stage", "coverage", "run_output"}:
            from pydantic import ValidationError
            from app.production.schema import ResourceRef
            try:
                parsed = ResourceRef.model_validate(ref)
                if not parsed.revision:
                    raise CanvasDocError(f"节点 {nid}：先解析资源取得 revision，再保存引用")
                if parsed.mode != "reference":
                    raise CanvasDocError(f"节点 {nid}：本批尚未支持历史快照或派生")
                ref = parsed.model_dump()
                data = {**data, "ref": ref}
            except ValidationError as exc:
                raise CanvasDocError(f"节点 {nid}：资源引用不符合 production/v0.1") from exc
        if ref.get("mode") == "reference" or ref["kind"] in LIVE_REF_KINDS:
            data = {k: v for k, v in data.items() if k in DERIVED_DATA_KEYS}
        else:
            data = {k: v for k, v in data.items() if k not in RUNTIME_DATA_KEYS}
        media = data.get("media")
        if media is not None:
            if not isinstance(media, dict):
                raise CanvasDocError(f"节点 {nid} 的 data.media 必须是对象")
            try:
                check_media_url(media.get("url"))
            except CanvasDocError as exc:
                raise CanvasDocError(f"节点 {nid}：{exc}") from exc
        out_nodes.append({**n, "data": data})

    out_edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    for e in edges:
        if not isinstance(e, dict) or not all(
                isinstance(e.get(k), str) and e.get(k) for k in ("id", "source", "target")):
            raise CanvasDocError("每条连线都要有字符串 id / source / target")
        if e["id"] in seen_edges:
            raise CanvasDocError(f"连线 id 重复：{e['id']}")
        seen_edges.add(e["id"])
        # 推导边每次载入现算；存进来下次就是两条叠在一起
        if isinstance(e.get("data"), dict) and e["data"].get("derived"):
            continue
        out_edges.append(e)

    out = {**doc, "nodes": out_nodes, "edges": out_edges, "hidden": hidden}
    try:
        raw = json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except ValueError as exc:
        # NaN/Infinity：JSONB 不收，不挡在这里就是一个 500
        raise CanvasDocError("文档里有 NaN 或 Infinity（多半是节点坐标算坏了）") from exc
    if len(raw.encode("utf-8")) > MAX_DOC_BYTES:
        raise CanvasDocError(f"画布文档超过 {MAX_DOC_BYTES // (1024 * 1024)}MB：大图请上传，别用 data: 存")
    return out


def version_conflict(current: int | None, base: int) -> bool:
    """current = 库里的版本（None = 这份计划还没有画布，等同 0）。"""
    return (current or 0) != base


def _conflict(version: int) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": "CANVAS_VERSION_CONFLICT",
        "message": f"画布在别处被改过（现在是第 {version} 版），先载入远端再改",
        "version": version,
    })


def build_shot_map(old: Iterable[tuple[str, int | None, int]],
                   new: Iterable[tuple[str, int | None, int]]) -> dict[str, str]:
    """旧计划镜头 id → 新计划镜头 id。行 = (shot_id, 场次 order_no | None, 镜头 order_no)。

    按「第几场的第几镜」对，不按镜头 order_no 本身：order_no 是整份计划连续编号的
    （shot_plan.py 里 order_no += 1 贯穿全部场次），第一场多切一镜，后面每一场的
    order_no 全部错一位，按它对会把整章的布局挪到隔壁镜头上。
    """
    def keyed(rows: Iterable[tuple[str, int | None, int]]) -> dict[tuple[int | None, int], str]:
        by_scene: dict[int | None, list[tuple[int, str]]] = {}
        for sid, scene_no, shot_no in rows:
            by_scene.setdefault(scene_no, []).append((shot_no, sid))
        return {(scene_no, rank): sid
                for scene_no, items in by_scene.items()
                for rank, (_n, sid) in enumerate(sorted(items))}

    new_by_key = keyed(new)
    return {sid: new_by_key[k] for k, sid in keyed(old).items() if k in new_by_key}


def build_scene_map(old: Iterable[tuple[str, int]], new: Iterable[tuple[str, int]]) -> dict[str, str]:
    """旧剧本场次 id → 新剧本场次 id，按场次 order_no。同一份剧本出的两份计划就是恒等映射。"""
    new_by_no = {no: sid for sid, no in new}
    return {sid: new_by_no[no] for sid, no in old if no in new_by_no}


class Remapped(NamedTuple):
    doc: dict[str, Any]
    #: 换了引用的派生节点数
    mapped: int
    #: 映射不上（或换完 id 撞车）丢掉的节点数
    dropped: int
    #: 因为一端被丢掉而跟着丢的用户连线数
    dropped_edges: int


#: 自动标题（「镜头 7」「场景 2」）里的序号；人改过的标题不碰
_AUTO_TITLE = re.compile(r"^(镜头|场景)\s*\d+$")


def remap_doc(doc: Mapping[str, Any], shot_map: Mapping[str, str], scene_map: Mapping[str, str],
              *, story_map: Mapping[str, str] | None = None,
              numbers: Mapping[str, int] | None = None) -> Remapped:
    """把画布文档里的 shot / scene（以及给了 story_map 时的 story）引用换成新计划的。

    节点 id 按前端 nodeIdOf 的规则重算（`shot:<id>` / `scene:<id>` / `story:<id>`），
    连线两端、连线 id、hidden 列表跟着换。映射不上的派生节点丢掉并计数，
    连到它们的连线也丢。角色视角、白模、导演产物、素材、自由节点与计划无关，原样搬。
    numbers = 新引用 id → 新序号：自动标题里的序号跟着改（否则「镜头 7」挂在第 8 镜上）。
    """
    maps: dict[str, Mapping[str, str]] = {"shot": shot_map, "scene": scene_map}
    if story_map is not None:
        maps["story"] = story_map
    id_map: dict[str, str | None] = {}
    nodes: list[dict[str, Any]] = []
    taken: set[str] = set()
    mapped = dropped = 0

    for n in as_items(doc, "nodes"):
        data = dict(n.get("data") or {})
        ref = data.get("ref") or {}
        table = maps.get(ref.get("kind"))
        if table is None:
            if n["id"] in taken:   # 和某个换过 id 的节点撞了：保留先来的
                id_map.setdefault(n["id"], None)
                dropped += 1
                continue
            # 记成恒等：自由节点的随机 id 碰巧长得像 `shot:…` 时，下面 move() 也不会去拆它
            id_map[n["id"]] = n["id"]
            taken.add(n["id"])
            nodes.append(dict(n))
            continue
        new_ref_id = table.get(ref.get("id"))
        new_id_ = f"{ref['kind']}:{new_ref_id}" if new_ref_id else None
        if new_id_ is None or new_id_ in taken:
            id_map[n["id"]] = None
            dropped += 1
            continue
        id_map[n["id"]] = new_id_
        taken.add(new_id_)
        data["ref"] = {**ref, "id": new_ref_id}
        title = data.get("title")
        if numbers and isinstance(title, str) and _AUTO_TITLE.match(title) and new_ref_id in numbers:
            data["title"] = re.sub(r"\d+$", str(numbers[new_ref_id]), title)
        nodes.append({**n, "id": new_id_, "data": data})
        mapped += 1

    def move(node_id: str) -> str | None:
        if node_id in id_map:
            return id_map[node_id]
        kind, sep, rid = node_id.partition(":")
        if sep and kind in maps:   # 不在 nodes 里的派生引用（hidden 里常见）
            new_ref_id = maps[kind].get(rid)
            return f"{kind}:{new_ref_id}" if new_ref_id else None
        return node_id

    edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    dropped_edges = 0
    for e in as_items(doc, "edges"):
        src, dst = move(e["source"]), move(e["target"])
        if src is None or dst is None:
            dropped_edges += 1
            continue
        eid = e["id"]
        for old, new in ((e["source"], src), (e["target"], dst)):
            if old != new:
                eid = eid.replace(old, new)
        if eid in seen_edges:
            dropped_edges += 1
            continue
        seen_edges.add(eid)
        edges.append({**e, "id": eid, "source": src, "target": dst})

    hidden = [h for h in (move(h) for h in doc.get("hidden") or []) if h is not None]
    out = {**doc, "nodes": nodes, "edges": edges, "hidden": list(dict.fromkeys(hidden))}
    return Remapped(out, mapped, dropped, dropped_edges)


def script_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """script._doc_payload 的结果投影成画布要的形状（前端 model.ts 的 ScriptScene）。

    场次 id 就是 Scene.id，和 board 里 shots[].scene_id 是同一套：
    分镜流水线建镜头时 scene_id 取的就是这份 script_doc 的 Scene（shot_plan.py）。
    """
    return {
        "script_doc_id": payload.get("id"),
        "version": payload.get("version"),
        "scenes": [
            {
                "id": s["id"], "order_no": s["order_no"], "title": s.get("title"),
                "time_of_day": s.get("time_of_day"), "location_text": s.get("location_text"),
                "summary": s.get("summary"),
                "blocks": [{"id": b["id"], "type": b["type"], "text": b.get("text") or "",
                            "speaker": b.get("speaker")} for b in s.get("blocks") or []],
            }
            for s in payload.get("scenes") or []
        ],
    }


def box_info(p: SceneProject, active_run: str | None, *, include_doc: bool = True) -> dict[str, Any]:
    """3D-BOX 项目的轻量信息（前端 model.ts 的 BoxInfo）。

    机位列表取编译好的 doc（带名字）；doc 编译失败时退到诊断摘要。
    thumb_url 原样给（库里存的是带主机的地址），前端照例过 media()。
    """
    d = p.diagnostics_json or {}
    summary = d.get("summary") or {}
    doc = p.compiled_json or None
    cams = (doc or {}).get("cameras") or summary.get("cameras") or []
    return {
        "id": p.id, "title": p.title, "thumb_url": p.thumb_url,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "ok": d.get("ok"),
        "duration": (doc or {}).get("duration") or summary.get("duration"),
        "cameras": [{"id": c.get("id"), "name": c.get("name") or c.get("id")}
                    for c in cams if isinstance(c, dict)],
        "objects": summary.get("objects"),
        "doc": doc if include_doc else None,
        "active_run": active_run,
    }


def upload_kind(mime: str) -> AssetKind | None:
    """画布只收图、视频、音频。SVG 不收：同源下发能带脚本，而且 /media 也认不出它的类型。"""
    if mime == "image/svg+xml":
        return None
    head = mime.split("/", 1)[0]
    return {"image": AssetKind.image, "video": AssetKind.video, "audio": AssetKind.audio}.get(head)


def same_origin(url: str) -> str:
    """库里的 Asset.url 写死了 public_base_url；给画布的一律是同源 /media 路径（同前端 media()）。"""
    i = url.find("/media/")
    return url[i:] if i >= 0 else url


# ── 纯函数：一章怎么分画布 ──────────────────────────────────────────────

#: 一张场次画布最多放几镜：再多节点挤成一片，生成面板、白模实时视口都顾不过来
MAX_SHOTS_PER_CANVAS = 24
#: 画布的种类（见 models/studio_board.py 文件头）
BOARD_KINDS = ("plan", "scene", "custom")


class ScopeRow(NamedTuple):
    #: 稳定键：重新分画布时按它认回已有的那张（布局不丢）。长场次第 i 段是 scene:<id>#i，段数变了第 1 段还是它
    key: str
    title: str
    scene_ids: list[str]
    shot_ids: list[str]
    sort: int


def _parts(key: str, label: str, scene_ids: list[str], ids: list[str], max_shots: int, base: int) -> list[ScopeRow]:
    """均分成 n 段（112 镜按 24 → 5 段，每段 22–23 镜），不留一段只有两三镜的零头。"""
    n = math.ceil(len(ids) / max_shots)
    size, extra = divmod(len(ids), n)               # 余数摊给前几段：段与段最多差一镜
    rows: list[ScopeRow] = []
    at = 0
    for i in range(n):
        take = size + (1 if i < extra else 0)
        rows.append(ScopeRow(f"{key}#{i + 1}", f"{label}（{i + 1}/{n}）" if n > 1 else label,
                             list(scene_ids), ids[at:at + take], base + i))
        at += take
    return rows


def split_scopes(scenes: Iterable[tuple[str, int, str | None]], shots: Iterable[tuple[str, str | None, int]],
                 max_shots: int = MAX_SHOTS_PER_CANVAS) -> list[ScopeRow]:
    """按剧本场次分画布，长场次按镜头数均分成几段。

    scenes = (scene_id, order_no, title)；shots = (shot_id, scene_id, order_no)。
    没有镜头的场次不建画布；归属不到任何场次的镜头放最后一张「未分场」。
    """
    max_shots = max(1, int(max_shots))
    by_scene: dict[str | None, list[tuple[int, str]]] = {}
    for sid, scene_id, no in shots:
        by_scene.setdefault(scene_id, []).append((no, sid))
    known = set()
    out: list[ScopeRow] = []
    for scene_id, no, title in sorted(scenes, key=lambda s: s[1]):
        known.add(scene_id)
        ids = [sid for _n, sid in sorted(by_scene.get(scene_id, []))]
        if ids:
            label = f"{no}. {title}" if title else f"场景 {no}"
            out += _parts(f"scene:{scene_id}", label, [scene_id], ids, max_shots, len(out))
    loose = sorted(item for scene_id, items in by_scene.items() if scene_id not in known for item in items)
    if loose:
        out += _parts("loose", "未分场", [], [sid for _n, sid in loose], max_shots, len(out))
    return out


def board_meta(row: StudioBoard, *, shots: int | None = None, videos: int | None = None) -> dict[str, Any]:
    """画布列表里的一行（前端 model.ts 的 CanvasMeta）。shots/videos = 这张画布管的镜头数、已出视频数。"""
    scope = dict(row.scope_json or {})
    purpose = (scope.get("production") or {}).get("purpose", scope.get("purpose"))
    if purpose not in {"assets", "directing", "finishing", "general"}:
        purpose = "directing" if row.kind in {"plan", "scene"} else "general"
    return {
        "id": row.id, "kind": row.kind, "title": row.title, "source": row.source, "sort": row.sort,
        "plan_id": row.shot_plan_id, "chapter_id": row.chapter_id, "novel_id": row.novel_id,
        "scope": scope, "purpose": purpose, "stale": bool(scope.get("stale")),
        "version": row.version, "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "shots": shots, "videos": videos,
    }


def scope_shot_ids(row: StudioBoard) -> list[str] | None:
    """None = 整章（总览管全部镜头）；列表 = 这张画布管的镜头。"""
    if row.kind == "plan":
        return None
    return [s for s in (row.scope_json or {}).get("shot_ids") or [] if isinstance(s, str)]


# ── 读库 ────────────────────────────────────────────────────────────────

def _plan(db: Session, plan_id: str, what: str = "shot plan") -> ShotPlan:
    plan = db.get(ShotPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return plan


def _overview(db: Session, plan_id: str, *, lock: bool = False) -> StudioBoard | None:
    """整章总览那张（一份计划只有一张）。"""
    stmt = select(StudioBoard).where(StudioBoard.shot_plan_id == plan_id, StudioBoard.kind == "plan")
    if lock:
        # 行锁：两个标签页同时 PUT，后到的等前一个提交完再读版本，读到新版本 → 409
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalars().first()


def _get_board(db: Session, board_id: str, *, lock: bool = False) -> StudioBoard:
    stmt = select(StudioBoard).where(StudioBoard.id == board_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="画布不存在")
    return row


def _chapter_of(db: Session, plan: ShotPlan) -> Chapter | None:
    doc = db.get(ScriptDoc, plan.script_doc_id)
    return db.get(Chapter, doc.chapter_id) if doc else None


def _new_board(db: Session, *, kind: str, title: str, plan: ShotPlan | None, chapter: Chapter | None,
               novel_id: str | None = None, scope: dict[str, Any] | None = None, sort: int = 0,
               source: str = "auto") -> StudioBoard:
    row = StudioBoard(id=new_id("brd"), kind=kind, title=title[:200], shot_plan_id=plan.id if plan else None,
                      chapter_id=chapter.id if chapter else None,
                      novel_id=(chapter.novel_id if chapter else None) or novel_id,
                      scope_json=scope or {}, sort=sort, source=source, version=0, doc_json={})
    db.add(row)
    return row


def overview_title(plan: ShotPlan) -> str:
    v = getattr(plan, "version", None)
    return f"整章总览 · 分镜 v{v}" if v else "整章总览"


def ensure_overview(db: Session, plan: ShotPlan) -> StudioBoard:
    """整章总览：没有就建一张空的（version 0，前端按自动布局摆）。两个请求同时建时后到的撞唯一索引，读回先建的。"""
    row = _overview(db, plan.id)
    if row is not None:
        return row
    row = _new_board(db, kind="plan", title=overview_title(plan), plan=plan, chapter=_chapter_of(db, plan), sort=0)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = _overview(db, plan.id)
        if row is None:
            raise
    return row


def sync_scene_boards(db: Session, plan: ShotPlan, max_shots: int = MAX_SHOTS_PER_CANVAS) -> list[StudioBoard]:
    """按场次（长场次切段）建 / 更新自动画布。

    按 scope 键认回已有的画布，只改标题和管的镜头，布局不动；
    分镜重编译后对不上的旧画布：没动过（version 0）的删掉，动过的留着标 stale，免得用户的布局丢了。
    """
    chapter = _chapter_of(db, plan)
    scenes = [(sid, no, title) for sid, no, title in db.execute(
        select(Scene.id, Scene.order_no, Scene.title).where(Scene.script_doc_id == plan.script_doc_id)).all()]
    shots = [(sid, scene_id, no) for sid, scene_id, no in db.execute(
        select(Shot.id, Shot.scene_id, Shot.order_no).where(Shot.shot_plan_id == plan.id)).all()]
    scopes = split_scopes(scenes, shots, max_shots)
    existing: dict[str, StudioBoard] = {}
    for b in db.execute(select(StudioBoard).where(
            StudioBoard.shot_plan_id == plan.id, StudioBoard.kind == "scene",
            StudioBoard.source == "auto")).scalars():
        existing.setdefault(str((b.scope_json or {}).get("key") or b.id), b)
    out: list[StudioBoard] = []
    for sc in scopes:
        b = existing.pop(sc.key, None) or _new_board(db, kind="scene", title=sc.title, plan=plan, chapter=chapter)
        b.title = sc.title[:200]
        b.scope_json = {"key": sc.key, "scene_ids": sc.scene_ids, "shot_ids": sc.shot_ids}
        b.sort = sc.sort + 1
        out.append(b)
    for b in existing.values():
        if not b.version:
            db.delete(b)
        else:
            b.scope_json = {**(b.scope_json or {}), "stale": True}
    db.commit()
    return out


def _plan_shots(db: Session, plan_id: str) -> dict[str, bool]:
    """这份计划的镜头 → 有没有成片视频。"""
    return {sid: bool(v) for sid, v in db.execute(
        select(Shot.id, Shot.video_asset_id).where(Shot.shot_plan_id == plan_id)).all()}


def _metas(rows: Iterable[StudioBoard], shots_by_plan: dict[str, dict[str, bool]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        have = shots_by_plan.get(row.shot_plan_id or "", {})
        ids = scope_shot_ids(row)
        scoped = list(have) if ids is None else [s for s in ids if s in have]
        out.append(board_meta(row, shots=len(scoped) if row.shot_plan_id else None,
                              videos=sum(1 for s in scoped if have.get(s)) if row.shot_plan_id else None))
    return out


def _default_plan(db: Session, chapter: Chapter) -> ShotPlan | None:
    """默认看最近一份正式分镜：试片计划只有几镜，不适合当画布的起点（同前端 App.tsx）。"""
    doc_ids = [d for d, in db.execute(select(ScriptDoc.id).where(ScriptDoc.chapter_id == chapter.id)).all()]
    rows = db.execute(
        select(ShotPlan, func.count(Shot.id)).outerjoin(Shot, Shot.shot_plan_id == ShotPlan.id)
        .where(ShotPlan.script_doc_id.in_(doc_ids or [""])).group_by(ShotPlan.id)
        .order_by(ShotPlan.created_at.desc())).all()
    main = next((p for p, n in rows if n and not (p.config_json or {}).get("sample")), None)
    return main or (rows[0][0] if rows else None)


def canvas_context(db: Session, row: StudioBoard) -> dict[str, Any]:
    """这张画布要现取哪些东西：管的镜头、出场人物（人物卡 id）和各自的音色。

    shot_ids / cast_ids 为 None = 整章全部。人物按表演单（ShotPerformance）算：这几镜里真正出场的人。
    """
    if not row.shot_plan_id:
        return {"shot_ids": [], "cast_ids": [], "voices": {}}
    plan = db.get(ShotPlan, row.shot_plan_id)
    ids = scope_shot_ids(row)
    q = select(ShotPerformance.entity_id).join(Shot, Shot.id == ShotPerformance.shot_id).where(
        Shot.shot_plan_id == row.shot_plan_id)
    if ids is not None:
        q = q.where(Shot.id.in_(ids or [""]))
    cast = list(dict.fromkeys(e for e, in db.execute(q).all() if e))
    voices: dict[str, dict[str, Any]] = {}
    transform = db.get(WorldTransform, plan.transform_id) if plan and plan.transform_id else None
    if transform is not None and cast:
        for vc in db.execute(select(VoiceCasting).where(
                VoiceCasting.world_profile_id == transform.target_profile_id,
                VoiceCasting.cast_key.in_(cast))).scalars():
            if vc.cast_key in voices and vc.epoch_key != "baseline":
                continue
            voices[vc.cast_key] = {"describe": VoiceSpec.from_json(vc.timbre_json).describe(),
                                   "engine": vc.voice_engine, "has_ref": bool(vc.voice_ref or vc.voice_asset_id)}
    return {"shot_ids": ids, "cast_ids": None if ids is None else cast, "voices": voices}


def _record(row: StudioBoard) -> dict[str, Any]:
    """画布文档记录（前端 CanvasRecord）。version 0 = 还没存过，doc 给 null，前端按自动布局摆。"""
    return {"version": row.version, "doc": row.doc_json if row.version else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def _save(db: Session, row: StudioBoard, doc: dict[str, Any]) -> StudioBoard:
    """写文档，version += 1，**先提交再回应**。

    get_db 的 commit 在响应发出之后才跑（见 blocking.put_blocking）：前端拿到新版本号
    立刻又存一次，那次读到的还是旧版本 → 平白一个 409。
    """
    row.doc_json = doc
    row.version = (row.version or 0) + 1
    try:
        db.commit()
    except IntegrityError as exc:
        # 两边同时首建整章总览：后到的撞唯一索引，按版本冲突回
        db.rollback()
        current = _overview(db, row.shot_plan_id) if row.shot_plan_id else None
        raise _conflict(current.version if current else 0) from exc
    return row


def _validated(doc: Any) -> dict[str, Any]:
    try:
        return validate_doc(doc)
    except CanvasDocError as exc:
        raise HTTPException(status_code=422, detail={"code": "CANVAS_INVALID", "message": str(exc)}) from exc


# ── 一章多张画布 ────────────────────────────────────────────────────────

class CanvasIn(BaseModel):
    base_version: int = Field(ge=0)
    doc: dict[str, Any]


@router.get("/chapters/{chapter_id}/canvases")
def chapter_canvases(chapter_id: str, plan_id: str | None = None, split: bool = True,
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    """这一章的画布：整章总览 + 按场次分的 + 自建的。第一次打开时自动分（split=false 只列不建）。

    plan_id 不给就取最近一份正式分镜。没挂分镜的自建画布（旅拍、相册）按章节挂在这里一起列。
    """
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    plan = _plan(db, plan_id) if plan_id else _default_plan(db, chapter)
    if plan is not None and split:
        ensure_overview(db, plan)
        has_auto = db.execute(select(StudioBoard.id).where(
            StudioBoard.shot_plan_id == plan.id, StudioBoard.kind == "scene", StudioBoard.source == "auto")).first()
        if not has_auto:
            sync_scene_boards(db, plan)
    conds = [StudioBoard.chapter_id == chapter.id, StudioBoard.shot_plan_id.is_(None)]
    q = select(StudioBoard).where(
        (StudioBoard.shot_plan_id == plan.id) | and_(*conds) if plan is not None else and_(*conds))
    rows = sorted(db.execute(q).scalars(), key=lambda b: (BOARD_KINDS.index(b.kind) if b.kind in BOARD_KINDS else 9,
                                                          b.sort, b.created_at))
    shots = {plan.id: _plan_shots(db, plan.id)} if plan is not None else {}
    return {"chapter": {"id": chapter.id, "title": chapter.title, "novel_id": chapter.novel_id},
            "plan_id": plan.id if plan else None, "canvases": _metas(rows, shots)}


class SplitIn(BaseModel):
    max_shots: int = Field(MAX_SHOTS_PER_CANVAS, ge=4, le=200)


@router.post("/plans/{plan_id}/canvases:split")
def split_canvases(plan_id: str, body: SplitIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """重新按场次分画布（分镜重编译之后、或想换每张的镜头数）。已有画布按场次认回，布局不丢。"""
    plan = _plan(db, plan_id)
    ensure_overview(db, plan)
    rows = sync_scene_boards(db, plan, body.max_shots)
    return {"plan_id": plan.id, "canvases": _metas(rows, {plan.id: _plan_shots(db, plan.id)})}


class BoardIn(BaseModel):
    title: str = Field("空白画布", min_length=1, max_length=200)
    #: Explicit free creation: no automatic graph; legacy callers keep their existing initialization.
    blank: bool = False
    #: 挂在哪份分镜上（不挂 = 空白画布：旅拍、相册、外部素材）
    plan_id: str | None = None
    chapter_id: str | None = None
    novel_id: str | None = None
    shot_ids: list[str] = Field(default_factory=list, max_length=2000)
    #: 只给场次时，取这些场次的全部镜头
    scene_ids: list[str] = Field(default_factory=list, max_length=200)
    #: 生产阶段用途；存量自由标签仍保留在 scope 中，展示时适配为 general。
    purpose: Literal["assets", "directing", "finishing", "general"] | None = None
    source: str = Field("api", pattern="^(user|api)$")


def _scoped_ids(db: Session, plan: ShotPlan, shot_ids: list[str], scene_ids: list[str]) -> list[str]:
    """把请求里的镜头 / 场次收敛成这份计划里真有的镜头，按镜头次序。"""
    rows = db.execute(select(Shot.id, Shot.scene_id, Shot.order_no).where(Shot.shot_plan_id == plan.id)).all()
    want = set(shot_ids)
    scenes = set(scene_ids)
    return [sid for sid, scene_id, _no in sorted(rows, key=lambda r: r[2])
            if sid in want or (not want and scene_id in scenes)]


@router.post("/canvases")
def create_canvas(body: BoardIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """自建画布：任意镜头集合（挑几镜单独打磨），或不挂分镜的空白画布（旅拍、相册、外部系统）。"""
    if body.blank and (body.plan_id or body.shot_ids or body.scene_ids):
        raise HTTPException(status_code=422, detail={
            "code": "blank_scope_conflict", "message": "空白画布不自动挂分镜计划或镜头；创建后按需添加引用节点", "issues": []})
    if not body.plan_id and (body.shot_ids or body.scene_ids):
        raise HTTPException(status_code=422, detail="镜头/场次范围需要 plan_id")
    plan = _plan(db, body.plan_id) if body.plan_id else None
    chapter = _chapter_of(db, plan) if plan else (db.get(Chapter, body.chapter_id) if body.chapter_id else None)
    if body.chapter_id and chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    if body.chapter_id and chapter and body.chapter_id != chapter.id:
        raise HTTPException(status_code=422, detail="chapter does not belong to plan")
    if body.novel_id:
        from app.models import Novel
        novel = db.get(Novel, body.novel_id)
        if novel is None:
            raise HTTPException(status_code=404, detail="novel not found")
        if chapter and chapter.novel_id != novel.id:
            raise HTTPException(status_code=422, detail="novel does not belong to chapter")
    scope: dict[str, Any] = {}
    if plan is not None:
        scope = {"scene_ids": list(body.scene_ids),
                 "shot_ids": _scoped_ids(db, plan, body.shot_ids, body.scene_ids)}
    if body.purpose:
        scope["purpose"] = body.purpose
    last = db.execute(select(func.max(StudioBoard.sort)).where(
        StudioBoard.shot_plan_id == plan.id if plan else StudioBoard.chapter_id == (chapter.id if chapter else ""))).scalar()
    row = _new_board(db, kind="custom", title=body.title, plan=plan, chapter=chapter, novel_id=body.novel_id,
                     scope=scope, sort=(last or 0) + 1, source=body.source)
    if body.blank:
        # version=0 means automatic layout to legacy readers. Persist an explicit empty
        # document and return its actual version so reload cannot populate a template.
        row.doc_json = {"schema": DOC_SCHEMA, "nodes": [], "edges": [], "hidden": [],
                        "viewport": {"x": 0, "y": 0, "zoom": 1}}
        row.version = 1
    db.commit()
    return board_meta(row, shots=len(scope.get("shot_ids") or []) if plan else None)


@router.get("/canvases")
def list_canvases(limit: int = Query(60, ge=1, le=500), free: bool = False,
                  purpose: list[Literal["assets", "directing", "finishing", "general"]] | None = Query(None),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    """全部画布（最近修改的在前），free=True 只列不挂章节的自由画布。"""
    q = select(StudioBoard)
    if free:
        q = q.where(StudioBoard.chapter_id.is_(None), StudioBoard.shot_plan_id.is_(None))
    if purpose:
        raw = func.coalesce(StudioBoard.scope_json["production"]["purpose"].astext,
                            StudioBoard.scope_json["purpose"].astext)
        effective = case(
            (raw.in_(["assets", "directing", "finishing", "general"]), raw),
            (StudioBoard.kind.in_(["plan", "scene"]), "directing"), else_="general")
        q = q.where(effective.in_(purpose))
    q = q.order_by(StudioBoard.updated_at.desc().nullslast(), StudioBoard.created_at.desc()).limit(limit)
    rows = db.execute(q).scalars().all()
    out = []
    for r in rows:
        m = board_meta(r)
        doc = r.doc_json or {}
        nodes = doc.get("nodes") or []
        cover = None
        for n in nodes:
            med = (n.get("data") or {}).get("media") or {}
            if med.get("url"):
                cover = med["url"]
                break
        out.append({**m, "cover": cover, "nodes": len(nodes)})
    return {"canvases": out}


@router.get("/canvases/{board_id}")
def get_board(board_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """一张画布：元信息 + 文档 + 现取用的上下文（管哪些镜头、出场人物卡 id、音色）。"""
    row = _get_board(db, board_id)
    shots = {row.shot_plan_id: _plan_shots(db, row.shot_plan_id)} if row.shot_plan_id else {}
    return {**_metas([row], shots)[0], **_record(row), "context": canvas_context(db, row)}


@router.put("/canvases/{board_id}")
def put_board(board_id: str, body: CanvasIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    doc = _validated(body.doc)
    row = _get_board(db, board_id, lock=True)
    if version_conflict(row.version, body.base_version):
        raise _conflict(row.version)
    return _record(_save(db, row, doc))


class BoardPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    shot_ids: list[str] | None = Field(None, max_length=2000)
    scene_ids: list[str] | None = Field(None, max_length=200)


@router.patch("/canvases/{board_id}")
def patch_board(board_id: str, body: BoardPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    """改标题、改管哪些镜头。整章总览管全部镜头，不能改范围；改了自动画布的范围它就变成自建的（重新分时不再覆盖）。"""
    row = _get_board(db, board_id)
    if body.title is not None:
        row.title = body.title
    if body.shot_ids is not None or body.scene_ids is not None:
        if row.kind == "plan" or not row.shot_plan_id:
            raise HTTPException(status_code=422, detail="整章总览和空白画布没有镜头范围可改")
        plan = _plan(db, row.shot_plan_id)
        scope = dict(row.scope_json or {})
        scope["shot_ids"] = _scoped_ids(db, plan, body.shot_ids or [], body.scene_ids or [])
        if body.scene_ids is not None:
            scope["scene_ids"] = list(body.scene_ids)
        scope.pop("key", None)
        scope.pop("stale", None)
        row.scope_json, row.kind, row.source = scope, "custom", "user"
    db.commit()
    shots = {row.shot_plan_id: _plan_shots(db, row.shot_plan_id)} if row.shot_plan_id else {}
    return _metas([row], shots)[0]


@router.delete("/canvases/{board_id}", status_code=204)
def delete_board(board_id: str, db: Session = Depends(get_db)) -> None:
    """删画布（只删布局，镜头、人物卡、白模这些真身都还在）。整章总览不能删。"""
    row = _get_board(db, board_id)
    if row.kind == "plan":
        raise HTTPException(status_code=422, detail="整章总览不能删")
    db.delete(row)
    db.commit()


@router.get("/shots/{shot_id}/canvas")
def shot_canvas(shot_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """从分镜画布点一镜「进入创作画布」：这一镜所在的场次画布（还没分过就先分）。找不到就给整章总览。"""
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    plan = _plan(db, shot.shot_plan_id)
    overview = ensure_overview(db, plan)
    rows = list(db.execute(select(StudioBoard).where(
        StudioBoard.shot_plan_id == plan.id, StudioBoard.kind == "scene")).scalars())
    if not rows:
        rows = sync_scene_boards(db, plan)
    hit = next((b for b in sorted(rows, key=lambda b: b.sort)
                if not (b.scope_json or {}).get("stale") and shot_id in (scope_shot_ids(b) or [])), None)
    return _metas([hit or overview], {plan.id: _plan_shots(db, plan.id)})[0]


class ExecuteIn(BaseModel):
    node_ids: list[str] | None = None
    downstream: bool = False
    force: bool = False


@router.post("/canvases/{board_id}:execute")
def execute_canvas(board_id: str, body: ExecuteIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return canvas_exec.execute(db, board_id, body)
    except canvas_exec.BoardNotFound:
        raise HTTPException(status_code=404, detail="画布不存在")


@router.post("/canvases/{board_id}:stop")
def stop_canvas(board_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return canvas_exec.stop(db, board_id)


@router.get("/canvases/{board_id}/node-runs")
def get_node_runs(board_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return canvas_exec.node_runs(db, board_id)


class ItemIn(BaseModel):
    """外部系统往画布上放一个素材节点（图、视频、一段文字）。媒体先走 /studio/uploads 或别的接口落库。"""
    type: str = Field(pattern="^(image|video|audio|text)$")
    title: str = Field(min_length=1, max_length=200)
    role: str | None = Field(None, max_length=32)
    asset_id: str | None = None
    url: str | None = None
    text: str | None = Field(None, max_length=20000)


def place_below(doc: Mapping[str, Any]) -> dict[str, float]:
    """新节点放在现有节点的左下方（最下面一个节点再往下 80px），空画布放原点。"""
    nodes = as_items(doc, "nodes")
    if not nodes:
        return {"x": 0.0, "y": 0.0}
    left = min(float((n.get("position") or {}).get("x") or 0) for n in nodes)
    bottom = max(float((n.get("position") or {}).get("y") or 0) + float(n.get("height") or 260) for n in nodes)
    return {"x": left, "y": bottom + 80}


@router.post("/canvases/{board_id}/items")
def add_item(board_id: str, body: ItemIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """服务端加一个自由节点（旅拍照片、相册素材、外部系统产物）。打开着这张画布的人下次保存会收到 409，按提示载入远端即可。"""
    row = _get_board(db, board_id, lock=True)
    data: dict[str, Any] = {"title": body.title}
    if body.role:
        data["role"] = body.role
    if body.type == "text":
        if not body.text:
            raise HTTPException(status_code=422, detail="文字节点要给 text")
        node_id = f"n{new_id('api')[3:]}"
        data.update(ref={"kind": "free", "id": node_id}, text=body.text, role=body.role or "note")
    else:
        if body.asset_id:
            asset = db.get(Asset, body.asset_id)
            if asset is None:
                raise HTTPException(status_code=404, detail="素材不存在")
            url, mime = same_origin(asset.url), asset.mime
            node_id = f"asset:{asset.id}"
            data["ref"] = {"kind": "asset", "id": asset.id}
        elif body.url:
            url, mime = body.url, None
            node_id = f"n{new_id('api')[3:]}"
            data["ref"] = {"kind": "free", "id": node_id}
        else:
            raise HTTPException(status_code=422, detail="图片、视频节点要给 asset_id 或 url（/media/… 或 data:）")
        data["media"] = {"url": url, "asset_id": body.asset_id, "mime": mime}
        data.setdefault("role", "upload" if body.type == "image" else "generated")
    doc = dict(row.doc_json or {}) if row.version else {}
    doc.setdefault("schema", DOC_SCHEMA)
    doc.setdefault("viewport", {"x": 0, "y": 0, "zoom": 1})
    nodes = list(doc.get("nodes") or [])
    if any(isinstance(n, dict) and n.get("id") == node_id for n in nodes):
        raise HTTPException(status_code=409, detail={"code": "NODE_EXISTS", "message": "这个素材已经在画布上了"})
    nodes.append({"id": node_id, "type": body.type, "position": place_below(doc), "data": data})
    doc.update(nodes=nodes, edges=list(doc.get("edges") or []))
    row = _save(db, row, _validated(doc))
    return {"node_id": node_id, "version": row.version}


# ── 兼容：按计划读写整章总览（早期前端、外部脚本用）────────────────────

class AdoptIn(BaseModel):
    from_plan_id: str
    force: bool = False


@router.get("/plans/{plan_id}/canvas")
def get_canvas(plan_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """整章总览的文档。没有画布 → version 0、doc null，前端按自动布局建一张。"""
    _plan(db, plan_id)
    row = _overview(db, plan_id)
    if row is None:
        return {"version": 0, "doc": None, "updated_at": None}
    return _record(row)


@router.put("/plans/{plan_id}/canvas")
def put_canvas(plan_id: str, body: CanvasIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    plan = _plan(db, plan_id)
    doc = _validated(body.doc)
    row = _overview(db, plan_id, lock=True)
    if version_conflict(row.version if row else None, body.base_version):
        raise _conflict(row.version if row else 0)
    if row is None:
        row = _new_board(db, kind="plan", title=overview_title(plan), plan=plan, chapter=_chapter_of(db, plan))
    return _record(_save(db, row, doc))


def _shot_rows(db: Session, plan: ShotPlan) -> list[tuple[str, int | None, int]]:
    return [(sid, scene_no, shot_no) for sid, shot_no, scene_no in db.execute(
        select(Shot.id, Shot.order_no, Scene.order_no)
        .outerjoin(Scene, Scene.id == Shot.scene_id)
        .where(Shot.shot_plan_id == plan.id)
    ).all()]


def _scene_rows(db: Session, plan: ShotPlan) -> list[tuple[str, int]]:
    return [(sid, no) for sid, no in db.execute(
        select(Scene.id, Scene.order_no).where(Scene.script_doc_id == plan.script_doc_id)
    ).all()]


@router.post("/plans/{plan_id}/canvas:adopt")
def adopt_canvas(plan_id: str, body: AdoptIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """把另一份计划（通常是重编译前的旧计划）的整章总览搬过来。

    不在 GET 里自动搬：搬是有损的（映射不上的节点会丢），要人点了才做，并告诉他丢了几个。
    """
    if body.from_plan_id == plan_id:
        raise HTTPException(status_code=422, detail="来源和目标是同一份计划")
    plan = _plan(db, plan_id)
    src_plan = _plan(db, body.from_plan_id, "source shot plan")
    src = _overview(db, src_plan.id)
    if src is None or not src.version:
        raise HTTPException(status_code=404, detail="来源计划还没有画布")
    row = _overview(db, plan.id, lock=True)
    if row is not None and row.version and not body.force:
        raise HTTPException(status_code=409, detail={
            "code": "CANVAS_EXISTS",
            "message": "这份计划已经有画布了；要覆盖请带 force=true",
            "version": row.version,
        })

    new_shots = _shot_rows(db, plan)
    new_scenes = _scene_rows(db, plan)
    old_ch, new_ch = _chapter_of(db, src_plan), _chapter_of(db, plan)
    story_map = ({old_ch.id: new_ch.id} if old_ch and new_ch and old_ch.id != new_ch.id else None)
    numbers = {sid: shot_no for sid, _scene_no, shot_no in new_shots}
    numbers.update({sid: no for sid, no in new_scenes})
    r = remap_doc(src.doc_json or {}, build_shot_map(_shot_rows(db, src_plan), new_shots),
                  build_scene_map(_scene_rows(db, src_plan), new_scenes),
                  story_map=story_map, numbers=numbers)
    doc = _validated(r.doc)
    if row is None:
        row = _new_board(db, kind="plan", title=overview_title(plan), plan=plan, chapter=new_ch)
    row = _save(db, row, doc)
    return {**_record(row), "mapped": r.mapped, "dropped": r.dropped, "dropped_edges": r.dropped_edges}


# ── 剧本、白模、上传 ────────────────────────────────────────────────────

@router.get("/plans/{plan_id}/script")
def plan_script(plan_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """这份计划所用的那一版剧本（不一定是激活版本）。"""
    plan = _plan(db, plan_id)
    doc = db.get(ScriptDoc, plan.script_doc_id)
    if doc is None:
        return {"script_doc_id": None, "version": None, "scenes": []}
    return script_payload(script_api._doc_payload(db, doc))


@router.get("/box/{project_id}/doc")
def box_doc(project_id: str, include_doc: bool = Query(True),
            db: Session = Depends(get_db)) -> dict[str, Any]:
    p = db.get(SceneProject, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="场景项目不存在")
    run = agent.active_run(project_id)
    return box_info(p, run.id if run else None, include_doc=include_doc)


class BoxRegenerateIn(BaseModel):
    instruction: str | None = Field(None, max_length=2000)
    model: str | None = None


@router.post("/box/{project_id}:regenerate")
def box_regenerate(project_id: str, body: BoxRegenerateIn | None = None,
                   db: Session = Depends(get_db)) -> dict[str, Any]:
    """重新生成/重新搭景 3D 白模项目。

    如果该项目关联了分镜镜头，按镜头的剧本要求通过 Director LLM Planner 重新规划并写入；
    如果是独立白模项目，通过 3D-BOX 智能体重新搭景。
    """
    from app.director import from_shot

    p = db.get(SceneProject, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="场景项目不存在")

    b = body or BoxRegenerateIn()
    # 查找关联此项目的镜头
    shot = db.execute(select(Shot).where(
        text("camera_json->'director_run'->>'box_project_id' = :pid")
    ), {"pid": project_id}).scalars().first()

    if shot is not None:
        out = from_shot.plan_shot_scene(db, shot.id, instruction=b.instruction, model=b.model)
        return {"project_id": project_id, "kind": "shot_plan", **out}

    msg = (b.instruction or "").strip() or f"清空并重新搭景（重新编排人物站位、动作与机位）：{p.title}"
    run = agent.start_run(project_id, msg, selected=[], sketches=[], model=b.model)
    return {"project_id": project_id, "kind": "box_agent", "run_id": run.id}


@router.post("/uploads")
def upload(file: UploadFile = File(...), novel_id: str | None = Form(None),
           db: Session = Depends(get_db)) -> dict[str, Any]:
    """画布「上传」：落成 Asset(source=uploaded)。

    同步函数（跑在线程池里）：读盘、写盘、写库都是阻塞的，别占着事件循环。
    """
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=422, detail="空文件")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
    declared = file.content_type or ""
    if declared in ("", "application/octet-stream"):
        # 浏览器认不出的类型（.webm 在有的系统上就是）会报 octet-stream，再按文件名猜一次
        declared = mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    # 先认真实类型再落盘：不收的文件不该在媒体目录里留下一份
    mime = sniff(raw, declared)
    kind = upload_kind(mime)
    if kind is None:
        raise HTTPException(status_code=422, detail=f"只收图片、视频、音频（收到 {mime}）")
    item = store_bytes(raw, mime=mime)
    # 按内容去重（同 handoff._attach_upload）：同一张图传两次是同一个素材
    asset = db.execute(select(Asset).where(Asset.sha256 == item["sha256"])).scalars().first()
    if asset is None:
        asset = Asset(
            id=new_id("as"), kind=kind, url=str(item["url"]), sha256=str(item["sha256"]),
            mime=str(item["mime"]), bytes=int(item["bytes"]),
            # uploaded 不是 generated：重跑生成时不能把人传的东西当自己的旧产物覆盖掉
            source=AssetSource.uploaded, novel_id=novel_id,
            meta_json={"uploaded_as": file.filename or "", "via": "canvas"},
        )
        db.add(asset)
    db.commit()
    return {"asset_id": asset.id, "url": same_origin(asset.url), "mime": asset.mime}
