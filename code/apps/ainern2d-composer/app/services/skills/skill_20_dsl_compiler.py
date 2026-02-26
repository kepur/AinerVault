"""SKILL 20: DslCompilerService — 业务逻辑实现。
参考规格: SKILL_20_SHOT_DSL_COMPILER_PROMPT_BACKEND.md
状态: SERVICE_READY
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_20 import (
    CompiledShot,
    CompilerTrace,
    Skill20Input,
    Skill20Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Backend-specific prompt suffixes ─────────────────────────────────────────
_BACKEND_SUFFIX: dict[str, str] = {
    "comfyui": ", workflow=i2v_standard, steps=30, cfg=7.5",
    "sdxl": ", steps=30, cfg=7.0, sampler=dpmpp_2m_karras",
    "flux": ", num_steps=28, guidance=3.5",
}


class DslCompilerService(BaseSkillService[Skill20Input, Skill20Output]):
    """SKILL 20 — Shot DSL Compiler & Prompt Backend.

    State machine:
      INIT → VALIDATING_DSL → INJECTING_CONTEXT → COMPILING → EMITTING_ARTIFACTS
           → COMPILED_READY | FAILED
    """

    skill_id = "skill_20"
    skill_name = "DslCompilerService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill20Input, ctx: SkillContext) -> Skill20Output:
        self._record_state(ctx, "INIT", "VALIDATING_DSL")

        plans: list[dict] = input_dto.shot_prompt_plans or []
        persona = input_dto.persona_style or {}
        creative_stack = input_dto.creative_control_stack or {}
        compute = input_dto.compute_budget or {}

        self._record_state(ctx, "VALIDATING_DSL", "INJECTING_CONTEXT")

        # Build persona influence tags
        persona_influences: list[str] = []
        if persona.get("narrative_tone"):
            persona_influences.append(f"tone:{persona['narrative_tone']}")
        if persona.get("visual_style"):
            for k, v in persona["visual_style"].items():
                persona_influences.append(f"style:{k}={v}")

        # Extract hard constraints from creative stack
        constraints_applied: list[str] = [
            c.get("rule", "") for c in creative_stack.get("hard_constraints", [])
            if c.get("rule")
        ]

        self._record_state(ctx, "INJECTING_CONTEXT", "COMPILING")

        compiled_shots: list[CompiledShot] = []
        compiler_traces: list[CompilerTrace] = []

        for plan in plans:
            shot_id = plan.get("shot_id", "")
            backend = plan.get("model_backend", plan.get("backend", "comfyui"))
            if backend not in _BACKEND_SUFFIX:
                backend = "comfyui"

            positive = plan.get("positive_prompt", "")
            negative = plan.get("negative_prompt", "")
            seed = plan.get("seed", -1)
            lora_refs: list[str] = plan.get("lora_refs", [])

            # Append backend-specific suffix
            compiled_positive = positive + _BACKEND_SUFFIX.get(backend, "")

            # Build parameters
            params: dict = {
                "seed": seed,
                "backend": backend,
            }
            params.update(plan.get("params_override", {}))
            if compute.get("gpu_tier"):
                params["gpu_tier"] = compute["gpu_tier"]

            # Inject lora into parameters
            if lora_refs:
                params["lora_refs"] = lora_refs

            decisions = [
                {"step": "backend_selection", "value": backend},
                {"step": "persona_injection", "value": persona_influences},
                {"step": "constraint_application", "value": constraints_applied},
            ]
            warnings: list[str] = []
            if not positive:
                warnings.append("empty_positive_prompt")

            compiled_shots.append(CompiledShot(
                shot_id=shot_id,
                backend=backend,
                positive_prompt=compiled_positive,
                negative_prompt=negative,
                parameters=params,
                constraints_applied=constraints_applied,
                persona_influences=persona_influences,
                rag_sources_used=[],
            ))
            compiler_traces.append(CompilerTrace(
                shot_id=shot_id,
                decisions=decisions,
                warnings=warnings,
            ))

        self._record_state(ctx, "COMPILING", "EMITTING_ARTIFACTS")
        self._record_state(ctx, "EMITTING_ARTIFACTS", "COMPILED_READY")

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"compiled={len(compiled_shots)}"
        )

        return Skill20Output(
            compiled_shots=compiled_shots,
            compiler_traces=compiler_traces,
            status="compiled_ready",
        )
