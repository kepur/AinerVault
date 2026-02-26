from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.auth_models import User

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str


class UserInfoResponse(BaseModel):
    user_id: str
    email: str
    display_name: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    # Stub: always succeed with a mock JWT
    stmt = select(User).where(User.email == body.username).limit(1)
    user = db.execute(stmt).scalars().first()
    user_id = user.id if user else f"user_{uuid4().hex}"
    mock_token = f"mock_jwt_{uuid4().hex}"
    return LoginResponse(token=mock_token, user_id=user_id)


@router.post("/register", response_model=UserInfoResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> UserInfoResponse:
    user = User(
        id=f"user_{uuid4().hex}",
        tenant_id="default",
        project_id="default",
        email=body.email,
        display_name=body.username,
        password_hash=f"hashed_{body.password}",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserInfoResponse(user_id=user.id, email=user.email, display_name=user.display_name)


@router.get("/me", response_model=UserInfoResponse)
def me(db: Session = Depends(get_db)) -> UserInfoResponse:
    # Stub: return default user
    stmt = select(User).limit(1)
    user = db.execute(stmt).scalars().first()
    if user:
        return UserInfoResponse(user_id=user.id, email=user.email, display_name=user.display_name)
    return UserInfoResponse(user_id="default_user", email="default@ainer.ai", display_name="Default User")
