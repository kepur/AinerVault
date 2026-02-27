"""SKILL 15: Creative Control Policy — Input/Output DTOs.

Constraint types:
  - hard_constraint: must enforce, blocks if violated
  - soft_constraint: prefer, warn if violated
  - guideline: suggest, info-level

Constraint sources:
  - system_default, culture_pack, style_pack, user_explicit, project_policy, regulatory

Constraint categories:
  - visual (color, composition, style)
  - audio (volume, tempo, genre)
  - narrative (pacing, tone, language)
  - technical (resolution, fps, duration)
"""
from __future__ import annotations

from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


# ── Constraint Model ──────────────────────────────────────────────


class Constraint(BaseSchema):
    """Single policy constraint with source attribution."""

    constraint_id: str = ""
    constraint_type: str = "hard_constraint"  # hard_constraint | soft_constraint | guideline
    source: str = "system_default"  # system_default | culture_pack | style_pack | user_explicit | project_policy | regulatory
    category: str = "visual"  # visual | audio | narrative | technical
    dimension: str = ""  # color | composition | style | volume | tempo | genre | pacing | tone | language | resolution | fps | duration
    parameter: str = ""
    rule: str = ""
    value: Any = None
    min_value: float | None = None
    max_value: float | None = None
    priority: int = 0
    description: str = ""
    enforceable: bool = True


# ── Conflict Detection ────────────────────────────────────────────


class ConflictRecord(BaseSchema):
    """Detected conflict between two constraints."""

    conflict_id: str = ""
    conflict_type: str = ""  # source_priority_conflict | mutual_exclusion | range_overlap | semantic_contradiction
    constraint_a_id: str = ""
    constraint_b_id: str = ""
    severity: str = "warning"  # error | warning | info
    description: str = ""
    resolution: str = ""
    resolution_path: str = ""
    winning_constraint_id: str = ""


# ── Exploration Band ──────────────────────────────────────────────


class ExplorationBand(BaseSchema):
    """Creative freedom range for a soft-constrained parameter."""

    parameter: str = ""
    category: str = "visual"
    hard_min: float = 0.0
    soft_min: float = 0.0
    preferred: float = 0.5
    soft_max: float = 1.0
    hard_max: float = 1.0
    unit: str = ""


# ── Policy Evaluation ─────────────────────────────────────────────


class EvaluationResult(BaseSchema):
    """Result of evaluating a proposed output against one constraint."""

    constraint_id: str = ""
    constraint_type: str = ""
    category: str = ""
    result: str = "pass"  # pass | fail | warn
    actual_value: Any = None
    expected: str = ""
    message: str = ""


# ── Downstream Export ─────────────────────────────────────────────


class DownstreamExport(BaseSchema):
    """Resolved policy exported for downstream skills."""

    prompt_constraints: dict = {}   # for SKILL 10
    render_constraints: dict = {}   # for SKILL 09
    asset_constraints: dict = {}    # for SKILL 08
    audio_constraints: dict = {}    # for SKILL 06


# ── Audit Trail ───────────────────────────────────────────────────


class AuditEntry(BaseSchema):
    """Audit log entry for constraint evaluation decisions."""

    timestamp: str = ""
    stage: str = ""
    action: str = ""
    constraint_id: str = ""
    decision: str = ""
    rationale: str = ""


# ── Feature Flags ─────────────────────────────────────────────────


class FeatureFlags(BaseSchema):
    """Runtime feature toggles for policy behavior."""

    strict_mode: bool = False
    allow_exploration_override: bool = False
    conflict_resolution_strategy: str = "priority"  # priority | merge | reject
    enable_policy_conflict_scan: bool = True
    enable_exploration_band: bool = True
    enable_persona_soft_constraints: bool = True


# ── Input / Output DTOs ──────────────────────────────────────────


class Skill15Input(BaseSchema):
    """Input for SKILL 15 Creative Control Policy."""

    # Required inputs (from upstream skills)
    timeline_final: dict = {}               # from SKILL 06
    audio_event_manifest: dict = {}         # from SKILL 06
    culture_constraints: list[dict] = []    # from SKILL 07
    persona_profile: dict = {}              # from SKILL 14
    persona_dataset_index_result: dict = {}  # from SKILL 22
    active_persona_ref: str = ""
    project_constraints: dict = {}          # project-level budget / SLA

    # Optional inputs
    user_overrides: list[dict] = []
    regulatory_constraints: list[dict] = []
    compute_budget: dict = {}               # from SKILL 19
    feature_flags: dict = {}

    # Evaluation target (optional — if provided, evaluates against resolved policy)
    proposed_output: dict = {}


class Skill15Output(BaseSchema):
    """Output of SKILL 15 Creative Control Policy."""

    version: str = "1.0"
    status: str = "policy_ready"  # policy_ready | review_required | failed
    policy_stack_id: str = ""
    policy_stack_name: str = ""
    policy_event_id: str = ""

    # Constraint layers
    hard_constraints: list[Constraint] = []
    soft_constraints: list[Constraint] = []
    guidelines: list[Constraint] = []

    # Exploration
    exploration_policy: dict = {}
    exploration_bands: list[ExplorationBand] = []

    # Conflicts
    conflict_report: list[ConflictRecord] = []
    conflict_resolution_policy: dict = {}

    # Downstream exports
    downstream_export: DownstreamExport | None = None

    # Evaluation (populated when proposed_output is provided)
    evaluation_results: list[EvaluationResult] = []

    # Audit
    audit_trail: list[AuditEntry] = []
    review_items: list[str] = []
