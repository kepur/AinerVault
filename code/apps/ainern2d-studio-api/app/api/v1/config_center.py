from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.provider_models import ModelProfile, ModelProvider

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/config", tags=["config"])


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
        default_factory=lambda: ["run.failed", "run.succeeded", "job.failed"]
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
        notify_events=["run.failed", "run.succeeded", "job.failed"],
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
    role_payload = _load_config_stack_payload(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        stack_name=_config_stack_name(_ROLE_PROFILE_PREFIX, body.role_id),
    )
    if role_payload is None:
        raise HTTPException(status_code=404, detail="role profile not found")
    skill_payload = _load_config_stack_payload(
        db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        stack_name=_config_stack_name(_SKILL_REGISTRY_PREFIX, body.skill_id),
    )
    if skill_payload is None:
        raise HTTPException(status_code=404, detail="skill profile not found")

    role_profile = _build_role_profile_response(
        role_payload,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        role_id=body.role_id,
    )
    skill_profile = _build_skill_registry_response(
        skill_payload,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        skill_id=body.skill_id,
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
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        prefix=_FEATURE_ROUTE_MAP_PREFIX,
    )
    visible_routes: list[FeatureRouteMapResponse] = []
    for row in route_rows:
        item_route_id = row.name.split(":", 1)[1]
        payload = dict(row.stack_json or {})
        allowed_roles = list(payload.get("allowed_roles") or [])
        if allowed_roles and body.role_id not in allowed_roles:
            continue
        visible_routes.append(
            _build_feature_route_response(
                payload,
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                route_id=item_route_id,
            )
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
