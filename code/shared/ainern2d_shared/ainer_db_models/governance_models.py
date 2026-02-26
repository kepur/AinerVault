from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin
from .enum_models import ExperimentStatus, GateDecision


class PersonaPack(Base, StandardColumnsMixin):
	__tablename__ = "persona_packs"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "name", name="uq_persona_packs_scope_name"),
		Index("ix_persona_packs_scope_name", "tenant_id", "project_id", "name"),
	)

	name: Mapped[str] = mapped_column(String(128), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)
	tags_json: Mapped[list | None] = mapped_column(JSONB)


class PersonaPackVersion(Base, StandardColumnsMixin):
	__tablename__ = "persona_pack_versions"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "persona_pack_id", "version_name", name="uq_persona_pack_versions_scope_name"),
		Index("ix_persona_pack_versions_scope_pack", "tenant_id", "project_id", "persona_pack_id"),
	)

	persona_pack_id: Mapped[str] = mapped_column(ForeignKey("persona_packs.id", ondelete="CASCADE"), nullable=False)
	version_name: Mapped[str] = mapped_column(String(64), nullable=False)
	style_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	voice_json: Mapped[dict | None] = mapped_column(JSONB)
	camera_json: Mapped[dict | None] = mapped_column(JSONB)


class CreativePolicyStack(Base, StandardColumnsMixin):
	__tablename__ = "creative_policy_stacks"
	__table_args__ = (UniqueConstraint("tenant_id", "project_id", "name", name="uq_policy_stacks_scope_name"),)

	name: Mapped[str] = mapped_column(String(128), nullable=False)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
	stack_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ShotComputeBudget(Base, StandardColumnsMixin):
	__tablename__ = "shot_compute_budgets"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "run_id", "shot_id", name="uq_shot_compute_budgets_scope_run_shot"),
		Index("ix_shot_compute_budgets_scope_run", "tenant_id", "project_id", "run_id"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), nullable=False)
	budget_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ShotDslCompilation(Base, StandardColumnsMixin):
	__tablename__ = "shot_dsl_compilations"
	__table_args__ = (Index("ix_shot_dsl_compilations_scope_shot", "tenant_id", "project_id", "shot_id"),)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), nullable=False)
	backend: Mapped[str] = mapped_column(String(64), nullable=False)
	dsl_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	compiled_prompt_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class CriticEvaluation(Base, StandardColumnsMixin):
	__tablename__ = "critic_evaluations"
	__table_args__ = (
		Index("ix_critic_evaluations_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_critic_evaluations_scope_decision", "tenant_id", "project_id", "gate_decision"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"))
	rubric_name: Mapped[str] = mapped_column(String(128), nullable=False)
	score_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	gate_decision: Mapped[GateDecision] = mapped_column(nullable=False)
	feedback_json: Mapped[dict | None] = mapped_column(JSONB)


class RecoveryPolicy(Base, StandardColumnsMixin):
	__tablename__ = "recovery_policies"
	__table_args__ = (UniqueConstraint("tenant_id", "project_id", "stage", "error_class", name="uq_recovery_policies_scope_stage_error"),)

	stage: Mapped[str] = mapped_column(String(64), nullable=False)
	error_class: Mapped[str] = mapped_column(String(64), nullable=False)
	policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class RecoveryExecution(Base, StandardColumnsMixin):
	__tablename__ = "recovery_executions"
	__table_args__ = (Index("ix_recovery_executions_scope_run", "tenant_id", "project_id", "run_id"),)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
	stage: Mapped[str] = mapped_column(String(64), nullable=False)
	error_code: Mapped[str] = mapped_column(String(64), nullable=False)
	actions_json: Mapped[list] = mapped_column(JSONB, nullable=False)
	final_result: Mapped[str] = mapped_column(String(32), nullable=False)


class ExperimentRun(Base, StandardColumnsMixin):
	__tablename__ = "experiment_runs"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "experiment_key", "idempotency_key", name="uq_experiment_runs_scope_key_idem"),
		Index("ix_experiment_runs_scope_status", "tenant_id", "project_id", "status"),
	)

	experiment_key: Mapped[str] = mapped_column(String(128), nullable=False)
	status: Mapped[ExperimentStatus] = mapped_column(nullable=False, default=ExperimentStatus.planned)
	population_rule_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ExperimentArm(Base, StandardColumnsMixin):
	__tablename__ = "experiment_arms"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "experiment_run_id", "arm_key", name="uq_experiment_arms_scope_arm"),
		Index("ix_experiment_arms_scope_experiment", "tenant_id", "project_id", "experiment_run_id"),
	)

	experiment_run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False)
	arm_key: Mapped[str] = mapped_column(String(64), nullable=False)
	config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	allocation_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=50)


class ExperimentObservation(Base, StandardColumnsMixin):
	__tablename__ = "experiment_observations"
	__table_args__ = (
		Index("ix_experiment_observations_scope_experiment", "tenant_id", "project_id", "experiment_run_id"),
		Index("ix_experiment_observations_scope_run", "tenant_id", "project_id", "run_id"),
	)

	experiment_run_id: Mapped[str] = mapped_column(ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False)
	arm_id: Mapped[str] = mapped_column(ForeignKey("experiment_arms.id", ondelete="CASCADE"), nullable=False)
	run_id: Mapped[str | None] = mapped_column(ForeignKey("render_runs.id", ondelete="SET NULL"))
	metric_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class GateEvalResult(Base, StandardColumnsMixin):
	"""Records the outcome of a dispatch-decision audit against policy stacks."""
	__tablename__ = "gate_eval_results"
	__table_args__ = (Index("ix_gate_eval_results_decision", "gate_decision"),)

	gate_decision: Mapped[GateDecision] = mapped_column(nullable=False)
	feedback_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
