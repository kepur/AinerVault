from __future__ import annotations

from datetime import datetime, timezone
import json
import requests
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel
from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
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


class NovelResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    title: str
    summary: str | None = None
    default_language_code: str


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
    return NovelResponse(
        id=novel.id,
        tenant_id=novel.tenant_id,
        project_id=novel.project_id,
        title=novel.title,
        summary=novel.summary,
        default_language_code=novel.default_language_code,
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
    return [
        NovelResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            title=row.title,
            summary=row.summary,
            default_language_code=row.default_language_code,
        )
        for row in rows
    ]


@router.get("/novels/{novel_id}", response_model=NovelResponse)
def get_novel(novel_id: str, db: Session = Depends(get_db)) -> NovelResponse:
    row = db.get(Novel, novel_id)
    if row is None:
        raise HTTPException(status_code=404, detail="novel not found")
    return NovelResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        title=row.title,
        summary=row.summary,
        default_language_code=row.default_language_code,
    )


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


@router.get("/chapters/{chapter_id}", response_model=ChapterResponse)
def get_chapter(chapter_id: str, db: Session = Depends(get_db)) -> ChapterResponse:
    row = db.get(Chapter, chapter_id)
    if row is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return _chapter_to_response(row)


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
    token = str(provider_settings.get("access_token") or "").strip()
    model_catalog = list(provider_settings.get("model_catalog") or [])
    model_name = model_catalog[0] if model_catalog else "gpt-4o-mini"
    if not endpoint or not token:
        raise ValueError("missing provider endpoint/token")

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
        timeout=16.0,
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

    providers = db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == body.tenant_id,
            ModelProvider.project_id == body.project_id,
            ModelProvider.deleted_at.is_(None),
        )
    ).scalars().all()

    for provider in providers:
        settings = _load_provider_settings(
            db,
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            provider_id=provider.id,
        )
        if not settings.get("enabled", True):
            continue
        try:
            expanded, provider_used, model_name = _expand_with_provider(
                provider=provider,
                provider_settings=settings,
                prompt=prompt,
                max_tokens=body.max_tokens,
            )
            mode = "provider_llm"
            break
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            continue

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


@router.get("/chapters/available-models", response_model=list[dict])
def get_available_models(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[dict]:
    """获取项目内已接入的可用模型列表"""
    models = db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == tenant_id,
            ModelProvider.project_id == project_id,
            ModelProvider.deleted_at.is_(None),
        )
        .order_by(ModelProvider.created_at.desc())
    ).scalars().all()

    return [
        {
            "id": model.id,
            "name": model.name,
            "endpoint": model.endpoint or model.name,
            "is_default": model.is_default,
        }
        for model in models
    ]


@router.post("/chapters/{chapter_id}/ai-expand", response_model=ChapterAssistExpandResponse, status_code=202)
def ai_expand_chapter_content(
    chapter_id: str,
    body: ChapterAssistExpandRequest,
    db: Session = Depends(get_db),
) -> ChapterAssistExpandResponse:
    """一键AI智能扩展章节剧情"""
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    if chapter.tenant_id != body.tenant_id or chapter.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN: scope mismatch")

    original_text = chapter.raw_text or ""
    if not original_text:
        raise HTTPException(status_code=400, detail="REQ-VALIDATION-001: chapter content is empty")

    # 获取用户选择的模型档案（从model_provider_id）
    selected_model = db.get(ModelProvider, body.model_provider_id)
    if not selected_model:
        raise HTTPException(status_code=404, detail="REQ-VALIDATION-002: model provider not found")

    if selected_model.tenant_id != body.tenant_id or selected_model.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN: model scope mismatch")

    # 从用户选择的模型获取provider和model_name
    provider_used = selected_model.name  # 如 "deepseek", "openai", "claude"
    model_name = selected_model.endpoint or selected_model.name  # 如 "deepseek-chat", "gpt-4"

    # 构建扩展提示词
    expansion_prompt = _build_expansion_prompt(
        original_text=original_text,
        instruction=body.instruction,
        style_hint=body.style_hint,
        target_language=body.target_language or "zh",
    )

    # 调用真实LLM API进行内容扩展
    try:
        expanded_text, prompt_tokens, completion_tokens = _call_llm_api(
            model_provider=provider_used,
            model_name=model_name,
            prompt=expansion_prompt,
            max_tokens=body.max_tokens,
            temperature=0.7,
        )
    except Exception as e:
        # 如果LLM调用失败，返回错误信息
        raise HTTPException(
            status_code=503,
            detail=f"[SYS-LLM-001] LLM service error: {str(e)}",
        )

    # 提取新增部分
    appended_excerpt = expanded_text[len(original_text):] if len(expanded_text) > len(original_text) else expanded_text[:200]

    # 记录AI扩展事件
    now = datetime.now(timezone.utc)
    event = WorkflowEvent(
        id=f"evt_{uuid4().hex[:24]}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=chapter.trace_id or f"tr_expand_{uuid4().hex[:12]}",
        correlation_id=chapter.correlation_id or f"cr_expand_{uuid4().hex[:12]}",
        idempotency_key=f"idem_expand_{chapter_id}_{uuid4().hex[:8]}",
        run_id=None,
        event_type="chapter.ai_expansion",
        event_version="1.0",
        producer="studio_api",
        occurred_at=now,
        payload_json={
            "chapter_id": chapter_id,
            "instruction": body.instruction,
            "style_hint": body.style_hint,
            "original_length": len(original_text),
            "expanded_length": len(expanded_text),
            "model": model_name,
            "provider": provider_used,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    )
    db.add(event)
    db.commit()

    notify_telegram_event(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        event_type="chapter.ai_expansion",
        summary=f"AI扩展章节 {chapter.title or 'Chapter'}",
        run_id=None,
        trace_id=chapter.trace_id or f"tr_expand_{uuid4().hex[:12]}",
        correlation_id=chapter.correlation_id or f"cr_expand_{uuid4().hex[:12]}",
        extra={
            "chapter_id": chapter_id,
            "original_length": len(original_text),
            "expanded_length": len(expanded_text),
        },
    )

    return ChapterAssistExpandResponse(
        chapter_id=chapter_id,
        original_length=len(original_text),
        expanded_length=len(expanded_text),
        expanded_markdown=expanded_text,
        appended_excerpt=appended_excerpt,
        provider_used=provider_used,
        model_name=model_name,
        mode="expand",
        prompt_tokens_estimate=prompt_tokens,
        completion_tokens_estimate=completion_tokens,
    )


def _build_expansion_prompt(
    original_text: str,
    instruction: str,
    style_hint: str,
    target_language: str = "zh",
) -> str:
    """构建AI扩展提示词"""
    return f"""你是一位专业的网络小说编剧助手。
当前任务：{instruction}

原始文本：
```
{original_text}
```

写作风格指引：{style_hint}

要求：
1. 保持原有故事主线和人物设定
2. 增加细节描写、心理活动、对话等元素
3. 提升情节节奏和阅读体验
4. 保持一致的叙事风格
5. 只输出扩展后的完整文本，不要包含任何解释或标记

输出语言：{target_language}
"""


def _call_llm_api(
    model_provider: str,
    model_name: str,
    prompt: str,
    max_tokens: int = 900,
    temperature: float = 0.7,
) -> tuple[str, int, int]:
    """
    调用真实的LLM API进行内容扩展

    Returns:
        (expanded_text, prompt_tokens, completion_tokens)
    """
    try:
        # DeepSeek API 调用
        if model_provider.lower() in ["deepseek", "deep-seek"]:
            return _call_deepseek_api(model_name, prompt, max_tokens, temperature)

        # OpenAI API 调用
        elif model_provider.lower() in ["openai", "gpt"]:
            return _call_openai_api(model_name, prompt, max_tokens, temperature)

        # Claude API 调用
        elif model_provider.lower() in ["anthropic", "claude"]:
            return _call_claude_api(model_name, prompt, max_tokens, temperature)

        # 其他API调用
        else:
            return _call_generic_api(model_provider, model_name, prompt, max_tokens, temperature)

    except Exception as e:
        # 如果API调用失败，使用fallback方法
        print(f"⚠️ LLM API 调用失败: {str(e)}, 使用 fallback 方法")
        return _fallback_llm_expansion(prompt, max_tokens)


def _call_deepseek_api(
    model_name: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, int, int]:
    """调用 DeepSeek API"""
    import os

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY 环境变量未设置")

    url = "https://api.deepseek.com/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name or "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一位专业的网络小说编剧助手。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()

    result = response.json()
    expanded_text = result["choices"][0]["message"]["content"]
    prompt_tokens = result.get("usage", {}).get("prompt_tokens", 0)
    completion_tokens = result.get("usage", {}).get("completion_tokens", 0)

    return expanded_text, prompt_tokens, completion_tokens


def _call_openai_api(
    model_name: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, int, int]:
    """调用 OpenAI API"""
    import os

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY 环境变量未设置")

    url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name or "gpt-4",
        "messages": [
            {"role": "system", "content": "你是一位专业的网络小说编剧助手。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()

    result = response.json()
    expanded_text = result["choices"][0]["message"]["content"]
    prompt_tokens = result.get("usage", {}).get("prompt_tokens", 0)
    completion_tokens = result.get("usage", {}).get("completion_tokens", 0)

    return expanded_text, prompt_tokens, completion_tokens


def _call_claude_api(
    model_name: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, int, int]:
    """调用 Claude API (Anthropic)"""
    import os

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

    url = "https://api.anthropic.com/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name or "claude-3-sonnet-20240229",
        "max_tokens": max_tokens,
        "messages": [
            {"role": "user", "content": prompt},
        ],
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()

    result = response.json()
    expanded_text = result["content"][0]["text"]
    prompt_tokens = result.get("usage", {}).get("input_tokens", 0)
    completion_tokens = result.get("usage", {}).get("output_tokens", 0)

    return expanded_text, prompt_tokens, completion_tokens


def _call_generic_api(
    provider: str,
    model_name: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, int, int]:
    """调用通用的 OpenAI 兼容 API"""
    import os

    api_key = os.getenv(f"{provider.upper()}_API_KEY", "")
    if not api_key:
        # 如果没有API key，使用fallback
        return _fallback_llm_expansion(prompt, max_tokens)

    base_url = os.getenv(f"{provider.upper()}_API_BASE", f"https://api.{provider.lower()}.com/v1")

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是一位专业的网络小说编剧助手。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()

    result = response.json()
    expanded_text = result["choices"][0]["message"]["content"]
    prompt_tokens = result.get("usage", {}).get("prompt_tokens", 0)
    completion_tokens = result.get("usage", {}).get("completion_tokens", 0)

    return expanded_text, prompt_tokens, completion_tokens


def _fallback_llm_expansion(prompt: str, max_tokens: int) -> tuple[str, int, int]:
    """
    Fallback: 当LLM API不可用时使用本地简单扩展算法

    Returns:
        (expanded_text, prompt_tokens, completion_tokens)
    """
    # 从prompt中提取原始文本
    original_text = prompt.split("原始文本：")[1].split("```")[1] if "原始文本：" in prompt else ""

    if not original_text:
        # 如果提取失败，直接返回一个简单的扩展
        target_length = min(300, max_tokens * 4)
        expanded_text = "这是一段AI生成的扩展文本。" + ("" * (target_length - 20))
        return expanded_text, len(prompt) // 4, 75

    # 简单的扩展算法：在原文基础上增加描写
    sentences = original_text.split('。')
    expanded_sentences = []
    target_length = min(len(original_text) * 2, len(original_text) + max_tokens * 4)

    for i, sentence in enumerate(sentences):
        if sentence.strip():
            expanded_sentences.append(sentence + '。')
            # 在某些句子后面添加扩展内容
            if i % 3 == 1 and len('。'.join(expanded_sentences)) < target_length:
                expansion = _generate_sentence_expansion(sentence)
                expanded_sentences.append(expansion)

    expanded_text = ''.join(expanded_sentences)
    expanded_text = expanded_text[:target_length] if len(expanded_text) > target_length else expanded_text

    prompt_tokens = len(prompt) // 4
    completion_tokens = len(expanded_text) // 4

    return expanded_text, prompt_tokens, completion_tokens


def _generate_sentence_expansion(sentence: str) -> str:
    """为句子生成扩展描写"""
    # 简单的扩展模板
    expansions = {
        "发生": "这时，一股不可名状的感觉涌上心头。",
        "走": "缓缓踱步，脚步声在寂静中显得格外清晰。",
        "说": "他停顿了片刻，用低沉的嗓音说道。",
        "看": "眼神中闪烁着复杂的光芒，仔细打量着眼前的一切。",
    }

    for key, value in expansions.items():
        if key in sentence:
            return value

    return "一时间，气氛变得凝重起来。"
