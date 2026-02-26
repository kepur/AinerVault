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

    def _shot_plan(self):
        return [
            {"shot_id": "sh_001", "scene_id": "sc_01", "duration_ms": 3000},
            {"shot_id": "sh_002", "scene_id": "sc_01", "duration_ms": 2500},
        ]

    def _audio_results(self):
        return [
            {"shot_id": "sh_001", "task_type": "tts", "scene_id": "sc_01",
             "asset_ref": "s3://ainer/audio/sh_001_tts.wav",
             "actual_duration_ms": 2800},
            {"shot_id": "sh_001", "task_type": "bgm", "scene_id": "sc_01",
             "asset_ref": "s3://ainer/audio/bgm_001.mp3",
             "actual_duration_ms": 3000},
            {"shot_id": "sh_002", "task_type": "sfx", "scene_id": "sc_01",
             "asset_ref": "s3://ainer/audio/sfx_sword.wav",
             "actual_duration_ms": 500},
        ]

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=self._audio_results(),
            shot_plan=self._shot_plan(),
            audio_plan={"status": "ready_for_audio_execution"},
        )
        out = svc.execute(inp, ctx)
        assert out.status == "ready_for_visual_render_planning"
        assert len(out.tracks) == 3

    def test_shot_timeline_matches_shots(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=self._audio_results(),
            shot_plan=self._shot_plan(),
            audio_plan={"status": "ready"},
        )
        out = svc.execute(inp, ctx)
        assert len(out.shot_timeline) == 2
        assert out.shot_timeline[0].shot_id == "sh_001"

    def test_final_duration_positive(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=self._audio_results(),
            shot_plan=self._shot_plan(),
            audio_plan={"status": "ready"},
        )
        out = svc.execute(inp, ctx)
        assert out.final_duration_ms > 0

    def test_bgm_has_fade(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=[
                {"shot_id": "sh_001", "task_type": "tts", "scene_id": "sc_01",
                 "asset_ref": "s3://x/tts.wav", "actual_duration_ms": 1000},
                {"shot_id": "sh_001", "task_type": "bgm", "scene_id": "sc_01",
                 "asset_ref": "s3://x/bgm.mp3", "actual_duration_ms": 3000},
            ],
            shot_plan=[{"shot_id": "sh_001", "scene_id": "sc_01", "duration_ms": 3000}],
            audio_plan={"status": "ready"},
        )
        out = svc.execute(inp, ctx)
        bgm_tracks = [t for t in out.tracks if t.track_type == "bgm"]
        assert bgm_tracks[0].events[0].fade_in_ms > 0
        assert bgm_tracks[0].events[0].fade_out_ms > 0

    def test_review_when_no_tts(self, mock_db, ctx):
        """§8: TTS missing → REVIEW_REQUIRED."""
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=[{"shot_id": "sh_001", "task_type": "bgm",
                             "asset_ref": "s3://x/bgm.mp3"}],
            shot_plan=self._shot_plan(),
            audio_plan={"status": "ready"},
        )
        out = svc.execute(inp, ctx)
        assert out.status == "review_required"

    def test_mix_hints_ducking(self, mock_db, ctx):
        """§C5: Ducking hints when dialogue + bgm present."""
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=self._audio_results(),
            shot_plan=self._shot_plan(),
            audio_plan={"status": "ready"},
            feature_flags={"enable_auto_ducking_plan": True},
        )
        out = svc.execute(inp, ctx)
        duck_hints = [h for h in out.mix_hints if h.type == "duck"]
        assert len(duck_hints) >= 1
        assert duck_hints[0].trigger_track == "dialogue"

    def test_audio_event_manifest(self, mock_db, ctx):
        """§7.2: Manifest includes events + summary + visual render hints."""
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        inp = Skill06Input(
            audio_results=self._audio_results(),
            shot_plan=self._shot_plan(),
            audio_plan={"status": "ready"},
        )
        out = svc.execute(inp, ctx)
        m = out.audio_event_manifest
        assert len(m.events) == 3
        assert m.summary.dialogue_events >= 1
        assert isinstance(m.analysis_hints_for_visual_render.dialogue_heavy_shots, list)

    def test_backfill_report(self, mock_db, ctx):
        """§C2: TTS duration backfill reports shifts."""
        from ainern2d_shared.schemas.skills.skill_06 import Skill06Input
        svc = self._make_service(mock_db)
        # TTS longer than planned shot
        inp = Skill06Input(
            audio_results=[
                {"shot_id": "sh_001", "task_type": "tts", "scene_id": "sc_01",
                 "asset_ref": "s3://x/tts.wav", "actual_duration_ms": 5000},
            ],
            shot_plan=[{"shot_id": "sh_001", "scene_id": "sc_01", "duration_ms": 3000}],
            audio_plan={"status": "ready"},
        )
        out = svc.execute(inp, ctx)
        assert out.backfill_report.total_shift_ms == 2000
        assert len(out.backfill_report.entries) == 1


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
