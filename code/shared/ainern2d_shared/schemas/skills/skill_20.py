"""SKILL 20: Shot DSL Compiler & Prompt Backend — Input/Output DTOs.

Spec: SKILL_20_SHOT_DSL_COMPILER_PROMPT_BACKEND.md
"""
from __future__ import annotations

from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


# ── Shot DSL Structure (§4) ──────────────────────────────────────────────────

class CameraSpec(BaseSchema):
    """Camera framing / angle / movement."""
    framing: str = ""
    angle: str = ""
    movement: str = ""


class ShotDSL(BaseSchema):
    """Single shot DSL entry — intent-driven intermediate representation (§4)."""
    shot_id: str
    scene_id: str = ""
    shot_intent: str = ""
    shot_type: str = ""
    camera: CameraSpec = CameraSpec()
    subject_action: str = ""
    timing_anchor: str = ""
    visual_constraints: list[str] = []
    style_targets: list[str] = []
    fallback_class: str = ""
    entity_refs: list[str] = []
    asset_refs: list[str] = []
    positive_prompt: str = ""
    negative_prompt: str = ""
    model_backend: str = "comfyui"
    seed: int = -1
    lora_refs: list[str] = []
    embedding_refs: list[str] = []
    params_override: dict[str, Any] = {}
    render_params: dict[str, Any] = {}
    asset_bindings: dict[str, Any] = {}


# ── Feature Flags (§2.2) ────────────────────────────────────────────────────

class Skill20FeatureFlags(BaseSchema):
    enable_rag_injection: bool = True
    enable_backend_specific_compiler: bool = True
    enable_compiler_trace: bool = True
    enable_multi_candidate_compile: bool = False
    compilation_format_version: str = "1.0"
    strict_validation: bool = False
    multi_candidate_count: int = 3
    enable_timing_verification: bool = True
    enable_lora_resolution: bool = True
    enable_batch_consistency: bool = True
    max_token_limit: int = 77


# ── RAG Context ──────────────────────────────────────────────────────────────

class RAGSnippet(BaseSchema):
    chunk_id: str
    content: str = ""
    source: str = ""
    relevance_score: float = 0.0
    kb_version: str = ""


# ── Timing Anchor Reference ─────────────────────────────────────────────────

class TimingAnchorRef(BaseSchema):
    anchor_id: str
    shot_id: str = ""
    time_ms: int = 0
    anchor_type: str = ""
    end_ms: int = 0


# ── LoRA / Embedding Resolution ─────────────────────────────────────────────

class ResolvedLoRA(BaseSchema):
    ref_id: str
    model_path: str = ""
    trigger_word: str = ""
    weight: float = 1.0
    status: str = "resolved"


class ResolvedEmbedding(BaseSchema):
    ref_id: str
    model_path: str = ""
    trigger_token: str = ""
    status: str = "resolved"


# ── Compiled Artifacts (§3.1) ────────────────────────────────────────────────

class CompiledShot(BaseSchema):
    shot_id: str
    backend: str = "comfyui"
    candidate_id: str = "C0"
    quality_tier: str = "primary"
    positive_prompt: str = ""
    negative_prompt: str = ""
    parameters: dict[str, Any] = {}
    constraints_applied: list[str] = []
    persona_influences: list[str] = []
    rag_sources_used: list[str] = []
    compile_warnings: list[str] = []
    lora_triggers: list[str] = []
    embedding_triggers: list[str] = []
    token_count: int = 0
    backend_payload: dict[str, Any] = {}


# ── Compiler Trace (§SD5) ───────────────────────────────────────────────────

class CompilerTrace(BaseSchema):
    shot_id: str
    decisions: list[dict[str, Any]] = []
    warnings: list[str] = []
    rag_chunks_injected: list[str] = []
    persona_version: str = ""
    kb_version: str = ""
    policy_version: str = ""
    compiler_template_version: str = ""
    constraints_trimmed: list[str] = []
    timing_verified: bool = False


# ── Compilation Manifest ─────────────────────────────────────────────────────

class ShotCompilationStatus(BaseSchema):
    shot_id: str
    status: str = "compiled"
    warnings: list[str] = []
    error: str = ""
    candidate_count: int = 1


class CompilationManifest(BaseSchema):
    version: str = "1.0"
    total_shots: int = 0
    compiled_count: int = 0
    warning_count: int = 0
    failed_count: int = 0
    shot_statuses: list[ShotCompilationStatus] = []
    batch_consistency_checks: list[str] = []


# ── Validation Report ────────────────────────────────────────────────────────

class ValidationEntry(BaseSchema):
    shot_id: str = ""
    check: str = ""
    severity: str = "warning"
    message: str = ""


class CompilationValidationReport(BaseSchema):
    passed: bool = True
    entries: list[ValidationEntry] = []
    token_limit_violations: int = 0
    reference_integrity_errors: int = 0
    format_compliance_errors: int = 0


# ── Input / Output ───────────────────────────────────────────────────────────

class Skill20Input(BaseSchema):
    """SKILL 20 input DTO (§2)."""
    shot_prompt_plans: list[dict[str, Any]] = []
    shot_dsl: list[ShotDSL] = []
    creative_control_stack: dict[str, Any] = {}
    compute_budget: dict[str, Any] = {}
    persona_style: dict[str, Any] = {}
    rag_snippets: list[RAGSnippet] = []
    kb_version: str = ""
    audio_event_manifest: dict[str, Any] = {}
    timing_anchors: list[TimingAnchorRef] = []
    lora_registry: dict[str, dict[str, Any]] = {}
    embedding_registry: dict[str, dict[str, Any]] = {}
    backend_capability_registry: dict[str, Any] = {}
    compiler_templates: dict[str, dict[str, Any]] = {}
    negative_prompt_policies: list[dict[str, Any]] = []
    feature_flags: Skill20FeatureFlags = Skill20FeatureFlags()


class Skill20Output(BaseSchema):
    """SKILL 20 output DTO (§3)."""
    version: str = "1.0"
    status: str = "compiled_ready"
    compiled_shots: list[CompiledShot] = []
    compiler_traces: list[CompilerTrace] = []
    manifest: CompilationManifest = CompilationManifest()
    validation_report: CompilationValidationReport = CompilationValidationReport()
    warnings: list[str] = []
