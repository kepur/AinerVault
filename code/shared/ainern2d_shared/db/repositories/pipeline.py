from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.pipeline_models import (
	Job,
	RenderRun,
	WorkflowEvent,
)
from .base import BaseRepository


class RenderRunRepository(BaseRepository[RenderRun]):
	model = RenderRun

	def get_by_scope(
		self, tenant_id: str, project_id: str, *, limit: int = 50
	) -> Sequence[RenderRun]:
		stmt = (
			select(RenderRun)
			.filter_by(tenant_id=tenant_id, project_id=project_id, deleted_at=None)
			.order_by(RenderRun.created_at.desc())
			.limit(limit)
		)
		return self.db.execute(stmt).scalars().all()


class JobRepository(BaseRepository[Job]):
	model = Job

	def list_by_run(self, run_id: str) -> Sequence[Job]:
		return self.list_by(run_id=run_id)

	def get_by_idempotency(
		self, tenant_id: str, project_id: str, job_type: str, idempotency_key: str
	) -> Optional[Job]:
		stmt = select(Job).filter_by(
			tenant_id=tenant_id,
			project_id=project_id,
			job_type=job_type,
			idempotency_key=idempotency_key,
		)
		return self.db.execute(stmt).scalars().first()


class WorkflowEventRepository(BaseRepository[WorkflowEvent]):
	model = WorkflowEvent

	def list_by_run(self, run_id: str, *, limit: int = 200) -> Sequence[WorkflowEvent]:
		stmt = (
			select(WorkflowEvent)
			.filter_by(run_id=run_id)
			.order_by(WorkflowEvent.created_at.desc())
			.limit(limit)
		)
		return self.db.execute(stmt).scalars().all()
