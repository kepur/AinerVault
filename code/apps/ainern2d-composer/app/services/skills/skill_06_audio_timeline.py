"""SKILL 06: AudioTimelineService — 业务逻辑实现。

Spec  : SKILL_06_AUDIO_TIMELINE_COMPOSER.md
Status: SERVICE_READY

State-machine (§6):
  INIT → PRECHECKING → BACKFILLING_TTS_DURATIONS → PLACING_TRACKS
       → BUILDING_EVENT_MANIFEST → EXPORTING_MIX_HINTS
       → READY_FOR_VISUAL_RENDER_PLANNING | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_06 import (
    AnalysisHintsForVisualRender,
    AudioEvent,
    AudioEventManifest,
    AudioTrack,
    BackfillEntry,
    BackfillReport,
    ConflictEntry,
    ManifestSummary,
    MixHint,
    MixHintParams,
    SceneTimeline,
    Skill06Input,
    Skill06Output,
    ShotTimeline,
    TimingAnchor,
    TimelineTracks,
    ValidationReport,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Constants ────────────────────────────────────────────────────────────────
_DEFAULT_SHOT_DUR_MS = 3000
_ALIGNMENT_PRECISION_MS = 50  # spec §6 — ≤50 ms precision
_DEFAULT_FADE_MS = 200
_DIALOGUE_VOLUME_DB = 0.0
_SFX_VOLUME_DB = -3.0
_BGM_VOLUME_DB = -8.0
_AMBIENCE_VOLUME_DB = -10.0
_TRACK_PRIORITY = {"dialogue": 0, "sfx": 1, "bgm": 2, "ambience": 3, "aux": 4}
_VOLUME_DEFAULTS: dict[str, float] = {
    "dialogue": _DIALOGUE_VOLUME_DB,
    "sfx": _SFX_VOLUME_DB,
    "bgm": _BGM_VOLUME_DB,
    "ambience": _AMBIENCE_VOLUME_DB,
    "aux": _AMBIENCE_VOLUME_DB,
}
_HIGH_INTENSITY_THRESHOLD = 0.7


class AudioTimelineService(BaseSkillService[Skill06Input, Skill06Output]):
    """SKILL 06 — Audio Timeline Composer.

    Consumes audio worker results + plans from SKILL 03/05 and produces
    ``timeline_final`` + ``audio_event_manifest`` for downstream SKILL 09.
    """

    skill_id = "skill_06"
    skill_name = "AudioTimelineService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # =====================================================================
    # execute — main entry
    # =====================================================================
    def execute(self, input_dto: Skill06Input, ctx: SkillContext) -> Skill06Output:  # noqa: C901
        warnings: list[str] = []
        conflicts: list[ConflictEntry] = []

        # ── [C1] PRECHECKING ─────────────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")

        audio_results = input_dto.audio_results or []
        audio_plan = input_dto.audio_plan or {}
        shot_plan = input_dto.shot_plan or []
        feature_flags = input_dto.feature_flags or {}

        precheck_ok, precheck_warnings = self._precheck(
            audio_results, audio_plan, shot_plan,
        )
        warnings.extend(precheck_warnings)

        if not precheck_ok:
            self._record_state(ctx, "PRECHECKING", "REVIEW_REQUIRED")
            logger.warning(f"[{self.skill_id}] precheck failed — REVIEW_REQUIRED")
            return self._build_review_output(warnings)

        # ── [C2] TTS DURATION BACKFILL ───────────────────────────────
        self._record_state(ctx, "PRECHECKING", "BACKFILLING_TTS_DURATIONS")

        shot_timing, scene_shots, backfill_report, bf_warnings = (
            self._backfill_tts_durations(audio_results, shot_plan)
        )
        warnings.extend(bf_warnings)

        # ── [C3] TRACK PLACEMENT ─────────────────────────────────────
        self._record_state(ctx, "BACKFILLING_TTS_DURATIONS", "PLACING_TRACKS")

        tracks, timing_anchors, shot_timelines, scene_timelines, place_conflicts = (
            self._place_tracks(
                audio_results, shot_timing, scene_shots, feature_flags,
            )
        )
        conflicts.extend(place_conflicts)
        tracks_contract = self._build_tracks_contract(tracks)

        total_duration_ms = self._compute_total_duration(tracks, shot_timing)

        # ── [C4] BUILD EVENT MANIFEST ────────────────────────────────
        self._record_state(ctx, "PLACING_TRACKS", "BUILDING_EVENT_MANIFEST")

        manifest = self._build_event_manifest(tracks, shot_timelines)

        # ── [C5] MIX HINT EXPORT ─────────────────────────────────────
        self._record_state(ctx, "BUILDING_EVENT_MANIFEST", "EXPORTING_MIX_HINTS")

        mix_hints = self._build_mix_hints(tracks, feature_flags)

        # ── VALIDATION ───────────────────────────────────────────────
        validation = self._validate(
            tracks, timing_anchors, shot_timelines, total_duration_ms, conflicts,
        )
        warnings.extend(validation.warnings)

        final_status = (
            "review_required"
            if not validation.passed
            else "ready_for_visual_render_planning"
        )
        final_state = (
            "REVIEW_REQUIRED" if not validation.passed
            else "READY_FOR_VISUAL_RENDER_PLANNING"
        )
        self._record_state(ctx, "EXPORTING_MIX_HINTS", final_state)

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"tracks={len(tracks)} anchors={len(timing_anchors)} "
            f"duration_ms={total_duration_ms} status={final_status}"
        )

        return Skill06Output(
            version="1.0",
            status=final_status,
            final_duration_ms=total_duration_ms,
            tracks=tracks_contract,
            track_layers=tracks,
            scene_timeline=scene_timelines,
            shot_timeline=shot_timelines,
            mix_hints=mix_hints,
            warnings=warnings,
            audio_event_manifest=manifest,
            validation_report=validation,
            backfill_report=backfill_report,
        )

    # =====================================================================
    # [C1] Precheck
    # =====================================================================
    @staticmethod
    def _precheck(
        audio_results: list[dict],
        audio_plan: dict,
        shot_plan: list[dict],
    ) -> tuple[bool, list[str]]:
        """Return (ok, warnings). Fail if no shot plan or TTS results missing."""
        warns: list[str] = []

        if not shot_plan:
            warns.append("shot_plan is empty — cannot build timeline")
            return False, warns

        plan_status = audio_plan.get("status", "")
        if plan_status == "failed":
            warns.append(f"audio_plan.status={plan_status} — cannot proceed")
            return False, warns

        # TTS is critical — check at least one dialogue result exists
        has_tts = any(
            r.get("task_type", r.get("source_type", "")) == "tts"
            or r.get("task_type", r.get("source_type", "")) == "dialogue"
            for r in audio_results
        )
        if not has_tts:
            warns.append("No TTS/dialogue results — entering REVIEW mode (§8)")
            return False, warns

        if not audio_results:
            warns.append("audio_results is empty")
            return False, warns

        return True, warns

    # =====================================================================
    # [C2] TTS Duration Backfill
    # =====================================================================
    @staticmethod
    def _backfill_tts_durations(
        audio_results: list[dict],
        shot_plan: list[dict],
    ) -> tuple[
        dict[str, tuple[int, int]],       # shot_timing: shot_id → (start, end)
        dict[str, list[str]],             # scene_shots: scene_id → [shot_ids]
        BackfillReport,
        list[str],                        # warnings
    ]:
        """Build shot timing map, backfilling actual TTS durations."""
        warnings: list[str] = []
        backfill_entries: list[BackfillEntry] = []

        # Index TTS results by shot_id for quick lookup
        tts_by_shot: dict[str, dict] = {}
        for r in audio_results:
            stype = r.get("task_type", r.get("source_type", ""))
            if stype in ("tts", "dialogue"):
                sid = r.get("shot_id", "")
                if sid:
                    tts_by_shot[sid] = r

        shot_timing: dict[str, tuple[int, int]] = {}
        scene_shots: dict[str, list[str]] = {}
        cursor_ms = 0
        total_shift = 0

        for shot in shot_plan:
            sid = shot.get("shot_id", "")
            scene_id = shot.get("scene_id", "")
            original_dur_ms = int(
                float(shot.get("duration_ms", 0))
                or float(shot.get("duration_seconds", _DEFAULT_SHOT_DUR_MS / 1000)) * 1000
            )

            actual_dur_ms = original_dur_ms
            if sid in tts_by_shot:
                tts_dur = tts_by_shot[sid].get("actual_duration_ms", 0)
                if tts_dur and tts_dur > 0:
                    # TTS duration may be longer than planned shot — take the max
                    actual_dur_ms = max(original_dur_ms, int(tts_dur))
                    delta = actual_dur_ms - original_dur_ms
                    if delta != 0:
                        total_shift += delta
                        backfill_entries.append(BackfillEntry(
                            shot_id=sid,
                            original_ms=original_dur_ms,
                            backfilled_ms=actual_dur_ms,
                            delta_ms=delta,
                        ))

            shot_timing[sid] = (cursor_ms, cursor_ms + actual_dur_ms)
            cursor_ms += actual_dur_ms

            scene_shots.setdefault(scene_id, []).append(sid)

        if total_shift > 0:
            warnings.append(
                f"TTS backfill shifted total duration by {total_shift}ms"
            )

        return (
            shot_timing,
            scene_shots,
            BackfillReport(entries=backfill_entries, total_shift_ms=total_shift),
            warnings,
        )

    # =====================================================================
    # [C3] Track Placement
    # =====================================================================
    def _place_tracks(
        self,
        audio_results: list[dict],
        shot_timing: dict[str, tuple[int, int]],
        scene_shots: dict[str, list[str]],
        feature_flags: dict,
    ) -> tuple[
        list[AudioTrack],
        list[TimingAnchor],
        list[ShotTimeline],
        list[SceneTimeline],
        list[ConflictEntry],
    ]:
        conflicts: list[ConflictEntry] = []

        # Buckets for events per track type
        events_by_type: dict[str, list[AudioEvent]] = {
            "dialogue": [], "bgm": [], "sfx": [], "ambience": [], "aux": [],
        }
        anchor_list: list[TimingAnchor] = []

        # ── shot boundary anchors + dialogue start/end anchors ───────
        dialogue_bounds: dict[str, tuple[int, int]] = {}

        event_counter = 0
        for r in audio_results:
            raw_type = r.get("task_type", r.get("source_type", ""))
            track_type = self._normalise_track_type(raw_type)
            shot_id = r.get("shot_id", "")
            scene_id = r.get("scene_id", "")
            asset_ref = r.get("asset_ref", r.get("asset_uri", r.get("output_uri", "")))
            actual_dur_ms = int(r.get("actual_duration_ms", 0))
            task_id = r.get("task_id", r.get("tts_task_id", r.get("sfx_task_id", "")))

            shot_start, shot_end = shot_timing.get(shot_id, (0, _DEFAULT_SHOT_DUR_MS))

            # Compute event start/end
            if track_type == "dialogue":
                ev_start = shot_start
                ev_end = shot_start + actual_dur_ms if actual_dur_ms else shot_end
                dialogue_bounds[shot_id] = (ev_start, ev_end)
            elif track_type in ("ambience", "bgm"):
                # Scene-level — span entire scene
                ev_start = shot_start
                ev_end = shot_end
                if actual_dur_ms > 0:
                    ev_end = max(shot_end, shot_start + actual_dur_ms)
            else:
                ev_start = shot_start
                ev_end = shot_start + actual_dur_ms if actual_dur_ms else shot_end

            # Fade defaults for non-dialogue
            fade_in = _DEFAULT_FADE_MS if track_type in ("bgm", "ambience") else 0
            fade_out = _DEFAULT_FADE_MS if track_type in ("bgm", "ambience") else 0

            eid = f"AE_{event_counter:04d}"
            event_counter += 1

            intensity = float(r.get("intensity", 0.5))
            transient = bool(r.get("transient_peak", False))
            if feature_flags.get("enable_peak_analysis_import"):
                if r.get("peak_data"):
                    transient = True
                    intensity = max(intensity, 0.85)

            ev = AudioEvent(
                event_id=eid,
                shot_id=shot_id,
                scene_id=scene_id,
                start_ms=ev_start,
                end_ms=ev_end,
                asset_ref=asset_ref,
                source_type=raw_type,
                fade_in_ms=fade_in,
                fade_out_ms=fade_out,
                speaker_id=r.get("speaker_id", ""),
                emotion_hint=r.get("emotion_hint", ""),
                event_type=r.get("event_type", track_type),
                intensity=intensity,
                transient_peak=transient,
                task_id=task_id,
            )
            events_by_type.setdefault(track_type, []).append(ev)

        # ── Resolve overlapping events within same track ─────────────
        for ttype, evts in events_by_type.items():
            evts.sort(key=lambda e: e.start_ms)
            for i in range(1, len(evts)):
                prev, cur = evts[i - 1], evts[i]
                if cur.start_ms < prev.end_ms:
                    overlap_ms = prev.end_ms - cur.start_ms
                    if ttype == "dialogue":
                        # Hard conflict — flag it
                        conflicts.append(ConflictEntry(
                            conflict_id=f"overlap_{prev.event_id}_{cur.event_id}",
                            description=(
                                f"Dialogue overlap {overlap_ms}ms between "
                                f"{prev.event_id} and {cur.event_id}"
                            ),
                            severity="error",
                            shot_id=cur.shot_id,
                        ))
                    else:
                        # Soft overlap — add crossfade
                        xfade = min(overlap_ms, _DEFAULT_FADE_MS)
                        evts[i - 1] = prev.model_copy(update={"fade_out_ms": xfade})
                        evts[i] = cur.model_copy(update={"fade_in_ms": xfade})

        # ── Build AudioTrack objects ─────────────────────────────────
        tracks: list[AudioTrack] = []
        for ttype in ("dialogue", "sfx", "bgm", "ambience", "aux"):
            evts = events_by_type.get(ttype, [])
            if not evts:
                continue
            tracks.append(AudioTrack(
                track_id=f"track_{ttype}",
                track_type=ttype,  # type: ignore[arg-type]
                events=evts,
                priority=_TRACK_PRIORITY.get(ttype, 4),
                volume_db=_VOLUME_DEFAULTS.get(ttype, 0.0),
            ))

        # ── Build timing anchors ─────────────────────────────────────
        for shot_id, (s, _e) in shot_timing.items():
            anchor_list.append(TimingAnchor(
                anchor_id=f"anc_sb_{shot_id}",
                shot_id=shot_id,
                time_ms=s,
                anchor_type="shot_boundary",
            ))
        for shot_id, (ds, de) in dialogue_bounds.items():
            anchor_list.append(TimingAnchor(
                anchor_id=f"anc_ds_{shot_id}",
                shot_id=shot_id,
                time_ms=ds,
                anchor_type="dialogue_start",
            ))
            anchor_list.append(TimingAnchor(
                anchor_id=f"anc_de_{shot_id}",
                shot_id=shot_id,
                time_ms=de,
                anchor_type="dialogue_end",
            ))
        anchor_list.sort(key=lambda a: a.time_ms)

        # ── Build shot timelines ─────────────────────────────────────
        shot_timelines: list[ShotTimeline] = []
        for shot_id, (s, e) in shot_timing.items():
            ds, de = dialogue_bounds.get(shot_id, (None, None))
            scene_id = ""
            for sc, sids in scene_shots.items():
                if shot_id in sids:
                    scene_id = sc
                    break
            shot_timelines.append(ShotTimeline(
                shot_id=shot_id,
                scene_id=scene_id,
                start_ms=s,
                end_ms=e,
                dialogue_start_ms=ds,
                dialogue_end_ms=de,
                duration_ms=e - s,
            ))

        # ── Build scene timelines ────────────────────────────────────
        scene_timelines: list[SceneTimeline] = []
        for scene_id, sids in scene_shots.items():
            if not sids:
                continue
            sc_start = min(shot_timing[s][0] for s in sids if s in shot_timing)
            sc_end = max(shot_timing[s][1] for s in sids if s in shot_timing)
            scene_timelines.append(SceneTimeline(
                scene_id=scene_id,
                start_ms=sc_start,
                end_ms=sc_end,
                shot_ids=sids,
                duration_ms=sc_end - sc_start,
            ))

        return tracks, anchor_list, shot_timelines, scene_timelines, conflicts

    # =====================================================================
    # [C4] Build Event Manifest
    # =====================================================================
    @staticmethod
    def _build_event_manifest(
        tracks: list[AudioTrack],
        shot_timelines: list[ShotTimeline],
    ) -> AudioEventManifest:
        all_events: list[AudioEvent] = []
        dialogue_count = 0
        sfx_count = 0
        bgm_count = 0
        ambience_count = 0

        for trk in tracks:
            for ev in trk.events:
                all_events.append(ev)
                if trk.track_type == "dialogue":
                    dialogue_count += 1
                elif trk.track_type == "sfx":
                    sfx_count += 1
                elif trk.track_type == "bgm":
                    bgm_count += 1
                elif trk.track_type == "ambience":
                    ambience_count += 1

        # Identify high-intensity windows
        high_intensity_evts = [e for e in all_events if e.intensity >= _HIGH_INTENSITY_THRESHOLD]
        high_intensity_shots = sorted({e.shot_id for e in high_intensity_evts})

        # Dialogue-heavy shots: shots with >1 dialogue events or long dialogue
        dialogue_events_by_shot: dict[str, int] = {}
        for trk in tracks:
            if trk.track_type != "dialogue":
                continue
            for ev in trk.events:
                dialogue_events_by_shot[ev.shot_id] = (
                    dialogue_events_by_shot.get(ev.shot_id, 0) + 1
                )
        dialogue_heavy = sorted(
            sid for sid, cnt in dialogue_events_by_shot.items() if cnt >= 1
        )

        # Low-motion ambience shots: shots with only ambience, no sfx/dialogue
        shots_with_action: set[str] = set()
        for trk in tracks:
            if trk.track_type in ("dialogue", "sfx"):
                for ev in trk.events:
                    shots_with_action.add(ev.shot_id)
        all_shot_ids = {st.shot_id for st in shot_timelines}
        low_motion = sorted(all_shot_ids - shots_with_action)

        return AudioEventManifest(
            version="1.0",
            events=all_events,
            summary=ManifestSummary(
                dialogue_events=dialogue_count,
                sfx_events=sfx_count,
                bgm_segments=bgm_count,
                ambience_segments=ambience_count,
                high_intensity_windows=len(high_intensity_shots),
            ),
            analysis_hints_for_visual_render=AnalysisHintsForVisualRender(
                high_motion_candidate_shots=high_intensity_shots,
                low_motion_ambience_shots=low_motion,
                dialogue_heavy_shots=dialogue_heavy,
            ),
        )

    # =====================================================================
    # [C5] Mix Hints
    # =====================================================================
    @staticmethod
    def _build_mix_hints(
        tracks: list[AudioTrack],
        feature_flags: dict,
    ) -> list[MixHint]:
        hints: list[MixHint] = []
        track_types_present = {t.track_type for t in tracks}

        # Ducking: dialogue ducks bgm & ambience
        if feature_flags.get("enable_auto_ducking_plan", True):
            if "dialogue" in track_types_present:
                if "bgm" in track_types_present:
                    hints.append(MixHint(
                        type="duck",
                        trigger_track="dialogue",
                        target_track="bgm",
                        params=MixHintParams(
                            gain_reduction_db=-6.0,
                            attack_ms=50,
                            release_ms=200,
                        ),
                    ))
                if "ambience" in track_types_present:
                    hints.append(MixHint(
                        type="duck",
                        trigger_track="dialogue",
                        target_track="ambience",
                        params=MixHintParams(
                            gain_reduction_db=-4.0,
                            attack_ms=50,
                            release_ms=300,
                        ),
                    ))

        # Impact emphasis for high-intensity sfx
        for trk in tracks:
            if trk.track_type != "sfx":
                continue
            for ev in trk.events:
                if ev.transient_peak or ev.intensity >= _HIGH_INTENSITY_THRESHOLD:
                    hints.append(MixHint(
                        type="emphasis",
                        trigger_track="sfx",
                        target_track="bgm",
                        params=MixHintParams(
                            hint=f"transient_clarity_priority:{ev.event_type}",
                        ),
                    ))

        return hints

    # =====================================================================
    # Validation
    # =====================================================================
    @staticmethod
    def _validate(
        tracks: list[AudioTrack],
        anchors: list[TimingAnchor],
        shot_timelines: list[ShotTimeline],
        total_duration_ms: int,
        existing_conflicts: list[ConflictEntry],
    ) -> ValidationReport:
        warnings: list[str] = []
        conflicts = list(existing_conflicts)

        # Check alignment precision — all anchors should be on multiples of
        # _ALIGNMENT_PRECISION_MS or at least within tolerance.
        max_drift = 0.0
        for anc in anchors:
            drift = anc.time_ms % _ALIGNMENT_PRECISION_MS
            if drift > 0:
                drift = min(drift, _ALIGNMENT_PRECISION_MS - drift)
            max_drift = max(max_drift, drift)

        if max_drift > _ALIGNMENT_PRECISION_MS:
            warnings.append(
                f"Anchor alignment drift {max_drift}ms exceeds {_ALIGNMENT_PRECISION_MS}ms"
            )

        # Check for empty tracks
        for trk in tracks:
            if not trk.events:
                warnings.append(f"Track {trk.track_id} has no events")

        # Check total duration consistency
        if total_duration_ms <= 0:
            conflicts.append(ConflictEntry(
                conflict_id="zero_duration",
                description="Total duration is 0 or negative",
                severity="error",
            ))

        has_errors = any(c.severity == "error" for c in conflicts)

        return ValidationReport(
            alignment_precision_ms=float(max_drift),
            conflicts=conflicts,
            warnings=warnings,
            passed=not has_errors,
        )

    # =====================================================================
    # Helpers
    # =====================================================================
    @staticmethod
    def _build_tracks_contract(tracks: list[AudioTrack]) -> TimelineTracks:
        grouped: dict[str, list[AudioEvent]] = {
            "dialogue": [],
            "ambience": [],
            "sfx": [],
            "bgm": [],
            "aux": [],
        }
        for trk in tracks:
            ttype = trk.track_type if trk.track_type in grouped else "aux"
            grouped[ttype].extend(trk.events)

        for ttype in grouped:
            grouped[ttype].sort(key=lambda ev: (ev.start_ms, ev.end_ms, ev.event_id))

        return TimelineTracks(**grouped)

    @staticmethod
    def _normalise_track_type(raw: str) -> str:
        mapping: dict[str, str] = {
            "tts": "dialogue",
            "dialogue": "dialogue",
            "bgm": "bgm",
            "bgm_file": "bgm",
            "music": "bgm",
            "sfx": "sfx",
            "sfx_file": "sfx",
            "sound_effect": "sfx",
            "ambience": "ambience",
            "ambience_file": "ambience",
            "ambient": "ambience",
        }
        return mapping.get(raw.lower(), "aux")

    @staticmethod
    def _compute_total_duration(
        tracks: list[AudioTrack],
        shot_timing: dict[str, tuple[int, int]],
    ) -> int:
        max_ms = 0
        for trk in tracks:
            for ev in trk.events:
                max_ms = max(max_ms, ev.end_ms)
        for _sid, (_, end) in shot_timing.items():
            max_ms = max(max_ms, end)
        return max_ms

    @staticmethod
    def _build_review_output(warnings: list[str]) -> Skill06Output:
        return Skill06Output(
            status="review_required",
            warnings=warnings,
            validation_report=ValidationReport(passed=False, warnings=warnings),
        )
