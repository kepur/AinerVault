"""entity_mapping.py — 实体对应表 CRUD API

Endpoints:
  POST   /api/v1/novels/{novel_id}/entity-mapping/build
  GET    /api/v1/novels/{novel_id}/entity-mapping
  GET    /api/v1/entity-mapping/{entity_uid}
  PATCH  /api/v1/entity-mapping/{entity_uid}
  POST   /api/v1/entity-mapping/{entity_uid}/merge
  POST   /api/v1/entity-mapping/{entity_uid}/translate
  DELETE /api/v1/entity-mapping/{entity_uid}
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
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
    EntityMappingType,
    Novel,
)
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider

from app.api.deps import get_db
from app.api.v1.translation import _call_provider_with_messages, _load_provider_settings

router = APIRouter(prefix="/api/v1", tags=["entity-mapping"])
logger = logging.getLogger(__name__)


# ── Pydantic models ────────────────────────────────────────────────────────────

class EntityMappingItem(BaseModel):
    id: str
    novel_id: str | None
    entity_type: str | None
    canonical_name: str
    source_language: str
    translations_json: dict | None
    translations: dict | None
    aliases_json: list | None
    culture_tags_json: list | None
    world_model_source: str | None
    anchor_asset_id: str | None
    continuity_status: str
    notes: str | None
    # Naming localization fields
    naming_policy: str | None
    locked: bool
    style_tags_json: list | None
    rationale: str | None
    localization_candidates_json: list | None
    localization_candidates: list | None
    drift_score: float
    locked_langs_json: dict | None
    naming_policy_by_lang_json: dict | None
    updated_by_ai: bool
    created_at: str | None
    updated_at: str | None


class BuildEntityMappingRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"


class BuildEntityMappingResponse(BaseModel):
    created: int
    updated: int
    total: int


class UpdateEntityMappingRequest(BaseModel):
    canonical_name: str | None = None
    translations_json: dict | None = None
    aliases_json: list | None = None
    culture_tags_json: list | None = None
    anchor_asset_id: str | None = None
    continuity_status: str | None = None
    notes: str | None = None
    naming_policy: str | None = None
    locked: bool | None = None
    style_tags_json: list | None = None
    rationale: str | None = None
    localization_candidates_json: list | None = None
    drift_score: float | None = None
    locked_langs_json: dict | None = None
    naming_policy_by_lang_json: dict | None = None


class MergeEntityMappingRequest(BaseModel):
    target_uid: str


class TranslateEntityMappingRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    model_provider_id: str
    target_languages: list[str] = Field(default_factory=lambda: ["en-US", "ja-JP"])


# ── Helper ─────────────────────────────────────────────────────────────────────

def _entity_to_item(e: EntityMapping) -> EntityMappingItem:
    return EntityMappingItem(
        id=e.id,
        novel_id=e.novel_id,
        entity_type=e.entity_type.value if e.entity_type else None,
        canonical_name=e.canonical_name,
        source_language=e.source_language,
        translations_json=e.translations_json,
        translations=e.translations_json,
        aliases_json=e.aliases_json,
        culture_tags_json=e.culture_tags_json,
        world_model_source=e.world_model_source,
        anchor_asset_id=e.anchor_asset_id,
        continuity_status=e.continuity_status.value if e.continuity_status else "unbound",
        notes=e.notes,
        naming_policy=e.naming_policy,
        locked=e.locked if e.locked is not None else False,
        style_tags_json=e.style_tags_json,
        rationale=e.rationale,
        localization_candidates_json=e.localization_candidates_json,
        localization_candidates=e.localization_candidates_json,
        drift_score=float(e.drift_score or 0.0),
        locked_langs_json=e.locked_langs_json,
        naming_policy_by_lang_json=e.naming_policy_by_lang_json,
        updated_by_ai=e.updated_by_ai if e.updated_by_ai is not None else False,
        created_at=e.created_at.isoformat() if e.created_at else None,
        updated_at=e.updated_at.isoformat() if e.updated_at else None,
    )


def _get_entity_or_404(db: Session, entity_uid: str) -> EntityMapping:
    entity = db.get(EntityMapping, entity_uid)
    if entity is None or entity.deleted_at is not None:
        raise HTTPException(status_code=404, detail="entity mapping not found")
    return entity


_CANONICAL_BIRTHNAME_RE = re.compile(
    r"^\s*(?P<display>.+?)\s*[（(]\s*(?:本名|原名|实名)\s*(?P<birth>.+?)\s*[)）]\s*$"
)
FORBIDDEN_PINYIN_PARTS = {
    "wang", "li", "zhang", "chen", "liu", "yang", "zhao", "huang", "wu", "zhou",
    "xu", "sun", "ma", "hu", "guo", "he", "lin", "luo", "gao", "xie",
    "youfu", "mazi", "xiuying", "ergou", "dazhuang", "xiaoming",
}
LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\\-]*")


def _split_display_and_birth_name(canonical_name: str) -> tuple[str, str | None]:
    text = str(canonical_name or "").strip()
    m = _CANONICAL_BIRTHNAME_RE.match(text)
    if not m:
        return text, None
    return m.group("display").strip(), m.group("birth").strip()


def _contains_pinyin_transliteration(name: str) -> bool:
    tokens = [t.lower() for t in LATIN_TOKEN_RE.findall(name)]
    return any(token in FORBIDDEN_PINYIN_PARTS for token in tokens)


def _is_valid_localized_name(name: str, target_language: str) -> bool:
    value = str(name or "").strip()
    if not value:
        return False
    if _contains_pinyin_transliteration(value):
        return False
    if target_language.startswith("en") and len(LATIN_TOKEN_RE.findall(value)) < 2:
        return False
    return True


def _fallback_localized_name(target_language: str, seed: str) -> str:
    if target_language.startswith("ja"):
        pool = ["ハヤト", "タクミ", "リョウ", "ユウタ", "ソラ", "ケン"]
        return pool[hash(seed) % len(pool)]
    pool = [
        "Jonny Miller",
        "Ethan Brooks",
        "Liam Carter",
        "Noah Parker",
        "Mason Turner",
        "Caleb Walker",
    ]
    return pool[hash(seed) % len(pool)]


def _parse_json_object(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if not m:
        raise ValueError("No JSON found")
    parsed = json.loads(m.group())
    if not isinstance(parsed, dict):
        raise ValueError("Non-dict JSON")
    return parsed


# ── Build (批量生成/更新) ──────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/entity-mapping/build", response_model=BuildEntityMappingResponse)
def build_entity_mapping(
    novel_id: str,
    body: BuildEntityMappingRequest,
    db: Session = Depends(get_db),
) -> BuildEntityMappingResponse:
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")

    # Load all chapters for this novel
    chapters = db.execute(
        select(Chapter).where(
            Chapter.novel_id == novel_id,
            Chapter.deleted_at.is_(None),
        )
    ).scalars().all()

    created = 0
    updated = 0

    # Build lookup: (canonical_name, entity_type) → existing EntityMapping
    existing_rows = db.execute(
        select(EntityMapping).where(
            EntityMapping.novel_id == novel_id,
            EntityMapping.deleted_at.is_(None),
        )
    ).scalars().all()
    lookup: dict[tuple[str, str], EntityMapping] = {
        (e.canonical_name, e.entity_type.value if e.entity_type else ""): e
        for e in existing_rows
    }

    def _upsert(
        name: str,
        etype: str,
        chapter_id: str,
        extra: dict,
    ) -> None:
        nonlocal created, updated
        key = (name, etype)
        if key in lookup:
            em = lookup[key]
            # Accumulate aliases
            existing_aliases: list = list(em.aliases_json or [])
            for alias in extra.get("aliases", []):
                if alias and alias not in existing_aliases and alias != name:
                    existing_aliases.append(alias)
            em.aliases_json = existing_aliases
            em.updated_at = datetime.now(timezone.utc)
            updated += 1
        else:
            em = EntityMapping(
                id=str(uuid4()).replace("-", ""),
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                novel_id=novel_id,
                entity_type=EntityMappingType(etype),
                canonical_name=name,
                source_language="zh-CN",
                aliases_json=[a for a in extra.get("aliases", []) if a and a != name],
                culture_tags_json=extra.get("tags", []),
                world_model_source=chapter_id,
                continuity_status=EntityContinuityStatus.unbound,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                version="v1",
                retry_count=0,
            )
            db.add(em)
            lookup[key] = em
            created += 1

    # Iterate chapters world_model_json
    for chapter in chapters:
        wm = chapter.world_model_json or {}

        for char in wm.get("characters", []):
            name = char.get("name", "").strip()
            if not name:
                continue
            _upsert(name, EntityMappingType.character.value, chapter.id, {
                "aliases": char.get("aliases", []),
            })

        for loc in wm.get("locations", []):
            name = loc.get("name", "").strip()
            if not name:
                continue
            _upsert(name, EntityMappingType.location.value, chapter.id, {})

        for prop in wm.get("props", []):
            name = prop.get("name", "").strip()
            if not name:
                continue
            _upsert(name, EntityMappingType.prop.value, chapter.id, {})

        for sh in wm.get("style_hints", []):
            genre_tags = sh.get("genre_tags", [])
            for tag in genre_tags:
                tag = str(tag).strip()
                if tag:
                    _upsert(tag, EntityMappingType.style.value, chapter.id, {})

    db.commit()

    total = db.execute(
        select(EntityMapping).where(
            EntityMapping.novel_id == novel_id,
            EntityMapping.deleted_at.is_(None),
        )
    ).scalars().all().__len__()

    return BuildEntityMappingResponse(created=created, updated=updated, total=total)


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/entity-mapping", response_model=list[EntityMappingItem])
def list_entity_mappings(
    novel_id: str,
    keyword: str | None = Query(None),
    entity_type: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[EntityMappingItem]:
    q = select(EntityMapping).where(
        EntityMapping.novel_id == novel_id,
        EntityMapping.deleted_at.is_(None),
    )
    if entity_type:
        q = q.where(EntityMapping.entity_type == entity_type)
    if status:
        q = q.where(EntityMapping.continuity_status == status)
    rows = db.execute(q).scalars().all()

    if keyword:
        kw = keyword.lower()
        rows = [
            r for r in rows
            if kw in r.canonical_name.lower()
            or any(kw in str(a).lower() for a in (r.aliases_json or []))
        ]

    return [_entity_to_item(r) for r in rows]


# ── Get detail ─────────────────────────────────────────────────────────────────

@router.get("/entity-mapping/{entity_uid}", response_model=EntityMappingItem)
def get_entity_mapping(
    entity_uid: str,
    db: Session = Depends(get_db),
) -> EntityMappingItem:
    return _entity_to_item(_get_entity_or_404(db, entity_uid))


# ── Update ─────────────────────────────────────────────────────────────────────

@router.patch("/entity-mapping/{entity_uid}", response_model=EntityMappingItem)
def update_entity_mapping(
    entity_uid: str,
    body: UpdateEntityMappingRequest,
    db: Session = Depends(get_db),
) -> EntityMappingItem:
    entity = _get_entity_or_404(db, entity_uid)

    if body.canonical_name is not None:
        entity.canonical_name = body.canonical_name
    if body.translations_json is not None:
        entity.translations_json = body.translations_json
    if body.aliases_json is not None:
        entity.aliases_json = body.aliases_json
    if body.culture_tags_json is not None:
        entity.culture_tags_json = body.culture_tags_json
    if body.anchor_asset_id is not None:
        entity.anchor_asset_id = body.anchor_asset_id
    if body.continuity_status is not None:
        try:
            entity.continuity_status = EntityContinuityStatus(body.continuity_status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"invalid continuity_status: {body.continuity_status}")
    if body.notes is not None:
        entity.notes = body.notes
    if body.naming_policy is not None:
        entity.naming_policy = body.naming_policy
    if body.locked is not None:
        entity.locked = body.locked
    if body.style_tags_json is not None:
        entity.style_tags_json = body.style_tags_json
    if body.rationale is not None:
        entity.rationale = body.rationale
    if body.localization_candidates_json is not None:
        entity.localization_candidates_json = body.localization_candidates_json
    if body.drift_score is not None:
        entity.drift_score = body.drift_score
    if body.locked_langs_json is not None:
        entity.locked_langs_json = body.locked_langs_json
    if body.naming_policy_by_lang_json is not None:
        entity.naming_policy_by_lang_json = body.naming_policy_by_lang_json

    entity.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entity)
    return _entity_to_item(entity)


# ── Merge ──────────────────────────────────────────────────────────────────────

@router.post("/entity-mapping/{entity_uid}/merge", response_model=EntityMappingItem)
def merge_entity_mapping(
    entity_uid: str,
    body: MergeEntityMappingRequest,
    db: Session = Depends(get_db),
) -> EntityMappingItem:
    source = _get_entity_or_404(db, entity_uid)
    target = _get_entity_or_404(db, body.target_uid)

    # Merge aliases from source into target
    target_aliases: list = list(target.aliases_json or [])
    # Add source canonical_name as alias of target
    if source.canonical_name not in target_aliases and source.canonical_name != target.canonical_name:
        target_aliases.append(source.canonical_name)
    # Add source's aliases
    for alias in source.aliases_json or []:
        if alias not in target_aliases:
            target_aliases.append(alias)
    target.aliases_json = target_aliases
    target.updated_at = datetime.now(timezone.utc)

    # Soft-delete source
    source.deleted_at = datetime.now(timezone.utc)
    source.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(target)
    return _entity_to_item(target)


# ── Translate ──────────────────────────────────────────────────────────────────

@router.post("/entity-mapping/{entity_uid}/translate", response_model=EntityMappingItem)
def translate_entity_mapping(
    entity_uid: str,
    body: TranslateEntityMappingRequest,
    db: Session = Depends(get_db),
) -> EntityMappingItem:
    entity = _get_entity_or_404(db, entity_uid)
    provider = db.get(ModelProvider, body.model_provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")

    langs = ", ".join(body.target_languages)
    display_name, _birth_name = _split_display_and_birth_name(entity.canonical_name)
    existing_translations = dict(entity.translations_json or {})
    provider_chain = [provider]
    fallback_rows = db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == body.tenant_id,
            ModelProvider.project_id == body.project_id,
            ModelProvider.deleted_at.is_(None),
            ModelProvider.id != provider.id,
        ).limit(3)
    ).scalars().all()
    provider_chain.extend(fallback_rows)

    normalized: dict[str, str] = {}
    for candidate_provider in provider_chain:
        try:
            candidate_settings = _load_provider_settings(
                db,
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                provider_id=candidate_provider.id,
            )
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是顶级姓名本地化顾问。当前任务是“补译名=一次性本土化命名”。\n"
                        "硬规则：\n"
                        "1) 绝对禁止任何拼音/音译片段（含姓氏与名）：Wang/Li/Zhang/Mazi/Youfu 等；\n"
                        "2) 对 en-US/en-GB 必须输出完整本地姓名（至少 first + last）；\n"
                        "3) 各语言都要给出目标文化母语者自然姓名；\n"
                        "4) 仅输出 JSON。\n"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"将人物名 '{display_name}' 本土化到以下语言：{langs}。\n"
                        f"当前已有译名（可参考但不强制沿用）：{json.dumps(existing_translations, ensure_ascii=False)}\n"
                        "输出 JSON：{\"en-US\":\"...\",\"ja-JP\":\"...\"}。"
                    ),
                },
            ]
            raw = _call_provider_with_messages(
                provider=candidate_provider,
                provider_settings=candidate_settings,
                messages=messages,
                max_tokens=512,
            )
            translations = _parse_json_object(raw)
            for lang in body.target_languages:
                if lang in normalized:
                    continue
                value = str(translations.get(lang) or "").strip()
                if not _is_valid_localized_name(value, lang):
                    continue
                normalized[lang] = value
            if all(lang in normalized for lang in body.target_languages):
                break
        except Exception as exc:
            logger.warning("translate localize provider failed provider=%s err=%s", candidate_provider.name, exc)

    for lang in body.target_languages:
        if lang not in normalized:
            existing_value = str(existing_translations.get(lang) or "").strip()
            if _is_valid_localized_name(existing_value, lang):
                normalized[lang] = existing_value
            else:
                normalized[lang] = _fallback_localized_name(lang, f"{entity.id}:{lang}")

    existing = dict(existing_translations)
    existing.update(normalized)
    entity.translations_json = existing
    policy_by_lang = dict(entity.naming_policy_by_lang_json or {})
    lock_by_lang = dict(entity.locked_langs_json or {})
    for lang in body.target_languages:
        policy_by_lang[lang] = "cultural_equivalent"
        lock_by_lang[lang] = True
    entity.naming_policy_by_lang_json = policy_by_lang
    entity.locked_langs_json = lock_by_lang
    entity.naming_policy = "cultural_equivalent"
    entity.locked = True
    entity.localization_candidates_json = [
        {"lang": lang, "name": normalized.get(lang), "naming_policy": "cultural_equivalent", "rationale": "auto localized via translate endpoint"}
        for lang in body.target_languages
        if normalized.get(lang)
    ]
    entity.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entity)
    return _entity_to_item(entity)


# ── Delete ─────────────────────────────────────────────────────────────────────

@router.delete("/entity-mapping/{entity_uid}")
def delete_entity_mapping(
    entity_uid: str,
    db: Session = Depends(get_db),
) -> dict:
    entity = _get_entity_or_404(db, entity_uid)
    entity.deleted_at = datetime.now(timezone.utc)
    entity.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"deleted": True, "id": entity_uid}
