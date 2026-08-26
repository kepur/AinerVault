from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import requests
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel
from ainern2d_shared.ainer_db_models.enum_models import EntityType, RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.knowledge_models import Entity, EntityAlias, EntityPromptVariant, StoryEvent
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun, WorkflowEvent
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider
from ainern2d_shared.schemas.skills.skill_01 import Skill01Input
from ainern2d_shared.schemas.skills.skill_02 import Skill02Input
from ainern2d_shared.schemas.skills.skill_03 import Skill03Input
from ainern2d_shared.services.base_skill import SkillContext

from app.api.deps import get_db
from app.api.v1.tasks import TaskSubmitAccepted, TaskSubmitRequest, create_task
from app.services.skill_registry import SkillRegistry
from app.services.telegram_notify import notify_telegram_event

router = APIRouter(prefix="/api/v1", tags=["novels"])


class NovelCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    title: str
    summary: str | None = None
    default_language_code: str = "zh"


class NovelUpdateRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    title: str | None = None
    summary: str | None = None
    default_language_code: str | None = None


class NovelTeamMember(BaseModel):
    persona_pack_id: str
    persona_pack_name: str = ""


class NovelTeamRequest(BaseModel):
    tenant_id: str = "default"
    project_id: str = "default"
    team: dict[str, NovelTeamMember]


class NovelTeamResponse(BaseModel):
    novel_id: str
    team: dict[str, NovelTeamMember]


class NovelResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    title: str
    summary: str | None = None
    default_language_code: str
    team_json: dict | None = None


class ChapterCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    chapter_no: int
    language_code: str = "zh"
    title: str | None = None
    markdown_text: str


class ChapterUpdateRequest(BaseModel):
    title: str | None = None
    language_code: str | None = None
    markdown_text: str
    revision_note: str | None = None


class ChapterResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    novel_id: str
    chapter_no: int
    language_code: str
    title: str | None = None
    markdown_text: str


class ChapterRevisionItem(BaseModel):
    revision_id: str
    occurred_at: datetime
    chapter_id: str
    note: str | None = None
    editor: str | None = None
    previous_markdown_text: str


class ChapterPreviewRequest(BaseModel):
    tenant_id: str
    project_id: str
    target_output_language: str | None = None
    target_locale: str | None = None
    genre: str = ""
    story_world_setting: str = ""
    culture_pack_id: str | None = None
    persona_ref: str | None = None


class ChapterPreviewResponse(BaseModel):
    preview_run_id: str
    skill_01_status: str
    skill_02_status: str
    skill_03_status: str
    normalized_text: str
    culture_candidates: list[str] = Field(default_factory=list)
    scene_count: int = 0
    shot_count: int = 0
    scene_plan: list[dict] = Field(default_factory=list)
    shot_plan: list[dict] = Field(default_factory=list)


class ChapterTaskRequest(BaseModel):
    tenant_id: str
    project_id: str
    requested_quality: str = "standard"
    language_context: str = "zh-CN"
    payload: dict = Field(default_factory=dict)
    trace_id: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None


class ChapterAssistExpandRequest(BaseModel):
    tenant_id: str
    project_id: str
    model_provider_id: str  # 用户选择的模型provider ID
    instruction: str = "扩展剧情，增强冲突、节奏与情绪转折，保持人物一致性。"
    style_hint: str = "影视化叙事，保留可分镜细节。"
    target_language: str | None = None
    max_tokens: int = Field(default=900, ge=200, le=2500)


class ModelProviderResponse(BaseModel):
    id: str
    name: str
    endpoint: str | None = None
    auth_mode: str | None = None


class ChapterAssistExpandResponse(BaseModel):
    chapter_id: str
    original_length: int
    expanded_length: int
    expanded_markdown: str
    appended_excerpt: str
    provider_used: str
    model_name: str
    mode: str
    prompt_tokens_estimate: int
    completion_tokens_estimate: int


class ChapterPublishStatus(BaseModel):
    """章节发布审批状态"""
    chapter_id: str
    status: str  # draft / pending / approved / released
    submitted_by: str | None = None
    submitted_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None


class ChapterDiffResponse(BaseModel):
    """章节版本 diff"""
    chapter_id: str
    from_version: str
    to_version: str
    from_text: str
    to_text: str
    diff_lines: list[dict]  # [{type: "add/remove/unchanged", content: "...", line_no: int}]
    additions: int
    deletions: int


class ChapterPublishApprovalRequest(BaseModel):
    """章节发布审批请求"""
    tenant_id: str
    action: str  # submit / approve / reject
    rejection_reason: str | None = None


class ChapterDiffRequest(BaseModel):
    """章节 diff 请求"""
    from_version: str = "latest"  # "latest" 或指定版本 ID
    to_version: str = "current"  # "current" 或指定版本 ID


@router.post("/novels", response_model=NovelResponse, status_code=201)
def create_novel(body: NovelCreateRequest, db: Session = Depends(get_db)) -> NovelResponse:
    novel = Novel(
        id=f"novel_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=f"tr_novel_{uuid4().hex[:12]}",
        correlation_id=f"cr_novel_{uuid4().hex[:12]}",
        idempotency_key=f"idem_novel_{body.project_id}_{uuid4().hex[:8]}",
        title=body.title,
        summary=body.summary,
        default_language_code=body.default_language_code,
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return _novel_to_response(novel)


def _novel_to_response(row: Novel) -> NovelResponse:
    return NovelResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        title=row.title,
        summary=row.summary,
        default_language_code=row.default_language_code,
        team_json=row.team_json,
    )


@router.get("/novels", response_model=list[NovelResponse])
def list_novels(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[NovelResponse]:
    rows = db.execute(
        select(Novel)
        .where(
            Novel.tenant_id == tenant_id,
            Novel.project_id == project_id,
            Novel.deleted_at.is_(None),
        )
        .order_by(Novel.created_at.desc())
    ).scalars().all()
    return [_novel_to_response(row) for row in rows]


@router.get("/novels/{novel_id}", response_model=NovelResponse)
def get_novel(novel_id: str, db: Session = Depends(get_db)) -> NovelResponse:
    row = db.get(Novel, novel_id)
    if row is None:
        raise HTTPException(status_code=404, detail="novel not found")
    return _novel_to_response(row)


@router.put("/novels/{novel_id}", response_model=NovelResponse)
def update_novel(
    novel_id: str,
    body: NovelUpdateRequest,
    db: Session = Depends(get_db),
) -> NovelResponse:
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")
    if body.title is not None:
        novel.title = body.title
    if body.summary is not None:
        novel.summary = body.summary
    if body.default_language_code is not None:
        novel.default_language_code = body.default_language_code
    db.commit()
    db.refresh(novel)
    return _novel_to_response(novel)


@router.delete("/novels/{novel_id}")
def delete_novel(
    novel_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    force: bool = Query(False, description="Force delete: cancel active runs first"),
    db: Session = Depends(get_db),
) -> dict:
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")
    # Check no active runs reference chapters of this novel
    active_runs = db.execute(
        select(RenderRun)
        .join(Chapter, RenderRun.chapter_id == Chapter.id)
        .where(
            Chapter.novel_id == novel_id,
            Chapter.deleted_at.is_(None),
            RenderRun.status.in_([RunStatus.queued, RunStatus.running]),
        )
    ).scalars().all()
    if active_runs:
        if not force:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "REQ-IDEMPOTENCY-001",
                    "message": "novel has active runs, cannot delete",
                    "active_run_count": len(active_runs),
                    "hint": "use force=true to cancel active runs and delete",
                },
            )
        # Force mode: cancel all active runs
        now = datetime.now(timezone.utc)
        for run in active_runs:
            run.status = RunStatus.canceled
            run.updated_at = now
        notify_telegram_event(
            db=db,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type="run.cancelled",
            summary=f"Force-deleted novel '{novel.title}': cancelled {len(active_runs)} active run(s)",
            extra={"novel_id": novel_id, "cancelled_run_ids": [r.id for r in active_runs]},
        )
    novel.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok", "cancelled_runs": len(active_runs) if active_runs else 0}


@router.get("/novels/{novel_id}/team", response_model=NovelTeamResponse)
def get_novel_team(novel_id: str, db: Session = Depends(get_db)) -> NovelTeamResponse:
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")
    raw = novel.team_json or {}
    team = {k: NovelTeamMember(**v) for k, v in raw.items() if isinstance(v, dict)}
    return NovelTeamResponse(novel_id=novel_id, team=team)


@router.put("/novels/{novel_id}/team", response_model=NovelTeamResponse)
def set_novel_team(
    novel_id: str,
    body: NovelTeamRequest,
    db: Session = Depends(get_db),
) -> NovelTeamResponse:
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")
    novel.team_json = {k: v.model_dump() for k, v in body.team.items()}
    db.commit()
    db.refresh(novel)
    raw = novel.team_json or {}
    team = {k: NovelTeamMember(**v) for k, v in raw.items() if isinstance(v, dict)}
    return NovelTeamResponse(novel_id=novel_id, team=team)


@router.delete("/chapters/{chapter_id}")
def delete_chapter(
    chapter_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None or chapter.deleted_at is not None:
        raise HTTPException(status_code=404, detail="chapter not found")
    chapter.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok"}


@router.post("/novels/{novel_id}/chapters", response_model=ChapterResponse, status_code=201)
def create_chapter(
    novel_id: str,
    body: ChapterCreateRequest,
    db: Session = Depends(get_db),
) -> ChapterResponse:
    novel = db.get(Novel, novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="novel not found")

    chapter = Chapter(
        id=f"chapter_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=f"tr_ch_{uuid4().hex[:12]}",
        correlation_id=f"cr_ch_{uuid4().hex[:12]}",
        idempotency_key=f"idem_chapter_{novel_id}_{body.chapter_no}_{uuid4().hex[:8]}",
        novel_id=novel_id,
        chapter_no=body.chapter_no,
        language_code=body.language_code,
        title=body.title,
        raw_text=body.markdown_text,
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    _append_revision_event(
        db=db,
        chapter=chapter,
        previous_markdown_text="",
        note="chapter.created",
        editor="system",
    )
    return _chapter_to_response(chapter)


@router.get("/novels/{novel_id}/chapters", response_model=list[ChapterResponse])
def list_chapters(novel_id: str, db: Session = Depends(get_db)) -> list[ChapterResponse]:
    rows = db.execute(
        select(Chapter)
        .where(
            Chapter.novel_id == novel_id,
            Chapter.deleted_at.is_(None),
        )
        .order_by(Chapter.chapter_no.asc())
    ).scalars().all()
    return [_chapter_to_response(row) for row in rows]


@router.get("/chapters/available-models", response_model=list[ModelProviderResponse])
def list_available_models(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[ModelProviderResponse]:
    rows = db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == tenant_id,
            ModelProvider.project_id == project_id,
            ModelProvider.deleted_at.is_(None),
        )
    ).scalars().all()
    return [
        ModelProviderResponse(
            id=row.id,
            name=row.name,
            endpoint=row.endpoint,
            auth_mode=row.auth_mode,
        )
        for row in rows
    ]


@router.get("/chapters/{chapter_id}", response_model=ChapterResponse)
def get_chapter(chapter_id: str, db: Session = Depends(get_db)) -> ChapterResponse:
    row = db.get(Chapter, chapter_id)
    if row is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return _chapter_to_response(row)


@router.put("/chapters/{chapter_id}", response_model=ChapterResponse)
def update_chapter(
    chapter_id: str,
    body: ChapterUpdateRequest,
    db: Session = Depends(get_db),
) -> ChapterResponse:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    previous_markdown_text = chapter.raw_text
    chapter.raw_text = body.markdown_text
    if body.title is not None:
        chapter.title = body.title
    if body.language_code is not None:
        chapter.language_code = body.language_code
    db.commit()
    db.refresh(chapter)

    _append_revision_event(
        db=db,
        chapter=chapter,
        previous_markdown_text=previous_markdown_text,
        note=body.revision_note or "chapter.updated",
        editor="editor",
    )
    return _chapter_to_response(chapter)


@router.get("/chapters/{chapter_id}/revisions", response_model=list[ChapterRevisionItem])
def list_chapter_revisions(chapter_id: str, db: Session = Depends(get_db)) -> list[ChapterRevisionItem]:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    rows = db.execute(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.tenant_id == chapter.tenant_id,
            WorkflowEvent.project_id == chapter.project_id,
            WorkflowEvent.event_type == "audit.recorded",
            WorkflowEvent.deleted_at.is_(None),
        )
        .order_by(WorkflowEvent.occurred_at.desc())
    ).scalars().all()

    items: list[ChapterRevisionItem] = []
    for row in rows:
        payload = row.payload_json or {}
        if payload.get("action") != "chapter.revision":
            continue
        if payload.get("chapter_id") != chapter_id:
            continue
        items.append(
            ChapterRevisionItem(
                revision_id=row.id,
                occurred_at=row.occurred_at,
                chapter_id=chapter_id,
                note=payload.get("note"),
                editor=payload.get("editor"),
                previous_markdown_text=payload.get("previous_markdown_text") or "",
            )
        )
    return items


@router.post("/chapters/{chapter_id}/preview-plan", response_model=ChapterPreviewResponse)
def preview_chapter_plan(
    chapter_id: str,
    body: ChapterPreviewRequest,
    db: Session = Depends(get_db),
) -> ChapterPreviewResponse:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    preview_run_id = f"run_preview_{uuid4().hex}"
    run = RenderRun(
        id=preview_run_id,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=f"tr_preview_{uuid4().hex[:12]}",
        correlation_id=f"cr_preview_{uuid4().hex[:12]}",
        idempotency_key=f"idem_preview_{chapter_id}_{uuid4().hex[:8]}",
        chapter_id=chapter_id,
        status=RunStatus.running,
        stage=RenderStage.plan,
        progress=0,
        config_json={"mode": "chapter_preview"},
    )
    db.add(run)
    db.commit()

    ctx = SkillContext(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        run_id=preview_run_id,
        trace_id=run.trace_id or f"tr_preview_{uuid4().hex[:12]}",
        correlation_id=run.correlation_id or f"cr_preview_{uuid4().hex[:12]}",
        idempotency_key=f"idem_preview_chain_{uuid4().hex[:12]}",
        schema_version="1.0",
    )

    registry = SkillRegistry(db)
    out_01 = registry.dispatch(
        "skill_01",
        Skill01Input(
            raw_text=chapter.raw_text,
            input_source_type="manual_text",
            source_metadata={"chapter_id": chapter.id, "novel_id": chapter.novel_id},
            project_id=chapter.project_id,
            task_id=f"preview_{chapter.id}",
        ),
        ctx,
    )
    out_02 = registry.dispatch(
        "skill_02",
        Skill02Input(
            primary_language=out_01.language_detection.primary_language,
            secondary_languages=out_01.language_detection.secondary_languages,
            normalized_text=out_01.normalized_text,
            quality_status=out_01.status,
            target_output_language=body.target_output_language or chapter.language_code,
            genre=body.genre,
            story_world_setting=body.story_world_setting,
            target_locale=body.target_locale or "",
            user_overrides={"culture_pack": body.culture_pack_id} if body.culture_pack_id else {},
            project_defaults={"active_persona_ref": body.persona_ref} if body.persona_ref else {},
        ),
        ctx,
    )
    out_03 = registry.dispatch(
        "skill_03",
        Skill03Input(
            segments=[segment.model_dump() for segment in out_01.segments],
            normalized_text=out_01.normalized_text,
            language_route=out_02.language_route.model_dump(),
            culture_hint=(
                body.culture_pack_id
                or (out_02.culture_candidates[0].culture_pack_id if out_02.culture_candidates else "")
            ),
            scene_planner_mode=out_02.planner_hints.scene_planner_mode,
        ),
        ctx,
    )

    run.progress = 100
    run.status = RunStatus.success
    run.stage = RenderStage.plan
    db.commit()

    return ChapterPreviewResponse(
        preview_run_id=preview_run_id,
        skill_01_status=out_01.status,
        skill_02_status=out_02.status,
        skill_03_status=out_03.status,
        normalized_text=out_01.normalized_text,
        culture_candidates=[item.culture_pack_id for item in out_02.culture_candidates],
        scene_count=len(out_03.scene_plan),
        shot_count=len(out_03.shot_plan),
        scene_plan=[item.model_dump() for item in out_03.scene_plan],
        shot_plan=[item.model_dump() for item in out_03.shot_plan],
    )


def _build_assist_prompt(
    *,
    chapter_title: str,
    markdown_text: str,
    instruction: str,
    style_hint: str,
    target_language: str,
) -> str:
    return (
        "你是小说编剧协作助手。请基于现有章节进行扩写，保留原剧情与人物设定。"
        "\n要求："
        "\n1) 在不改动核心剧情的情况下增加冲突和反转。"
        "\n2) 增加环境、动作和情绪细节，便于后续分镜。"
        "\n3) 输出为 Markdown，段落清晰。"
        f"\n4) 输出语言：{target_language}。"
        f"\n5) 风格提示：{style_hint or '影视化叙事'}。"
        f"\n6) 额外指令：{instruction}。"
        f"\n\n章节标题：{chapter_title or 'Untitled'}"
        "\n\n原文：\n"
        f"{markdown_text}"
    )


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


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


def _template_expand(markdown_text: str, instruction: str) -> str:
    appendix = (
        "\n\n## AI 扩写片段\n"
        "夜色压低了街巷的回声，主角在门前停顿半秒，确认每一道视线的方向。"
        "他推门而入时，灯火在盔甲边缘折出冷光，桌边的对话突然安静。"
        "最先开口的人没有提名字，只把一枚旧徽章推到木桌中央。"
        "主角看见那道刻痕，意识到这不是普通交易，而是对旧案的公开试探。"
        "冲突从言语升温到动作，三步之内就必须作出选择：妥协、对峙，或反制。"
        f"\n\n> 扩写方向：{instruction}"
    )
    return f"{markdown_text.rstrip()}{appendix}"


def _expand_with_provider(
    *,
    provider: ModelProvider,
    provider_settings: dict,
    prompt: str,
    max_tokens: int,
) -> tuple[str, str, str]:
    endpoint = (provider.endpoint or "").strip().rstrip("/")

    # Priority: ModelProvider.access_token (set via Provider form) > policy override
    token = (
        str(getattr(provider, "access_token", None) or "").strip()
        or str(provider_settings.get("access_token") or "").strip()
    )

    # Priority: ModelProvider.model_catalog > policy override, pick first available model
    model_catalog_from_provider: list = list(getattr(provider, "model_catalog", None) or [])
    model_catalog_from_settings: list = list(provider_settings.get("model_catalog") or [])
    model_catalog = model_catalog_from_provider or model_catalog_from_settings

    # DeepSeek-aware default: if provider name looks like deepseek, use its flagship model
    if not model_catalog:
        pname = (provider.name or "").lower()
        if "deepseek" in pname:
            model_catalog = ["deepseek-chat"]
        elif "anthropic" in pname or "claude" in pname:
            model_catalog = ["claude-3-5-sonnet-20241022"]
        elif "gemini" in pname or "google" in pname:
            model_catalog = ["gemini-1.5-pro"]
        elif "qwen" in pname or "alibaba" in pname or "aliyun" in pname:
            model_catalog = ["qwen-turbo"]
        elif "zhipu" in pname or "chatglm" in pname:
            model_catalog = ["glm-4"]
        elif "baidu" in pname or "ernie" in pname:
            model_catalog = ["ernie-3.5-8k"]
        elif "moonshot" in pname or "kimi" in pname:
            model_catalog = ["moonshot-v1-8k"]
        elif "minimax" in pname:
            model_catalog = ["abab6.5s-chat"]
        elif "stepfun" in pname or "step" in pname:
            model_catalog = ["step-1v-32k"]
        elif "openai" in pname or "gpt" in pname:
            model_catalog = ["gpt-4o-mini"]
        else:
            model_catalog = ["gpt-4o-mini"]

    model_name = model_catalog[0]

    if not endpoint or not token:
        raise ValueError(f"missing provider endpoint/token for provider '{provider.name}'")

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是专业编剧助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
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
    return content, provider.name, model_name


@router.post("/chapters/{chapter_id}/ai-expand", response_model=ChapterAssistExpandResponse)
def ai_expand_chapter(
    chapter_id: str,
    body: ChapterAssistExpandRequest,
    db: Session = Depends(get_db),
) -> ChapterAssistExpandResponse:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    markdown_text = chapter.raw_text or ""
    prompt = _build_assist_prompt(
        chapter_title=chapter.title or "",
        markdown_text=markdown_text,
        instruction=body.instruction,
        style_hint=body.style_hint,
        target_language=body.target_language or chapter.language_code or "zh-CN",
    )

    expanded = ""
    provider_used = "template_fallback"
    model_name = "template_v1"
    mode = "template"

    # 使用用户选择的指定 provider
    provider = db.get(ModelProvider, body.model_provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")
    if provider.tenant_id != body.tenant_id or provider.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="model provider scope mismatch")

    settings = _load_provider_settings(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        provider_id=provider.id,
    )
    try:
        expanded, provider_used, model_name = _expand_with_provider(
            provider=provider,
            provider_settings=settings,
            prompt=prompt,
            max_tokens=body.max_tokens,
        )
        mode = "provider_llm"
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        expanded = _template_expand(markdown_text, body.instruction)

    if not expanded:
        expanded = _template_expand(markdown_text, body.instruction)

    appended_excerpt = expanded[len(markdown_text):].strip() if expanded.startswith(markdown_text) else expanded[-320:]
    response = ChapterAssistExpandResponse(
        chapter_id=chapter_id,
        original_length=len(markdown_text),
        expanded_length=len(expanded),
        expanded_markdown=expanded,
        appended_excerpt=appended_excerpt,
        provider_used=provider_used,
        model_name=model_name,
        mode=mode,
        prompt_tokens_estimate=_estimate_tokens(prompt),
        completion_tokens_estimate=_estimate_tokens(expanded),
    )
    notify_telegram_event(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        event_type="plan.prompt.generated",
        summary="Chapter assist expansion completed",
        trace_id=chapter.trace_id,
        correlation_id=chapter.correlation_id,
        extra={
            "chapter_id": chapter_id,
            "mode": mode,
            "provider_used": provider_used,
            "model_name": model_name,
            "expanded_length": response.expanded_length,
        },
    )
    return response


@router.post("/chapters/{chapter_id}/tasks", response_model=TaskSubmitAccepted, status_code=202)
def create_chapter_task(
    chapter_id: str,
    body: ChapterTaskRequest,
    db: Session = Depends(get_db),
) -> TaskSubmitAccepted:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    now = datetime.now(timezone.utc)
    submit = TaskSubmitRequest(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        chapter_id=chapter_id,
        requested_quality=body.requested_quality,
        language_context=body.language_context,
        payload=body.payload,
        trace_id=body.trace_id or f"tr_task_{uuid4().hex[:12]}",
        correlation_id=body.correlation_id or f"cr_task_{uuid4().hex[:12]}",
        idempotency_key=body.idempotency_key or f"idem_task_{chapter_id}_{int(now.timestamp())}",
    )
    return create_task(submit, db)


def _chapter_to_response(chapter: Chapter) -> ChapterResponse:
    return ChapterResponse(
        id=chapter.id,
        tenant_id=chapter.tenant_id,
        project_id=chapter.project_id,
        novel_id=chapter.novel_id,
        chapter_no=chapter.chapter_no,
        language_code=chapter.language_code,
        title=chapter.title,
        markdown_text=chapter.raw_text,
    )


def _compute_diff(from_text: str, to_text: str) -> tuple[list[dict], int, int]:
    """
    简单的行级 diff 计算（基于行的增删比较）

    返回:
        (diff_lines, additions, deletions)
        - diff_lines: [{"type": "add/remove/unchanged", "content": "...", "line_no": int}]
        - additions: 增加的行数
        - deletions: 删除的行数
    """
    from_lines = from_text.split("\n")
    to_lines = to_text.split("\n")

    diff_lines = []
    additions = 0
    deletions = 0

    # 简单逻辑：比较行数
    i, j = 0, 0
    while i < len(from_lines) or j < len(to_lines):
        if i >= len(from_lines):
            # 剩余的是新增
            diff_lines.append({
                "type": "add",
                "content": to_lines[j],
                "line_no": j + 1
            })
            additions += 1
            j += 1
        elif j >= len(to_lines):
            # 剩余的是删除
            diff_lines.append({
                "type": "remove",
                "content": from_lines[i],
                "line_no": i + 1
            })
            deletions += 1
            i += 1
        elif from_lines[i] == to_lines[j]:
            # 相同行
            diff_lines.append({
                "type": "unchanged",
                "content": from_lines[i],
                "line_no": i + 1
            })
            i += 1
            j += 1
        else:
            # 不同：优先认为是删除 + 新增
            diff_lines.append({
                "type": "remove",
                "content": from_lines[i],
                "line_no": i + 1
            })
            diff_lines.append({
                "type": "add",
                "content": to_lines[j],
                "line_no": j + 1
            })
            additions += 1
            deletions += 1
            i += 1
            j += 1

    return diff_lines, additions, deletions


def _append_revision_event(
    *,
    db: Session,
    chapter: Chapter,
    previous_markdown_text: str,
    note: str,
    editor: str,
) -> None:
    event = WorkflowEvent(
        id=f"evt_{uuid4().hex[:24]}",
        tenant_id=chapter.tenant_id,
        project_id=chapter.project_id,
        trace_id=chapter.trace_id,
        correlation_id=chapter.correlation_id,
        idempotency_key=f"idem_revision_{chapter.id}_{uuid4().hex[:8]}",
        run_id=None,
        stage=None,
        event_type="audit.recorded",
        event_version="1.0",
        producer="studio_api",
        occurred_at=datetime.now(timezone.utc),
        payload_json={
            "action": "chapter.revision",
            "chapter_id": chapter.id,
            "note": note,
            "editor": editor,
            "previous_markdown_text": previous_markdown_text,
        },
    )
    db.add(event)
    db.commit()


@router.get("/chapters/{chapter_id}/publish-status", response_model=ChapterPublishStatus)
def get_chapter_publish_status(
    chapter_id: str,
    db: Session = Depends(get_db),
) -> ChapterPublishStatus:
    """获取章节发布状态"""
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    # 从 metadata 或事件日志中读取发布状态
    publish_metadata = chapter.metadata or {}
    publish_status = publish_metadata.get("publish_status", "draft")

    return ChapterPublishStatus(
        chapter_id=chapter_id,
        status=publish_status,
        submitted_by=publish_metadata.get("submitted_by"),
        submitted_at=publish_metadata.get("submitted_at"),
        approved_by=publish_metadata.get("approved_by"),
        approved_at=publish_metadata.get("approved_at"),
        rejected_by=publish_metadata.get("rejected_by"),
        rejected_at=publish_metadata.get("rejected_at"),
        rejection_reason=publish_metadata.get("rejection_reason"),
    )


@router.post("/chapters/{chapter_id}/publish-approval", response_model=ChapterPublishStatus)
def handle_chapter_publish_approval(
    chapter_id: str,
    body: ChapterPublishApprovalRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ChapterPublishStatus:
    """章节发布审批流程：submit/approve/reject"""
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    if not hasattr(request.state, "auth_claims") or not request.state.auth_claims:
        raise HTTPException(status_code=401, detail="AUTH-VALIDATION-001: unauthorized")

    user_id = request.state.auth_claims.user_id
    now = datetime.now(timezone.utc)

    # 初始化 metadata
    if chapter.metadata is None:
        chapter.metadata = {}

    action = body.action

    if action == "submit":
        # 提交审批
        chapter.metadata["publish_status"] = "pending"
        chapter.metadata["submitted_by"] = user_id
        chapter.metadata["submitted_at"] = now.isoformat()
        event_action = "chapter.publish.submitted"
    elif action == "approve":
        # 审批通过
        if chapter.metadata.get("publish_status") != "pending":
            raise HTTPException(
                status_code=400,
                detail="chapter must be in pending status to approve"
            )
        chapter.metadata["publish_status"] = "released"
        chapter.metadata["approved_by"] = user_id
        chapter.metadata["approved_at"] = now.isoformat()
        event_action = "chapter.publish.approved"
    elif action == "reject":
        # 驳回
        if chapter.metadata.get("publish_status") != "pending":
            raise HTTPException(
                status_code=400,
                detail="chapter must be in pending status to reject"
            )
        chapter.metadata["publish_status"] = "draft"
        chapter.metadata["rejected_by"] = user_id
        chapter.metadata["rejected_at"] = now.isoformat()
        chapter.metadata["rejection_reason"] = body.rejection_reason or ""
        event_action = "chapter.publish.rejected"
    else:
        raise HTTPException(status_code=400, detail=f"invalid action: {action}")

    # 记录审计事件
    event = WorkflowEvent(
        id=f"evt_{uuid4().hex[:24]}",
        tenant_id=chapter.tenant_id,
        project_id=chapter.project_id,
        trace_id=chapter.trace_id,
        correlation_id=chapter.correlation_id,
        idempotency_key=f"idem_publish_{chapter_id}_{uuid4().hex[:8]}",
        run_id=None,
        stage=None,
        event_type="audit.recorded",
        event_version="1.0",
        producer="studio_api",
        occurred_at=now,
        payload_json={
            "action": event_action,
            "chapter_id": chapter_id,
            "actor": user_id,
            "rejection_reason": body.rejection_reason,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(chapter)

    return ChapterPublishStatus(
        chapter_id=chapter_id,
        status=chapter.metadata.get("publish_status", "draft"),
        submitted_by=chapter.metadata.get("submitted_by"),
        submitted_at=chapter.metadata.get("submitted_at"),
        approved_by=chapter.metadata.get("approved_by"),
        approved_at=chapter.metadata.get("approved_at"),
        rejected_by=chapter.metadata.get("rejected_by"),
        rejected_at=chapter.metadata.get("rejected_at"),
        rejection_reason=chapter.metadata.get("rejection_reason"),
    )


@router.get("/chapters/{chapter_id}/diff", response_model=ChapterDiffResponse)
def get_chapter_diff(
    chapter_id: str,
    from_version: str = Query(default="latest"),
    to_version: str = Query(default="current"),
    db: Session = Depends(get_db),
) -> ChapterDiffResponse:
    """获取章节版本对比（PR 风格）"""
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    # 获取当前版本
    current_text = chapter.raw_text or ""

    # 获取历史版本（从事件日志中查询）
    revisions = db.execute(
        select(WorkflowEvent).where(
            WorkflowEvent.project_id == chapter.project_id,
            WorkflowEvent.payload_json["chapter_id"].astext == chapter_id,
            WorkflowEvent.event_type == "audit.recorded",
            WorkflowEvent.deleted_at.is_(None),
        ).order_by(WorkflowEvent.occurred_at.desc())
    ).scalars().all()

    from_text = current_text
    if from_version == "latest" and len(revisions) > 0:
        # 从最近的修订版本中获取
        for rev in revisions:
            if rev.payload_json.get("action") == "chapter.revision":
                from_text = rev.payload_json.get("previous_markdown_text", current_text)
                break

    to_text = current_text
    if to_version != "current":
        # 可以在这里扩展以支持指定版本查询
        pass

    diff_lines, additions, deletions = _compute_diff(from_text, to_text)

    return ChapterDiffResponse(
        chapter_id=chapter_id,
        from_version=from_version,
        to_version=to_version,
        from_text=from_text,
        to_text=to_text,
        diff_lines=diff_lines,
        additions=additions,
        deletions=deletions,
    )



class EntityExtractionRequest(BaseModel):
    tenant_id: str
    project_id: str
    model_provider_id: str
    chapter_ids: list[str] | None = None


class EntityExtractionResponse(BaseModel):
    novel_id: str
    entities_count: int
    aliases_count: int
    events_count: int
    preview: dict = Field(default_factory=dict)
    raw_response: str = ""


class DebugEntityExtractionRequest(BaseModel):
    text: str = Field(..., min_length=200)
    tenant_id: str = "default"
    project_id: str = "default"
    model_provider_id: str = "provider_deepseek"

@router.post("/debug/entity-extract")
def debug_entity_extract(
    body: DebugEntityExtractionRequest,
    db: Session = Depends(get_db),
):
    provider = db.get(ModelProvider, body.model_provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")
        
    prompt = _ENTITY_EXTRACTION_PROMPT.format(content=body.text)
    settings = _load_provider_settings(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        provider_id=provider.id,
    )
    
    import re as _re
    from loguru import logger

    extracted = None
    last_error = ""
    last_raw = ""
    current_prompt = prompt
    
    for attempt in range(2):  # 1 initial + 1 retry
        try:
            content, _, _ = _expand_with_provider(
                provider=provider,
                provider_settings=settings,
                prompt=current_prompt,
                max_tokens=2000,
            )
            last_raw = content
            json_match = _re.search(r'\{.*\}', content, _re.DOTALL)
            if json_match:
                extracted = json.loads(json_match.group())
                if isinstance(extracted, dict):
                    break
                else:
                    raise ValueError("Extracted JSON is not a dictionary/object.")
            else:
                raise ValueError("No JSON object found in output.")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Debug entity extraction iteration {attempt} failed: {e}. Raw content: {last_raw}")
            
            # If the error is an HTTP API error from the provider (like 401), fail immediately with a clear message
            if "provider_http_status_401" in last_error:
                raise HTTPException(
                    status_code=400,
                    detail="模型提供商身份鉴权失败（HTTP 401）。请前往「模型资产管理」确保证您的 API Key (Access Token) 配置正确且有效！"
                )
            elif "provider_http_status_" in last_error:
                raise HTTPException(
                    status_code=400,
                    detail=f"调用模型提供商 API 时遇到网络或服务端异常: {last_error}"
                )
                
            current_prompt += f"\n\n注意：你的上一次输出无法解析为JSON ({e})。请务必核对并**只**输出合法的 JSON 格式，请不要随意转义或输出任何多余文字。"

    if not isinstance(extracted, dict):
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract valid JSON after 1 retry. Last error: {last_error}",
        )
        
    return {
        "success": True,
        "raw_response": last_raw,
        "extracted": extracted,
    }


# ── Debug: LLM Run ─────────────────────────────────────────────────────────────

class DebugLLMRunRequest(BaseModel):
    system_prompt: str = "你是助手，请完成用户任务。"
    user_prompt: str = Field(..., min_length=1)
    tenant_id: str = "default"
    project_id: str = "default"
    model_provider_id: str = "provider_deepseek"
    max_tokens: int = 2000
    expect_json: bool = False


@router.post("/debug/llm-run")
def debug_llm_run(
    body: DebugLLMRunRequest,
    db: Session = Depends(get_db),
):
    import re as _re
    from loguru import logger

    provider = db.get(ModelProvider, body.model_provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")

    settings = _load_provider_settings(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        provider_id=provider.id,
    )

    model_catalog = list(settings.get("model_catalog") or [])
    model_name = model_catalog[0] if model_catalog else "unknown"
    run_id = str(uuid4()).replace("-", "")[:16]

    prompt_full = f"{body.system_prompt}\n\n{body.user_prompt}"
    raw_response = ""
    parsed_json = None
    validation_errors: list[str] = []
    token_usage: dict = {}
    finish_reason = ""

    try:
        raw_response, _provider_name, _model_name = _expand_with_provider(
            provider=provider,
            provider_settings=settings,
            prompt=prompt_full,
            max_tokens=body.max_tokens,
        )
    except Exception as exc:
        return {
            "run_id": run_id,
            "provider_name": provider.name,
            "model_name": model_name,
            "input_text_len": len(prompt_full),
            "text_preview": prompt_full[:200],
            "raw_response": "",
            "parsed_json": None,
            "validation_errors": [str(exc)],
            "token_usage": {},
            "finish_reason": "error",
        }

    if body.expect_json:
        cleaned = _re.sub(r"^```(?:json)?\s*", "", raw_response.strip(), flags=_re.MULTILINE)
        cleaned = _re.sub(r"\s*```$", "", cleaned.strip(), flags=_re.MULTILINE)
        try:
            m = _re.search(r"\{[\s\S]*\}", cleaned)
            if m:
                parsed_json = json.loads(m.group())
            else:
                validation_errors.append("No JSON object found in response")
        except Exception as exc:
            validation_errors.append(f"JSON parse error: {exc}")

    return {
        "run_id": run_id,
        "provider_name": provider.name,
        "model_name": model_name,
        "input_text_len": len(prompt_full),
        "text_preview": prompt_full[:200],
        "raw_response": raw_response,
        "parsed_json": parsed_json,
        "validation_errors": validation_errors,
        "token_usage": token_usage,
        "finish_reason": finish_reason,
    }


_ENTITY_EXTRACTION_PROMPT = """请从以下章节内提取实体信息，以严格的 JSON 格式输出，不要输出任何多余内容（不带 Markdown 标记）。如果文本长度超过 200 字，必须至少提取出主要角色和事件！

输出格式限定为：
{{
  "characters": [{{"name": "真实姓名", "aliases": ["其他称呼"], "role": "主角/核心配角/边缘配角/反派", "traits": ["性格特征或外貌"]}}],
  "locations": [{{"name": "地点名称", "description": "详细描述", "type": "室内/室外/城市/建筑"}}],
  "events": [{{"title": "核心事件概括", "participants": ["人物姓名"], "summary": "事件详细摘要"}}]
}}

注意：绝对不能返回空数组（除非文本毫无内容）。请务必仔细阅读以下章节内容进行抽取：

{content}
"""


@router.post("/novels/{novel_id}/extract-entities", response_model=EntityExtractionResponse)
def extract_novel_entities(
    novel_id: str,
    body: EntityExtractionRequest,
    db: Session = Depends(get_db),
) -> EntityExtractionResponse:
    novel = db.get(Novel, novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="novel not found")
    if novel.tenant_id != body.tenant_id or novel.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="novel scope mismatch")

    provider = db.get(ModelProvider, body.model_provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="model provider not found")
    if provider.tenant_id != body.tenant_id or provider.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="model provider scope mismatch")

    # Load chapters
    stmt = select(Chapter).where(
        Chapter.novel_id == novel_id,
        Chapter.deleted_at.is_(None),
    ).order_by(Chapter.chapter_no.asc())
    if body.chapter_ids:
        stmt = stmt.where(Chapter.id.in_(body.chapter_ids))
    chapters = db.execute(stmt).scalars().all()
    if not chapters:
        raise HTTPException(status_code=404, detail="no chapters found for extraction")

    # Combine chapter content
    content_parts = []
    for ch in chapters:
        text = (ch.raw_text or "").strip()
        if text:
            content_parts.append(f"=== 第{ch.chapter_no}章 {ch.title or ''} ===\n{text[:3000]}")
    combined_content = "\n\n".join(content_parts[:5])  # Limit to 5 chapters

    prompt = _ENTITY_EXTRACTION_PROMPT.format(content=combined_content)
    settings = _load_provider_settings(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        provider_id=provider.id,
    )

    import re as _re
    from loguru import logger

    extracted = None
    last_error = ""
    last_raw = ""
    current_prompt = prompt
    
    for attempt in range(2):  # 1 initial + 1 retry
        try:
            content, _, _ = _expand_with_provider(
                provider=provider,
                provider_settings=settings,
                prompt=current_prompt,
                max_tokens=2000,
            )
            last_raw = content
            json_match = _re.search(r'\{.*\}', content, _re.DOTALL)
            if json_match:
                extracted = json.loads(json_match.group())
                if isinstance(extracted, dict):
                    break
                else:
                    raise ValueError("Extracted JSON is not a dictionary/object.")
            else:
                raise ValueError("No JSON object found in output.")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Entity extraction iteration {attempt} for novel {novel_id} failed: {e}. Raw content: {last_raw}")
            
            # If the error is an HTTP API error from the provider (like 401), fail immediately with a clear message
            if "provider_http_status_401" in last_error:
                raise HTTPException(
                    status_code=400,
                    detail="模型提供商身份鉴权失败（HTTP 401）。请前往「模型资产管理」确保证您的 API Key (Access Token) 配置正确且有效！"
                )
            elif "provider_http_status_" in last_error:
                raise HTTPException(
                    status_code=400,
                    detail=f"调用模型提供商 API 时遇到网络或服务端异常: {last_error}"
                )
                
            # Append warning message strictly pointing back to original shape for retry
            current_prompt += f"\n\n注意：你的上一次输出无法解析为JSON ({e})。请仔细核查上一次输出错误的地方并**只**输出合法的 JSON 格式。"

    if not isinstance(extracted, dict):
        raise HTTPException(
            status_code=500,
            detail=f"实体提取失败：与大模型交互后提取到的结果无法解析为有效 JSON。内部错误：{last_error}"
        )

    # Calculate total parsed units for UI display/validation
    parsed_characters = len(extracted.get("characters", []))
    parsed_locations = len(extracted.get("locations", []))
    parsed_events = len(extracted.get("events", []))
    parsed_entity_count = parsed_characters + parsed_locations + parsed_events

    # Hard guard: 200+ len content typically shouldn't yield ZERO of everything
    if parsed_entity_count == 0 and len(combined_content) >= 200:
        raise HTTPException(
            status_code=500,
            detail=f"Parsed 0 entities from 200+ length text. Extraction may have failed. Raw: {last_raw}"
        )

    entities_count = parsed_entity_count
    aliases_count = 0
    events_count = parsed_events

    # Store characters
    for char in extracted.get("characters", []):
        name = str(char.get("name") or "").strip()
        if not name:
            continue
        # Check uniqueness constraint
        existing = db.execute(
            select(Entity).where(
                Entity.tenant_id == body.tenant_id,
                Entity.project_id == body.project_id,
                Entity.novel_id == novel_id,
                Entity.type == EntityType.person,
                Entity.label == name,
                Entity.deleted_at.is_(None),
            )
        ).scalars().first()
        if existing is None:
            entity = Entity(
                id=f"ent_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                novel_id=novel_id,
                type=EntityType.person,
                label=name,
                canonical_label=name,
                traits_json={
                    "role": char.get("role", ""),
                    "traits": char.get("traits", []),
                },
            )
            db.add(entity)
            db.flush()
            entities_count += 1

            for alias in char.get("aliases", []):
                alias_str = str(alias).strip()
                if alias_str and alias_str != name:
                    al = EntityAlias(
                        id=f"eal_{uuid4().hex}",
                        tenant_id=body.tenant_id,
                        project_id=body.project_id,
                        entity_id=entity.id,
                        alias=alias_str,
                    )
                    db.add(al)
                    aliases_count += 1

    # Store locations
    for loc in extracted.get("locations", []):
        name = str(loc.get("name") or "").strip()
        if not name:
            continue
        existing = db.execute(
            select(Entity).where(
                Entity.tenant_id == body.tenant_id,
                Entity.project_id == body.project_id,
                Entity.novel_id == novel_id,
                Entity.type == EntityType.place,
                Entity.label == name,
                Entity.deleted_at.is_(None),
            )
        ).scalars().first()
        if existing is None:
            entity = Entity(
                id=f"ent_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                novel_id=novel_id,
                type=EntityType.place,
                label=name,
                canonical_label=name,
                traits_json={
                    "description": loc.get("description", ""),
                    "type": loc.get("type", ""),
                },
            )
            db.add(entity)
            entities_count += 1

    # Store events (attached to first chapter)
    first_chapter = chapters[0] if chapters else None
    if first_chapter:
        for ev_idx, ev in enumerate(extracted.get("events", [])):
            title = str(ev.get("title") or "").strip()
            summary = str(ev.get("summary") or title).strip()
            if not summary:
                continue
            event_no = ev_idx + 1
            existing_ev = db.execute(
                select(StoryEvent).where(
                    StoryEvent.tenant_id == body.tenant_id,
                    StoryEvent.project_id == body.project_id,
                    StoryEvent.chapter_id == first_chapter.id,
                    StoryEvent.event_no == event_no,
                    StoryEvent.deleted_at.is_(None),
                )
            ).scalars().first()
            if existing_ev is None:
                story_event = StoryEvent(
                    id=f"sev_{uuid4().hex}",
                    tenant_id=body.tenant_id,
                    project_id=body.project_id,
                    chapter_id=first_chapter.id,
                    event_no=event_no,
                    summary=summary,
                    structured_json={
                        "title": title,
                        "participants": ev.get("participants", []),
                    },
                )
                db.add(story_event)
                events_count += 1

    db.commit()

    preview = {
        "characters": [c.get("name") for c in extracted.get("characters", [])[:5]],
        "locations": [l.get("name") for l in extracted.get("locations", [])[:5]],
        "events": [e.get("title") for e in extracted.get("events", [])[:5]],
    }

    notify_telegram_event(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        event_type="plan.prompt.generated",
        summary="Entity extraction completed",
        trace_id=novel.trace_id,
        correlation_id=novel.correlation_id,
        extra={
            "novel_id": novel_id,
            "entities_count": entities_count,
            "aliases_count": aliases_count,
            "events_count": events_count,
        },
    )

    return EntityExtractionResponse(
        novel_id=novel_id,
        entities_count=entities_count,
        aliases_count=aliases_count,
        events_count=events_count,
        preview=preview,
        raw_response=last_raw,
    )


# ---------------------------------------------------------------------------
# Entity Prompt Management
# ---------------------------------------------------------------------------

class PromptStruct(BaseModel):
    positive_zh: str = ""
    negative_zh: str = ""
    positive_en: str = ""
    negative_en: str = ""


class EntityPromptItem(BaseModel):
    entity_id: str
    type: str
    label: str
    canonical_label: str | None = None
    anchor_prompt: str | None = None
    prompt_struct: PromptStruct | None = None
    traits_json: dict | None = None
    alias_list: list[str] = Field(default_factory=list)
    reference_images: list[dict] = Field(default_factory=list)
    # classification fields (extracted from traits_json)
    role_tag: str | None = None
    persistence_type: str | None = None
    growth_type: str | None = None
    chapter_count: int = 0
    culture_pack_id: str | None = None
    prompt_origin: str = "base"


class EntityPromptsResponse(BaseModel):
    novel_id: str
    total: int
    by_type: dict[str, list[EntityPromptItem]]
    stats: dict = Field(default_factory=dict)
    culture_pack_id: str | None = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _std_variant_columns(prefix: str, token: str) -> dict[str, str | datetime]:
    now = _now_utc()
    return {
        "id": f"{prefix}_{uuid4().hex}",
        "trace_id": f"tr_{prefix}_{uuid4().hex[:12]}",
        "correlation_id": f"cr_{prefix}_{uuid4().hex[:12]}",
        "idempotency_key": f"idem_{prefix}_{token}_{uuid4().hex[:8]}",
        "created_at": now,
        "updated_at": now,
    }


def _get_prompt_variant_map(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    novel_id: str,
    entity_ids: list[str],
    culture_pack_id: str | None,
) -> dict[str, EntityPromptVariant]:
    if not culture_pack_id or not entity_ids:
        return {}
    rows = db.execute(
        select(EntityPromptVariant).where(
            EntityPromptVariant.tenant_id == tenant_id,
            EntityPromptVariant.project_id == project_id,
            EntityPromptVariant.novel_id == novel_id,
            EntityPromptVariant.entity_id.in_(entity_ids),
            EntityPromptVariant.culture_pack_id == culture_pack_id,
            EntityPromptVariant.deleted_at.is_(None),
        )
    ).scalars().all()
    return {row.entity_id: row for row in rows}


def _get_or_create_prompt_variant(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    novel_id: str,
    entity_id: str,
    culture_pack_id: str,
) -> EntityPromptVariant:
    row = db.execute(
        select(EntityPromptVariant).where(
            EntityPromptVariant.tenant_id == tenant_id,
            EntityPromptVariant.project_id == project_id,
            EntityPromptVariant.novel_id == novel_id,
            EntityPromptVariant.entity_id == entity_id,
            EntityPromptVariant.culture_pack_id == culture_pack_id,
            EntityPromptVariant.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = EntityPromptVariant(
        tenant_id=tenant_id,
        project_id=project_id,
        novel_id=novel_id,
        entity_id=entity_id,
        culture_pack_id=culture_pack_id,
        source="manual",
        **_std_variant_columns("epv", f"{entity_id}_{culture_pack_id}"),
    )
    db.add(row)
    db.flush()
    return row


def _load_culture_pack_context(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    culture_pack_id: str | None,
) -> dict[str, str | dict | None]:
    if not culture_pack_id:
        return {"display_name": None, "constraints": {}}
    rows = db.execute(
        select(CreativePolicyStack)
        .where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.deleted_at.is_(None),
        )
        .order_by(CreativePolicyStack.created_at.desc())
    ).scalars().all()
    for row in rows:
        payload = row.stack_json or {}
        if payload.get("type") == "culture_pack" and payload.get("culture_pack_id") == culture_pack_id:
            return {
                "display_name": payload.get("display_name") or culture_pack_id,
                "constraints": payload.get("constraints") or {},
            }
    return {"display_name": culture_pack_id, "constraints": {}}


@router.get("/novels/{novel_id}/entity-prompts", response_model=EntityPromptsResponse)
def get_entity_prompts(
    novel_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    entity_type: str | None = Query(None),
    culture_pack_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> EntityPromptsResponse:
    """Get all entities with their anchor_prompt, grouped by type."""
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")

    q = select(Entity).where(
        Entity.novel_id == novel_id,
        Entity.tenant_id == tenant_id,
        Entity.project_id == project_id,
        Entity.deleted_at.is_(None),
    )
    if entity_type:
        q = q.where(Entity.type == entity_type)
    q = q.order_by(Entity.type, Entity.label)
    entities = db.execute(q).scalars().all()

    entity_ids = [e.id for e in entities]
    aliases_map: dict[str, list[str]] = {}
    if entity_ids:
        alias_rows = db.execute(
            select(EntityAlias).where(
                EntityAlias.entity_id.in_(entity_ids),
                EntityAlias.deleted_at.is_(None),
            )
        ).scalars().all()
        for a in alias_rows:
            aliases_map.setdefault(a.entity_id, []).append(a.alias)

    variant_map = _get_prompt_variant_map(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        novel_id=novel_id,
        entity_ids=entity_ids,
        culture_pack_id=culture_pack_id,
    )

    by_type: dict[str, list[EntityPromptItem]] = {}
    for e in entities:
        tj = e.traits_json or {}
        variant = variant_map.get(e.id)
        prompt_origin = "base"
        effective_struct = e.prompt_struct_json
        effective_anchor_prompt = e.anchor_prompt
        if variant is not None:
            prompt_origin = "variant"
            effective_struct = variant.prompt_struct_json
            effective_anchor_prompt = variant.anchor_prompt
        elif culture_pack_id:
            prompt_origin = "inherited"
        ps = PromptStruct(**effective_struct) if effective_struct else None
        item = EntityPromptItem(
            entity_id=e.id,
            type=e.type.value if hasattr(e.type, "value") else str(e.type),
            label=e.label,
            canonical_label=e.canonical_label,
            anchor_prompt=effective_anchor_prompt,
            prompt_struct=ps,
            traits_json=e.traits_json,
            alias_list=aliases_map.get(e.id, []),
            reference_images=e.reference_images_json or [],
            role_tag=tj.get("role_tag"),
            persistence_type=tj.get("persistence_type"),
            growth_type=tj.get("growth_type"),
            chapter_count=len(tj.get("chapter_appearances", [])),
            culture_pack_id=culture_pack_id,
            prompt_origin=prompt_origin,
        )
        t = item.type
        by_type.setdefault(t, []).append(item)

    # Build stats
    all_items = [it for lst in by_type.values() for it in lst]
    stats = {
        "total": len(all_items),
        "with_prompt": sum(1 for it in all_items if it.anchor_prompt),
        "without_prompt": sum(1 for it in all_items if not it.anchor_prompt),
        "by_role": {},
        "by_persistence": {},
    }
    for it in all_items:
        r = it.role_tag or "unclassified"
        stats["by_role"][r] = stats["by_role"].get(r, 0) + 1
        p = it.persistence_type or "unclassified"
        stats["by_persistence"][p] = stats["by_persistence"].get(p, 0) + 1

    return EntityPromptsResponse(
        novel_id=novel_id,
        total=len(entities),
        by_type=by_type,
        stats=stats,
        culture_pack_id=culture_pack_id,
    )


class AnchorPromptUpdateRequest(BaseModel):
    anchor_prompt: str | None = None
    prompt_struct: PromptStruct | None = None
    traits_json: dict | None = None
    culture_pack_id: str | None = None


class AnchorPromptUpdateResponse(BaseModel):
    entity_id: str
    anchor_prompt: str | None
    prompt_struct: dict | None = None
    traits_json: dict | None
    updated: bool


@router.put("/entities/{entity_id}/anchor-prompt", response_model=AnchorPromptUpdateResponse)
def update_anchor_prompt(
    entity_id: str,
    body: AnchorPromptUpdateRequest,
    db: Session = Depends(get_db),
) -> AnchorPromptUpdateResponse:
    """Edit anchor_prompt and/or traits_json for an entity."""
    entity = db.get(Entity, entity_id)
    if entity is None or entity.deleted_at is not None:
        raise HTTPException(status_code=404, detail="entity not found")

    target_anchor = entity.anchor_prompt
    target_struct = entity.prompt_struct_json or {}
    variant: EntityPromptVariant | None = None
    if body.culture_pack_id:
        variant = _get_or_create_prompt_variant(
            db,
            tenant_id=entity.tenant_id,
            project_id=entity.project_id,
            novel_id=entity.novel_id,
            entity_id=entity.id,
            culture_pack_id=body.culture_pack_id,
        )
        target_anchor = variant.anchor_prompt
        target_struct = variant.prompt_struct_json or {}

    changed = False
    if body.anchor_prompt is not None and body.anchor_prompt != target_anchor:
        if variant is not None:
            variant.anchor_prompt = body.anchor_prompt
            variant.updated_at = _now_utc()
            variant.source = "manual"
        else:
            entity.anchor_prompt = body.anchor_prompt
        changed = True
    if body.prompt_struct is not None:
        new_struct = body.prompt_struct.model_dump()
        if new_struct != target_struct:
            if variant is not None:
                variant.prompt_struct_json = new_struct
                if new_struct.get("positive_zh"):
                    variant.anchor_prompt = new_struct["positive_zh"]
                variant.updated_at = _now_utc()
                variant.source = "manual"
            else:
                entity.prompt_struct_json = new_struct
                # Sync anchor_prompt from Chinese positive
                if new_struct.get("positive_zh"):
                    entity.anchor_prompt = new_struct["positive_zh"]
            changed = True
    if body.traits_json is not None and body.traits_json != entity.traits_json:
        entity.traits_json = body.traits_json
        changed = True
    if changed:
        db.commit()
        db.refresh(entity)

    return AnchorPromptUpdateResponse(
        entity_id=entity.id,
        anchor_prompt=variant.anchor_prompt if variant is not None else entity.anchor_prompt,
        prompt_struct=variant.prompt_struct_json if variant is not None else entity.prompt_struct_json,
        traits_json=entity.traits_json,
        updated=changed,
    )


class ChapterBeatItem(BaseModel):
    chapter_id: str
    chapter_no: int
    chapter_title: str | None = None
    beats: list[dict] = Field(default_factory=list)
    style_hints: list[dict] = Field(default_factory=list)


class ChapterBeatsResponse(BaseModel):
    novel_id: str
    chapters: list[ChapterBeatItem]


@router.get("/novels/{novel_id}/chapter-beats", response_model=ChapterBeatsResponse)
def get_chapter_beats(
    novel_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> ChapterBeatsResponse:
    """Get per-chapter beats and style_hints from world_model_json."""
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")

    chapters = db.execute(
        select(Chapter).where(
            Chapter.novel_id == novel_id,
            Chapter.tenant_id == tenant_id,
            Chapter.project_id == project_id,
            Chapter.deleted_at.is_(None),
        ).order_by(Chapter.chapter_no.asc())
    ).scalars().all()

    items: list[ChapterBeatItem] = []
    for ch in chapters:
        wm = ch.world_model_json or {}
        items.append(ChapterBeatItem(
            chapter_id=ch.id,
            chapter_no=ch.chapter_no,
            chapter_title=ch.title,
            beats=wm.get("beats", []),
            style_hints=wm.get("style_hints", []),
        ))

    return ChapterBeatsResponse(novel_id=novel_id, chapters=items)


class BatchAnchorPromptItem(BaseModel):
    entity_id: str
    anchor_prompt: str
    prompt_struct: dict | None = None


class BatchAnchorPromptRequest(BaseModel):
    items: list[BatchAnchorPromptItem] = Field(..., min_length=1, max_length=100)
    culture_pack_id: str | None = None


class BatchAnchorPromptResponse(BaseModel):
    updated: int
    skipped: int


@router.put("/novels/{novel_id}/entity-prompts/batch", response_model=BatchAnchorPromptResponse)
def batch_update_anchor_prompts(
    novel_id: str,
    body: BatchAnchorPromptRequest,
    db: Session = Depends(get_db),
) -> BatchAnchorPromptResponse:
    """Batch update anchor_prompt for multiple entities in a novel."""
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")

    entity_ids = [i.entity_id for i in body.items]
    entities = db.execute(
        select(Entity).where(
            Entity.id.in_(entity_ids),
            Entity.novel_id == novel_id,
            Entity.deleted_at.is_(None),
        )
    ).scalars().all()
    entity_map = {e.id: e for e in entities}

    updated = 0
    skipped = 0
    for item in body.items:
        entity = entity_map.get(item.entity_id)
        if entity is None:
            skipped += 1
            continue
        variant: EntityPromptVariant | None = None
        current_anchor_prompt = entity.anchor_prompt
        current_prompt_struct = entity.prompt_struct_json
        if body.culture_pack_id:
            variant = _get_or_create_prompt_variant(
                db,
                tenant_id=entity.tenant_id,
                project_id=entity.project_id,
                novel_id=entity.novel_id,
                entity_id=entity.id,
                culture_pack_id=body.culture_pack_id,
            )
            current_anchor_prompt = variant.anchor_prompt
            current_prompt_struct = variant.prompt_struct_json
        changed = False
        if current_anchor_prompt != item.anchor_prompt:
            if variant is not None:
                variant.anchor_prompt = item.anchor_prompt
                variant.source = "manual"
                variant.updated_at = _now_utc()
            else:
                entity.anchor_prompt = item.anchor_prompt
            changed = True
        if item.prompt_struct is not None:
            if current_prompt_struct != item.prompt_struct:
                if variant is not None:
                    variant.prompt_struct_json = item.prompt_struct
                    if item.prompt_struct.get("positive_zh"):
                        variant.anchor_prompt = str(item.prompt_struct["positive_zh"])
                    variant.source = "manual"
                    variant.updated_at = _now_utc()
                else:
                    entity.prompt_struct_json = item.prompt_struct
                changed = True
        if changed:
            updated += 1
        else:
            skipped += 1

    db.commit()
    return BatchAnchorPromptResponse(updated=updated, skipped=skipped)


# ---------------------------------------------------------------------------
# Entity Prompt Generation & Classification
# ---------------------------------------------------------------------------

class GenerateEntityPromptsRequest(BaseModel):
    tenant_id: str
    project_id: str
    model_provider_id: str | None = None  # If provided, use LLM to generate rich prompts
    overwrite: bool = False  # overwrite existing prompts
    chapter_ids: list[str] | None = None  # Limit to specific chapters for more detail
    culture_pack_id: str | None = None


class EntityClassificationItem(BaseModel):
    entity_id: str
    label: str
    type: str
    role_tag: str | None = None
    persistence_type: str | None = None
    growth_type: str | None = None
    chapter_count: int = 0
    anchor_prompt: str | None = None
    prompt_source: str = ""  # "generated" | "existing" | "skipped"


class GenerateEntityPromptsResponse(BaseModel):
    novel_id: str
    total: int
    generated: int
    classified: int
    skipped: int
    items: list[EntityClassificationItem]


def _match_entity_in_world_models(
    entity_label: str,
    entity_aliases: list[str],
    entity_type_str: str,
    chapters_wm: list[tuple[str, dict]],
) -> list[tuple[str, dict]]:
    """Find world model entries matching an entity across chapters.
    Returns list of (chapter_id, world_model_entry) tuples.
    """
    names = {entity_label.lower().strip()}
    for a in entity_aliases:
        names.add(a.lower().strip())

    # Map entity type to world model key
    type_to_wm_key = {
        "person": "characters",
        "place": "locations",
        "item": "props",
    }
    wm_key = type_to_wm_key.get(entity_type_str)
    if not wm_key:
        return []

    matches = []
    for chapter_id, wm in chapters_wm:
        entries = wm.get(wm_key, [])
        for entry in entries:
            entry_name = (entry.get("name") or "").lower().strip()
            # Check direct match or alias match
            entry_aliases = {a.lower().strip() for a in entry.get("aliases", [])}
            all_entry_names = {entry_name} | entry_aliases
            if names & all_entry_names:
                matches.append((chapter_id, entry))
    return matches


def _build_character_prompt(label: str, wm_entries: list[dict]) -> str:
    """Build base-model reference prompt for a character from world model entries.
    Focuses on stable physical traits: appearance, features, default outfit."""
    parts = [label]
    appearances = set()
    features = set()

    for entry in wm_entries:
        app = (entry.get("appearance") or "").strip()
        if app:
            appearances.add(app)
        feat = (entry.get("signature_features") or "").strip()
        if feat:
            features.add(feat)

    if appearances:
        parts.append("，".join(appearances))
    if features:
        parts.append("标志性特征：" + "，".join(features))

    return "。".join(parts)


def _build_location_prompt(label: str, wm_entries: list[dict]) -> str:
    """Build base-model reference prompt for a location.
    Focuses on spatial layout, architectural style, lighting, key visual elements."""
    parts = [label]
    keywords = set()

    for entry in wm_entries:
        for kw in entry.get("visual_keywords", []):
            kws = str(kw).strip()
            if kws:
                keywords.add(kws)

    if keywords:
        parts.append("视觉关键词：" + "、".join(keywords))

    return "。".join(parts)


def _build_prop_prompt(label: str, wm_entries: list[dict]) -> str:
    """Build base-model reference prompt for a prop.
    Focuses on material, shape, color, size, surface markings."""
    parts = [label]
    for entry in wm_entries:
        ptype = (entry.get("type") or "").strip()
        if ptype:
            parts.append(ptype)
        cond = (entry.get("material_condition") or "").strip()
        if cond:
            parts.append(cond)

    return "，".join(parts)


def _build_prompt_rule_based(label: str, type_str: str, wm_entries: list[dict], traits: dict) -> str:
    """Unified rule-based prompt builder. Returns empty string on failure."""
    if wm_entries:
        if type_str == "person":
            prompt = _build_character_prompt(label, wm_entries)
        elif type_str == "place":
            prompt = _build_location_prompt(label, wm_entries)
        elif type_str == "item":
            prompt = _build_prop_prompt(label, wm_entries)
        else:
            descs = []
            for e_wm in wm_entries:
                d = e_wm.get("description") or e_wm.get("summary") or ""
                if d:
                    descs.append(d)
            prompt = f"{label}：{'。'.join(descs)}" if descs else ""
        if prompt and prompt != label:
            return prompt
    # Fallback to traits
    trait_list = traits.get("traits", [])
    desc = traits.get("description", "")
    if trait_list or desc:
        pieces = [label]
        if desc:
            pieces.append(desc)
        if trait_list:
            pieces.append("，".join(str(t) for t in trait_list))
        return "。".join(pieces)
    return ""


def _classify_entity(
    entity_type_str: str,
    traits: dict,
    chapter_count: int,
    total_chapters: int,
    wm_entries: list[dict],
) -> tuple[str, str, str]:
    """Return (role_tag, persistence_type, growth_type)."""
    # ── persistence_type ──
    if chapter_count >= 3 or (total_chapters > 0 and chapter_count / total_chapters > 0.5):
        persistence_type = "recurring"
    else:
        persistence_type = "episodic"

    # ── role_tag ──
    role_raw = (traits.get("role") or "").lower()
    if entity_type_str != "person":
        if persistence_type == "recurring":
            role_tag = "key"
        else:
            role_tag = "background"
    elif "主角" in role_raw:
        role_tag = "protagonist"
    elif "核心" in role_raw or "反派" in role_raw:
        role_tag = "supporting"
    elif "配角" in role_raw:
        role_tag = "minor"
    elif chapter_count >= 3 or (total_chapters > 0 and chapter_count / total_chapters > 0.4):
        role_tag = "supporting"
    elif chapter_count >= 1:
        role_tag = "minor"
    else:
        role_tag = "background"

    # ── growth_type ──
    if entity_type_str == "person" and role_tag in ("protagonist", "supporting"):
        # Check if appearance descriptions differ across chapters
        appearances = set()
        for entry in wm_entries:
            app = (entry.get("appearance") or "").strip()
            if app:
                appearances.add(app)
        growth_type = "evolving" if len(appearances) > 1 else "static"
    else:
        growth_type = "static"

    return role_tag, persistence_type, growth_type


@router.post("/novels/{novel_id}/generate-entity-prompts", response_model=GenerateEntityPromptsResponse)
def generate_entity_prompts(
    novel_id: str,
    body: GenerateEntityPromptsRequest,
    db: Session = Depends(get_db),
) -> GenerateEntityPromptsResponse:
    """Aggregate world model data across all chapters, auto-classify entities,
    and generate anchor prompts for each entity.
    If no entities exist yet, creates them from world_model_json."""
    novel = db.get(Novel, novel_id)
    if novel is None or novel.deleted_at is not None:
        raise HTTPException(status_code=404, detail="novel not found")

    # ── 1. Load all chapters with world_model_json ──
    chapters = db.execute(
        select(Chapter).where(
            Chapter.novel_id == novel_id,
            Chapter.tenant_id == body.tenant_id,
            Chapter.project_id == body.project_id,
            Chapter.deleted_at.is_(None),
        ).order_by(Chapter.chapter_no.asc())
    ).scalars().all()

    chapters_wm: list[tuple[str, dict]] = []
    for ch in chapters:
        wm = ch.world_model_json
        if wm and isinstance(wm, dict):
            chapters_wm.append((ch.id, wm))

    total_chapters = len(chapters)

    # ── 2. Load existing entities for this novel ──
    entities = list(db.execute(
        select(Entity).where(
            Entity.novel_id == novel_id,
            Entity.tenant_id == body.tenant_id,
            Entity.project_id == body.project_id,
            Entity.deleted_at.is_(None),
        ).order_by(Entity.type, Entity.label)
    ).scalars().all())

    # ── 2b. If no entities exist, auto-create from world_model_json ──
    if not entities and chapters_wm:
        wm_type_map = {
            "characters": EntityType.person,
            "locations": EntityType.place,
            "props": EntityType.item,
        }
        seen_labels: set[tuple[str, str]] = set()  # (type, label_lower)
        for _ch_id, wm in chapters_wm:
            for wm_key, etype in wm_type_map.items():
                for entry in wm.get(wm_key, []):
                    name = str(entry.get("name") or "").strip()
                    if not name:
                        continue
                    type_str = etype.value
                    key = (type_str, name.lower())
                    if key in seen_labels:
                        continue
                    seen_labels.add(key)

                    # Build traits_json from world model entry
                    traits: dict = {}
                    if wm_key == "characters":
                        traits["role"] = entry.get("role", "")
                        traits["traits"] = entry.get("aliases", [])
                    elif wm_key == "locations":
                        traits["description"] = entry.get("mood", "")
                        traits["type"] = entry.get("type", "")
                    elif wm_key == "props":
                        traits["description"] = entry.get("material_condition", "")
                        traits["type"] = entry.get("type", "")

                    entity = Entity(
                        id=f"ent_{uuid4().hex}",
                        tenant_id=body.tenant_id,
                        project_id=body.project_id,
                        novel_id=novel_id,
                        type=etype,
                        label=name,
                        canonical_label=name,
                        traits_json=traits,
                    )
                    db.add(entity)
                    db.flush()

                    # Add aliases for characters
                    if wm_key == "characters":
                        for alias in entry.get("aliases", []):
                            alias_str = str(alias).strip()
                            if alias_str and alias_str.lower() != name.lower():
                                al = EntityAlias(
                                    id=f"eal_{uuid4().hex}",
                                    tenant_id=body.tenant_id,
                                    project_id=body.project_id,
                                    entity_id=entity.id,
                                    alias=alias_str,
                                )
                                db.add(al)

        db.flush()
        # Reload entities after creation
        entities = list(db.execute(
            select(Entity).where(
                Entity.novel_id == novel_id,
                Entity.tenant_id == body.tenant_id,
                Entity.project_id == body.project_id,
                Entity.deleted_at.is_(None),
            ).order_by(Entity.type, Entity.label)
        ).scalars().all())

    if not entities:
        return GenerateEntityPromptsResponse(
            novel_id=novel_id, total=0, generated=0, classified=0, skipped=0, items=[],
        )

    # ── 3. Load aliases ──
    entity_ids = [e.id for e in entities]
    alias_rows = db.execute(
        select(EntityAlias).where(
            EntityAlias.entity_id.in_(entity_ids),
            EntityAlias.deleted_at.is_(None),
        )
    ).scalars().all()
    aliases_map: dict[str, list[str]] = {}
    for a in alias_rows:
        aliases_map.setdefault(a.entity_id, []).append(a.alias)

    # ── 4. Process each entity: classify + collect world model context ──
    generated = 0
    classified = 0
    skipped = 0
    result_items: list[EntityClassificationItem] = []
    entities_needing_prompt: list[tuple[Entity, str, list[dict]]] = []  # (entity, type_str, wm_entries)
    variant_map = _get_prompt_variant_map(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        novel_id=novel_id,
        entity_ids=entity_ids,
        culture_pack_id=body.culture_pack_id,
    )

    for entity in entities:
        type_str = entity.type.value if hasattr(entity.type, "value") else str(entity.type)
        entity_aliases = aliases_map.get(entity.id, [])
        traits = entity.traits_json or {}

        # Find world model matches across chapters
        matches = _match_entity_in_world_models(
            entity.label, entity_aliases, type_str, chapters_wm,
        )
        matched_chapter_ids = list(dict.fromkeys(m[0] for m in matches))
        wm_entries = [m[1] for m in matches]

        # Classify
        role_tag, persistence_type, growth_type = _classify_entity(
            type_str, traits, len(matched_chapter_ids), total_chapters, wm_entries,
        )

        # Update traits_json with classification + chapter appearances
        new_traits = dict(traits)
        new_traits["role_tag"] = role_tag
        new_traits["persistence_type"] = persistence_type
        new_traits["growth_type"] = growth_type
        new_traits["chapter_appearances"] = matched_chapter_ids
        new_traits["appearance_count"] = len(matched_chapter_ids)
        entity.traits_json = new_traits
        classified += 1

        # Collect entities that need prompt generation
        existing_variant = variant_map.get(entity.id)
        current_prompt = existing_variant.anchor_prompt if existing_variant is not None else entity.anchor_prompt
        needs_gen = body.overwrite or not current_prompt
        if needs_gen:
            entities_needing_prompt.append((entity, type_str, wm_entries))

    # ── 5. Generate prompts ──
    if entities_needing_prompt and body.model_provider_id:
        # ── LLM-based generation ──
        provider = db.get(ModelProvider, body.model_provider_id)
        if provider is None or provider.deleted_at is not None:
            raise HTTPException(status_code=404, detail="model provider not found")

        settings = _load_provider_settings(
            db,
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            provider_id=provider.id,
        )

        # Build context for LLM: entity list with world model descriptions
        entity_contexts = []
        for entity, type_str, wm_entries in entities_needing_prompt:
            ctx = {
                "entity_id": entity.id,
                "name": entity.label,
                "type": type_str,
                "role_tag": (entity.traits_json or {}).get("role_tag", ""),
                "persistence_type": (entity.traits_json or {}).get("persistence_type", ""),
                "growth_type": (entity.traits_json or {}).get("growth_type", ""),
                "aliases": aliases_map.get(entity.id, []),
                "traits": entity.traits_json or {},
            }
            # Add world model evidence — focus on stable physical traits
            evidence = []
            for wm_e in wm_entries:
                # Descriptive fields that contain stable traits
                for k in ("appearance", "signature_features",
                           "material_condition", "description"):
                    v = wm_e.get(k, "")
                    if v and str(v).strip():
                        evidence.append(f"{k}: {v}")
                # Also add basic evidence snippets
                evs = wm_e.get("evidence", [])
                for ev in evs[:2]:
                    evidence.append(str(ev).strip())
            ctx["evidence"] = evidence[:12]
            entity_contexts.append(ctx)

        # Batch into chunks of 10 for LLM calls
        import re as _re
        from loguru import logger

        culture_ctx = _load_culture_pack_context(
            db,
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            culture_pack_id=body.culture_pack_id,
        )
        culture_instruction = ""
        if body.culture_pack_id:
            culture_instruction = (
                f"\n═══ 文化包约束 ═══\n"
                f"- culture_pack_id: {body.culture_pack_id}\n"
                f"- culture_pack_name: {culture_ctx.get('display_name') or body.culture_pack_id}\n"
                f"- constraints_json: {json.dumps(culture_ctx.get('constraints') or {}, ensure_ascii=False)}\n"
                "- 在保持同一实体核心身份与基模稳定的前提下，服饰、道具、场景语汇、材质与视觉文化表达要符合该文化包。\n"
            )

        for batch_start in range(0, len(entity_contexts), 10):
            batch = entity_contexts[batch_start:batch_start + 10]
            batch_json = json.dumps(batch, ensure_ascii=False, indent=2)

            prompt_text = f"""你是一位专业的 AI 绘图提示词工程师。请为以下小说实体生成**结构化基础模型参考提示词**，用于 AI 绘图生成该实体的基础参考图 / 模型设定图。

你需要为每个实体输出 4 个字段：
- positive_zh: 中文正向提示词（描述要画什么）
- negative_zh: 中文反向提示词（描述要避免什么）
- positive_en: 英文正向提示词（与中文语义一致，适配 Stable Diffusion / Midjourney 等英文模型）
- negative_en: 英文反向提示词

═══ 正向提示词格式规范 ═══
- 使用逗号分隔的短语标签式写法，不要写完整长句
- 人物(person) 必须包含标签：主体类型, 性别, 年龄段, 体型, 发型发色, 瞳色, 肤色, 默认服饰, 标志性特征/饰品, 画面风格/画质标签
  示例: "1girl, young woman, slender build, long black hair, dark brown eyes, fair skin, traditional Chinese daoist robe, wooden sword on back, detailed face, full body, standing pose, white background, masterpiece, best quality"
- 场景(place) 必须包含标签：场景类型, 空间规模, 建筑/自然风格, 主色调, 光线, 关键视觉元素, 材质纹理
- 道具(item) 必须包含标签：物品类型, 材质, 形状, 颜色, 尺寸参照, 表面标记/装饰, 画面风格

═══ 反向提示词格式规范 ═══
- 列出此实体应避免的视觉元素
- 通用反向标签：lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, blurry, watermark, text, signature
- 根据实体类型追加：
  - 人物：wrong eye color, wrong hair color, deformed face, ugly, duplicate, mutilated
  - 场景：out of frame, poorly drawn, amateur
  - 道具：out of frame, poorly drawn

═══ 核心原则 ═══
- 只描述恒定基础外观，禁止动作/姿态/表情/情绪描写
- 默认正面站立 / 自然静态视角，白色或简洁背景
- 从 evidence 提取永久外观特征，忽略章节内动态描写
- 可成长(evolving)实体只描述默认基础形态
- 贯穿型(recurring)实体要更详细
- 不要凭空创造证据中不存在的外观细节
{culture_instruction}

═══ 输出格式 ═══
严格 JSON：
{{"prompts": [
  {{
    "entity_id": "xxx",
    "positive_zh": "中文正向标签...",
    "negative_zh": "中文反向标签...",
    "positive_en": "English positive tags...",
    "negative_en": "English negative tags..."
  }}
]}}

实体列表：
{batch_json}"""

            try:
                content, _, _ = _expand_with_provider(
                    provider=provider,
                    provider_settings=settings,
                    prompt=prompt_text,
                    max_tokens=6000,
                )
                json_match = _re.search(r'\{.*\}', content, _re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    prompts_list = result.get("prompts", [])
                    prompt_map = {p["entity_id"]: p for p in prompts_list if p.get("entity_id")}

                    for entity, type_str, wm_entries in entities_needing_prompt[batch_start:batch_start + 10]:
                        p_data = prompt_map.get(entity.id)
                        if p_data and (p_data.get("positive_zh") or p_data.get("positive_en")):
                            struct = {
                                "positive_zh": p_data.get("positive_zh", ""),
                                "negative_zh": p_data.get("negative_zh", ""),
                                "positive_en": p_data.get("positive_en", ""),
                                "negative_en": p_data.get("negative_en", ""),
                            }
                            if body.culture_pack_id:
                                variant = _get_or_create_prompt_variant(
                                    db,
                                    tenant_id=entity.tenant_id,
                                    project_id=entity.project_id,
                                    novel_id=entity.novel_id,
                                    entity_id=entity.id,
                                    culture_pack_id=body.culture_pack_id,
                                )
                                variant.prompt_struct_json = struct
                                variant.anchor_prompt = struct["positive_zh"]
                                variant.source = "generated"
                                variant.updated_at = _now_utc()
                            else:
                                entity.prompt_struct_json = struct
                                # Keep anchor_prompt as legacy fallback (Chinese positive)
                                entity.anchor_prompt = struct["positive_zh"]
                            generated += 1
                        else:
                            skipped += 1
                else:
                    logger.warning(f"LLM returned no JSON for batch {batch_start}")
                    skipped += len(batch)
            except Exception as e:
                logger.error(f"LLM prompt generation failed for batch {batch_start}: {e}")
                # Fallback to rule-based for this batch
                for entity, type_str, wm_entries in entities_needing_prompt[batch_start:batch_start + 10]:
                    prompt = _build_prompt_rule_based(entity.label, type_str, wm_entries, entity.traits_json or {})
                    if prompt:
                        if body.culture_pack_id:
                            variant = _get_or_create_prompt_variant(
                                db,
                                tenant_id=entity.tenant_id,
                                project_id=entity.project_id,
                                novel_id=entity.novel_id,
                                entity_id=entity.id,
                                culture_pack_id=body.culture_pack_id,
                            )
                            variant.anchor_prompt = prompt
                            variant.source = "generated"
                            variant.updated_at = _now_utc()
                        else:
                            entity.anchor_prompt = prompt
                        generated += 1
                    else:
                        skipped += 1

    elif entities_needing_prompt:
        # ── Rule-based generation (no model selected) ──
        for entity, type_str, wm_entries in entities_needing_prompt:
            prompt = _build_prompt_rule_based(entity.label, type_str, wm_entries, entity.traits_json or {})
            if prompt:
                if body.culture_pack_id:
                    variant = _get_or_create_prompt_variant(
                        db,
                        tenant_id=entity.tenant_id,
                        project_id=entity.project_id,
                        novel_id=entity.novel_id,
                        entity_id=entity.id,
                        culture_pack_id=body.culture_pack_id,
                    )
                    variant.anchor_prompt = prompt
                    variant.source = "generated"
                    variant.updated_at = _now_utc()
                else:
                    entity.anchor_prompt = prompt
                generated += 1
            else:
                skipped += 1

    if body.culture_pack_id:
        variant_map = _get_prompt_variant_map(
            db,
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            novel_id=novel_id,
            entity_ids=entity_ids,
            culture_pack_id=body.culture_pack_id,
        )

    # Build result items
    for entity in entities:
        type_str = entity.type.value if hasattr(entity.type, "value") else str(entity.type)
        tj = entity.traits_json or {}
        matched_chapter_ids = tj.get("chapter_appearances", [])

        # Determine prompt_source
        was_in_needing = any(e.id == entity.id for e, _, _ in entities_needing_prompt)
        variant = variant_map.get(entity.id)
        effective_anchor_prompt = variant.anchor_prompt if variant is not None else entity.anchor_prompt
        if was_in_needing and effective_anchor_prompt:
            prompt_source = "generated"
        elif was_in_needing:
            prompt_source = "skipped"
        else:
            prompt_source = "existing"

        result_items.append(EntityClassificationItem(
            entity_id=entity.id,
            label=entity.label,
            type=type_str,
            role_tag=tj.get("role_tag"),
            persistence_type=tj.get("persistence_type"),
            growth_type=tj.get("growth_type"),
            chapter_count=len(matched_chapter_ids),
            anchor_prompt=effective_anchor_prompt,
            prompt_source=prompt_source,
        ))

    db.commit()

    return GenerateEntityPromptsResponse(
        novel_id=novel_id,
        total=len(entities),
        generated=generated,
        classified=classified,
        skipped=skipped,
        items=result_items,
    )


# ---------------------------------------------------------------------------
# Entity Classification Update
# ---------------------------------------------------------------------------

class UpdateEntityClassificationRequest(BaseModel):
    role_tag: str | None = None
    persistence_type: str | None = None
    growth_type: str | None = None


class UpdateEntityClassificationResponse(BaseModel):
    entity_id: str
    role_tag: str | None
    persistence_type: str | None
    growth_type: str | None
    updated: bool


@router.put("/entities/{entity_id}/classification", response_model=UpdateEntityClassificationResponse)
def update_entity_classification(
    entity_id: str,
    body: UpdateEntityClassificationRequest,
    db: Session = Depends(get_db),
) -> UpdateEntityClassificationResponse:
    """Manually override entity classification."""
    entity = db.get(Entity, entity_id)
    if entity is None or entity.deleted_at is not None:
        raise HTTPException(status_code=404, detail="entity not found")

    traits = dict(entity.traits_json or {})
    changed = False

    for field in ("role_tag", "persistence_type", "growth_type"):
        val = getattr(body, field)
        if val is not None and traits.get(field) != val:
            traits[field] = val
            changed = True

    if changed:
        entity.traits_json = traits
        db.commit()
        db.refresh(entity)

    return UpdateEntityClassificationResponse(
        entity_id=entity.id,
        role_tag=traits.get("role_tag"),
        persistence_type=traits.get("persistence_type"),
        growth_type=traits.get("growth_type"),
        updated=changed,
    )


# ── Entity Reference Image Upload / Delete ──────────────────────

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))


class EntityReferenceImageResponse(BaseModel):
    entity_id: str
    reference_images: list[dict]


@router.post("/entities/{entity_id}/reference-images", response_model=EntityReferenceImageResponse)
async def upload_entity_reference_image(
    entity_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> EntityReferenceImageResponse:
    """Upload a reference / model-sheet image for an entity."""
    entity = db.get(Entity, entity_id)
    if entity is None or entity.deleted_at is not None:
        raise HTTPException(status_code=404, detail="entity not found")

    # Validate file type
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的图片格式: .{ext}，允许: {', '.join(ALLOWED_IMAGE_EXTENSIONS)}")

    # Validate file size (max 10MB)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片大小不能超过 10MB")

    # Save file
    image_id = uuid4().hex[:12]
    safe_filename = f"{entity_id}_{image_id}.{ext}"
    entity_dir = UPLOAD_DIR / "entity_images"
    entity_dir.mkdir(parents=True, exist_ok=True)
    file_path = entity_dir / safe_filename
    file_path.write_bytes(content)

    # Update reference_images_json
    images = list(entity.reference_images_json or [])
    images.append({
        "id": image_id,
        "url": f"/uploads/entity_images/{safe_filename}",
        "filename": file.filename or safe_filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    })
    entity.reference_images_json = images
    db.commit()
    db.refresh(entity)

    return EntityReferenceImageResponse(
        entity_id=entity.id,
        reference_images=entity.reference_images_json or [],
    )


@router.delete("/entities/{entity_id}/reference-images/{image_id}", response_model=EntityReferenceImageResponse)
def delete_entity_reference_image(
    entity_id: str,
    image_id: str,
    db: Session = Depends(get_db),
) -> EntityReferenceImageResponse:
    """Delete a reference image from an entity."""
    entity = db.get(Entity, entity_id)
    if entity is None or entity.deleted_at is not None:
        raise HTTPException(status_code=404, detail="entity not found")

    images = list(entity.reference_images_json or [])
    target = None
    remaining = []
    for img in images:
        if img.get("id") == image_id:
            target = img
        else:
            remaining.append(img)

    if target is None:
        raise HTTPException(status_code=404, detail="image not found")

    # Delete file from disk
    url = target.get("url", "")
    if url.startswith("/uploads/"):
        rel_path = url[len("/uploads/"):]
        file_path = UPLOAD_DIR / rel_path
        if file_path.is_file():
            file_path.unlink()

    entity.reference_images_json = remaining
    db.commit()
    db.refresh(entity)

    return EntityReferenceImageResponse(
        entity_id=entity.id,
        reference_images=entity.reference_images_json or [],
    )
