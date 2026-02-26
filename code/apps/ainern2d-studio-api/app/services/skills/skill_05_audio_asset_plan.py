"""SKILL 05: AudioAssetPlanService — 业务逻辑实现。
参考规格: SKILL_05_AUDIO_ASSET_PLANNER.md
状态: SERVICE_READY
"""
from __future__ import annotations

from uuid import uuid4

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_05 import (
    AmbienceTask,
    AudioTaskDAG,
    BGMTask,
    ParallelAudioGroup,
    ProvisionalAudioTimeline,
    SFXTask,
    Skill05Input,
    Skill05Output,
    TTSTask,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Ambience type mapping ──────────────────────────────────────────────────────
_AMBIENCE_MAP: dict[str, str] = {
    "action": "outdoor_wind_battle_atmosphere",
    "dialogue": "indoor_murmur_ambient_low",
    "atmosphere": "outdoor_nature_ambient",
    "atmosphere_dialogue": "indoor_crowd_murmur_wind_leak",
    "transition": "transitional_ambient_fade",
    "generic": "generic_ambient_low",
}

_BGM_MOOD_MAP: dict[str, str] = {
    "tense": "tense_suspense",
    "calm": "peaceful_melodic",
    "dramatic": "epic_dramatic",
    "joyful": "upbeat_light",
    "sad": "melancholic_slow",
    "neutral": "neutral_background",
}

_NON_TTS_HINTS = {"ambient_environment", "wind_rain", "crowd", "outdoor_nature_ambient"}

_SFX_HINT_KEYWORDS = {
    "metal_hit_sfx", "movement_sfx", "metal_hit_possible",
    "action_sfx", "metal_hit", "explosion",
}


class AudioAssetPlanService(BaseSkillService[Skill05Input, Skill05Output]):
    """SKILL 05 — Audio Asset Planner.

    State machine:
      INIT → PRECHECKING → PLANNING_TTS → PLANNING_BGM
           → PLANNING_SFX_AMBIENCE → BUILDING_AUDIO_DAG
           → READY_FOR_AUDIO_EXECUTION | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_05"
    skill_name = "AudioAssetPlanService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Public entry ───────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill05Input, ctx: SkillContext) -> Skill05Output:
        warnings: list[str] = []

        # ── [A1] Precheck ─────────────────────────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")
        if not input_dto.shot_plan:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError("REQ-VALIDATION-001: shot_plan is empty — SKILL 03 output required")

        # Index scene metadata for quick lookup
        scene_by_id: dict[str, dict] = {
            s.get("scene_id", ""): s for s in input_dto.scene_plan
        }

        # ── [A2] TTS Planning ─────────────────────────────────────────────────
        self._record_state(ctx, "PRECHECKING", "PLANNING_TTS")
        tts_plan = self._plan_tts(input_dto, scene_by_id)
        if not tts_plan:
            warnings.append("tts_plan_empty: no dialogue shots found in shot_plan")

        # ── [A3] BGM Planning ─────────────────────────────────────────────────
        self._record_state(ctx, "PLANNING_TTS", "PLANNING_BGM")
        bgm_plan = self._plan_bgm(input_dto.scene_plan, input_dto.music_style_profile)

        # ── [A4] SFX + Ambience Planning ─────────────────────────────────────
        self._record_state(ctx, "PLANNING_BGM", "PLANNING_SFX_AMBIENCE")
        sfx_plan = self._plan_sfx(input_dto.shot_plan, input_dto.audio_event_candidates)
        ambience_plan = self._plan_ambience(input_dto.scene_plan)

        # ── [A5] Audio DAG + Parallel Groups ──────────────────────────────────
        self._record_state(ctx, "PLANNING_SFX_AMBIENCE", "BUILDING_AUDIO_DAG")
        all_task_ids = (
            [t.tts_task_id for t in tts_plan]
            + [t.bgm_task_id for t in bgm_plan]
            + [t.sfx_task_id for t in sfx_plan]
            + [t.amb_task_id for t in ambience_plan]
        )
        finalize_node = "AUDIO_TIMELINE_FINALIZE"
        dag = AudioTaskDAG(
            nodes=all_task_ids + [finalize_node],
            edges=[[tid, finalize_node] for tid in all_task_ids],
        )
        parallel_groups = [
            ParallelAudioGroup(
                group_id="PA1",
                tasks=[t.tts_task_id for t in tts_plan],
            ),
            ParallelAudioGroup(
                group_id="PA2",
                tasks=[t.bgm_task_id for t in bgm_plan]
                + [t.amb_task_id for t in ambience_plan],
            ),
            ParallelAudioGroup(
                group_id="PA3",
                tasks=[t.sfx_task_id for t in sfx_plan],
            ),
        ]

        # ── Final status ──────────────────────────────────────────────────────
        self._record_state(ctx, "BUILDING_AUDIO_DAG", "READY_FOR_AUDIO_EXECUTION")
        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"tts={len(tts_plan)} bgm={len(bgm_plan)} "
            f"sfx={len(sfx_plan)} amb={len(ambience_plan)}"
        )
        return Skill05Output(
            tts_plan=tts_plan,
            bgm_plan=bgm_plan,
            sfx_plan=sfx_plan,
            ambience_plan=ambience_plan,
            audio_task_dag=dag,
            provisional_audio_timeline=ProvisionalAudioTimeline(
                is_final=False,
                requires_tts_duration_backfill=bool(tts_plan),
            ),
            parallel_audio_groups=parallel_groups,
            warnings=warnings,
            status="ready_for_audio_execution",
        )

    # ── [A2] TTS Planning ─────────────────────────────────────────────────────

    @staticmethod
    def _plan_tts(
        input_dto: Skill05Input,
        scene_by_id: dict[str, dict],
    ) -> list[TTSTask]:
        tasks: list[TTSTask] = []
        voice_cast = input_dto.voice_cast_profile

        for shot in input_dto.shot_plan:
            audio_hints: list[str] = shot.get("audio_hints", [])
            tts_needed = (
                shot.get("tts_backfill_required", False)
                or "dialogue_tts" in audio_hints
            )
            if not tts_needed:
                continue

            shot_id = shot.get("shot_id", "")
            scene_id = shot.get("scene_id", "")
            scene = scene_by_id.get(scene_id, {})
            emotion = scene.get("emotion_tone", "neutral")

            characters = shot.get("characters_present", [])
            speaker_id = characters[0] if characters else "speaker_unknown"
            # Allow voice cast override
            speaker_id = voice_cast.get(speaker_id, speaker_id)

            tasks.append(
                TTSTask(
                    tts_task_id=f"TTS_{uuid4().hex[:6].upper()}",
                    scene_id=scene_id,
                    shot_id=shot_id,
                    speaker_id=speaker_id,
                    text="",  # actual text to be filled by orchestrator
                    emotion_hint=emotion,
                    speed_hint="slow" if emotion in ("sad", "tense") else "normal",
                    must_complete_before_final_timeline=True,
                )
            )
        return tasks

    # ── [A3] BGM Planning ─────────────────────────────────────────────────────

    @staticmethod
    def _plan_bgm(
        scene_plan: list[dict],
        music_style: dict,
    ) -> list[BGMTask]:
        tasks: list[BGMTask] = []
        style_prefix = music_style.get("culture_prefix", "")

        for scene in scene_plan:
            scene_id = scene.get("scene_id", "")
            emotion = scene.get("emotion_tone", "neutral")
            scene_type = scene.get("scene_type", "generic")
            mood = _BGM_MOOD_MAP.get(emotion, "neutral_background")
            if style_prefix:
                mood = f"{style_prefix}_{mood}"
            intensity = "high" if scene_type == "action" else "medium"

            tasks.append(
                BGMTask(
                    bgm_task_id=f"BGM_{scene_id}",
                    scene_id=scene_id,
                    mood=mood,
                    intensity=intensity,
                    provisional_start_ref=f"{scene_id}_START",
                    provisional_end_ref=f"{scene_id}_END",
                )
            )
        return tasks

    # ── [A4] SFX Planning ────────────────────────────────────────────────────

    @staticmethod
    def _plan_sfx(
        shot_plan: list[dict],
        audio_event_candidates: list[dict],
    ) -> list[SFXTask]:
        tasks: list[SFXTask] = []

        for shot in shot_plan:
            shot_id = shot.get("shot_id", "")
            for hint in shot.get("audio_hints", []):
                if hint in _SFX_HINT_KEYWORDS:
                    event_type = hint.replace("_sfx", "").replace("_possible", "")
                    density = "high" if "metal" in hint or "explosion" in hint else "medium"
                    tasks.append(
                        SFXTask(
                            sfx_task_id=f"SFX_{uuid4().hex[:6].upper()}",
                            shot_id=shot_id,
                            event_type=event_type,
                            density_hint=density,
                        )
                    )

        # Supplement from audio_event_candidates
        for candidate in audio_event_candidates:
            event_type = candidate.get("event_type", "")
            shot_id = candidate.get("source_shot_id", "")
            conf = candidate.get("confidence", 0.5)
            if event_type and conf > 0.5:
                tasks.append(
                    SFXTask(
                        sfx_task_id=f"SFX_{uuid4().hex[:6].upper()}",
                        shot_id=shot_id,
                        event_type=event_type,
                        density_hint="medium",
                    )
                )
        return tasks

    # ── Ambience Planning ─────────────────────────────────────────────────────

    @staticmethod
    def _plan_ambience(scene_plan: list[dict]) -> list[AmbienceTask]:
        tasks: list[AmbienceTask] = []
        for scene in scene_plan:
            scene_id = scene.get("scene_id", "")
            scene_type = scene.get("scene_type", "generic")
            loc = scene.get("scene_location_hint", "")

            base_type = _AMBIENCE_MAP.get(scene_type, "generic_ambient_low")
            if loc and loc not in ("unknown", ""):
                base_type = f"{base_type}_{loc}"[:64]

            tasks.append(
                AmbienceTask(
                    amb_task_id=f"AMB_{scene_id}",
                    scene_id=scene_id,
                    ambience_type=base_type,
                    layering_hint="medium" if scene_type == "action" else "low_medium",
                )
            )
        return tasks
