from __future__ import annotations

import os
import threading

from fastapi import FastAPI, Request

from ainern2d_shared.queue.topics import SYSTEM_TOPICS

from app.api.deps import has_required_role
from app.api.error_mapping import build_error_response, register_error_handlers
from app.api.v1.assets import router as assets_router
from app.api.v1.auth import router as auth_router
from app.api.v1.config_center import router as config_center_router
from app.api.v1.culture_packs import router as culture_packs_router
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
from app.security.auth_token import decode_access_token, extract_bearer_token

app = FastAPI(title="ainern2d-studio-api", version="0.1.0")
register_error_handlers(app)
app.include_router(auth_router)
app.include_router(task_router)
app.include_router(orchestrator_router)
app.include_router(observer_router)
app.include_router(projects_router)
app.include_router(novels_router)
app.include_router(config_center_router)
app.include_router(rag_console_router)
app.include_router(culture_packs_router)
app.include_router(assets_router)
app.include_router(timeline_router)
app.include_router(regenerate_router)
app.include_router(preview_router)

_PUBLIC_PATHS = {
	"/healthz",
	"/api/v1/auth/login",
	"/api/v1/auth/register",
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
)


def _is_public_path(path: str) -> bool:
	if path in _PUBLIC_PATHS:
		return True
	return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def _required_role(path: str, method: str) -> str:
	if any(path.startswith(prefix) for prefix in _ADMIN_PREFIXES):
		return "admin"
	if path in {"/api/v1/auth/me", "/api/v1/auth/logout"}:
		return "viewer"
	if method in {"POST", "PUT", "PATCH", "DELETE"}:
		return "editor"
	return "viewer"


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
	):
		thread = threading.Thread(target=consume_orchestrator_topic, args=(topic,), daemon=True)
		thread.start()


@app.get("/healthz")
def healthz() -> dict[str, str]:
	return {"status": "ok"}
