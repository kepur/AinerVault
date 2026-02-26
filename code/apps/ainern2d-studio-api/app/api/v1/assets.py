from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Artifact
from ainern2d_shared.schemas.artifact import ArtifactResponse

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["assets"])


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
