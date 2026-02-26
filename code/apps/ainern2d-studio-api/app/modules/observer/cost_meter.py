from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.provider_models import CostLedger
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("observer.cost_meter")


class CostMeter:
    """Record and aggregate cost events attached to pipeline runs."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_cost(
        self,
        run_id: str,
        job_id: str,
        cost_type: str,
        amount: float,
        currency: str = "USD",
    ) -> None:
        """Persist a single cost event in the CostLedger."""
        entry = CostLedger(
            id=f"cl_{uuid4().hex[:12]}",
            run_id=run_id,
            job_id=job_id,
            metric_json={
                "cost_type": cost_type,
                "amount": amount,
                "currency": currency,
            },
        )
        self.db.add(entry)
        self.db.flush()
        logger.info(
            "cost_recorded | run_id={} job_id={} type={} amount={}",
            run_id, job_id, cost_type, amount,
        )

    def get_run_cost(self, run_id: str) -> float:
        """Sum all recorded costs for a given run."""
        rows = (
            self.db.query(CostLedger)
            .filter(CostLedger.run_id == run_id)
            .all()
        )
        total = sum(
            (r.metric_json or {}).get("amount", 0.0) for r in rows
        )
        return total

    def get_project_cost(self, tenant_id: str, project_id: str) -> float:
        """Sum all recorded costs for a tenant/project pair.

        Requires CostLedger rows to carry tenant_id/project_id via
        StandardColumnsMixin.
        """
        rows = (
            self.db.query(CostLedger)
            .filter(
                CostLedger.tenant_id == tenant_id,
                CostLedger.project_id == project_id,
            )
            .all()
        )
        total = sum(
            (r.metric_json or {}).get("amount", 0.0) for r in rows
        )
        return total
