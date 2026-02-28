from __future__ import annotations

import os
import re
import threading

from fastapi import FastAPI, Request
from sqlalchemy import select

from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.ainer_db_models.auth_models import ProjectMember
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun

from app.api.deps import has_required_role
from app.api.error_mapping import build_error_response, register_error_handlers
from app.api.v1.assets import router as assets_router
from app.api.v1.auth import router as auth_router
from app.api.v1.auto_router import router as auto_router_router
from app.api.v1.config_center import router as config_center_router
from app.api.v1.culture_packs import router as culture_packs_router
from app.api.v1.init import router as init_router
from app.api.v1.novels import router as novels_router
from app.api.v1.observer import router as observer_router
from app.api.v1.orchestrator import consume_orchestrator_topic
from app.api.v1.orchestrator import router as orchestrator_router
from app.api.v1.preview import router as preview_router
from app.api.v1.projects import router as projects_router
from app.api.v1.rag_console import router as rag_console_router
from app.api.v1.regenerate import router as regenerate_router
from app.api.v1.tasks import router as task_router
from app.api.v1.timesline import router as timeline_router
from app.api.v1.translation import router as translation_router
from app.api.v1.kb_assets import router as kb_assets_router
from app.api.v1.nle_projects import router as nle_projects_router
from app.security.auth_token import decode_access_token, extract_bearer_token
from ainern2d_shared.db.session import SessionLocal

app = FastAPI(title="ainern2d-studio-api", version="0.1.0")
register_error_handlers(app)
app.include_router(auth_router)
app.include_router(init_router)
app.include_router(task_router)
app.include_router(orchestrator_router)
app.include_router(observer_router)
app.include_router(projects_router)
app.include_router(novels_router)
app.include_router(config_center_router)
app.include_router(auto_router_router)
app.include_router(rag_console_router)
app.include_router(culture_packs_router)
app.include_router(assets_router)
app.include_router(timeline_router)
app.include_router(regenerate_router)
app.include_router(preview_router)
app.include_router(translation_router)
app.include_router(kb_assets_router)
app.include_router(nle_projects_router)

_PUBLIC_PATHS = {
	"/healthz",
	"/api/v1/auth/login",
	"/api/v1/auth/register",
	"/api/v1/init/bootstrap-all",
}

_PUBLIC_PREFIXES = (
	"/docs",
	"/redoc",
	"/openapi.json",
)

_ADMIN_PREFIXES = (
	"/api/v1/config/",
	"/api/v1/auth/projects/",
	"/api/v1/auth/audit/",
	"/api/v1/auth/users",
	"/api/v1/init/",
)

_ADMIN_ROUTES = {
	("POST", "/api/v1/projects"),
}
_PROJECT_PATH_RE = re.compile(r"^/api/v1/projects/([^/]+)")
_RUN_PATH_RE = re.compile(r"^/api/v1/runs/([^/]+)")


def _is_public_path(path: str) -> bool:
	if path in _PUBLIC_PATHS:
		return True
	return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def _required_role(path: str, method: str) -> str:
	if (method, path) in _ADMIN_ROUTES:
		return "admin"
	if any(path.startswith(prefix) for prefix in _ADMIN_PREFIXES):
		return "admin"
	if path in {"/api/v1/auth/me", "/api/v1/auth/logout"}:
		return "viewer"
	if method in {"POST", "PUT", "PATCH", "DELETE"}:
		return "editor"
	return "viewer"


def _extract_project_id(request: Request) -> str | None:
	match = _PROJECT_PATH_RE.match(request.url.path)
	if match:
		return match.group(1)
	query_project = request.query_params.get("project_id")
	if query_project:
		return query_project
	run_match = _RUN_PATH_RE.match(request.url.path)
	if not run_match:
		return None
	run_id = run_match.group(1)
	db = SessionLocal()
	try:
		run = db.execute(
			select(RenderRun).where(
				RenderRun.id == run_id,
				RenderRun.deleted_at.is_(None),
			)
		).scalars().first()
		if run is None:
			return None
		return run.project_id
	finally:
		db.close()


def _has_project_acl(
	*,
	tenant_id: str,
	project_id: str,
	user_id: str,
	required_role: str,
) -> tuple[bool, str]:
	"""
	Check if user has required role in a specific project.

	Returns:
		(allowed: bool, user_role: str | None)
			- allowed: True if user has sufficient role in project
			- user_role: The user's actual role in the project, or None if no membership
	"""
	db = SessionLocal()
	try:
		member = db.execute(
			select(ProjectMember).where(
				ProjectMember.tenant_id == tenant_id,
				ProjectMember.project_id == project_id,
				ProjectMember.user_id == user_id,
				ProjectMember.deleted_at.is_(None),
			)
		).scalars().first()
		if member is None:
			return False, None
		member_role = member.role.value if hasattr(member.role, "value") else str(member.role)
		allowed = has_required_role(member_role, required_role)
		return allowed, member_role
	finally:
		db.close()


@app.middleware("http")
async def auth_and_rbac_middleware(request: Request, call_next):
	if os.getenv("AINER_AUTH_ENFORCE", "1") != "1":
		return await call_next(request)
	if request.method == "OPTIONS" or _is_public_path(request.url.path):
		return await call_next(request)

	try:
		token = extract_bearer_token(request.headers.get("authorization"))
		claims = decode_access_token(token)
	except ValueError as exc:
		message = str(exc)
		if ": " in message:
			message = message.split(": ", 1)[1]
		return build_error_response(
			request=request,
			status_code=401,
			error_code="AUTH-VALIDATION-001",
			message=message or "invalid access token",
		)

	request.state.auth_claims = claims
	required_role = _required_role(request.url.path, request.method)
	if not has_required_role(claims.role, required_role):
		return build_error_response(
			request=request,
			status_code=403,
			error_code="AUTH-FORBIDDEN-002",
			message="insufficient role for this operation",
			details={
				"required_role": required_role,
				"actual_role": claims.role,
			},
		)
	if claims.role not in {"owner", "admin", "service"}:
		project_id = _extract_project_id(request)
		if project_id:
			allowed, user_role = _has_project_acl(
				tenant_id=claims.tenant_id,
				project_id=project_id,
				user_id=claims.user_id,
				required_role=required_role,
			)
			if not allowed:
				return build_error_response(
					request=request,
					status_code=403,
					error_code="AUTH-FORBIDDEN-002",
					message="no project permission",
					details={
						"project_id": project_id,
						"required_role": required_role,
						"user_role": user_role,
					},
				)

	return await call_next(request)


@app.on_event("startup")
def startup_consumers() -> None:
	if os.getenv("AINER_ENABLE_RMQ_CONSUMERS", "1") != "1":
		return

	for topic in (
		SYSTEM_TOPICS.TASK_SUBMITTED,
		SYSTEM_TOPICS.JOB_STATUS,
		SYSTEM_TOPICS.COMPOSE_STATUS,
		SYSTEM_TOPICS.SKILL_EVENTS,
		SYSTEM_TOPICS.ALERT_EVENTS,
	):
		thread = threading.Thread(target=consume_orchestrator_topic, args=(topic,), daemon=True)
		thread.start()


@app.get("/healthz")
def healthz() -> dict[str, str]:
	return {"status": "ok"}
