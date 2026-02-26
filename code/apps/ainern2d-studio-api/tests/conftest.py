"""Shared pytest fixtures for studio-api unit tests."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ainern2d_shared.services.base_skill import SkillContext


@pytest.fixture
def mock_db():
    """A MagicMock SQLAlchemy Session that silently accepts add/commit calls."""
    db = MagicMock()
    db.add.return_value = None
    db.commit.return_value = None
    db.flush.return_value = None
    return db


@pytest.fixture
def ctx():
    """A minimal SkillContext for unit tests."""
    return SkillContext(
        tenant_id="tenant_test",
        project_id="proj_test",
        run_id="run_test_001",
        trace_id="trace_001",
        correlation_id="corr_001",
        idempotency_key="idem_test_001",
        schema_version="1.0",
    )
