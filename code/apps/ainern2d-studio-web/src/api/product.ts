import { http } from "@/api/http";

export interface LoginResponse {
  token: string;
  user_id: string;
}

export interface UserInfoResponse {
  user_id: string;
  email: string;
  display_name: string;
}

export interface ProjectAclItem {
  project_id: string;
  user_id: string;
  role: string;
}

export interface AuditLogItem {
  event_id: string;
  event_type: string;
  producer: string;
  occurred_at: string;
  run_id?: string | null;
  job_id?: string | null;
  payload: Record<string, unknown>;
}

export interface NovelResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  title: string;
  summary?: string | null;
  default_language_code: string;
}

export interface ChapterResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  novel_id: string;
  chapter_no: number;
  language_code: string;
  title?: string | null;
  markdown_text: string;
}

export interface ChapterRevisionItem {
  revision_id: string;
  occurred_at: string;
  chapter_id: string;
  note?: string | null;
  editor?: string | null;
  previous_markdown_text: string;
}

export interface ChapterPreviewResponse {
  preview_run_id: string;
  skill_01_status: string;
  skill_02_status: string;
  skill_03_status: string;
  normalized_text: string;
  culture_candidates: string[];
  scene_count: number;
  shot_count: number;
  scene_plan: Record<string, unknown>[];
  shot_plan: Record<string, unknown>[];
}

export interface TaskSubmitAccepted {
  run_id: string;
  status: string;
  message?: string;
}

export interface RunSnapshotResponse {
  run_id: string;
  snapshot: Record<string, unknown>;
}

export interface ProviderResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  name: string;
  endpoint?: string | null;
  auth_mode?: string | null;
  enabled?: boolean;
  access_token_masked?: string | null;
  model_catalog?: string[];
  headers_json?: Record<string, unknown>;
  capability_flags?: {
    supports_text_generation?: boolean;
    supports_embedding?: boolean;
    supports_multimodal?: boolean;
    supports_image_generation?: boolean;
    supports_video_generation?: boolean;
    supports_tts?: boolean;
    supports_stt?: boolean;
    supports_tool_calling?: boolean;
    supports_reasoning?: boolean;
  };
}

export interface ModelProfileResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  provider_id: string;
  purpose: string;
  name: string;
  params_json: Record<string, unknown>;
}

export interface StageRoutingResponse {
  tenant_id: string;
  project_id: string;
  routes: Record<string, unknown>;
  fallback_chain: Record<string, unknown>;
  feature_routes?: Record<string, unknown>;
}

export interface FeatureMatrixResponse {
  tenant_id: string;
  project_id: string;
  items: Array<{
    feature_key: string;
    description: string;
    eligible_profiles: Array<{
      profile_id: string;
      provider_id: string;
      provider_name: string;
      purpose: string;
      model_name: string;
    }>;
  }>;
}

export interface ProviderConnectionTestResponse {
  provider_id: string;
  provider_name: string;
  endpoint: string;
  probe_url: string;
  connected: boolean;
  status_code?: number | null;
  latency_ms?: number | null;
  message: string;
}

export interface ConfigHealthResponse {
  tenant_id: string;
  project_id: string;
  provider_count: number;
  profile_count: number;
  routing_ready: boolean;
  providers: Array<{
    provider_id: string;
    provider_name: string;
    status: string;
    reason: string;
  }>;
}

export interface LanguageDefinition {
  language_code: string;
  label: string;
  locales: string[];
  direction: string;
  enabled: boolean;
}

export interface LanguageSettingsResponse {
  tenant_id: string;
  project_id: string;
  default_source_language: string;
  default_target_languages: string[];
  enabled_languages: LanguageDefinition[];
  translation_notes?: string | null;
  glossary: Record<string, unknown>;
  schema_version: string;
  updated_at?: string | null;
}

export interface TelegramSettingsResponse {
  tenant_id: string;
  project_id: string;
  enabled: boolean;
  bot_token_masked?: string | null;
  chat_id?: string | null;
  thread_id?: string | null;
  parse_mode: string;
  notify_events: string[];
  schema_version: string;
  updated_at?: string | null;
}

export interface RagCollectionResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  name: string;
  language_code?: string | null;
  description?: string | null;
  tags_json: string[];
}

export interface KbVersionResponse {
  id: string;
  collection_id: string;
  version_name: string;
  status: string;
  recipe_id?: string | null;
  embedding_model_profile_id?: string | null;
  release_note?: string | null;
}

export interface PersonaPackResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  name: string;
  description?: string | null;
  tags_json: string[];
}

export interface PersonaVersionResponse {
  id: string;
  persona_pack_id: string;
  version_name: string;
  style_json: Record<string, unknown>;
  voice_json: Record<string, unknown>;
  camera_json: Record<string, unknown>;
}

export interface PersonaBindingResponse {
  persona_pack_version_id: string;
  dataset_bindings: string[];
  index_bindings: string[];
}

export interface PersonaPreviewResponse {
  persona_pack_version_id: string;
  query: string;
  top_k: number;
  chunks: Array<{
    doc_id: string;
    collection_id?: string | null;
    kb_version_id?: string | null;
    title?: string | null;
    source_type: string;
    source_id?: string | null;
    score: number;
    snippet: string;
  }>;
}

export interface CulturePackResponse {
  culture_pack_id: string;
  version: string;
  display_name: string;
  description?: string | null;
  status: string;
  constraints: Record<string, unknown>;
}

export interface CulturePackExportResponse {
  culture_pack_id: string;
  version: string;
  export_for_skill_02: Record<string, unknown>;
  export_for_skill_07: Record<string, unknown>;
  export_for_skill_10: Record<string, unknown>;
}

export interface ProjectAssetItem {
  id: string;
  run_id: string;
  chapter_id?: string | null;
  shot_id?: string | null;
  type: string;
  uri: string;
  size_bytes?: number | null;
  checksum?: string | null;
  meta_info: Record<string, unknown>;
  anchored: boolean;
}

export interface AssetAnchorResponse {
  asset_id: string;
  run_id: string;
  project_id: string;
  anchored: boolean;
  anchor_info: Record<string, unknown>;
  continuity_profile_id?: string | null;
}

export interface AnchoredAssetItem {
  asset_id: string;
  run_id: string;
  shot_id?: string | null;
  uri: string;
  anchor_info: Record<string, unknown>;
}

export interface AssetBindingConsistencyItem {
  entity_id: string;
  entity_name: string;
  entity_type: string;
  chapter_id?: string | null;
  run_id?: string | null;
  shot_id?: string | null;
  scene_id?: string | null;
  scene_label?: string | null;
  continuity_status: string;
  locked_preview_variant_id?: string | null;
  latest_preview_variant_id?: string | null;
  latest_preview_status?: string | null;
  locked_asset_id?: string | null;
  locked_asset_uri?: string | null;
  latest_asset_id?: string | null;
  latest_asset_uri?: string | null;
  anchor_name?: string | null;
  anchor_notes?: string | null;
}

export interface TimelinePlan {
  run_id: string;
  total_duration_ms: number;
  video_tracks: Array<Record<string, unknown>>;
  audio_tracks: Array<Record<string, unknown>>;
  effect_tracks: Array<Record<string, unknown>>;
}

export interface TimelinePatchResponse {
  run_id: string;
  patch_id: string;
  job_id: string;
  status: string;
  message: string;
}

export interface GeneratePreviewResponse {
  run_id: string;
  entity_id: string;
  created_variants: string[];
  created_jobs: string[];
  message?: string;
}

export interface ReviewPreviewVariantResponse {
  variant_id: string;
  status: string;
  continuity_profile_id?: string | null;
  regenerated_variant_id?: string | null;
  regenerated_job_id?: string | null;
}

export async function registerUser(payload: {
  username: string;
  password: string;
  email: string;
}): Promise<UserInfoResponse> {
  const { data } = await http.post<UserInfoResponse>("/api/v1/auth/register", payload);
  return data;
}

export async function login(payload: { username: string; password: string }): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>("/api/v1/auth/login", payload);
  return data;
}

export async function getCurrentUser(): Promise<UserInfoResponse> {
  const { data } = await http.get<UserInfoResponse>("/api/v1/auth/me");
  return data;
}

export async function logout(): Promise<void> {
  await http.post("/api/v1/auth/logout");
}

export async function listProjectAcl(projectId: string, tenantId: string): Promise<ProjectAclItem[]> {
  const { data } = await http.get<ProjectAclItem[]>(`/api/v1/auth/projects/${projectId}/acl`, {
    params: { tenant_id: tenantId },
  });
  return data;
}

export async function upsertProjectAcl(
  projectId: string,
  userId: string,
  payload: { tenant_id: string; role: string }
): Promise<ProjectAclItem> {
  const { data } = await http.put<ProjectAclItem>(`/api/v1/auth/projects/${projectId}/acl/${userId}`, payload);
  return data;
}

export async function listAuditLogs(params: {
  tenant_id: string;
  project_id?: string;
  limit?: number;
}): Promise<AuditLogItem[]> {
  const { data } = await http.get<AuditLogItem[]>("/api/v1/auth/audit/logs", { params });
  return data;
}

export async function createNovel(payload: {
  tenant_id: string;
  project_id: string;
  title: string;
  summary?: string;
  default_language_code?: string;
}): Promise<NovelResponse> {
  const { data } = await http.post<NovelResponse>("/api/v1/novels", payload);
  return data;
}

export async function listNovels(tenantId: string, projectId: string): Promise<NovelResponse[]> {
  const { data } = await http.get<NovelResponse[]>("/api/v1/novels", {
    params: { tenant_id: tenantId, project_id: projectId },
  });
  return data;
}

export async function createChapter(novelId: string, payload: {
  tenant_id: string;
  project_id: string;
  chapter_no: number;
  language_code?: string;
  title?: string;
  markdown_text: string;
}): Promise<ChapterResponse> {
  const { data } = await http.post<ChapterResponse>(`/api/v1/novels/${novelId}/chapters`, payload);
  return data;
}

export async function listChapters(novelId: string): Promise<ChapterResponse[]> {
  const { data } = await http.get<ChapterResponse[]>(`/api/v1/novels/${novelId}/chapters`);
  return data;
}

export async function updateChapter(chapterId: string, payload: {
  markdown_text: string;
  title?: string;
  language_code?: string;
  revision_note?: string;
}): Promise<ChapterResponse> {
  const { data } = await http.put<ChapterResponse>(`/api/v1/chapters/${chapterId}`, payload);
  return data;
}

export async function listChapterRevisions(chapterId: string): Promise<ChapterRevisionItem[]> {
  const { data } = await http.get<ChapterRevisionItem[]>(`/api/v1/chapters/${chapterId}/revisions`);
  return data;
}

export async function previewChapterPlan(chapterId: string, payload: {
  tenant_id: string;
  project_id: string;
  target_output_language?: string;
  target_locale?: string;
  genre?: string;
  story_world_setting?: string;
  culture_pack_id?: string;
  persona_ref?: string;
}): Promise<ChapterPreviewResponse> {
  const { data } = await http.post<ChapterPreviewResponse>(`/api/v1/chapters/${chapterId}/preview-plan`, payload);
  return data;
}

export async function createChapterTask(chapterId: string, payload: {
  tenant_id: string;
  project_id: string;
  requested_quality?: string;
  language_context?: string;
  payload?: Record<string, unknown>;
}): Promise<TaskSubmitAccepted> {
  const { data } = await http.post<TaskSubmitAccepted>(`/api/v1/chapters/${chapterId}/tasks`, payload);
  return data;
}

export async function getRunSnapshot(runId: string): Promise<RunSnapshotResponse> {
  const { data } = await http.get<RunSnapshotResponse>(`/api/v1/runs/${runId}/snapshot`);
  return data;
}

export async function upsertProvider(payload: {
  tenant_id: string;
  project_id: string;
  name: string;
  endpoint?: string;
  auth_mode?: string;
  enabled?: boolean;
  access_token?: string;
  model_catalog?: string[];
  headers_json?: Record<string, unknown>;
  capability_flags?: Record<string, unknown>;
}): Promise<ProviderResponse> {
  const { data } = await http.post<ProviderResponse>("/api/v1/config/providers", payload);
  return data;
}

export async function listProviders(tenantId: string, projectId: string): Promise<ProviderResponse[]> {
  const { data } = await http.get<ProviderResponse[]>("/api/v1/config/providers", {
    params: { tenant_id: tenantId, project_id: projectId },
  });
  return data;
}

export async function deleteProvider(providerId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<void> {
  await http.delete(`/api/v1/config/providers/${providerId}`, { params });
}

export async function testProviderConnection(providerId: string, payload: {
  tenant_id: string;
  project_id: string;
  probe_path?: string;
  timeout_ms?: number;
}): Promise<ProviderConnectionTestResponse> {
  const { data } = await http.post<ProviderConnectionTestResponse>(
    `/api/v1/config/providers/${providerId}/test-connection`,
    payload
  );
  return data;
}

export async function upsertModelProfile(payload: {
  tenant_id: string;
  project_id: string;
  provider_id: string;
  purpose: string;
  name: string;
  params_json?: Record<string, unknown>;
}): Promise<ModelProfileResponse> {
  const { data } = await http.post<ModelProfileResponse>("/api/v1/config/profiles", payload);
  return data;
}

export async function listModelProfiles(params: {
  tenant_id: string;
  project_id: string;
  purpose?: string;
}): Promise<ModelProfileResponse[]> {
  const { data } = await http.get<ModelProfileResponse[]>("/api/v1/config/profiles", { params });
  return data;
}

export async function deleteModelProfile(profileId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<void> {
  await http.delete(`/api/v1/config/profiles/${profileId}`, { params });
}

export async function upsertStageRouting(payload: {
  tenant_id: string;
  project_id: string;
  routes: Record<string, unknown>;
  fallback_chain: Record<string, unknown>;
  feature_routes?: Record<string, unknown>;
}): Promise<StageRoutingResponse> {
  const { data } = await http.put<StageRoutingResponse>("/api/v1/config/stage-routing", payload);
  return data;
}

export async function getFeatureMatrix(tenantId: string, projectId: string): Promise<FeatureMatrixResponse> {
  const { data } = await http.get<FeatureMatrixResponse>("/api/v1/config/feature-matrix", {
    params: { tenant_id: tenantId, project_id: projectId },
  });
  return data;
}

export async function getConfigHealth(tenantId: string, projectId: string): Promise<ConfigHealthResponse> {
  const { data } = await http.get<ConfigHealthResponse>("/api/v1/config/health", {
    params: { tenant_id: tenantId, project_id: projectId },
  });
  return data;
}

export async function upsertLanguageSettings(payload: {
  tenant_id: string;
  project_id: string;
  default_source_language: string;
  default_target_languages: string[];
  enabled_languages: LanguageDefinition[];
  translation_notes?: string;
  glossary?: Record<string, unknown>;
  schema_version?: string;
}): Promise<LanguageSettingsResponse> {
  const { data } = await http.put<LanguageSettingsResponse>("/api/v1/config/language-settings", payload);
  return data;
}

export async function getLanguageSettings(tenantId: string, projectId: string): Promise<LanguageSettingsResponse> {
  const { data } = await http.get<LanguageSettingsResponse>("/api/v1/config/language-settings", {
    params: { tenant_id: tenantId, project_id: projectId },
  });
  return data;
}

export async function upsertTelegramSettings(payload: {
  tenant_id: string;
  project_id: string;
  enabled: boolean;
  bot_token?: string;
  chat_id?: string;
  thread_id?: string;
  parse_mode?: string;
  notify_events?: string[];
  schema_version?: string;
}): Promise<TelegramSettingsResponse> {
  const { data } = await http.put<TelegramSettingsResponse>("/api/v1/config/telegram-settings", payload);
  return data;
}

export async function getTelegramSettings(tenantId: string, projectId: string): Promise<TelegramSettingsResponse> {
  const { data } = await http.get<TelegramSettingsResponse>("/api/v1/config/telegram-settings", {
    params: { tenant_id: tenantId, project_id: projectId },
  });
  return data;
}

export async function createRagCollection(payload: {
  tenant_id: string;
  project_id: string;
  name: string;
  language_code?: string;
  description?: string;
  tags_json?: string[];
}): Promise<RagCollectionResponse> {
  const { data } = await http.post<RagCollectionResponse>("/api/v1/rag/collections", payload);
  return data;
}

export async function listRagCollections(params: {
  tenant_id: string;
  project_id: string;
  keyword?: string;
  language_code?: string;
}): Promise<RagCollectionResponse[]> {
  const { data } = await http.get<RagCollectionResponse[]>("/api/v1/rag/collections", {
    params,
  });
  return data;
}

export async function deleteRagCollection(collectionId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<void> {
  await http.delete(`/api/v1/rag/collections/${collectionId}`, { params });
}

export async function createKbVersion(collectionId: string, payload: {
  tenant_id: string;
  project_id: string;
  version_name: string;
  status?: string;
}): Promise<KbVersionResponse> {
  const { data } = await http.post<KbVersionResponse>(`/api/v1/rag/collections/${collectionId}/kb-versions`, payload);
  return data;
}

export async function listKbVersions(collectionId: string, params?: {
  status?: string;
}): Promise<KbVersionResponse[]> {
  const { data } = await http.get<KbVersionResponse[]>(`/api/v1/rag/collections/${collectionId}/kb-versions`, {
    params,
  });
  return data;
}

export async function createPersonaPack(payload: {
  tenant_id: string;
  project_id: string;
  name: string;
  description?: string;
}): Promise<PersonaPackResponse> {
  const { data } = await http.post<PersonaPackResponse>("/api/v1/rag/persona-packs", payload);
  return data;
}

export async function listPersonaPacks(params: {
  tenant_id: string;
  project_id: string;
  keyword?: string;
}): Promise<PersonaPackResponse[]> {
  const { data } = await http.get<PersonaPackResponse[]>("/api/v1/rag/persona-packs", { params });
  return data;
}

export async function deletePersonaPack(personaPackId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<void> {
  await http.delete(`/api/v1/rag/persona-packs/${personaPackId}`, { params });
}

export async function createPersonaVersion(personaPackId: string, payload: {
  tenant_id: string;
  project_id: string;
  version_name: string;
  style_json?: Record<string, unknown>;
  voice_json?: Record<string, unknown>;
  camera_json?: Record<string, unknown>;
}): Promise<PersonaVersionResponse> {
  const { data } = await http.post<PersonaVersionResponse>(`/api/v1/rag/persona-packs/${personaPackId}/versions`, payload);
  return data;
}

export async function listPersonaVersions(personaPackId: string): Promise<PersonaVersionResponse[]> {
  const { data } = await http.get<PersonaVersionResponse[]>(`/api/v1/rag/persona-packs/${personaPackId}/versions`);
  return data;
}

export async function bindPersonaResources(personaVersionId: string, payload: {
  tenant_id: string;
  project_id: string;
  dataset_collection_ids: string[];
  kb_version_ids: string[];
  binding_role?: string;
}): Promise<PersonaBindingResponse> {
  const { data } = await http.post<PersonaBindingResponse>(`/api/v1/rag/persona-versions/${personaVersionId}/bindings`, payload);
  return data;
}

export async function previewPersona(payload: {
  tenant_id: string;
  project_id: string;
  persona_pack_version_id: string;
  query: string;
  top_k?: number;
}): Promise<PersonaPreviewResponse> {
  const { data } = await http.post<PersonaPreviewResponse>("/api/v1/rag/persona-preview", payload);
  return data;
}

export async function createCulturePack(payload: {
  tenant_id: string;
  project_id: string;
  culture_pack_id: string;
  display_name: string;
  description?: string;
  constraints?: Record<string, unknown>;
}): Promise<CulturePackResponse> {
  const { data } = await http.post<CulturePackResponse>("/api/v1/culture-packs", payload);
  return data;
}

export async function listCulturePacks(params: {
  tenant_id: string;
  project_id: string;
  keyword?: string;
  status?: string;
}): Promise<CulturePackResponse[]> {
  const { data } = await http.get<CulturePackResponse[]>("/api/v1/culture-packs", { params });
  return data;
}

export async function deleteCulturePack(culturePackId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<void> {
  await http.delete(`/api/v1/culture-packs/${culturePackId}`, { params });
}

export async function exportCulturePack(params: {
  tenant_id: string;
  project_id: string;
  culture_pack_id: string;
}): Promise<CulturePackExportResponse> {
  const { data } = await http.get<CulturePackExportResponse>(`/api/v1/culture-packs/${params.culture_pack_id}/export`, {
    params: {
      tenant_id: params.tenant_id,
      project_id: params.project_id,
    },
  });
  return data;
}

export async function listProjectAssets(params: {
  tenant_id: string;
  project_id: string;
  chapter_id?: string;
  run_id?: string;
  shot_id?: string;
  asset_type?: string;
  keyword?: string;
  anchored?: boolean;
}): Promise<ProjectAssetItem[]> {
  const { data } = await http.get<ProjectAssetItem[]>(`/api/v1/projects/${params.project_id}/assets`, {
    params,
  });
  return data;
}

export async function deleteAsset(assetId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<void> {
  await http.delete(`/api/v1/assets/${assetId}`, { params });
}

export async function markAssetAnchor(assetId: string, payload: {
  tenant_id: string;
  project_id: string;
  entity_id?: string;
  anchor_name?: string;
  notes?: string;
  tags?: string[];
}): Promise<AssetAnchorResponse> {
  const { data } = await http.post<AssetAnchorResponse>(`/api/v1/assets/${assetId}/anchor`, payload);
  return data;
}

export async function listProjectAnchors(projectId: string, tenantId: string): Promise<AnchoredAssetItem[]> {
  const { data } = await http.get<AnchoredAssetItem[]>(`/api/v1/projects/${projectId}/anchors`, {
    params: { tenant_id: tenantId },
  });
  return data;
}

export async function listAssetBindingConsistency(params: {
  tenant_id: string;
  project_id: string;
  chapter_id?: string;
  run_id?: string;
  entity_type?: string;
  keyword?: string;
}): Promise<AssetBindingConsistencyItem[]> {
  const { data } = await http.get<AssetBindingConsistencyItem[]>(
    `/api/v1/projects/${params.project_id}/asset-bindings`,
    { params }
  );
  return data;
}

export async function generateEntityPreviewVariants(runId: string, entityId: string, payload: {
  shot_id?: string;
  scene_id?: string;
  view_angles?: string[];
  prompt_text?: string;
  negative_prompt_text?: string;
  generation_backend?: string;
}): Promise<GeneratePreviewResponse> {
  const { data } = await http.post<GeneratePreviewResponse>(
    `/api/v1/runs/${runId}/preview/entities/${entityId}/generate`,
    payload
  );
  return data;
}

export async function reviewPreviewVariant(variantId: string, payload: {
  decision: "approve" | "reject" | "regenerate";
  note?: string;
}): Promise<ReviewPreviewVariantResponse> {
  const { data } = await http.post<ReviewPreviewVariantResponse>(
    `/api/v1/preview/variants/${variantId}/review`,
    payload
  );
  return data;
}

export async function getRunTimeline(runId: string): Promise<TimelinePlan> {
  const { data } = await http.get<TimelinePlan>(`/api/v1/runs/${runId}/timeline`);
  return data;
}

export async function patchRunTimeline(runId: string, payload: {
  tenant_id: string;
  project_id: string;
  shot_id: string;
  patch_text: string;
  track?: string;
  patch_scope?: string;
  requested_by?: string;
}): Promise<TimelinePatchResponse> {
  const { data } = await http.post<TimelinePatchResponse>(`/api/v1/runs/${runId}/timeline/patch`, payload);
  return data;
}

export async function updateRunTimeline(runId: string, payload: TimelinePlan): Promise<TimelinePlan> {
  const { data } = await http.put<TimelinePlan>(`/api/v1/runs/${runId}/timeline`, payload);
  return data;
}
