"""SKILL 33 — Prompt Assets API.

Endpoints:
  Semantic Assets:       GET/POST /prompt-assets, GET/PATCH /prompt-assets/{id}
  Character Stages:      GET/POST /characters/{entity_id}/stages, PATCH /character-stages/{id}
  Shot Asset Bindings:   GET /chapters/{chapter_id}/shot-asset-bindings
                         POST /shots/{shot_id}/asset-bindings, PATCH /shot-asset-bindings/{id}
  Prompt Snapshots:      GET/POST /shots/{shot_id}/prompt-snapshots, GET /prompt-snapshots/{id}
  Consistency Check:     POST /prompt-assets/consistency-check
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Chapter, Shot
from ainern2d_shared.ainer_db_models.knowledge_models import Entity
from ainern2d_shared.ainer_db_models.preview_models import EntityContinuityProfile
from ainern2d_shared.ainer_db_models.prompt_asset_models import (
    CharacterStageProfile,
    PromptSnapshot,
    SemanticAsset,
    ShotAssetBinding,
)

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["prompt-assets"])

_NOW = lambda: datetime.now(timezone.utc)
_ID = lambda prefix: f"{prefix}_{uuid4().hex[:24]}"


# ═══════════════════════════════════════════════════════════════════════════════
# Request / Response Models
# ═══════════════════════════════════════════════════════════════════════════════

# ── Semantic Asset ────────────────────────────────────────────────────────────

class SemanticAssetCreate(BaseModel):
    tenant_id: str
    project_id: str
    novel_id: str
    entity_id: str | None = None
    asset_type: str  # costume/expression/action/prop/scene/mood_camera/prompt_template
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    structured: dict[str, Any] = Field(default_factory=dict)
    prompt: dict[str, Any] = Field(default_factory=dict)
    negative_prompt: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class SemanticAssetPatch(BaseModel):
    canonical_name: str | None = None
    aliases: list[str] | None = None
    tags: list[str] | None = None
    status: str | None = None
    structured: dict[str, Any] | None = None
    prompt: dict[str, Any] | None = None
    negative_prompt: dict[str, Any] | None = None
    is_active: bool | None = None
    meta: dict[str, Any] | None = None


class SemanticAssetResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    novel_id: str
    entity_id: str | None = None
    asset_type: str
    canonical_name: str
    aliases: list[str] = []
    tags: list[str] = []
    status: str = "draft"
    structured: dict[str, Any] = {}
    prompt: dict[str, Any] = {}
    negative_prompt: dict[str, Any] = {}
    is_active: bool = True
    meta: dict[str, Any] = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Character Stage ───────────────────────────────────────────────────────────

class CharacterStageCreate(BaseModel):
    tenant_id: str
    project_id: str
    novel_id: str
    stage_name: str
    chapter_start: int = 1
    chapter_end: int | None = None
    appearance_override: dict[str, Any] = Field(default_factory=dict)
    temperament_override: dict[str, Any] = Field(default_factory=dict)
    default_costume_asset_id: str | None = None
    default_prop_asset_ids: list[str] = Field(default_factory=list)
    emotional_baseline: dict[str, Any] = Field(default_factory=dict)
    status_tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class CharacterStagePatch(BaseModel):
    stage_name: str | None = None
    chapter_start: int | None = None
    chapter_end: int | None = None
    appearance_override: dict[str, Any] | None = None
    temperament_override: dict[str, Any] | None = None
    default_costume_asset_id: str | None = None
    default_prop_asset_ids: list[str] | None = None
    emotional_baseline: dict[str, Any] | None = None
    status_tags: list[str] | None = None
    notes: str | None = None
    meta: dict[str, Any] | None = None


class CharacterStageResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    novel_id: str
    entity_id: str
    stage_name: str
    chapter_start: int
    chapter_end: int | None = None
    appearance_override: dict[str, Any] = {}
    temperament_override: dict[str, Any] = {}
    default_costume_asset_id: str | None = None
    default_prop_asset_ids: list[str] = []
    emotional_baseline: dict[str, Any] = {}
    status_tags: list[str] = []
    notes: str | None = None
    meta: dict[str, Any] = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Shot Asset Binding ────────────────────────────────────────────────────────

class ShotAssetBindingCreate(BaseModel):
    tenant_id: str
    project_id: str
    chapter_id: str
    scene_id: str | None = None
    run_id: str | None = None
    entity_id: str | None = None
    binding_role: str = "subject"
    stage_profile_id: str | None = None
    selected_asset_ids: list[str] = Field(default_factory=list)
    state_override: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class ShotAssetBindingPatch(BaseModel):
    binding_role: str | None = None
    stage_profile_id: str | None = None
    selected_asset_ids: list[str] | None = None
    state_override: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None


class ShotAssetBindingResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    run_id: str | None = None
    chapter_id: str
    scene_id: str | None = None
    shot_id: str
    entity_id: str | None = None
    binding_role: str
    stage_profile_id: str | None = None
    selected_asset_ids: list[str] = []
    state_override: dict[str, Any] = {}
    prompt_snapshot_id: str | None = None
    meta: dict[str, Any] = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Prompt Snapshot ───────────────────────────────────────────────────────────

class PromptSnapshotCreate(BaseModel):
    tenant_id: str
    project_id: str
    chapter_id: str
    scene_id: str | None = None
    run_id: str | None = None
    entity_id: str | None = None
    source_type: str = "manual"
    merged_prompt_text: str = ""
    merged_negative_prompt_text: str | None = None
    merged_json: dict[str, Any] = Field(default_factory=dict)
    generation_params: dict[str, Any] = Field(default_factory=dict)
    regenerate_parent_snapshot_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class PromptSnapshotResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    run_id: str | None = None
    chapter_id: str
    scene_id: str | None = None
    shot_id: str
    entity_id: str | None = None
    source_type: str
    source_id: str | None = None
    merged_prompt_text: str
    merged_negative_prompt_text: str | None = None
    merged_json: dict[str, Any] = {}
    generation_params: dict[str, Any] = {}
    consistency_hash: str | None = None
    regenerate_parent_snapshot_id: str | None = None
    meta: dict[str, Any] = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Consistency Check ─────────────────────────────────────────────────────────

class ConsistencyCheckRequest(BaseModel):
    tenant_id: str
    project_id: str
    novel_id: str
    chapter_ids: list[str] = Field(default_factory=list)


class ConsistencyViolation(BaseModel):
    item_type: str
    entity_id: str = ""
    shot_id: str = ""
    description: str = ""
    severity: str = "warning"


class ConsistencyCheckResponse(BaseModel):
    status: str
    violations: list[ConsistencyViolation] = []
    checked_entities: int = 0
    checked_bindings: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════════════════

def _to_asset_response(a: SemanticAsset) -> SemanticAssetResponse:
    return SemanticAssetResponse(
        id=a.id,
        tenant_id=a.tenant_id,
        project_id=a.project_id,
        novel_id=a.novel_id,
        entity_id=a.entity_id,
        asset_type=a.asset_type,
        canonical_name=a.canonical_name,
        aliases=a.aliases_json or [],
        tags=a.tags_json or [],
        status=a.status,
        structured=a.structured_json or {},
        prompt=a.prompt_json or {},
        negative_prompt=a.negative_prompt_json or {},
        is_active=a.is_active,
        meta=a.meta_json or {},
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def _to_stage_response(s: CharacterStageProfile) -> CharacterStageResponse:
    return CharacterStageResponse(
        id=s.id,
        tenant_id=s.tenant_id,
        project_id=s.project_id,
        novel_id=s.novel_id,
        entity_id=s.entity_id,
        stage_name=s.stage_name,
        chapter_start=s.chapter_start,
        chapter_end=s.chapter_end,
        appearance_override=s.appearance_override_json or {},
        temperament_override=s.temperament_override_json or {},
        default_costume_asset_id=s.default_costume_asset_id,
        default_prop_asset_ids=s.default_prop_asset_ids_json or [],
        emotional_baseline=s.emotional_baseline_json or {},
        status_tags=s.status_tags_json or [],
        notes=s.notes,
        meta=s.meta_json or {},
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _to_binding_response(b: ShotAssetBinding) -> ShotAssetBindingResponse:
    return ShotAssetBindingResponse(
        id=b.id,
        tenant_id=b.tenant_id,
        project_id=b.project_id,
        run_id=b.run_id,
        chapter_id=b.chapter_id,
        scene_id=b.scene_id,
        shot_id=b.shot_id,
        entity_id=b.entity_id,
        binding_role=b.binding_role,
        stage_profile_id=b.stage_profile_id,
        selected_asset_ids=b.selected_asset_ids_json or [],
        state_override=b.state_override_json or {},
        prompt_snapshot_id=b.prompt_snapshot_id,
        meta=b.meta_json or {},
        created_at=b.created_at,
        updated_at=b.updated_at,
    )


def _to_snapshot_response(s: PromptSnapshot) -> PromptSnapshotResponse:
    return PromptSnapshotResponse(
        id=s.id,
        tenant_id=s.tenant_id,
        project_id=s.project_id,
        run_id=s.run_id,
        chapter_id=s.chapter_id,
        scene_id=s.scene_id,
        shot_id=s.shot_id,
        entity_id=s.entity_id,
        source_type=s.source_type,
        source_id=s.source_id,
        merged_prompt_text=s.merged_prompt_text,
        merged_negative_prompt_text=s.merged_negative_prompt_text,
        merged_json=s.merged_json or {},
        generation_params=s.generation_params_json or {},
        consistency_hash=s.consistency_hash,
        regenerate_parent_snapshot_id=s.regenerate_parent_snapshot_id,
        meta=s.meta_json or {},
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1) Semantic Assets
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/prompt-assets", response_model=list[SemanticAssetResponse])
def list_prompt_assets(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    novel_id: str | None = Query(None),
    asset_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[SemanticAssetResponse]:
    stmt = (
        select(SemanticAsset)
        .where(
            SemanticAsset.tenant_id == tenant_id,
            SemanticAsset.project_id == project_id,
            SemanticAsset.deleted_at.is_(None),
        )
        .order_by(SemanticAsset.created_at.desc())
    )
    if novel_id:
        stmt = stmt.where(SemanticAsset.novel_id == novel_id)
    if asset_type:
        stmt = stmt.where(SemanticAsset.asset_type == asset_type)
    if entity_id:
        stmt = stmt.where(SemanticAsset.entity_id == entity_id)
    rows = db.execute(stmt).scalars().all()
    return [_to_asset_response(r) for r in rows]


@router.post("/prompt-assets", response_model=SemanticAssetResponse, status_code=201)
def create_prompt_asset(
    body: SemanticAssetCreate,
    db: Session = Depends(get_db),
) -> SemanticAssetResponse:
    now = _NOW()
    asset = SemanticAsset(
        id=_ID("sa"),
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        novel_id=body.novel_id,
        entity_id=body.entity_id,
        asset_type=body.asset_type,
        canonical_name=body.canonical_name,
        aliases_json=body.aliases or [],
        tags_json=body.tags or [],
        status="draft",
        structured_json=body.structured,
        prompt_json=body.prompt,
        negative_prompt_json=body.negative_prompt,
        is_active=True,
        meta_json=body.meta,
        created_at=now,
        updated_at=now,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _to_asset_response(asset)


@router.get("/prompt-assets/{asset_id}", response_model=SemanticAssetResponse)
def get_prompt_asset(asset_id: str, db: Session = Depends(get_db)) -> SemanticAssetResponse:
    asset = db.get(SemanticAsset, asset_id)
    if not asset or asset.deleted_at is not None:
        raise HTTPException(404, "asset not found")
    return _to_asset_response(asset)


@router.patch("/prompt-assets/{asset_id}", response_model=SemanticAssetResponse)
def patch_prompt_asset(
    asset_id: str,
    body: SemanticAssetPatch,
    db: Session = Depends(get_db),
) -> SemanticAssetResponse:
    asset = db.get(SemanticAsset, asset_id)
    if not asset or asset.deleted_at is not None:
        raise HTTPException(404, "asset not found")
    if body.canonical_name is not None:
        asset.canonical_name = body.canonical_name
    if body.aliases is not None:
        asset.aliases_json = body.aliases
    if body.tags is not None:
        asset.tags_json = body.tags
    if body.status is not None:
        asset.status = body.status
    if body.structured is not None:
        asset.structured_json = body.structured
    if body.prompt is not None:
        asset.prompt_json = body.prompt
    if body.negative_prompt is not None:
        asset.negative_prompt_json = body.negative_prompt
    if body.is_active is not None:
        asset.is_active = body.is_active
    if body.meta is not None:
        asset.meta_json = body.meta
    asset.updated_at = _NOW()
    db.commit()
    db.refresh(asset)
    return _to_asset_response(asset)


# ═══════════════════════════════════════════════════════════════════════════════
# 2) Character Stages
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/characters/{entity_id}/stages", response_model=list[CharacterStageResponse])
def list_character_stages(
    entity_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[CharacterStageResponse]:
    stmt = (
        select(CharacterStageProfile)
        .where(
            CharacterStageProfile.tenant_id == tenant_id,
            CharacterStageProfile.project_id == project_id,
            CharacterStageProfile.entity_id == entity_id,
            CharacterStageProfile.deleted_at.is_(None),
        )
        .order_by(CharacterStageProfile.chapter_start)
    )
    rows = db.execute(stmt).scalars().all()
    return [_to_stage_response(r) for r in rows]


@router.post("/characters/{entity_id}/stages", response_model=CharacterStageResponse, status_code=201)
def create_character_stage(
    entity_id: str,
    body: CharacterStageCreate,
    db: Session = Depends(get_db),
) -> CharacterStageResponse:
    entity = db.get(Entity, entity_id)
    if not entity or entity.deleted_at is not None:
        raise HTTPException(404, "entity not found")
    now = _NOW()
    stage = CharacterStageProfile(
        id=_ID("csp"),
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        novel_id=body.novel_id,
        entity_id=entity_id,
        stage_name=body.stage_name,
        chapter_start=body.chapter_start,
        chapter_end=body.chapter_end,
        appearance_override_json=body.appearance_override,
        temperament_override_json=body.temperament_override,
        default_costume_asset_id=body.default_costume_asset_id,
        default_prop_asset_ids_json=body.default_prop_asset_ids,
        emotional_baseline_json=body.emotional_baseline,
        status_tags_json=body.status_tags,
        notes=body.notes,
        meta_json=body.meta,
        created_at=now,
        updated_at=now,
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return _to_stage_response(stage)


@router.patch("/character-stages/{stage_id}", response_model=CharacterStageResponse)
def patch_character_stage(
    stage_id: str,
    body: CharacterStagePatch,
    db: Session = Depends(get_db),
) -> CharacterStageResponse:
    stage = db.get(CharacterStageProfile, stage_id)
    if not stage or stage.deleted_at is not None:
        raise HTTPException(404, "stage not found")
    if body.stage_name is not None:
        stage.stage_name = body.stage_name
    if body.chapter_start is not None:
        stage.chapter_start = body.chapter_start
    if body.chapter_end is not None:
        stage.chapter_end = body.chapter_end
    if body.appearance_override is not None:
        stage.appearance_override_json = body.appearance_override
    if body.temperament_override is not None:
        stage.temperament_override_json = body.temperament_override
    if body.default_costume_asset_id is not None:
        stage.default_costume_asset_id = body.default_costume_asset_id
    if body.default_prop_asset_ids is not None:
        stage.default_prop_asset_ids_json = body.default_prop_asset_ids
    if body.emotional_baseline is not None:
        stage.emotional_baseline_json = body.emotional_baseline
    if body.status_tags is not None:
        stage.status_tags_json = body.status_tags
    if body.notes is not None:
        stage.notes = body.notes
    if body.meta is not None:
        stage.meta_json = body.meta
    stage.updated_at = _NOW()
    db.commit()
    db.refresh(stage)
    return _to_stage_response(stage)


# ═══════════════════════════════════════════════════════════════════════════════
# 3) Shot Asset Bindings
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/chapters/{chapter_id}/shot-asset-bindings", response_model=list[ShotAssetBindingResponse])
def list_shot_asset_bindings(
    chapter_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    shot_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[ShotAssetBindingResponse]:
    stmt = (
        select(ShotAssetBinding)
        .where(
            ShotAssetBinding.tenant_id == tenant_id,
            ShotAssetBinding.project_id == project_id,
            ShotAssetBinding.chapter_id == chapter_id,
            ShotAssetBinding.deleted_at.is_(None),
        )
        .order_by(ShotAssetBinding.created_at)
    )
    if shot_id:
        stmt = stmt.where(ShotAssetBinding.shot_id == shot_id)
    rows = db.execute(stmt).scalars().all()
    return [_to_binding_response(r) for r in rows]


@router.post("/shots/{shot_id}/asset-bindings", response_model=ShotAssetBindingResponse, status_code=201)
def create_shot_asset_binding(
    shot_id: str,
    body: ShotAssetBindingCreate,
    db: Session = Depends(get_db),
) -> ShotAssetBindingResponse:
    shot = db.get(Shot, shot_id)
    if not shot or shot.deleted_at is not None:
        raise HTTPException(404, "shot not found")
    now = _NOW()
    binding = ShotAssetBinding(
        id=_ID("sab"),
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        run_id=body.run_id,
        chapter_id=body.chapter_id,
        scene_id=body.scene_id,
        shot_id=shot_id,
        entity_id=body.entity_id,
        binding_role=body.binding_role,
        stage_profile_id=body.stage_profile_id,
        selected_asset_ids_json=body.selected_asset_ids,
        state_override_json=body.state_override,
        meta_json=body.meta,
        created_at=now,
        updated_at=now,
    )
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return _to_binding_response(binding)


@router.patch("/shot-asset-bindings/{binding_id}", response_model=ShotAssetBindingResponse)
def patch_shot_asset_binding(
    binding_id: str,
    body: ShotAssetBindingPatch,
    db: Session = Depends(get_db),
) -> ShotAssetBindingResponse:
    binding = db.get(ShotAssetBinding, binding_id)
    if not binding or binding.deleted_at is not None:
        raise HTTPException(404, "binding not found")
    if body.binding_role is not None:
        binding.binding_role = body.binding_role
    if body.stage_profile_id is not None:
        binding.stage_profile_id = body.stage_profile_id
    if body.selected_asset_ids is not None:
        binding.selected_asset_ids_json = body.selected_asset_ids
    if body.state_override is not None:
        binding.state_override_json = body.state_override
    if body.meta is not None:
        binding.meta_json = body.meta
    binding.updated_at = _NOW()
    db.commit()
    db.refresh(binding)
    return _to_binding_response(binding)


# ═══════════════════════════════════════════════════════════════════════════════
# 4) Prompt Snapshots
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/shots/{shot_id}/prompt-snapshots", response_model=list[PromptSnapshotResponse])
def list_prompt_snapshots(
    shot_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[PromptSnapshotResponse]:
    stmt = (
        select(PromptSnapshot)
        .where(
            PromptSnapshot.tenant_id == tenant_id,
            PromptSnapshot.project_id == project_id,
            PromptSnapshot.shot_id == shot_id,
            PromptSnapshot.deleted_at.is_(None),
        )
        .order_by(PromptSnapshot.created_at.desc())
    )
    rows = db.execute(stmt).scalars().all()
    return [_to_snapshot_response(r) for r in rows]


@router.post("/shots/{shot_id}/prompt-snapshots", response_model=PromptSnapshotResponse, status_code=201)
def create_prompt_snapshot(
    shot_id: str,
    body: PromptSnapshotCreate,
    db: Session = Depends(get_db),
) -> PromptSnapshotResponse:
    shot = db.get(Shot, shot_id)
    if not shot or shot.deleted_at is not None:
        raise HTTPException(404, "shot not found")
    now = _NOW()
    c_hash = hashlib.sha256(
        f"{body.merged_prompt_text}|{body.merged_negative_prompt_text or ''}".encode()
    ).hexdigest()[:32]
    snapshot = PromptSnapshot(
        id=_ID("ps"),
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        run_id=body.run_id,
        chapter_id=body.chapter_id,
        scene_id=body.scene_id,
        shot_id=shot_id,
        entity_id=body.entity_id,
        source_type=body.source_type,
        merged_prompt_text=body.merged_prompt_text,
        merged_negative_prompt_text=body.merged_negative_prompt_text,
        merged_json=body.merged_json,
        generation_params_json=body.generation_params,
        consistency_hash=c_hash,
        regenerate_parent_snapshot_id=body.regenerate_parent_snapshot_id,
        meta_json=body.meta,
        created_at=now,
        updated_at=now,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return _to_snapshot_response(snapshot)


@router.get("/prompt-snapshots/{snapshot_id}", response_model=PromptSnapshotResponse)
def get_prompt_snapshot(snapshot_id: str, db: Session = Depends(get_db)) -> PromptSnapshotResponse:
    snapshot = db.get(PromptSnapshot, snapshot_id)
    if not snapshot or snapshot.deleted_at is not None:
        raise HTTPException(404, "snapshot not found")
    return _to_snapshot_response(snapshot)


# ═══════════════════════════════════════════════════════════════════════════════
# 5) Consistency Check
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/prompt-assets/consistency-check", response_model=ConsistencyCheckResponse)
def consistency_check(
    body: ConsistencyCheckRequest,
    db: Session = Depends(get_db),
) -> ConsistencyCheckResponse:
    """Check forbidden/must_not rules across shot bindings for given novel."""
    violations: list[ConsistencyViolation] = []

    # Load entities
    entity_stmt = (
        select(Entity)
        .where(
            Entity.tenant_id == body.tenant_id,
            Entity.project_id == body.project_id,
            Entity.novel_id == body.novel_id,
            Entity.deleted_at.is_(None),
        )
    )
    entities = {e.id: e for e in db.execute(entity_stmt).scalars().all()}

    # Load continuity profiles for forbidden/must_not rules
    profile_stmt = select(EntityContinuityProfile).where(
        EntityContinuityProfile.tenant_id == body.tenant_id,
        EntityContinuityProfile.project_id == body.project_id,
        EntityContinuityProfile.entity_id.in_(list(entities.keys())),
    )
    profiles = {p.entity_id: p for p in db.execute(profile_stmt).scalars().all()}

    # Load chapters
    ch_stmt = (
        select(Chapter)
        .where(
            Chapter.tenant_id == body.tenant_id,
            Chapter.project_id == body.project_id,
            Chapter.novel_id == body.novel_id,
            Chapter.deleted_at.is_(None),
        )
    )
    if body.chapter_ids:
        ch_stmt = ch_stmt.where(Chapter.id.in_(body.chapter_ids))
    chapters = list(db.execute(ch_stmt).scalars().all())
    chapter_ids = [c.id for c in chapters]

    # Load bindings
    bind_stmt = (
        select(ShotAssetBinding)
        .where(
            ShotAssetBinding.tenant_id == body.tenant_id,
            ShotAssetBinding.project_id == body.project_id,
            ShotAssetBinding.chapter_id.in_(chapter_ids),
            ShotAssetBinding.deleted_at.is_(None),
        )
    )
    bindings = list(db.execute(bind_stmt).scalars().all())

    # Load all referenced assets
    all_asset_ids: set[str] = set()
    for b in bindings:
        for aid in (b.selected_asset_ids_json or []):
            all_asset_ids.add(aid)
    asset_map: dict[str, SemanticAsset] = {}
    if all_asset_ids:
        a_stmt = select(SemanticAsset).where(SemanticAsset.id.in_(list(all_asset_ids)))
        asset_map = {a.id: a for a in db.execute(a_stmt).scalars().all()}

    # Check each binding
    for binding in bindings:
        entity_id = binding.entity_id or ""
        profile = profiles.get(entity_id)
        if not profile:
            continue
        rules = profile.rules_json or {}
        forbidden_list = rules.get("forbidden", [])
        must_not_list = rules.get("must_not", [])

        for aid in (binding.selected_asset_ids_json or []):
            asset = asset_map.get(aid)
            if not asset:
                continue
            for f_item in forbidden_list:
                f_lower = f_item.lower()
                name_lower = asset.canonical_name.lower()
                tags_lower = [t.lower() for t in (asset.tags_json or [])]
                if f_lower in name_lower or f_lower in tags_lower:
                    violations.append(ConsistencyViolation(
                        item_type="forbidden_hit",
                        entity_id=entity_id,
                        shot_id=binding.shot_id,
                        description=f"Asset '{asset.canonical_name}' matches forbidden '{f_item}'",
                        severity="error",
                    ))

        override_str = str(binding.state_override_json or {}).lower()
        for m_item in must_not_list:
            if m_item.lower() in override_str:
                violations.append(ConsistencyViolation(
                    item_type="must_not_violation",
                    entity_id=entity_id,
                    shot_id=binding.shot_id,
                    description=f"Override contains must_not '{m_item}'",
                    severity="error",
                ))

    return ConsistencyCheckResponse(
        status="review_required" if violations else "consistent",
        violations=violations,
        checked_entities=len(entities),
        checked_bindings=len(bindings),
    )
