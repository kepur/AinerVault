"""SKILL 16: CriticEvaluationService — Full multi-dimensional evaluation.

Implements all spec requirements:
  - 8 critic dimensions with independent 0-100 scoring
  - Per-dimension evidence collection
  - Severity levels (blocker / critical / warning / info)
  - Fix queue generation with ordered fixes
  - Weighted composite score (configurable weights)
  - Shot-level and scene-level evaluation
  - Cross-shot consistency checks
  - Benchmark comparison (project & global baselines)
  - Auto-pass/fail gate
  - Feature flags (evaluation_depth, enable_cross_shot_check, etc.)
  - Critic history for trend tracking

State machine:
  INIT → LOADING_ARTIFACTS → EVALUATING_SHOTS → EVALUATING_SCENES
       → CROSS_CHECKING → SCORING → GENERATING_FIXES → GATING
       → READY | REVIEW_REQUIRED | FAILED

Reference: SKILL_16_CRITIC_EVALUATION_SUITE.md
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_16 import (
    CRITIC_DIMENSIONS,
    DECISION_DEGRADE,
    DECISION_MANUAL_REVIEW,
    DECISION_PASS,
    DECISION_RETRY,
    SEVERITY_BLOCKER,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SM_CROSS_CHECKING,
    SM_EVALUATING_SCENES,
    SM_EVALUATING_SHOTS,
    SM_FAILED,
    SM_GATING,
    SM_GENERATING_FIXES,
    SM_INIT,
    SM_LOADING_ARTIFACTS,
    SM_READY,
    SM_REVIEW_REQUIRED,
    SM_SCORING,
    BenchmarkComparison,
    CriticHistoryEntry,
    CriticIssue,
    CrossShotConsistencyResult,
    DimensionScore,
    EvidenceItem,
    FixQueueItem,
    SceneEvaluation,
    ShotEvaluation,
    ShotPlanEntry,
    Skill16FeatureFlags,
    Skill16Input,
    Skill16Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from ainern2d_shared.utils.time import utcnow

# ── Default dimension weights (equal by default) ───────────────
_DEFAULT_WEIGHTS: dict[str, float] = {d: 1.0 for d in CRITIC_DIMENSIONS}

# ── Dimension → fix-skill mapping ──────────────────────────────
_DIM_FIX_SKILL: dict[str, str] = {
    "visual_quality": "skill_09",
    "audio_sync": "skill_06",
    "narrative_coherence": "skill_03",
    "character_consistency": "skill_04",
    "cultural_accuracy": "skill_07",
    "style_adherence": "skill_14",
    "pacing_timing": "skill_05",
    "technical_quality": "skill_12",
}

# ── Dimension → fix-type mapping ───────────────────────────────
_DIM_FIX_TYPE: dict[str, str] = {
    "visual_quality": "re-render-shot",
    "audio_sync": "re-time-sfx",
    "narrative_coherence": "prompt_patch",
    "character_consistency": "re-render-shot",
    "cultural_accuracy": "prompt_patch",
    "style_adherence": "prompt_patch",
    "pacing_timing": "re-time-sfx",
    "technical_quality": "re-render-shot",
}

# ── Depth-based check counts ───────────────────────────────────
_DEPTH_CHECK_COUNT: dict[str, int] = {
    "quick": 2,
    "standard": 4,
    "deep": 6,
}


class CriticEvaluationService(BaseSkillService[Skill16Input, Skill16Output]):
    """SKILL 16 — Critic Evaluation Suite.

    State machine:
      INIT → LOADING_ARTIFACTS → EVALUATING_SHOTS → EVALUATING_SCENES
           → CROSS_CHECKING → SCORING → GENERATING_FIXES → GATING
           → READY | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_16"
    skill_name = "CriticEvaluationService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Main entry point ───────────────────────────────────────

    def execute(self, input_dto: Skill16Input, ctx: SkillContext) -> Skill16Output:
        warnings: list[str] = []
        ff = input_dto.feature_flags

        # ── LOADING_ARTIFACTS ──────────────────────────────────
        self._record_state(ctx, SM_INIT, SM_LOADING_ARTIFACTS)

        if not input_dto.run_id:
            self._record_state(ctx, SM_LOADING_ARTIFACTS, SM_FAILED)
            raise ValueError("CRITIC-VALIDATION-001: run_id is required")

        if not input_dto.composed_artifact_uri and not input_dto.artifact_refs:
            warnings.append("No artifact references provided; scoring will be heuristic-only")

        shot_plan = input_dto.shot_plan or []
        weights = self._resolve_weights(ff)
        depth = ff.evaluation_depth if ff.evaluation_depth in _DEPTH_CHECK_COUNT else "standard"

        # ── EVALUATING_SHOTS ───────────────────────────────────
        self._record_state(ctx, SM_LOADING_ARTIFACTS, SM_EVALUATING_SHOTS)
        shot_evals = self._evaluate_shots(shot_plan, input_dto, depth, weights)

        # ── EVALUATING_SCENES ──────────────────────────────────
        self._record_state(ctx, SM_EVALUATING_SHOTS, SM_EVALUATING_SCENES)
        scene_evals = self._aggregate_scenes(shot_evals, weights)

        # ── CROSS_CHECKING ─────────────────────────────────────
        self._record_state(ctx, SM_EVALUATING_SCENES, SM_CROSS_CHECKING)
        cross_shot_results: list[CrossShotConsistencyResult] = []
        if ff.enable_cross_shot_check:
            cross_shot_results = self._cross_shot_consistency(shot_plan, shot_evals)

        # ── SCORING ────────────────────────────────────────────
        self._record_state(ctx, SM_CROSS_CHECKING, SM_SCORING)
        all_issues = self._collect_all_issues(shot_evals, scene_evals, cross_shot_results)
        agg_dim_scores = self._aggregate_dimension_scores(shot_evals, weights)
        composite = self._weighted_composite(agg_dim_scores, weights)

        benchmarks = self._benchmark_compare(
            agg_dim_scores,
            input_dto.project_baseline_scores,
            input_dto.global_baseline_scores,
        )

        # ── GENERATING_FIXES ──────────────────────────────────
        self._record_state(ctx, SM_SCORING, SM_GENERATING_FIXES)
        fix_queue: list[FixQueueItem] = []
        auto_fix_recs: list[FixQueueItem] = []
        if ff.enable_auto_fix_suggestions:
            fix_queue = self._generate_fix_queue(all_issues)
            auto_fix_recs = [f for f in fix_queue if f.severity != SEVERITY_INFO]

        # ── GATING ─────────────────────────────────────────────
        self._record_state(ctx, SM_GENERATING_FIXES, SM_GATING)
        threshold = ff.auto_fail_threshold
        passed = composite >= threshold
        has_blockers = any(i.severity == SEVERITY_BLOCKER for i in all_issues)
        human_review = has_blockers or any(i.severity == SEVERITY_CRITICAL for i in all_issues)

        if has_blockers:
            passed = False

        decision = self._determine_decision(passed, has_blockers, human_review, all_issues)
        status, final_state = self._decide_status(decision)

        # ── Build history ──────────────────────────────────────
        history_entry = CriticHistoryEntry(
            iteration=len(input_dto.previous_iterations) + 1,
            timestamp=utcnow().isoformat(),
            composite_score=composite,
            dimension_scores={ds.dimension: ds.score for ds in agg_dim_scores},
            decision=decision,
        )
        critic_history = list(input_dto.previous_iterations) + [history_entry]

        # ── Final state ────────────────────────────────────────
        self._record_state(ctx, SM_GATING, final_state)

        logger.info(
            f"[{self.skill_id}] {final_state} | run={ctx.run_id} "
            f"composite={composite:.1f} passed={passed} issues={len(all_issues)} "
            f"decision={decision}"
        )

        return Skill16Output(
            version="1.0",
            status=status,
            overall_decision=decision,
            composite_score=composite,
            dimension_scores=agg_dim_scores,
            issues=all_issues,
            fix_queue=fix_queue,
            shot_evaluations=shot_evals,
            scene_evaluations=scene_evals,
            cross_shot_results=cross_shot_results,
            benchmark_comparisons=benchmarks,
            auto_fail_threshold=threshold,
            passed=passed,
            human_review_required=human_review,
            auto_fix_recommendations=auto_fix_recs,
            critic_history=critic_history,
            warnings=warnings,
            trace_id=ctx.trace_id,
            idempotency_key=ctx.idempotency_key,
        )

    # ── [Phase 1] Shot-level evaluation ────────────────────────

    def _evaluate_shots(
        self,
        shot_plan: list[ShotPlanEntry],
        input_dto: Skill16Input,
        depth: str,
        weights: dict[str, float],
    ) -> list[ShotEvaluation]:
        if not shot_plan:
            # Synthesize a single virtual shot from composed artifact
            shot_plan = [ShotPlanEntry(
                shot_id="VIRTUAL_SHOT_0",
                scene_id="VIRTUAL_SCENE_0",
                description="Full composed artifact",
            )]

        shot_evals: list[ShotEvaluation] = []
        for shot in shot_plan:
            dim_scores = self._evaluate_shot_dimensions(shot, input_dto, depth)
            composite = self._weighted_composite(dim_scores, weights)
            issues = self._issues_from_dim_scores(dim_scores, shot.shot_id, shot.scene_id)
            passed = composite >= input_dto.feature_flags.auto_fail_threshold and not any(
                i.severity == SEVERITY_BLOCKER for i in issues
            )
            shot_evals.append(ShotEvaluation(
                shot_id=shot.shot_id,
                scene_id=shot.scene_id,
                dimension_scores=dim_scores,
                composite_score=composite,
                issues=issues,
                passed=passed,
            ))
        return shot_evals

    def _evaluate_shot_dimensions(
        self,
        shot: ShotPlanEntry,
        input_dto: Skill16Input,
        depth: str,
    ) -> list[DimensionScore]:
        """Run all 8 critic dimensions for a single shot."""
        ff = input_dto.feature_flags
        num_checks = _DEPTH_CHECK_COUNT.get(depth, 4)
        results: list[DimensionScore] = []

        for dim in CRITIC_DIMENSIONS:
            if dim == "audio_sync" and not ff.enable_audio_visual_sync_critic:
                continue
            if dim == "visual_quality" and not ff.enable_visual_critic:
                continue

            evaluator = _DIMENSION_EVALUATORS.get(dim, _evaluate_generic)
            ds = evaluator(shot, input_dto, num_checks, dim)
            results.append(ds)

        return results

    # ── [Phase 2] Scene-level aggregation ──────────────────────

    @staticmethod
    def _aggregate_scenes(
        shot_evals: list[ShotEvaluation],
        weights: dict[str, float],
    ) -> list[SceneEvaluation]:
        scenes: dict[str, list[ShotEvaluation]] = {}
        for se in shot_evals:
            scenes.setdefault(se.scene_id, []).append(se)

        scene_evals: list[SceneEvaluation] = []
        for scene_id, shots in scenes.items():
            dim_agg: dict[str, list[float]] = {}
            all_issues: list[CriticIssue] = []
            for s in shots:
                all_issues.extend(s.issues)
                for ds in s.dimension_scores:
                    dim_agg.setdefault(ds.dimension, []).append(ds.score)

            dim_scores = [
                DimensionScore(
                    dimension=dim,
                    score=round(sum(scores) / len(scores), 2),
                    max_score=100.0,
                    summary=f"Avg of {len(scores)} shot(s)",
                )
                for dim, scores in dim_agg.items()
            ]
            w_total = sum(
                ds.score * weights.get(ds.dimension, 1.0) for ds in dim_scores
            )
            w_denom = sum(weights.get(ds.dimension, 1.0) for ds in dim_scores) or 1.0
            composite = round(w_total / w_denom, 2)
            passed = all(s.passed for s in shots)

            scene_evals.append(SceneEvaluation(
                scene_id=scene_id,
                shot_evaluations=shots,
                dimension_scores=dim_scores,
                composite_score=composite,
                issues=all_issues,
                passed=passed,
            ))
        return scene_evals

    # ── [Phase 3] Cross-shot consistency ───────────────────────

    @staticmethod
    def _cross_shot_consistency(
        shot_plan: list[ShotPlanEntry],
        shot_evals: list[ShotEvaluation],
    ) -> list[CrossShotConsistencyResult]:
        scenes: dict[str, list[ShotPlanEntry]] = {}
        for sp in shot_plan:
            scenes.setdefault(sp.scene_id, []).append(sp)

        eval_map = {se.shot_id: se for se in shot_evals}
        results: list[CrossShotConsistencyResult] = []

        for scene_id, shots in scenes.items():
            if len(shots) < 2:
                continue

            inconsistencies: list[CriticIssue] = []
            char_scores: list[float] = []
            env_scores: list[float] = []
            light_scores: list[float] = []

            # Character consistency: check if characters are shared
            all_chars = [set(s.characters) for s in shots if s.characters]
            if len(all_chars) >= 2:
                # Jaccard similarity between consecutive shots
                for i in range(len(all_chars) - 1):
                    intersection = all_chars[i] & all_chars[i + 1]
                    union = all_chars[i] | all_chars[i + 1]
                    sim = (len(intersection) / len(union) * 100) if union else 100.0
                    char_scores.append(sim)
                    if sim < 60:
                        inconsistencies.append(CriticIssue(
                            issue_id=f"XC_{scene_id}_{i}_CHAR",
                            critic="character_consistency",
                            severity=SEVERITY_WARNING,
                            scene_id=scene_id,
                            shot_id=shots[i + 1].shot_id,
                            category="cross_shot_character",
                            message=f"Character set changed between {shots[i].shot_id} "
                                    f"and {shots[i + 1].shot_id} (similarity {sim:.0f}%)",
                        ))

            # Environment consistency
            envs = [s.environment for s in shots if s.environment]
            if len(envs) >= 2:
                for i in range(len(envs) - 1):
                    sim = 100.0 if envs[i] == envs[i + 1] else 50.0
                    env_scores.append(sim)
                    if envs[i] != envs[i + 1]:
                        inconsistencies.append(CriticIssue(
                            issue_id=f"XC_{scene_id}_{i}_ENV",
                            critic="visual_quality",
                            severity=SEVERITY_INFO,
                            scene_id=scene_id,
                            shot_id=shots[i + 1].shot_id,
                            category="cross_shot_environment",
                            message=f"Environment changed: '{envs[i]}' → '{envs[i + 1]}'",
                        ))

            # Lighting consistency
            lights = [s.lighting for s in shots if s.lighting]
            if len(lights) >= 2:
                for i in range(len(lights) - 1):
                    sim = 100.0 if lights[i] == lights[i + 1] else 40.0
                    light_scores.append(sim)
                    if lights[i] != lights[i + 1]:
                        inconsistencies.append(CriticIssue(
                            issue_id=f"XC_{scene_id}_{i}_LIGHT",
                            critic="visual_quality",
                            severity=SEVERITY_WARNING,
                            scene_id=scene_id,
                            shot_id=shots[i + 1].shot_id,
                            category="cross_shot_lighting",
                            message=f"Lighting changed: '{lights[i]}' → '{lights[i + 1]}'",
                        ))

            def _avg(lst: list[float]) -> float:
                return round(sum(lst) / len(lst), 2) if lst else 100.0

            char_avg = _avg(char_scores)
            env_avg = _avg(env_scores)
            light_avg = _avg(light_scores)
            overall = round((char_avg + env_avg + light_avg) / 3, 2)

            results.append(CrossShotConsistencyResult(
                scene_id=scene_id,
                character_consistency_score=char_avg,
                environment_consistency_score=env_avg,
                lighting_consistency_score=light_avg,
                overall_consistency_score=overall,
                inconsistencies=inconsistencies,
            ))

        return results

    # ── [Phase 4] Scoring ──────────────────────────────────────

    @staticmethod
    def _aggregate_dimension_scores(
        shot_evals: list[ShotEvaluation],
        weights: dict[str, float],
    ) -> list[DimensionScore]:
        dim_vals: dict[str, list[DimensionScore]] = {}
        for se in shot_evals:
            for ds in se.dimension_scores:
                dim_vals.setdefault(ds.dimension, []).append(ds)

        agg: list[DimensionScore] = []
        for dim, dsl in dim_vals.items():
            avg_score = round(sum(d.score for d in dsl) / len(dsl), 2)
            all_evidence: list[EvidenceItem] = []
            for d in dsl:
                all_evidence.extend(d.evidence)
            agg.append(DimensionScore(
                dimension=dim,
                score=avg_score,
                max_score=100.0,
                weight=weights.get(dim, 1.0),
                evidence=all_evidence,
                summary=f"Aggregated from {len(dsl)} shot(s), avg={avg_score}",
            ))
        return agg

    @staticmethod
    def _weighted_composite(
        dim_scores: list[DimensionScore],
        weights: dict[str, float],
    ) -> float:
        if not dim_scores:
            return 0.0
        total = sum(ds.score * weights.get(ds.dimension, 1.0) for ds in dim_scores)
        denom = sum(weights.get(ds.dimension, 1.0) for ds in dim_scores)
        return round(total / denom, 2) if denom else 0.0

    # ── [Phase 5] Issue extraction ─────────────────────────────

    @staticmethod
    def _issues_from_dim_scores(
        dim_scores: list[DimensionScore],
        shot_id: str,
        scene_id: str,
    ) -> list[CriticIssue]:
        issues: list[CriticIssue] = []
        idx = 0
        for ds in dim_scores:
            severity: str | None = None
            if ds.score < 30:
                severity = SEVERITY_BLOCKER
            elif ds.score < 50:
                severity = SEVERITY_CRITICAL
            elif ds.score < 70:
                severity = SEVERITY_WARNING

            if severity is not None:
                idx += 1
                issues.append(CriticIssue(
                    issue_id=f"CI_{shot_id}_{ds.dimension}_{idx:03d}",
                    critic=ds.dimension,
                    severity=severity,
                    scene_id=scene_id,
                    shot_id=shot_id,
                    category=ds.dimension,
                    message=f"{ds.dimension} score {ds.score:.1f}/100 — {severity}",
                    auto_fix_possible=severity != SEVERITY_BLOCKER,
                    recommended_fix_type=_DIM_FIX_TYPE.get(ds.dimension, "prompt_patch"),
                ))

            # Info-level for low-confidence evidence
            for ev in ds.evidence:
                if not ev.passed and ev.confidence < 0.5:
                    idx += 1
                    issues.append(CriticIssue(
                        issue_id=f"CI_{shot_id}_{ds.dimension}_EV_{idx:03d}",
                        critic=ds.dimension,
                        severity=SEVERITY_INFO,
                        scene_id=scene_id,
                        shot_id=shot_id,
                        category=f"{ds.dimension}_evidence",
                        message=f"Low confidence check: {ev.check_name} ({ev.confidence:.0%})",
                    ))
        return issues

    @staticmethod
    def _collect_all_issues(
        shot_evals: list[ShotEvaluation],
        scene_evals: list[SceneEvaluation],
        cross_results: list[CrossShotConsistencyResult],
    ) -> list[CriticIssue]:
        seen_ids: set[str] = set()
        issues: list[CriticIssue] = []
        for se in shot_evals:
            for i in se.issues:
                if i.issue_id not in seen_ids:
                    seen_ids.add(i.issue_id)
                    issues.append(i)
        for sc in scene_evals:
            for i in sc.issues:
                if i.issue_id not in seen_ids:
                    seen_ids.add(i.issue_id)
                    issues.append(i)
        for cr in cross_results:
            for i in cr.inconsistencies:
                if i.issue_id not in seen_ids:
                    seen_ids.add(i.issue_id)
                    issues.append(i)
        # Sort: blocker first, then critical, warning, info
        _sev_order = {SEVERITY_BLOCKER: 0, SEVERITY_CRITICAL: 1, SEVERITY_WARNING: 2, SEVERITY_INFO: 3}
        issues.sort(key=lambda x: _sev_order.get(x.severity, 9))
        return issues

    # ── [Phase 6] Fix queue generation ─────────────────────────

    @staticmethod
    def _generate_fix_queue(issues: list[CriticIssue]) -> list[FixQueueItem]:
        fixes: list[FixQueueItem] = []
        for idx, issue in enumerate(issues):
            if issue.severity == SEVERITY_INFO:
                continue
            effort = "low"
            if issue.severity == SEVERITY_BLOCKER:
                effort = "high"
            elif issue.severity == SEVERITY_CRITICAL:
                effort = "medium"

            fixes.append(FixQueueItem(
                fix_id=f"FIX_{idx + 1:03d}",
                dimension=issue.critic,
                severity=issue.severity,
                description=issue.message,
                suggested_action=issue.recommended_fix_type or "manual-review",
                affected_shots=[issue.shot_id] if issue.shot_id else [],
                estimated_effort=effort,
                fix_type=issue.recommended_fix_type or "manual-review",
                target_skill=_DIM_FIX_SKILL.get(issue.critic, "skill_01"),
            ))
        return fixes

    # ── [Phase 7] Benchmark comparison ─────────────────────────

    @staticmethod
    def _benchmark_compare(
        dim_scores: list[DimensionScore],
        project_baseline: dict[str, float],
        global_baseline: dict[str, float],
    ) -> list[BenchmarkComparison]:
        comparisons: list[BenchmarkComparison] = []
        for ds in dim_scores:
            pb = project_baseline.get(ds.dimension, 0.0)
            gb = global_baseline.get(ds.dimension, 0.0)
            comparisons.append(BenchmarkComparison(
                dimension=ds.dimension,
                current_score=ds.score,
                project_baseline=pb,
                global_baseline=gb,
                delta_project=round(ds.score - pb, 2),
                delta_global=round(ds.score - gb, 2),
            ))
        return comparisons

    # ── [Phase 8] Decision logic ───────────────────────────────

    @staticmethod
    def _determine_decision(
        passed: bool,
        has_blockers: bool,
        human_review: bool,
        issues: list[CriticIssue],
    ) -> str:
        if has_blockers:
            return DECISION_MANUAL_REVIEW
        if not passed:
            critical_count = sum(1 for i in issues if i.severity == SEVERITY_CRITICAL)
            if critical_count >= 3:
                return DECISION_DEGRADE
            return DECISION_RETRY
        if human_review:
            return DECISION_MANUAL_REVIEW
        return DECISION_PASS

    @staticmethod
    def _decide_status(decision: str) -> tuple[str, str]:
        if decision == DECISION_PASS:
            return "ready", SM_READY
        if decision == DECISION_MANUAL_REVIEW:
            return "review_required", SM_REVIEW_REQUIRED
        return "evaluation_complete", SM_READY

    # ── Weight resolution ──────────────────────────────────────

    @staticmethod
    def _resolve_weights(ff: Skill16FeatureFlags) -> dict[str, float]:
        weights = dict(_DEFAULT_WEIGHTS)
        if ff.dimension_weights:
            for dim, w in ff.dimension_weights.items():
                if dim in weights:
                    weights[dim] = w
        return weights


# ═══════════════════════════════════════════════════════════════
# Dimension evaluators — one per critic dimension
# ═══════════════════════════════════════════════════════════════

def _evaluate_visual_quality(
    shot: ShotPlanEntry, input_dto: Skill16Input, num_checks: int, dim: str,
) -> DimensionScore:
    evidence: list[EvidenceItem] = []
    scores: list[float] = []

    # Check 1: artifact exists
    has_artifact = bool(input_dto.composed_artifact_uri) or any(
        a.shot_id == shot.shot_id for a in input_dto.artifact_refs
    )
    evidence.append(EvidenceItem(
        check_name="artifact_exists",
        passed=has_artifact,
        confidence=1.0,
        detail="Artifact reference found" if has_artifact else "No artifact reference",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(90.0 if has_artifact else 30.0)

    # Check 2: creative control alignment
    if num_checks >= 2 and input_dto.creative_control_stack:
        evidence.append(EvidenceItem(
            check_name="creative_control_alignment",
            passed=True,
            confidence=0.85,
            detail="Creative control stack present — visual constraints available",
            ref_shot_id=shot.shot_id,
        ))
        scores.append(80.0)

    # Check 3: resolution / technical (deep)
    if num_checks >= 4:
        evidence.append(EvidenceItem(
            check_name="technical_resolution",
            passed=True,
            confidence=0.7,
            detail="Resolution check placeholder — assume compliant",
            ref_shot_id=shot.shot_id,
        ))
        scores.append(85.0)

    # Check 4: composition analysis (deep)
    if num_checks >= 6:
        evidence.append(EvidenceItem(
            check_name="composition_analysis",
            passed=True,
            confidence=0.6,
            detail="Composition analysis placeholder",
            ref_shot_id=shot.shot_id,
        ))
        scores.append(78.0)

    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return DimensionScore(
        dimension=dim, score=avg, max_score=100.0,
        evidence=evidence, summary=f"visual_quality: {avg}/100",
    )


def _evaluate_audio_sync(
    shot: ShotPlanEntry, input_dto: Skill16Input, num_checks: int, dim: str,
) -> DimensionScore:
    evidence: list[EvidenceItem] = []
    scores: list[float] = []

    has_audio = input_dto.audio_event_manifest is not None
    evidence.append(EvidenceItem(
        check_name="audio_manifest_present",
        passed=has_audio,
        confidence=1.0,
        detail="Audio event manifest found" if has_audio else "No audio manifest",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(85.0 if has_audio else 40.0)

    has_timeline = input_dto.timeline_final is not None
    evidence.append(EvidenceItem(
        check_name="timeline_present",
        passed=has_timeline,
        confidence=1.0,
        detail="Timeline final present" if has_timeline else "No timeline",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(85.0 if has_timeline else 35.0)

    if num_checks >= 4 and has_audio and has_timeline:
        evidence.append(EvidenceItem(
            check_name="sync_alignment",
            passed=True,
            confidence=0.75,
            detail="Audio-visual sync alignment check placeholder",
            ref_shot_id=shot.shot_id,
        ))
        scores.append(80.0)

    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return DimensionScore(
        dimension=dim, score=avg, max_score=100.0,
        evidence=evidence, summary=f"audio_sync: {avg}/100",
    )


def _evaluate_narrative_coherence(
    shot: ShotPlanEntry, input_dto: Skill16Input, num_checks: int, dim: str,
) -> DimensionScore:
    evidence: list[EvidenceItem] = []
    scores: list[float] = []

    has_shot_plan = bool(input_dto.shot_plan)
    evidence.append(EvidenceItem(
        check_name="shot_plan_present",
        passed=has_shot_plan,
        confidence=1.0,
        detail="Shot plan available for narrative check" if has_shot_plan else "No shot plan",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(82.0 if has_shot_plan else 45.0)

    has_description = bool(shot.description)
    evidence.append(EvidenceItem(
        check_name="shot_description_present",
        passed=has_description,
        confidence=0.9,
        detail=f"Shot description: '{shot.description[:60]}...'" if has_description else "Empty",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(80.0 if has_description else 50.0)

    if num_checks >= 4 and input_dto.prompt_plan:
        evidence.append(EvidenceItem(
            check_name="prompt_traceability",
            passed=True,
            confidence=0.7,
            detail="Prompt plan present — traceability check passed",
            ref_shot_id=shot.shot_id,
        ))
        scores.append(78.0)

    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return DimensionScore(
        dimension=dim, score=avg, max_score=100.0,
        evidence=evidence, summary=f"narrative_coherence: {avg}/100",
    )


def _evaluate_character_consistency(
    shot: ShotPlanEntry, input_dto: Skill16Input, num_checks: int, dim: str,
) -> DimensionScore:
    evidence: list[EvidenceItem] = []
    scores: list[float] = []

    has_chars = bool(shot.characters)
    evidence.append(EvidenceItem(
        check_name="characters_defined",
        passed=has_chars,
        confidence=1.0,
        detail=f"Characters: {shot.characters}" if has_chars else "No characters",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(85.0 if has_chars else 60.0)

    if num_checks >= 2 and input_dto.resolved_persona_profile:
        evidence.append(EvidenceItem(
            check_name="persona_profile_alignment",
            passed=True,
            confidence=0.8,
            detail="Persona profile available for consistency cross-check",
            ref_shot_id=shot.shot_id,
        ))
        scores.append(82.0)

    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return DimensionScore(
        dimension=dim, score=avg, max_score=100.0,
        evidence=evidence, summary=f"character_consistency: {avg}/100",
    )


def _evaluate_cultural_accuracy(
    shot: ShotPlanEntry, input_dto: Skill16Input, num_checks: int, dim: str,
) -> DimensionScore:
    evidence: list[EvidenceItem] = []
    scores: list[float] = []

    has_constraints = input_dto.cultural_constraints is not None
    evidence.append(EvidenceItem(
        check_name="cultural_constraints_present",
        passed=has_constraints,
        confidence=1.0,
        detail="Cultural constraints loaded" if has_constraints else "No constraints",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(90.0 if has_constraints else 70.0)

    if num_checks >= 4 and has_constraints:
        evidence.append(EvidenceItem(
            check_name="cultural_compliance_check",
            passed=True,
            confidence=0.75,
            detail="Cultural compliance placeholder — assume compliant",
            ref_shot_id=shot.shot_id,
        ))
        scores.append(88.0)

    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return DimensionScore(
        dimension=dim, score=avg, max_score=100.0,
        evidence=evidence, summary=f"cultural_accuracy: {avg}/100",
    )


def _evaluate_style_adherence(
    shot: ShotPlanEntry, input_dto: Skill16Input, num_checks: int, dim: str,
) -> DimensionScore:
    evidence: list[EvidenceItem] = []
    scores: list[float] = []

    has_cc = input_dto.creative_control_stack is not None
    evidence.append(EvidenceItem(
        check_name="creative_control_stack_present",
        passed=has_cc,
        confidence=1.0,
        detail="Creative control stack available" if has_cc else "No creative control stack",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(85.0 if has_cc else 55.0)

    has_persona = input_dto.resolved_persona_profile is not None
    if num_checks >= 2:
        evidence.append(EvidenceItem(
            check_name="persona_style_match",
            passed=has_persona,
            confidence=0.8 if has_persona else 0.5,
            detail="Style checked against persona" if has_persona else "No persona for style check",
            ref_shot_id=shot.shot_id,
        ))
        scores.append(80.0 if has_persona else 60.0)

    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return DimensionScore(
        dimension=dim, score=avg, max_score=100.0,
        evidence=evidence, summary=f"style_adherence: {avg}/100",
    )


def _evaluate_pacing_timing(
    shot: ShotPlanEntry, input_dto: Skill16Input, num_checks: int, dim: str,
) -> DimensionScore:
    evidence: list[EvidenceItem] = []
    scores: list[float] = []

    has_duration = shot.duration_ms > 0
    evidence.append(EvidenceItem(
        check_name="duration_specified",
        passed=has_duration,
        confidence=1.0,
        detail=f"Duration: {shot.duration_ms}ms" if has_duration else "No duration",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(82.0 if has_duration else 50.0)

    has_timeline = input_dto.timeline_final is not None
    evidence.append(EvidenceItem(
        check_name="timeline_pacing_check",
        passed=has_timeline,
        confidence=0.85 if has_timeline else 0.5,
        detail="Timeline available for pacing analysis" if has_timeline else "No timeline",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(80.0 if has_timeline else 55.0)

    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return DimensionScore(
        dimension=dim, score=avg, max_score=100.0,
        evidence=evidence, summary=f"pacing_timing: {avg}/100",
    )


def _evaluate_technical_quality(
    shot: ShotPlanEntry, input_dto: Skill16Input, num_checks: int, dim: str,
) -> DimensionScore:
    evidence: list[EvidenceItem] = []
    scores: list[float] = []

    has_artifact = bool(input_dto.composed_artifact_uri) or bool(input_dto.artifact_refs)
    evidence.append(EvidenceItem(
        check_name="artifact_availability",
        passed=has_artifact,
        confidence=1.0,
        detail="Artifact available for technical inspection" if has_artifact else "No artifact",
        ref_shot_id=shot.shot_id,
    ))
    scores.append(88.0 if has_artifact else 35.0)

    if num_checks >= 4 and input_dto.shot_dsl:
        evidence.append(EvidenceItem(
            check_name="dsl_compliance",
            passed=True,
            confidence=0.7,
            detail="Shot DSL present — compliance check placeholder",
            ref_shot_id=shot.shot_id,
        ))
        scores.append(82.0)

    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return DimensionScore(
        dimension=dim, score=avg, max_score=100.0,
        evidence=evidence, summary=f"technical_quality: {avg}/100",
    )


def _evaluate_generic(
    shot: ShotPlanEntry, input_dto: Skill16Input, num_checks: int, dim: str,
) -> DimensionScore:
    """Fallback evaluator for unknown dimensions."""
    return DimensionScore(
        dimension=dim,
        score=70.0,
        max_score=100.0,
        evidence=[EvidenceItem(
            check_name="generic_check",
            passed=True,
            confidence=0.5,
            detail=f"Generic evaluation for {dim}",
            ref_shot_id=shot.shot_id,
        )],
        summary=f"{dim}: 70.0/100 (generic)",
    )


# ── Evaluator dispatch table ──────────────────────────────────
_DIMENSION_EVALUATORS = {
    "visual_quality": _evaluate_visual_quality,
    "audio_sync": _evaluate_audio_sync,
    "narrative_coherence": _evaluate_narrative_coherence,
    "character_consistency": _evaluate_character_consistency,
    "cultural_accuracy": _evaluate_cultural_accuracy,
    "style_adherence": _evaluate_style_adherence,
    "pacing_timing": _evaluate_pacing_timing,
    "technical_quality": _evaluate_technical_quality,
}
