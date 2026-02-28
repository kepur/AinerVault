from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin


class ModelProvider(Base, StandardColumnsMixin):
	__tablename__ = "model_providers"
	__table_args__ = (UniqueConstraint("tenant_id", "project_id", "name", name="uq_model_providers_scope_name"),)

	name: Mapped[str] = mapped_column(String(128), nullable=False)
	endpoint: Mapped[str | None] = mapped_column(String(512))
	auth_mode: Mapped[str | None] = mapped_column(String(64))


class ProviderAdapter(Base, StandardColumnsMixin):
	__tablename__ = "provider_adapters"
	__table_args__ = (
		Index("ix_provider_adapters_scope_provider", "tenant_id", "project_id", "provider_id"),
		UniqueConstraint("tenant_id", "project_id", "provider_id", "feature", name="uq_provider_adapters_feature"),
	)

	provider_id: Mapped[str] = mapped_column(ForeignKey("model_providers.id", ondelete="CASCADE"), nullable=False)
	feature: Mapped[str] = mapped_column(String(64), nullable=False)
	
	endpoint_json: Mapped[dict | None] = mapped_column(JSONB)
	auth_json: Mapped[dict | None] = mapped_column(JSONB)
	request_json: Mapped[dict | None] = mapped_column(JSONB)
	response_json: Mapped[dict | None] = mapped_column(JSONB)
	
	timeout_sec: Mapped[int] = mapped_column(default=60)
	retry_json: Mapped[dict | None] = mapped_column(JSONB)
	version: Mapped[str] = mapped_column(String(32), default="v1")


class ModelProfile(Base, StandardColumnsMixin):
	__tablename__ = "model_profiles"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "purpose", "name", name="uq_model_profiles_scope_purpose_name"),
		Index("ix_model_profiles_scope_provider", "tenant_id", "project_id", "provider_id"),
	)

	provider_id: Mapped[str] = mapped_column(ForeignKey("model_providers.id", ondelete="CASCADE"), nullable=False)
	adapter_id: Mapped[str | None] = mapped_column(ForeignKey("provider_adapters.id", ondelete="SET NULL"))
	purpose: Mapped[str] = mapped_column(String(64), nullable=False)
	name: Mapped[str] = mapped_column(String(128), nullable=False)
	params_json: Mapped[dict | None] = mapped_column(JSONB)


class RouteDecision(Base, StandardColumnsMixin):
	__tablename__ = "route_decisions"
	__table_args__ = (Index("ix_route_decisions_scope_job", "tenant_id", "project_id", "job_id"),)

	run_id: Mapped[str | None] = mapped_column(ForeignKey("render_runs.id", ondelete="SET NULL"))
	job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
	model_profile_id: Mapped[str | None] = mapped_column(ForeignKey("model_profiles.id", ondelete="SET NULL"))
	decision_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class CostLedger(Base, StandardColumnsMixin):
	__tablename__ = "cost_ledgers"
	__table_args__ = (
		Index("ix_cost_ledgers_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_cost_ledgers_scope_provider", "tenant_id", "project_id", "provider_id"),
	)

	run_id: Mapped[str | None] = mapped_column(ForeignKey("render_runs.id", ondelete="SET NULL"))
	job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
	provider_id: Mapped[str | None] = mapped_column(ForeignKey("model_providers.id", ondelete="SET NULL"))
	metric_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
