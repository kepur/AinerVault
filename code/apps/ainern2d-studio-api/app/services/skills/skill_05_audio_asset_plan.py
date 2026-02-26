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
    BackendAudioCapability,
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

# SFX density levels used by auto-density feature
_SFX_AUTO_DENSITY: dict[str, str] = {
    "action": "high",
    "dialogue": "low",
    "atmosphere": "medium",
    "transition": "low",
    "generic": "medium",
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

        # Parse feature flags once
        ff = input_dto.feature_flags
        ff_sfx_auto_density: bool = ff.get("enable_sfx_auto_density", False)
        ff_ambience_layers: bool = ff.get("enable_ambience_scene_layers", False)
        ff_parallel_groups: bool = ff.get("enable_parallel_audio_groups", True)

        # Parse user overrides once
        uo = input_dto.user_overrides
        uo_voice_prefs: dict[str, str] = uo.get("voice_preferences", {})
        uo_bgm_selections: dict[str, str] = uo.get("bgm_selections", {})
        uo_sfx_density_override: str | None = uo.get("sfx_density_override")
        uo_ambience_override: dict[str, str] = uo.get("ambience_override", {})

        # ── [A1] Precheck ─────────────────────────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")
        if not input_dto.shot_plan:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError("REQ-VALIDATION-001: shot_plan is empty — SKILL 03 output required")

        # Validate voice_cast_profile completeness
        self._validate_voice_cast(input_dto, warnings)

        # Validate backend_audio_capability if provided
        backend_cap = input_dto.backend_audio_capability

        # Index scene metadata for quick lookup
        scene_by_id: dict[str, dict] = {
            s.get("scene_id", ""): s for s in input_dto.scene_plan
        }

        # ── [A2] TTS Planning ─────────────────────────────────────────────────
        self._record_state(ctx, "PRECHECKING", "PLANNING_TTS")
        tts_plan = self._plan_tts(input_dto, scene_by_id, uo_voice_prefs, warnings)
        if not tts_plan:
            warnings.append("tts_plan_empty: no dialogue shots found in shot_plan")

        # Validate TTS speakers against backend
        if backend_cap:
            self._validate_backend_tts(tts_plan, backend_cap, warnings)

        # ── [A3] BGM Planning ─────────────────────────────────────────────────
        self._record_state(ctx, "PLANNING_TTS", "PLANNING_BGM")
        bgm_plan = self._plan_bgm(
            input_dto.scene_plan, input_dto.music_style_profile,
            uo_bgm_selections, warnings,
        )

        # Validate BGM moods against backend
        if backend_cap:
            self._validate_backend_bgm(bgm_plan, backend_cap, warnings)

        # ── [A4] SFX + Ambience Planning ─────────────────────────────────────
        self._record_state(ctx, "PLANNING_BGM", "PLANNING_SFX_AMBIENCE")
        sfx_plan = self._plan_sfx(
            input_dto.shot_plan, input_dto.audio_event_candidates,
            scene_by_id, ff_sfx_auto_density, uo_sfx_density_override, warnings,
        )
        ambience_plan = self._plan_ambience(
            input_dto.scene_plan, ff_ambience_layers,
            uo_ambience_override, warnings,
        )

        # Validate SFX event types against backend
        if backend_cap:
            self._validate_backend_sfx(sfx_plan, backend_cap, warnings)

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

        if ff_parallel_groups:
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
        else:
            # All tasks in a single sequential group
            parallel_groups = [
                ParallelAudioGroup(group_id="PA_ALL", tasks=all_task_ids),
            ]
            warnings.append(
                "parallel_groups_disabled: all tasks placed in single sequential group"
            )

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

    # ── [A1] Voice-cast & backend validation helpers ──────────────────────────

    @staticmethod
    def _validate_voice_cast(
        input_dto: Skill05Input,
        warnings: list[str],
    ) -> None:
        """Check that every character referenced in shot_plan has a voice cast entry."""
        voice_cast = input_dto.voice_cast_profile
        if not voice_cast:
            return
        seen_speakers: set[str] = set()
        for shot in input_dto.shot_plan:
            for ch in shot.get("characters_present", []):
                seen_speakers.add(ch)
        for spk in sorted(seen_speakers):
            if spk not in voice_cast:
                warnings.append(
                    f"voice_cast_unresolved: speaker '{spk}' not found in voice_cast_profile"
                )

    @staticmethod
    def _validate_backend_tts(
        tts_plan: list[TTSTask],
        cap: BackendAudioCapability,
        warnings: list[str],
    ) -> None:
        if not cap.supported_tts_speakers:
            return
        supported = set(cap.supported_tts_speakers)
        for task in tts_plan:
            if task.speaker_id not in supported and task.speaker_id != "speaker_unknown":
                warnings.append(
                    f"backend_capability_unsupported_speaker: "
                    f"'{task.speaker_id}' not in backend supported speakers"
                )

    @staticmethod
    def _validate_backend_bgm(
        bgm_plan: list[BGMTask],
        cap: BackendAudioCapability,
        warnings: list[str],
    ) -> None:
        if not cap.supported_bgm_moods:
            return
        supported = set(cap.supported_bgm_moods)
        for task in bgm_plan:
            if task.mood not in supported:
                warnings.append(
                    f"backend_capability_unsupported_mood: "
                    f"'{task.mood}' not in backend supported moods"
                )

    @staticmethod
    def _validate_backend_sfx(
        sfx_plan: list[SFXTask],
        cap: BackendAudioCapability,
        warnings: list[str],
    ) -> None:
        if not cap.supported_sfx_event_types:
            return
        supported = set(cap.supported_sfx_event_types)
        for task in sfx_plan:
            if task.event_type not in supported:
                warnings.append(
                    f"backend_capability_unsupported_sfx: "
                    f"'{task.event_type}' not in backend supported event types"
                )

    # ── [A2] TTS Planning ─────────────────────────────────────────────────────

    @staticmethod
    def _plan_tts(
        input_dto: Skill05Input,
        scene_by_id: dict[str, dict],
        uo_voice_prefs: dict[str, str],
        warnings: list[str],
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
            # Apply voice cast mapping
            speaker_id = voice_cast.get(speaker_id, speaker_id)
            # Apply user override voice preference (highest priority)
            if speaker_id in uo_voice_prefs:
                original = speaker_id
                speaker_id = uo_voice_prefs[speaker_id]
                warnings.append(
                    f"user_override_applied: voice preference "
                    f"'{original}' → '{speaker_id}'"
                )

            # TTS text backfill: extract dialogue text from shot_plan data
            text = (
                shot.get("dialogue_text", "")
                or shot.get("text", "")
                or shot.get("subtitle", "")
            )
            if not text:
                warnings.append(
                    f"tts_text_missing: shot '{shot_id}' requires TTS but has no "
                    f"dialogue_text/text/subtitle — must be filled by orchestrator"
                )

            tasks.append(
                TTSTask(
                    tts_task_id=f"TTS_{uuid4().hex[:6].upper()}",
                    scene_id=scene_id,
                    shot_id=shot_id,
                    speaker_id=speaker_id,
                    text=text,
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
        uo_bgm_selections: dict[str, str],
        warnings: list[str],
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

            # Apply user override for BGM mood
            if scene_id in uo_bgm_selections:
                original_mood = mood
                mood = uo_bgm_selections[scene_id]
                warnings.append(
                    f"user_override_applied: bgm mood for scene '{scene_id}' "
                    f"'{original_mood}' → '{mood}'"
                )

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
        scene_by_id: dict[str, dict],
        ff_sfx_auto_density: bool,
        uo_sfx_density_override: str | None,
        warnings: list[str],
    ) -> list[SFXTask]:
        tasks: list[SFXTask] = []

        for shot in shot_plan:
            shot_id = shot.get("shot_id", "")
            scene_id = shot.get("scene_id", "")
            scene = scene_by_id.get(scene_id, {})
            scene_type = scene.get("scene_type", "generic")

            for hint in shot.get("audio_hints", []):
                if hint in _SFX_HINT_KEYWORDS:
                    event_type = hint.replace("_sfx", "").replace("_possible", "")
                    density = "high" if "metal" in hint or "explosion" in hint else "medium"

                    # Feature flag: auto-density based on scene type
                    if ff_sfx_auto_density:
                        auto = _SFX_AUTO_DENSITY.get(scene_type, "medium")
                        if auto != density:
                            warnings.append(
                                f"sfx_density_auto_adjusted: shot '{shot_id}' "
                                f"'{density}' → '{auto}' (scene_type={scene_type})"
                            )
                            density = auto

                    # User override: global SFX density
                    if uo_sfx_density_override and uo_sfx_density_override in (
                        "low", "medium", "high",
                    ):
                        density = uo_sfx_density_override

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
                density = "medium"
                if uo_sfx_density_override and uo_sfx_density_override in (
                    "low", "medium", "high",
                ):
                    density = uo_sfx_density_override
                tasks.append(
                    SFXTask(
                        sfx_task_id=f"SFX_{uuid4().hex[:6].upper()}",
                        shot_id=shot_id,
                        event_type=event_type,
                        density_hint=density,
                    )
                )
        return tasks

    # ── Ambience Planning ─────────────────────────────────────────────────────

    @staticmethod
    def _plan_ambience(
        scene_plan: list[dict],
        ff_ambience_layers: bool,
        uo_ambience_override: dict[str, str],
        warnings: list[str],
    ) -> list[AmbienceTask]:
        tasks: list[AmbienceTask] = []
        for scene in scene_plan:
            scene_id = scene.get("scene_id", "")
            scene_type = scene.get("scene_type", "generic")
            loc = scene.get("scene_location_hint", "")

            base_type = _AMBIENCE_MAP.get(scene_type, "generic_ambient_low")
            if loc and loc not in ("unknown", ""):
                base_type = f"{base_type}_{loc}"[:64]

            layering = "medium" if scene_type == "action" else "low_medium"

            # User override for ambience type
            if scene_id in uo_ambience_override:
                original = base_type
                base_type = uo_ambience_override[scene_id]
                warnings.append(
                    f"user_override_applied: ambience for scene '{scene_id}' "
                    f"'{original}' → '{base_type}'"
                )

            tasks.append(
                AmbienceTask(
                    amb_task_id=f"AMB_{scene_id}",
                    scene_id=scene_id,
                    ambience_type=base_type,
                    layering_hint=layering,
                )
            )

            # Feature flag: add extra ambience layer for scene transitions
            if ff_ambience_layers and scene_type in ("action", "atmosphere"):
                layer_type = f"{base_type}_layer"[:64]
                tasks.append(
                    AmbienceTask(
                        amb_task_id=f"AMB_{scene_id}_L2",
                        scene_id=scene_id,
                        ambience_type=layer_type,
                        layering_hint="medium",
                    )
                )
                warnings.append(
                    f"ambience_layer_added: extra layer for scene '{scene_id}' "
                    f"(scene_type={scene_type})"
                )

        return tasks
