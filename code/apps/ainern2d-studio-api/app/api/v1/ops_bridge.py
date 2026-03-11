from __future__ import annotations

import hashlib
from pathlib import Path
import re
import secrets
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.ops_bridge_models import OpsBridgeToken, OpsProviderReport
from ainern2d_shared.ainer_db_models.provider_models import ModelProvider
from ainern2d_shared.config.setting import settings

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/ops-bridge", tags=["ops-bridge"])

TOKEN_HEADER = "X-AinerOps-Token"
TOKEN_TTL_DAYS = 90
DEFAULT_TOKEN_NAME = "ainerops_ingress"
_TEST_TIMEOUT_SEC = 6.0
_DOC_TIMEOUT_SEC = 8.0
_DOC_MAX_BYTES = 2_000_000
_MAX_MODEL_CATALOG = 128

SUPPORTED_TRACK_TYPES: list[str] = [
    "storyboard",
    "video",
    "lipsync",
    "tts",
    "dialogue",
    "narration",
    "sfx",
    "ambience",
    "aux",
    "bgm",
    "subtitle",
]


CAPABILITY_STANDARDS: dict[str, dict[str, Any]] = {
    "llm_structured": {
        "display_name": "LLM Structured Planning",
        "track_targets": ["storyboard", "subtitle", "dialogue", "narration"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "structured_json_output",
                "multilingual_generation",
                "system_prompt_control",
            ],
            "medium": [
                "function_calling",
                "tool_calling",
                "long_context_32k",
            ],
            "high": [
                "schema_guard_strict",
                "long_context_128k",
                "reasoning_trace",
            ],
        },
    },
    "storyboard_t2i": {
        "display_name": "Storyboard Text-to-Image",
        "track_targets": ["storyboard"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "prompt_to_image",
                "seed_control",
                "aspect_ratio_control",
            ],
            "medium": [
                "character_reference",
                "style_reference",
                "batch_generation",
            ],
            "high": [
                "pose_lock",
                "region_editing",
                "depth_or_canny_control",
            ],
        },
    },
    "video_t2v": {
        "display_name": "Video Text-to-Video",
        "track_targets": ["video"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "prompt_to_video",
                "duration_control",
                "fps_control",
            ],
            "medium": [
                "camera_motion_control",
                "negative_prompt",
                "temporal_consistency",
            ],
            "high": [
                "shot_continuity_lock",
                "keyframe_path",
                "motion_brush",
            ],
        },
    },
    "video_i2v": {
        "display_name": "Video Image-to-Video",
        "track_targets": ["video"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "image_to_video",
                "duration_control",
                "fps_control",
            ],
            "medium": [
                "strength_control",
                "camera_motion_control",
                "temporal_consistency",
            ],
            "high": [
                "first_last_frame_lock",
                "region_motion_control",
                "keyframe_path",
            ],
        },
    },
    "lipsync": {
        "display_name": "LipSync",
        "track_targets": ["lipsync"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "audio_driven_lipsync",
                "face_detect",
                "output_video",
            ],
            "medium": [
                "viseme_alignment",
                "multi_face_select",
                "expression_preserve",
            ],
            "high": [
                "phoneme_level_control",
                "head_pose_lock",
                "batch_lipsync",
            ],
        },
    },
    "tts": {
        "display_name": "TTS Core",
        "track_targets": ["tts"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "male_female_voice",
                "emotion_basic",
                "multilingual_voice",
            ],
            "medium": [
                "sentence_timestamps",
                "speaking_rate_control",
                "style_control",
            ],
            "high": [
                "word_timestamps",
                "voice_clone_stable",
                "seed_reproducible",
            ],
        },
    },
    "dialogue_tts": {
        "display_name": "Dialogue TTS",
        "track_targets": ["dialogue"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "speaker_role_binding",
                "turn_batch_inference",
                "emotion_basic",
            ],
            "medium": [
                "sentence_timestamps",
                "character_voice_memory",
                "retry_failed_segments",
            ],
            "high": [
                "word_timestamps",
                "prosody_control",
                "phoneme_override",
            ],
        },
    },
    "narration_tts": {
        "display_name": "Narration TTS",
        "track_targets": ["narration"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "narration_voice",
                "pace_control",
                "paragraph_input",
            ],
            "medium": [
                "sentence_timestamps",
                "style_preset",
                "long_text_chunking",
            ],
            "high": [
                "word_timestamps",
                "breath_pause_control",
                "continuity_voice_lock",
            ],
        },
    },
    "sfx": {
        "display_name": "SFX Generation",
        "track_targets": ["sfx"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "text_to_sfx",
                "duration_control",
                "wav_output",
            ],
            "medium": [
                "start_offset_hint",
                "category_control",
                "intensity_control",
            ],
            "high": [
                "layer_stem_output",
                "event_batch",
                "spectral_shaping",
            ],
        },
    },
    "ambience": {
        "display_name": "Ambience Bed",
        "track_targets": ["ambience"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "ambience_loop_generation",
                "stereo_output",
                "duration_control",
            ],
            "medium": [
                "weather_scene_presets",
                "seamless_loop_points",
                "noise_floor_control",
            ],
            "high": [
                "multichannel_output",
                "dynamic_density_curve",
                "stem_layers_export",
            ],
        },
    },
    "aux": {
        "display_name": "Aux Texture Layer",
        "track_targets": ["aux"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "texture_layer_generation",
                "duration_control",
                "loop_option",
            ],
            "medium": [
                "tone_color_control",
                "rhythmic_texture",
                "sidechain_hint",
            ],
            "high": [
                "spectral_envelope_control",
                "adaptive_follow_bpm",
                "stem_layers_export",
            ],
        },
    },
    "bgm": {
        "display_name": "BGM Generation",
        "track_targets": ["bgm"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "prompt_to_music",
                "mood_control",
                "duration_control",
            ],
            "medium": [
                "bpm_control",
                "key_control",
                "loop_points",
            ],
            "high": [
                "section_structure",
                "stem_export",
                "hitpoint_sync",
            ],
        },
    },
    "subtitle": {
        "display_name": "Subtitle/Caption",
        "track_targets": ["subtitle"],
        "min_required_tier": "low",
        "tiers": {
            "low": [
                "subtitle_text_generation",
                "line_break_control",
                "bilingual_output",
            ],
            "medium": [
                "sentence_timestamps",
                "speaker_tagging",
                "max_chars_control",
            ],
            "high": [
                "word_timestamps",
                "cps_control",
                "style_template",
            ],
        },
    },
}

CAPABILITY_ALIASES: dict[str, str] = {
    "llm": "llm_structured",
    "structured_llm": "llm_structured",
    "storyboard": "storyboard_t2i",
    "t2i": "storyboard_t2i",
    "text_to_image": "storyboard_t2i",
    "storyboard_t2i": "storyboard_t2i",
    "video": "video_t2v",
    "t2v": "video_t2v",
    "text_to_video": "video_t2v",
    "video_t2v": "video_t2v",
    "i2v": "video_i2v",
    "image_to_video": "video_i2v",
    "video_i2v": "video_i2v",
    "lipsync": "lipsync",
    "tts": "tts",
    "dialogue": "dialogue_tts",
    "dialogue_tts": "dialogue_tts",
    "narration": "narration_tts",
    "narration_tts": "narration_tts",
    "sfx": "sfx",
    "ambience": "ambience",
    "aux": "aux",
    "bgm": "bgm",
    "subtitle": "subtitle",
}

ADAPTER_SPEC: dict[str, dict[str, Any]] = {
    "tts": {
        "request_required": ["task_id", "language", "segments", "voice_ref"],
        "response_required": ["audio_url", "duration_ms", "segments"],
        "response_optional": ["word_timestamps", "provider_id", "model_version"],
    },
    "storyboard_t2i": {
        "request_required": ["task_id", "prompt", "style", "resolution"],
        "response_required": ["image_url", "width", "height"],
        "response_optional": ["seed", "safety_flags", "provider_id"],
    },
    "video_t2v": {
        "request_required": ["task_id", "prompt", "duration_s", "fps"],
        "response_required": ["video_url", "duration_ms", "fps"],
        "response_optional": ["seed", "keyframes", "provider_id"],
    },
    "video_i2v": {
        "request_required": ["task_id", "image_url", "duration_s", "fps"],
        "response_required": ["video_url", "duration_ms", "fps"],
        "response_optional": ["motion_strength", "keyframes", "provider_id"],
    },
    "sfx": {
        "request_required": ["task_id", "description", "duration_ms"],
        "response_required": ["audio_url", "duration_ms"],
        "response_optional": ["category", "intensity", "provider_id"],
    },
    "ambience": {
        "request_required": ["task_id", "description", "duration_ms", "loop"],
        "response_required": ["audio_url", "duration_ms"],
        "response_optional": ["loop_points", "stems", "provider_id"],
    },
    "aux": {
        "request_required": ["task_id", "description", "duration_ms"],
        "response_required": ["audio_url", "duration_ms"],
        "response_optional": ["loop_points", "stems", "provider_id"],
    },
    "bgm": {
        "request_required": ["task_id", "prompt", "duration_s", "mood"],
        "response_required": ["audio_url", "duration_ms"],
        "response_optional": ["bpm", "musical_key", "stems", "provider_id"],
    },
    "subtitle": {
        "request_required": ["task_id", "dialogues", "target_language"],
        "response_required": ["segments", "duration_ms"],
        "response_optional": ["word_timestamps", "style_template", "provider_id"],
    },
    "lipsync": {
        "request_required": ["task_id", "video_url", "audio_url"],
        "response_required": ["video_url", "duration_ms"],
        "response_optional": ["alignment_mode", "provider_id"],
    },
    "llm_structured": {
        "request_required": ["task_id", "messages", "output_schema"],
        "response_required": ["output_json", "usage"],
        "response_optional": ["tool_calls", "trace", "provider_id"],
    },
}

TIER_ORDER: dict[str, int] = {"none": 0, "low": 1, "medium": 2, "high": 3}

_CANONICAL_FIELD_ALIASES: dict[str, list[str]] = {
    "task_id": ["task", "job_id", "request_id", "trace_id"],
    "language": ["lang", "locale", "language_code"],
    "segments": ["segment", "sentences", "sentence_list", "lines", "utterances", "chunks"],
    "voice_ref": ["voice", "voice_id", "speaker", "speaker_id", "voice_name"],
    "audio_url": ["audio_uri", "audio_path", "audio_file", "output_audio_url", "url"],
    "duration_ms": ["duration", "duration_s", "length_ms", "audio_duration_ms", "video_duration_ms"],
    "prompt": ["text", "description", "query", "positive_prompt", "input"],
    "description": ["prompt", "text", "sfx_text", "effect_text"],
    "mood": ["emotion", "tone", "style_mood"],
    "image_url": ["image_uri", "image_path", "input_image", "source_image"],
    "video_url": ["video_uri", "video_path", "output_video_url", "render_url"],
    "fps": ["frame_rate", "frame_per_second"],
    "dialogues": ["dialogue", "dialogs", "lines", "subtitles_input"],
    "target_language": ["target_lang", "target_locale", "language"],
    "messages": ["prompt_messages", "chat_messages", "input_messages"],
    "output_schema": ["schema", "json_schema", "response_schema"],
    "output_json": ["result", "json", "response_json", "structured_output"],
    "usage": ["token_usage", "usage_stats", "cost_usage", "billing_usage"],
}


class CapabilityStandardItem(BaseModel):
    capability_type: str
    display_name: str
    track_targets: list[str]
    min_required_tier: str
    tiers: dict[str, list[str]]


class CapabilityStandardsResponse(BaseModel):
    supported_track_types: list[str]
    items: list[CapabilityStandardItem]


class AdapterSpecResponse(BaseModel):
    items: dict[str, dict[str, Any]]


class OpsStorageConfigResponse(BaseModel):
    storage_backend: str
    provider: str
    endpoint: str
    internal_endpoint: str
    console_endpoint: str | None = None
    bucket: str
    region: str
    access_key: str
    secret_key: str
    root_user: str
    root_password: str
    copy_env_block: str


class OpsStorageConfigUpdateRequest(BaseModel):
    endpoint: str
    internal_endpoint: str
    console_endpoint: str | None = None
    bucket: str
    region: str = "us-east-1"
    access_key: str
    secret_key: str
    root_user: str
    root_password: str


class OpsTokenResponse(BaseModel):
    token_id: str
    name: str
    token_masked: str
    is_active: bool
    created_at: datetime
    expires_at: datetime
    days_remaining: int
    last_used_at: datetime | None = None


class OpsTokenRevealResponse(BaseModel):
    token_id: str
    name: str
    token: str
    expires_at: datetime


class OpsTokenRegenerateRequest(BaseModel):
    tenant_id: str
    project_id: str
    name: str = DEFAULT_TOKEN_NAME


class OpsTokenQuery(BaseModel):
    tenant_id: str
    project_id: str
    name: str = DEFAULT_TOKEN_NAME


class OpsProviderReportRequest(BaseModel):
    tenant_id: str
    project_id: str
    provider_key: str
    provider_name: str
    capability_type: str
    endpoint_base_url: str | None = None
    protocol: str = "ainer-unified"
    openapi_url: str | None = None
    model_catalog: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    health: dict[str, Any] = Field(default_factory=dict)
    adapter_spec: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpsProviderReportUpsertResponse(BaseModel):
    report_id: str
    provider_key: str
    capability_type: str
    capability_tier: str
    integration_status: str
    matched_provider_id: str | None = None
    meets_minimum: bool
    adapter_gap_features: list[str] = Field(default_factory=list)
    mapping_status: str = "pending"
    mapping_confidence: float | None = None
    mapping_gaps: list[str] = Field(default_factory=list)


class OpsProviderRow(BaseModel):
    report_id: str
    provider_key: str
    provider_name: str
    capability_type: str
    capability_tier: str
    min_required_tier: str
    meets_minimum: bool
    integration_status: str
    integration_status_label: str
    matched_provider_id: str | None = None
    matched_provider_name: str | None = None
    endpoint_base_url: str | None = None
    protocol: str
    openapi_url: str | None = None
    model_catalog: list[str] = Field(default_factory=list)
    last_reported_at: datetime | None = None
    last_tested_at: datetime | None = None
    integration_notes: str | None = None
    mapping_status: str = "pending"
    mapping_confidence: float | None = None
    request_coverage: float | None = None
    response_coverage: float | None = None
    feature_coverage: float | None = None
    mapping_gaps: list[str] = Field(default_factory=list)
    mapping_generated_at: datetime | None = None
    connectivity_status: str = "untested"
    connectivity_label: str = "未测试"
    last_connectivity_detail: str | None = None
    last_checked_url: str | None = None
    last_latency_ms: int | None = None


class OpsProviderListResponse(BaseModel):
    items: list[OpsProviderRow]


class OpsProviderManualBindRequest(BaseModel):
    provider_id: str | None = None
    integration_notes: str | None = None


class OpsProviderTestResponse(BaseModel):
    report_id: str
    ok: bool
    status: str
    latency_ms: int | None = None
    detail: str
    checked_url: str | None = None
    connectivity_status: str = "disconnected"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mask_secret(token: str) -> str:
    token = token.strip()
    if len(token) <= 10:
        return "*" * len(token)
    return f"{token[:6]}...{token[-4:]}"


def _normalize_endpoint(endpoint: str | None) -> str:
    if not endpoint:
        return ""
    text = endpoint.strip().rstrip("/")
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.scheme:
        return text.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{netloc}{path}"


def _normalize_capability(capability_type: str) -> str:
    key = capability_type.strip().lower().replace("-", "_")
    return CAPABILITY_ALIASES.get(key, key)


def _collect_feature_keys(data: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(data, dict):
        for raw_key, value in data.items():
            key = str(raw_key).strip()
            if not key:
                continue
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, bool):
                if value:
                    keys.add(full_key)
                    keys.add(key)
            elif isinstance(value, (int, float)):
                if value > 0:
                    keys.add(full_key)
                    keys.add(key)
            elif isinstance(value, str):
                if value.strip():
                    keys.add(full_key)
                    keys.add(key)
            elif isinstance(value, list):
                if value:
                    keys.add(full_key)
                    keys.add(key)
                for item in value:
                    if isinstance(item, str) and item.strip():
                        keys.add(item.strip())
                    elif isinstance(item, dict):
                        keys.update(_collect_feature_keys(item, full_key))
            elif isinstance(value, dict):
                keys.update(_collect_feature_keys(value, full_key))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str) and item.strip():
                keys.add(item.strip())
            elif isinstance(item, dict):
                keys.update(_collect_feature_keys(item, prefix=prefix))
    return keys


def _normalize_key_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _collect_schema_property_names(schema: Any, out: set[str]) -> None:
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for prop_name, prop_schema in properties.items():
            name = str(prop_name).strip()
            if name:
                out.add(name)
            _collect_schema_property_names(prop_schema, out)
    items = schema.get("items")
    if items is not None:
        _collect_schema_property_names(items, out)
    for branch_key in ("allOf", "anyOf", "oneOf"):
        branch = schema.get(branch_key)
        if isinstance(branch, list):
            for node in branch:
                _collect_schema_property_names(node, out)


def _extract_openapi_hints_from_json(doc: dict[str, Any]) -> dict[str, Any]:
    request_keys: set[str] = set()
    response_keys: set[str] = set()
    feature_keys: set[str] = set()
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return {
            "request_keys": request_keys,
            "response_keys": response_keys,
            "feature_keys": feature_keys,
        }

    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            for text_key in ("operationId", "summary", "description"):
                text_val = operation.get(text_key)
                if isinstance(text_val, str) and text_val.strip():
                    feature_keys.update(re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{2,}", text_val))
            tags = operation.get("tags")
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, str) and tag.strip():
                        feature_keys.add(tag.strip())

            parameters = operation.get("parameters")
            if isinstance(parameters, list):
                for param in parameters:
                    if not isinstance(param, dict):
                        continue
                    name = str(param.get("name", "")).strip()
                    if name:
                        request_keys.add(name)
                    schema = param.get("schema")
                    _collect_schema_property_names(schema, request_keys)

            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content")
                if isinstance(content, dict):
                    for media in content.values():
                        if isinstance(media, dict):
                            _collect_schema_property_names(media.get("schema"), request_keys)

            responses = operation.get("responses")
            if isinstance(responses, dict):
                for response_obj in responses.values():
                    if not isinstance(response_obj, dict):
                        continue
                    content = response_obj.get("content")
                    if isinstance(content, dict):
                        for media in content.values():
                            if isinstance(media, dict):
                                _collect_schema_property_names(media.get("schema"), response_keys)
                    description = response_obj.get("description")
                    if isinstance(description, str) and description.strip():
                        feature_keys.update(re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{2,}", description))

    return {
        "request_keys": request_keys,
        "response_keys": response_keys,
        "feature_keys": feature_keys,
    }


def _fetch_openapi_hints(openapi_url: str | None) -> dict[str, Any]:
    if not openapi_url or not openapi_url.strip():
        return {
            "fetched": False,
            "ok": False,
            "status_code": None,
            "error": "openapi_url missing",
            "request_keys": set(),
            "response_keys": set(),
            "feature_keys": set(),
        }

    url = openapi_url.strip()
    try:
        with httpx.Client(timeout=_DOC_TIMEOUT_SEC, follow_redirects=True) as client:
            resp = client.get(url)
        status_code = int(resp.status_code)
        raw_bytes = resp.content[:_DOC_MAX_BYTES]

        request_keys: set[str] = set()
        response_keys: set[str] = set()
        feature_keys: set[str] = set()
        error: str | None = None

        try:
            parsed = resp.json()
            if isinstance(parsed, dict):
                hints = _extract_openapi_hints_from_json(parsed)
                request_keys = set(hints["request_keys"])
                response_keys = set(hints["response_keys"])
                feature_keys = set(hints["feature_keys"])
            else:
                text = raw_bytes.decode("utf-8", errors="ignore")
                feature_keys = set(re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{2,}", text))
        except Exception:
            text = raw_bytes.decode("utf-8", errors="ignore")
            feature_keys = set(re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{2,}", text))
            error = "non-json doc parsed by keyword fallback"

        return {
            "fetched": True,
            "ok": status_code < 500,
            "status_code": status_code,
            "error": error,
            "request_keys": request_keys,
            "response_keys": response_keys,
            "feature_keys": feature_keys,
        }
    except Exception as exc:
        return {
            "fetched": True,
            "ok": False,
            "status_code": None,
            "error": str(exc),
            "request_keys": set(),
            "response_keys": set(),
            "feature_keys": set(),
        }


def _collect_declared_io_keys(adapter_spec: dict[str, Any]) -> tuple[set[str], set[str]]:
    req: set[str] = set()
    resp: set[str] = set()
    for req_key in ("request_required", "request_optional", "input_required", "input_optional"):
        val = adapter_spec.get(req_key)
        if isinstance(val, list):
            req.update(str(item).strip() for item in val if str(item).strip())
    for resp_key in ("response_required", "response_optional", "output_required", "output_optional"):
        val = adapter_spec.get(resp_key)
        if isinstance(val, list):
            resp.update(str(item).strip() for item in val if str(item).strip())
    request_section = adapter_spec.get("request")
    response_section = adapter_spec.get("response")
    req.update(_collect_feature_keys(request_section))
    resp.update(_collect_feature_keys(response_section))
    return req, resp


def _match_score(canonical_key: str, candidate_key: str) -> int:
    canonical_norm = _normalize_key_name(canonical_key)
    candidate_norm = _normalize_key_name(candidate_key)
    if not canonical_norm or not candidate_norm:
        return 0
    if canonical_norm == candidate_norm:
        return 100

    canonical_aliases = _CANONICAL_FIELD_ALIASES.get(canonical_key, [])
    alias_norms = {_normalize_key_name(alias) for alias in canonical_aliases if alias.strip()}
    if candidate_norm in alias_norms:
        return 92

    canonical_tokens = {tok for tok in canonical_norm.split("_") if tok}
    candidate_tokens = {tok for tok in candidate_norm.split("_") if tok}
    if canonical_tokens and canonical_tokens.issubset(candidate_tokens):
        return 80
    for alias_norm in alias_norms:
        alias_tokens = {tok for tok in alias_norm.split("_") if tok}
        if alias_tokens and alias_tokens.issubset(candidate_tokens):
            return 74

    if canonical_norm in candidate_norm or candidate_norm in canonical_norm:
        return 62
    for alias_norm in alias_norms:
        if alias_norm and (alias_norm in candidate_norm or candidate_norm in alias_norm):
            return 58
    return 0


def _build_field_mapping(required_keys: list[str], candidates: set[str]) -> tuple[dict[str, str], list[str], float]:
    mapping: dict[str, str] = {}
    missing: list[str] = []
    for required in required_keys:
        best: tuple[str, int] | None = None
        for candidate in candidates:
            score = _match_score(required, candidate)
            if score <= 0:
                continue
            if best is None or score > best[1]:
                best = (candidate, score)
        if best:
            mapping[required] = best[0]
        else:
            missing.append(required)

    total = len(required_keys)
    coverage = 1.0 if total == 0 else (total - len(missing)) / total
    return mapping, missing, round(coverage, 4)


def _build_mapping_summary(
    *,
    capability_type: str,
    features: dict[str, Any],
    adapter_spec: dict[str, Any],
    openapi_url: str | None,
    fetch_openapi: bool,
) -> dict[str, Any]:
    canonical_spec = ADAPTER_SPEC.get(capability_type, {})
    req_required = list(canonical_spec.get("request_required", []))
    resp_required = list(canonical_spec.get("response_required", []))
    feature_required_low = _tier_requirements(capability_type, "low")

    declared_req, declared_resp = _collect_declared_io_keys(adapter_spec)
    feature_keys = _collect_feature_keys(features)

    openapi_hints = {
        "fetched": False,
        "ok": False,
        "status_code": None,
        "error": "not fetched",
        "request_keys": set(),
        "response_keys": set(),
        "feature_keys": set(),
    }
    if fetch_openapi:
        openapi_hints = _fetch_openapi_hints(openapi_url)

    req_candidates = set(declared_req) | set(openapi_hints["request_keys"])
    resp_candidates = set(declared_resp) | set(openapi_hints["response_keys"])
    feature_keys = set(feature_keys) | set(openapi_hints["feature_keys"])

    req_mapping, req_missing, req_coverage = _build_field_mapping(req_required, req_candidates)
    resp_mapping, resp_missing, resp_coverage = _build_field_mapping(resp_required, resp_candidates)

    feature_norms = {_normalize_key_name(item) for item in feature_keys if str(item).strip()}
    feature_missing: list[str] = []
    for req in feature_required_low:
        if _normalize_key_name(req) not in feature_norms:
            feature_missing.append(req)
    total_features = len(feature_required_low)
    feature_coverage = 1.0 if total_features == 0 else (total_features - len(feature_missing)) / total_features
    feature_coverage = round(feature_coverage, 4)

    if not fetch_openapi and not adapter_spec:
        mapping_status = "pending"
    elif req_coverage == 1.0 and resp_coverage == 1.0 and feature_coverage >= 0.67:
        mapping_status = "mapped"
    elif req_coverage >= 0.5 or resp_coverage >= 0.5 or feature_coverage >= 0.34:
        mapping_status = "partial"
    else:
        mapping_status = "failed"

    confidence = min(
        1.0,
        (req_coverage * 0.45)
        + (resp_coverage * 0.35)
        + (feature_coverage * 0.2)
        + (0.05 if bool(openapi_hints["ok"]) else 0.0),
    )
    confidence = round(confidence, 4)

    gaps = [f"request:{item}" for item in req_missing]
    gaps.extend(f"response:{item}" for item in resp_missing)
    gaps.extend(f"feature:{item}" for item in feature_missing)

    return {
        "status": mapping_status,
        "confidence": confidence if mapping_status != "pending" else None,
        "request_coverage": req_coverage,
        "response_coverage": resp_coverage,
        "feature_coverage": feature_coverage,
        "request_mapping": req_mapping,
        "response_mapping": resp_mapping,
        "gaps": gaps,
        "source": {
            "adapter_spec_present": bool(adapter_spec),
            "openapi_url": openapi_url,
            "openapi_fetched": bool(openapi_hints["fetched"]),
            "openapi_ok": bool(openapi_hints["ok"]),
            "openapi_status_code": openapi_hints["status_code"],
            "openapi_error": openapi_hints["error"],
        },
        "generated_at": _utcnow().isoformat(),
    }


def _connectivity_label(code: str) -> str:
    if code == "connected":
        return "联通"
    if code == "disconnected":
        return "不联通"
    if code == "testing":
        return "测试中"
    return "未测试"


def _build_storage_env_block() -> str:
    lines = [
        f"STORAGE_BACKEND={settings.storage_backend}",
        f"S3_ENDPOINT={settings.s3_endpoint}",
        f"S3_PUBLIC_ENDPOINT={settings.s3_public_endpoint}",
        f"S3_ACCESS_KEY={settings.s3_access_key}",
        f"S3_SECRET_KEY={settings.s3_secret_key}",
        f"S3_BUCKET={settings.s3_bucket}",
        f"S3_REGION={settings.s3_region}",
        f"MINIO_ROOT_USER={settings.minio_root_user}",
        f"MINIO_ROOT_PASSWORD={settings.minio_root_password}",
    ]
    if settings.minio_console_endpoint:
        lines.append(f"MINIO_CONSOLE_ENDPOINT={settings.minio_console_endpoint}")
    return "\n".join(lines)


def _env_file_path() -> Path:
    return Path(__file__).resolve().parents[5] / ".env"


def _upsert_env_assignments(env_text: str, assignments: dict[str, str]) -> str:
    lines = env_text.splitlines()
    seen: set[str] = set()
    updated_lines: list[str] = []
    pattern_cache = {
        key: re.compile(rf"^{re.escape(key)}=")
        for key in assignments
    }

    for line in lines:
        replaced = False
        for key, pattern in pattern_cache.items():
            if pattern.match(line):
                updated_lines.append(f"{key}={assignments[key]}")
                seen.add(key)
                replaced = True
                break
        if not replaced:
            updated_lines.append(line)

    if updated_lines and updated_lines[-1].strip():
        updated_lines.append("")
    for key, value in assignments.items():
        if key not in seen:
            updated_lines.append(f"{key}={value}")
    return "\n".join(updated_lines).rstrip() + "\n"


def _apply_storage_config_update(payload: OpsStorageConfigUpdateRequest) -> None:
    settings.storage_backend = "minio"
    settings.s3_public_endpoint = payload.endpoint.strip()
    settings.s3_endpoint = payload.internal_endpoint.strip()
    settings.minio_console_endpoint = (payload.console_endpoint or "").strip() or ""
    settings.s3_bucket = payload.bucket.strip()
    settings.s3_region = payload.region.strip()
    settings.s3_access_key = payload.access_key.strip()
    settings.s3_secret_key = payload.secret_key.strip()
    settings.minio_root_user = payload.root_user.strip()
    settings.minio_root_password = payload.root_password.strip()

    env_path = _env_file_path()
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    env_path.write_text(
        _upsert_env_assignments(
            existing,
            {
                "STORAGE_BACKEND": settings.storage_backend,
                "S3_ENDPOINT": settings.s3_endpoint,
                "S3_PUBLIC_ENDPOINT": settings.s3_public_endpoint,
                "S3_ACCESS_KEY": settings.s3_access_key,
                "S3_SECRET_KEY": settings.s3_secret_key,
                "S3_BUCKET": settings.s3_bucket,
                "S3_REGION": settings.s3_region,
                "MINIO_ROOT_USER": settings.minio_root_user,
                "MINIO_ROOT_PASSWORD": settings.minio_root_password,
                "MINIO_CONSOLE_ENDPOINT": settings.minio_console_endpoint,
            },
        ),
        encoding="utf-8",
    )


def _tier_requirements(capability_type: str, tier: str) -> list[str]:
    spec = CAPABILITY_STANDARDS.get(capability_type) or {}
    tiers: dict[str, list[str]] = spec.get("tiers", {})
    return list(tiers.get(tier, []))


def _evaluate_tier(capability_type: str, features: dict[str, Any]) -> tuple[str, list[str]]:
    feature_keys = _collect_feature_keys(features)
    for tier in ("high", "medium", "low"):
        required = _tier_requirements(capability_type, tier)
        if required and all(req in feature_keys for req in required):
            return tier, []

    low_required = _tier_requirements(capability_type, "low")
    missing_low = [item for item in low_required if item not in feature_keys]
    return "none", missing_low


def _integration_status_label(code: str) -> str:
    if code == "integrated":
        return "已对接"
    if code == "capability_gap":
        return "未对接(能力/映射不足)"
    if code == "unbound":
        return "未对接"
    return code


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _build_new_token_value() -> str:
    return f"ops_{secrets.token_urlsafe(42)}"


def _get_token_or_none(db: Session, tenant_id: str, project_id: str, name: str) -> OpsBridgeToken | None:
    return db.execute(
        select(OpsBridgeToken)
        .where(
            OpsBridgeToken.tenant_id == tenant_id,
            OpsBridgeToken.project_id == project_id,
            OpsBridgeToken.name == name,
            OpsBridgeToken.deleted_at.is_(None),
        )
        .limit(1)
    ).scalars().first()


def _create_token_row(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    name: str,
    actor: str = "studio-admin",
) -> OpsBridgeToken:
    raw = _build_new_token_value()
    row = OpsBridgeToken(
        id=f"ops_tok_{uuid4().hex}",
        tenant_id=tenant_id,
        project_id=project_id,
        trace_id=None,
        correlation_id=None,
        idempotency_key=f"idem_ops_token_{tenant_id}_{project_id}_{name}",
        name=name,
        token_value=raw,
        token_hash=_token_hash(raw),
        token_masked=_mask_secret(raw),
        is_active=True,
        expires_at=_utcnow() + timedelta(days=TOKEN_TTL_DAYS),
        last_used_at=None,
        revoked_at=None,
        scope_json={"source": "ainerops"},
        created_by=actor,
        updated_by=actor,
    )
    db.add(row)
    db.flush()
    return row


def _ensure_token_row(db: Session, tenant_id: str, project_id: str, name: str) -> OpsBridgeToken:
    existing = _get_token_or_none(db, tenant_id=tenant_id, project_id=project_id, name=name)
    if existing:
        return existing
    return _create_token_row(db=db, tenant_id=tenant_id, project_id=project_id, name=name)


def _regenerate_token_row(row: OpsBridgeToken, actor: str = "studio-admin") -> OpsBridgeToken:
    raw = _build_new_token_value()
    now = _utcnow()
    row.token_value = raw
    row.token_hash = _token_hash(raw)
    row.token_masked = _mask_secret(raw)
    row.is_active = True
    row.expires_at = now + timedelta(days=TOKEN_TTL_DAYS)
    row.last_used_at = None
    row.revoked_at = None
    row.updated_by = actor
    row.updated_at = now
    row.retry_count = 0
    row.error_code = None
    row.error_message = None
    return row


def _to_token_response(row: OpsBridgeToken) -> OpsTokenResponse:
    now = _utcnow()
    days_remaining = max(0, int((row.expires_at - now).total_seconds() // 86400))
    return OpsTokenResponse(
        token_id=row.id,
        name=row.name,
        token_masked=row.token_masked or _mask_secret(row.token_value),
        is_active=bool(row.is_active) and row.revoked_at is None and row.expires_at > now,
        created_at=row.created_at,
        expires_at=row.expires_at,
        days_remaining=days_remaining,
        last_used_at=row.last_used_at,
    )


def _verify_ingress_token(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    raw_token: str,
) -> OpsBridgeToken:
    row = _ensure_token_row(db, tenant_id=tenant_id, project_id=project_id, name=DEFAULT_TOKEN_NAME)
    now = _utcnow()
    if not row.is_active or row.revoked_at is not None:
        raise HTTPException(status_code=401, detail="ops ingress token is inactive")
    if row.expires_at <= now:
        raise HTTPException(status_code=401, detail="ops ingress token expired")
    if not secrets.compare_digest(row.token_value, raw_token):
        raise HTTPException(status_code=401, detail="invalid ops ingress token")
    row.last_used_at = now
    row.updated_at = now
    return row


def _auto_match_provider(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    provider_name: str,
    endpoint_base_url: str | None,
) -> ModelProvider | None:
    providers = db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == tenant_id,
            ModelProvider.project_id == project_id,
            ModelProvider.deleted_at.is_(None),
        )
    ).scalars().all()
    if not providers:
        return None

    target_endpoint = _normalize_endpoint(endpoint_base_url)
    target_name = provider_name.strip().casefold()

    if target_endpoint:
        for item in providers:
            if _normalize_endpoint(item.endpoint) == target_endpoint:
                return item

    if target_name:
        for item in providers:
            if (item.name or "").strip().casefold() == target_name:
                return item
    return None


def _find_provider_by_name(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    name: str,
) -> ModelProvider | None:
    if not name.strip():
        return None
    return db.execute(
        select(ModelProvider).where(
            ModelProvider.tenant_id == tenant_id,
            ModelProvider.project_id == project_id,
            ModelProvider.name == name.strip(),
            ModelProvider.deleted_at.is_(None),
        )
    ).scalars().first()


def _ensure_local_provider_from_report(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    provider_key: str,
    provider_name: str,
    endpoint_base_url: str | None,
    capability_type: str,
    protocol: str,
) -> ModelProvider | None:
    matched = _auto_match_provider(
        db=db,
        tenant_id=tenant_id,
        project_id=project_id,
        provider_name=provider_name,
        endpoint_base_url=endpoint_base_url,
    )
    if matched:
        return matched

    display_name = provider_name.strip()
    key_name = provider_key.strip()
    capability_name = capability_type.strip()
    candidate_names = [
        display_name,
        key_name,
        f"{display_name}__{capability_name}" if display_name and capability_name else "",
        f"ops_{key_name}" if key_name else "",
    ]
    normalized_candidates: list[str] = []
    for item in candidate_names:
        val = item.strip()
        if not val:
            continue
        if val not in normalized_candidates:
            normalized_candidates.append(val[:120])

    for name in normalized_candidates:
        existing = _find_provider_by_name(
            db=db,
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
        )
        if existing is None:
            auth_mode = "none" if (protocol or "").strip().lower() == "none" else "api_key"
            row = ModelProvider(
                id=f"provider_{uuid4().hex}",
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_provider_ops_{uuid4().hex[:12]}",
                correlation_id=f"co_provider_ops_{uuid4().hex[:12]}",
                idempotency_key=f"idem_provider_ops_{provider_key}_{capability_type}",
                name=name,
                endpoint=endpoint_base_url,
                auth_mode=auth_mode,
                created_by="ops-bridge",
                updated_by="ops-bridge",
            )
            db.add(row)
            db.flush()
            return row

    return _auto_match_provider(
        db=db,
        tenant_id=tenant_id,
        project_id=project_id,
        provider_name=provider_name,
        endpoint_base_url=endpoint_base_url,
    )


def _build_report_row_response(db: Session, row: OpsProviderReport) -> OpsProviderRow:
    required_tier = str((CAPABILITY_STANDARDS.get(row.capability_type) or {}).get("min_required_tier", "low"))
    meets_minimum = TIER_ORDER.get(row.capability_tier, 0) >= TIER_ORDER.get(required_tier, 1)
    provider_name: str | None = None
    if row.matched_provider_id:
        provider_name = db.execute(
            select(ModelProvider.name).where(
                ModelProvider.id == row.matched_provider_id,
                ModelProvider.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
    mapping_summary: dict[str, Any] = {}
    raw_payload = row.raw_payload_json or {}
    if isinstance(raw_payload, dict):
        mapping_obj = raw_payload.get("mapping")
        if isinstance(mapping_obj, dict):
            mapping_summary = mapping_obj
    test_result = row.last_test_result_json if isinstance(row.last_test_result_json, dict) else {}
    connectivity_status = str(test_result.get("connectivity_status") or "untested")
    mapping_generated_at: datetime | None = None
    generated_at_raw = mapping_summary.get("generated_at")
    if isinstance(generated_at_raw, str) and generated_at_raw.strip():
        try:
            mapping_generated_at = datetime.fromisoformat(generated_at_raw.replace("Z", "+00:00"))
        except Exception:
            mapping_generated_at = None
    return OpsProviderRow(
        report_id=row.id,
        provider_key=row.provider_key,
        provider_name=row.provider_name,
        capability_type=row.capability_type,
        capability_tier=row.capability_tier,
        min_required_tier=required_tier,
        meets_minimum=meets_minimum,
        integration_status=row.integration_status,
        integration_status_label=_integration_status_label(row.integration_status),
        matched_provider_id=row.matched_provider_id,
        matched_provider_name=provider_name,
        endpoint_base_url=row.endpoint_base_url,
        protocol=row.protocol or "ainer-unified",
        openapi_url=row.openapi_url,
        model_catalog=list((row.model_catalog_json or [])[:_MAX_MODEL_CATALOG]),
        last_reported_at=row.last_reported_at,
        last_tested_at=row.last_tested_at,
        integration_notes=row.integration_notes,
        mapping_status=str(mapping_summary.get("status") or "pending"),
        mapping_confidence=mapping_summary.get("confidence"),
        request_coverage=mapping_summary.get("request_coverage"),
        response_coverage=mapping_summary.get("response_coverage"),
        feature_coverage=mapping_summary.get("feature_coverage"),
        mapping_gaps=list(mapping_summary.get("gaps") or []),
        mapping_generated_at=mapping_generated_at,
        connectivity_status=connectivity_status,
        connectivity_label=_connectivity_label(connectivity_status),
        last_connectivity_detail=test_result.get("detail"),
        last_checked_url=test_result.get("checked_url"),
        last_latency_ms=test_result.get("latency_ms"),
    )


def _assign_integration_status(
    *,
    row: OpsProviderReport,
    meets_minimum: bool,
    mapping_ready: bool,
) -> None:
    if row.matched_provider_id and meets_minimum and mapping_ready:
        row.integration_status = "integrated"
        return
    if row.matched_provider_id and (not meets_minimum or not mapping_ready):
        row.integration_status = "capability_gap"
        return
    row.integration_status = "unbound"


@router.get("/capability-standards", response_model=CapabilityStandardsResponse)
def get_capability_standards() -> CapabilityStandardsResponse:
    items = [
        CapabilityStandardItem(
            capability_type=capability_type,
            display_name=str(spec["display_name"]),
            track_targets=list(spec["track_targets"]),
            min_required_tier=str(spec["min_required_tier"]),
            tiers={
                "low": list(spec["tiers"]["low"]),
                "medium": list(spec["tiers"]["medium"]),
                "high": list(spec["tiers"]["high"]),
            },
        )
        for capability_type, spec in CAPABILITY_STANDARDS.items()
    ]
    return CapabilityStandardsResponse(
        supported_track_types=list(SUPPORTED_TRACK_TYPES),
        items=items,
    )


@router.get("/adapter-spec", response_model=AdapterSpecResponse)
def get_adapter_spec() -> AdapterSpecResponse:
    return AdapterSpecResponse(items=ADAPTER_SPEC)


@router.get("/storage-config", response_model=OpsStorageConfigResponse)
def get_storage_config() -> OpsStorageConfigResponse:
    endpoint = settings.s3_public_endpoint or settings.s3_endpoint
    provider = "minio" if settings.storage_backend.strip().lower() == "minio" else settings.storage_backend
    return OpsStorageConfigResponse(
        storage_backend=settings.storage_backend,
        provider=provider,
        endpoint=endpoint,
        internal_endpoint=settings.s3_endpoint,
        console_endpoint=settings.minio_console_endpoint or None,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        root_user=settings.minio_root_user,
        root_password=settings.minio_root_password,
        copy_env_block=_build_storage_env_block(),
    )


@router.put("/storage-config", response_model=OpsStorageConfigResponse)
def update_storage_config(payload: OpsStorageConfigUpdateRequest) -> OpsStorageConfigResponse:
    if not payload.endpoint.strip():
        raise HTTPException(status_code=400, detail="endpoint is required")
    if not payload.internal_endpoint.strip():
        raise HTTPException(status_code=400, detail="internal_endpoint is required")
    if not payload.bucket.strip():
        raise HTTPException(status_code=400, detail="bucket is required")
    if not payload.access_key.strip():
        raise HTTPException(status_code=400, detail="access_key is required")
    if not payload.secret_key.strip():
        raise HTTPException(status_code=400, detail="secret_key is required")
    if not payload.root_user.strip():
        raise HTTPException(status_code=400, detail="root_user is required")
    if not payload.root_password.strip():
        raise HTTPException(status_code=400, detail="root_password is required")

    _apply_storage_config_update(payload)
    return get_storage_config()


@router.get("/token", response_model=OpsTokenResponse)
def get_ops_token(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    name: str = Query(DEFAULT_TOKEN_NAME),
    db: Session = Depends(get_db),
) -> OpsTokenResponse:
    row = _ensure_token_row(db, tenant_id=tenant_id, project_id=project_id, name=name)
    db.commit()
    db.refresh(row)
    return _to_token_response(row)


@router.post("/token/reveal", response_model=OpsTokenRevealResponse)
def reveal_ops_token(
    payload: OpsTokenQuery,
    db: Session = Depends(get_db),
) -> OpsTokenRevealResponse:
    row = _ensure_token_row(db, tenant_id=payload.tenant_id, project_id=payload.project_id, name=payload.name)
    db.commit()
    db.refresh(row)
    return OpsTokenRevealResponse(
        token_id=row.id,
        name=row.name,
        token=row.token_value,
        expires_at=row.expires_at,
    )


@router.post("/token/regenerate", response_model=OpsTokenRevealResponse)
def regenerate_ops_token(
    payload: OpsTokenRegenerateRequest,
    db: Session = Depends(get_db),
) -> OpsTokenRevealResponse:
    row = _ensure_token_row(db, tenant_id=payload.tenant_id, project_id=payload.project_id, name=payload.name)
    _regenerate_token_row(row)
    db.commit()
    db.refresh(row)
    return OpsTokenRevealResponse(
        token_id=row.id,
        name=row.name,
        token=row.token_value,
        expires_at=row.expires_at,
    )


@router.post("/report", response_model=OpsProviderReportUpsertResponse)
def report_provider(
    payload: OpsProviderReportRequest,
    db: Session = Depends(get_db),
    ops_token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> OpsProviderReportUpsertResponse:
    if not ops_token or not ops_token.strip():
        raise HTTPException(status_code=401, detail=f"missing {TOKEN_HEADER} header")
    _verify_ingress_token(
        db=db,
        tenant_id=payload.tenant_id,
        project_id=payload.project_id,
        raw_token=ops_token.strip(),
    )

    capability_type = _normalize_capability(payload.capability_type)
    if capability_type not in CAPABILITY_STANDARDS:
        raise HTTPException(status_code=400, detail=f"unsupported capability_type: {payload.capability_type}")

    tier, missing_low_features = _evaluate_tier(capability_type, payload.features)
    required_tier = str(CAPABILITY_STANDARDS[capability_type]["min_required_tier"])
    meets_minimum = TIER_ORDER.get(tier, 0) >= TIER_ORDER.get(required_tier, 1)

    report = db.execute(
        select(OpsProviderReport).where(
            OpsProviderReport.tenant_id == payload.tenant_id,
            OpsProviderReport.project_id == payload.project_id,
            OpsProviderReport.provider_key == payload.provider_key,
            OpsProviderReport.capability_type == capability_type,
            OpsProviderReport.deleted_at.is_(None),
        )
    ).scalars().first()

    now = _utcnow()
    if report is None:
        report = OpsProviderReport(
            id=f"ops_pr_{uuid4().hex}",
            tenant_id=payload.tenant_id,
            project_id=payload.project_id,
            trace_id=None,
            correlation_id=None,
            idempotency_key=f"idem_ops_report_{payload.provider_key}_{capability_type}",
            provider_key=payload.provider_key,
            provider_name=payload.provider_name,
            capability_type=capability_type,
            protocol=payload.protocol or "ainer-unified",
            created_by="ainerops",
            updated_by="ainerops",
        )
        db.add(report)
        db.flush()

    report.provider_name = payload.provider_name
    report.endpoint_base_url = payload.endpoint_base_url
    report.protocol = payload.protocol or "ainer-unified"
    report.openapi_url = payload.openapi_url
    report.model_catalog_json = list(payload.model_catalog[:_MAX_MODEL_CATALOG])
    report.features_json = dict(payload.features)
    report.constraints_json = dict(payload.constraints)
    report.health_json = dict(payload.health)
    report.adapter_spec_json = dict(payload.adapter_spec)
    mapping_summary = _build_mapping_summary(
        capability_type=capability_type,
        features=dict(payload.features),
        adapter_spec=dict(payload.adapter_spec),
        openapi_url=payload.openapi_url,
        fetch_openapi=False,
    )

    report.raw_payload_json = {
        "metadata": payload.metadata,
        "reported_at": now.isoformat(),
        "mapping": mapping_summary,
    }
    report.capability_tier = tier
    report.last_reported_at = now
    report.updated_at = now
    report.updated_by = "ainerops"
    report.retry_count = 0
    report.error_code = None
    report.error_message = None

    if not report.matched_provider_id:
        provider = _ensure_local_provider_from_report(
            db=db,
            tenant_id=payload.tenant_id,
            project_id=payload.project_id,
            provider_key=payload.provider_key,
            provider_name=payload.provider_name,
            endpoint_base_url=payload.endpoint_base_url,
            capability_type=capability_type,
            protocol=payload.protocol or "ainer-unified",
        )
        report.matched_provider_id = provider.id if provider else None

    _assign_integration_status(
        row=report,
        meets_minimum=meets_minimum,
        mapping_ready=str(mapping_summary.get("status")) == "mapped",
    )
    db.commit()
    db.refresh(report)

    return OpsProviderReportUpsertResponse(
        report_id=report.id,
        provider_key=report.provider_key,
        capability_type=report.capability_type,
        capability_tier=report.capability_tier,
        integration_status=report.integration_status,
        matched_provider_id=report.matched_provider_id,
        meets_minimum=meets_minimum,
        adapter_gap_features=missing_low_features,
        mapping_status=str(mapping_summary.get("status") or "pending"),
        mapping_confidence=mapping_summary.get("confidence"),
        mapping_gaps=list(mapping_summary.get("gaps") or []),
    )


@router.get("/providers", response_model=OpsProviderListResponse)
def list_reported_providers(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    capability_type: str | None = Query(default=None),
    integration_status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> OpsProviderListResponse:
    stmt = select(OpsProviderReport).where(
        OpsProviderReport.tenant_id == tenant_id,
        OpsProviderReport.project_id == project_id,
        OpsProviderReport.deleted_at.is_(None),
    )
    if capability_type:
        stmt = stmt.where(OpsProviderReport.capability_type == _normalize_capability(capability_type))
    if integration_status:
        stmt = stmt.where(OpsProviderReport.integration_status == integration_status)
    stmt = stmt.order_by(
        func.coalesce(OpsProviderReport.last_reported_at, OpsProviderReport.updated_at).desc(),
        OpsProviderReport.created_at.desc(),
    )
    rows = db.execute(stmt).scalars().all()
    return OpsProviderListResponse(items=[_build_report_row_response(db, row) for row in rows])


@router.post("/providers/{report_id}/auto-bind", response_model=OpsProviderRow)
def auto_bind_reported_provider(
    report_id: str,
    db: Session = Depends(get_db),
) -> OpsProviderRow:
    row = db.get(OpsProviderReport, report_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="report not found")

    matched = _auto_match_provider(
        db=db,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        provider_name=row.provider_name,
        endpoint_base_url=row.endpoint_base_url,
    )
    if matched is None:
        matched = _ensure_local_provider_from_report(
            db=db,
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            provider_key=row.provider_key,
            provider_name=row.provider_name,
            endpoint_base_url=row.endpoint_base_url,
            capability_type=row.capability_type,
            protocol=row.protocol or "ainer-unified",
        )
    row.matched_provider_id = matched.id if matched else None
    mapping_summary = _build_mapping_summary(
        capability_type=row.capability_type,
        features=dict(row.features_json or {}),
        adapter_spec=dict(row.adapter_spec_json or {}),
        openapi_url=row.openapi_url,
        fetch_openapi=True,
    )
    raw_payload = dict(row.raw_payload_json or {})
    raw_payload["mapping"] = mapping_summary
    raw_payload["auto_bind_at"] = _utcnow().isoformat()
    row.raw_payload_json = raw_payload

    required_tier = str((CAPABILITY_STANDARDS.get(row.capability_type) or {}).get("min_required_tier", "low"))
    meets_minimum = TIER_ORDER.get(row.capability_tier, 0) >= TIER_ORDER.get(required_tier, 1)
    _assign_integration_status(
        row=row,
        meets_minimum=meets_minimum,
        mapping_ready=str(mapping_summary.get("status")) == "mapped",
    )
    row.integration_notes = (
        f"auto-bind: mapping={mapping_summary.get('status')} "
        f"confidence={mapping_summary.get('confidence')}"
    )
    row.updated_at = _utcnow()
    row.updated_by = "studio-admin"
    db.commit()
    db.refresh(row)
    return _build_report_row_response(db, row)


@router.post("/providers/{report_id}/manual-bind", response_model=OpsProviderRow)
def manual_bind_reported_provider(
    report_id: str,
    payload: OpsProviderManualBindRequest,
    db: Session = Depends(get_db),
) -> OpsProviderRow:
    row = db.get(OpsProviderReport, report_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="report not found")

    if payload.provider_id:
        provider = db.get(ModelProvider, payload.provider_id)
        if provider is None or provider.deleted_at is not None:
            raise HTTPException(status_code=404, detail="provider not found")
        if provider.tenant_id != row.tenant_id or provider.project_id != row.project_id:
            raise HTTPException(status_code=400, detail="provider scope mismatch")
        row.matched_provider_id = provider.id
    else:
        row.matched_provider_id = None

    if payload.integration_notes is not None:
        row.integration_notes = payload.integration_notes.strip() or None

    required_tier = str((CAPABILITY_STANDARDS.get(row.capability_type) or {}).get("min_required_tier", "low"))
    meets_minimum = TIER_ORDER.get(row.capability_tier, 0) >= TIER_ORDER.get(required_tier, 1)
    current_mapping = {}
    if isinstance(row.raw_payload_json, dict):
        mapping_obj = row.raw_payload_json.get("mapping")
        if isinstance(mapping_obj, dict):
            current_mapping = mapping_obj
    _assign_integration_status(
        row=row,
        meets_minimum=meets_minimum,
        mapping_ready=str(current_mapping.get("status")) == "mapped",
    )
    row.updated_at = _utcnow()
    row.updated_by = "studio-admin"
    db.commit()
    db.refresh(row)
    return _build_report_row_response(db, row)


@router.post("/providers/{report_id}/test", response_model=OpsProviderTestResponse)
def test_reported_provider(
    report_id: str,
    db: Session = Depends(get_db),
) -> OpsProviderTestResponse:
    row = db.get(OpsProviderReport, report_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="report not found")

    endpoint = row.endpoint_base_url
    if not endpoint and row.matched_provider_id:
        provider = db.get(ModelProvider, row.matched_provider_id)
        endpoint = provider.endpoint if provider else None

    candidates: list[str] = []
    seen: set[str] = set()

    def _push_candidate(url: str | None) -> None:
        if not url or not str(url).strip():
            return
        key = str(url).strip()
        if key in seen:
            return
        seen.add(key)
        candidates.append(key)

    if endpoint and endpoint.strip():
        base = endpoint.strip().rstrip("/")
        _push_candidate(base)
        if not base.endswith("/healthz"):
            _push_candidate(f"{base}/healthz")
        if not base.endswith("/health"):
            _push_candidate(f"{base}/health")
    _push_candidate(row.openapi_url)

    if not candidates:
        raise HTTPException(status_code=400, detail="missing endpoint to test")

    ok = False
    status = "disconnected"
    detail = "all probes failed"
    checked_url: str | None = None
    latency_ms: int | None = None

    for candidate in candidates:
        try:
            start = perf_counter()
            with httpx.Client(timeout=_TEST_TIMEOUT_SEC) as client:
                resp = client.get(candidate)
            elapsed = int((perf_counter() - start) * 1000)
            checked_url = candidate
            latency_ms = elapsed
            if resp.status_code < 500:
                ok = True
                status = "connected"
                detail = f"HTTP {resp.status_code}"
                break
            detail = f"HTTP {resp.status_code}"
        except Exception as exc:
            checked_url = candidate
            detail = str(exc)

    row.last_tested_at = _utcnow()
    row.last_test_result_json = {
        "ok": ok,
        "status": status,
        "connectivity_status": status,
        "detail": detail,
        "checked_url": checked_url,
        "latency_ms": latency_ms,
    }
    row.updated_at = _utcnow()
    row.updated_by = "studio-admin"
    db.commit()

    return OpsProviderTestResponse(
        report_id=row.id,
        ok=ok,
        status=status,
        latency_ms=latency_ms,
        detail=detail,
        checked_url=checked_url,
        connectivity_status=status,
    )
