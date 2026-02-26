from __future__ import annotations

import asyncio
import hashlib
from uuid import uuid4

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.rag_models import RagDocument, RagEmbedding

_EMBEDDING_DIM = 1536
_OPENAI_EMBED_MODEL = "text-embedding-3-small"


def _hash_vector(text: str, dim: int = _EMBEDDING_DIM) -> list[float]:
    """Deterministic pseudo-vector from text hash (fallback when no API key)."""
    h = hashlib.sha256(text.encode()).digest()
    return [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(dim)]


async def _embed_openai(text: str, api_key: str, base_url: str | None = None) -> list[float]:
    """Call OpenAI embeddings API; returns a list[float] of length _EMBEDDING_DIM."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise RuntimeError("openai SDK not installed")
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncOpenAI(**kwargs)
    response = await client.embeddings.create(
        model=_OPENAI_EMBED_MODEL,
        input=text,
    )
    return response.data[0].embedding


class EmbeddingGenerator:
    def __init__(self, db: Session, api_key: str = "", base_url: str | None = None) -> None:
        self.db = db
        self._api_key = api_key
        self._base_url = base_url

    def embed(
        self,
        doc_id: str,
        model_profile_id: str | None = None,
    ) -> RagEmbedding:
        doc = self.db.get(RagDocument, doc_id)
        if doc is None:
            raise LookupError(f"RagDocument id={doc_id} not found")

        if self._api_key:
            # Run async embed in a new event loop if needed
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(
                            asyncio.run,
                            _embed_openai(doc.content_text or "", self._api_key, self._base_url),
                        )
                        vector = future.result()
                else:
                    vector = loop.run_until_complete(
                        _embed_openai(doc.content_text or "", self._api_key, self._base_url)
                    )
            except Exception:
                vector = _hash_vector(doc.content_text or "")
        else:
            vector = _hash_vector(doc.content_text or "")

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
