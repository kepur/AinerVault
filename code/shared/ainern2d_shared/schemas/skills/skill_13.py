"""SKILL 13: Feedback Evolution Loop — Input/Output DTOs.

Implements the full feedback → proposal → review → release evolution loop.
Ref: SKILL_13_FEEDBACK_EVOLUTION_LOOP.md
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from ainern2d_shared.schemas.base import BaseSchema
from ainern2d_shared.schemas.events import EventEnvelope


# ── Enums ─────────────────────────────────────────────────────────────────────

class FeedbackIssueCategory(str, Enum):
    """Feedback taxonomy — maps to MD §4."""
    CINEMATOGRAPHY_CAMERA_MOVE = "cinematography_camera_move"
    LIGHTING_GAFFER = "lighting_gaffer"
    ART_STYLE = "art_style"
    CONTINUITY_SCRIPT_SUPERVISOR = "continuity_script_supervisor"
    MOTION_READABILITY = "motion_readability"
    CULTURE_MISMATCH = "culture_mismatch"
    CHARACTER_INCONSISTENCY = "character_inconsistency"
    PROP_INCONSISTENCY = "prop_inconsistency"
    PACING_EDITING = "pacing_editing"
    PROMPT_QUALITY = "prompt_quality"
    MODEL_FAILURE = "model_failure"


class FeedbackSource(str, Enum):
    USER_EXPLICIT = "user_explicit"
    CRITIC_AUTO = "critic_auto"
    AB_TEST = "ab_test"
    SYSTEM_METRIC = "system_metric"


class ActionTaken(str, Enum):
    RUN_PATCH = "run_patch"
    PROPOSAL_CREATED = "proposal_created"
    IGNORED = "ignored"
    NEEDS_REVIEW = "needs_review"


class ProposalStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    MERGED = "merged"
    REJECTED = "rejected"


class ProposalStrength(str, Enum):
    HARD_CONSTRAINT = "hard_constraint"
    SOFT_CONSTRAINT = "soft_constraint"


class ProposalContentType(str, Enum):
    RULE = "rule"
    CHECKLIST = "checklist"
    TEMPLATE = "template"
    ANTI_PATTERN = "anti_pattern"


class ProposalVisibility(str, Enum):
    PRIVATE = "private"
    PROJECT_SHARED = "project_shared"


class Skill13State(str, Enum):
    """State machine — MD §6."""
    INIT = "INIT"
    CAPTURING_FEEDBACK = "CAPTURING_FEEDBACK"
    DECIDING_ACTION = "DECIDING_ACTION"
    BUILDING_RUN_PATCH = "BUILDING_RUN_PATCH"
    GENERATING_PROPOSAL = "GENERATING_PROPOSAL"
    REVIEWING_PROPOSAL = "REVIEWING_PROPOSAL"
    APPLYING_TO_KB = "APPLYING_TO_KB"
    RELEASING_VERSION = "RELEASING_VERSION"
    EMBEDDING_BUILDING = "EMBEDDING_BUILDING"
    EVALUATING_IMPROVEMENT = "EVALUATING_IMPROVEMENT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ── Sub-models ────────────────────────────────────────────────────────────────

class RunContext(BaseSchema):
    """§2.1 run_context."""
    run_id: str = ""
    task_id: str = ""
    kb_version_id: str = ""
    model_info: dict = {}


class ShotResultContext(BaseSchema):
    """§2.1 shot_result_context."""
    shot_id: str = ""
    microshot_id: str = ""
    prompts_used: list[str] = []
    assets_used: list[str] = []
    render_plan_used: dict = {}


class UserFeedback(BaseSchema):
    """§2.1 user_feedback."""
    rating: int = 0  # 1-5
    issues: list[str] = []  # FeedbackIssueCategory values
    free_text: str = ""


class AutoDiagnostics(BaseSchema):
    """§2.2 auto_diagnostics."""
    detected_failures: list[str] = []
    diagnostics_detail: dict = {}


class FeatureFlags(BaseSchema):
    """§2.2 feature_flags + §10 feature flags."""
    enable_proposal_autogeneration: bool = True
    enable_role_auto_routing: bool = True
    enable_review_gate: bool = True
    enable_auto_tagging: bool = True
    auto_merge_threshold: float = 0.9
    regression_test_enabled: bool = True
    max_pending_rules: int = 50
    feedback_retention_days: int = 90


class UserPreferences(BaseSchema):
    """§2.2 user_preferences."""
    allow_shared_kb_write: bool = False


class ImpactScore(BaseSchema):
    """Impact scoring per feedback item."""
    frequency: int = 1
    severity: float = 0.0  # 0.0-1.0
    user_priority: int = 0
    affected_skill_count: int = 0
    composite_score: float = 0.0


class FeedbackEvent(BaseSchema):
    """§7.1 feedback_event — one recorded feedback item."""
    version: str = "1.0"
    feedback_event_id: str = ""
    run_id: str = ""
    kb_version_id: str = ""
    shot_id: str = ""
    rating: int = 0
    issues: list[str] = []
    free_text: str = ""
    source: str = "user_explicit"  # FeedbackSource value
    impact: ImpactScore | None = None
    created_at: str = ""


class SuggestedTags(BaseSchema):
    """Structured tags for a proposal."""
    culture_pack: list[str] = []
    genre: list[str] = []
    motion_level: list[str] = []
    shot_type: list[str] = []


class ImprovementProposal(BaseSchema):
    """§7.2 improvement_proposal — full proposal for KB evolution."""
    version: str = "1.0"
    proposal_id: str = ""
    feedback_event_id: str = ""
    suggested_role: str = ""
    suggested_strength: str = "soft_constraint"  # ProposalStrength
    suggested_tags: SuggestedTags = SuggestedTags()
    suggested_content_type: str = "rule"  # ProposalContentType
    suggested_title: str = ""
    suggested_knowledge_content: str = ""
    status: str = "pending_review"  # ProposalStatus
    visibility: str = "project_shared"  # ProposalVisibility
    target_skill: str = ""
    evolution_version: str = ""


class RunPatchRecord(BaseSchema):
    """§F3 run-level patch — only affects the current run."""
    patch_id: str = ""
    run_id: str = ""
    prompt_patch: str = ""
    negative_constraints: list[str] = []
    param_adjustments: dict = {}
    feedback_event_id: str = ""


class KBUpdateProposal(BaseSchema):
    """Specific KB entry update to send to SKILL 11."""
    kb_id: str = ""
    entry_id: str = ""
    action: str = "create"  # create | update
    content: str = ""
    entry_type: str = "rule"
    tags: list[str] = []
    metadata: dict = {}
    source_proposal_id: str = ""


class RegressionTestResult(BaseSchema):
    """Regression test result for a proposed rule."""
    test_id: str = ""
    proposal_id: str = ""
    historical_case_id: str = ""
    previous_score: float = 0.0
    new_score: float = 0.0
    passed: bool = True
    detail: str = ""


class EvolutionRecommendation(BaseSchema):
    """Per-skill evolution recommendation."""
    target_skill: str = ""
    recommendation: str = ""
    priority: int = 0
    source_proposal_ids: list[str] = []


class FeedbackAggregation(BaseSchema):
    """Aggregated feedback pattern."""
    issue_category: str = ""
    count: int = 0
    avg_rating: float = 0.0
    representative_texts: list[str] = []
    trend: str = "stable"  # rising | stable | declining


class EvolutionHistory(BaseSchema):
    """Versioned evolution record."""
    evolution_id: str = ""
    version_tag: str = ""
    proposals_merged: list[str] = []
    kb_version_before: str = ""
    kb_version_after: str = ""
    regression_passed: bool = True
    created_at: str = ""


# ── Top-level Input / Output ─────────────────────────────────────────────────

class Skill13Input(BaseSchema):
    """Full input for SKILL 13 — Feedback Evolution Loop."""
    run_context: RunContext = RunContext()
    shot_result_context: ShotResultContext = ShotResultContext()
    user_feedback: UserFeedback = UserFeedback()
    auto_diagnostics: AutoDiagnostics | None = None
    feature_flags: FeatureFlags = FeatureFlags()
    user_preferences: UserPreferences = UserPreferences()
    kb_manager_config: dict = {}  # pass-through to SKILL 11
    embedding_pipeline_config: dict = {}  # pass-through to SKILL 12


class Skill13Output(BaseSchema):
    """Full output for SKILL 13 — Feedback Evolution Loop."""
    # Core outputs
    feedback_event: FeedbackEvent = FeedbackEvent()
    action_taken: str = "ignored"  # ActionTaken value
    run_patch: RunPatchRecord | None = None
    proposal: ImprovementProposal | None = None

    # Aggregation & analysis
    feedback_aggregations: list[FeedbackAggregation] = []
    impact_score: ImpactScore = ImpactScore()

    # Evolution outputs
    kb_update_proposals: list[KBUpdateProposal] = []
    regression_results: list[RegressionTestResult] = []
    evolution_recommendations: list[EvolutionRecommendation] = []
    evolution_history: EvolutionHistory | None = None

    # Status
    state: str = "COMPLETED"  # Skill13State value
    kb_evolution_triggered: bool = False
    new_kb_version_id: str = ""
    status: str = "completed"
    events_emitted: list[str] = []
    event_envelopes: list[EventEnvelope] = []
