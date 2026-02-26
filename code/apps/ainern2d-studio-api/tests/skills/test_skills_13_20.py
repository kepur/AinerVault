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

    def test_execute_low_rating_with_issues_creates_proposal(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_13 import (
            RunContext, ShotResultContext, UserFeedback, Skill13Input,
        )
        svc = self._make_service(mock_db)
        inp = Skill13Input(
            run_context=RunContext(run_id="r1", kb_version_id="KB_V1"),
            shot_result_context=ShotResultContext(shot_id="sh_001"),
            user_feedback=UserFeedback(
                rating=2,
                issues=["cinematography_camera_move", "motion_readability"],
                free_text="Camera moves too slow during action.",
            ),
        )
        out = svc.execute(inp, ctx)
        assert out.status == "completed"
        assert out.action_taken == "proposal_created"
        assert out.proposal is not None
        assert out.proposal.suggested_role == "cinematographer"
        assert len(out.evolution_recommendations) > 0

    def test_execute_good_rating_ignored(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_13 import (
            UserFeedback, Skill13Input,
        )
        svc = self._make_service(mock_db)
        inp = Skill13Input(
            user_feedback=UserFeedback(rating=5, issues=[], free_text="Great!"),
        )
        out = svc.execute(inp, ctx)
        assert out.action_taken == "ignored"
        assert out.proposal is None
        assert out.kb_evolution_triggered is False

    def test_free_text_only_creates_run_patch(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_13 import (
            UserFeedback, Skill13Input,
        )
        svc = self._make_service(mock_db)
        inp = Skill13Input(
            user_feedback=UserFeedback(
                rating=2, issues=[], free_text="Please make the face sharper.",
            ),
        )
        out = svc.execute(inp, ctx)
        assert out.action_taken == "run_patch"
        assert out.run_patch is not None
        assert out.kb_evolution_triggered is False


# ── SKILL 14: PersonaStyleService ────────────────────────────────────────────

class TestSkill14:
    def _make_service(self, db):
        from app.services.skills.skill_14_persona_style import PersonaStyleService
        return PersonaStyleService(db)

    def test_create_persona(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_14 import PersonaPack, Skill14Input
        svc = self._make_service(mock_db)
        pack = PersonaPack(persona_pack_id="p001", display_name="武侠导演")
        inp = Skill14Input(action="create", persona_pack=pack)
        out = svc.execute(inp, ctx)
        assert out.persona_pack_id == "p001"
        assert out.status == "draft"

    def test_publish_status(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_14 import PersonaPack, Skill14Input
        svc = self._make_service(mock_db)
        # Create first, then publish
        pack = PersonaPack(persona_pack_id="p002", display_name="测试导演")
        svc.execute(Skill14Input(action="create", persona_pack=pack), ctx)
        inp = Skill14Input(action="publish", persona_pack=PersonaPack(persona_pack_id="p002"))
        out = svc.execute(inp, ctx)
        assert out.status == "active"

    def test_invalid_action_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_14 import Skill14Input
        svc = self._make_service(mock_db)
        inp = Skill14Input(action="bogus_action")
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
        inp = Skill15Input()
        out = svc.execute(inp, ctx)
        assert out.status == "policy_ready"
        assert len(out.hard_constraints) >= 2
        assert len(out.soft_constraints) >= 2

    def test_user_override_hard_added(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_15 import Skill15Input
        svc = self._make_service(mock_db)
        overrides = [{"type": "hard_constraint", "category": "visual",
                       "dimension": "style", "parameter": "blood_splatter",
                       "rule": "no_blood_splatter", "priority": 90}]
        inp = Skill15Input(user_overrides=overrides)
        out = svc.execute(inp, ctx)
        rules = [c.rule for c in out.hard_constraints]
        assert "no_blood_splatter" in rules

    def test_exploration_policy_present(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_15 import Skill15Input
        svc = self._make_service(mock_db)
        inp = Skill15Input()
        out = svc.execute(inp, ctx)
        assert "candidate_generation" in out.exploration_policy

    def test_runtime_manifest_is_consumed(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_15 import Skill15Input
        svc = self._make_service(mock_db)
        inp = Skill15Input(
            persona_dataset_index_result={
                "runtime_manifests": [
                    {
                        "persona_ref": "director_A@2.0",
                        "style_pack_ref": "style_A@2.0",
                        "policy_override_ref": "policy_A@2.0",
                        "critic_profile_ref": "critic_A@2.0",
                        "resolved_dataset_ids": ["DS_001", "DS_002"],
                        "resolved_index_ids": ["IDX_001"],
                    }
                ]
            },
            active_persona_ref="director_A@2.0",
        )
        out = svc.execute(inp, ctx)
        rules = [c.rule for c in (out.hard_constraints + out.soft_constraints + out.guidelines)]
        assert "use_persona_style_pack" in rules
        assert "apply_persona_policy_override" in rules
        assert "critic_profile_alignment" in rules


# ── SKILL 16: CriticEvaluationService ────────────────────────────────────────

class TestSkill16:
    def _make_service(self, db):
        from app.services.skills.skill_16_critic_evaluation import CriticEvaluationService
        return CriticEvaluationService(db)

    def test_execute_with_artifact(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_16 import Skill16Input, ShotPlanEntry
        svc = self._make_service(mock_db)
        inp = Skill16Input(
            run_id="run01",
            composed_artifact_uri="s3://bucket/run01/final.mp4",
            shot_plan=[ShotPlanEntry(shot_id="S1", scene_id="SC1", description="Test shot")],
        )
        out = svc.execute(inp, ctx)
        assert out.status in ("ready", "review_required", "evaluation_complete")
        assert len(out.dimension_scores) == 8
        assert 0 <= out.composite_score <= 100

    def test_no_artifact_lower_scores(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_16 import Skill16Input
        svc = self._make_service(mock_db)
        inp_no = Skill16Input(run_id="r1", composed_artifact_uri="")
        inp_yes = Skill16Input(run_id="r1",
                                composed_artifact_uri="s3://x/y.mp4")
        out_no = svc.execute(inp_no, ctx)
        out_yes = svc.execute(inp_yes, ctx)
        assert out_yes.composite_score >= out_no.composite_score

    def test_missing_run_id_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_16 import Skill16Input
        svc = self._make_service(mock_db)
        inp = Skill16Input(run_id="")
        with pytest.raises(ValueError, match="CRITIC-VALIDATION"):
            svc.execute(inp, ctx)

    def test_continuity_exports_are_consumed(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_16 import Skill16Input, ShotPlanEntry
        svc = self._make_service(mock_db)
        inp = Skill16Input(
            run_id="run_continuity",
            composed_artifact_uri="s3://bucket/run/final.mp4",
            shot_plan=[
                ShotPlanEntry(
                    shot_id="S1",
                    scene_id="SC1",
                    description="hero closeup",
                    characters=["CHAR_0001"],
                )
            ],
            continuity_exports={
                "prompt_consistency_anchors": [
                    {"entity_id": "CHAR_0001", "continuity_status": "active"}
                ],
                "critic_rules_baseline": [
                    {"entity_id": "CHAR_0001", "identity_lock": True}
                ],
            },
        )
        out = svc.execute(inp, ctx)
        character_score = next(ds for ds in out.dimension_scores if ds.dimension == "character_consistency")
        checks = {ev.check_name for ev in character_score.evidence}
        assert "continuity_critic_rules_present" in checks
        assert "identity_lock_alignment" in checks


# ── SKILL 17: ExperimentService ──────────────────────────────────────────────

class TestSkill17:
    def _make_service(self, db):
        from app.services.skills.skill_17_experiment import ExperimentService
        return ExperimentService(db)

    def test_execute_selects_winner(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_17 import VariantConfig, Skill17Input
        svc = self._make_service(mock_db)
        inp = Skill17Input(
            experiment_name="style_test",
            control_variant=VariantConfig(variant_id="v_a", description="variant A"),
            test_variants=[VariantConfig(variant_id="v_b", description="variant B")],
        )
        out = svc.execute(inp, ctx)
        assert out.status in ("concluded", "analyzing")
        assert out.winner_variant_id in ("v_a", "v_b")
        assert len(out.variant_metrics) == 2
        assert len(out.recommendations) >= 1

    def test_empty_variants_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_17 import Skill17Input, VariantConfig
        svc = self._make_service(mock_db)
        inp = Skill17Input(
            experiment_name="test",
            control_variant=VariantConfig(variant_id="ctrl"),
            test_variants=[],
        )
        with pytest.raises(ValueError, match="EXP-VALIDATION"):
            svc.execute(inp, ctx)

    def test_deterministic_winner(self, mock_db, ctx):
        """Same input -> same winner."""
        from ainern2d_shared.schemas.skills.skill_17 import VariantConfig, Skill17Input
        svc = self._make_service(mock_db)
        inp = Skill17Input(
            control_variant=VariantConfig(variant_id="v_x"),
            test_variants=[VariantConfig(variant_id="v_y")],
        )
        w1 = svc.execute(inp, ctx).winner_variant_id
        w2 = svc.execute(inp, ctx).winner_variant_id
        assert w1 == w2

    def test_runtime_manifest_injected_to_variants(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_17 import VariantConfig, Skill17Input
        svc = self._make_service(mock_db)
        inp = Skill17Input(
            control_variant=VariantConfig(variant_id="v_ctrl"),
            test_variants=[VariantConfig(variant_id="v_test")],
            persona_dataset_index_result={
                "runtime_manifests": [
                    {
                        "persona_ref": "director_A@2.0",
                        "style_pack_ref": "style_A@2.0",
                        "policy_override_ref": "policy_A@2.0",
                        "critic_profile_ref": "critic_A@2.0",
                        "resolved_dataset_ids": ["DS_001"],
                        "resolved_index_ids": ["KB_V1"],
                    }
                ]
            },
            active_persona_ref="director_A@2.0",
        )
        out = svc.execute(inp, ctx)
        for variant in out.variants:
            assert variant.persona_version == "director_A@2.0"
            assert variant.kb_version == "KB_V1"
            assert variant.prompt_policy_version == "policy_A@2.0"
            assert variant.param_overrides.get("persona_style_pack_ref") == "style_A@2.0"


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
        # First plan step should be a retry strategy
        assert len(out.recovery_plan) > 0
        first_strategy = out.recovery_plan[0].action.strategy.value
        assert "retry" in first_strategy
        assert out.failure_classification.failure_type.value == "resource_exhaustion"

    def test_degrade_on_repeated_gpu_failure(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_18 import Skill18Input, FeatureFlags
        svc = self._make_service(mock_db)
        inp = Skill18Input(error_code="WORKER-GPU-001",
                           failed_skill="skill_09", retry_count=4,
                           feature_flags=FeatureFlags(max_retries=3))
        out = svc.execute(inp, ctx)
        # Retry budget exhausted → degradation should be in the plan
        assert out.degradation_applied is True or any(
            s.action.strategy.value == "degrade_one_level" for s in out.recovery_plan
        )

    def test_circuit_breaker_at_threshold(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_18 import Skill18Input
        svc = self._make_service(mock_db)
        # Fire multiple failures to trip circuit breaker
        for _ in range(4):
            inp = Skill18Input(error_code="SYS-DEPENDENCY-001",
                               failed_skill="skill_01", retry_count=5)
            out = svc.execute(inp, ctx)
        assert out.circuit_breaker_triggered is True
        assert len(out.circuit_breaker_states) > 0


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
