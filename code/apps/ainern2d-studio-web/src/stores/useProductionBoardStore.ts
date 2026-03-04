import { computed, reactive, ref } from "vue";
import { defineStore } from "pinia";

import {
  PRODUCTION_TRACK_OPTIONS,
  createProductionRun,
  initProductionTracks,
  loadChapters,
  loadNovels,
  loadPersonaPacks,
  loadRunMeta,
  loadScriptVersion,
  loadTrackSummaries,
  loadTrackUnits,
  loadUnitAttempts,
  loadTranslationProjects,
  retryTrackUnitWithPatch,
  runTrackBatch,
  selectUnitCandidate,
  tryLoadTimeline,
} from "@/api/production";
import type { RetryPatchPayload, ProductionTimelineBlock, ProductionTrackType } from "@/types/production";

function normalizeTrackType(trackType: string): ProductionTrackType | null {
  const allowed: ProductionTrackType[] = [
    "video",
    "storyboard",
    "lipsync",
    "tts",
    "dialogue",
    "narration",
    "sfx",
    "ambience",
    "aux",
    "bgm",
    "subtitle",
  ];
  return allowed.includes(trackType as ProductionTrackType) ? (trackType as ProductionTrackType) : null;
}

export const useProductionBoardStore = defineStore("productionBoard", () => {
  const context = reactive({
    tenantId: "default",
    projectId: "default",
    novelId: "",
    chapterId: "",
    scriptVersion: "original",
    planVersion: "plan:auto",
    personaPackId: "",
    quality: "standard",
    languageContext: "en-US",
    culturePackId: "cn_wuxia",
    selectedTracks: [
      "storyboard",
      "video",
      "lipsync",
      "tts",
      "dialogue",
      "narration",
      "sfx",
      "ambience",
      "aux",
      "bgm",
      "subtitle",
    ] as ProductionTrackType[],
  });

  const options = reactive({
    novels: [] as Array<{ id: string; title: string }>,
    chapters: [] as Array<{ id: string; chapter_no: number; title?: string | null; language_code: string }>,
    translationProjects: [] as Array<{ id: string; target_language_code: string; status: string }>,
    personaPacks: [] as Array<{ id: string; name: string }>,
    scriptVersions: [{ label: "Original", value: "original" }] as Array<{ label: string; value: string }>,
    planVersions: [{ label: "Auto Plan", value: "plan:auto" }] as Array<{ label: string; value: string }>,
  });

  const runId = ref("");
  const runMeta = ref({
    runId: "",
    status: "idle",
    stage: "ingest",
    progress: 0,
  });

  const activeTrack = ref<ProductionTrackType>("tts");
  const trackSummaries = ref<Array<{
    track_run_id: string;
    track_type: string;
    worker_type?: string | null;
    status: string;
    blocked_reason?: string | null;
    total_units: number;
    success_units: number;
    failed_units: number;
    running_units: number;
    blocked_units: number;
  }>>([]);
  const unitsByTrack = ref<Record<string, Array<{
    unit_id: string;
    unit_ref_id: string;
    unit_kind: string;
    status: string;
    planned_start_ms?: number | null;
    planned_end_ms?: number | null;
    attempt_count: number;
    max_attempts: number;
    blocked_reason?: string | null;
    last_error_code?: string | null;
    last_error_message?: string | null;
    selected_asset_id?: string | null;
    selected_job_id?: string | null;
    output_candidates?: Array<Record<string, unknown>>;
  }>>>({});
  const attemptsByUnit = ref<Record<string, Array<{
    attempt_id: string;
    attempt_no: number;
    trigger_type: string;
    status: string;
    job_id?: string | null;
    artifact_id?: string | null;
    error_code?: string | null;
    error_message?: string | null;
    duration_ms?: number | null;
    started_at?: string | null;
    finished_at?: string | null;
  }>>>({});

  const timelinePlanLoaded = ref(false);
  const isLoading = ref(false);
  const isRunning = ref(false);
  const message = ref("");
  const errorMessage = ref("");

  const qualityOptions = [
    { label: "draft", value: "draft" },
    { label: "standard", value: "standard" },
    { label: "high", value: "high" },
  ];

  const trackOptions = PRODUCTION_TRACK_OPTIONS;

  const novelSelectOptions = computed(() => options.novels.map((item) => ({ label: item.title, value: item.id })));
  const chapterSelectOptions = computed(() =>
    options.chapters.map((item) => ({ label: `#${item.chapter_no} ${item.title || item.id}`, value: item.id })),
  );
  const personaSelectOptions = computed(() => options.personaPacks.map((item) => ({ label: item.name, value: item.id })));
  const scriptVersionOptions = computed(() => options.scriptVersions);
  const planVersionOptions = computed(() => options.planVersions);

  const activeUnits = computed(() => unitsByTrack.value[activeTrack.value] ?? []);
  const timelineBlocks = computed<ProductionTimelineBlock[]>(() => {
    const out: ProductionTimelineBlock[] = [];
    for (const trackType of Object.keys(unitsByTrack.value)) {
      const normalized = normalizeTrackType(trackType);
      if (!normalized) continue;
      for (const unit of unitsByTrack.value[trackType] ?? []) {
        const start = Number(unit.planned_start_ms ?? 0);
        const end = Number(unit.planned_end_ms ?? start + 300);
        out.push({
          unitId: unit.unit_id,
          trackType: normalized,
          label: unit.unit_ref_id,
          startMs: start,
          endMs: Math.max(start + 100, end),
          status: unit.status,
        });
      }
    }
    return out.sort((a, b) => a.startMs - b.startMs);
  });

  const hasRunnableContext = computed(() => Boolean(context.novelId && context.chapterId));

  function clearNotice(): void {
    message.value = "";
    errorMessage.value = "";
  }

  async function bootstrap(): Promise<void> {
    clearNotice();
    isLoading.value = true;
    try {
      const [novels, personaPacks] = await Promise.all([
        loadNovels(context.tenantId, context.projectId),
        loadPersonaPacks(context.tenantId, context.projectId),
      ]);
      options.novels = novels.map((item) => ({ id: item.id, title: item.title }));
      options.personaPacks = personaPacks.map((item) => ({ id: item.id, name: item.name }));
      if (!context.novelId && options.novels.length > 0) {
        context.novelId = options.novels[0].id;
      }
      if (context.novelId) {
        await loadNovelContext(context.novelId);
      }
    } catch (error) {
      errorMessage.value = `load context failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isLoading.value = false;
    }
  }

  async function loadNovelContext(novelId: string): Promise<void> {
    clearNotice();
    context.novelId = novelId;
    isLoading.value = true;
    try {
      const [chapters, projects] = await Promise.all([
        loadChapters(novelId),
        loadTranslationProjects({ tenant_id: context.tenantId, project_id: context.projectId, novel_id: novelId }),
      ]);
      options.chapters = chapters.map((item) => ({
        id: item.id,
        chapter_no: item.chapter_no,
        title: item.title,
        language_code: item.language_code,
      }));
      options.translationProjects = projects.map((item) => ({
        id: item.id,
        target_language_code: item.target_language_code,
        status: item.status,
      }));
      if (!options.chapters.some((item) => item.id === context.chapterId)) {
        context.chapterId = options.chapters[0]?.id || "";
      }
      if (context.chapterId) {
        await loadChapterContext(context.chapterId);
      }
    } catch (error) {
      errorMessage.value = `load novel context failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isLoading.value = false;
    }
  }

  async function loadChapterContext(chapterId: string): Promise<void> {
    clearNotice();
    context.chapterId = chapterId;
    isLoading.value = true;
    try {
      const chapter = options.chapters.find((item) => item.id === chapterId);
      if (chapter?.language_code) {
        context.languageContext = chapter.language_code;
      }

      const scriptVersion = await loadScriptVersion(chapterId);
      options.scriptVersions = [
        { label: "Original", value: "original" },
        { label: `Script v${scriptVersion}`, value: `script:v${scriptVersion}` },
        ...options.translationProjects.map((item, index) => ({
          label: `Translation v${index + 1} (${item.target_language_code})`,
          value: `translation:${item.id}`,
        })),
      ];
      if (!options.scriptVersions.some((item) => item.value === context.scriptVersion)) {
        context.scriptVersion = options.scriptVersions[0]?.value || "original";
      }

      options.planVersions = [
        { label: "Auto Plan", value: "plan:auto" },
        { label: `Plan for ${context.scriptVersion}`, value: `plan:${context.scriptVersion}` },
      ];
      if (!options.planVersions.some((item) => item.value === context.planVersion)) {
        context.planVersion = options.planVersions[0]?.value || "plan:auto";
      }
    } catch (error) {
      errorMessage.value = `load chapter context failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isLoading.value = false;
    }
  }

  async function createRun(): Promise<void> {
    clearNotice();
    if (!context.chapterId) {
      errorMessage.value = "chapter is required";
      return;
    }
    isRunning.value = true;
    try {
      const accepted = await createProductionRun({
        chapterId: context.chapterId,
        tenantId: context.tenantId,
        projectId: context.projectId,
        quality: context.quality,
        languageContext: context.languageContext,
        culturePackId: context.culturePackId,
        personaRef: context.personaPackId || undefined,
        selectedTracks: context.selectedTracks,
      });
      runId.value = accepted.run_id;
      runMeta.value.runId = accepted.run_id;
      message.value = `run created: ${accepted.run_id}`;
      await refreshRunMeta();
    } catch (error) {
      errorMessage.value = `create run failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isRunning.value = false;
    }
  }

  async function refreshRunMeta(): Promise<void> {
    if (!runId.value) return;
    try {
      const detail = await loadRunMeta(runId.value);
      runMeta.value = {
        runId: detail.run_id,
        status: detail.status,
        stage: detail.stage,
        progress: Number(detail.progress || 0),
      };
    } catch (error) {
      errorMessage.value = `load run meta failed: ${error instanceof Error ? error.message : String(error)}`;
    }
  }

  async function initTracks(recreate = false): Promise<void> {
    clearNotice();
    if (!runId.value) {
      errorMessage.value = "run_id is required";
      return;
    }
    isRunning.value = true;
    try {
      await initProductionTracks(runId.value, context.selectedTracks, recreate);
      message.value = recreate ? "tracks rebuilt" : "tracks initialized";
      await refreshTrackDashboard();
    } catch (error) {
      errorMessage.value = `init tracks failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isRunning.value = false;
    }
  }

  async function refreshTrackDashboard(): Promise<void> {
    if (!runId.value) return;
    try {
      trackSummaries.value = await loadTrackSummaries(runId.value);
      const availableTrackTypes = trackSummaries.value
        .map((item) => normalizeTrackType(item.track_type))
        .filter((item): item is ProductionTrackType => item !== null);
      if (!availableTrackTypes.includes(activeTrack.value) && availableTrackTypes.length > 0) {
        activeTrack.value = availableTrackTypes[0];
      }
      const unitsEntries = await Promise.all(
        availableTrackTypes.map(async (trackType) => [trackType, await loadTrackUnits(runId.value, trackType)] as const),
      );
      unitsByTrack.value = Object.fromEntries(unitsEntries);
      const timeline = await tryLoadTimeline(runId.value);
      timelinePlanLoaded.value = timeline !== null;
      await refreshRunMeta();
    } catch (error) {
      errorMessage.value = `refresh track dashboard failed: ${error instanceof Error ? error.message : String(error)}`;
    }
  }

  async function runTrack(trackType: ProductionTrackType): Promise<void> {
    if (!runId.value) {
      errorMessage.value = "run_id is required";
      return;
    }
    clearNotice();
    isRunning.value = true;
    try {
      const result = await runTrackBatch(runId.value, trackType, { force: false });
      message.value = result.blocked_reason
        ? `${trackType} blocked: ${result.blocked_reason}`
        : `${trackType} jobs: ${result.jobs_created}`;
      await refreshTrackDashboard();
    } catch (error) {
      errorMessage.value = `run track failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isRunning.value = false;
    }
  }

  async function runSelectedTracks(): Promise<void> {
    if (!runId.value) {
      errorMessage.value = "run_id is required";
      return;
    }
    clearNotice();
    isRunning.value = true;
    try {
      for (const track of context.selectedTracks) {
        await runTrackBatch(runId.value, track, { force: false });
      }
      message.value = `dispatched ${context.selectedTracks.length} tracks`;
      await refreshTrackDashboard();
    } catch (error) {
      errorMessage.value = `run selected tracks failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isRunning.value = false;
    }
  }

  async function runUnit(trackType: ProductionTrackType, unitId: string): Promise<void> {
    if (!runId.value) {
      errorMessage.value = "run_id is required";
      return;
    }
    clearNotice();
    isRunning.value = true;
    try {
      await runTrackBatch(runId.value, trackType, { unit_ids: [unitId], force: true });
      message.value = `unit dispatched: ${unitId}`;
      await refreshTrackDashboard();
    } catch (error) {
      errorMessage.value = `run unit failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isRunning.value = false;
    }
  }

  async function retryFailedInTrack(trackType: ProductionTrackType): Promise<void> {
    if (!runId.value) {
      errorMessage.value = "run_id is required";
      return;
    }
    clearNotice();
    isRunning.value = true;
    try {
      const result = await runTrackBatch(runId.value, trackType, { only_failed: true, force: true });
      message.value = `${trackType} retried failed: ${result.jobs_created}`;
      await refreshTrackDashboard();
    } catch (error) {
      errorMessage.value = `retry failed units failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isRunning.value = false;
    }
  }

  async function retryUnit(trackType: ProductionTrackType, unitId: string, patch?: RetryPatchPayload): Promise<void> {
    if (!runId.value) {
      errorMessage.value = "run_id is required";
      return;
    }
    clearNotice();
    isRunning.value = true;
    try {
      if (patch && Object.keys(patch).length > 0) {
        await retryTrackUnitWithPatch(runId.value, unitId, patch);
      } else {
        await runTrackBatch(runId.value, trackType, { unit_ids: [unitId], force: true });
      }
      message.value = `unit retried: ${unitId}`;
      await refreshTrackDashboard();
    } catch (error) {
      errorMessage.value = `retry unit failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isRunning.value = false;
    }
  }

  async function selectCandidate(trackType: ProductionTrackType, unitId: string, artifactId: string): Promise<void> {
    if (!runId.value) {
      errorMessage.value = "run_id is required";
      return;
    }
    clearNotice();
    isRunning.value = true;
    try {
      await selectUnitCandidate(runId.value, unitId, artifactId);
      message.value = `${trackType} candidate selected: ${artifactId}`;
      await refreshTrackDashboard();
    } catch (error) {
      errorMessage.value = `select candidate failed: ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isRunning.value = false;
    }
  }

  async function loadAttemptHistory(unitId: string): Promise<void> {
    if (!runId.value) {
      return;
    }
    try {
      attemptsByUnit.value[unitId] = await loadUnitAttempts(runId.value, unitId);
    } catch {
      attemptsByUnit.value[unitId] = [];
    }
  }

  return {
    context,
    options,
    runId,
    runMeta,
    activeTrack,
    trackSummaries,
    unitsByTrack,
    attemptsByUnit,
    timelinePlanLoaded,
    isLoading,
    isRunning,
    message,
    errorMessage,
    qualityOptions,
    trackOptions,
    novelSelectOptions,
    chapterSelectOptions,
    personaSelectOptions,
    scriptVersionOptions,
    planVersionOptions,
    activeUnits,
    timelineBlocks,
    hasRunnableContext,
    bootstrap,
    loadNovelContext,
    loadChapterContext,
    createRun,
    refreshRunMeta,
    initTracks,
    refreshTrackDashboard,
    runTrack,
    runSelectedTracks,
    runUnit,
    retryFailedInTrack,
    retryUnit,
    selectCandidate,
    loadAttemptHistory,
    clearNotice,
  };
});
