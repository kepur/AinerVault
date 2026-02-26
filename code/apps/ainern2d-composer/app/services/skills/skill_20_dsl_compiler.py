"""SKILL 20: DslCompilerService — 业务逻辑实现。
参考规格: SKILL_20_SHOT_DSL_COMPILER_PROMPT_BACKEND.md
状态: SERVICE_READY

State-machine (§7):
  INIT → PARSING_DSL → VALIDATING → INJECTING_RAG → RESOLVING_REFS
       → COMPILING → VERIFYING_TIMING → GENERATING_CANDIDATES
       → READY | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

import copy
import re
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_20 import (
    CompilationManifest,
    CompilationValidationReport,
    CompiledShot,
    CompilerTrace,
    RAGSnippet,
    ResolvedEmbedding,
    ResolvedLoRA,
    ShotCompilationStatus,
    ShotDSL,
    Skill20FeatureFlags,
    Skill20Input,
    Skill20Output,
    TimingAnchorRef,
    ValidationEntry,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Backend-specific prompt suffixes ─────────────────────────────────────────
_BACKEND_SUFFIX: dict[str, str] = {
    "comfyui": ", workflow=i2v_standard, steps=30, cfg=7.5",
    "sdxl": ", steps=30, cfg=7.0, sampler=dpmpp_2m_karras",
    "flux": ", num_steps=28, guidance=3.5",
    "wan": ", model=wan_i2v, steps=25, cfg=6.0",
    "hunyuan": ", model=hunyuan_dit, steps=30, cfg=5.0",
}

# ── Backend default parameter templates ──────────────────────────────────────
_BACKEND_DEFAULTS: dict[str, dict[str, Any]] = {
    "comfyui": {
        "workflow": "i2v_standard", "steps": 30, "cfg": 7.5,
        "sampler": "euler_a", "scheduler": "normal",
        "resolution": "720p", "fps": 24,
    },
    "sdxl": {
        "steps": 30, "cfg": 7.0, "sampler": "dpmpp_2m_karras",
        "resolution": "1024x1024",
    },
    "flux": {
        "num_steps": 28, "guidance": 3.5, "resolution": "1024x1024",
    },
    "wan": {
        "model": "wan_i2v", "steps": 25, "cfg": 6.0,
        "resolution": "720p", "fps": 24,
    },
    "hunyuan": {
        "model": "hunyuan_dit", "steps": 30, "cfg": 5.0,
        "resolution": "1024x1024",
    },
}

# ── Quality tier configs for multi-candidate ─────────────────────────────────
_QUALITY_TIERS: list[dict[str, Any]] = [
    {"tier": "primary", "step_mult": 1.0, "cfg_mult": 1.0, "suffix": ""},
    {"tier": "fallback", "step_mult": 0.7, "cfg_mult": 0.9, "suffix": " (simplified)"},
    {"tier": "minimal", "step_mult": 0.5, "cfg_mult": 0.8, "suffix": " (minimal)"},
]

_REQUIRED_DSL_FIELDS = {"shot_id"}
_ESTIMATED_TOKENS_PER_WORD = 1.3


class DslCompilerService(BaseSkillService[Skill20Input, Skill20Output]):
    """SKILL 20 — Shot DSL Compiler & Prompt Backend.

    State machine:
      INIT → PARSING_DSL → VALIDATING → INJECTING_RAG → RESOLVING_REFS
           → COMPILING → VERIFYING_TIMING → GENERATING_CANDIDATES
           → READY | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_20"
    skill_name = "DslCompilerService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # =====================================================================
    # execute — main entry
    # =====================================================================
    def execute(self, input_dto: Skill20Input, ctx: SkillContext) -> Skill20Output:
        warnings: list[str] = []
        ff = input_dto.feature_flags or Skill20FeatureFlags()

        # ── [S1] PARSING_DSL ─────────────────────────────────────────
        self._record_state(ctx, "INIT", "PARSING_DSL")
        shots_dsl, parse_warnings = self._parse_dsl(input_dto)
        warnings.extend(parse_warnings)

        if not shots_dsl:
            self._record_state(ctx, "PARSING_DSL", "FAILED")
            return self._build_failed_output(warnings, "DSL-PARSE-001: no shots to compile")

        # ── [S2] VALIDATING ──────────────────────────────────────────
        self._record_state(ctx, "PARSING_DSL", "VALIDATING")
        validated_shots, val_warnings, val_errors = self._validate_dsl(shots_dsl, ff)
        warnings.extend(val_warnings)

        if val_errors and ff.strict_validation:
            self._record_state(ctx, "VALIDATING", "FAILED")
            return self._build_failed_output(
                warnings + val_errors, "DSL-VAL-001: strict validation failed",
            )

        # ── [S3] INJECTING_RAG ───────────────────────────────────────
        self._record_state(ctx, "VALIDATING", "INJECTING_RAG")
        enriched_shots, rag_map = self._inject_rag(
            validated_shots, input_dto.rag_snippets,
            input_dto.kb_version, ff,
        )

        # Inject persona / creative control / compute budget context
        persona = input_dto.persona_style or {}
        creative_stack = input_dto.creative_control_stack or {}
        compute = input_dto.compute_budget or {}

        persona_influences = self._build_persona_influences(persona)
        constraints_applied = self._extract_constraints(creative_stack)

        # ── [S4] RESOLVING_REFS ──────────────────────────────────────
        self._record_state(ctx, "INJECTING_RAG", "RESOLVING_REFS")
        resolved_loras, resolved_embeddings, ref_warnings = self._resolve_refs(
            enriched_shots, input_dto.lora_registry,
            input_dto.embedding_registry, ff,
        )
        warnings.extend(ref_warnings)

        # ── [S5] COMPILING ───────────────────────────────────────────
        self._record_state(ctx, "RESOLVING_REFS", "COMPILING")
        compiled_shots, traces, compile_warnings = self._compile_all(
            enriched_shots, persona_influences, constraints_applied,
            resolved_loras, resolved_embeddings, rag_map,
            compute, creative_stack, persona, ff,
        )
        warnings.extend(compile_warnings)

        # ── [S6] VERIFYING_TIMING ────────────────────────────────────
        self._record_state(ctx, "COMPILING", "VERIFYING_TIMING")
        timing_warnings = self._verify_timing(
            enriched_shots, input_dto.timing_anchors,
            input_dto.audio_event_manifest, ff,
        )
        warnings.extend(timing_warnings)

        # Update traces with timing verification status
        for trace in traces:
            trace.timing_verified = len(timing_warnings) == 0

        # ── [S7] GENERATING_CANDIDATES ───────────────────────────────
        self._record_state(ctx, "VERIFYING_TIMING", "GENERATING_CANDIDATES")
        if ff.enable_multi_candidate_compile:
            compiled_shots, traces = self._generate_candidates(
                compiled_shots, traces, enriched_shots, ff,
            )

        # ── [S8] POST-COMPILATION VALIDATION ─────────────────────────
        validation_report = self._validate_compilation(compiled_shots, ff)

        # ── [S9] BATCH CONSISTENCY ───────────────────────────────────
        batch_checks: list[str] = []
        if ff.enable_batch_consistency:
            batch_checks = self._check_batch_consistency(compiled_shots)
            warnings.extend(
                f"batch_consistency: {c}" for c in batch_checks if "error" in c.lower()
            )

        # ── BUILD MANIFEST ───────────────────────────────────────────
        manifest = self._build_manifest(compiled_shots, traces, batch_checks)

        # ── FINAL STATE ──────────────────────────────────────────────
        has_errors = not validation_report.passed or manifest.failed_count > 0
        needs_review = has_errors or manifest.warning_count > 0

        if has_errors and ff.strict_validation:
            final_status = "failed"
            final_state = "FAILED"
        elif needs_review:
            final_status = "review_required"
            final_state = "REVIEW_REQUIRED"
        else:
            final_status = "compiled_ready"
            final_state = "READY"

        self._record_state(ctx, "GENERATING_CANDIDATES", final_state)

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"compiled={len(compiled_shots)} status={final_status}"
        )

        return Skill20Output(
            version=ff.compilation_format_version,
            status=final_status,
            compiled_shots=compiled_shots,
            compiler_traces=traces,
            manifest=manifest,
            validation_report=validation_report,
            warnings=warnings,
        )

    # =====================================================================
    # [S1] Parse DSL — convert legacy dict plans + structured DSL
    # =====================================================================
    @staticmethod
    def _parse_dsl(
        input_dto: Skill20Input,
    ) -> tuple[list[ShotDSL], list[str]]:
        warnings: list[str] = []
        result: list[ShotDSL] = []

        # Prefer structured shot_dsl; fall back to legacy shot_prompt_plans
        if input_dto.shot_dsl:
            result = list(input_dto.shot_dsl)
        else:
            for plan in input_dto.shot_prompt_plans or []:
                try:
                    result.append(ShotDSL(
                        shot_id=plan.get("shot_id", ""),
                        scene_id=plan.get("scene_id", ""),
                        shot_intent=plan.get("shot_intent", ""),
                        shot_type=plan.get("shot_type", ""),
                        subject_action=plan.get("subject_action", ""),
                        timing_anchor=plan.get("timing_anchor", ""),
                        visual_constraints=plan.get("visual_constraints", []),
                        style_targets=plan.get("style_targets", []),
                        fallback_class=plan.get("fallback_class", ""),
                        entity_refs=plan.get("entity_refs", []),
                        asset_refs=plan.get("asset_refs", []),
                        positive_prompt=plan.get("positive_prompt", ""),
                        negative_prompt=plan.get("negative_prompt", ""),
                        model_backend=plan.get(
                            "model_backend", plan.get("backend", "comfyui"),
                        ),
                        seed=plan.get("seed", -1),
                        lora_refs=plan.get("lora_refs", []),
                        embedding_refs=plan.get("embedding_refs", []),
                        params_override=plan.get("params_override", {}),
                        render_params=plan.get("render_params", {}),
                        asset_bindings=plan.get("asset_bindings", {}),
                    ))
                except Exception as exc:
                    warnings.append(f"DSL-PARSE-002: failed to parse plan: {exc}")

        if not result:
            warnings.append("DSL-PARSE-003: no valid shots parsed")

        return result, warnings

    # =====================================================================
    # [S2] Validate DSL (§SD1)
    # =====================================================================
    @staticmethod
    def _validate_dsl(
        shots: list[ShotDSL],
        ff: Skill20FeatureFlags,
    ) -> tuple[list[ShotDSL], list[str], list[str]]:
        """Return (valid_shots, warnings, errors)."""
        warnings: list[str] = []
        errors: list[str] = []
        valid: list[ShotDSL] = []

        seen_ids: set[str] = set()
        for shot in shots:
            # Required field: shot_id
            if not shot.shot_id:
                errors.append("DSL-VAL-010: shot missing shot_id")
                continue

            if shot.shot_id in seen_ids:
                errors.append(f"DSL-VAL-011: duplicate shot_id={shot.shot_id}")
                continue
            seen_ids.add(shot.shot_id)

            # Validate backend
            if shot.model_backend not in _BACKEND_SUFFIX:
                warnings.append(
                    f"DSL-VAL-020: shot={shot.shot_id} unknown backend "
                    f"'{shot.model_backend}', defaulting to comfyui"
                )
                shot = shot.model_copy(update={"model_backend": "comfyui"})

            # Check entity_refs format (expect entity IDs like "ENT_xxx")
            for ref in shot.entity_refs:
                if not isinstance(ref, str) or not ref.strip():
                    warnings.append(
                        f"DSL-VAL-030: shot={shot.shot_id} invalid entity_ref='{ref}'"
                    )

            # Check asset_refs format
            for ref in shot.asset_refs:
                if not isinstance(ref, str) or not ref.strip():
                    warnings.append(
                        f"DSL-VAL-031: shot={shot.shot_id} invalid asset_ref='{ref}'"
                    )

            # Strict mode: require positive_prompt or shot_intent
            if ff.strict_validation:
                if not shot.positive_prompt and not shot.shot_intent:
                    errors.append(
                        f"DSL-VAL-040: shot={shot.shot_id} "
                        f"requires positive_prompt or shot_intent in strict mode"
                    )
                    continue

            valid.append(shot)

        return valid, warnings, errors

    # =====================================================================
    # [S3] RAG Injection (§SD2)
    # =====================================================================
    @staticmethod
    def _inject_rag(
        shots: list[ShotDSL],
        rag_snippets: list[RAGSnippet],
        kb_version: str,
        ff: Skill20FeatureFlags,
    ) -> tuple[list[ShotDSL], dict[str, list[str]]]:
        """Inject RAG knowledge into shot prompts. Returns enriched shots + rag_map."""
        rag_map: dict[str, list[str]] = {}

        if not ff.enable_rag_injection or not rag_snippets:
            return shots, rag_map

        # Sort snippets by relevance
        sorted_snippets = sorted(
            rag_snippets, key=lambda s: s.relevance_score, reverse=True,
        )

        enriched: list[ShotDSL] = []
        for shot in shots:
            chunk_ids: list[str] = []
            rag_additions: list[str] = []

            # Match RAG snippets to shot context via style targets & visual constraints
            shot_keywords = set()
            shot_keywords.update(shot.style_targets)
            shot_keywords.update(shot.visual_constraints)
            if shot.shot_intent:
                shot_keywords.update(shot.shot_intent.lower().split())
            if shot.positive_prompt:
                shot_keywords.update(shot.positive_prompt.lower().split()[:10])

            for snippet in sorted_snippets:
                content_lower = snippet.content.lower()
                # Simple keyword overlap matching
                if any(kw.lower() in content_lower for kw in shot_keywords if kw):
                    rag_additions.append(snippet.content.strip())
                    chunk_ids.append(snippet.chunk_id)
                    if len(chunk_ids) >= 3:
                        break

            if rag_additions:
                rag_context = ", ".join(rag_additions)
                updated_prompt = (
                    f"{shot.positive_prompt}, {rag_context}"
                    if shot.positive_prompt else rag_context
                )
                shot = shot.model_copy(update={"positive_prompt": updated_prompt})

            rag_map[shot.shot_id] = chunk_ids
            enriched.append(shot)

        return enriched, rag_map

    # =====================================================================
    # [S4] Resolve LoRA / Embedding References
    # =====================================================================
    @staticmethod
    def _resolve_refs(
        shots: list[ShotDSL],
        lora_registry: dict[str, dict[str, Any]],
        embedding_registry: dict[str, dict[str, Any]],
        ff: Skill20FeatureFlags,
    ) -> tuple[dict[str, list[ResolvedLoRA]], dict[str, list[ResolvedEmbedding]], list[str]]:
        """Resolve LoRA and embedding references to actual model paths/triggers."""
        lora_map: dict[str, list[ResolvedLoRA]] = {}
        emb_map: dict[str, list[ResolvedEmbedding]] = {}
        warnings: list[str] = []

        if not ff.enable_lora_resolution:
            return lora_map, emb_map, warnings

        for shot in shots:
            resolved_loras: list[ResolvedLoRA] = []
            for ref in shot.lora_refs:
                if ref in lora_registry:
                    entry = lora_registry[ref]
                    resolved_loras.append(ResolvedLoRA(
                        ref_id=ref,
                        model_path=entry.get("model_path", ""),
                        trigger_word=entry.get("trigger_word", ""),
                        weight=float(entry.get("weight", 1.0)),
                        status="resolved",
                    ))
                else:
                    resolved_loras.append(ResolvedLoRA(
                        ref_id=ref, status="missing",
                    ))
                    warnings.append(
                        f"DSL-REF-010: shot={shot.shot_id} LoRA '{ref}' not in registry"
                    )
            lora_map[shot.shot_id] = resolved_loras

            resolved_embs: list[ResolvedEmbedding] = []
            for ref in shot.embedding_refs:
                if ref in embedding_registry:
                    entry = embedding_registry[ref]
                    resolved_embs.append(ResolvedEmbedding(
                        ref_id=ref,
                        model_path=entry.get("model_path", ""),
                        trigger_token=entry.get("trigger_token", ""),
                        status="resolved",
                    ))
                else:
                    resolved_embs.append(ResolvedEmbedding(
                        ref_id=ref, status="missing",
                    ))
                    warnings.append(
                        f"DSL-REF-011: shot={shot.shot_id} embedding '{ref}' not in registry"
                    )
            emb_map[shot.shot_id] = resolved_embs

        return lora_map, emb_map, warnings

    # =====================================================================
    # [S5] Compile all shots (§SD3)
    # =====================================================================
    def _compile_all(
        self,
        shots: list[ShotDSL],
        persona_influences: list[str],
        constraints_applied: list[str],
        resolved_loras: dict[str, list[ResolvedLoRA]],
        resolved_embeddings: dict[str, list[ResolvedEmbedding]],
        rag_map: dict[str, list[str]],
        compute: dict[str, Any],
        creative_stack: dict[str, Any],
        persona: dict[str, Any],
        ff: Skill20FeatureFlags,
    ) -> tuple[list[CompiledShot], list[CompilerTrace], list[str]]:
        compiled: list[CompiledShot] = []
        traces: list[CompilerTrace] = []
        warnings: list[str] = []

        for shot in shots:
            backend = shot.model_backend
            if backend not in _BACKEND_SUFFIX:
                backend = "comfyui"

            # ── Merge prompt layers (SKILL 10 + SKILL 08 + SKILL 09) ─
            merged_positive = self._merge_prompt_layers(
                shot.positive_prompt, shot.asset_bindings,
                shot.render_params, shot.style_targets,
            )

            # ── Inject LoRA / embedding triggers ─────────────────────
            lora_triggers: list[str] = []
            for lr in resolved_loras.get(shot.shot_id, []):
                if lr.status == "resolved" and lr.trigger_word:
                    lora_triggers.append(lr.trigger_word)

            emb_triggers: list[str] = []
            for er in resolved_embeddings.get(shot.shot_id, []):
                if er.status == "resolved" and er.trigger_token:
                    emb_triggers.append(er.trigger_token)

            if lora_triggers:
                merged_positive = f"{merged_positive}, {', '.join(lora_triggers)}"
            if emb_triggers:
                merged_positive = f"{merged_positive}, {', '.join(emb_triggers)}"

            # ── Apply negative prompt policies ───────────────────────
            negative = shot.negative_prompt

            # ── Backend-specific suffix ──────────────────────────────
            compiled_positive = merged_positive + _BACKEND_SUFFIX.get(backend, "")

            # ── Build parameters ─────────────────────────────────────
            params = self._build_parameters(shot, backend, compute)

            # ── Build backend payload ────────────────────────────────
            backend_payload: dict[str, Any] = {}
            if ff.enable_backend_specific_compiler:
                backend_payload = self._build_backend_payload(
                    backend, compiled_positive, negative, params,
                    resolved_loras.get(shot.shot_id, []),
                )

            # ── Estimate token count ─────────────────────────────────
            token_count = self._estimate_tokens(compiled_positive)

            shot_warnings: list[str] = []
            if not merged_positive:
                shot_warnings.append("empty_positive_prompt")
            if token_count > ff.max_token_limit:
                shot_warnings.append(
                    f"token_count={token_count} exceeds limit={ff.max_token_limit}"
                )

            compiled.append(CompiledShot(
                shot_id=shot.shot_id,
                backend=backend,
                candidate_id="C0",
                quality_tier="primary",
                positive_prompt=compiled_positive,
                negative_prompt=negative,
                parameters=params,
                constraints_applied=constraints_applied,
                persona_influences=persona_influences,
                rag_sources_used=rag_map.get(shot.shot_id, []),
                compile_warnings=shot_warnings,
                lora_triggers=lora_triggers,
                embedding_triggers=emb_triggers,
                token_count=token_count,
                backend_payload=backend_payload,
            ))

            # ── Build trace (§SD5) ───────────────────────────────────
            decisions = [
                {"step": "backend_selection", "value": backend},
                {"step": "persona_injection", "value": persona_influences},
                {"step": "constraint_application", "value": constraints_applied},
                {"step": "lora_resolution",
                 "value": [lr.ref_id for lr in resolved_loras.get(shot.shot_id, [])]},
                {"step": "embedding_resolution",
                 "value": [er.ref_id for er in resolved_embeddings.get(shot.shot_id, [])]},
                {"step": "rag_injection", "value": rag_map.get(shot.shot_id, [])},
                {"step": "prompt_merge",
                 "value": {"has_asset_bindings": bool(shot.asset_bindings),
                           "has_render_params": bool(shot.render_params)}},
            ]

            traces.append(CompilerTrace(
                shot_id=shot.shot_id,
                decisions=decisions,
                warnings=shot_warnings,
                rag_chunks_injected=rag_map.get(shot.shot_id, []),
                persona_version=persona.get("version", ""),
                kb_version="",
                policy_version=creative_stack.get("version", ""),
                compiler_template_version=ff.compilation_format_version,
                constraints_trimmed=[],
            ))

            warnings.extend(
                f"shot={shot.shot_id}: {w}" for w in shot_warnings
            )

        return compiled, traces, warnings

    # =====================================================================
    # [S6] Verify Timing Anchors (§SD1.2)
    # =====================================================================
    @staticmethod
    def _verify_timing(
        shots: list[ShotDSL],
        timing_anchors: list[TimingAnchorRef],
        audio_manifest: dict[str, Any],
        ff: Skill20FeatureFlags,
    ) -> list[str]:
        """Validate timing anchors match audio timeline from SKILL 06."""
        warnings: list[str] = []

        if not ff.enable_timing_verification or not timing_anchors:
            return warnings

        anchor_index: dict[str, TimingAnchorRef] = {
            a.anchor_id: a for a in timing_anchors
        }
        anchor_by_shot: dict[str, list[TimingAnchorRef]] = {}
        for a in timing_anchors:
            anchor_by_shot.setdefault(a.shot_id, []).append(a)

        for shot in shots:
            if not shot.timing_anchor:
                continue

            # Check that the referenced anchor exists
            if shot.timing_anchor not in anchor_index:
                warnings.append(
                    f"DSL-TIME-010: shot={shot.shot_id} timing_anchor "
                    f"'{shot.timing_anchor}' not found in audio_event_manifest"
                )
                continue

            anchor = anchor_index[shot.timing_anchor]

            # Check for timing overlap with other shots referencing same anchor
            if anchor.shot_id and anchor.shot_id != shot.shot_id:
                warnings.append(
                    f"DSL-TIME-020: shot={shot.shot_id} timing_anchor "
                    f"'{shot.timing_anchor}' belongs to different shot "
                    f"'{anchor.shot_id}'"
                )

        # Check for overlapping shot time windows
        shot_anchors_sorted: list[tuple[str, int, int]] = []
        for shot_id, anchors in anchor_by_shot.items():
            times = [a.time_ms for a in anchors]
            end_times = [a.end_ms for a in anchors if a.end_ms > 0]
            if times:
                start = min(times)
                end = max(end_times) if end_times else max(times)
                shot_anchors_sorted.append((shot_id, start, end))

        shot_anchors_sorted.sort(key=lambda x: x[1])
        for i in range(1, len(shot_anchors_sorted)):
            prev_id, _, prev_end = shot_anchors_sorted[i - 1]
            cur_id, cur_start, _ = shot_anchors_sorted[i]
            if cur_start < prev_end:
                warnings.append(
                    f"DSL-TIME-030: timing overlap between shot={prev_id} "
                    f"and shot={cur_id} (overlap {prev_end - cur_start}ms)"
                )

        return warnings

    # =====================================================================
    # [S7] Multi-Candidate Compilation (§SD4)
    # =====================================================================
    @staticmethod
    def _generate_candidates(
        primary_shots: list[CompiledShot],
        primary_traces: list[CompilerTrace],
        dsl_shots: list[ShotDSL],
        ff: Skill20FeatureFlags,
    ) -> tuple[list[CompiledShot], list[CompilerTrace]]:
        """Generate multi-candidate prompt variants per shot."""
        all_compiled: list[CompiledShot] = []
        all_traces: list[CompilerTrace] = []
        count = min(ff.multi_candidate_count, len(_QUALITY_TIERS))

        dsl_index = {s.shot_id: s for s in dsl_shots}

        for idx, shot in enumerate(primary_shots):
            trace = primary_traces[idx] if idx < len(primary_traces) else None

            for tier_idx in range(count):
                tier = _QUALITY_TIERS[tier_idx]
                candidate_id = f"C{tier_idx}"

                if tier_idx == 0:
                    # Primary — use as-is
                    all_compiled.append(shot.model_copy(
                        update={"candidate_id": candidate_id, "quality_tier": tier["tier"]},
                    ))
                else:
                    # Build degraded variant
                    degraded_params = dict(shot.parameters)
                    for key in ("steps", "num_steps"):
                        if key in degraded_params:
                            degraded_params[key] = max(
                                1, int(degraded_params[key] * tier["step_mult"]),
                            )
                    for key in ("cfg", "guidance"):
                        if key in degraded_params:
                            degraded_params[key] = round(
                                degraded_params[key] * tier["cfg_mult"], 2,
                            )

                    degraded_prompt = shot.positive_prompt + tier["suffix"]
                    dsl = dsl_index.get(shot.shot_id)
                    if dsl and dsl.fallback_class and tier_idx >= 2:
                        degraded_prompt = (
                            f"{dsl.fallback_class}{tier['suffix']}"
                            + _BACKEND_SUFFIX.get(shot.backend, "")
                        )

                    all_compiled.append(CompiledShot(
                        shot_id=shot.shot_id,
                        backend=shot.backend,
                        candidate_id=candidate_id,
                        quality_tier=tier["tier"],
                        positive_prompt=degraded_prompt,
                        negative_prompt=shot.negative_prompt,
                        parameters=degraded_params,
                        constraints_applied=shot.constraints_applied,
                        persona_influences=shot.persona_influences,
                        rag_sources_used=shot.rag_sources_used,
                        compile_warnings=shot.compile_warnings
                        + [f"degraded_tier={tier['tier']}"],
                        lora_triggers=shot.lora_triggers if tier_idx < 2 else [],
                        embedding_triggers=shot.embedding_triggers if tier_idx < 2 else [],
                        token_count=shot.token_count,
                        backend_payload={},
                    ))

                if trace:
                    all_traces.append(trace.model_copy(
                        update={
                            "decisions": trace.decisions + [
                                {"step": "candidate_generation",
                                 "value": {"candidate_id": candidate_id,
                                           "tier": tier["tier"]}},
                            ],
                        },
                    ))

        return all_compiled, all_traces

    # =====================================================================
    # Post-compilation Validation
    # =====================================================================
    @staticmethod
    def _validate_compilation(
        compiled: list[CompiledShot],
        ff: Skill20FeatureFlags,
    ) -> CompilationValidationReport:
        entries: list[ValidationEntry] = []
        token_violations = 0
        ref_errors = 0
        format_errors = 0

        for shot in compiled:
            # Token limit check
            if shot.token_count > ff.max_token_limit:
                token_violations += 1
                entries.append(ValidationEntry(
                    shot_id=shot.shot_id,
                    check="token_limit",
                    severity="warning",
                    message=(
                        f"Token count {shot.token_count} exceeds "
                        f"limit {ff.max_token_limit}"
                    ),
                ))

            # Reference integrity — LoRA triggers should be in prompt
            for trigger in shot.lora_triggers:
                if trigger and trigger not in shot.positive_prompt:
                    ref_errors += 1
                    entries.append(ValidationEntry(
                        shot_id=shot.shot_id,
                        check="lora_trigger_in_prompt",
                        severity="error",
                        message=f"LoRA trigger '{trigger}' not found in compiled prompt",
                    ))

            # Format compliance per backend
            if shot.backend == "comfyui" and shot.backend_payload:
                if "workflow" not in shot.backend_payload:
                    format_errors += 1
                    entries.append(ValidationEntry(
                        shot_id=shot.shot_id,
                        check="comfyui_workflow_required",
                        severity="error",
                        message="ComfyUI payload missing 'workflow' field",
                    ))

            # Empty prompt check
            if not shot.positive_prompt.strip():
                entries.append(ValidationEntry(
                    shot_id=shot.shot_id,
                    check="empty_prompt",
                    severity="error",
                    message="Compiled positive prompt is empty",
                ))

        has_errors = any(e.severity == "error" for e in entries)
        return CompilationValidationReport(
            passed=not has_errors,
            entries=entries,
            token_limit_violations=token_violations,
            reference_integrity_errors=ref_errors,
            format_compliance_errors=format_errors,
        )

    # =====================================================================
    # Batch Consistency
    # =====================================================================
    @staticmethod
    def _check_batch_consistency(compiled: list[CompiledShot]) -> list[str]:
        """Check consistency constraints across all shots in a batch."""
        checks: list[str] = []

        # Group by scene (if scene info embedded in shot_id pattern "scXX_shYY")
        backends_used: set[str] = set()
        resolutions_used: set[str] = set()
        fps_used: set[int] = set()

        for shot in compiled:
            if shot.quality_tier != "primary":
                continue
            backends_used.add(shot.backend)
            res = shot.parameters.get("resolution", "")
            if res:
                resolutions_used.add(str(res))
            fps = shot.parameters.get("fps")
            if fps is not None:
                fps_used.add(int(fps))

        if len(backends_used) > 1:
            checks.append(
                f"info: mixed backends in batch: {sorted(backends_used)}"
            )

        if len(resolutions_used) > 1:
            checks.append(
                f"warning: inconsistent resolutions: {sorted(resolutions_used)}"
            )

        if len(fps_used) > 1:
            checks.append(
                f"error: inconsistent fps values: {sorted(fps_used)}"
            )

        if not checks:
            checks.append("ok: batch consistency passed")

        return checks

    # =====================================================================
    # Build Manifest
    # =====================================================================
    @staticmethod
    def _build_manifest(
        compiled: list[CompiledShot],
        traces: list[CompilerTrace],
        batch_checks: list[str],
    ) -> CompilationManifest:
        statuses: list[ShotCompilationStatus] = []
        # Deduplicate by shot_id (multi-candidate produces multiples)
        seen: dict[str, ShotCompilationStatus] = {}

        for shot in compiled:
            if shot.shot_id not in seen:
                seen[shot.shot_id] = ShotCompilationStatus(
                    shot_id=shot.shot_id,
                    status="compiled" if not shot.compile_warnings else "warning",
                    warnings=shot.compile_warnings,
                    candidate_count=1,
                )
            else:
                seen[shot.shot_id].candidate_count += 1

        statuses = list(seen.values())
        compiled_count = sum(1 for s in statuses if s.status in ("compiled", "warning"))
        warning_count = sum(1 for s in statuses if s.status == "warning")
        failed_count = sum(1 for s in statuses if s.status == "failed")

        return CompilationManifest(
            version="1.0",
            total_shots=len(statuses),
            compiled_count=compiled_count,
            warning_count=warning_count,
            failed_count=failed_count,
            shot_statuses=statuses,
            batch_consistency_checks=batch_checks,
        )

    # =====================================================================
    # Helpers
    # =====================================================================

    @staticmethod
    def _build_persona_influences(persona: dict[str, Any]) -> list[str]:
        influences: list[str] = []
        if persona.get("narrative_tone"):
            influences.append(f"tone:{persona['narrative_tone']}")
        if persona.get("visual_style"):
            for k, v in persona["visual_style"].items():
                influences.append(f"style:{k}={v}")
        if persona.get("director_id"):
            version = persona.get("version", "latest")
            influences.append(f"{persona['director_id']}@{version}")
        return influences

    @staticmethod
    def _extract_constraints(creative_stack: dict[str, Any]) -> list[str]:
        constraints: list[str] = []
        for c in creative_stack.get("hard_constraints", []):
            rule = c.get("rule", "")
            if rule:
                constraints.append(f"hard:{rule}")
        for c in creative_stack.get("soft_constraints", []):
            rule = c.get("rule", "")
            if rule:
                constraints.append(f"soft:{rule}")
        return constraints

    @staticmethod
    def _merge_prompt_layers(
        base_prompt: str,
        asset_bindings: dict[str, Any],
        render_params: dict[str, Any],
        style_targets: list[str],
    ) -> str:
        """Merge prompt from SKILL 10 with asset refs (08) and render params (09)."""
        parts: list[str] = [base_prompt] if base_prompt else []

        # Inject asset descriptions from SKILL 08
        for key, binding in asset_bindings.items():
            desc = binding if isinstance(binding, str) else binding.get("description", "")
            if desc:
                parts.append(desc)

        # Inject render style hints from SKILL 09
        if render_params.get("style_hint"):
            parts.append(render_params["style_hint"])
        if render_params.get("lighting"):
            parts.append(render_params["lighting"])
        if render_params.get("color_palette"):
            parts.append(f"color palette: {render_params['color_palette']}")

        # Inject style targets from DSL
        if style_targets:
            parts.extend(style_targets)

        return ", ".join(p for p in parts if p)

    @staticmethod
    def _build_parameters(
        shot: ShotDSL,
        backend: str,
        compute: dict[str, Any],
    ) -> dict[str, Any]:
        """Build parameter dict from defaults + overrides + compute budget."""
        params: dict[str, Any] = dict(_BACKEND_DEFAULTS.get(backend, {}))
        params["seed"] = shot.seed
        params["backend"] = backend

        # Apply render params from SKILL 09
        for k, v in shot.render_params.items():
            if k not in ("style_hint", "lighting", "color_palette"):
                params[k] = v

        # Apply explicit overrides
        params.update(shot.params_override)

        # Apply compute budget constraints from SKILL 19
        if compute.get("gpu_tier"):
            params["gpu_tier"] = compute["gpu_tier"]
        if compute.get("max_steps"):
            for key in ("steps", "num_steps"):
                if key in params and params[key] > compute["max_steps"]:
                    params[key] = compute["max_steps"]
        if compute.get("max_resolution"):
            params["resolution"] = compute["max_resolution"]

        # Inject LoRA refs into parameters
        if shot.lora_refs:
            params["lora_refs"] = shot.lora_refs

        return params

    @staticmethod
    def _build_backend_payload(
        backend: str,
        positive: str,
        negative: str,
        params: dict[str, Any],
        loras: list[ResolvedLoRA],
    ) -> dict[str, Any]:
        """Build backend-specific compiled payload."""
        if backend == "comfyui":
            lora_nodes = [
                {"model_path": lr.model_path, "strength": lr.weight}
                for lr in loras if lr.status == "resolved" and lr.model_path
            ]
            return {
                "workflow": params.get("workflow", "i2v_standard"),
                "nodes": {
                    "KSampler": {
                        "seed": params.get("seed", -1),
                        "steps": params.get("steps", 30),
                        "cfg": params.get("cfg", 7.5),
                        "sampler_name": params.get("sampler", "euler_a"),
                        "scheduler": params.get("scheduler", "normal"),
                    },
                    "CLIPTextEncode_positive": {"text": positive},
                    "CLIPTextEncode_negative": {"text": negative},
                    "EmptyLatentImage": {
                        "width": _parse_resolution(params.get("resolution", "720p"))[0],
                        "height": _parse_resolution(params.get("resolution", "720p"))[1],
                    },
                },
                "lora_stack": lora_nodes,
            }
        elif backend == "sdxl":
            return {
                "prompt": positive,
                "negative_prompt": negative,
                "steps": params.get("steps", 30),
                "cfg_scale": params.get("cfg", 7.0),
                "sampler_name": params.get("sampler", "dpmpp_2m_karras"),
                "width": _parse_resolution(params.get("resolution", "1024x1024"))[0],
                "height": _parse_resolution(params.get("resolution", "1024x1024"))[1],
                "seed": params.get("seed", -1),
            }
        elif backend == "flux":
            return {
                "prompt": positive,
                "num_steps": params.get("num_steps", 28),
                "guidance": params.get("guidance", 3.5),
                "width": _parse_resolution(params.get("resolution", "1024x1024"))[0],
                "height": _parse_resolution(params.get("resolution", "1024x1024"))[1],
                "seed": params.get("seed", -1),
            }
        elif backend == "wan":
            return {
                "prompt": positive,
                "negative_prompt": negative,
                "model": params.get("model", "wan_i2v"),
                "steps": params.get("steps", 25),
                "cfg": params.get("cfg", 6.0),
                "fps": params.get("fps", 24),
                "resolution": params.get("resolution", "720p"),
                "seed": params.get("seed", -1),
            }
        elif backend == "hunyuan":
            return {
                "prompt": positive,
                "negative_prompt": negative,
                "model": params.get("model", "hunyuan_dit"),
                "steps": params.get("steps", 30),
                "cfg": params.get("cfg", 5.0),
                "resolution": params.get("resolution", "1024x1024"),
                "seed": params.get("seed", -1),
            }
        return {}

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough CLIP token estimation (~1.3 tokens per word)."""
        if not text:
            return 0
        words = len(text.split())
        return int(words * _ESTIMATED_TOKENS_PER_WORD)

    @staticmethod
    def _build_failed_output(warnings: list[str], error: str) -> Skill20Output:
        return Skill20Output(
            status="failed",
            warnings=warnings + [error],
            validation_report=CompilationValidationReport(passed=False),
        )


# ── Module-level helpers ─────────────────────────────────────────────────────

def _parse_resolution(res: str | Any) -> tuple[int, int]:
    """Parse resolution string to (width, height)."""
    if isinstance(res, str):
        res_lower = res.lower().strip()
        presets = {
            "720p": (1280, 720), "1080p": (1920, 1080),
            "480p": (854, 480), "4k": (3840, 2160),
        }
        if res_lower in presets:
            return presets[res_lower]
        match = re.match(r"(\d+)\s*[xX×]\s*(\d+)", res)
        if match:
            return int(match.group(1)), int(match.group(2))
    return 1280, 720
