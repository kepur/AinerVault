from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin
from .enum_models import JobStatus, JobType, RenderStage, RunStatus


class ExecutionRequest(Base, StandardColumnsMixin):
	__tablename__ = "execution_requests"
	__table_args__ = (
		Index("ix_execution_requests_scope_chapter", "tenant_id", "project_id", "chapter_id"),
		Index("ix_execution_requests_scope_status", "tenant_id", "project_id", "status"),
		UniqueConstraint("tenant_id", "project_id", "idempotency_key", name="uq_execution_requests_scope_idem"),
	)

	novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
	chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
	status: Mapped[RunStatus] = mapped_column(default=RunStatus.queued, nullable=False)
	requested_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
	requested_quality: Mapped[str | None] = mapped_column(String(32))
	target_language_code: Mapped[str] = mapped_column(String(16), nullable=False, default="zh")
	kb_version_id: Mapped[str | None] = mapped_column(ForeignKey("kb_versions.id", ondelete="SET NULL"))
	policy_stack_id: Mapped[str | None] = mapped_column(ForeignKey("creative_policy_stacks.id", ondelete="SET NULL"))
	persona_pack_version_id: Mapped[str | None] = mapped_column(ForeignKey("persona_pack_versions.id", ondelete="SET NULL"))
	options_json: Mapped[dict | None] = mapped_column(JSONB)


class RenderRun(Base, StandardColumnsMixin):
	__tablename__ = "render_runs"
	__table_args__ = (
		Index("ix_render_runs_scope_chapter", "tenant_id", "project_id", "chapter_id"),
		Index("ix_render_runs_scope_status", "tenant_id", "project_id", "status"),
		Index("ix_render_runs_scope_stage", "tenant_id", "project_id", "stage"),
		Index("ix_render_runs_scope_kb", "tenant_id", "project_id", "kb_version_id"),
	)

	execution_request_id: Mapped[str | None] = mapped_column(ForeignKey("execution_requests.id", ondelete="SET NULL"))
	chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
	status: Mapped[RunStatus] = mapped_column(default=RunStatus.queued, nullable=False)
	stage: Mapped[RenderStage] = mapped_column(default=RenderStage.ingest, nullable=False)
	progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
	kb_version_id: Mapped[str | None] = mapped_column(ForeignKey("kb_versions.id", ondelete="SET NULL"))
	recipe_id: Mapped[str | None] = mapped_column(String(64))
	embedding_model_profile_id: Mapped[str | None] = mapped_column(ForeignKey("model_profiles.id", ondelete="SET NULL"))
	terminal_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
	started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	config_json: Mapped[dict | None] = mapped_column(JSONB)


class Job(Base, StandardColumnsMixin):
	__tablename__ = "jobs"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "job_type", "idempotency_key", name="uq_jobs_scope_type_idem"),
		Index("ix_jobs_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_jobs_scope_status", "tenant_id", "project_id", "status"),
		Index("ix_jobs_scope_type", "tenant_id", "project_id", "job_type"),
		Index("ix_jobs_scope_stage", "tenant_id", "project_id", "stage"),
	)

	run_id: Mapped[str | None] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"))
	chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
	shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"))
	job_type: Mapped[JobType] = mapped_column(nullable=False)
	stage: Mapped[RenderStage] = mapped_column(nullable=False, default=RenderStage.execute)
	status: Mapped[JobStatus] = mapped_column(default=JobStatus.queued, nullable=False)
	priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
	payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	result_json: Mapped[dict | None] = mapped_column(JSONB)
	attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
	max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
	locked_by: Mapped[str | None] = mapped_column(String(128))
	locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowEvent(Base, StandardColumnsMixin):
	__tablename__ = "workflow_events"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "idempotency_key", name="uq_workflow_events_scope_idem"),
		Index("ix_workflow_events_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_workflow_events_scope_job", "tenant_id", "project_id", "job_id"),
		Index("ix_workflow_events_scope_type", "tenant_id", "project_id", "event_type"),
	)

	run_id: Mapped[str | None] = mapped_column(ForeignKey("render_runs.id", ondelete="SET NULL"))
	job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
	stage: Mapped[RenderStage | None] = mapped_column()
	event_type: Mapped[str] = mapped_column(String(128), nullable=False)
	event_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
	producer: Mapped[str] = mapped_column(String(128), nullable=False)
	occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
	payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	error_json: Mapped[dict | None] = mapped_column(JSONB)


class RunStageTransition(Base, StandardColumnsMixin):
	__tablename__ = "run_stage_transitions"
	__table_args__ = (
		Index("ix_run_stage_transitions_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_run_stage_transitions_scope_stage", "tenant_id", "project_id", "to_stage"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	from_stage: Mapped[RenderStage | None] = mapped_column()
	to_stage: Mapped[RenderStage] = mapped_column(nullable=False)
	reason: Mapped[str | None] = mapped_column(String(256))
	guard_result_json: Mapped[dict | None] = mapped_column(JSONB)


class JobAttempt(Base, StandardColumnsMixin):
	__tablename__ = "job_attempts"
	__table_args__ = (
		Index("ix_job_attempts_scope_job", "tenant_id", "project_id", "job_id"),
		UniqueConstraint("tenant_id", "project_id", "job_id", "attempt_no", name="uq_job_attempts_scope_no"),
	)

	job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
	attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
	worker_node: Mapped[str | None] = mapped_column(String(128))
	status: Mapped[JobStatus] = mapped_column(nullable=False, default=JobStatus.running)
	started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	diagnostic_json: Mapped[dict | None] = mapped_column(JSONB)


class JobDependency(Base, StandardColumnsMixin):
	__tablename__ = "job_dependencies"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "job_id", "depends_on_job_id", name="uq_job_dependencies_scope_pair"),
		Index("ix_job_dependencies_scope_job", "tenant_id", "project_id", "job_id"),
	)

	job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
	depends_on_job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)


class RunCheckpoint(Base, StandardColumnsMixin):
	__tablename__ = "run_checkpoints"
	__table_args__ = (
		Index("ix_run_checkpoints_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_run_checkpoints_scope_stage", "tenant_id", "project_id", "stage"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	stage: Mapped[RenderStage] = mapped_column(nullable=False)
	checkpoint_name: Mapped[str] = mapped_column(String(128), nullable=False)
	snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class RunPatchRecord(Base, StandardColumnsMixin):
	__tablename__ = "run_patch_records"
	__table_args__ = (
		Index("ix_run_patch_records_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_run_patch_records_scope_stage", "tenant_id", "project_id", "stage"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	stage: Mapped[RenderStage | None] = mapped_column()
	patch_type: Mapped[str] = mapped_column(String(64), nullable=False)
	patch_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	applied_by: Mapped[str | None] = mapped_column(String(128))


class CompensationRecord(Base, StandardColumnsMixin):
	__tablename__ = "compensation_records"
	__table_args__ = (
		Index("ix_comp_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_comp_scope_phase", "tenant_id", "project_id", "compensation_phase"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
	compensation_phase: Mapped[str] = mapped_column(String(64), nullable=False)
	action_name: Mapped[str] = mapped_column(String(128), nullable=False)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
	detail: Mapped[str | None] = mapped_column(Text)


class DlqEvent(Base, StandardColumnsMixin):
	__tablename__ = "dlq_events"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "event_id", name="uq_dlq_events_scope_event"),
		Index("ix_dlq_events_scope_type", "tenant_id", "project_id", "event_type"),
	)

	event_id: Mapped[str] = mapped_column(String(64), nullable=False)
	event_type: Mapped[str] = mapped_column(String(128), nullable=False)
	producer: Mapped[str] = mapped_column(String(128), nullable=False)
	run_id: Mapped[str | None] = mapped_column(ForeignKey("render_runs.id", ondelete="SET NULL"))
	job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
	error_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
