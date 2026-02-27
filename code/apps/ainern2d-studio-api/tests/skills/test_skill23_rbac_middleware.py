from __future__ import annotations

import os
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))


@pytest.mark.skipif(
	not os.getenv("DATABASE_URL"),
	reason="requires DATABASE_URL for auth+rabc middleware checks",
)
def test_rbac_middleware_requires_token() -> None:
	os.environ["AINER_ENABLE_RMQ_CONSUMERS"] = "0"
	from app.main import app

	with TestClient(app) as client:
		response = client.get("/api/v1/novels")
	assert response.status_code == 401
	payload = response.json()
	assert payload["error_code"] == "AUTH-VALIDATION-001"
	assert payload["success"] is False


@pytest.mark.skipif(
	not os.getenv("DATABASE_URL"),
	reason="requires DATABASE_URL for auth+rabc middleware checks",
)
def test_rbac_middleware_admin_can_access_config_but_editor_cannot() -> None:
	os.environ["AINER_ENABLE_RMQ_CONSUMERS"] = "0"
	from app.main import app

	with TestClient(app) as client:
		admin_login = client.post(
			"/api/v1/auth/login",
			json={"username": "admin@ainer.ai", "password": "Admin@123456"},
		)
		assert admin_login.status_code == 200
		admin_token = admin_login.json()["token"]

		editor_login = client.post(
			"/api/v1/auth/login",
			json={"username": "editor@ainer.ai", "password": "Editor@123456"},
		)
		assert editor_login.status_code == 200
		editor_token = editor_login.json()["token"]

		admin_health = client.get(
			"/api/v1/config/health",
			params={"tenant_id": "default", "project_id": "default"},
			headers={"Authorization": f"Bearer {admin_token}"},
		)
		assert admin_health.status_code == 200

		editor_health = client.get(
			"/api/v1/config/health",
			params={"tenant_id": "default", "project_id": "default"},
			headers={"Authorization": f"Bearer {editor_token}"},
		)
		assert editor_health.status_code == 403
		assert editor_health.json()["error_code"] == "AUTH-FORBIDDEN-002"


@pytest.mark.skipif(
	not os.getenv("DATABASE_URL"),
	reason="requires DATABASE_URL for auth+rabc middleware checks",
)
def test_rbac_middleware_enforces_project_acl_for_editor() -> None:
	os.environ["AINER_ENABLE_RMQ_CONSUMERS"] = "0"
	from app.main import app

	suffix = uuid4().hex[:8]
	with TestClient(app) as client:
		admin_login = client.post(
			"/api/v1/auth/login",
			json={"username": "admin@ainer.ai", "password": "Admin@123456"},
		)
		assert admin_login.status_code == 200
		admin_token = admin_login.json()["token"]
		editor_login = client.post(
			"/api/v1/auth/login",
			json={"username": "editor@ainer.ai", "password": "Editor@123456"},
		)
		assert editor_login.status_code == 200
		editor_token = editor_login.json()["token"]

		project = client.post(
			"/api/v1/projects",
			json={
				"slug": f"acl-{suffix}",
				"name": f"acl-{suffix}",
				"description": "acl-check",
				"tenant_id": "default",
			},
			headers={"Authorization": f"Bearer {admin_token}"},
		)
		assert project.status_code == 201
		project_id = project.json()["project_id"]

		editor_access = client.get(
			f"/api/v1/projects/{project_id}/assets",
			params={"tenant_id": "default"},
			headers={"Authorization": f"Bearer {editor_token}"},
		)
		assert editor_access.status_code == 403
		assert editor_access.json()["error_code"] == "AUTH-FORBIDDEN-002"
