from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../"))

from ainern2d_shared.config.setting import settings
from app.api.v1.ops_bridge import _upsert_env_assignments, router


def test_storage_config_returns_copyable_minio_settings() -> None:
    app = FastAPI()
    app.include_router(router)

    original_values = {
        "storage_backend": settings.storage_backend,
        "s3_endpoint": settings.s3_endpoint,
        "s3_public_endpoint": settings.s3_public_endpoint,
        "s3_access_key": settings.s3_access_key,
        "s3_secret_key": settings.s3_secret_key,
        "s3_bucket": settings.s3_bucket,
        "s3_region": settings.s3_region,
        "minio_root_user": settings.minio_root_user,
        "minio_root_password": settings.minio_root_password,
        "minio_console_endpoint": settings.minio_console_endpoint,
    }
    try:
        settings.storage_backend = "minio"
        settings.s3_endpoint = "http://minio:9000"
        settings.s3_public_endpoint = "http://localhost:9000"
        settings.s3_access_key = "ainer_minio"
        settings.s3_secret_key = "ainer_minio_2024"
        settings.s3_bucket = "ainer-assets"
        settings.s3_region = "us-east-1"
        settings.minio_root_user = "ainer_minio"
        settings.minio_root_password = "ainer_minio_2024"
        settings.minio_console_endpoint = "http://localhost:9001"

        with TestClient(app) as client:
            response = client.get("/api/v1/ops-bridge/storage-config")

        assert response.status_code == 200
        payload = response.json()
        assert payload["provider"] == "minio"
        assert payload["endpoint"] == "http://localhost:9000"
        assert payload["internal_endpoint"] == "http://minio:9000"
        assert payload["access_key"] == "ainer_minio"
        assert payload["secret_key"] == "ainer_minio_2024"
        assert payload["copy_env_block"].count("\n") >= 8
        assert "S3_PUBLIC_ENDPOINT=http://localhost:9000" in payload["copy_env_block"]
        assert "MINIO_ROOT_PASSWORD=ainer_minio_2024" in payload["copy_env_block"]
    finally:
        for key, value in original_values.items():
            setattr(settings, key, value)


def test_upsert_env_assignments_replaces_and_appends_values() -> None:
    content = "LOG_LEVEL=INFO\nS3_ENDPOINT=http://old:9000\n"
    updated = _upsert_env_assignments(
        content,
        {
            "S3_ENDPOINT": "http://minio:9000",
            "S3_PUBLIC_ENDPOINT": "http://localhost:9000",
        },
    )
    assert "S3_ENDPOINT=http://minio:9000" in updated
    assert "S3_PUBLIC_ENDPOINT=http://localhost:9000" in updated
    assert updated.count("S3_ENDPOINT=") == 1