"""add_ops_bridge_token_and_provider_report

Revision ID: b8f1c3d6e902
Revises: 3c2a9f7b6d11
Create Date: 2026-03-04 10:20:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8f1c3d6e902"
down_revision: Union[str, Sequence[str], None] = "3c2a9f7b6d11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _standard_columns() -> list[sa.Column]:
	return [
		sa.Column("id", sa.String(64), primary_key=True),
		sa.Column("tenant_id", sa.String(64), nullable=False),
		sa.Column("project_id", sa.String(64), nullable=False),
		sa.Column("trace_id", sa.String(128), nullable=True),
		sa.Column("correlation_id", sa.String(128), nullable=True),
		sa.Column("idempotency_key", sa.String(256), nullable=True),
		sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
		sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column("created_by", sa.String(64), nullable=True),
		sa.Column("updated_by", sa.String(64), nullable=True),
		sa.Column("error_code", sa.String(64), nullable=True),
		sa.Column("error_message", sa.String(1024), nullable=True),
		sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
	]


def upgrade() -> None:
	op.create_table(
		"ops_bridge_tokens",
		*_standard_columns(),
		sa.Column("name", sa.String(128), nullable=False),
		sa.Column("token_value", sa.String(512), nullable=False),
		sa.Column("token_hash", sa.String(128), nullable=False),
		sa.Column("token_masked", sa.String(128), nullable=True),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
		sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("scope_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("generated_from_token_id", sa.String(64), nullable=True),
		sa.ForeignKeyConstraint(["generated_from_token_id"], ["ops_bridge_tokens.id"], ondelete="SET NULL"),
		sa.UniqueConstraint("tenant_id", "project_id", "name", name="uq_ops_bridge_tokens_scope_name"),
	)
	op.create_index("ix_ops_bridge_tokens_scope_active", "ops_bridge_tokens", ["tenant_id", "project_id", "is_active"])
	op.create_index("ix_ops_bridge_tokens_scope_expires", "ops_bridge_tokens", ["tenant_id", "project_id", "expires_at"])
	op.create_index("ix_ops_bridge_tokens_token_hash", "ops_bridge_tokens", ["token_hash"])
	op.create_index("ix_ops_bridge_tokens_expires_at", "ops_bridge_tokens", ["expires_at"])
	op.create_index("ix_ops_bridge_tokens_tenant_id", "ops_bridge_tokens", ["tenant_id"])
	op.create_index("ix_ops_bridge_tokens_project_id", "ops_bridge_tokens", ["project_id"])
	op.create_index("ix_ops_bridge_tokens_deleted_at", "ops_bridge_tokens", ["deleted_at"])
	op.create_index("ix_ops_bridge_tokens_created_at", "ops_bridge_tokens", ["created_at"])

	op.create_table(
		"ops_provider_reports",
		*_standard_columns(),
		sa.Column("provider_key", sa.String(128), nullable=False),
		sa.Column("provider_name", sa.String(128), nullable=False),
		sa.Column("capability_type", sa.String(64), nullable=False),
		sa.Column("capability_tier", sa.String(32), nullable=False, server_default="none"),
		sa.Column("integration_status", sa.String(32), nullable=False, server_default="unbound"),
		sa.Column("endpoint_base_url", sa.String(512), nullable=True),
		sa.Column("protocol", sa.String(64), nullable=False, server_default="ainer-unified"),
		sa.Column("openapi_url", sa.String(512), nullable=True),
		sa.Column("model_catalog_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("features_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("constraints_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("adapter_spec_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("health_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("raw_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.Column("matched_provider_id", sa.String(64), nullable=True),
		sa.Column("matched_profile_id", sa.String(64), nullable=True),
		sa.Column("integration_notes", sa.String(1024), nullable=True),
		sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
		sa.Column("last_test_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
		sa.ForeignKeyConstraint(["matched_provider_id"], ["model_providers.id"], ondelete="SET NULL"),
		sa.ForeignKeyConstraint(["matched_profile_id"], ["model_profiles.id"], ondelete="SET NULL"),
		sa.UniqueConstraint(
			"tenant_id",
			"project_id",
			"provider_key",
			"capability_type",
			name="uq_ops_provider_reports_scope_key_capability",
		),
	)
	op.create_index(
		"ix_ops_provider_reports_scope_status",
		"ops_provider_reports",
		["tenant_id", "project_id", "integration_status"],
	)
	op.create_index(
		"ix_ops_provider_reports_scope_capability",
		"ops_provider_reports",
		["tenant_id", "project_id", "capability_type"],
	)
	op.create_index("ix_ops_provider_reports_last_reported_at", "ops_provider_reports", ["last_reported_at"])
	op.create_index("ix_ops_provider_reports_tenant_id", "ops_provider_reports", ["tenant_id"])
	op.create_index("ix_ops_provider_reports_project_id", "ops_provider_reports", ["project_id"])
	op.create_index("ix_ops_provider_reports_deleted_at", "ops_provider_reports", ["deleted_at"])
	op.create_index("ix_ops_provider_reports_created_at", "ops_provider_reports", ["created_at"])


def downgrade() -> None:
	op.drop_table("ops_provider_reports")
	op.drop_table("ops_bridge_tokens")
