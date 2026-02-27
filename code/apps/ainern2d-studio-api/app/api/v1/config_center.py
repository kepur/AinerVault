from __future__ import annotations

from datetime import datetime, timezone
import importlib
import json
import re
from time import perf_counter
from typing import Any, TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from langgraph.graph import END, StateGraph

from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.provider_models import ModelProfile, ModelProvider
from ainern2d_shared.services.base_skill import SkillContext

from app.api.deps import get_db
from app.services.skill_registry import SkillRegistry
from app.services.telegram_notify import notify_telegram_event

router = APIRouter(prefix="/api/v1/config", tags=["config"])
_BOOTSTRAP_WS_CLIENTS: dict[str, set[WebSocket]] = {}


class ProviderUpsertRequest(BaseModel):
    tenant_id: str
    project_id: str
    name: str
    endpoint: str | None = None
    auth_mode: str | None = "api_key"
    enabled: bool | None = None
    access_token: str | None = None
    model_catalog: list[str] | None = None
    headers_json: dict | None = None
    capability_flags: dict | None = None


class ProviderCapabilitySet(BaseModel):
    supports_text_generation: bool = True
    supports_embedding: bool = False
    supports_multimodal: bool = False
    supports_image_generation: bool = False
    supports_video_generation: bool = False
    supports_tts: bool = False
    supports_stt: bool = False
    supports_tool_calling: bool = False
    supports_reasoning: bool = False


class ProviderResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    name: str
    endpoint: str | None = None
    auth_mode: str | None = None
    enabled: bool = True
    access_token_masked: str | None = None
    model_catalog: list[str] = Field(default_factory=list)
    headers_json: dict = Field(default_factory=dict)
    capability_flags: ProviderCapabilitySet = Field(default_factory=ProviderCapabilitySet)


class ModelProfileUpsertRequest(BaseModel):
    tenant_id: str
    project_id: str
    provider_id: str
    purpose: str
    name: str
    params_json: dict = Field(default_factory=dict)
    capability_tags: list[str] = Field(default_factory=list)
    default_params: dict = Field(default_factory=dict)
    cost_rate_limit: dict = Field(default_factory=dict)
    guardrails: dict = Field(default_factory=dict)
    routing_policy: dict = Field(default_factory=dict)


class ModelProfileResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    provider_id: str
    purpose: str
    name: str
    params_json: dict = Field(default_factory=dict)
    capability_tags: list[str] = Field(default_factory=list)
    default_params: dict = Field(default_factory=dict)
    cost_rate_limit: dict = Field(default_factory=dict)
    guardrails: dict = Field(default_factory=dict)
    routing_policy: dict = Field(default_factory=dict)


class RolePermissionSet(BaseModel):
    can_import_data: bool = False
    can_publish_task: bool = False
    can_edit_global_knowledge: bool = False
    can_manage_model_router: bool = False


class RoleProfileUpsertRequest(BaseModel):
    tenant_id: str
    project_id: str
    role_id: str
    prompt_style: str = ""
    default_skills: list[str] = Field(default_factory=list)
    default_knowledge_scopes: list[str] = Field(default_factory=list)
    default_model_profile: str | None = None
    permissions: RolePermissionSet = Field(default_factory=RolePermissionSet)
    enabled: bool = True
    schema_version: str = "1.0"


class RoleProfileResponse(BaseModel):
    tenant_id: str
    project_id: str
    role_id: str
    prompt_style: str = ""
    default_skills: list[str] = Field(default_factory=list)
    default_knowledge_scopes: list[str] = Field(default_factory=list)
    default_model_profile: str | None = None
    permissions: RolePermissionSet = Field(default_factory=RolePermissionSet)
    enabled: bool = True
    schema_version: str = "1.0"
    updated_at: str | None = None


class SkillRegistryUpsertRequest(BaseModel):
    tenant_id: str
    project_id: str
    skill_id: str
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    required_knowledge_scopes: list[str] = Field(default_factory=list)
    default_model_profile: str | None = None
    tools_required: list[str] = Field(default_factory=list)
    ui_renderer: str = "form"
    init_template: str | None = None
    enabled: bool = True
    schema_version: str = "1.0"


class SkillRegistryResponse(BaseModel):
    tenant_id: str
    project_id: str
    skill_id: str
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    required_knowledge_scopes: list[str] = Field(default_factory=list)
    default_model_profile: str | None = None
    tools_required: list[str] = Field(default_factory=list)
    ui_renderer: str = "form"
    init_template: str | None = None
    enabled: bool = True
    schema_version: str = "1.0"
    updated_at: str | None = None


class FeatureRouteMapUpsertRequest(BaseModel):
    tenant_id: str
    project_id: str
    route_id: str
    path: str
    component: str
    feature_id: str
    allowed_roles: list[str] = Field(default_factory=list)
    ui_mode: str = "list"
    depends_on: list[str] = Field(default_factory=list)
    enabled: bool = True
    schema_version: str = "1.0"


class FeatureRouteMapResponse(BaseModel):
    tenant_id: str
    project_id: str
    route_id: str
    path: str
    component: str
    feature_id: str
    allowed_roles: list[str] = Field(default_factory=list)
    ui_mode: str = "list"
    depends_on: list[str] = Field(default_factory=list)
    enabled: bool = True
    schema_version: str = "1.0"
    updated_at: str | None = None


class RoleStudioResolveRequest(BaseModel):
    tenant_id: str
    project_id: str
    role_id: str
    skill_id: str
    context: dict = Field(default_factory=dict)


class RoleStudioResolveResponse(BaseModel):
    tenant_id: str
    project_id: str
    role_id: str
    skill_id: str
    resolved_model_profile: dict = Field(default_factory=dict)
    resolved_knowledge_scopes: list[str] = Field(default_factory=list)
    visible_routes: list[FeatureRouteMapResponse] = Field(default_factory=list)
    role_profile: RoleProfileResponse
    skill_profile: SkillRegistryResponse


class RoleStudioRunSkillRequest(BaseModel):
    tenant_id: str
    project_id: str
    role_id: str
    skill_id: str
    input_payload: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    run_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None
    schema_version: str = "1.0"


class RoleStudioRunSkillResponse(BaseModel):
    tenant_id: str
    project_id: str
    role_id: str
    skill_id: str
    run_id: str
    execution_mode: str
    status: str
    resolved_model_profile: dict = Field(default_factory=dict)
    resolved_knowledge_scopes: list[str] = Field(default_factory=list)
    output: dict = Field(default_factory=dict)
    logs: list[dict] = Field(default_factory=list)


class StageRoutingRequest(BaseModel):
    tenant_id: str
    project_id: str
    routes: dict = Field(default_factory=dict)
    fallback_chain: dict = Field(default_factory=dict)
    feature_routes: dict = Field(default_factory=dict)


class StageRoutingResponse(BaseModel):
    tenant_id: str
    project_id: str
    routes: dict = Field(default_factory=dict)
    fallback_chain: dict = Field(default_factory=dict)
    feature_routes: dict = Field(default_factory=dict)


class FeatureProfileOption(BaseModel):
    profile_id: str
    provider_id: str
    provider_name: str
    purpose: str
    model_name: str


class FeatureMatrixItem(BaseModel):
    feature_key: str
    description: str
    eligible_profiles: list[FeatureProfileOption] = Field(default_factory=list)


class FeatureMatrixResponse(BaseModel):
    tenant_id: str
    project_id: str
    items: list[FeatureMatrixItem] = Field(default_factory=list)


class ProviderConnectionTestRequest(BaseModel):
    tenant_id: str
    project_id: str
    probe_path: str = "/models"
    timeout_ms: int = 4000


class ProviderConnectionTestResponse(BaseModel):
    provider_id: str
    provider_name: str
    endpoint: str
    probe_url: str
    connected: bool
    status_code: int | None = None
    latency_ms: int | None = None
    message: str


class ProviderHealthItem(BaseModel):
    provider_id: str
    provider_name: str
    status: str
    reason: str


class ConfigHealthResponse(BaseModel):
    tenant_id: str
    project_id: str
    provider_count: int
    profile_count: int
    routing_ready: bool
    providers: list[ProviderHealthItem] = Field(default_factory=list)


class LanguageDefinition(BaseModel):
    language_code: str
    label: str
    locales: list[str] = Field(default_factory=list)
    direction: str = "ltr"
    enabled: bool = True


class LanguageSettingsRequest(BaseModel):
    tenant_id: str
    project_id: str
    default_source_language: str = "zh-CN"
    default_target_languages: list[str] = Field(default_factory=lambda: ["en-US"])
    enabled_languages: list[LanguageDefinition] = Field(default_factory=list)
    translation_notes: str | None = None
    glossary: dict = Field(default_factory=dict)
    schema_version: str = "1.0"


class LanguageSettingsResponse(BaseModel):
    tenant_id: str
    project_id: str
    default_source_language: str
    default_target_languages: list[str] = Field(default_factory=list)
    enabled_languages: list[LanguageDefinition] = Field(default_factory=list)
    translation_notes: str | None = None
    glossary: dict = Field(default_factory=dict)
    schema_version: str = "1.0"
    updated_at: str | None = None


class TelegramSettingsRequest(BaseModel):
    tenant_id: str
    project_id: str
    enabled: bool = False
    bot_token: str | None = None
    chat_id: str | None = None
    thread_id: str | None = None
    parse_mode: str = "Markdown"
    notify_events: list[str] = Field(
        default_factory=lambda: [
            "run.failed",
            "run.succeeded",
            "job.failed",
            "job.created",
            "task.submitted",
            "bootstrap.started",
            "bootstrap.completed",
            "bootstrap.failed",
            "role.skill.run.completed",
            "role.skill.run.failed",
            "plan.prompt.generated",
            "rag.embedding.completed",
        ]
    )
    schema_version: str = "1.0"


class TelegramSettingsResponse(BaseModel):
    tenant_id: str
    project_id: str
    enabled: bool = False
    bot_token_masked: str | None = None
    chat_id: str | None = None
    thread_id: str | None = None
    parse_mode: str = "Markdown"
    notify_events: list[str] = Field(default_factory=list)
    schema_version: str = "1.0"
    updated_at: str | None = None


class TelegramSettingsTestRequest(BaseModel):
    tenant_id: str
    project_id: str
    message_text: str | None = None
    bot_token: str | None = None
    chat_id: str | None = None
    thread_id: str | None = None
    parse_mode: str | None = None
    timeout_ms: int = 5000


class TelegramSettingsTestResponse(BaseModel):
    delivered: bool
    status_code: int | None = None
    latency_ms: int | None = None
    message: str
    telegram_ok: bool | None = None


class BootstrapDefaultsRequest(BaseModel):
    tenant_id: str
    project_id: str
    seed_mode: str = "llm_template"
    model_profile_id: str | None = None
    role_ids: list[str] = Field(default_factory=list)
    enrich_rounds: int = Field(default=2, ge=1, le=6)
    session_id: str | None = None
    include_roles: bool = True
    include_skills: bool = True
    include_routes: bool = True
    include_language_settings: bool = True
    include_stage_routing: bool = True


class BootstrapDefaultsResponse(BaseModel):
    tenant_id: str
    project_id: str
    seed_mode: str
    roles_upserted: int
    skills_upserted: int
    routes_upserted: int
    language_settings_applied: bool
    stage_routing_applied: bool
    summary: dict = Field(default_factory=dict)


class BootstrapGraphState(TypedDict):
    tenant_id: str
    project_id: str
    seed_mode: str
    session_id: str | None
    default_model_profile: str | None
    enrich_rounds: int
    include_roles: bool
    include_skills: bool
    include_routes: bool
    include_language_settings: bool
    include_stage_routing: bool
    role_templates: list[dict[str, Any]]
    skills_templates: list[dict[str, Any]]
    route_templates: list[dict[str, Any]]
    roles_upserted: int
    skills_upserted: int
    routes_upserted: int
    language_settings_applied: bool
    stage_routing_applied: bool


def _mask_secret(secret: str | None) -> str | None:
    if not secret:
        return None
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


def _default_telegram_settings(tenant_id: str, project_id: str) -> TelegramSettingsResponse:
    return TelegramSettingsResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        enabled=False,
        bot_token_masked=None,
        chat_id=None,
        thread_id=None,
        parse_mode="Markdown",
        notify_events=[
            "run.failed",
            "run.succeeded",
            "job.failed",
            "job.created",
            "task.submitted",
            "bootstrap.started",
            "bootstrap.completed",
            "bootstrap.failed",
            "role.skill.run.completed",
            "role.skill.run.failed",
            "plan.prompt.generated",
            "rag.embedding.completed",
        ],
        schema_version="1.0",
        updated_at=None,
    )


def _provider_settings_stack_name(provider_id: str) -> str:
    return f"provider_settings:{provider_id}"


def _default_provider_settings() -> dict:
    return {
        "type": "provider_settings",
        "enabled": True,
        "access_token": None,
        "model_catalog": [],
        "headers_json": {},
        "capability_flags": ProviderCapabilitySet().model_dump(mode="json"),
        "schema_version": "1.0",
        "updated_at": None,
    }


def _provider_settings_map(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    provider_ids: list[str],
) -> dict[str, dict]:
    if not provider_ids:
        return {}
    stack_names = [_provider_settings_stack_name(provider_id) for provider_id in provider_ids]
    rows = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name.in_(stack_names),
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().all()
    payload_by_name = {
        row.name: dict(row.stack_json or {})
        for row in rows
    }
    result: dict[str, dict] = {}
    for provider_id in provider_ids:
        payload = payload_by_name.get(_provider_settings_stack_name(provider_id)) or _default_provider_settings()
        result[provider_id] = payload
    return result


def _upsert_provider_settings(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    provider_id: str,
    payload: dict,
) -> None:
    stack_name = _provider_settings_stack_name(provider_id)
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == stack_name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        row = CreativePolicyStack(
            id=f"policy_{uuid4().hex}",
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_provider_meta_{uuid4().hex[:12]}",
            correlation_id=f"cr_provider_meta_{uuid4().hex[:12]}",
            idempotency_key=f"idem_provider_meta_{provider_id}_{uuid4().hex[:8]}",
            name=stack_name,
            status="active",
            stack_json=payload,
        )
        db.add(row)
    else:
        row.status = "active"
        row.stack_json = payload


def _build_provider_response(row: ModelProvider, settings_payload: dict) -> ProviderResponse:
    default_settings = _default_provider_settings()
    merged = {**default_settings, **(settings_payload or {})}
    capability_flags = ProviderCapabilitySet.model_validate(merged.get("capability_flags") or {})
    return ProviderResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        name=row.name,
        endpoint=row.endpoint,
        auth_mode=row.auth_mode,
        enabled=bool(merged.get("enabled", True)),
        access_token_masked=_mask_secret(merged.get("access_token")),
        model_catalog=list(merged.get("model_catalog") or []),
        headers_json=dict(merged.get("headers_json") or {}),
        capability_flags=capability_flags,
    )


def _provider_supports_feature(capability_flags: ProviderCapabilitySet, feature_key: str) -> bool:
    feature_gate_map = {
        "text_generation": capability_flags.supports_text_generation,
        "embedding": capability_flags.supports_embedding,
        "multimodal": capability_flags.supports_multimodal,
        "image_generation": capability_flags.supports_image_generation,
        "video_generation": capability_flags.supports_video_generation,
        "tts": capability_flags.supports_tts,
        "stt": capability_flags.supports_stt,
    }
    return bool(feature_gate_map.get(feature_key, False))


def _build_model_profile_params(body: ModelProfileUpsertRequest) -> dict:
    params = dict(body.params_json or {})
    params["capability_tags"] = list(body.capability_tags or [])
    params["default_params"] = dict(body.default_params or {})
    params["cost_rate_limit"] = dict(body.cost_rate_limit or {})
    params["guardrails"] = dict(body.guardrails or {})
    params["routing_policy"] = dict(body.routing_policy or {})
    return params


def _build_model_profile_response(row: ModelProfile) -> ModelProfileResponse:
    payload = dict(row.params_json or {})
    return ModelProfileResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        provider_id=row.provider_id,
        purpose=row.purpose,
        name=row.name,
        params_json=payload,
        capability_tags=list(payload.get("capability_tags") or []),
        default_params=dict(payload.get("default_params") or {}),
        cost_rate_limit=dict(payload.get("cost_rate_limit") or {}),
        guardrails=dict(payload.get("guardrails") or {}),
        routing_policy=dict(payload.get("routing_policy") or {}),
    )


def _config_stack_name(prefix: str, item_id: str) -> str:
    return f"{prefix}:{item_id}"


def _upsert_config_stack(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    stack_name: str,
    payload: dict,
    trace_prefix: str,
) -> dict:
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == stack_name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        row = CreativePolicyStack(
            id=f"policy_{uuid4().hex}",
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{trace_prefix}_{uuid4().hex[:12]}",
            correlation_id=f"cr_{trace_prefix}_{uuid4().hex[:12]}",
            idempotency_key=f"idem_{trace_prefix}_{uuid4().hex[:8]}",
            name=stack_name,
            status="active",
            stack_json=payload,
        )
        db.add(row)
    else:
        row.status = "active"
        row.stack_json = payload
    return payload


def _delete_config_stack(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    stack_name: str,
) -> bool:
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == stack_name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        return False
    row.deleted_at = datetime.now(timezone.utc)
    return True


def _list_config_stacks(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    prefix: str,
) -> list[CreativePolicyStack]:
    rows = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name.like(f"{prefix}:%"),
            CreativePolicyStack.deleted_at.is_(None),
        ).order_by(CreativePolicyStack.created_at.desc())
    ).scalars().all()
    return rows


def _load_config_stack_payload(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    stack_name: str,
) -> dict | None:
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == stack_name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        return None
    return dict(row.stack_json or {})


@router.post("/providers", response_model=ProviderResponse)
def upsert_provider(body: ProviderUpsertRequest, db: Session = Depends(get_db)) -> ProviderResponse:
    row = db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == body.tenant_id,
            ModelProvider.project_id == body.project_id,
            ModelProvider.name == body.name,
            ModelProvider.deleted_at.is_(None),
        )
    ).scalars().first()

    if row is None:
        row = ModelProvider(
            id=f"provider_{uuid4().hex}",
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            trace_id=f"tr_provider_{uuid4().hex[:12]}",
            correlation_id=f"cr_provider_{uuid4().hex[:12]}",
            idempotency_key=f"idem_provider_{body.name}_{uuid4().hex[:8]}",
            name=body.name,
            endpoint=body.endpoint,
            auth_mode=body.auth_mode,
        )
        db.add(row)
    else:
        row.endpoint = body.endpoint
        row.auth_mode = body.auth_mode

    current_settings = _provider_settings_map(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        provider_ids=[row.id],
    ).get(row.id, _default_provider_settings())

    if body.access_token is None:
        access_token = current_settings.get("access_token")
    else:
        access_token = body.access_token or None

    capability_source = body.capability_flags if body.capability_flags is not None else current_settings.get(
        "capability_flags"
    )
    settings_payload = {
        "type": "provider_settings",
        "enabled": bool(body.enabled if body.enabled is not None else current_settings.get("enabled", True)),
        "access_token": access_token,
        "model_catalog": body.model_catalog if body.model_catalog is not None else current_settings.get("model_catalog", []),
        "headers_json": body.headers_json if body.headers_json is not None else current_settings.get("headers_json", {}),
        "capability_flags": ProviderCapabilitySet.model_validate(capability_source or {}).model_dump(mode="json"),
        "schema_version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _upsert_provider_settings(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        provider_id=row.id,
        payload=settings_payload,
    )
    db.commit()
    db.refresh(row)
    return _build_provider_response(row, settings_payload)


@router.get("/providers", response_model=list[ProviderResponse])
def list_providers(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[ProviderResponse]:
    rows = db.execute(
        select(ModelProvider)
        .where(
            ModelProvider.tenant_id == tenant_id,
            ModelProvider.project_id == project_id,
            ModelProvider.deleted_at.is_(None),
        )
        .order_by(ModelProvider.created_at.desc())
    ).scalars().all()
    settings_by_provider = _provider_settings_map(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        provider_ids=[row.id for row in rows],
    )
    return [_build_provider_response(row, settings_by_provider.get(row.id, {})) for row in rows]


@router.delete("/providers/{provider_id}")
def delete_provider(
    provider_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    row = db.get(ModelProvider, provider_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="provider not found")
    if row.tenant_id != tenant_id or row.project_id != project_id:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN-002: provider scope mismatch")

    now = datetime.now(timezone.utc)
    row.deleted_at = now
    profiles = db.execute(
        select(ModelProfile).where(
            ModelProfile.provider_id == provider_id,
            ModelProfile.deleted_at.is_(None),
        )
    ).scalars().all()
    for profile in profiles:
        profile.deleted_at = now
    stack = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == _provider_settings_stack_name(provider_id),
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if stack is not None:
        stack.deleted_at = now
    db.commit()
    return {"status": "deleted", "provider_id": provider_id}


@router.post("/providers/{provider_id}/test-connection", response_model=ProviderConnectionTestResponse)
def test_provider_connection(
    provider_id: str,
    body: ProviderConnectionTestRequest,
    db: Session = Depends(get_db),
) -> ProviderConnectionTestResponse:
    provider = db.get(ModelProvider, provider_id)
    if provider is None or provider.deleted_at is not None:
        raise HTTPException(status_code=404, detail="provider not found")
    if provider.tenant_id != body.tenant_id or provider.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN-002: provider scope mismatch")

    endpoint = (provider.endpoint or "").strip()
    if not endpoint:
        return ProviderConnectionTestResponse(
            provider_id=provider.id,
            provider_name=provider.name,
            endpoint="",
            probe_url="",
            connected=False,
            status_code=None,
            latency_ms=0,
            message="missing provider endpoint",
        )

    settings_payload = _provider_settings_map(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        provider_ids=[provider.id],
    ).get(provider.id, _default_provider_settings())
    token = (settings_payload.get("access_token") or "").strip()
    auth_mode = (provider.auth_mode or "api_key").strip().lower()
    probe_path = (body.probe_path or "/models").strip()
    if not probe_path.startswith("/"):
        probe_path = f"/{probe_path}"
    probe_url = f"{endpoint.rstrip('/')}{probe_path}"
    timeout_seconds = max(0.2, min(15.0, body.timeout_ms / 1000.0))

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    raw_headers = settings_payload.get("headers_json") or {}
    for key, value in dict(raw_headers).items():
        if key and value is not None:
            headers[str(key)] = str(value)
    if auth_mode in {"api_key", "token", "bearer"} and token:
        headers.setdefault("Authorization", f"Bearer {token}")

    if auth_mode in {"api_key", "token", "bearer"} and not token:
        return ProviderConnectionTestResponse(
            provider_id=provider.id,
            provider_name=provider.name,
            endpoint=endpoint,
            probe_url=probe_url,
            connected=False,
            status_code=None,
            latency_ms=0,
            message="missing provider token for auth mode",
        )

    started = perf_counter()
    request = Request(url=probe_url, method="GET", headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            latency_ms = int((perf_counter() - started) * 1000)
            status_code = int(getattr(response, "status", 0) or 0)
            connected = 200 <= status_code < 300
            message = "connected" if connected else f"unexpected status {status_code}"
            return ProviderConnectionTestResponse(
                provider_id=provider.id,
                provider_name=provider.name,
                endpoint=endpoint,
                probe_url=probe_url,
                connected=connected,
                status_code=status_code,
                latency_ms=latency_ms,
                message=message,
            )
    except HTTPError as exc:
        latency_ms = int((perf_counter() - started) * 1000)
        # 401/403 also prove endpoint is reachable; surface as connected with auth warning.
        reachable = exc.code in {401, 403}
        return ProviderConnectionTestResponse(
            provider_id=provider.id,
            provider_name=provider.name,
            endpoint=endpoint,
            probe_url=probe_url,
            connected=reachable,
            status_code=exc.code,
            latency_ms=latency_ms,
            message=f"http_error:{exc.code}",
        )
    except URLError as exc:
        latency_ms = int((perf_counter() - started) * 1000)
        return ProviderConnectionTestResponse(
            provider_id=provider.id,
            provider_name=provider.name,
            endpoint=endpoint,
            probe_url=probe_url,
            connected=False,
            status_code=None,
            latency_ms=latency_ms,
            message=f"network_error:{exc.reason}",
        )
    except Exception as exc:  # pragma: no cover
        latency_ms = int((perf_counter() - started) * 1000)
        return ProviderConnectionTestResponse(
            provider_id=provider.id,
            provider_name=provider.name,
            endpoint=endpoint,
            probe_url=probe_url,
            connected=False,
            status_code=None,
            latency_ms=latency_ms,
            message=f"probe_error:{str(exc)}",
        )


@router.post("/profiles", response_model=ModelProfileResponse)
def upsert_model_profile(
    body: ModelProfileUpsertRequest,
    db: Session = Depends(get_db),
) -> ModelProfileResponse:
    provider = db.get(ModelProvider, body.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")

    row = db.execute(
        select(ModelProfile).where(
            ModelProfile.tenant_id == body.tenant_id,
            ModelProfile.project_id == body.project_id,
            ModelProfile.purpose == body.purpose,
            ModelProfile.name == body.name,
            ModelProfile.deleted_at.is_(None),
        )
    ).scalars().first()

    if row is None:
        row = ModelProfile(
            id=f"profile_{uuid4().hex}",
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            trace_id=f"tr_profile_{uuid4().hex[:12]}",
            correlation_id=f"cr_profile_{uuid4().hex[:12]}",
            idempotency_key=f"idem_profile_{body.purpose}_{body.name}_{uuid4().hex[:8]}",
            provider_id=body.provider_id,
            purpose=body.purpose,
            name=body.name,
            params_json=_build_model_profile_params(body),
        )
        db.add(row)
    else:
        row.provider_id = body.provider_id
        row.params_json = _build_model_profile_params(body)
    db.commit()
    db.refresh(row)
    return _build_model_profile_response(row)


@router.get("/profiles", response_model=list[ModelProfileResponse])
def list_model_profiles(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    purpose: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ModelProfileResponse]:
    stmt = select(ModelProfile).where(
        ModelProfile.tenant_id == tenant_id,
        ModelProfile.project_id == project_id,
        ModelProfile.deleted_at.is_(None),
    )
    if purpose:
        stmt = stmt.where(ModelProfile.purpose == purpose)
    rows = db.execute(stmt.order_by(ModelProfile.created_at.desc())).scalars().all()
    return [_build_model_profile_response(row) for row in rows]


@router.delete("/profiles/{profile_id}")
def delete_model_profile(
    profile_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    row = db.get(ModelProfile, profile_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="profile not found")
    if row.tenant_id != tenant_id or row.project_id != project_id:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN-002: profile scope mismatch")
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "deleted", "profile_id": profile_id}


@router.put("/stage-routing", response_model=StageRoutingResponse)
def upsert_stage_routing(body: StageRoutingRequest, db: Session = Depends(get_db)) -> StageRoutingResponse:
    stack_name = "stage_router_policy_default"
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == body.tenant_id,
            CreativePolicyStack.project_id == body.project_id,
            CreativePolicyStack.name == stack_name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()

    payload = {
        "type": "stage_routing",
        "routes": body.routes,
        "fallback_chain": body.fallback_chain,
        "feature_routes": body.feature_routes,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if row is None:
        row = CreativePolicyStack(
            id=f"policy_{uuid4().hex}",
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            trace_id=f"tr_route_{uuid4().hex[:12]}",
            correlation_id=f"cr_route_{uuid4().hex[:12]}",
            idempotency_key=f"idem_route_{uuid4().hex[:8]}",
            name=stack_name,
            status="active",
            stack_json=payload,
        )
        db.add(row)
    else:
        row.status = "active"
        row.stack_json = payload
    db.commit()

    return StageRoutingResponse(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        routes=body.routes,
        fallback_chain=body.fallback_chain,
        feature_routes=body.feature_routes,
    )


@router.get("/stage-routing", response_model=StageRoutingResponse)
def get_stage_routing(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> StageRoutingResponse:
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == "stage_router_policy_default",
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        return StageRoutingResponse(
            tenant_id=tenant_id,
            project_id=project_id,
            routes={},
            fallback_chain={},
            feature_routes={},
        )

    payload = row.stack_json or {}
    return StageRoutingResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        routes=payload.get("routes") or {},
        fallback_chain=payload.get("fallback_chain") or {},
        feature_routes=payload.get("feature_routes") or {},
    )


@router.get("/feature-matrix", response_model=FeatureMatrixResponse)
def get_feature_matrix(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> FeatureMatrixResponse:
    providers = db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == tenant_id,
            ModelProvider.project_id == project_id,
            ModelProvider.deleted_at.is_(None),
        )
    ).scalars().all()
    provider_map = {row.id: row for row in providers}
    settings_by_provider = _provider_settings_map(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        provider_ids=[row.id for row in providers],
    )

    profiles = db.execute(
        select(ModelProfile).where(
            ModelProfile.tenant_id == tenant_id,
            ModelProfile.project_id == project_id,
            ModelProfile.deleted_at.is_(None),
        ).order_by(ModelProfile.created_at.desc())
    ).scalars().all()

    feature_descriptions = {
        "text_generation": "SKILL 01/02/03/10/15/16/17 等文本推理与规划",
        "embedding": "SKILL 11/12/22 的向量与检索链路",
        "multimodal": "SKILL 09/10 的图文多模态输入",
        "image_generation": "关键帧/分镜图生成",
        "video_generation": "I2V/V2V 视频生成",
        "tts": "SKILL 05/06 语音合成",
        "stt": "语音识别与字幕辅助",
    }

    items: list[FeatureMatrixItem] = []
    for feature_key, description in feature_descriptions.items():
        options: list[FeatureProfileOption] = []
        for profile in profiles:
            provider = provider_map.get(profile.provider_id)
            if provider is None:
                continue
            settings = settings_by_provider.get(provider.id) or _default_provider_settings()
            if not settings.get("enabled", True):
                continue
            capability_flags = ProviderCapabilitySet.model_validate(settings.get("capability_flags") or {})
            if not _provider_supports_feature(capability_flags, feature_key):
                continue
            options.append(
                FeatureProfileOption(
                    profile_id=profile.id,
                    provider_id=provider.id,
                    provider_name=provider.name,
                    purpose=profile.purpose,
                    model_name=profile.name,
                )
            )
        items.append(FeatureMatrixItem(feature_key=feature_key, description=description, eligible_profiles=options))

    return FeatureMatrixResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        items=items,
    )


_ROLE_PROFILE_PREFIX = "role_profile"
_SKILL_REGISTRY_PREFIX = "skill_registry"
_FEATURE_ROUTE_MAP_PREFIX = "feature_route_map"


def _build_role_profile_response(
    payload: dict,
    *,
    tenant_id: str,
    project_id: str,
    role_id: str,
) -> RoleProfileResponse:
    return RoleProfileResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        role_id=role_id,
        prompt_style=str(payload.get("prompt_style") or ""),
        default_skills=list(payload.get("default_skills") or []),
        default_knowledge_scopes=list(payload.get("default_knowledge_scopes") or []),
        default_model_profile=payload.get("default_model_profile"),
        permissions=RolePermissionSet.model_validate(payload.get("permissions") or {}),
        enabled=bool(payload.get("enabled", True)),
        schema_version=str(payload.get("schema_version") or "1.0"),
        updated_at=payload.get("updated_at"),
    )


def _build_skill_registry_response(
    payload: dict,
    *,
    tenant_id: str,
    project_id: str,
    skill_id: str,
) -> SkillRegistryResponse:
    return SkillRegistryResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        skill_id=skill_id,
        input_schema=dict(payload.get("input_schema") or {}),
        output_schema=dict(payload.get("output_schema") or {}),
        required_knowledge_scopes=list(payload.get("required_knowledge_scopes") or []),
        default_model_profile=payload.get("default_model_profile"),
        tools_required=list(payload.get("tools_required") or []),
        ui_renderer=str(payload.get("ui_renderer") or "form"),
        init_template=payload.get("init_template"),
        enabled=bool(payload.get("enabled", True)),
        schema_version=str(payload.get("schema_version") or "1.0"),
        updated_at=payload.get("updated_at"),
    )


def _build_feature_route_response(
    payload: dict,
    *,
    tenant_id: str,
    project_id: str,
    route_id: str,
) -> FeatureRouteMapResponse:
    return FeatureRouteMapResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        route_id=route_id,
        path=str(payload.get("path") or ""),
        component=str(payload.get("component") or ""),
        feature_id=str(payload.get("feature_id") or ""),
        allowed_roles=list(payload.get("allowed_roles") or []),
        ui_mode=str(payload.get("ui_mode") or "list"),
        depends_on=list(payload.get("depends_on") or []),
        enabled=bool(payload.get("enabled", True)),
        schema_version=str(payload.get("schema_version") or "1.0"),
        updated_at=payload.get("updated_at"),
    )


def _resolve_role_and_skill_profiles(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    role_id: str,
    skill_id: str,
) -> tuple[RoleProfileResponse, SkillRegistryResponse, dict, list[str], list[FeatureRouteMapResponse]]:
    role_payload = _load_config_stack_payload(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        stack_name=_config_stack_name(_ROLE_PROFILE_PREFIX, role_id),
    )
    if role_payload is None:
        raise HTTPException(status_code=404, detail="role profile not found")
    skill_payload = _load_config_stack_payload(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        stack_name=_config_stack_name(_SKILL_REGISTRY_PREFIX, skill_id),
    )
    if skill_payload is None:
        raise HTTPException(status_code=404, detail="skill profile not found")

    role_profile = _build_role_profile_response(
        role_payload,
        tenant_id=tenant_id,
        project_id=project_id,
        role_id=role_id,
    )
    skill_profile = _build_skill_registry_response(
        skill_payload,
        tenant_id=tenant_id,
        project_id=project_id,
        skill_id=skill_id,
    )

    model_profile_id = skill_profile.default_model_profile or role_profile.default_model_profile
    resolved_model_profile: dict = {}
    if model_profile_id:
        model_row = db.get(ModelProfile, model_profile_id)
        if model_row is not None and model_row.deleted_at is None:
            resolved_model_profile = _build_model_profile_response(model_row).model_dump(mode="json")

    resolved_scopes: list[str] = []
    for scope in role_profile.default_knowledge_scopes + skill_profile.required_knowledge_scopes:
        if scope and scope not in resolved_scopes:
            resolved_scopes.append(scope)

    route_rows = _list_config_stacks(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        prefix=_FEATURE_ROUTE_MAP_PREFIX,
    )
    visible_routes: list[FeatureRouteMapResponse] = []
    for row in route_rows:
        item_route_id = row.name.split(":", 1)[1]
        payload = dict(row.stack_json or {})
        allowed_roles = list(payload.get("allowed_roles") or [])
        if allowed_roles and role_id not in allowed_roles:
            continue
        visible_routes.append(
            _build_feature_route_response(
                payload,
                tenant_id=tenant_id,
                project_id=project_id,
                route_id=item_route_id,
            )
        )

    return role_profile, skill_profile, resolved_model_profile, resolved_scopes, visible_routes


def _to_skill_input_dto(skill_id: str, payload: dict):
    match = skill_id.strip().lower()
    pattern = r"^skill_(\d{2})$"

    token_match = re.match(pattern, match)
    if token_match is None:
        return payload
    skill_token = token_match.group(1)
    module_path = f"ainern2d_shared.schemas.skills.skill_{skill_token}"
    class_name = f"Skill{skill_token}Input"
    try:
        module = importlib.import_module(module_path)
    except Exception:
        return payload
    input_cls = getattr(module, class_name, None)
    if input_cls is None or not hasattr(input_cls, "model_validate"):
        return payload
    return input_cls.model_validate(payload)


def _extract_skill_logs(result: object) -> list[dict]:
    logs: list[dict] = []
    event_envelopes = getattr(result, "event_envelopes", None)
    if event_envelopes:
        for item in event_envelopes:
            if hasattr(item, "model_dump"):
                logs.append(item.model_dump(mode="json"))
            elif isinstance(item, dict):
                logs.append(item)
    events = getattr(result, "events_emitted", None)
    if events:
        for event_name in list(events):
            logs.append({"event_type": str(event_name)})
    return logs


def _llm_template_roles() -> list[dict]:
    return [
        {
            "role_id": "director",
            "prompt_style": "以导演视角输出镜头决策，先结论后依据，结构化列风险与下一步。",
            "default_skills": ["skill_03", "skill_10", "shot_planner", "dialogue_director"],
            "default_knowledge_scopes": ["director_basic", "project_novel", "culture_constraints"],
            "permissions": {
                "can_import_data": True,
                "can_publish_task": True,
                "can_edit_global_knowledge": False,
                "can_manage_model_router": False,
            },
        },
        {
            "role_id": "script_supervisor",
            "prompt_style": "以场记视角追踪连续性，输出差异点与修复建议。",
            "default_skills": ["continuity_checker", "asset_consistency_review"],
            "default_knowledge_scopes": ["continuity_rules", "project_novel"],
            "permissions": {
                "can_import_data": True,
                "can_publish_task": False,
                "can_edit_global_knowledge": False,
                "can_manage_model_router": False,
            },
        },
        {
            "role_id": "art",
            "prompt_style": "以美术总监视角输出场景/道具/色板规范。",
            "default_skills": ["art_style_guide", "prop_norms_check"],
            "default_knowledge_scopes": ["art_direction", "culture_constraints"],
            "permissions": {
                "can_import_data": True,
                "can_publish_task": False,
                "can_edit_global_knowledge": False,
                "can_manage_model_router": False,
            },
        },
        {
            "role_id": "lighting",
            "prompt_style": "以灯光指导视角输出布光方案、色温范围与风险。",
            "default_skills": ["lighting_setup", "mood_lighting_balance"],
            "default_knowledge_scopes": ["lighting_baseline", "scene_constraints"],
            "permissions": {
                "can_import_data": True,
                "can_publish_task": False,
                "can_edit_global_knowledge": False,
                "can_manage_model_router": False,
            },
        },
        {
            "role_id": "stunt",
            "prompt_style": "以武术指导视角拆分动作节奏并标记安全边界。",
            "default_skills": ["stunt_breakdown", "action_safety_review"],
            "default_knowledge_scopes": ["stunt_sop", "safety_rules"],
            "permissions": {
                "can_import_data": True,
                "can_publish_task": False,
                "can_edit_global_knowledge": False,
                "can_manage_model_router": False,
            },
        },
        {
            "role_id": "translator",
            "prompt_style": "以本地化译者视角保证术语一致与语气一致。",
            "default_skills": ["translator_zh_en", "subtitle_localization"],
            "default_knowledge_scopes": ["translation_glossary", "culture_constraints"],
            "permissions": {
                "can_import_data": True,
                "can_publish_task": False,
                "can_edit_global_knowledge": False,
                "can_manage_model_router": False,
            },
        },
    ]


def _llm_template_skills() -> list[dict]:
    return [
        {
            "skill_id": "shot_planner",
            "input_schema": {"type": "object", "properties": {"chapter_id": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"shot_plan": {"type": "array"}}},
            "required_knowledge_scopes": ["director_basic", "visual_grammar"],
            "tools_required": ["search", "embedding"],
            "ui_renderer": "timeline",
            "init_template": "director_bootstrap_v1",
        },
        {
            "skill_id": "translator_zh_en",
            "input_schema": {"type": "object", "properties": {"markdown": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"translated_markdown": {"type": "string"}}},
            "required_knowledge_scopes": ["translation_glossary", "culture_constraints"],
            "tools_required": ["search"],
            "ui_renderer": "form",
            "init_template": "translator_bootstrap_v1",
        },
        {
            "skill_id": "lighting_setup",
            "input_schema": {"type": "object", "properties": {"scene_id": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"lighting_plan": {"type": "array"}}},
            "required_knowledge_scopes": ["lighting_baseline"],
            "tools_required": ["search"],
            "ui_renderer": "table",
            "init_template": "lighting_bootstrap_v1",
        },
    ]


def _llm_template_routes() -> list[dict]:
    return [
        {
            "route_id": "route_novel_chapter_workspace",
            "path": "/studio/chapters",
            "component": "StudioChapterManagerPage",
            "feature_id": "chapter_workspace",
            "allowed_roles": ["director", "script_supervisor", "translator"],
            "ui_mode": "editor",
            "depends_on": ["rag", "embedding"],
        },
        {
            "route_id": "route_role_studio",
            "path": "/studio/roles",
            "component": "StudioRoleStudioPage",
            "feature_id": "role_studio",
            "allowed_roles": ["admin", "director"],
            "ui_mode": "config",
            "depends_on": ["rag", "embedding", "worker_hub"],
        },
        {
            "route_id": "route_timeline_patch",
            "path": "/studio/timeline",
            "component": "StudioTimelinePatchPage",
            "feature_id": "timeline_patch",
            "allowed_roles": ["director", "editor", "script_supervisor"],
            "ui_mode": "timeline",
            "depends_on": ["worker_hub", "minio"],
        },
    ]


def _enrich_role_template(role_template: dict, round_index: int) -> dict:
    role_id = str(role_template.get("role_id") or "")
    enriched = dict(role_template)
    scopes = list(enriched.get("default_knowledge_scopes") or [])
    skills = list(enriched.get("default_skills") or [])
    scope_token = f"{role_id}_insight_round_{round_index}"
    skill_token = f"{role_id}_workstep_round_{round_index}"
    if scope_token not in scopes:
        scopes.append(scope_token)
    if skill_token not in skills:
        skills.append(skill_token)
    enriched["default_knowledge_scopes"] = scopes
    enriched["default_skills"] = skills
    base_prompt = str(enriched.get("prompt_style") or "")
    enriched["prompt_style"] = (
        f"{base_prompt} | Round {round_index}: 继续补充行业细则、例外处理和复核清单。"
    ).strip()
    return enriched


async def _broadcast_bootstrap_event(session_id: str | None, payload: dict) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    clients = _BOOTSTRAP_WS_CLIENTS.get(sid)
    if not clients:
        return
    dead_clients: list[WebSocket] = []
    message = dict(payload)
    message.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    for ws in list(clients):
        try:
            await ws.send_json(message)
        except Exception:
            dead_clients.append(ws)
    for dead in dead_clients:
        clients.discard(dead)
    if not clients:
        _BOOTSTRAP_WS_CLIENTS.pop(sid, None)


@router.put("/role-profiles/{role_id}", response_model=RoleProfileResponse)
def upsert_role_profile(
    role_id: str,
    body: RoleProfileUpsertRequest,
    db: Session = Depends(get_db),
) -> RoleProfileResponse:
    if body.role_id != role_id:
        raise HTTPException(status_code=400, detail="role_id mismatch")
    payload = {
        "type": "role_profile",
        "role_id": role_id,
        "prompt_style": body.prompt_style,
        "default_skills": body.default_skills,
        "default_knowledge_scopes": body.default_knowledge_scopes,
        "default_model_profile": body.default_model_profile,
        "permissions": body.permissions.model_dump(mode="json"),
        "enabled": body.enabled,
        "schema_version": body.schema_version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _upsert_config_stack(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        stack_name=_config_stack_name(_ROLE_PROFILE_PREFIX, role_id),
        payload=payload,
        trace_prefix="role_profile",
    )
    db.commit()
    return _build_role_profile_response(
        payload,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        role_id=role_id,
    )


@router.get("/role-profiles", response_model=list[RoleProfileResponse])
def list_role_profiles(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[RoleProfileResponse]:
    rows = _list_config_stacks(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        prefix=_ROLE_PROFILE_PREFIX,
    )
    results: list[RoleProfileResponse] = []
    for row in rows:
        item_role_id = row.name.split(":", 1)[1]
        payload = dict(row.stack_json or {})
        if keyword:
            key = keyword.strip().lower()
            haystacks = [item_role_id.lower(), str(payload.get("prompt_style") or "").lower()]
            if not any(key in item for item in haystacks):
                continue
        results.append(
            _build_role_profile_response(
                payload,
                tenant_id=tenant_id,
                project_id=project_id,
                role_id=item_role_id,
            )
        )
    return results


@router.delete("/role-profiles/{role_id}")
def delete_role_profile(
    role_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    deleted = _delete_config_stack(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        stack_name=_config_stack_name(_ROLE_PROFILE_PREFIX, role_id),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="role profile not found")
    db.commit()
    return {"status": "deleted", "role_id": role_id}


@router.put("/skill-registry/{skill_id}", response_model=SkillRegistryResponse)
def upsert_skill_registry(
    skill_id: str,
    body: SkillRegistryUpsertRequest,
    db: Session = Depends(get_db),
) -> SkillRegistryResponse:
    if body.skill_id != skill_id:
        raise HTTPException(status_code=400, detail="skill_id mismatch")
    payload = {
        "type": "skill_registry",
        "skill_id": skill_id,
        "input_schema": body.input_schema,
        "output_schema": body.output_schema,
        "required_knowledge_scopes": body.required_knowledge_scopes,
        "default_model_profile": body.default_model_profile,
        "tools_required": body.tools_required,
        "ui_renderer": body.ui_renderer,
        "init_template": body.init_template,
        "enabled": body.enabled,
        "schema_version": body.schema_version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _upsert_config_stack(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        stack_name=_config_stack_name(_SKILL_REGISTRY_PREFIX, skill_id),
        payload=payload,
        trace_prefix="skill_registry",
    )
    db.commit()
    return _build_skill_registry_response(
        payload,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        skill_id=skill_id,
    )


@router.get("/skill-registry", response_model=list[SkillRegistryResponse])
def list_skill_registry(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[SkillRegistryResponse]:
    rows = _list_config_stacks(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        prefix=_SKILL_REGISTRY_PREFIX,
    )
    results: list[SkillRegistryResponse] = []
    for row in rows:
        item_skill_id = row.name.split(":", 1)[1]
        payload = dict(row.stack_json or {})
        if keyword:
            key = keyword.strip().lower()
            haystacks = [item_skill_id.lower(), str(payload.get("ui_renderer") or "").lower()]
            if not any(key in item for item in haystacks):
                continue
        results.append(
            _build_skill_registry_response(
                payload,
                tenant_id=tenant_id,
                project_id=project_id,
                skill_id=item_skill_id,
            )
        )
    return results


@router.delete("/skill-registry/{skill_id}")
def delete_skill_registry(
    skill_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    deleted = _delete_config_stack(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        stack_name=_config_stack_name(_SKILL_REGISTRY_PREFIX, skill_id),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="skill profile not found")
    db.commit()
    return {"status": "deleted", "skill_id": skill_id}


@router.put("/feature-route-maps/{route_id}", response_model=FeatureRouteMapResponse)
def upsert_feature_route_map(
    route_id: str,
    body: FeatureRouteMapUpsertRequest,
    db: Session = Depends(get_db),
) -> FeatureRouteMapResponse:
    if body.route_id != route_id:
        raise HTTPException(status_code=400, detail="route_id mismatch")
    payload = {
        "type": "feature_route_map",
        "route_id": route_id,
        "path": body.path,
        "component": body.component,
        "feature_id": body.feature_id,
        "allowed_roles": body.allowed_roles,
        "ui_mode": body.ui_mode,
        "depends_on": body.depends_on,
        "enabled": body.enabled,
        "schema_version": body.schema_version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _upsert_config_stack(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        stack_name=_config_stack_name(_FEATURE_ROUTE_MAP_PREFIX, route_id),
        payload=payload,
        trace_prefix="feature_route",
    )
    db.commit()
    return _build_feature_route_response(
        payload,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        route_id=route_id,
    )


@router.get("/feature-route-maps", response_model=list[FeatureRouteMapResponse])
def list_feature_route_maps(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    role_id: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[FeatureRouteMapResponse]:
    rows = _list_config_stacks(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        prefix=_FEATURE_ROUTE_MAP_PREFIX,
    )
    results: list[FeatureRouteMapResponse] = []
    for row in rows:
        item_route_id = row.name.split(":", 1)[1]
        payload = dict(row.stack_json or {})
        allowed_roles = list(payload.get("allowed_roles") or [])
        if role_id and allowed_roles and role_id not in allowed_roles:
            continue
        if keyword:
            key = keyword.strip().lower()
            haystacks = [
                item_route_id.lower(),
                str(payload.get("path") or "").lower(),
                str(payload.get("feature_id") or "").lower(),
            ]
            if not any(key in item for item in haystacks):
                continue
        results.append(
            _build_feature_route_response(
                payload,
                tenant_id=tenant_id,
                project_id=project_id,
                route_id=item_route_id,
            )
        )
    return results


@router.delete("/feature-route-maps/{route_id}")
def delete_feature_route_map(
    route_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    deleted = _delete_config_stack(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        stack_name=_config_stack_name(_FEATURE_ROUTE_MAP_PREFIX, route_id),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="feature route map not found")
    db.commit()
    return {"status": "deleted", "route_id": route_id}


@router.post("/role-studio/resolve", response_model=RoleStudioResolveResponse)
def resolve_role_studio_runtime(
    body: RoleStudioResolveRequest,
    db: Session = Depends(get_db),
) -> RoleStudioResolveResponse:
    role_profile, skill_profile, resolved_model_profile, resolved_scopes, visible_routes = _resolve_role_and_skill_profiles(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        role_id=body.role_id,
        skill_id=body.skill_id,
    )

    return RoleStudioResolveResponse(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        role_id=body.role_id,
        skill_id=body.skill_id,
        resolved_model_profile=resolved_model_profile,
        resolved_knowledge_scopes=resolved_scopes,
        visible_routes=visible_routes,
        role_profile=role_profile,
        skill_profile=skill_profile,
    )


@router.post("/role-studio/run-skill", response_model=RoleStudioRunSkillResponse)
def run_role_studio_skill(
    body: RoleStudioRunSkillRequest,
    db: Session = Depends(get_db),
) -> RoleStudioRunSkillResponse:
    role_profile, skill_profile, resolved_model_profile, resolved_scopes, _ = _resolve_role_and_skill_profiles(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        role_id=body.role_id,
        skill_id=body.skill_id,
    )
    run_id = body.run_id or f"run_role_studio_{uuid4().hex[:12]}"
    trace_id = body.trace_id or f"tr_role_skill_{uuid4().hex[:12]}"
    correlation_id = body.correlation_id or f"cr_role_skill_{uuid4().hex[:12]}"
    idempotency_key = body.idempotency_key or f"idem_role_skill_{body.skill_id}_{uuid4().hex[:8]}"
    try:
        if SkillRegistry.is_registered(body.skill_id):
            ctx = SkillContext(
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                run_id=run_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                schema_version=body.schema_version,
                extra={
                    "role_id": role_profile.role_id,
                    "resolved_model_profile": resolved_model_profile,
                    "resolved_knowledge_scopes": resolved_scopes,
                    "runtime_context": body.context,
                },
            )
            input_dto = _to_skill_input_dto(body.skill_id, dict(body.input_payload or {}))
            result = SkillRegistry(db).dispatch(body.skill_id, input_dto, ctx)
            if hasattr(result, "model_dump"):
                output = result.model_dump(mode="json")
            elif isinstance(result, dict):
                output = result
            else:
                output = {"result": str(result)}
            logs = _extract_skill_logs(result)
            status = str(getattr(result, "status", "completed"))
            response = RoleStudioRunSkillResponse(
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                role_id=body.role_id,
                skill_id=body.skill_id,
                run_id=run_id,
                execution_mode="skill_registry",
                status=status,
                resolved_model_profile=resolved_model_profile,
                resolved_knowledge_scopes=resolved_scopes,
                output=output,
                logs=logs,
            )
        else:
            output = {
                "message": "skill not registered in backend registry; fallback to configuration simulation",
                "input_echo": body.input_payload,
                "resolved_model_profile": resolved_model_profile,
                "resolved_knowledge_scopes": resolved_scopes,
                "role_prompt_style": role_profile.prompt_style,
                "ui_renderer": skill_profile.ui_renderer,
                "tools_required": skill_profile.tools_required,
            }
            logs = [
                {
                    "event_type": "role.skill.simulated",
                    "producer": "role_studio",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "details": {
                        "role_id": body.role_id,
                        "skill_id": body.skill_id,
                        "reason": "skill_not_registered",
                    },
                }
            ]
            response = RoleStudioRunSkillResponse(
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                role_id=body.role_id,
                skill_id=body.skill_id,
                run_id=run_id,
                execution_mode="simulated",
                status="simulated",
                resolved_model_profile=resolved_model_profile,
                resolved_knowledge_scopes=resolved_scopes,
                output=output,
                logs=logs,
            )

        notify_telegram_event(
            db=db,
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            event_type="role.skill.run.completed",
            summary="Role skill run completed",
            run_id=run_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            extra={
                "role_id": body.role_id,
                "skill_id": body.skill_id,
                "status": response.status,
                "execution_mode": response.execution_mode,
            },
        )
        return response
    except Exception as exc:
        notify_telegram_event(
            db=db,
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            event_type="role.skill.run.failed",
            summary="Role skill run failed",
            run_id=run_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            extra={
                "role_id": body.role_id,
                "skill_id": body.skill_id,
                "error": str(exc),
            },
        )
        raise


def _default_language_settings(tenant_id: str, project_id: str) -> LanguageSettingsResponse:
    defaults = [
        LanguageDefinition(language_code="zh-CN", label="简体中文", locales=["zh-CN"], enabled=True),
        LanguageDefinition(language_code="en-US", label="English", locales=["en-US", "en-GB"], enabled=True),
        LanguageDefinition(language_code="ja-JP", label="日本語", locales=["ja-JP"], enabled=True),
        LanguageDefinition(language_code="ko-KR", label="한국어", locales=["ko-KR"], enabled=True),
        LanguageDefinition(language_code="fr-FR", label="Français", locales=["fr-FR"], enabled=True),
        LanguageDefinition(language_code="de-DE", label="Deutsch", locales=["de-DE"], enabled=True),
        LanguageDefinition(language_code="es-ES", label="Español", locales=["es-ES", "es-MX"], enabled=True),
        LanguageDefinition(language_code="ar-SA", label="العربية", locales=["ar-SA"], direction="rtl", enabled=True),
        LanguageDefinition(language_code="pt-BR", label="Português", locales=["pt-BR", "pt-PT"], enabled=True),
        LanguageDefinition(language_code="ru-RU", label="Русский", locales=["ru-RU"], enabled=True),
        LanguageDefinition(language_code="hi-IN", label="हिन्दी", locales=["hi-IN"], enabled=True),
        LanguageDefinition(language_code="th-TH", label="ไทย", locales=["th-TH"], enabled=True),
    ]
    return LanguageSettingsResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        default_source_language="zh-CN",
        default_target_languages=["en-US"],
        enabled_languages=defaults,
        translation_notes="default language policy",
        glossary={},
        schema_version="1.0",
        updated_at=None,
    )


@router.put("/language-settings", response_model=LanguageSettingsResponse)
def upsert_language_settings(
    body: LanguageSettingsRequest,
    db: Session = Depends(get_db),
) -> LanguageSettingsResponse:
    stack_name = "language_policy_default"
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == body.tenant_id,
            CreativePolicyStack.project_id == body.project_id,
            CreativePolicyStack.name == stack_name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()

    updated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "type": "language_settings",
        "default_source_language": body.default_source_language,
        "default_target_languages": body.default_target_languages,
        "enabled_languages": [item.model_dump(mode="json") for item in body.enabled_languages],
        "translation_notes": body.translation_notes,
        "glossary": body.glossary,
        "schema_version": body.schema_version,
        "updated_at": updated_at,
    }

    if row is None:
        row = CreativePolicyStack(
            id=f"policy_{uuid4().hex}",
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            trace_id=f"tr_lang_{uuid4().hex[:12]}",
            correlation_id=f"cr_lang_{uuid4().hex[:12]}",
            idempotency_key=f"idem_lang_{uuid4().hex[:8]}",
            name=stack_name,
            status="active",
            stack_json=payload,
        )
        db.add(row)
    else:
        row.status = "active"
        row.stack_json = payload
    db.commit()

    return LanguageSettingsResponse(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        default_source_language=body.default_source_language,
        default_target_languages=body.default_target_languages,
        enabled_languages=body.enabled_languages,
        translation_notes=body.translation_notes,
        glossary=body.glossary,
        schema_version=body.schema_version,
        updated_at=updated_at,
    )


@router.get("/language-settings", response_model=LanguageSettingsResponse)
def get_language_settings(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> LanguageSettingsResponse:
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == "language_policy_default",
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        return _default_language_settings(tenant_id=tenant_id, project_id=project_id)

    payload = row.stack_json or {}
    default_settings = _default_language_settings(tenant_id=tenant_id, project_id=project_id)
    enabled_languages_payload = payload.get("enabled_languages") or [
        item.model_dump(mode="json") for item in default_settings.enabled_languages
    ]
    enabled_languages = [LanguageDefinition.model_validate(item) for item in enabled_languages_payload]
    return LanguageSettingsResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        default_source_language=payload.get("default_source_language") or default_settings.default_source_language,
        default_target_languages=payload.get("default_target_languages") or default_settings.default_target_languages,
        enabled_languages=enabled_languages,
        translation_notes=payload.get("translation_notes"),
        glossary=payload.get("glossary") or {},
        schema_version=payload.get("schema_version") or "1.0",
        updated_at=payload.get("updated_at"),
    )


@router.put("/telegram-settings", response_model=TelegramSettingsResponse)
def upsert_telegram_settings(
    body: TelegramSettingsRequest,
    db: Session = Depends(get_db),
) -> TelegramSettingsResponse:
    stack_name = "telegram_notify_default"
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == body.tenant_id,
            CreativePolicyStack.project_id == body.project_id,
            CreativePolicyStack.name == stack_name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()

    updated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "type": "telegram_settings",
        "enabled": body.enabled,
        "bot_token": body.bot_token,
        "chat_id": body.chat_id,
        "thread_id": body.thread_id,
        "parse_mode": body.parse_mode,
        "notify_events": body.notify_events,
        "schema_version": body.schema_version,
        "updated_at": updated_at,
    }

    if row is None:
        row = CreativePolicyStack(
            id=f"policy_{uuid4().hex}",
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            trace_id=f"tr_tg_{uuid4().hex[:12]}",
            correlation_id=f"cr_tg_{uuid4().hex[:12]}",
            idempotency_key=f"idem_tg_{uuid4().hex[:8]}",
            name=stack_name,
            status="active",
            stack_json=payload,
        )
        db.add(row)
    else:
        row.status = "active"
        row.stack_json = payload
    db.commit()

    return TelegramSettingsResponse(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        enabled=body.enabled,
        bot_token_masked=_mask_secret(body.bot_token),
        chat_id=body.chat_id,
        thread_id=body.thread_id,
        parse_mode=body.parse_mode,
        notify_events=body.notify_events,
        schema_version=body.schema_version,
        updated_at=updated_at,
    )


@router.get("/telegram-settings", response_model=TelegramSettingsResponse)
def get_telegram_settings(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> TelegramSettingsResponse:
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == "telegram_notify_default",
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    if row is None:
        return _default_telegram_settings(tenant_id=tenant_id, project_id=project_id)

    payload = row.stack_json or {}
    default_settings = _default_telegram_settings(tenant_id=tenant_id, project_id=project_id)
    return TelegramSettingsResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        enabled=bool(payload.get("enabled", False)),
        bot_token_masked=_mask_secret(payload.get("bot_token")),
        chat_id=payload.get("chat_id"),
        thread_id=payload.get("thread_id"),
        parse_mode=payload.get("parse_mode") or default_settings.parse_mode,
        notify_events=payload.get("notify_events") or default_settings.notify_events,
        schema_version=payload.get("schema_version") or "1.0",
        updated_at=payload.get("updated_at"),
    )


@router.post("/telegram-settings/test", response_model=TelegramSettingsTestResponse)
def test_telegram_settings(
    body: TelegramSettingsTestRequest,
    db: Session = Depends(get_db),
) -> TelegramSettingsTestResponse:
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == body.tenant_id,
            CreativePolicyStack.project_id == body.project_id,
            CreativePolicyStack.name == "telegram_notify_default",
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    payload = dict(row.stack_json or {}) if row is not None else {}

    bot_token = (body.bot_token or payload.get("bot_token") or "").strip()
    chat_id = (body.chat_id or payload.get("chat_id") or "").strip()
    thread_id = (body.thread_id or payload.get("thread_id") or "").strip()
    parse_mode = (body.parse_mode or payload.get("parse_mode") or "Markdown").strip()
    if not bot_token:
        return TelegramSettingsTestResponse(
            delivered=False,
            status_code=None,
            latency_ms=0,
            message="missing bot token",
            telegram_ok=None,
        )
    if not chat_id:
        return TelegramSettingsTestResponse(
            delivered=False,
            status_code=None,
            latency_ms=0,
            message="missing chat id",
            telegram_ok=None,
        )

    text = (body.message_text or "").strip() or (
        f"[Ainer Studio] Telegram test at {datetime.now(timezone.utc).isoformat()} (tenant={body.tenant_id}, project={body.project_id})"
    )
    req_payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if thread_id:
        req_payload["message_thread_id"] = thread_id

    request = Request(
        url=f"https://api.telegram.org/bot{bot_token}/sendMessage",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        data=json.dumps(req_payload).encode("utf-8"),
    )
    timeout_seconds = max(0.5, min(20.0, body.timeout_ms / 1000.0))
    started = perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            latency = int((perf_counter() - started) * 1000)
            status_code = int(getattr(response, "status", 0) or 0)
            parsed = {}
            try:
                parsed = json.loads(response.read().decode("utf-8") or "{}")
            except Exception:
                parsed = {}
            telegram_ok = bool(parsed.get("ok", 200 <= status_code < 300))
            return TelegramSettingsTestResponse(
                delivered=(200 <= status_code < 300) and telegram_ok,
                status_code=status_code,
                latency_ms=latency,
                message="delivered" if telegram_ok else "telegram api returned not-ok",
                telegram_ok=telegram_ok,
            )
    except HTTPError as exc:
        latency = int((perf_counter() - started) * 1000)
        return TelegramSettingsTestResponse(
            delivered=False,
            status_code=exc.code,
            latency_ms=latency,
            message=f"http_error:{exc.code}",
            telegram_ok=False,
        )
    except URLError as exc:
        latency = int((perf_counter() - started) * 1000)
        return TelegramSettingsTestResponse(
            delivered=False,
            status_code=None,
            latency_ms=latency,
            message=f"network_error:{exc.reason}",
            telegram_ok=False,
        )
    except Exception as exc:  # pragma: no cover
        latency = int((perf_counter() - started) * 1000)
        return TelegramSettingsTestResponse(
            delivered=False,
            status_code=None,
            latency_ms=latency,
            message=f"probe_error:{str(exc)}",
            telegram_ok=False,
        )


@router.post("/bootstrap-defaults", response_model=BootstrapDefaultsResponse)
async def bootstrap_defaults(
    body: BootstrapDefaultsRequest,
    db: Session = Depends(get_db),
) -> BootstrapDefaultsResponse:
    target_role_ids = {item.strip().lower() for item in body.role_ids if item.strip()}
    role_templates = _llm_template_roles()
    if target_role_ids:
        role_templates = [
            item for item in role_templates if str(item.get("role_id") or "").strip().lower() in target_role_ids
        ]
    if body.include_roles and not role_templates:
        raise HTTPException(status_code=400, detail="no matching role templates for role_ids")

    skills_templates = _llm_template_skills()
    route_templates = _llm_template_routes()
    await _broadcast_bootstrap_event(
        body.session_id,
        {
            "event": "bootstrap.started",
            "seed_mode": body.seed_mode,
            "role_count": len(role_templates),
            "enrich_rounds": body.enrich_rounds,
            "model_profile_id": body.model_profile_id,
            "engine": "langgraph",
        },
    )
    notify_telegram_event(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        event_type="bootstrap.started",
        summary="Bootstrap started",
        extra={
            "seed_mode": body.seed_mode,
            "role_count": len(role_templates),
            "enrich_rounds": body.enrich_rounds,
        },
    )

    initial_state: BootstrapGraphState = {
        "tenant_id": body.tenant_id,
        "project_id": body.project_id,
        "seed_mode": body.seed_mode,
        "session_id": body.session_id,
        "default_model_profile": body.model_profile_id,
        "enrich_rounds": body.enrich_rounds,
        "include_roles": body.include_roles,
        "include_skills": body.include_skills,
        "include_routes": body.include_routes,
        "include_language_settings": body.include_language_settings,
        "include_stage_routing": body.include_stage_routing,
        "role_templates": role_templates,
        "skills_templates": skills_templates,
        "route_templates": route_templates,
        "roles_upserted": 0,
        "skills_upserted": 0,
        "routes_upserted": 0,
        "language_settings_applied": False,
        "stage_routing_applied": False,
    }

    async def _resolve_model_profile_node(state: BootstrapGraphState) -> dict[str, Any]:
        default_model_profile = state.get("default_model_profile")
        if default_model_profile:
            profile_row = db.execute(
                select(ModelProfile).where(
                    ModelProfile.id == default_model_profile,
                    ModelProfile.tenant_id == state["tenant_id"],
                    ModelProfile.project_id == state["project_id"],
                    ModelProfile.deleted_at.is_(None),
                )
            ).scalars().first()
            if profile_row is None:
                raise HTTPException(status_code=404, detail="model profile not found")
            return {"default_model_profile": profile_row.id}
        default_profile = db.execute(
            select(ModelProfile).where(
                ModelProfile.tenant_id == state["tenant_id"],
                ModelProfile.project_id == state["project_id"],
                ModelProfile.deleted_at.is_(None),
            )
        ).scalars().first()
        if default_profile is None:
            return {"default_model_profile": None}
        return {"default_model_profile": default_profile.id}

    async def _seed_roles_node(state: BootstrapGraphState) -> dict[str, Any]:
        if not bool(state.get("include_roles", False)):
            return {}
        count = int(state.get("roles_upserted") or 0)
        for template in list(state.get("role_templates") or []):
            enriched_template = dict(template)
            for round_index in range(1, int(state.get("enrich_rounds") or 1) + 1):
                enriched_template = _enrich_role_template(enriched_template, round_index)
                await _broadcast_bootstrap_event(
                    state.get("session_id"),
                    {
                        "event": "bootstrap.role.enriching",
                        "role_id": enriched_template["role_id"],
                        "round": round_index,
                    },
                )
            role_id = str(template["role_id"])
            role_payload = {
                "type": "role_profile",
                "role_id": role_id,
                "prompt_style": enriched_template["prompt_style"],
                "default_skills": list(enriched_template.get("default_skills") or []),
                "default_knowledge_scopes": list(enriched_template.get("default_knowledge_scopes") or []),
                "default_model_profile": state.get("default_model_profile"),
                "permissions": dict(enriched_template.get("permissions") or {}),
                "enabled": True,
                "schema_version": "1.0",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _upsert_config_stack(
                db,
                tenant_id=state["tenant_id"],
                project_id=state["project_id"],
                stack_name=_config_stack_name(_ROLE_PROFILE_PREFIX, role_id),
                payload=role_payload,
                trace_prefix="bootstrap_role",
            )
            count += 1
            await _broadcast_bootstrap_event(
                state.get("session_id"),
                {
                    "event": "bootstrap.role.inserted",
                    "role_id": role_id,
                    "default_skills": role_payload["default_skills"],
                    "default_knowledge_scopes": role_payload["default_knowledge_scopes"],
                },
            )
        return {"roles_upserted": count}

    async def _seed_skills_node(state: BootstrapGraphState) -> dict[str, Any]:
        if not bool(state.get("include_skills", False)):
            return {}
        count = int(state.get("skills_upserted") or 0)
        for template in list(state.get("skills_templates") or []):
            skill_id = str(template["skill_id"])
            skill_payload = {
                "type": "skill_registry",
                "skill_id": skill_id,
                "input_schema": dict(template.get("input_schema") or {}),
                "output_schema": dict(template.get("output_schema") or {}),
                "required_knowledge_scopes": list(template.get("required_knowledge_scopes") or []),
                "default_model_profile": state.get("default_model_profile"),
                "tools_required": list(template.get("tools_required") or []),
                "ui_renderer": str(template.get("ui_renderer") or "form"),
                "init_template": template.get("init_template"),
                "enabled": True,
                "schema_version": "1.0",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _upsert_config_stack(
                db,
                tenant_id=state["tenant_id"],
                project_id=state["project_id"],
                stack_name=_config_stack_name(_SKILL_REGISTRY_PREFIX, skill_id),
                payload=skill_payload,
                trace_prefix="bootstrap_skill",
            )
            count += 1
            await _broadcast_bootstrap_event(
                state.get("session_id"),
                {
                    "event": "bootstrap.skill.inserted",
                    "skill_id": skill_id,
                    "ui_renderer": skill_payload["ui_renderer"],
                },
            )
        return {"skills_upserted": count}

    async def _seed_routes_node(state: BootstrapGraphState) -> dict[str, Any]:
        if not bool(state.get("include_routes", False)):
            return {}
        count = int(state.get("routes_upserted") or 0)
        for template in list(state.get("route_templates") or []):
            route_id = str(template["route_id"])
            route_payload = {
                "type": "feature_route_map",
                "route_id": route_id,
                "path": str(template["path"]),
                "component": str(template["component"]),
                "feature_id": str(template["feature_id"]),
                "allowed_roles": list(template.get("allowed_roles") or []),
                "ui_mode": str(template.get("ui_mode") or "list"),
                "depends_on": list(template.get("depends_on") or []),
                "enabled": True,
                "schema_version": "1.0",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _upsert_config_stack(
                db,
                tenant_id=state["tenant_id"],
                project_id=state["project_id"],
                stack_name=_config_stack_name(_FEATURE_ROUTE_MAP_PREFIX, route_id),
                payload=route_payload,
                trace_prefix="bootstrap_route",
            )
            count += 1
            await _broadcast_bootstrap_event(
                state.get("session_id"),
                {
                    "event": "bootstrap.route.inserted",
                    "route_id": route_id,
                    "path": route_payload["path"],
                },
            )
        return {"routes_upserted": count}

    async def _apply_language_node(state: BootstrapGraphState) -> dict[str, Any]:
        if not bool(state.get("include_language_settings", False)):
            return {"language_settings_applied": False}
        defaults = _default_language_settings(tenant_id=state["tenant_id"], project_id=state["project_id"])
        _upsert_config_stack(
            db,
            tenant_id=state["tenant_id"],
            project_id=state["project_id"],
            stack_name="language_policy_default",
            payload={
                "type": "language_settings",
                "default_source_language": defaults.default_source_language,
                "default_target_languages": defaults.default_target_languages,
                "enabled_languages": [item.model_dump(mode="json") for item in defaults.enabled_languages],
                "translation_notes": "bootstrap llm template",
                "glossary": {},
                "schema_version": "1.0",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            trace_prefix="bootstrap_language",
        )
        await _broadcast_bootstrap_event(
            state.get("session_id"),
            {"event": "bootstrap.language.applied"},
        )
        return {"language_settings_applied": True}

    async def _apply_stage_routing_node(state: BootstrapGraphState) -> dict[str, Any]:
        if not bool(state.get("include_stage_routing", False)):
            return {"stage_routing_applied": False}
        _upsert_config_stack(
            db,
            tenant_id=state["tenant_id"],
            project_id=state["project_id"],
            stack_name="stage_router_policy_default",
            payload={
                "type": "stage_routing",
                "routes": {
                    "skill_01": "text_generation",
                    "skill_03": "text_generation",
                    "skill_10": "text_generation",
                    "skill_12": "embedding",
                    "skill_16": "critic",
                },
                "fallback_chain": {
                    "text_generation": ["planner_fallback"],
                    "embedding": ["embedding_fallback"],
                },
                "feature_routes": {
                    "text_generation": state.get("default_model_profile") or "",
                    "embedding": state.get("default_model_profile") or "",
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            trace_prefix="bootstrap_routing",
        )
        await _broadcast_bootstrap_event(
            state.get("session_id"),
            {"event": "bootstrap.routing.applied"},
        )
        return {"stage_routing_applied": True}

    graph = StateGraph(BootstrapGraphState)
    graph.add_node("resolve_model_profile", _resolve_model_profile_node)
    graph.add_node("seed_roles", _seed_roles_node)
    graph.add_node("seed_skills", _seed_skills_node)
    graph.add_node("seed_routes", _seed_routes_node)
    graph.add_node("apply_language", _apply_language_node)
    graph.add_node("apply_stage_routing", _apply_stage_routing_node)
    graph.set_entry_point("resolve_model_profile")
    graph.add_edge("resolve_model_profile", "seed_roles")
    graph.add_edge("seed_roles", "seed_skills")
    graph.add_edge("seed_skills", "seed_routes")
    graph.add_edge("seed_routes", "apply_language")
    graph.add_edge("apply_language", "apply_stage_routing")
    graph.add_edge("apply_stage_routing", END)

    try:
        final_state = await graph.compile().ainvoke(initial_state)
        db.commit()
    except Exception as exc:
        db.rollback()
        await _broadcast_bootstrap_event(
            body.session_id,
            {
                "event": "bootstrap.failed",
                "error": str(exc),
            },
        )
        notify_telegram_event(
            db=db,
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            event_type="bootstrap.failed",
            summary="Bootstrap failed",
            extra={"error": str(exc)},
        )
        raise

    summary = {
        "seed_mode": body.seed_mode,
        "default_model_profile": final_state.get("default_model_profile"),
        "roles_seeded": [item["role_id"] for item in role_templates] if body.include_roles else [],
        "skills_seeded": [item["skill_id"] for item in skills_templates] if body.include_skills else [],
        "routes_seeded": [item["route_id"] for item in route_templates] if body.include_routes else [],
        "enrich_rounds": body.enrich_rounds,
        "orchestration_engine": "langgraph_stategraph",
    }
    await _broadcast_bootstrap_event(
        body.session_id,
        {
            "event": "bootstrap.completed",
            "roles_upserted": int(final_state.get("roles_upserted") or 0),
            "skills_upserted": int(final_state.get("skills_upserted") or 0),
            "routes_upserted": int(final_state.get("routes_upserted") or 0),
            "summary": summary,
        },
    )
    notify_telegram_event(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        event_type="bootstrap.completed",
        summary="Bootstrap completed",
        extra={
            "roles_upserted": int(final_state.get("roles_upserted") or 0),
            "skills_upserted": int(final_state.get("skills_upserted") or 0),
            "routes_upserted": int(final_state.get("routes_upserted") or 0),
            "engine": "langgraph_stategraph",
        },
    )
    return BootstrapDefaultsResponse(
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        seed_mode=body.seed_mode,
        roles_upserted=int(final_state.get("roles_upserted") or 0),
        skills_upserted=int(final_state.get("skills_upserted") or 0),
        routes_upserted=int(final_state.get("routes_upserted") or 0),
        language_settings_applied=bool(final_state.get("language_settings_applied")),
        stage_routing_applied=bool(final_state.get("stage_routing_applied")),
        summary=summary,
    )


@router.websocket("/ws/bootstrap/{session_id}")
async def bootstrap_progress_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    sid = session_id.strip()
    if not sid:
        await websocket.send_json({"event": "error", "message": "missing session id"})
        await websocket.close()
        return
    clients = _BOOTSTRAP_WS_CLIENTS.setdefault(sid, set())
    clients.add(websocket)
    await websocket.send_json({"event": "ws.connected", "session_id": sid})
    try:
        while True:
            # keepalive/read loop; client may send ping
            msg = await websocket.receive_text()
            if msg.strip().lower() == "ping":
                await websocket.send_json({"event": "ws.pong", "session_id": sid})
    except WebSocketDisconnect:
        clients.discard(websocket)
        if not clients:
            _BOOTSTRAP_WS_CLIENTS.pop(sid, None)
    except Exception:
        clients.discard(websocket)
        if not clients:
            _BOOTSTRAP_WS_CLIENTS.pop(sid, None)


@router.get("/health", response_model=ConfigHealthResponse)
def get_config_health(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> ConfigHealthResponse:
    providers = db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == tenant_id,
            ModelProvider.project_id == project_id,
            ModelProvider.deleted_at.is_(None),
        )
    ).scalars().all()
    profiles = db.execute(
        select(ModelProfile).where(
            ModelProfile.tenant_id == tenant_id,
            ModelProfile.project_id == project_id,
            ModelProfile.deleted_at.is_(None),
        )
    ).scalars().all()
    routing = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == "stage_router_policy_default",
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    settings_by_provider = _provider_settings_map(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        provider_ids=[provider.id for provider in providers],
    )

    items: list[ProviderHealthItem] = []
    for provider in providers:
        settings = settings_by_provider.get(provider.id) or _default_provider_settings()
        access_token = settings.get("access_token")
        requires_token = (provider.auth_mode or "").lower() in {"api_key", "token", "bearer"}
        if not provider.endpoint:
            status = "degraded"
            reason = "missing_endpoint"
        elif requires_token and not access_token:
            status = "degraded"
            reason = "missing_token"
        elif not settings.get("enabled", True):
            status = "degraded"
            reason = "provider_disabled"
        else:
            status = "configured"
            reason = "ready"
        items.append(
            ProviderHealthItem(
                provider_id=provider.id,
                provider_name=provider.name,
                status=status,
                reason=reason,
            )
        )

    return ConfigHealthResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        provider_count=len(providers),
        profile_count=len(profiles),
        routing_ready=routing is not None,
        providers=items,
    )
