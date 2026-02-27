"""SKILL 12: RagPipelineService — Full RAG pipeline implementation.

Reference: SKILL_12_RAG_PIPELINE_EMBEDDING.md
State machine: INIT → CHUNKING → ENRICHING → EMBEDDING → INDEXING
              → VALIDATING → REPORTING → READY | FAILED

Pipeline stages: chunk → enrich → embed → index → validate → report
"""
from __future__ import annotations

import hashlib
import math
import re
import uuid
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.skills.skill_12 import (
    Chunk,
    ChunkConfig,
    ChunkMetadata,
    ChunkingStrategy,
    ContentType,
    EmbeddingModelConfig,
    EmbeddingQualityReport,
    EvalMetrics,
    FeatureFlags,
    IncrementalIndexDelta,
    IndexConfig,
    IndexMetadata,
    IndexType,
    ItemStatus,
    KnowledgeItem,
    PipelineStage,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalResult,
    Skill12Input,
    Skill12Output,
    StageRecord,
    Strength,
    VectorStoreConfig,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from ainern2d_shared.utils.time import utcnow

# ── Constants ─────────────────────────────────────────────────────

_CONTENT_TYPE_TOKEN_RANGES: dict[ContentType, tuple[int, int]] = {
    ContentType.RULE: (150, 400),
    ContentType.CHECKLIST: (150, 400),
    ContentType.TEMPLATE: (200, 600),
    ContentType.LONG_DOC: (400, 900),
    ContentType.ANTI_PATTERN: (150, 400),
}

_DIM_MAP: dict[str, int] = {
    "text-embedding-3-small": 384,
    "text-embedding-3-large": 1024,
    "text-embedding-ada-002": 768,
}

_ENTITY_RE = re.compile(
    r'(?:《[^》]+》|「[^」]+」|\u201c[^\u201d]+\u201d|"[^"]+"|[A-Z][a-z]+(?:\s[A-Z][a-z]+)+)'
)
_CULTURE_RE = re.compile(
    r"(?:仙侠|武侠|修仙|江湖|wuxia|xianxia|samurai|bushido|cultivation)",
    re.IGNORECASE,
)
_DOMAIN_RE = re.compile(
    r"(?:medical|legal|finance|tech|education|gaming|医疗|法律|金融|科技|教育|游戏)",
    re.IGNORECASE,
)


class RagPipelineService(BaseSkillService[Skill12Input, Skill12Output]):
    """SKILL 12 — RAG Pipeline & Embedding.

    Implements the full vector-indexing pipeline with:
    - Multiple chunking strategies (fixed_window / semantic / entity_aware / hybrid)
    - Embedding generation simulation (384/768/1024 dims)
    - Index management (HNSW / IVF / Flat)
    - Chunk metadata enrichment
    - Incremental indexing support
    - Quality validation & eval suite
    - pgvector-compatible similarity simulation
    """

    skill_id = "skill_12"
    skill_name = "RagPipelineService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)
        self._vectors: dict[str, list[float]] = {}
        self._chunks: dict[str, Chunk] = {}
        self._index_version: int = 0

    # ── public entry (overrides base) ─────────────────────────────

    def execute(self, inp: Skill12Input, ctx: SkillContext) -> Skill12Output:
        stage_log: list[StageRecord] = []
        warnings: list[str] = []
        review_items: list[str] = []
        events: list[str] = []
        event_envelopes: list[EventEnvelope] = []
        build_id = f"KB_BUILD_{uuid.uuid4().hex[:8].upper()}"

        ff = inp.feature_flags or FeatureFlags()
        emb_cfg = inp.embedding_model_config or EmbeddingModelConfig()
        idx_cfg = inp.index_config or IndexConfig()
        chunk_cfg = inp.chunk_config or ChunkConfig()
        vs_cfg = inp.vector_store_config or VectorStoreConfig()

        # Resolve effective chunking strategy from feature flags
        effective_strategy = ff.chunking_strategy or chunk_cfg.strategy
        chunk_cfg_resolved = chunk_cfg.model_copy(update={"strategy": effective_strategy})

        # Resolve embedding dimensions from model name
        dim = _DIM_MAP.get(emb_cfg.model_name, emb_cfg.embedding_dim)

        try:
            # ── P1: Precheck ──────────────────────────────────────
            self._transition(ctx, PipelineStage.INIT, PipelineStage.CHUNKING)

            if not inp.kb_id:
                raise ValueError("RAG-VALIDATION-001: kb_id is required")
            if not inp.knowledge_items:
                raise ValueError("RAG-VALIDATION-002: knowledge_items must not be empty")

            active_items = [
                it for it in inp.knowledge_items if it.status == ItemStatus.ACTIVE
            ]
            deprecated_items = [
                it for it in inp.knowledge_items if it.status == ItemStatus.DEPRECATED
            ]
            if deprecated_items:
                warnings.append(
                    f"RAG-WARN-001: {len(deprecated_items)} deprecated items skipped"
                )

            if not active_items:
                raise ValueError("RAG-VALIDATION-003: no active knowledge items")

            # ── P2+P3: Chunking ───────────────────────────────────
            self._emit_event(
                events,
                event_envelopes,
                ctx,
                event_type="rag.chunking.started",
                payload={
                    "kb_id": inp.kb_id,
                    "kb_version_id": inp.kb_version_id,
                    "chunking_policy_id": inp.chunking_policy_id,
                    "knowledge_item_count": len(active_items),
                },
            )
            t0 = utcnow()
            chunks = self._stage_chunk(active_items, chunk_cfg_resolved, inp.kb_version_id)
            stage_log.append(self._stage_record(
                PipelineStage.CHUNKING, t0, len(chunks),
            ))

            # ── Enriching ─────────────────────────────────────────
            self._transition(ctx, PipelineStage.CHUNKING, PipelineStage.ENRICHING)
            t0 = utcnow()
            chunks = self._stage_enrich(chunks, active_items)
            stage_log.append(self._stage_record(
                PipelineStage.ENRICHING, t0, len(chunks),
            ))

            # Dedup
            if ff.enable_dedup:
                before = len(chunks)
                chunks = self._dedup_chunks(chunks)
                if len(chunks) < before:
                    warnings.append(
                        f"RAG-INFO-001: dedup removed {before - len(chunks)} chunks"
                    )

            # ── Embedding ─────────────────────────────────────────
            self._transition(ctx, PipelineStage.ENRICHING, PipelineStage.EMBEDDING)
            t0 = utcnow()
            embed_stats = self._stage_embed(chunks, emb_cfg, dim)
            stage_log.append(self._stage_record(
                PipelineStage.EMBEDDING, t0, embed_stats["embedded"],
            ))
            self._emit_event(
                events,
                event_envelopes,
                ctx,
                event_type="rag.embedding.completed",
                payload={
                    "kb_id": inp.kb_id,
                    "kb_version_id": inp.kb_version_id,
                    "embedded_chunks": embed_stats["embedded"],
                    "failed_chunks": embed_stats["failed"],
                    "embedding_model": emb_cfg.model_name,
                    "embedding_dim": dim,
                },
            )

            # ── Indexing ──────────────────────────────────────────
            self._transition(ctx, PipelineStage.EMBEDDING, PipelineStage.INDEXING)
            t0 = utcnow()
            inc_delta: IncrementalIndexDelta | None = None
            if inp.incremental and inp.previous_index_id:
                inc_delta = self._stage_incremental_index(
                    chunks, inp, idx_cfg, vs_cfg,
                )
            else:
                self._stage_full_index(chunks, idx_cfg, vs_cfg)
            idx_meta = self._build_index_metadata(
                inp, idx_cfg, dim, len(chunks), t0,
            )
            stage_log.append(self._stage_record(
                PipelineStage.INDEXING, t0, len(chunks),
            ))
            self._emit_event(
                events,
                event_envelopes,
                ctx,
                event_type="rag.index.ready",
                payload={
                    "kb_id": inp.kb_id,
                    "kb_version_id": inp.kb_version_id,
                    "index_id": idx_meta.index_id,
                    "index_version": idx_meta.index_version,
                    "total_vectors": idx_meta.total_vectors,
                },
            )

            # ── Validating ────────────────────────────────────────
            self._transition(ctx, PipelineStage.INDEXING, PipelineStage.VALIDATING)
            t0 = utcnow()
            quality = self._stage_validate(chunks, embed_stats, active_items)
            stage_log.append(self._stage_record(
                PipelineStage.VALIDATING, t0, len(chunks),
            ))

            # ── Reporting / Eval ──────────────────────────────────
            self._transition(ctx, PipelineStage.VALIDATING, PipelineStage.REPORTING)
            t0 = utcnow()
            eval_metrics = EvalMetrics(enabled=False)
            if ff.enable_eval_suite and inp.preview_queries:
                eval_metrics = self._stage_eval(
                    inp.preview_queries, chunks, ff, active_items,
                )
                self._emit_event(
                    events,
                    event_envelopes,
                    ctx,
                    event_type="rag.eval.completed",
                    payload={
                        "kb_id": inp.kb_id,
                        "kb_version_id": inp.kb_version_id,
                        "preview_queries": eval_metrics.preview_queries,
                        "recall_at_k": eval_metrics.recall_at_k,
                        "constraint_conflict_rate": eval_metrics.constraint_conflict_rate,
                        "redundancy_rate": eval_metrics.redundancy_rate,
                        "recommendation": eval_metrics.recommendation,
                    },
                )
                if eval_metrics.recommendation == "rollback":
                    warnings.append("RAG-WARN-002: eval recommends rollback")
                    review_items.append("eval_rollback_recommended")
                elif eval_metrics.recommendation == "review_required":
                    review_items.append("eval_review_required")
            stage_log.append(self._stage_record(
                PipelineStage.REPORTING, t0, len(inp.preview_queries),
            ))

            # ── Final status ──────────────────────────────────────
            promote_gate_passed = False
            if eval_metrics.enabled:
                promote_gate_passed = self._promote_gate_passed(eval_metrics)
                if not promote_gate_passed:
                    review_items.append("promote_gate_failed")
                elif not review_items:
                    self._emit_event(
                        events,
                        event_envelopes,
                        ctx,
                        event_type="kb.rollout.promoted",
                        payload={
                            "kb_id": inp.kb_id,
                            "kb_version_id": inp.kb_version_id,
                            "build_id": build_id,
                            "recall_at_k": eval_metrics.recall_at_k,
                            "constraint_conflict_rate": eval_metrics.constraint_conflict_rate,
                        },
                    )

            final_status = "index_ready"
            if review_items:
                final_status = "review_required"
            self._transition(ctx, PipelineStage.REPORTING, PipelineStage.READY)

            logger.info(
                f"[{self.skill_id}] completed | run={ctx.run_id} "
                f"kb={inp.kb_id} chunks={len(chunks)} status={final_status}"
            )

            return Skill12Output(
                version=ctx.schema_version,
                kb_version_id=inp.kb_version_id,
                build_id=build_id,
                status=final_status,
                chunking_policy_id=inp.chunking_policy_id,
                embedding_model=emb_cfg.model_name,
                stats=quality,
                eval=eval_metrics,
                index_metadata=idx_meta,
                incremental_delta=inc_delta,
                stage_log=stage_log,
                warnings=warnings,
                review_required_items=review_items,
                chunks=chunks,
                promote_gate_passed=promote_gate_passed,
                events_emitted=events,
                event_envelopes=event_envelopes,
            )

        except Exception as exc:
            self._transition(
                ctx,
                stage_log[-1].stage if stage_log else PipelineStage.INIT,
                PipelineStage.FAILED,
            )
            logger.error(f"[{self.skill_id}] FAILED | run={ctx.run_id} error={exc}")
            raise

    # ══════════════════════════════════════════════════════════════
    # Stage implementations
    # ══════════════════════════════════════════════════════════════

    # ── Chunking ──────────────────────────────────────────────────

    def _stage_chunk(
        self,
        items: list[KnowledgeItem],
        cfg: ChunkConfig,
        kb_version_id: str,
    ) -> list[Chunk]:
        all_chunks: list[Chunk] = []
        for item in items:
            text = self._normalize_text(item.content)
            if not text.strip():
                continue
            raw = self._apply_chunking_strategy(text, cfg, item.content_type)
            for i, seg in enumerate(raw):
                tok_count = self._estimate_tokens(seg)
                if tok_count < cfg.min_chunk_tokens:
                    continue
                cid = self._chunk_id(item.item_id, i)
                all_chunks.append(Chunk(
                    chunk_id=cid,
                    chunk_text=seg,
                    token_count=tok_count,
                    metadata=ChunkMetadata(
                        chunk_id=cid,
                        source_entry_id=item.item_id,
                        kb_version_id=kb_version_id,
                        knowledge_item_id=item.item_id,
                        role=item.role,
                        tags=list(item.tags),
                        strength=item.strength,
                        status=item.status,
                        content_type=item.content_type,
                        source=item.source,
                        created_at=utcnow().isoformat(),
                        updated_at=utcnow().isoformat(),
                    ),
                ))
        return all_chunks

    def _apply_chunking_strategy(
        self, text: str, cfg: ChunkConfig, content_type: ContentType,
    ) -> list[str]:
        strategy = cfg.strategy

        if strategy == ChunkingStrategy.FIXED_WINDOW:
            return self._chunk_fixed_window(text, cfg.chunk_size, cfg.chunk_overlap)

        if strategy == ChunkingStrategy.SEMANTIC:
            return self._chunk_semantic(text, cfg, content_type)

        if strategy == ChunkingStrategy.ENTITY_AWARE:
            return self._chunk_entity_aware(text, cfg)

        if strategy == ChunkingStrategy.HYBRID:
            # Combine semantic boundaries then refine with entity awareness
            sem = self._chunk_semantic(text, cfg, content_type)
            result: list[str] = []
            for seg in sem:
                entities = _ENTITY_RE.findall(seg)
                if entities:
                    result.extend(self._chunk_entity_aware(seg, cfg))
                else:
                    result.append(seg)
            return result

        return self._chunk_fixed_window(text, cfg.chunk_size, cfg.chunk_overlap)

    def _chunk_fixed_window(
        self, text: str, size: int, overlap: int,
    ) -> list[str]:
        chars_per_token = 4
        win = size * chars_per_token
        step = max(1, win - overlap * chars_per_token)
        segments: list[str] = []
        pos = 0
        while pos < len(text):
            end = min(pos + win, len(text))
            seg = text[pos:end].strip()
            if seg:
                segments.append(seg)
            pos += step
        return segments

    def _chunk_semantic(
        self, text: str, cfg: ChunkConfig, content_type: ContentType,
    ) -> list[str]:
        lo, hi = _CONTENT_TYPE_TOKEN_RANGES.get(content_type, (400, 900))
        if cfg.semantic_boundary == "section":
            splits = re.split(r"\n#{1,3}\s+", text)
        else:
            splits = re.split(r"\n\s*\n", text)

        # Merge small paragraphs, split oversized ones
        merged: list[str] = []
        buf = ""
        for part in splits:
            part = part.strip()
            if not part:
                continue
            combined_tokens = self._estimate_tokens(buf + " " + part)
            if combined_tokens <= hi:
                buf = (buf + "\n\n" + part).strip() if buf else part
            else:
                if buf:
                    merged.append(buf)
                buf = part
        if buf:
            merged.append(buf)

        # Force-split any oversized segments
        final: list[str] = []
        for seg in merged:
            if self._estimate_tokens(seg) > cfg.max_chunk_tokens:
                final.extend(
                    self._chunk_fixed_window(seg, cfg.chunk_size, cfg.chunk_overlap)
                )
            else:
                final.append(seg)
        return final

    def _chunk_entity_aware(self, text: str, cfg: ChunkConfig) -> list[str]:
        entities = [(m.start(), m.end()) for m in _ENTITY_RE.finditer(text)]
        if not entities:
            return self._chunk_fixed_window(text, cfg.chunk_size, cfg.chunk_overlap)

        chars_per_token = 4
        window = cfg.entity_window_tokens * chars_per_token
        segments: list[str] = []
        used_end = 0

        for start, end in entities:
            seg_start = max(used_end, start - window)
            seg_end = min(len(text), end + window)
            seg = text[seg_start:seg_end].strip()
            if seg:
                segments.append(seg)
            used_end = seg_end

        # Capture trailing text
        if used_end < len(text):
            tail = text[used_end:].strip()
            if tail:
                segments.append(tail)

        return segments or [text]

    # ── Enrichment ────────────────────────────────────────────────

    def _stage_enrich(
        self, chunks: list[Chunk], items: list[KnowledgeItem],
    ) -> list[Chunk]:
        item_map = {it.item_id: it for it in items}
        for chunk in chunks:
            md = chunk.metadata
            txt = chunk.chunk_text

            # Entity mentions
            md.entity_mentions = list(set(_ENTITY_RE.findall(txt)))

            # Culture tags
            md.culture_tags = list(set(
                m.group().lower() for m in _CULTURE_RE.finditer(txt)
            ))

            # Domain tags
            md.domain_tags = list(set(
                m.group().lower() for m in _DOMAIN_RE.finditer(txt)
            ))

            # Importance score: composite of length, entity density, strength
            tok = chunk.token_count or 1
            entity_density = min(len(md.entity_mentions) / max(tok / 100, 1), 1.0)
            strength_bonus = 0.2 if md.strength == Strength.HARD_CONSTRAINT else 0.0
            length_score = min(tok / 500, 1.0)
            md.importance_score = round(
                0.4 * length_score + 0.4 * entity_density + 0.2 + strength_bonus, 4
            )
            md.importance_score = min(md.importance_score, 1.0)

        return chunks

    # ── Embedding ─────────────────────────────────────────────────

    def _stage_embed(
        self,
        chunks: list[Chunk],
        cfg: EmbeddingModelConfig,
        dim: int,
    ) -> dict[str, Any]:
        embedded = 0
        failed = 0
        batch_count = math.ceil(len(chunks) / max(cfg.batch_size, 1))

        for batch_idx in range(batch_count):
            start = batch_idx * cfg.batch_size
            end = min(start + cfg.batch_size, len(chunks))
            batch = chunks[start:end]

            for chunk in batch:
                vec = self._generate_embedding(chunk.chunk_text, dim)
                if vec is not None:
                    self._vectors[chunk.chunk_id] = vec
                    self._chunks[chunk.chunk_id] = chunk
                    embedded += 1
                else:
                    failed += 1

            logger.debug(
                f"[{self.skill_id}] embed batch {batch_idx + 1}/{batch_count} "
                f"({len(batch)} chunks)"
            )

        return {
            "embedded": embedded,
            "failed": failed,
            "total": len(chunks),
            "batches": batch_count,
            "dim": dim,
        }

    def _generate_embedding(self, text: str, dim: int) -> list[float] | None:
        """Simulate embedding generation with deterministic pseudo-vectors."""
        if not text.strip():
            return None
        h = hashlib.sha256(text.encode()).hexdigest()
        vec: list[float] = []
        for i in range(dim):
            byte_idx = i % 32
            val = int(h[byte_idx * 2: byte_idx * 2 + 2], 16) / 255.0
            sign = -1.0 if (i + int(h[byte_idx], 16)) % 2 == 0 else 1.0
            vec.append(round(sign * val, 6))
        # L2-normalize
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [round(v / norm, 6) for v in vec]

    # ── Indexing ──────────────────────────────────────────────────

    def _stage_full_index(
        self,
        chunks: list[Chunk],
        idx_cfg: IndexConfig,
        vs_cfg: VectorStoreConfig,
    ) -> None:
        """Build full vector index (simulated)."""
        self._index_version += 1
        logger.info(
            f"[{self.skill_id}] full index build | type={idx_cfg.index_type.value} "
            f"vectors={len(chunks)} version={self._index_version}"
        )
        # HNSW: log construction params
        if idx_cfg.index_type == IndexType.HNSW:
            logger.debug(
                f"  HNSW params: ef_construction={idx_cfg.ef_construction} "
                f"M={idx_cfg.m_parameter} ef_search={idx_cfg.ef_search}"
            )
        elif idx_cfg.index_type == IndexType.IVF:
            logger.debug(
                f"  IVF params: nlist={idx_cfg.nlist} nprobe={idx_cfg.nprobe}"
            )

    def _stage_incremental_index(
        self,
        chunks: list[Chunk],
        inp: Skill12Input,
        idx_cfg: IndexConfig,
        vs_cfg: VectorStoreConfig,
    ) -> IncrementalIndexDelta:
        """Add/remove chunks without full rebuild."""
        ver_before = self._index_version
        self._index_version += 1

        current_ids = {c.chunk_id for c in chunks}
        added = [cid for cid in inp.added_item_ids if cid in current_ids]
        removed = list(inp.removed_item_ids)

        for rid in removed:
            self._vectors.pop(rid, None)
            self._chunks.pop(rid, None)

        logger.info(
            f"[{self.skill_id}] incremental index | +{len(added)} -{len(removed)} "
            f"version {ver_before}→{self._index_version}"
        )

        return IncrementalIndexDelta(
            added_chunk_ids=added,
            removed_chunk_ids=removed,
            index_version_before=ver_before,
            index_version_after=self._index_version,
        )

    def _build_index_metadata(
        self,
        inp: Skill12Input,
        idx_cfg: IndexConfig,
        dim: int,
        total_vectors: int,
        t0: Any,
    ) -> IndexMetadata:
        elapsed = (utcnow() - t0).total_seconds()
        params: dict[str, Any] = {"index_type": idx_cfg.index_type.value}
        if idx_cfg.index_type == IndexType.HNSW:
            params.update(
                ef_construction=idx_cfg.ef_construction,
                m=idx_cfg.m_parameter,
                ef_search=idx_cfg.ef_search,
            )
        elif idx_cfg.index_type == IndexType.IVF:
            params.update(nlist=idx_cfg.nlist, nprobe=idx_cfg.nprobe)

        return IndexMetadata(
            index_id=f"idx_{inp.kb_id}_{inp.kb_version_id}_{self._index_version}",
            index_type=idx_cfg.index_type,
            index_version=self._index_version,
            total_vectors=total_vectors,
            dimensions=dim,
            build_time_sec=round(elapsed, 3),
            params=params,
        )

    # ── Validation ────────────────────────────────────────────────

    def _stage_validate(
        self,
        chunks: list[Chunk],
        embed_stats: dict[str, Any],
        items: list[KnowledgeItem],
    ) -> EmbeddingQualityReport:
        total = embed_stats["total"]
        embedded = embed_stats["embedded"]
        coverage = round(embedded / max(total, 1), 4)

        # avg chunk quality: based on importance scores
        quality_scores = [c.metadata.importance_score for c in chunks if c.metadata]
        avg_quality = round(
            sum(quality_scores) / max(len(quality_scores), 1), 4
        )

        # Duplicate detection via text fingerprint
        seen: set[str] = set()
        dup_count = 0
        for c in chunks:
            fp = hashlib.md5(c.chunk_text.strip().lower().encode()).hexdigest()
            if fp in seen:
                dup_count += 1
            seen.add(fp)
        dup_ratio = round(dup_count / max(len(chunks), 1), 4)

        # Orphan entity ratio: entities in items not found in any chunk
        all_item_entities: set[str] = set()
        for it in items:
            all_item_entities.update(_ENTITY_RE.findall(it.content))
        chunk_entities: set[str] = set()
        for c in chunks:
            chunk_entities.update(c.metadata.entity_mentions)
        orphan = len(all_item_entities - chunk_entities)
        orphan_ratio = round(orphan / max(len(all_item_entities), 1), 4)

        char_lens = [len(c.chunk_text) for c in chunks]
        tok_lens = [c.token_count for c in chunks]

        return EmbeddingQualityReport(
            total_chunks=total,
            embedded_chunks=embedded,
            coverage_ratio=coverage,
            avg_chunk_quality=avg_quality,
            duplicate_chunk_ratio=dup_ratio,
            orphan_entity_ratio=orphan_ratio,
            avg_chunk_chars=round(sum(char_lens) / max(len(char_lens), 1)),
            avg_chunk_tokens=round(sum(tok_lens) / max(len(tok_lens), 1)),
            min_chunk_tokens=min(tok_lens) if tok_lens else 0,
            max_chunk_tokens=max(tok_lens) if tok_lens else 0,
        )

    # ── Eval suite ────────────────────────────────────────────────

    def _stage_eval(
        self,
        queries: list[str],
        chunks: list[Chunk],
        ff: FeatureFlags,
        items: list[KnowledgeItem],
    ) -> EvalMetrics:
        if not queries:
            return EvalMetrics(enabled=True, recommendation="review_required")

        total_recall = 0.0
        total_conflict = 0.0
        total_latency = 0.0

        for q in queries:
            resp = self.retrieve(
                RetrievalQuery(
                    query_text=q,
                    top_k=8,
                    enable_reranking=ff.enable_reranking,
                    hybrid_alpha=ff.hybrid_search_alpha,
                ),
            )
            # Recall approximation: did we get results?
            recall = min(len(resp.results) / 8.0, 1.0)
            total_recall += recall
            # Conflict: check for hard_constraint vs soft_preference clashes
            total_conflict += len(resp.conflict_candidates) / max(len(resp.results), 1)
            total_latency += resp.latency_ms

        n = len(queries)
        avg_recall = round(total_recall / n, 4)
        avg_conflict = round(total_conflict / n, 4)
        avg_latency = round(total_latency / n, 2)

        # Redundancy: duplicate ratio from chunks
        seen: set[str] = set()
        dup = 0
        for c in chunks:
            fp = hashlib.md5(c.chunk_text.strip().lower().encode()).hexdigest()
            if fp in seen:
                dup += 1
            seen.add(fp)
        redundancy = round(dup / max(len(chunks), 1), 4)

        # Recommendation logic
        if avg_recall < 0.5 or avg_conflict > 0.2:
            recommendation = "rollback"
        elif avg_recall < 0.7 or avg_conflict > 0.1:
            recommendation = "review_required"
        else:
            recommendation = "promote_to_active"

        return EvalMetrics(
            enabled=True,
            preview_queries=n,
            recall_at_k=avg_recall,
            constraint_conflict_rate=avg_conflict,
            redundancy_rate=redundancy,
            avg_latency_ms=avg_latency,
            recommendation=recommendation,
        )

    # ── Retrieval pipeline ────────────────────────────────────────
    # query → embed → search → rerank → filter → return

    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        """Full retrieval pipeline with hybrid search support."""
        t0 = utcnow()

        # Step 1: Embed query
        dim = len(next(iter(self._vectors.values()), []))
        if dim == 0:
            return RetrievalResponse(query_text=query.query_text)
        q_vec = self._generate_embedding(query.query_text, dim)
        if q_vec is None:
            return RetrievalResponse(query_text=query.query_text)

        # Step 2: Filter-first (role / tags / locale / strength)
        candidates = self._filter_candidates(query)

        # Step 3: Semantic similarity (pgvector cosine/L2 simulation)
        scored: list[tuple[str, float]] = []
        for cid in candidates:
            vec = self._vectors.get(cid)
            if vec is None:
                continue
            sem_score = self._cosine_similarity(q_vec, vec)
            scored.append((cid, sem_score))

        # Step 4: BM25 keyword score (simplified TF simulation)
        keyword_scores: dict[str, float] = {}
        query_terms = set(query.query_text.lower().split())
        for cid in candidates:
            chunk = self._chunks.get(cid)
            if not chunk:
                continue
            chunk_terms = set(chunk.chunk_text.lower().split())
            overlap = len(query_terms & chunk_terms)
            keyword_scores[cid] = overlap / max(len(query_terms), 1)

        # Step 5: Hybrid fusion
        alpha = query.hybrid_alpha
        fused: list[tuple[str, float, float, float]] = []
        for cid, sem in scored:
            kw = keyword_scores.get(cid, 0.0)
            combined = alpha * sem + (1.0 - alpha) * kw
            fused.append((cid, combined, sem, kw))
        fused.sort(key=lambda x: x[1], reverse=True)

        # Step 6: Reranking (simulate cross-encoder boost)
        if query.enable_reranking:
            fused = self._rerank(fused, query.query_text)

        # Step 7: Top-k
        top = fused[: query.top_k]

        # Build results
        results: list[RetrievalResult] = []
        conflict_candidates: list[RetrievalResult] = []
        for cid, score, sem, kw in top:
            chunk = self._chunks.get(cid)
            if not chunk:
                continue
            rr = RetrievalResult(
                chunk_id=cid,
                chunk_text=chunk.chunk_text,
                score=round(score, 4),
                semantic_score=round(sem, 4),
                keyword_score=round(kw, 4),
                rerank_score=round(score, 4),
                metadata=chunk.metadata,
            )
            results.append(rr)

        # Detect conflicts: hard_constraint items with opposing content
        hard = [r for r in results if r.metadata.strength == Strength.HARD_CONSTRAINT]
        soft = [r for r in results if r.metadata.strength == Strength.SOFT_PREFERENCE]
        if hard and soft:
            conflict_candidates = soft[:2]

        elapsed_ms = round((utcnow() - t0).total_seconds() * 1000, 2)

        return RetrievalResponse(
            query_text=query.query_text,
            results=results,
            total_candidates=len(candidates),
            filtered_count=len(candidates) - len(results),
            latency_ms=elapsed_ms,
            conflict_candidates=conflict_candidates,
        )

    def _filter_candidates(self, query: RetrievalQuery) -> list[str]:
        """Filter-first: role → tags → locale → strength then vector search."""
        candidates: list[str] = []
        for cid, chunk in self._chunks.items():
            md = chunk.metadata
            if md.status != ItemStatus.ACTIVE:
                continue
            if query.role_filter and md.role not in query.role_filter:
                continue
            if query.tag_filter and not set(query.tag_filter) & set(md.tags):
                continue
            if query.locale_filter and query.locale_filter not in md.culture_tags:
                continue
            if query.strength_filter and md.strength != query.strength_filter:
                continue
            candidates.append(cid)
        return candidates or list(self._chunks.keys())

    def _rerank(
        self,
        fused: list[tuple[str, float, float, float]],
        query_text: str,
    ) -> list[tuple[str, float, float, float]]:
        """Simulate cross-encoder reranking with query-overlap boost."""
        q_terms = set(query_text.lower().split())
        reranked: list[tuple[str, float, float, float]] = []
        for cid, score, sem, kw in fused:
            chunk = self._chunks.get(cid)
            boost = 0.0
            if chunk:
                c_terms = set(chunk.chunk_text.lower().split())
                overlap = len(q_terms & c_terms) / max(len(q_terms), 1)
                boost = overlap * 0.1
            new_score = score + boost
            reranked.append((cid, round(new_score, 4), sem, kw))
        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked

    # ── pgvector-compatible similarity functions ──────────────────

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return round(dot / (na * nb), 6)

    @staticmethod
    def _l2_distance(a: list[float], b: list[float]) -> float:
        return round(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))), 6)

    @staticmethod
    def _inner_product(a: list[float], b: list[float]) -> float:
        return round(sum(x * y for x, y in zip(a, b)), 6)

    # ── Utilities ─────────────────────────────────────────────────

    def _transition(
        self, ctx: SkillContext, from_s: PipelineStage, to_s: PipelineStage,
    ) -> None:
        self._record_state(ctx, from_s.value, to_s.value)

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    @staticmethod
    def _chunk_id(item_id: str, index: int) -> str:
        return f"chk_{item_id}_{index:04d}"

    def _dedup_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        seen: set[str] = set()
        result: list[Chunk] = []
        for c in chunks:
            fp = hashlib.md5(c.chunk_text.strip().lower().encode()).hexdigest()
            if fp not in seen:
                seen.add(fp)
                result.append(c)
        return result

    @staticmethod
    def _stage_record(
        stage: PipelineStage, t0: Any, items_processed: int,
    ) -> StageRecord:
        now = utcnow()
        return StageRecord(
            stage=stage,
            started_at=t0.isoformat(),
            completed_at=now.isoformat(),
            duration_sec=round((now - t0).total_seconds(), 3),
            items_processed=items_processed,
        )


# Backward-compatible alias
RagEmbeddingService = RagPipelineService
