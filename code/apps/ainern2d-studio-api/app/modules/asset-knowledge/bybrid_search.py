from __future__ import annotations

import math
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.rag_models import RagDocument, RagEmbedding


class HybridSearcher:
    def __init__(self, db: Session) -> None:
        self.db = db

    def search(
        self,
        query: str,
        collection_id: str,
        top_k: int = 10,
    ) -> list[dict]:
        kw_results = self.keyword_search(query, collection_id, top_k=top_k * 2)
        vec_results = self.vector_search(query, collection_id, top_k=top_k * 2)
        return self.merge_results(kw_results, vec_results, top_k=top_k)

    def keyword_search(
        self,
        query: str,
        collection_id: str,
        top_k: int = 20,
    ) -> list[dict]:
        pattern = f"%{query}%"
        stmt = (
            select(RagDocument)
            .filter_by(collection_id=collection_id, deleted_at=None)
            .where(RagDocument.content_text.ilike(pattern))
            .limit(top_k)
        )
        docs: Sequence[RagDocument] = self.db.execute(stmt).scalars().all()
        results = []
        for doc in docs:
            text_lower = doc.content_text.lower()
            freq = text_lower.count(query.lower())
            score = min(1.0, freq / 10.0)
            results.append(
                {"doc_id": doc.id, "score": score, "source": "keyword", "content": doc.content_text}
            )
        return results

    def vector_search(
        self,
        query: str,
        collection_id: str,
        top_k: int = 20,
    ) -> list[dict]:
        """Stub vector search using cosine similarity.

        TODO: Replace with proper ANN index query (pgvector <=> operator).
        Currently loads embeddings and computes cosine distance in Python.
        """
        doc_stmt = (
            select(RagDocument.id)
            .filter_by(collection_id=collection_id, deleted_at=None)
        )
        doc_ids = [r for r in self.db.execute(doc_stmt).scalars().all()]
        if not doc_ids:
            return []

        emb_stmt = (
            select(RagEmbedding)
            .where(RagEmbedding.doc_id.in_(doc_ids))
            .where(RagEmbedding.is_primary.is_(True))
        )
        embeddings: Sequence[RagEmbedding] = self.db.execute(emb_stmt).scalars().all()

        # Stub query vector: hash-based deterministic pseudo-vector
        query_vec = self._pseudo_query_vector(query, dim=1536)

        scored = []
        for emb in embeddings:
            sim = self._cosine_similarity(query_vec, list(emb.embedding))
            scored.append(
                {"doc_id": emb.doc_id, "score": sim, "source": "vector", "content": ""}
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def merge_results(
        self,
        kw_results: list[dict],
        vec_results: list[dict],
        top_k: int = 10,
    ) -> list[dict]:
        merged: dict[str, dict] = {}
        for r in kw_results:
            doc_id = r["doc_id"]
            merged[doc_id] = {
                "doc_id": doc_id,
                "score": r["score"] * 0.4,
                "content": r.get("content", ""),
            }
        for r in vec_results:
            doc_id = r["doc_id"]
            if doc_id in merged:
                merged[doc_id]["score"] += r["score"] * 0.6
            else:
                merged[doc_id] = {
                    "doc_id": doc_id,
                    "score": r["score"] * 0.6,
                    "content": r.get("content", ""),
                }

        ranked = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return ranked[:top_k]

    @staticmethod
    def _pseudo_query_vector(query: str, dim: int) -> list[float]:
        """Deterministic pseudo-vector from query string for stub purposes."""
        import hashlib

        h = hashlib.sha256(query.encode()).digest()
        vec = []
        for i in range(dim):
            byte_val = h[i % len(h)]
            vec.append((byte_val / 255.0) * 2 - 1)
        return vec

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
