from __future__ import annotations

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

from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider
from ainern2d_shared.ainer_db_models.translation_models import (
    BlockType,
    ConsistencyMode,
    ConsistencyWarning,
    EntityNameVariant,
    ScriptBlock,
    TranslationBlock,
    TranslationBlockStatus,
    TranslationProject,
    TranslationProjectStatus,
    WarningStatus,
    WarningType,
)

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


class UpdateTranslationProjectRequest(BaseModel):
    term_dictionary_json: dict[str, str] | None = None
    consistency_mode: ConsistencyMode | None = None
    model_provider_id: str | None = None
    status: TranslationProjectStatus | None = None


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
    created_at: datetime


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
    locked_variants = db.execute(
        select(EntityNameVariant).where(
            EntityNameVariant.translation_project_id == project.id,
            EntityNameVariant.is_locked == True,  # noqa: E712
            EntityNameVariant.deleted_at.is_(None),
        )
    ).scalars().all()

    warnings_created = 0
    for variant in locked_variants:
        aliases = variant.aliases_json or []
        for alias in aliases:
            if alias == variant.canonical_target_name:
                continue
            # Find translation blocks that contain this alias
            all_blocks = db.execute(
                select(TranslationBlock).where(
                    TranslationBlock.translation_project_id == project.id,
                    TranslationBlock.deleted_at.is_(None),
                    TranslationBlock.translated_text.isnot(None),
                )
            ).scalars().all()
            for tb in all_blocks:
                text = tb.translated_text or ""
                if alias not in text:
                    continue

                # Deduplicate: don't create same warning twice
                existing = db.execute(
                    select(ConsistencyWarning).where(
                        ConsistencyWarning.translation_project_id == project.id,
                        ConsistencyWarning.translation_block_id == tb.id,
                        ConsistencyWarning.detected_variant == alias,
                        ConsistencyWarning.status == WarningStatus.open,
                        ConsistencyWarning.deleted_at.is_(None),
                    )
                ).scalars().first()
                if existing:
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

    # Callers are responsible for committing — do not commit here.
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
        created_at=p.created_at,
    )


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
        stats_json=None,
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _to_project_response(project)


@router.get("/translations/projects", response_model=list[TranslationProjectResponse])
def list_translation_projects(
    novel_id: str = Query(...),
    tenant_id: str = Query(default="default"),
    project_id: str = Query(default="default"),
    db: Session = Depends(get_db),
) -> list[TranslationProjectResponse]:
    rows = db.execute(
        select(TranslationProject).where(
            TranslationProject.novel_id == novel_id,
            TranslationProject.tenant_id == tenant_id,
            TranslationProject.project_id == project_id,
            TranslationProject.deleted_at.is_(None),
        )
    ).scalars().all()
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

    if not project.model_provider_id:
        raise HTTPException(status_code=400, detail="no model provider configured for this project")

    provider = db.get(ModelProvider, project.model_provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")

    settings = _load_provider_settings(
        db,
        tenant_id=project.tenant_id,
        project_id=project.project_id,
        provider_id=provider.id,
    )

    # Find script blocks that need translation (no TranslationBlock yet)
    block_query = select(ScriptBlock).where(
        ScriptBlock.translation_project_id == project.id,
        ScriptBlock.deleted_at.is_(None),
    )
    if body.chapter_id:
        block_query = block_query.where(ScriptBlock.chapter_id == body.chapter_id)
    all_script_blocks = db.execute(block_query.order_by(ScriptBlock.seq_no)).scalars().all()

    # Find blocks that don't have a translation yet
    existing_tb_ids = {
        row[0]
        for row in db.execute(
            select(TranslationBlock.script_block_id).where(
                TranslationBlock.translation_project_id == project.id,
                TranslationBlock.deleted_at.is_(None),
            )
        ).all()
    }
    pending_blocks = [sb for sb in all_script_blocks if sb.id not in existing_tb_ids]

    # Build term dictionary injection
    term_dict = project.term_dictionary_json or {}
    terms_str = "\n".join(f"  {k} → {v}" for k, v in term_dict.items()) if term_dict else "  (none)"

    translated_count = 0
    all_translated_results: list[dict] = []
    now = _utcnow()

    # Update project status
    project.status = TranslationProjectStatus.in_progress
    db.commit()

    for batch in _chunks(pending_blocks, body.batch_size):
        system_msg = (
            f"你是专业文学翻译，从 {project.source_language_code} 翻译为 {project.target_language_code}。\n"
            "保持文学风格，按原文顺序逐块翻译，输出 JSON 数组。\n"
            "每个元素格式: {\"id\": \"...\", \"translated_text\": \"...\"}\n"
            f"术语表（必须严格遵守，不得更改）：\n{terms_str}"
        )
        user_content = json.dumps(
            [
                {
                    "id": sb.id,
                    "type": sb.block_type.value if hasattr(sb.block_type, "value") else str(sb.block_type),
                    "text": sb.source_text,
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
        except (requests.RequestException, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"LLM call failed: {exc}",
            )

        # Parse JSON array from response
        # Try to extract JSON array from response (LLM may wrap in markdown code blocks)
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
            # If JSON parse fails, create draft blocks with empty translation
            results = [{"id": sb.id, "translated_text": ""} for sb in batch]

        # Map results by id
        results_by_id = {r.get("id"): r for r in results if isinstance(r, dict) and r.get("id")}

        for sb in batch:
            result = results_by_id.get(sb.id)
            translated_text = (result or {}).get("translated_text") or ""

            tb = TranslationBlock(
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
            db.add(tb)
            translated_count += 1
            all_translated_results.append({"id": sb.id, "translated_text": translated_text})

        db.commit()

    # Extract entity name variants from translated results
    _extract_entity_variants(all_translated_results, project, db)

    # Run consistency check
    warnings_count = _run_consistency_check(project, db)

    # Update stats
    project.stats_json = {
        "total_blocks": len(all_script_blocks),
        "translated": translated_count,
        "warnings": warnings_count,
    }
    project.updated_at = _utcnow()
    db.commit()

    return {"translated": translated_count, "warnings": warnings_count}


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
