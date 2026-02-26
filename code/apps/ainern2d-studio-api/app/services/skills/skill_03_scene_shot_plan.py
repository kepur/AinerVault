"""SKILL 03: SceneShotPlanService — 业务逻辑实现。
参考规格: SKILL_03_STORY_SCENE_SHOT_PLANNER.md
状态: SERVICE_READY
"""
from __future__ import annotations

import re
from uuid import uuid4

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_03 import (
    AudioPreHint,
    EntityExtractionHints,
    ParallelTaskGroup,
    ProvisionalTimeline,
    ScenePlan,
    Skill03Input,
    Skill03Output,
    ShotPlan,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Signal keyword sets ────────────────────────────────────────────────────────
_LOCATION_ZH = re.compile(
    r"客栈|山|城|大堂|院|楼|林|江|河|湖|洞|谷|峰|街|寺|庙|村|府|殿|宫|亭|桥"
)
_LOCATION_EN = re.compile(
    r"\b(?:inn|mountain|hall|courtyard|room|forest|river|lake|cave|city|"
    r"street|temple|village|palace|bridge|tower)\b",
    re.I,
)
_TIME_ZH = re.compile(r"次日|翌日|清晨|傍晚|夜晚|午后|黎明|日落|深夜|时辰后|天亮")
_TIME_EN = re.compile(
    r"\b(?:next day|morning|evening|night|dawn|dusk|later that|the following)\b", re.I
)
_ACTION_ZH = re.compile(r"出剑|挥刀|出拳|掌法|踢|飞身|斗|战|击|劈|刺|冲|跃|翻")
_ACTION_EN = re.compile(
    r"\b(?:sword|strike|punch|kick|leap|fight|battle|charge|slash|thrust|block)\b", re.I
)
_DIALOGUE_ZH = re.compile(r"说道|道[：:]|问道|答道|笑道|怒道|轻声|喝道|哈哈|大喝")
_DIALOGUE_EN = re.compile(r"\b(?:said|asked|replied|whispered|shouted|murmured|cried)\b", re.I)

_MAX_SEGS_PER_SCENE = 5  # split scene if segment count exceeds this


class SceneShotPlanService(BaseSkillService[Skill03Input, Skill03Output]):
    """SKILL 03 — Story → Scene → Shot Planner.

    State machine:
      INIT → PRECHECKING → SEGMENTING_SCENES → PLANNING_SHOTS
           → ESTIMATING_TIMING → EXPORTING_HINTS
           → READY_FOR_PARALLEL_EXECUTION | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_03"
    skill_name = "SceneShotPlanService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Public entry ───────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill03Input, ctx: SkillContext) -> Skill03Output:
        warnings: list[str] = []
        review_items: list[str] = []
        max_shots = max(1, input_dto.max_shots_per_scene)

        # ── [S1] Precheck ─────────────────────────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")
        if not input_dto.segments:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError("REQ-VALIDATION-001: segments list is empty — SKILL 01 output required")

        lang = (input_dto.language_route.get("source_primary_language", "zh-CN") or "zh-CN")

        # ── [S2] Scene Segmentation ───────────────────────────────────────────
        self._record_state(ctx, "PRECHECKING", "SEGMENTING_SCENES")
        scene_groups = self._segment_scenes(input_dto.segments, lang)
        if not scene_groups:
            warnings.append("scene_segmentation_produced_zero_scenes: using single scene fallback")
            scene_groups = [input_dto.segments]

        scene_plans: list[ScenePlan] = []
        for idx, group in enumerate(scene_groups):
            sc_id = f"SC{idx + 1:02d}"
            scene_plans.append(self._build_scene_plan(sc_id, idx, group, lang))

        # ── [S3] Shot Planning ────────────────────────────────────────────────
        self._record_state(ctx, "SEGMENTING_SCENES", "PLANNING_SHOTS")
        shot_plans: list[ShotPlan] = []
        for scene in scene_plans:
            seg_group = scene_groups[int(scene.scene_id[2:]) - 1]
            shots = self._plan_shots(scene, seg_group, lang, max_shots)
            shot_plans.extend(shots)

        if not shot_plans:
            warnings.append("shot_planning_produced_zero_shots")
            review_items.append("shot_plan_empty")

        # ── [S4] Provisional Timing ───────────────────────────────────────────
        self._record_state(ctx, "PLANNING_SHOTS", "ESTIMATING_TIMING")
        total_ms = sum(s.provisional_duration_ms for s in shot_plans)
        needs_tts = any(s.tts_backfill_required for s in shot_plans)
        provisional_timeline = ProvisionalTimeline(
            total_duration_estimate_ms=total_ms,
            is_final=False,
            requires_tts_backfill=needs_tts,
        )

        # ── [S5] Entity & Audio Hints Export ──────────────────────────────────
        self._record_state(ctx, "ESTIMATING_TIMING", "EXPORTING_HINTS")
        culture_hint = input_dto.culture_hint or input_dto.language_route.get("culture_hint", "")
        entity_hints = EntityExtractionHints(
            focus_entities=["characters", "scene_places", "props", "costumes"],
            culture_hint_from_router=culture_hint,
        )
        audio_pre_hints = self._build_audio_pre_hints(scene_plans, shot_plans, lang)
        parallel_groups = [
            ParallelTaskGroup(
                group_id="G_A",
                tasks=["entity_extraction_prepare", "canonicalization_prepare"],
            ),
            ParallelTaskGroup(
                group_id="G_B",
                tasks=["tts_planning", "dialogue_speaker_split"],
            ),
            ParallelTaskGroup(
                group_id="G_C",
                tasks=["sfx_bgm_ambience_planning"],
            ),
        ]

        # ── Final status ──────────────────────────────────────────────────────
        needs_review = bool(review_items) or len(scene_plans) == 0
        status = "review_required" if needs_review else "ready_for_parallel_execution"
        final_state = "REVIEW_REQUIRED" if needs_review else "READY_FOR_PARALLEL_EXECUTION"
        self._record_state(ctx, "EXPORTING_HINTS", final_state)

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} status={status} "
            f"scenes={len(scene_plans)} shots={len(shot_plans)} "
            f"total_ms={total_ms}"
        )

        return Skill03Output(
            scene_plan=scene_plans,
            shot_plan=shot_plans,
            provisional_timeline=provisional_timeline,
            entity_extraction_hints=entity_hints,
            audio_pre_hints=audio_pre_hints,
            parallel_task_groups=parallel_groups,
            warnings=warnings,
            review_required_items=review_items,
            status=status,
        )

    # ── [S2] Scene Segmentation ────────────────────────────────────────────────

    @staticmethod
    def _segment_scenes(
        segments: list[dict], lang: str
    ) -> list[list[dict]]:
        """Group segments into scene buckets using chapter, location, and time signals."""
        loc_re = _LOCATION_ZH if lang.startswith("zh") else _LOCATION_EN
        time_re = _TIME_ZH if lang.startswith("zh") else _TIME_EN

        groups: list[list[dict]] = []
        current: list[dict] = []
        prev_chapter = None

        for seg in segments:
            text = seg.get("text", "")
            chapter = seg.get("chapter_id", "ch_001")

            # Chapter boundary → new scene
            chapter_changed = prev_chapter is not None and chapter != prev_chapter
            # Location / time shift signal
            location_signal = bool(loc_re.search(text[:60]))  # look at paragraph opening
            time_signal = bool(time_re.search(text))
            # Scene too large
            size_overflow = len(current) >= _MAX_SEGS_PER_SCENE

            if current and (chapter_changed or time_signal or size_overflow):
                groups.append(current)
                current = []

            current.append(seg)
            prev_chapter = chapter

        if current:
            groups.append(current)

        return groups

    # ── Scene plan builder ─────────────────────────────────────────────────────

    @classmethod
    def _build_scene_plan(
        cls, scene_id: str, idx: int, group: list[dict], lang: str
    ) -> ScenePlan:
        action_re = _ACTION_ZH if lang.startswith("zh") else _ACTION_EN
        dialogue_re = _DIALOGUE_ZH if lang.startswith("zh") else _DIALOGUE_EN
        loc_re = _LOCATION_ZH if lang.startswith("zh") else _LOCATION_EN

        full_text = " ".join(s.get("text", "") for s in group)
        action_hits = len(action_re.findall(full_text))
        dialogue_hits = len(dialogue_re.findall(full_text))

        if action_hits > 3 and dialogue_hits > 3:
            scene_type = "atmosphere_dialogue"
            scene_goal = "action_with_dialogue"
            emotion = "tense"
        elif action_hits > 3:
            scene_type = "action"
            scene_goal = "combat_or_movement"
            emotion = "dramatic"
        elif dialogue_hits > 3:
            scene_type = "dialogue"
            scene_goal = "character_interaction"
            emotion = "calm"
        elif idx == 0:
            scene_type = "atmosphere"
            scene_goal = "establish_setting"
            emotion = "neutral"
        else:
            scene_type = "atmosphere"
            scene_goal = "narrative_progression"
            emotion = "neutral"

        loc_match = loc_re.search(full_text)
        loc_hint = loc_match.group(0) if loc_match else "unknown"

        start_offset = group[0].get("start_offset", 0) if group else 0
        end_offset = group[-1].get("end_offset", 0) if group else 0

        return ScenePlan(
            scene_id=scene_id,
            scene_goal=scene_goal,
            scene_type=scene_type,
            scene_location_hint=loc_hint,
            emotion_tone=emotion,
            source_range={"segment_start": start_offset, "segment_end": end_offset},
        )

    # ── [S3] Shot planning ─────────────────────────────────────────────────────

    @classmethod
    def _plan_shots(
        cls,
        scene: ScenePlan,
        group: list[dict],
        lang: str,
        max_shots: int,
    ) -> list[ShotPlan]:
        dialogue_re = _DIALOGUE_ZH if lang.startswith("zh") else _DIALOGUE_EN
        action_re = _ACTION_ZH if lang.startswith("zh") else _ACTION_EN
        shots: list[ShotPlan] = []

        def new_shot(
            shot_type: str,
            goal: str,
            duration_ms: int,
            criticality: str = "normal",
            entity_hints: list[str] | None = None,
            audio_hints: list[str] | None = None,
            tts: bool = False,
        ) -> ShotPlan:
            return ShotPlan(
                shot_id=f"S{uuid4().hex[:6].upper()}",
                scene_id=scene.scene_id,
                shot_type=shot_type,
                shot_goal=goal,
                criticality=criticality,
                provisional_duration_ms=duration_ms,
                entity_hints=entity_hints or [],
                audio_hints=audio_hints or [],
                tts_backfill_required=tts,
            )

        # Opening shot: always establishing for first scene, else wide
        if scene.scene_type in ("atmosphere", "atmosphere_dialogue") or scene.scene_goal == "establish_setting":
            shots.append(new_shot(
                "establishing", "establish_space_and_context", 3500,
                criticality="important",
                entity_hints=[scene.scene_location_hint],
                audio_hints=["ambient_environment"],
            ))

        # Content shots based on scene type
        if scene.scene_type == "dialogue":
            for seg in group[:max_shots - 2]:
                text = seg.get("text", "")
                if dialogue_re.search(text):
                    shots.append(new_shot(
                        "medium", "present_dialogue_exchange",
                        _estimate_dialogue_duration(text),
                        criticality="important",
                        audio_hints=["dialogue_tts"],
                        tts=True,
                    ))
                if len(shots) >= max_shots - 1:
                    break

        elif scene.scene_type == "action":
            for seg in group[:max_shots - 2]:
                text = seg.get("text", "")
                hits = len(action_re.findall(text))
                if hits > 0:
                    shots.append(new_shot(
                        "action", "show_combat_movement",
                        max(1500, min(4000, 500 + hits * 500)),
                        criticality="critical" if hits > 3 else "important",
                        audio_hints=["metal_hit_sfx", "movement_sfx"],
                    ))
                if len(shots) >= max_shots - 1:
                    break

        elif scene.scene_type in ("atmosphere_dialogue", "atmosphere"):
            # Mix of medium/close-up
            for i, seg in enumerate(group[: max_shots - 2]):
                shot_type = "close-up" if i % 2 else "medium"
                shots.append(new_shot(
                    shot_type, "build_atmosphere_and_character",
                    3000 if shot_type == "medium" else 2500,
                    audio_hints=["ambient_environment"],
                ))
                if len(shots) >= max_shots - 1:
                    break

        # Closing shot: transition to next scene (unless first/only scene)
        if scene.scene_type != "atmosphere" or len(group) > 2:
            shots.append(new_shot("transition", "close_scene_and_bridge", 1500))

        return shots[:max_shots]

    # ── [S5] Audio pre-hints ───────────────────────────────────────────────────

    @staticmethod
    def _build_audio_pre_hints(
        scenes: list[ScenePlan],
        shots: list[ShotPlan],
        lang: str,
    ) -> list[AudioPreHint]:
        hints: list[AudioPreHint] = []
        shot_by_scene: dict[str, list[ShotPlan]] = {}
        for s in shots:
            shot_by_scene.setdefault(s.scene_id, []).append(s)

        for scene in scenes:
            scene_shots = shot_by_scene.get(scene.scene_id, [])

            if scene.scene_type in ("dialogue", "atmosphere_dialogue"):
                hints.append(AudioPreHint(scene_id=scene.scene_id, hint="dialogue_heavy"))

            if scene.scene_type == "action":
                hints.append(AudioPreHint(scene_id=scene.scene_id, hint="action_sfx"))
                # Check if metal / weapon sounds likely
                entity_texts = " ".join(
                    " ".join(s.entity_hints) for s in scene_shots
                )
                if any(k in entity_texts for k in ("sword", "剑", "刀", "weapon", "武器")):
                    hints.append(AudioPreHint(scene_id=scene.scene_id, hint="metal_hit_possible"))

            if scene.scene_location_hint in ("林", "forest", "河", "river", "湖", "lake", "mountain", "山"):
                hints.append(AudioPreHint(scene_id=scene.scene_id, hint="wind_rain"))

        return hints


# ── Helpers ────────────────────────────────────────────────────────────────────

def _estimate_dialogue_duration(text: str) -> int:
    """Rough TTS duration estimate: ~150ms per CJK char or ~100ms per English word."""
    cjk = sum(1 for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF)
    words = len(text.split()) - cjk // 2
    return max(1500, cjk * 150 + words * 100)
