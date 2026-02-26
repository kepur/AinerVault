"""Unit tests for composer SKILLs 06 and 20."""
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
        tenant_id="t1", project_id="p1", run_id="run06",
        trace_id="tr6", correlation_id="co6",
        idempotency_key="idem06", schema_version="1.0",
    )


# ── SKILL 06: AudioTimelineService ───────────────────────────────────────────

class TestSkill06:
    def _make_service(self, db):
        from app.services.skills.skill_06_audio_timeline import AudioTimelineService
        return AudioTimelineService(db)

    def _shots(self):
        return [
            {"shot_id": "sh_001", "duration_seconds": 3.0},
            {"shot_id": "sh_002", "duration_seconds": 2.5},
        ]

    def _audio_results(self):
        return [
            {"shot_id": "sh_001", "task_type": "dialogue",
             "asset_uri": "s3://ainer/audio/sh_001_tts.wav", "volume": 1.0},
            {"shot_id": "sh_001", "task_type": "bgm",
             "asset_uri": "s3://ainer/audio/bgm_001.mp3", "volume": 0.6},
            {"shot_id": "sh_002", "task_type": "sfx",
             "asset_uri": "s3://ainer/audio/sfx_sword.wav", "volume": 0.8},
        ]

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=self._audio_results(),
            shots=self._shots(),
            timing_constraints={},
        )
        out = svc.execute(inp, ctx)
        assert out.status == "ready_for_visual_render_planning"
        assert len(out.tracks) == 3

    def test_timing_anchors_match_shots(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=[], shots=self._shots(), timing_constraints={}
        )
        out = svc.execute(inp, ctx)
        assert len(out.timing_anchors) == 2
        assert out.timing_anchors[0].shot_id == "sh_001"

    def test_total_duration_positive(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=self._audio_results(),
            shots=self._shots(),
        )
        out = svc.execute(inp, ctx)
        assert out.total_duration_ms > 0

    def test_bgm_has_fade(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=[{"shot_id": "sh_001", "task_type": "bgm",
                             "asset_uri": "s3://x/bgm.mp3", "volume": 0.5}],
            shots=[{"shot_id": "sh_001", "duration_seconds": 3.0}],
        )
        out = svc.execute(inp, ctx)
        bgm_tracks = [t for t in out.tracks if t.track_type == "bgm"]
        assert bgm_tracks[0].fade_in_ms > 0
        assert bgm_tracks[0].fade_out_ms > 0


# ── SKILL 20: DslCompilerService ─────────────────────────────────────────────

class TestSkill20:
    def _make_service(self, db):
        from app.services.skills.skill_20_dsl_compiler import DslCompilerService
        return DslCompilerService(db)

    def _shot_plans(self):
        return [
            {"shot_id": "sh_001", "positive_prompt": "ancient chinese inn, jianghu warrior",
             "negative_prompt": "modern elements", "model_backend": "comfyui", "seed": 42},
            {"shot_id": "sh_002", "positive_prompt": "mountain top, misty",
             "negative_prompt": "low quality", "model_backend": "sdxl", "seed": 123},
        ]

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_20 import Skill20Input
        svc = self._make_service(mock_db)
        inp = Skill20Input(shot_prompt_plans=self._shot_plans())
        out = svc.execute(inp, ctx)
        assert out.status == "compiled_ready"
        assert len(out.compiled_shots) == 2

    def test_backend_suffix_appended(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_20 import Skill20Input
        svc = self._make_service(mock_db)
        inp = Skill20Input(shot_prompt_plans=[
            {"shot_id": "sh_001", "positive_prompt": "test prompt",
             "model_backend": "comfyui", "seed": 1}
        ])
        out = svc.execute(inp, ctx)
        assert "steps=" in out.compiled_shots[0].positive_prompt

    def test_persona_influences_injected(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_20 import Skill20Input
        svc = self._make_service(mock_db)
        inp = Skill20Input(
            shot_prompt_plans=[
                {"shot_id": "sh_001", "positive_prompt": "test",
                 "model_backend": "sdxl", "seed": 1}
            ],
            persona_style={"narrative_tone": "dramatic", "visual_style": {}},
        )
        out = svc.execute(inp, ctx)
        assert "tone:dramatic" in out.compiled_shots[0].persona_influences

    def test_compiler_traces_present(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_20 import Skill20Input
        svc = self._make_service(mock_db)
        inp = Skill20Input(shot_prompt_plans=self._shot_plans())
        out = svc.execute(inp, ctx)
        assert len(out.compiler_traces) == 2
        assert out.compiler_traces[0].shot_id == "sh_001"
