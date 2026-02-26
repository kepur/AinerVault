"""Unit tests for SKILL 13–20 execute() logic (including composer SKILLs 06+20)."""
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
        tenant_id="t1", project_id="p1", run_id="run13",
        trace_id="tr13", correlation_id="co13",
        idempotency_key="idem13", schema_version="1.0",
    )


# ── SKILL 13: FeedbackLoopService ────────────────────────────────────────────

class TestSkill13:
    def _make_service(self, db):
        from app.services.skills.skill_13_feedback_loop import FeedbackLoopService
        return FeedbackLoopService(db)

    def test_execute_low_visual_score(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_13 import FeedbackEntry, Skill13Input
        svc = self._make_service(mock_db)
        entries = [
            FeedbackEntry(feedback_id="f1", run_id="r1", shot_id="sh_001",
                          dimension="visual", rating=2),
            FeedbackEntry(feedback_id="f2", run_id="r1", shot_id="sh_001",
                          dimension="visual", rating=1),
        ]
        inp = Skill13Input(feedback_entries=entries)
        out = svc.execute(inp, ctx)
        assert out.status == "completed"
        assert len(out.proposals) > 0
        assert any(p.target_skill == "skill_09" for p in out.proposals)

    def test_execute_good_scores_no_proposals(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_13 import FeedbackEntry, Skill13Input
        svc = self._make_service(mock_db)
        entries = [
            FeedbackEntry(feedback_id="f3", dimension="visual", rating=5),
            FeedbackEntry(feedback_id="f4", dimension="audio", rating=4),
        ]
        inp = Skill13Input(feedback_entries=entries)
        out = svc.execute(inp, ctx)
        assert out.proposals == []
        assert out.kb_evolution_triggered is False

    def test_narrative_low_triggers_kb_evolution(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_13 import FeedbackEntry, Skill13Input
        svc = self._make_service(mock_db)
        entries = [
            FeedbackEntry(feedback_id="f5", dimension="narrative", rating=1),
        ]
        inp = Skill13Input(feedback_entries=entries)
        out = svc.execute(inp, ctx)
        assert out.kb_evolution_triggered is True


# ── SKILL 14: PersonaStyleService ────────────────────────────────────────────

class TestSkill14:
    def _make_service(self, db):
        from app.services.skills.skill_14_persona_style import PersonaStyleService
        return PersonaStyleService(db)

    def test_create_persona(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_14 import PersonaDefinition, Skill14Input
        svc = self._make_service(mock_db)
        persona = PersonaDefinition(persona_id="p001", name="武侠导演",
                                     narrative_tone="cinematic")
        inp = Skill14Input(action="create", persona=persona, rag_bindings=[])
        out = svc.execute(inp, ctx)
        assert out.persona_id == "p001"
        assert out.status == "draft"

    def test_publish_status(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_14 import PersonaDefinition, Skill14Input
        svc = self._make_service(mock_db)
        inp = Skill14Input(action="publish",
                           persona=PersonaDefinition(persona_id="p002"), rag_bindings=[])
        out = svc.execute(inp, ctx)
        assert out.status == "ready_to_publish"

    def test_invalid_action_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_14 import PersonaDefinition, Skill14Input
        svc = self._make_service(mock_db)
        inp = Skill14Input(action="delete", persona=PersonaDefinition(), rag_bindings=[])
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)


# ── SKILL 15: CreativeControlService ─────────────────────────────────────────

class TestSkill15:
    def _make_service(self, db):
        from app.services.skills.skill_15_creative_control import CreativeControlService
        return CreativeControlService(db)

    def test_default_constraints_loaded(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_15 import Skill15Input
        svc = self._make_service(mock_db)
        inp = Skill15Input(persona_style={}, project_settings={}, user_overrides=[])
        out = svc.execute(inp, ctx)
        assert out.status == "policy_ready"
        assert len(out.hard_constraints) >= 2
        assert len(out.soft_constraints) >= 2

    def test_user_override_hard_added(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_15 import Skill15Input
        svc = self._make_service(mock_db)
        overrides = [{"type": "hard", "dimension": "visual",
                       "rule": "no_blood_splatter", "priority": 90}]
        inp = Skill15Input(user_overrides=overrides)
        out = svc.execute(inp, ctx)
        rules = [c.rule for c in out.hard_constraints]
        assert "no_blood_splatter" in rules

    def test_exploration_range_present(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_15 import Skill15Input
        svc = self._make_service(mock_db)
        inp = Skill15Input()
        out = svc.execute(inp, ctx)
        assert "style_variance" in out.exploration_range


# ── SKILL 16: CriticEvaluationService ────────────────────────────────────────

class TestSkill16:
    def _make_service(self, db):
        from app.services.skills.skill_16_critic_evaluation import CriticEvaluationService
        return CriticEvaluationService(db)

    def test_execute_with_artifact(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_16 import Skill16Input
        svc = self._make_service(mock_db)
        inp = Skill16Input(
            run_id="run01",
            composed_artifact_uri="s3://bucket/run01/final.mp4",
            evaluation_dimensions=["visual_consistency", "audio_sync"],
        )
        out = svc.execute(inp, ctx)
        assert out.status == "completed"
        assert len(out.dimension_scores) == 2
        assert 0 <= out.overall_score <= 10

    def test_no_artifact_lower_scores(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_16 import Skill16Input
        svc = self._make_service(mock_db)
        inp_no = Skill16Input(run_id="r1", composed_artifact_uri="",
                               evaluation_dimensions=["visual_consistency"])
        inp_yes = Skill16Input(run_id="r1",
                                composed_artifact_uri="s3://x/y.mp4",
                                evaluation_dimensions=["visual_consistency"])
        out_no = svc.execute(inp_no, ctx)
        out_yes = svc.execute(inp_yes, ctx)
        assert out_yes.overall_score >= out_no.overall_score

    def test_missing_run_id_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_16 import Skill16Input
        svc = self._make_service(mock_db)
        inp = Skill16Input(run_id="")
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)


# ── SKILL 17: ExperimentService ──────────────────────────────────────────────

class TestSkill17:
    def _make_service(self, db):
        from app.services.skills.skill_17_experiment import ExperimentService
        return ExperimentService(db)

    def test_execute_selects_winner(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_17 import ExperimentVariant, Skill17Input
        svc = self._make_service(mock_db)
        variants = [
            ExperimentVariant(variant_id="v_a", description="variant A"),
            ExperimentVariant(variant_id="v_b", description="variant B"),
        ]
        inp = Skill17Input(experiment_name="style_test",
                           variants=variants,
                           evaluation_dimensions=["overall"])
        out = svc.execute(inp, ctx)
        assert out.status == "completed"
        assert out.winner_variant_id in ("v_a", "v_b")
        assert len(out.results) == 2
        assert out.results[0].promoted is True

    def test_empty_variants_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_17 import Skill17Input
        svc = self._make_service(mock_db)
        inp = Skill17Input(experiment_name="test", variants=[])
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)

    def test_deterministic_winner(self, mock_db, ctx):
        """Same input → same winner."""
        from ainern2d_shared.schemas.skills.skill_17 import ExperimentVariant, Skill17Input
        svc = self._make_service(mock_db)
        variants = [ExperimentVariant(variant_id="v_x"), ExperimentVariant(variant_id="v_y")]
        inp = Skill17Input(variants=variants, evaluation_dimensions=["overall"])
        w1 = svc.execute(inp, ctx).winner_variant_id
        w2 = svc.execute(inp, ctx).winner_variant_id
        assert w1 == w2


# ── SKILL 18: FailureRecoveryService ─────────────────────────────────────────

class TestSkill18:
    def _make_service(self, db):
        from app.services.skills.skill_18_failure_recovery import FailureRecoveryService
        return FailureRecoveryService(db)

    def test_retry_on_first_gpu_failure(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_18 import Skill18Input
        svc = self._make_service(mock_db)
        inp = Skill18Input(error_code="WORKER-GPU-001",
                           failed_skill="skill_09", retry_count=0)
        out = svc.execute(inp, ctx)
        assert out.decision.action_type == "retry"
        assert out.circuit_breaker_triggered is False

    def test_degrade_on_repeated_gpu_failure(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_18 import Skill18Input
        svc = self._make_service(mock_db)
        inp = Skill18Input(error_code="WORKER-GPU-001",
                           failed_skill="skill_09", retry_count=2)
        out = svc.execute(inp, ctx)
        assert out.decision.action_type == "degrade"
        assert out.degradation_applied is True

    def test_circuit_breaker_at_threshold(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_18 import Skill18Input
        svc = self._make_service(mock_db)
        inp = Skill18Input(error_code="INFRA-001", failed_skill="skill_01", retry_count=5)
        out = svc.execute(inp, ctx)
        assert out.circuit_breaker_triggered is True
        assert out.decision.action_type == "abort"


# ── SKILL 19: ComputeBudgetService ───────────────────────────────────────────

class TestSkill19:
    def _make_service(self, db):
        from app.services.skills.skill_19_compute_budget import ComputeBudgetService
        return ComputeBudgetService(db)

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_19 import Skill19Input
        svc = self._make_service(mock_db)
        shots = [
            {"shot_id": "sh_001", "duration_seconds": 3.0, "action_cues": ["battle"]},
            {"shot_id": "sh_002", "duration_seconds": 2.0, "action_cues": ["dialogue"]},
        ]
        inp = Skill19Input(shots=shots, cluster_resources={"gpu_tier": "A100",
                                                            "gpu_hours_budget": 10.0})
        out = svc.execute(inp, ctx)
        assert out.status == "compute_plan_ready"
        assert len(out.shot_plans) == 2
        assert out.total_gpu_hours >= 0

    def test_high_complexity_costs_more(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_19 import Skill19Input
        svc = self._make_service(mock_db)
        resources = {"gpu_tier": "A100", "gpu_hours_budget": 10.0}
        inp_battle = Skill19Input(
            shots=[{"shot_id": "s1", "duration_seconds": 5.0, "action_cues": ["battle"]}],
            cluster_resources=resources,
        )
        inp_dialogue = Skill19Input(
            shots=[{"shot_id": "s2", "duration_seconds": 5.0, "action_cues": ["dialogue"]}],
            cluster_resources=resources,
        )
        out_b = svc.execute(inp_battle, ctx)
        out_d = svc.execute(inp_dialogue, ctx)
        assert out_b.shot_plans[0].estimated_seconds > out_d.shot_plans[0].estimated_seconds
