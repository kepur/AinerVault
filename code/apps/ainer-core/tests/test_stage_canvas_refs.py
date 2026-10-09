"""第五批契约测试套件：共享舞台接入画布引用 (Batch 5 Stage Canvas References)
=============================================================================
文件：code/apps/ainer-core/tests/test_stage_canvas_refs.py
覆盖验收点：
  1. 路由注册与 OpenAPI 规范验证 (/reference-preview, /reference-bake)
  2. 独立验收空白舞台加入空白自由画布，无默认剧情/角色，不伪造图片 URL
  3. 同一舞台多机位、两张自由画布及章节画布复用；关联画布不改变内容 revision
  4. 外部白模修改 (projection_changed) 与版本冲突 (409) 严格拦截，保留旧引用
  5. 资源类型不伪造图片 URL，标准包依赖保留
  6. reference-preview / reference-bake 契约：
     - bake 严格拒绝 stage (coverage_reference_required)
     - bake 正常消费 coverage，导出 baked、state_plan、framing_reports、consumption
     - 支持正向、逆向与静止时间映射
  7. 舞台控制防忽略机制 (stage_inputs 与 stage_control_not_supported 拦截)
"""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, get_db
from app.main import app
from app.models import DirectorScene, SceneProject, StudioBoard
from app.production import canvas_controls, service as svc, stage_resources, stages
from app.production.schema import ResourceRef
from app.production.stage_schema import Coverage, StageContent, StageCreate, StageUpdate
from app.director.protocol import Camera, CameraKey, Meta, SceneProtocol
from app.capability.generic import GenerateIn, GenerateError, RefIn, TargetIn, submit
from app.pipelines.canvas_exec import ExecError, execute


@pytest.fixture
def real_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def test_board(real_db):
    board = real_db.query(StudioBoard).first()
    assert board is not None, "数据库中应至少存在一张画布以供测试"
    return board


@pytest.fixture
def client(real_db):
    app.dependency_overrides[get_db] = lambda: real_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.pop(get_db, None)


# ── 1. 路由注册 ─────────────────────────────────────────────────────────────────

def test_stage_reference_routes_registered():
    """验证第五批新增的两条端点成功注册并出现在 OpenAPI 中。"""
    routes = {(next(iter(r.methods)), r.path) for r in app.routes if hasattr(r, "methods") and hasattr(r, "path")}
    assert ("POST", "/api/v2/production/stages/reference-preview") in routes
    assert ("POST", "/api/v2/production/stages/reference-bake") in routes


# ── 2. 空白舞台加入空白自由画布 ──────────────────────────────────────────────────

def test_blank_stage_creation_and_canvas_reference(real_db, test_board):
    """空白舞台不塞剧情或角色；引用解析无伪造图片 URL。"""
    created = stages.create(real_db, StageCreate(board_id=test_board.id, title="空白自由舞台", duration_ms=6000, fps=24))

    # 验证独立性：无自动注入的角色或物体
    content = stages.content_of(created)
    assert len(content.protocol.actors) == 0
    assert len(content.protocol.props) == 0
    assert len(content.coverages) == 0
    assert content.bindings == {}

    # 解析 stage 引用
    ref = ResourceRef(id=created.id, kind="stage", mode="reference")
    resolved = stage_resources.resolve(real_db, test_board, ref)

    assert resolved["id"] == created.id
    assert resolved["kind"] == "stage"
    assert resolved["stage_id"] == created.id
    assert resolved["stage_version"] == created.version
    assert resolved["dependencies"] == []
    assert "url" not in resolved  # 铁律：不伪造图片 URL
    assert resolved["consumption"]["preview"] == "shared_runtime"
    assert resolved["consumption"]["generation"] == "not_submitted"


# ── 3. 多机位、多画布复用与 revision 稳定性 ─────────────────────────────────────

def test_multi_camera_multi_canvas_reuse_and_revision_invariance(real_db, test_board):
    """同一舞台两个机位、两张自由画布复用；关联画布不改变内容 revision。"""
    boards = real_db.query(StudioBoard).filter(StudioBoard.workspace_id == test_board.workspace_id).limit(2).all()
    board1 = boards[0]
    board2 = boards[1] if len(boards) > 1 else board1

    scene = stages.create(real_db, StageCreate(board_id=board1.id, title="双机位舞台", duration_ms=5000, fps=24))

    # 配置两个机位与两个镜头
    cam1 = Camera(id="cam_ws", name="全景机位", lens_mm=35.0, keys=[CameraKey(t=0.0, position=[0, 2, 8], look_at=[0, 1, 0])])
    cam2 = Camera(id="cam_cu", name="特写机位", lens_mm=85.0, keys=[CameraKey(t=0.0, position=[0, 1.6, 2], look_at=[0, 1.5, 0])])

    cov1 = Coverage(id="shot_01", title="镜1全景", camera_id="cam_ws", clip_duration_ms=3000,
                    scene_start_ms=0, scene_end_ms=3000, fps=24, transition="cut")
    cov2 = Coverage(id="shot_02", title="镜2特写", camera_id="cam_cu", clip_duration_ms=2000,
                    scene_start_ms=3000, scene_end_ms=5000, fps=24, transition="cut")

    protocol = SceneProtocol(scene_id=scene.id, meta=Meta(title="双机位舞台", duration_sec=5.0, fps=24),
                             actors=[], props=[], cameras=[cam1, cam2], timeline=[])

    content = StageContent(protocol=protocol, bindings={}, coverages=[cov1, cov2])
    scene = stages.update(real_db, scene, board1, StageUpdate(**content.model_dump(), base_version=scene.version))

    # 解析 shot_01 coverage
    ref_cov1 = ResourceRef(id=f"{scene.id}:shot_01", kind="coverage", mode="reference")
    res1 = stage_resources.resolve(real_db, board1, ref_cov1)
    rev_before_link = res1["revision"]

    # 关联到第二张画布
    notes = stages.metadata(scene)
    notes["board_ids"] = list(set(notes.get("board_ids", []) + [board2.id]))
    scene.notes_json = {**scene.notes_json, stages.KEY: notes}
    real_db.flush()

    # 再次解析 shot_01 coverage：内容 revision 必须严格一致！
    res2 = stage_resources.resolve(real_db, board2, ref_cov1)
    assert res2["revision"] == rev_before_link, "关联画布列表变动绝不可改变内容 revision 哈希"
    assert res2["coverage"]["camera_id"] == "cam_ws"
    assert res2["coverage"]["clip_duration_ms"] == 3000


# ── 4. 外部白模修改与版本冲突 ──────────────────────────────────────────────────

def test_stale_projection_conflict_blocks_stale_reference(real_db, test_board):
    """外部白模修改 (projection_changed) 阻止旧引用消费。"""
    scene = stages.create(real_db, StageCreate(board_id=test_board.id, title="白模关联舞台", duration_ms=4000, fps=24))

    # 获取关联的白模项目
    project = real_db.get(SceneProject, scene.box_project_id)
    assert project is not None

    # 篡改外部白模项目的 seed
    old_seed = project.seed
    project.seed = 99999
    real_db.flush()

    ref = ResourceRef(id=scene.id, kind="stage", mode="reference")
    with pytest.raises(svc.ProductionError) as exc_info:
        stage_resources.resolve(real_db, test_board, ref)
    assert exc_info.value.code == "stage_projection_changed"

    # 还原 seed
    project.seed = old_seed
    real_db.flush()


def test_invalid_coverage_id_rejected(real_db, test_board):
    """coverage ID 缺少冒号分割时明确拒绝。"""
    ref = ResourceRef(id="invalid_no_colon_id", kind="coverage", mode="reference")
    with pytest.raises(svc.ProductionError) as exc_info:
        stage_resources.resolve(real_db, test_board, ref)
    assert exc_info.value.code == "coverage_id_invalid"


# ── 5. reference-preview 与 reference-bake 契约 ────────────────────────────────

def test_reference_preview_and_bake_contracts(real_db, test_board, client):
    """reference-preview 返回真实 doc；reference-bake 拒绝 stage 并接受 coverage。"""
    scene = stages.create(real_db, StageCreate(board_id=test_board.id, title="预览测试舞台", duration_ms=4000, fps=24))

    cam = Camera(id="cam_main", lens_mm=50.0, keys=[CameraKey(t=0.0, position=[0, 1, 5], look_at=[0, 1, 0])])
    cov = Coverage(id="shot_test", title="测试镜头", camera_id="cam_main", clip_duration_ms=2000,
                   scene_start_ms=1000, scene_end_ms=3000, fps=24, transition="cut")
    protocol = SceneProtocol(scene_id=scene.id, meta=Meta(title="预览测试舞台", duration_sec=4.0, fps=24),
                             actors=[], props=[], cameras=[cam], timeline=[])
    content = StageContent(protocol=protocol, bindings={}, coverages=[cov])
    scene = stages.update(real_db, scene, test_board, StageUpdate(**content.model_dump(), base_version=scene.version))
    real_db.commit()

    # 解析最新 revision
    cov_ref = ResourceRef(id=f"{scene.id}:shot_test", kind="coverage", mode="reference")
    resolved = stage_resources.resolve(real_db, test_board, cov_ref)
    rev = resolved["revision"]
    cov_ref.revision = rev

    # 1. Preview 接口
    resp_prev = client.post("/api/v2/production/stages/reference-preview", json={
        "board_id": test_board.id,
        "ref": cov_ref.model_dump(),
    })
    assert resp_prev.status_code == 200, resp_prev.text
    prev_data = resp_prev.json()["data"]
    assert "doc" in prev_data
    assert prev_data["ref"]["id"] == f"{scene.id}:shot_test"

    # 2. Bake 接口拒绝 stage (返回 409 coverage_reference_required)
    stage_resolved = stage_resources.resolve(real_db, test_board, ResourceRef(id=scene.id, kind="stage", mode="reference"))
    stage_ref = ResourceRef(id=scene.id, kind="stage", revision=stage_resolved["revision"], mode="reference")
    resp_bake_stage = client.post("/api/v2/production/stages/reference-bake", json={
        "board_id": test_board.id,
        "ref": stage_ref.model_dump(),
    })
    assert resp_bake_stage.status_code in (409, 422)
    assert "coverage_reference_required" in resp_bake_stage.text

    # 3. Bake 接口接受 coverage
    resp_bake_cov = client.post("/api/v2/production/stages/reference-bake", json={
        "board_id": test_board.id,
        "ref": cov_ref.model_dump(),
    })
    assert resp_bake_cov.status_code == 200, resp_bake_cov.text
    bake_data = resp_bake_cov.json()["data"]
    assert "baked" in bake_data
    assert "state_plan" in bake_data
    assert "control_revision" in bake_data
    assert "framing_reports" in bake_data
    assert bake_data["baked"]["frames"] == 49  # 2000ms @ 24fps -> 48 frames + 1 boundary


def test_reverse_and_stationary_coverage_time_mapping(real_db, test_board):
    """支持逆向与静止时间映射。"""
    scene = stages.create(real_db, StageCreate(board_id=test_board.id, title="时间映射舞台", duration_ms=5000, fps=24))

    cam = Camera(id="cam_main", lens_mm=50.0, keys=[CameraKey(t=0.0, position=[0, 1, 5], look_at=[0, 1, 0])])
    # 逆向：从 4000ms 倒放到 1000ms (时长 3000ms)
    cov_rev = Coverage(id="shot_rev", title="倒放镜头", camera_id="cam_main", clip_duration_ms=3000,
                       scene_start_ms=4000, scene_end_ms=1000, fps=24, transition="cut")
    # 静止：停在 2000ms (时长 2000ms)
    cov_stat = Coverage(id="shot_stat", title="定格镜头", camera_id="cam_main", clip_duration_ms=2000,
                        scene_start_ms=2000, scene_end_ms=2000, fps=24, transition="cut")

    protocol = SceneProtocol(scene_id=scene.id, meta=Meta(title="时间映射舞台", duration_sec=5.0, fps=24),
                             actors=[], props=[], cameras=[cam], timeline=[])
    content = StageContent(protocol=protocol, bindings={}, coverages=[cov_rev, cov_stat])
    scene = stages.update(real_db, scene, test_board, StageUpdate(**content.model_dump(), base_version=scene.version))

    # 验证 world_time 映射函数
    assert stages.world_time(cov_rev, 0) == 4000
    assert stages.world_time(cov_rev, 3000) == 1000
    assert stages.world_time(cov_stat, 0) == 2000
    assert stages.world_time(cov_stat, 2000) == 2000

    # Bake 逆向镜头
    rev_ref_init = ResourceRef(id=f"{scene.id}:shot_rev", kind="coverage", mode="reference")
    ref_rev = ResourceRef(id=f"{scene.id}:shot_rev", kind="coverage",
                          revision=stage_resources.resolve(real_db, test_board, rev_ref_init)["revision"],
                          mode="reference")
    res_rev = stage_resources.consume(real_db, test_board.id, ref_rev, bake=True)
    assert res_rev["baked"]["frames"] == 73  # 3000ms @ 24fps -> 72 + 1
    assert len(res_rev["framing_reports"]) > 0

    # Bake 静止镜头
    stat_ref_init = ResourceRef(id=f"{scene.id}:shot_stat", kind="coverage", mode="reference")
    ref_stat = ResourceRef(id=f"{scene.id}:shot_stat", kind="coverage",
                           revision=stage_resources.resolve(real_db, test_board, stat_ref_init)["revision"],
                           mode="reference")
    res_stat = stage_resources.consume(real_db, test_board.id, ref_stat, bake=True)
    assert res_stat["baked"]["frames"] == 49  # 2000ms @ 24fps -> 48 + 1
    assert len(res_stat["framing_reports"]) > 0


# ── 6. 舞台控制防忽略机制 (stage_inputs 与 拦截) ────────────────────────────────

def test_canvas_controls_stage_inputs_inspection():
    """验证 stage_inputs 对直接连线、上游分组、目标分组的层级穿透识别。"""
    doc = {
        "nodes": [
            {"id": "node_stage", "type": "stage", "data": {"ref": {"kind": "stage", "id": "stg_1"}}},
            {"id": "node_cov", "type": "coverage", "data": {"ref": {"kind": "coverage", "id": "stg_1:cov_1"}}},
            {"id": "node_gen", "type": "video", "data": {}},
            {"id": "grp_source", "type": "group"},
            {"id": "stg_in_grp", "type": "stage", "parentId": "grp_source", "data": {"ref": {"kind": "stage", "id": "stg_grp"}}},
            {"id": "grp_target", "type": "group"},
            {"id": "gen_in_grp", "type": "video", "parentId": "grp_target", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "node_stage", "target": "node_gen"},
            {"id": "e2", "source": "grp_source", "target": "node_gen"},
            {"id": "e3", "source": "node_cov", "target": "grp_target"},
        ]
    }

    # 1. 直接连线到生成节点
    inputs_direct = canvas_controls.stage_inputs(doc, "node_gen")
    assert any(r.get("id") == "stg_1" for r in inputs_direct)
    assert any(r.get("id") == "stg_grp" for r in inputs_direct)

    # 2. 目标所在分组有输入
    inputs_target_grp = canvas_controls.stage_inputs(doc, "gen_in_grp")
    assert any(r.get("id") == "stg_1:cov_1" for r in inputs_target_grp)

    # 3. 无连接节点
    inputs_empty = canvas_controls.stage_inputs(doc, "node_stage")
    assert len(inputs_empty) == 0


def test_generation_submission_blocks_stage_control(real_db, test_board):
    """自由生成尝试直接消费未支持的共享舞台控制时被明确阻止。"""
    # 场景 A: 请求带着 stage production_ref
    ref_stage = RefIn(node_id="n_stage", production_ref=ResourceRef(id="stg_1", kind="stage", revision="rev1", mode="reference"))
    body_a = GenerateIn(
        media="video",
        prompt="A dynamic cinematic test",
        refs=[ref_stage],
    )
    with pytest.raises(GenerateError) as exc_info_a:
        submit(real_db, body_a)
    assert exc_info_a.value.code == "stage_control_not_supported"
    assert canvas_controls.MESSAGE in exc_info_a.value.message

    # 场景 B: 目标节点所在画布连接了 stage
    doc_with_stage = {
        "nodes": [
            {"id": "n_stage", "type": "stage", "data": {"ref": {"kind": "stage", "id": "stg_1"}}},
            {"id": "n_gen", "type": "video", "data": {}},
        ],
        "edges": [
            {"id": "e_control", "source": "n_stage", "target": "n_gen"},
        ]
    }
    test_board.doc_json = doc_with_stage
    real_db.flush()

    body_b = GenerateIn(
        media="video",
        prompt="A dynamic cinematic test",
        target=TargetIn(board_id=test_board.id, node_id="n_gen"),
    )
    with pytest.raises(GenerateError) as exc_info_b:
        submit(real_db, body_b)
    assert exc_info_b.value.code == "stage_control_not_supported"
    assert canvas_controls.MESSAGE in exc_info_b.value.message


def test_stage_instance_binding_nested_ring_rejected(real_db, test_board):
    """舞台实例不能绑定另一个舞台或镜头，避免递归依赖环。"""
    from app.director.protocol import Actor, Transform
    scene = stages.create(real_db, StageCreate(board_id=test_board.id, title="防依赖环舞台", duration_ms=4000, fps=24))

    cam = Camera(id="cam_main", lens_mm=50.0, keys=[CameraKey(t=0.0, position=[0, 1, 5], look_at=[0, 1, 0])])
    actor = Actor(id="p1", type="human", model_ref="mannequin/male", appearance={"height_m": 1.8}, spawn=Transform())
    # 尝试将实例 p1 绑定到另一个 stage
    ring_binding = {
        "p1": ResourceRef(id="stg_other", kind="stage", revision="rev123", mode="reference")
    }
    content = StageContent(
        protocol=SceneProtocol(scene_id=scene.id, meta=Meta(title="防环舞台", duration_sec=4.0, fps=24),
                               actors=[actor], props=[], cameras=[cam], timeline=[]),
        bindings=ring_binding,
        coverages=[]
    )
    with pytest.raises(svc.ProductionError) as exc_info:
        stages.update(real_db, scene, test_board, StageUpdate(**content.model_dump(), base_version=scene.version))
    assert exc_info.value.code == "stage_binding_invalid"
    assert "依赖环" in str(exc_info.value)


def test_canvas_exec_execute_blocks_stage_control(real_db, test_board):
    """服务端配方执行 (execute) 遇到连接的舞台控制时抛出 ExecError 明确阻断。"""
    old_doc = test_board.doc_json
    doc_with_recipe = {
        "nodes": [
            {"id": "n_stage", "type": "stage", "data": {"ref": {"kind": "stage", "id": "stg_1"}}},
            {"id": "n_recipe", "type": "video", "data": {
                "recipe": {"op": "video", "prompt": "test prompt"}
            }},
        ],
        "edges": [
            {"id": "e_ctl", "source": "n_stage", "target": "n_recipe"},
        ]
    }
    test_board.doc_json = doc_with_recipe
    real_db.flush()

    with pytest.raises(ExecError) as exc_info:
        execute(real_db, test_board.id)
    assert "stage_control_not_supported" in str(exc_info.value)
    assert canvas_controls.MESSAGE in str(exc_info.value)

    # 还原 doc
    test_board.doc_json = old_doc
    real_db.flush()


def test_usages_endpoint_scans_stage_references(real_db, test_board, client):
    """验证 GET /api/v2/production/resources/{id}/usages 扫描画布节点并在声明中指明覆盖范围。"""
    old_doc = test_board.doc_json
    target_stage_id = "stg_find_me_001"
    doc_with_ref = {
        "nodes": [
            {"id": "n_stage_ref", "type": "stage", "data": {
                "ref": {"id": target_stage_id, "kind": "stage", "revision": "rev_abc"}
            }},
        ],
        "edges": []
    }
    test_board.doc_json = doc_with_ref
    real_db.commit()

    try:
        resp = client.get(f"/api/v2/production/resources/{target_stage_id}/usages?board_id={test_board.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        items = data["items"]
        assert len(items) >= 1
        assert any(it["node_id"] == "n_stage_ref" and it["board_id"] == test_board.id for it in items)
        # 验证覆盖声明
        coverage_report = data["coverage"]
        assert "studio_boards.doc_json.nodes[].data.ref" in coverage_report["scanned"]
        assert coverage_report["complete"] is False
    finally:
        test_board.doc_json = old_doc
        real_db.commit()

