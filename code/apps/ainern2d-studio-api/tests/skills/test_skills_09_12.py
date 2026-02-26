"""Unit tests for SKILL 09–12 execute() logic."""
from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.services.base_skill import SkillContext


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.add.return_value = None
    db.commit.return_value = None
    db.flush.return_value = None
    return db


@pytest.fixture
def ctx():
    return SkillContext(
        tenant_id="t1", project_id="p1", run_id="run09",
        trace_id="tr9", correlation_id="co9",
        idempotency_key="idem09", schema_version="1.0",
    )


# ── SKILL 09: VisualRenderPlanService ────────────────────────────────────────

class TestSkill09:
    def _make_service(self, db):
        from app.services.skills.skill_09_visual_render_plan import VisualRenderPlanService
        return VisualRenderPlanService(db)

    def _shots(self):
        return [
            {"shot_id": "sh_001", "scene_type": "outdoor", "duration_seconds": 3.0,
             "action_cues": ["sword fight", "battle"]},
            {"shot_id": "sh_002", "scene_type": "indoor", "duration_seconds": 2.0,
             "action_cues": ["talk", "dialogue"]},
        ]

    def test_execute_medium_load(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_09 import Skill09Input
        svc = self._make_service(mock_db)
        inp = Skill09Input(
            shots=self._shots(),
            compute_budget={"global_render_profile": "MEDIUM_LOAD"},
        )
        out = svc.execute(inp, ctx)
        assert out.status == "ready_for_render_execution"
        assert len(out.render_plans) == 2

    def test_high_action_uses_i2v(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_09 import Skill09Input
        svc = self._make_service(mock_db)
        inp = Skill09Input(
            shots=[{"shot_id": "sh_001", "duration_seconds": 4.0,
                    "action_cues": ["fight", "battle"]}],
            compute_budget={"global_render_profile": "MEDIUM_LOAD"},
        )
        out = svc.execute(inp, ctx)
        assert out.render_plans[0].render_mode == "i2v"

    def test_dialogue_uses_static(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_09 import Skill09Input
        svc = self._make_service(mock_db)
        inp = Skill09Input(
            shots=[{"shot_id": "sh_002", "duration_seconds": 2.0,
                    "action_cues": ["dialogue", "talk"]}],
            compute_budget={"global_render_profile": "MEDIUM_LOAD"},
        )
        out = svc.execute(inp, ctx)
        assert out.render_plans[0].render_mode == "static"

    def test_gpu_hours_positive(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_09 import Skill09Input
        svc = self._make_service(mock_db)
        inp = Skill09Input(shots=self._shots(), compute_budget={})
        out = svc.execute(inp, ctx)
        assert out.total_gpu_hours_estimate >= 0


# ── SKILL 10: PromptPlannerService ───────────────────────────────────────────

class TestSkill10:
    def _make_service(self, db):
        from app.services.skills.skill_10_prompt_planner import PromptPlannerService
        return PromptPlannerService(db)

    def _make_input(self, **overrides):
        """Build a valid Skill10Input with sensible defaults."""
        from ainern2d_shared.schemas.skills.skill_10 import Skill10Input
        base = dict(
            entity_canonicalization_result={
                "selected_culture_pack": {"id": "cn_wuxia"},
                "culture_constraints": {"visual_do": [], "visual_dont": []},
                "entity_variant_mapping": [
                    {"entity_uid": "e1", "entity_type": "character",
                     "surface_form": "李明", "visual_traits": ["dark robe"]},
                ],
                "status": "ready_for_asset_match",
            },
            asset_match_result={
                "entity_asset_matches": [
                    {"entity_uid": "e1", "lora_refs": [], "embedding_refs": []},
                ],
                "status": "ready",
            },
            visual_render_plan={
                "shot_render_plans": [
                    {"shot_id": "sh_001", "scene_id": "SC01",
                     "motion_level": "MEDIUM"},
                    {"shot_id": "sh_002", "scene_id": "SC01",
                     "motion_level": "LOW"},
                ],
                "status": "ready_for_render_execution",
            },
            shot_plan={
                "shots": [
                    {"shot_id": "sh_001", "shot_type": "medium",
                     "goal": "duel sequence", "entities": ["e1"]},
                    {"shot_id": "sh_002", "shot_type": "establishing",
                     "goal": "inn exterior", "entities": []},
                ],
            },
        )
        base.update(overrides)
        return Skill10Input(**base)

    def test_execute_basic(self, mock_db, ctx):
        svc = self._make_service(mock_db)
        inp = self._make_input()
        out = svc.execute(inp, ctx)
        assert out.status == "review_required"
        assert len(out.shot_prompt_plans) == 2

    def test_positive_prompt_contains_culture_style(self, mock_db, ctx):
        svc = self._make_service(mock_db)
        inp = self._make_input()
        out = svc.execute(inp, ctx)
        # Model variant positive prompt should contain culture keywords
        assert len(out.model_variants) > 0
        prompt = out.model_variants[0].positive_prompt.lower()
        assert any(kw in prompt for kw in ["chinese", "jianghu", "wuxia", "ancient"])

    def test_negative_prompt_not_empty(self, mock_db, ctx):
        svc = self._make_service(mock_db)
        inp = self._make_input()
        out = svc.execute(inp, ctx)
        assert len(out.shot_prompt_plans) > 0
        neg = out.shot_prompt_plans[0].negative_layers
        assert len(neg.global_negative) > 0

    def test_output_deterministic(self, mock_db, ctx):
        svc = self._make_service(mock_db)
        inp1 = self._make_input()
        inp2 = self._make_input()
        out1 = svc.execute(inp1, ctx)
        out2 = svc.execute(inp2, ctx)
        assert out1.model_variants[0].variant_id == out2.model_variants[0].variant_id


# ── SKILL 11: RagKBManagerService ────────────────────────────────────────────

class TestSkill11:
    def _make_service(self, db):
        from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
        return RagKBManagerService(db)

    def test_create_kb(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input
        svc = self._make_service(mock_db)
        inp = Skill11Input(
            kb_id="kb_t11_001",
            action="create",
            entries=[KBEntry(
                entry_id="e1", title="武侠世界设定", role="director",
                content_markdown="武侠世界观描述", entry_type="entity_profile",
                flat_tags=["wuxia"],
            )],
        )
        out = svc.execute(inp, ctx)
        assert out.status == "READY"
        assert out.kb_id == "kb_t11_001"
        assert out.entry_count == 1

    def test_publish_action(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input
        svc = self._make_service(mock_db)
        # First create an active entry
        svc.execute(Skill11Input(
            kb_id="kb_t11_002", action="create",
            entries=[KBEntry(
                entry_id="e_pub", title="规则", role="director",
                content_markdown="内容", entry_type="entity_profile",
                status="active", flat_tags=["tag1"],
            )],
        ), ctx)
        out = svc.execute(Skill11Input(kb_id="kb_t11_002", action="publish"), ctx)
        assert out.status == "READY"
        assert out.kb_version_id != ""

    def test_rollback_action(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input
        svc = self._make_service(mock_db)
        # Create + publish first
        svc.execute(Skill11Input(
            kb_id="kb_t11_003", action="create",
            entries=[KBEntry(
                entry_id="e_rb", title="条目", role="gaffer",
                content_markdown="内容", entry_type="style_guide",
                status="active", flat_tags=["t"],
            )],
        ), ctx)
        pub_out = svc.execute(Skill11Input(kb_id="kb_t11_003", action="publish"), ctx)
        # Rollback to published version
        out = svc.execute(Skill11Input(
            kb_id="kb_t11_003", action="rollback",
            rollback_target_version_id=pub_out.kb_version_id,
            rollback_reason="test rollback",
        ), ctx)
        assert out.status == "READY"
        assert "kb.version.rolled_back" in out.events_emitted

    def test_invalid_action_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import Skill11Input
        svc = self._make_service(mock_db)
        inp = Skill11Input(kb_id="kb_t11_004", action="destroy", entries=[])
        with pytest.raises(ValueError, match="RAG-VALIDATION"):
            svc.execute(inp, ctx)

    def test_auto_generates_kb_id(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import Skill11Input
        svc = self._make_service(mock_db)
        inp = Skill11Input(kb_id="", action="create", entries=[])
        out = svc.execute(inp, ctx)
        assert out.kb_id != ""


# ── SKILL 12: RagPipelineService ────────────────────────────────────────────

class TestSkill12:
    def _make_service(self, db):
        from app.services.skills.skill_12_rag_embedding import RagPipelineService
        return RagPipelineService(db)

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_12 import (
            ChunkConfig, KnowledgeItem, Skill12Input,
        )
        svc = self._make_service(mock_db)
        inp = Skill12Input(
            kb_id="kb_001",
            kb_version_id="v1.0",
            chunk_config=ChunkConfig(chunk_size=512, chunk_overlap=64),
            knowledge_items=[
                KnowledgeItem(item_id="item_1", content="Hello world. " * 100),
                KnowledgeItem(item_id="item_2", content="Test document. " * 80),
            ],
        )
        out = svc.execute(inp, ctx)
        assert out.status == "index_ready"
        assert out.index_metadata.index_id.startswith("idx_kb_001")
        assert out.index_metadata.total_vectors > 0

    def test_coverage_ratio_valid(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_12 import KnowledgeItem, Skill12Input
        svc = self._make_service(mock_db)
        inp = Skill12Input(
            kb_id="kb_002",
            kb_version_id="v1",
            knowledge_items=[
                KnowledgeItem(item_id="item_1", content="Coverage test content. " * 60),
            ],
        )
        out = svc.execute(inp, ctx)
        assert 0.0 <= out.stats.coverage_ratio <= 1.0

    def test_empty_kb_id_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_12 import Skill12Input
        svc = self._make_service(mock_db)
        inp = Skill12Input(kb_id="", kb_version_id="v1")
        with pytest.raises(ValueError, match="RAG-VALIDATION"):
            svc.execute(inp, ctx)
