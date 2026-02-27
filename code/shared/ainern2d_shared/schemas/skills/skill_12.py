"""SKILL 12: RAG Pipeline & Embedding — Input/Output DTOs.

Covers the full pipeline: chunk → enrich → embed → index → validate → report.
State machine: INIT → CHUNKING → ENRICHING → EMBEDDING → INDEXING
              → VALIDATING → REPORTING → READY | FAILED
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from ainern2d_shared.schemas.base import BaseSchema
from ainern2d_shared.schemas.events import EventEnvelope


# ── Enums ─────────────────────────────────────────────────────────

class ChunkingStrategy(str, Enum):
    FIXED_WINDOW = "fixed_window"
    SEMANTIC = "semantic"
    ENTITY_AWARE = "entity_aware"
    HYBRID = "hybrid"


class IndexType(str, Enum):
    HNSW = "hnsw"
    IVF = "ivf"
    FLAT = "flat"


class PipelineStage(str, Enum):
    INIT = "INIT"
    CHUNKING = "CHUNKING"
    ENRICHING = "ENRICHING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    VALIDATING = "VALIDATING"
    REPORTING = "REPORTING"
    READY = "READY"
    FAILED = "FAILED"


class ContentType(str, Enum):
    RULE = "rule"
    CHECKLIST = "checklist"
    TEMPLATE = "template"
    LONG_DOC = "long_doc"
    ANTI_PATTERN = "anti_pattern"


class Strength(str, Enum):
    HARD_CONSTRAINT = "hard_constraint"
    SOFT_PREFERENCE = "soft_preference"


class ItemStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


# ── Sub-configs ───────────────────────────────────────────────────

class ChunkConfig(BaseSchema):
    """Chunking policy configuration."""
    strategy: ChunkingStrategy = ChunkingStrategy.FIXED_WINDOW
    chunk_size: int = Field(512, ge=64, le=4096, description="Target tokens per chunk")
    chunk_overlap: int = Field(64, ge=0, le=512, description="Overlap tokens between chunks")
    semantic_boundary: str = Field(
        "paragraph", description="Boundary type for semantic strategy: paragraph | section"
    )
    entity_window_tokens: int = Field(
        200, ge=50, le=1000,
        description="Window size around entity mentions for entity_aware strategy",
    )
    min_chunk_tokens: int = Field(32, ge=1, description="Drop chunks shorter than this")
    max_chunk_tokens: int = Field(2048, ge=64, description="Force-split chunks longer than this")


class EmbeddingModelConfig(BaseSchema):
    """Embedding model selection and dimension config."""
    model_name: str = "text-embedding-3-small"
    embedding_dim: int = Field(384, description="Vector dimensions: 384 | 768 | 1024")
    batch_size: int = Field(64, ge=1, le=512, description="Chunks per embedding batch")
    is_primary: bool = True
    embedding_model_profile_id: str = ""


class IndexConfig(BaseSchema):
    """Vector index build parameters."""
    index_type: IndexType = IndexType.HNSW
    # HNSW params
    ef_construction: int = Field(200, ge=16, le=800)
    m_parameter: int = Field(16, ge=4, le=128, description="HNSW M parameter")
    ef_search: int = Field(64, ge=16, le=512)
    # IVF params
    nlist: int = Field(128, ge=1, le=65536, description="IVF cluster count")
    nprobe: int = Field(16, ge=1, le=512, description="IVF probe count at search time")


class VectorStoreConfig(BaseSchema):
    """pgvector-compatible store configuration."""
    distance_metric: str = Field("cosine", description="cosine | l2 | inner_product")
    partition_by_version: bool = True
    table_prefix: str = "kb_vectors"


class FeatureFlags(BaseSchema):
    """Runtime feature toggles for the RAG pipeline."""
    chunking_strategy: ChunkingStrategy = ChunkingStrategy.FIXED_WINDOW
    embedding_model: str = "text-embedding-3-small"
    index_type: IndexType = IndexType.HNSW
    enable_reranking: bool = True
    hybrid_search_alpha: float = Field(
        0.7, ge=0.0, le=1.0,
        description="Weight for semantic vs keyword (BM25). 1.0 = pure semantic",
    )
    enable_semantic_chunking: bool = False
    enable_dedup: bool = True
    enable_eval_suite: bool = True
    enable_conflict_scan: bool = True
    enable_incremental: bool = False


# ── Knowledge item & chunk models ─────────────────────────────────

class KnowledgeItem(BaseSchema):
    """A single knowledge entry from kb_release_manifest."""
    item_id: str
    content: str
    content_type: ContentType = ContentType.LONG_DOC
    role: str = ""
    tags: list[str] = Field(default_factory=list)
    strength: Strength = Strength.SOFT_PREFERENCE
    status: ItemStatus = ItemStatus.ACTIVE
    locale: str = "en"
    culture_pack: str = ""
    source: str = ""


class ChunkMetadata(BaseSchema):
    """Per-chunk enrichment metadata (§ chunk metadata enrichment)."""
    chunk_id: str = ""
    source_entry_id: str = ""
    kb_version_id: str = ""
    knowledge_item_id: str = ""
    role: str = ""
    tags: list[str] = Field(default_factory=list)
    strength: Strength = Strength.SOFT_PREFERENCE
    status: ItemStatus = ItemStatus.ACTIVE
    content_type: ContentType = ContentType.LONG_DOC
    source: str = ""
    entity_mentions: list[str] = Field(default_factory=list)
    culture_tags: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    importance_score: float = Field(0.5, ge=0.0, le=1.0)
    created_at: str = ""
    updated_at: str = ""


class Chunk(BaseSchema):
    """A text chunk with metadata."""
    chunk_id: str = ""
    chunk_text: str = ""
    token_count: int = 0
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)


# ── Retrieval models ──────────────────────────────────────────────

class RetrievalQuery(BaseSchema):
    """A single retrieval request."""
    query_text: str
    top_k: int = Field(8, ge=1, le=100)
    role_filter: list[str] = Field(default_factory=list)
    tag_filter: list[str] = Field(default_factory=list)
    locale_filter: str = ""
    strength_filter: Strength | None = None
    enable_reranking: bool = True
    hybrid_alpha: float = Field(0.7, ge=0.0, le=1.0)


class RetrievalResult(BaseSchema):
    """A single retrieval hit."""
    chunk_id: str = ""
    chunk_text: str = ""
    score: float = 0.0
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    rerank_score: float = 0.0
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)


class RetrievalResponse(BaseSchema):
    """Full retrieval pipeline result."""
    query_text: str = ""
    results: list[RetrievalResult] = Field(default_factory=list)
    total_candidates: int = 0
    filtered_count: int = 0
    latency_ms: float = 0.0
    conflict_candidates: list[RetrievalResult] = Field(default_factory=list)


# ── Eval / quality ────────────────────────────────────────────────

class EmbeddingQualityReport(BaseSchema):
    """Quality metrics for the embedding pipeline."""
    total_chunks: int = 0
    embedded_chunks: int = 0
    coverage_ratio: float = 0.0
    avg_chunk_quality: float = 0.0
    duplicate_chunk_ratio: float = 0.0
    orphan_entity_ratio: float = 0.0
    avg_chunk_chars: int = 0
    avg_chunk_tokens: int = 0
    min_chunk_tokens: int = 0
    max_chunk_tokens: int = 0


class EvalMetrics(BaseSchema):
    """Evaluation suite results (§6 P6)."""
    enabled: bool = False
    preview_queries: int = 0
    recall_at_k: float = 0.0
    constraint_conflict_rate: float = 0.0
    redundancy_rate: float = 0.0
    avg_latency_ms: float = 0.0
    recommendation: str = "review_required"  # promote_to_active | review_required | rollback


class IndexMetadata(BaseSchema):
    """Index build output metadata."""
    index_id: str = ""
    index_type: IndexType = IndexType.HNSW
    index_version: int = 1
    total_vectors: int = 0
    dimensions: int = 384
    build_time_sec: float = 0.0
    params: dict[str, Any] = Field(default_factory=dict)


class IncrementalIndexDelta(BaseSchema):
    """Tracks incremental changes without full rebuild."""
    added_chunk_ids: list[str] = Field(default_factory=list)
    removed_chunk_ids: list[str] = Field(default_factory=list)
    index_version_before: int = 0
    index_version_after: int = 0


# ── Pipeline stage tracking ───────────────────────────────────────

class StageRecord(BaseSchema):
    """Tracks one pipeline stage execution."""
    stage: PipelineStage = PipelineStage.INIT
    started_at: str = ""
    completed_at: str = ""
    duration_sec: float = 0.0
    items_processed: int = 0
    error: str | None = None


# ── Input / Output ────────────────────────────────────────────────

class Skill12Input(BaseSchema):
    """Full input for the RAG pipeline skill."""
    # Required
    kb_id: str
    kb_version_id: str
    chunking_policy_id: str = "CHUNK_POLICY_V1"
    knowledge_items: list[KnowledgeItem] = Field(default_factory=list)
    embedding_model_config: EmbeddingModelConfig = Field(default_factory=EmbeddingModelConfig)
    vector_store_config: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    index_config: IndexConfig = Field(default_factory=IndexConfig)
    chunk_config: ChunkConfig = Field(default_factory=ChunkConfig)

    # Optional
    preview_queries: list[str] = Field(default_factory=list)
    role_recipes: list[dict[str, Any]] = Field(default_factory=list)
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)

    # Incremental indexing
    incremental: bool = False
    previous_index_id: str = ""
    added_item_ids: list[str] = Field(default_factory=list)
    removed_item_ids: list[str] = Field(default_factory=list)


class Skill12Output(BaseSchema):
    """Output contract matching §8 of the spec.

    Example::
        {
          "version": "1.0",
          "kb_version_id": "KB_V1_20260226_001",
          "build_id": "KB_BUILD_0001",
          "status": "index_ready",
          ...
        }
    """
    version: str = "1.0"
    kb_version_id: str = ""
    build_id: str = ""
    status: str = "index_ready"
    chunking_policy_id: str = ""
    embedding_model: str = ""
    stats: EmbeddingQualityReport = Field(default_factory=EmbeddingQualityReport)
    eval: EvalMetrics = Field(default_factory=EvalMetrics)
    index_metadata: IndexMetadata = Field(default_factory=IndexMetadata)
    incremental_delta: IncrementalIndexDelta | None = None
    stage_log: list[StageRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    review_required_items: list[str] = Field(default_factory=list)
    chunks: list[Chunk] = Field(default_factory=list)
    promote_gate_passed: bool = False
    events_emitted: list[str] = Field(default_factory=list)
    event_envelopes: list[EventEnvelope] = Field(default_factory=list)
