"""World DB 服务层：建世界、区域栅格化、空间/文本查询、章节 delta 的提议/应用/拒绝、版本快照、表演与 take。

规则：
- 版本单调递增；apply delta 时 base_version 必须等于 current_version，否则标 conflict，不静默覆盖。
- 修改 = 关闭旧行（valid_to_version = 新版本-1… 即 < 新版本）+ 新增一行；快照按 valid_from <= v <= valid_to 取。
- 表演/机位冻结 frozen_deps；delta 改到的 region 下的 take 标 stale。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    OPEN_VERSION, SpatialWorld, WorldAsset, WorldChunk, WorldDelta, WorldFact, WorldInstance, WorldLandmark,
    WorldPerformance, WorldPortal, WorldRegion, WorldTake, WorldVersion,
)
from app.worldmodel import geometry as geo


class WorldError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


OPS = {"add_region", "add_landmark", "add_portal", "add_asset", "add_instance", "move_instance",
       "remove_instance", "add_fact", "lock_region"}


def _live(model, v: int):
    return (model.valid_from_version <= v) & (model.valid_to_version >= v)


# ---------------------------------------------------------------- 世界与版本

def create_world(db: Session, *, title: str, novel_id: str | None = None, chunk_size_m: float = 8.0,
                 style_ref: dict | None = None) -> SpatialWorld:
    w = SpatialWorld(id=new_id("ws"), title=title, novel_id=novel_id, chunk_size_m=chunk_size_m,
                     current_version=1, style_ref=style_ref)
    db.add(w)
    db.flush()
    db.add(WorldVersion(id=new_id("wv"), world_id=w.id, n=1, parent_n=None, note="genesis"))
    db.flush()
    return w


def get_world(db: Session, world_id: str) -> SpatialWorld:
    w = db.get(SpatialWorld, world_id)
    if w is None:
        raise WorldError("world_not_found", "世界不存在", 404)
    return w


def region_by_key(db: Session, world_id: str, key: str, v: int | None = None) -> WorldRegion:
    w = get_world(db, world_id)
    v = v or w.current_version
    r = db.scalar(select(WorldRegion).where(WorldRegion.world_id == world_id, WorldRegion.stable_key == key,
                                            _live(WorldRegion, v)))
    if r is None:
        raise WorldError("region_not_found", f"区域 {key} 在 v{v} 不存在", 404)
    return r


def _rasterize(db: Session, w: SpatialWorld, r: WorldRegion) -> int:
    cells = geo.chunks_for_aabb(r.bounds_aabb, w.chunk_size_m)
    have = {(c.cx, c.cy) for c in db.scalars(select(WorldChunk).where(WorldChunk.region_id == r.id))}
    for cx, cy in cells:
        if (cx, cy) not in have:
            db.add(WorldChunk(id=new_id("wc"), world_id=w.id, region_id=r.id, cx=cx, cy=cy, lod=r.lod))
    return len(cells)


# ---------------------------------------------------------------- 直接写入（v=当前版本；用于 delta 应用内部和初始化）

def _add_region(db, w, v, op):
    aabb = op["bounds_aabb"]
    if any(aabb["min"][i] >= aabb["max"][i] for i in range(3)):
        raise WorldError("bad_aabb", f"区域 {op['key']} 的包围盒无效")
    exists = db.scalar(select(WorldRegion).where(WorldRegion.world_id == w.id, WorldRegion.stable_key == op["key"],
                                                 _live(WorldRegion, v)))
    if exists:
        raise WorldError("region_exists", f"区域 {op['key']} 已存在")
    parent = op.get("parent_key")
    r = WorldRegion(id=new_id("wr"), world_id=w.id, stable_key=op["key"], name=op.get("name"),
                    kind=op.get("kind", "room"), bounds_aabb=aabb, anchor_xform=op.get("anchor_xform"),
                    lod=op.get("lod", "L0"), status=op.get("status", "provisional"), aliases=op.get("aliases"),
                    description=op.get("description"),
                    parent_id=region_by_key(db, w.id, parent, v).id if parent else None, valid_from_version=v)
    db.add(r)
    db.flush()
    _rasterize(db, w, r)
    return r


def _add_landmark(db, w, v, op):
    r = region_by_key(db, w.id, op["region_key"], v)
    if not geo.aabb_contains(r.bounds_aabb, op["pos"], margin=0.5):
        raise WorldError("landmark_outside_region", f"地标 {op['key']} 不在区域 {r.stable_key} 内")
    lm = WorldLandmark(id=new_id("wl"), region_id=r.id, key=op["key"], kind=op.get("kind", "spot"), pos=op["pos"],
                       facing_deg=float(op.get("facing_deg", 0.0)), size=op.get("size"),
                       description=op.get("description"), valid_from_version=v)
    db.add(lm)
    return lm


def _add_portal(db, w, v, op):
    a, b = region_by_key(db, w.id, op["from_key"], v), region_by_key(db, w.id, op["to_key"], v)
    p = WorldPortal(id=new_id("wp"), world_id=w.id, from_region_id=a.id, to_region_id=b.id,
                    landmark_id=op.get("landmark_id"), traversable=op.get("traversable", True), valid_from_version=v)
    db.add(p)
    return p


def _asset_by_key(db, w, key) -> WorldAsset:
    a = db.scalar(select(WorldAsset).where(WorldAsset.world_id == w.id, WorldAsset.key == key))
    if a is None:
        raise WorldError("asset_not_found", f"资产 {key} 不存在", 404)
    return a


def _add_asset(db, w, v, op):
    if db.scalar(select(WorldAsset).where(WorldAsset.world_id == w.id, WorldAsset.key == op["key"])):
        raise WorldError("asset_exists", f"资产 {op['key']} 已存在")
    a = WorldAsset(id=new_id("wa"), world_id=w.id, key=op["key"], kind=op["kind"], name=op.get("name"),
                   dims_m=op.get("dims_m"), front_axis=op.get("front_axis", "-Y"), rig=op.get("rig"),
                   mesh_path=op.get("mesh_path"), entity_id=op.get("entity_id"), meta=op.get("meta"))
    db.add(a)
    db.flush()
    return a


def _live_instance(db, r, key, v):
    return db.scalar(select(WorldInstance).where(WorldInstance.region_id == r.id, WorldInstance.key == key,
                                                 _live(WorldInstance, v)))


def _add_instance(db, w, v, op):
    r = region_by_key(db, w.id, op["region_key"], v)
    if _live_instance(db, r, op["key"], v):
        raise WorldError("instance_exists", f"实例 {op['key']} 已存在")
    a = _asset_by_key(db, w, op["asset_key"])
    i = WorldInstance(id=new_id("wi"), region_id=r.id, asset_id=a.id, key=op["key"], xform=op["xform"],
                      collision=op.get("collision", True), nav_flags=op.get("nav_flags"), valid_from_version=v)
    db.add(i)
    return i


def _close_instance(db, w, v, op):
    r = region_by_key(db, w.id, op["region_key"], v - 1)
    if r.locked:
        raise WorldError("region_locked", f"区域 {r.stable_key} 已锁定，不能改实例")
    old = _live_instance(db, r, op["key"], v - 1)
    if old is None:
        raise WorldError("instance_not_found", f"实例 {op['key']} 不存在", 404)
    old.valid_to_version = v - 1
    return r, old


def _move_instance(db, w, v, op):
    r, old = _close_instance(db, w, v, op)
    db.flush()
    i = WorldInstance(id=new_id("wi"), region_id=r.id, asset_id=old.asset_id, key=old.key, xform=op["xform"],
                      collision=old.collision, nav_flags=old.nav_flags, rev=old.rev + 1, valid_from_version=v)
    db.add(i)
    return i


def _remove_instance(db, w, v, op):
    return _close_instance(db, w, v, op)[1]


def _add_fact(db, w, v, op, chapter_id=None):
    f = WorldFact(id=new_id("wf"), world_id=w.id, subject_kind=op.get("subject_kind", "region"),
                  subject_key=op["subject_key"], predicate=op["predicate"], value=op.get("value"),
                  source=op.get("source", "inferred"), chapter_id=op.get("chapter_id") or chapter_id,
                  evidence_span=op.get("evidence_span"), confidence=float(op.get("confidence", 0.5)), version_n=v)
    if f.source == "explicit" and not f.evidence_span:
        raise WorldError("evidence_required", f"显式事实 {f.subject_key}.{f.predicate} 必须带原文出处")
    db.add(f)
    return f


def _lock_region(db, w, v, op):
    r = region_by_key(db, w.id, op["key"], v)
    r.locked, r.status = True, op.get("status", "confirmed")
    return r


_APPLY = {"add_region": _add_region, "add_landmark": _add_landmark, "add_portal": _add_portal,
          "add_asset": _add_asset, "add_instance": _add_instance, "move_instance": _move_instance,
          "remove_instance": _remove_instance, "lock_region": _lock_region}


def _touched_region_keys(ops: list[dict]) -> set[str]:
    return {op.get("region_key") or op.get("key") for op in ops
            if op["op"] in ("move_instance", "remove_instance", "add_instance", "add_landmark")}


# ---------------------------------------------------------------- 章节 delta

def propose_delta(db: Session, world_id: str, ops: list[dict], *, chapter_id: str | None = None,
                  base_version: int | None = None, note: str | None = None) -> WorldDelta:
    w = get_world(db, world_id)
    bad = [o.get("op") for o in ops if o.get("op") not in OPS]
    if bad:
        raise WorldError("unknown_op", f"未知的 delta 操作：{bad}")
    for o in ops:
        if o["op"] == "add_fact" and o.get("source") == "explicit" and not o.get("evidence_span"):
            raise WorldError("evidence_required", "显式事实必须带原文出处 evidence_span")
    d = WorldDelta(id=new_id("wd"), world_id=w.id, chapter_id=chapter_id, ops=ops, note=note,
                   base_version=base_version if base_version is not None else w.current_version)
    db.add(d)
    db.flush()
    return d


def apply_delta(db: Session, delta_id: str) -> WorldDelta:
    d = db.get(WorldDelta, delta_id)
    if d is None:
        raise WorldError("delta_not_found", "delta 不存在", 404)
    if d.status != "proposed":
        raise WorldError("delta_not_proposed", f"delta 状态为 {d.status}，不能应用", 409)
    w = get_world(db, d.world_id)
    if d.base_version != w.current_version:
        d.status = "conflict"
        d.report = {"reason": f"基于 v{d.base_version}，世界已到 v{w.current_version}"}
        db.flush()
        raise WorldError("delta_conflict", d.report["reason"], 409)
    v = w.current_version + 1
    # 先把旧版本的东西“延续”到新版本：valid_to 是开区间 OPEN_VERSION，天然延续，无需复制
    applied = []
    sp = db.begin_nested()
    try:
        for op in d.ops:
            kind = op["op"]
            if kind == "add_fact":
                _add_fact(db, w, v, op, d.chapter_id)
            else:
                _APPLY[kind](db, w, v, op)
            db.flush()
            applied.append(kind)
    except WorldError as exc:
        sp.rollback()
        d.status, d.report = "rejected", {"reason": str(exc), "code": exc.code, "applied_before_error": applied}
        db.flush()
        raise
    sp.commit()
    w.current_version = v
    db.add(WorldVersion(id=new_id("wv"), world_id=w.id, n=v, parent_n=v - 1, delta_id=d.id,
                        note=d.note or f"delta {d.id}"))
    stale = mark_stale_takes(db, w.id, _touched_region_keys(d.ops))
    d.status, d.result_version = "applied", v
    d.report = {"applied": applied, "stale_takes": stale}
    db.flush()
    return d


def reject_delta(db: Session, delta_id: str, reason: str = "") -> WorldDelta:
    d = db.get(WorldDelta, delta_id)
    if d is None:
        raise WorldError("delta_not_found", "delta 不存在", 404)
    if d.status != "proposed":
        raise WorldError("delta_not_proposed", f"delta 状态为 {d.status}", 409)
    d.status, d.report = "rejected", {"reason": reason or "rejected by user"}
    db.flush()
    return d


def mark_stale_takes(db: Session, world_id: str, region_keys: set[str]) -> list[str]:
    if not region_keys:
        return []
    perfs = db.scalars(select(WorldPerformance).where(WorldPerformance.world_id == world_id,
                                                      WorldPerformance.region_key.in_(region_keys))).all()
    out = []
    for p in perfs:
        for t in db.scalars(select(WorldTake).where(WorldTake.performance_id == p.id)):
            if t.status != "stale":
                t.status = "stale"
                out.append(t.id)
    return out


# ---------------------------------------------------------------- 查询与快照

def region_out(r: WorldRegion) -> dict[str, Any]:
    return {"id": r.id, "key": r.stable_key, "name": r.name, "kind": r.kind, "bounds_aabb": r.bounds_aabb,
            "lod": r.lod, "status": r.status, "locked": r.locked, "aliases": r.aliases or [],
            "valid_from_version": r.valid_from_version, "description": r.description}


def snapshot(db: Session, world_id: str, version: int | None = None, region_keys: list[str] | None = None
             ) -> dict[str, Any]:
    w = get_world(db, world_id)
    v = version or w.current_version
    if not 1 <= v <= w.current_version:
        raise WorldError("bad_version", f"版本只能在 1–{w.current_version}")
    q = select(WorldRegion).where(WorldRegion.world_id == w.id, _live(WorldRegion, v))
    if region_keys:
        q = q.where(WorldRegion.stable_key.in_(region_keys))
    regions = db.scalars(q.order_by(WorldRegion.stable_key)).all()
    rid = {r.id: r.stable_key for r in regions}
    assets = {a.id: a for a in db.scalars(select(WorldAsset).where(WorldAsset.world_id == w.id))}
    lms = db.scalars(select(WorldLandmark).where(WorldLandmark.region_id.in_(rid), _live(WorldLandmark, v))).all()
    ins = db.scalars(select(WorldInstance).where(WorldInstance.region_id.in_(rid), _live(WorldInstance, v))).all()
    chunks = db.scalars(select(WorldChunk).where(WorldChunk.region_id.in_(rid))).all()
    portals = db.scalars(select(WorldPortal).where(WorldPortal.world_id == w.id, _live(WorldPortal, v))).all()
    facts = db.scalars(select(WorldFact).where(WorldFact.world_id == w.id, WorldFact.version_n <= v)).all()
    return {
        "world": {"id": w.id, "title": w.title, "novel_id": w.novel_id, "units": w.units, "up_axis": w.up_axis,
                  "chunk_size_m": w.chunk_size_m, "current_version": w.current_version},
        "version": v,
        "regions": [region_out(r) for r in regions],
        "chunks": sorted([{"region": rid[c.region_id], "cx": c.cx, "cy": c.cy, "lod": c.lod, "rev": c.rev}
                          for c in chunks], key=lambda c: (c["region"], c["cx"], c["cy"])),
        "landmarks": [{"region": rid[l.region_id], "key": l.key, "kind": l.kind, "pos": l.pos,
                       "facing_deg": l.facing_deg, "size": l.size, "description": l.description} for l in lms],
        "instances": [{"region": rid[i.region_id], "key": i.key, "asset": assets[i.asset_id].key,
                       "kind": assets[i.asset_id].kind, "dims_m": assets[i.asset_id].dims_m, "xform": i.xform,
                       "collision": i.collision, "rev": i.rev,
                       "aabb": geo.instance_aabb(i.xform, assets[i.asset_id].dims_m or [1, 1, 1])} for i in ins],
        "portals": [{"from": rid.get(p.from_region_id), "to": rid.get(p.to_region_id),
                     "traversable": p.traversable} for p in portals],
        "assets": [{"key": a.key, "kind": a.kind, "name": a.name, "dims_m": a.dims_m, "rig": a.rig,
                    "entity_id": a.entity_id, "meta": a.meta} for a in assets.values()],
        "facts": [{"subject": f"{f.subject_kind}:{f.subject_key}", "predicate": f.predicate, "value": f.value,
                   "source": f.source, "chapter_id": f.chapter_id, "evidence_span": f.evidence_span,
                   "confidence": f.confidence, "version": f.version_n} for f in facts],
    }


def regions_near(db: Session, world_id: str, x: float, y: float, radius: float, version: int | None = None
                 ) -> list[dict[str, Any]]:
    """空间查询：先按 chunk 栅格粗筛，再按 AABB 距离精筛。"""
    w = get_world(db, world_id)
    v = version or w.current_version
    s = w.chunk_size_m
    box = {"min": [x - radius, y - radius, 0], "max": [x + radius, y + radius, 1]}
    cells = geo.chunks_for_aabb(box, s)
    xs, ys = [c[0] for c in cells], [c[1] for c in cells]
    rids = set(db.scalars(select(WorldChunk.region_id).where(
        WorldChunk.world_id == w.id, WorldChunk.cx.between(min(xs), max(xs)), WorldChunk.cy.between(min(ys), max(ys)))))
    regions = db.scalars(select(WorldRegion).where(WorldRegion.id.in_(rids), _live(WorldRegion, v))).all()
    hits = [(geo.aabb_dist2d(r.bounds_aabb, (x, y)), r) for r in regions]
    return [{**region_out(r), "distance_m": round(d, 3)} for d, r in sorted(hits, key=lambda h: h[0]) if d <= radius]


def search_regions(db: Session, world_id: str, q: str, version: int | None = None) -> list[dict[str, Any]]:
    w = get_world(db, world_id)
    v = version or w.current_version
    ql = q.lower()
    out = []
    for r in db.scalars(select(WorldRegion).where(WorldRegion.world_id == w.id, _live(WorldRegion, v))):
        hay = " ".join([r.stable_key, r.name or "", r.description or "", *(r.aliases or [])]).lower()
        if ql in hay:
            out.append(region_out(r))
    return out


# ---------------------------------------------------------------- 表演与 take

def create_performance(db: Session, world_id: str, *, scene_key: str, region_key: str, duration_ms: int,
                       tracks: dict, fps: int = 24, mood: dict | None = None,
                       director_scene_id: str | None = None) -> WorldPerformance:
    w = get_world(db, world_id)
    region_by_key(db, world_id, region_key)
    if duration_ms <= 0:
        raise WorldError("bad_duration", "表演时长必须大于 0")
    for actor, tr in tracks.items():
        keys = tr.get("keys") or []
        if not keys:
            raise WorldError("track_empty", f"{actor} 没有位置关键帧")
        ts = [k["t_ms"] for k in keys]
        if ts != sorted(ts):
            raise WorldError("track_unsorted", f"{actor} 的关键帧时间必须递增")
    p = WorldPerformance(id=new_id("wpf"), world_id=w.id, world_version=w.current_version, scene_key=scene_key,
                         region_key=region_key, duration_ms=duration_ms, fps=fps, tracks=tracks, mood=mood,
                         director_scene_id=director_scene_id)
    db.add(p)
    db.flush()
    return p


def performance_for_scene(db: Session, scene_key: str) -> WorldPerformance | None:
    return db.scalar(select(WorldPerformance).where(WorldPerformance.scene_key == scene_key)
                     .order_by(WorldPerformance.rev.desc(), WorldPerformance.created_at.desc()))


def add_take(db: Session, perf: WorldPerformance, *, shot_key: str, start_ms: int, end_ms: int, camera: dict,
             order_no: int = 0, route: str | None = None, fps: int = 8, focus: list | None = None,
             mood: str | None = None) -> WorldTake:
    if not 0 <= start_ms < end_ms <= perf.duration_ms:
        raise WorldError("take_out_of_range", f"take 时间窗 {start_ms}–{end_ms} 超出表演 0–{perf.duration_ms}")
    if fps not in (4, 8, 12, 24, 25):
        raise WorldError("bad_fps", "fps 只能是 4/8/12/24/25（与动态漫画参数一致）")
    for k in ("pos", "target"):
        if len(camera.get(k) or []) != 3:
            raise WorldError("bad_camera", f"camera.{k} 需要 [x,y,z]")
    t = WorldTake(id=new_id("wtk"), performance_id=perf.id, shot_key=shot_key, order_no=order_no,
                  start_ms=start_ms, end_ms=end_ms, camera=camera, route=route, fps=fps, focus=focus, mood=mood,
                  frozen_deps={"world_version": perf.world_version, "performance_rev": perf.rev,
                               "region_key": perf.region_key})
    db.add(t)
    db.flush()
    return t


def take_out(t: WorldTake) -> dict[str, Any]:
    return {"id": t.id, "shot_key": t.shot_key, "order_no": t.order_no, "start_ms": t.start_ms, "end_ms": t.end_ms,
            "camera": t.camera, "route": t.route, "fps": t.fps, "focus": t.focus or [], "mood": t.mood,
            "frozen_deps": t.frozen_deps, "status": t.status, "outputs": t.outputs}


def performance_out(p: WorldPerformance, takes: list[WorldTake] | None = None) -> dict[str, Any]:
    out = {"id": p.id, "world_id": p.world_id, "world_version": p.world_version, "scene_key": p.scene_key,
           "region_key": p.region_key, "duration_ms": p.duration_ms, "fps": p.fps, "tracks": p.tracks,
           "mood": p.mood, "director_scene_id": p.director_scene_id, "check_report": p.check_report, "rev": p.rev}
    if takes is not None:
        out["takes"] = [take_out(t) for t in sorted(takes, key=lambda t: t.order_no)]
    return out
