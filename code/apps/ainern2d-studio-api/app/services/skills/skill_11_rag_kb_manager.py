"""SKILL 11: RagKBManagerService — 业务逻辑实现。
参考规格: SKILL_11_RAG_KB_MANAGER.md
状态: SERVICE_READY

State machine:
  INIT → LOADING_KB → VALIDATING_ENTRIES → DEDUPLICATING →
  INDEXING → VERSIONING → PUBLISHING → READY | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_11 import (
    BulkImportItem,
    CoverageStatEntry,
    DedupResult,
    KBEntry,
    KBItemTags,
    KBManifest,
    KBManagerSummary,
    KBVersion,
    KBVersionDiff,
    PreviewSearchHit,
    QualityIssue,
    ReviewDecision,
    ReviewRequiredItem,
    SearchIndexStats,
    Skill11FeatureFlags,
    Skill11Input,
    Skill11Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from ainern2d_shared.utils.time import utcnow

# ── In-memory KB store (per-process; replaced by DB in production) ───────────

_KB_STORES: dict[str, dict[str, KBEntry]] = {}
_KB_VERSIONS: dict[str, list[KBVersion]] = {}
_KB_ACTIVE_VERSION: dict[str, str] = {}

_VALID_ACTIONS = frozenset(
    {"sync", "create", "update", "delete", "publish", "rollback", "search", "import", "export"}
)
_VALID_ENTRY_TYPES = frozenset(
    {"entity_profile", "culture_pack", "style_guide", "prompt_recipe", "asset_catalog", "glossary"}
)
_VALID_STATUSES = frozenset({"draft", "active", "deprecated", "archived"})
_VALID_STRENGTHS = frozenset({"hard_constraint", "soft_hint"})


class RagKBManagerService(BaseSkillService[Skill11Input, Skill11Output]):
    """SKILL 11 — RAG Knowledge Base Manager.

    Full CRUD + versioning + review + dedup + quality + indexing.

    State machine:
      INIT → LOADING_KB → VALIDATING_ENTRIES → DEDUPLICATING →
      INDEXING → VERSIONING → PUBLISHING → READY | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_11"
    skill_name = "RagKBManagerService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Main entry ───────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill11Input, ctx: SkillContext) -> Skill11Output:  # noqa: C901
        self._record_state(ctx, "INIT", "LOADING_KB")
        now = utcnow().isoformat()
        events: list[str] = []
        warnings: list[str] = []

        action = input_dto.action or "sync"
        if action not in _VALID_ACTIONS:
            self._record_state(ctx, "LOADING_KB", "FAILED")
            raise ValueError(f"RAG-VALIDATION-001: unsupported KB action '{action}'")

        kb_id = input_dto.kb_id or str(uuid.uuid4())
        ff = input_dto.feature_flags

        # Ensure store exists
        if kb_id not in _KB_STORES:
            _KB_STORES[kb_id] = {}
            _KB_VERSIONS[kb_id] = []

        store = _KB_STORES[kb_id]
        self._record_state(ctx, "LOADING_KB", "VALIDATING_ENTRIES")

        # ── Dispatch action ──────────────────────────────────────────────
        if action == "create":
            return self._action_create(kb_id, input_dto, ctx, ff, store, now, events, warnings)
        if action == "update":
            return self._action_update(kb_id, input_dto, ctx, ff, store, now, events, warnings)
        if action == "delete":
            return self._action_delete(kb_id, input_dto, ctx, ff, store, now, events, warnings)
        if action == "publish":
            return self._action_publish(kb_id, input_dto, ctx, ff, store, now, events, warnings)
        if action == "rollback":
            return self._action_rollback(kb_id, input_dto, ctx, ff, store, now, events, warnings)
        if action == "search":
            return self._action_search(kb_id, input_dto, ctx, store, now, events, warnings)
        if action == "import":
            return self._action_import(kb_id, input_dto, ctx, ff, store, now, events, warnings)
        if action == "export":
            return self._action_export(kb_id, input_dto, ctx, store, now, events, warnings)
        # sync — default full pipeline
        return self._action_sync(kb_id, input_dto, ctx, ff, store, now, events, warnings)

    # ── Action: create ───────────────────────────────────────────────────────

    def _action_create(
        self,
        kb_id: str,
        dto: Skill11Input,
        ctx: SkillContext,
        ff: Skill11FeatureFlags,
        store: dict[str, KBEntry],
        now: str,
        events: list[str],
        warnings: list[str],
    ) -> Skill11Output:
        quality_issues: list[QualityIssue] = []
        review_items: list[ReviewRequiredItem] = []
        created: list[KBEntry] = []

        for entry in dto.entries:
            issues = self._validate_entry(entry, ff)
            quality_issues.extend(issues)
            if any(i.severity == "error" for i in issues):
                warnings.append(f"Entry '{entry.entry_id}' has validation errors; skipped")
                continue

            entry.entry_id = entry.entry_id or f"KI_{uuid.uuid4().hex[:8]}"
            entry.created_at = entry.created_at or now
            entry.updated_at = now
            entry.embedding_status = "stale"

            # Review workflow gate
            if ff.enable_review_workflow and entry.strength == "hard_constraint":
                entry.status = "draft"
                review_items.append(ReviewRequiredItem(
                    item_id=entry.entry_id,
                    reason="hard_constraint requires review before activation",
                    severity="high",
                ))

            # Max entries per type check
            type_count = sum(1 for e in store.values() if e.entry_type == entry.entry_type)
            if type_count >= ff.max_entries_per_type:
                warnings.append(
                    f"Max entries ({ff.max_entries_per_type}) for type '{entry.entry_type}' reached"
                )
                continue

            store[entry.entry_id] = entry
            created.append(entry)
            events.append("kb.item.created")

        self._record_state(ctx, "VALIDATING_ENTRIES", "DEDUPLICATING")
        dedup_results = self._deduplicate(store, ff)

        self._record_state(ctx, "DEDUPLICATING", "INDEXING")
        index_stats = self._rebuild_indices(store)

        terminal = "REVIEW_REQUIRED" if review_items else "READY"
        self._record_state(ctx, "INDEXING", terminal)

        if ff.version_auto_increment:
            self._auto_increment_version(kb_id, store, now)

        summary = self._build_summary(store, dedup_results, quality_issues, review_items)
        self._log_completion(ctx, kb_id, "create", len(created))

        return Skill11Output(
            kb_id=kb_id,
            kb_version_id=_KB_ACTIVE_VERSION.get(kb_id, ""),
            status=terminal,
            entries=created,
            entry_count=len(store),
            review_required_items=review_items,
            dedup_results=dedup_results,
            quality_issues=quality_issues,
            index_stats=index_stats,
            summary=summary,
            events_emitted=events,
            warnings=warnings,
        )

    # ── Action: update ───────────────────────────────────────────────────────

    def _action_update(
        self,
        kb_id: str,
        dto: Skill11Input,
        ctx: SkillContext,
        ff: Skill11FeatureFlags,
        store: dict[str, KBEntry],
        now: str,
        events: list[str],
        warnings: list[str],
    ) -> Skill11Output:
        quality_issues: list[QualityIssue] = []
        review_items: list[ReviewRequiredItem] = []
        updated: list[KBEntry] = []

        for entry in dto.entries:
            if entry.entry_id not in store:
                warnings.append(f"Entry '{entry.entry_id}' not found; skipping update")
                continue

            issues = self._validate_entry(entry, ff)
            quality_issues.extend(issues)

            existing = store[entry.entry_id]
            # Incremental merge: only overwrite non-empty fields
            merged = self._merge_entry(existing, entry)
            merged.updated_at = now
            merged.embedding_status = "stale"

            if ff.enable_review_workflow and merged.strength == "hard_constraint":
                review_items.append(ReviewRequiredItem(
                    item_id=merged.entry_id,
                    reason="hard_constraint update requires review",
                    severity="high",
                ))

            store[merged.entry_id] = merged
            updated.append(merged)
            events.append("kb.item.updated")

        # Apply review decisions
        decisions = self._apply_review_decisions(dto.review_decisions, store, now)

        self._record_state(ctx, "VALIDATING_ENTRIES", "DEDUPLICATING")
        dedup_results = self._deduplicate(store, ff)

        self._record_state(ctx, "DEDUPLICATING", "INDEXING")
        index_stats = self._rebuild_indices(store)

        terminal = "REVIEW_REQUIRED" if review_items else "READY"
        self._record_state(ctx, "INDEXING", terminal)

        summary = self._build_summary(store, dedup_results, quality_issues, review_items)
        self._log_completion(ctx, kb_id, "update", len(updated))

        return Skill11Output(
            kb_id=kb_id,
            kb_version_id=_KB_ACTIVE_VERSION.get(kb_id, ""),
            status=terminal,
            entries=updated,
            entry_count=len(store),
            review_required_items=review_items,
            review_decisions=decisions,
            dedup_results=dedup_results,
            quality_issues=quality_issues,
            index_stats=index_stats,
            summary=summary,
            events_emitted=events,
            warnings=warnings,
        )

    # ── Action: delete ───────────────────────────────────────────────────────

    def _action_delete(
        self,
        kb_id: str,
        dto: Skill11Input,
        ctx: SkillContext,
        ff: Skill11FeatureFlags,
        store: dict[str, KBEntry],
        now: str,
        events: list[str],
        warnings: list[str],
    ) -> Skill11Output:
        deleted_ids: list[str] = []
        for eid in dto.delete_entry_ids:
            if eid in store:
                del store[eid]
                deleted_ids.append(eid)
            else:
                warnings.append(f"Entry '{eid}' not found for deletion")

        self._record_state(ctx, "VALIDATING_ENTRIES", "INDEXING")
        index_stats = self._rebuild_indices(store)
        self._record_state(ctx, "INDEXING", "READY")

        summary = self._build_summary(store, [], [], [])
        self._log_completion(ctx, kb_id, "delete", len(deleted_ids))

        return Skill11Output(
            kb_id=kb_id,
            kb_version_id=_KB_ACTIVE_VERSION.get(kb_id, ""),
            status="READY",
            entry_count=len(store),
            index_stats=index_stats,
            summary=summary,
            events_emitted=events,
            warnings=warnings,
        )

    # ── Action: publish ──────────────────────────────────────────────────────

    def _action_publish(
        self,
        kb_id: str,
        dto: Skill11Input,
        ctx: SkillContext,
        ff: Skill11FeatureFlags,
        store: dict[str, KBEntry],
        now: str,
        events: list[str],
        warnings: list[str],
    ) -> Skill11Output:
        review_items: list[ReviewRequiredItem] = []

        # Gate: no un-reviewed hard_constraints
        if ff.enable_review_workflow:
            for entry in store.values():
                if entry.strength == "hard_constraint" and entry.status == "draft":
                    review_items.append(ReviewRequiredItem(
                        item_id=entry.entry_id,
                        reason="hard_constraint must be reviewed before publish",
                        severity="high",
                    ))
            if review_items:
                self._record_state(ctx, "VALIDATING_ENTRIES", "REVIEW_REQUIRED")
                return Skill11Output(
                    kb_id=kb_id,
                    status="REVIEW_REQUIRED",
                    review_required_items=review_items,
                    entry_count=len(store),
                    events_emitted=events,
                    warnings=warnings,
                )

        self._record_state(ctx, "VALIDATING_ENTRIES", "VERSIONING")

        active_ids = [eid for eid, e in store.items() if e.status == "active"]
        deprecated_ids = [eid for eid, e in store.items() if e.status == "deprecated"]

        # Compute diff against previous version
        prev_versions = _KB_VERSIONS.get(kb_id, [])
        diff = self._compute_version_diff(prev_versions, active_ids, deprecated_ids)

        version_label = dto.version_label or self._next_version_label(kb_id)
        content_hash = self._compute_content_hash(store, active_ids)
        version_id = f"KB_{kb_id[:8]}_{version_label}_{uuid.uuid4().hex[:6]}"

        version = KBVersion(
            kb_version_id=version_id,
            parent_version_id=_KB_ACTIVE_VERSION.get(kb_id, ""),
            version_label=version_label,
            release_notes=dto.release_notes,
            included_item_ids=active_ids,
            deprecated_item_ids=deprecated_ids,
            diff=diff,
            target_embedding_model=dto.target_embedding_model,
            chunking_policy_id=dto.chunking_policy_id,
            content_hash=content_hash,
            status="published",
            created_by=ctx.tenant_id,
            created_at=now,
        )
        _KB_VERSIONS.setdefault(kb_id, []).append(version)
        _KB_ACTIVE_VERSION[kb_id] = version_id

        self._record_state(ctx, "VERSIONING", "PUBLISHING")
        events.append("kb.version.release.requested")

        index_stats = self._rebuild_indices(store)

        # Build manifest
        manifest = self._build_manifest(kb_id, version, store, now)

        self._record_state(ctx, "PUBLISHING", "READY")
        events.append("kb.version.released")

        # Auto-publish triggers downstream embedding event
        if ff.auto_publish:
            events.append("rag.chunking.started")

        summary = self._build_summary(store, [], [], [])
        self._log_completion(ctx, kb_id, "publish", len(active_ids))

        return Skill11Output(
            kb_id=kb_id,
            kb_version_id=version_id,
            release_manifest_hash=content_hash,
            active_recipe_set_id=f"recipe_{kb_id[:8]}",
            approval_ticket_id=f"APR_{uuid.uuid4().hex[:8]}",
            status="READY",
            manifest=manifest,
            current_version=version,
            version_history=_KB_VERSIONS.get(kb_id, []),
            entry_count=len(store),
            index_stats=index_stats,
            summary=summary,
            events_emitted=events,
            warnings=warnings,
        )

    # ── Action: rollback ─────────────────────────────────────────────────────

    def _action_rollback(
        self,
        kb_id: str,
        dto: Skill11Input,
        ctx: SkillContext,
        ff: Skill11FeatureFlags,
        store: dict[str, KBEntry],
        now: str,
        events: list[str],
        warnings: list[str],
    ) -> Skill11Output:
        target_vid = dto.rollback_target_version_id
        versions = _KB_VERSIONS.get(kb_id, [])

        target_version: KBVersion | None = None
        for v in versions:
            if v.kb_version_id == target_vid:
                target_version = v
                break

        if target_version is None:
            self._record_state(ctx, "VALIDATING_ENTRIES", "FAILED")
            raise ValueError(f"RAG-VALIDATION-002: rollback target version '{target_vid}' not found")

        self._record_state(ctx, "VALIDATING_ENTRIES", "VERSIONING")

        # Restore state: mark only included items as active
        for eid, entry in store.items():
            if eid in target_version.included_item_ids:
                entry.status = "active"
            elif eid in target_version.deprecated_item_ids:
                entry.status = "deprecated"

        # Record rollback version
        rollback_version = KBVersion(
            kb_version_id=f"KB_RB_{uuid.uuid4().hex[:8]}",
            parent_version_id=_KB_ACTIVE_VERSION.get(kb_id, ""),
            version_label=f"rollback_to_{target_version.version_label}",
            release_notes=dto.rollback_reason or f"Rolled back to {target_vid}",
            included_item_ids=target_version.included_item_ids,
            deprecated_item_ids=target_version.deprecated_item_ids,
            status="published",
            created_by=ctx.tenant_id,
            created_at=now,
        )
        _KB_VERSIONS.setdefault(kb_id, []).append(rollback_version)
        _KB_ACTIVE_VERSION[kb_id] = rollback_version.kb_version_id

        self._record_state(ctx, "VERSIONING", "READY")
        events.append("kb.version.rolled_back")

        index_stats = self._rebuild_indices(store)
        summary = self._build_summary(store, [], [], [])
        self._log_completion(ctx, kb_id, "rollback", 0)

        return Skill11Output(
            kb_id=kb_id,
            kb_version_id=rollback_version.kb_version_id,
            status="READY",
            current_version=rollback_version,
            version_history=_KB_VERSIONS.get(kb_id, []),
            entry_count=len(store),
            index_stats=index_stats,
            summary=summary,
            events_emitted=events,
            warnings=warnings,
        )

    # ── Action: search ───────────────────────────────────────────────────────

    def _action_search(
        self,
        kb_id: str,
        dto: Skill11Input,
        ctx: SkillContext,
        store: dict[str, KBEntry],
        now: str,
        events: list[str],
        warnings: list[str],
    ) -> Skill11Output:
        self._record_state(ctx, "VALIDATING_ENTRIES", "INDEXING")

        query = dto.search_query
        if query is None:
            self._record_state(ctx, "INDEXING", "FAILED")
            raise ValueError("RAG-VALIDATION-003: search_query is required for search action")

        results = self._search_entries(store, query)
        self._record_state(ctx, "INDEXING", "READY")

        return Skill11Output(
            kb_id=kb_id,
            kb_version_id=_KB_ACTIVE_VERSION.get(kb_id, ""),
            status="READY",
            search_results=results,
            entry_count=len(store),
            events_emitted=events,
            warnings=warnings,
        )

    # ── Action: import ───────────────────────────────────────────────────────

    def _action_import(
        self,
        kb_id: str,
        dto: Skill11Input,
        ctx: SkillContext,
        ff: Skill11FeatureFlags,
        store: dict[str, KBEntry],
        now: str,
        events: list[str],
        warnings: list[str],
    ) -> Skill11Output:
        imported: list[KBEntry] = []
        quality_issues: list[QualityIssue] = []

        for item in dto.import_items:
            entry = KBEntry(
                entry_id=item.entry_id or f"KI_{uuid.uuid4().hex[:8]}",
                role=item.role,
                title=item.title,
                content_type=item.content_type,
                content_markdown=item.content_markdown,
                entry_type=item.entry_type,
                tags=item.tags,
                flat_tags=item.flat_tags,
                strength=item.strength,
                status=item.status,
                visibility=item.visibility,
                source=item.source,
                metadata=item.metadata,
                embedding_status="stale",
                created_at=now,
                updated_at=now,
            )

            issues = self._validate_entry(entry, ff)
            quality_issues.extend(issues)
            if any(i.severity == "error" for i in issues):
                warnings.append(f"Import entry '{entry.entry_id}' has errors; skipped")
                continue

            store[entry.entry_id] = entry
            imported.append(entry)
            events.append("kb.item.created")

        self._record_state(ctx, "VALIDATING_ENTRIES", "DEDUPLICATING")
        dedup_results = self._deduplicate(store, ff)

        self._record_state(ctx, "DEDUPLICATING", "INDEXING")
        index_stats = self._rebuild_indices(store)
        self._record_state(ctx, "INDEXING", "READY")

        summary = self._build_summary(store, dedup_results, quality_issues, [])
        self._log_completion(ctx, kb_id, "import", len(imported))

        return Skill11Output(
            kb_id=kb_id,
            kb_version_id=_KB_ACTIVE_VERSION.get(kb_id, ""),
            status="READY",
            entries=imported,
            entry_count=len(store),
            dedup_results=dedup_results,
            quality_issues=quality_issues,
            index_stats=index_stats,
            summary=summary,
            events_emitted=events,
            warnings=warnings,
        )

    # ── Action: export ───────────────────────────────────────────────────────

    def _action_export(
        self,
        kb_id: str,
        dto: Skill11Input,
        ctx: SkillContext,
        store: dict[str, KBEntry],
        now: str,
        events: list[str],
        warnings: list[str],
    ) -> Skill11Output:
        self._record_state(ctx, "VALIDATING_ENTRIES", "READY")

        active_version_id = _KB_ACTIVE_VERSION.get(kb_id, "")
        versions = _KB_VERSIONS.get(kb_id, [])
        current_version = next(
            (v for v in reversed(versions) if v.kb_version_id == active_version_id), None
        )

        manifest = self._build_manifest(
            kb_id,
            current_version or KBVersion(kb_version_id=active_version_id),
            store,
            now,
        )

        return Skill11Output(
            kb_id=kb_id,
            kb_version_id=active_version_id,
            status="READY",
            manifest=manifest,
            entries=list(store.values()),
            entry_count=len(store),
            version_history=versions,
            events_emitted=events,
            warnings=warnings,
        )

    # ── Action: sync (full pipeline) ─────────────────────────────────────────

    def _action_sync(
        self,
        kb_id: str,
        dto: Skill11Input,
        ctx: SkillContext,
        ff: Skill11FeatureFlags,
        store: dict[str, KBEntry],
        now: str,
        events: list[str],
        warnings: list[str],
    ) -> Skill11Output:
        quality_issues: list[QualityIssue] = []
        review_items: list[ReviewRequiredItem] = []

        # Upsert entries
        for entry in dto.entries:
            issues = self._validate_entry(entry, ff)
            quality_issues.extend(issues)
            entry.entry_id = entry.entry_id or f"KI_{uuid.uuid4().hex[:8]}"
            entry.updated_at = now
            entry.created_at = entry.created_at or now
            entry.embedding_status = "stale"

            if ff.enable_review_workflow and entry.strength == "hard_constraint" and entry.status != "active":
                review_items.append(ReviewRequiredItem(
                    item_id=entry.entry_id,
                    reason="hard_constraint requires review",
                    severity="high",
                ))

            store[entry.entry_id] = entry
            events.append("kb.item.updated" if entry.entry_id in store else "kb.item.created")

        # Apply reviews
        decisions = self._apply_review_decisions(dto.review_decisions, store, now)

        self._record_state(ctx, "VALIDATING_ENTRIES", "DEDUPLICATING")
        dedup_results = self._deduplicate(store, ff)

        self._record_state(ctx, "DEDUPLICATING", "INDEXING")
        index_stats = self._rebuild_indices(store)

        self._record_state(ctx, "INDEXING", "VERSIONING")

        # Auto version if enabled
        if ff.version_auto_increment:
            self._auto_increment_version(kb_id, store, now)

        terminal = "REVIEW_REQUIRED" if review_items else "READY"

        # Auto publish
        if ff.auto_publish and not review_items:
            self._record_state(ctx, "VERSIONING", "PUBLISHING")
            active_ids = [eid for eid, e in store.items() if e.status == "active"]
            content_hash = self._compute_content_hash(store, active_ids)
            vlabel = self._next_version_label(kb_id)
            vid = f"KB_{kb_id[:8]}_{vlabel}_{uuid.uuid4().hex[:6]}"
            version = KBVersion(
                kb_version_id=vid,
                parent_version_id=_KB_ACTIVE_VERSION.get(kb_id, ""),
                version_label=vlabel,
                release_notes="Auto-published sync",
                included_item_ids=active_ids,
                deprecated_item_ids=[eid for eid, e in store.items() if e.status == "deprecated"],
                content_hash=content_hash,
                status="published",
                created_by=ctx.tenant_id,
                created_at=now,
            )
            _KB_VERSIONS.setdefault(kb_id, []).append(version)
            _KB_ACTIVE_VERSION[kb_id] = vid
            events.extend(["kb.version.release.requested", "kb.version.released", "rag.chunking.started"])
            self._record_state(ctx, "PUBLISHING", terminal)
        else:
            self._record_state(ctx, "VERSIONING", terminal)

        summary = self._build_summary(store, dedup_results, quality_issues, review_items)
        self._log_completion(ctx, kb_id, "sync", len(dto.entries))

        return Skill11Output(
            kb_id=kb_id,
            kb_version_id=_KB_ACTIVE_VERSION.get(kb_id, ""),
            release_manifest_hash=self._compute_content_hash(
                store, [eid for eid in store if store[eid].status == "active"]
            ),
            active_recipe_set_id=f"recipe_{kb_id[:8]}",
            status=terminal,
            current_version=(_KB_VERSIONS.get(kb_id, [None]) or [None])[-1],
            version_history=_KB_VERSIONS.get(kb_id, []),
            entries=list(store.values()),
            entry_count=len(store),
            review_required_items=review_items,
            review_decisions=decisions,
            dedup_results=dedup_results,
            quality_issues=quality_issues,
            index_stats=index_stats,
            summary=summary,
            events_emitted=events,
            warnings=warnings,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ══════════════════════════════════════════════════════════════════════════

    # ── Validation ───────────────────────────────────────────────────────────

    @staticmethod
    def _validate_entry(entry: KBEntry, ff: Skill11FeatureFlags) -> list[QualityIssue]:
        """Validate KB entry completeness and consistency."""
        issues: list[QualityIssue] = []

        if not entry.title and not entry.content_markdown:
            issues.append(QualityIssue(
                item_id=entry.entry_id,
                issue_type="missing_field",
                message="Entry must have at least a title or content_markdown",
                severity="error",
            ))

        if entry.entry_type and entry.entry_type not in _VALID_ENTRY_TYPES:
            issues.append(QualityIssue(
                item_id=entry.entry_id,
                issue_type="missing_field",
                message=f"Invalid entry_type '{entry.entry_type}'",
                severity="warning",
            ))

        if entry.strength and entry.strength not in _VALID_STRENGTHS:
            issues.append(QualityIssue(
                item_id=entry.entry_id,
                issue_type="missing_field",
                message=f"Invalid strength '{entry.strength}'",
                severity="warning",
            ))

        if entry.status and entry.status not in _VALID_STATUSES:
            issues.append(QualityIssue(
                item_id=entry.entry_id,
                issue_type="missing_field",
                message=f"Invalid status '{entry.status}'",
                severity="warning",
            ))

        if not entry.role:
            issues.append(QualityIssue(
                item_id=entry.entry_id,
                issue_type="missing_field",
                message="Missing role field",
                severity="warning",
            ))

        # Cross-ref integrity: check tag fields are not entirely empty
        tags = entry.tags
        all_tags_empty = (
            not tags.culture_pack and not tags.genre and not tags.motion_level
            and not tags.shot_type and not tags.era and not tags.style_mode
            and not tags.custom and not entry.flat_tags
        )
        if all_tags_empty:
            issues.append(QualityIssue(
                item_id=entry.entry_id,
                issue_type="weak_content",
                message="Entry has no tags; discoverability will be poor",
                severity="warning",
            ))

        return issues

    # ── Incremental merge ────────────────────────────────────────────────────

    @staticmethod
    def _merge_entry(existing: KBEntry, patch: KBEntry) -> KBEntry:
        """Merge patch into existing, keeping existing values for empty patch fields."""
        data = existing.model_dump()
        patch_data = patch.model_dump(exclude_defaults=True)
        # Only overwrite non-default patch fields
        for key, val in patch_data.items():
            if key in ("entry_id", "created_at"):
                continue
            if val is not None and val != "" and val != [] and val != {}:
                data[key] = val
        return KBEntry(**data)

    # ── Deduplication ────────────────────────────────────────────────────────

    @staticmethod
    def _deduplicate(store: dict[str, KBEntry], ff: Skill11FeatureFlags) -> list[DedupResult]:
        """Detect and merge duplicate entries based on title + content similarity."""
        results: list[DedupResult] = []
        ids = list(store.keys())
        seen: set[str] = set()

        for i, id_a in enumerate(ids):
            if id_a in seen:
                continue
            for id_b in ids[i + 1:]:
                if id_b in seen:
                    continue
                a, b = store[id_a], store[id_b]
                sim = RagKBManagerService._jaccard_similarity(
                    (a.title + " " + a.content_markdown).lower().split(),
                    (b.title + " " + b.content_markdown).lower().split(),
                )
                if sim >= ff.dedup_threshold:
                    # Keep the one with more content
                    if len(a.content_markdown) >= len(b.content_markdown):
                        kept, merged = id_a, id_b
                    else:
                        kept, merged = id_b, id_a
                    results.append(DedupResult(kept_id=kept, merged_id=merged, similarity=round(sim, 3), action="merged"))
                    # Merge tags from merged into kept
                    kept_entry = store[kept]
                    merged_entry = store[merged]
                    kept_entry.flat_tags = list(set(kept_entry.flat_tags + merged_entry.flat_tags))
                    del store[merged]
                    seen.add(merged)

        return results

    @staticmethod
    def _jaccard_similarity(a: list[str], b: list[str]) -> float:
        set_a, set_b = set(a), set(b)
        if not set_a and not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union) if union else 0.0

    # ── Search index ─────────────────────────────────────────────────────────

    @staticmethod
    def _rebuild_indices(store: dict[str, KBEntry]) -> SearchIndexStats:
        """Rebuild in-memory search indices and return stats."""
        tag_idx: set[str] = set()
        type_idx: set[str] = set()
        culture_idx: set[str] = set()
        role_idx: set[str] = set()

        for entry in store.values():
            # Flat tags
            for t in entry.flat_tags:
                tag_idx.add(t)
            # Structured tags
            for t in entry.tags.culture_pack:
                culture_idx.add(t)
                tag_idx.add(t)
            for t in entry.tags.genre:
                tag_idx.add(t)
            for t in entry.tags.motion_level:
                tag_idx.add(t)
            for t in entry.tags.shot_type:
                tag_idx.add(t)
            for t in entry.tags.custom:
                tag_idx.add(t)
            type_idx.add(entry.entry_type)
            if entry.role:
                role_idx.add(entry.role)

        return SearchIndexStats(
            tag_index_size=len(tag_idx),
            type_index_size=len(type_idx),
            culture_index_size=len(culture_idx),
            role_index_size=len(role_idx),
            total_indexed=len(store),
        )

    # ── Preview search ───────────────────────────────────────────────────────

    @staticmethod
    def _search_entries(
        store: dict[str, KBEntry],
        query: Any,
    ) -> list[PreviewSearchHit]:
        """Simple keyword + filter search over in-memory store."""
        hits: list[PreviewSearchHit] = []
        query_tokens = set(query.query_text.lower().split()) if query.query_text else set()

        for entry in store.values():
            if entry.status not in ("active", "draft"):
                continue

            # Role filter
            if query.role_filter and entry.role not in query.role_filter:
                continue
            # Culture filter
            if query.culture_filter and not set(entry.tags.culture_pack) & set(query.culture_filter):
                continue
            # Genre filter
            if query.genre_filter and not set(entry.tags.genre) & set(query.genre_filter):
                continue
            # Strength filter
            if query.strength_filter and entry.strength != query.strength_filter:
                continue

            # Score by token overlap
            entry_tokens = set((entry.title + " " + entry.content_markdown).lower().split())
            if query_tokens:
                overlap = len(query_tokens & entry_tokens)
                score = overlap / len(query_tokens) if query_tokens else 0.0
            else:
                score = 1.0  # No query = return all matching filters

            if score > 0.0 or not query_tokens:
                # Check hard_constraint conflicts
                conflict_flags: list[str] = []
                if entry.strength == "hard_constraint":
                    conflict_flags.append("hard_constraint_active")

                snippet = entry.content_markdown[:200] if entry.content_markdown else entry.title
                hits.append(PreviewSearchHit(
                    item_id=entry.entry_id,
                    title=entry.title,
                    role=entry.role,
                    score=round(score, 3),
                    snippet=snippet,
                    tags=entry.tags,
                    strength=entry.strength,
                    version=entry.version,
                    conflict_flags=conflict_flags,
                ))

        # Sort by score descending, limit to top_k
        hits.sort(key=lambda h: h.score, reverse=True)
        top_k = query.top_k if query.top_k > 0 else 10
        return hits[:top_k]

    # ── Versioning helpers ───────────────────────────────────────────────────

    @staticmethod
    def _next_version_label(kb_id: str) -> str:
        versions = _KB_VERSIONS.get(kb_id, [])
        return f"v{len(versions) + 1}.0"

    @staticmethod
    def _auto_increment_version(kb_id: str, store: dict[str, KBEntry], now: str) -> None:
        """Create a draft version snapshot without publishing."""
        if not store:
            return
        vlabel = RagKBManagerService._next_version_label(kb_id)
        vid = f"KB_{kb_id[:8]}_{vlabel}_draft"
        version = KBVersion(
            kb_version_id=vid,
            version_label=vlabel,
            included_item_ids=[eid for eid, e in store.items() if e.status in ("active", "draft")],
            deprecated_item_ids=[eid for eid, e in store.items() if e.status == "deprecated"],
            status="draft",
            created_at=now,
        )
        existing = _KB_VERSIONS.get(kb_id, [])
        # Replace existing draft or append
        if existing and existing[-1].status == "draft":
            existing[-1] = version
        else:
            _KB_VERSIONS.setdefault(kb_id, []).append(version)

    @staticmethod
    def _compute_version_diff(
        prev_versions: list[KBVersion],
        active_ids: list[str],
        deprecated_ids: list[str],
    ) -> KBVersionDiff:
        if not prev_versions:
            return KBVersionDiff(added_ids=active_ids, deprecated_ids=deprecated_ids)

        prev = prev_versions[-1]
        prev_set = set(prev.included_item_ids)
        curr_set = set(active_ids)

        return KBVersionDiff(
            added_ids=sorted(curr_set - prev_set),
            removed_ids=sorted(prev_set - curr_set),
            deprecated_ids=deprecated_ids,
        )

    @staticmethod
    def _compute_content_hash(store: dict[str, KBEntry], active_ids: list[str]) -> str:
        content = "|".join(
            f"{eid}:{store[eid].version}:{store[eid].updated_at}"
            for eid in sorted(active_ids)
            if eid in store
        )
        return f"sha256:{hashlib.sha256(content.encode()).hexdigest()[:16]}"

    # ── Review workflow ──────────────────────────────────────────────────────

    @staticmethod
    def _apply_review_decisions(
        decisions: list[ReviewDecision],
        store: dict[str, KBEntry],
        now: str,
    ) -> list[ReviewDecision]:
        applied: list[ReviewDecision] = []
        for dec in decisions:
            if dec.item_id not in store:
                continue
            entry = store[dec.item_id]
            if dec.decision == "approved":
                entry.status = "active"
            elif dec.decision == "rejected":
                entry.status = "draft"
            elif dec.decision == "needs_edit":
                entry.status = "draft"
            dec.reviewed_at = now
            entry.updated_at = now
            applied.append(dec)
        return applied

    # ── Manifest builder ─────────────────────────────────────────────────────

    @staticmethod
    def _build_manifest(
        kb_id: str,
        version: KBVersion,
        store: dict[str, KBEntry],
        now: str,
    ) -> KBManifest:
        """Build complete KB release manifest."""
        # Coverage stats
        domain_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        culture_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        type_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])

        for entry in store.values():
            if entry.role:
                domain_counts[entry.role][0] += 1
                if entry.status == "active":
                    domain_counts[entry.role][1] += 1
            for cp in entry.tags.culture_pack:
                culture_counts[cp][0] += 1
                if entry.status == "active":
                    culture_counts[cp][1] += 1
            type_counts[entry.entry_type][0] += 1
            if entry.status == "active":
                type_counts[entry.entry_type][1] += 1

        return KBManifest(
            kb_id=kb_id,
            kb_version_id=version.kb_version_id,
            release_notes=version.release_notes,
            entry_count=len(store),
            included_item_ids=version.included_item_ids,
            deprecated_item_ids=version.deprecated_item_ids,
            version_history=_KB_VERSIONS.get(kb_id, []),
            coverage_by_domain=[
                CoverageStatEntry(key=k, count=v[0], active_count=v[1])
                for k, v in sorted(domain_counts.items())
            ],
            coverage_by_culture=[
                CoverageStatEntry(key=k, count=v[0], active_count=v[1])
                for k, v in sorted(culture_counts.items())
            ],
            coverage_by_type=[
                CoverageStatEntry(key=k, count=v[0], active_count=v[1])
                for k, v in sorted(type_counts.items())
            ],
            target_embedding_model=version.target_embedding_model,
            chunking_policy_id=version.chunking_policy_id,
            content_hash=version.content_hash,
            active_recipe_set_id=f"recipe_{kb_id[:8]}",
            created_at=now,
        )

    # ── Summary builder ──────────────────────────────────────────────────────

    @staticmethod
    def _build_summary(
        store: dict[str, KBEntry],
        dedup_results: list[DedupResult],
        quality_issues: list[QualityIssue],
        review_items: list[ReviewRequiredItem],
    ) -> KBManagerSummary:
        active = sum(1 for e in store.values() if e.status == "active")
        draft = sum(1 for e in store.values() if e.status == "draft")
        deprecated = sum(1 for e in store.values() if e.status == "deprecated")
        return KBManagerSummary(
            total_entries=len(store),
            active_entries=active,
            draft_entries=draft,
            deprecated_entries=deprecated,
            dedup_actions=len(dedup_results),
            quality_issues_found=len(quality_issues),
            review_required_count=len(review_items),
            index_rebuild=True,
        )

    # ── Logging ──────────────────────────────────────────────────────────────

    def _log_completion(self, ctx: SkillContext, kb_id: str, action: str, count: int) -> None:
        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} kb={kb_id} "
            f"action={action} affected={count}"
        )
