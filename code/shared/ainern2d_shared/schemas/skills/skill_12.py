"""SKILL 12: RAG Pipeline & Embedding — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class ChunkConfig(BaseSchema):
    chunk_size: int = 512
    chunk_overlap: int = 64
    strategy: str = "recursive"  # recursive | sentence | fixed


class EmbeddingQualityReport(BaseSchema):
    total_chunks: int = 0
    embedded_chunks: int = 0
    coverage_ratio: float = 0.0
    fragmentation_ratio: float = 0.0


class Skill12Input(BaseSchema):
    kb_id: str
    version_id: str
    chunk_config: ChunkConfig = ChunkConfig()
    embedding_model: str = "text-embedding-3-small"


class Skill12Output(BaseSchema):
    index_id: str = ""
    total_vectors: int = 0
    quality_report: EmbeddingQualityReport = EmbeddingQualityReport()
    status: str = "index_ready"
