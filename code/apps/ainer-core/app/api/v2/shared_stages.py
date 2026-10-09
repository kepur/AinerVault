"""Independent R2/R3 entry point; no generation, recovery or GPU side effects."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db import get_db
from app.director.store import SceneStoreError
from app.models import DirectorScene
from app.production import service as sources, stages
from app.production.schema import ResourceRef
from app.production.stage_resources import consume
from app.production.stage_schema import CoverageBake, CoverageSample, StageCreate, StageLink, StageSample, StageUpdate, NarrativeStageCreate
from app.scene3d.runner import SceneRunError

router = APIRouter(prefix="/api/v2/production/stages", tags=["shared-stages"])


def fail(db, exc):
    db.rollback()
    code = exc.code if isinstance(exc, sources.ProductionError) else "stage_compile_failed"
    status = exc.status if isinstance(exc, sources.ProductionError) else 422
    raise HTTPException(status, detail={"code": code, "message": str(exc), "issues": []}) from exc


ERRORS = (sources.ProductionError, SceneStoreError, SceneRunError, ValueError)


class ReferenceInput(BaseModel):
    board_id: str
    ref: ResourceRef


@router.post("/reference-preview")
def reference_preview(body: ReferenceInput, db: Session = Depends(get_db)):
    try:
        return stages.envelope(consume(db, body.board_id, body.ref))
    except ERRORS as exc:
        fail(db, exc)


@router.post("/reference-bake")
def reference_bake(body: ReferenceInput, db: Session = Depends(get_db)):
    try:
        return stages.envelope(consume(db, body.board_id, body.ref, bake=True))
    except ERRORS as exc:
        fail(db, exc)


@router.get("")
def list_stages(board_id: str, limit: int = Query(100, ge=1, le=200), db: Session = Depends(get_db)):
    try:
        board = sources.board(db, board_id)
        q = select(DirectorScene).where(DirectorScene.workspace_id == board.workspace_id,
            DirectorScene.notes_json[stages.KEY].isnot(None)).order_by(DirectorScene.updated_at.desc()).limit(limit)
        return stages.envelope({"items": [stages.out(s, False) for s in db.scalars(q)
            if isinstance((s.notes_json or {}).get(stages.KEY), dict)]})
    except ERRORS as exc:
        fail(db, exc)


@router.post("")
def create_stage(body: StageCreate, db: Session = Depends(get_db)):
    try:
        scene = stages.create(db, body)
        db.commit()
        return stages.envelope(stages.out(scene))
    except ERRORS as exc:
        fail(db, exc)


@router.get("/{stage_id}")
def get_stage(stage_id: str, board_id: str, db: Session = Depends(get_db)):
    try:
        _, scene = stages.get(db, stage_id, board_id)
        return stages.envelope(stages.out(scene))
    except ERRORS as exc:
        fail(db, exc)


@router.post("/from-narrative")
def create_from_narrative(body: NarrativeStageCreate, db: Session = Depends(get_db)):
    try:
        scene = stages.create_from_narrative(db, body)
        db.commit()
        return stages.envelope(stages.out(scene))
    except ERRORS as exc:
        fail(db, exc)


@router.put("/{stage_id}")
def save_stage(stage_id: str, body: StageUpdate, board_id: str, db: Session = Depends(get_db)):
    try:
        board, scene = stages.get(db, stage_id, board_id, lock=True)
        stages.update(db, scene, board, body)
        db.commit()
        return stages.envelope(stages.out(scene))
    except ERRORS as exc:
        fail(db, exc)


@router.post("/{stage_id}/boards")
def link_board(stage_id: str, body: StageLink, db: Session = Depends(get_db)):
    try:
        _, scene = stages.get(db, stage_id, body.board_id, lock=True)
        stages.assert_version(scene, body.base_version)
        meta = stages.metadata(scene)
        if body.board_id not in meta.get("board_ids", []):
            scene.notes_json = {**scene.notes_json, stages.KEY: {**meta, "board_ids": [*meta.get("board_ids", []), body.board_id]}}
            scene.version += 1
        db.commit()
        return stages.envelope(stages.out(scene))
    except ERRORS as exc:
        fail(db, exc)


@router.post("/{stage_id}/sample")
def sample_stage(stage_id: str, body: StageSample, board_id: str, db: Session = Depends(get_db)):
    try:
        board, scene = stages.get(db, stage_id, board_id)
        return stages.envelope(stages.sample(db, scene, board, body.base_version, body.time_ms, body.camera_id))
    except ERRORS as exc:
        fail(db, exc)


@router.post("/{stage_id}/adopt-projection")
def adopt_projection(stage_id: str, body: CoverageBake, board_id: str, db: Session = Depends(get_db)):
    try:
        board, scene = stages.get(db, stage_id, board_id, lock=True)
        stages.adopt_projection(db, scene, board, body.base_version)
        db.commit()
        return stages.envelope(stages.out(scene))
    except ERRORS as exc:
        fail(db, exc)


@router.get("/{stage_id}/preview")
def preview(stage_id: str, board_id: str, base_version: int, db: Session = Depends(get_db)):
    try:
        board, scene = stages.get(db, stage_id, board_id)
        _, doc, _ = stages.resolve_doc(db, scene, board, base_version)
        return stages.envelope({"stage_id": scene.id, "stage_version": scene.version, "doc": doc})
    except ERRORS as exc:
        fail(db, exc)


@router.post("/{stage_id}/coverages/{coverage_id}/sample")
def sample_coverage(stage_id: str, coverage_id: str, body: CoverageSample, board_id: str, db: Session = Depends(get_db)):
    try:
        board, scene = stages.get(db, stage_id, board_id)
        coverage = stages.coverage_of(stages.content_of(scene), coverage_id)
        result = stages.sample(db, scene, board, body.base_version,
            stages.world_time(coverage, body.clip_time_ms), coverage.camera_id)
        return stages.envelope({**result, "coverage_id": coverage.id, "clip_time_ms": body.clip_time_ms})
    except ERRORS as exc:
        fail(db, exc)


@router.post("/{stage_id}/coverages/{coverage_id}/bake")
def bake_coverage(stage_id: str, coverage_id: str, body: CoverageBake, board_id: str, db: Session = Depends(get_db)):
    try:
        board, scene = stages.get(db, stage_id, board_id)
        return stages.envelope(stages.bake_coverage(db, scene, board, body.base_version, coverage_id))
    except ERRORS as exc:
        fail(db, exc)
