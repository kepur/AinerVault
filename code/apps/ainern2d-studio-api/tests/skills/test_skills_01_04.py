"""Unit tests for SKILL 01–04 execute() logic."""
from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.services.base_skill import SkillContext


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.add.return_value = None
    db.commit.return_value = None
    db.flush.return_value = None
    return db


@pytest.fixture
def ctx():
    return SkillContext(
        tenant_id="t1", project_id="p1", run_id="run01",
        trace_id="tr1", correlation_id="co1",
        idempotency_key="idem01", schema_version="1.0",
    )


# ── SKILL 01: StoryIngestionService ──────────────────────────────────────────

class TestSkill01:
    def _make_service(self, mock_db):
        from app.services.skills.skill_01_story_ingestion import StoryIngestionService
        return StoryIngestionService(mock_db)

    def test_execute_basic_zh_story(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_01 import Skill01Input
        svc = self._make_service(mock_db)
        inp = Skill01Input(raw_text="第一章 少年出山\n\n少年提剑走天涯，行至一处客栈。")
        out = svc.execute(inp, ctx)
        assert out.status in ("ready_for_routing", "review_required")
        assert out.language_detection.primary_language != ""
        assert out.normalized_text != ""
        assert out.tenant_id == ctx.tenant_id
        assert out.project_id == ctx.project_id
        assert out.trace_id == ctx.trace_id
        assert out.correlation_id == ctx.correlation_id
        assert out.idempotency_key == ctx.idempotency_key
        assert out.schema_version == ctx.schema_version

    def test_execute_empty_text_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_01 import Skill01Input
        svc = self._make_service(mock_db)
        inp = Skill01Input(raw_text="   ")
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)

    def test_execute_en_story(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_01 import Skill01Input
        svc = self._make_service(mock_db)
        inp = Skill01Input(
            raw_text="Chapter 1: The Hero's Journey\nA young warrior sets out on a quest.",
        )
        out = svc.execute(inp, ctx)
        assert out.status in ("ready_for_routing", "review_required")
        assert "en" in out.language_detection.primary_language.lower()

    def test_output_has_structure(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_01 import Skill01Input
        svc = self._make_service(mock_db)
        inp = Skill01Input(
            raw_text="第一章\n第一节 开篇\n主角登场。\n\n第二章\n第二节 发展",
        )
        out = svc.execute(inp, ctx)
        assert out.structure is not None
        assert out.ingestion_log is not None


# ── SKILL 02: LanguageContextService ─────────────────────────────────────────

class TestSkill02:
    def _make_service(self, mock_db):
        from app.services.skills.skill_02_language_context import LanguageContextService
        return LanguageContextService(mock_db)

    def test_execute_zh_wuxia(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_02 import Skill02Input
        svc = self._make_service(mock_db)
        inp = Skill02Input(
            primary_language="zh-CN",
            genre="wuxia",
            story_world_setting="ancient China",
            normalized_text="行走江湖，快意恩仇",
        )
        out = svc.execute(inp, ctx)
        assert out.status.startswith("ready") or out.status == "failed"
        assert len(out.culture_candidates) > 0
        assert any("wuxia" in c.culture_pack_id for c in out.culture_candidates)

    def test_execute_en_fantasy(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_02 import Skill02Input
        svc = self._make_service(mock_db)
        inp = Skill02Input(
            primary_language="en-US",
            genre="fantasy",
            story_world_setting="medieval fantasy kingdom",
            normalized_text="A dragon loomed over the castle.",
        )
        out = svc.execute(inp, ctx)
        assert out.language_route is not None
        assert out.language_route.source_primary_language == "en-US"

    def test_execute_empty_language_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_02 import Skill02Input
        svc = self._make_service(mock_db)
        inp = Skill02Input(primary_language="", normalized_text="some text")
        with pytest.raises(ValueError, match="REQ-VALIDATION-001"):
            svc.execute(inp, ctx)


# ── SKILL 03: SceneShotPlanService ───────────────────────────────────────────

class TestSkill03:
    def _make_service(self, mock_db):
        from app.services.skills.skill_03_scene_shot_plan import SceneShotPlanService
        return SceneShotPlanService(mock_db)

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_03 import Skill03Input
        svc = self._make_service(mock_db)
        inp = Skill03Input(
            segments=[
                {"segment_id": "s1", "chapter_id": "ch_001",
                 "text": "主角走进客栈，四处张望。"},
                {"segment_id": "s2", "chapter_id": "ch_002",
                 "text": "一场打斗在后院展开。"},
            ],
            culture_hint="wuxia",
        )
        out = svc.execute(inp, ctx)
        assert out.status in ("ready_for_parallel_execution", "review_required")
        assert len(out.scene_plan) >= 1
        assert len(out.shot_plan) >= 1

    def test_provisional_timeline_non_empty(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_03 import Skill03Input
        svc = self._make_service(mock_db)
        inp = Skill03Input(
            segments=[{"segment_id": "s1", "chapter_id": "ch_001",
                        "text": "主角望向远方。"}],
        )
        out = svc.execute(inp, ctx)
        assert out.provisional_timeline is not None
        assert out.provisional_timeline.total_duration_estimate_ms >= 0

    def test_empty_segments_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_03 import Skill03Input
        svc = self._make_service(mock_db)
        inp = Skill03Input(segments=[])
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)


# ── SKILL 04: EntityExtractionService ────────────────────────────────────────

class TestSkill04:
    def _make_service(self, mock_db):
        from app.services.skills.skill_04_entity_extraction import EntityExtractionService
        return EntityExtractionService(mock_db)

    def test_execute_extracts_characters(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_04 import Skill04Input
        svc = self._make_service(mock_db)
        inp = Skill04Input(
            segments=[{"segment_id": "s1", "body": "少侠李明走进了客栈，掌柜王大叔迎了上来。"}],
            scene_plan=[{"scene_id": "sc_001", "scene_title": "客栈"}],
            shot_plan=[{"shot_id": "sh_001", "scene_id": "sc_001"}],
            primary_language="zh-CN",
        )
        out = svc.execute(inp, ctx)
        assert out.status in ("ready_for_canonicalization", "review_required")
        assert out.entity_summary.total_entities >= 0
        assert out.continuity_handoff is not None
        assert out.continuity_handoff.shot_plan_refs

    def test_execute_en_text(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_04 import Skill04Input
        svc = self._make_service(mock_db)
        inp = Skill04Input(
            segments=[{"segment_id": "s1", "body": "Sir Arthur entered the castle. Lady Eleanor greeted him."}],
            scene_plan=[{"scene_id": "sc_001", "scene_title": "Castle"}],
            shot_plan=[{"shot_id": "sh_001", "scene_id": "sc_001"}],
            primary_language="en-US",
        )
        out = svc.execute(inp, ctx)
        assert out.status in ("ready_for_canonicalization", "review_required")

    def test_empty_input_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_04 import Skill04Input
        svc = self._make_service(mock_db)
        inp = Skill04Input(
            segments=[], scene_plan=[], shot_plan=[], primary_language="zh-CN"
        )
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)
