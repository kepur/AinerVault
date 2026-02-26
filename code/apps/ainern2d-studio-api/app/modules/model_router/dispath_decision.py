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

        Checks applied (in order):
        1. Cost ceiling — reject if decision.cost_estimate > stack_json["cost_ceiling"]
        2. Banned providers — reject if decision.worker_type in stack_json["banned_providers"]
        3. Required worker types — reject if stack_json["required_worker_types"] set and
           decision.worker_type not in it
        """
        active_stacks: list[CreativePolicyStack] = (
            self.db.query(CreativePolicyStack)
            .filter(CreativePolicyStack.status == "active")
            .all()
        )

        gate = GateDecision.pass_
        feedback: dict = {"detail": "all_policy_checks_passed", "violations": []}

        for stack in active_stacks:
            spec: dict = stack.stack_json or {}

            cost_ceiling = spec.get("cost_ceiling")
            if cost_ceiling is not None and decision.cost_estimate > float(cost_ceiling):
                gate = GateDecision.reject
                feedback["violations"].append(
                    f"cost_ceiling_exceeded: {decision.cost_estimate:.4f} > {cost_ceiling}"
                )

            banned: list = spec.get("banned_providers", [])
            if decision.worker_type in banned or decision.model_profile_id in banned:
                gate = GateDecision.reject
                feedback["violations"].append(
                    f"banned_provider: {decision.worker_type}"
                )

            required: list = spec.get("required_worker_types", [])
            if required and decision.worker_type not in required:
                gate = GateDecision.reject
                feedback["violations"].append(
                    f"worker_type_not_allowed: {decision.worker_type} not in {required}"
                )

            if gate == GateDecision.reject:
                feedback["detail"] = f"rejected_by_policy_stack: {stack.name}"
                break

        result = GateEvalResult(
            id=f"ge_{uuid4().hex[:12]}",
            gate_decision=gate,
            feedback_json=feedback,
        )
        self.db.add(result)
        self.db.flush()
        logger.info(
            "audit_done | task_id={} decision={} violations={}",
            decision.task_id, result.gate_decision.value, len(feedback.get("violations", [])),
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
