from __future__ import annotations

from sqlalchemy import ARRAY, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

try:
	from pgvector.sqlalchemy import Vector
except ImportError:
	Vector = None

from .base_model import Base, StandardColumnsMixin
from .enum_models import KBBindType, KBPackStatus, KBSourceType, ProposalStatus, RagScope, RagSourceType, RolloutStatus


class RagCollection(Base, StandardColumnsMixin):
	__tablename__ = "rag_collections"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "name", "version", "language_code", name="uq_rag_collections_scope_name_ver_lang"),
		Index("ix_rag_collections_scope_name", "tenant_id", "project_id", "name"),
		Index("ix_rag_collections_bind", "tenant_id", "project_id", "bind_type", "bind_id"),
	)

	novel_id: Mapped[str | None] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
	name: Mapped[str] = mapped_column(String(128), nullable=False)
	language_code: Mapped[str | None] = mapped_column(String(16))
	description: Mapped[str | None] = mapped_column(Text)
	tags_json: Mapped[list | None] = mapped_column(JSONB)
	bind_type: Mapped[KBBindType | None] = mapped_column(nullable=True)
	bind_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

	def __init__(self, **kwargs):
		# Backward compatibility for older call sites/tests.
		legacy_name = kwargs.pop("collection_name", None)
		if legacy_name is not None and "name" not in kwargs:
			kwargs["name"] = legacy_name
		kwargs.pop("status", None)
		super().__init__(**kwargs)


class KbVersion(Base, StandardColumnsMixin):
	__tablename__ = "kb_versions"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "collection_id", "version_name", name="uq_kb_versions_scope_name"),
		Index("ix_kb_versions_scope_collection", "tenant_id", "project_id", "collection_id"),
	)

	collection_id: Mapped[str] = mapped_column(ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False)
	version_name: Mapped[str] = mapped_column(String(64), nullable=False)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
	recipe_id: Mapped[str | None] = mapped_column(String(64))
	embedding_model_profile_id: Mapped[str | None] = mapped_column(ForeignKey("model_profiles.id", ondelete="SET NULL"))
	release_note: Mapped[str | None] = mapped_column(Text)


class RagDocument(Base, StandardColumnsMixin):
	__tablename__ = "rag_documents"
	__table_args__ = (
		Index("ix_rag_documents_scope_type", "tenant_id", "project_id", "scope", "source_type"),
		Index("ix_rag_documents_scope_collection", "tenant_id", "project_id", "collection_id"),
	)

	collection_id: Mapped[str | None] = mapped_column(ForeignKey("rag_collections.id", ondelete="SET NULL"))
	kb_version_id: Mapped[str | None] = mapped_column(ForeignKey("kb_versions.id", ondelete="SET NULL"))
	novel_id: Mapped[str | None] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
	scope: Mapped[RagScope] = mapped_column(nullable=False)
	source_type: Mapped[RagSourceType] = mapped_column(nullable=False)
	source_id: Mapped[str | None] = mapped_column(String(128))
	language_code: Mapped[str | None] = mapped_column(String(16))
	title: Mapped[str | None] = mapped_column(String(256))
	content_text: Mapped[str] = mapped_column(Text, nullable=False)
	metadata_json: Mapped[dict | None] = mapped_column(JSONB)


class RagEmbedding(Base, StandardColumnsMixin):
	__tablename__ = "rag_embeddings"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "doc_id", "embedding_model_profile_id", name="uq_rag_embeddings_scope_doc_model"),
		Index("ix_rag_embeddings_scope_doc", "tenant_id", "project_id", "doc_id"),
		Index("ix_rag_embeddings_scope_model", "tenant_id", "project_id", "embedding_model_profile_id"),
	)

	doc_id: Mapped[str] = mapped_column(ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False)
	embedding_model_profile_id: Mapped[str | None] = mapped_column(ForeignKey("model_profiles.id", ondelete="SET NULL"))
	embedding_dim: Mapped[int] = mapped_column(nullable=False, default=0)
	embedding: Mapped[list[float]] = mapped_column(
		Vector(1536) if Vector is not None else ARRAY(Float),
		nullable=False,
	)
	quality_score: Mapped[float | None] = mapped_column(Float)
	is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)


class FeedbackEvent(Base, StandardColumnsMixin):
	__tablename__ = "feedback_events"
	__table_args__ = (
		Index("ix_feedback_events_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_feedback_events_scope_kb", "tenant_id", "project_id", "kb_version_id"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"))
	kb_version_id: Mapped[str | None] = mapped_column(ForeignKey("kb_versions.id", ondelete="SET NULL"))
	rating: Mapped[int | None] = mapped_column()
	issues_json: Mapped[list | None] = mapped_column(JSONB)
	free_text: Mapped[str | None] = mapped_column(Text)


class KbProposal(Base, StandardColumnsMixin):
	__tablename__ = "kb_proposals"
	__table_args__ = (
		Index("ix_kb_proposals_scope_kb", "tenant_id", "project_id", "kb_version_id"),
		Index("ix_kb_proposals_scope_status", "tenant_id", "project_id", "status"),
	)

	kb_version_id: Mapped[str] = mapped_column(ForeignKey("kb_versions.id", ondelete="CASCADE"), nullable=False)
	feedback_event_id: Mapped[str | None] = mapped_column(ForeignKey("feedback_events.id", ondelete="SET NULL"))
	status: Mapped[ProposalStatus] = mapped_column(nullable=False, default=ProposalStatus.draft)
	proposal_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	review_comment: Mapped[str | None] = mapped_column(Text)


class RagEvalReport(Base, StandardColumnsMixin):
	__tablename__ = "rag_eval_reports"
	__table_args__ = (Index("ix_rag_eval_reports_scope_kb", "tenant_id", "project_id", "kb_version_id"),)

	kb_version_id: Mapped[str] = mapped_column(ForeignKey("kb_versions.id", ondelete="CASCADE"), nullable=False)
	eval_suite: Mapped[str] = mapped_column(String(64), nullable=False)
	score_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	passed: Mapped[bool] = mapped_column(nullable=False, default=False)


class KbRollout(Base, StandardColumnsMixin):
	__tablename__ = "kb_rollouts"
	__table_args__ = (Index("ix_kb_rollouts_scope_kb", "tenant_id", "project_id", "kb_version_id"),)

	kb_version_id: Mapped[str] = mapped_column(ForeignKey("kb_versions.id", ondelete="CASCADE"), nullable=False)
	status: Mapped[RolloutStatus] = mapped_column(nullable=False, default=RolloutStatus.planned)
	rollout_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


# ═══════════════════════════════════════════════════════════════════════════════
# KBPack — 知识包资产（可复用、可多绑定）
# ═══════════════════════════════════════════════════════════════════════════════

class KBPack(Base, StandardColumnsMixin):
	"""知识包资产主表，底层使用 RagCollection 作为向量存储容器。"""
	__tablename__ = "kb_packs"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "name", name="uq_kb_packs_scope_name"),
		Index("ix_kb_packs_scope_name", "tenant_id", "project_id", "name"),
		Index("ix_kb_packs_scope_status", "tenant_id", "project_id", "status"),
	)

	name: Mapped[str] = mapped_column(String(128), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)
	language_code: Mapped[str | None] = mapped_column(String(16))         # zh/en/ja
	culture_pack: Mapped[str | None] = mapped_column(String(64))          # cn_wuxia/us_hollywood
	version_name: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
	status: Mapped[KBPackStatus] = mapped_column(nullable=False, default=KBPackStatus.draft)
	tags_json: Mapped[list | None] = mapped_column(JSONB)
	bind_suggestions_json: Mapped[list | None] = mapped_column(JSONB)    # 建议绑定的 role_ids
	# 底层向量存储容器（创建 KBPack 时自动创建一个 RagCollection）
	collection_id: Mapped[str | None] = mapped_column(
		ForeignKey("rag_collections.id", ondelete="SET NULL"), nullable=True
	)


class KBSource(Base, StandardColumnsMixin):
	"""导入源文件追踪记录。"""
	__tablename__ = "kb_sources"
	__table_args__ = (
		Index("ix_kb_sources_pack", "kb_pack_id"),
		Index("ix_kb_sources_status", "parse_status"),
	)

	kb_pack_id: Mapped[str] = mapped_column(ForeignKey("kb_packs.id", ondelete="CASCADE"), nullable=False)
	source_type: Mapped[KBSourceType] = mapped_column(nullable=False, default=KBSourceType.txt)
	source_name: Mapped[str | None] = mapped_column(String(256))          # 文件名
	source_uri: Mapped[str | None] = mapped_column(String(512))           # URL 或 object_key
	parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending/done/failed
	parse_log: Mapped[str | None] = mapped_column(Text)
	chunk_count: Mapped[int] = mapped_column(nullable=False, default=0)


# ─── 绑定关系表 ───────────────────────────────────────────────────────────────

class RoleKBMap(Base, StandardColumnsMixin):
	"""职业 ↔ 知识包绑定关系。"""
	__tablename__ = "role_kb_maps"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "role_id", "kb_pack_id", name="uq_role_kb_maps_role_pack"),
		Index("ix_role_kb_maps_role", "tenant_id", "project_id", "role_id"),
		Index("ix_role_kb_maps_pack", "kb_pack_id"),
	)

	role_id: Mapped[str] = mapped_column(String(128), nullable=False)
	kb_pack_id: Mapped[str] = mapped_column(ForeignKey("kb_packs.id", ondelete="CASCADE"), nullable=False)
	priority: Mapped[int] = mapped_column(nullable=False, default=100)    # 越大越优先
	enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
	note: Mapped[str | None] = mapped_column(String(256))


class PersonaKBMap(Base, StandardColumnsMixin):
	"""Persona ↔ 知识包绑定关系（叠加在 Role KB 之上）。"""
	__tablename__ = "persona_kb_maps"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "persona_pack_id", "kb_pack_id", name="uq_persona_kb_maps_persona_pack"),
		Index("ix_persona_kb_maps_persona", "tenant_id", "project_id", "persona_pack_id"),
		Index("ix_persona_kb_maps_pack", "kb_pack_id"),
	)

	persona_pack_id: Mapped[str] = mapped_column(ForeignKey("persona_packs.id", ondelete="CASCADE"), nullable=False)
	kb_pack_id: Mapped[str] = mapped_column(ForeignKey("kb_packs.id", ondelete="CASCADE"), nullable=False)
	priority: Mapped[int] = mapped_column(nullable=False, default=100)
	enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
	note: Mapped[str | None] = mapped_column(String(256))


class NovelKBMap(Base, StandardColumnsMixin):
	"""小说 ↔ 知识包绑定关系（项目一致性最高优先级）。"""
	__tablename__ = "novel_kb_maps"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "novel_id", "kb_pack_id", name="uq_novel_kb_maps_novel_pack"),
		Index("ix_novel_kb_maps_novel", "tenant_id", "project_id", "novel_id"),
		Index("ix_novel_kb_maps_pack", "kb_pack_id"),
	)

	novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
	kb_pack_id: Mapped[str] = mapped_column(ForeignKey("kb_packs.id", ondelete="CASCADE"), nullable=False)
	priority: Mapped[int] = mapped_column(nullable=False, default=100)
	enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
	note: Mapped[str | None] = mapped_column(String(256))

