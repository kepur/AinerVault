"""script_workflow.py — 剧本转换 + 世界模型抽离 API（缓存优先版本）

缓存策略：
  - 每次 LLM 调用创建 SkillRun 记录
  - input_hash = SHA256(text[:8000] + JSON(params))
  - /generate: 若相同 input_hash 且 status=succeeded → 直接返回缓存
  - /regenerate: 强制创建新 Run，版本号 +1

Endpoints:
  POST /api/v1/chapters/{chapter_id}/format-detect
  GET  /api/v1/chapters/{chapter_id}/script
  POST /api/v1/chapters/{chapter_id}/script/generate      ← 缓存优先
  POST /api/v1/chapters/{chapter_id}/script/regenerate    ← 强制重生成
  GET  /api/v1/chapters/{chapter_id}/world-model
  POST /api/v1/chapters/{chapter_id}/world-model/generate    ← 缓存优先
  POST /api/v1/chapters/{chapter_id}/world-model/regenerate  ← 强制重生成
  GET  /api/v1/skill-runs (list)
  GET  /api/v1/skill-runs/{run_id}
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Chapter, SkillRun, SkillRunStatus
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider

from app.api.deps import get_db
from app.api.v1.translation import _call_provider_with_messages, _load_provider_settings

router = APIRouter(prefix="/api/v1", tags=["script-workflow"])


# ─── Regex signal for script detection ────────────────────────────────────────
_SCRIPT_SIGNALS = re.compile(
    r"【场景|时间[\s：:]|地点[\s：:]|INT\.|EXT\.|第.{1,4}场|幕后|旁白："
)


# ── Pydantic models ────────────────────────────────────────────────────────────

class FormatDetectRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    model_provider_id: str | None = None
    force: bool = False


class FormatDetectResponse(BaseModel):
    chapter_id: str
    format: str
    confidence: float
    signals: list[str]
    method: str
    cached: bool = False


class ScriptGenerateRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    model_provider_id: str
    granularity: str = "normal"
    style_hint: str | None = None
    force: bool = False   # if True → always call LLM (regenerate path)


class ScriptResponse(BaseModel):
    chapter_id: str
    scenes: list[dict]
    summary: str
    warnings: list[str]
    version: int = 0
    run_id: str | None = None
    cached: bool = False
    script_updated_at: str | None = None


class WorldModelGenerateRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    model_provider_id: str
    level: str = "rich"
    force: bool = False


class WorldModelResponse(BaseModel):
    chapter_id: str
    characters: list[dict]
    locations: list[dict]
    props: list[dict]
    beats: list[dict]
    style_hints: list[dict]
    version: int = 0
    run_id: str | None = None
    cached: bool = False
    world_model_updated_at: str | None = None


class SkillRunItem(BaseModel):
    id: str
    skill_id: str
    chapter_id: str | None
    novel_id: str | None
    status: str
    input_hash: str | None
    model_provider_id: str | None
    model_name: str | None
    token_usage: dict | None
    cost_estimate: float | None
    created_at: str | None
    updated_at: str | None
    cached: bool = False


class LatestWorldRunResponse(BaseModel):
    run: SkillRunItem | None


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _compute_input_hash(text: str, params: dict) -> str:
    """SHA256(full_text + sorted_params_json) → first 32 hex chars."""
    payload = text + json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _find_cached_run(
    db: Session,
    *,
    skill_id: str,
    input_hash: str,
    chapter_id: str | None = None,
) -> SkillRun | None:
    q = (
        select(SkillRun)
        .where(
            SkillRun.skill_id == skill_id,
            SkillRun.input_hash == input_hash,
            SkillRun.status == SkillRunStatus.succeeded,
            SkillRun.deleted_at.is_(None),
        )
        .order_by(SkillRun.created_at.desc())
        .limit(1)
    )
    if chapter_id:
        q = q.where(SkillRun.chapter_id == chapter_id)
    return db.execute(q).scalars().first()


def _create_skill_run(
    db: Session,
    *,
    skill_id: str,
    tenant_id: str,
    project_id: str,
    chapter_id: str | None = None,
    novel_id: str | None = None,
    input_hash: str,
    input_snapshot: dict | None = None,
    model_provider_id: str | None = None,
    model_name: str | None = None,
) -> SkillRun:
    run = SkillRun(
        id=str(uuid4()).replace("-", ""),
        tenant_id=tenant_id,
        project_id=project_id,
        skill_id=skill_id,
        chapter_id=chapter_id,
        novel_id=novel_id,
        input_hash=input_hash,
        input_snapshot=input_snapshot,
        status=SkillRunStatus.running,
        model_provider_id=model_provider_id,
        model_name=model_name,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version="v1",
        retry_count=0,
    )
    db.add(run)
    db.flush()
    return run


def _finish_run(
    db: Session,
    run: SkillRun,
    *,
    output_json: dict,
    raw_response: str = "",
    token_usage: dict | None = None,
) -> None:
    run.status = SkillRunStatus.succeeded
    run.output_json = output_json
    run.raw_response = raw_response[:4000] if raw_response else None
    run.token_usage = token_usage
    run.updated_at = datetime.now(timezone.utc)


def _fail_run(db: Session, run: SkillRun, error: str) -> None:
    run.status = SkillRunStatus.failed
    run.error_message = error[:512]
    run.updated_at = datetime.now(timezone.utc)


# ── Other helpers ──────────────────────────────────────────────────────────────

def _get_chapter_or_404(db: Session, chapter_id: str) -> Chapter:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None or chapter.deleted_at is not None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return chapter


def _get_provider_or_404(db: Session, provider_id: str) -> ModelProvider:
    provider = db.get(ModelProvider, provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")
    return provider


def _extract_model_name(settings: dict) -> str:
    model_catalog = list(settings.get("model_catalog") or [])
    return model_catalog[0] if model_catalog else "unknown"


def _parse_json_with_retry(
    *,
    provider: ModelProvider,
    provider_settings: dict,
    messages: list[dict],
    max_tokens: int,
    retry_suffix: str,
    validate_fn=None,
) -> tuple[dict, str]:
    """Call LLM, parse JSON; retry once on failure. Returns (parsed, raw_response)."""
    last_error = ""
    raw = ""
    current_messages = list(messages)

    for attempt in range(2):
        raw = _call_provider_with_messages(
            provider=provider,
            provider_settings=provider_settings,
            messages=current_messages,
            max_tokens=max_tokens,
        )
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
        try:
            m = re.search(r"\{[\s\S]*\}", cleaned)
            if not m:
                raise ValueError("No JSON object in LLM output")
            parsed = json.loads(m.group())
            if not isinstance(parsed, dict):
                raise ValueError("LLM returned non-dict JSON")
            if validate_fn:
                validate_fn(parsed)
            return parsed, raw
        except Exception as exc:
            last_error = str(exc)
            if attempt == 0:
                current_messages = current_messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": retry_suffix},
                ]

    raise HTTPException(
        status_code=500,
        detail=f"LLM JSON parse failed after retry: {last_error}",
    )


# ── Format Detect ──────────────────────────────────────────────────────────────

@router.post("/chapters/{chapter_id}/format-detect", response_model=FormatDetectResponse)
def format_detect(
    chapter_id: str,
    body: FormatDetectRequest,
    db: Session = Depends(get_db),
) -> FormatDetectResponse:
    chapter = _get_chapter_or_404(db, chapter_id)
    text = chapter.cleaned_text or chapter.raw_text or ""

    # Return cached format_detect_json if not forcing
    if not body.force and chapter.format_detect_json:
        fd = chapter.format_detect_json
        return FormatDetectResponse(
            chapter_id=chapter_id,
            format=fd.get("format", "unknown"),
            confidence=float(fd.get("confidence", 0.5)),
            signals=fd.get("signals", []),
            method=fd.get("method", "cached"),
            cached=True,
        )

    preview = text[:2000]

    if body.model_provider_id:
        try:
            provider = _get_provider_or_404(db, body.model_provider_id)
            settings = _load_provider_settings(
                db, tenant_id=body.tenant_id, project_id=body.project_id, provider_id=provider.id,
            )
            messages = [
                {"role": "system", "content": "你是文本格式分析专家。判断给定文本是叙述体小说（novel）、剧本体（script）还是无法判断（unknown）。输出 JSON，不含 Markdown 标记。"},
                {"role": "user", "content": (
                    f"请分析以下文本（前2000字）的格式，输出：\n"
                    f'{{\"format\":\"novel|script|unknown\",\"confidence\":0.0-1.0,\"signals\":[\"找到的格式信号\"]}}\n\n文本：{preview}'
                )},
            ]
            parsed, _ = _parse_json_with_retry(
                provider=provider, provider_settings=settings, messages=messages,
                max_tokens=512, retry_suffix="请修复 JSON 格式后重新输出。",
            )
            result = {"format": str(parsed.get("format", "unknown")), "confidence": float(parsed.get("confidence", 0.5)), "signals": list(parsed.get("signals", [])), "method": "llm"}
        except HTTPException:
            raise
        except Exception:
            signal_matches = _SCRIPT_SIGNALS.findall(preview)
            confidence = min(len(signal_matches) / 5.0, 1.0)
            result = {"format": "script" if confidence >= 0.4 else "novel", "confidence": confidence, "signals": signal_matches, "method": "regex_fallback"}
    else:
        signal_matches = _SCRIPT_SIGNALS.findall(preview)
        confidence = min(len(signal_matches) / 5.0, 1.0)
        result = {"format": "script" if confidence >= 0.4 else "novel", "confidence": confidence, "signals": signal_matches, "method": "regex_fallback"}

    # Persist
    chapter.format_detect_json = result
    chapter.updated_at = datetime.now(timezone.utc)
    db.commit()

    return FormatDetectResponse(chapter_id=chapter_id, **result, cached=False)


# ── Script: GET ────────────────────────────────────────────────────────────────

@router.get("/chapters/{chapter_id}/script", response_model=ScriptResponse)
def get_script(chapter_id: str, db: Session = Depends(get_db)) -> ScriptResponse:
    chapter = _get_chapter_or_404(db, chapter_id)
    data = chapter.script_json or {}
    return ScriptResponse(
        chapter_id=chapter_id,
        scenes=data.get("scenes", []),
        summary=data.get("summary", ""),
        warnings=data.get("warnings", []),
        version=chapter.script_version or 0,
        run_id=chapter.script_run_id,
        cached=True,
        script_updated_at=chapter.script_updated_at.isoformat() if chapter.script_updated_at else None,
    )


# ── Script: Generate (cache-first) ────────────────────────────────────────────

@router.post("/chapters/{chapter_id}/script/generate", response_model=ScriptResponse)
def generate_script(
    chapter_id: str,
    body: ScriptGenerateRequest,
    db: Session = Depends(get_db),
) -> ScriptResponse:
    chapter = _get_chapter_or_404(db, chapter_id)
    text = chapter.cleaned_text or chapter.raw_text or ""

    input_hash = _compute_input_hash(
        text,
        {"granularity": body.granularity, "style_hint": body.style_hint, "provider": body.model_provider_id},
    )

    # Cache lookup (unless force=True)
    if not body.force:
        cached_run = _find_cached_run(db, skill_id="novel_to_script", input_hash=input_hash, chapter_id=chapter_id)
        if cached_run and cached_run.output_json:
            out = cached_run.output_json
            return ScriptResponse(
                chapter_id=chapter_id,
                scenes=out.get("scenes", []),
                summary=out.get("summary", ""),
                warnings=out.get("warnings", []),
                version=chapter.script_version or 0,
                run_id=cached_run.id,
                cached=True,
                script_updated_at=chapter.script_updated_at.isoformat() if chapter.script_updated_at else None,
            )

    # Also return DB value if exists and no force
    if not body.force and chapter.script_json:
        data = chapter.script_json
        return ScriptResponse(
            chapter_id=chapter_id,
            scenes=data.get("scenes", []),
            summary=data.get("summary", ""),
            warnings=data.get("warnings", []),
            version=chapter.script_version or 0,
            run_id=chapter.script_run_id,
            cached=True,
            script_updated_at=chapter.script_updated_at.isoformat() if chapter.script_updated_at else None,
        )

    return _do_script_generation(db, chapter, body, input_hash, is_regenerate=False)


# ── Script: Regenerate (force) ────────────────────────────────────────────────

@router.post("/chapters/{chapter_id}/script/regenerate", response_model=ScriptResponse)
def regenerate_script(
    chapter_id: str,
    body: ScriptGenerateRequest,
    db: Session = Depends(get_db),
) -> ScriptResponse:
    chapter = _get_chapter_or_404(db, chapter_id)
    text = chapter.cleaned_text or chapter.raw_text or ""
    input_hash = _compute_input_hash(
        text,
        {"granularity": body.granularity, "style_hint": body.style_hint, "provider": body.model_provider_id},
    )
    return _do_script_generation(db, chapter, body, input_hash, is_regenerate=True)


def _do_script_generation(
    db: Session,
    chapter: Chapter,
    body: ScriptGenerateRequest,
    input_hash: str,
    is_regenerate: bool,
) -> ScriptResponse:
    provider = _get_provider_or_404(db, body.model_provider_id)
    settings = _load_provider_settings(
        db, tenant_id=body.tenant_id, project_id=body.project_id, provider_id=provider.id,
    )
    model_name = _extract_model_name(settings)
    text = chapter.cleaned_text or chapter.raw_text or ""
    granularity_desc = {"coarse": "粗", "normal": "普通", "fine": "细"}.get(body.granularity, "普通")

    run = _create_skill_run(
        db,
        skill_id="novel_to_script",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        chapter_id=chapter.id,
        novel_id=chapter.novel_id,
        input_hash=input_hash,
        input_snapshot={"text_preview": text[:300], "granularity": body.granularity, "style_hint": body.style_hint},
        model_provider_id=provider.id,
        model_name=model_name,
    )

    messages = [
        {"role": "system", "content": "你是专业剧本改编者。将小说叙述体改写为结构化场景，输出 JSON，不要 Markdown 代码块。"},
        {"role": "user", "content": (
            f"原文（{len(text)}字）：{text[:8000]}\n"
            f"粒度：{body.granularity}（{granularity_desc}）  风格：{body.style_hint or '通用'}\n\n"
            '必须输出：{"scenes":[{"scene_id":"s001","title":"","time":"","location":"","weather":"",'
            '"mood":"","narration":"","dialogue_blocks":[{"speaker":"","line":""}],"actions":[]}],'
            '"summary":"","warnings":[]}'
        )},
    ]

    try:
        parsed, raw = _parse_json_with_retry(
            provider=provider, provider_settings=settings, messages=messages,
            max_tokens=4000, retry_suffix="请修复 JSON 格式后重新输出。",
        )
    except HTTPException as exc:
        _fail_run(db, run, str(exc.detail))
        db.commit()
        raise

    _finish_run(db, run, output_json=parsed, raw_response=raw)

    now = datetime.now(timezone.utc)
    new_version = (chapter.script_version or 0) + (1 if is_regenerate else 0)
    if not chapter.script_json:
        new_version = 1

    chapter.script_json = parsed
    chapter.script_version = new_version
    chapter.script_run_id = run.id
    chapter.script_updated_at = now
    chapter.updated_at = now
    db.commit()

    return ScriptResponse(
        chapter_id=chapter.id,
        scenes=parsed.get("scenes", []),
        summary=parsed.get("summary", ""),
        warnings=parsed.get("warnings", []),
        version=new_version,
        run_id=run.id,
        cached=False,
        script_updated_at=now.isoformat(),
    )


# ── World Model: GET ───────────────────────────────────────────────────────────

@router.get("/chapters/{chapter_id}/world-model", response_model=WorldModelResponse)
def get_world_model(chapter_id: str, db: Session = Depends(get_db)) -> WorldModelResponse:
    chapter = _get_chapter_or_404(db, chapter_id)
    data = chapter.world_model_json or {}
    return WorldModelResponse(
        chapter_id=chapter_id,
        characters=data.get("characters", []),
        locations=data.get("locations", []),
        props=data.get("props", []),
        beats=data.get("beats", []),
        style_hints=data.get("style_hints", []),
        version=chapter.world_model_version or 0,
        run_id=chapter.world_model_run_id,
        cached=True,
        world_model_updated_at=chapter.world_model_updated_at.isoformat() if chapter.world_model_updated_at else None,
    )


@router.get("/chapters/{chapter_id}/world-runs/latest", response_model=LatestWorldRunResponse)
def get_latest_world_run(
    chapter_id: str,
    tenant_id: str = Query("default"),
    project_id: str = Query("default"),
    db: Session = Depends(get_db),
) -> LatestWorldRunResponse:
    _get_chapter_or_404(db, chapter_id)
    run = db.execute(
        select(SkillRun)
        .where(
            SkillRun.tenant_id == tenant_id,
            SkillRun.project_id == project_id,
            SkillRun.skill_id == "world_model_extract",
            SkillRun.chapter_id == chapter_id,
            SkillRun.deleted_at.is_(None),
        )
        .order_by(SkillRun.created_at.desc())
        .limit(1)
    ).scalars().first()
    return LatestWorldRunResponse(run=_run_to_item(run) if run else None)


# ── World Model: Generate (cache-first) ───────────────────────────────────────

@router.post("/chapters/{chapter_id}/world-model/generate", response_model=WorldModelResponse)
def generate_world_model(
    chapter_id: str,
    body: WorldModelGenerateRequest,
    db: Session = Depends(get_db),
) -> WorldModelResponse:
    chapter = _get_chapter_or_404(db, chapter_id)

    script_data = chapter.script_json or {}
    scenes = script_data.get("scenes", [])
    cache_text = json.dumps(scenes[:20], ensure_ascii=False) if scenes else (chapter.cleaned_text or chapter.raw_text or "")
    input_hash = _compute_input_hash(cache_text, {"level": body.level, "provider": body.model_provider_id})

    if not body.force:
        cached_run = _find_cached_run(db, skill_id="world_model_extract", input_hash=input_hash, chapter_id=chapter_id)
        if cached_run and cached_run.output_json:
            out = cached_run.output_json
            return WorldModelResponse(
                chapter_id=chapter_id,
                characters=out.get("characters", []),
                locations=out.get("locations", []),
                props=out.get("props", []),
                beats=out.get("beats", []),
                style_hints=out.get("style_hints", []),
                version=chapter.world_model_version or 0,
                run_id=cached_run.id,
                cached=True,
                world_model_updated_at=chapter.world_model_updated_at.isoformat() if chapter.world_model_updated_at else None,
            )

        if chapter.world_model_json:
            data = chapter.world_model_json
            return WorldModelResponse(
                chapter_id=chapter_id,
                characters=data.get("characters", []),
                locations=data.get("locations", []),
                props=data.get("props", []),
                beats=data.get("beats", []),
                style_hints=data.get("style_hints", []),
                version=chapter.world_model_version or 0,
                run_id=chapter.world_model_run_id,
                cached=True,
                world_model_updated_at=chapter.world_model_updated_at.isoformat() if chapter.world_model_updated_at else None,
            )

    return _do_world_model_extraction(db, chapter, body, input_hash, is_regenerate=False)


# ── World Model: Regenerate (force) ───────────────────────────────────────────

@router.post("/chapters/{chapter_id}/world-model/regenerate", response_model=WorldModelResponse)
def regenerate_world_model(
    chapter_id: str,
    body: WorldModelGenerateRequest,
    db: Session = Depends(get_db),
) -> WorldModelResponse:
    chapter = _get_chapter_or_404(db, chapter_id)
    script_data = chapter.script_json or {}
    scenes = script_data.get("scenes", [])
    cache_text = json.dumps(scenes[:20], ensure_ascii=False) if scenes else (chapter.cleaned_text or chapter.raw_text or "")
    input_hash = _compute_input_hash(cache_text, {"level": body.level, "provider": body.model_provider_id})
    return _do_world_model_extraction(db, chapter, body, input_hash, is_regenerate=True)


def _validate_world_model(parsed: dict) -> None:
    for key in ("characters", "locations", "props", "beats", "style_hints"):
        for item in parsed.get(key, []):
            if not item.get("evidence"):
                raise ValueError(f"Missing evidence in {key}: {item.get('name', '?')}")


def _do_world_model_extraction(
    db: Session,
    chapter: Chapter,
    body: WorldModelGenerateRequest,
    input_hash: str,
    is_regenerate: bool,
) -> WorldModelResponse:
    provider = _get_provider_or_404(db, body.model_provider_id)
    settings = _load_provider_settings(
        db, tenant_id=body.tenant_id, project_id=body.project_id, provider_id=provider.id,
    )
    model_name = _extract_model_name(settings)

    script_data = chapter.script_json or {}
    scenes = script_data.get("scenes", [])
    scene_payload = json.dumps(scenes[:20], ensure_ascii=False)[:6000] if scenes else (chapter.cleaned_text or chapter.raw_text or "")[:6000]

    run = _create_skill_run(
        db,
        skill_id="world_model_extract",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        chapter_id=chapter.id,
        novel_id=chapter.novel_id,
        input_hash=input_hash,
        input_snapshot={"level": body.level, "has_script": bool(scenes)},
        model_provider_id=provider.id,
        model_name=model_name,
    )

    messages = [
        {"role": "system", "content": "你是世界观分析师。从场景中深度抽离人物/地点/道具/节拍/风格，每项必须包含 evidence（原文引用）。输出 JSON，不含 Markdown 标记。"},
        {"role": "user", "content": (
            f"scenes/text: {scene_payload}\n"
            f"提取级别: {body.level}（basic=基础/rich=丰富/cinematic=电影级）\n\n"
            '输出 JSON（每类每项的 evidence 不得为空）：\n'
            '{"characters":[{"name":"","aliases":[],"appearance":"","signature_features":"",'
            '"voice_hints":"","props_on_body":[],"evidence":["原文片段"]}],'
            '"locations":[{"name":"","type":"","visual_keywords":[],"ambience":[],"mood":"","evidence":[""]}],'
            '"props":[{"name":"","type":"","material_condition":"","owner":"","usage":"","evidence":[""]}],'
            '"beats":[{"title":"","participants":[],"location":"","time":"","tension_level":0,"evidence":[""]}],'
            '"style_hints":[{"lighting_style":"","camera_language":"","pacing":"","genre_tags":[],"evidence":[""]}]}'
        )},
    ]

    try:
        parsed, raw = _parse_json_with_retry(
            provider=provider, provider_settings=settings, messages=messages,
            max_tokens=4000, retry_suffix="请为每个实体补充 evidence 原文引用。",
            validate_fn=_validate_world_model,
        )
    except HTTPException as exc:
        _fail_run(db, run, str(exc.detail))
        db.commit()
        raise

    _finish_run(db, run, output_json=parsed, raw_response=raw)

    now = datetime.now(timezone.utc)
    new_version = (chapter.world_model_version or 0) + (1 if is_regenerate else 0)
    if not chapter.world_model_json:
        new_version = 1

    chapter.world_model_json = parsed
    chapter.world_model_version = new_version
    chapter.world_model_run_id = run.id
    chapter.world_model_updated_at = now
    chapter.updated_at = now
    db.commit()

    return WorldModelResponse(
        chapter_id=chapter.id,
        characters=parsed.get("characters", []),
        locations=parsed.get("locations", []),
        props=parsed.get("props", []),
        beats=parsed.get("beats", []),
        style_hints=parsed.get("style_hints", []),
        version=new_version,
        run_id=run.id,
        cached=False,
        world_model_updated_at=now.isoformat(),
    )


# ── SkillRun: List ─────────────────────────────────────────────────────────────

@router.get("/skill-runs", response_model=list[SkillRunItem])
def list_skill_runs(
    tenant_id: str = Query("default"),
    project_id: str = Query("default"),
    skill_id: str | None = Query(None),
    chapter_id: str | None = Query(None),
    novel_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
) -> list[SkillRunItem]:
    q = (
        select(SkillRun)
        .where(
            SkillRun.tenant_id == tenant_id,
            SkillRun.project_id == project_id,
            SkillRun.deleted_at.is_(None),
        )
        .order_by(SkillRun.created_at.desc())
        .limit(limit)
    )
    if skill_id:
        q = q.where(SkillRun.skill_id == skill_id)
    if chapter_id:
        q = q.where(SkillRun.chapter_id == chapter_id)
    if novel_id:
        q = q.where(SkillRun.novel_id == novel_id)
    if status:
        q = q.where(SkillRun.status == status)

    rows = db.execute(q).scalars().all()
    return [_run_to_item(r) for r in rows]


@router.get("/skill-runs/{run_id}", response_model=SkillRunItem)
def get_skill_run(run_id: str, db: Session = Depends(get_db)) -> SkillRunItem:
    run = db.get(SkillRun, run_id)
    if run is None or run.deleted_at is not None:
        raise HTTPException(status_code=404, detail="skill run not found")
    return _run_to_item(run)


def _run_to_item(r: SkillRun) -> SkillRunItem:
    return SkillRunItem(
        id=r.id,
        skill_id=r.skill_id,
        chapter_id=r.chapter_id,
        novel_id=r.novel_id,
        status=r.status.value if r.status else "unknown",
        input_hash=r.input_hash,
        model_provider_id=r.model_provider_id,
        model_name=r.model_name,
        token_usage=r.token_usage,
        cost_estimate=r.cost_estimate,
        created_at=r.created_at.isoformat() if r.created_at else None,
        updated_at=r.updated_at.isoformat() if r.updated_at else None,
    )
