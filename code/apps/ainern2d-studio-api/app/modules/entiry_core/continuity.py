from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.knowledge_models import EntityState
from ainern2d_shared.schemas.entity import EntityPack
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("entiry_core.continuity")


class ContinuityChecker:
    """Verify that entity states remain consistent across chapters."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, run_id: str, entity_pack: EntityPack) -> dict:
        """Return a continuity report for the entities in *entity_pack*.

        The report maps each entity_id to a dict with keys:
        - ``consistent``: bool indicating whether the entity's state
          matches the previously recorded state.
        - ``detail``: human-readable explanation when inconsistent.
        """
        report: dict[str, dict] = {}
        for item in entity_pack.entities:
            prev_state: EntityState | None = (
                self.db.query(EntityState)
                .filter(EntityState.entity_id == item.entity_id)
                .order_by(EntityState.created_at.desc())
                .first()
            )
            if prev_state is None:
                report[item.entity_id] = {"consistent": True, "detail": "first_appearance"}
                continue

            prev: dict = prev_state.state_json or {}
            curr: dict = item.attributes or {}

            # Detect conflicting attribute values (same key, different non-None value)
            conflicts: list[str] = []
            for key in set(prev) & set(curr):
                old_val = prev[key]
                new_val = curr[key]
                if old_val is not None and new_val is not None and old_val != new_val:
                    conflicts.append(f"{key}: {old_val!r} → {new_val!r}")

            if conflicts:
                report[item.entity_id] = {
                    "consistent": False,
                    "detail": f"attribute_conflict: {'; '.join(conflicts)}",
                }
            else:
                report[item.entity_id] = {"consistent": True, "detail": "no_conflicts"}

        logger.info(
            "continuity_check | run_id={} entities={}",
            run_id, len(report),
        )
        return report

    def update_states(self, chapter_id: str, entity_pack: EntityPack) -> None:
        """Persist current entity states for the given chapter."""
        for item in entity_pack.entities:
            state = EntityState(
                id=f"es_{uuid4().hex[:12]}",
                entity_id=item.entity_id,
                chapter_id=chapter_id,
                state_json=item.attributes,
            )
            self.db.add(state)
        self.db.flush()
        logger.info(
            "states_updated | chapter_id={} count={}",
            chapter_id, len(entity_pack.entities),
        )
