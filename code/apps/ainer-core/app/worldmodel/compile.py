"""表演检查与编译：World 快照 + 一场一演 + take → Blender 多机位任务（world_take.json）。

check_performance 是纯 Python 的确定性检查（与 Blender 侧 world_check 同口径，Blender 侧额外查相机遮挡），
correct 按报告做确定性修正（推出墙体、拉开穿插、把接触动作的人拉到接触距离），bounded_stage 最多跑 N 轮。
"""
from __future__ import annotations

import copy
import math
from typing import Any

from app.worldmodel import geometry as geo

BODY_R = 0.22          # 人物俯视半径（m）
MIN_GAP = 0.45         # 两人中心最小间距（m）——小于此即穿插
CONTACT_CLIPS = {"slap": 0.75, "punch": 0.8, "kick": 0.95, "grab": 0.7, "push": 0.75, "search_pockets": 0.6,
                 "take_money": 0.65}
CHECK_STEP_MS = 125


def _collision_boxes(snap: dict) -> list[dict]:
    return [i for i in snap["instances"] if i.get("collision") and i["kind"] != "floor"]


def _region_aabb(snap: dict, key: str) -> dict:
    return next(r["bounds_aabb"] for r in snap["regions"] if r["key"] == key)


def _landmark(snap: dict, key: str) -> dict | None:
    return next((l for l in snap["landmarks"] if l["key"] == key), None)


def check_performance(snap: dict, perf: dict, step_ms: int = CHECK_STEP_MS) -> dict[str, Any]:
    boxes = _collision_boxes(snap)
    region = _region_aabb(snap, perf["region_key"])
    tracks = perf["tracks"]
    rep: dict[str, list] = {"collisions": [], "interpenetrations": [], "out_of_region": [], "unreachable": [],
                            "contact_misses": [], "unknown_landmarks": []}
    for t in geo.iter_times(0, perf["duration_ms"], step_ms):
        pos = {a: geo.lerp_track(tr["keys"], t)[0] for a, tr in tracks.items()}
        for a, p in pos.items():
            for b in boxes:
                depth = geo.circle_hits_aabb(p, BODY_R, b["aabb"])
                if depth > 0.01:
                    rep["collisions"].append({"actor": a, "t_ms": t, "with": b["key"], "depth_m": round(depth, 3)})
            if not geo.aabb_contains(region, p, margin=0.05):
                rep["out_of_region"].append({"actor": a, "t_ms": t, "pos": [round(x, 2) for x in p]})
        names = sorted(pos)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                d = math.dist(pos[a][:2], pos[b][:2])
                if d < MIN_GAP:
                    rep["interpenetrations"].append({"actors": [a, b], "t_ms": t, "gap_m": round(d, 3)})
    for a, tr in tracks.items():
        keys = tr["keys"]
        for k0, k1 in zip(keys, keys[1:]):
            for b in boxes:
                if geo.segment_hits_aabb(k0["pos"], k1["pos"], b["aabb"], BODY_R * 0.9):
                    rep["unreachable"].append({"actor": a, "from_ms": k0["t_ms"], "to_ms": k1["t_ms"], "blocked_by": b["key"]})
        for c in [x for x in (tr.get("clips") or []) if isinstance(x, dict)]:
            if c.get("landmark") and _landmark(snap, c["landmark"]) is None:
                rep["unknown_landmarks"].append({"actor": a, "landmark": c["landmark"]})
            reach = CONTACT_CLIPS.get(c["clip"])
            tgt = c.get("target")
            if reach and tgt in tracks:
                mid = (c["start_ms"] + c["end_ms"]) / 2
                pa = geo.lerp_track(keys, mid)[0]
                pb = geo.lerp_track(tracks[tgt]["keys"], mid)[0]
                d = math.dist(pa[:2], pb[:2])
                if d > reach + 0.05:
                    rep["contact_misses"].append({"actor": a, "target": tgt, "clip": c["clip"], "t_ms": mid,
                                                  "distance_m": round(d, 3), "reach_m": reach})
    # 去重：同一演员同一障碍只报第一次
    seen, coll = set(), []
    for c in rep["collisions"]:
        k = (c["actor"], c["with"])
        if k not in seen:
            seen.add(k)
            coll.append(c)
    rep["collisions"] = coll
    rep["ok"] = not any(v for k, v in rep.items() if k != "ok")
    return rep


def correct(snap: dict, perf: dict, rep: dict) -> dict:
    """确定性修正，返回新的 perf（不改入参）。"""
    p = copy.deepcopy(perf)
    tracks = p["tracks"]
    boxes = {b["key"]: b for b in _collision_boxes(snap)}
    region = _region_aabb(snap, p["region_key"])
    for c in rep["collisions"]:
        b = boxes[c["with"]]
        for k in tracks[c["actor"]]["keys"]:
            if geo.circle_hits_aabb(k["pos"], BODY_R, b["aabb"]) > 0.0:
                new = geo.push_out(k["pos"], BODY_R, b["aabb"], 0.05)
                k["pos"] = [round(new[0], 3), round(new[1], 3), k["pos"][2]]
    for o in rep["out_of_region"]:
        lo, hi = region["min"], region["max"]
        for k in tracks[o["actor"]]["keys"]:
            k["pos"][0] = min(max(k["pos"][0], lo[0] + BODY_R), hi[0] - BODY_R)
            k["pos"][1] = min(max(k["pos"][1], lo[1] + BODY_R), hi[1] - BODY_R)
    def _free(pt):
        return all(geo.circle_hits_aabb(pt, BODY_R, b["aabb"]) <= 0.0 for b in boxes.values())

    for it in rep["interpenetrations"]:
        # 两人贴太近：沿连线把其中一人推开到 MIN_GAP；先试后者，推进墙里就改推前者
        t = it["t_ms"]
        for mover, anchor in (tuple(it["actors"][::-1]), tuple(it["actors"])):
            pm, yaw = geo.lerp_track(tracks[mover]["keys"], t)
            pa = geo.lerp_track(tracks[anchor]["keys"], t)[0]
            vx, vy = pm[0] - pa[0], pm[1] - pa[1]
            n = math.hypot(vx, vy) or 1.0
            cand = [round(pa[0] + vx / n * (MIN_GAP + 0.1), 3), round(pa[1] + vy / n * (MIN_GAP + 0.1), 3), pm[2]]
            if _free(cand):
                keys = [k for k in tracks[mover]["keys"] if k["t_ms"] != t]
                keys.append({"t_ms": t, "pos": cand, "yaw_deg": round(yaw, 1)})
                tracks[mover]["keys"] = sorted(keys, key=lambda k: k["t_ms"])
                break

    for m in rep["contact_misses"]:
        # 接触动作前插入一个“上前一步”关键帧，停在 reach*0.85
        tr = tracks[m["actor"]]
        tgt = geo.lerp_track(tracks[m["target"]]["keys"], m["t_ms"])[0]
        cur = geo.lerp_track(tr["keys"], m["t_ms"])[0]
        vx, vy = cur[0] - tgt[0], cur[1] - tgt[1]
        n = math.hypot(vx, vy) or 1.0
        stand = [round(tgt[0] + vx / n * m["reach_m"] * 0.85, 3), round(tgt[1] + vy / n * m["reach_m"] * 0.85, 3), cur[2]]
        clip = next(c for c in tr["clips"] if c["clip"] == m["clip"] and c.get("target") == m["target"])
        t_arrive = max(0, clip["start_ms"] - 1)
        yaw = math.degrees(math.atan2(-(tgt[0] - stand[0]), (tgt[1] - stand[1])))  # 面朝目标（-Y 为正面时的偏航）
        keys = [k for k in tr["keys"] if not (t_arrive - 400 < k["t_ms"] <= clip["end_ms"])]
        keys += [{"t_ms": t_arrive, "pos": stand, "yaw_deg": round(yaw, 1)},
                 {"t_ms": clip["end_ms"], "pos": stand, "yaw_deg": round(yaw, 1)}]
        tr["keys"] = sorted(keys, key=lambda k: k["t_ms"])
    p["rev"] = int(p.get("rev", 1)) + 1
    return p


def bounded_stage(snap: dict, perf: dict, max_rounds: int = 3) -> tuple[dict, list[dict]]:
    """检查 → 修正 → 再查，最多 max_rounds 轮。返回 (最终表演, 每轮报告)。"""
    rounds = []
    cur = perf
    for _ in range(max_rounds + 1):
        rep = check_performance(snap, cur)
        rounds.append(rep)
        if rep["ok"] or len(rounds) > max_rounds:
            break
        cur = correct(snap, cur, rep)
    return cur, rounds


def ltx_frames(dur_ms: int, fps: int) -> int:
    """LTX 要求 8k+1 帧：向上取整到 8k+1，至少 9 帧。"""
    n = max(1, round(dur_ms / 1000 * fps))
    return max(9, ((n - 1 + 7) // 8) * 8 + 1)


def compile_take_job(snap: dict, perf: dict, take: dict, *, out_dir: str, resolution: tuple[int, int],
                     passes: list[str] | None = None, actors_meta: dict | None = None) -> dict[str, Any]:
    """Blender world_multicam worker 的输入：一个区域的几何 + 整场表演 + 本镜相机与时间窗。"""
    fps = int(take["fps"])
    dur = take["end_ms"] - take["start_ms"]
    frames = ltx_frames(dur, fps)
    region = next(r for r in snap["regions"] if r["key"] == perf["region_key"])
    from app.worldmodel import motion, staging

    cam0 = {k: take["camera"][k] for k in ("pos", "target", "lens_mm") if k in take["camera"]}
    move = take["camera"].get("move") or {"type": "hold"}
    cams, acts = [], {a: [] for a in perf["tracks"]}
    for f in range(frames):
        u = f / max(1, frames - 1)
        t = take["start_ms"] + min(dur, f * 1000.0 / fps)
        cams.append(staging.move_camera(cam0, move, u * u * (3 - 2 * u)))
        for a, tr in perf["tracks"].items():
            pos, yaw = geo.lerp_track(tr["keys"], t)
            bones, dz = motion.pose_at(tr.get("clips") or [], t)
            acts[a].append({"t_ms": round(t), "pos": [round(x, 4) for x in pos], "yaw_deg": round(yaw, 2),
                            "bones": bones, "hips_dz": dz})
    return {
        "job_type": "world_multicam",
        "out_dir": out_dir,
        "resolution": list(resolution),
        "passes": passes or ["clay", "depth", "pose", "idmask"],
        "fps": fps,
        "frames": frames,
        "start_ms": take["start_ms"],
        "end_ms": take["end_ms"],
        "world": {"id": snap["world"]["id"], "version": snap["version"], "region": region,
                  "chunks": [c for c in snap["chunks"] if c["region"] == region["key"]],
                  "instances": [i for i in snap["instances"] if i["region"] == region["key"]],
                  "landmarks": [l for l in snap["landmarks"] if l["region"] == region["key"]]},
        "performance": {"id": perf.get("id"), "rev": perf.get("rev", 1), "duration_ms": perf["duration_ms"]},
        "actors": {a: {**(actors_meta or {}).get(a, {}), "frames": acts[a]} for a in acts},
        "camera": take["camera"],
        "camera_frames": cams,
        "focus": take.get("focus") or [],
        "take": {"id": take.get("id"), "shot_key": take["shot_key"]},
    }
