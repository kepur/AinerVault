"""SKILL 09: VisualRenderPlanService — Full implementation.

Per SKILL_09_VISUAL_RENDER_PLANNER.md spec with:
- Audio feature aggregation per shot (V2)
- Motion complexity scoring 0-100 (V3)
- Render strategy mapping (V4)
- Micro-shot splitting for high-motion shots (V5)
- 4-level backend degradation cascade (V6)
- Camera motion inference, transition planning, layer composition (V7)
- Feature flags & user overrides

State machine:
  INIT → PRECHECKING → PRECHECK_READY → AGGREGATING_AUDIO → AUDIO_FEATURES_READY
       → SCORING_MOTION → MOTION_SCORED → ASSIGNING_RENDER → STRATEGY_READY
       → SPLITTING_MICRO → PLANNING_CAMERA → PLANNING_TRANSITIONS
       → COMPOSING_LAYERS → DEGRADE_PROCESSING → ASSEMBLING_RENDER_PLAN
       → READY_FOR_RENDER_EXECUTION | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_09 import (
    AudioFeatures,
    BackendCapability,
    BackendLoadStatus,
    CameraMotion,
    Criticality,
    DegradeAction,
    DegradeLevel,
    FeatureFlags,
    FRAME_BUDGET_MAP,
    GlobalRenderProfile,
    I2VMode,
    LayerComposition,
    MICRO_SHOT_MAX_DURATION_MS,
    MICRO_SHOT_MIN_DURATION_MS,
    MICRO_SHOT_MOTION_THRESHOLD,
    MicroshotRenderPlan,
    MOTION_THRESHOLDS,
    MotionLevel,
    PlanningSummary,
    RenderState,
    RenderStrategy,
    ResourceStrategy,
    ReviewRequiredItem,
    SHOT_TYPE_MOTION_WEIGHT,
    ShotRenderConfig,
    ShotRenderPlan,
    Skill09Input,
    Skill09Output,
    TransitionPlan,
    TransitionType,
    UserOverrides,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Semantic action keywords → base score contribution ───────────────────────
_ACTION_SEMANTIC_SCORES: dict[str, int] = {
    "battle": 28, "fight": 28, "combat": 28, "duel": 26,
    "chase": 25, "pursuit": 25, "flee": 22,
    "explosion": 30, "explode": 30, "blast": 28,
    "jump": 18, "leap": 18, "flip": 20, "roll": 16, "tumble": 16,
    "run": 14, "sprint": 16, "dash": 16,
    "walk": 8, "move": 8, "stroll": 6,
    "talk": 3, "speak": 3, "dialogue": 3, "whisper": 2,
    "stand": 1, "sit": 1, "wait": 1, "idle": 0,
    "strike": 26, "slash": 26, "punch": 24, "kick": 24,
    "block": 15, "parry": 15, "dodge": 20,
}

# Criticality keywords
_CRITICALITY_KEYWORDS: dict[str, str] = {
    "climax": "critical", "highlight": "critical", "turning_point": "critical",
    "first_appearance": "critical", "debut": "critical",
    "action": "important", "battle": "important", "fight": "important",
    "dialogue": "normal", "talk": "normal",
    "establishing": "background", "ambience": "background", "empty": "background",
}


class VisualRenderPlanService(BaseSkillService[Skill09Input, Skill09Output]):
    """SKILL 09 — Visual Render Planner.

    Generates an executable visual render plan per shot (and micro-shots for
    high-motion segments), aligning audio events with render strategy.
    """

    skill_id = "skill_09"
    skill_name = "VisualRenderPlanService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── main entry ────────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill09Input, ctx: SkillContext) -> Skill09Output:
        # Parse config
        ff = self._parse_feature_flags(input_dto.feature_flags)
        overrides = self._parse_user_overrides(input_dto.user_overrides)
        backend_cap = self._parse_backend_capability(input_dto.backend_capability)
        backend_load = self._parse_backend_load(input_dto.backend_load_status)
        profile_key = self._resolve_profile(input_dto.compute_budget, overrides)

        # ── V1: Precheck ──────────────────────────────────────────────────────
        self._record_state(ctx, RenderState.INIT, RenderState.PRECHECKING)
        blocking = self._precheck(input_dto)
        if blocking:
            self._record_state(ctx, RenderState.PRECHECKING, RenderState.FAILED)
            return self._fail_output(profile_key, blocking)
        self._record_state(ctx, RenderState.PRECHECKING, RenderState.PRECHECK_READY)

        # Build audio event index (shot_id → list[event_dict])
        audio_events = (input_dto.audio_timeline or {}).get("events", [])
        shot_events_map: dict[str, list[dict]] = {}
        for ev in audio_events:
            sid = ev.get("shot_id", "")
            if sid:
                shot_events_map.setdefault(sid, []).append(ev)

        # ── V2: Audio Feature Aggregation ─────────────────────────────────────
        self._record_state(ctx, RenderState.PRECHECK_READY, RenderState.AGGREGATING_AUDIO)
        shot_audio: dict[str, AudioFeatures] = {}
        for shot in input_dto.shots:
            sid = shot.get("shot_id", "")
            evts = shot_events_map.get(sid, [])
            duration_s = float(shot.get("duration_seconds", 0) or 0)
            if duration_s <= 0:
                start_ms = int(shot.get("start_ms", 0) or 0)
                end_ms = int(shot.get("end_ms", 0) or 0)
                duration_s = max((end_ms - start_ms) / 1000.0, 1.0)
            shot_audio[sid] = self._aggregate_audio_features(evts, duration_s)
        self._record_state(ctx, RenderState.AGGREGATING_AUDIO, RenderState.AUDIO_FEATURES_READY)

        # ── V3: Motion Scoring ────────────────────────────────────────────────
        self._record_state(ctx, RenderState.AUDIO_FEATURES_READY, RenderState.SCORING_MOTION)
        shot_scores: dict[str, tuple[int, str, list[str]]] = {}
        for shot in input_dto.shots:
            sid = shot.get("shot_id", "")
            af = shot_audio.get(sid, AudioFeatures())
            score, level, tags = self._compute_motion_score(shot, af, ff)
            shot_scores[sid] = (score, level, tags)
        self._record_state(ctx, RenderState.SCORING_MOTION, RenderState.MOTION_SCORED)

        # ── V4: Render Strategy Mapping ───────────────────────────────────────
        self._record_state(ctx, RenderState.MOTION_SCORED, RenderState.ASSIGNING_RENDER)
        shot_plans: list[ShotRenderPlan] = []
        for i, shot in enumerate(input_dto.shots):
            sid = shot.get("shot_id", f"shot_{i:03d}")
            scene_id = shot.get("scene_id", "")
            start_ms = int(shot.get("start_ms", 0) or 0)
            end_ms = int(shot.get("end_ms", 0) or 0)
            dur_s = float(shot.get("duration_seconds", 0) or 0)
            if dur_s <= 0 and end_ms > start_ms:
                dur_s = (end_ms - start_ms) / 1000.0
            if dur_s <= 0:
                dur_s = 3.0
            duration_ms = int(dur_s * 1000)
            if end_ms <= start_ms:
                end_ms = start_ms + duration_ms

            score, level, tags = shot_scores.get(sid, (0, MotionLevel.LOW_MOTION.value, []))
            af = shot_audio.get(sid, AudioFeatures())
            criticality = self._infer_criticality(shot, level, tags)
            strategy = self._build_render_strategy(
                profile_key, level, score, criticality, duration_ms,
                backend_cap, overrides, ff, input_dto.quality_profile,
            )

            plan = ShotRenderPlan(
                shot_id=sid,
                scene_id=scene_id,
                start_ms=start_ms,
                end_ms=end_ms,
                duration_ms=duration_ms,
                motion_complexity_score=score,
                motion_level=level,
                audio_features=af,
                render_strategy=strategy,
                split_into_microshots=False,
                criticality=criticality,
                reasoning_tags=tags,
                rag_retrieval_tags={
                    "motion_level": level,
                    "shot_type": shot.get("shot_type", "medium"),
                    "camera_move_type": CameraMotion.STATIC.value,
                    "degrade_level": strategy.degrade_level,
                },
            )
            shot_plans.append(plan)
        self._record_state(ctx, RenderState.ASSIGNING_RENDER, RenderState.STRATEGY_READY)

        # ── V5: Micro-shot Splitting ──────────────────────────────────────────
        self._record_state(ctx, RenderState.STRATEGY_READY, RenderState.SPLITTING_MICRO)
        microshots: list[MicroshotRenderPlan] = []
        if ff.micro_shot_enabled and not ff.static_fallback_only:
            for plan in shot_plans:
                if plan.motion_complexity_score >= MICRO_SHOT_MOTION_THRESHOLD:
                    ms_list = self._split_microshots(plan, shot_events_map.get(plan.shot_id, []))
                    if ms_list:
                        plan.split_into_microshots = True
                        microshots.extend(ms_list)

        # ── V6-extra: Camera Motion ───────────────────────────────────────────
        self._record_state(ctx, RenderState.SPLITTING_MICRO, RenderState.PLANNING_CAMERA)
        for plan in shot_plans:
            cam = self._infer_camera_motion(plan)
            plan.camera_motion = cam
            plan.rag_retrieval_tags["camera_move_type"] = cam
        for ms in microshots:
            ms.camera_motion = self._infer_camera_motion_from_score(
                ms.motion_complexity_score,
            )

        # ── V6-extra: Transitions ─────────────────────────────────────────────
        self._record_state(ctx, RenderState.PLANNING_CAMERA, RenderState.PLANNING_TRANSITIONS)
        transitions = self._plan_transitions(shot_plans)

        # ── V6-extra: Layer Composition ───────────────────────────────────────
        self._record_state(ctx, RenderState.PLANNING_TRANSITIONS, RenderState.COMPOSING_LAYERS)
        for plan in shot_plans:
            plan.layer_composition = self._build_layer_composition(plan)
        for ms in microshots:
            ms.layer_composition = LayerComposition(
                background=True, character=True,
                fx_overlay=ms.motion_complexity_score > 60,
            )

        # ── V6: Backend-Aware Degradation ─────────────────────────────────────
        self._record_state(ctx, RenderState.COMPOSING_LAYERS, RenderState.DEGRADE_PROCESSING)
        degrade_actions: list[DegradeAction] = []
        if ff.enable_backend_auto_degrade:
            degrade_actions = self._apply_degradation(
                shot_plans, microshots, backend_load, overrides, ff,
            )

        # ── V7: Assemble Render Plan ──────────────────────────────────────────
        self._record_state(ctx, RenderState.DEGRADE_PROCESSING, RenderState.ASSEMBLING_RENDER_PLAN)
        warnings: list[str] = []
        review_items: list[ReviewRequiredItem] = []
        self._assemble_warnings(shot_plans, microshots, degrade_actions, warnings, review_items)

        summary = PlanningSummary(
            total_shots=len(shot_plans),
            high_motion_shots=sum(1 for p in shot_plans if p.motion_level == MotionLevel.HIGH_MOTION.value),
            microshot_splits=sum(1 for p in shot_plans if p.split_into_microshots),
            total_microshots=len(microshots),
            degraded_shots=len(degrade_actions),
            critical_segments_protected=sum(
                1 for p in shot_plans if p.criticality in ("critical", "important")
                and not p.render_strategy.degrade_allowed
            ),
        )

        resource_strategy = ResourceStrategy(
            recommended_parallelism=min(ff.parallel_render_groups, max(1, len(shot_plans) // 4)),
            queue_priority_mode="critical_first" if summary.critical_segments_protected > 0 else "fifo",
            preview_first=input_dto.quality_profile == "preview",
        )

        # Determine final status
        if review_items:
            final_status = RenderState.REVIEW_REQUIRED.value
            self._record_state(ctx, RenderState.ASSEMBLING_RENDER_PLAN, RenderState.REVIEW_REQUIRED)
        else:
            final_status = RenderState.READY_FOR_RENDER_EXECUTION.value
            self._record_state(ctx, RenderState.ASSEMBLING_RENDER_PLAN, RenderState.READY_FOR_RENDER_EXECUTION)

        # Backward-compat: populate legacy render_plans
        legacy_plans = self._build_legacy_plans(shot_plans, profile_key)
        gpu_hours = self._estimate_gpu_hours(shot_plans)

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"shots={len(shot_plans)} micro={len(microshots)} "
            f"degrade={len(degrade_actions)} status={final_status}"
        )

        return Skill09Output(
            version="1.0",
            status=self._status_to_output(final_status),
            global_render_profile=profile_key,
            planning_summary=summary,
            resource_strategy=resource_strategy,
            shot_render_plans=shot_plans,
            microshot_render_plans=microshots,
            degrade_actions=degrade_actions,
            warnings=warnings,
            review_required_items=review_items,
            transitions=transitions,
            render_plans=legacy_plans,
            total_gpu_hours_estimate=gpu_hours,
        )

    # ── V1: Precheck ──────────────────────────────────────────────────────────

    @staticmethod
    def _precheck(inp: Skill09Input) -> list[str]:
        issues: list[str] = []
        if not inp.shots:
            issues.append("RENDER-PRECHECK-001: shot_plan is empty or missing")
        tl_status = (inp.audio_timeline or {}).get("status", "")
        if tl_status and "provisional" in str(tl_status).lower():
            issues.append("RENDER-PRECHECK-002: timeline is provisional, not final")
        return issues

    # ── V2: Audio Feature Aggregation ─────────────────────────────────────────

    @staticmethod
    def _aggregate_audio_features(events: list[dict], duration_s: float) -> AudioFeatures:
        if duration_s <= 0:
            duration_s = 1.0
        tts_count = 0
        sfx_count = 0
        peak_count = 0
        bgm_intensity_sum = 0.0
        bgm_count = 0
        ambience_sum = 0.0
        ambience_count = 0
        alignment_pts: list[int] = []
        total_intensity = 0.0

        for ev in events:
            src = str(ev.get("source_type", "") or ev.get("event_type", "")).lower()
            intensity = float(ev.get("intensity", 0.5))
            total_intensity += intensity
            start = int(ev.get("start_ms", 0) or 0)

            if "tts" in src or "dialogue" in src:
                tts_count += 1
            elif "sfx" in src or "metal" in src or "impact" in src or "hit" in src:
                sfx_count += 1
                if ev.get("transient_peak", False) or intensity > 0.7:
                    peak_count += 1
                    alignment_pts.append(start)
            elif "bgm" in src or "music" in src:
                bgm_intensity_sum += intensity
                bgm_count += 1
                if intensity > 0.7:
                    alignment_pts.append(start)
            elif "ambience" in src or "ambient" in src:
                ambience_sum += intensity
                ambience_count += 1

        sfx_per_sec = round(sfx_count / duration_s, 2)
        peak_density = round(peak_count / duration_s, 2)
        bgm_beat = round(bgm_intensity_sum / max(bgm_count, 1), 2)
        amb_int = round(ambience_sum / max(ambience_count, 1), 2)
        tts_dens = round(tts_count / duration_s, 2)

        # Derived metrics
        rhythm_density = round(min(1.0, (sfx_per_sec + peak_density) / 6.0), 2)
        energy = round(min(1.0, total_intensity / max(len(events), 1)), 2)
        # rough tempo estimate from beat events
        tempo = round(min(200.0, bgm_beat * 120), 1) if bgm_count else 0.0

        return AudioFeatures(
            tts_density=tts_dens,
            sfx_events_per_sec=sfx_per_sec,
            transient_peak_density=peak_density,
            bgm_beat_intensity=bgm_beat,
            ambience_intensity=amb_int,
            alignment_points=sorted(set(alignment_pts)),
            rhythm_density=rhythm_density,
            tempo_bpm=tempo,
            energy_level=energy,
        )

    # ── V3: Motion Scoring ────────────────────────────────────────────────────

    @staticmethod
    def _compute_motion_score(
        shot: dict, af: AudioFeatures, ff: FeatureFlags,
    ) -> tuple[int, str, list[str]]:
        """Multi-signal motion score 0-100 per §7.2."""
        tags: list[str] = []

        # 1. Semantic action intensity (0-30)
        action_cues = shot.get("action_cues", [])
        semantic_score = 0
        for cue in action_cues:
            cue_lower = str(cue).lower()
            for kw, sc in _ACTION_SEMANTIC_SCORES.items():
                if kw in cue_lower:
                    semantic_score = max(semantic_score, sc)
                    tags.append(kw)
        semantic_score = min(30, semantic_score)

        # 2. SFX event density (0-25)
        sfx_score = min(25, int(af.sfx_events_per_sec * 7.5))
        if af.sfx_events_per_sec > 2.0:
            tags.append("high_sfx_density")

        # 3. Transient peak density (0-20)
        peak_score = min(20, int(af.transient_peak_density * 7.0))
        if af.transient_peak_density > 1.5:
            tags.append("dense_transient_peaks")

        # 4. BGM beat intensity (0-15)
        bgm_score = min(15, int(af.bgm_beat_intensity * 15))
        if af.bgm_beat_intensity > 0.7:
            tags.append("fast_bgm")

        # 5. Entity count influence (0-10)
        entities = shot.get("entities", [])
        entity_score = min(10, len(entities) * 2)

        # Shot type weight bonus (0-10)
        shot_type = str(shot.get("shot_type", "medium")).lower()
        type_weight = SHOT_TYPE_MOTION_WEIGHT.get(shot_type, 30)
        type_bonus = min(10, int(type_weight * 0.12))

        # Audio energy influence
        energy_bonus = int(af.energy_level * 8)  # 0-8

        raw = semantic_score + sfx_score + peak_score + bgm_score + entity_score + type_bonus + energy_bonus
        capped = min(ff.max_motion_score_cap, max(0, raw))

        # §7.3 classification
        if capped <= MOTION_THRESHOLDS["low_max"]:
            level = MotionLevel.LOW_MOTION.value
        elif capped <= MOTION_THRESHOLDS["medium_max"]:
            level = MotionLevel.MEDIUM_MOTION.value
        else:
            level = MotionLevel.HIGH_MOTION.value

        # Extra semantic tags
        if af.ambience_intensity > 0.6 and capped < 30:
            tags.append("ambient_calm")
        if af.tts_density > 1.0:
            tags.append("dialogue_heavy")
        if shot_type in ("establishing", "wide", "wide_shot"):
            tags.append("establishing_shot")

        return capped, level, list(dict.fromkeys(tags))  # dedupe preserving order

    # ── V4: Render Strategy ───────────────────────────────────────────────────

    @staticmethod
    def _build_render_strategy(
        profile_key: str,
        motion_level: str,
        motion_score: int,
        criticality: str,
        duration_ms: int,
        backend_cap: BackendCapability,
        overrides: UserOverrides,
        ff: FeatureFlags,
        quality_profile: str,
    ) -> RenderStrategy:
        # Frame budget from map
        fb_map = FRAME_BUDGET_MAP.get(profile_key, FRAME_BUDGET_MAP["MEDIUM_LOAD"])
        frame_budget = fb_map.get(motion_level, 12)

        # Critical segments can get upgraded
        if criticality == "critical" and frame_budget < 24:
            frame_budget = 24

        # I2V mode selection (§16.1)
        if motion_level == MotionLevel.HIGH_MOTION.value:
            if motion_score > 80:
                i2v_mode = I2VMode.MULTI_KEYFRAME.value
            else:
                i2v_mode = I2VMode.START_MID_END.value
        elif motion_level == MotionLevel.MEDIUM_MOTION.value:
            i2v_mode = I2VMode.START_MID_END.value if motion_score > 40 else I2VMode.START_END.value
        else:
            i2v_mode = I2VMode.START_END.value

        # Validate against backend capabilities
        constraints: list[str] = []
        if i2v_mode not in backend_cap.supported_i2v_modes:
            constraints.append(f"downgraded_i2v_{i2v_mode}")
            # Fallback: pick best supported
            pref_order = [I2VMode.MULTI_KEYFRAME.value, I2VMode.START_MID_END.value, I2VMode.START_END.value]
            i2v_mode = next((m for m in pref_order if m in backend_cap.supported_i2v_modes), I2VMode.START_END.value)

        if criticality in ("critical", "important"):
            constraints.append("critical_protection")

        # Beat alignment strength
        if motion_level == MotionLevel.HIGH_MOTION.value:
            beat_align = "high"
        elif motion_level == MotionLevel.MEDIUM_MOTION.value:
            beat_align = "medium"
        else:
            beat_align = "low"

        # Quality / compute priority
        if criticality == "critical":
            qp, cp = "high", "high"
        elif criticality == "important":
            qp, cp = "high", "medium"
        elif motion_level == MotionLevel.HIGH_MOTION.value:
            qp, cp = "high", "high"
        else:
            qp = "medium" if motion_level == MotionLevel.MEDIUM_MOTION.value else "low"
            cp = "medium" if motion_level == MotionLevel.MEDIUM_MOTION.value else "low"

        degrade_allowed = criticality not in ("critical",) and motion_level != MotionLevel.HIGH_MOTION.value
        if ff.static_fallback_only:
            i2v_mode = I2VMode.START_END.value
            frame_budget = 8

        # Resolution based on profile
        if profile_key == "HIGH_LOAD":
            resolution = "1920x1080"
            fps = 24
        elif profile_key == "MEDIUM_LOAD":
            resolution = "1280x720"
            fps = 24
        else:
            resolution = "1280x720"
            fps = 24

        # Apply overrides
        if overrides.resolution_cap:
            resolution = overrides.resolution_cap
        if overrides.backend_force:
            backend = overrides.backend_force
        else:
            backend = "comfyui"

        quality_preset = quality_profile if quality_profile in ("preview", "standard", "final") else "standard"

        return RenderStrategy(
            frame_budget=frame_budget,
            i2v_mode=i2v_mode,
            target_shot_duration_ms=duration_ms,
            beat_alignment_strength=beat_align,
            quality_priority=qp,
            compute_priority=cp,
            degrade_allowed=degrade_allowed,
            degrade_level=DegradeLevel.FULL_QUALITY.value,
            fallback_i2v_mode=I2VMode.START_END.value,
            backend_constraints_applied=constraints,
            render_backend=backend,
            resolution=resolution,
            fps=fps,
            quality_preset=quality_preset,
        )

    # ── V5: Micro-shot Splitting ──────────────────────────────────────────────

    @staticmethod
    def _split_microshots(
        plan: ShotRenderPlan, events: list[dict],
    ) -> list[MicroshotRenderPlan]:
        """Split a high-motion shot into micro-shots at alignment points."""
        if plan.duration_ms < MICRO_SHOT_MIN_DURATION_MS * 2:
            return []  # too short to split

        # Gather split points from alignment + peaks
        alignment = list(plan.audio_features.alignment_points)
        for ev in events:
            if ev.get("transient_peak", False):
                alignment.append(int(ev.get("start_ms", 0) or 0))
        # Filter to within shot range and sort
        pts = sorted(set(
            p for p in alignment
            if plan.start_ms < p < plan.end_ms
        ))

        # Build segments from boundaries
        boundaries = [plan.start_ms] + pts + [plan.end_ms]
        # Merge segments that are too short
        merged: list[tuple[int, int]] = []
        seg_start = boundaries[0]
        for j in range(1, len(boundaries)):
            seg_end = boundaries[j]
            dur = seg_end - seg_start
            if dur >= MICRO_SHOT_MIN_DURATION_MS:
                if dur > MICRO_SHOT_MAX_DURATION_MS and j < len(boundaries) - 1:
                    # further split large segments
                    mid = seg_start + dur // 2
                    merged.append((seg_start, mid))
                    seg_start = mid
                else:
                    merged.append((seg_start, seg_end))
                    seg_start = seg_end
            # else accumulate into next segment
        # Handle leftover
        if merged and seg_start != merged[-1][1]:
            last = merged[-1]
            merged[-1] = (last[0], max(last[1], seg_start))

        if len(merged) <= 1:
            return []  # no useful split

        result: list[MicroshotRenderPlan] = []
        for idx, (s, e) in enumerate(merged):
            ms_id = f"{plan.shot_id}_{chr(65 + idx)}"  # S27_A, S27_B, ...
            dur = e - s
            # Find alignment points within this micro-shot
            local_pts = [p for p in pts if s <= p < e]
            # Reason tags
            reason_tags = list(plan.reasoning_tags)
            if local_pts:
                reason_tags.append("impact_peak_alignment")

            # Slightly adjust score per micro-shot
            ms_score = max(0, plan.motion_complexity_score - (idx * 2))

            strategy = RenderStrategy(
                frame_budget=plan.render_strategy.frame_budget,
                i2v_mode=plan.render_strategy.i2v_mode,
                target_shot_duration_ms=dur,
                beat_alignment_strength=plan.render_strategy.beat_alignment_strength,
                quality_priority=plan.render_strategy.quality_priority,
                compute_priority=plan.render_strategy.compute_priority,
                degrade_allowed=plan.render_strategy.degrade_allowed,
                degrade_level=plan.render_strategy.degrade_level,
                fallback_i2v_mode=plan.render_strategy.fallback_i2v_mode,
                backend_constraints_applied=list(plan.render_strategy.backend_constraints_applied),
                render_backend=plan.render_strategy.render_backend,
                resolution=plan.render_strategy.resolution,
                fps=plan.render_strategy.fps,
                quality_preset=plan.render_strategy.quality_preset,
            )

            result.append(MicroshotRenderPlan(
                microshot_id=ms_id,
                parent_shot_id=plan.shot_id,
                start_ms=s,
                end_ms=e,
                duration_ms=dur,
                split_reason_tags=reason_tags,
                alignment_points=local_pts,
                motion_complexity_score=ms_score,
                render_strategy=strategy,
                criticality=plan.criticality,
            ))

        return result

    # ── Camera Motion ─────────────────────────────────────────────────────────

    @staticmethod
    def _infer_camera_motion(plan: ShotRenderPlan) -> str:
        score = plan.motion_complexity_score
        level = plan.motion_level
        if level == MotionLevel.HIGH_MOTION.value:
            return CameraMotion.TRACKING.value if score > 80 else CameraMotion.PAN.value
        if level == MotionLevel.MEDIUM_MOTION.value:
            return CameraMotion.PAN.value if score > 35 else CameraMotion.TILT.value
        return CameraMotion.STATIC.value

    @staticmethod
    def _infer_camera_motion_from_score(score: int) -> str:
        if score > 80:
            return CameraMotion.TRACKING.value
        if score > 55:
            return CameraMotion.PAN.value
        if score > 25:
            return CameraMotion.TILT.value
        return CameraMotion.STATIC.value

    # ── Transitions ───────────────────────────────────────────────────────────

    @staticmethod
    def _plan_transitions(plans: list[ShotRenderPlan]) -> list[TransitionPlan]:
        transitions: list[TransitionPlan] = []
        for i in range(len(plans) - 1):
            cur = plans[i]
            nxt = plans[i + 1]
            # Scene boundary → dissolve/fade; same scene → cut
            if cur.scene_id != nxt.scene_id:
                if cur.motion_level == MotionLevel.LOW_MOTION.value:
                    tt = TransitionType.FADE.value
                    dur = 500
                else:
                    tt = TransitionType.DISSOLVE.value
                    dur = 300
            else:
                # Within same scene — motion continuity
                if cur.motion_level == MotionLevel.HIGH_MOTION.value:
                    tt = TransitionType.CUT.value
                    dur = 0
                elif abs(cur.motion_complexity_score - nxt.motion_complexity_score) > 30:
                    tt = TransitionType.WIPE.value
                    dur = 200
                else:
                    tt = TransitionType.CUT.value
                    dur = 0
            transitions.append(TransitionPlan(
                from_shot_id=cur.shot_id,
                to_shot_id=nxt.shot_id,
                transition_type=tt,
                duration_ms=dur,
            ))
        return transitions

    # ── Layer Composition ─────────────────────────────────────────────────────

    @staticmethod
    def _build_layer_composition(plan: ShotRenderPlan) -> LayerComposition:
        has_entities = "establishing_shot" not in plan.reasoning_tags
        return LayerComposition(
            background=True,
            midground=plan.motion_level != MotionLevel.LOW_MOTION.value,
            character=has_entities,
            fx_overlay=plan.motion_complexity_score > 60 or "explosion" in " ".join(plan.reasoning_tags),
            text_overlay="dialogue_heavy" in plan.reasoning_tags,
        )

    # ── V6: Backend Degradation ───────────────────────────────────────────────

    @staticmethod
    def _apply_degradation(
        plans: list[ShotRenderPlan],
        microshots: list[MicroshotRenderPlan],
        load: BackendLoadStatus,
        overrides: UserOverrides,
        ff: FeatureFlags,
    ) -> list[DegradeAction]:
        actions: list[DegradeAction] = []
        congestion = load.congestion_level.lower()
        if congestion == "low" and load.vram_usage_pct < 70:
            return actions  # no degradation needed

        locked = set(overrides.locked_shot_ids) | set(overrides.forced_high_quality_shot_ids)

        # Sort by criticality — degrade least important first
        crit_order = {"background": 0, "normal": 1, "important": 2, "critical": 3}

        sortable = sorted(plans, key=lambda p: crit_order.get(p.criticality, 1))
        for plan in sortable:
            if plan.shot_id in locked:
                continue
            if plan.criticality == "critical":
                continue  # never degrade critical

            strat = plan.render_strategy
            if congestion == "high" or load.vram_usage_pct > 90:
                # Aggressive: 2-level drop
                if plan.motion_level == MotionLevel.LOW_MOTION.value:
                    new_budget = 8
                    new_mode = I2VMode.START_END.value
                    dlevel = DegradeLevel.STATIC_FALLBACK.value
                elif plan.motion_level == MotionLevel.MEDIUM_MOTION.value:
                    new_budget = max(8, strat.frame_budget // 2)
                    new_mode = I2VMode.START_END.value
                    dlevel = DegradeLevel.SIMPLIFIED_COMP.value
                else:
                    # HIGH_MOTION non-critical: reduce FX only
                    new_budget = max(12, strat.frame_budget)
                    new_mode = strat.i2v_mode
                    dlevel = DegradeLevel.REDUCED_FX.value
            else:
                # Medium congestion: 1-level drop for low/medium
                if plan.motion_level == MotionLevel.LOW_MOTION.value:
                    new_budget = 8
                    new_mode = I2VMode.START_END.value
                    dlevel = DegradeLevel.SIMPLIFIED_COMP.value
                elif plan.motion_level == MotionLevel.MEDIUM_MOTION.value:
                    new_budget = max(8, strat.frame_budget - 4)
                    new_mode = I2VMode.START_END.value
                    dlevel = DegradeLevel.REDUCED_FX.value
                else:
                    continue  # don't degrade high motion under medium congestion

            if new_budget == strat.frame_budget and new_mode == strat.i2v_mode:
                continue

            before = {"frame_budget": strat.frame_budget, "i2v_mode": strat.i2v_mode}
            strat.frame_budget = new_budget
            strat.i2v_mode = new_mode
            strat.degrade_level = dlevel

            actions.append(DegradeAction(
                target_type="shot",
                target_id=plan.shot_id,
                action="reduce_frame_budget" if new_budget < before["frame_budget"] else "simplify_i2v_mode",
                before=before,
                after={"frame_budget": new_budget, "i2v_mode": new_mode},
                reason_tags=[f"congestion_{congestion}", f"vram_{int(load.vram_usage_pct)}pct"],
                degrade_level=dlevel,
                degrade_policy_id=f"auto_degrade_{congestion}",
            ))

        return actions

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_profile(compute_budget: dict, overrides: UserOverrides) -> str:
        if overrides.render_profile_override:
            key = overrides.render_profile_override
        else:
            key = (compute_budget or {}).get("global_render_profile", "MEDIUM_LOAD")
        return key if key in ("LOW_LOAD", "MEDIUM_LOAD", "HIGH_LOAD") else "MEDIUM_LOAD"

    @staticmethod
    def _parse_feature_flags(raw: dict) -> FeatureFlags:
        if not raw:
            return FeatureFlags()
        return FeatureFlags(
            micro_shot_enabled=raw.get("enable_microshot_split", raw.get("micro_shot_enabled", True)),
            max_motion_score_cap=raw.get("max_motion_score_cap", 100),
            static_fallback_only=raw.get("static_fallback_only", False),
            parallel_render_groups=raw.get("parallel_render_groups", 2),
            enable_compute_aware_planning=raw.get("enable_compute_aware_planning", True),
            enable_backend_auto_degrade=raw.get("enable_backend_auto_degrade", True),
            enable_audio_beat_alignment=raw.get("enable_audio_beat_alignment", True),
        )

    @staticmethod
    def _parse_user_overrides(raw: dict) -> UserOverrides:
        if not raw:
            return UserOverrides()
        return UserOverrides(
            render_profile_override=raw.get("render_profile_override"),
            backend_force=raw.get("backend_force"),
            resolution_cap=raw.get("resolution_cap"),
            locked_shot_ids=raw.get("locked_shot_ids", []),
            forced_high_quality_shot_ids=raw.get("forced_high_quality_shot_ids", []),
        )

    @staticmethod
    def _parse_backend_capability(raw: dict) -> BackendCapability:
        if not raw:
            return BackendCapability()
        return BackendCapability(
            gpu_model=raw.get("gpu_model", "A100"),
            supported_i2v_modes=raw.get("supported_i2v_modes", ["start_end", "start_mid_end", "multi_keyframe"]),
            max_concurrency=raw.get("max_concurrency", 4),
            suggested_frame_budget=raw.get("suggested_frame_budget", 24),
            supported_workflows=raw.get("supported_workflows", []),
        )

    @staticmethod
    def _parse_backend_load(raw: dict) -> BackendLoadStatus:
        if not raw:
            return BackendLoadStatus()
        return BackendLoadStatus(
            queue_length=raw.get("queue_length", 0),
            vram_usage_pct=raw.get("vram_usage_pct", 0.0),
            avg_task_duration_s=raw.get("avg_task_duration_s", 0.0),
            congestion_level=raw.get("congestion_level", "low"),
        )

    @staticmethod
    def _infer_criticality(shot: dict, motion_level: str, tags: list[str]) -> str:
        # Check explicit criticality first
        explicit = shot.get("criticality", "")
        if explicit in ("critical", "important", "normal", "background"):
            return explicit
        # Infer from tags / cues
        cues = [str(c).lower() for c in shot.get("action_cues", [])]
        scene_type = str(shot.get("scene_type", "")).lower()
        all_hints = cues + tags + [scene_type]
        best = "normal"
        for hint in all_hints:
            for kw, crit in _CRITICALITY_KEYWORDS.items():
                if kw in hint:
                    order = {"critical": 3, "important": 2, "normal": 1, "background": 0}
                    if order.get(crit, 0) > order.get(best, 0):
                        best = crit
        # HIGH_MOTION defaults to at least important
        if motion_level == MotionLevel.HIGH_MOTION.value and best in ("normal", "background"):
            best = "important"
        return best

    @staticmethod
    def _assemble_warnings(
        plans: list[ShotRenderPlan],
        microshots: list[MicroshotRenderPlan],
        degrade_actions: list[DegradeAction],
        warnings: list[str],
        review_items: list[ReviewRequiredItem],
    ) -> None:
        # Check for excessive micro-shot splitting
        for p in plans:
            child_count = sum(1 for m in microshots if m.parent_shot_id == p.shot_id)
            if child_count > 6:
                warnings.append(
                    f"RENDER-WARN-001: shot {p.shot_id} split into {child_count} microshots (>6)"
                )
                review_items.append(ReviewRequiredItem(
                    item_type="shot",
                    item_id=p.shot_id,
                    reason=f"Excessive micro-shot split ({child_count} segments)",
                    severity="medium",
                    suggested_action="Review split points or increase min_duration",
                ))
        # Degrade conflict check
        for da in degrade_actions:
            if da.degrade_level == DegradeLevel.STATIC_FALLBACK.value:
                warnings.append(
                    f"RENDER-WARN-002: {da.target_id} degraded to STATIC_FALLBACK"
                )

    @staticmethod
    def _build_legacy_plans(plans: list[ShotRenderPlan], profile_key: str) -> list[ShotRenderConfig]:
        """Backward-compat: populate render_plans for old consumers."""
        gpu_tier = "A100" if profile_key != "HIGH_LOAD" else "T4"
        legacy: list[ShotRenderConfig] = []
        for i, p in enumerate(plans):
            if p.motion_level == MotionLevel.LOW_MOTION.value:
                mode = "static"
            else:
                mode = "i2v"
            legacy.append(ShotRenderConfig(
                shot_id=p.shot_id,
                render_mode=mode,
                fps=p.render_strategy.fps,
                resolution=p.render_strategy.resolution,
                priority=i,
                gpu_tier=gpu_tier,
                fallback_chain=["i2v", "static"] if mode == "i2v" else ["static"],
            ))
        return legacy

    @staticmethod
    def _estimate_gpu_hours(plans: list[ShotRenderPlan]) -> float:
        total_frames = 0
        for p in plans:
            dur_s = p.duration_ms / 1000.0
            total_frames += int(dur_s * p.render_strategy.fps)
        return round(total_frames / 24.0 / 3600.0 * 0.5, 4)

    @staticmethod
    def _status_to_output(state: str) -> str:
        mapping = {
            RenderState.READY_FOR_RENDER_EXECUTION.value: "ready_for_render_execution",
            RenderState.REVIEW_REQUIRED.value: "review_required",
            RenderState.FAILED.value: "failed",
        }
        return mapping.get(state, "ready_for_render_execution")

    @staticmethod
    def _fail_output(profile_key: str, issues: list[str]) -> Skill09Output:
        return Skill09Output(
            status="failed",
            global_render_profile=profile_key,
            warnings=issues,
        )
