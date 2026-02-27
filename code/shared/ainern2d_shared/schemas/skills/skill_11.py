"""SKILL 11: RAG KB Manager — Input/Output DTOs.

Full KB management contract per SKILL_11_RAG_KB_MANAGER.md.
Covers: KB CRUD, versioning, review workflow, deduplication,
quality validation, search index, import/export, feature flags.
"""
from __future__ import annotations

from typing import Any

from ainern2d_shared.schemas.base import BaseSchema
from ainern2d_shared.schemas.events import EventEnvelope


# ── Feature Flags ────────────────────────────────────────────────────────────


class Skill11FeatureFlags(BaseSchema):
    """Runtime feature toggles for KB management (§3.2)."""

    auto_publish: bool = False
    dedup_threshold: float = 0.85
    version_auto_increment: bool = True
    max_entries_per_type: int = 500
    enable_role_packs: bool = True
    enable_versioning: bool = True
    enable_review_workflow: bool = True
    enable_preview_search: bool = True


# ── Knowledge Item & Tags ────────────────────────────────────────────────────


class KBItemTags(BaseSchema):
    """Structured tag set for a knowledge item (§6.1)."""

    culture_pack: list[str] = []
    genre: list[str] = []
    motion_level: list[str] = []
    shot_type: list[str] = []
    era: list[str] = []
    style_mode: list[str] = []
    custom: list[str] = []


class KBItemSource(BaseSchema):
    """Provenance of a knowledge item."""

    type: str = "user_note"  # user_note | import | feedback_loop | url
    ref: str = "manual"
    url: str = ""


class KBEntry(BaseSchema):
    """Minimum knowledge item for bulk operations (§6.1)."""

    entry_id: str = ""
    role: str = ""  # director | cinematographer | gaffer | art_director | ...
    title: str = ""
    content_type: str = "rule"  # rule | checklist | template | case | counter_example
    content_markdown: str = ""
    entry_type: str = "entity_profile"  # entity_profile | culture_pack | style_guide | prompt_recipe | asset_catalog | glossary
    tags: KBItemTags = KBItemTags()
    flat_tags: list[str] = []
    strength: str = "soft_hint"  # hard_constraint | soft_hint
    status: str = "draft"  # draft | active | deprecated | archived
    visibility: str = "project_shared"  # personal | project_shared | org_public
    source: KBItemSource = KBItemSource()
    metadata: dict[str, Any] = {}
    embedding_status: str = "stale"  # stale | indexed | error
    version: str = "1.0"
    created_at: str = ""
    updated_at: str = ""


# ── Version & Diff ───────────────────────────────────────────────────────────


class KBVersionDiff(BaseSchema):
    """Difference summary between two KB versions."""

    added_ids: list[str] = []
    modified_ids: list[str] = []
    deprecated_ids: list[str] = []
    removed_ids: list[str] = []


class KBVersion(BaseSchema):
    """A frozen KB version snapshot (§6.2)."""

    kb_version_id: str = ""
    parent_version_id: str = ""
    version_label: str = ""
    release_notes: str = ""
    included_item_ids: list[str] = []
    deprecated_item_ids: list[str] = []
    diff: KBVersionDiff = KBVersionDiff()
    target_embedding_model: str = ""
    chunking_policy_id: str = ""
    content_hash: str = ""
    status: str = "draft"  # draft | published | rolled_back
    created_by: str = ""
    created_at: str = ""


# ── Review Workflow ──────────────────────────────────────────────────────────


class ReviewDecision(BaseSchema):
    """Result of a review step (§K2)."""

    review_id: str = ""
    item_id: str = ""
    reviewer: str = ""
    decision: str = "pending"  # pending | approved | rejected | needs_edit
    reason: str = ""
    reviewed_at: str = ""


class ReviewRequiredItem(BaseSchema):
    """Items flagged for review before publishing."""

    item_id: str = ""
    reason: str = ""
    severity: str = "medium"  # low | medium | high


# ── Deduplication ────────────────────────────────────────────────────────────


class DedupResult(BaseSchema):
    """Result of deduplication for a pair of entries."""

    kept_id: str = ""
    merged_id: str = ""
    similarity: float = 0.0
    action: str = "merged"  # merged | flagged | skipped


# ── Quality Validation ───────────────────────────────────────────────────────


class QualityIssue(BaseSchema):
    """A quality problem found during validation."""

    item_id: str = ""
    issue_type: str = ""  # missing_field | cross_ref_broken | duplicate_title | weak_content
    message: str = ""
    severity: str = "warning"  # warning | error


# ── Search Index ─────────────────────────────────────────────────────────────


class SearchIndexStats(BaseSchema):
    """Statistics of the search-ready indices."""

    tag_index_size: int = 0
    type_index_size: int = 0
    culture_index_size: int = 0
    role_index_size: int = 0
    total_indexed: int = 0


# ── Coverage Stats ───────────────────────────────────────────────────────────


class CoverageStatEntry(BaseSchema):
    """Coverage count for a domain or culture."""

    key: str = ""
    count: int = 0
    active_count: int = 0


# ── KB Manifest ──────────────────────────────────────────────────────────────


class KBManifest(BaseSchema):
    """Full KB release manifest (§4.2)."""

    kb_id: str = ""
    kb_version_id: str = ""
    release_notes: str = ""
    entry_count: int = 0
    included_item_ids: list[str] = []
    deprecated_item_ids: list[str] = []
    version_history: list[KBVersion] = []
    coverage_by_domain: list[CoverageStatEntry] = []
    coverage_by_culture: list[CoverageStatEntry] = []
    coverage_by_type: list[CoverageStatEntry] = []
    target_embedding_model: str = ""
    chunking_policy_id: str = ""
    content_hash: str = ""
    active_recipe_set_id: str = ""
    created_at: str = ""


# ── Preview Search ───────────────────────────────────────────────────────────


class PreviewSearchQuery(BaseSchema):
    """User query for KB preview search (§K5)."""

    query_text: str = ""
    role_filter: list[str] = []
    culture_filter: list[str] = []
    genre_filter: list[str] = []
    strength_filter: str = ""  # "" | hard_constraint | soft_hint
    top_k: int = 10


class PreviewSearchHit(BaseSchema):
    """A single search result item."""

    item_id: str = ""
    title: str = ""
    role: str = ""
    score: float = 0.0
    snippet: str = ""
    tags: KBItemTags = KBItemTags()
    strength: str = ""
    version: str = ""
    conflict_flags: list[str] = []


# ── Summary ──────────────────────────────────────────────────────────────────


class KBManagerSummary(BaseSchema):
    """Execution summary for a KB management operation."""

    total_entries: int = 0
    active_entries: int = 0
    draft_entries: int = 0
    deprecated_entries: int = 0
    dedup_actions: int = 0
    quality_issues_found: int = 0
    review_required_count: int = 0
    index_rebuild: bool = False


# ── Import / Export ──────────────────────────────────────────────────────────


class BulkImportItem(BaseSchema):
    """A single item in a bulk import payload."""

    entry_id: str = ""
    role: str = ""
    title: str = ""
    content_type: str = "rule"
    content_markdown: str = ""
    entry_type: str = "entity_profile"
    tags: KBItemTags = KBItemTags()
    flat_tags: list[str] = []
    strength: str = "soft_hint"
    status: str = "draft"
    visibility: str = "project_shared"
    source: KBItemSource = KBItemSource()
    metadata: dict[str, Any] = {}


# ── Input / Output ───────────────────────────────────────────────────────────


class Skill11Input(BaseSchema):
    """RAG KB Manager inputs (§3)."""

    # Action control
    kb_id: str = ""
    action: str = "sync"  # sync | create | update | delete | publish | rollback | search | import | export

    # Entry payloads (for create / update / delete)
    entries: list[KBEntry] = []
    delete_entry_ids: list[str] = []

    # Version control (for publish / rollback)
    version_label: str = ""
    release_notes: str = ""
    rollback_target_version_id: str = ""
    rollback_reason: str = ""

    # Preview search
    search_query: PreviewSearchQuery | None = None

    # Bulk import
    import_items: list[BulkImportItem] = []

    # Review decisions (external reviewer submits)
    review_decisions: list[ReviewDecision] = []

    # Config
    target_embedding_model: str = ""
    chunking_policy_id: str = ""
    feature_flags: Skill11FeatureFlags = Skill11FeatureFlags()


class Skill11Output(BaseSchema):
    """RAG KB Manager output contract (§4)."""

    # Core identifiers (§11.1)
    kb_id: str = ""
    kb_version_id: str = ""
    release_manifest_hash: str = ""
    active_recipe_set_id: str = ""
    approval_ticket_id: str = ""

    # State machine terminal state
    status: str = "READY"  # READY | REVIEW_REQUIRED | FAILED

    # Manifest (for publish / sync / export)
    manifest: KBManifest | None = None

    # Version info
    current_version: KBVersion | None = None
    version_history: list[KBVersion] = []

    # Entry results
    entries: list[KBEntry] = []
    entry_count: int = 0

    # Review
    review_required_items: list[ReviewRequiredItem] = []
    review_decisions: list[ReviewDecision] = []

    # Dedup
    dedup_results: list[DedupResult] = []

    # Quality
    quality_issues: list[QualityIssue] = []

    # Search
    search_results: list[PreviewSearchHit] = []

    # Index stats
    index_stats: SearchIndexStats = SearchIndexStats()

    # Summary
    summary: KBManagerSummary = KBManagerSummary()

    # Events emitted (§11.2)
    events_emitted: list[str] = []
    event_envelopes: list[EventEnvelope] = []

    # Warnings
    warnings: list[str] = []
