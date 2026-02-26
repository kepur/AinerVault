from __future__ import annotations

import random
from uuid import uuid4

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.rag_models import RagDocument, RagEmbedding

_EMBEDDING_DIM = 1536


class EmbeddingGenerator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def embed(
        self,
        doc_id: str,
        model_profile_id: str | None = None,
    ) -> RagEmbedding:
        doc = self.db.get(RagDocument, doc_id)
        if doc is None:
            raise LookupError(f"RagDocument id={doc_id} not found")

        # TODO: Replace with real embedding model call (e.g. OpenAI, BGE, etc.)
        vector = [random.gauss(0, 1) for _ in range(_EMBEDDING_DIM)]

        emb = RagEmbedding(
            id=f"emb_{uuid4().hex}",
            tenant_id=doc.tenant_id,
            project_id=doc.project_id,
            doc_id=doc_id,
            embedding_model_profile_id=model_profile_id,
            embedding_dim=_EMBEDDING_DIM,
            embedding=vector,
            is_primary=True,
        )
        self.db.add(emb)
        self.db.flush()
        return emb
