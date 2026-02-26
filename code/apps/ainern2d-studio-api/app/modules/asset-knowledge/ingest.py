from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Chapter
from ainern2d_shared.ainer_db_models.enum_models import RagScope, RagSourceType
from ainern2d_shared.ainer_db_models.rag_models import RagDocument


class RagIngestor:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ingest(
        self,
        collection_id: str,
        source_type: str,
        content: str,
        metadata: dict | None = None,
    ) -> RagDocument:
        doc = RagDocument(
            id=f"doc_{uuid4().hex}",
            tenant_id=metadata.get("tenant_id", "default") if metadata else "default",
            project_id=metadata.get("project_id", "default") if metadata else "default",
            collection_id=collection_id,
            scope=RagScope(metadata.get("scope", "novel")) if metadata else RagScope.novel,
            source_type=RagSourceType(source_type),
            source_id=metadata.get("source_id") if metadata else None,
            language_code=metadata.get("language_code") if metadata else None,
            title=metadata.get("title") if metadata else None,
            content_text=content,
            metadata_json=metadata,
        )
        self.db.add(doc)
        self.db.flush()
        return doc

    def ingest_chapter(self, collection_id: str, chapter_id: str) -> RagDocument:
        chapter = self.db.get(Chapter, chapter_id)
        if chapter is None:
            raise LookupError(f"Chapter id={chapter_id} not found")

        text = chapter.cleaned_text or chapter.raw_text
        metadata = {
            "tenant_id": chapter.tenant_id,
            "project_id": chapter.project_id,
            "scope": RagScope.chapter.value,
            "source_id": chapter_id,
            "language_code": chapter.language_code,
            "title": chapter.title or f"Chapter {chapter.chapter_no}",
        }
        return self.ingest(
            collection_id=collection_id,
            source_type=RagSourceType.chapter.value,
            content=text,
            metadata=metadata,
        )
