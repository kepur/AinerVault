from __future__ import annotations

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.auth_models import Project

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    slug: str
    name: str
    description: Optional[str] = None
    tenant_id: str


class ProjectResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: Optional[str] = None
    tenant_id: str
    project_id: str


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    body: ProjectCreateRequest,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    project_id = f"proj_{uuid4().hex}"
    project = Project(
        id=project_id,
        tenant_id=body.tenant_id,
        project_id=project_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectResponse(
        id=project.id,
        slug=project.slug,
        name=project.name,
        description=project.description,
        tenant_id=project.tenant_id,
        project_id=project.project_id,
    )


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[ProjectResponse]:
    stmt = (
        select(Project)
        .filter_by(tenant_id=tenant_id, deleted_at=None)
        .order_by(Project.created_at.desc())
    )
    rows = db.execute(stmt).scalars().all()
    return [
        ProjectResponse(
            id=p.id,
            slug=p.slug,
            name=p.name,
            description=p.description,
            tenant_id=p.tenant_id,
            project_id=p.project_id,
        )
        for p in rows
    ]


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return ProjectResponse(
        id=project.id,
        slug=project.slug,
        name=project.name,
        description=project.description,
        tenant_id=project.tenant_id,
        project_id=project.project_id,
    )
