from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import GateDecision
from ainern2d_shared.ainer_db_models.governance_models import (
    CreativePolicyStack,
    GateEvalResult,
)
from ainern2d_shared.ainer_db_models.pipeline_models import WorkflowEvent
from ainern2d_shared.schemas.task import DispatchDecision
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("model_router.dispath_decision")


class DispatchDecisionAuditor:
    """Validate and audit DispatchDecision objects against policy constraints."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def audit(self, decision: DispatchDecision) -> GateEvalResult:
        """Evaluate *decision* against active policy stacks.

        TODO: load active CreativePolicyStack and run real constraint
        checks (cost ceiling, banned providers, etc.).
        """
        # Stub: pass all decisions through.
        result = GateEvalResult(
            id=f"ge_{uuid4().hex[:12]}",
            gate_decision=GateDecision.pass_,
            feedback_json={"detail": "stub_audit_passed"},
        )
        self.db.add(result)
        self.db.flush()
        logger.info(
            "audit_done | task_id={} decision={}",
            decision.task_id, result.gate_decision.value,
        )
        return result

    def log_decision(self, decision: DispatchDecision, run_id: str) -> None:
        """Persist the dispatch decision as a WorkflowEvent for the audit trail."""
        event = WorkflowEvent(
            id=f"we_{uuid4().hex[:12]}",
            run_id=run_id,
            event_type="dispatch.decision",
            event_version="1",
            producer="model_router",
            occurred_at=datetime.now(timezone.utc),
            payload_json={
                "task_id": decision.task_id,
                "route_id": decision.route_id,
                "worker_type": decision.worker_type,
                "model_profile_id": decision.model_profile_id,
                "fallback_chain": decision.fallback_chain,
                "cost_estimate": decision.cost_estimate,
            },
        )
        self.db.add(event)
        self.db.flush()
        logger.info(
            "decision_logged | run_id={} task_id={}",
            run_id, decision.task_id,
        )
