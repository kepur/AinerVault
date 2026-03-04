"""name_localization.py — 姓名本地化建议 & 应用 API

文化等价命名（文化映射）：将中文原名（王麻子）映射为目标语言文化等价名（Jonny Miller）。
策略：transliteration（音译）/ literal（字面）/ cultural_equivalent（文化等价）。

Endpoints:
  GET  /api/v1/novels/{novel_id}/name-localization          列出实体+当前命名状态
  POST /api/v1/novels/{novel_id}/name-localization/suggest  LLM 批量建议候选名
  POST /api/v1/novels/{novel_id}/name-localization/apply    应用选定名称并锁定
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import EntityMapping, EntityContinuityStatus
from ainern2d_shared.ainer_db_models.content_models import Novel, SkillRun, SkillRunStatus
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider

from app.api.deps import get_db
from app.api.v1.translation import _call_provider_with_messages, _load_provider_settings
from app.api.v1.entity_mapping import _split_display_and_birth_name

router = APIRouter(prefix="/api/v1", tags=["name-localization"])

ALLOWED_NAMING_POLICIES = {"transliteration", "literal", "cultural_equivalent", "hybrid"}
POLICY_ALIAS = {
    "character_driven": "cultural_equivalent",
    "setting_authentic": "hybrid",
}
FORBIDDEN_PINYIN_PARTS = {
    "wang", "li", "zhang", "chen", "liu", "yang", "zhao", "huang", "wu", "zhou",
    "xu", "sun", "ma", "hu", "guo", "he", "lin", "luo", "gao", "xie",
    "youfu", "mazi", "xiuying", "ergou", "dazhuang", "xiaoming",
}
LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\\-]*")


def _contains_pinyin_transliteration(name: str) -> bool:
    tokens = [t.lower() for t in LATIN_TOKEN_RE.findall(name)]
    return any(token in FORBIDDEN_PINYIN_PARTS for token in tokens)


def _is_valid_localized_name(name: str, target_language: str) -> bool:
    value = str(name or "").strip()
    if not value:
        return False
    if _contains_pinyin_transliteration(value):
        return False
    if target_language.startswith("en"):
        # Full localized EN name should generally include at least first + last.
        if len(LATIN_TOKEN_RE.findall(value)) < 2:
            return False
    return True


def _fallback_localized_name(target_language: str, entity_id: str) -> str:
    if target_language.startswith("ja"):
        pool = ["ハヤト", "タクミ", "リョウ", "ユウタ", "ソラ", "ケン"]
        return pool[hash(entity_id) % len(pool)]
    pool = [
        "Jonny Miller",
        "Ethan Brooks",
        "Liam Carter",
        "Noah Parker",
        "Mason Turner",
        "Caleb Walker",
    ]
    return pool[hash(entity_id) % len(pool)]


# ── Pydantic models ────────────────────────────────────────────────────────────

class NameCandidate(BaseModel):
    name: str
    naming_policy: str
    rationale: str


class NameSuggestion(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str | None
    candidates: list[NameCandidate]
    recommended_name: str | None = None
    rationale: str | None = None


class SuggestNameRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    model_provider_id: str
    entity_uids: list[str] = Field(default_factory=list)   # empty = suggest for all unlocked
    target_language: str = "en-US"
    culture_profile: str | None = None   # e.g. "western_contemporary", "japanese_light_novel"
    era_profile: str | None = None
    social_class: str | None = None
    max_entities: int = Field(default=30, le=100)


class SuggestNameResponse(BaseModel):
    suggestions: list[NameSuggestion]
    run_id: str | None = None
    total: int


class ApplyNameRequest(BaseModel):
    entity_uid: str
    chosen_name: str
    target_language: str = "en-US"
    naming_policy: str = "cultural_equivalent"   # transliteration / literal / cultural_equivalent
    rationale: str | None = None
    lock: bool = True


class NameLocalizationListItem(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str | None
    source_language: str
    naming_policy: str | None
    locked: bool
    rationale: str | None
    translations_json: dict | None
    translations: dict | None
    localization_candidates_json: list | None
    localization_candidates: list | None
    drift_score: float
    locked_langs_json: dict | None
    naming_policy_by_lang_json: dict | None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_novel_or_404(db: Session, novel_id: str) -> Novel:
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")
    return novel


def _normalize_policy(policy: str | None) -> str:
    normalized = str(policy or "cultural_equivalent").strip()
    normalized = POLICY_ALIAS.get(normalized, normalized)
    if normalized not in ALLOWED_NAMING_POLICIES:
        raise HTTPException(status_code=422, detail=f"invalid naming_policy: {normalized}")
    return normalized


# ── GET: list ─────────────────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/name-localization", response_model=list[NameLocalizationListItem])
@router.get("/novels/{novel_id}/name-localize", response_model=list[NameLocalizationListItem])
def list_name_localizations(
    novel_id: str,
    entity_type: str | None = Query(None),
    locked: bool | None = Query(None),
    target_language: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[NameLocalizationListItem]:
    _get_novel_or_404(db, novel_id)

    q = select(EntityMapping).where(
        EntityMapping.novel_id == novel_id,
        EntityMapping.deleted_at.is_(None),
    )
    if entity_type:
        q = q.where(EntityMapping.entity_type == entity_type)
    if locked is not None:
        q = q.where(EntityMapping.locked == locked)

    rows = db.execute(q).scalars().all()

    # If target_language filter provided, only return items with that lang translated or all if locked
    if target_language:
        rows = [
            r for r in rows
            if target_language in (r.translations_json or {})
            or r.locked
        ]

    return [
        NameLocalizationListItem(
            entity_id=r.id,
            canonical_name=r.canonical_name,
            entity_type=r.entity_type.value if r.entity_type else None,
            source_language=r.source_language,
            naming_policy=r.naming_policy,
            locked=r.locked if r.locked is not None else False,
            rationale=r.rationale,
            translations_json=r.translations_json,
            translations=r.translations_json,
            localization_candidates_json=r.localization_candidates_json,
            localization_candidates=r.localization_candidates_json,
            drift_score=float(r.drift_score or 0.0),
            locked_langs_json=r.locked_langs_json,
            naming_policy_by_lang_json=r.naming_policy_by_lang_json,
        )
        for r in rows
    ]


# ── POST: suggest ─────────────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/name-localization/suggest", response_model=SuggestNameResponse)
@router.post("/novels/{novel_id}/name-localize/suggest", response_model=SuggestNameResponse)
def suggest_names(
    novel_id: str,
    body: SuggestNameRequest,
    db: Session = Depends(get_db),
) -> SuggestNameResponse:
    _get_novel_or_404(db, novel_id)

    provider = db.get(ModelProvider, body.model_provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")

    settings = _load_provider_settings(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        provider_id=provider.id,
    )

    # Load entities to suggest for
    if body.entity_uids:
        entities = db.execute(
            select(EntityMapping).where(
                EntityMapping.id.in_(body.entity_uids),
                EntityMapping.novel_id == novel_id,
                EntityMapping.deleted_at.is_(None),
            )
        ).scalars().all()
    else:
        entities = db.execute(
            select(EntityMapping).where(
                EntityMapping.novel_id == novel_id,
                EntityMapping.deleted_at.is_(None),
                EntityMapping.locked.is_(False),
            ).limit(body.max_entities)
        ).scalars().all()

    if not entities:
        return SuggestNameResponse(suggestions=[], run_id=None, total=0)

    entity_list = []
    for e in entities:
        display_name, birth_name = _split_display_and_birth_name(e.canonical_name)
        item = {
            "id": e.id,
            "display_name": display_name,
            "entity_type": e.entity_type.value if e.entity_type else "unknown",
            "aliases": e.aliases_json or [],
        }
        if birth_name:
            item["birth_name_in_source"] = birth_name
        entity_list.append(item)

    culture_hint = f"\n目标文化背景：{body.culture_profile}" if body.culture_profile else ""
    era_hint = f"\n时代画像：{body.era_profile}" if body.era_profile else ""
    class_hint = f"\n社会阶层：{body.social_class}" if body.social_class else ""

    lang_culture_guide = {
        "en-US": "美国英语。根据角色所处地域/时代/阶层给出完全本土化的英文名。乡村背景→Bobby,Earl,Hank,Cletus等；都市精英→Charles,Victoria等；底层混混→Deckard,Rusty等。",
        "en-GB": "英式英语。贵族/中产→Alistair,Rupert,Beatrice；工人阶级→Ron,Dave,Sharon；地方口音→Gordie,Sheila等。",
        "ja-JP": "日语。按角色特征选择：古风→源之介、勘解由；现代→翔太、莉奈；黑道→竜一、鉄哉；学生→拓海、美咲等。",
        "ko-KR": "韩语。按角色背景：财阀→允赫、智贤；普通市民→民俊、秀真；江湖人物→哲洙、龙镇等。",
        "fr-FR": "法语。贵族→Gaspard,Céleste；市民→René,Brigitte；底层→Marcel,Josette等。",
        "de-DE": "德语。根据背景→Hans,Klaus,Bernd；现代→Tim,Lea；精英→Friedrich,Hildegard等。",
        "es-ES": "西班牙语。→Miguel,Carmen,Dolores,Paco,Conchi等。",
    }.get(body.target_language, f"目标语言 {body.target_language}。请根据该语言文化给出完全本土化的地道名字。")

    messages = [
        {
            "role": "system",
            "content": (
                "你是顶级跨文化影视/小说内容本地化（Name Localization）命名顾问。\n"
                "你的核心任务是进行【文化等效命名（Cultural-Equivalent）】，将源语言人物名字、绰号等，转换为符合目标语言母语者直觉的地道名字。\n\n"
                "核心原则：\n"
                "1. 【拼音消除】：绝对禁止使用任何拼音或音译片段（包括姓氏与名字；禁止 Wang/Li/Zhang/Mazi/Youfu 等）。\n"
                "2. 【文化等效（Cultural Equivalent）】：判断原名的社会阶层、年代、地域特征，并在目标文化中找到对应的名字。例如中国乡村混混“王麻子”，在美国乡村背景下，应给出含有类似气质的乡土名（例如 Jonny Miller, Hank Walker 等）。\n"
                "3. 【完整本土化全名】：姓名必须是目标文化的完整本地姓名，不允许保留任何中文拼音姓氏。\n"
                "4. 【忽略原名标注】：若输入包含 `birth_name_in_source`（本名/原名），请以核心称呼（display_name）的气质为准进行本地化命名。\n"
                "5. 每个实体必须提供 3~5 个不同侧重的本地化候选名字。\n"
                "6. 输出必须为纯JSON大括号包裹，不可带Markdown格式。\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"目标语言：{body.target_language}{culture_hint}\n"
                f"{era_hint}{class_hint}\n"
                f"命名参考：{lang_culture_guide}\n\n"
                f"待处理实体列表：\n{json.dumps(entity_list, ensure_ascii=False)}\n\n"
                "输出 JSON 格式要求：\n"
                '{"suggestions":[{"entity_id":"...实体ID...","recommended_name":"最适合的候选名","rationale":"整体选择理由","candidates":'
                '[{"name":"...本土化名字...","naming_policy":"cultural_equivalent","rationale":"为什么这个名字具有对应的等效感？"}]}]}'
            ),
        },
    ]

    # Create SkillRun record
    run = SkillRun(
        id=str(uuid4()).replace("-", ""),
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        skill_id="name_localization_suggest",
        novel_id=novel_id,
        status=SkillRunStatus.running,
        input_snapshot={
            "entity_count": len(entity_list),
            "target_language": body.target_language,
            "culture_profile": body.culture_profile,
            "era_profile": body.era_profile,
            "social_class": body.social_class,
        },
        model_provider_id=provider.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version="v1",
        retry_count=0,
    )
    db.add(run)
    db.flush()

    # LLM call with retry
    last_error = ""
    raw = ""
    parsed: dict[str, Any] = {}
    current_messages = list(messages)

    for attempt in range(2):
        try:
            raw = _call_provider_with_messages(
                provider=provider,
                provider_settings=settings,
                messages=current_messages,
                max_tokens=3000,
            )
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
            m = re.search(r"\{[\s\S]*\}", cleaned)
            if not m:
                raise ValueError("No JSON in LLM output")
            parsed = json.loads(m.group())
            break
        except Exception as exc:
            last_error = str(exc)
            if attempt == 0:
                current_messages = current_messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "请修复 JSON 格式后重新输出，确保每个实体都有3个candidates，naming_policy只能是 transliteration / literal / cultural_equivalent / hybrid 之一，名字不能含任何中文拼音。"},
                ]

    if not parsed:
        run.status = SkillRunStatus.failed
        run.error_message = last_error[:512]
        run.updated_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=500, detail=f"name localization LLM failed: {last_error}")

    run.status = SkillRunStatus.succeeded
    run.output_json = parsed
    run.raw_response = raw[:4000] if raw else None
    run.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Build entity_id → canonical_name lookup
    entity_map = {e.id: e for e in entities}

    suggestions = []
    for sug in parsed.get("suggestions", []):
        eid = sug.get("entity_id", "")
        entity = entity_map.get(eid)
        if entity is None:
            continue
        candidates: list[NameCandidate] = []
        for c in sug.get("candidates", []):
            raw_name = str(c.get("name", "")).strip()
            if not raw_name:
                continue
            if not _is_valid_localized_name(raw_name, body.target_language):
                continue
            candidates.append(
                NameCandidate(
                    name=raw_name,
                    naming_policy=_normalize_policy(c.get("naming_policy", "cultural_equivalent")),
                    rationale=c.get("rationale", ""),
                )
            )
        if not candidates:
            candidates = [
                NameCandidate(
                    name=_fallback_localized_name(body.target_language, entity.id),
                    naming_policy="cultural_equivalent",
                    rationale="fallback: strict localization validator auto-selected",
                )
            ]
        recommended_name = str(sug.get("recommended_name") or "").strip()
        if not _is_valid_localized_name(recommended_name, body.target_language):
            recommended_name = ""
        if not recommended_name and candidates:
            recommended_name = candidates[0].name
        rationale = str(sug.get("rationale") or "").strip()
        if not rationale and candidates:
            rationale = candidates[0].rationale
        entity.localization_candidates_json = [c.model_dump() for c in candidates]
        entity.drift_score = 0.0
        entity.updated_by_ai = True
        entity.updated_at = datetime.now(timezone.utc)
        suggestions.append(NameSuggestion(
            entity_id=eid,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type.value if entity.entity_type else None,
            candidates=candidates,
            recommended_name=recommended_name or None,
            rationale=rationale or None,
        ))
    db.commit()

    return SuggestNameResponse(
        suggestions=suggestions,
        run_id=run.id,
        total=len(suggestions),
    )


# ── POST: apply ───────────────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/name-localization/apply")
@router.post("/novels/{novel_id}/name-localize/apply")
def apply_name(
    novel_id: str,
    body: ApplyNameRequest,
    db: Session = Depends(get_db),
) -> dict:
    _get_novel_or_404(db, novel_id)

    entity = db.get(EntityMapping, body.entity_uid)
    if entity is None or entity.deleted_at is not None:
        raise HTTPException(status_code=404, detail="entity mapping not found")
    if entity.novel_id != novel_id:
        raise HTTPException(status_code=400, detail="entity does not belong to this novel")

    # Update translations
    existing = dict(entity.translations_json or {})
    existing[body.target_language] = body.chosen_name
    entity.translations_json = existing

    # Apply naming metadata
    entity.naming_policy = _normalize_policy(body.naming_policy)
    policy_by_lang = dict(entity.naming_policy_by_lang_json or {})
    policy_by_lang[body.target_language] = entity.naming_policy
    entity.naming_policy_by_lang_json = policy_by_lang
    if body.rationale is not None:
        entity.rationale = body.rationale
    candidates = list(entity.localization_candidates_json or [])
    if body.chosen_name and body.chosen_name not in [str(c.get("name")) for c in candidates if isinstance(c, dict)]:
        candidates.append(
            {
                "name": body.chosen_name,
                "naming_policy": entity.naming_policy,
                "rationale": body.rationale or "",
            }
        )
    entity.localization_candidates_json = candidates
    entity.drift_score = 0.0

    if body.lock:
        entity.locked = True
        entity.continuity_status = EntityContinuityStatus.locked
    lock_by_lang = dict(entity.locked_langs_json or {})
    lock_by_lang[body.target_language] = bool(body.lock)
    entity.locked_langs_json = lock_by_lang

    entity.updated_by_ai = False   # applied by human choice
    entity.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(entity)

    return {
        "entity_id": entity.id,
        "canonical_name": entity.canonical_name,
        "target_language": body.target_language,
        "chosen_name": body.chosen_name,
        "naming_policy": entity.naming_policy,
        "locked": entity.locked,
        "translations_json": entity.translations_json,
        "translations": entity.translations_json,
        "localization_candidates_json": entity.localization_candidates_json,
        "localization_candidates": entity.localization_candidates_json,
        "drift_score": float(entity.drift_score or 0.0),
        "locked_langs_json": entity.locked_langs_json,
        "naming_policy_by_lang_json": entity.naming_policy_by_lang_json,
    }
