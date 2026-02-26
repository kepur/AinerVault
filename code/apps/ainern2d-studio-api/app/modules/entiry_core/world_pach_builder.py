from __future__ import annotations

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.knowledge_models import (
    Entity,
    EntityState,
    Relationship,
)
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("entiry_core.world_pach_builder")


class WorldPatchBuilder:
    """Aggregate entity states and relationships into a world-patch dict
    that downstream planners can consume."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, run_id: str, chapter_id: str) -> dict:
        """Build and return a world patch for a given chapter.

        The patch contains:
        - ``entities``: list of entity dicts with latest state.
        - ``relationships``: list of relationship dicts.
        """
        states = (
            self.db.query(EntityState)
            .filter(EntityState.chapter_id == chapter_id)
            .all()
        )
        entity_ids = [s.entity_id for s in states]

        entities_data: list[dict] = []
        for s in states:
            ent: Entity | None = self.db.get(Entity, s.entity_id)
            entities_data.append({
                "entity_id": s.entity_id,
                "label": ent.label if ent else None,
                "state": s.state_json,
            })

        rels = (
            self.db.query(Relationship)
            .filter(
                Relationship.subject_entity_id.in_(entity_ids)
                | Relationship.object_entity_id.in_(entity_ids)
            )
            .all()
        )
        relationships_data = [
            {
                "subject": r.subject_entity_id,
                "object": r.object_entity_id,
                "relation": r.relation,
                "confidence": r.confidence,
            }
            for r in rels
        ]

        patch = {
            "run_id": run_id,
            "chapter_id": chapter_id,
            "entities": entities_data,
            "relationships": relationships_data,
        }
        logger.info(
            "world_patch_built | run_id={} chapter_id={} ents={} rels={}",
            run_id, chapter_id, len(entities_data), len(relationships_data),
        )
        return patch

    def get_entity_graph(self, novel_id: str) -> list[Relationship]:
        """Return all entity relationships for a novel.

        TODO: filter by novel_id once Entity carries a novel FK.
        Currently returns all relationships as a placeholder.
        """
        return self.db.query(Relationship).all()
