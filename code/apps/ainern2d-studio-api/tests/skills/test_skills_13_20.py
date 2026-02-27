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
        assert "feedback.event.created" in out.events_emitted
        assert "proposal.created" in out.events_emitted
        assert "proposal.reviewed" in out.events_emitted

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
        assert out.events_emitted == ["feedback.event.created"]
        assert out.event_envelopes[0].tenant_id == ctx.tenant_id

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
        assert "feedback.event.created" in out.events_emitted

    def test_regression_reject_triggers_rollback_event(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_13 import (
            RegressionTestResult,
            RunContext,
            ShotResultContext,
            Skill13Input,
            UserFeedback,
        )
        svc = self._make_service(mock_db)

        svc._run_regression_tests = lambda proposal: [  # type: ignore[method-assign]
            RegressionTestResult(
                test_id="rt_fail",
                proposal_id=proposal.proposal_id,
                historical_case_id="case_1",
                previous_score=0.6,
                new_score=0.2,
                passed=False,
                detail="forced failure",
            )
        ]

        inp = Skill13Input(
            run_context=RunContext(run_id="run_rb", kb_version_id="KB_V_BASE"),
            shot_result_context=ShotResultContext(shot_id="S1"),
            user_feedback=UserFeedback(
                rating=1,
                issues=["prompt_quality"],
                free_text="force regression fail path",
            ),
        )
        out = svc.execute(inp, ctx)
        assert out.status == "regression_failed"
        assert "proposal.rejected" in out.events_emitted
        assert "kb.version.rolled_back" in out.events_emitted
        rollback_env = next(
            env for env in out.event_envelopes if env.event_type == "kb.version.rolled_back"
        )
        assert rollback_env.payload["rollback_target_kb_version_id"] == "KB_V_BASE"
        assert rollback_env.payload["executor_triggered"] is False
        assert rollback_env.payload["executor_status"] == "skipped"
        assert rollback_env.payload["rollback_result_kb_version_id"] == ""

    def test_regression_reject_triggers_skill11_rollback_executor(self, mock_db, ctx):
        from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
        from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input
        from ainern2d_shared.schemas.skills.skill_13 import (
            RegressionTestResult,
            RunContext,
            ShotResultContext,
            Skill13Input,
            UserFeedback,
        )

        s11 = RagKBManagerService(mock_db)
        kb_id = "kb_skill13_executor_path"
        s11.execute(
            Skill11Input(
                kb_id=kb_id,
                action="create",
                entries=[
                    KBEntry(
                        entry_id="k1",
                        title="v1 rule",
                        content_markdown="baseline",
                        status="active",
                        entry_type="style_guide",
                    )
                ],
            ),
            ctx,
        )
        v1_out = s11.execute(Skill11Input(kb_id=kb_id, action="publish"), ctx)

        s11.execute(
            Skill11Input(
                kb_id=kb_id,
                action="create",
                entries=[
                    KBEntry(
                        entry_id="k2",
                        title="v2 rule",
                        content_markdown="candidate",
                        status="active",
                        entry_type="style_guide",
                    )
                ],
            ),
            ctx,
        )
        s11.execute(Skill11Input(kb_id=kb_id, action="publish"), ctx)

        svc = self._make_service(mock_db)
        svc._run_regression_tests = lambda proposal: [  # type: ignore[method-assign]
            RegressionTestResult(
                test_id="rt_fail_exec",
                proposal_id=proposal.proposal_id,
                historical_case_id="case_exec",
                previous_score=0.8,
                new_score=0.2,
                passed=False,
                detail="force rollback executor",
            )
        ]

        out = svc.execute(
            Skill13Input(
                run_context=RunContext(run_id="run_exec", kb_version_id=v1_out.kb_version_id),
                shot_result_context=ShotResultContext(shot_id="S2"),
                user_feedback=UserFeedback(
                    rating=1,
                    issues=["art_style"],
                    free_text="force executor path",
                ),
                kb_manager_config={
                    "kb_id": kb_id,
                    "enable_skill11_rollback": True,
                },
            ),
            ctx,
        )
        rollback_env = next(
            env for env in out.event_envelopes if env.event_type == "kb.version.rolled_back"
        )
        rollback_payload = rollback_env.payload
        assert rollback_payload["rollback_target_kb_version_id"] == v1_out.kb_version_id
        assert rollback_payload["executor_triggered"] is True
        assert rollback_payload["executor_status"] == "ready"
        assert rollback_payload["rollback_result_kb_version_id"].startswith("KB_RB_")

        out_export = s11.execute(Skill11Input(kb_id=kb_id, action="export"), ctx)
        assert out_export.kb_version_id == rollback_payload["rollback_result_kb_version_id"]


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
        assert out.style_pack_ref == "p001@0.1.0"
        assert out.persona_pack_version_ref == "p001@0.1.0"

    def test_publish_status(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_14 import (
            CriticThresholdOverride,
            PersonaPack,
            PolicyOverride,
            Skill14Input,
        )
        svc = self._make_service(mock_db)
        # Create first, then publish
        pack = PersonaPack(
            persona_pack_id="p002",
            display_name="测试导演",
            policy_override=PolicyOverride(prefer_microshots_in_high_motion=True),
            critic_threshold_override=CriticThresholdOverride(motion_readability_min=0.82),
        )
        svc.execute(Skill14Input(action="create", persona_pack=pack), ctx)
        inp = Skill14Input(action="publish", persona_pack=PersonaPack(persona_pack_id="p002"))
        out = svc.execute(inp, ctx)
        assert out.status == "active"
        assert out.style_pack_ref == f"p002@{out.current_version}"
        assert out.persona_pack_version_ref == f"p002@{out.current_version}"
        assert out.policy_override_ref.endswith(":policy")
        assert out.critic_profile_ref.endswith(":critic")

    def test_update_with_rollback_to_version(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_14 import PersonaPack, Skill14Input

        svc = self._make_service(mock_db)
        created = svc.execute(
            Skill14Input(
                action="create",
                persona_pack=PersonaPack(persona_pack_id="p003", display_name="rollback_demo"),
            ),
            ctx,
        )
        base_version = created.current_version

        updated = svc.execute(
            Skill14Input(
                action="update",
                persona_pack=PersonaPack(
                    persona_pack_id="p003",
                    display_name="rollback_demo_v2",
                ),
            ),
            ctx,
        )
        assert updated.current_version != base_version

        rolled = svc.execute(
            Skill14Input(
                action="update",
                target_pack_id="p003",
                rollback_to_version=base_version,
            ),
            ctx,
        )
        assert rolled.status == "draft"
        assert any("rolled back to" in w for w in rolled.warnings)
        assert rolled.style_pack_ref == f"p003@{rolled.current_version}"

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
        assert out.policy_stack_id.startswith("CPS_")
        assert out.policy_stack_name == f"run_policy_{ctx.run_id}"
        assert out.policy_event_id.startswith("evt_")
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
        assert len(out.summary_scores) == 8
        assert 0 <= out.composite_score <= 100
        assert 0.0 <= out.normalized_composite_score <= 1.0
        assert out.score_scale == "0-100"

    def test_threshold_supports_normalized_scale(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_16 import (
            SCORE_SCALE_0_1,
            Skill16FeatureFlags,
            Skill16Input,
            ShotPlanEntry,
        )
        svc = self._make_service(mock_db)
        inp = Skill16Input(
            run_id="run_norm_scale",
            composed_artifact_uri="s3://bucket/run_norm_scale/final.mp4",
            shot_plan=[ShotPlanEntry(shot_id="S1", scene_id="SC1", description="norm")],
            feature_flags=Skill16FeatureFlags(
                auto_fail_threshold=0.9,
                score_scale=SCORE_SCALE_0_1,
            ),
        )
        out = svc.execute(inp, ctx)
        assert out.auto_fail_threshold == 90.0
        assert out.normalized_auto_fail_threshold == 0.9
        assert all(0.0 <= score <= 1.0 for score in out.summary_scores.values())

    def test_threshold_supports_implicit_normalized_value(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_16 import Skill16FeatureFlags, Skill16Input
        svc = self._make_service(mock_db)
        inp = Skill16Input(
            run_id="run_norm_hint",
            composed_artifact_uri="s3://bucket/run_norm_hint/final.mp4",
            feature_flags=Skill16FeatureFlags(auto_fail_threshold=0.85),
        )
        out = svc.execute(inp, ctx)
        assert out.auto_fail_threshold == 85.0
        assert out.normalized_auto_fail_threshold == 0.85
        assert any("converted to 0-100" in w for w in out.warnings)

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
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
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

    @staticmethod
    def _build_critic_reports(
        variant_scores: dict[str, float],
        sample_count: int = 12,
    ) -> dict[str, list[dict]]:
        from ainern2d_shared.schemas.skills.skill_17 import CRITIC_DIMENSIONS

        reports: dict[str, list[dict]] = {}
        for variant_id, base_score in variant_scores.items():
            samples: list[dict] = []
            for i in range(sample_count):
                score = max(0.0, min(1.0, base_score + ((i % 3) - 1) * 0.01))
                summary_scores = {dim: round(score, 4) for dim in CRITIC_DIMENSIONS}
                dimension_scores = [
                    {"dimension": dim, "score": round(score * 100.0, 2), "max_score": 100.0}
                    for dim in CRITIC_DIMENSIONS
                ]
                samples.append(
                    {
                        "summary_scores": summary_scores,
                        "dimension_scores": dimension_scores,
                    }
                )
            reports[variant_id] = samples
        return reports

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
        assert out.promotion_gate_passed is False

    def test_empty_variants_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_17 import Skill17Input, VariantConfig
        svc = self._make_service(mock_db)
        inp = Skill17Input(
            experiment_name="test",
            control_variant=VariantConfig(variant_id="ctrl"),
            test_variants=[],
        )
        with pytest.raises(ValueError, match="PLAN-VALIDATION"):
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

    def test_no_critic_reports_no_synthetic_samples(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_17 import Skill17Input, VariantConfig
        svc = self._make_service(mock_db)
        out = svc.execute(
            Skill17Input(
                control_variant=VariantConfig(variant_id="ctrl"),
                test_variants=[VariantConfig(variant_id="test")],
            ),
            ctx,
        )
        metrics = {m.variant_id: m for m in out.variant_metrics}
        assert metrics["ctrl"].sample_count == 0
        assert metrics["test"].sample_count == 0
        assert any("missing_critic_reports:ctrl" in w for w in out.warnings)
        assert any("missing_critic_reports:test" in w for w in out.warnings)

    def test_promotion_gate_blocks_when_auto_promote_disabled(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_17 import (
            FeatureFlags,
            Skill17Input,
            VariantConfig,
        )
        svc = self._make_service(mock_db)
        critic_reports = self._build_critic_reports({"v_ctrl": 0.72, "v_test": 0.92})
        out = svc.execute(
            Skill17Input(
                control_variant=VariantConfig(variant_id="v_ctrl"),
                test_variants=[VariantConfig(variant_id="v_test")],
                critic_reports=critic_reports,
                feature_flags=FeatureFlags(enable_auto_promote=False, min_sample_size=10),
            ),
            ctx,
        )
        assert any(r.decision == "promote_to_default" for r in out.recommendations)
        assert out.promotion_candidate_id == "v_test"
        assert out.promotion_gate_passed is False
        assert out.promotion_block_reason == "enable_auto_promote_disabled"
        assert out.winner_variant_id == "v_ctrl"

    def test_promotion_gate_passes_with_auto_promote(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_17 import (
            FeatureFlags,
            Skill17Input,
            VariantConfig,
        )
        svc = self._make_service(mock_db)
        critic_reports = self._build_critic_reports({"v_ctrl": 0.70, "v_test": 0.93})
        out = svc.execute(
            Skill17Input(
                control_variant=VariantConfig(variant_id="v_ctrl"),
                test_variants=[VariantConfig(variant_id="v_test")],
                critic_reports=critic_reports,
                feature_flags=FeatureFlags(enable_auto_promote=True, min_sample_size=10),
            ),
            ctx,
        )
        assert out.promotion_candidate_id == "v_test"
        assert out.promotion_gate_passed is True
        assert out.promotion_block_reason == ""
        assert out.winner_variant_id == "v_test"

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
        from ainern2d_shared.schemas.skills.skill_18 import (
            DegradationLevel,
            FeatureFlags,
            Skill18Input,
        )
        svc = self._make_service(mock_db)
        inp = Skill18Input(error_code="WORKER-GPU-001",
                           failed_skill="skill_09", retry_count=4,
                           feature_flags=FeatureFlags(max_retries=3, enable_backend_fallback=False))
        out = svc.execute(inp, ctx)
        # Retry budget exhausted → degradation should be in the plan
        assert out.degradation_applied is True or any(
            s.action.strategy.value == "degrade_one_level" for s in out.recovery_plan
        )
        if out.degradation_applied:
            assert out.degradation_level == DegradationLevel.L1_SHORTEN_DURATION

    def test_legacy_manual_review_threshold_is_compatible(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_18 import FeatureFlags, Skill18Input
        svc = self._make_service(mock_db)
        out = svc.execute(
            Skill18Input(
                error_code="WORKER-GPU-001",
                failed_skill="skill_09",
                retry_count=4,
                feature_flags=FeatureFlags(
                    max_retries=3,
                    enable_backend_fallback=False,
                    manual_review_threshold="L5_PLACEHOLDER_ASSET",
                ),
            ),
            ctx,
        )
        assert out.degradation_applied is True
        assert out.manual_review_required is False

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

    def test_historical_stats_adjust_estimation(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_19 import Skill19Input

        svc = self._make_service(mock_db)
        resources = {"gpu_tier": "A100", "gpu_hours_budget": 10.0}
        shots = [{
            "shot_id": "hist_001",
            "shot_type": "dialogue",
            "duration_seconds": 3.0,
            "action_cues": ["dialogue"],
        }]

        out_without_history = svc.execute(
            Skill19Input(shots=shots, cluster_resources=resources),
            ctx,
        )
        out_with_history = svc.execute(
            Skill19Input(
                shots=shots,
                cluster_resources=resources,
                historical_render_stats=[{
                    "shot_type": "dialogue",
                    "complexity": "low",
                    "sample_count": 30,
                    "avg_gpu_sec_per_second": 20.0,
                    "p95_gpu_sec_per_second": 24.0,
                    "overrun_rate": 0.2,
                }],
            ),
            ctx,
        )

        base_plan = out_without_history.shot_plans[0]
        hist_plan = out_with_history.shot_plans[0]
        assert hist_plan.estimated_seconds > base_plan.estimated_seconds
        assert hist_plan.estimated_cost.historical_factor > 1.0
        assert hist_plan.estimated_cost.history_confidence > 0.0

    def test_dynamic_reallocation_prefers_deficit_fill(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_19 import Skill19Input

        svc = self._make_service(mock_db)
        out = svc.execute(
            Skill19Input(
                shots=[
                    {
                        "shot_id": "heavy",
                        "shot_type": "battle",
                        "duration_seconds": 4.0,
                        "action_cues": ["battle"],
                        "narrative_importance": 1.0,
                        "visual_complexity": 1.0,
                        "motion_score": 1.0,
                        "user_priority": 1.0,
                    },
                    {
                        "shot_id": "light",
                        "shot_type": "dialogue",
                        "duration_seconds": 1.0,
                        "action_cues": ["dialogue"],
                        "narrative_importance": 1.0,
                        "visual_complexity": 0.5,
                        "motion_score": 0.5,
                        "user_priority": 1.0,
                    },
                ],
                cluster_resources={
                    "gpu_tier": "A100",
                    "gpu_hours_budget": 150.0 / 3600.0,
                },
            ),
            ctx,
        )

        deficit_logs = [
            row for row in out.reallocation_log
            if row.get("shot_id") == "heavy" and row.get("action") == "deficit_fill"
        ]
        assert deficit_logs
        assert deficit_logs[0]["new_budget_gpu_sec"] > deficit_logs[0]["old_budget_gpu_sec"]
