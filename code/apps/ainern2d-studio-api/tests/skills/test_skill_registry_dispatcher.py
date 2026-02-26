"""Unit tests for SkillRegistry and SkillDispatcher."""
from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType
from ainern2d_shared.services.base_skill import SkillContext


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.add.return_value = None
    db.commit.return_value = None
    db.flush.return_value = None
    return db


# ── SkillRegistry ─────────────────────────────────────────────────────────────

class TestSkillRegistry:
    def test_list_skills_returns_all(self, mock_db):
        from app.services.skill_registry import SkillRegistry
        skills = SkillRegistry.list_skills()
        assert len(skills) >= 17  # 01-05, 07-19 (06+20 are in composer)
        assert "skill_01" in skills
        assert "skill_10" in skills
        assert "skill_19" in skills

    def test_get_unknown_raises(self, mock_db):
        from app.services.skill_registry import SkillRegistry
        registry = SkillRegistry(mock_db)
        with pytest.raises(ValueError, match="Unknown skill_id"):
            registry.get("skill_99")

    def test_get_returns_singleton(self, mock_db):
        from app.services.skill_registry import SkillRegistry
        registry = SkillRegistry(mock_db)
        s1 = registry.get("skill_01")
        s2 = registry.get("skill_01")
        assert s1 is s2

    def test_is_registered(self, mock_db):
        from app.services.skill_registry import SkillRegistry
        assert SkillRegistry.is_registered("skill_07")
        assert not SkillRegistry.is_registered("skill_06")  # composer only
        assert not SkillRegistry.is_registered("skill_99")


# ── SkillDispatcher ───────────────────────────────────────────────────────────

class TestSkillDispatcher:
    def _make_job(self, job_type_val: str, payload: dict | None = None) -> MagicMock:
        job = MagicMock()
        job.id = "job_001"
        job.job_type = MagicMock()
        job.job_type.value = job_type_val
        job.run_id = "run_001"
        job.tenant_id = "t1"
        job.project_id = "p1"
        job.idempotency_key = "idem_001"
        job.payload_json = payload or {}
        job.attempts = 0
        job.status = JobStatus.enqueued
        return job

    def test_list_skill_job_types(self, mock_db):
        from app.services.skill_dispatcher import SkillDispatcher
        mapping = SkillDispatcher.list_skill_job_types()
        assert JobType.ingest_story.value in mapping
        assert mapping[JobType.ingest_story.value] == "skill_01"
        assert JobType.extract_entities.value in mapping
        assert mapping[JobType.extract_entities.value] == "skill_04"
        assert JobType.evaluate_quality.value in mapping
        assert mapping[JobType.evaluate_quality.value] == "skill_16"

    def test_worker_job_skipped(self, mock_db):
        from app.services.skill_dispatcher import SkillDispatcher
        dispatcher = SkillDispatcher(mock_db)
        job = self._make_job(JobType.render_video.value)
        result = dispatcher.execute_job(job)
        assert result is None
        # Status should NOT have been set to claimed/success
        job.status = JobStatus.enqueued  # unchanged

    def test_unknown_job_type_sets_failed(self, mock_db):
        from app.services.skill_dispatcher import SkillDispatcher
        dispatcher = SkillDispatcher(mock_db)
        job = self._make_job("unknown_type_xyz")
        result = dispatcher.execute_job(job)
        assert result is None
        assert job.status == JobStatus.failed

    def test_ingest_story_dispatches_skill_01(self, mock_db):
        from app.services.skill_dispatcher import SkillDispatcher
        from ainern2d_shared.schemas.skills.skill_01 import Skill01Input
        dispatcher = SkillDispatcher(mock_db)
        payload = {
            "raw_story_text": "第一章 少年出山\n主角登场",
            "source_type": "text",
            "tenant_id": "t1",
            "project_id": "p1",
        }
        job = self._make_job(JobType.ingest_story.value, payload)

        # Patch registry dispatch to avoid real execution
        with patch.object(dispatcher._registry, "dispatch") as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                model_dump=lambda mode: {"status": "ready_for_routing"}
            )
            dispatcher.execute_job(job)
            assert mock_dispatch.called
            call_args = mock_dispatch.call_args
            assert call_args[0][0] == "skill_01"

    def test_extract_entities_dispatches_skill_04(self, mock_db):
        from app.services.skill_dispatcher import SkillDispatcher
        dispatcher = SkillDispatcher(mock_db)
        job = self._make_job(JobType.extract_entities.value, {})
        with patch.object(dispatcher._registry, "dispatch") as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                model_dump=lambda mode: {"status": "ready_for_canonicalization"}
            )
            dispatcher.execute_job(job)
            assert mock_dispatch.call_args[0][0] == "skill_04"

    def test_execute_job_marks_success(self, mock_db):
        from app.services.skill_dispatcher import SkillDispatcher
        dispatcher = SkillDispatcher(mock_db)
        job = self._make_job(JobType.ingest_story.value, {
            "raw_story_text": "第一章\n开场",
            "source_type": "text",
            "tenant_id": "t1",
            "project_id": "p1",
        })
        with patch.object(dispatcher._registry, "dispatch") as mock_dispatch:
            mock_out = MagicMock()
            mock_out.model_dump.return_value = {"status": "ready_for_routing"}
            mock_dispatch.return_value = mock_out
            dispatcher.execute_job(job)
        assert job.status == JobStatus.success
