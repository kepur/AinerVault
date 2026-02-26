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

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_10 import Skill10Input
        svc = self._make_service(mock_db)
        inp = Skill10Input(
            canonical_entities=[{"entity_uid": "e1", "surface_form": "李明"}],
            asset_manifest=[],
            render_plans=[
                {"shot_id": "sh_001", "render_mode": "i2v", "fps": 24},
                {"shot_id": "sh_002", "render_mode": "static", "fps": 1},
            ],
            persona_style={"quality_preset": "standard"},
            creative_controls={"culture_pack_id": "cn_wuxia"},
        )
        out = svc.execute(inp, ctx)
        assert out.status == "ready_for_prompt_execution"
        assert len(out.shot_prompt_plans) == 2

    def test_positive_prompt_contains_culture_style(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_10 import Skill10Input
        svc = self._make_service(mock_db)
        inp = Skill10Input(
            canonical_entities=[],
            asset_manifest=[],
            render_plans=[{"shot_id": "sh_001", "render_mode": "i2v", "fps": 24}],
            creative_controls={"culture_pack_id": "cn_wuxia"},
        )
        out = svc.execute(inp, ctx)
        prompt = out.shot_prompt_plans[0].positive_prompt.lower()
        assert any(kw in prompt for kw in ["chinese", "jianghu", "wuxia", "ancient"])

    def test_negative_prompt_not_empty(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_10 import Skill10Input
        svc = self._make_service(mock_db)
        inp = Skill10Input(
            canonical_entities=[], asset_manifest=[],
            render_plans=[{"shot_id": "sh_001", "render_mode": "static", "fps": 1}],
            creative_controls={"culture_pack_id": "cn_wuxia"},
        )
        out = svc.execute(inp, ctx)
        assert out.shot_prompt_plans[0].negative_prompt != ""

    def test_seed_deterministic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_10 import Skill10Input
        svc = self._make_service(mock_db)
        render_plans = [{"shot_id": "sh_abc", "render_mode": "static", "fps": 1}]
        inp1 = Skill10Input(canonical_entities=[], asset_manifest=[],
                            render_plans=render_plans)
        inp2 = Skill10Input(canonical_entities=[], asset_manifest=[],
                            render_plans=render_plans)
        out1 = svc.execute(inp1, ctx)
        out2 = svc.execute(inp2, ctx)
        assert out1.shot_prompt_plans[0].seed == out2.shot_prompt_plans[0].seed


# ── SKILL 11: RagKBManagerService ────────────────────────────────────────────

class TestSkill11:
    def _make_service(self, db):
        from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
        return RagKBManagerService(db)

    def test_create_kb(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input
        svc = self._make_service(mock_db)
        inp = Skill11Input(
            kb_id="kb_001",
            action="create",
            entries=[KBEntry(entry_id="e1", content="武侠世界设定", entry_type="text")],
            version_label="v1.0",
        )
        out = svc.execute(inp, ctx)
        assert out.status == "ready_to_release"
        assert out.kb_id == "kb_001"
        assert out.entry_count == 1

    def test_publish_action(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import Skill11Input
        svc = self._make_service(mock_db)
        inp = Skill11Input(kb_id="kb_002", action="publish", entries=[])
        out = svc.execute(inp, ctx)
        assert out.status == "ready_to_release"

    def test_rollback_action(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import Skill11Input
        svc = self._make_service(mock_db)
        inp = Skill11Input(kb_id="kb_003", action="rollback", entries=[])
        out = svc.execute(inp, ctx)
        assert out.status == "rolled_back"

    def test_invalid_action_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import Skill11Input
        svc = self._make_service(mock_db)
        inp = Skill11Input(kb_id="kb_004", action="destroy", entries=[])
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)

    def test_auto_generates_kb_id(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_11 import Skill11Input
        svc = self._make_service(mock_db)
        inp = Skill11Input(kb_id="", action="create", entries=[])
        out = svc.execute(inp, ctx)
        assert out.kb_id != ""


# ── SKILL 12: RagEmbeddingService ────────────────────────────────────────────

class TestSkill12:
    def _make_service(self, db):
        from app.services.skills.skill_12_rag_embedding import RagEmbeddingService
        return RagEmbeddingService(db)

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_12 import ChunkConfig, Skill12Input
        svc = self._make_service(mock_db)
        inp = Skill12Input(
            kb_id="kb_001",
            version_id="v1.0",
            chunk_config=ChunkConfig(chunk_size=512, chunk_overlap=64),
            embedding_model="text-embedding-3-small",
        )
        out = svc.execute(inp, ctx)
        assert out.status == "index_ready"
        assert out.index_id.startswith("idx_kb_001")
        assert out.total_vectors > 0

    def test_coverage_ratio_valid(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_12 import Skill12Input
        svc = self._make_service(mock_db)
        inp = Skill12Input(kb_id="kb_002", version_id="v1")
        out = svc.execute(inp, ctx)
        assert 0.0 <= out.quality_report.coverage_ratio <= 1.0
        assert 0.0 <= out.quality_report.fragmentation_ratio <= 1.0

    def test_empty_kb_id_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_12 import Skill12Input
        svc = self._make_service(mock_db)
        inp = Skill12Input(kb_id="", version_id="v1")
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)
