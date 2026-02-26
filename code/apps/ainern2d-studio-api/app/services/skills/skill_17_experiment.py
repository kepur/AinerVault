"""SKILL 17: ExperimentService — 业务逻辑实现。
参考规格: SKILL_17_EXPERIMENT_AB_TEST_ORCHESTRATOR.md
状态: SERVICE_READY

State machine:
  INIT → DESIGNING → GENERATING_VARIANTS → ALLOCATING → EXECUTING
       → COLLECTING_METRICS → ANALYZING → RECOMMENDING
       → READY | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

import hashlib
import math
import uuid

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_17 import (
    CRITIC_DIMENSIONS,
    BenchmarkCase,
    DimensionRanking,
    DimensionScore,
    EvaluationCriteria,
    ExperimentHistoryEntry,
    FeatureFlags,
    PromotionRecommendation,
    RollbackPlan,
    Skill17Input,
    Skill17Output,
    StatisticalResult,
    TrafficAllocation,
    VariantConfig,
    VariantMetrics,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from ainern2d_shared.utils.time import utcnow

# ── Constants ──────────────────────────────────────────────────────────────────
_MAX_VARIANTS = 10
_EARLY_STOP_MIN_SAMPLES = 5


def _history(stage: str, action: str, detail: str = "") -> ExperimentHistoryEntry:
    """Create a timestamped audit-trail entry."""
    return ExperimentHistoryEntry(
        timestamp=utcnow().isoformat(),
        stage=stage,
        action=action,
        detail=detail,
    )


def _deterministic_seed(variant_id: str, case_id: str, dim: str) -> int:
    """Repeatable hash seed for simulated scoring."""
    raw = f"{variant_id}:{case_id}:{dim}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16)


# ── Module-level math helpers ──────────────────────────────────────────────────

def _pooled_std(dim_scores: list[DimensionScore]) -> float:
    """Average std across dimensions as proxy for overall variability."""
    if not dim_scores:
        return 1.0
    return sum(ds.std for ds in dim_scores) / len(dim_scores)


def _normal_cdf(x: float) -> float:
    """Standard normal CDF (Abramowitz & Stegun via math.erf)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _z_for_confidence(confidence: float) -> float:
    """Return z-score for a given two-tailed confidence level."""
    lookup = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576, 0.999: 3.291}
    return lookup.get(confidence, 1.96)


def _identify_improvements(
    control_m: VariantMetrics | None,
    test_m: VariantMetrics,
) -> list[str]:
    """Find dimensions where test outperforms control by ≥ 0.5 points."""
    if not control_m:
        return []
    improvements: list[str] = []
    for td in test_m.dimension_scores:
        cd = next((d for d in control_m.dimension_scores if d.dimension == td.dimension), None)
        if cd and td.mean > cd.mean + 0.5:
            improvements.append(f"{td.dimension}: +{round(td.mean - cd.mean, 3)}")
    return improvements


# ── Service ────────────────────────────────────────────────────────────────────

class ExperimentService(BaseSkillService[Skill17Input, Skill17Output]):
    """SKILL 17 — Experiment & A/B Test Orchestrator.

    Implements the full experiment lifecycle:
      [AB1] Define experiment — lock versions, register variants
      [AB2] Execute variants  — benchmark × variant, collect critic scores
      [AB3] Aggregate metrics — quality / efficiency / stability
      [AB4] Rank & recommend  — statistical tests, promotion decisions

    State machine:
      INIT → DESIGNING → GENERATING_VARIANTS → ALLOCATING → EXECUTING
           → COLLECTING_METRICS → ANALYZING → RECOMMENDING
           → READY | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_17"
    skill_name = "ExperimentService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Public entry ───────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill17Input, ctx: SkillContext) -> Skill17Output:
        history: list[ExperimentHistoryEntry] = []
        warnings: list[str] = []

        ff = input_dto.feature_flags or FeatureFlags()
        criteria = input_dto.evaluation_criteria or EvaluationCriteria()
        allocation = input_dto.traffic_allocation or TrafficAllocation()
        sample_size = max(input_dto.sample_size, ff.min_sample_size)

        experiment_id = f"EXP_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
        history.append(_history("INIT", "experiment_created", f"id={experiment_id}"))

        # ── Validate ─────────────────────────────────────────────────────────
        self._record_state(ctx, "INIT", "DESIGNING")
        issues = self._validate_input(input_dto, ff)
        if issues:
            self._record_state(ctx, "DESIGNING", "FAILED")
            history.append(_history("DESIGNING", "validation_failed", "; ".join(issues)))
            raise ValueError(f"EXP-VALIDATION-001: {'; '.join(issues)}")
        history.append(_history("DESIGNING", "validation_passed"))

        # ── [AB1] Design experiment — lock versions ──────────────────────────
        control = input_dto.control_variant
        assert control is not None  # guaranteed by validation
        test_variants = list(input_dto.test_variants)
        history.append(_history(
            "DESIGNING", "versions_locked",
            f"control={control.variant_id} tests={[v.variant_id for v in test_variants]}",
        ))

        # ── Generate variant configs ─────────────────────────────────────────
        self._record_state(ctx, "DESIGNING", "GENERATING_VARIANTS")
        all_variants = self._generate_variant_configs(control, test_variants)
        history.append(_history(
            "GENERATING_VARIANTS", "variants_generated", f"count={len(all_variants)}",
        ))

        # ── Allocate traffic ─────────────────────────────────────────────────
        self._record_state(ctx, "GENERATING_VARIANTS", "ALLOCATING")
        allocation = self._resolve_traffic_allocation(allocation, all_variants, ff)
        history.append(_history(
            "ALLOCATING", "traffic_allocated",
            f"strategy={allocation.strategy} weights={allocation.variant_weights}",
        ))

        # ── [AB2] Execute benchmark variants (simulated) ─────────────────────
        self._record_state(ctx, "ALLOCATING", "EXECUTING")
        benchmark_cases = input_dto.benchmark_cases
        if not benchmark_cases:
            benchmark_cases = [
                BenchmarkCase(case_id=f"auto_case_{i + 1}", scene_id=f"scene_{i + 1}")
                for i in range(sample_size)
            ]
            warnings.append("no benchmark_cases provided; auto-generated placeholders")
        history.append(_history(
            "EXECUTING", "execution_started",
            f"cases={len(benchmark_cases)} variants={len(all_variants)}",
        ))

        raw_scores = self._execute_variants(
            all_variants, benchmark_cases, criteria,
            input_dto.critic_reports, sample_size,
        )
        history.append(_history("EXECUTING", "execution_completed"))

        # ── [AB3] Collect & aggregate metrics ────────────────────────────────
        self._record_state(ctx, "EXECUTING", "COLLECTING_METRICS")
        variant_metrics = self._aggregate_metrics(
            all_variants, raw_scores, criteria,
            input_dto.user_ratings, input_dto.cost_data,
        )
        history.append(_history("COLLECTING_METRICS", "metrics_aggregated"))

        # ── Analyze — statistical tests + rankings ───────────────────────────
        self._record_state(ctx, "COLLECTING_METRICS", "ANALYZING")
        statistical_results = self._compute_statistics(
            control.variant_id, variant_metrics, criteria,
        )
        overall_ranking, dimension_rankings = self._rank_variants(variant_metrics, criteria)
        history.append(_history("ANALYZING", "analysis_completed", f"ranking={overall_ranking}"))

        # ── Early stop check ─────────────────────────────────────────────────
        early_stopped = False
        if ff.enable_early_stop and len(benchmark_cases) >= _EARLY_STOP_MIN_SAMPLES:
            for sr in statistical_results:
                if sr.is_significant and sr.p_value < (1.0 - ff.early_stop_confidence):
                    early_stopped = True
                    history.append(_history(
                        "ANALYZING", "early_stop_triggered",
                        f"variant={sr.test_variant_id} p={sr.p_value:.4f}",
                    ))
                    break

        # ── [AB4] Recommend ──────────────────────────────────────────────────
        self._record_state(ctx, "ANALYZING", "RECOMMENDING")
        recommendations = self._recommend(
            control.variant_id, all_variants, variant_metrics,
            statistical_results, criteria, ff,
        )
        history.append(_history("RECOMMENDING", "recommendations_generated"))

        # Determine winner
        winner_id = ""
        for rec in recommendations:
            if rec.decision == "promote_to_default":
                winner_id = rec.variant_id
                break
        if not winner_id and overall_ranking:
            winner_id = overall_ranking[0]

        # ── Final state ──────────────────────────────────────────────────────
        needs_review = any(r.decision == "needs_more_data" for r in recommendations)
        if needs_review:
            final_stage = "REVIEW_REQUIRED"
            status = "analyzing"
        else:
            final_stage = "READY"
            status = "concluded"

        self._record_state(ctx, "RECOMMENDING", final_stage)
        history.append(_history(
            final_stage, "experiment_concluded",
            f"winner={winner_id} status={status} early_stop={early_stopped}",
        ))

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"experiment={experiment_id} winner={winner_id} status={status}"
        )

        return Skill17Output(
            version="1.0",
            experiment_id=experiment_id,
            experiment_name=input_dto.experiment_name,
            status=status,
            stage=final_stage,
            variants=all_variants,
            variant_metrics=variant_metrics,
            overall_ranking=overall_ranking,
            dimension_rankings=dimension_rankings,
            statistical_results=statistical_results,
            recommendations=recommendations,
            winner_variant_id=winner_id,
            traffic_allocation=allocation,
            history=history,
            warnings=warnings,
            trace_id=ctx.trace_id,
            idempotency_key=ctx.idempotency_key,
        )

    # ── Validation ─────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_input(input_dto: Skill17Input, ff: FeatureFlags) -> list[str]:
        issues: list[str] = []
        if not input_dto.control_variant:
            issues.append("control_variant is required")
        if not input_dto.test_variants:
            issues.append("at least one test_variant is required")
        if len(input_dto.test_variants) > _MAX_VARIANTS:
            issues.append(f"too many test_variants (max {_MAX_VARIANTS})")
        if not ff.enable_multi_variant and len(input_dto.test_variants) > 1:
            issues.append("enable_multi_variant is disabled; only 1 test variant allowed")
        if input_dto.sample_size < 1:
            issues.append("sample_size must be >= 1")
        # Duplicate variant IDs
        ids: list[str] = []
        if input_dto.control_variant:
            ids.append(input_dto.control_variant.variant_id)
        ids.extend(v.variant_id for v in input_dto.test_variants)
        if len(ids) != len(set(ids)):
            issues.append("duplicate variant_id detected")
        return issues

    # ── [AB1] Generate variant configs ─────────────────────────────────────────

    @staticmethod
    def _generate_variant_configs(
        control: VariantConfig,
        test_variants: list[VariantConfig],
    ) -> list[VariantConfig]:
        """Ensure control flag is set and return unified variant list."""
        control_copy = control.model_copy(update={"is_control": True})
        tests = [v.model_copy(update={"is_control": False}) for v in test_variants]
        return [control_copy] + tests

    # ── Traffic allocation ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve_traffic_allocation(
        alloc: TrafficAllocation,
        variants: list[VariantConfig],
        ff: FeatureFlags,
    ) -> TrafficAllocation:
        if ff.enable_adaptive_allocation:
            alloc = alloc.model_copy(update={"strategy": "multi_arm_bandit"})
        if not alloc.variant_weights:
            n = len(variants)
            even = round(1.0 / n, 4)
            weights = {v.variant_id: even for v in variants}
            alloc = alloc.model_copy(update={"variant_weights": weights})
        return alloc

    # ── [AB2] Execute variants (simulated benchmark) ───────────────────────────

    @staticmethod
    def _execute_variants(
        variants: list[VariantConfig],
        benchmark_cases: list[BenchmarkCase],
        criteria: EvaluationCriteria,
        external_critic_reports: dict[str, list[dict]],
        sample_size: int,
    ) -> dict[str, list[dict[str, float]]]:
        """Run each variant × case and collect per-dimension scores.

        Uses externally supplied SKILL 16 critic reports when available,
        otherwise produces deterministic simulated scores.
        """
        dims = criteria.dimensions or CRITIC_DIMENSIONS
        results: dict[str, list[dict[str, float]]] = {}

        for variant in variants:
            vid = variant.variant_id
            case_scores: list[dict[str, float]] = []

            if vid in external_critic_reports:
                for report in external_critic_reports[vid][:sample_size]:
                    dim_map: dict[str, float] = {}
                    for ds in report.get("dimension_scores", []):
                        dim_map[ds.get("dimension", "")] = float(ds.get("score", 0.0))
                    for d in dims:
                        dim_map.setdefault(d, 0.0)
                    case_scores.append(dim_map)
            else:
                for case in benchmark_cases[:sample_size]:
                    scores: dict[str, float] = {}
                    for dim in dims:
                        seed = _deterministic_seed(vid, case.case_id, dim)
                        base = 4.0 + (seed % 5500) / 1000.0
                        override_boost = len(variant.param_overrides) * 0.05
                        scores[dim] = round(min(10.0, base + override_boost), 3)
                    case_scores.append(scores)

            results[vid] = case_scores

        return results

    # ── [AB3] Aggregate metrics ────────────────────────────────────────────────

    @staticmethod
    def _aggregate_metrics(
        variants: list[VariantConfig],
        raw_scores: dict[str, list[dict[str, float]]],
        criteria: EvaluationCriteria,
        user_ratings: dict[str, list[float]],
        cost_data: dict[str, dict],
    ) -> list[VariantMetrics]:
        metrics_list: list[VariantMetrics] = []
        dims = criteria.dimensions or CRITIC_DIMENSIONS
        weights = criteria.dimension_weights or {d: 1.0 for d in dims}

        for variant in variants:
            vid = variant.variant_id
            case_scores = raw_scores.get(vid, [])
            n = len(case_scores)
            if n == 0:
                metrics_list.append(VariantMetrics(variant_id=vid))
                continue

            # Per-dimension statistics
            dim_scores: list[DimensionScore] = []
            weighted_sum = 0.0
            total_weight = 0.0

            for dim in dims:
                vals = [cs.get(dim, 0.0) for cs in case_scores]
                mean = sum(vals) / len(vals)
                variance = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
                std = math.sqrt(variance)
                dim_scores.append(DimensionScore(
                    dimension=dim,
                    mean=round(mean, 4),
                    std=round(std, 4),
                    min_val=round(min(vals), 4),
                    max_val=round(max(vals), 4),
                    sample_count=len(vals),
                ))
                w = weights.get(dim, 1.0)
                weighted_sum += mean * w
                total_weight += w

            quality_score = round(weighted_sum / max(total_weight, 1e-9), 4)

            # Cost & efficiency
            cd = cost_data.get(vid, {})
            avg_latency = float(cd.get("avg_latency_ms", 0.0))
            total_cost = float(cd.get("total_cost_units", 0.0))
            failure_rate = float(cd.get("failure_rate", 0.0))
            retry_rate = float(cd.get("retry_rate", 0.0))
            partial_rate = float(cd.get("partial_success_rate", 0.0))
            cost_score = round(max(0.0, 1.0 - total_cost / max(total_cost + 1.0, 1.0)), 4)

            # User ratings
            ratings = user_ratings.get(vid, [])
            user_mean = round(sum(ratings) / len(ratings), 4) if ratings else 0.0

            metrics_list.append(VariantMetrics(
                variant_id=vid,
                sample_count=n,
                dimension_scores=dim_scores,
                quality_score=quality_score,
                avg_latency_ms=avg_latency,
                total_cost_units=total_cost,
                cost_score=cost_score,
                failure_rate=failure_rate,
                retry_rate=retry_rate,
                partial_success_rate=partial_rate,
                user_rating_mean=user_mean,
                user_rating_count=len(ratings),
            ))

        return metrics_list

    # ── Statistical significance (Welch t-test) ───────────────────────────────

    @staticmethod
    def _compute_statistics(
        control_id: str,
        metrics: list[VariantMetrics],
        criteria: EvaluationCriteria,
    ) -> list[StatisticalResult]:
        """Simplified Welch's two-sample t-test between control and each test."""
        control_m = next((m for m in metrics if m.variant_id == control_id), None)
        if not control_m or control_m.sample_count < 2:
            return []

        alpha = 1.0 - criteria.confidence_level
        results: list[StatisticalResult] = []

        for m in metrics:
            if m.variant_id == control_id or m.sample_count < 2:
                continue

            ctrl_mean = control_m.quality_score
            test_mean = m.quality_score
            ctrl_std = _pooled_std(control_m.dimension_scores)
            test_std = _pooled_std(m.dimension_scores)
            n1, n2 = control_m.sample_count, m.sample_count

            se = math.sqrt(ctrl_std ** 2 / n1 + test_std ** 2 / n2) if (n1 > 0 and n2 > 0) else 1e-9
            diff = test_mean - ctrl_mean

            if se > 0:
                t_stat = diff / se
                p_value = 2.0 * (1.0 - _normal_cdf(abs(t_stat)))
            else:
                t_stat = 0.0
                p_value = 1.0

            z = _z_for_confidence(criteria.confidence_level)
            ci_low = round(diff - z * se, 4)
            ci_high = round(diff + z * se, 4)

            is_sig = p_value < alpha
            effect = round(diff / max(ctrl_std, 1e-9), 4)  # Cohen's d

            results.append(StatisticalResult(
                test_variant_id=m.variant_id,
                control_variant_id=control_id,
                metric=criteria.primary_metric,
                control_mean=round(ctrl_mean, 4),
                test_mean=round(test_mean, 4),
                difference=round(diff, 4),
                confidence_interval_low=ci_low,
                confidence_interval_high=ci_high,
                p_value=round(max(p_value, 1e-10), 6),
                is_significant=is_sig,
                confidence_level=criteria.confidence_level,
                effect_size=effect,
            ))

        return results

    # ── Multi-dimensional ranking ──────────────────────────────────────────────

    @staticmethod
    def _rank_variants(
        metrics: list[VariantMetrics],
        criteria: EvaluationCriteria,
    ) -> tuple[list[str], list[DimensionRanking]]:
        """Rank variants overall and per each of the 8 critic dimensions."""
        dims = criteria.dimensions or CRITIC_DIMENSIONS

        def _sort_key(m: VariantMetrics) -> float:
            score = m.quality_score
            if criteria.enable_cost_weighted_ranking:
                score = score * (1.0 - criteria.cost_weight) + m.cost_score * criteria.cost_weight
            return score

        sorted_metrics = sorted(metrics, key=_sort_key, reverse=True)
        overall = [m.variant_id for m in sorted_metrics]

        dim_rankings: list[DimensionRanking] = []
        for dim in dims:
            dim_vals: dict[str, float] = {}
            for m in metrics:
                ds = next((d for d in m.dimension_scores if d.dimension == dim), None)
                dim_vals[m.variant_id] = ds.mean if ds else 0.0
            ranked = sorted(dim_vals, key=lambda vid: dim_vals[vid], reverse=True)
            dim_rankings.append(DimensionRanking(
                dimension=dim,
                ranked_variant_ids=ranked,
                scores={vid: round(dim_vals[vid], 4) for vid in ranked},
            ))

        return overall, dim_rankings

    # ── [AB4] Promotion recommendations ────────────────────────────────────────

    @staticmethod
    def _recommend(
        control_id: str,
        variants: list[VariantConfig],
        metrics: list[VariantMetrics],
        stats: list[StatisticalResult],
        criteria: EvaluationCriteria,
        ff: FeatureFlags,
    ) -> list[PromotionRecommendation]:
        recommendations: list[PromotionRecommendation] = []
        control_m = next((m for m in metrics if m.variant_id == control_id), None)

        for variant in variants:
            vid = variant.variant_id
            if vid == control_id:
                continue

            vm = next((m for m in metrics if m.variant_id == vid), None)
            sr = next((s for s in stats if s.test_variant_id == vid), None)

            if not vm or not sr:
                recommendations.append(PromotionRecommendation(
                    variant_id=vid,
                    decision="needs_more_data",
                    reasoning="insufficient data for comparison",
                ))
                continue

            if vm.sample_count < ff.min_sample_size:
                recommendations.append(PromotionRecommendation(
                    variant_id=vid,
                    decision="needs_more_data",
                    confidence=0.0,
                    reasoning=f"sample_count {vm.sample_count} < min {ff.min_sample_size}",
                ))
                continue

            diff = sr.difference
            significant = sr.is_significant

            if significant and diff > 0 and vm.quality_score >= ff.auto_promote_threshold:
                # Clear winner — promote_to_default
                rollback = RollbackPlan(
                    variant_id=vid,
                    rollback_to_variant_id=control_id,
                    rollback_trigger=(
                        f"quality_score < {criteria.pass_threshold} for 5 consecutive runs"
                    ),
                    rollback_steps=[
                        f"revert default config to {control_id}",
                        "notify stakeholders",
                        "log rollback event",
                    ],
                )
                recommendations.append(PromotionRecommendation(
                    variant_id=vid,
                    decision="promote_to_default",
                    confidence=round(1.0 - sr.p_value, 4),
                    reasoning=(
                        f"test outperforms control by {diff:+.4f} "
                        f"(p={sr.p_value:.6f}, effect_size={sr.effect_size:.4f})"
                    ),
                    rollback_plan=rollback,
                ))

            elif significant and diff > 0:
                # Significant improvement but below auto-promote threshold
                improvements = _identify_improvements(control_m, vm)
                if improvements:
                    recommendations.append(PromotionRecommendation(
                        variant_id=vid,
                        decision="merge_partial",
                        confidence=round(1.0 - sr.p_value, 4),
                        reasoning=(
                            f"significant improvement ({diff:+.4f}) but "
                            f"quality {vm.quality_score:.4f} < threshold {ff.auto_promote_threshold}"
                        ),
                        improvements_to_adopt=improvements,
                        rollback_plan=RollbackPlan(
                            variant_id=vid,
                            rollback_to_variant_id=control_id,
                            rollback_trigger="merged dimensions degrade below control baseline",
                            rollback_steps=[
                                f"revert merged params from {vid}",
                                "restore control defaults",
                            ],
                        ),
                    ))
                else:
                    recommendations.append(PromotionRecommendation(
                        variant_id=vid,
                        decision="needs_more_data",
                        confidence=round(1.0 - sr.p_value, 4),
                        reasoning=f"marginal improvement {diff:+.4f}; no clear dimension wins",
                    ))

            elif significant and diff <= 0:
                # Test is worse — reject
                recommendations.append(PromotionRecommendation(
                    variant_id=vid,
                    decision="reject",
                    confidence=round(1.0 - sr.p_value, 4),
                    reasoning=f"test underperforms control by {diff:+.4f} (significant)",
                ))

            else:
                # Not significant — need more data
                recommendations.append(PromotionRecommendation(
                    variant_id=vid,
                    decision="needs_more_data",
                    confidence=round(1.0 - sr.p_value, 4),
                    reasoning=f"no significant difference (p={sr.p_value:.6f})",
                ))

        return recommendations
