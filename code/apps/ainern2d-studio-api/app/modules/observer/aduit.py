from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.pipeline_models import WorkflowEvent
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("observer.aduit")


class AuditLogger:
    """Create and query audit-trail entries stored as WorkflowEvent rows."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_action(
        self,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        detail: Optional[dict] = None,
    ) -> None:
        """Persist an audit entry as a WorkflowEvent with event_type ``audit.*``."""
        event = WorkflowEvent(
            id=f"we_{uuid4().hex[:12]}",
            event_type=f"audit.{action}",
            event_version="1",
            producer=actor,
            occurred_at=datetime.now(timezone.utc),
            payload_json={
                "actor": actor,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "detail": detail or {},
            },
        )
        self.db.add(event)
        self.db.flush()
        logger.info(
            "audit_logged | actor={} action={} resource={}/{}",
            actor, action, resource_type, resource_id,
        )

    def query_audit(
        self,
        run_id: Optional[str] = None,
        actor: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        """Query audit events, optionally filtered by run_id or actor."""
        q = (
            self.db.query(WorkflowEvent)
            .filter(WorkflowEvent.event_type.like("audit.%"))
        )
        if run_id is not None:
            q = q.filter(WorkflowEvent.run_id == run_id)
        if actor is not None:
            q = q.filter(WorkflowEvent.producer == actor)
        return q.order_by(WorkflowEvent.occurred_at.desc()).limit(limit).all()
