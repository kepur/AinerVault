"""SKILL 15: CreativeControlService — 业务逻辑实现。

参考规格: SKILL_15_CREATIVE_CONTROL_POLICY.md

状态机:
  INIT → LOADING_CONSTRAINTS → DETECTING_CONFLICTS → RESOLVING_CONFLICTS
  → CALCULATING_BANDS → EXPORTING → EVALUATING → READY | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun, WorkflowEvent
from ainern2d_shared.schemas.skills.skill_15 import (
    AuditEntry,
    Constraint,
    ConflictRecord,
    DownstreamExport,
    EvaluationResult,
    ExplorationBand,
    FeatureFlags,
    Skill15Input,
    Skill15Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from ainern2d_shared.utils.time import utcnow

# ── Source priority (higher wins; regulatory always wins) ─────────
_SOURCE_PRIORITY: dict[str, int] = {
    "regulatory": 100,
    "user_explicit": 90,
    "project_policy": 80,
    "culture_pack": 70,
    "style_pack": 60,
    "system_default": 50,
}

# ── Default system constraints ────────────────────────────────────
_SYSTEM_HARD_DEFAULTS: list[dict[str, Any]] = [
    {"category": "visual", "dimension": "style", "parameter": "explicit_violence",
     "rule": "no_explicit_violence", "priority": 100},
    {"category": "visual", "dimension": "style", "parameter": "nsfw_content",
     "rule": "no_nsfw_content", "priority": 100},
    {"category": "audio", "dimension": "volume", "parameter": "abrupt_silence",
     "rule": "no_abrupt_silence_mid_scene", "priority": 80},
]
_SYSTEM_SOFT_DEFAULTS: list[dict[str, Any]] = [
    {"category": "visual", "dimension": "style", "parameter": "culture_consistency",
     "rule": "prefer_culture_consistent_visuals", "priority": 60},
    {"category": "narrative", "dimension": "pacing", "parameter": "story_coherence",
     "rule": "maintain_story_coherence", "priority": 70},
    {"category": "visual", "dimension": "style", "parameter": "art_style",
     "rule": "consistent_art_style_across_shots", "priority": 65},
]
_SYSTEM_GUIDELINE_DEFAULTS: list[dict[str, Any]] = [
    {"category": "visual", "dimension": "composition", "parameter": "shot_variety",
     "rule": "vary_shot_composition", "priority": 30},
    {"category": "narrative", "dimension": "tone", "parameter": "tone_transitions",
     "rule": "smooth_tone_transitions", "priority": 25},
]

# Persona style DNA → constraint mapping
_STYLE_DNA_MAP: dict[str, tuple[str, str, str]] = {
    "cut_density": ("visual", "composition", "cut_density"),
    "impact_alignment_priority": ("visual", "composition", "impact_alignment"),
    "color_temperature": ("visual", "color", "color_temperature"),
    "lighting_intensity": ("visual", "style", "lighting_intensity"),
    "camera_movement_range": ("visual", "composition", "camera_movement"),
    "pacing_preference": ("narrative", "pacing", "pacing_preference"),
    "tone_preference": ("narrative", "tone", "tone_preference"),
    "volume_baseline": ("audio", "volume", "volume_baseline"),
    "tempo_preference": ("audio", "tempo", "tempo_preference"),
}


def _uid() -> str:
    return str(uuid.uuid4())[:8]


class CreativeControlService(BaseSkillService[Skill15Input, Skill15Output]):
    """SKILL 15 — Creative Control Policy.

    Collects constraints from SKILL 06/07/14/19, project settings, user
    overrides, and regulatory rules.  Detects conflicts, resolves them by
    source priority, calculates exploration bands, and exports resolved
    policy for downstream skills (08/09/10).

    State machine:
      INIT → LOADING_CONSTRAINTS → DETECTING_CONFLICTS → RESOLVING_CONFLICTS
      → CALCULATING_BANDS → EXPORTING → EVALUATING → READY | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_15"
    skill_name = "CreativeControlService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Main execute ─────────────────────────────────────────────

    def execute(self, input_dto: Skill15Input, ctx: SkillContext) -> Skill15Output:
        audit: list[AuditEntry] = []
        flags = self._parse_flags(input_dto.feature_flags)
        effective_input, runtime_review_items = self._inject_persona_runtime_profile(
            input_dto, audit,
        )

        # ── INIT → LOADING_CONSTRAINTS ───────────────────────────
        self._record_state(ctx, "INIT", "LOADING_CONSTRAINTS")
        all_constraints = self._load_all_constraints(effective_input, flags, audit)
        self._audit(
            audit, "LOADING_CONSTRAINTS", "loaded_constraints",
            decision=f"total={len(all_constraints)}",
            rationale="Collected from all sources",
        )

        hard = [c for c in all_constraints if c.constraint_type == "hard_constraint"]
        soft = [c for c in all_constraints if c.constraint_type == "soft_constraint"]
        guidelines = [c for c in all_constraints if c.constraint_type == "guideline"]

        if flags.strict_mode:
            soft, guidelines = [], []
            self._audit(
                audit, "LOADING_CONSTRAINTS", "strict_mode_filter",
                decision="soft_and_guidelines_removed",
                rationale="strict_mode=True, only hard constraints retained",
            )

        # ── LOADING_CONSTRAINTS → DETECTING_CONFLICTS ────────────
        self._record_state(ctx, "LOADING_CONSTRAINTS", "DETECTING_CONFLICTS")
        conflicts: list[ConflictRecord] = []
        if flags.enable_policy_conflict_scan:
            conflicts = self._detect_conflicts(all_constraints, audit)
        self._audit(
            audit, "DETECTING_CONFLICTS", "scan_complete",
            decision=f"conflicts={len(conflicts)}",
            rationale="Scanned all constraint pairs for same-parameter conflicts",
        )

        # ── DETECTING_CONFLICTS → RESOLVING_CONFLICTS ────────────
        self._record_state(ctx, "DETECTING_CONFLICTS", "RESOLVING_CONFLICTS")
        suppressed_ids: set[str] = set()
        if conflicts:
            suppressed_ids = self._resolve_conflicts(
                conflicts, all_constraints, flags, audit,
            )

        # Remove suppressed (losing) constraints from active sets
        if suppressed_ids:
            hard = [c for c in hard if c.constraint_id not in suppressed_ids]
            soft = [c for c in soft if c.constraint_id not in suppressed_ids]
            guidelines = [c for c in guidelines if c.constraint_id not in suppressed_ids]

        # ── RESOLVING_CONFLICTS → CALCULATING_BANDS ──────────────
        self._record_state(ctx, "RESOLVING_CONFLICTS", "CALCULATING_BANDS")
        bands: list[ExplorationBand] = []
        if flags.enable_exploration_band:
            bands = self._calculate_exploration_bands(hard, soft, audit)
        exploration_policy = self._build_exploration_policy(effective_input, bands, flags)

        # ── CALCULATING_BANDS → EXPORTING ────────────────────────
        self._record_state(ctx, "CALCULATING_BANDS", "EXPORTING")
        downstream = self._build_downstream_export(hard, soft, guidelines, bands)
        conflict_resolution_policy = {
            "hard_over_soft": True,
            "soft_tie_breaker": "source_priority",
            "strategy": flags.conflict_resolution_strategy,
        }

        # ── EXPORTING → EVALUATING ───────────────────────────────
        self._record_state(ctx, "EXPORTING", "EVALUATING")
        eval_results: list[EvaluationResult] = []
        if effective_input.proposed_output:
            eval_results = self._evaluate_policy(
                effective_input.proposed_output, hard + soft + guidelines, audit,
            )

        # ── Determine final state ────────────────────────────────
        review_items: list[str] = list(runtime_review_items)
        unresolved_hard = [
            c for c in conflicts if not c.resolution and c.severity == "error"
        ]
        for c in unresolved_hard:
            review_items.append(f"Unresolved hard conflict: {c.description}")

        failed_evals = [e for e in eval_results if e.result == "fail"]
        for e in failed_evals:
            review_items.append(f"Policy violation: {e.message}")

        if unresolved_hard and flags.conflict_resolution_strategy == "reject":
            status = "failed"
            final_state = "FAILED"
        elif review_items:
            status = "review_required"
            final_state = "REVIEW_REQUIRED"
        else:
            status = "policy_ready"
            final_state = "READY"

        self._record_state(ctx, "EVALUATING", final_state)

        output = Skill15Output(
            version="1.0",
            status=status,
            hard_constraints=hard,
            soft_constraints=soft,
            guidelines=guidelines,
            exploration_policy=exploration_policy,
            exploration_bands=bands,
            conflict_report=conflicts,
            conflict_resolution_policy=conflict_resolution_policy,
            downstream_export=downstream,
            evaluation_results=eval_results,
            audit_trail=audit,
            review_items=review_items,
        )
        policy_stack_id, policy_stack_name, policy_event_id = self._persist_policy_snapshot(
            ctx=ctx,
            input_dto=effective_input,
            output=output,
        )
        output.policy_stack_id = policy_stack_id
        output.policy_stack_name = policy_stack_name
        output.policy_event_id = policy_event_id

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"status={status} hard={len(hard)} soft={len(soft)} "
            f"guidelines={len(guidelines)} conflicts={len(conflicts)} "
            f"bands={len(bands)} policy_stack_id={policy_stack_id or 'n/a'}"
        )
        return output

    # ── Feature flags parsing ────────────────────────────────────

    @staticmethod
    def _parse_flags(raw: dict) -> FeatureFlags:
        return FeatureFlags(
            strict_mode=raw.get("strict_mode", False),
            allow_exploration_override=raw.get("allow_exploration_override", False),
            conflict_resolution_strategy=raw.get(
                "conflict_resolution_strategy", "priority",
            ),
            enable_policy_conflict_scan=raw.get("enable_policy_conflict_scan", True),
            enable_exploration_band=raw.get("enable_exploration_band", True),
            enable_persona_soft_constraints=raw.get(
                "enable_persona_soft_constraints", True,
            ),
        )

    def _inject_persona_runtime_profile(
        self,
        inp: Skill15Input,
        audit: list[AuditEntry],
    ) -> tuple[Skill15Input, list[str]]:
        """If SKILL 14 persona_profile is absent, derive it from SKILL 22 runtime manifests."""
        if inp.persona_profile:
            return inp, []

        runtime_result = inp.persona_dataset_index_result or {}
        manifests = runtime_result.get("runtime_manifests", [])
        if not isinstance(manifests, list) or not manifests:
            return inp, []

        review_items: list[str] = []
        selected_manifest: dict[str, Any] | None = None
        if inp.active_persona_ref:
            selected_manifest = next(
                (
                    item for item in manifests
                    if isinstance(item, dict)
                    and str(item.get("persona_ref") or "") == inp.active_persona_ref
                ),
                None,
            )
            if selected_manifest is None:
                review_items.append(
                    f"persona_runtime_not_found:{inp.active_persona_ref}"
                )

        if selected_manifest is None:
            selected_manifest = next(
                (item for item in manifests if isinstance(item, dict)),
                None,
            )
        if not selected_manifest:
            return inp, review_items

        runtime_manifest = dict(selected_manifest.get("runtime_manifest") or {})
        persona_ref = str(
            selected_manifest.get("persona_ref")
            or runtime_manifest.get("persona_ref")
            or ""
        )
        style_pack_ref = str(
            selected_manifest.get("style_pack_ref")
            or runtime_manifest.get("style_pack_ref")
            or ""
        )
        policy_override_ref = str(
            selected_manifest.get("policy_override_ref")
            or runtime_manifest.get("policy_override_ref")
            or ""
        )
        critic_profile_ref = str(
            selected_manifest.get("critic_profile_ref")
            or runtime_manifest.get("critic_profile_ref")
            or ""
        )
        dataset_ids = list(
            selected_manifest.get("resolved_dataset_ids")
            or runtime_manifest.get("dataset_ids")
            or []
        )
        index_ids = list(
            selected_manifest.get("resolved_index_ids")
            or runtime_manifest.get("index_ids")
            or []
        )

        derived_constraints: list[dict[str, Any]] = []
        if style_pack_ref:
            derived_constraints.append(
                {
                    "type": "soft_constraint",
                    "category": "visual",
                    "dimension": "style",
                    "parameter": "persona_style_pack_ref",
                    "rule": "use_persona_style_pack",
                    "value": style_pack_ref,
                    "priority": 65,
                }
            )
        if policy_override_ref:
            derived_constraints.append(
                {
                    "type": "soft_constraint",
                    "category": "narrative",
                    "dimension": "tone",
                    "parameter": "persona_policy_override_ref",
                    "rule": "apply_persona_policy_override",
                    "value": policy_override_ref,
                    "priority": 68,
                }
            )
        if critic_profile_ref:
            derived_constraints.append(
                {
                    "type": "guideline",
                    "category": "visual",
                    "dimension": "style",
                    "parameter": "persona_critic_profile_ref",
                    "rule": "critic_profile_alignment",
                    "value": critic_profile_ref,
                    "priority": 55,
                }
            )
        if dataset_ids:
            derived_constraints.append(
                {
                    "type": "guideline",
                    "category": "technical",
                    "dimension": "duration",
                    "parameter": "persona_dataset_count",
                    "rule": "persona_dataset_context",
                    "value": len(dataset_ids),
                    "priority": 45,
                }
            )

        derived_profile = {
            "persona_id": persona_ref or "runtime_persona",
            "style_dna": {},
            "constraints": derived_constraints,
            "runtime_manifest_refs": {
                "persona_ref": persona_ref,
                "dataset_ids": dataset_ids,
                "index_ids": index_ids,
            },
        }
        self._audit(
            audit,
            "LOADING_CONSTRAINTS",
            "injected_persona_profile_from_skill22",
            decision=persona_ref or "runtime_persona",
            rationale=f"dataset_ids={len(dataset_ids)} index_ids={len(index_ids)}",
        )
        return inp.model_copy(update={"persona_profile": derived_profile}), review_items

    # ── Constraint Loading ───────────────────────────────────────

    def _load_all_constraints(
        self,
        inp: Skill15Input,
        flags: FeatureFlags,
        audit: list[AuditEntry],
    ) -> list[Constraint]:
        result: list[Constraint] = []

        # 1) System defaults
        for d in _SYSTEM_HARD_DEFAULTS:
            result.append(Constraint(
                constraint_id=_uid(), constraint_type="hard_constraint",
                source="system_default", **d,
            ))
        for d in _SYSTEM_SOFT_DEFAULTS:
            result.append(Constraint(
                constraint_id=_uid(), constraint_type="soft_constraint",
                source="system_default", **d,
            ))
        for d in _SYSTEM_GUIDELINE_DEFAULTS:
            result.append(Constraint(
                constraint_id=_uid(), constraint_type="guideline",
                source="system_default", **d,
            ))
        self._audit(
            audit, "LOADING_CONSTRAINTS", "loaded_system_defaults",
            decision=f"count={len(result)}", rationale="system_default source",
        )

        # 2) Culture pack constraints (from SKILL 07)
        culture_count = 0
        for cc in inp.culture_constraints:
            ctype = cc.get("type", "hard_constraint")
            if ctype not in ("hard_constraint", "soft_constraint", "guideline"):
                ctype = "hard_constraint"
            result.append(Constraint(
                constraint_id=_uid(),
                constraint_type=ctype,
                source="culture_pack",
                category=cc.get("category", "visual"),
                dimension=cc.get("dimension", "style"),
                parameter=cc.get("parameter", ""),
                rule=cc.get("rule", ""),
                value=cc.get("value"),
                min_value=cc.get("min_value"),
                max_value=cc.get("max_value"),
                priority=cc.get("priority", 70),
                description=cc.get("description", ""),
                enforceable=cc.get("enforceable", True),
            ))
            culture_count += 1
        if culture_count:
            self._audit(
                audit, "LOADING_CONSTRAINTS", "loaded_culture_pack",
                decision=f"count={culture_count}", rationale="from SKILL 07",
            )

        # 3) Persona / style pack (from SKILL 14)
        if flags.enable_persona_soft_constraints and inp.persona_profile:
            self._load_persona_constraints(inp.persona_profile, result, audit)

        # 4) Project policy constraints
        if inp.project_constraints:
            self._load_project_constraints(inp.project_constraints, result, audit)

        # 5) Timeline / audio constraints (from SKILL 06)
        if inp.timeline_final:
            self._load_timeline_constraints(inp.timeline_final, result, audit)
        if inp.audio_event_manifest:
            self._load_audio_constraints(inp.audio_event_manifest, result, audit)

        # 6) Compute budget (from SKILL 19)
        if inp.compute_budget:
            self._load_compute_constraints(inp.compute_budget, result, audit)

        # 7) Regulatory constraints (always hard, always max priority)
        reg_count = 0
        for rc in inp.regulatory_constraints:
            result.append(Constraint(
                constraint_id=_uid(),
                constraint_type="hard_constraint",
                source="regulatory",
                category=rc.get("category", "visual"),
                dimension=rc.get("dimension", ""),
                parameter=rc.get("parameter", ""),
                rule=rc.get("rule", ""),
                value=rc.get("value"),
                priority=100,
                description=rc.get("description", ""),
                enforceable=True,
            ))
            reg_count += 1
        if reg_count:
            self._audit(
                audit, "LOADING_CONSTRAINTS", "loaded_regulatory",
                decision=f"count={reg_count}", rationale="regulatory source",
            )

        # 8) User explicit overrides
        user_count = 0
        for uo in inp.user_overrides:
            ctype = uo.get("type", "soft_constraint")
            if ctype not in ("hard_constraint", "soft_constraint", "guideline"):
                ctype = "soft_constraint"
            result.append(Constraint(
                constraint_id=_uid(),
                constraint_type=ctype,
                source="user_explicit",
                category=uo.get("category", "visual"),
                dimension=uo.get("dimension", ""),
                parameter=uo.get("parameter", ""),
                rule=uo.get("rule", ""),
                value=uo.get("value"),
                min_value=uo.get("min_value"),
                max_value=uo.get("max_value"),
                priority=uo.get("priority", 90),
                description=uo.get("description", ""),
                enforceable=uo.get("enforceable", True),
            ))
            user_count += 1
        if user_count:
            self._audit(
                audit, "LOADING_CONSTRAINTS", "loaded_user_explicit",
                decision=f"count={user_count}", rationale="user_explicit source",
            )

        return result

    def _load_persona_constraints(
        self,
        profile: dict,
        result: list[Constraint],
        audit: list[AuditEntry],
    ) -> None:
        """Map persona style DNA fields to soft constraints."""
        count = 0
        style_dna = profile.get("style_dna", {})
        persona_id = profile.get("persona_id", "unknown")

        for key, (cat, dim, param) in _STYLE_DNA_MAP.items():
            if key in style_dna:
                val = style_dna[key]
                result.append(Constraint(
                    constraint_id=_uid(),
                    constraint_type="soft_constraint",
                    source="style_pack",
                    category=cat,
                    dimension=dim,
                    parameter=param,
                    rule=f"persona_{persona_id}_{key}",
                    value=val,
                    priority=60,
                    description=f"Persona {persona_id} style: {key}={val}",
                ))
                count += 1

        # Explicit constraints from persona profile
        for pc in profile.get("constraints", []):
            ctype = pc.get("type", "soft_constraint")
            if ctype not in ("hard_constraint", "soft_constraint", "guideline"):
                ctype = "soft_constraint"
            result.append(Constraint(
                constraint_id=_uid(),
                constraint_type=ctype,
                source="style_pack",
                category=pc.get("category", "visual"),
                dimension=pc.get("dimension", "style"),
                parameter=pc.get("parameter", ""),
                rule=pc.get("rule", ""),
                value=pc.get("value"),
                priority=pc.get("priority", 60),
                description=pc.get("description", f"Persona {persona_id} constraint"),
            ))
            count += 1

        if count:
            self._audit(
                audit, "LOADING_CONSTRAINTS", "loaded_persona_style",
                decision=f"count={count}", rationale=f"persona={persona_id}",
            )

    def _load_project_constraints(
        self,
        proj: dict,
        result: list[Constraint],
        audit: list[AuditEntry],
    ) -> None:
        count = 0
        _PROJ_HARD: list[tuple[str, str, str, str]] = [
            ("max_gpu_minutes", "technical", "duration", "gpu_budget_cap"),
            ("preview_deadline_sec", "technical", "duration", "preview_deadline"),
            ("max_duration_ms", "technical", "duration", "max_output_duration"),
        ]
        for field, cat, dim, rule in _PROJ_HARD:
            if field in proj:
                result.append(Constraint(
                    constraint_id=_uid(), constraint_type="hard_constraint",
                    source="project_policy", category=cat, dimension=dim,
                    parameter=field, rule=rule, value=proj[field],
                    max_value=float(proj[field]),
                    priority=85, description=f"Project {rule}",
                ))
                count += 1

        _PROJ_SOFT: list[tuple[str, str, str, str]] = [
            ("target_resolution", "technical", "resolution", "target_resolution"),
            ("target_fps", "technical", "fps", "target_fps"),
        ]
        for field, cat, dim, rule in _PROJ_SOFT:
            if field in proj:
                result.append(Constraint(
                    constraint_id=_uid(), constraint_type="soft_constraint",
                    source="project_policy", category=cat, dimension=dim,
                    parameter=field, rule=rule, value=proj[field],
                    priority=75, description=f"Project {rule}",
                ))
                count += 1

        if count:
            self._audit(
                audit, "LOADING_CONSTRAINTS", "loaded_project_policy",
                decision=f"count={count}", rationale="project constraints",
            )

    def _load_timeline_constraints(
        self,
        timeline: dict,
        result: list[Constraint],
        audit: list[AuditEntry],
    ) -> None:
        """Extract hard timing constraints from the finalized timeline."""
        total_ms = timeline.get("total_duration_ms")
        if total_ms is not None:
            result.append(Constraint(
                constraint_id=_uid(), constraint_type="hard_constraint",
                source="project_policy", category="technical",
                dimension="duration", parameter="final_duration_ms",
                rule="timeline_locked_duration", value=total_ms,
                min_value=float(total_ms), max_value=float(total_ms),
                priority=95,
                description="Locked timeline duration from SKILL 06",
            ))

        for anchor in timeline.get("anchors", []):
            result.append(Constraint(
                constraint_id=_uid(), constraint_type="hard_constraint",
                source="project_policy", category="technical",
                dimension="duration",
                parameter=f"anchor_{anchor.get('id', '')}",
                rule="time_anchor", value=anchor.get("timestamp_ms"),
                priority=95,
                description=f"Time anchor: {anchor.get('label', '')}",
            ))

        self._audit(
            audit, "LOADING_CONSTRAINTS", "loaded_timeline",
            decision="ok", rationale="from SKILL 06 timeline_final",
        )

    def _load_audio_constraints(
        self,
        manifest: dict,
        result: list[Constraint],
        audit: list[AuditEntry],
    ) -> None:
        """Extract audio constraints from SKILL 06 audio event manifest."""
        for ev in manifest.get("events", []):
            result.append(Constraint(
                constraint_id=_uid(), constraint_type="hard_constraint",
                source="project_policy", category="audio",
                dimension="volume",
                parameter=f"audio_event_{ev.get('id', '')}",
                rule="audio_event_sync", value=ev, priority=90,
                description=f"Audio sync point: {ev.get('type', '')}",
            ))
        self._audit(
            audit, "LOADING_CONSTRAINTS", "loaded_audio_manifest",
            decision="ok", rationale="from SKILL 06 audio_event_manifest",
        )

    def _load_compute_constraints(
        self,
        budget: dict,
        result: list[Constraint],
        audit: list[AuditEntry],
    ) -> None:
        if "max_gpu_minutes" in budget:
            result.append(Constraint(
                constraint_id=_uid(), constraint_type="hard_constraint",
                source="project_policy", category="technical",
                dimension="duration", parameter="compute_gpu_cap",
                rule="compute_budget_cap",
                value=budget["max_gpu_minutes"],
                max_value=float(budget["max_gpu_minutes"]),
                priority=88,
                description="Compute budget cap from SKILL 19",
            ))
        if "max_candidates_per_shot" in budget:
            result.append(Constraint(
                constraint_id=_uid(), constraint_type="soft_constraint",
                source="project_policy", category="technical",
                dimension="fps", parameter="max_candidates_per_shot",
                rule="candidate_budget",
                value=budget["max_candidates_per_shot"],
                max_value=float(budget["max_candidates_per_shot"]),
                priority=70,
                description="Max candidates per shot from compute budget",
            ))
        self._audit(
            audit, "LOADING_CONSTRAINTS", "loaded_compute_budget",
            decision="ok", rationale="from SKILL 19",
        )

    # ── Conflict Detection ───────────────────────────────────────

    def _detect_conflicts(
        self,
        constraints: list[Constraint],
        audit: list[AuditEntry],
    ) -> list[ConflictRecord]:
        """Detect conflicts between constraint pairs on the same parameter."""
        conflicts: list[ConflictRecord] = []
        n = len(constraints)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = constraints[i], constraints[j]
                if not (a.parameter and b.parameter and a.parameter == b.parameter):
                    continue
                conflict = self._check_pair(a, b)
                if conflict:
                    conflicts.append(conflict)
                    self._audit(
                        audit, "DETECTING_CONFLICTS", "conflict_detected",
                        constraint_id=f"{a.constraint_id}↔{b.constraint_id}",
                        decision=conflict.conflict_type,
                        rationale=conflict.description,
                    )
        return conflicts

    @staticmethod
    def _check_pair(a: Constraint, b: Constraint) -> ConflictRecord | None:
        """Check if two constraints on the same parameter conflict."""

        # Mutual exclusion (forbid vs require)
        if _mutually_exclusive(a, b):
            return ConflictRecord(
                conflict_id=_uid(),
                conflict_type="mutual_exclusion",
                constraint_a_id=a.constraint_id,
                constraint_b_id=b.constraint_id,
                severity="error",
                description=(
                    f"Mutually exclusive rules on '{a.parameter}': "
                    f"{a.rule} vs {b.rule}"
                ),
            )

        # Range overlap (non-overlapping ranges)
        if (a.min_value is not None and a.max_value is not None
                and b.min_value is not None and b.max_value is not None):
            if a.max_value < b.min_value or b.max_value < a.min_value:
                severity = (
                    "error" if a.constraint_type == "hard_constraint"
                    and b.constraint_type == "hard_constraint"
                    else "warning"
                )
                return ConflictRecord(
                    conflict_id=_uid(),
                    conflict_type="range_overlap",
                    constraint_a_id=a.constraint_id,
                    constraint_b_id=b.constraint_id,
                    severity=severity,
                    description=(
                        f"Non-overlapping ranges on '{a.parameter}': "
                        f"[{a.min_value},{a.max_value}] vs "
                        f"[{b.min_value},{b.max_value}]"
                    ),
                )

        # Source priority conflict (different sources, contradictory values)
        if a.source != b.source and _rules_contradict(a, b):
            severity = (
                "error" if a.constraint_type == "hard_constraint"
                and b.constraint_type == "hard_constraint"
                else "warning"
            )
            return ConflictRecord(
                conflict_id=_uid(),
                conflict_type="source_priority_conflict",
                constraint_a_id=a.constraint_id,
                constraint_b_id=b.constraint_id,
                severity=severity,
                description=(
                    f"Source conflict on '{a.parameter}': "
                    f"{a.source}({a.rule}) vs {b.source}({b.rule})"
                ),
            )

        # Semantic contradiction (same type, different explicit values)
        if (a.value is not None and b.value is not None
                and a.constraint_type == b.constraint_type):
            contradicts = False
            if isinstance(a.value, (int, float)) and isinstance(b.value, (int, float)):
                contradicts = a.value != b.value
            elif isinstance(a.value, str) and isinstance(b.value, str):
                contradicts = a.value != b.value
            if contradicts:
                return ConflictRecord(
                    conflict_id=_uid(),
                    conflict_type="semantic_contradiction",
                    constraint_a_id=a.constraint_id,
                    constraint_b_id=b.constraint_id,
                    severity="warning",
                    description=(
                        f"Different values on '{a.parameter}': "
                        f"{a.value} ({a.source}) vs {b.value} ({b.source})"
                    ),
                )

        return None

    # ── Conflict Resolution ──────────────────────────────────────

    def _resolve_conflicts(
        self,
        conflicts: list[ConflictRecord],
        all_constraints: list[Constraint],
        flags: FeatureFlags,
        audit: list[AuditEntry],
    ) -> set[str]:
        """Resolve conflicts and return IDs of suppressed (losing) constraints."""
        cmap = {c.constraint_id: c for c in all_constraints}
        suppressed: set[str] = set()

        for conflict in conflicts:
            a = cmap.get(conflict.constraint_a_id)
            b = cmap.get(conflict.constraint_b_id)
            if not a or not b:
                continue

            # "reject" strategy: leave hard-hard conflicts unresolved → FAILED
            if flags.conflict_resolution_strategy == "reject":
                if conflict.severity == "error":
                    continue  # unresolved → triggers review/fail

            # "merge" strategy: try range intersection first
            if flags.conflict_resolution_strategy == "merge":
                if _try_merge(a, b):
                    conflict.resolution = "merged"
                    conflict.resolution_path = (
                        f"Merged {a.source}+{b.source} on '{a.parameter}'"
                    )
                    self._audit(
                        audit, "RESOLVING_CONFLICTS", "merged",
                        constraint_id=conflict.conflict_id,
                        decision="merged",
                        rationale=conflict.resolution_path,
                    )
                    continue

            # Default: priority-based resolution
            winner, loser = _pick_winner(a, b)
            conflict.winning_constraint_id = winner.constraint_id
            conflict.resolution = "priority"
            conflict.resolution_path = (
                f"{winner.source}(pri={_SOURCE_PRIORITY.get(winner.source, 0)}) > "
                f"{loser.source}(pri={_SOURCE_PRIORITY.get(loser.source, 0)})"
            )
            suppressed.add(loser.constraint_id)
            self._audit(
                audit, "RESOLVING_CONFLICTS", "priority_resolved",
                constraint_id=conflict.conflict_id,
                decision=f"winner={winner.constraint_id}",
                rationale=conflict.resolution_path,
            )

        return suppressed

    # ── Exploration Band Calculation ─────────────────────────────

    def _calculate_exploration_bands(
        self,
        hard: list[Constraint],
        soft: list[Constraint],
        audit: list[AuditEntry],
    ) -> list[ExplorationBand]:
        """Calculate creative freedom bands for soft-constrained parameters."""
        param_hard: dict[str, list[Constraint]] = {}
        param_soft: dict[str, list[Constraint]] = {}

        for c in hard:
            if c.parameter:
                param_hard.setdefault(c.parameter, []).append(c)
        for c in soft:
            if c.parameter:
                param_soft.setdefault(c.parameter, []).append(c)

        bands: list[ExplorationBand] = []
        for param, soft_list in param_soft.items():
            hard_list = param_hard.get(param, [])

            # Determine hard boundaries
            hard_min = 0.0
            hard_max = 1.0
            for h in hard_list:
                if h.min_value is not None:
                    hard_min = max(hard_min, h.min_value)
                if h.max_value is not None:
                    hard_max = min(hard_max, h.max_value)

            # Determine soft boundaries and preferred value
            soft_min = hard_min
            soft_max = hard_max
            preferred = (hard_min + hard_max) / 2.0

            for s in soft_list:
                if s.value is not None and isinstance(s.value, (int, float)):
                    preferred = float(s.value)
                if s.min_value is not None:
                    soft_min = max(soft_min, s.min_value)
                if s.max_value is not None:
                    soft_max = min(soft_max, s.max_value)

            # Clamp to valid ranges
            soft_min = max(soft_min, hard_min)
            soft_max = min(soft_max, hard_max)
            preferred = max(soft_min, min(preferred, soft_max))

            cat = soft_list[0].category if soft_list else "visual"
            unit = soft_list[0].dimension if soft_list else ""

            band = ExplorationBand(
                parameter=param, category=cat,
                hard_min=hard_min, soft_min=soft_min,
                preferred=preferred,
                soft_max=soft_max, hard_max=hard_max,
                unit=unit,
            )
            bands.append(band)
            self._audit(
                audit, "CALCULATING_BANDS", "band_calculated",
                constraint_id=param,
                decision=(
                    f"[{hard_min},{soft_min},{preferred},{soft_max},{hard_max}]"
                ),
                rationale=f"hard={len(hard_list)} soft={len(soft_list)}",
            )

        return bands

    # ── Exploration Policy Builder ───────────────────────────────

    @staticmethod
    def _build_exploration_policy(
        inp: Skill15Input,
        bands: list[ExplorationBand],
        flags: FeatureFlags,
    ) -> dict:
        default_candidates = inp.project_constraints.get(
            "default_candidates_per_key_shot", 3,
        )
        stable_shots = inp.project_constraints.get("stable_shots", [])
        allowed_fields = [
            b.parameter for b in bands if b.soft_max - b.soft_min > 0.01
        ]

        return {
            "candidate_generation": {
                "enabled": not flags.strict_mode,
                "default_candidates_per_key_shot": default_candidates,
            },
            "allowed_variation_fields": allowed_fields,
            "stable_shots": stable_shots,
            "exploration_override_allowed": flags.allow_exploration_override,
        }

    # ── Downstream Export Builder ────────────────────────────────

    @staticmethod
    def _build_downstream_export(
        hard: list[Constraint],
        soft: list[Constraint],
        guidelines: list[Constraint],
        bands: list[ExplorationBand],
    ) -> DownstreamExport:
        all_active = hard + soft + guidelines

        def _filter(cats: set[str]) -> list[dict]:
            return [
                {
                    "constraint_id": c.constraint_id,
                    "type": c.constraint_type,
                    "parameter": c.parameter,
                    "rule": c.rule,
                    "value": c.value,
                    "min": c.min_value,
                    "max": c.max_value,
                }
                for c in all_active if c.category in cats
            ]

        band_map = {
            b.parameter: {
                "hard_min": b.hard_min, "soft_min": b.soft_min,
                "preferred": b.preferred,
                "soft_max": b.soft_max, "hard_max": b.hard_max,
            }
            for b in bands
        }

        prompt_cats = {"visual", "narrative"}
        render_cats = {"visual", "technical"}
        asset_cats = {"visual"}
        audio_cats = {"audio"}

        def _bands_for(cats: set[str]) -> dict:
            return {
                k: v for k, v in band_map.items()
                if any(
                    c.parameter == k and c.category in cats
                    for c in all_active
                )
            }

        return DownstreamExport(
            prompt_constraints={
                "constraints": _filter(prompt_cats),
                "bands": _bands_for(prompt_cats),
            },
            render_constraints={
                "constraints": _filter(render_cats),
                "bands": _bands_for(render_cats),
            },
            asset_constraints={
                "constraints": _filter(asset_cats),
            },
            audio_constraints={
                "constraints": _filter(audio_cats),
                "bands": _bands_for(audio_cats),
            },
        )

    # ── Policy Evaluation ────────────────────────────────────────

    def _evaluate_policy(
        self,
        proposed: dict,
        constraints: list[Constraint],
        audit: list[AuditEntry],
    ) -> list[EvaluationResult]:
        """Evaluate proposed creative output against all active constraints."""
        results: list[EvaluationResult] = []
        for c in constraints:
            if not c.parameter or not c.enforceable:
                continue

            actual = proposed.get(c.parameter)
            if actual is None:
                # Nested lookup: category.parameter
                cat_data = proposed.get(c.category, {})
                if isinstance(cat_data, dict):
                    actual = cat_data.get(c.parameter)
            if actual is None:
                continue

            result = _evaluate_single(c, actual)
            results.append(result)
            self._audit(
                audit, "EVALUATING", "evaluated_constraint",
                constraint_id=c.constraint_id,
                decision=result.result,
                rationale=result.message,
            )

        return results

    def _persist_policy_snapshot(
        self,
        ctx: SkillContext,
        input_dto: Skill15Input,
        output: Skill15Output,
    ) -> tuple[str, str, str]:
        """Persist policy stack + build event for API/DB replay and audit traceability."""
        stack_name = f"run_policy_{ctx.run_id}"
        event_id = ""
        try:
            stack_payload = {
                "run_id": ctx.run_id,
                "tenant_id": ctx.tenant_id,
                "project_id": ctx.project_id,
                "status": output.status,
                "active_persona_ref": input_dto.active_persona_ref,
                "summary": {
                    "hard_constraints": len(output.hard_constraints),
                    "soft_constraints": len(output.soft_constraints),
                    "guidelines": len(output.guidelines),
                    "conflicts": len(output.conflict_report),
                    "review_items": len(output.review_items),
                    "audit_entries": len(output.audit_trail),
                },
                "policy_output": output.model_dump(mode="json", exclude={
                    "policy_stack_id",
                    "policy_stack_name",
                    "policy_event_id",
                }),
            }

            stack = self._get_existing_policy_stack(ctx, stack_name)
            if stack is None:
                stack = CreativePolicyStack(
                    id=f"CPS_{uuid.uuid4().hex[:16].upper()}",
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    trace_id=ctx.trace_id,
                    correlation_id=ctx.correlation_id,
                    idempotency_key=(
                        f"{ctx.idempotency_key}:{self.skill_id}:policy_stack:{ctx.run_id}"
                    ),
                    name=stack_name,
                    status=output.status,
                    stack_json=stack_payload,
                )
                self.db.add(stack)
            else:
                stack.trace_id = ctx.trace_id
                stack.correlation_id = ctx.correlation_id
                stack.idempotency_key = (
                    f"{ctx.idempotency_key}:{self.skill_id}:policy_stack:{ctx.run_id}"
                )
                stack.status = output.status
                stack.stack_json = stack_payload

            run = self.db.get(RenderRun, ctx.run_id)
            run_stage = None
            if isinstance(run, RenderRun):
                run_stage = run.stage
                cfg = dict(run.config_json or {})
                cfg["policy_stack_id"] = stack.id
                cfg["policy_stack_name"] = stack.name
                cfg["policy_status"] = output.status
                run.config_json = cfg

            event_id = f"evt_{uuid.uuid4().hex[:24]}"
            self.db.add(
                WorkflowEvent(
                    id=event_id,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    trace_id=ctx.trace_id,
                    correlation_id=ctx.correlation_id,
                    idempotency_key=(
                        f"{ctx.idempotency_key}:{self.skill_id}:policy_stack_built:{uuid.uuid4().hex[:12]}"
                    ),
                    run_id=ctx.run_id,
                    stage=run_stage,
                    event_type="policy.stack.built",
                    event_version="1.0",
                    producer="ainern2d-studio-api.skill_15",
                    occurred_at=utcnow(),
                    payload_json={
                        "run_id": ctx.run_id,
                        "policy_stack_id": stack.id,
                        "policy_stack_name": stack.name,
                        "status": output.status,
                        "active_persona_ref": input_dto.active_persona_ref,
                        "review_items": list(output.review_items),
                        "audit_entries": len(output.audit_trail),
                    },
                )
            )
            self.db.commit()
            return stack.id, stack.name, event_id
        except Exception as exc:
            self.db.rollback()
            logger.warning(
                f"[{self.skill_id}] policy stack persistence failed | run={ctx.run_id} err={exc}"
            )
            return "", stack_name, ""

    def _get_existing_policy_stack(
        self,
        ctx: SkillContext,
        stack_name: str,
    ) -> CreativePolicyStack | None:
        try:
            row = self.db.execute(
                select(CreativePolicyStack)
                .where(
                    CreativePolicyStack.tenant_id == ctx.tenant_id,
                    CreativePolicyStack.project_id == ctx.project_id,
                    CreativePolicyStack.name == stack_name,
                    CreativePolicyStack.deleted_at.is_(None),
                )
                .limit(1)
            ).scalars().first()
            return row if isinstance(row, CreativePolicyStack) else None
        except Exception:
            return None

    # ── Audit Trail Helper ───────────────────────────────────────

    @staticmethod
    def _audit(
        trail: list[AuditEntry],
        stage: str,
        action: str,
        constraint_id: str = "",
        decision: str = "",
        rationale: str = "",
    ) -> None:
        trail.append(AuditEntry(
            timestamp=utcnow().isoformat(),
            stage=stage,
            action=action,
            constraint_id=constraint_id,
            decision=decision,
            rationale=rationale,
        ))


# ── Module-level helpers (stateless) ─────────────────────────────


def _rules_contradict(a: Constraint, b: Constraint) -> bool:
    """Heuristic: two constraints contradict if values disagree."""
    if a.value is not None and b.value is not None and a.value != b.value:
        return True
    if a.min_value is not None and b.max_value is not None and a.min_value > b.max_value:
        return True
    if b.min_value is not None and a.max_value is not None and b.min_value > a.max_value:
        return True
    return False


def _mutually_exclusive(a: Constraint, b: Constraint) -> bool:
    """Check if rules are logically mutually exclusive (forbid vs require)."""
    r1, r2 = a.rule.lower(), b.rule.lower()
    if r1.startswith("no_") and r2.startswith("require_") and r1[3:] == r2[8:]:
        return True
    if r2.startswith("no_") and r1.startswith("require_") and r2[3:] == r1[8:]:
        return True
    if r1.startswith("forbid_") and r2.startswith("require_") and r1[7:] == r2[8:]:
        return True
    if r2.startswith("forbid_") and r1.startswith("require_") and r2[7:] == r1[8:]:
        return True
    return False


def _pick_winner(
    a: Constraint, b: Constraint,
) -> tuple[Constraint, Constraint]:
    """Select winner by source priority, then constraint priority."""
    pri_a = _SOURCE_PRIORITY.get(a.source, 0)
    pri_b = _SOURCE_PRIORITY.get(b.source, 0)
    if pri_a != pri_b:
        return (a, b) if pri_a > pri_b else (b, a)
    return (a, b) if a.priority >= b.priority else (b, a)


def _try_merge(a: Constraint, b: Constraint) -> bool:
    """Try to merge two range constraints into their intersection."""
    if (a.min_value is not None and a.max_value is not None
            and b.min_value is not None and b.max_value is not None):
        new_min = max(a.min_value, b.min_value)
        new_max = min(a.max_value, b.max_value)
        if new_min <= new_max:
            a.min_value = new_min
            a.max_value = new_max
            return True
    return False


def _evaluate_single(c: Constraint, actual: Any) -> EvaluationResult:
    """Evaluate a single constraint against an actual value."""
    result = "pass"
    message = ""

    if isinstance(actual, (int, float)):
        if c.min_value is not None and actual < c.min_value:
            message = f"{c.parameter}={actual} below min {c.min_value}"
            result = "fail" if c.constraint_type == "hard_constraint" else "warn"
        elif c.max_value is not None and actual > c.max_value:
            message = f"{c.parameter}={actual} above max {c.max_value}"
            result = "fail" if c.constraint_type == "hard_constraint" else "warn"
        elif c.value is not None and isinstance(c.value, (int, float)):
            if actual != c.value and c.constraint_type == "hard_constraint":
                message = f"{c.parameter}={actual} != required {c.value}"
                result = "fail"
    elif isinstance(actual, str) and isinstance(c.value, str):
        if actual != c.value:
            if c.constraint_type == "hard_constraint":
                result = "fail"
                message = f"{c.parameter}='{actual}' != required '{c.value}'"
            elif c.constraint_type == "soft_constraint":
                result = "warn"
                message = f"{c.parameter}='{actual}' differs from preferred '{c.value}'"
    elif isinstance(actual, bool) and isinstance(c.value, bool):
        if actual != c.value:
            result = "fail" if c.constraint_type == "hard_constraint" else "warn"
            message = f"{c.parameter}={actual} violates {c.rule}"

    if not message:
        message = f"{c.parameter} within policy"

    expected = ""
    if c.min_value is not None and c.max_value is not None:
        expected = f"[{c.min_value}, {c.max_value}]"
    elif c.value is not None:
        expected = str(c.value)

    return EvaluationResult(
        constraint_id=c.constraint_id,
        constraint_type=c.constraint_type,
        category=c.category,
        result=result,
        actual_value=actual,
        expected=expected,
        message=message,
    )


class CreativeControlPolicyService(CreativeControlService):
    """Backward-compatible alias used by legacy imports/tests."""
