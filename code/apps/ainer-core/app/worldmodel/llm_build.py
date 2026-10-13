"""LLM 章节 → World DB 增量（delta）与整场表演草稿。

结果只**提议**（propose_delta），不自动应用：人审或 API :apply 之后才进世界。表演草稿交 bounded_stage 做碰撞/可达修正。
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.worldmodel import motion
from app.worldmodel import service as ws

OPS_SCHEMA = {
    "type": "object", "required": ["ops"],
    "properties": {"ops": {"type": "array", "items": {
        "type": "object", "required": ["op"],
        "properties": {"op": {"type": "string", "enum": ["add_region", "add_landmark", "add_asset", "add_instance", "add_fact"]},
                       "key": {"type": "string"}, "kind": {"type": "string"}, "name": {"type": "string"},
                       "region_key": {"type": "string"}, "asset_key": {"type": "string"},
                       "bounds_aabb": {"type": "object"}, "dims_m": {"type": "array", "items": {"type": "number"}},
                       "pos": {"type": "array", "items": {"type": "number"}}, "xform": {"type": "object"},
                       "subject_kind": {"type": "string"}, "subject_key": {"type": "string"},
                       "predicate": {"type": "string"}, "value": {}, "evidence_span": {"type": "string"},
                       "source": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}}}}}},
}

PERF_SCHEMA = {
    "type": "object", "required": ["tracks"],
    "properties": {"tracks": {"type": "object", "additionalProperties": {
        "type": "object", "required": ["keys"],
        "properties": {"keys": {"type": "array", "items": {"type": "object", "required": ["t_ms", "pos"],
                                                              "properties": {"t_ms": {"type": "integer"},
                                                                             "pos": {"type": "array", "items": {"type": "number"}},
                                                                             "yaw_deg": {"type": "number"}}}},
                       "clips": {"type": "array", "items": {"type": "object", "required": ["clip", "start_ms", "end_ms"],
                                                             "properties": {"clip": {"type": "string", "enum": sorted(motion.KNOWN_CLIPS)},
                                                                            "start_ms": {"type": "integer"},
                                                                            "end_ms": {"type": "integer"}}}}}}}},
}

SYSTEM_WORLD = ("You extract the physical places of a novel chapter into a spatial world database (metres, Z up). "
                "Only add what the text states or clearly implies; every add_fact needs a verbatim evidence_span from the text. "
                "Reuse existing region keys when the place already exists. Rough greybox sizes are fine.")
SYSTEM_PERF = ("You stage one scene as a single continuous performance in metres on the given region floor plan. "
               "Give each actor position keys over time and body clips from the allowed list. Keep people >0.45 m apart "
               "and inside the region; contact actions need the actors within arm's reach.")


def _chat(db: Session, chat: Callable | None):
    if chat is not None:
        return chat
    from app.pipelines.base import chat_json

    def _c(messages, schema, **kw):
        return chat_json(db, messages, schema, purpose="world_build", **kw)[0]
    return _c


def propose_chapter_delta(db: Session, world_id: str, *, chapter_id: str, text: str, chat: Callable | None = None):
    snap = ws.snapshot(db, world_id)
    have = [{"key": r["key"], "name": r["name"], "kind": r["kind"], "bounds": r["bounds_aabb"]} for r in snap["regions"]]
    out = _chat(db, chat)([{"role": "system", "content": SYSTEM_WORLD},
                           {"role": "user", "content": f"Existing regions: {have}\n\nChapter text:\n{text[:12000]}"}],
                          OPS_SCHEMA, chapter_id=chapter_id)
    ops = [o for o in out.get("ops", []) if o.get("op") != "add_fact" or o.get("evidence_span")]
    return ws.propose_delta(db, world_id, ops, chapter_id=chapter_id, note="llm chapter extraction")


def draft_performance(db: Session, world_id: str, *, region_key: str, scene_text: str, actors: dict[str, Any],
                      duration_ms: int, chat: Callable | None = None) -> dict:
    snap = ws.snapshot(db, world_id, region_keys=[region_key])
    region = next(r for r in snap["regions"] if r["key"] == region_key)
    inst = [{"key": i["key"], "pos": i["xform"].get("pos")} for i in snap["instances"] if i["region"] == region_key]
    out = _chat(db, chat)([{"role": "system", "content": SYSTEM_PERF},
                           {"role": "user", "content": f"Region bounds {region['bounds_aabb']}; obstacles {inst}; "
                                                       f"actors {list(actors)}; duration_ms {duration_ms}.\n\nScene:\n{scene_text[:8000]}"}],
                          PERF_SCHEMA)
    tracks = {}
    for a, tr in (out.get("tracks") or {}).items():
        if a not in actors or not isinstance(tr, dict):
            continue
        tracks[a] = {"entity_id": actors[a].get("entity_id"), "keys": tr.get("keys") or [],
                     "clips": [c for c in (tr.get("clips") or []) if isinstance(c, dict) and c.get("clip") in motion.KNOWN_CLIPS]}
    return {"region_key": region_key, "duration_ms": duration_ms, "tracks": tracks, "rev": 1}
