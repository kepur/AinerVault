"""Plan A 最小测试数据与隔离夹具 (Minimum Test Dataset & Fixtures)
=============================================================================
文件：scripts/planA_qa/min_test_fixtures.py
用途：
  1. 提供 Plan A 验收全流程所需的最小闭环测试数据：
     - 3 个角色：主角色（双时期+完整16格）、反派（单时期+残缺格）、配角（遗留旧键+别名）
     - 2 个道具：滑雪板/杖、储物柜钥匙（验证 CR-08 空态及道具卡契约）
     - 2 个地点：雪山滑雪场、学校储物柜走廊（地标坐标 RHS [x, z]）
     - 1 组剧本/分镜事件：NarrativeIR 序列、3 镜头覆盖（ELS/WS/MCU）、动作与轴线
     - 4 张画布：素材画布 (assets)、导演画布 (directing)、通用自由画布 (general)、遗留标签画布
  2. 纯内存隔离：不依赖、不污染、不修改本地 PostgreSQL 生产数据库。
  3. 提供 `IsolatedMockSession` 夹具，可直接供 FastAPI dependency_overrides[get_db] 与 pytest 使用。
"""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Asset, AssetEpoch, AssetKind, AssetSource, Chapter, EntityKind,
    Novel, ProfileStatus, ReviewStatus, Scene, ScriptBlock, ScriptDoc,
    Shot, ShotPlan, StudioBoard, WorldEntity, WorldProfile, WorldTransform,
)
from app.production.schema import (
    Binding, ContextPatch, PackBinding, PrepareIn, ProductionContext,
    ResourceRef, ReturnSlot, ReturnTo, Scope,
)
from app.production.canonical import ALIASES, VIEW_KEYS

# ─────────────────────────────────────────────────────────────────────────────
# 辅助哈希与常量
# ─────────────────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _ref_rev(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()

WS_TEST = "ws_plana_qa_isolated"
NOVEL_ID = "nv_plana_min_01"
CHAPTER_ID = "ch_plana_min_01"
PLAN_ID = "sp_plana_min_01"
SCRIPT_ID = "doc_plana_min_01"
WORLD_PROFILE_ID = "wp_plana_modern_01"
TRANSFORM_ID = "wt_plana_trans_01"

BOARD_ASSETS_ID = "brd_plana_assets_01"
BOARD_DIRECTING_ID = "brd_plana_directing_01"
BOARD_GENERAL_ID = "brd_plana_free_01"
BOARD_LEGACY_ID = "brd_plana_legacy_01"

# ─────────────────────────────────────────────────────────────────────────────
# 1. 最小角色数据 (3 Characters)
# ─────────────────────────────────────────────────────────────────────────────

# 角色 1：主角色「陈默」（双时期，完整 16 格，物理推断）
CHAR_CHENG_MO_ID = "ent_cheng_mo_01"
EPOCH_CHENG_MO_UNIFORM = "ep_cm_uniform_01"
EPOCH_CHENG_MO_COAT = "ep_cm_coat_02"

# 角色 2：反派「赵烈」（单时期，部分缺失格，运动健壮型）
CHAR_ZHAO_LIE_ID = "ent_zhao_lie_01"
EPOCH_ZHAO_LIE_BASE = "ep_zl_base_01"

# 角色 3：配角「林小雨」（单时期，包含旧 legacy 键与旧别名）
CHAR_LIN_XIAOYU_ID = "ent_lin_xiaoyu_01"
EPOCH_LIN_XIAOYU_LEGACY = "ep_lxy_legacy_01"

# ─────────────────────────────────────────────────────────────────────────────
# 2. 最小道具数据 (2 Props) & 地点数据 (2 Locations)
# ─────────────────────────────────────────────────────────────────────────────

PROP_SKI_POLE_ID = "ent_prop_ski_pole_01"
PROP_LOCKER_KEY_ID = "ent_prop_locker_key_01"

LOC_SKI_RESORT_ID = "ent_loc_ski_resort_01"
LOC_CORRIDOR_ID = "ent_loc_corridor_01"

# ─────────────────────────────────────────────────────────────────────────────
# 3. 内存模拟数据库 (IsolatedMockSession)
# ─────────────────────────────────────────────────────────────────────────────

class MockRowResult:
    def __init__(self, items: list[Any]):
        self._items = items

    def scalar(self):
        return self._items[0] if self._items else None

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def first(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._items)

    def all(self):
        return list(self._items)


class IsolatedMockSession:
    """全面模拟 SQLAlchemy Session，完全自包含于内存中。"""

    def __init__(self):
        self.workspace_id = WS_TEST
        self.novels: dict[str, Novel] = {}
        self.chapters: dict[str, Chapter] = {}
        self.world_profiles: dict[str, WorldProfile] = {}
        self.world_transforms: dict[str, WorldTransform] = {}
        self.script_docs: dict[str, ScriptDoc] = {}
        self.script_blocks: dict[str, list[ScriptBlock]] = {}
        self.shot_plans: dict[str, ShotPlan] = {}
        self.shots: dict[str, list[Shot]] = {}
        self.scenes: dict[str, list[Scene]] = {}
        self.boards: dict[str, StudioBoard] = {}
        self.entities: dict[str, WorldEntity] = {}
        self.epochs: dict[str, AssetEpoch] = {}
        self.assets: dict[str, Asset] = {}

        self.commits: int = 0
        self.rollbacks: int = 0
        self._seed_data()

    def _seed_data(self):
        """填充最小闭环测试数据。"""
        # 小说与章节
        self.novels[NOVEL_ID] = Novel(
            id=NOVEL_ID,
            workspace_id=WS_TEST,
            title="雪道追逐",
            source_language_code="zh",
            source_world_profile_id=WORLD_PROFILE_ID,
        )
        self.chapters[CHAPTER_ID] = Chapter(
            id=CHAPTER_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            order_no=1,
            title="第一章 突围",
            content="滑雪场狂风呼啸，陈默压低重心穿行在松林间。赵烈在后方紧追不舍。",
        )

        # 世界观与转译
        self.world_profiles[WORLD_PROFILE_ID] = WorldProfile(
            id=WORLD_PROFILE_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            code="wp_modern",
            display_name="现代竞技世界观",
            status=ProfileStatus.active if hasattr(ProfileStatus, "active") else "active",
        )
        self.world_transforms[TRANSFORM_ID] = WorldTransform(
            id=TRANSFORM_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            source_profile_id=WORLD_PROFILE_ID,
            target_profile_id=WORLD_PROFILE_ID,
            target_language_code="zh",
        )

        # 剧本与计划
        self.script_docs[SCRIPT_ID] = ScriptDoc(
            id=SCRIPT_ID,
            workspace_id=WS_TEST,
            chapter_id=CHAPTER_ID,
            version=1,
            input_fingerprint="fp_sdoc_01_hash",
        )
        b1 = ScriptBlock(
            id="blk_01",
            workspace_id=WS_TEST,
            script_doc_id=SCRIPT_ID,
            seq_no=1,
            block_type="action",
            source_text="陈默俯身滑降，穿过第一道旗门。",
            scene_id="sc_01",
            meta_json={},
        )
        b2 = ScriptBlock(
            id="blk_02",
            workspace_id=WS_TEST,
            script_doc_id=SCRIPT_ID,
            seq_no=2,
            block_type="dialogue",
            source_text="别想逃走！",
            scene_id="sc_01",
            speaker_entity_id=CHAR_ZHAO_LIE_ID,
            meta_json={},
        )
        self.script_blocks[SCRIPT_ID] = [b1, b2]

        self.shot_plans[PLAN_ID] = ShotPlan(
            id=PLAN_ID,
            workspace_id=WS_TEST,
            script_doc_id=SCRIPT_ID,
            transform_id=TRANSFORM_ID,
            target_language_code="zh",
            version=1,
        )

        sh1 = Shot(id="sh_01", workspace_id=WS_TEST, shot_plan_id=PLAN_ID, order_no=1)
        sh2 = Shot(id="sh_02", workspace_id=WS_TEST, shot_plan_id=PLAN_ID, order_no=2)
        sh3 = Shot(id="sh_03", workspace_id=WS_TEST, shot_plan_id=PLAN_ID, order_no=3)
        self.shots[PLAN_ID] = [sh1, sh2, sh3]

        sc1 = Scene(id="sc_01", workspace_id=WS_TEST, script_doc_id=SCRIPT_ID)
        self.scenes[SCRIPT_ID] = [sc1]

        # 画布 1：素材画布 (assets)
        self.boards[BOARD_ASSETS_ID] = StudioBoard(
            id=BOARD_ASSETS_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            chapter_id=CHAPTER_ID,
            shot_plan_id=None,
            kind="asset",
            version=1,
            scope_json={
                "purpose": "assets",
                "production": {
                    "purpose": "assets",
                    "world_profile_id": WORLD_PROFILE_ID,
                },
            },
            doc_json={"schema": "ainer.board/v1", "nodes": [], "edges": []},
        )

        # 画布 2：导演画布 (directing)
        self.boards[BOARD_DIRECTING_ID] = StudioBoard(
            id=BOARD_DIRECTING_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            chapter_id=CHAPTER_ID,
            shot_plan_id=PLAN_ID,
            kind="plan",
            version=1,
            scope_json={
                "purpose": "directing",
                "scene_ids": ["sc_01"],
                "shot_ids": ["sh_01", "sh_02", "sh_03"],
                "production": {
                    "purpose": "directing",
                    "world_profile_id": WORLD_PROFILE_ID,
                },
            },
            doc_json={
                "schema": "ainer.board/v1",
                "nodes": [
                    {
                        "id": "node_cm_01",
                        "type": "image",
                        "data": {
                            "ref": {
                                "kind": "canonical_view",
                                "id": f"{EPOCH_CHENG_MO_UNIFORM}:face_front",
                                "revision": "rev_cm_face_front_01",
                                "mode": "reference",
                            }
                        },
                    }
                ],
                "edges": [],
            },
        )

        # 画布 3：自由/通用画布 (general)
        self.boards[BOARD_GENERAL_ID] = StudioBoard(
            id=BOARD_GENERAL_ID,
            workspace_id=WS_TEST,
            novel_id=None,
            chapter_id=None,
            shot_plan_id=None,
            kind="custom",
            version=1,
            scope_json={"purpose": "general", "production": {"purpose": "general"}},
            doc_json={"schema": "ainer.board/v1", "nodes": [], "edges": []},
        )

        # 画布 4：遗留标签画布 (custom/legacy purpose)
        self.boards[BOARD_LEGACY_ID] = StudioBoard(
            id=BOARD_LEGACY_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            chapter_id=CHAPTER_ID,
            shot_plan_id=None,
            kind="custom",
            version=1,
            scope_json={"purpose": "brainstorming_custom"},
            doc_json={"schema": "ainer.board/v1", "nodes": [], "edges": []},
        )

        # ── 实体、造型时期与资产 ──────────────────────────────
        # 1. 陈默 (主角色)
        self.entities[CHAR_CHENG_MO_ID] = WorldEntity(
            id=CHAR_CHENG_MO_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=EntityKind.character,
            display_name="陈默",
            version=1,
            appearance="瘦高的少年，短发，目光坚定",
            visual_prompt="teenage boy, slim build, short dark hair, determined eyes",
            ref_asset_ids=[],
            summary="滑雪天才少年",
            voice_profile_json={},
        )

        # 创建 16 格资产
        cm_views_uniform = {}
        for vk in VIEW_KEYS:
            aid = f"as_cm_u_{vk}"
            self.assets[aid] = Asset(
                id=aid,
                workspace_id=WS_TEST,
                novel_id=NOVEL_ID,
                kind=AssetKind.image,
                url=f"/media/test/cm_u_{vk}.png",
                sha256=_sha256(f"content_cm_u_{vk}"),
                mime="image/png",
                source=AssetSource.generated,
                gen_task_id=f"task_cm_u_{vk}",
                meta_json={"view": vk},
            )
            cm_views_uniform[vk] = {
                "asset_id": aid,
                "status": "reviewed",
                "source_refs": [],
            }

        # 拼版与身份锚图
        aid_sheet = "as_cm_u_sheet"
        self.assets[aid_sheet] = Asset(
            id=aid_sheet,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=AssetKind.image,
            url="/media/test/cm_u_sheet.png",
            sha256=_sha256("content_cm_u_sheet"),
            mime="image/png",
            source=AssetSource.generated,
            gen_task_id="task_cm_sheet",
            meta_json={"kind": "contact_sheet"},
        )
        aid_anchor = "as_cm_u_anchor"
        self.assets[aid_anchor] = Asset(
            id=aid_anchor,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=AssetKind.image,
            url="/media/test/cm_u_anchor.png",
            sha256=_sha256("content_cm_u_anchor"),
            mime="image/png",
            source=AssetSource.generated,
            gen_task_id="task_cm_anchor",
            meta_json={"kind": "identity_anchor"},
        )

        self.epochs[EPOCH_CHENG_MO_UNIFORM] = AssetEpoch(
            id=EPOCH_CHENG_MO_UNIFORM,
            workspace_id=WS_TEST,
            subject_key=CHAR_CHENG_MO_ID,
            entity_id=CHAR_CHENG_MO_ID,
            world_profile_id=WORLD_PROFILE_ID,
            epoch_key="uniform",
            display_name="校服时期",
            from_chapter_order=1,
            to_chapter_order=5,
            locked=False,
            status=ReviewStatus.approved if hasattr(ReviewStatus, "approved") else SimpleNamespace(value="approved"),
            identity_ref_asset_id=aid_anchor,
            reference_set_json={
                "canonical_sheet_asset_id": aid_sheet,
                "canonical_views": cm_views_uniform,
                "physical": {"height_m": 1.78, "build": "slim", "handedness": "right", "source": "user"},
            },
        )

        # 陈默时期 2：冬装大衣 (锁定时期，用于测试防改写)
        self.epochs[EPOCH_CHENG_MO_COAT] = AssetEpoch(
            id=EPOCH_CHENG_MO_COAT,
            workspace_id=WS_TEST,
            subject_key=CHAR_CHENG_MO_ID,
            entity_id=CHAR_CHENG_MO_ID,
            world_profile_id=WORLD_PROFILE_ID,
            epoch_key="winter_coat",
            display_name="大衣时期",
            from_chapter_order=6,
            to_chapter_order=None,
            locked=True,  # 锁定！
            status=ReviewStatus.approved if hasattr(ReviewStatus, "approved") else SimpleNamespace(value="approved"),
            identity_ref_asset_id=aid_anchor,
            reference_set_json={"canonical_views": cm_views_uniform},
        )

        # 2. 赵烈 (反派角色，部分缺失格)
        self.entities[CHAR_ZHAO_LIE_ID] = WorldEntity(
            id=CHAR_ZHAO_LIE_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=EntityKind.character,
            display_name="赵烈",
            version=1,
            appearance="高大健壮的青年，肌肉发达，神情凶狠",
            visual_prompt="athletic muscular young man, tall build, fierce gaze",
            ref_asset_ids=[],
            summary="主要竞争对手",
            voice_profile_json={},
        )
        zl_aid_front = "as_zl_face_front"
        self.assets[zl_aid_front] = Asset(
            id=zl_aid_front,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=AssetKind.image,
            url="/media/test/zl_face_front.png",
            sha256=_sha256("content_zl_face_front"),
            mime="image/png",
            source=AssetSource.generated,
            gen_task_id="task_zl_front",
            meta_json={},
        )
        self.epochs[EPOCH_ZHAO_LIE_BASE] = AssetEpoch(
            id=EPOCH_ZHAO_LIE_BASE,
            workspace_id=WS_TEST,
            subject_key=CHAR_ZHAO_LIE_ID,
            entity_id=CHAR_ZHAO_LIE_ID,
            world_profile_id=WORLD_PROFILE_ID,
            epoch_key="racing_suit",
            display_name="赛车服时期",
            from_chapter_order=1,
            to_chapter_order=None,
            locked=False,
            status=ReviewStatus.pending if hasattr(ReviewStatus, "pending") else SimpleNamespace(value="pending"),
            identity_ref_asset_id=None,
            reference_set_json={
                # 仅有正脸，其他 15 格缺失
                "canonical_views": {"face_front": {"asset_id": zl_aid_front, "status": "bound_unreviewed"}},
                "physical": {"height_m": 1.85, "build": "athletic", "source": "inferred"},
            },
        )

        # 3. 林小雨 (配角，包含 legacy 格式与旧别名)
        self.entities[CHAR_LIN_XIAOYU_ID] = WorldEntity(
            id=CHAR_LIN_XIAOYU_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=EntityKind.character,
            display_name="林小雨",
            version=1,
            appearance="娇小的少女，扎双马尾",
            visual_prompt="petite teenage girl, twin pigtails",
            ref_asset_ids=[],
            summary="滑雪队后勤支援",
            voice_profile_json={},
        )
        lxy_aid_front = "as_lxy_legacy_front"
        lxy_aid_bust = "as_lxy_legacy_bust"
        lxy_aid_sad = "as_lxy_legacy_sad"
        for aid, u in [
            (lxy_aid_front, "/media/test/lxy_front.png"),
            (lxy_aid_bust, "/media/test/lxy_bust.png"),
            (lxy_aid_sad, "/media/test/lxy_sad.png"),
        ]:
            self.assets[aid] = Asset(
                id=aid,
                workspace_id=WS_TEST,
                novel_id=NOVEL_ID,
                kind=AssetKind.image,
                url=u,
                sha256=_sha256(f"content_{aid}"),
                mime="image/png",
                source=AssetSource.generated,
                gen_task_id="task_lxy",
                meta_json={},
            )

        self.epochs[EPOCH_LIN_XIAOYU_LEGACY] = AssetEpoch(
            id=EPOCH_LIN_XIAOYU_LEGACY,
            workspace_id=WS_TEST,
            subject_key=CHAR_LIN_XIAOYU_ID,
            entity_id=CHAR_LIN_XIAOYU_ID,
            world_profile_id=WORLD_PROFILE_ID,
            epoch_key="default",
            display_name="默认时期",
            from_chapter_order=1,
            to_chapter_order=None,
            locked=False,
            status=ReviewStatus.approved if hasattr(ReviewStatus, "approved") else SimpleNamespace(value="approved"),
            identity_ref_asset_id=None,
            reference_set_json={
                "views": {
                    "front": {"asset_id": lxy_aid_front},
                    "bust": {"asset_id": lxy_aid_bust},
                },
                "sheet_panels": [
                    {"key": "expr_sorrow", "asset_id": lxy_aid_sad},  # 旧别名 expr_sorrow -> expr_sad
                ],
            },
        )

        # 4. 道具实体 (CR-08 验证道具卡)
        self.entities[PROP_SKI_POLE_ID] = WorldEntity(
            id=PROP_SKI_POLE_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=EntityKind.prop,
            display_name="碳纤维滑雪杖",
            version=1,
            appearance="黑色碳纤维滑雪杖，带有荧光黄腕带",
            visual_prompt="carbon fiber ski pole with neon yellow strap",
            ref_asset_ids=[],
            summary="比赛用专业滑雪杖",
            voice_profile_json={},
        )
        self.entities[PROP_LOCKER_KEY_ID] = WorldEntity(
            id=PROP_LOCKER_KEY_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=EntityKind.prop,
            display_name="储物柜铜钥匙",
            version=1,
            appearance="小巧的黄铜钥匙，带有 104 编号牌",
            visual_prompt="small brass key with number 104 tag",
            ref_asset_ids=[],
            summary="储物柜钥匙",
            voice_profile_json={},
        )

        # 5. 地点实体
        self.entities[LOC_SKI_RESORT_ID] = WorldEntity(
            id=LOC_SKI_RESORT_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=EntityKind.location,
            display_name="长白山野雪赛道",
            version=1,
            appearance="积雪深厚的高山陡坡，两侧为茂密红松林",
            visual_prompt="steep alpine ski slope with deep snow, dense pine forest",
            ref_asset_ids=[],
            summary="主要滑雪追逐场景",
            voice_profile_json={},
        )
        self.entities[LOC_CORRIDOR_ID] = WorldEntity(
            id=LOC_CORRIDOR_ID,
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=EntityKind.location,
            display_name="滑雪学校更衣室走廊",
            version=1,
            appearance="狭长的走廊，两侧排列着蓝色的金属储物柜",
            visual_prompt="narrow hallway with blue metal lockers on both sides",
            ref_asset_ids=[],
            summary="室内剧情场景",
            voice_profile_json={},
        )

        # 音频素材
        self.assets["as_bgm_ski_01"] = Asset(
            id="as_bgm_ski_01",
            workspace_id=WS_TEST,
            novel_id=NOVEL_ID,
            kind=AssetKind.audio,
            url="/media/test/bgm_ski.mp3",
            sha256=_sha256("ski_bgm_audio"),
            mime="audio/mpeg",
            source=AssetSource.uploaded,
            gen_task_id=None,
            meta_json={"bpm": 130},
        )

    # ── Session 接口实现 ───────────────────────────────────────────────────────

    def get(self, model: type, key: str | None):
        if not key:
            return None
        mapping = {
            Novel: self.novels,
            Chapter: self.chapters,
            WorldProfile: self.world_profiles,
            WorldTransform: self.world_transforms,
            ScriptDoc: self.script_docs,
            ShotPlan: self.shot_plans,
            StudioBoard: self.boards,
            WorldEntity: self.entities,
            AssetEpoch: self.epochs,
            Asset: self.assets,
        }
        store = mapping.get(model)
        return store.get(key) if store else None

    def scalar(self, stmt):
        res = self.execute(stmt)
        return res.scalar_one_or_none()

    def scalars(self, stmt):
        res = self.execute(stmt)
        return res.scalars()

    def execute(self, stmt):
        # 兼容简易 SQLAlchemy 查询表达式执行
        # 针对各模型的查询返回过滤后的项目
        from sqlalchemy.sql.selectable import Select
        try:
            sql_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        except Exception:
            sql_str = str(stmt)

        if "studio_boards" in sql_str:
            items = []
            for b in self.boards.values():
                if f"'{b.id}'" in sql_str or f"studio_boards.id = '{b.id}'" in sql_str:
                    items.append(b)
                elif f"studio_boards.novel_id = '{b.novel_id}'" in sql_str:
                    items.append(b)
            if not items and ("WHERE" not in sql_str or "workspace_id" in sql_str and "studio_boards.id =" not in sql_str):
                items = list(self.boards.values())
            return MockRowResult(items)

        if "asset_epochs" in sql_str:
            items = []
            for ep in self.epochs.values():
                if f"asset_epochs.id = '{ep.id}'" in sql_str:
                    items.append(ep)
                    continue
                match_subject = f"'{ep.subject_key}'" in sql_str
                match_world = f"'{ep.world_profile_id}'" in sql_str
                if match_subject and match_world:
                    if "asset_epochs.id =" in sql_str:
                        if f"asset_epochs.id = '{ep.id}'" in sql_str:
                            items.append(ep)
                    else:
                        items.append(ep)
            return MockRowResult(items)

        if "world_entities" in sql_str:
            items = []
            for ent in self.entities.values():
                if f"'{ent.id}'" in sql_str or f"world_entities.id = '{ent.id}'" in sql_str:
                    items.append(ent)
                elif f"world_entities.novel_id = '{ent.novel_id}'" in sql_str:
                    items.append(ent)
            if not items and ("WHERE" not in sql_str or "workspace_id" in sql_str and "world_entities.id =" not in sql_str and "novel_id" not in sql_str):
                items = list(self.entities.values())
            return MockRowResult(items)

        if "assets" in sql_str:
            items = []
            for a in self.assets.values():
                if f"'{a.id}'" in sql_str:
                    items.append(a)
                elif "assets.novel_id" in sql_str:
                    if a.novel_id == NOVEL_ID or a.novel_id is None:
                        if "kind = 'audio'" in sql_str or "assets.kind = 'audio'" in sql_str:
                            if a.kind == AssetKind.audio:
                                items.append(a)
                        elif "kind = 'image'" in sql_str or "assets.kind = 'image'" in sql_str:
                            if a.kind == AssetKind.image:
                                items.append(a)
                        else:
                            items.append(a)
            if not items and "WHERE" not in sql_str:
                items = list(self.assets.values())
            return MockRowResult(items)

        if "script_blocks" in sql_str:
            blocks = []
            for b_list in self.script_blocks.values():
                blocks.extend(b_list)
            return MockRowResult(blocks)

        if "shots" in sql_str:
            shots = []
            for s_list in self.shots.values():
                shots.extend(s_list)
            return MockRowResult(shots)

        if "scenes" in sql_str:
            scs = []
            for s_list in self.scenes.values():
                scs.extend(s_list)
            return MockRowResult(scs)

        return MockRowResult([])

    def add(self, obj):
        if isinstance(obj, StudioBoard):
            self.boards[obj.id] = obj
        elif isinstance(obj, AssetEpoch):
            self.epochs[obj.id] = obj
        elif isinstance(obj, Asset):
            self.assets[obj.id] = obj
        elif isinstance(obj, WorldEntity):
            self.entities[obj.id] = obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def flush(self):
        pass

    def close(self):
        pass


def create_isolated_mock_db() -> IsolatedMockSession:
    """创建并返回干净独立的测试 Session 实例。"""
    return IsolatedMockSession()
