from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Artifact, Scene, Shot
from ainern2d_shared.ainer_db_models.knowledge_models import Entity
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun, WorkflowEvent
from ainern2d_shared.ainer_db_models.preview_models import (
    EntityContinuityProfile,
    EntityInstanceLink,
    EntityPreviewVariant,
)
from ainern2d_shared.schemas.artifact import ArtifactResponse

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["assets"])


class ProjectAssetItem(BaseModel):
    id: str
    run_id: str
    chapter_id: str | None = None
    shot_id: str | None = None
    type: str
    uri: str
    size_bytes: int | None = None
    checksum: str | None = None
    meta_info: dict = Field(default_factory=dict)
    anchored: bool = False


class AssetAnchorRequest(BaseModel):
    tenant_id: str
    project_id: str
    entity_id: str | None = None
    anchor_name: str = "default"
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class AssetAnchorResponse(BaseModel):
    asset_id: str
    run_id: str
    project_id: str
    anchored: bool
    anchor_info: dict = Field(default_factory=dict)
    continuity_profile_id: str | None = None


class AnchoredAssetItem(BaseModel):
    asset_id: str
    run_id: str
    shot_id: str | None = None
    uri: str
    anchor_info: dict = Field(default_factory=dict)


class AssetBindingConsistencyItem(BaseModel):
    entity_id: str
    entity_name: str
    entity_type: str
    chapter_id: str | None = None
    run_id: str | None = None
    shot_id: str | None = None
    scene_id: str | None = None
    scene_label: str | None = None
    continuity_status: str = "draft"
    locked_preview_variant_id: str | None = None
    latest_preview_variant_id: str | None = None
    latest_preview_status: str | None = None
    locked_asset_id: str | None = None
    locked_asset_uri: str | None = None
    latest_asset_id: str | None = None
    latest_asset_uri: str | None = None
    anchor_name: str | None = None
    anchor_notes: str | None = None


def _to_response(a: Artifact) -> ArtifactResponse:
    return ArtifactResponse(
        id=a.id,
        run_id=a.run_id or "",
        shot_id=a.shot_id,
        type=a.type.value if a.type else "unknown",
        uri=a.uri,
        size_bytes=a.size_bytes,
        checksum=a.checksum,
        meta_info=a.media_meta_json,
    )


@router.get("/assets/{asset_id}", response_model=ArtifactResponse)
def get_asset(asset_id: str, db: Session = Depends(get_db)) -> ArtifactResponse:
    artifact = db.get(Artifact, asset_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return _to_response(artifact)


@router.get("/runs/{run_id}/assets", response_model=list[ArtifactResponse])
def list_run_assets(run_id: str, db: Session = Depends(get_db)) -> list[ArtifactResponse]:
    stmt = (
        select(Artifact)
        .filter_by(run_id=run_id, deleted_at=None)
        .order_by(Artifact.created_at.asc())
    )
    rows = db.execute(stmt).scalars().all()
    return [_to_response(a) for a in rows]


@router.get("/projects/{project_id}/assets", response_model=list[ProjectAssetItem])
def list_project_assets(
    project_id: str,
    tenant_id: str = Query(...),
    chapter_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    shot_id: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    anchored: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ProjectAssetItem]:
    stmt = select(Artifact).where(
        Artifact.tenant_id == tenant_id,
        Artifact.project_id == project_id,
        Artifact.deleted_at.is_(None),
    )
    if run_id:
        stmt = stmt.where(Artifact.run_id == run_id)
    if shot_id:
        stmt = stmt.where(Artifact.shot_id == shot_id)
    if asset_type:
        stmt = stmt.where(Artifact.type == asset_type)

    rows = db.execute(stmt.order_by(Artifact.created_at.desc())).scalars().all()

    run_map: dict[str, RenderRun] = {}
    run_ids = [row.run_id for row in rows if row.run_id]
    if run_ids:
        run_rows = db.execute(select(RenderRun).where(RenderRun.id.in_(run_ids))).scalars().all()
        run_map = {run_row.id: run_row for run_row in run_rows}

    items: list[ProjectAssetItem] = []
    for row in rows:
        linked_run = run_map.get(row.run_id or "")
        linked_chapter_id = linked_run.chapter_id if linked_run else None
        if chapter_id and linked_chapter_id != chapter_id:
            continue
        anchor_info = ((row.media_meta_json or {}).get("anchor") or {})
        if keyword:
            search = keyword.strip().lower()
            if search not in (row.id or "").lower() and search not in (row.uri or "").lower() and search not in str(
                row.type
            ).lower():
                continue
        if anchored is not None and bool(anchor_info) != anchored:
            continue
        items.append(
            ProjectAssetItem(
                id=row.id,
                run_id=row.run_id or "",
                chapter_id=linked_chapter_id,
                shot_id=row.shot_id,
                type=row.type.value if hasattr(row.type, "value") else str(row.type),
                uri=row.uri,
                size_bytes=row.size_bytes,
                checksum=row.checksum,
                meta_info=row.media_meta_json or {},
                anchored=bool(anchor_info),
            )
        )
    return items


def _normalize_entity_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    aliases = {
        "scene": "place",
        "prop": "item",
        "character": "person",
    }
    return aliases.get(normalized, normalized)


@router.get("/projects/{project_id}/asset-bindings", response_model=list[AssetBindingConsistencyItem])
def list_asset_binding_consistency(
    project_id: str,
    tenant_id: str = Query(...),
    chapter_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[AssetBindingConsistencyItem]:
    link_stmt = (
        select(EntityInstanceLink)
        .where(
            EntityInstanceLink.tenant_id == tenant_id,
            EntityInstanceLink.project_id == project_id,
            EntityInstanceLink.deleted_at.is_(None),
        )
        .order_by(EntityInstanceLink.updated_at.desc(), EntityInstanceLink.created_at.desc())
    )
    if run_id:
        link_stmt = link_stmt.where(EntityInstanceLink.run_id == run_id)
    links = db.execute(link_stmt).scalars().all()

    artifact_stmt = (
        select(Artifact)
        .where(
            Artifact.tenant_id == tenant_id,
            Artifact.project_id == project_id,
            Artifact.deleted_at.is_(None),
        )
        .order_by(Artifact.updated_at.desc(), Artifact.created_at.desc())
    )
    if run_id:
        artifact_stmt = artifact_stmt.where(Artifact.run_id == run_id)
    artifacts = db.execute(artifact_stmt).scalars().all()

    run_ids: set[str] = {
        link.run_id for link in links if link.run_id
    } | {
        artifact.run_id for artifact in artifacts if artifact.run_id
    }
    runs = (
        db.execute(select(RenderRun).where(RenderRun.id.in_(run_ids))).scalars().all()
        if run_ids
        else []
    )
    run_map = {row.id: row for row in runs}

    shot_ids: set[str] = {
        link.shot_id for link in links if link.shot_id
    } | {
        artifact.shot_id for artifact in artifacts if artifact.shot_id
    }
    shots = (
        db.execute(select(Shot).where(Shot.id.in_(shot_ids))).scalars().all()
        if shot_ids
        else []
    )
    shot_map = {row.id: row for row in shots}

    filtered_links: list[EntityInstanceLink] = []
    for link in links:
        if chapter_id:
            shot = shot_map.get(link.shot_id or "")
            linked_run = run_map.get(link.run_id)
            linked_chapter_id = shot.chapter_id if shot else (linked_run.chapter_id if linked_run else None)
            if linked_chapter_id != chapter_id:
                continue
        filtered_links.append(link)
    links = filtered_links

    entity_ids: set[str] = {link.entity_id for link in links}
    anchored_asset_map: dict[str, Artifact] = {}
    for artifact in artifacts:
        anchor_info = (artifact.media_meta_json or {}).get("anchor") or {}
        entity_id = (anchor_info.get("entity_id") or "").strip()
        if not entity_id:
            continue
        if chapter_id:
            shot = shot_map.get(artifact.shot_id or "")
            linked_run = run_map.get(artifact.run_id or "")
            linked_chapter_id = shot.chapter_id if shot else (linked_run.chapter_id if linked_run else None)
            if linked_chapter_id != chapter_id:
                continue
        entity_ids.add(entity_id)
        if entity_id not in anchored_asset_map:
            anchored_asset_map[entity_id] = artifact

    if not entity_ids:
        return []

    normalized_entity_type = _normalize_entity_type(entity_type)
    entity_stmt = select(Entity).where(
        Entity.tenant_id == tenant_id,
        Entity.project_id == project_id,
        Entity.deleted_at.is_(None),
        Entity.id.in_(entity_ids),
    )
    if normalized_entity_type:
        entity_stmt = entity_stmt.where(Entity.type == normalized_entity_type)
    entities = db.execute(entity_stmt).scalars().all()
    if not entities:
        return []
    entity_map = {row.id: row for row in entities}

    visible_entity_ids = set(entity_map.keys())
    links = [link for link in links if link.entity_id in visible_entity_ids]
    anchored_asset_map = {
        entity_id: artifact
        for entity_id, artifact in anchored_asset_map.items()
        if entity_id in visible_entity_ids
    }

    latest_link_map: dict[str, EntityInstanceLink] = {}
    for link in links:
        if link.entity_id not in latest_link_map:
            latest_link_map[link.entity_id] = link

    profile_rows = db.execute(
        select(EntityContinuityProfile).where(
            EntityContinuityProfile.tenant_id == tenant_id,
            EntityContinuityProfile.project_id == project_id,
            EntityContinuityProfile.entity_id.in_(visible_entity_ids),
            EntityContinuityProfile.deleted_at.is_(None),
        )
    ).scalars().all()
    profile_map = {row.entity_id: row for row in profile_rows}

    locked_variant_ids = {
        row.locked_preview_variant_id
        for row in profile_rows
        if row.locked_preview_variant_id
    }

    variant_stmt = select(EntityPreviewVariant).where(
        EntityPreviewVariant.tenant_id == tenant_id,
        EntityPreviewVariant.project_id == project_id,
        EntityPreviewVariant.entity_id.in_(visible_entity_ids),
        EntityPreviewVariant.deleted_at.is_(None),
    ).order_by(EntityPreviewVariant.created_at.desc())
    if run_id:
        variant_stmt = variant_stmt.where(EntityPreviewVariant.run_id == run_id)
    variants = db.execute(variant_stmt).scalars().all()

    variant_map: dict[str, EntityPreviewVariant] = {row.id: row for row in variants}
    missing_locked_variant_ids = {
        variant_id for variant_id in locked_variant_ids if variant_id not in variant_map
    }
    if missing_locked_variant_ids:
        locked_variants = db.execute(
            select(EntityPreviewVariant).where(
                EntityPreviewVariant.id.in_(missing_locked_variant_ids),
                EntityPreviewVariant.deleted_at.is_(None),
            )
        ).scalars().all()
        for row in locked_variants:
            variant_map[row.id] = row
            variants.append(row)

    latest_variant_map: dict[str, EntityPreviewVariant] = {}
    for variant in variants:
        if variant.entity_id not in latest_variant_map:
            latest_variant_map[variant.entity_id] = variant

    profile_anchor_asset_ids: set[str] = set()
    for row in profile_rows:
        asset_ids = (row.anchors_json or {}).get("asset_anchor_ids") or []
        for asset_id in asset_ids:
            if asset_id:
                profile_anchor_asset_ids.add(asset_id)

    extra_artifact_ids = {
        variant.artifact_id for variant in variants if variant.artifact_id
    } | profile_anchor_asset_ids
    extra_artifacts = (
        db.execute(select(Artifact).where(Artifact.id.in_(extra_artifact_ids))).scalars().all()
        if extra_artifact_ids
        else []
    )
    artifact_map = {row.id: row for row in artifacts}
    for row in extra_artifacts:
        artifact_map[row.id] = row

    scene_ids = {
        link.scene_id
        for link in latest_link_map.values()
        if link.scene_id
    } | {
        shot.scene_id
        for shot in shot_map.values()
        if shot.scene_id
    }
    scenes = (
        db.execute(select(Scene).where(Scene.id.in_(scene_ids))).scalars().all()
        if scene_ids
        else []
    )
    scene_map = {row.id: row for row in scenes}

    items: list[AssetBindingConsistencyItem] = []
    search = (keyword or "").strip().lower()
    for entity in entities:
        profile = profile_map.get(entity.id)
        latest_link = latest_link_map.get(entity.id)
        latest_variant = latest_variant_map.get(entity.id)

        locked_variant = variant_map.get(profile.locked_preview_variant_id) if profile else None
        locked_asset: Artifact | None = None
        if locked_variant and locked_variant.artifact_id:
            locked_asset = artifact_map.get(locked_variant.artifact_id)

        if locked_asset is None and profile:
            for asset_id in (profile.anchors_json or {}).get("asset_anchor_ids") or []:
                if asset_id in artifact_map:
                    locked_asset = artifact_map[asset_id]
                    break

        if locked_asset is None:
            locked_asset = anchored_asset_map.get(entity.id)

        latest_asset: Artifact | None = None
        if latest_variant and latest_variant.artifact_id:
            latest_asset = artifact_map.get(latest_variant.artifact_id)
        if latest_asset is None:
            latest_asset = anchored_asset_map.get(entity.id) or locked_asset

        chosen_shot_id = (
            latest_link.shot_id
            if latest_link and latest_link.shot_id
            else latest_variant.shot_id if latest_variant else latest_asset.shot_id if latest_asset else None
        )
        chosen_run_id = (
            latest_link.run_id
            if latest_link
            else latest_variant.run_id if latest_variant else latest_asset.run_id if latest_asset else None
        )
        shot = shot_map.get(chosen_shot_id or "")
        run = run_map.get(chosen_run_id or "")
        chosen_chapter_id = shot.chapter_id if shot else (run.chapter_id if run else None)
        chosen_scene_id = (
            latest_link.scene_id
            if latest_link and latest_link.scene_id
            else shot.scene_id if shot else latest_variant.scene_id if latest_variant else None
        )
        scene_label = scene_map.get(chosen_scene_id).label if chosen_scene_id in scene_map else None

        anchor_info = (locked_asset.media_meta_json or {}).get("anchor") if locked_asset else {}
        anchor_name = (anchor_info or {}).get("anchor_name")
        anchor_notes = (anchor_info or {}).get("notes")

        if search:
            haystack = " ".join(
                [
                    entity.id or "",
                    entity.label or "",
                    entity.canonical_label or "",
                    scene_label or "",
                    locked_asset.uri if locked_asset else "",
                    latest_asset.uri if latest_asset else "",
                ]
            ).lower()
            if search not in haystack:
                continue

        items.append(
            AssetBindingConsistencyItem(
                entity_id=entity.id,
                entity_name=entity.label,
                entity_type=entity.type.value if hasattr(entity.type, "value") else str(entity.type),
                chapter_id=chosen_chapter_id,
                run_id=chosen_run_id,
                shot_id=chosen_shot_id,
                scene_id=chosen_scene_id,
                scene_label=scene_label,
                continuity_status=profile.continuity_status if profile else "draft",
                locked_preview_variant_id=profile.locked_preview_variant_id if profile else None,
                latest_preview_variant_id=latest_variant.id if latest_variant else None,
                latest_preview_status=latest_variant.status if latest_variant else None,
                locked_asset_id=locked_asset.id if locked_asset else None,
                locked_asset_uri=locked_asset.uri if locked_asset else None,
                latest_asset_id=latest_asset.id if latest_asset else None,
                latest_asset_uri=latest_asset.uri if latest_asset else None,
                anchor_name=anchor_name,
                anchor_notes=anchor_notes,
            )
        )

    items.sort(key=lambda item: (item.entity_type, item.entity_name, item.entity_id))
    return items


@router.delete("/assets/{asset_id}")
def delete_asset(
    asset_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    artifact = db.get(Artifact, asset_id)
    if artifact is None or artifact.deleted_at is not None:
        raise HTTPException(status_code=404, detail="REQ-VALIDATION-001: asset not found")
    if artifact.tenant_id != tenant_id or artifact.project_id != project_id:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN-002: asset scope mismatch")
    artifact.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "deleted", "asset_id": asset_id}


@router.post("/assets/{asset_id}/anchor", response_model=AssetAnchorResponse)
def mark_asset_anchor(
    asset_id: str,
    body: AssetAnchorRequest,
    db: Session = Depends(get_db),
) -> AssetAnchorResponse:
    artifact = db.get(Artifact, asset_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="asset not found")
    if artifact.tenant_id != body.tenant_id or artifact.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN-002: asset scope mismatch")

    anchor_info = {
        "anchor_name": body.anchor_name,
        "entity_id": body.entity_id,
        "notes": body.notes,
        "tags": body.tags,
        "anchored_at": datetime.now(timezone.utc).isoformat(),
    }
    media_meta = dict(artifact.media_meta_json or {})
    media_meta["anchor"] = anchor_info
    artifact.media_meta_json = media_meta

    continuity_profile_id = None
    if body.entity_id:
        profile = db.execute(
            select(EntityContinuityProfile).where(
                EntityContinuityProfile.tenant_id == body.tenant_id,
                EntityContinuityProfile.project_id == body.project_id,
                EntityContinuityProfile.entity_id == body.entity_id,
                EntityContinuityProfile.deleted_at.is_(None),
            )
        ).scalars().first()
        if profile is None:
            profile = EntityContinuityProfile(
                id=f"cont_profile_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                trace_id=f"tr_anchor_{uuid4().hex[:12]}",
                correlation_id=f"cr_anchor_{uuid4().hex[:12]}",
                idempotency_key=f"idem_anchor_{asset_id}_{uuid4().hex[:8]}",
                entity_id=body.entity_id,
                continuity_status="locked",
                anchors_json={"asset_anchor_ids": [asset_id]},
                rules_json={},
                meta_json={"source": "asset_anchor"},
            )
            db.add(profile)
        else:
            anchors = dict(profile.anchors_json or {})
            anchor_assets = list(anchors.get("asset_anchor_ids") or [])
            if asset_id not in anchor_assets:
                anchor_assets.append(asset_id)
            anchors["asset_anchor_ids"] = anchor_assets
            profile.anchors_json = anchors
            profile.continuity_status = "locked"
        continuity_profile_id = profile.id

    event = WorkflowEvent(
        id=f"evt_{uuid4().hex[:24]}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=artifact.trace_id,
        correlation_id=artifact.correlation_id,
        idempotency_key=f"idem_anchor_evt_{asset_id}_{uuid4().hex[:8]}",
        run_id=artifact.run_id,
        event_type="entity.continuity.locked",
        event_version="1.0",
        producer="studio_api",
        occurred_at=datetime.now(timezone.utc),
        payload_json={
            "asset_id": asset_id,
            "run_id": artifact.run_id,
            "shot_id": artifact.shot_id,
            "anchor": anchor_info,
        },
    )
    db.add(event)
    db.commit()

    return AssetAnchorResponse(
        asset_id=asset_id,
        run_id=artifact.run_id or "",
        project_id=artifact.project_id,
        anchored=True,
        anchor_info=anchor_info,
        continuity_profile_id=continuity_profile_id,
    )


@router.get("/projects/{project_id}/anchors", response_model=list[AnchoredAssetItem])
def list_project_anchors(
    project_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[AnchoredAssetItem]:
    rows = db.execute(
        select(Artifact).where(
            Artifact.tenant_id == tenant_id,
            Artifact.project_id == project_id,
            Artifact.deleted_at.is_(None),
        ).order_by(Artifact.updated_at.desc())
    ).scalars().all()

    items: list[AnchoredAssetItem] = []
    for row in rows:
        anchor_info = (row.media_meta_json or {}).get("anchor")
        if not anchor_info:
            continue
        items.append(
            AnchoredAssetItem(
                asset_id=row.id,
                run_id=row.run_id or "",
                shot_id=row.shot_id,
                uri=row.uri,
                anchor_info=anchor_info,
            )
        )
    return items
