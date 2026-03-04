import {
  createChapterTask,
  getRunDetail,
  getRunTimeline,
  getScript,
  initRunTracks,
  listChapters,
  listNovels,
  listPersonaPacks,
  listRunTrackUnits,
  listRunTracks,
  listTrackUnitAttempts,
  listTranslationProjects,
  retryTrackUnit,
  runTrack,
  selectTrackUnitCandidate,
  type ChapterResponse,
  type InitTracksResponse,
  type NovelResponse,
  type PersonaPackResponse,
  type RunDetailResponse,
  type RunTrackResponse,
  type TaskSubmitAccepted,
  type TimelinePlan,
  type TrackUnitAttemptResponse,
  type TrackSummary,
  type TrackUnitItem,
  type TranslationProjectResponse,
} from "@/api/product";

import type { ProductionTrackType } from "@/types/production";

export const PRODUCTION_TRACK_OPTIONS: Array<{ label: string; value: ProductionTrackType }> = [
  { label: "Video", value: "video" },
  { label: "LipSync", value: "lipsync" },
  { label: "Dialogue TTS", value: "dialogue" },
  { label: "Narration TTS", value: "narration" },
  { label: "TTS", value: "tts" },
  { label: "SFX", value: "sfx" },
  { label: "Ambience", value: "ambience" },
  { label: "AUX", value: "aux" },
  { label: "BGM", value: "bgm" },
  { label: "Subtitle", value: "subtitle" },
  { label: "Storyboard", value: "storyboard" },
];

export async function loadNovels(tenantId: string, projectId: string): Promise<NovelResponse[]> {
  return listNovels(tenantId, projectId);
}

export async function loadChapters(novelId: string): Promise<ChapterResponse[]> {
  return listChapters(novelId);
}

export async function loadTranslationProjects(params: {
  tenant_id: string;
  project_id: string;
  novel_id?: string;
}): Promise<TranslationProjectResponse[]> {
  return listTranslationProjects(params);
}

export async function loadPersonaPacks(tenantId: string, projectId: string): Promise<PersonaPackResponse[]> {
  return listPersonaPacks({ tenant_id: tenantId, project_id: projectId });
}

export async function createProductionRun(payload: {
  chapterId: string;
  tenantId: string;
  projectId: string;
  quality: string;
  languageContext: string;
  culturePackId?: string;
  personaRef?: string;
  selectedTracks: ProductionTrackType[];
}): Promise<TaskSubmitAccepted> {
  return createChapterTask(payload.chapterId, {
    tenant_id: payload.tenantId,
    project_id: payload.projectId,
    requested_quality: payload.quality,
    language_context: payload.languageContext,
    payload: {
      track_mode: true,
      source_language: payload.languageContext,
      target_language: payload.languageContext,
      culture_pack_id: payload.culturePackId || undefined,
      persona_ref: payload.personaRef || undefined,
      tracks: payload.selectedTracks,
    },
  });
}

export async function initProductionTracks(runId: string, trackTypes: ProductionTrackType[], recreate = false): Promise<InitTracksResponse> {
  return initRunTracks(runId, { track_types: trackTypes, recreate });
}

export async function loadTrackSummaries(runId: string): Promise<TrackSummary[]> {
  return listRunTracks(runId);
}

export async function loadTrackUnits(runId: string, trackType: ProductionTrackType): Promise<TrackUnitItem[]> {
  return listRunTrackUnits(runId, trackType);
}

export async function runTrackBatch(
  runId: string,
  trackType: ProductionTrackType,
  payload: { unit_ids?: string[]; only_failed?: boolean; force?: boolean } = {},
): Promise<RunTrackResponse> {
  return runTrack(runId, trackType, payload);
}

export async function retryTrackUnitWithPatch(
  runId: string,
  unitId: string,
  patch: Record<string, unknown> = {},
): Promise<{ status: string }> {
  const result = await retryTrackUnit(runId, unitId, { patch });
  return { status: result.status };
}

export async function selectUnitCandidate(runId: string, unitId: string, artifactId: string): Promise<{ status: string }> {
  const result = await selectTrackUnitCandidate(runId, unitId, { artifact_id: artifactId });
  return { status: result.status };
}

export async function loadUnitAttempts(runId: string, unitId: string): Promise<TrackUnitAttemptResponse[]> {
  return listTrackUnitAttempts(runId, unitId);
}

export async function loadRunMeta(runId: string): Promise<RunDetailResponse> {
  return getRunDetail(runId);
}

export async function tryLoadTimeline(runId: string): Promise<TimelinePlan | null> {
  try {
    return await getRunTimeline(runId);
  } catch {
    return null;
  }
}

export async function loadScriptVersion(chapterId: string): Promise<number> {
  try {
    const script = await getScript(chapterId);
    return script.version ?? 0;
  } catch {
    return 0;
  }
}
