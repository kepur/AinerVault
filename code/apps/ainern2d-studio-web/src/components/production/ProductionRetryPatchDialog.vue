<template>
  <NModal :show="show" preset="dialog" title="Retry With Patch" style="width: min(920px, 94vw)" @update:show="(v) => emit('update:show', v)">
    <NSpace vertical :size="10">
      <NAlert type="info" :bordered="false">{{ trackGuide }}</NAlert>
      <NSpace align="center" :wrap-item="true">
        <NText depth="3">Capability</NText>
        <NSelect
          :value="selectedCapability || null"
          :options="capabilityOptions"
          clearable
          style="min-width: 240px"
          placeholder="Auto"
          @update:value="onCapabilityChange"
        />
      </NSpace>
      <NAlert v-if="adapterSpecHint" type="default" :bordered="false">
        {{ adapterSpecHint }}
      </NAlert>
      <NAlert v-if="adapterSpecError" type="warning" :bordered="false">
        {{ adapterSpecError }}
      </NAlert>
      <NForm label-placement="top">
        <NGrid :cols="2" :x-gap="12" :y-gap="2" responsive="screen" item-responsive>
          <NGridItem v-for="field in fields" :key="field.key" :span="field.span === 2 ? '0:2' : '0:2 920:1'">
            <NFormItem :label="field.label">
              <NInput
                v-if="field.type === 'text'"
                :value="stringValue(field.key)"
                :placeholder="field.placeholder"
                @update:value="(v) => updateField(field.key, v)"
              />
              <NInput
                v-else-if="field.type === 'textarea'"
                :value="stringValue(field.key)"
                type="textarea"
                :placeholder="field.placeholder"
                :autosize="{ minRows: 2, maxRows: 5 }"
                @update:value="(v) => updateField(field.key, v)"
              />
              <NInputNumber
                v-else-if="field.type === 'number'"
                :value="numberValue(field.key)"
                :min="field.min"
                :max="field.max"
                :step="field.step ?? 1"
                :precision="field.precision"
                @update:value="(v) => updateField(field.key, v ?? undefined)"
              />
              <NSelect
                v-else-if="field.type === 'select'"
                :value="selectValue(field.key)"
                :options="field.options || []"
                filterable
                clearable
                :placeholder="field.placeholder"
                @update:value="(v) => updateField(field.key, (v || undefined) as string | undefined)"
              />
              <NSelect
                v-else
                :value="booleanSelectValue(field.key)"
                :options="BOOLEAN_OPTIONS"
                :placeholder="field.placeholder || 'Inherit default'"
                @update:value="(v) => updateField(field.key, parseBooleanOption(v))"
              />
              <NText v-if="field.help" depth="3" class="field-help">{{ field.help }}</NText>
            </NFormItem>
          </NGridItem>
        </NGrid>
      </NForm>
    </NSpace>
    <template #action>
      <NSpace>
        <NButton @click="emit('update:show', false)">Cancel</NButton>
        <NButton type="default" @click="onReset">Reset</NButton>
        <NButton type="primary" @click="onConfirm">Retry</NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import {
  NAlert,
  NButton,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSpace,
  NText,
} from "naive-ui";
import { getOpsAdapterSpec, type AdapterSpecResponse } from "@/api/product";
import type { ProductionCapabilityType, ProductionTrackType, RetryPatchPayload } from "@/types/production";
import type { SelectOption } from "naive-ui";

type DynamicFieldType = "text" | "textarea" | "number" | "select" | "boolean";

interface DynamicFieldConfig {
  key: string;
  label: string;
  type: DynamicFieldType;
  placeholder?: string;
  help?: string;
  span?: 1 | 2;
  min?: number;
  max?: number;
  step?: number;
  precision?: number;
  options?: SelectOption[];
  source?: "base" | "adapter";
  jsonLike?: boolean;
}

const BOOLEAN_OPTIONS: SelectOption[] = [
  { label: "Inherit default", value: "inherit" },
  { label: "Enabled", value: "true" },
  { label: "Disabled", value: "false" },
];

type AdapterSpecItem = {
  request_required?: string[];
  response_required?: string[];
  response_optional?: string[];
};

const TRACK_TO_CAPABILITIES: Record<ProductionTrackType, ProductionCapabilityType[]> = {
  storyboard: ["storyboard_t2i"],
  video: ["video_t2v", "video_i2v"],
  lipsync: ["lipsync"],
  tts: ["tts"],
  dialogue: ["dialogue_tts"],
  narration: ["narration_tts"],
  sfx: ["sfx"],
  ambience: ["ambience"],
  aux: ["aux"],
  bgm: ["bgm"],
  subtitle: ["subtitle"],
};

const CAPABILITY_LABELS: Record<string, string> = {
  llm_structured: "LLM Structured",
  storyboard_t2i: "Storyboard T2I",
  video_t2v: "Video T2V",
  video_i2v: "Video I2V",
  lipsync: "LipSync",
  tts: "TTS",
  dialogue_tts: "Dialogue TTS",
  narration_tts: "Narration TTS",
  sfx: "SFX",
  ambience: "Ambience",
  aux: "AUX",
  bgm: "BGM",
  subtitle: "Subtitle",
};

const ADAPTER_EXCLUDED_KEYS = new Set([
  "task_id",
  "audio_url",
  "video_url",
  "image_url",
  "output_json",
  "usage",
  "provider_id",
  "model_version",
]);

let ADAPTER_SPEC_CACHE: Record<string, AdapterSpecItem> | null = null;

const TRACK_GUIDE: Record<ProductionTrackType, string> = {
  video: "Video retry accepts cinematic prompt tweaks and generation controls (seed/cfg/steps/fps).",
  storyboard: "Storyboard retry focuses on prompt/style patching for static frame quality.",
  tts: "TTS retry supports voice, tone and text overrides. Use this for per-line correction.",
  dialogue: "Dialogue retry is tuned for character lines: emotion, speaking rate and voice selection.",
  narration: "Narration retry is tuned for narrator style and pacing consistency.",
  sfx: "SFX retry supports event description, category and timing (start/duration).",
  ambience: "Ambience retry supports environment bed parameters and loop control.",
  aux: "AUX retry supports auxiliary texture layer generation and loop control.",
  bgm: "BGM retry supports mood/genre/BPM and custom music prompt patch.",
  subtitle: "Subtitle retry supports text rewrite and line-breaking strategy.",
  lipsync: "LipSync retry supports alignment, face detect and backend selection. Pads supports comma values like 0,10,0,0.",
};

const TRACK_FIELDS: Record<ProductionTrackType, DynamicFieldConfig[]> = {
  video: [
    { key: "prompt_patch", label: "Prompt Patch", type: "textarea", span: 2, placeholder: "Add camera/style adjustments" },
    {
      key: "negative_prompt_patch",
      label: "Negative Prompt",
      type: "textarea",
      span: 2,
      placeholder: "Artifacts to avoid",
    },
    {
      key: "style_preset",
      label: "Style Preset",
      type: "select",
      placeholder: "cinematic",
      options: [
        { label: "Cinematic", value: "cinematic" },
        { label: "Anime", value: "anime" },
        { label: "Realistic", value: "realistic" },
        { label: "Storyboard", value: "storyboard" },
      ],
    },
    {
      key: "camera_motion",
      label: "Camera Motion",
      type: "select",
      options: [
        { label: "Static", value: "static" },
        { label: "Pan", value: "pan" },
        { label: "Push In", value: "push_in" },
        { label: "Handheld", value: "handheld" },
      ],
    },
    { key: "cfg_scale", label: "CFG Scale", type: "number", min: 1, max: 30, step: 0.5, precision: 2 },
    { key: "steps", label: "Steps", type: "number", min: 1, max: 200, step: 1 },
    { key: "motion_strength", label: "Motion Strength", type: "number", min: 0, max: 1, step: 0.05, precision: 2 },
    { key: "fps", label: "FPS", type: "number", min: 1, max: 120, step: 1 },
    { key: "seed", label: "Seed", type: "number", min: 0, step: 1 },
    { key: "temperature", label: "Temperature", type: "number", min: 0, max: 2, step: 0.1, precision: 2 },
  ],
  storyboard: [
    { key: "prompt_patch", label: "Prompt Patch", type: "textarea", span: 2 },
    { key: "negative_prompt_patch", label: "Negative Prompt", type: "textarea", span: 2 },
    {
      key: "style_preset",
      label: "Visual Style",
      type: "select",
      options: [
        { label: "Sketch", value: "sketch" },
        { label: "Cinematic", value: "cinematic" },
        { label: "Manga", value: "manga" },
      ],
    },
    { key: "cfg_scale", label: "CFG Scale", type: "number", min: 1, max: 30, step: 0.5, precision: 2 },
    { key: "steps", label: "Steps", type: "number", min: 1, max: 120, step: 1 },
    { key: "seed", label: "Seed", type: "number", min: 0, step: 1 },
  ],
  tts: [
    { key: "text_override", label: "Text Override", type: "textarea", span: 2, placeholder: "Override this line text" },
    { key: "voice_id", label: "Voice ID", type: "text", placeholder: "narrator" },
    { key: "style", label: "Style", type: "text", placeholder: "calm" },
    { key: "emotion", label: "Emotion", type: "text", placeholder: "serious" },
    { key: "speaking_rate", label: "Speaking Rate", type: "number", min: 0.5, max: 2, step: 0.05, precision: 2 },
    { key: "pitch_shift", label: "Pitch Shift", type: "number", min: -12, max: 12, step: 0.1, precision: 2 },
    { key: "tts_model", label: "TTS Model", type: "text", placeholder: "provider/model" },
    {
      key: "output_format",
      label: "Output Format",
      type: "select",
      options: [
        { label: "WAV", value: "wav" },
        { label: "MP3", value: "mp3" },
        { label: "FLAC", value: "flac" },
      ],
    },
    { key: "seed", label: "Seed", type: "number", min: 0, step: 1 },
    { key: "temperature", label: "Temperature", type: "number", min: 0, max: 2, step: 0.1, precision: 2 },
  ],
  dialogue: [
    { key: "text_override", label: "Dialogue Override", type: "textarea", span: 2 },
    { key: "voice_id", label: "Voice ID", type: "text", placeholder: "hero_male_01" },
    { key: "style", label: "Delivery Style", type: "text", placeholder: "urgent" },
    { key: "emotion", label: "Emotion", type: "text", placeholder: "angry" },
    { key: "speaking_rate", label: "Speaking Rate", type: "number", min: 0.5, max: 2, step: 0.05, precision: 2 },
    { key: "pitch_shift", label: "Pitch Shift", type: "number", min: -12, max: 12, step: 0.1, precision: 2 },
    { key: "seed", label: "Seed", type: "number", min: 0, step: 1 },
  ],
  narration: [
    { key: "text_override", label: "Narration Override", type: "textarea", span: 2 },
    { key: "voice_id", label: "Voice ID", type: "text", placeholder: "narrator_female_01" },
    { key: "style", label: "Narration Style", type: "text", placeholder: "warm" },
    { key: "speaking_rate", label: "Pacing", type: "number", min: 0.5, max: 2, step: 0.05, precision: 2 },
    { key: "pitch_shift", label: "Pitch Shift", type: "number", min: -12, max: 12, step: 0.1, precision: 2 },
    {
      key: "output_format",
      label: "Output Format",
      type: "select",
      options: [
        { label: "WAV", value: "wav" },
        { label: "MP3", value: "mp3" },
      ],
    },
    { key: "seed", label: "Seed", type: "number", min: 0, step: 1 },
  ],
  sfx: [
    { key: "description", label: "SFX Description", type: "textarea", span: 2, placeholder: "sword slash close-up" },
    {
      key: "category",
      label: "Category",
      type: "select",
      options: [
        { label: "Action", value: "action" },
        { label: "Foley", value: "foley" },
        { label: "UI", value: "ui" },
        { label: "Nature", value: "nature" },
      ],
    },
    { key: "intensity", label: "Intensity", type: "number", min: 0, max: 1, step: 0.05, precision: 2 },
    { key: "start_ms", label: "Start (ms)", type: "number", min: 0, step: 10 },
    { key: "duration_ms", label: "Duration (ms)", type: "number", min: 50, step: 10 },
  ],
  ambience: [
    { key: "description", label: "Ambience Description", type: "textarea", span: 2, placeholder: "night forest wind" },
    { key: "mood", label: "Mood", type: "text", placeholder: "tense" },
    { key: "start_ms", label: "Start (ms)", type: "number", min: 0, step: 10 },
    { key: "duration_ms", label: "Duration (ms)", type: "number", min: 100, step: 10 },
    { key: "loop", label: "Loop", type: "boolean" },
  ],
  aux: [
    { key: "description", label: "AUX Description", type: "textarea", span: 2, placeholder: "low drone texture layer" },
    { key: "mood", label: "Mood", type: "text", placeholder: "mysterious" },
    { key: "start_ms", label: "Start (ms)", type: "number", min: 0, step: 10 },
    { key: "duration_ms", label: "Duration (ms)", type: "number", min: 100, step: 10 },
    { key: "loop", label: "Loop", type: "boolean" },
  ],
  bgm: [
    { key: "custom_prompt", label: "Music Prompt", type: "textarea", span: 2, placeholder: "dark orchestral tension" },
    { key: "mood", label: "Mood", type: "text", placeholder: "suspense" },
    { key: "genre", label: "Genre", type: "text", placeholder: "orchestral" },
    { key: "bpm", label: "BPM", type: "number", min: 40, max: 220, step: 1 },
    { key: "musical_key", label: "Key", type: "text", placeholder: "D minor" },
    { key: "duration_s", label: "Duration (s)", type: "number", min: 1, step: 1 },
    { key: "loop", label: "Loop", type: "boolean" },
  ],
  subtitle: [
    { key: "text_override", label: "Subtitle Override", type: "textarea", span: 2 },
    {
      key: "line_break_mode",
      label: "Line Break Mode",
      type: "select",
      options: [
        { label: "Smart", value: "smart" },
        { label: "Greedy", value: "greedy" },
        { label: "Fixed", value: "fixed" },
      ],
    },
    { key: "max_chars_per_line", label: "Max Chars/Line", type: "number", min: 8, max: 64, step: 1 },
    { key: "bilingual", label: "Bilingual", type: "boolean" },
    { key: "style", label: "Subtitle Style", type: "text", placeholder: "clean" },
  ],
  lipsync: [
    {
      key: "alignment_mode",
      label: "Alignment Mode",
      type: "select",
      options: [
        { label: "Auto", value: "auto" },
        { label: "Phoneme", value: "phoneme" },
        { label: "Viseme", value: "viseme" },
      ],
    },
    { key: "face_detect", label: "Face Detect", type: "boolean" },
    { key: "face_region", label: "Face Region", type: "text", placeholder: "x,y,w,h" },
    {
      key: "backend",
      label: "Backend",
      type: "select",
      options: [
        { label: "Auto", value: "auto" },
        { label: "Wav2Lip", value: "wav2lip" },
        { label: "SadTalker", value: "sadtalker" },
      ],
    },
    {
      key: "output_format",
      label: "Output Format",
      type: "select",
      options: [
        { label: "MP4", value: "mp4" },
        { label: "MOV", value: "mov" },
        { label: "WEBM", value: "webm" },
      ],
    },
    { key: "pads", label: "Pads", type: "text", placeholder: "0,10,0,0", help: "top,right,bottom,left" },
  ],
};

const props = withDefaults(
  defineProps<{
    show: boolean;
    trackType: ProductionTrackType;
    capabilityType?: string;
    initialPatch?: RetryPatchPayload;
  }>(),
  {
    trackType: "tts",
  },
);

const emit = defineEmits<{
  (event: "update:show", value: boolean): void;
  (event: "update:capabilityType", value: string): void;
  (event: "confirm", patch: RetryPatchPayload): void;
}>();

const state = reactive<Record<string, string | number | boolean | undefined>>({});
const adapterSpecMap = ref<Record<string, AdapterSpecItem>>({});
const adapterSpecError = ref("");
const selectedCapability = ref<string>("");

const capabilityOptions = computed<Array<{ label: string; value: string }>>(() => {
  const values = TRACK_TO_CAPABILITIES[props.trackType] || [];
  return values.map((value) => ({
    label: CAPABILITY_LABELS[value] || value,
    value,
  }));
});

const baseFields = computed<DynamicFieldConfig[]>(() => TRACK_FIELDS[props.trackType] || TRACK_FIELDS.tts);
const adapterFields = computed<DynamicFieldConfig[]>(() => {
  const capability = selectedCapability.value;
  if (!capability) {
    return [];
  }
  const spec = adapterSpecMap.value[capability];
  if (!spec || !Array.isArray(spec.request_required)) {
    return [];
  }
  const used = new Set(baseFields.value.map((field) => field.key));
  return spec.request_required
    .filter((key) => !ADAPTER_EXCLUDED_KEYS.has(key))
    .filter((key) => !used.has(key))
    .map((key) => inferDynamicField(key));
});

const fields = computed<DynamicFieldConfig[]>(() => [...baseFields.value, ...adapterFields.value]);
const trackGuide = computed(() => {
  const base = TRACK_GUIDE[props.trackType] || TRACK_GUIDE.tts;
  if (!selectedCapability.value) {
    return base;
  }
  return `${base} Current capability: ${selectedCapability.value}.`;
});
const adapterSpecHint = computed(() => {
  const capability = selectedCapability.value;
  if (!capability) return "";
  const spec = adapterSpecMap.value[capability];
  if (!spec || !spec.request_required?.length) return "";
  return `Adapter required request fields: ${spec.request_required.join(", ")}`;
});

function titleizeKey(key: string): string {
  return key
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function inferDynamicField(key: string): DynamicFieldConfig {
  const normalized = key.toLowerCase();
  const isBoolean =
    normalized.startsWith("is_") ||
    normalized.startsWith("has_") ||
    normalized.includes("enable") ||
    normalized.includes("enabled") ||
    normalized === "loop";
  const isNumber =
    /(duration|fps|bpm|rate|pitch|seed|steps|scale|strength|temperature|count|width|height|ms|timeout|score)/.test(
      normalized,
    );
  const isJsonLike =
    normalized.endsWith("_json") ||
    /(segments|dialogues|messages|schema|metadata|constraints|features|pads)/.test(normalized);
  const isLongText = /(prompt|description|script|text)/.test(normalized);
  const type: DynamicFieldType = isBoolean
    ? "boolean"
    : isNumber
      ? "number"
      : isJsonLike || isLongText
        ? "textarea"
        : "text";
  return {
    key,
    label: `${titleizeKey(key)} (Adapter)`,
    type,
    span: type === "textarea" ? 2 : 1,
    source: "adapter",
    jsonLike: isJsonLike,
    help: isJsonLike ? "Accepts JSON object/array. Raw text also supported." : "Derived from adapter request_required.",
  };
}

async function ensureAdapterSpecLoaded(): Promise<void> {
  if (ADAPTER_SPEC_CACHE) {
    adapterSpecMap.value = ADAPTER_SPEC_CACHE;
    adapterSpecError.value = "";
    return;
  }
  try {
    const response: AdapterSpecResponse = await getOpsAdapterSpec();
    ADAPTER_SPEC_CACHE = response.items || {};
    adapterSpecMap.value = ADAPTER_SPEC_CACHE;
    adapterSpecError.value = "";
  } catch (error) {
    adapterSpecError.value = `Adapter spec unavailable: ${error instanceof Error ? error.message : String(error)}`;
  }
}

function applyInitialState(): void {
  for (const key of Object.keys(state)) {
    delete state[key];
  }
  for (const field of fields.value) {
    const key = field.key;
    const sourceValue = props.initialPatch?.[key];
    if (sourceValue !== undefined) {
      if (Array.isArray(sourceValue)) {
        state[key] = sourceValue.join(",");
      } else {
        state[key] = sourceValue as string | number | boolean;
      }
      continue;
    }
    state[key] = undefined;
  }
}

watch(
  () => [props.trackType, props.initialPatch, props.show, props.capabilityType],
  () => {
    if (!props.show) {
      return;
    }
    void ensureAdapterSpecLoaded();
    const options = capabilityOptions.value;
    const fromPatch = typeof props.initialPatch?.capability_type === "string" ? props.initialPatch.capability_type : "";
    const preferred =
      props.capabilityType && options.some((item) => item.value === props.capabilityType)
        ? props.capabilityType
        : fromPatch && options.some((item) => item.value === fromPatch)
          ? fromPatch
        : options[0]?.value || "";
    selectedCapability.value = preferred;
    applyInitialState();
  },
  { immediate: true },
);

watch(
  () => selectedCapability.value,
  () => {
    for (const field of fields.value) {
      if (!(field.key in state)) {
        state[field.key] = undefined;
      }
    }
  },
);

function onCapabilityChange(value: string | number | null): void {
  selectedCapability.value = typeof value === "string" ? value : "";
  emit("update:capabilityType", selectedCapability.value);
}

function stringValue(key: string): string {
  const value = state[key];
  return typeof value === "string" ? value : "";
}

function numberValue(key: string): number | null {
  const value = state[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function selectValue(key: string): string | null {
  const value = state[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function booleanSelectValue(key: string): string {
  const value = state[key];
  if (value === true) return "true";
  if (value === false) return "false";
  return "inherit";
}

function parseBooleanOption(value: string | null): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

function updateField(key: string, value: string | number | boolean | undefined): void {
  state[key] = value;
}

function buildPatch(): RetryPatchPayload {
  const patch: RetryPatchPayload = {};
  for (const field of fields.value) {
    const raw = state[field.key];
    if (raw === undefined || raw === null) {
      continue;
    }
    if (typeof raw === "string") {
      const trimmed = raw.trim();
      if (!trimmed) {
        continue;
      }
      if (field.key === "pads") {
        const values = trimmed
          .split(/[\s,]+/)
          .map((item) => Number(item.trim()))
          .filter((item) => Number.isFinite(item));
        if (values.length > 0) {
          patch[field.key] = values;
        }
        continue;
      }
      if (field.jsonLike) {
        try {
          patch[field.key] = JSON.parse(trimmed) as RetryPatchPayload[string];
          continue;
        } catch {
          patch[field.key] = trimmed;
          continue;
        }
      }
      patch[field.key] = trimmed;
      continue;
    }
    patch[field.key] = raw;
  }
  if (selectedCapability.value) {
    patch.capability_type = selectedCapability.value;
  }
  return patch;
}

function onReset(): void {
  applyInitialState();
}

function onConfirm(): void {
  emit("confirm", buildPatch());
  emit("update:show", false);
}
</script>

<style scoped>
.field-help {
  display: block;
  margin-top: 4px;
}
</style>
