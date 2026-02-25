from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin
from .enum_models import MembershipRole


class Tenant(Base, StandardColumnsMixin):
	__tablename__ = "tenants"
	__table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenants_tenant_idempotency"),)

	name: Mapped[str] = mapped_column(String(128), nullable=False)


class User(Base, StandardColumnsMixin):
	__tablename__ = "users"
	__table_args__ = (
		UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
		Index("ix_users_project_created", "project_id", "created_at"),
	)

	email: Mapped[str] = mapped_column(String(256), nullable=False)
	display_name: Mapped[str] = mapped_column(String(128), nullable=False)
	password_hash: Mapped[str] = mapped_column(String(512), nullable=False)


class Project(Base, StandardColumnsMixin):
	__tablename__ = "projects"
	__table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_projects_tenant_slug"),)

	slug: Mapped[str] = mapped_column(String(128), nullable=False)
	name: Mapped[str] = mapped_column(String(256), nullable=False)
	description: Mapped[str | None] = mapped_column(String(1024))


class TenantMember(Base, StandardColumnsMixin):
	__tablename__ = "tenant_members"
	__table_args__ = (
		UniqueConstraint("tenant_id", "user_id", name="uq_tenant_members_user"),
		Index("ix_tenant_members_project_role", "project_id", "role"),
	)

	user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
	role: Mapped[MembershipRole] = mapped_column(nullable=False)


class ProjectMember(Base, StandardColumnsMixin):
	__tablename__ = "project_members"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "user_id", name="uq_project_members_user"),
		Index("ix_project_members_project_role", "project_id", "role"),
	)

	user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
	role: Mapped[MembershipRole] = mapped_column(nullable=False)


class ServiceAccount(Base, StandardColumnsMixin):
	__tablename__ = "service_accounts"
	__table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_service_accounts_name"),)

	name: Mapped[str] = mapped_column(String(128), nullable=False)
	token_hash: Mapped[str] = mapped_column(String(512), nullable=False)
