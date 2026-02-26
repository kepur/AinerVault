from __future__ import annotations

import re
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import EntityType
from ainern2d_shared.ainer_db_models.knowledge_models import Entity, EntityAlias
from ainern2d_shared.schemas.entity import EntityItem, EntityPack
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("entiry_core.extractor")

# Lightweight regex patterns for stub extraction.
_PERSON_PATTERN = re.compile(r"[「「]([^」」]+)[」」]")
_QUOTED_PATTERN = re.compile(r"\u201c([^\u201d]+)\u201d")


class EntityExtractor:
    """Parse raw text to identify entities and persist Entity + EntityAlias rows."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        chapter_id: str,
        text: str,
        language: str = "zh-CN",
    ) -> EntityPack:
        """Extract entities from *text* and return an EntityPack.

        Current implementation uses simple regex heuristics.
        TODO: replace with LLM-based NER call via model_router.
        """
        raw_names = self._find_candidate_names(text)
        items: list[EntityItem] = []

        for name in raw_names:
            entity_id = f"ent_{uuid4().hex[:12]}"
            entity = Entity(
                id=entity_id,
                label=name,
                canonical_label=name,
                anchor_prompt=f"Entity extracted from chapter {chapter_id}",
                traits_json={},
            )
            alias = EntityAlias(
                id=f"ea_{uuid4().hex[:12]}",
                entity_id=entity_id,
                alias=name,
                locale=language,
            )
            self.db.add(entity)
            self.db.add(alias)

            items.append(
                EntityItem(
                    entity_id=entity_id,
                    entity_type=EntityType.person.value,
                    display_name=name,
                    aliases=[name],
                    attributes={},
                    confidence=0.5,
                )
            )

        self.db.flush()

        pack = EntityPack(
            pack_id=f"ep_{uuid4().hex[:12]}",
            run_id=chapter_id,
            language=language,
            entities=items,
        )
        logger.info(
            "extract_done | chapter_id={} entities={}",
            chapter_id, len(items),
        )
        return pack

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_candidate_names(self, text: str) -> list[str]:
        """Return deduplicated candidate entity names from *text*."""
        candidates: list[str] = []
        candidates.extend(_PERSON_PATTERN.findall(text))
        candidates.extend(_QUOTED_PATTERN.findall(text))
        # Deduplicate while preserving order.
        seen: set[str] = set()
        result: list[str] = []
        for c in candidates:
            c = c.strip()
            if c and c not in seen:
                seen.add(c)
                result.append(c)
        return result
