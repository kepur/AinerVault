from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.rag_models import RagDocument
from ainern2d_shared.schemas.entity import EntityPack

from .bybrid_search import HybridSearcher


@dataclass
class AssetCandidate:
    doc_id: str
    score: float
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AssetRetriever:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._searcher = HybridSearcher(db)

    def retrieve(
        self,
        query: str,
        entity_pack: EntityPack | None,
        collection_id: str,
        top_k: int = 5,
    ) -> list[AssetCandidate]:
        # Augment query with entity names for better recall
        augmented = query
        if entity_pack:
            names = " ".join(e.display_name for e in entity_pack.entities)
            augmented = f"{query} {names}"

        raw = self._searcher.search(augmented, collection_id, top_k=top_k)

        candidates: list[AssetCandidate] = []
        for item in raw:
            doc = self.db.get(RagDocument, item["doc_id"])
            content = item.get("content", "")
            if not content and doc:
                content = doc.content_text
            metadata = (doc.metadata_json or {}) if doc else {}
            candidates.append(
                AssetCandidate(
                    doc_id=item["doc_id"],
                    score=item["score"],
                    content=content,
                    metadata=metadata,
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_k]
