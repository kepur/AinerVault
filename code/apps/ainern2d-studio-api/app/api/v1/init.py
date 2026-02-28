from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.auth_models import User
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.governance_models import PersonaPack, PersonaPackVersion
from ainern2d_shared.ainer_db_models.rag_models import RagCollection

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/init", tags=["init"])

_DEFAULT_TENANT_ID = "default"
_DEFAULT_PROJECT_ID = "default"


class BootstrapAllRequest(BaseModel):
    tenant_id: str = _DEFAULT_TENANT_ID
    project_id: str = _DEFAULT_PROJECT_ID
    model_provider_id: str | None = None
    force: bool = False


class BootstrapStepResult(BaseModel):
    step: str
    status: str
    detail: str | None = None


class BootstrapAllResponse(BaseModel):
    status: str
    steps: list[BootstrapStepResult]


_DEFAULT_USERS = [
    {"email": "admin@ainer.ai", "display_name": "Ainer Admin", "raw_password": "Admin@123456"},
    {"email": "editor@ainer.ai", "display_name": "Ainer Editor", "raw_password": "Editor@123456"},
    {"email": "viewer@ainer.ai", "display_name": "Ainer Viewer", "raw_password": "Viewer@123456"},
]

_DEFAULT_ROUTE_PERMISSIONS = [
    {"path_prefix": "/api/v1/auth/users", "method": "*", "required_role": "admin"},
    {"path_prefix": "/api/v1/config/", "method": "*", "required_role": "admin"},
    {"path_prefix": "/api/v1/novels", "method": "POST", "required_role": "editor"},
    {"path_prefix": "/api/v1/rag/", "method": "POST", "required_role": "editor"},
    {"path_prefix": "/api/v1/culture-packs/", "method": "POST", "required_role": "editor"},
]

_DEFAULT_CULTURE_PACKS = [
    {
        "id": "default_wuxia",
        "display_name": "中式武侠",
        "constraints": {
            "visual_do": ["传统中式建筑", "丝绸服饰", "竹林山水"],
            "visual_dont": ["现代元素", "西式建筑", "塑料制品"],
            "signage_rules": {"character_limit": 30, "language": "中文", "font_style": "书法体"},
            "costume_norms": {"color_palette": ["红", "金", "黑", "白"], "fabric_types": ["丝绸", "棉麻"]},
            "prop_norms": {"material_constraints": ["木", "金属", "竹", "皮革"], "common_items": ["武器", "茶具", "卷轴"]},
        },
    },
    {
        "id": "default_modern",
        "display_name": "现代都市",
        "constraints": {
            "visual_do": ["高楼大厦", "霓虹灯", "现代科技"],
            "visual_dont": ["历史遗迹", "破旧装备"],
            "signage_rules": {"character_limit": 100, "language": "中英文", "font_style": "现代无衬线"},
            "costume_norms": {"color_palette": ["黑", "白", "灰", "深蓝"], "fabric_types": ["棉", "聚酯", "牛仔"]},
            "prop_norms": {"material_constraints": ["金属", "玻璃", "塑料"], "common_items": ["手机", "电脑", "车辆"]},
        },
    },
]


def _hash_password(raw_password: str) -> str:
    import hashlib
    digest = hashlib.sha256(f"ainer::{raw_password}".encode("utf-8")).hexdigest()
    return f"sha256${digest}"


@router.post("/bootstrap-all", response_model=BootstrapAllResponse)
def bootstrap_all(
    body: BootstrapAllRequest,
    db: Session = Depends(get_db),
) -> BootstrapAllResponse:
    steps: list[BootstrapStepResult] = []

    # Step 1: Create default users
    try:
        created_count = 0
        for u in _DEFAULT_USERS:
            existing = db.execute(
                select(User).where(
                    User.tenant_id == body.tenant_id,
                    User.email == u["email"],
                    User.deleted_at.is_(None),
                )
            ).scalars().first()
            if existing is None or body.force:
                if existing is None:
                    user = User(
                        id=f"user_{uuid4().hex}",
                        tenant_id=body.tenant_id,
                        project_id=body.project_id,
                        email=u["email"],
                        display_name=u["display_name"],
                        password_hash=_hash_password(u["raw_password"]),
                    )
                    db.add(user)
                    created_count += 1
        db.flush()
        steps.append(BootstrapStepResult(step="default_users", status="ok", detail=f"created {created_count} users"))
    except Exception as exc:
        db.rollback()
        steps.append(BootstrapStepResult(step="default_users", status="error", detail=str(exc)))

    # Step 2: Write route permissions
    try:
        written = 0
        for perm in _DEFAULT_ROUTE_PERMISSIONS:
            name = f"route_permission:{perm['path_prefix']}:{perm['method']}"
            existing = db.execute(
                select(CreativePolicyStack).where(
                    CreativePolicyStack.tenant_id == body.tenant_id,
                    CreativePolicyStack.project_id == body.project_id,
                    CreativePolicyStack.name == name,
                    CreativePolicyStack.deleted_at.is_(None),
                )
            ).scalars().first()
            payload = {
                "type": "route_permission",
                "path_prefix": perm["path_prefix"],
                "method": perm["method"],
                "required_role": perm["required_role"],
            }
            if existing is None:
                row = CreativePolicyStack(
                    id=f"perm_{uuid4().hex}",
                    tenant_id=body.tenant_id,
                    project_id=body.project_id,
                    trace_id=f"tr_perm_{uuid4().hex[:12]}",
                    correlation_id=f"cr_perm_{uuid4().hex[:12]}",
                    idempotency_key=f"idem_perm_{uuid4().hex[:8]}",
                    name=name,
                    status="active",
                    stack_json=payload,
                )
                db.add(row)
                written += 1
        db.flush()
        steps.append(BootstrapStepResult(step="route_permissions", status="ok", detail=f"written {written} permissions"))
    except Exception as exc:
        steps.append(BootstrapStepResult(step="route_permissions", status="error", detail=str(exc)))

    # Step 3: Create default culture packs
    try:
        packs_created = 0
        for pack in _DEFAULT_CULTURE_PACKS:
            name = f"culture_pack:{pack['id']}:v1"
            existing = db.execute(
                select(CreativePolicyStack).where(
                    CreativePolicyStack.tenant_id == body.tenant_id,
                    CreativePolicyStack.project_id == body.project_id,
                    CreativePolicyStack.name == name,
                    CreativePolicyStack.deleted_at.is_(None),
                )
            ).scalars().first()
            if existing is None:
                payload = {
                    "type": "culture_pack",
                    "culture_pack_id": pack["id"],
                    "version": "v1",
                    "display_name": pack["display_name"],
                    "description": f"Default culture pack: {pack['display_name']}",
                    "constraints": pack["constraints"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                row = CreativePolicyStack(
                    id=f"culture_pack_{uuid4().hex}",
                    tenant_id=body.tenant_id,
                    project_id=body.project_id,
                    trace_id=f"tr_culture_{uuid4().hex[:12]}",
                    correlation_id=f"cr_culture_{uuid4().hex[:12]}",
                    idempotency_key=f"idem_culture_{pack['id']}_v1_{uuid4().hex[:8]}",
                    name=name,
                    status="active",
                    stack_json=payload,
                )
                db.add(row)
                packs_created += 1
        db.flush()
        steps.append(BootstrapStepResult(step="culture_packs", status="ok", detail=f"created {packs_created} packs"))
    except Exception as exc:
        steps.append(BootstrapStepResult(step="culture_packs", status="error", detail=str(exc)))

    # Step 4: Create default RAG collection
    try:
        existing_coll = db.execute(
            select(RagCollection).where(
                RagCollection.tenant_id == body.tenant_id,
                RagCollection.project_id == body.project_id,
                RagCollection.name == "default_knowledge",
                RagCollection.deleted_at.is_(None),
            )
        ).scalars().first()
        if existing_coll is None:
            coll = RagCollection(
                id=f"coll_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                name="default_knowledge",
                language_code="zh",
                description="Default knowledge collection",
            )
            db.add(coll)
            db.flush()
            detail = f"created collection: {coll.id}"
        else:
            detail = f"already exists: {existing_coll.id}"
        steps.append(BootstrapStepResult(step="rag_collection", status="ok", detail=detail))
    except Exception as exc:
        steps.append(BootstrapStepResult(step="rag_collection", status="error", detail=str(exc)))

    # Step 5: Create default Persona Pack
    try:
        existing_persona = db.execute(
            select(PersonaPack).where(
                PersonaPack.tenant_id == body.tenant_id,
                PersonaPack.project_id == body.project_id,
                PersonaPack.name == "director_default",
                PersonaPack.deleted_at.is_(None),
            )
        ).scalars().first()
        if existing_persona is None:
            persona = PersonaPack(
                id=f"persona_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                name="director_default",
                description="Default director persona",
            )
            db.add(persona)
            db.flush()
            persona_version = PersonaPackVersion(
                id=f"pv_{uuid4().hex}",
                tenant_id=body.tenant_id,
                project_id=body.project_id,
                persona_pack_id=persona.id,
                version_name="v1",
                style_json={"style": "cinematic", "tone": "neutral"},
                voice_json={},
                camera_json={"default_angle": "medium", "movement": "smooth"},
            )
            db.add(persona_version)
            db.flush()
            detail = f"created persona: {persona.id}"
        else:
            detail = f"already exists: {existing_persona.id}"
        steps.append(BootstrapStepResult(step="persona_pack", status="ok", detail=detail))
    except Exception as exc:
        steps.append(BootstrapStepResult(step="persona_pack", status="error", detail=str(exc)))

    db.commit()

    all_ok = all(s.status == "ok" for s in steps)
    return BootstrapAllResponse(
        status="completed" if all_ok else "partial",
        steps=steps,
    )
