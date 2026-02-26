from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun, RunStageTransition
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("orchestrator.state_machine")

# Ordered pipeline stages — forward-only transitions allowed.
STAGE_ORDER: List[RenderStage] = [
    RenderStage.ingest,
    RenderStage.entity,
    RenderStage.knowledge,
    RenderStage.plan,
    RenderStage.route,
    RenderStage.execute,
    RenderStage.audio,
    RenderStage.video,
    RenderStage.lipsync,
    RenderStage.compose,
    RenderStage.observe,
]
_STAGE_INDEX: Dict[RenderStage, int] = {s: i for i, s in enumerate(STAGE_ORDER)}

ERROR_ILLEGAL_TRANSITION = "ORCH-STATE-001"


class RunStateMachine:
    """Forward-only stage state machine for a RenderRun."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transition(
        self,
        run_id: str,
        from_stage: RenderStage,
        to_stage: RenderStage,
        guard_result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Attempt a stage transition.  Returns True on success, False if
        the guard failed or the transition is illegal."""

        run: Optional[RenderRun] = self.db.get(RenderRun, run_id)
        if run is None:
            logger.error("run_not_found | run_id={}", run_id)
            return False

        # ---- validate forward-only ----
        from_idx = _STAGE_INDEX.get(from_stage)
        to_idx = _STAGE_INDEX.get(to_stage)

        if from_idx is None or to_idx is None or to_idx <= from_idx:
            logger.warning(
                "illegal_transition | run_id={} from={} to={} error_code={}",
                run_id, from_stage, to_stage, ERROR_ILLEGAL_TRANSITION,
            )
            run.error_code = ERROR_ILLEGAL_TRANSITION
            run.error_message = (
                f"Illegal stage transition from {from_stage.value} to {to_stage.value}"
            )
            self.db.flush()
            return False

        # ---- verify current run stage matches from_stage ----
        if run.stage != from_stage:
            logger.warning(
                "stage_mismatch | run_id={} expected={} actual={}",
                run_id, from_stage, run.stage,
            )
            run.error_code = ERROR_ILLEGAL_TRANSITION
            run.error_message = (
                f"Run stage is {run.stage.value}, expected {from_stage.value}"
            )
            self.db.flush()
            return False

        # ---- evaluate guard (if provided) ----
        if guard_result is not None and not guard_result.get("passed", True):
            logger.info(
                "guard_failed | run_id={} from={} to={} guard={}",
                run_id, from_stage, to_stage, guard_result,
            )
            return False

        # ---- apply transition ----
        run.stage = to_stage
        if run.status == RunStatus.queued:
            run.status = RunStatus.running
        self.db.flush()

        # ---- persist transition record ----
        record = RunStageTransition(
            id=f"rst_{run_id}_{to_stage.value}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            run_id=run_id,
            from_stage=from_stage,
            to_stage=to_stage,
            reason=guard_result.get("reason") if guard_result else None,
            guard_result_json=guard_result,
        )
        self.db.add(record)
        self.db.flush()

        logger.info(
            "stage_transitioned | run_id={} {} -> {}",
            run_id, from_stage.value, to_stage.value,
        )
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def next_stage(current: RenderStage) -> Optional[RenderStage]:
        """Return the next stage in the pipeline, or None if already at the end."""
        idx = _STAGE_INDEX.get(current)
        if idx is None or idx >= len(STAGE_ORDER) - 1:
            return None
        return STAGE_ORDER[idx + 1]

    @staticmethod
    def is_terminal(stage: RenderStage) -> bool:
        return stage == STAGE_ORDER[-1]
