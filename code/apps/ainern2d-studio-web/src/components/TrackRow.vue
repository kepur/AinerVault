<script setup lang="ts">
import { useNleTimelineStore, type Clip } from '@/stores/useNleTimelineStore'

const props = defineProps<{
  track: { id: string, name: string, type: string }
  clips: Clip[]
}>()

const store = useNleTimelineStore()

const selectClip = (clip: Clip) => {
  store.selectedClipId = clip.id
}
</script>

<template>
  <div class="track-row">
      <!-- 每个轨道上的独立剪辑块 -->
      <div 
        v-for="clip in clips" 
        :key="clip.id"
        class="track-clip"
        :class="store.selectedClipId === clip.id ? 'clip-selected' : ''"
        :style="{
          left: `${clip.start * store.zoomLevel}px`,
          width: `${clip.duration * store.zoomLevel}px`
        }"
        @click.stop="selectClip(clip)"
      >
        <!-- 内容预览: 波形/文字/缩略图 -->
        <div class="clip-content">
          {{ clip.content?.title || 'Unnamed Clip' }}
        </div>
      </div>
  </div>
</template>

<style scoped>
.track-row {
  height: 80px;
  border-bottom: 1px solid #374151; /* gray-700 */
  position: relative;
  width: 100%;
  background-color: rgba(31, 41, 55, 0.5); /* gray-800/50 */
}

.track-clip {
  position: absolute;
  top: 8px;
  bottom: 8px;
  background-color: rgba(37, 99, 235, 0.8); /* blue-600/80 */
  border-radius: 4px;
  cursor: pointer;
  overflow: hidden;
  border: 2px solid transparent;
  transition: background-color 0.2s, border-color 0.2s, box-shadow 0.2s;
}

.track-clip:hover {
  background-color: rgba(59, 130, 246, 1); /* blue-500 */
}

.clip-selected {
  border-color: #facc15; /* yellow-400 */
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05); /* shadow-lg */
  z-index: 10;
}

.clip-content {
  padding: 4px 8px;
  font-size: 12px;
  color: white;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
