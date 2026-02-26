from __future__ import annotations

from typing import List, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.pipeline_models import WorkflowEvent
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("orchestrator.event_log")


class EventLogger:
    """Persists EventEnvelope instances as WorkflowEvent rows."""

    def __init__(self, db: Session):
        self.db = db

    def log(self, event: EventEnvelope) -> WorkflowEvent:
        """Convert an EventEnvelope to a WorkflowEvent row and persist it."""
        row = WorkflowEvent(
            id=event.event_id or f"we_{uuid4().hex[:12]}",
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            trace_id=event.trace_id,
            correlation_id=event.correlation_id,
            idempotency_key=event.idempotency_key,
            run_id=event.run_id,
            job_id=event.job_id,
            event_type=event.event_type,
            event_version=event.event_version,
            producer=event.producer,
            occurred_at=event.occurred_at,
            payload_json=event.payload,
        )
        self.db.add(row)
        self.db.flush()
        logger.info(
            "event_logged | event_id={} type={} run_id={}",
            row.id, row.event_type, row.run_id,
        )
        return row

    def list_by_run(
        self, run_id: str, limit: int = 200
    ) -> List[WorkflowEvent]:
        """Return recent workflow events for a given run, newest first."""
        stmt = (
            select(WorkflowEvent)
            .filter_by(run_id=run_id)
            .order_by(WorkflowEvent.created_at.desc())
            .limit(limit)
        )
        rows: Sequence[WorkflowEvent] = self.db.execute(stmt).scalars().all()
        return list(rows)
