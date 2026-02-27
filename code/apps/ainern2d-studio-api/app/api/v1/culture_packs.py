from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/culture-packs", tags=["culture_packs"])


class CulturePackCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    culture_pack_id: str
    display_name: str
    description: str | None = None
    constraints: dict = Field(default_factory=dict)


class CulturePackVersionCreateRequest(BaseModel):
    tenant_id: str
    project_id: str
    version: str
    display_name: str
    description: str | None = None
    constraints: dict = Field(default_factory=dict)
    status: str = "active"


class CulturePackResponse(BaseModel):
    culture_pack_id: str
    version: str
    display_name: str
    description: str | None = None
    status: str
    constraints: dict = Field(default_factory=dict)


class CulturePackExportResponse(BaseModel):
    culture_pack_id: str
    version: str
    export_for_skill_02: dict = Field(default_factory=dict)
    export_for_skill_07: dict = Field(default_factory=dict)
    export_for_skill_10: dict = Field(default_factory=dict)


@router.post("", response_model=CulturePackResponse, status_code=201)
def create_culture_pack(
    body: CulturePackCreateRequest,
    db: Session = Depends(get_db),
) -> CulturePackResponse:
    version = "v1"
    row = _create_or_update_version(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        culture_pack_id=body.culture_pack_id,
        version=version,
        display_name=body.display_name,
        description=body.description,
        constraints=body.constraints,
        status="active",
    )
    return _to_response(row)


@router.post("/{culture_pack_id}/versions", response_model=CulturePackResponse, status_code=201)
def create_culture_pack_version(
    culture_pack_id: str,
    body: CulturePackVersionCreateRequest,
    db: Session = Depends(get_db),
) -> CulturePackResponse:
    row = _create_or_update_version(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        culture_pack_id=culture_pack_id,
        version=body.version,
        display_name=body.display_name,
        description=body.description,
        constraints=body.constraints,
        status=body.status,
    )
    return _to_response(row)


@router.get("", response_model=list[CulturePackResponse])
def list_culture_packs(
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CulturePackResponse]:
    rows = db.execute(
        select(CreativePolicyStack)
        .where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.deleted_at.is_(None),
        )
        .order_by(CreativePolicyStack.created_at.desc())
    ).scalars().all()

    latest_by_pack: dict[str, CreativePolicyStack] = {}
    for row in rows:
        payload = row.stack_json or {}
        if payload.get("type") != "culture_pack":
            continue
        pack_id = str(payload.get("culture_pack_id") or "")
        if not pack_id:
            continue
        if keyword and keyword.strip().lower() not in pack_id.lower() and keyword.strip().lower() not in str(
            payload.get("display_name") or ""
        ).lower():
            continue
        if status and row.status != status:
            continue
        if pack_id not in latest_by_pack:
            latest_by_pack[pack_id] = row

    return [_to_response(item) for item in latest_by_pack.values()]


@router.get("/{culture_pack_id}/versions", response_model=list[CulturePackResponse])
def list_culture_pack_versions(
    culture_pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[CulturePackResponse]:
    rows = _query_culture_pack_rows(
        db=db,
        tenant_id=tenant_id,
        project_id=project_id,
        culture_pack_id=culture_pack_id,
    )
    return [_to_response(item) for item in rows]


@router.get("/{culture_pack_id}/export", response_model=CulturePackExportResponse)
def export_culture_pack(
    culture_pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    version: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CulturePackExportResponse:
    rows = _query_culture_pack_rows(
        db=db,
        tenant_id=tenant_id,
        project_id=project_id,
        culture_pack_id=culture_pack_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="culture pack not found")

    selected = rows[0]
    if version:
        for row in rows:
            payload = row.stack_json or {}
            if payload.get("version") == version:
                selected = row
                break

    payload = selected.stack_json or {}
    constraints = payload.get("constraints") or {}
    return CulturePackExportResponse(
        culture_pack_id=culture_pack_id,
        version=str(payload.get("version") or "v1"),
        export_for_skill_02={
            "culture_candidates": [culture_pack_id],
            "routing_constraints": constraints,
        },
        export_for_skill_07={
            "binding_constraints": constraints,
        },
        export_for_skill_10={
            "prompt_culture_layer": constraints,
        },
    )


@router.delete("/{culture_pack_id}")
def delete_culture_pack(
    culture_pack_id: str,
    tenant_id: str = Query(...),
    project_id: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    rows = _query_culture_pack_rows(
        db=db,
        tenant_id=tenant_id,
        project_id=project_id,
        culture_pack_id=culture_pack_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="REQ-VALIDATION-001: culture pack not found")
    now = datetime.now(timezone.utc)
    for row in rows:
        row.deleted_at = now
    db.commit()
    return {"status": "deleted", "culture_pack_id": culture_pack_id}


def _query_culture_pack_rows(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    culture_pack_id: str,
) -> list[CreativePolicyStack]:
    rows = db.execute(
        select(CreativePolicyStack)
        .where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.deleted_at.is_(None),
        )
        .order_by(CreativePolicyStack.created_at.desc())
    ).scalars().all()
    out: list[CreativePolicyStack] = []
    for row in rows:
        payload = row.stack_json or {}
        if payload.get("type") != "culture_pack":
            continue
        if payload.get("culture_pack_id") != culture_pack_id:
            continue
        out.append(row)
    return out


def _create_or_update_version(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    culture_pack_id: str,
    version: str,
    display_name: str,
    description: str | None,
    constraints: dict,
    status: str,
) -> CreativePolicyStack:
    name = f"culture_pack:{culture_pack_id}:{version}"
    row = db.execute(
        select(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
            CreativePolicyStack.name == name,
            CreativePolicyStack.deleted_at.is_(None),
        )
    ).scalars().first()

    payload = {
        "type": "culture_pack",
        "culture_pack_id": culture_pack_id,
        "version": version,
        "display_name": display_name,
        "description": description,
        "constraints": constraints,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if row is None:
        row = CreativePolicyStack(
            id=f"culture_pack_{uuid4().hex}",
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_culture_{uuid4().hex[:12]}",
            correlation_id=f"cr_culture_{uuid4().hex[:12]}",
            idempotency_key=f"idem_culture_{culture_pack_id}_{version}_{uuid4().hex[:8]}",
            name=name,
            status=status,
            stack_json=payload,
        )
        db.add(row)
    else:
        row.status = status
        row.stack_json = payload

    db.commit()
    db.refresh(row)
    return row


def _to_response(row: CreativePolicyStack) -> CulturePackResponse:
    payload = row.stack_json or {}
    return CulturePackResponse(
        culture_pack_id=str(payload.get("culture_pack_id") or ""),
        version=str(payload.get("version") or "v1"),
        display_name=str(payload.get("display_name") or row.name),
        description=payload.get("description"),
        status=row.status,
        constraints=payload.get("constraints") or {},
    )
