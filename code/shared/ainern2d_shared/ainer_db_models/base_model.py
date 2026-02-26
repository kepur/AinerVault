from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
	return datetime.now(timezone.utc)


class Base(DeclarativeBase):
	pass


class IdMixin:
	id: Mapped[str] = mapped_column(String(64), primary_key=True)


class TenantProjectMixin:
	tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
	project_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class TraceMixin:
	trace_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
	correlation_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)


class IdempotencyMixin:
	idempotency_key: Mapped[Optional[str]] = mapped_column(String(256), index=True)


class VersionSoftDeleteMixin:
	version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
	deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)


class AuditMixin:
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		default=utcnow,
		onupdate=utcnow,
		nullable=False,
	)
	created_by: Mapped[Optional[str]] = mapped_column(String(64))
	updated_by: Mapped[Optional[str]] = mapped_column(String(64))


class ErrorMixin:
	error_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)
	error_message: Mapped[Optional[str]] = mapped_column(String(1024))


class StandardColumnsMixin(
	IdMixin,
	TenantProjectMixin,
	TraceMixin,
	IdempotencyMixin,
	VersionSoftDeleteMixin,
	AuditMixin,
	ErrorMixin,
):
	retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
