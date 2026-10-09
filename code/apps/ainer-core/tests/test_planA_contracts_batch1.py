"""Plan A 第一批契约与集成独立验证套件 (Gemini QA Verification Suite)
=============================================================================
文件：code/apps/ainer-core/tests/test_planA_contracts_batch1.py
覆盖目标：
  1. 路由注册与 OpenAPI 规范验证 (FastAPI app routes & OpenAPI)
  2. 生产上下文 (GET /production/context, PATCH .../context, 乐观锁 409, 自由画布)
  3. 资源引用解析 (POST /production/resources:resolve, 严格等长对齐, 版本过期 409, 跨项目隔离)
  4. 16 格标准包与别名 (GET /canonical-pack, missing 列表, expr_sorrow -> expr_sad 别名)
  5. 增量包绑定与安全 (PATCH /canonical-pack, 行锁, 锁定防篡改, 单格查重, 拼版防冒充)
  6. 缺项规划与使用位置 (POST /prepare 拦截 submit=true, GET /usages 扫描覆盖声明)
  7. Stage cards 独立范围查询 (GET /stage/cards 支持 board_id / novel_id, CR-01)
  8. 视角与机位偏好 (preferred_canonical_view, 右侧不镜像, 3/4 偏角不冒充)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 引入项目与隔离测试夹具
ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import get_db
from app.main import app
from app.production.canonical import ALIASES, VIEW_KEYS, canonical_views, preferred_canonical_view
from app.production.schema import SCHEMA_VERSION

from scripts.planA_qa.min_test_fixtures import (
    BOARD_ASSETS_ID, BOARD_DIRECTING_ID, BOARD_GENERAL_ID, BOARD_LEGACY_ID,
    CHAR_CHENG_MO_ID, CHAR_LIN_XIAOYU_ID, CHAR_ZHAO_LIE_ID,
    EPOCH_CHENG_MO_COAT, EPOCH_CHENG_MO_UNIFORM, EPOCH_LIN_XIAOYU_LEGACY, EPOCH_ZHAO_LIE_BASE,
    NOVEL_ID, CHAPTER_ID, PLAN_ID, SCRIPT_ID, WORLD_PROFILE_ID,
    create_isolated_mock_db,
)


@pytest.fixture
def mock_db():
    """提供纯净的内存隔离数据库实例。"""
    return create_isolated_mock_db()


@pytest.fixture
def client(mock_db):
    """基于隔离数据库重载 get_db 的 FastAPI TestClient。"""
    app.dependency_overrides[get_db] = lambda: mock_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.pop(get_db, None)


# ── 1. 路由注册与 OpenAPI 规范 ──────────────────────────────────────────────────

def test_production_routes_registered_and_openapi_valid():
    """验证所有 8 个生产端点已注册，且 OpenAPI schema 可以无误生成。"""
    expected_paths = {
        "/api/v2/production/context",
        "/api/v2/production/canvases/{board_id}/context",
        "/api/v2/production/resources:resolve",
        "/api/v2/production/entities/{entity_id}/canonical-pack",
        "/api/v2/production/resources",
        "/api/v2/production/prepare",
        "/api/v2/production/resources/{resource_id}/usages",
    }
    registered = {r.path for r in app.routes if hasattr(r, "path")}
    for path in expected_paths:
        assert path in registered, f"生产路由缺失: {path}"

    # 验证 OpenAPI 模式正常生成
    schema = app.openapi()
    assert schema["openapi"].startswith("3.")
    assert "/api/v2/production/context" in schema["paths"]


# ── 2. 生产上下文 (Context & Optimistic Lock) ───────────────────────────────────

def test_get_context_directing_and_free(client, mock_db):
    """验证导演画布与自由画布的上下文查询规范。"""
    # 导演画布
    res = client.get(f"/api/v2/production/context?board_id={BOARD_DIRECTING_ID}")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    ctx = data["context"]
    assert ctx["schema_version"] == SCHEMA_VERSION
    assert ctx["board_id"] == BOARD_DIRECTING_ID
    assert ctx["novel_id"] == NOVEL_ID
    assert ctx["plan_id"] == PLAN_ID
    assert ctx["purpose"] == "directing"
    assert data["board_version"] == 1
    assert data["readiness"]["context"] == "available"

    # 自由画布（无关联小说与计划）
    res_free = client.get(f"/api/v2/production/context?board_id={BOARD_GENERAL_ID}")
    assert res_free.status_code == 200
    free_ctx = res_free.json()["data"]["context"]
    assert free_ctx["board_id"] == BOARD_GENERAL_ID
    assert free_ctx["project_id"] == f"board:{BOARD_GENERAL_ID}"
    assert free_ctx["novel_id"] is None
    assert free_ctx["purpose"] == "general"

    # 画布不存在
    res_404 = client.get("/api/v2/production/context?board_id=brd_non_existent")
    assert res_404.status_code == 404
    assert res_404.json()["detail"]["code"] == "board_missing"


def test_get_context_legacy_purpose_tag(client):
    """CR-02: 存量非标用途标签降级为 general 并报 issue。"""
    res = client.get(f"/api/v2/production/context?board_id={BOARD_LEGACY_ID}")
    assert res.status_code == 200
    body = res.json()
    assert body["data"]["context"]["purpose"] == "general"
    issues = [iss["code"] for iss in body["issues"]]
    assert "legacy_purpose" in issues


def test_patch_context_optimistic_lock_and_return_to(client, mock_db):
    """验证上下文修改、版本锁 (409) 及返回定位 (return_to)。"""
    # 正常更新
    payload = {
        "base_version": 1,
        "purpose": "assets",
        "world_profile_id": WORLD_PROFILE_ID,
        "return_to": None,
    }
    res = client.patch(f"/api/v2/production/canvases/{BOARD_ASSETS_ID}/context", json=payload)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["board_version"] == 2
    assert mock_db.boards[BOARD_ASSETS_ID].version == 2
    assert mock_db.commits >= 1

    # 版本冲突 (Stale base_version) -> 409
    res_conflict = client.patch(f"/api/v2/production/canvases/{BOARD_ASSETS_ID}/context", json=payload)
    assert res_conflict.status_code == 409
    assert res_conflict.json()["detail"]["code"] == "board_version_conflict"

    # return_to 指向不存在的节点 -> 404
    bad_return = {
        "base_version": 2,
        "purpose": "assets",
        "world_profile_id": WORLD_PROFILE_ID,
        "return_to": {
            "board_id": BOARD_DIRECTING_ID,
            "node_id": "non_existent_node_id",
            "panel": "directing",
        },
    }
    res_bad_node = client.patch(f"/api/v2/production/canvases/{BOARD_ASSETS_ID}/context", json=bad_return)
    assert res_bad_node.status_code == 404
    assert res_bad_node.json()["detail"]["code"] == "return_target_invalid"


# ── 3. 资源解析 (Resource Resolver) ─────────────────────────────────────────────

def test_resolve_resources_alignment_and_modes(client):
    """验证 resolve 接口 items 严格等长对齐、逐项 issue 及未实现模式拦截。"""
    ctx_res = client.get(f"/api/v2/production/context?board_id={BOARD_DIRECTING_ID}").json()["data"]["context"]

    refs = [
        # 1. 实体引用
        {
            "kind": "entity",
            "id": CHAR_CHENG_MO_ID,
            "mode": "reference",
            "binding": {},
        },
        # 2. 单格视图引用
        {
            "kind": "canonical_view",
            "id": f"{EPOCH_CHENG_MO_UNIFORM}:face_front",
            "mode": "reference",
            "binding": {
                "entity_id": CHAR_CHENG_MO_ID,
                "world_profile_id": WORLD_PROFILE_ID,
                "epoch_id": EPOCH_CHENG_MO_UNIFORM,
                "view_key": "face_front",
            },
        },
        # 3. 资产引用
        {
            "kind": "asset",
            "id": "as_cm_u_face_front",
            "mode": "reference",
            "binding": {},
        },
        # 4. 音频素材引用
        {
            "kind": "audio",
            "id": "as_bgm_ski_01",
            "mode": "reference",
            "binding": {},
        },
        # 5. 故意写错不存在的视图 -> 单项 unresolved，不破坏整体
        {
            "kind": "canonical_view",
            "id": f"{EPOCH_ZHAO_LIE_BASE}:body_back",
            "mode": "reference",
            "binding": {
                "entity_id": CHAR_ZHAO_LIE_ID,
                "world_profile_id": WORLD_PROFILE_ID,
                "epoch_id": EPOCH_ZHAO_LIE_BASE,
                "view_key": "body_back",
            },
        },
    ]

    res = client.post("/api/v2/production/resources:resolve", json={"context": ctx_res, "refs": refs})
    assert res.status_code == 200, res.text
    items = res.json()["data"]["items"]
    assert len(items) == len(refs), "items 必须与 refs 严格等长对齐"

    assert items[0]["status"] == "resolved"
    assert items[0]["resource"]["id"] == CHAR_CHENG_MO_ID

    assert items[1]["status"] == "resolved"
    assert items[1]["resource"]["view_key"] == "face_front"

    assert items[2]["status"] == "resolved"
    assert items[3]["status"] == "resolved"

    # 第 5 项缺失格
    assert items[4]["status"] == "unresolved"
    assert items[4]["issues"][0]["code"] == "view_missing"


def test_resolve_revision_conflict_and_forbidden_modes(client):
    """测试 revision 过期冲突 (409) 及 snapshot/instance 拦截。"""
    ctx_res = client.get(f"/api/v2/production/context?board_id={BOARD_DIRECTING_ID}").json()["data"]["context"]

    # 1. 过期的 revision
    stale_ref = {
        "kind": "entity",
        "id": CHAR_CHENG_MO_ID,
        "revision": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "mode": "reference",
        "binding": {},
    }
    res = client.post("/api/v2/production/resources:resolve", json={"context": ctx_res, "refs": [stale_ref]})
    assert res.status_code == 200
    item = res.json()["data"]["items"][0]
    assert item["status"] == "unresolved"
    assert item["issues"][0]["code"] == "revision_conflict"

    # 2. snapshot 模式暂不支持
    snap_ref = {
        "kind": "entity",
        "id": CHAR_CHENG_MO_ID,
        "mode": "snapshot",
        "binding": {},
    }
    res_snap = client.post("/api/v2/production/resources:resolve", json={"context": ctx_res, "refs": [snap_ref]})
    assert res_snap.status_code == 200
    assert res_snap.json()["data"]["items"][0]["issues"][0]["code"] == "mode_not_implemented"

    # 3. instance_id 暂不支持
    inst_ref = {
        "kind": "entity",
        "id": CHAR_CHENG_MO_ID,
        "mode": "reference",
        "binding": {"instance_id": "inst_01"},
    }
    res_inst = client.post("/api/v2/production/resources:resolve", json={"context": ctx_res, "refs": [inst_ref]})
    assert res_inst.status_code == 200
    assert res_inst.json()["data"]["items"][0]["issues"][0]["code"] == "instance_not_implemented"


# ── 4. 16 格标准包与别名转换 ──────────────────────────────────────────────────

def test_canonical_pack_full_partial_and_aliases(client):
    """测试 16 格全量包、残缺包及 CR-05/CR-06 别名与遗留格式转换。"""
    # 全量包：陈默
    res_cm = client.get(
        f"/api/v2/production/entities/{CHAR_CHENG_MO_ID}/canonical-pack"
        f"?world_profile_id={WORLD_PROFILE_ID}&epoch_id={EPOCH_CHENG_MO_UNIFORM}"
    )
    assert res_cm.status_code == 200
    data_cm = res_cm.json()["data"]
    assert len(data_cm["views"]) == 16
    assert data_cm["missing"] == []
    assert data_cm["locked"] is False

    # 残缺包：赵烈 (仅 1 格，15 格缺失)
    res_zl = client.get(
        f"/api/v2/production/entities/{CHAR_ZHAO_LIE_ID}/canonical-pack"
        f"?world_profile_id={WORLD_PROFILE_ID}&epoch_id={EPOCH_ZHAO_LIE_BASE}"
    )
    assert res_zl.status_code == 200
    data_zl = res_zl.json()["data"]
    assert len(data_zl["views"]) == 1
    assert "face_front" in data_zl["views"]
    assert len(data_zl["missing"]) == 15

    # 遗留包与别名：林小雨 (包含 front, bust, expr_sorrow)
    res_lxy = client.get(
        f"/api/v2/production/entities/{CHAR_LIN_XIAOYU_ID}/canonical-pack"
        f"?world_profile_id={WORLD_PROFILE_ID}&epoch_id={EPOCH_LIN_XIAOYU_LEGACY}"
    )
    assert res_lxy.status_code == 200
    data_lxy = res_lxy.json()["data"]
    # front -> body_front
    assert "body_front" in data_lxy["views"]
    assert data_lxy["views"]["body_front"]["legacy_key"] == "front"
    # bust -> face_front
    assert "face_front" in data_lxy["views"]
    assert data_lxy["views"]["face_front"]["legacy_key"] == "bust"
    # expr_sorrow -> expr_sad
    assert "expr_sad" in data_lxy["views"]
    assert data_lxy["views"]["expr_sad"]["legacy_key"] == "expr_sorrow"


# ── 5. 增量包绑定与安全 (PATCH canonical-pack) ──────────────────────────────────

def test_patch_canonical_pack_security_and_incremental(client, mock_db):
    """测试标准包增量绑定、锁定保护、同一素材防冒充。"""
    # 1. 尝试修改锁定时期 -> 409 pack_locked
    lock_patch = {
        "epoch_id": EPOCH_CHENG_MO_COAT,
        "base_revision": "dummy_rev",
        "views": {"body_front": "as_cm_u_body_front"},
    }
    res_lock = client.patch(f"/api/v2/production/entities/{CHAR_CHENG_MO_ID}/canonical-pack", json=lock_patch)
    assert res_lock.status_code == 409
    assert res_lock.json()["detail"]["code"] == "pack_locked"

    # 2. 对赵烈增量绑定 face_left，使用有效 base_revision
    pack_zl = client.get(
        f"/api/v2/production/entities/{CHAR_ZHAO_LIE_ID}/canonical-pack"
        f"?world_profile_id={WORLD_PROFILE_ID}&epoch_id={EPOCH_ZHAO_LIE_BASE}"
    ).json()["data"]

    # 新建有效资产
    mock_db.assets["as_zl_face_left_new"] = copy.deepcopy(mock_db.assets["as_zl_face_front"])
    mock_db.assets["as_zl_face_left_new"].id = "as_zl_face_left_new"

    bind_payload = {
        "epoch_id": EPOCH_ZHAO_LIE_BASE,
        "base_revision": pack_zl["revision"],
        "views": {"face_left": "as_zl_face_left_new"},
    }
    res_bind = client.patch(f"/api/v2/production/entities/{CHAR_ZHAO_LIE_ID}/canonical-pack", json=bind_payload)
    assert res_bind.status_code == 200, res_bind.text
    new_pack = res_bind.json()["data"]
    # 原有 face_front 保留，新加 face_left
    assert "face_front" in new_pack["views"]
    assert "face_left" in new_pack["views"]
    assert new_pack["views"]["face_left"]["asset_id"] == "as_zl_face_left_new"
    assert new_pack["views"]["face_left"]["status"] == "bound_unreviewed"

    # 3. 同一素材冒充多个视角拒绝 -> duplicate_view_asset
    dup_payload = {
        "epoch_id": EPOCH_ZHAO_LIE_BASE,
        "base_revision": new_pack["revision"],
        "views": {
            "face_right": "as_zl_face_left_new",  # 与新绑的 face_left 相同
        },
    }
    res_dup = client.patch(f"/api/v2/production/entities/{CHAR_ZHAO_LIE_ID}/canonical-pack", json=dup_payload)
    assert res_dup.status_code == 422
    assert res_dup.json()["detail"]["code"] == "duplicate_view_asset"

    # 4. 拼版冒充单格拒绝 -> sheet_used_as_view
    sheet_dup = {
        "epoch_id": EPOCH_ZHAO_LIE_BASE,
        "base_revision": new_pack["revision"],
        "sheet_asset_id": "as_zl_temp_sheet",
        "views": {"face_right": "as_zl_temp_sheet"},
    }
    # 先放入资产
    mock_db.assets["as_zl_temp_sheet"] = copy.deepcopy(mock_db.assets["as_zl_face_front"])
    mock_db.assets["as_zl_temp_sheet"].id = "as_zl_temp_sheet"
    res_sheet_dup = client.patch(f"/api/v2/production/entities/{CHAR_ZHAO_LIE_ID}/canonical-pack", json=sheet_dup)
    assert res_sheet_dup.status_code == 422
    assert res_sheet_dup.json()["detail"]["code"] == "sheet_used_as_view"


# ── 6. 缺项规划与节点使用位置 ───────────────────────────────────────────────────

def test_prepare_planning_and_submit_restriction(client):
    """测试 prepare 规划缺项，并严格拒绝 submit=True。"""
    ctx_res = client.get(f"/api/v2/production/context?board_id={BOARD_DIRECTING_ID}").json()["data"]["context"]

    # 规划陈默 (全量) 与赵烈 (缺 15 格)
    prep_in = {
        "context": ctx_res,
        "refs": [
            {
                "kind": "canonical_pack",
                "id": EPOCH_CHENG_MO_UNIFORM,
                "mode": "reference",
                "binding": {
                    "entity_id": CHAR_CHENG_MO_ID,
                    "epoch_id": EPOCH_CHENG_MO_UNIFORM,
                    "world_profile_id": WORLD_PROFILE_ID,
                },
            },
            {
                "kind": "canonical_pack",
                "id": EPOCH_ZHAO_LIE_BASE,
                "mode": "reference",
                "binding": {
                    "entity_id": CHAR_ZHAO_LIE_ID,
                    "epoch_id": EPOCH_ZHAO_LIE_BASE,
                    "world_profile_id": WORLD_PROFILE_ID,
                },
            },
        ],
        "submit": False,
    }
    res = client.post("/api/v2/production/prepare", json=prep_in)
    assert res.status_code == 200, res.text
    plan = res.json()["data"]["plan"]
    assert plan[0]["action"] == "reuse"
    assert plan[1]["action"] == "missing_views"
    assert len(plan[1]["missing"]) >= 14

    # 尝试提交任务 -> 422 submission_not_implemented
    prep_in["submit"] = True
    res_sub = client.post("/api/v2/production/prepare", json=prep_in)
    assert res_sub.status_code == 422
    assert res_sub.json()["detail"]["code"] == "submission_not_implemented"


def test_resource_usages_scanning_coverage(client):
    """测试 usages 接口扫描已保存节点并明确声明 coverage 范围。"""
    res = client.get(
        f"/api/v2/production/resources/{EPOCH_CHENG_MO_UNIFORM}:face_front/usages"
        f"?board_id={BOARD_DIRECTING_ID}"
    )
    assert res.status_code == 200
    data = res.json()["data"]
    # DIRECTING_ID 画布上恰好有 node_cm_01
    assert len(data["items"]) == 1
    assert data["items"][0]["node_id"] == "node_cm_01"
    # coverage 必须明确声明
    coverage = data["coverage"]
    assert "studio_boards.doc_json.nodes[].data.ref" in coverage["scanned"]
    assert "recipes" in coverage["not_scanned"]
    assert coverage["complete"] is False


# ── 7. Stage Cards 与镜头偏好映射 ───────────────────────────────────────────────

def test_stage_cards_query_by_board_and_novel(client):
    """CR-01: 验证 stage/cards 支持无 plan_id 的 board_id 与 novel_id 查询。"""
    # 1. 按 board_id 查询素材画布
    res_b = client.get(f"/api/v2/stage/cards?board_id={BOARD_ASSETS_ID}")
    assert res_b.status_code == 200, res_b.text
    data = res_b.json()
    cards = data.get("cards") if isinstance(data, dict) else data
    assert isinstance(cards, list)
    card_ids = {c["id"] for c in cards}
    assert f"e:{CHAR_CHENG_MO_ID}" in card_ids

    # 2. 冲突范围传参 (同时传 board_id 与 novel_id) 拒绝 422
    res_conflict = client.get(f"/api/v2/stage/cards?board_id={BOARD_ASSETS_ID}&novel_id={NOVEL_ID}")
    assert res_conflict.status_code == 422


def test_preferred_canonical_view_selection_rules():
    """验证镜头视角偏好计算逻辑：特写取 face，全景取 body，右侧不镜像，3/4 偏角不冒充。"""
    # 特写景别
    assert preferred_canonical_view("front", "cu") == "face_front"
    assert preferred_canonical_view("profile_left", "ecu") == "face_left"
    assert preferred_canonical_view("profile_right", "mcu") == "face_right"
    assert preferred_canonical_view("away", "close") == "face_back"

    # 全景与中景
    assert preferred_canonical_view("front", "ws") == "body_front"
    assert preferred_canonical_view("away", "fs") == "body_back"
    assert preferred_canonical_view("profile_left", "ms") == "body_side"
    assert preferred_canonical_view("profile_right", "ms") == "body_side"

    # 3/4 偏角不能冒充正侧面
    assert preferred_canonical_view("three_quarter", "cu") is None
    assert preferred_canonical_view("three_quarter", "ws") is None


# ── 8. 新建空白与自定义画布契约 ──────────────────────────────────────────────────

def test_create_blank_and_custom_canvas_contracts(client, mock_db):
    """验证新建空白/自定义画布的契约完整性：支持无计划自由画布与小说素材画布。"""
    # 1. 创建完全空白自由画布 (purpose="general", 无 plan, 无 chapter, 无 novel)
    res_free = client.post("/api/v2/studio/canvases", json={
        "title": "用户自由空白画布",
        "purpose": "general",
        "source": "user",
    })
    assert res_free.status_code == 200, res_free.text
    free_data = res_free.json()
    free_board_id = free_data["id"]
    assert free_data["plan_id"] is None
    assert free_data["chapter_id"] is None
    assert free_data["novel_id"] is None
    assert free_data["purpose"] == "general"

    # 2. 初始保存空文档 (nodes=[], edges=[]) -> version 从 0 提升到 1
    empty_doc = {
        "schema": "ainer.board/v1",
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": [],
        "edges": [],
    }
    res_save = client.put(f"/api/v2/studio/canvases/{free_board_id}", json={
        "base_version": 0,
        "doc": empty_doc,
    })
    assert res_save.status_code == 200, res_save.text
    assert res_save.json()["version"] == 1

    # 3. 读取生产上下文，确保自由画布有合法 project_id 且无冲突
    res_ctx = client.get(f"/api/v2/production/context?board_id={free_board_id}")
    assert res_ctx.status_code == 200
    ctx = res_ctx.json()["data"]["context"]
    assert ctx["board_id"] == free_board_id
    assert ctx["project_id"] == f"board:{free_board_id}"
    assert ctx["purpose"] == "general"
    assert ctx["plan_id"] is None

    # 4. 创建小说素材画布 (purpose="assets", 绑定 novel_id，无 plan_id)
    res_assets = client.post("/api/v2/studio/canvases", json={
        "title": "角色素材沉淀板",
        "novel_id": NOVEL_ID,
        "purpose": "assets",
        "source": "user",
    })
    assert res_assets.status_code == 200, res_assets.text
    assets_data = res_assets.json()
    assert assets_data["novel_id"] == NOVEL_ID
    assert assets_data["plan_id"] is None
    assert assets_data["purpose"] == "assets"


# ── 14. CR-09 契约验证：同一事实在不同接口必须保持一致 (同一份真实对象) ────────

def test_cr09_physical_consistency_canonical_pack_and_stage_cards(client, mock_db):
    """
    CR-09 契约验证：
    同一个真实对象在 canonical-pack 与 stage/cards 中必须保证物理事实一致，
    不得出现一个接口推断出体型身高、另一个接口返回 missing，或两个接口推断结果冲突的情况。
    """
    # 1. 验证反派「赵烈」(单时期无用户显式 physical，仅外貌描述为高大健壮)
    res_zl_pack = client.get(
        f"/api/v2/production/entities/{CHAR_ZHAO_LIE_ID}/canonical-pack"
        f"?world_profile_id={WORLD_PROFILE_ID}&epoch_id={EPOCH_ZHAO_LIE_BASE}"
    )
    assert res_zl_pack.status_code == 200, res_zl_pack.text
    zl_pack_physical = res_zl_pack.json()["data"]["physical"]
    assert zl_pack_physical is not None
    assert zl_pack_physical.get("source") != "missing", "canonical-pack 对有外貌描述的角色不应返回 source=missing"

    res_cards = client.get(f"/api/v2/stage/cards?board_id={BOARD_DIRECTING_ID}")
    assert res_cards.status_code == 200, res_cards.text
    cards_map = {c["entity_id"]: c for c in res_cards.json()["cards"]}
    assert CHAR_ZHAO_LIE_ID in cards_map, "赵烈必须出现在 stage/cards 中"
    zl_card_physical = cards_map[CHAR_ZHAO_LIE_ID]["physical"]

    # 断言两者给出的基础物理事实严格对齐 (同一份真实对象)
    assert zl_pack_physical["height_m"] == zl_card_physical["height_m"], (
        f"赵烈身高不一致: pack={zl_pack_physical['height_m']}, card={zl_card_physical['height_m']}"
    )
    assert zl_pack_physical["build"] == zl_card_physical["build"], (
        f"赵烈体型不一致: pack={zl_pack_physical['build']}, card={zl_card_physical['build']}"
    )
    assert zl_pack_physical["source"] == zl_card_physical["source"]

    # 2. 验证非角色实体 (如地点、道具) 在 stage/cards 中的 physical 表现
    from scripts.planA_qa.min_test_fixtures import LOC_SKI_RESORT_ID
    loc_card = cards_map.get(LOC_SKI_RESORT_ID)
    if loc_card:
        # 地点卡片在 stage/cards 中的 kind 必须为 location
        assert loc_card["kind"] == "location"
        # 记录 CR-09 观测事实：若 stage/cards 赋了 physical，应当标记或限制其仅属于角色
        # canonical-pack 对地点无时期返回 404 epoch_missing
        res_loc_pack = client.get(
            f"/api/v2/production/entities/{LOC_SKI_RESORT_ID}/canonical-pack"
            f"?world_profile_id={WORLD_PROFILE_ID}"
        )
        assert res_loc_pack.status_code == 404, "canonical-pack 对未绑定时期的地点实体正确返回 404 epoch_missing"
        assert res_loc_pack.json()["detail"]["code"] == "epoch_missing"


