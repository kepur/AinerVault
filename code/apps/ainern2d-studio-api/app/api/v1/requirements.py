from __future__ import annotations

import hashlib
import json
from time import perf_counter
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.ops_bridge_models import OpsProviderReport
from ainern2d_shared.ainer_db_models.provider_models import ModelProfile, ModelProvider, ProviderAdapter, RouteDecision

from app.api.deps import get_db
from app.api.v1.ops_bridge import (
    CAPABILITY_ALIASES,
    CAPABILITY_STANDARDS,
    TIER_ORDER,
    _assign_integration_status,
    _auto_match_provider,
    _build_mapping_summary,
    _collect_feature_keys,
    _ensure_local_provider_from_report,
    _normalize_capability,
    _tier_requirements,
    _utcnow,
)

router = APIRouter(prefix="/api/v1", tags=["requirements"])

_TIER_ALIAS_TO_INTERNAL = {
    "basic": "low",
    "standard": "medium",
    "advanced": "high",
    "low": "low",
    "medium": "medium",
    "high": "high",
}
_INTERNAL_TO_TIER_ALIAS = {
    "low": "basic",
    "medium": "standard",
    "high": "advanced",
    "none": "basic",
}

_DEFAULT_TIER_CONSTRAINTS: dict[str, dict[str, dict[str, Any]]] = {
    "storyboard_t2i": {
        "basic": {"latency_ms_max": 12000, "resolution": "720p", "budget_level": "low"},
        "standard": {"latency_ms_max": 18000, "resolution": "1080p", "budget_level": "medium"},
        "advanced": {"latency_ms_max": 30000, "resolution": "1440p", "budget_level": "high"},
    },
    "video_t2v": {
        "basic": {"duration_s": 4, "fps": 12, "resolution": "720p", "latency_ms_max": 30000},
        "standard": {"duration_s": 6, "fps": 18, "resolution": "1080p", "latency_ms_max": 60000},
        "advanced": {"duration_s": 8, "fps": 24, "resolution": "1440p", "latency_ms_max": 120000},
    },
    "video_i2v": {
        "basic": {"duration_s": 4, "fps": 12, "resolution": "720p", "latency_ms_max": 30000},
        "standard": {"duration_s": 6, "fps": 18, "resolution": "1080p", "latency_ms_max": 60000},
        "advanced": {"duration_s": 8, "fps": 24, "resolution": "1440p", "latency_ms_max": 120000},
    },
    "llm_structured": {
        "basic": {"latency_ms_max": 10000, "budget_level": "low"},
        "standard": {"latency_ms_max": 20000, "budget_level": "medium"},
        "advanced": {"latency_ms_max": 40000, "budget_level": "high"},
    },
    "tts": {
        "basic": {"latency_ms_max": 8000, "duration_s": 15, "budget_level": "low"},
        "standard": {"latency_ms_max": 12000, "duration_s": 30, "budget_level": "medium"},
        "advanced": {"latency_ms_max": 20000, "duration_s": 60, "budget_level": "high"},
    },
    "dialogue_tts": {
        "basic": {"latency_ms_max": 10000, "duration_s": 20, "budget_level": "low"},
        "standard": {"latency_ms_max": 15000, "duration_s": 40, "budget_level": "medium"},
        "advanced": {"latency_ms_max": 24000, "duration_s": 80, "budget_level": "high"},
    },
    "narration_tts": {
        "basic": {"latency_ms_max": 10000, "duration_s": 20, "budget_level": "low"},
        "standard": {"latency_ms_max": 15000, "duration_s": 40, "budget_level": "medium"},
        "advanced": {"latency_ms_max": 24000, "duration_s": 80, "budget_level": "high"},
    },
    "sfx": {
        "basic": {"latency_ms_max": 6000, "duration_s": 6, "budget_level": "low"},
        "standard": {"latency_ms_max": 10000, "duration_s": 12, "budget_level": "medium"},
        "advanced": {"latency_ms_max": 15000, "duration_s": 20, "budget_level": "high"},
    },
    "bgm": {
        "basic": {"latency_ms_max": 6000, "duration_s": 15, "budget_level": "low"},
        "standard": {"latency_ms_max": 10000, "duration_s": 30, "budget_level": "medium"},
        "advanced": {"latency_ms_max": 18000, "duration_s": 60, "budget_level": "high"},
    },
}


class RequirementTierDefinition(BaseModel):
    tier: str
    target_values: dict[str, Any] = Field(default_factory=dict)
    must_support: list[str] = Field(default_factory=list)
    optional_support: list[str] = Field(default_factory=list)


class CapabilityRequirementDefinition(BaseModel):
    capability_type: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    tiers: dict[str, RequirementTierDefinition] = Field(default_factory=dict)


class RequirementTiersResponse(BaseModel):
    schema_version: str = "1.0"
    items: list[CapabilityRequirementDefinition] = Field(default_factory=list)


class RequirementSchemaResponse(BaseModel):
    schema_version: str = "1.0"
    capability_aliases: dict[str, str] = Field(default_factory=dict)
    tier_aliases: dict[str, str] = Field(default_factory=dict)
    requirement_profile_schema: dict[str, Any] = Field(default_factory=dict)
    route_plan_schema: dict[str, Any] = Field(default_factory=dict)
    gap_report_schema: dict[str, Any] = Field(default_factory=dict)


class OpsPlanRequest(BaseModel):
    tenant_id: str
    project_id: str
    capability: str
    tier: str = "basic"
    constraints: dict[str, Any] = Field(default_factory=dict)
    required_features: list[str] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)
    auto_integrate: bool = True
    validate_connectivity: bool = True
    initiated_by: str = "ai"


class IntegrationVersionResponse(BaseModel):
    integration_id: str
    capability_type: str
    tier: str
    provider_key: str
    provider_name: str
    version: int
    status: str
    mapping_status: str
    created_at: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class RoutePlanResponse(BaseModel):
    selected_provider_key: str
    selected_provider_name: str
    selected_report_id: str
    matched_provider_id: str | None = None
    data_endpoint: str | None = None
    selected_template_id: str
    selected_template_version: str = "v1"
    workflow_hash: str
    resolved_params: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, Any] = Field(default_factory=dict)
    fallback_chain: list[dict[str, Any]] = Field(default_factory=list)
    mapping_status: str = "pending"
    mapping_confidence: float | None = None


class GapReportResponse(BaseModel):
    gap_type: str
    summary: str
    missing_features: list[str] = Field(default_factory=list)
    unmet_constraints: dict[str, Any] = Field(default_factory=dict)
    repair_actions: dict[str, Any] = Field(default_factory=dict)
    candidate_summaries: list[dict[str, Any]] = Field(default_factory=list)


class OpsPlanResponse(BaseModel):
    status: str
    capability: str
    tier: str
    requirement_profile: dict[str, Any] = Field(default_factory=dict)
    route_plan: RoutePlanResponse | None = None
    gap_report: GapReportResponse | None = None
    integration: IntegrationVersionResponse | None = None
    candidates_considered: int = 0


class OpsIntegrationListResponse(BaseModel):
    items: list[IntegrationVersionResponse] = Field(default_factory=list)


class OpsIntegrationRollbackRequest(BaseModel):
    tenant_id: str
    project_id: str


class OpsIntegrationRollbackResponse(BaseModel):
    integration: IntegrationVersionResponse
    status: str = "rolled_back"


class RuntimeRouteDecisionResponse(BaseModel):
    decision_id: str
    created_at: str | None = None
    capability_type: str
    provider_key: str | None = None
    provider_name: str | None = None
    profile_name: str | None = None
    integration_id: str | None = None
    mode: str | None = None
    probe_ok: bool | None = None
    probe_detail: str | None = None
    probe_latency_ms: int | None = None
    live_ok: bool | None = None
    live_status_code: int | None = None
    live_latency_ms: int | None = None


class RuntimeCapabilityStatResponse(BaseModel):
    capability_type: str
    total_runs: int = 0
    success_runs: int = 0
    success_rate: float = 0.0
    latest_status: str = "no_runs"
    latest_latency_ms: int | None = None
    latest_provider_name: str | None = None
    latest_at: str | None = None


class RuntimeRouteItemResponse(BaseModel):
    integration_id: str
    capability_type: str
    tier: str
    provider_key: str
    provider_name: str
    version: int
    status: str
    mapping_status: str
    profile_name: str | None = None
    runtime_route_key: str
    feature_route_key: str
    applied_profile_name: str | None = None
    applied_route_profile_name: str | None = None
    route_plan: dict[str, Any] = Field(default_factory=dict)
    requirement_profile: dict[str, Any] = Field(default_factory=dict)
    fallback_chain: list[dict[str, Any]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class RuntimeRoutingViewResponse(BaseModel):
    tenant_id: str
    project_id: str
    stage_routes: dict[str, Any] = Field(default_factory=dict)
    feature_routes: dict[str, Any] = Field(default_factory=dict)
    fallback_chain: dict[str, Any] = Field(default_factory=dict)
    items: list[RuntimeRouteItemResponse] = Field(default_factory=list)
    recent_decisions: list[RuntimeRouteDecisionResponse] = Field(default_factory=list)
    capability_stats: list[RuntimeCapabilityStatResponse] = Field(default_factory=list)


class RuntimeRoutingApplyRequest(BaseModel):
    tenant_id: str
    project_id: str
    integration_id: str


class QuickRunRequest(BaseModel):
    tenant_id: str
    project_id: str
    integration_id: str | None = None
    capability_type: str | None = None
    sample_input: dict[str, Any] = Field(default_factory=dict)
    probe_connectivity: bool = True


class QuickRunResponse(BaseModel):
    mode: str = "probe_preview"
    integration: IntegrationVersionResponse
    runtime_route_key: str
    profile_name: str | None = None
    request_preview: dict[str, Any] = Field(default_factory=dict)
    probe: dict[str, Any] = Field(default_factory=dict)
    live_request: dict[str, Any] = Field(default_factory=dict)
    live_response: dict[str, Any] = Field(default_factory=dict)
    decision_id: str | None = None


class RequirementProfileModel(BaseModel):
    capability: str
    tier: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    required_features: list[str] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)


class RoutePlanModel(BaseModel):
    selected_provider_key: str
    data_endpoint: str | None = None
    selected_template_id: str
    selected_template_version: str = "v1"
    workflow_hash: str
    resolved_params: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, Any] = Field(default_factory=dict)
    fallback_chain: list[dict[str, Any]] = Field(default_factory=list)


class GapReportModel(BaseModel):
    gap_type: str
    details: dict[str, Any] = Field(default_factory=dict)
    repair_actions: dict[str, Any] = Field(default_factory=dict)


class _CandidateScore(BaseModel):
    report_id: str
    score: float
    feature_gaps: list[str] = Field(default_factory=list)
    unmet_constraints: dict[str, Any] = Field(default_factory=dict)
    mapping_summary: dict[str, Any] = Field(default_factory=dict)
    meets_requested_tier: bool = False
    connectivity_status: str = "untested"


def _internal_tier_name(value: str) -> str:
    internal = _TIER_ALIAS_TO_INTERNAL.get(value.strip().lower())
    if internal is None:
        raise HTTPException(status_code=400, detail=f"unsupported tier: {value}")
    return internal


def _tier_constraints(capability_type: str, tier: str) -> dict[str, Any]:
    return dict((_DEFAULT_TIER_CONSTRAINTS.get(capability_type) or {}).get(tier) or {})


def _cumulative_required_features(capability_type: str, internal_tier: str) -> list[str]:
    ordered = ["low", "medium", "high"]
    target_index = ordered.index(internal_tier)
    result: list[str] = []
    for idx in range(target_index + 1):
        for feature in _tier_requirements(capability_type, ordered[idx]):
            if feature not in result:
                result.append(feature)
    return result


def _available_aliases(capability_type: str) -> list[str]:
    return sorted({key for key, value in CAPABILITY_ALIASES.items() if value == capability_type})


def _normalize_resolution_value(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            raise ValueError()
        return int(float(value))
    except Exception:
        return default


def _masked_headers(headers: dict[str, Any]) -> dict[str, str]:
    return {key: ("***" if str(key).lower() == "authorization" else str(value)) for key, value in headers.items()}


def _evaluate_constraints(report: OpsProviderReport, requested: dict[str, Any]) -> dict[str, Any]:
    if not requested:
        return {}
    facts_constraints = dict(report.constraints_json or {})
    facts_health = dict(report.health_json or {})
    unmet: dict[str, Any] = {}

    latency_ms_max = requested.get("latency_ms_max")
    if latency_ms_max is not None:
        actual = facts_health.get("latency_ms")
        if actual is None or float(actual) > float(latency_ms_max):
            unmet["latency_ms_max"] = {"required": latency_ms_max, "actual": actual}

    duration_s = requested.get("duration_s")
    if duration_s is not None:
        actual = facts_constraints.get("max_duration_s") or facts_constraints.get("duration_s_max") or facts_constraints.get("max_duration")
        if actual is None or float(actual) < float(duration_s):
            unmet["duration_s"] = {"required": duration_s, "actual": actual}

    fps = requested.get("fps")
    if fps is not None:
        actual = facts_constraints.get("max_fps") or facts_constraints.get("fps_max") or facts_constraints.get("fps")
        if actual is None or float(actual) < float(fps):
            unmet["fps"] = {"required": fps, "actual": actual}

    resolution = requested.get("resolution")
    if resolution is not None:
        actual = facts_constraints.get("max_resolution") or facts_constraints.get("resolution") or facts_constraints.get("res")
        required_val = _normalize_resolution_value(resolution)
        actual_val = _normalize_resolution_value(actual)
        if required_val is not None and (actual_val is None or actual_val < required_val):
            unmet["resolution"] = {"required": resolution, "actual": actual}

    frames = requested.get("frames")
    if frames is not None:
        actual = facts_constraints.get("max_frames") or facts_constraints.get("frames")
        if actual is None or float(actual) < float(frames):
            unmet["frames"] = {"required": frames, "actual": actual}

    return unmet


def _candidate_connectivity_status(report: OpsProviderReport) -> str:
    if isinstance(report.last_test_result_json, dict):
        status = str(report.last_test_result_json.get("connectivity_status") or "").strip()
        if status:
            return status
    health_status = str((report.health_json or {}).get("status") or "").strip().lower()
    if health_status in {"up", "healthy", "ok"}:
        return "connected"
    return "untested"


def _build_requirement_profile(payload: OpsPlanRequest, capability_type: str, external_tier: str, internal_tier: str) -> dict[str, Any]:
    merged_constraints = _tier_constraints(capability_type, external_tier)
    merged_constraints.update(dict(payload.constraints or {}))
    required_features = _cumulative_required_features(capability_type, internal_tier)
    for feature in payload.required_features:
        if feature not in required_features:
            required_features.append(feature)
    return RequirementProfileModel(
        capability=capability_type,
        tier=external_tier,
        constraints=merged_constraints,
        required_features=required_features,
        preferences=dict(payload.preferences or {}),
    ).model_dump()


def _score_candidate(report: OpsProviderReport, requirement_profile: dict[str, Any]) -> _CandidateScore:
    capability_type = requirement_profile["capability"]
    internal_tier = _internal_tier_name(requirement_profile["tier"])
    required_features = list(requirement_profile.get("required_features") or [])
    feature_keys = _collect_feature_keys(report.features_json or {})
    feature_gaps = [feature for feature in required_features if feature not in feature_keys]
    unmet_constraints = _evaluate_constraints(report, dict(requirement_profile.get("constraints") or {}))
    mapping_summary = _build_mapping_summary(
        capability_type=capability_type,
        features=dict(report.features_json or {}),
        adapter_spec=dict(report.adapter_spec_json or {}),
        openapi_url=report.openapi_url,
        fetch_openapi=True,
    )
    meets_requested_tier = TIER_ORDER.get(report.capability_tier or "none", 0) >= TIER_ORDER.get(internal_tier, 0)
    connectivity_status = _candidate_connectivity_status(report)

    score = 0.0
    score += 40.0 if meets_requested_tier else 0.0
    score += 15.0 if connectivity_status == "connected" else 0.0
    score += 10.0 if report.matched_provider_id else 0.0
    score += float(mapping_summary.get("confidence") or 0.0) * 30.0
    score -= float(len(feature_gaps) * 12)
    score -= float(len(unmet_constraints) * 10)

    return _CandidateScore(
        report_id=report.id,
        score=score,
        feature_gaps=feature_gaps,
        unmet_constraints=unmet_constraints,
        mapping_summary=mapping_summary,
        meets_requested_tier=meets_requested_tier,
        connectivity_status=connectivity_status,
    )


def _template_metadata(report: OpsProviderReport, capability_type: str, external_tier: str) -> tuple[str, str]:
    raw_payload = dict(report.raw_payload_json or {})
    metadata = dict(raw_payload.get("metadata") or {}) if isinstance(raw_payload.get("metadata"), dict) else {}
    template_id = str(metadata.get("template_id") or f"auto::{capability_type}::{external_tier}")
    template_version = str(metadata.get("template_version") or metadata.get("version") or "v1")
    return template_id, template_version


def _build_route_plan(report: OpsProviderReport, candidate: _CandidateScore, requirement_profile: dict[str, Any], fallback_chain: list[dict[str, Any]]) -> dict[str, Any]:
    template_id, template_version = _template_metadata(report, requirement_profile["capability"], requirement_profile["tier"])
    bindings = {
        "request": dict(candidate.mapping_summary.get("request_mapping") or {}),
        "response": dict(candidate.mapping_summary.get("response_mapping") or {}),
    }
    resolved_params = {
        "constraints": dict(requirement_profile.get("constraints") or {}),
        "preferences": dict(requirement_profile.get("preferences") or {}),
        "provider_constraints": dict(report.constraints_json or {}),
    }
    workflow_hash = hashlib.sha256(
        f"{report.provider_key}|{requirement_profile['capability']}|{requirement_profile['tier']}|{template_id}|{bindings}".encode("utf-8")
    ).hexdigest()[:16]
    return RoutePlanModel(
        selected_provider_key=report.provider_key,
        data_endpoint=report.endpoint_base_url,
        selected_template_id=template_id,
        selected_template_version=template_version,
        workflow_hash=workflow_hash,
        resolved_params=resolved_params,
        bindings=bindings,
        fallback_chain=fallback_chain,
    ).model_dump()


def _build_gap_report(capability_type: str, requirement_profile: dict[str, Any], ranked: list[tuple[OpsProviderReport, _CandidateScore]]) -> dict[str, Any]:
    top_candidates = ranked[:3]
    missing_features: list[str] = []
    unmet_constraints: dict[str, Any] = {}
    summaries: list[dict[str, Any]] = []
    for report, item in top_candidates:
        for feature in item.feature_gaps:
            if feature not in missing_features:
                missing_features.append(feature)
        for key, value in item.unmet_constraints.items():
            unmet_constraints.setdefault(key, value)
        summaries.append(
            {
                "provider_key": report.provider_key,
                "provider_name": report.provider_name,
                "capability_tier": report.capability_tier,
                "mapping_status": item.mapping_summary.get("status"),
                "feature_gaps": item.feature_gaps,
                "unmet_constraints": item.unmet_constraints,
                "connectivity_status": item.connectivity_status,
            }
        )

    gap_type = "template_missing"
    if missing_features:
        gap_type = "feature_missing"
    elif unmet_constraints:
        gap_type = "constraint_unmet"
    elif not ranked:
        gap_type = "provider_missing"

    return GapReportModel(
        gap_type=gap_type,
        details={
            "capability": capability_type,
            "tier": requirement_profile["tier"],
            "missing_features": missing_features,
            "unmet_constraints": unmet_constraints,
            "candidate_summaries": summaries,
        },
        repair_actions={
            "auto_possible": bool(ranked),
            "suggested_jobs": [
                "refresh_ops_facts",
                "request_provider_auto_bind",
                "generate_candidate_template",
            ],
            "manual_needed": [
                "add_or_upgrade provider/template assets in AinerOps",
                "补充 openapi/detail_doc 以提升自动映射准确率",
            ],
        },
    ).model_dump()


def _integration_stack_name(capability_type: str, tier: str, provider_key: str, version: int) -> str:
    return f"ops_integration:{capability_type}:{tier}:{provider_key}:v{version}"


def _runtime_route_key(capability_type: str) -> str:
    return f"route_ops_{capability_type}"


def _feature_route_key(capability_type: str) -> str:
    return capability_type


def _load_integration_rows(db: Session, tenant_id: str, project_id: str) -> list[CreativePolicyStack]:
    rows = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().all()
    return [row for row in rows if isinstance(row.stack_json, dict) and row.stack_json.get("type") == "ops_integration"]


def _build_integration_response(row: CreativePolicyStack) -> IntegrationVersionResponse:
    payload = dict(row.stack_json or {})
    return IntegrationVersionResponse(
        integration_id=row.id,
        capability_type=str(payload.get("capability_type") or ""),
        tier=str(payload.get("tier") or "basic"),
        provider_key=str(payload.get("provider_key") or ""),
        provider_name=str(payload.get("provider_name") or payload.get("provider_key") or ""),
        version=int(payload.get("version") or 1),
        status=row.status,
        mapping_status=str(payload.get("mapping_status") or "pending"),
        created_at=row.created_at.isoformat() if row.created_at else None,
        evidence=dict(payload.get("evidence") or {}),
    )


def _load_stage_routing_row(db: Session, tenant_id: str, project_id: str) -> CreativePolicyStack | None:
    return db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == "stage_router_policy_default",
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()


def _load_stage_routing_payload(db: Session, tenant_id: str, project_id: str) -> dict[str, Any]:
    row = _load_stage_routing_row(db, tenant_id, project_id)
    if row is None:
        return {"routes": {}, "feature_routes": {}, "fallback_chain": {}}
    payload = dict(row.stack_json or {})
    return {
        "routes": dict(payload.get("routes") or {}),
        "feature_routes": dict(payload.get("feature_routes") or {}),
        "fallback_chain": dict(payload.get("fallback_chain") or {}),
    }


def _find_profile_name_by_integration(db: Session, tenant_id: str, project_id: str, integration_id: str) -> str | None:
    rows = db.execute(
        select(ModelProfile).where(
            ModelProfile.tenant_id == tenant_id,
            ModelProfile.project_id == project_id,
            ModelProfile.deleted_at.is_(None),
        )
    ).scalars().all()
    for row in rows:
        params = dict(row.params_json or {})
        if str(params.get("integration_id") or "") == integration_id:
            return row.name
    return None


def _find_profile_by_integration(db: Session, tenant_id: str, project_id: str, integration_id: str) -> ModelProfile | None:
    rows = db.execute(
        select(ModelProfile).where(
            ModelProfile.tenant_id == tenant_id,
            ModelProfile.project_id == project_id,
            ModelProfile.deleted_at.is_(None),
        )
    ).scalars().all()
    for row in rows:
        params = dict(row.params_json or {})
        if str(params.get("integration_id") or "") == integration_id:
            return row
    return None


def _provider_settings_payload(db: Session, tenant_id: str, project_id: str, provider_id: str) -> dict[str, Any]:
    stack_name = f"provider_settings:{provider_id}"
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == stack_name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()
    return dict(row.stack_json or {}) if row else {}


def _latest_runtime_integration_row(
    db: Session,
    tenant_id: str,
    project_id: str,
    capability_type: str | None = None,
    integration_id: str | None = None,
) -> CreativePolicyStack | None:
    rows = _load_integration_rows(db, tenant_id, project_id)
    if integration_id:
        return next((row for row in rows if row.id == integration_id), None)
    target_capability = _normalize_capability(capability_type) if capability_type else None
    candidates = []
    for row in rows:
        payload = dict(row.stack_json or {})
        if target_capability and str(payload.get("capability_type") or "") != target_capability:
            continue
        candidates.append(row)
    candidates.sort(key=lambda row: (0 if row.status == "active" else 1, -(int((row.stack_json or {}).get("version") or 0))))
    return candidates[0] if candidates else None


def _build_runtime_routing_view(db: Session, tenant_id: str, project_id: str) -> RuntimeRoutingViewResponse:
    stage = _load_stage_routing_payload(db, tenant_id, project_id)
    items: list[RuntimeRouteItemResponse] = []
    for row in _load_integration_rows(db, tenant_id, project_id):
        payload = dict(row.stack_json or {})
        capability_type = str(payload.get("capability_type") or "")
        route_plan = dict(payload.get("route_plan") or {})
        feature_key = _feature_route_key(capability_type)
        runtime_key = _runtime_route_key(capability_type)
        profile_name = _find_profile_name_by_integration(db, tenant_id, project_id, row.id)
        items.append(
            RuntimeRouteItemResponse(
                integration_id=row.id,
                capability_type=capability_type,
                tier=str(payload.get("tier") or "basic"),
                provider_key=str(payload.get("provider_key") or ""),
                provider_name=str(payload.get("provider_name") or payload.get("provider_key") or ""),
                version=int(payload.get("version") or 1),
                status=row.status,
                mapping_status=str(payload.get("mapping_status") or "pending"),
                profile_name=profile_name,
                runtime_route_key=runtime_key,
                feature_route_key=feature_key,
                applied_profile_name=str(stage["feature_routes"].get(feature_key) or "") or None,
                applied_route_profile_name=str(stage["routes"].get(runtime_key) or "") or None,
                route_plan=route_plan,
                requirement_profile=dict(payload.get("requirement_profile") or {}),
                fallback_chain=list(route_plan.get("fallback_chain") or []),
                evidence=dict(payload.get("evidence") or {}),
                created_at=row.created_at.isoformat() if row.created_at else None,
            )
        )
    items.sort(key=lambda item: ((0 if item.status == "active" else 1), -item.version, item.capability_type))

    capability_stats_seed: dict[str, dict[str, Any]] = {
        item.capability_type: {
            "capability_type": item.capability_type,
            "total_runs": 0,
            "success_runs": 0,
            "success_rate": 0.0,
            "latest_status": "no_runs",
            "latest_latency_ms": None,
            "latest_provider_name": None,
            "latest_at": None,
        }
        for item in items
    }

    decisions = db.execute(
        select(RouteDecision).where(
            RouteDecision.tenant_id == tenant_id,
            RouteDecision.project_id == project_id,
            RouteDecision.deleted_at.is_(None),
        ).order_by(RouteDecision.created_at.desc())
    ).scalars().all()[:50]
    recent_decisions = []
    for row in decisions:
        payload = dict(row.decision_json or {})
        capability_type = str(payload.get("capability_type") or "")
        quick_run_success = payload.get("quick_run_success")
        quick_run_latency_ms = payload.get("quick_run_latency_ms")
        if capability_type:
            stat = capability_stats_seed.setdefault(
                capability_type,
                {
                    "capability_type": capability_type,
                    "total_runs": 0,
                    "success_runs": 0,
                    "success_rate": 0.0,
                    "latest_status": "no_runs",
                    "latest_latency_ms": None,
                    "latest_provider_name": None,
                    "latest_at": None,
                },
            )
            if payload.get("type") == "ops_quick_run":
                stat["total_runs"] += 1
                if bool(quick_run_success):
                    stat["success_runs"] += 1
                if stat["latest_at"] is None:
                    stat["latest_at"] = row.created_at.isoformat() if row.created_at else None
                    stat["latest_status"] = "success" if bool(quick_run_success) else "failed"
                    stat["latest_latency_ms"] = quick_run_latency_ms if isinstance(quick_run_latency_ms, int) else None
                    stat["latest_provider_name"] = payload.get("provider_name") or payload.get("provider_key")
        recent_decisions.append(
            RuntimeRouteDecisionResponse(
                decision_id=row.id,
                created_at=row.created_at.isoformat() if row.created_at else None,
                capability_type=capability_type,
                provider_key=payload.get("provider_key"),
                provider_name=payload.get("provider_name"),
                profile_name=payload.get("profile_name"),
                integration_id=payload.get("integration_id"),
                mode=payload.get("mode"),
                probe_ok=payload.get("probe_ok"),
                probe_detail=payload.get("probe_detail"),
                probe_latency_ms=payload.get("probe_latency_ms"),
                live_ok=payload.get("live_ok"),
                live_status_code=payload.get("live_status_code"),
                live_latency_ms=payload.get("live_latency_ms"),
            )
        )
    capability_stats = []
    for item in capability_stats_seed.values():
        total_runs = int(item.get("total_runs") or 0)
        success_runs = int(item.get("success_runs") or 0)
        item["success_rate"] = round((success_runs / total_runs) * 100, 1) if total_runs else 0.0
        capability_stats.append(RuntimeCapabilityStatResponse(**item))
    capability_stats.sort(key=lambda item: item.capability_type)
    return RuntimeRoutingViewResponse(
        tenant_id=tenant_id,
        project_id=project_id,
        stage_routes=stage["routes"],
        feature_routes=stage["feature_routes"],
        fallback_chain=stage["fallback_chain"],
        items=items,
        recent_decisions=recent_decisions[:10],
        capability_stats=capability_stats,
    )


def _probe_runtime_endpoint(base_url: str | None) -> dict[str, Any]:
    if not base_url:
        return {"ok": False, "detail": "missing endpoint", "checked_url": None, "latency_ms": None}
    candidates: list[str] = []
    base = str(base_url).strip().rstrip("/")
    if not base:
        return {"ok": False, "detail": "missing endpoint", "checked_url": None, "latency_ms": None}
    candidates.append(base)
    if not base.endswith("/healthz"):
        candidates.append(f"{base}/healthz")
    if not base.endswith("/health"):
        candidates.append(f"{base}/health")
    last_error = "all probes failed"
    checked_url: str | None = None
    latency_ms: int | None = None
    for candidate in candidates:
        try:
            start = perf_counter()
            req = urllib_request.Request(candidate, method="GET")
            with urllib_request.urlopen(req, timeout=6.0) as resp:
                status_code = int(getattr(resp, "status", 200))
            latency_ms = int((perf_counter() - start) * 1000)
            checked_url = candidate
            if status_code < 500:
                return {
                    "ok": True,
                    "detail": f"HTTP {status_code}",
                    "checked_url": candidate,
                    "latency_ms": latency_ms,
                    "status": "connected",
                }
            last_error = f"HTTP {status_code}"
        except urllib_error.HTTPError as exc:
            checked_url = candidate
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            checked_url = candidate
            last_error = str(exc)
    return {
        "ok": False,
        "detail": last_error,
        "checked_url": checked_url,
        "latency_ms": latency_ms,
        "status": "disconnected",
    }


def _openai_like_url(base_url: str | None, path: str) -> str | None:
    if not base_url:
        return None
    base = str(base_url).strip().rstrip("/")
    if not base:
        return None
    if not path.startswith("/"):
        path = f"/{path}"
    if base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return f"{base}{path}"


def _quick_run_request_payload(capability_type: str, sample_input: dict[str, Any], model_name: str | None) -> tuple[str, dict[str, Any]]:
    prompt = str(sample_input.get("prompt") or sample_input.get("text") or "Quick run ping")
    if capability_type == "llm_structured":
        return "/v1/chat/completions", {
            "model": model_name or "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 64,
            "temperature": 0.2,
        }
    if capability_type == "storyboard_t2i":
        return "/v1/images/generations", {
            "model": model_name or "gpt-image-1",
            "prompt": prompt,
            "size": str(sample_input.get("size") or "1024x1024"),
        }
    if capability_type in {"tts", "dialogue_tts", "narration_tts"}:
        return "/v1/audio/speech", {
            "model": model_name or "tts-1",
            "input": str(sample_input.get("text") or prompt),
            "voice": str(sample_input.get("voice") or "alloy"),
            "format": str(sample_input.get("format") or "mp3"),
        }
    return "", {}


def _quick_run_request_candidates(capability_type: str, sample_input: dict[str, Any], model_name: str | None) -> list[tuple[str, dict[str, Any]]]:
    default_path, default_payload = _quick_run_request_payload(capability_type, sample_input, model_name)
    if default_path and default_payload:
        return [(default_path, default_payload)]

    prompt = str(sample_input.get("prompt") or sample_input.get("text") or "Quick run ping")
    duration_s = _to_int(sample_input.get("duration") or sample_input.get("duration_s"), 4)
    fps = _to_int(sample_input.get("fps"), 12)
    resolution = str(sample_input.get("resolution") or "720p")
    output_format = str(sample_input.get("format") or ("mp4" if capability_type.startswith("video_") else "mp3"))

    if capability_type in {"video_t2v", "video_i2v"}:
        canonical_payload: dict[str, Any] = {
            "model": model_name or "video-model-1",
            "prompt": prompt,
            "duration": duration_s,
            "duration_s": duration_s,
            "duration_ms": duration_s * 1000,
            "fps": fps,
            "resolution": resolution,
            "format": output_format,
            "scene": sample_input.get("scene"),
            "seed": sample_input.get("seed"),
        }
        image_url = sample_input.get("image_url") or sample_input.get("imageUrl")
        if capability_type == "video_i2v" and image_url:
            canonical_payload["image_url"] = str(image_url)
            canonical_payload["image"] = str(image_url)
        for key, value in sample_input.items():
            if key not in canonical_payload and value is not None:
                canonical_payload[key] = value
        return [
            ("/v1/videos/generations", dict(canonical_payload)),
            ("/v1/video/generations", dict(canonical_payload)),
            ("/v1/video/generate", dict(canonical_payload)),
            ("/generate", {"capability_type": capability_type, **dict(canonical_payload)}),
        ]

    if capability_type in {"sfx", "bgm"}:
        canonical_payload = {
            "model": model_name or ("audio-gen-1" if capability_type == "sfx" else "music-gen-1"),
            "prompt": prompt,
            "duration": duration_s,
            "duration_s": duration_s,
            "duration_ms": duration_s * 1000,
            "format": output_format,
            "audio_type": capability_type,
            "text": str(sample_input.get("text") or ""),
        }
        for key, value in sample_input.items():
            if key not in canonical_payload and value is not None:
                canonical_payload[key] = value
        candidates = [
            ("/v1/audio/generations", dict(canonical_payload)),
            ("/v1/audio/generate", dict(canonical_payload)),
        ]
        if capability_type == "bgm":
            candidates.insert(0, ("/v1/music/generations", dict(canonical_payload)))
        else:
            candidates.insert(0, ("/v1/sound-effects/generations", dict(canonical_payload)))
        candidates.append(("/generate", {"capability_type": capability_type, **dict(canonical_payload)}))
        return candidates

    return []


def _quick_run_live_request(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    integration_id: str,
    capability_type: str,
    sample_input: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    profile = _find_profile_by_integration(db, tenant_id, project_id, integration_id)
    if profile is None:
        return "probe_preview", {}, {"ok": False, "detail": "profile not found"}
    provider = db.get(ModelProvider, profile.provider_id)
    if provider is None or not provider.endpoint:
        return "probe_preview", {}, {"ok": False, "detail": "provider endpoint missing"}

    settings = _provider_settings_payload(db, tenant_id, project_id, provider.id)
    token = str(settings.get("access_token") or "").strip()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    for key, value in dict(settings.get("headers_json") or {}).items():
        if key and value is not None:
            headers[str(key)] = str(value)
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")

    model_catalog = list(settings.get("model_catalog") or [])
    candidates = _quick_run_request_candidates(capability_type, sample_input, model_catalog[0] if model_catalog else None)
    if not candidates:
        return "probe_preview", {}, {"ok": False, "detail": f"capability {capability_type} 暂不支持真实 quick-run"}

    last_preview: dict[str, Any] = {}
    last_response: dict[str, Any] = {"ok": False, "detail": "all quick-run candidates failed"}
    for path, payload in candidates:
        url = _openai_like_url(provider.endpoint, path) if path else None
        if not url or not payload:
            continue
        body = json.dumps(payload).encode("utf-8")
        request_preview = {
            "url": url,
            "headers": _masked_headers(headers),
            "payload": payload,
        }
        last_preview = request_preview
        try:
            started = perf_counter()
            req = urllib_request.Request(url, data=body, headers=headers, method="POST")
            with urllib_request.urlopen(req, timeout=20.0) as resp:
                latency_ms = int((perf_counter() - started) * 1000)
                raw_text = resp.read().decode("utf-8", errors="replace")
                parsed: Any
                try:
                    parsed = json.loads(raw_text)
                except Exception:
                    parsed = raw_text[:1000]
                return "live_request", request_preview, {
                    "ok": True,
                    "status_code": int(getattr(resp, "status", 200)),
                    "latency_ms": latency_ms,
                    "body": parsed,
                }
        except urllib_error.HTTPError as exc:
            detail_text = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
            last_response = {
                "ok": False,
                "status_code": exc.code,
                "detail": detail_text[:1000],
            }
            if exc.code in {404, 405}:
                continue
            return "live_request", request_preview, last_response
        except Exception as exc:
            last_response = {"ok": False, "detail": str(exc)}
            if "timed out" in str(exc).lower():
                return "live_request", request_preview, last_response
    return "live_request", last_preview, last_response


def _upsert_adapter_and_profile(
    db: Session,
    *,
    report: OpsProviderReport,
    capability_type: str,
    tier: str,
    route_plan: dict[str, Any],
    requirement_profile: dict[str, Any],
    mapping_summary: dict[str, Any],
    integration_id: str,
    version: int,
) -> str | None:
    provider_id = report.matched_provider_id
    if not provider_id:
        provider = _auto_match_provider(
            db=db,
            tenant_id=report.tenant_id,
            project_id=report.project_id,
            provider_name=report.provider_name,
            endpoint_base_url=report.endpoint_base_url,
        )
        if provider is None:
            provider = _ensure_local_provider_from_report(
                db=db,
                tenant_id=report.tenant_id,
                project_id=report.project_id,
                provider_key=report.provider_key,
                provider_name=report.provider_name,
                endpoint_base_url=report.endpoint_base_url,
                capability_type=report.capability_type,
                protocol=report.protocol or "ainer-unified",
            )
        provider_id = provider.id if provider else None
        report.matched_provider_id = provider_id
    if not provider_id:
        return None

    adapter = db.execute(
        select(ProviderAdapter).where(
            ProviderAdapter.tenant_id == report.tenant_id,
            ProviderAdapter.project_id == report.project_id,
            ProviderAdapter.provider_id == provider_id,
            ProviderAdapter.feature == capability_type,
        )
    ).scalars().first()
    if adapter is None:
        adapter = ProviderAdapter(
            id=f"adapter_{uuid4().hex}",
            tenant_id=report.tenant_id,
            project_id=report.project_id,
            trace_id=f"tr_adapter_{uuid4().hex[:12]}",
            correlation_id=f"cr_adapter_{uuid4().hex[:12]}",
            idempotency_key=f"idem_adapter_{provider_id}_{capability_type}",
            provider_id=provider_id,
            feature=capability_type,
            created_by="ops-auto-integration",
            updated_by="ops-auto-integration",
        )
        db.add(adapter)
        db.flush()
    adapter.endpoint_json = {
        "data_endpoint": route_plan.get("data_endpoint"),
        "protocol": report.protocol,
    }
    adapter.request_json = {
        "requirement_profile": requirement_profile,
        "bindings": route_plan.get("bindings") or {},
    }
    adapter.response_json = {
        "mapping_summary": mapping_summary,
        "fallback_chain": route_plan.get("fallback_chain") or [],
    }
    adapter.version = f"v{version}"
    adapter.updated_by = "ops-auto-integration"

    profile_name = f"{tier}_{report.provider_key}"[:120]
    profile = db.execute(
        select(ModelProfile).where(
            ModelProfile.tenant_id == report.tenant_id,
            ModelProfile.project_id == report.project_id,
            ModelProfile.purpose == f"ops_{capability_type}",
            ModelProfile.name == profile_name,
        )
    ).scalars().first()
    if profile is None:
        profile = ModelProfile(
            id=f"profile_{uuid4().hex}",
            tenant_id=report.tenant_id,
            project_id=report.project_id,
            trace_id=f"tr_profile_{uuid4().hex[:12]}",
            correlation_id=f"cr_profile_{uuid4().hex[:12]}",
            idempotency_key=f"idem_profile_{provider_id}_{capability_type}_{tier}",
            provider_id=provider_id,
            adapter_id=adapter.id,
            purpose=f"ops_{capability_type}",
            name=profile_name,
            created_by="ops-auto-integration",
            updated_by="ops-auto-integration",
        )
        db.add(profile)
        db.flush()
    profile.adapter_id = adapter.id
    profile.params_json = {
        "tier": tier,
        "integration_id": integration_id,
        "route_plan": route_plan,
        "requirement_profile": requirement_profile,
    }
    profile.updated_by = "ops-auto-integration"
    report.matched_profile_id = profile.id
    return profile.id


def _persist_integration(
    db: Session,
    *,
    report: OpsProviderReport,
    candidate: _CandidateScore,
    capability_type: str,
    tier: str,
    requirement_profile: dict[str, Any],
    route_plan: dict[str, Any],
    validation: dict[str, Any],
    initiated_by: str,
) -> CreativePolicyStack:
    existing_rows = [
        row for row in _load_integration_rows(db, report.tenant_id, report.project_id)
        if str((row.stack_json or {}).get("capability_type") or "") == capability_type
        and str((row.stack_json or {}).get("tier") or "") == tier
    ]
    next_version = max([int((row.stack_json or {}).get("version") or 0) for row in existing_rows] or [0]) + 1
    for row in existing_rows:
        if row.status == "active":
            row.status = "archived"
            row.updated_by = "ops-auto-integration"
    stack = CreativePolicyStack(
        id=f"policy_{uuid4().hex}",
        tenant_id=report.tenant_id,
        project_id=report.project_id,
        trace_id=f"tr_ops_plan_{uuid4().hex[:12]}",
        correlation_id=f"cr_ops_plan_{uuid4().hex[:12]}",
        idempotency_key=f"idem_ops_plan_{capability_type}_{tier}_{next_version}",
        name=_integration_stack_name(capability_type, tier, report.provider_key, next_version),
        status="active",
        stack_json={
            "type": "ops_integration",
            "capability_type": capability_type,
            "tier": tier,
            "provider_key": report.provider_key,
            "provider_name": report.provider_name,
            "report_id": report.id,
            "version": next_version,
            "mapping_status": str(candidate.mapping_summary.get("status") or "pending"),
            "mapping_summary": candidate.mapping_summary,
            "requirement_profile": requirement_profile,
            "route_plan": route_plan,
            "evidence": validation,
            "created_by": initiated_by,
        },
    )
    db.add(stack)
    db.flush()
    _upsert_adapter_and_profile(
        db,
        report=report,
        capability_type=capability_type,
        tier=tier,
        route_plan=route_plan,
        requirement_profile=requirement_profile,
        mapping_summary=candidate.mapping_summary,
        integration_id=stack.id,
        version=next_version,
    )
    report.raw_payload_json = {**dict(report.raw_payload_json or {}), "mapping": candidate.mapping_summary, "active_integration_id": stack.id}
    _assign_integration_status(
        row=report,
        meets_minimum=True,
        mapping_ready=str(candidate.mapping_summary.get("status")) in {"mapped", "partial"},
    )
    report.integration_notes = f"auto-plan active integration v{next_version}"
    report.updated_by = "ops-auto-integration"
    report.updated_at = _utcnow()
    return stack


def _build_validation_payload(report: OpsProviderReport, candidate: _CandidateScore, validate_connectivity: bool) -> dict[str, Any]:
    return {
        "validated": validate_connectivity,
        "connectivity_status": candidate.connectivity_status,
        "openapi_url": report.openapi_url,
        "endpoint_base_url": report.endpoint_base_url,
        "mapping_status": candidate.mapping_summary.get("status"),
    }


@router.get("/requirements/tiers", response_model=RequirementTiersResponse)
def get_requirement_tiers() -> RequirementTiersResponse:
    items: list[CapabilityRequirementDefinition] = []
    for capability_type, spec in CAPABILITY_STANDARDS.items():
        tiers: dict[str, RequirementTierDefinition] = {}
        for external_tier, internal_tier in (("basic", "low"), ("standard", "medium"), ("advanced", "high")):
            required = _cumulative_required_features(capability_type, internal_tier)
            tiers[external_tier] = RequirementTierDefinition(
                tier=external_tier,
                target_values=_tier_constraints(capability_type, external_tier),
                must_support=required,
                optional_support=list(spec.get("tiers", {}).get(internal_tier, [])),
            )
        items.append(
            CapabilityRequirementDefinition(
                capability_type=capability_type,
                display_name=str(spec.get("display_name") or capability_type),
                aliases=_available_aliases(capability_type),
                tiers=tiers,
            )
        )
    return RequirementTiersResponse(items=items)


@router.get("/requirements/schema", response_model=RequirementSchemaResponse)
def get_requirement_schema() -> RequirementSchemaResponse:
    return RequirementSchemaResponse(
        capability_aliases=dict(CAPABILITY_ALIASES),
        tier_aliases={"basic": "low", "standard": "medium", "advanced": "high"},
        requirement_profile_schema=RequirementProfileModel.model_json_schema(),
        route_plan_schema=RoutePlanModel.model_json_schema(),
        gap_report_schema=GapReportModel.model_json_schema(),
    )


@router.post("/ops/plan", response_model=OpsPlanResponse)
def create_ops_plan(payload: OpsPlanRequest, db: Session = Depends(get_db)) -> OpsPlanResponse:
    capability_type = _normalize_capability(payload.capability)
    if capability_type not in CAPABILITY_STANDARDS:
        raise HTTPException(status_code=400, detail=f"unsupported capability: {payload.capability}")
    internal_tier = _internal_tier_name(payload.tier)
    external_tier = _INTERNAL_TO_TIER_ALIAS[internal_tier]
    requirement_profile = _build_requirement_profile(payload, capability_type, external_tier, internal_tier)

    reports = db.execute(
        select(OpsProviderReport).where(
            OpsProviderReport.tenant_id == payload.tenant_id,
            OpsProviderReport.project_id == payload.project_id,
            OpsProviderReport.capability_type == capability_type,
            OpsProviderReport.deleted_at.is_(None),
        )
    ).scalars().all()
    ranked = sorted(
        [(report, _score_candidate(report, requirement_profile)) for report in reports],
        key=lambda item: item[1].score,
        reverse=True,
    )
    selected = next(
        (
            item for item in ranked
            if item[1].meets_requested_tier and not item[1].feature_gaps and not item[1].unmet_constraints
        ),
        None,
    )

    if selected is None:
        gap = _build_gap_report(capability_type, requirement_profile, ranked)
        return OpsPlanResponse(
            status="gap",
            capability=capability_type,
            tier=external_tier,
            requirement_profile=requirement_profile,
            gap_report=GapReportResponse(
                gap_type=str(gap.get("gap_type") or "provider_missing"),
                summary=f"{capability_type}/{external_tier} 当前无满足候选",
                missing_features=list((gap.get("details") or {}).get("missing_features") or []),
                unmet_constraints=dict((gap.get("details") or {}).get("unmet_constraints") or {}),
                repair_actions=dict(gap.get("repair_actions") or {}),
                candidate_summaries=list((gap.get("details") or {}).get("candidate_summaries") or []),
            ),
            candidates_considered=len(ranked),
        )

    report, candidate = selected
    fallback_chain = [
        {
            "provider_key": item_report.provider_key,
            "provider_name": item_report.provider_name,
            "report_id": item_report.id,
            "capability_tier": item_report.capability_tier,
        }
        for item_report, item_score in ranked
        if item_report.id != report.id and item_score.meets_requested_tier
    ][:3]
    route_plan = _build_route_plan(report, candidate, requirement_profile, fallback_chain)
    validation = _build_validation_payload(report, candidate, payload.validate_connectivity)
    integration_row: CreativePolicyStack | None = None
    if payload.auto_integrate:
        integration_row = _persist_integration(
            db,
            report=report,
            candidate=candidate,
            capability_type=capability_type,
            tier=external_tier,
            requirement_profile=requirement_profile,
            route_plan=route_plan,
            validation=validation,
            initiated_by=payload.initiated_by,
        )
        db.commit()
        db.refresh(integration_row)
        db.refresh(report)

    integration_resp = _build_integration_response(integration_row) if integration_row is not None else None
    return OpsPlanResponse(
        status="planned",
        capability=capability_type,
        tier=external_tier,
        requirement_profile=requirement_profile,
        route_plan=RoutePlanResponse(
            selected_provider_key=report.provider_key,
            selected_provider_name=report.provider_name,
            selected_report_id=report.id,
            matched_provider_id=report.matched_provider_id,
            data_endpoint=route_plan.get("data_endpoint"),
            selected_template_id=str(route_plan.get("selected_template_id") or ""),
            selected_template_version=str(route_plan.get("selected_template_version") or "v1"),
            workflow_hash=str(route_plan.get("workflow_hash") or ""),
            resolved_params=dict(route_plan.get("resolved_params") or {}),
            bindings=dict(route_plan.get("bindings") or {}),
            fallback_chain=list(route_plan.get("fallback_chain") or []),
            mapping_status=str(candidate.mapping_summary.get("status") or "pending"),
            mapping_confidence=candidate.mapping_summary.get("confidence"),
        ),
        integration=integration_resp,
        candidates_considered=len(ranked),
    )


@router.get("/ops/integrations", response_model=OpsIntegrationListResponse)
def list_ops_integrations(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    capability_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> OpsIntegrationListResponse:
    target_capability = _normalize_capability(capability_type) if capability_type else None
    rows = _load_integration_rows(db, tenant_id, project_id)
    items = []
    for row in rows:
        payload = dict(row.stack_json or {})
        if target_capability and str(payload.get("capability_type") or "") != target_capability:
            continue
        items.append(_build_integration_response(row))
    items.sort(key=lambda item: (item.created_at or "", item.version), reverse=True)
    return OpsIntegrationListResponse(items=items)


@router.post("/ops/integrations/{integration_id}/rollback", response_model=OpsIntegrationRollbackResponse)
def rollback_ops_integration(
    integration_id: str,
    payload: OpsIntegrationRollbackRequest,
    db: Session = Depends(get_db),
) -> OpsIntegrationRollbackResponse:
    target = db.get(CreativePolicyStack, integration_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=404, detail="integration not found")
    target_payload = dict(target.stack_json or {})
    if target_payload.get("type") != "ops_integration":
        raise HTTPException(status_code=400, detail="integration type mismatch")
    if target.tenant_id != payload.tenant_id or target.project_id != payload.project_id:
        raise HTTPException(status_code=400, detail="integration scope mismatch")

    capability_type = str(target_payload.get("capability_type") or "")
    tier = str(target_payload.get("tier") or "basic")
    rows = _load_integration_rows(db, payload.tenant_id, payload.project_id)
    for row in rows:
        row_payload = dict(row.stack_json or {})
        if str(row_payload.get("capability_type") or "") == capability_type and str(row_payload.get("tier") or "") == tier:
            row.status = "archived"
            row.updated_by = "ops-auto-integration"
    target.status = "active"
    target.updated_by = "ops-auto-integration"
    db.commit()
    db.refresh(target)
    return OpsIntegrationRollbackResponse(integration=_build_integration_response(target))


@router.get("/ops/runtime-routing", response_model=RuntimeRoutingViewResponse)
def get_runtime_routing_view(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> RuntimeRoutingViewResponse:
    return _build_runtime_routing_view(db, tenant_id, project_id)


@router.post("/ops/runtime-routing/apply", response_model=RuntimeRoutingViewResponse)
def apply_ops_integration_to_runtime(
    payload: RuntimeRoutingApplyRequest,
    db: Session = Depends(get_db),
) -> RuntimeRoutingViewResponse:
    target = db.get(CreativePolicyStack, payload.integration_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=404, detail="integration not found")
    if target.tenant_id != payload.tenant_id or target.project_id != payload.project_id:
        raise HTTPException(status_code=400, detail="integration scope mismatch")

    integration_payload = dict(target.stack_json or {})
    if integration_payload.get("type") != "ops_integration":
        raise HTTPException(status_code=400, detail="integration type mismatch")

    capability_type = str(integration_payload.get("capability_type") or "")
    route_key = _runtime_route_key(capability_type)
    feature_key = _feature_route_key(capability_type)
    profile_name = _find_profile_name_by_integration(db, payload.tenant_id, payload.project_id, payload.integration_id)
    if not profile_name:
        raise HTTPException(status_code=400, detail="integration profile not found")

    stage_row = _load_stage_routing_row(db, payload.tenant_id, payload.project_id)
    stage_payload = _load_stage_routing_payload(db, payload.tenant_id, payload.project_id)
    stage_payload["routes"][route_key] = profile_name
    stage_payload["feature_routes"][feature_key] = profile_name
    stage_payload["fallback_chain"][feature_key] = list((integration_payload.get("route_plan") or {}).get("fallback_chain") or [])

    body = {
        "type": "stage_routing",
        "routes": stage_payload["routes"],
        "feature_routes": stage_payload["feature_routes"],
        "fallback_chain": stage_payload["fallback_chain"],
        "updated_at": _utcnow().isoformat(),
        "updated_by": "ops-runtime-routing",
    }
    if stage_row is None:
        stage_row = CreativePolicyStack(
            id=f"policy_{uuid4().hex}",
            tenant_id=payload.tenant_id,
            project_id=payload.project_id,
            trace_id=f"tr_route_{uuid4().hex[:12]}",
            correlation_id=f"cr_route_{uuid4().hex[:12]}",
            idempotency_key=f"idem_route_apply_{uuid4().hex[:8]}",
            name="stage_router_policy_default",
            status="active",
            stack_json=body,
            created_by="ops-runtime-routing",
            updated_by="ops-runtime-routing",
        )
        db.add(stage_row)
    else:
        stage_row.status = "active"
        stage_row.stack_json = body
        stage_row.updated_by = "ops-runtime-routing"

    db.commit()
    return _build_runtime_routing_view(db, payload.tenant_id, payload.project_id)


@router.post("/ops/quick-run", response_model=QuickRunResponse)
def quick_run_ops_integration(
    payload: QuickRunRequest,
    db: Session = Depends(get_db),
) -> QuickRunResponse:
    row = _latest_runtime_integration_row(
        db,
        payload.tenant_id,
        payload.project_id,
        capability_type=payload.capability_type,
        integration_id=payload.integration_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="integration not found")

    integration = _build_integration_response(row)
    row_payload = dict(row.stack_json or {})
    route_plan = dict(row_payload.get("route_plan") or {})
    profile_name = _find_profile_name_by_integration(db, payload.tenant_id, payload.project_id, row.id)
    mode, live_request, live_response = _quick_run_live_request(
        db=db,
        tenant_id=payload.tenant_id,
        project_id=payload.project_id,
        integration_id=row.id,
        capability_type=integration.capability_type,
        sample_input=dict(payload.sample_input or {}),
    )
    probe = _probe_runtime_endpoint(route_plan.get("data_endpoint")) if payload.probe_connectivity else {
        "ok": None,
        "detail": "probe skipped",
        "checked_url": route_plan.get("data_endpoint"),
        "latency_ms": None,
        "status": "skipped",
    }
    request_preview = {
        "capability_type": integration.capability_type,
        "tier": integration.tier,
        "selected_template_id": route_plan.get("selected_template_id"),
        "selected_template_version": route_plan.get("selected_template_version"),
        "request_bindings": dict((route_plan.get("bindings") or {}).get("request") or {}),
        "resolved_params": dict(route_plan.get("resolved_params") or {}),
        "sample_input": dict(payload.sample_input or {}),
        "data_endpoint": route_plan.get("data_endpoint"),
    }
    quick_run_success = bool(live_response.get("ok")) if mode == "live_request" else bool(probe.get("ok"))
    quick_run_latency_ms = live_response.get("latency_ms") if isinstance(live_response.get("latency_ms"), int) else probe.get("latency_ms")
    decision = RouteDecision(
        id=f"route_decision_{uuid4().hex}",
        tenant_id=payload.tenant_id,
        project_id=payload.project_id,
        trace_id=f"tr_quick_run_{uuid4().hex[:12]}",
        correlation_id=f"cr_quick_run_{uuid4().hex[:12]}",
        idempotency_key=f"idem_quick_run_{row.id}_{uuid4().hex[:8]}",
        created_by="ops-quick-run",
        updated_by="ops-quick-run",
        decision_json={
            "type": "ops_quick_run",
            "integration_id": row.id,
            "capability_type": integration.capability_type,
            "provider_key": integration.provider_key,
            "provider_name": integration.provider_name,
            "profile_name": profile_name,
            "request_preview": request_preview,
            "probe_ok": probe.get("ok"),
            "probe_detail": probe.get("detail"),
            "probe_latency_ms": probe.get("latency_ms"),
            "mode": mode,
            "live_ok": live_response.get("ok"),
            "live_status_code": live_response.get("status_code"),
            "live_latency_ms": live_response.get("latency_ms"),
            "quick_run_success": quick_run_success,
            "quick_run_latency_ms": quick_run_latency_ms,
            "live_request": live_request,
            "live_response": live_response,
        },
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return QuickRunResponse(
        mode=mode,
        integration=integration,
        runtime_route_key=_runtime_route_key(integration.capability_type),
        profile_name=profile_name,
        request_preview=request_preview,
        probe=probe,
        live_request=live_request,
        live_response=live_response,
        decision_id=decision.id,
    )
