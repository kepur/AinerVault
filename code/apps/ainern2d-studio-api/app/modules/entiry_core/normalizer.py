from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.knowledge_models import EntityAlias
from ainern2d_shared.schemas.entity import EntityItem, EntityPack
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("entiry_core.normalizer")


class EntityNormalizer:
    """Deduplicate and merge entities within an EntityPack by alias matching."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize(self, entity_pack: EntityPack) -> EntityPack:
        """Deduplicate entities whose aliases overlap and merge confidence scores."""
        alias_to_items: dict[str, list[EntityItem]] = defaultdict(list)
        for item in entity_pack.entities:
            for alias in item.aliases:
                alias_to_items[alias.lower()].append(item)

        merged_ids: set[str] = set()
        result: list[EntityItem] = []

        for item in entity_pack.entities:
            if item.entity_id in merged_ids:
                continue

            # Collect cluster of items sharing any alias with this item.
            cluster: list[EntityItem] = [item]
            for alias in item.aliases:
                for other in alias_to_items[alias.lower()]:
                    if other.entity_id != item.entity_id and other.entity_id not in merged_ids:
                        cluster.append(other)

            merged = self._merge_cluster(cluster)
            for c in cluster:
                merged_ids.add(c.entity_id)
            result.append(merged)

        entity_pack = entity_pack.model_copy(update={"entities": result})
        logger.info(
            "normalize_done | pack_id={} before={} after={}",
            entity_pack.pack_id, len(alias_to_items), len(result),
        )
        return entity_pack

    def resolve_aliases(self, entity_id: str) -> list[str]:
        """Return all known aliases for *entity_id* from the database."""
        rows = (
            self.db.query(EntityAlias.alias)
            .filter(EntityAlias.entity_id == entity_id)
            .all()
        )
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_cluster(cluster: list[EntityItem]) -> EntityItem:
        """Merge a cluster of overlapping EntityItems into one."""
        primary = cluster[0]
        all_aliases: list[str] = []
        max_confidence = primary.confidence
        merged_attrs: dict = {}

        for item in cluster:
            for a in item.aliases:
                if a not in all_aliases:
                    all_aliases.append(a)
            if item.confidence > max_confidence:
                max_confidence = item.confidence
            merged_attrs.update(item.attributes)

        return EntityItem(
            entity_id=primary.entity_id,
            entity_type=primary.entity_type,
            display_name=primary.display_name,
            aliases=all_aliases,
            attributes=merged_attrs,
            confidence=max_confidence,
        )
