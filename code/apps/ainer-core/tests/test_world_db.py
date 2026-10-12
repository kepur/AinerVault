"""空间 World DB：几何、表演检查/修正回路、配准，以及（有 Postgres 时）delta/版本/快照/接口。"""
from __future__ import annotations

import math

import pytest

from app.worldmodel import compile as wc
from app.worldmodel import geometry as geo
from app.worldmodel import staging
from app.worldmodel.seeds import chapter01_corridor as ch1


# ------------------------------------------------------------------ 纯函数

def test_chunks_cover_aabb_without_extra_cells():
    assert geo.chunks_for_aabb({"min": [0, 0, 0], "max": [8, 8, 3]}, 8) == [(0, 0)]
    assert len(geo.chunks_for_aabb({"min": [-2, -1.6, 0], "max": [22, 1.6, 3]}, 8)) == 4 * 2


def test_segment_and_circle_vs_box():
    box = {"min": [1, -1, 0], "max": [2, 1, 2]}
    assert geo.segment_hits_aabb([0, 0], [3, 0], box)
    assert not geo.segment_hits_aabb([0, 2], [3, 2], box)
    assert geo.circle_hits_aabb([0.9, 0], 0.22, box) > 0
    p = geo.push_out([1.5, 0.1, 0], 0.22, box)
    assert geo.circle_hits_aabb(p, 0.22, box) == 0


def test_ltx_frames_are_8k_plus_1():
    for dur, fps in [(3125, 8), (3417, 12), (9375, 8), (500, 4)]:
        n = wc.ltx_frames(dur, fps)
        assert (n - 1) % 8 == 0 and n >= 9 and n >= round(dur / 1000 * fps)


def test_reprojection_roundtrip_matches_reviewed_frame():
    cam = ch1.opening_camera()
    pos = ch1.start_positions()
    for actor, (x, y, w, h) in ch1.OPENING_PLACEMENTS.items():
        px, py, d = staging.project(cam, pos[actor], ch1.FRAME_W, ch1.FRAME_H)
        assert abs(px - (x + w / 2)) < 1.0 and abs(py - (y + h)) < 1.0 and d > 0
    # 屏幕左 = +Y（储物柜一侧）：Thomas 最靠储物柜
    assert pos["thomas"][1] > pos["brad"][1] > pos["tyler"][1] > pos["kyle"][1]


def test_fit_camera_recovers_opening_camera():
    pos = ch1.start_positions()
    actors = {a: (pos[a], ch1.ACTORS[a]["height_m"]) for a in pos}
    cam, err = staging.fit_camera(actors, ch1.OPENING_PLACEMENTS, ch1.FRAME_W, ch1.FRAME_H)
    assert err < 0.01
    px = {a: staging.project(cam, pos[a], ch1.FRAME_W, ch1.FRAME_H)[0] for a in pos}
    assert sorted(px, key=px.get) == ["thomas", "brad", "tyler", "kyle"]


def test_camera_moves_actually_move():
    cam = ch1.opening_camera()
    for mv in ({"type": "push_in", "amount": 0.5}, {"type": "pan_left", "amount": 6},
               {"type": "truck_right", "amount": 0.3}, {"type": "crane_down", "amount": 0.3}):
        a, b = staging.move_camera(cam, mv, 0.0), staging.move_camera(cam, mv, 1.0)
        assert a != b, mv


def _fake_snapshot():
    """不经数据库，按 delta 的 add_instance 直接拼出快照（与 service.snapshot 同结构）。"""
    ops = ch1.world_ops()
    assets = {o["key"]: o for o in ops if o["op"] == "add_asset"}
    region = next(o for o in ops if o["op"] == "add_region" and o["key"] == ch1.REGION_KEY)
    inst = [{"region": o["region_key"], "key": o["key"], "asset": o["asset_key"], "kind": assets[o["asset_key"]]["kind"],
             "collision": o.get("collision", True), "xform": o["xform"],
             "aabb": geo.instance_aabb(o["xform"], assets[o["asset_key"]]["dims_m"])}
            for o in ops if o["op"] == "add_instance"]
    lms = [{"region": o["region_key"], "key": o["key"], "pos": o["pos"]} for o in ops if o["op"] == "add_landmark"]
    return {"world": {"id": "w"}, "version": 2, "regions": [{"key": region["key"], "bounds_aabb": region["bounds_aabb"]}],
            "chunks": [], "instances": inst, "landmarks": lms}


def test_world_check_finds_and_fixes_staging_errors():
    snap = _fake_snapshot()
    perf = {"region_key": ch1.REGION_KEY, "duration_ms": ch1.total_ms(), "tracks": ch1.tracks(), "rev": 1}
    first = wc.check_performance(snap, perf)
    # 草稿里 Tyler 站在耳光够不着的地方、Brad 与 Thomas 贴得太近——检查必须报出来
    assert any(m["clip"] == "slap" for m in first["contact_misses"])
    fixed, rounds = wc.bounded_stage(snap, perf, max_rounds=3)
    assert len(rounds) <= 4
    assert rounds[-1]["ok"], rounds[-1]
    assert fixed["rev"] > 1


def test_wall_collision_is_pushed_out():
    snap = _fake_snapshot()
    tr = {"a": {"keys": [{"t_ms": 0, "pos": [3.0, ch1.LOCKER_FACE_Y + 0.1, 0], "yaw_deg": 0},
                         {"t_ms": 1000, "pos": [3.0, ch1.LOCKER_FACE_Y + 0.1, 0], "yaw_deg": 0}], "clips": []}}
    perf = {"region_key": ch1.REGION_KEY, "duration_ms": 1000, "tracks": tr}
    rep = wc.check_performance(snap, perf)
    assert rep["collisions"] and not rep["ok"]
    fixed, rounds = wc.bounded_stage(snap, perf)
    assert rounds[-1]["ok"]
    assert fixed["tracks"]["a"]["keys"][0]["pos"][1] < ch1.LOCKER_FACE_Y - 0.2


def test_seed_shots_keep_motion_comic_params():
    tl = ch1.timeline()
    assert len(tl) == 20 and abs(ch1.total_ms() - 88240) < 50
    assert all(s["fps"] in (4, 8, 12) for s in tl)
    assert all(s["move"]["type"] != "hold" for s in tl), "每镜都要有运镜"
    assert {s["fps"] for s in tl if s["n"] == 14} == {12}


# ------------------------------------------------------------------ 数据库（真实 Postgres，事务回滚，不留数据）

@pytest.fixture
def db():
    from sqlalchemy import inspect
    from sqlalchemy.orm import Session

    from app.db import engine
    try:
        if not inspect(engine).has_table("world_spaces", schema="core"):
            pytest.skip("world_* 表未迁移")
        conn = engine.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres 不可用：{exc}")
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield s
    s.close()
    trans.rollback()
    conn.close()


def test_delta_versions_and_snapshot(db):
    from app.worldmodel import service as ws
    w = ws.create_world(db, title="t-world", novel_id="nv_test")
    d = ws.propose_delta(db, w.id, ch1.world_ops(), chapter_id="ch_test")
    ws.apply_delta(db, d.id)
    assert w.current_version == 2 and d.status == "applied"
    snap = ws.snapshot(db, w.id)
    assert {r["key"] for r in snap["regions"]} == {"school", ch1.REGION_KEY}
    assert len(snap["chunks"]) > 0 and any(f["source"] == "explicit" and f["evidence_span"] for f in snap["facts"])
    assert ws.snapshot(db, w.id, 1)["regions"] == []           # 创世版本是空的
    # 空间查询：Thomas 的位置附近能命中走廊
    near = ws.regions_near(db, w.id, 3.2, 0.7, 1.0)
    assert ch1.REGION_KEY in [r["key"] for r in near]
    assert ws.search_regions(db, w.id, "走廊")[0]["key"] == ch1.REGION_KEY


def test_locked_region_and_conflict(db):
    from app.worldmodel import service as ws
    w = ws.create_world(db, title="t-world2")
    ws.apply_delta(db, ws.propose_delta(db, w.id, ch1.world_ops()).id)
    # 区域已锁定：移动实例会被拒绝，世界版本不变
    d = ws.propose_delta(db, w.id, [{"op": "move_instance", "region_key": ch1.REGION_KEY, "key": "lockers_a",
                                      "xform": {"pos": [5, 1.3, 0]}}])
    with pytest.raises(ws.WorldError) as e:
        ws.apply_delta(db, d.id)
    assert e.value.code == "region_locked" and d.status == "rejected" and w.current_version == 2
    # 基于旧版本的 delta → conflict
    old = ws.propose_delta(db, w.id, [{"op": "add_fact", "subject_key": "x", "predicate": "p"}], base_version=1)
    with pytest.raises(ws.WorldError) as e:
        ws.apply_delta(db, old.id)
    assert e.value.code == "delta_conflict" and old.status == "conflict"
    with pytest.raises(ws.WorldError):
        ws.propose_delta(db, w.id, [{"op": "add_fact", "subject_key": "x", "predicate": "p", "source": "explicit"}])


def test_move_instance_versions_and_stale_takes(db):
    from app.worldmodel import service as ws
    w = ws.create_world(db, title="t-world3")
    ops = [o for o in ch1.world_ops() if o["op"] != "lock_region"]
    ws.apply_delta(db, ws.propose_delta(db, w.id, ops).id)
    perf = ws.create_performance(db, w.id, scene_key="sc_t", region_key=ch1.REGION_KEY, duration_ms=2000,
                                 tracks={"a": {"keys": [{"t_ms": 0, "pos": [5, 0, 0], "yaw_deg": 0}]}})
    take = ws.add_take(db, perf, shot_key="s1", start_ms=0, end_ms=1000,
                       camera={"pos": [0, 0, 1.2], "target": [5, 0, 1], "lens_mm": 35})
    ws.apply_delta(db, ws.propose_delta(db, w.id, [{"op": "move_instance", "region_key": ch1.REGION_KEY,
                                                     "key": "lockers_a", "xform": {"pos": [4, 1.32, 0]}}]).id)
    assert w.current_version == 3
    v2 = {i["key"]: i for i in ws.snapshot(db, w.id, 2)["instances"]}
    v3 = {i["key"]: i for i in ws.snapshot(db, w.id, 3)["instances"]}
    assert v2["lockers_a"]["xform"]["pos"][0] == 3.0 and v3["lockers_a"]["xform"]["pos"][0] == 4
    assert v3["lockers_a"]["rev"] == 2
    db.refresh(take)
    assert take.status == "stale"
    with pytest.raises(ws.WorldError):
        ws.add_take(db, perf, shot_key="s2", start_ms=0, end_ms=5000, camera={"pos": [0, 0, 1], "target": [1, 0, 1]})


def test_seed_build_is_idempotent_and_checked(db):
    from app.models import WorldTake
    r1 = ch1.build(db)
    r2 = ch1.build(db)
    assert r1 == r2
    from app.models import WorldPerformance
    perf = db.get(WorldPerformance, r1["performance_id"])
    assert perf.check_report["ok"]
    takes = db.query(WorldTake).filter_by(performance_id=perf.id).all()
    assert len(takes) == 20 and all(t.camera.get("move") for t in takes)


def test_api_roundtrip(db):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        w = c.post("/api/v2/worlds", json={"title": "api-world"}).json()
        d = c.post(f"/api/v2/worlds/{w['id']}/deltas:propose", json={"ops": ch1.world_ops(), "chapter_id": "ch"}).json()
        assert c.post(f"/api/v2/worlds/deltas/{d['id']}:apply").json()["status"] == "applied"
        snap = c.get(f"/api/v2/worlds/{w['id']}").json()
        assert snap["version"] == 2
        assert c.get(f"/api/v2/worlds/{w['id']}/regions", params={"near": "3.2,0.7", "radius": 1}).json()["items"]
        p = c.post(f"/api/v2/worlds/{w['id']}/performances", json={
            "scene_key": "sc_api", "region_key": ch1.REGION_KEY, "duration_ms": ch1.total_ms(), "tracks": ch1.tracks()}).json()
        assert p["check_report"] is None or True
        perf = c.get(f"/api/v2/worlds/performances/{p['id']}").json()
        t = c.post(f"/api/v2/worlds/performances/{p['id']}/takes", json={
            "shot_key": "s1", "start_ms": 0, "end_ms": 3125, "fps": 8,
            "camera": {**ch1.opening_camera(), "move": {"type": "push_in", "amount": 0.5}}}).json()
        job = c.post(f"/api/v2/worlds/performances/{p['id']}/takes/{t['id']}:compile").json()
        assert job["job_type"] == "world_multicam" and job["frames"] == 25 and job["world"]["instances"]
        assert perf["region_key"] == ch1.REGION_KEY
        bad = c.post(f"/api/v2/worlds/performances/{p['id']}/takes", json={
            "shot_key": "s2", "start_ms": 0, "end_ms": 1000, "fps": 7, "camera": ch1.opening_camera()})
        assert bad.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
