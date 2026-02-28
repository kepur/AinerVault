<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { NButton, NInput, NInputNumber, NSelect, NSlider, NEmpty, NSpin, NAlert } from 'naive-ui'
import { useNleTimelineStore, type ClipDef, type AssetCandidate } from '@/stores/useNleTimelineStore'

const store = useNleTimelineStore()

// ── UI state ──────────────────────────────────────────────────────────────────
const runIdInput = ref('')
const isRegenerating = ref(false)
const regenPrompt = ref('')

// ── Playhead drag ─────────────────────────────────────────────────────────────
let isDragging = false

const startDragPlayhead = () => { isDragging = true }
const stopDragPlayhead = () => { isDragging = false }

const onMouseMove = (e: MouseEvent) => {
  if (!isDragging) return
  const container = document.getElementById('timeline-scroll-area')
  if (!container) return
  const trackHeaderWidth = 140
  const rect = container.getBoundingClientRect()
  const offsetX = e.clientX - rect.left - trackHeaderWidth + container.scrollLeft
  store.currentTime = Math.max(0, offsetX / store.zoomLevel)
}

const onTimelineClick = (e: MouseEvent) => {
  const container = e.currentTarget as HTMLElement
  if (!container) return
  const trackHeaderWidth = 140
  const rect = container.getBoundingClientRect()
  const offsetX = e.clientX - rect.left - trackHeaderWidth + container.scrollLeft
  store.currentTime = Math.max(0, offsetX / store.zoomLevel)
}

onMounted(() => {
  window.addEventListener('mouseup', stopDragPlayhead)
  window.addEventListener('mousemove', onMouseMove)
})

onUnmounted(() => {
  window.removeEventListener('mouseup', stopDragPlayhead)
  window.removeEventListener('mousemove', onMouseMove)
})

// ── Run load ───────────────────────────────────────────────────────────────────
async function handleLoadRun() {
  if (!runIdInput.value.trim()) return
  await store.loadRun(runIdInput.value.trim())
}

async function handleSaveProject() {
  await store.saveProject()
}

// ── Clip prop panel ────────────────────────────────────────────────────────────
const clip = computed(() => store.selectedClip as ClipDef | null)

function updateSpeed(val: number) {
  if (!clip.value) return
  store.updateClip(clip.value.clip_id, { speed: Math.max(0.5, Math.min(2.0, val)) })
}

function updateVolume(val: number) {
  if (!clip.value) return
  store.updateClip(clip.value.clip_id, { volume: Math.max(0, Math.min(1, val)) })
}

function updateFadeIn(val: number) {
  if (!clip.value) return
  store.updateClip(clip.value.clip_id, { fade_in: val })
}

function updateFadeOut(val: number) {
  if (!clip.value) return
  store.updateClip(clip.value.clip_id, { fade_out: val })
}

function handleSplitClip() {
  if (!clip.value) return
  store.splitClip(clip.value.clip_id, store.currentTime)
}

// ── Regenerate ────────────────────────────────────────────────────────────────
async function handleRegenerate() {
  if (!clip.value?.meta?.shot_id) return
  isRegenerating.value = true
  try {
    await fetch(`/api/v1/runs/${store.runId}/regenerate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_id: 'default',
        project_id: 'default',
        shot_id: clip.value.meta.shot_id,
        prompt_patch: regenPrompt.value,
        quality: 'standard',
        target_duration_sec: clip.value.end - clip.value.start,
      }),
    })
  } finally {
    isRegenerating.value = false
  }
}

// ── Track type label ──────────────────────────────────────────────────────────
function trackTypeIcon(type: string): string {
  const m: Record<string, string> = { video: '🎬', audio: '🎵', storyboard: '🖼️', text: '📝', overlay: '✨' }
  return m[type] ?? '📦'
}

// ── Clip style ────────────────────────────────────────────────────────────────
function clipColor(clip: ClipDef): string {
  const colors: Record<string, string> = {
    video: '#2563eb',
    audio: '#7c3aed',
    storyboard: '#0891b2',
    text: '#065f46',
  }
  return colors[clip.kind] ?? '#475569'
}

// ── Time ruler ────────────────────────────────────────────────────────────────
const rulerTicks = computed(() => {
  const total = Math.max(store.totalDurationSec || 60, 60)
  const interval = store.zoomLevel >= 80 ? 1 : store.zoomLevel >= 40 ? 2 : 5
  const ticks: Array<{ sec: number; label: string; isMajor: boolean }> = []
  for (let i = 0; i <= total; i += interval) {
    const min = Math.floor(i / 60)
    const sec = i % 60
    const label = min > 0 ? `${min}m${sec}s` : `${i}s`
    ticks.push({ sec: i, label, isMajor: i % (interval * 5) === 0 })
  }
  return ticks
})
</script>

<template>
  <div class="nle-root">
    <!-- ── TOP TOOLBAR ──────────────────────────────────────────────────────── -->
    <div class="nle-toolbar">
      <div class="toolbar-brand">
        <span class="brand-icon">🎬</span>
        <span class="brand-label">NLE Timeline</span>
      </div>

      <!-- Load Run -->
      <div class="toolbar-run-loader">
        <n-input
          v-model:value="runIdInput"
          size="small"
          placeholder="Run ID..."
          class="run-id-input"
          @keydown.enter="handleLoadRun"
        />
        <n-button size="small" type="primary" :loading="store.isLoading" @click="handleLoadRun">
          Load Run
        </n-button>
        <n-button v-if="store.projectId" size="small" :loading="store.isSaving" @click="handleSaveProject">
          💾 Save
        </n-button>
      </div>

      <!-- Project Info -->
      <div v-if="store.projectId" class="toolbar-meta">
        <span class="meta-chip">Project: <code>{{ store.projectId.slice(0, 12) }}…</code></span>
        <span class="meta-chip">{{ store.fps }} fps ·  {{ store.resolution.w }}×{{ store.resolution.h }}</span>
        <span class="meta-chip">Total: {{ store.totalDurationSec.toFixed(1) }}s</span>
      </div>

      <!-- Zoom & Playhead -->
      <div class="toolbar-zoom">
        <span class="meta-chip">{{ store.currentTime.toFixed(2) }}s</span>
        <n-button size="tiny" @click="store.zoomLevel = Math.max(10, store.zoomLevel - 15)">－</n-button>
        <span class="zoom-val">{{ store.zoomLevel }}px/s</span>
        <n-button size="tiny" @click="store.zoomLevel = Math.min(300, store.zoomLevel + 15)">＋</n-button>
      </div>
    </div>

    <!-- ── ALERT ─────────────────────────────────────────────────────────────── -->
    <n-alert v-if="store.loadError" type="error" class="nle-alert" closable>
      {{ store.loadError }}
    </n-alert>

    <!-- ── MAIN BODY ──────────────────────────────────────────────────────────── -->
    <div class="nle-body">

      <!-- ── LEFT: ASSET SIDEBAR ──────────────────────────────────────────── -->
      <div class="nle-sidebar">
        <div class="sidebar-section-title">素材库</div>

        <!-- Shots -->
        <div v-if="store.manifest?.shots?.length" class="sidebar-group">
          <div class="sidebar-group-label">🎬 分镜（Shots）</div>
          <div v-for="shot in store.manifest.shots" :key="shot.shot_id" class="sidebar-item">
            <div class="sidebar-item-title">{{ shot.title || shot.shot_id }}</div>
            <div class="sidebar-item-sub">{{ shot.duration_sec.toFixed(1) }}s · {{ shot.video_candidates.length }} videos</div>
          </div>
        </div>

        <!-- Dialogues -->
        <div v-if="store.manifest?.dialogues?.length" class="sidebar-group">
          <div class="sidebar-group-label">🎤 对白（Dialogues）</div>
          <div v-for="dlg in store.manifest.dialogues" :key="dlg.dialogue_id" class="sidebar-item">
            <div class="sidebar-item-title">{{ dlg.speaker_persona || 'Unknown' }}</div>
            <div class="sidebar-item-sub">{{ dlg.text.slice(0, 40) }}…</div>
          </div>
        </div>

        <!-- Empty state -->
        <div v-if="!store.manifest && !store.isLoading" class="sidebar-empty">
          <p>输入 Run ID 并点击 "Load Run" 一键装配时间线</p>
        </div>
        <n-spin v-if="store.isLoading" size="small" class="sidebar-spin" />
      </div>

      <!-- ── CENTER: TIMELINE ──────────────────────────────────────────────── -->
      <div class="nle-timeline-area">
        <!-- Empty hint when no tracks loaded -->
        <div v-if="store.tracks.length === 0 && !store.isLoading" class="timeline-empty">
          <n-empty description="尚未加载 Run，请在左上角输入 Run ID 并点击 Load Run" />
        </div>
        <n-spin v-else-if="store.isLoading" class="timeline-spin" />

        <!-- Timeline grid -->
        <div
          v-else
          id="timeline-scroll-area"
          class="timeline-scroll-area"
          @mousedown="onTimelineClick"
        >
          <!-- Fixed track headers (sticky left) -->
          <div class="track-headers">
            <div class="ruler-header-stub"></div>
            <div v-for="track in store.sortedTracks" :key="track.track_id" class="track-header">
              <span class="track-icon">{{ trackTypeIcon(track.type) }}</span>
              <span class="track-name">{{ track.name }}</span>
            </div>
          </div>

          <!-- Scrollable track content -->
          <div class="track-content-wrapper">
            <!-- Time ruler -->
            <div class="time-ruler">
              <div
                v-for="tick in rulerTicks"
                :key="tick.sec"
                class="ruler-tick"
                :class="{ 'major-tick': tick.isMajor }"
                :style="{ left: `${tick.sec * store.zoomLevel}px` }"
              >
                <span v-if="tick.isMajor" class="tick-label">{{ tick.label }}</span>
              </div>
            </div>

            <!-- Tracks + clips container -->
            <div
              class="tracks-body"
              :style="{ width: `${Math.max((store.totalDurationSec || 120) * store.zoomLevel + 200, 1000)}px` }"
            >
              <div v-for="track in store.sortedTracks" :key="track.track_id" class="track-row">
                <!-- Clips -->
                <div
                  v-for="c in store.clipsForTrack(track.track_id)"
                  :key="c.clip_id"
                  class="clip-block"
                  :class="{ 'clip-selected': store.selectedClipId === c.clip_id }"
                  :style="{
                    left: `${c.start * store.zoomLevel}px`,
                    width: `${Math.max((c.end - c.start) * store.zoomLevel - 2, 4)}px`,
                    backgroundColor: clipColor(c),
                  }"
                  @click.stop="store.selectClip(c.clip_id)"
                >
                  <span class="clip-label">{{ c.meta?.title || c.meta?.text || c.clip_id }}</span>
                </div>
              </div>
            </div>

            <!-- Playhead -->
            <div
              class="playhead"
              :style="{ left: `${store.currentTime * store.zoomLevel}px` }"
              @mousedown.stop="startDragPlayhead"
            >
              <div class="playhead-diamond"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── RIGHT: CLIP PROPERTY PANEL ───────────────────────────────────── -->
      <div class="nle-prop-panel">
        <div class="prop-title">属性面板</div>

        <div v-if="clip" class="prop-content">
          <!-- Clip ID + kind -->
          <div class="prop-section">
            <div class="prop-label">Clip ID</div>
            <code class="prop-val-code">{{ clip.clip_id.slice(0, 16) }}</code>
            <div class="prop-badge" :style="{ backgroundColor: clipColor(clip) }">{{ clip.kind }}</div>
          </div>

          <!-- Shot info -->
          <div v-if="clip.meta?.shot_id" class="prop-section">
            <div class="prop-label">Shot ID</div>
            <code class="prop-val-code">{{ clip.meta.shot_id }}</code>
          </div>
          <div v-if="clip.meta?.prompt" class="prop-section">
            <div class="prop-label">Prompt</div>
            <div class="prop-prompt-text">{{ clip.meta.prompt }}</div>
          </div>
          <div v-if="clip.meta?.text" class="prop-section">
            <div class="prop-label">Dialogue</div>
            <div class="prop-prompt-text">{{ clip.meta.text }}</div>
          </div>

          <!-- Timing -->
          <div class="prop-section prop-row">
            <div>
              <div class="prop-label">Start (s)</div>
              <n-input-number
                :value="clip.start"
                size="small"
                :min="0"
                :precision="2"
                @update:value="v => store.updateClip(clip!.clip_id, { start: v ?? 0 })"
              />
            </div>
            <div>
              <div class="prop-label">End (s)</div>
              <n-input-number
                :value="clip.end"
                size="small"
                :min="clip.start + 0.01"
                :precision="2"
                @update:value="v => store.updateClip(clip!.clip_id, { end: v ?? clip!.start + 1 })"
              />
            </div>
          </div>

          <!-- Speed -->
          <div class="prop-section">
            <div class="prop-label">Speed ({{ clip.speed.toFixed(2) }}x)</div>
            <n-slider
              :value="clip.speed"
              :min="0.5"
              :max="2.0"
              :step="0.05"
              :on-update:value="updateSpeed"
            />
          </div>

          <!-- Volume -->
          <div v-if="clip.kind === 'audio'" class="prop-section">
            <div class="prop-label">Volume ({{ (clip.volume * 100).toFixed(0) }}%)</div>
            <n-slider
              :value="clip.volume"
              :min="0"
              :max="1"
              :step="0.05"
              :on-update:value="updateVolume"
            />
          </div>

          <!-- Fade In/Out -->
          <div v-if="clip.kind === 'audio'" class="prop-section prop-row">
            <div>
              <div class="prop-label">Fade In (s)</div>
              <n-input-number
                :value="clip.fade_in"
                size="small"
                :min="0"
                :precision="1"
                :step="0.1"
                @update:value="v => updateFadeIn(v ?? 0)"
              />
            </div>
            <div>
              <div class="prop-label">Fade Out (s)</div>
              <n-input-number
                :value="clip.fade_out"
                size="small"
                :min="0"
                :precision="1"
                :step="0.1"
                @update:value="v => updateFadeOut(v ?? 0)"
              />
            </div>
          </div>

          <!-- Actions -->
          <div class="prop-actions">
            <n-button size="small" @click="handleSplitClip">✂️ Split at Playhead</n-button>
          </div>

          <!-- Regenerate Shot (only for video clips with shot_id) -->
          <div v-if="clip.kind === 'video' && clip.meta?.shot_id" class="prop-regen-section">
            <div class="prop-section-title">🔄 重新生成镜头</div>
            <n-input
              v-model:value="regenPrompt"
              type="textarea"
              placeholder="Prompt patch for this shot..."
              :autosize="{ minRows: 3 }"
              class="regen-prompt-input"
            />
            <n-button
              type="primary"
              class="regen-btn"
              :loading="isRegenerating"
              @click="handleRegenerate"
            >
              🚀 Regenerate AI Shot
            </n-button>
          </div>
        </div>

        <!-- Empty state -->
        <div v-else class="prop-empty">
          <div class="prop-empty-icon">🎛️</div>
          <p>在时间轴上点击一个 Clip 即可编辑其属性</p>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
/* ── Root Layout ──────────────────────────────────────────────────────────── */
.nle-root {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 64px);
  background-color: #0a0e1a;
  color: #e2e8f0;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
  overflow: hidden;
}

/* ── Top Toolbar ──────────────────────────────────────────────────────────── */
.nle-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 20px;
  height: 52px;
  flex-shrink: 0;
  background: linear-gradient(90deg, #0f172a 0%, #1e293b 100%);
  border-bottom: 1px solid #334155;
  box-shadow: 0 2px 12px rgba(0,0,0,0.4);
}

.toolbar-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.brand-icon { font-size: 1.25rem; }
.brand-label {
  font-weight: 700;
  font-size: 0.95rem;
  color: #38bdf8;
  letter-spacing: 0.5px;
}

.toolbar-run-loader {
  display: flex;
  gap: 8px;
  align-items: center;
}

.run-id-input {
  width: 200px;
}

.toolbar-meta {
  display: flex;
  gap: 8px;
  flex: 1;
}

.meta-chip {
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 0.75rem;
  color: #94a3b8;
  white-space: nowrap;
}

.toolbar-zoom {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.zoom-val {
  font-size: 0.75rem;
  color: #64748b;
  min-width: 60px;
  text-align: center;
}

.nle-alert {
  margin: 8px 16px;
}

/* ── Main Body ────────────────────────────────────────────────────────────── */
.nle-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── Left Asset Sidebar ───────────────────────────────────────────────────── */
.nle-sidebar {
  width: 200px;
  flex-shrink: 0;
  background-color: #0f172a;
  border-right: 1px solid #1e293b;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 8px 0;
}

.sidebar-section-title {
  font-size: 0.7rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 1px;
  padding: 8px 12px 4px;
}

.sidebar-group {
  margin-bottom: 8px;
}

.sidebar-group-label {
  font-size: 0.72rem;
  color: #38bdf8;
  padding: 4px 12px;
  font-weight: 500;
}

.sidebar-item {
  padding: 5px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  cursor: pointer;
  transition: background 0.15s;
}

.sidebar-item:hover {
  background: rgba(59,130,246,0.1);
}

.sidebar-item-title {
  font-size: 0.78rem;
  color: #cbd5e1;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-item-sub {
  font-size: 0.68rem;
  color: #64748b;
  margin-top: 1px;
}

.sidebar-empty {
  padding: 24px 12px;
  color: #475569;
  font-size: 0.8rem;
  text-align: center;
  line-height: 1.6;
}

.sidebar-spin {
  margin: 16px auto;
}

/* ── Timeline Area ────────────────────────────────────────────────────────── */
.nle-timeline-area {
  flex: 1;
  display: flex;
  overflow: hidden;
  position: relative;
}

.timeline-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: #475569;
}

.timeline-spin {
  margin: auto;
}

.timeline-scroll-area {
  flex: 1;
  display: flex;
  overflow: auto;
  position: relative;
  background-color: #0d1117;
}

/* Track Headers (sticky-ish) */
.track-headers {
  position: sticky;
  left: 0;
  z-index: 20;
  flex-shrink: 0;
  width: 140px;
  background: #0f172a;
  border-right: 1px solid #1e3354;
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 8px rgba(0,0,0,0.3);
}

.ruler-header-stub {
  height: 36px;
  background: #080c14;
  border-bottom: 1px solid #1e293b;
}

.track-header {
  height: 72px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border-bottom: 1px solid #1e293b;
  font-size: 0.78rem;
  font-weight: 500;
  color: #94a3b8;
  transition: background 0.15s;
}

.track-header:hover {
  background: rgba(255,255,255,0.03);
}

.track-icon { font-size: 1rem; }
.track-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Scrollable Track Content */
.track-content-wrapper {
  position: relative;
  overflow: visible;
}

/* Time Ruler */
.time-ruler {
  position: relative;
  height: 36px;
  background: #080c14;
  border-bottom: 1px solid #1e293b;
  overflow: hidden;
}

.ruler-tick {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(255,255,255,0.06);
}

.major-tick {
  background: rgba(255,255,255,0.15);
}

.tick-label {
  position: absolute;
  top: 4px;
  left: 4px;
  font-size: 0.65rem;
  color: #64748b;
  white-space: nowrap;
  pointer-events: none;
}

/* Track rows + clips */
.tracks-body {
  position: relative;
}

.track-row {
  height: 72px;
  position: relative;
  border-bottom: 1px solid #1a2332;
  background-color: rgba(15, 23, 42, 0.6);
  background-image: linear-gradient(to right, rgba(255,255,255,0.015) 1px, transparent 1px);
  background-size: 50px 100%;
}

.track-row:hover {
  background-color: rgba(30, 41, 59, 0.6);
}

/* Clip Blocks */
.clip-block {
  position: absolute;
  top: 6px;
  height: calc(100% - 12px);
  border-radius: 4px;
  cursor: pointer;
  overflow: hidden;
  opacity: 0.85;
  border: 2px solid transparent;
  transition: opacity 0.15s, border-color 0.15s, transform 0.1s;
  box-sizing: border-box;
  min-width: 4px;
}

.clip-block:hover {
  opacity: 1;
  transform: scaleY(1.02);
}

.clip-selected {
  border-color: #fbbf24 !important;
  opacity: 1;
  box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.25);
}

.clip-label {
  display: block;
  padding: 4px 6px;
  font-size: 0.7rem;
  color: rgba(255,255,255,0.9);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 500;
  text-shadow: 0 1px 2px rgba(0,0,0,0.5);
}

/* Playhead */
.playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background-color: #f43f5e;
  z-index: 25;
  cursor: ew-resize;
  box-shadow: 0 0 6px rgba(244, 63, 94, 0.6);
  pointer-events: all;
}

.playhead-diamond {
  position: absolute;
  top: -1px;
  left: -7px;
  width: 16px;
  height: 16px;
  background: #f43f5e;
  clip-path: polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%);
  box-shadow: 0 0 8px rgba(244, 63, 94, 0.8);
}

/* ── Right Property Panel ──────────────────────────────────────────────── */
.nle-prop-panel {
  width: 260px;
  flex-shrink: 0;
  background: #0f172a;
  border-left: 1px solid #1e293b;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.prop-title {
  padding: 14px 16px 8px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 1px;
  border-bottom: 1px solid #1e293b;
  flex-shrink: 0;
}

.prop-content {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.prop-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.prop-section.prop-row {
  flex-direction: row;
  gap: 12px;
}

.prop-section.prop-row > div {
  flex: 1;
}

.prop-label {
  font-size: 0.7rem;
  color: #64748b;
  font-weight: 500;
  margin-bottom: 2px;
}

.prop-val-code {
  font-family: monospace;
  font-size: 0.72rem;
  color: #38bdf8;
  background: rgba(56,189,248,0.08);
  border-radius: 3px;
  padding: 2px 4px;
}

.prop-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 600;
  color: white;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  width: fit-content;
}

.prop-prompt-text {
  font-size: 0.75rem;
  color: #94a3b8;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 4px;
  padding: 6px 8px;
  line-height: 1.5;
  max-height: 80px;
  overflow-y: auto;
}

.prop-section-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: #38bdf8;
  padding-top: 4px;
  border-top: 1px solid rgba(255,255,255,0.06);
  margin-top: 4px;
}

.prop-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.prop-regen-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.regen-prompt-input {
  font-size: 0.78rem;
}

.regen-btn {
  width: 100%;
}

.prop-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex: 1;
  color: #475569;
  padding: 32px 16px;
  text-align: center;
}

.prop-empty-icon {
  font-size: 2rem;
  opacity: 0.4;
}

/* ── Naive UI overrides ───────────────────────────────────────────────── */
:deep(.n-input .n-input__input-el),
:deep(.n-input .n-input__textarea-el) {
  color: #e2e8f0 !important;
  background-color: #111827 !important;
}

:deep(.n-input.n-input--focus) {
  border-color: #3b82f6 !important;
}

:deep(.n-slider .n-slider-rail) {
  background: #1e293b;
}

:deep(.n-slider .n-slider-fill) {
  background: #3b82f6;
}

:deep(.n-slider .n-slider-handle) {
  background: #60a5fa;
  border-color: #60a5fa;
}
</style>
