from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin


class OpsBridgeToken(Base, StandardColumnsMixin):
	__tablename__ = "ops_bridge_tokens"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "name", name="uq_ops_bridge_tokens_scope_name"),
		Index("ix_ops_bridge_tokens_scope_active", "tenant_id", "project_id", "is_active"),
		Index("ix_ops_bridge_tokens_scope_expires", "tenant_id", "project_id", "expires_at"),
	)

	name: Mapped[str] = mapped_column(String(128), nullable=False)
	token_value: Mapped[str] = mapped_column(String(512), nullable=False)
	token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
	token_masked: Mapped[str | None] = mapped_column(String(128))
	is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
	expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
	last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	scope_json: Mapped[dict | None] = mapped_column(JSONB)
	generated_from_token_id: Mapped[str | None] = mapped_column(
		ForeignKey("ops_bridge_tokens.id", ondelete="SET NULL")
	)


class OpsProviderReport(Base, StandardColumnsMixin):
	__tablename__ = "ops_provider_reports"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id",
			"project_id",
			"provider_key",
			"capability_type",
			name="uq_ops_provider_reports_scope_key_capability",
		),
		Index("ix_ops_provider_reports_scope_status", "tenant_id", "project_id", "integration_status"),
		Index("ix_ops_provider_reports_scope_capability", "tenant_id", "project_id", "capability_type"),
	)

	provider_key: Mapped[str] = mapped_column(String(128), nullable=False)
	provider_name: Mapped[str] = mapped_column(String(128), nullable=False)
	capability_type: Mapped[str] = mapped_column(String(64), nullable=False)
	capability_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
	integration_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unbound")

	endpoint_base_url: Mapped[str | None] = mapped_column(String(512))
	protocol: Mapped[str] = mapped_column(String(64), nullable=False, default="ainer-unified")
	openapi_url: Mapped[str | None] = mapped_column(String(512))

	model_catalog_json: Mapped[list | None] = mapped_column(JSONB)
	features_json: Mapped[dict | None] = mapped_column(JSONB)
	constraints_json: Mapped[dict | None] = mapped_column(JSONB)
	adapter_spec_json: Mapped[dict | None] = mapped_column(JSONB)
	health_json: Mapped[dict | None] = mapped_column(JSONB)
	raw_payload_json: Mapped[dict | None] = mapped_column(JSONB)

	matched_provider_id: Mapped[str | None] = mapped_column(ForeignKey("model_providers.id", ondelete="SET NULL"))
	matched_profile_id: Mapped[str | None] = mapped_column(ForeignKey("model_profiles.id", ondelete="SET NULL"))
	integration_notes: Mapped[str | None] = mapped_column(String(1024))

	last_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
	last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	last_test_result_json: Mapped[dict | None] = mapped_column(JSONB)
