/**
 * NLE Timeline Store — Sprint 1
 * 
 * Supports:
 * - Loading a run's artifact manifest and auto-assembling timeline
 * - Track/clip state management
 * - Clip editing (trim, speed, volume, fade)
 * - selectedClip property panel
 * - Project save/load
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TrackDef {
    track_id: string
    type: 'video' | 'audio' | 'text' | 'storyboard' | 'overlay'
    name: string
    order: number
}

export interface ClipDef {
    clip_id: string
    track_id: string
    asset_id: string | null
    kind: 'video' | 'audio' | 'text' | 'storyboard'
    start: number     // seconds
    end: number       // seconds
    offset_in_asset: number
    speed: number
    volume: number
    fade_in: number
    fade_out: number
    meta: {
        shot_id?: string
        dialogue_id?: string
        title?: string
        prompt?: string
        text?: string
        speaker?: string
        url?: string
        [key: string]: unknown
    }
}

export interface AssetCandidate {
    asset_id: string
    url: string
    duration_sec: number
    type: string
}

export interface ShotManifest {
    shot_id: string
    order: number
    duration_sec: number
    title: string
    prompt: string
    video_candidates: AssetCandidate[]
    storyboard_image: AssetCandidate | null
}

export interface DialogueManifest {
    dialogue_id: string
    shot_id: string | null
    speaker_persona: string
    text: string
    tts_candidates: AssetCandidate[]
}

export interface RunArtifactsManifest {
    run_id: string
    fps: number
    resolution: { w: number; h: number }
    total_duration_sec: number
    shots: ShotManifest[]
    dialogues: DialogueManifest[]
    bgm: Array<{ asset_id: string; url: string; duration_sec: number; suggest_range: Record<string, string> }>
    sfx: Array<{ asset_id: string; url: string; shot_id: string | null; at_sec_in_shot: number }>
}

export interface TimelineProject {
    project_id: string
    run_id: string
    fps: number
    resolution: { w: number; h: number }
    tracks: TrackDef[]
    clips: ClipDef[]
    bindings: Record<string, string[]>
    total_duration_sec: number
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useNleTimelineStore = defineStore('nleTimeline', () => {
    // ── Playback state ─────────────────────────────────────────────────────────
    const currentTime = ref(0)          // playhead position (seconds)
    const zoomLevel = ref(60)           // px per second
    const isPlaying = ref(false)

    // ── Project state ──────────────────────────────────────────────────────────
    const projectId = ref<string | null>(null)
    const runId = ref('')
    const fps = ref(24)
    const resolution = ref({ w: 1280, h: 720 })
    const totalDurationSec = ref(0)
    const tracks = ref<TrackDef[]>([])
    const clips = ref<ClipDef[]>([])
    const bindings = ref<Record<string, string[]>>({})

    // ── Selection ──────────────────────────────────────────────────────────────
    const selectedClipId = ref<string | null>(null)
    const selectedClip = computed(() => clips.value.find(c => c.clip_id === selectedClipId.value) ?? null)

    // ── Assets sidecar (from manifest) ───────────────────────────────────────
    const manifest = ref<RunArtifactsManifest | null>(null)

    // ── Loading state ─────────────────────────────────────────────────────────
    const isLoading = ref(false)
    const isSaving = ref(false)
    const loadError = ref<string | null>(null)

    // ── Derived ───────────────────────────────────────────────────────────────
    const sortedTracks = computed(() =>
        [...tracks.value].sort((a, b) => a.order - b.order)
    )

    const clipsForTrack = (trackId: string) =>
        clips.value.filter(c => c.track_id === trackId)

    // ── Actions ───────────────────────────────────────────────────────────────

    /** Load manifest and auto-assemble OR load existing project. */
    async function loadRun(rid: string) {
        isLoading.value = true
        loadError.value = null
        runId.value = rid
        try {
            // 1. First try to load an existing project for this run
            // 2. If not found, create one (triggers auto-assemble on backend)
            const createResp = await axios.post('/api/v1/timeline/projects', {
                tenant_id: 'default',
                project_id: 'default',
                run_id: rid,
                auto_assemble: true,
            })
            _applyProjectResponse(createResp.data)
        } catch (err: unknown) {
            if (axios.isAxiosError(err)) {
                loadError.value = err.response?.data?.detail ?? err.message
            } else {
                loadError.value = String(err)
            }
        } finally {
            isLoading.value = false
        }
    }

    /** Load an existing project by ID. */
    async function loadProject(pid: string) {
        isLoading.value = true
        loadError.value = null
        try {
            const resp = await axios.get(`/api/v1/timeline/projects/${pid}`)
            _applyProjectResponse(resp.data)
        } catch (err: unknown) {
            if (axios.isAxiosError(err)) {
                loadError.value = err.response?.data?.detail ?? err.message
            } else {
                loadError.value = String(err)
            }
        } finally {
            isLoading.value = false
        }
    }

    /** Save current project state to backend. */
    async function saveProject() {
        if (!projectId.value) return
        isSaving.value = true
        try {
            await axios.put(`/api/v1/timeline/projects/${projectId.value}`, {
                run_id: runId.value,
                fps: fps.value,
                resolution: resolution.value,
                tracks: tracks.value,
                clips: clips.value,
                bindings: bindings.value,
                total_duration_sec: totalDurationSec.value,
            })
        } finally {
            isSaving.value = false
        }
    }

    /** Update a property of the selected clip in-place. */
    function updateClip(clipId: string, updates: Partial<ClipDef>) {
        const idx = clips.value.findIndex(c => c.clip_id === clipId)
        if (idx < 0) return
        clips.value[idx] = { ...clips.value[idx], ...updates }
    }

    /** Trim a clip (adjust start/end). */
    function trimClip(clipId: string, newStart: number, newEnd: number) {
        updateClip(clipId, { start: newStart, end: newEnd })
    }

    /** Split a clip at the given time into two clips. */
    function splitClip(clipId: string, splitAt: number) {
        const idx = clips.value.findIndex(c => c.clip_id === clipId)
        if (idx < 0) return
        const original = clips.value[idx]
        if (splitAt <= original.start || splitAt >= original.end) return

        const leftPart: ClipDef = {
            ...original,
            clip_id: `${original.clip_id}_L`,
            end: splitAt,
        }
        const rightPart: ClipDef = {
            ...original,
            clip_id: `${original.clip_id}_R`,
            start: splitAt,
            offset_in_asset: original.offset_in_asset + (splitAt - original.start) * original.speed,
        }
        clips.value.splice(idx, 1, leftPart, rightPart)
    }

    /** Move a clip to a new start position (keeping duration). */
    function moveClip(clipId: string, newStart: number) {
        const idx = clips.value.findIndex(c => c.clip_id === clipId)
        if (idx < 0) return
        const dur = clips.value[idx].end - clips.value[idx].start
        clips.value[idx] = { ...clips.value[idx], start: newStart, end: newStart + dur }
    }

    /** Replace candidate asset for a clip. */
    function replaceCandidateAsset(clipId: string, candidate: AssetCandidate) {
        updateClip(clipId, {
            asset_id: candidate.asset_id,
            meta: { ...(clips.value.find(c => c.clip_id === clipId)?.meta ?? {}), url: candidate.url },
        })
    }

    function selectClip(clipId: string | null) {
        selectedClipId.value = clipId
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    function _applyProjectResponse(data: {
        project_id: string
        run_id: string
        payload: {
            fps: number
            resolution: { w: number; h: number }
            tracks: TrackDef[]
            clips: ClipDef[]
            bindings: Record<string, string[]>
            total_duration_sec: number
        }
    }) {
        projectId.value = data.project_id
        runId.value = data.run_id
        const p = data.payload
        fps.value = p.fps
        resolution.value = p.resolution
        tracks.value = [...p.tracks].sort((a, b) => a.order - b.order)
        clips.value = p.clips
        bindings.value = p.bindings
        totalDurationSec.value = p.total_duration_sec
    }

    return {
        // state
        currentTime, zoomLevel, isPlaying,
        projectId, runId, fps, resolution, totalDurationSec,
        tracks, clips, bindings,
        selectedClipId, selectedClip,
        manifest,
        isLoading, isSaving, loadError,
        // computed
        sortedTracks, clipsForTrack,
        // actions
        loadRun, loadProject, saveProject,
        updateClip, trimClip, splitClip, moveClip, replaceCandidateAsset,
        selectClip,
    }
})
