import type {
  ChapterResponse,
  NovelResponse,
  PersonaPackResponse,
  TrackSummary,
  TrackUnitItem,
  TranslationProjectResponse,
} from "@/api/product";

export type ProductionTrackType =
  | "video"
  | "storyboard"
  | "tts"
  | "dialogue"
  | "narration"
  | "sfx"
  | "ambience"
  | "aux"
  | "bgm"
  | "subtitle"
  | "lipsync";

export type ProductionCapabilityType =
  | "llm_structured"
  | "storyboard_t2i"
  | "video_t2v"
  | "video_i2v"
  | "lipsync"
  | "tts"
  | "dialogue_tts"
  | "narration_tts"
  | "sfx"
  | "ambience"
  | "aux"
  | "bgm"
  | "subtitle";

export interface SelectOption {
  label: string;
  value: string;
}

export interface ProductionContextState {
  tenantId: string;
  projectId: string;
  novelId: string;
  chapterId: string;
  scriptVersion: string;
  planVersion: string;
  personaPackId: string;
  quality: string;
  languageContext: string;
  culturePackId: string;
  selectedTracks: ProductionTrackType[];
}

export interface ProductionContextOptions {
  novels: NovelResponse[];
  chapters: ChapterResponse[];
  translationProjects: TranslationProjectResponse[];
  personaPacks: PersonaPackResponse[];
  scriptVersions: SelectOption[];
  planVersions: SelectOption[];
}

export interface ProductionTimelineBlock {
  unitId: string;
  trackType: ProductionTrackType;
  label: string;
  startMs: number;
  endMs: number;
  status: string;
}

export interface ProductionRunSnapshot {
  runId: string;
  status: string;
  stage: string;
  progress: number;
}

export interface ProductionTrackState {
  summaries: TrackSummary[];
  unitsByTrack: Record<string, TrackUnitItem[]>;
}

export interface RetryPatchPayload {
  capability_type?: ProductionCapabilityType | string;
  text_override?: string;
  prompt_patch?: string;
  negative_prompt_patch?: string;
  voice_id?: string;
  style?: string;
  emotion?: string;
  speaking_rate?: number;
  pitch_shift?: number;
  tts_model?: string;
  output_format?: string;
  seed?: number;
  temperature?: number;
  duration_hint_ms?: number;
  duration_ms?: number;
  duration_s?: number;
  start_ms?: number;
  event?: string;
  description?: string;
  category?: string;
  intensity?: number;
  mood?: string;
  genre?: string;
  bpm?: number;
  musical_key?: string;
  custom_prompt?: string;
  camera_motion?: string;
  cfg_scale?: number;
  steps?: number;
  motion_strength?: number;
  fps?: number;
  alignment_mode?: string;
  face_region?: string;
  backend?: string;
  style_preset?: string;
  line_break_mode?: string;
  max_chars_per_line?: number;
  face_detect?: boolean;
  loop?: boolean;
  bilingual?: boolean;
  pads?: string | number[];
  [key: string]: string | number | boolean | number[] | Record<string, unknown> | unknown[] | undefined;
}
