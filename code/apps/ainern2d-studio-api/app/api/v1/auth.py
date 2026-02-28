from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ainern2d_shared.ainer_db_models.auth_models import ProjectMember, User
from ainern2d_shared.ainer_db_models.enum_models import MembershipRole
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.pipeline_models import WorkflowEvent

from app.api.deps import get_db
from app.security.auth_token import create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_DEFAULT_TENANT_ID = "default"
_DEFAULT_PROJECT_ID = "default"

_DEFAULT_USERS: dict[str, tuple[str, str, str]] = {
    "admin@ainer.ai": ("Admin@123456", "Ainer Admin", "admin"),
    "editor@ainer.ai": ("Editor@123456", "Ainer Editor", "editor"),
    "viewer@ainer.ai": ("Viewer@123456", "Ainer Viewer", "viewer"),
    "demo_user@ainer.ai": ("demo_pass", "Demo User", "editor"),
}


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    role: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str


class UserInfoResponse(BaseModel):
    user_id: str
    email: str
    display_name: str


class LogoutResponse(BaseModel):
    status: str = "ok"
    message: str = "logged out"


class ProjectAclItem(BaseModel):
    project_id: str
    user_id: str
    role: str


class ProjectAclUpsertRequest(BaseModel):
    tenant_id: str
    role: str = Field(description="owner/admin/editor/viewer")


class AuditLogItem(BaseModel):
    event_id: str
    event_type: str
    producer: str
    occurred_at: datetime
    run_id: str | None = None
    job_id: str | None = None
    payload: dict = Field(default_factory=dict)


class UserListItem(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    created_at: datetime | None = None


class UserUpdateRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None


class PasswordResetRequest(BaseModel):
    new_password: str


class BootstrapPermissionsResponse(BaseModel):
    status: str
    permissions_written: int
    permissions: list[dict]


_DEFAULT_ROUTE_PERMISSIONS = [
    {"path_prefix": "/api/v1/auth/users", "method": "*", "required_role": "admin"},
    {"path_prefix": "/api/v1/config/", "method": "*", "required_role": "admin"},
    {"path_prefix": "/api/v1/novels", "method": "POST", "required_role": "editor"},
    {"path_prefix": "/api/v1/novels", "method": "PUT", "required_role": "editor"},
    {"path_prefix": "/api/v1/novels", "method": "DELETE", "required_role": "editor"},
    {"path_prefix": "/api/v1/rag/", "method": "POST", "required_role": "editor"},
    {"path_prefix": "/api/v1/culture-packs/", "method": "POST", "required_role": "editor"},
    {"path_prefix": "/api/v1/culture-packs/", "method": "DELETE", "required_role": "editor"},
]


def _hash_password(raw_password: str) -> str:
    digest = hashlib.sha256(f"ainer::{raw_password}".encode("utf-8")).hexdigest()
    return f"sha256${digest}"


def _verify_password(raw_password: str, stored_password_hash: str) -> bool:
    if stored_password_hash.startswith("sha256$"):
        return stored_password_hash == _hash_password(raw_password)
    if stored_password_hash.startswith("hashed_"):
        return stored_password_hash == f"hashed_{raw_password}"
    return stored_password_hash == raw_password


def _create_user(
    db: Session,
    *,
    email: str,
    display_name: str,
    raw_password: str,
) -> User:
    user = User(
        id=f"user_{uuid4().hex}",
        tenant_id=_DEFAULT_TENANT_ID,
        project_id=_DEFAULT_PROJECT_ID,
        email=email,
        display_name=display_name,
        password_hash=_hash_password(raw_password),
    )
    db.add(user)
    db.flush()
    return user


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    identity = body.username.strip().lower()
    if not identity or not body.password:
        raise HTTPException(status_code=400, detail="AUTH-VALIDATION-001: username/password required")

    default_role: str | None = None
    if identity in _DEFAULT_USERS:
        default_role = _DEFAULT_USERS[identity][2]

    user = db.execute(
        select(User).where(
            User.deleted_at.is_(None),
            or_(User.email == identity, User.display_name == body.username),
        )
    ).scalars().first()

    role = default_role or "viewer"
    if user is None and identity in _DEFAULT_USERS:
        expected_password, display_name, seed_role = _DEFAULT_USERS[identity]
        if expected_password != body.password:
            raise HTTPException(status_code=401, detail="AUTH-VALIDATION-001: invalid credentials")
        user = _create_user(
            db,
            email=identity,
            display_name=display_name,
            raw_password=expected_password,
        )
        role = seed_role
        db.commit()
        db.refresh(user)

    if user is None:
        raise HTTPException(status_code=401, detail="AUTH-VALIDATION-001: invalid credentials")
    if not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="AUTH-VALIDATION-001: invalid credentials")

    # Resolve the user's actual role in default project from ACL
    # Default users seed their role; other users query from ProjectMember
    if role == "viewer":
        member = db.execute(
            select(ProjectMember).where(
                ProjectMember.tenant_id == _DEFAULT_TENANT_ID,
                ProjectMember.project_id == _DEFAULT_PROJECT_ID,
                ProjectMember.user_id == user.id,
                ProjectMember.deleted_at.is_(None),
            )
        ).scalars().first()
        if member is not None:
            role = member.role.value if hasattr(member.role, "value") else str(member.role)

    signed_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=role,
        tenant_id=_DEFAULT_TENANT_ID,
        project_id=_DEFAULT_PROJECT_ID,
    )
    return LoginResponse(token=signed_token, user_id=user.id, role=role)


@router.post("/register", response_model=UserInfoResponse, status_code=201, deprecated=True)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> UserInfoResponse:
    """[DEPRECATED] Use POST /auth/admin/create-user instead."""
    normalized_email = body.email.strip().lower()
    if not normalized_email or not body.password or not body.username:
        raise HTTPException(status_code=400, detail="AUTH-VALIDATION-001: invalid register payload")

    exists = db.execute(
        select(User).where(
            User.tenant_id == _DEFAULT_TENANT_ID,
            User.email == normalized_email,
            User.deleted_at.is_(None),
        )
    ).scalars().first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="REQ-IDEMPOTENCY-001: email already registered")

    user = User(
        id=f"user_{uuid4().hex}",
        tenant_id=_DEFAULT_TENANT_ID,
        project_id=_DEFAULT_PROJECT_ID,
        email=normalized_email,
        display_name=body.username.strip(),
        password_hash=_hash_password(body.password),
    )
    try:
        db.add(user)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="REQ-IDEMPOTENCY-001: email already registered") from exc
    db.refresh(user)
    return UserInfoResponse(user_id=user.id, email=user.email, display_name=user.display_name)


class AdminCreateUserRequest(BaseModel):
    email: str
    display_name: str
    password: str
    role: str = "editor"  # admin / producer / editor / viewer
    tg_chat_id: str | None = None


class AdminCreateUserResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    tg_chat_id: str | None = None


@router.post("/admin/create-user", response_model=AdminCreateUserResponse, status_code=201)
def admin_create_user(
    body: AdminCreateUserRequest,
    db: Session = Depends(get_db),
) -> AdminCreateUserResponse:
    """Admin-only: create a new user with role assignment."""
    normalized_email = body.email.strip().lower()
    if not normalized_email or not body.password or len(body.password) < 6:
        raise HTTPException(status_code=400, detail="email and password (>=6 chars) required")

    exists = db.execute(
        select(User).where(
            User.tenant_id == _DEFAULT_TENANT_ID,
            User.email == normalized_email,
            User.deleted_at.is_(None),
        )
    ).scalars().first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    user = _create_user(db, email=normalized_email, display_name=body.display_name.strip(), raw_password=body.password)

    # Assign role via ProjectMember ACL
    try:
        role_enum = MembershipRole(body.role)
    except ValueError:
        role_enum = MembershipRole("editor")

    member = ProjectMember(
        id=f"pm_{uuid4().hex}",
        tenant_id=_DEFAULT_TENANT_ID,
        project_id=_DEFAULT_PROJECT_ID,
        trace_id=f"tr_acl_{uuid4().hex[:12]}",
        correlation_id=f"cr_acl_{uuid4().hex[:12]}",
        idempotency_key=f"idem_acl_{_DEFAULT_PROJECT_ID}_{user.id}_{uuid4().hex[:8]}",
        user_id=user.id,
        role=role_enum,
    )
    db.add(member)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="failed to create user") from exc
    db.refresh(user)

    return AdminCreateUserResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=body.role,
        tg_chat_id=body.tg_chat_id,
    )


@router.get("/me", response_model=UserInfoResponse)
def me(db: Session = Depends(get_db)) -> UserInfoResponse:
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.created_at.asc()).limit(1)
    user = db.execute(stmt).scalars().first()
    if user:
        return UserInfoResponse(user_id=user.id, email=user.email, display_name=user.display_name)
    return UserInfoResponse(user_id="default_user", email="admin@ainer.ai", display_name="Ainer Admin")


@router.post("/logout", response_model=LogoutResponse)
def logout() -> LogoutResponse:
    return LogoutResponse()


@router.get("/projects/{project_id}/acl", response_model=list[ProjectAclItem])
def list_project_acl(
    project_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[ProjectAclItem]:
    rows = db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.tenant_id == tenant_id,
            ProjectMember.deleted_at.is_(None),
        )
    ).scalars().all()
    return [
        ProjectAclItem(
            project_id=row.project_id,
            user_id=row.user_id,
            role=row.role.value if hasattr(row.role, "value") else str(row.role),
        )
        for row in rows
    ]


@router.put("/projects/{project_id}/acl/{user_id}", response_model=ProjectAclItem)
def upsert_project_acl(
    project_id: str,
    user_id: str,
    body: ProjectAclUpsertRequest,
    db: Session = Depends(get_db),
) -> ProjectAclItem:
    try:
        role = MembershipRole(body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid role: {body.role}") from exc

    row = db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.tenant_id == body.tenant_id,
            ProjectMember.user_id == user_id,
        )
    ).scalars().first()
    if row is None:
        row = ProjectMember(
            id=f"pm_{uuid4().hex}",
            tenant_id=body.tenant_id,
            project_id=project_id,
            trace_id=f"tr_acl_{uuid4().hex[:12]}",
            correlation_id=f"cr_acl_{uuid4().hex[:12]}",
            idempotency_key=f"idem_acl_{project_id}_{user_id}_{uuid4().hex[:8]}",
            user_id=user_id,
            role=role,
        )
        db.add(row)
    else:
        row.role = role
    db.commit()
    return ProjectAclItem(project_id=project_id, user_id=user_id, role=role.value)


@router.get("/users", response_model=list[UserListItem])
def list_users(
    tenant_id: str = Query(default=_DEFAULT_TENANT_ID),
    db: Session = Depends(get_db),
) -> list[UserListItem]:
    stmt = (
        select(User)
        .where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
        .order_by(User.created_at.asc())
    )
    users = db.execute(stmt).scalars().all()
    result = []
    for user in users:
        # Resolve role from ProjectMember ACL
        member = db.execute(
            select(ProjectMember).where(
                ProjectMember.tenant_id == tenant_id,
                ProjectMember.project_id == _DEFAULT_PROJECT_ID,
                ProjectMember.user_id == user.id,
                ProjectMember.deleted_at.is_(None),
            )
        ).scalars().first()
        role = "viewer"
        if member is not None:
            role = member.role.value if hasattr(member.role, "value") else str(member.role)
        # Check default users for seeded role
        if user.email in _DEFAULT_USERS:
            seeded_role = _DEFAULT_USERS[user.email][2]
            if role == "viewer":
                role = seeded_role
        result.append(
            UserListItem(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                role=role,
                created_at=user.created_at,
            )
        )
    return result


@router.get("/users/{user_id}", response_model=UserListItem)
def get_user(
    user_id: str,
    tenant_id: str = Query(default=_DEFAULT_TENANT_ID),
    db: Session = Depends(get_db),
) -> UserListItem:
    user = db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.deleted_at.is_(None),
        )
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    member = db.execute(
        select(ProjectMember).where(
            ProjectMember.tenant_id == tenant_id,
            ProjectMember.project_id == _DEFAULT_PROJECT_ID,
            ProjectMember.user_id == user.id,
            ProjectMember.deleted_at.is_(None),
        )
    ).scalars().first()
    role = "viewer"
    if member is not None:
        role = member.role.value if hasattr(member.role, "value") else str(member.role)
    if user.email in _DEFAULT_USERS and role == "viewer":
        role = _DEFAULT_USERS[user.email][2]
    return UserListItem(id=user.id, email=user.email, display_name=user.display_name, role=role, created_at=user.created_at)


@router.put("/users/{user_id}", response_model=UserListItem)
def update_user(
    user_id: str,
    body: UserUpdateRequest,
    tenant_id: str = Query(default=_DEFAULT_TENANT_ID),
    db: Session = Depends(get_db),
) -> UserListItem:
    user = db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.deleted_at.is_(None),
        )
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    if body.display_name is not None:
        user.display_name = body.display_name

    role = "viewer"
    if body.role is not None:
        try:
            new_role = MembershipRole(body.role)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid role: {body.role}") from exc
        member = db.execute(
            select(ProjectMember).where(
                ProjectMember.tenant_id == tenant_id,
                ProjectMember.project_id == _DEFAULT_PROJECT_ID,
                ProjectMember.user_id == user_id,
            )
        ).scalars().first()
        if member is None:
            member = ProjectMember(
                id=f"pm_{uuid4().hex}",
                tenant_id=tenant_id,
                project_id=_DEFAULT_PROJECT_ID,
                trace_id=f"tr_acl_{uuid4().hex[:12]}",
                correlation_id=f"cr_acl_{uuid4().hex[:12]}",
                idempotency_key=f"idem_acl_{_DEFAULT_PROJECT_ID}_{user_id}_{uuid4().hex[:8]}",
                user_id=user_id,
                role=new_role,
            )
            db.add(member)
        else:
            member.role = new_role
        role = body.role
    else:
        member = db.execute(
            select(ProjectMember).where(
                ProjectMember.tenant_id == tenant_id,
                ProjectMember.project_id == _DEFAULT_PROJECT_ID,
                ProjectMember.user_id == user_id,
                ProjectMember.deleted_at.is_(None),
            )
        ).scalars().first()
        if member is not None:
            role = member.role.value if hasattr(member.role, "value") else str(member.role)

    db.commit()
    db.refresh(user)
    return UserListItem(id=user.id, email=user.email, display_name=user.display_name, role=role, created_at=user.created_at)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    tenant_id: str = Query(default=_DEFAULT_TENANT_ID),
    db: Session = Depends(get_db),
) -> dict:
    user = db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.deleted_at.is_(None),
        )
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "deleted", "user_id": user_id}


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    body: PasswordResetRequest,
    tenant_id: str = Query(default=_DEFAULT_TENANT_ID),
    db: Session = Depends(get_db),
) -> dict:
    if not body.new_password or len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="password must be at least 6 characters")
    user = db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.deleted_at.is_(None),
        )
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.password_hash = _hash_password(body.new_password)
    db.commit()
    return {"status": "ok", "user_id": user_id}


@router.post("/init-permissions", response_model=BootstrapPermissionsResponse)
def init_permissions(
    tenant_id: str = Query(default=_DEFAULT_TENANT_ID),
    project_id: str = Query(default=_DEFAULT_PROJECT_ID),
    db: Session = Depends(get_db),
) -> BootstrapPermissionsResponse:
    written = 0
    for perm in _DEFAULT_ROUTE_PERMISSIONS:
        name = f"route_permission:{perm['path_prefix']}:{perm['method']}"
        existing = db.execute(
            select(CreativePolicyStack).where(
                CreativePolicyStack.tenant_id == tenant_id,
                CreativePolicyStack.project_id == project_id,
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
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_perm_{uuid4().hex[:12]}",
                correlation_id=f"cr_perm_{uuid4().hex[:12]}",
                idempotency_key=f"idem_perm_{uuid4().hex[:8]}",
                name=name,
                status="active",
                stack_json=payload,
            )
            db.add(row)
            written += 1
        else:
            existing.stack_json = payload
    db.commit()
    return BootstrapPermissionsResponse(
        status="ok",
        permissions_written=written,
        permissions=_DEFAULT_ROUTE_PERMISSIONS,
    )


@router.get("/audit/logs", response_model=list[AuditLogItem])
def list_audit_logs(
    tenant_id: str = Query(...),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[AuditLogItem]:
    stmt = select(WorkflowEvent).where(
        WorkflowEvent.tenant_id == tenant_id,
        WorkflowEvent.deleted_at.is_(None),
    )
    if project_id:
        stmt = stmt.where(WorkflowEvent.project_id == project_id)
    rows = db.execute(stmt.order_by(WorkflowEvent.occurred_at.desc()).limit(limit)).scalars().all()
    return [
        AuditLogItem(
            event_id=row.id,
            event_type=row.event_type,
            producer=row.producer,
            occurred_at=row.occurred_at or datetime.now(timezone.utc),
            run_id=row.run_id,
            job_id=row.job_id,
            payload=row.payload_json or {},
        )
        for row in rows
    ]
