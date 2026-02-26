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
    ReviewRequiredItem,
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

# Character name extraction
_CHAR_NAME_ZH = re.compile(
    r"([\u4e00-\u9fff]{2,4})"
    r"(?:说道|道[：:]|问道|答道|笑道|怒道|轻声道|喝道|大喝|沉声道|冷声道|低声道|微笑道|点头|摇头|冷笑|怒吼)"
)
_CHAR_NAME_EN = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+"
    r"(?:said|asked|replied|whispered|shouted|murmured|cried|nodded|shook|smiled|frowned)"
)

# Semantic signal keywords for scene goal classification
_EMOTION_ZH = re.compile(r"悲|哭|泣|伤心|难过|喜|乐|怒|愤|恐|惧|惊|震|感动|绝望")
_EMOTION_EN = re.compile(
    r"\b(?:sad|cry|grief|happy|joy|angry|rage|fear|shock|surprise|despair|moved)\b", re.I
)
_TENSION_ZH = re.compile(r"紧张|不安|警惕|杀气|危险|阴谋|暗中|偷偷|秘密|盯着|冷汗")
_TENSION_EN = re.compile(
    r"\b(?:tense|uneasy|danger|plot|secret|hidden|suspicious|stare|sweat)\b", re.I
)
_DESCRIPTION_ZH = re.compile(r"风景|景色|环境|房间|装饰|布置|陈设|远处|四周|天空|大地")
_DESCRIPTION_EN = re.compile(
    r"\b(?:landscape|scenery|room|decor|surroundings|horizon|sky|ground|view)\b", re.I
)
_HUMOR_ZH = re.compile(r"哈哈|笑|滑稽|好笑|搞笑|有趣|逗|傻|呆|囧")
_HUMOR_EN = re.compile(r"\b(?:laugh|funny|humor|comic|joke|silly|ridiculous|grin)\b", re.I)

# Culture-specific patterns
_WUXIA_ACTION_ZH = re.compile(r"内力|真气|轻功|暗器|江湖|武功|掌法|剑法|刀法|拳法|点穴|运功")
_WUXIA_ACTION_EN = re.compile(
    r"\b(?:qi|martial\s+arts|inner\s+power|kung\s+fu|wuxia|jianghu)\b", re.I
)

_MAX_SEGS_PER_SCENE = 5  # split scene if segment count exceeds this

# Pacing multipliers
_PACING_MULTIPLIER = {"fast": 0.75, "slow": 1.4, "normal": 1.0}


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
        review_items: list[ReviewRequiredItem] = []

        # ── Resolve effective config from overrides / defaults ────────────────
        overrides = input_dto.user_overrides or {}
        defaults = input_dto.project_defaults or {}
        flags = input_dto.feature_flags or {}

        max_shots = max(1, overrides.get(
            "max_shots_per_scene", input_dto.max_shots_per_scene,
        ))
        shot_style = overrides.get("shot_style", defaults.get("shot_style", "standard"))
        pacing = overrides.get("pacing_preference", defaults.get("pacing_preference", "normal"))
        pacing_mult = _PACING_MULTIPLIER.get(pacing, 1.0)
        default_shot_duration_ms = int(defaults.get("default_shot_duration_ms", 3000))

        enable_timing = flags.get("enable_provisional_timing", True)
        enable_audio_hints = flags.get("enable_audio_event_pre_hints", True)
        enable_parallel = flags.get("enable_parallel_task_grouping", True)

        culture_hint = (
            input_dto.culture_hint
            or input_dto.language_route.get("culture_hint", "")
        )

        # ── [S1] Precheck ─────────────────────────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")
        if not input_dto.segments:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError(
                "REQ-VALIDATION-001: segments list is empty — SKILL 01 output required"
            )

        lang = input_dto.language_route.get("source_primary_language", "zh-CN") or "zh-CN"
        lang_from_defaults = defaults.get("language")
        if lang_from_defaults:
            lang = lang_from_defaults

        # Check if content is outline-only (short segments, no detail)
        avg_seg_len = sum(
            len(s.get("text", "")) for s in input_dto.segments
        ) / max(1, len(input_dto.segments))
        if avg_seg_len < 30:
            warnings.append(
                "outline_only_content: segments appear to be summaries, producing coarse plan"
            )
            review_items.append(ReviewRequiredItem(
                item="outline_level_content",
                reason="Segments average <30 chars; only outline-level detail available, "
                       "plan is coarse-grained",
            ))

        # ── [S2] Scene Segmentation ───────────────────────────────────────────
        self._record_state(ctx, "PRECHECKING", "SEGMENTING_SCENES")
        scene_groups = self._segment_scenes(input_dto.segments, lang)
        if not scene_groups:
            warnings.append(
                "scene_segmentation_produced_zero_scenes: using single scene fallback"
            )
            scene_groups = [input_dto.segments]

        scene_plans: list[ScenePlan] = []
        for idx, group in enumerate(scene_groups):
            sc_id = f"SC{idx + 1:02d}"
            scene_plans.append(
                self._build_scene_plan(sc_id, idx, group, lang, culture_hint)
            )

        # ── [S3] Shot Planning ────────────────────────────────────────────────
        self._record_state(ctx, "SEGMENTING_SCENES", "PLANNING_SHOTS")
        shot_plans: list[ShotPlan] = []
        for scene in scene_plans:
            seg_group = scene_groups[int(scene.scene_id[2:]) - 1]
            shots = self._plan_shots(
                scene, seg_group, lang, max_shots,
                culture_hint=culture_hint,
                shot_style=shot_style,
                pacing_mult=pacing_mult,
                default_duration_ms=default_shot_duration_ms,
            )
            shot_plans.extend(shots)

        if not shot_plans:
            warnings.append("shot_planning_produced_zero_shots")
            review_items.append(ReviewRequiredItem(
                item="shot_plan_empty",
                reason="No shots generated from the provided segments; "
                       "text may lack sufficient narrative detail",
            ))

        # Flag scenes with unknown locations for manual review
        for sc in scene_plans:
            if sc.scene_location_hint == "unknown":
                warnings.append(
                    f"{sc.scene_id}_location_unknown: insufficient spatial info"
                )
                review_items.append(ReviewRequiredItem(
                    item=f"{sc.scene_id}_ambiguous_location",
                    reason=f"Scene {sc.scene_id} has no detectable location hint; "
                           "manual assignment suggested",
                ))

        # ── [S4] Provisional Timing ───────────────────────────────────────────
        self._record_state(ctx, "PLANNING_SHOTS", "ESTIMATING_TIMING")
        if enable_timing:
            total_ms = sum(s.provisional_duration_ms for s in shot_plans)
            needs_tts = any(s.tts_backfill_required for s in shot_plans)
            provisional_timeline = ProvisionalTimeline(
                total_duration_estimate_ms=total_ms,
                is_final=False,
                requires_tts_backfill=needs_tts,
            )
        else:
            provisional_timeline = ProvisionalTimeline(
                total_duration_estimate_ms=0,
                is_final=False,
                requires_tts_backfill=True,
            )

        # ── [S5] Entity & Audio Hints Export ──────────────────────────────────
        self._record_state(ctx, "ESTIMATING_TIMING", "EXPORTING_HINTS")
        entity_hints = EntityExtractionHints(
            focus_entities=["characters", "scene_places", "props", "costumes"],
            culture_hint_from_router=culture_hint,
        )

        audio_pre_hints: list[AudioPreHint] = []
        if enable_audio_hints:
            audio_pre_hints = self._build_audio_pre_hints(scene_plans, shot_plans, lang)

        parallel_groups: list[ParallelTaskGroup] = []
        if enable_parallel:
            parallel_groups = self._build_parallel_groups(scene_plans, shot_plans)

        # ── Final status ──────────────────────────────────────────────────────
        needs_review = bool(review_items) or len(scene_plans) == 0
        status = "review_required" if needs_review else "ready_for_parallel_execution"
        final_state = "REVIEW_REQUIRED" if needs_review else "READY_FOR_PARALLEL_EXECUTION"
        self._record_state(ctx, "EXPORTING_HINTS", final_state)

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} status={status} "
            f"scenes={len(scene_plans)} shots={len(shot_plans)} "
            f"total_ms={provisional_timeline.total_duration_estimate_ms}"
        )

        return Skill03Output(
            version="1.0",
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
            location_signal = bool(loc_re.search(text[:60]))
            time_signal = bool(time_re.search(text))
            # Scene too large
            size_overflow = len(current) >= _MAX_SEGS_PER_SCENE

            if current and (chapter_changed or location_signal or time_signal or size_overflow):
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
        cls,
        scene_id: str,
        idx: int,
        group: list[dict],
        lang: str,
        culture_hint: str = "",
    ) -> ScenePlan:
        is_zh = lang.startswith("zh")
        action_re = _ACTION_ZH if is_zh else _ACTION_EN
        dialogue_re = _DIALOGUE_ZH if is_zh else _DIALOGUE_EN
        emotion_re = _EMOTION_ZH if is_zh else _EMOTION_EN
        tension_re = _TENSION_ZH if is_zh else _TENSION_EN
        desc_re = _DESCRIPTION_ZH if is_zh else _DESCRIPTION_EN
        humor_re = _HUMOR_ZH if is_zh else _HUMOR_EN
        loc_re = _LOCATION_ZH if is_zh else _LOCATION_EN

        full_text = " ".join(s.get("text", "") for s in group)
        action_hits = len(action_re.findall(full_text))
        dialogue_hits = len(dialogue_re.findall(full_text))
        emotion_hits = len(emotion_re.findall(full_text))
        tension_hits = len(tension_re.findall(full_text))
        desc_hits = len(desc_re.findall(full_text))
        humor_hits = len(humor_re.findall(full_text))

        # Culture boost: wuxia/xianxia genres amplify action signals
        is_wuxia = "wuxia" in culture_hint.lower() or "武侠" in culture_hint
        is_xianxia = "xianxia" in culture_hint.lower() or "仙侠" in culture_hint
        if is_wuxia or is_xianxia:
            wuxia_re = _WUXIA_ACTION_ZH if is_zh else _WUXIA_ACTION_EN
            action_hits += len(wuxia_re.findall(full_text)) * 2

        scene_type, scene_goal, emotion = cls._classify_scene(
            idx, action_hits, dialogue_hits, emotion_hits,
            tension_hits, desc_hits, humor_hits,
        )

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

    @staticmethod
    def _classify_scene(
        idx: int,
        action_hits: int,
        dialogue_hits: int,
        emotion_hits: int,
        tension_hits: int,
        desc_hits: int,
        humor_hits: int,
    ) -> tuple[str, str, str]:
        """Return (scene_type, scene_goal, emotion_tone) via multi-signal analysis."""
        has_action = action_hits > 2
        has_dialogue = dialogue_hits > 2
        has_emotion = emotion_hits > 1
        has_tension = tension_hits > 1

        # Mixed signal combinations (most specific first)
        if has_action and has_dialogue and has_emotion:
            return "atmosphere_dialogue", "emotional_confrontation", "dramatic"
        if has_action and has_dialogue:
            return "atmosphere_dialogue", "action_with_dialogue", "tense"
        if has_action and has_tension:
            return "action", "tension_building_combat", "tense"
        if has_dialogue and has_emotion:
            return "dialogue", "emotional_exchange", "dramatic"
        if has_dialogue and has_tension:
            return "dialogue", "reveal_information", "tense"

        # Single dominant signal
        if has_action:
            return "action", "combat_or_movement", "dramatic"
        if has_dialogue:
            return "dialogue", "character_interaction", "calm"
        if has_emotion:
            return "atmosphere", "emotional_climax", "dramatic"
        if has_tension:
            return "atmosphere", "tension_building", "tense"
        if humor_hits > 1:
            return "dialogue", "comic_relief", "joyful"
        if desc_hits > 1:
            return "atmosphere", "world_building", "neutral"

        # Positional fallback
        if idx == 0:
            return "atmosphere", "establish_setting", "neutral"
        return "atmosphere", "narrative_progression", "neutral"

    # ── [S3] Shot planning ─────────────────────────────────────────────────────

    @classmethod
    def _plan_shots(
        cls,
        scene: ScenePlan,
        group: list[dict],
        lang: str,
        max_shots: int,
        *,
        culture_hint: str = "",
        shot_style: str = "standard",
        pacing_mult: float = 1.0,
        default_duration_ms: int = 3000,
    ) -> list[ShotPlan]:
        dialogue_re = _DIALOGUE_ZH if lang.startswith("zh") else _DIALOGUE_EN
        action_re = _ACTION_ZH if lang.startswith("zh") else _ACTION_EN
        is_wuxia = "wuxia" in culture_hint.lower() or "武侠" in culture_hint
        shots: list[ShotPlan] = []

        def _dur(ms: int) -> int:
            return max(500, int(ms * pacing_mult))

        def new_shot(
            shot_type: str,
            goal: str,
            duration_ms: int,
            criticality: str = "normal",
            entity_hints: list[str] | None = None,
            audio_hints: list[str] | None = None,
            tts: bool = False,
            text: str = "",
        ) -> ShotPlan:
            characters = cls._extract_characters(text, lang) if text else []
            return ShotPlan(
                shot_id=f"S{uuid4().hex[:6].upper()}",
                scene_id=scene.scene_id,
                shot_type=shot_type,
                shot_goal=goal,
                criticality=criticality,
                provisional_duration_ms=_dur(duration_ms),
                characters_present=characters,
                entity_hints=entity_hints or [],
                audio_hints=audio_hints or [],
                tts_backfill_required=tts,
            )

        # ── Opening shot ──────────────────────────────────────────────────────
        if scene.scene_type in ("atmosphere", "atmosphere_dialogue") or \
                scene.scene_goal == "establish_setting":
            shots.append(new_shot(
                "establishing", "establish_space_and_context", 3500,
                criticality="important",
                entity_hints=[scene.scene_location_hint],
                audio_hints=["ambient_environment"],
            ))
        elif scene.scene_type == "action":
            shots.append(new_shot(
                "wide", "show_action_arena", 2500,
                criticality="important",
                entity_hints=[scene.scene_location_hint],
                audio_hints=["ambient_environment"],
            ))

        # ── Content shots by scene type ───────────────────────────────────────
        if scene.scene_type == "dialogue":
            cls._plan_dialogue_shots(
                shots, group, max_shots, dialogue_re, new_shot, default_duration_ms,
            )
        elif scene.scene_type == "action":
            cls._plan_action_shots(
                shots, group, max_shots, action_re, new_shot, is_wuxia,
            )
        elif scene.scene_type in ("atmosphere_dialogue", "atmosphere"):
            cls._plan_atmosphere_shots(
                shots, group, max_shots, dialogue_re, action_re, new_shot,
                default_duration_ms, is_wuxia,
            )

        # ── Insert shot for notable detail ────────────────────────────────────
        if len(shots) < max_shots - 1 and shot_style != "minimal":
            full_text = " ".join(s.get("text", "") for s in group)
            detail_entities = cls._extract_detail_entities(full_text, lang)
            if detail_entities:
                shots.append(new_shot(
                    "insert", "highlight_key_detail", 1500,
                    criticality="background",
                    entity_hints=detail_entities[:3],
                ))

        # ── Closing transition shot ───────────────────────────────────────────
        if len(group) > 1 or scene.scene_type != "atmosphere":
            if len(shots) < max_shots:
                shots.append(new_shot("transition", "close_scene_and_bridge", 1500))

        return shots[:max_shots]

    # ── Shot sub-planners ──────────────────────────────────────────────────────

    @classmethod
    def _plan_dialogue_shots(
        cls, shots, group, max_shots, dialogue_re, new_shot, default_duration_ms,
    ):
        for i, seg in enumerate(group[:max_shots - 2]):
            if len(shots) >= max_shots - 1:
                break
            text = seg.get("text", "")
            if dialogue_re.search(text):
                shots.append(new_shot(
                    "medium", "present_dialogue_exchange",
                    _estimate_dialogue_duration(text),
                    criticality="important",
                    audio_hints=["dialogue_tts"],
                    tts=True,
                    text=text,
                ))
                # Reaction shot after every other dialogue beat
                if i % 2 == 1 and len(shots) < max_shots - 1:
                    shots.append(new_shot(
                        "reaction", "show_listener_reaction", 1500,
                        criticality="normal",
                        text=text,
                    ))
            else:
                shots.append(new_shot(
                    "medium", "narrative_beat", default_duration_ms,
                    text=text,
                ))

    @classmethod
    def _plan_action_shots(
        cls, shots, group, max_shots, action_re, new_shot, is_wuxia,
    ):
        for i, seg in enumerate(group[:max_shots - 2]):
            if len(shots) >= max_shots - 1:
                break
            text = seg.get("text", "")
            hits = len(action_re.findall(text))
            if hits > 0:
                # Alternate between action and close-up for shot variety
                if i % 3 == 2:
                    shots.append(new_shot(
                        "close-up", "emphasize_action_impact",
                        max(1000, min(2500, 500 + hits * 400)),
                        criticality="important",
                        audio_hints=["impact_sfx"],
                        text=text,
                    ))
                else:
                    audio = ["metal_hit_sfx", "movement_sfx"] if is_wuxia else ["movement_sfx"]
                    shots.append(new_shot(
                        "action", "show_combat_movement",
                        max(1500, min(4000, 500 + hits * 500)),
                        criticality="critical" if hits > 3 else "important",
                        audio_hints=audio,
                        text=text,
                    ))
                # Reaction shot after intense combat moments
                if hits > 3 and len(shots) < max_shots - 1:
                    shots.append(new_shot(
                        "reaction", "show_character_reaction_to_impact", 1200,
                        criticality="normal",
                        text=text,
                    ))
            else:
                shots.append(new_shot(
                    "medium", "contextual_action_beat", 2500, text=text,
                ))

    @classmethod
    def _plan_atmosphere_shots(
        cls, shots, group, max_shots, dialogue_re, action_re, new_shot,
        default_duration_ms, is_wuxia,
    ):
        shot_cycle = ["medium", "close-up", "wide", "medium", "reaction"]
        for i, seg in enumerate(group[:max_shots - 2]):
            if len(shots) >= max_shots - 1:
                break
            text = seg.get("text", "")
            cycle_type = shot_cycle[i % len(shot_cycle)]

            if action_re.search(text):
                audio = ["metal_hit_sfx", "movement_sfx"] if is_wuxia else ["movement_sfx"]
                shots.append(new_shot(
                    "action", "capture_action_moment", 2500,
                    criticality="important",
                    audio_hints=audio, text=text,
                ))
            elif dialogue_re.search(text):
                shots.append(new_shot(
                    "medium", "present_dialogue_beat",
                    _estimate_dialogue_duration(text),
                    criticality="important",
                    audio_hints=["dialogue_tts"],
                    tts=True, text=text,
                ))
            else:
                dur = default_duration_ms if cycle_type == "medium" else 2500
                goal = "build_atmosphere_and_character"
                if cycle_type == "wide":
                    goal = "establish_wider_context"
                elif cycle_type == "reaction":
                    goal = "show_character_reaction"
                shots.append(new_shot(
                    cycle_type, goal, dur,
                    audio_hints=["ambient_environment"],
                    text=text,
                ))

    # ── Character extraction ───────────────────────────────────────────────────

    @staticmethod
    def _extract_characters(text: str, lang: str) -> list[str]:
        """Extract character names from text using dialogue attribution patterns."""
        if not text:
            return []
        if lang.startswith("zh"):
            matches = _CHAR_NAME_ZH.findall(text)
        else:
            matches = _CHAR_NAME_EN.findall(text)
        seen: set[str] = set()
        result: list[str] = []
        for name in matches:
            name = name.strip()
            if name and name not in seen:
                seen.add(name)
                result.append(name)
        return result

    # ── Detail entity extraction for insert shots ──────────────────────────────

    @staticmethod
    def _extract_detail_entities(text: str, lang: str) -> list[str]:
        """Extract notable objects/props that warrant an insert shot."""
        if lang.startswith("zh"):
            patterns = re.findall(r"(?:一[把柄张面盏盘壶][^\s，。]{1,4})", text)
            if not patterns:
                patterns = re.findall(
                    r"(剑|刀|酒壶|灯笼|书信|卷轴|玉佩|令牌)", text
                )
        else:
            patterns = re.findall(
                r"\b(sword|knife|lantern|letter|scroll|pendant|token|cup|table|book)\b",
                text, re.I,
            )
        return list(dict.fromkeys(patterns))  # deduplicate, preserve order

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
                entity_texts = " ".join(
                    " ".join(s.entity_hints) for s in scene_shots
                )
                if any(k in entity_texts for k in ("sword", "剑", "刀", "weapon", "武器")):
                    hints.append(AudioPreHint(scene_id=scene.scene_id, hint="metal_hit_possible"))

            if scene.scene_location_hint in (
                "林", "forest", "河", "river", "湖", "lake", "mountain", "山",
            ):
                hints.append(AudioPreHint(scene_id=scene.scene_id, hint="wind_rain"))

            # Crowd ambience for indoor social locations
            if scene.scene_location_hint in (
                "客栈", "inn", "大堂", "hall", "街", "street", "city",
            ):
                hints.append(AudioPreHint(scene_id=scene.scene_id, hint="crowd_ambience"))

            # BGM hint for emotional scenes
            if scene.emotion_tone in ("dramatic", "tense", "sad"):
                hints.append(AudioPreHint(scene_id=scene.scene_id, hint="bgm_emotional"))

        return hints

    # ── Parallel task groups (dynamic) ─────────────────────────────────────────

    @staticmethod
    def _build_parallel_groups(
        scenes: list[ScenePlan],
        shots: list[ShotPlan],
    ) -> list[ParallelTaskGroup]:
        """Build parallel task groups correlated with actual scene/shot content."""
        has_dialogue = any(s.tts_backfill_required for s in shots)
        has_action = any(s.shot_type == "action" for s in shots)
        has_entities = any(s.entity_hints for s in shots)

        groups: list[ParallelTaskGroup] = []

        # Group A: Entity extraction — always if entities detected
        if has_entities:
            entity_scenes = sorted({s.scene_id for s in shots if s.entity_hints})
            groups.append(ParallelTaskGroup(
                group_id="G_A",
                tasks=["entity_extraction_prepare", "canonicalization_prepare"]
                      + [f"entity_scan_{sc}" for sc in entity_scenes],
            ))

        # Group B: TTS / dialogue — only if dialogue shots exist
        if has_dialogue:
            dialogue_scenes = sorted({s.scene_id for s in shots if s.tts_backfill_required})
            groups.append(ParallelTaskGroup(
                group_id="G_B",
                tasks=["tts_planning", "dialogue_speaker_split"]
                      + [f"tts_prepare_{sc}" for sc in dialogue_scenes],
            ))

        # Group C: SFX / BGM / Ambience
        sfx_scenes = sorted({s.scene_id for s in shots if s.audio_hints})
        if sfx_scenes:
            tasks = ["sfx_bgm_ambience_planning"]
            if has_action:
                tasks.append("action_sfx_prepare")
            tasks.extend(f"audio_prepare_{sc}" for sc in sfx_scenes)
            groups.append(ParallelTaskGroup(group_id="G_C", tasks=tasks))

        # Group D: Asset pre-fetch (optional, for entity-heavy plans)
        if has_entities:
            groups.append(ParallelTaskGroup(
                group_id="G_D",
                tasks=["asset_library_prefetch", "material_cache_warmup"],
            ))

        # Fallback: at least one group
        if not groups:
            groups.append(ParallelTaskGroup(
                group_id="G_A",
                tasks=["entity_extraction_prepare", "canonicalization_prepare"],
            ))

        return groups


# ── Helpers ────────────────────────────────────────────────────────────────────

def _estimate_dialogue_duration(text: str) -> int:
    """Rough TTS duration estimate: ~150ms per CJK char or ~100ms per English word."""
    cjk = sum(1 for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF)
    words = len(text.split()) - cjk // 2
    return max(1500, cjk * 150 + words * 100)
