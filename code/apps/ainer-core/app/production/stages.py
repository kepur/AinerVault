"""Shared DirectorScene stages, versioned coverage and runtime sampling.

No LLM/GPU tasks are submitted here. Geometry lives in protocol_json; the box
project is its compiled projection. Story metadata lives in notes_json, not a
second copy of the world in a canvas node.
"""
from __future__ import annotations

import json
import math
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.director import store
from app.director.convert import doc_to_protocol
from app.director.protocol import Meta, SceneProtocol
from app.ids import new_id
from app.models import DirectorScene, SceneProject
from app.production import service as sources
from app.production.service import ProductionError
from app.production.stage_schema import Coverage, StageContent, StageCreate, StageUpdate, NarrativeStageCreate
from app.production.stage_state import replay, validate
from app.scene3d.runner import _call, shot_reports
from app.scene3d import service as box

SCHEMA = "ainer.shared-stage/v0.1"
KEY = "production_stage"


def envelope(data):
    return {"schema_version": SCHEMA, "data": data, "issues": []}


def metadata(scene):
    value = (scene.notes_json or {}).get(KEY)
    if not isinstance(value, dict):
        raise ProductionError("shared_stage_missing", "该场景尚未作为共享舞台创建", 404)
    return value


def get(db: Session, stage_id: str, board_id: str, *, lock=False):
    board = sources.board(db, board_id)
    q = select(DirectorScene).where(DirectorScene.id == stage_id, DirectorScene.workspace_id == board.workspace_id)
    scene = db.scalar(q.with_for_update() if lock else q)
    if scene is None:
        raise ProductionError("shared_stage_missing", "共享舞台不存在", 404)
    metadata(scene)
    return board, scene


def content_of(scene) -> StageContent:
    meta = metadata(scene)
    return StageContent.model_validate({"protocol": scene.protocol_json,
        **{k: meta.get(k, {} if k in ("bindings", "initial_state") else [])
           for k in ("bindings", "initial_state", "events", "coverages")}})


def out(scene, full=True):
    result = {"id": scene.id, "title": scene.title, "version": scene.version,
              "revision": sources.revision({"protocol": scene.protocol_json, "stage": metadata(scene)}),
              "box_project_id": scene.box_project_id, "board_ids": metadata(scene).get("board_ids", []),
              "source_board_id": metadata(scene).get("source_board_id"),
              "coverage_count": len(metadata(scene).get("coverages", []))}
    if full:
        result.update(content_of(scene).model_dump(mode="json"))
    return result


def projection_revision(project):
    return sources.revision({"script": (project.files_json or {}).get(box.ENTRY),
                             "overrides": project.overrides_json, "seed": project.seed})


def assert_version(scene, version):
    if scene.version != version:
        raise ProductionError("stage_version_conflict", "舞台已在别处修改，请重新载入；当前编辑保留", 409)


def projection(db, scene):
    p = db.scalar(select(SceneProject).where(SceneProject.id == scene.box_project_id)
        .with_for_update().execution_options(populate_existing=True)) if scene.box_project_id else None
    if not p or p.workspace_id != scene.workspace_id:
        raise ProductionError("stage_projection_missing", "舞台的白模项目不存在", 409)
    if projection_revision(p) != metadata(scene).get("projection_revision"):
        raise ProductionError("stage_projection_changed", "白模项目已被另一个编辑器修改；请先明确采用哪份舞台版本", 409)
    return p


def bind_sources(db, board, content):
    context, _ = sources.context_for(db, board)
    resources = {}
    actors = {a.id: a for a in content.protocol.actors}
    worlds = set()
    for instance_id, ref in content.bindings.items():
        if ref.kind in {"stage", "coverage", "event", "run_output"}:
            raise ProductionError("stage_binding_invalid", "舞台实例须引用原子素材，不能嵌套舞台或镜头形成依赖环")
        if ref.mode != "reference" or not ref.revision:
            raise ProductionError("stage_binding_invalid", "舞台素材必须引用明确的来源版本")
        item = sources.resolve_one(db, board, context, ref)
        if item.get("status") != "resolved":
            issue = next(iter(item.get("issues") or []), {})
            raise ProductionError(issue.get("code", "stage_binding_unresolved"), issue.get("message", "舞台素材引用无法解析"), 409)
        resource = item["resource"]
        if ref.binding.world_profile_id:
            worlds.add(ref.binding.world_profile_id)
        if len(worlds) > 1:
            raise ProductionError("stage_world_mismatch", "同一舞台的造型素材必须属于同一个表现世界")
        resources[instance_id] = resource
        actor = actors.get(instance_id)
        if actor and actor.type == "human":
            if ref.kind != "canonical_pack" or resource.get("entity_kind") != "character":
                raise ProductionError("stage_character_binding_invalid", "人物实例须绑定角色的世界/时期标准素材包")
            entity_id = resource.get("entity_id")
            if actor.character_ref != f"e:{entity_id}":
                raise ProductionError("stage_character_binding_mismatch", "演员身份必须与绑定素材的实体 ID 一致")
    return resources


def assert_consumable(content):
    """Reject known protocol-to-runtime losses for this stricter stage entry point."""
    try:
        json.dumps(content.model_dump(mode="json"), allow_nan=False)
    except ValueError as exc:
        raise ProductionError("stage_number_invalid", "坐标和摄影参数必须是有限数值") from exc
    for actor in content.protocol.actors:
        if actor.type == "human":
            height = actor.appearance.get("height_m")
            if not isinstance(height, (float, int)) or isinstance(height, bool) or not math.isfinite(height) or not 0.2 <= height <= 8:
                raise ProductionError("stage_height_missing", "人物需明确米制身高；不能用未说明的默认体型代替")
            if not actor.model_ref.startswith("mannequin/"):
                raise ProductionError("stage_rig_unsupported", "当前预演只支持已注册的人偶体型")
    if (content.protocol.actors or content.protocol.props) and not content.protocol.cameras:
        raise ProductionError("stage_camera_missing", "有场景实例时请明确添加机位，不能自动塞入全景机位")
    for instance in [*content.protocol.actors, *content.protocol.props]:
        if any(v <= 0 for v in instance.spawn.scale):
            raise ProductionError("stage_scale_invalid", "实例缩放必须大于零，不能通过负缩放镜像身体左右")
        if getattr(instance, "size", None) and any(v <= 0 for v in instance.size):
            raise ProductionError("stage_size_invalid", "物体尺寸必须大于零")
    for prop in content.protocol.props:
        if prop.hidden or prop.strip or prop.primitive in ("capsule", "prism"):
            raise ProductionError("stage_geometry_unsupported", "当前共享舞台编译尚不支持隐藏物体、带状物或该基本体，请保留在原白模编辑器")
        if not prop.prefab and not prop.primitive:
            raise ProductionError("stage_geometry_missing", "物体需选择真实预制件或基本体")
    motion_targets = set()
    action_intervals = {}
    for op in content.protocol.timeline:
        if op.op in ("camera.frame", "camera.keys"):
            raise ProductionError("stage_camera_op_unsupported", "机位关键帧请直接写在 cameras[].keys，避免时间线里的摄影指令被忽略")
        if op.op.startswith("camera.") and op.op != "camera.cut":
            raise ProductionError("stage_camera_op_unsupported", "共享舞台直接保存展开后的机位关键帧，不叠加会被忽略的运镜预设")
        if getattr(op, "target_bone", None):
            raise ProductionError("stage_contact_unsupported", "目标骨骼接触尚未接入，不能只记录字段就当已执行")
        end = op.time + (getattr(op, "duration", None) or 0)
        if end > content.protocol.meta.duration_sec:
            raise ProductionError("stage_time_out_of_range", "动作区间超出舞台时长")
        if op.op in ("actor.move", "prop.move"):
            times = [k.get("t") for k in op.keys]
            if any(not isinstance(t, (int, float)) or t < 0 or t > content.protocol.meta.duration_sec for t in times):
                raise ProductionError("stage_time_out_of_range", "位移关键帧需明确舞台时间，且落在舞台范围内")
            if len(set(times)) != len(times):
                raise ProductionError("stage_motion_conflict", "同一位移轨的时刻不能重复")
            if any(set(k) - {"t", "at", "rot", "scale"} for k in op.keys):
                raise ProductionError("stage_motion_field_unsupported", "位移关键帧只消费 t/at/rot/scale，不可包含被忽略字段")
        if op.op.startswith(("actor.move", "prop.move")):
            who = op.actor if op.op.startswith("actor.") else op.prop
            if not who or (op.op.startswith("actor.") and op.prop) or (op.op.startswith("prop.") and op.actor):
                raise ProductionError("stage_motion_target_invalid", "位移轨必须指定对应类型的 actor 或 prop")
            if who in motion_targets:
                raise ProductionError("stage_motion_conflict", "同一实例只允许一条完整位移轨，请合并关键帧，避免后一轨覆盖前一轨")
            motion_targets.add(who)
            if op.op.endswith(("move_to", "move_along")) and not op.duration:
                raise ProductionError("stage_motion_duration_required", "共享舞台位移需明确时长，不能隐式按默认速度推算")
        if op.op == "actor.play_action":
            if not op.duration:
                raise ProductionError("stage_action_duration_required", "身体动作需明确时长")
            for start, stop in action_intervals.get(op.actor, []):
                if op.time < stop and end > start:
                    raise ProductionError("stage_action_conflict", "当前全身动作通道不能同时播放两段动作")
            action_intervals.setdefault(op.actor, []).append((op.time, end))


def create(db: Session, body: StageCreate):
    board = sources.board(db, body.board_id)
    protocol = SceneProtocol(scene_id=new_id("dsc"), meta=Meta(title=body.title or "空白舞台",
        duration_sec=body.duration_ms / 1000, fps=body.fps))
    scene = store.create_from_protocol(db, protocol.model_dump(mode="json"), notes={KEY: {
        "schema_version": SCHEMA, "source_board_id": board.id, "board_ids": [board.id],
        "bindings": {}, "initial_state": {}, "events": [], "coverages": []}})
    scene.workspace_id = board.workspace_id
    project = db.get(SceneProject, scene.box_project_id)
    project.workspace_id = board.workspace_id
    scene.notes_json = {**scene.notes_json, KEY: {**metadata(scene), "projection_revision": projection_revision(project)}}
    db.flush()
    return scene


def create_from_narrative(db, body: NarrativeStageCreate):
    """Bridge the narrative compiler into persisted protocol-first shared stages."""
    from app.stage.compile import compile_stage_to_protocol
    board = sources.board(db, body.board_id)
    context, _ = sources.context_for(db, board)
    data = compile_stage_to_protocol(body.stage, body.shots, fps=body.fps, title=body.title)
    for actor in data["actors"]:
        height = body.heights_m.get(actor["id"])
        ref = body.bindings.get(actor["id"])
        if height is None and ref:
            resource = sources.resolve_one(db, board, context, ref)["resource"]
            height = (resource.get("physical") or {}).get("height_m")
        if height is None:
            raise ProductionError("stage_height_missing", f"{actor['id']} 需绑定明确造型尺寸或输入米制身高")
        actor["appearance"] = {"height_m": height}
    # Expanded camera keys are the execution source; semantic presets are provenance.
    data["timeline"] = [op for op in data["timeline"] if not op["op"].startswith("camera.") or op["op"] == "camera.cut"]
    coverages = []
    for shot in body.shots:
        ticks = [t * 1000 for t in shot.window]
        if any(abs(t - round(t)) > 1e-6 for t in ticks):
            raise ProductionError("stage_time_precision", "当前导入需要毫秒时间边界，不能暗中舍入")
        start, end = map(round, ticks)
        coverages.append(Coverage(id=shot.shot_id, title=f"镜 {shot.order_no}", camera_id=f"cam_{shot.order_no:02d}",
            clip_duration_ms=end-start, scene_start_ms=start, scene_end_ms=end, fps=body.fps,
            participants=[a.actor for a in body.stage.cast], must_show=shot.visible,
            transition={"cut": "cut", "continuous": "continuous", "match_action": "cut", "time_jump": "jump"}[shot.transition_in]))
    content = StageContent(protocol=SceneProtocol.model_validate(data), bindings=body.bindings, coverages=coverages)
    validate(content)
    assert_consumable(content)
    bind_sources(db, board, content)
    scene = create(db, StageCreate(board_id=board.id, title=body.title,
        duration_ms=round(content.protocol.meta.duration_sec*1000), fps=body.fps))
    content.protocol.scene_id = scene.id
    scene = update(db, scene, board, StageUpdate(**content.model_dump(), base_version=scene.version))
    scene.notes_json = {**scene.notes_json, KEY: {**metadata(scene),
        "narrative_source": body.stage.model_dump(mode="json"),
        "narrative_import_consumption": {"geometry_motion_camera": "compiled",
            "holding_effects_state": "source_retained_not_imported", "contact_ik_collision": "not_implemented"}}}
    db.flush()
    return scene


def update(db: Session, scene, board, body: StageUpdate):
    assert_version(scene, body.base_version)
    projection(db, scene)  # Never erase another editor's manual overrides silently.
    content = StageContent.model_validate(body.model_dump(exclude={"base_version"}))
    if content.protocol.scene_id != scene.id:
        raise ProductionError("stage_id_mismatch", "场景 ID 不能在编辑时更换")
    validate(content)
    assert_consumable(content)
    bind_sources(db, board, content)
    notes = deepcopy(scene.notes_json or {})
    notes[KEY].update(content.model_dump(mode="json", exclude={"protocol"}))
    # Existing converter compiles the same protocol for preview and Blender.
    project = store._sync_box(db, scene, content.protocol, "共享舞台显式保存")
    if project.seed != 1:
        project.seed = 1
        box.compile_project(project)
    notes[KEY]["projection_revision"] = projection_revision(project)
    scene.protocol_json = content.protocol.model_dump(mode="json", exclude_none=True)
    scene.notes_json = notes
    scene.title = content.protocol.meta.title
    project.title = scene.title
    scene.version += 1
    db.flush()
    return scene


def adopt_projection(db, scene, board, version):
    """Explicitly adopt manual box edits, then return to protocol-first authority."""
    assert_version(scene, version)
    p = db.scalar(select(SceneProject).where(SceneProject.id == scene.box_project_id,
        SceneProject.workspace_id == scene.workspace_id).with_for_update().execution_options(populate_existing=True))
    if not p:
        raise ProductionError("stage_projection_missing", "白模项目不存在", 404)
    compiled = box.compile_project(p)
    if not compiled.get("ok"):
        raise ProductionError("stage_compile_failed", "白模项目有编译错误，请先在白模编辑器中修复")
    content = content_of(scene)
    content.protocol = SceneProtocol.model_validate(doc_to_protocol(p.compiled_json,
        scene_id=scene.id, title=p.title, source={"kind": "3dbox", "project_id": p.id}))
    # doc_to_protocol already materializes camera keys; redundant camera intent
    # ops are provenance, not a second animation source.
    content.protocol.timeline = [op for op in content.protocol.timeline
        if not op.op.startswith("camera.") or op.op == "camera.cut"]
    validate(content)
    assert_consumable(content)
    bind_sources(db, board, content)
    notes = deepcopy(scene.notes_json or {})
    notes[KEY].update(content.model_dump(mode="json", exclude={"protocol"}))
    project = store._sync_box(db, scene, content.protocol, "显式采用白模编辑器版本")
    if project.seed != 1:
        project.seed = 1
        box.compile_project(project)
    notes[KEY]["projection_revision"] = projection_revision(project)
    scene.protocol_json = content.protocol.model_dump(mode="json", exclude_none=True)
    scene.notes_json = notes
    scene.source = "api"
    scene.title = content.protocol.meta.title
    scene.version += 1
    db.flush()
    return scene


def resolve_doc(db, scene, board, version):
    assert_version(scene, version)
    projection(db, scene)
    content = content_of(scene)
    validate(content)
    assert_consumable(content)
    resources = bind_sources(db, board, content)
    doc = store.scene_doc(db, scene)
    return content, doc, resources


def sample(db, scene, board, version, time_ms, camera_id=None):
    content, doc, _ = resolve_doc(db, scene, board, version)
    if not 0 <= time_ms <= round(content.protocol.meta.duration_sec * 1000):
        raise ProductionError("stage_time_out_of_range", "采样时刻超出舞台范围")
    if camera_id and camera_id not in {c.id for c in content.protocol.cameras}:
        raise ProductionError("stage_camera_missing", "采样机位不存在")
    physical = _call({"mode": "state", "doc": doc, "time": time_ms / 1000, "camera": camera_id}, wall_timeout=20)
    if physical.get("errors"):
        raise ProductionError("stage_sampling_failed", "共享运行时无法采样舞台状态")
    return {"stage_id": scene.id, "stage_version": scene.version, "stage_revision": out(scene, False)["revision"],
            "physical": physical, "semantic": replay(content, time_ms),
            "consumption": {"position_camera_rig": "shared_runtime", "semantic_events": "state_only",
                            "contact_ik_collision": "not_implemented"}}


def coverage_of(content, coverage_id) -> Coverage:
    found = next((c for c in content.coverages if c.id == coverage_id), None)
    if not found:
        raise ProductionError("coverage_missing", "舞台镜头不存在", 404)
    return found


def world_time(coverage, clip_ms):
    if not 0 <= clip_ms <= coverage.clip_duration_ms:
        raise ProductionError("coverage_time_out_of_range", "采样时刻超出镜头范围")
    return coverage.scene_start_ms + (coverage.scene_end_ms - coverage.scene_start_ms) * clip_ms / coverage.clip_duration_ms


def bake_coverage(db, scene, board, version, coverage_id):
    content, doc, _ = resolve_doc(db, scene, board, version)
    coverage = coverage_of(content, coverage_id)
    count = coverage.clip_duration_ms * coverage.fps // 1000
    if count + 1 > 4321:
        raise ProductionError("coverage_sampling_limit", "本接口最多采样 4321 帧，请拆分长镜头")
    times = [world_time(coverage, i * 1000 / coverage.fps) / 1000 for i in range(count + 1)]
    baked = _call({"mode": "bake", "doc": doc, "options": {"fps": coverage.fps, "camera": coverage.camera_id,
        "t0": times[0], "sampleTimes": times}, "timeoutMs": 20000}, wall_timeout=35)
    if baked.get("errors") or baked.get("frames") != count + 1:
        raise ProductionError("coverage_sampling_failed", "共享运行时未按镜头时间映射完成采样")
    probes = sorted(set([times[0], times[count // 2], times[-1],
        *[e.time_ms / 1000 for e in content.events if min(times) <= e.time_ms / 1000 <= max(times)]]))
    reports = shot_reports(doc, [{"camera": coverage.camera_id, "t": t} for t in probes])
    return {"stage_id": scene.id, "stage_version": scene.version, "stage_revision": out(scene, False)["revision"],
            "coverage": coverage.model_dump(), "baked": baked,
            "boundary_rule": "inclusive_preview_endpoints; frame i maps to i/fps; final assembly owns endpoint deduplication",
            "framing_reports": [{"scene_time_ms": t * 1000, "report": report} for t, report in zip(probes, reports)],
            "consumption": {"camera_world_time_motion": "baked", "identity": "reference_only",
                            "must_show_offscreen": "report_only", "contact_ik_collision": "not_implemented",
                            "semantic_events": "state_only", "video_generation": "not_submitted"}}
