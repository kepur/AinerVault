"""Semantic state replay. Does not claim to simulate contact, IK or dynamics."""
from __future__ import annotations

from copy import deepcopy
from itertools import groupby

from app.production.service import ProductionError
from app.production.stage_schema import StageContent


def replay(content: StageContent, time_ms: float) -> dict:
    actors = {a.id for a in content.protocol.actors}
    props = {p.id for p in content.protocol.props}
    instances = actors | props
    state = {i: {} for i in instances}
    for instance, values in content.initial_state.items():
        if instance not in instances:
            raise ProductionError("stage_instance_missing", f"初始状态引用不存在的实例：{instance}")
        state[instance] = deepcopy(values)

    def check_holders():
        occupied = {}
        for instance in props:
            holder, slot = state[instance].get("held_by"), state[instance].get("slot")
            if holder is None:
                if slot is not None:
                    raise ProductionError("stage_holding_conflict", f"{instance} 没有持有人却占有手部槽位")
                continue
            if holder not in actors or slot not in ("left_hand", "right_hand"):
                raise ProductionError("stage_holding_invalid", f"{instance} 必须指定有效演员和身体左右手")
            if (holder, slot) in occupied:
                raise ProductionError("stage_holding_conflict", f"{holder}/{slot} 同时持有两件物品")
            occupied[holder, slot] = instance

    check_holders()
    occurred = set()
    ordered = []
    planned = set()
    for when, group in groupby(sorted(content.events, key=lambda e: (e.time_ms, e.id)), key=lambda e: e.time_ms):
        if when > time_ms:
            break
        pending = list(group)
        written = {}
        while pending:
            ready = next((e for e in pending if set(e.requires) <= planned), None)
            if ready is None:
                raise ProductionError("stage_event_precondition", "同刻事件有环路、缺失依赖或引用尚未发生的事件")
            for change in ready.changes:
                key = (change.instance_id, change.key)
                previous = written.get(key)
                if previous and previous not in ready.requires:
                    raise ProductionError("stage_event_conflict", "同刻事件重复修改同一状态，请明确先后依赖或合成一次原子事件")
                written[key] = ready.id
            ordered.append(ready)
            planned.add(ready.id)
            pending.remove(ready)
    for event in ordered:
        if not set(event.requires) <= occurred:
            raise ProductionError("stage_event_precondition", f"{event.id} 的前置事件尚未发生")
        for condition in event.conditions:
            if condition.instance_id not in instances:
                raise ProductionError("stage_instance_missing", f"{event.id} 引用不存在的实例")
            if state[condition.instance_id].get(condition.key) != condition.value:
                raise ProductionError("stage_event_precondition", f"{event.id} 前提不成立：{condition.instance_id}/{condition.key}")
        touched = set()
        for change in event.changes:
            if change.instance_id not in instances:
                raise ProductionError("stage_instance_missing", f"{event.id} 引用不存在的实例")
            key = (change.instance_id, change.key)
            if key in touched:
                raise ProductionError("stage_event_conflict", f"{event.id} 重复写入同一状态字段")
            touched.add(key)
            state[change.instance_id][change.key] = deepcopy(change.value)
        # A transfer is atomic: all release/acquire changes are applied before checking slots.
        check_holders()
        occurred.add(event.id)
    return {"instances": state, "occurred_events": sorted(occurred)}


def validate(content: StageContent) -> None:
    protocol = content.protocol
    things = {a.id for a in protocol.actors} | {p.id for p in protocol.props}
    cams = {c.id for c in protocol.cameras}
    duration = round(protocol.meta.duration_sec * 1000)
    for items, what in ((protocol.cameras, "机位"), (content.events, "事件"), (content.coverages, "镜头")):
        ids = [x.id for x in items]
        if len(set(ids)) != len(ids):
            raise ProductionError("stage_duplicate_id", f"{what} ID 重复")
    if not set(content.bindings) <= things:
        raise ProductionError("stage_instance_missing", "素材绑定必须指向真实舞台实例")
    for instance in [*protocol.actors, *protocol.props]:
        chain = {instance.id}
        parent = instance.parent
        while parent:
            if parent not in things or parent in chain:
                raise ProductionError("stage_parent_invalid", "实例父级不存在或存在环路")
            chain.add(parent)
            parent = next(x.parent for x in [*protocol.actors, *protocol.props] if x.id == parent)
    for c in protocol.cameras:
        if not c.keys:
            raise ProductionError("stage_camera_keys_missing", f"{c.id} 需明确机位关键帧，不能用默认相机替代")
        times = [k.t for k in c.keys]
        if len(times) != len(set(times)) or any(t > protocol.meta.duration_sec for t in times):
            raise ProductionError("stage_camera_time_invalid", f"{c.id} 机位时刻重复或超出舞台时长")
        for key in c.keys:
            if sum(x is not None for x in (key.position, key.follow, key.orbit)) != 1:
                raise ProductionError("stage_camera_position_invalid", "机位关键帧必须且只能选世界位置、跟拍或环绕")
            look = key.look_at
            target = look if isinstance(look, str) else look.get("target") if isinstance(look, dict) else None
            if target and target not in things:
                raise ProductionError("stage_camera_target_missing", f"机位视点 {target} 不存在")
    for coverage in content.coverages:
        if coverage.camera_id not in cams:
            raise ProductionError("stage_camera_missing", f"{coverage.id} 引用不存在的机位")
        if max(coverage.scene_start_ms, coverage.scene_end_ms) > duration:
            raise ProductionError("stage_time_out_of_range", "镜头的场景时间超出舞台时长")
        if not set(coverage.participants + coverage.must_show + coverage.offscreen) <= things:
            raise ProductionError("stage_instance_missing", "镜头引用不存在的实例")
    for event in content.events:
        if event.time_ms > duration:
            raise ProductionError("stage_time_out_of_range", "事件超出舞台时长")
    # Replay the whole stage, so invalid future events cannot hide behind an early sample.
    replay(content, duration)
