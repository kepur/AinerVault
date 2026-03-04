from __future__ import annotations

import hashlib
import json
import re
import requests
from datetime import datetime, timezone
from itertools import islice
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import (
    Chapter,
    EntityContinuityStatus,
    EntityMapping,
    Novel,
    SkillRun,
    SkillRunStatus,
)
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider
from ainern2d_shared.ainer_db_models.translation_models import (
    BlockType,
    ConsistencyMode,
    ConsistencyWarning,
    EntityNameVariant,
    PlanItemStatus,
    ScriptBlock,
    TranslationBlock,
    TranslationBlockStatus,
    TranslationPlanItem,
    TranslationProject,
    TranslationProjectStatus,
    WarningStatus,
    WarningType,
)
from app.api.v1.tasks import TaskSubmitAccepted, TaskSubmitRequest, create_task

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["translation"])


# ── Pydantic Models ────────────────────────────────────────────────────────────

class CreateTranslationProjectRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    novel_id: str
    source_language_code: str = "zh-CN"
    target_language_code: str = "en-US"
    model_provider_id: str | None = None
    consistency_mode: ConsistencyMode = ConsistencyMode.balanced
    term_dictionary_json: dict[str, str] | None = None
    scope_mode: str = "chapters_selected"
    scope_payload: dict | None = None
    granularity: str = "chapter"
    batch_size: int = Field(default=10, ge=1, le=50)
    max_cost: float | None = None
    max_tokens: int | None = None
    run_policy: str = "manual"
    culture_mode: str = "auto"
    culture_packs: list[dict] | None = None
    temporal_enabled: bool = False
    temporal_layers: list[dict] | None = None
    temporal_detect_policy: str = "off"
    naming_policy_by_lang: dict[str, str] | None = None
    auto_fill_missing_names: bool = False


class UpdateTranslationProjectRequest(BaseModel):
    term_dictionary_json: dict[str, str] | None = None
    consistency_mode: ConsistencyMode | None = None
    model_provider_id: str | None = None
    status: TranslationProjectStatus | None = None
    scope_mode: str | None = None
    scope_payload: dict | None = None
    granularity: str | None = None
    batch_size: int | None = Field(default=None, ge=1, le=50)
    max_cost: float | None = None
    max_tokens: int | None = None
    run_policy: str | None = None
    culture_mode: str | None = None
    culture_packs: list[dict] | None = None
    temporal_enabled: bool | None = None
    temporal_layers: list[dict] | None = None
    temporal_detect_policy: str | None = None
    naming_policy_by_lang: dict[str, str] | None = None
    auto_fill_missing_names: bool | None = None


class TranslationBlockResponse(BaseModel):
    id: str
    translated_text: str | None
    status: str
    translation_notes: str | None


class ScriptBlockResponse(BaseModel):
    id: str
    chapter_id: str
    seq_no: int
    block_type: str
    source_text: str
    speaker_tag: str | None
    translation: TranslationBlockResponse | None


class TranslationProjectResponse(BaseModel):
    id: str
    novel_id: str
    source_language_code: str
    target_language_code: str
    status: str
    consistency_mode: str
    model_provider_id: str | None
    term_dictionary_json: dict | None
    stats_json: dict | None
    scope_mode: str
    scope_payload: dict | None
    granularity: str
    batch_size: int
    max_cost: float | None
    max_tokens: int | None
    run_policy: str
    culture_mode: str
    culture_packs: list | None
    temporal_enabled: bool
    temporal_layers: list | None
    temporal_detect_policy: str
    naming_policy_by_lang: dict | None
    auto_fill_missing_names: bool
    created_at: datetime


class TranslationPlanItemResponse(BaseModel):
    id: str
    scope_type: str
    chapter_id: str | None
    scene_id: str | None
    segment_id: str | None
    order_no: int
    item_status: str
    retry_count: int
    last_error: str | None
    last_run_id: str | None


class ExecutePlanRequest(BaseModel):
    batch_size: int = Field(default=10, ge=1, le=100)
    only_failed: bool = False
    only_pending: bool = False
    only_untranslated: bool = False
    selected_item_ids: list[str] = Field(default_factory=list)
    model_provider_id: str | None = None


class TranslationJobsBatchRequest(BaseModel):
    job_ids: list[str] = Field(default_factory=list)
    delete_with_artifacts: bool = False


class EntityNameVariantResponse(BaseModel):
    id: str
    source_name: str
    canonical_target_name: str
    is_locked: bool
    aliases_json: list | None
    entity_id: str | None


class ConsistencyWarningResponse(BaseModel):
    id: str
    warning_type: str
    source_name: str
    detected_variant: str
    expected_canonical: str | None
    status: str
    translation_block_id: str | None


class SegmentRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    chapter_id: str | None = None


class TranslateRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    chapter_id: str | None = None
    script_block_ids: list[str] | None = None   # if set, only translate these specific blocks
    model_provider_id: str | None = None         # override project's provider
    batch_size: int = Field(default=10, ge=1, le=30)


class UpdateTranslationBlockRequest(BaseModel):
    translated_text: str | None = None
    status: str | None = None
    translation_notes: str | None = None


class CreateEntityVariantRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    source_name: str
    canonical_target_name: str
    entity_id: str | None = None
    aliases_json: list[str] | None = None


class LockEntityVariantRequest(BaseModel):
    canonical_target_name: str


class ResolveWarningRequest(BaseModel):
    status: str  # "resolved" | "ignored"


class TranslationRunGateRequest(BaseModel):
    chapter_id: str | None = None


class TranslationRunGateResponse(BaseModel):
    ready_to_run: bool
    chapter_id: str | None
    missing: list[str]
    stale: list[str]
    recommended_actions: list[str]
    disabled_reason: str | None = None


class TranslationCreateRunRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    chapter_id: str | None = None
    requested_quality: str = "standard"
    language_context: str | None = None
    force_rerun: bool = False
    use_cache: bool = True
    dry_run: bool = False


class TranslationCreateRunResponse(BaseModel):
    run_id: str | None = None
    status: str
    chapter_id: str | None
    gate: TranslationRunGateResponse
    message: str | None = None


class PlaceholderApplyRequest(BaseModel):
    novel_id: str
    target_language: str = "en-US"
    text: str


class PlaceholderApplyResponse(BaseModel):
    text: str
    placeholder_to_target: dict[str, str]


class PlaceholderRestoreRequest(BaseModel):
    text: str
    placeholder_to_target: dict[str, str]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid4().hex


def _chunks(lst: list, n: int):
    """Yield successive n-sized chunks from lst."""
    it = iter(lst)
    while True:
        batch = list(islice(it, n))
        if not batch:
            break
        yield batch


def _compute_input_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _entity_placeholder(entity: EntityMapping) -> str:
    type_map = {
        "character": "CHAR",
        "location": "LOC",
        "prop": "PROP",
        "style": "STYLE",
        "event": "EVENT",
    }
    etype = (
        type_map.get(entity.entity_type.value, "ENTITY")
        if entity.entity_type is not None and hasattr(entity.entity_type, "value")
        else "ENTITY"
    )
    stable_token = f"e_{entity.id[:10].lower()}"
    return f"{{{{{etype}:{stable_token}}}}}"


def _placeholder_mutation_variants(placeholder: str, target_name: str) -> list[str]:
    """
    Models may mutate placeholder inner token, e.g. {{CHAR:e_xxx}} -> {{CHAR:Mason}}.
    Build compatible keys so restore can still recover target text.
    """
    match = re.match(r"^\{\{([A-Z]+):[^}]+\}\}$", placeholder)
    if not match:
        return []
    entity_prefix = match.group(1)
    base = str(target_name or "").strip()
    if not base:
        return []

    normalized = re.sub(r"\s+", "_", base)
    compact = re.sub(r"[^A-Za-z0-9_\-]+", "_", normalized).strip("_")

    variants = {
        f"{{{{{entity_prefix}:{base}}}}}",
        f"{{{{{entity_prefix}:{base.lower()}}}}}",
    }
    if compact:
        variants.add(f"{{{{{entity_prefix}:{compact}}}}}")
        variants.add(f"{{{{{entity_prefix}:{compact.lower()}}}}}")

    return list(variants)


def _build_placeholder_maps(
    entities: list[EntityMapping],
    target_language: str,
    *,
    auto_fill_missing_names: bool,
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    source_to_placeholder: list[tuple[str, str]] = []
    placeholder_to_target: dict[str, str] = {}
    missing_locked_entities: list[str] = []
    base_lang = target_language.split("-")[0]
    for entity in entities:
        placeholder = _entity_placeholder(entity)
        translations = dict(entity.translations_json or {})
        target_name = translations.get(target_language) or translations.get(base_lang)
        if not target_name and auto_fill_missing_names:
            for candidate in list(entity.localization_candidates_json or []):
                if not isinstance(candidate, dict):
                    continue
                picked = str(candidate.get("name") or "").strip()
                if picked:
                    target_name = picked
                    translations[target_language] = picked
                    entity.translations_json = translations
                    entity.updated_at = _utcnow()
                    break
        locked_langs = dict(entity.locked_langs_json or {})
        lang_locked = bool(
            locked_langs.get(target_language)
            or locked_langs.get(base_lang)
            or (entity.locked and not locked_langs)
        )
        if not target_name and lang_locked:
            missing_locked_entities.append(entity.canonical_name)
            target_name = placeholder
        if not target_name:
            target_name = entity.canonical_name
        placeholder_to_target[placeholder] = target_name
        for variant in _placeholder_mutation_variants(placeholder, target_name):
            placeholder_to_target.setdefault(variant, target_name)
        candidates = [entity.canonical_name] + list(entity.aliases_json or [])
        for candidate in candidates:
            name = str(candidate or "").strip()
            if name:
                source_to_placeholder.append((name, placeholder))
    source_to_placeholder.sort(key=lambda x: len(x[0]), reverse=True)
    if missing_locked_entities:
        raise HTTPException(
            status_code=422,
            detail=(
                "missing translations for locked target language entities: "
                + ", ".join(missing_locked_entities[:10])
            ),
        )
    return source_to_placeholder, placeholder_to_target


def _apply_placeholders_to_text(text: str, source_to_placeholder: list[tuple[str, str]]) -> str:
    converted = text
    for source_name, placeholder in source_to_placeholder:
        converted = converted.replace(source_name, placeholder)
    return converted


def _restore_placeholders(text: str, placeholder_to_target: dict[str, str]) -> str:
    restored = text
    for placeholder, target_name in sorted(
        placeholder_to_target.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        restored = restored.replace(placeholder, target_name)

    # Final fallback: if model still outputs {{TYPE:token}} and token is already a target name,
    # unwrap braces to plain text to avoid leaking placeholders to UI.
    target_lookup = {
        str(value).strip().lower(): str(value).strip()
        for value in placeholder_to_target.values()
        if str(value or "").strip()
    }

    def _unwrap(match: re.Match[str]) -> str:
        token = match.group(2).strip()
        exact = target_lookup.get(token.lower())
        if exact:
            return exact
        # Hard fallback: never leak placeholder wrappers to UI/storage.
        # If token cannot be mapped, at least unwrap `{{TYPE:token}}` -> `token`.
        return token

    restored = re.sub(r"\{\{([A-Z]+):([^}]+)\}\}", _unwrap, restored)
    return restored


def _find_cached_translation_run(
    db: Session,
    *,
    project: TranslationProject,
    input_hash: str,
) -> SkillRun | None:
    return db.execute(
        select(SkillRun).where(
            SkillRun.skill_id == "translation_run",
            SkillRun.input_hash == input_hash,
            SkillRun.novel_id == project.novel_id,
            SkillRun.status == SkillRunStatus.succeeded,
            SkillRun.deleted_at.is_(None),
        ).order_by(SkillRun.created_at.desc())
    ).scalars().first()


def _load_provider_settings(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    provider_id: str,
) -> dict:
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == f"provider_settings:{provider_id}",
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        return {}
    return dict(row.stack_json or {})


def _call_provider_with_messages(
    *,
    provider: ModelProvider,
    provider_settings: dict,
    messages: list[dict],
    max_tokens: int = 2000,
) -> str:
    """Call an OpenAI-compatible chat completions endpoint with explicit messages."""
    endpoint = (provider.endpoint or "").strip().rstrip("/")
    token = str(provider_settings.get("access_token") or "").strip()
    model_catalog = list(provider_settings.get("model_catalog") or [])
    model_name = model_catalog[0] if model_catalog else "gpt-4o-mini"
    if not endpoint or not token:
        raise ValueError("missing provider endpoint or token")

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    response = requests.post(
        f"{endpoint}/chat/completions",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=90.0,
    )
    if response.status_code < 200 or response.status_code >= 300:
        raise ValueError(f"provider_http_status_{response.status_code}")

    parsed = response.json() if response.text else {}
    choices = parsed.get("choices") or []
    if not choices:
        raise ValueError("provider_response_missing_choices")
    content = str((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("provider_response_empty_content")
    return content


def _segment_text(text: str, chapter_id: str) -> list[dict[str, Any]]:
    """
    Split chapter raw text into typed blocks.
    Returns list of dicts with keys: block_type, source_text, speaker_tag, seq_no.
    """
    blocks: list[dict[str, Any]] = []
    seq = 0

    # Split by blank lines to get paragraphs
    paragraphs = re.split(r"\n{2,}", text.strip())

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Scene break markers: ---, ***, ===
        if re.match(r"^[-*=]{3,}$", para):
            blocks.append({
                "block_type": BlockType.scene_break,
                "source_text": para,
                "speaker_tag": None,
                "seq_no": seq,
            })
            seq += 1
            continue

        # Heading: starts with # markdown or all-caps short line
        if re.match(r"^#{1,6}\s", para) or (len(para) < 80 and re.match(r"^第[零一二三四五六七八九十百千\d]+[章节回部]", para)):
            blocks.append({
                "block_type": BlockType.heading,
                "source_text": para,
                "speaker_tag": None,
                "seq_no": seq,
            })
            seq += 1
            continue

        # Dialogue: Chinese quotation marks or ASCII quotes with speaker prefix
        # Pattern: 「...」 or "..." or speaker："..."
        speaker_match = re.match(
            r'^([^：""\n]{1,20})[：""](.+)$',
            para,
            re.DOTALL,
        )
        if speaker_match:
            blocks.append({
                "block_type": BlockType.dialogue,
                "source_text": para,
                "speaker_tag": speaker_match.group(1).strip(),
                "seq_no": seq,
            })
            seq += 1
            continue

        if re.match(r'^[「"『]', para) or re.search(r'[」"』]', para):
            blocks.append({
                "block_type": BlockType.dialogue,
                "source_text": para,
                "speaker_tag": None,
                "seq_no": seq,
            })
            seq += 1
            continue

        # Action: parenthetical stage direction
        if re.match(r"^[（(【\[]", para):
            blocks.append({
                "block_type": BlockType.action,
                "source_text": para,
                "speaker_tag": None,
                "seq_no": seq,
            })
            seq += 1
            continue

        # Default: narration
        blocks.append({
            "block_type": BlockType.narration,
            "source_text": para,
            "speaker_tag": None,
            "seq_no": seq,
        })
        seq += 1

    return blocks


def _segment_script_doc(script_doc: dict[str, Any], chapter_id: str) -> list[dict[str, Any]]:
    """Flatten structured ScriptDoc scenes into translation blocks while preserving dialogue."""
    scenes = list(script_doc.get("scenes") or [])
    blocks: list[dict[str, Any]] = []
    seq = 0

    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or f"s{i + 1:03d}")
        title = str(scene.get("title") or "").strip()
        time_text = str(scene.get("time") or "").strip()
        location = str(scene.get("location") or "").strip()
        heading_parts = [p for p in [scene_id, title, time_text, location] if p]
        if heading_parts:
            blocks.append(
                {
                    "block_type": BlockType.heading,
                    "source_text": " | ".join(heading_parts),
                    "speaker_tag": None,
                    "seq_no": seq,
                }
            )
            seq += 1

        # Prefer explicit script-doc blocks if present.
        structured_blocks = list(scene.get("blocks") or [])
        if structured_blocks:
            for item in structured_blocks:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or item.get("block_type") or "").strip().lower()
                text = str(item.get("text") or item.get("line") or item.get("content") or "").strip()
                if not text:
                    continue
                speaker = str(item.get("speaker") or item.get("speaker_tag") or "").strip() or None
                mapped_type = BlockType.narration
                if item_type in {"dialogue", "dialog"}:
                    mapped_type = BlockType.dialogue
                elif item_type in {"action", "camera", "sfx_hint", "bgm_hint"}:
                    mapped_type = BlockType.action
                elif item_type in {"heading", "title", "meta", "separator", "scene_break"}:
                    mapped_type = BlockType.heading
                if mapped_type == BlockType.dialogue and speaker:
                    text = f"{speaker}：{text}"
                blocks.append(
                    {
                        "block_type": mapped_type,
                        "source_text": text,
                        "speaker_tag": speaker,
                        "seq_no": seq,
                    }
                )
                seq += 1
            continue

        narration = str(scene.get("narration") or "").strip()
        if narration:
            blocks.append(
                {
                    "block_type": BlockType.narration,
                    "source_text": narration,
                    "speaker_tag": None,
                    "seq_no": seq,
                }
            )
            seq += 1

        for d in list(scene.get("dialogue_blocks") or []):
            if not isinstance(d, dict):
                continue
            speaker = str(d.get("speaker") or "").strip() or None
            line = str(d.get("line") or d.get("text") or "").strip()
            if not line:
                continue
            source_text = f"{speaker}：{line}" if speaker else line
            blocks.append(
                {
                    "block_type": BlockType.dialogue,
                    "source_text": source_text,
                    "speaker_tag": speaker,
                    "seq_no": seq,
                }
            )
            seq += 1

        for action_item in list(scene.get("actions") or []):
            if isinstance(action_item, dict):
                action_text = str(
                    action_item.get("text")
                    or action_item.get("action")
                    or action_item.get("description")
                    or ""
                ).strip()
            else:
                action_text = str(action_item or "").strip()
            if not action_text:
                continue
            blocks.append(
                {
                    "block_type": BlockType.action,
                    "source_text": action_text,
                    "speaker_tag": None,
                    "seq_no": seq,
                }
            )
            seq += 1

    return blocks


def _extract_entity_variants(
    translated_results: list[dict],
    project: TranslationProject,
    db: Session,
) -> None:
    """
    Heuristically extract potential entity name variants from translated text.
    Looks for capitalized multi-word tokens (likely proper nouns in EN).
    Creates EntityNameVariant records for newly discovered names.
    """
    # Collect all translated text
    for item in translated_results:
        translated = item.get("translated_text") or ""
        if not translated:
            continue

        # Find capitalized runs (e.g., "Ye Zichen", "Dragon Phoenix Sect")
        candidates = re.findall(
            r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)\b",
            translated,
        )
        for candidate in set(candidates):
            # Check if this variant is already known
            existing = db.execute(
                select(EntityNameVariant).where(
                    EntityNameVariant.translation_project_id == project.id,
                    EntityNameVariant.canonical_target_name == candidate,
                    EntityNameVariant.deleted_at.is_(None),
                )
            ).scalars().first()
            if existing:
                continue

            # Check if it exists as an alias in any variant
            all_variants = db.execute(
                select(EntityNameVariant).where(
                    EntityNameVariant.translation_project_id == project.id,
                    EntityNameVariant.deleted_at.is_(None),
                )
            ).scalars().all()
            found_in_alias = any(
                candidate in (v.aliases_json or []) for v in all_variants
            )
            if found_in_alias:
                continue

            # Create a new tentative variant
            now = _utcnow()
            variant = EntityNameVariant(
                id=_new_id(),
                tenant_id=project.tenant_id,
                project_id=project.project_id,
                translation_project_id=project.id,
                source_name=candidate,
                canonical_target_name=candidate,
                is_locked=False,
                aliases_json=[],
                created_at=now,
                updated_at=now,
            )
            db.add(variant)


def _run_consistency_check(project: TranslationProject, db: Session) -> int:
    """
    For every locked EntityNameVariant, scan all TranslationBlocks for alias usage.
    Create ConsistencyWarning for any detected drift.
    Returns count of new warnings created.
    """
    all_blocks = db.execute(
        select(TranslationBlock).where(
            TranslationBlock.translation_project_id == project.id,
            TranslationBlock.deleted_at.is_(None),
            TranslationBlock.translated_text.isnot(None),
        )
    ).scalars().all()

    def _warning_exists(tb_id: str, detected_variant: str) -> bool:
        existing = db.execute(
            select(ConsistencyWarning).where(
                ConsistencyWarning.translation_project_id == project.id,
                ConsistencyWarning.translation_block_id == tb_id,
                ConsistencyWarning.detected_variant == detected_variant,
                ConsistencyWarning.status == WarningStatus.open,
                ConsistencyWarning.deleted_at.is_(None),
            )
        ).scalars().first()
        return existing is not None

    warnings_created = 0

    locked_variants = db.execute(
        select(EntityNameVariant).where(
            EntityNameVariant.translation_project_id == project.id,
            EntityNameVariant.is_locked == True,  # noqa: E712
            EntityNameVariant.deleted_at.is_(None),
        )
    ).scalars().all()
    for variant in locked_variants:
        aliases = variant.aliases_json or []
        for alias in aliases:
            if alias == variant.canonical_target_name:
                continue
            for tb in all_blocks:
                text = tb.translated_text or ""
                if alias not in text or _warning_exists(tb.id, alias):
                    continue
                now = _utcnow()
                warning = ConsistencyWarning(
                    id=_new_id(),
                    tenant_id=project.tenant_id,
                    project_id=project.project_id,
                    translation_project_id=project.id,
                    translation_block_id=tb.id,
                    warning_type=WarningType.name_drift,
                    source_name=variant.source_name,
                    detected_variant=alias,
                    expected_canonical=variant.canonical_target_name,
                    status=WarningStatus.open,
                    created_at=now,
                    updated_at=now,
                )
                db.add(warning)
                warnings_created += 1

    # EntityMapping-level drift check for locked localized names.
    locked_entities = db.execute(
        select(EntityMapping).where(
            EntityMapping.novel_id == project.novel_id,
            EntityMapping.locked == True,  # noqa: E712
            EntityMapping.deleted_at.is_(None),
        )
    ).scalars().all()
    for entity in locked_entities:
        translations = dict(entity.translations_json or {})
        expected_name = (
            translations.get(project.target_language_code)
            or translations.get(project.target_language_code.split("-")[0])
            or entity.canonical_name
        )
        drift_variants = {
            str(v).strip()
            for v in (entity.aliases_json or [])
            if str(v).strip() and str(v).strip() != expected_name
        }
        for candidate in list(entity.localization_candidates_json or []):
            if not isinstance(candidate, dict):
                continue
            candidate_name = str(candidate.get("name") or "").strip()
            if candidate_name and candidate_name != expected_name:
                drift_variants.add(candidate_name)
        for translated_name in translations.values():
            translated_name = str(translated_name or "").strip()
            if translated_name and translated_name != expected_name:
                drift_variants.add(translated_name)
        if entity.canonical_name and entity.canonical_name != expected_name:
            drift_variants.add(entity.canonical_name)

        entity_has_drift = False
        for tb in all_blocks:
            text = tb.translated_text or ""
            for variant_name in drift_variants:
                if variant_name not in text or _warning_exists(tb.id, variant_name):
                    continue
                now = _utcnow()
                warning = ConsistencyWarning(
                    id=_new_id(),
                    tenant_id=project.tenant_id,
                    project_id=project.project_id,
                    translation_project_id=project.id,
                    translation_block_id=tb.id,
                    warning_type=WarningType.name_drift,
                    source_name=entity.canonical_name,
                    detected_variant=variant_name,
                    expected_canonical=expected_name,
                    status=WarningStatus.open,
                    created_at=now,
                    updated_at=now,
                )
                db.add(warning)
                warnings_created += 1
                entity_has_drift = True
        entity.drift_score = 0.9 if entity_has_drift else 0.0
        entity.continuity_status = (
            EntityContinuityStatus.drifted
            if entity_has_drift
            else EntityContinuityStatus.locked
        )
        entity.updated_at = _utcnow()

    return warnings_created


def _to_project_response(p: TranslationProject) -> TranslationProjectResponse:
    return TranslationProjectResponse(
        id=p.id,
        novel_id=p.novel_id,
        source_language_code=p.source_language_code,
        target_language_code=p.target_language_code,
        status=p.status.value if hasattr(p.status, "value") else str(p.status),
        consistency_mode=(
            p.consistency_mode.value
            if hasattr(p.consistency_mode, "value")
            else str(p.consistency_mode)
        ),
        model_provider_id=p.model_provider_id,
        term_dictionary_json=p.term_dictionary_json,
        stats_json=p.stats_json,
        scope_mode=p.scope_mode,
        scope_payload=p.scope_payload_json,
        granularity=p.granularity,
        batch_size=p.batch_size,
        max_cost=p.max_cost,
        max_tokens=p.max_tokens,
        run_policy=p.run_policy,
        culture_mode=p.culture_mode,
        culture_packs=p.culture_packs_json,
        temporal_enabled=p.temporal_enabled,
        temporal_layers=p.temporal_layers_json,
        temporal_detect_policy=p.temporal_detect_policy,
        naming_policy_by_lang=p.naming_policy_by_lang_json,
        auto_fill_missing_names=p.auto_fill_missing_names,
        created_at=p.created_at,
    )


def _to_plan_item_response(item: TranslationPlanItem) -> TranslationPlanItemResponse:
    return TranslationPlanItemResponse(
        id=item.id,
        scope_type=item.scope_type,
        chapter_id=item.chapter_id,
        scene_id=item.scene_id,
        segment_id=item.segment_id,
        order_no=item.order_no,
        item_status=item.item_status,
        retry_count=item.retry_count,
        last_error=item.last_error,
        last_run_id=item.last_run_id,
    )


def _normalize_scope_payload(scope_payload: dict | None) -> dict:
    payload = dict(scope_payload or {})
    chapters = payload.get("chapters")
    if chapters is None:
        payload["chapters"] = []
    elif isinstance(chapters, list):
        payload["chapters"] = [str(c).strip() for c in chapters if str(c).strip()]
    else:
        payload["chapters"] = []
    return payload


def _extract_chapter_ids_from_scope(project: TranslationProject, db: Session) -> list[str]:
    payload = _normalize_scope_payload(project.scope_payload_json)
    mode = str(project.scope_mode or "chapters_selected")
    granularity = str(project.granularity or "chapter")

    if mode == "chapters_selected":
        chapter_ids = list(payload.get("chapters") or [])
        if chapter_ids:
            return chapter_ids
    if mode == "scenes_selected":
        scenes = list(payload.get("scenes") or [])
        chapter_ids = [str(s.get("chapter_id")).strip() for s in scenes if isinstance(s, dict) and s.get("chapter_id")]
        if chapter_ids:
            return list(dict.fromkeys(chapter_ids))
    if mode == "segments_selected":
        segments = list(payload.get("segments") or [])
        chapter_ids = [
            str(seg.get("chapter_id")).strip()
            for seg in segments
            if isinstance(seg, dict) and seg.get("chapter_id")
        ]
        if chapter_ids:
            return list(dict.fromkeys(chapter_ids))

    chapter_rows = db.execute(
        select(Chapter.id).where(
            Chapter.novel_id == project.novel_id,
            Chapter.deleted_at.is_(None),
        ).order_by(Chapter.chapter_no.asc())
    ).all()
    return [row[0] for row in chapter_rows]


def _rebuild_plan_items(project: TranslationProject, db: Session) -> list[TranslationPlanItem]:
    now = _utcnow()
    old_items = db.execute(
        select(TranslationPlanItem).where(
            TranslationPlanItem.translation_project_id == project.id,
            TranslationPlanItem.deleted_at.is_(None),
        )
    ).scalars().all()
    for item in old_items:
        item.deleted_at = now
        item.updated_at = now

    chapter_ids = _extract_chapter_ids_from_scope(project, db)
    new_items: list[TranslationPlanItem] = []
    for idx, chapter_id in enumerate(chapter_ids):
        item = TranslationPlanItem(
            id=_new_id(),
            tenant_id=project.tenant_id,
            project_id=project.project_id,
            translation_project_id=project.id,
            scope_type=project.granularity or "chapter",
            chapter_id=chapter_id,
            scene_id=None,
            segment_id=None,
            order_no=idx,
            item_status=PlanItemStatus.pending.value,
            created_at=now,
            updated_at=now,
        )
        db.add(item)
        new_items.append(item)
    return new_items


def _to_block_response(
    sb: ScriptBlock,
    tb: TranslationBlock | None,
) -> ScriptBlockResponse:
    translation = None
    if tb:
        translation = TranslationBlockResponse(
            id=tb.id,
            translated_text=tb.translated_text,
            status=tb.status.value if hasattr(tb.status, "value") else str(tb.status),
            translation_notes=tb.translation_notes,
        )
    return ScriptBlockResponse(
        id=sb.id,
        chapter_id=sb.chapter_id,
        seq_no=sb.seq_no,
        block_type=(
            sb.block_type.value if hasattr(sb.block_type, "value") else str(sb.block_type)
        ),
        source_text=sb.source_text,
        speaker_tag=sb.speaker_tag,
        translation=translation,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/translations/projects", response_model=TranslationProjectResponse)
def create_translation_project(
    body: CreateTranslationProjectRequest,
    db: Session = Depends(get_db),
) -> TranslationProjectResponse:
    novel = db.get(Novel, body.novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")

    now = _utcnow()
    project = TranslationProject(
        id=_new_id(),
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        novel_id=body.novel_id,
        source_language_code=body.source_language_code,
        target_language_code=body.target_language_code,
        status=TranslationProjectStatus.draft,
        model_provider_id=body.model_provider_id,
        consistency_mode=body.consistency_mode,
        term_dictionary_json=body.term_dictionary_json,
        stats_json={"plan_items": 0, "pending_items": 0, "completed_items": 0, "failed_items": 0},
        scope_mode=body.scope_mode,
        scope_payload_json=_normalize_scope_payload(body.scope_payload),
        granularity=body.granularity,
        batch_size=body.batch_size,
        max_cost=body.max_cost,
        max_tokens=body.max_tokens,
        run_policy=body.run_policy,
        culture_mode=body.culture_mode,
        culture_packs_json=body.culture_packs,
        temporal_enabled=body.temporal_enabled,
        temporal_layers_json=body.temporal_layers,
        temporal_detect_policy=body.temporal_detect_policy,
        naming_policy_by_lang_json=body.naming_policy_by_lang,
        auto_fill_missing_names=body.auto_fill_missing_names,
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    db.flush()
    plan_items = _rebuild_plan_items(project, db)
    project.stats_json = {
        "plan_items": len(plan_items),
        "pending_items": len(plan_items),
        "completed_items": 0,
        "failed_items": 0,
    }
    db.commit()
    db.refresh(project)
    return _to_project_response(project)


@router.get("/translations/projects", response_model=list[TranslationProjectResponse])
def list_translation_projects(
    novel_id: str | None = Query(default=None),
    tenant_id: str = Query(default="default"),
    project_id: str = Query(default="default"),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[TranslationProjectResponse]:
    q = select(TranslationProject).where(
        TranslationProject.tenant_id == tenant_id,
        TranslationProject.project_id == project_id,
        TranslationProject.deleted_at.is_(None),
    )
    if novel_id:
        q = q.where(TranslationProject.novel_id == novel_id)
    if status:
        q = q.where(TranslationProject.status == status)
    q = q.order_by(TranslationProject.created_at.desc())
    rows = db.execute(q).scalars().all()
    return [_to_project_response(p) for p in rows]


@router.get(
    "/translations/projects/{project_id_path}",
    response_model=TranslationProjectResponse,
)
def get_translation_project(
    project_id_path: str,
    db: Session = Depends(get_db),
) -> TranslationProjectResponse:
    p = db.get(TranslationProject, project_id_path)
    if p is None or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")
    return _to_project_response(p)


@router.put(
    "/translations/projects/{project_id_path}",
    response_model=TranslationProjectResponse,
)
def update_translation_project(
    project_id_path: str,
    body: UpdateTranslationProjectRequest,
    db: Session = Depends(get_db),
) -> TranslationProjectResponse:
    p = db.get(TranslationProject, project_id_path)
    if p is None or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")

    if body.term_dictionary_json is not None:
        p.term_dictionary_json = body.term_dictionary_json
    if body.consistency_mode is not None:
        p.consistency_mode = body.consistency_mode
    if body.model_provider_id is not None:
        p.model_provider_id = body.model_provider_id
    if body.status is not None:
        p.status = body.status
    if body.scope_mode is not None:
        p.scope_mode = body.scope_mode
    if body.scope_payload is not None:
        p.scope_payload_json = _normalize_scope_payload(body.scope_payload)
    if body.granularity is not None:
        p.granularity = body.granularity
    if body.batch_size is not None:
        p.batch_size = body.batch_size
    if body.max_cost is not None:
        p.max_cost = body.max_cost
    if body.max_tokens is not None:
        p.max_tokens = body.max_tokens
    if body.run_policy is not None:
        p.run_policy = body.run_policy
    if body.culture_mode is not None:
        p.culture_mode = body.culture_mode
    if body.culture_packs is not None:
        p.culture_packs_json = body.culture_packs
    if body.temporal_enabled is not None:
        p.temporal_enabled = body.temporal_enabled
    if body.temporal_layers is not None:
        p.temporal_layers_json = body.temporal_layers
    if body.temporal_detect_policy is not None:
        p.temporal_detect_policy = body.temporal_detect_policy
    if body.naming_policy_by_lang is not None:
        p.naming_policy_by_lang_json = body.naming_policy_by_lang
    if body.auto_fill_missing_names is not None:
        p.auto_fill_missing_names = body.auto_fill_missing_names

    if (
        body.scope_mode is not None
        or body.scope_payload is not None
        or body.granularity is not None
    ):
        plan_items = _rebuild_plan_items(p, db)
        p.stats_json = {
            **(p.stats_json or {}),
            "plan_items": len(plan_items),
            "pending_items": len(plan_items),
            "completed_items": 0,
            "failed_items": 0,
        }
    p.updated_at = _utcnow()
    db.commit()
    db.refresh(p)
    return _to_project_response(p)


@router.delete("/translations/projects/{project_id_path}", response_model=dict)
def delete_translation_project(
    project_id_path: str,
    db: Session = Depends(get_db),
) -> dict:
    p = db.get(TranslationProject, project_id_path)
    if p is None or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")
    p.deleted_at = _utcnow()
    db.commit()
    return {"status": "deleted"}


@router.post("/translation/placeholder/apply", response_model=PlaceholderApplyResponse)
def apply_translation_placeholders(
    body: PlaceholderApplyRequest,
    db: Session = Depends(get_db),
) -> PlaceholderApplyResponse:
    entities = db.execute(
        select(EntityMapping).where(
            EntityMapping.novel_id == body.novel_id,
            EntityMapping.deleted_at.is_(None),
        )
    ).scalars().all()
    source_to_placeholder, placeholder_to_target = _build_placeholder_maps(
        entities,
        body.target_language,
        auto_fill_missing_names=False,
    )
    return PlaceholderApplyResponse(
        text=_apply_placeholders_to_text(body.text, source_to_placeholder),
        placeholder_to_target=placeholder_to_target,
    )


@router.post("/translation/placeholder/restore", response_model=dict)
def restore_translation_placeholders(
    body: PlaceholderRestoreRequest,
) -> dict:
    return {"text": _restore_placeholders(body.text, body.placeholder_to_target)}


def _refresh_plan_stats(project: TranslationProject, db: Session) -> None:
    items = db.execute(
        select(TranslationPlanItem).where(
            TranslationPlanItem.translation_project_id == project.id,
            TranslationPlanItem.deleted_at.is_(None),
        )
    ).scalars().all()
    project.stats_json = {
        **(project.stats_json or {}),
        "plan_items": len(items),
        "pending_items": sum(1 for i in items if i.item_status == PlanItemStatus.pending.value),
        "running_items": sum(1 for i in items if i.item_status == PlanItemStatus.running.value),
        "completed_items": sum(1 for i in items if i.item_status == PlanItemStatus.succeeded.value),
        "failed_items": sum(1 for i in items if i.item_status == PlanItemStatus.failed.value),
    }
    project.updated_at = _utcnow()


def _resolve_run_chapter_id(
    project: TranslationProject,
    chapter_id: str | None,
    db: Session,
) -> str | None:
    if chapter_id:
        chapter = db.get(Chapter, chapter_id)
        if chapter is None or chapter.deleted_at is not None or chapter.novel_id != project.novel_id:
            raise HTTPException(status_code=400, detail="chapter does not belong to translation project novel")
        return chapter.id

    scope_chapter_ids = _extract_chapter_ids_from_scope(project, db)
    if scope_chapter_ids:
        return scope_chapter_ids[0]

    chapter = db.execute(
        select(Chapter).where(
            Chapter.novel_id == project.novel_id,
            Chapter.deleted_at.is_(None),
        ).order_by(Chapter.chapter_no.asc())
    ).scalars().first()
    return chapter.id if chapter else None


def _build_run_gate(
    project: TranslationProject,
    chapter_id: str | None,
    db: Session,
) -> TranslationRunGateResponse:
    missing: list[str] = []
    stale: list[str] = []
    recommended_actions: list[str] = []
    disabled_reason: str | None = None

    resolved_chapter_id = _resolve_run_chapter_id(project, chapter_id, db)
    if not resolved_chapter_id:
        return TranslationRunGateResponse(
            ready_to_run=False,
            chapter_id=None,
            missing=["chapter"],
            stale=[],
            recommended_actions=["select_or_create_chapter"],
            disabled_reason="chapter_not_selected",
        )

    script_blocks = db.execute(
        select(ScriptBlock).where(
            ScriptBlock.translation_project_id == project.id,
            ScriptBlock.chapter_id == resolved_chapter_id,
            ScriptBlock.deleted_at.is_(None),
        )
    ).scalars().all()
    if not script_blocks:
        missing.append("script_doc")
        recommended_actions.append("segment_chapter_into_script_blocks")

    script_block_ids = [item.id for item in script_blocks]
    translated_count = 0
    if script_block_ids:
        translation_rows = db.execute(
            select(TranslationBlock).where(
                TranslationBlock.translation_project_id == project.id,
                TranslationBlock.script_block_id.in_(script_block_ids),
                TranslationBlock.deleted_at.is_(None),
            )
        ).scalars().all()
        translated_count = sum(1 for item in translation_rows if (item.translated_text or "").strip())
    if translated_count == 0:
        missing.append("translation")
        recommended_actions.append("translate_script_blocks")

    variant_exists = db.execute(
        select(EntityNameVariant).where(
            EntityNameVariant.translation_project_id == project.id,
            EntityNameVariant.deleted_at.is_(None),
        )
    ).scalars().first()
    if variant_exists is None:
        missing.append("entity_map")
        recommended_actions.append("extract_or_lock_entity_variants")

    entity_mapping_exists = db.execute(
        select(EntityMapping).where(
            EntityMapping.novel_id == project.novel_id,
            EntityMapping.deleted_at.is_(None),
        )
    ).scalars().first()
    if entity_mapping_exists is None:
        missing.append("world_model")
        recommended_actions.append("run_world_model_extract")

    plan_item_exists = db.execute(
        select(TranslationPlanItem).where(
            TranslationPlanItem.translation_project_id == project.id,
            TranslationPlanItem.chapter_id == resolved_chapter_id,
            TranslationPlanItem.deleted_at.is_(None),
        )
    ).scalars().first()
    if plan_item_exists is None:
        missing.append("plans")
        recommended_actions.append("rebuild_translation_plan_items")

    if missing:
        disabled_reason = "dependency_not_ready"

    return TranslationRunGateResponse(
        ready_to_run=len(missing) == 0,
        chapter_id=resolved_chapter_id,
        missing=missing,
        stale=stale,
        recommended_actions=recommended_actions,
        disabled_reason=disabled_reason,
    )


def _is_job_deletable(item_status: str) -> bool:
    return item_status in {
        PlanItemStatus.failed.value,
        PlanItemStatus.skipped.value,
        "canceled",
        "stale",
    }


def _delete_plan_item_run_data(
    item: TranslationPlanItem,
    db: Session,
    *,
    delete_with_artifacts: bool,
) -> None:
    item.deleted_at = _utcnow()
    item.updated_at = _utcnow()
    if not delete_with_artifacts:
        return
    if not item.chapter_id:
        return
    tbs = db.execute(
        select(TranslationBlock)
        .join(ScriptBlock, ScriptBlock.id == TranslationBlock.script_block_id)
        .where(
            ScriptBlock.translation_project_id == item.translation_project_id,
            ScriptBlock.chapter_id == item.chapter_id,
            TranslationBlock.deleted_at.is_(None),
        )
    ).scalars().all()
    for tb in tbs:
        tb.deleted_at = _utcnow()
        tb.updated_at = _utcnow()


@router.get(
    "/translations/projects/{project_id_path}/plan",
    response_model=list[TranslationPlanItemResponse],
)
def list_translation_plan_items(
    project_id_path: str,
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[TranslationPlanItemResponse]:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")
    q = select(TranslationPlanItem).where(
        TranslationPlanItem.translation_project_id == project_id_path,
        TranslationPlanItem.deleted_at.is_(None),
    )
    if status:
        q = q.where(TranslationPlanItem.item_status == status)
    q = q.order_by(TranslationPlanItem.order_no.asc())
    items = db.execute(q).scalars().all()
    return [_to_plan_item_response(item) for item in items]


@router.delete("/translation_jobs/{job_id}", response_model=dict)
def delete_translation_job(
    job_id: str,
    delete_with_artifacts: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(TranslationPlanItem, job_id)
    if job is None or job.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation job not found")
    if not _is_job_deletable(job.item_status):
        raise HTTPException(status_code=409, detail="running/pending jobs must be canceled before delete")
    _delete_plan_item_run_data(job, db, delete_with_artifacts=delete_with_artifacts)
    project = db.get(TranslationProject, job.translation_project_id)
    if project and project.deleted_at is None:
        _refresh_plan_stats(project, db)
    db.commit()
    return {"deleted": True, "job_id": job_id, "delete_with_artifacts": delete_with_artifacts}


@router.post("/translation_jobs/batch_delete", response_model=dict)
def batch_delete_translation_jobs(
    body: TranslationJobsBatchRequest,
    db: Session = Depends(get_db),
) -> dict:
    if not body.job_ids:
        return {"deleted": 0, "skipped": 0}
    rows = db.execute(
        select(TranslationPlanItem).where(
            TranslationPlanItem.id.in_(body.job_ids),
            TranslationPlanItem.deleted_at.is_(None),
        )
    ).scalars().all()
    deleted = 0
    skipped = 0
    touched_projects: set[str] = set()
    for row in rows:
        if not _is_job_deletable(row.item_status):
            skipped += 1
            continue
        _delete_plan_item_run_data(row, db, delete_with_artifacts=body.delete_with_artifacts)
        touched_projects.add(row.translation_project_id)
        deleted += 1
    for project_id in touched_projects:
        project = db.get(TranslationProject, project_id)
        if project and project.deleted_at is None:
            _refresh_plan_stats(project, db)
    db.commit()
    return {"deleted": deleted, "skipped": skipped}


@router.post("/translation_jobs/{job_id}/cancel", response_model=dict)
def cancel_translation_job(
    job_id: str,
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(TranslationPlanItem, job_id)
    if job is None or job.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation job not found")
    if job.item_status != PlanItemStatus.running.value:
        raise HTTPException(status_code=409, detail="only running jobs can be canceled")
    job.item_status = PlanItemStatus.skipped.value
    job.last_error = "canceled by user"
    job.updated_at = _utcnow()
    project = db.get(TranslationProject, job.translation_project_id)
    if project and project.deleted_at is None:
        _refresh_plan_stats(project, db)
    db.commit()
    return {"canceled": True, "job_id": job_id}


@router.post("/translation_jobs/batch_cancel", response_model=dict)
def batch_cancel_translation_jobs(
    body: TranslationJobsBatchRequest,
    db: Session = Depends(get_db),
) -> dict:
    if not body.job_ids:
        return {"canceled": 0, "skipped": 0}
    rows = db.execute(
        select(TranslationPlanItem).where(
            TranslationPlanItem.id.in_(body.job_ids),
            TranslationPlanItem.deleted_at.is_(None),
        )
    ).scalars().all()
    canceled = 0
    skipped = 0
    touched_projects: set[str] = set()
    for row in rows:
        if row.item_status != PlanItemStatus.running.value:
            skipped += 1
            continue
        row.item_status = PlanItemStatus.skipped.value
        row.last_error = "canceled by user"
        row.updated_at = _utcnow()
        touched_projects.add(row.translation_project_id)
        canceled += 1
    for project_id in touched_projects:
        project = db.get(TranslationProject, project_id)
        if project and project.deleted_at is None:
            _refresh_plan_stats(project, db)
    db.commit()
    return {"canceled": canceled, "skipped": skipped}


@router.post("/translation_jobs/batch_retry", response_model=dict)
def batch_retry_translation_jobs(
    body: TranslationJobsBatchRequest,
    db: Session = Depends(get_db),
) -> dict:
    if not body.job_ids:
        return {"retried": 0, "skipped": 0}
    rows = db.execute(
        select(TranslationPlanItem).where(
            TranslationPlanItem.id.in_(body.job_ids),
            TranslationPlanItem.deleted_at.is_(None),
        )
    ).scalars().all()
    retried = 0
    skipped = 0
    touched_projects: set[str] = set()
    for row in rows:
        if row.item_status not in {PlanItemStatus.failed.value, PlanItemStatus.skipped.value, "canceled", "stale"}:
            skipped += 1
            continue
        row.item_status = PlanItemStatus.pending.value
        row.last_error = None
        row.updated_at = _utcnow()
        touched_projects.add(row.translation_project_id)
        retried += 1
    for project_id in touched_projects:
        project = db.get(TranslationProject, project_id)
        if project and project.deleted_at is None:
            _refresh_plan_stats(project, db)
    db.commit()
    return {"retried": retried, "skipped": skipped}


@router.post(
    "/translations/projects/{project_id_path}/plan/execute",
    response_model=dict,
)
def execute_translation_plan(
    project_id_path: str,
    body: ExecutePlanRequest,
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")

    q = select(TranslationPlanItem).where(
        TranslationPlanItem.translation_project_id == project_id_path,
        TranslationPlanItem.deleted_at.is_(None),
    ).order_by(TranslationPlanItem.order_no.asc())
    items = db.execute(q).scalars().all()
    if body.selected_item_ids:
        selected = set(body.selected_item_ids)
        items = [i for i in items if i.id in selected]
    if body.only_failed:
        items = [i for i in items if i.item_status == PlanItemStatus.failed.value]
    elif body.only_pending:
        items = [i for i in items if i.item_status == PlanItemStatus.pending.value]
    if body.only_untranslated:
        filtered: list[TranslationPlanItem] = []
        for item in items:
            if not item.chapter_id:
                continue
            has_translated = db.execute(
                select(TranslationBlock.id)
                .join(ScriptBlock, ScriptBlock.id == TranslationBlock.script_block_id)
                .where(
                    ScriptBlock.translation_project_id == project.id,
                    ScriptBlock.chapter_id == item.chapter_id,
                    ScriptBlock.deleted_at.is_(None),
                    TranslationBlock.deleted_at.is_(None),
                )
                .limit(1)
            ).first()
            if not has_translated:
                filtered.append(item)
        items = filtered

    batch = items[: body.batch_size]
    if not batch:
        _refresh_plan_stats(project, db)
        db.commit()
        return {"executed": 0, "succeeded": 0, "failed": 0, "warnings": 0}

    executed = 0
    succeeded = 0
    failed = 0
    warnings_total = 0
    for item in batch:
        item.item_status = PlanItemStatus.running.value
        item.updated_at = _utcnow()
        db.commit()
        try:
            if not item.chapter_id:
                raise HTTPException(status_code=422, detail="plan item missing chapter_id")
            segment_chapters(
                project_id_path=project.id,
                body=SegmentRequest(
                    tenant_id=project.tenant_id,
                    project_id=project.project_id,
                    chapter_id=item.chapter_id,
                ),
                db=db,
            )
            result = translate_blocks(
                project_id_path=project.id,
                body=TranslateRequest(
                    tenant_id=project.tenant_id,
                    project_id=project.project_id,
                    chapter_id=item.chapter_id,
                    model_provider_id=body.model_provider_id,
                    batch_size=min(body.batch_size, max(1, project.batch_size)),
                ),
                db=db,
            )
            item.item_status = PlanItemStatus.succeeded.value
            item.last_error = None
            item.last_run_id = str(result.get("run_id") or "")
            warnings_total += int(result.get("warnings") or 0)
            succeeded += 1
        except Exception as exc:
            item.item_status = PlanItemStatus.failed.value
            item.last_error = str(exc)[:1024]
            item.retry_count = (item.retry_count or 0) + 1
            failed += 1
        finally:
            executed += 1
            item.updated_at = _utcnow()
            db.commit()

    _refresh_plan_stats(project, db)
    db.commit()
    return {
        "executed": executed,
        "succeeded": succeeded,
        "failed": failed,
        "warnings": warnings_total,
    }


@router.post(
    "/translations/projects/{project_id_path}/segment",
    response_model=dict,
)
def segment_chapters(
    project_id_path: str,
    body: SegmentRequest,
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")

    # Fetch chapters to segment
    chapter_query = select(Chapter).where(
        Chapter.novel_id == project.novel_id,
        Chapter.deleted_at.is_(None),
    )
    if body.chapter_id:
        chapter_query = chapter_query.where(Chapter.id == body.chapter_id)
    chapters = db.execute(chapter_query).scalars().all()

    if not chapters:
        raise HTTPException(status_code=404, detail="no chapters found")

    blocks_created = 0
    now = _utcnow()

    for chapter in chapters:
        # Delete existing script blocks for this chapter in this project (re-segment)
        existing_blocks = db.execute(
            select(ScriptBlock).where(
                ScriptBlock.translation_project_id == project.id,
                ScriptBlock.chapter_id == chapter.id,
                ScriptBlock.deleted_at.is_(None),
            )
        ).scalars().all()
        existing_block_ids = [eb.id for eb in existing_blocks]
        for eb in existing_blocks:
            eb.deleted_at = now

        # Soft-delete orphaned TranslationBlocks that referenced the old ScriptBlocks
        if existing_block_ids:
            orphaned_tbs = db.execute(
                select(TranslationBlock).where(
                    TranslationBlock.script_block_id.in_(existing_block_ids),
                    TranslationBlock.deleted_at.is_(None),
                )
            ).scalars().all()
            for otb in orphaned_tbs:
                otb.deleted_at = now

        script_doc = dict(chapter.script_json or {})
        segments: list[dict[str, Any]] = []
        if script_doc.get("scenes"):
            segments = _segment_script_doc(script_doc, chapter.id)
        if not segments:
            text = chapter.raw_text or chapter.cleaned_text or ""
            if not text:
                continue
            segments = _segment_text(text, chapter.id)
        for seg in segments:
            sb = ScriptBlock(
                id=_new_id(),
                tenant_id=project.tenant_id,
                project_id=project.project_id,
                translation_project_id=project.id,
                chapter_id=chapter.id,
                seq_no=seg["seq_no"],
                block_type=seg["block_type"],
                source_text=seg["source_text"],
                speaker_tag=seg["speaker_tag"],
                created_at=now,
                updated_at=now,
            )
            db.add(sb)
            blocks_created += 1

    db.commit()
    return {"blocks_created": blocks_created}


@router.post(
    "/translations/projects/{project_id_path}/translate",
    response_model=dict,
)
def translate_blocks(
    project_id_path: str,
    body: TranslateRequest,
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")

    # Resolve provider: body override first, then project setting
    provider_id = body.model_provider_id or project.model_provider_id
    if not provider_id:
        raise HTTPException(status_code=400, detail="no model provider configured for this project")

    provider = db.get(ModelProvider, provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")

    settings = _load_provider_settings(
        db,
        tenant_id=project.tenant_id,
        project_id=project.project_id,
        provider_id=provider.id,
    )

    # Find script blocks that need translation
    block_query = select(ScriptBlock).where(
        ScriptBlock.translation_project_id == project.id,
        ScriptBlock.deleted_at.is_(None),
    )
    if body.chapter_id:
        block_query = block_query.where(ScriptBlock.chapter_id == body.chapter_id)
    if body.script_block_ids:
        block_query = block_query.where(ScriptBlock.id.in_(body.script_block_ids))
    all_script_blocks = db.execute(block_query.order_by(ScriptBlock.seq_no)).scalars().all()

    # Find blocks that don't have a translation yet (skip if re-translating specific blocks)
    existing_tb_ids = {
        row[0]
        for row in db.execute(
            select(TranslationBlock.script_block_id).where(
                TranslationBlock.translation_project_id == project.id,
                TranslationBlock.deleted_at.is_(None),
            )
        ).all()
    }
    if body.script_block_ids:
        # When targeting specific blocks, translate all of them regardless of existing TB
        pending_blocks = list(all_script_blocks)
    else:
        pending_blocks = [sb for sb in all_script_blocks if sb.id not in existing_tb_ids]

    # Build placeholder maps from entity mappings (replace -> translate -> restore).
    entity_rows = db.execute(
        select(EntityMapping).where(
            EntityMapping.novel_id == project.novel_id,
            EntityMapping.deleted_at.is_(None),
        )
    ).scalars().all()
    source_to_placeholder, placeholder_to_target = _build_placeholder_maps(
        entity_rows,
        project.target_language_code,
        auto_fill_missing_names=project.auto_fill_missing_names,
    )
    db.flush()
    placeholder_text_by_id = {
        sb.id: _apply_placeholders_to_text(sb.source_text, source_to_placeholder)
        for sb in pending_blocks
    }

    # Build term dictionary injection
    term_dict = project.term_dictionary_json or {}
    terms_str = "\n".join(f"  {k} → {v}" for k, v in term_dict.items()) if term_dict else "  (none)"

    # Translation input hash for run persistence and cache reuse.
    translation_input = {
        "project_id": project.id,
        "chapter_id": body.chapter_id,
        "script_block_ids": sorted(body.script_block_ids or []),
        "source_language": project.source_language_code,
        "target_language": project.target_language_code,
        "provider_id": provider.id,
        "term_dict": term_dict,
        "placeholder_to_target": placeholder_to_target,
        "blocks": [
            {
                "id": sb.id,
                "type": sb.block_type.value if hasattr(sb.block_type, "value") else str(sb.block_type),
                "speaker": sb.speaker_tag,
                "text": placeholder_text_by_id.get(sb.id, sb.source_text),
            }
            for sb in pending_blocks
        ],
    }
    input_hash = _compute_input_hash(translation_input)

    if not pending_blocks:
        warnings_count = _run_consistency_check(project, db)
        project.stats_json = {
            "total_blocks": len(all_script_blocks),
            "translated": 0,
            "warnings": warnings_count,
        }
        project.updated_at = _utcnow()
        db.commit()
        return {"translated": 0, "warnings": warnings_count, "run_id": None, "cached": True}

    cached_run = _find_cached_translation_run(db, project=project, input_hash=input_hash)
    if cached_run and isinstance(cached_run.output_json, dict):
        cached_results = list(cached_run.output_json.get("results") or [])
        cached_by_id = {r.get("id"): r for r in cached_results if isinstance(r, dict) and r.get("id")}
        translated_count = 0
        now = _utcnow()
        all_translated_results: list[dict] = []
        for sb in pending_blocks:
            result = cached_by_id.get(sb.id, {})
            translated_text = _restore_placeholders(
                str(result.get("translated_text") or ""),
                placeholder_to_target,
            )
            existing_tb = db.execute(
                select(TranslationBlock).where(
                    TranslationBlock.script_block_id == sb.id,
                    TranslationBlock.translation_project_id == project.id,
                    TranslationBlock.deleted_at.is_(None),
                )
            ).scalars().first()
            if existing_tb:
                existing_tb.translated_text = translated_text
                existing_tb.status = TranslationBlockStatus.draft
                existing_tb.model_provider_id = provider.id
                existing_tb.updated_at = now
            else:
                db.add(
                    TranslationBlock(
                        id=_new_id(),
                        tenant_id=project.tenant_id,
                        project_id=project.project_id,
                        script_block_id=sb.id,
                        translation_project_id=project.id,
                        translated_text=translated_text,
                        status=TranslationBlockStatus.draft,
                        model_provider_id=provider.id,
                        created_at=now,
                        updated_at=now,
                    )
                )
            translated_count += 1
            all_translated_results.append({"id": sb.id, "translated_text": translated_text})

        _extract_entity_variants(all_translated_results, project, db)
        warnings_count = _run_consistency_check(project, db)
        project.stats_json = {
            "total_blocks": len(all_script_blocks),
            "translated": translated_count,
            "warnings": warnings_count,
        }
        project.updated_at = _utcnow()
        db.commit()
        return {
            "translated": translated_count,
            "warnings": warnings_count,
            "run_id": cached_run.id,
            "cached": True,
        }

    translated_count = 0
    all_translated_results: list[dict] = []
    now = _utcnow()
    raw_fragments: list[str] = []

    run = SkillRun(
        id=_new_id(),
        tenant_id=project.tenant_id,
        project_id=project.project_id,
        skill_id="translation_run",
        novel_id=project.novel_id,
        chapter_id=body.chapter_id,
        status=SkillRunStatus.running,
        input_hash=input_hash,
        input_snapshot={
            "project_id": project.id,
            "block_count": len(pending_blocks),
            "target_language": project.target_language_code,
        },
        model_provider_id=provider.id,
        created_at=now,
        updated_at=now,
        version="v1",
        retry_count=0,
    )
    db.add(run)
    db.flush()

    project.status = TranslationProjectStatus.in_progress
    db.commit()

    for batch in _chunks(pending_blocks, body.batch_size):
        system_msg = (
            f"你是专业文学翻译，从 {project.source_language_code} 翻译为 {project.target_language_code}。\n"
            "必须严格保留并原样输出占位符（例如 {{CHAR:xxx}} / {{LOCATION:xxx}}），禁止翻译或改写占位符。\n"
            "保持文学风格，按原文顺序逐块翻译，输出 JSON 数组。\n"
            "每个元素格式: {\"id\": \"...\", \"translated_text\": \"...\"}\n"
            f"术语表（必须严格遵守，不得更改）：\n{terms_str}"
        )
        user_content = json.dumps(
            [
                {
                    "id": sb.id,
                    "type": sb.block_type.value if hasattr(sb.block_type, "value") else str(sb.block_type),
                    "text": placeholder_text_by_id.get(sb.id, sb.source_text),
                    "speaker": sb.speaker_tag,
                }
                for sb in batch
            ],
            ensure_ascii=False,
        )
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_content},
        ]

        try:
            raw_response = _call_provider_with_messages(
                provider=provider,
                provider_settings=settings,
                messages=messages,
                max_tokens=3000,
            )
            raw_fragments.append(raw_response)
        except (requests.RequestException, ValueError) as exc:
            run.status = SkillRunStatus.failed
            run.error_message = str(exc)[:512]
            run.updated_at = _utcnow()
            db.commit()
            raise HTTPException(
                status_code=502,
                detail=f"LLM call failed: {exc}",
            )

        json_text = raw_response
        md_match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw_response)
        if md_match:
            json_text = md_match.group(1).strip()
        else:
            arr_match = re.search(r"(\[[\s\S]+\])", raw_response)
            if arr_match:
                json_text = arr_match.group(1)

        try:
            results: list[dict] = json.loads(json_text)
        except (json.JSONDecodeError, ValueError):
            results = [{"id": sb.id, "translated_text": ""} for sb in batch]

        results_by_id = {r.get("id"): r for r in results if isinstance(r, dict) and r.get("id")}

        for sb in batch:
            result = results_by_id.get(sb.id)
            translated_text = _restore_placeholders(
                (result or {}).get("translated_text") or "",
                placeholder_to_target,
            )

            existing_tb = db.execute(
                select(TranslationBlock).where(
                    TranslationBlock.script_block_id == sb.id,
                    TranslationBlock.translation_project_id == project.id,
                    TranslationBlock.deleted_at.is_(None),
                )
            ).scalars().first()

            if existing_tb:
                existing_tb.translated_text = translated_text
                existing_tb.status = TranslationBlockStatus.draft
                existing_tb.model_provider_id = provider.id
                existing_tb.updated_at = now
            else:
                db.add(
                    TranslationBlock(
                        id=_new_id(),
                        tenant_id=project.tenant_id,
                        project_id=project.project_id,
                        script_block_id=sb.id,
                        translation_project_id=project.id,
                        translated_text=translated_text,
                        status=TranslationBlockStatus.draft,
                        model_provider_id=provider.id,
                        created_at=now,
                        updated_at=now,
                    )
                )
            translated_count += 1
            all_translated_results.append({"id": sb.id, "translated_text": translated_text})

        db.commit()

    _extract_entity_variants(all_translated_results, project, db)
    warnings_count = _run_consistency_check(project, db)
    project.stats_json = {
        "total_blocks": len(all_script_blocks),
        "translated": translated_count,
        "warnings": warnings_count,
    }
    project.updated_at = _utcnow()
    run.status = SkillRunStatus.succeeded
    run.output_json = {
        "results": all_translated_results,
        "translated": translated_count,
        "warnings": warnings_count,
    }
    run.raw_response = "\n\n".join(raw_fragments)[:4000] if raw_fragments else None
    run.updated_at = _utcnow()
    db.commit()

    return {"translated": translated_count, "warnings": warnings_count, "run_id": run.id, "cached": False}


@router.get(
    "/translations/projects/{project_id_path}/blocks",
    response_model=list[ScriptBlockResponse],
)
def list_script_blocks(
    project_id_path: str,
    chapter_id: str | None = Query(default=None),
    tenant_id: str = Query(default="default"),
    project_id: str = Query(default="default"),
    db: Session = Depends(get_db),
) -> list[ScriptBlockResponse]:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")

    block_q = select(ScriptBlock).where(
        ScriptBlock.translation_project_id == project_id_path,
        ScriptBlock.deleted_at.is_(None),
    )
    if chapter_id:
        block_q = block_q.where(ScriptBlock.chapter_id == chapter_id)
    script_blocks = db.execute(block_q.order_by(ScriptBlock.seq_no)).scalars().all()

    # Fetch all translation blocks for this project
    tb_by_script = {}
    if script_blocks:
        tbs = db.execute(
            select(TranslationBlock).where(
                TranslationBlock.translation_project_id == project_id_path,
                TranslationBlock.deleted_at.is_(None),
            )
        ).scalars().all()
        tb_by_script = {tb.script_block_id: tb for tb in tbs}

    return [_to_block_response(sb, tb_by_script.get(sb.id)) for sb in script_blocks]


@router.patch(
    "/translations/projects/{project_id_path}/blocks/{block_id}",
    response_model=TranslationBlockResponse,
)
def update_translation_block(
    project_id_path: str,
    block_id: str,
    body: UpdateTranslationBlockRequest,
    db: Session = Depends(get_db),
) -> TranslationBlockResponse:
    tb = db.get(TranslationBlock, block_id)
    if tb is None or tb.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation block not found")
    if tb.translation_project_id != project_id_path:
        raise HTTPException(status_code=403, detail="block does not belong to this project")

    if body.translated_text is not None:
        tb.translated_text = body.translated_text
    if body.translation_notes is not None:
        tb.translation_notes = body.translation_notes
    if body.status is not None:
        try:
            tb.status = TranslationBlockStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {body.status}")
    tb.updated_at = _utcnow()
    db.commit()
    db.refresh(tb)
    return TranslationBlockResponse(
        id=tb.id,
        translated_text=tb.translated_text,
        status=tb.status.value if hasattr(tb.status, "value") else str(tb.status),
        translation_notes=tb.translation_notes,
    )


@router.delete(
    "/translations/projects/{project_id_path}/blocks/{block_id}",
    response_model=dict,
)
def delete_translation_block(
    project_id_path: str,
    block_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Soft-delete a translation block (clears the translated text, allows re-translation)."""
    tb = db.get(TranslationBlock, block_id)
    if tb is None or tb.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation block not found")
    if tb.translation_project_id != project_id_path:
        raise HTTPException(status_code=403, detail="block does not belong to this project")
    tb.deleted_at = _utcnow()
    tb.updated_at = _utcnow()
    db.commit()
    return {"deleted": True, "block_id": block_id}


@router.get(
    "/translations/projects/{project_id_path}/entities",
    response_model=list[EntityNameVariantResponse],
)
def list_entity_variants(
    project_id_path: str,
    tenant_id: str = Query(default="default"),
    project_id: str = Query(default="default"),
    db: Session = Depends(get_db),
) -> list[EntityNameVariantResponse]:
    variants = db.execute(
        select(EntityNameVariant).where(
            EntityNameVariant.translation_project_id == project_id_path,
            EntityNameVariant.deleted_at.is_(None),
        )
    ).scalars().all()
    return [
        EntityNameVariantResponse(
            id=v.id,
            source_name=v.source_name,
            canonical_target_name=v.canonical_target_name,
            is_locked=v.is_locked,
            aliases_json=v.aliases_json,
            entity_id=v.entity_id,
        )
        for v in variants
    ]


@router.post(
    "/translations/projects/{project_id_path}/entities",
    response_model=EntityNameVariantResponse,
)
def create_entity_variant(
    project_id_path: str,
    body: CreateEntityVariantRequest,
    db: Session = Depends(get_db),
) -> EntityNameVariantResponse:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")

    now = _utcnow()
    v = EntityNameVariant(
        id=_new_id(),
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        translation_project_id=project_id_path,
        entity_id=body.entity_id,
        source_name=body.source_name,
        canonical_target_name=body.canonical_target_name,
        is_locked=False,
        aliases_json=body.aliases_json or [],
        created_at=now,
        updated_at=now,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return EntityNameVariantResponse(
        id=v.id,
        source_name=v.source_name,
        canonical_target_name=v.canonical_target_name,
        is_locked=v.is_locked,
        aliases_json=v.aliases_json,
        entity_id=v.entity_id,
    )


@router.patch(
    "/translations/projects/{project_id_path}/entities/{variant_id}/lock",
    response_model=EntityNameVariantResponse,
)
def lock_entity_variant(
    project_id_path: str,
    variant_id: str,
    body: LockEntityVariantRequest,
    db: Session = Depends(get_db),
) -> EntityNameVariantResponse:
    v = db.get(EntityNameVariant, variant_id)
    if v is None or v.deleted_at is not None:
        raise HTTPException(status_code=404, detail="entity variant not found")
    if v.translation_project_id != project_id_path:
        raise HTTPException(status_code=403, detail="variant does not belong to this project")

    v.canonical_target_name = body.canonical_target_name
    v.is_locked = True
    v.updated_at = _utcnow()
    db.commit()
    db.refresh(v)
    return EntityNameVariantResponse(
        id=v.id,
        source_name=v.source_name,
        canonical_target_name=v.canonical_target_name,
        is_locked=v.is_locked,
        aliases_json=v.aliases_json,
        entity_id=v.entity_id,
    )


@router.get(
    "/translations/projects/{project_id_path}/warnings",
    response_model=list[ConsistencyWarningResponse],
)
def list_consistency_warnings(
    project_id_path: str,
    status: str | None = Query(default=None),
    tenant_id: str = Query(default="default"),
    db: Session = Depends(get_db),
) -> list[ConsistencyWarningResponse]:
    q = select(ConsistencyWarning).where(
        ConsistencyWarning.translation_project_id == project_id_path,
        ConsistencyWarning.deleted_at.is_(None),
    )
    if status:
        try:
            q = q.where(ConsistencyWarning.status == WarningStatus(status))
        except ValueError:
            pass
    warnings = db.execute(q).scalars().all()
    return [
        ConsistencyWarningResponse(
            id=w.id,
            warning_type=w.warning_type.value if hasattr(w.warning_type, "value") else str(w.warning_type),
            source_name=w.source_name,
            detected_variant=w.detected_variant,
            expected_canonical=w.expected_canonical,
            status=w.status.value if hasattr(w.status, "value") else str(w.status),
            translation_block_id=w.translation_block_id,
        )
        for w in warnings
    ]


@router.patch(
    "/translations/projects/{project_id_path}/warnings/{warning_id}",
    response_model=ConsistencyWarningResponse,
)
def resolve_warning(
    project_id_path: str,
    warning_id: str,
    body: ResolveWarningRequest,
    db: Session = Depends(get_db),
) -> ConsistencyWarningResponse:
    w = db.get(ConsistencyWarning, warning_id)
    if w is None or w.deleted_at is not None:
        raise HTTPException(status_code=404, detail="warning not found")
    if w.translation_project_id != project_id_path:
        raise HTTPException(status_code=403, detail="warning does not belong to this project")

    try:
        w.status = WarningStatus(body.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid status: {body.status}")
    w.updated_at = _utcnow()
    db.commit()
    db.refresh(w)
    return ConsistencyWarningResponse(
        id=w.id,
        warning_type=w.warning_type.value if hasattr(w.warning_type, "value") else str(w.warning_type),
        source_name=w.source_name,
        detected_variant=w.detected_variant,
        expected_canonical=w.expected_canonical,
        status=w.status.value if hasattr(w.status, "value") else str(w.status),
        translation_block_id=w.translation_block_id,
    )


@router.post(
    "/translations/projects/{project_id_path}/check-consistency",
    response_model=dict,
)
def check_consistency(
    project_id_path: str,
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")

    warnings_created = _run_consistency_check(project, db)
    db.commit()
    return {"warnings_created": warnings_created}


@router.get("/translations/projects/{project_id_path}/conflicts", response_model=list[ConsistencyWarningResponse])
def list_translation_conflicts(
    project_id_path: str,
    lang: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ConsistencyWarningResponse]:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")
    if lang and lang not in {project.target_language_code, project.target_language_code.split("-")[0]}:
        return []
    q = select(ConsistencyWarning).where(
        ConsistencyWarning.translation_project_id == project_id_path,
        ConsistencyWarning.deleted_at.is_(None),
        ConsistencyWarning.status == WarningStatus.open,
    ).order_by(ConsistencyWarning.created_at.desc())
    warnings = db.execute(q).scalars().all()
    return [
        ConsistencyWarningResponse(
            id=w.id,
            warning_type=w.warning_type.value if hasattr(w.warning_type, "value") else str(w.warning_type),
            source_name=w.source_name,
            detected_variant=w.detected_variant,
            expected_canonical=w.expected_canonical,
            status=w.status.value if hasattr(w.status, "value") else str(w.status),
            translation_block_id=w.translation_block_id,
        )
        for w in warnings
    ]


@router.get("/translations/projects/{project_id_path}/drift", response_model=list[dict])
def list_translation_drift(
    project_id_path: str,
    lang: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")
    target_lang = lang or project.target_language_code
    entities = db.execute(
        select(EntityMapping).where(
            EntityMapping.novel_id == project.novel_id,
            EntityMapping.deleted_at.is_(None),
        )
    ).scalars().all()
    rows: list[dict] = []
    for e in entities:
        translations = dict(e.translations_json or {})
        expected = translations.get(target_lang) or translations.get(target_lang.split("-")[0])
        if not expected:
            continue
        rows.append(
            {
                "entity_id": e.id,
                "canonical_name": e.canonical_name,
                "target_lang": target_lang,
                "expected_name": expected,
                "drift_score": float(e.drift_score or 0.0),
                "locked": bool((e.locked_langs_json or {}).get(target_lang) or e.locked),
            }
        )
    rows.sort(key=lambda r: r["drift_score"], reverse=True)
    return rows


@router.post(
    "/translations/projects/{project_id_path}/run-gate",
    response_model=TranslationRunGateResponse,
)
def gate_translation_project_run(
    project_id_path: str,
    body: TranslationRunGateRequest,
    db: Session = Depends(get_db),
) -> TranslationRunGateResponse:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")
    return _build_run_gate(project, body.chapter_id, db)


@router.post(
    "/translations/projects/{project_id_path}/create-run",
    response_model=TranslationCreateRunResponse,
    status_code=202,
)
def create_run_from_translation_project(
    project_id_path: str,
    body: TranslationCreateRunRequest,
    db: Session = Depends(get_db),
) -> TranslationCreateRunResponse:
    project = db.get(TranslationProject, project_id_path)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="translation project not found")

    gate = _build_run_gate(project, body.chapter_id, db)
    if body.dry_run:
        return TranslationCreateRunResponse(
            run_id=None,
            status="dry_run",
            chapter_id=gate.chapter_id,
            gate=gate,
            message="dry_run only, no run created",
        )
    if not gate.ready_to_run or not gate.chapter_id:
        return TranslationCreateRunResponse(
            run_id=None,
            status="blocked",
            chapter_id=gate.chapter_id,
            gate=gate,
            message="run prerequisites are not ready",
        )

    now = _utcnow()
    submit = TaskSubmitRequest(
        tenant_id=body.tenant_id or project.tenant_id,
        project_id=body.project_id or project.project_id,
        chapter_id=gate.chapter_id,
        requested_quality=body.requested_quality,
        language_context=body.language_context or project.target_language_code,
        payload={
            "source_language": project.source_language_code,
            "target_language": project.target_language_code,
            "translation_project_id": project.id,
            "culture_mode": project.culture_mode,
            "culture_packs": project.culture_packs_json or [],
            "temporal_enabled": project.temporal_enabled,
            "temporal_layers": project.temporal_layers_json or [],
            "force_rerun": body.force_rerun,
            "use_cache": body.use_cache,
            "consistency_mode": (
                project.consistency_mode.value
                if hasattr(project.consistency_mode, "value")
                else str(project.consistency_mode)
            ),
            "model_provider_id": project.model_provider_id,
        },
        trace_id=f"tr_from_translation_{uuid4().hex[:12]}",
        correlation_id=f"cr_from_translation_{uuid4().hex[:12]}",
        idempotency_key=(
            f"idem_translation_run_{project.id}_{gate.chapter_id}_{int(now.timestamp())}"
        ),
    )
    accepted: TaskSubmitAccepted = create_task(submit, db)
    return TranslationCreateRunResponse(
        run_id=accepted.run_id,
        status=accepted.status,
        chapter_id=gate.chapter_id,
        gate=gate,
        message=accepted.message,
    )
