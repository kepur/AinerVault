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

export interface NovelTeamMember {
  persona_pack_id: string;
  persona_pack_name: string;
}

export interface NovelTeamResponse {
  novel_id: string;
  team: Record<string, NovelTeamMember>;
}

export interface NovelResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  title: string;
  summary?: string | null;
  default_language_code: string;
  team_json?: Record<string, NovelTeamMember> | null;
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

export interface ChapterAssistExpandResponse {
  chapter_id: string;
  original_length: number;
  expanded_length: number;
  expanded_markdown: string;
  appended_excerpt: string;
  provider_used: string;
  model_name: string;
  mode: string;
  prompt_tokens_estimate: number;
  completion_tokens_estimate: number;
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

export interface RunDetailResponse {
  run_id: string;
  status: string;
  stage: string;
  progress: number;
  latest_error?: {
    error_code?: string;
    message?: string;
  } | null;
  final_artifact_uri?: string | null;
}

export interface TrackInitItem {
  track_type: string;
  track_run_id: string;
  units_created: number;
  status: string;
}

export interface InitTracksResponse {
  run_id: string;
  tracks: TrackInitItem[];
}

export interface TrackSummary {
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
}

export interface TrackUnitItem {
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
}

export interface RunTrackResponse {
  run_id: string;
  track_type: string;
  track_run_id: string;
  track_status: string;
  jobs_created: number;
  blocked_reason?: string | null;
}

export interface RetryTrackUnitResponse {
  run_id: string;
  track_run_id: string;
  track_unit_id: string;
  job_id: string;
  status: string;
}

export interface TrackUnitAttemptResponse {
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
}

export interface SelectTrackUnitCandidateResponse {
  run_id: string;
  track_run_id: string;
  track_unit_id: string;
  selected_asset_id: string;
  selected_job_id?: string | null;
  status: string;
}

export interface PromptPlanReplayItem {
  plan_id: string;
  run_id: string;
  shot_id: string;
  prompt_text: string;
  negative_prompt_text?: string | null;
  model_hint_json?: Record<string, unknown> | null;
}

export interface PolicyStackReplayItem {
  policy_stack_id: string;
  run_id: string;
  name: string;
  status: string;
  active_persona_ref: string;
  review_items: string[];
  hard_constraints: number;
  soft_constraints: number;
  guidelines: number;
  conflicts: number;
  audit_entries: number;
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

export interface OpsTokenResponse {
  token_id: string;
  name: string;
  token_masked: string;
  is_active: boolean;
  created_at: string;
  expires_at: string;
  days_remaining: number;
  last_used_at?: string | null;
}

export interface OpsTokenRevealResponse {
  token_id: string;
  name: string;
  token: string;
  expires_at: string;
}

export interface CapabilityStandardItem {
  capability_type: string;
  display_name: string;
  track_targets: string[];
  min_required_tier: "low" | "medium" | "high";
  tiers: {
    low: string[];
    medium: string[];
    high: string[];
  };
}

export interface CapabilityStandardsResponse {
  supported_track_types: string[];
  items: CapabilityStandardItem[];
}

export interface AdapterSpecResponse {
  items: Record<
    string,
    {
      request_required: string[];
      response_required: string[];
      response_optional?: string[];
    }
  >;
}

export interface OpsStorageConfigResponse {
  storage_backend: string;
  provider: string;
  endpoint: string;
  internal_endpoint: string;
  console_endpoint?: string | null;
  bucket: string;
  region: string;
  access_key: string;
  secret_key: string;
  root_user: string;
  root_password: string;
  copy_env_block: string;
}

export interface OpsStorageConfigUpdatePayload {
  endpoint: string;
  internal_endpoint: string;
  console_endpoint?: string | null;
  bucket: string;
  region: string;
  access_key: string;
  secret_key: string;
  root_user: string;
  root_password: string;
}

export interface RequirementTierDefinition {
  tier: "basic" | "standard" | "advanced";
  target_values: Record<string, unknown>;
  must_support: string[];
  optional_support: string[];
}

export interface CapabilityRequirementDefinition {
  capability_type: string;
  display_name: string;
  aliases: string[];
  tiers: Record<string, RequirementTierDefinition>;
}

export interface RequirementTiersResponse {
  schema_version: string;
  items: CapabilityRequirementDefinition[];
}

export interface RequirementSchemaResponse {
  schema_version: string;
  capability_aliases: Record<string, string>;
  tier_aliases: Record<string, string>;
  requirement_profile_schema: Record<string, unknown>;
  route_plan_schema: Record<string, unknown>;
  gap_report_schema: Record<string, unknown>;
}

export interface OpsIntegrationVersion {
  integration_id: string;
  capability_type: string;
  tier: string;
  provider_key: string;
  provider_name: string;
  version: number;
  status: string;
  mapping_status: string;
  created_at?: string | null;
  evidence: Record<string, unknown>;
}

export interface OpsRoutePlan {
  selected_provider_key: string;
  selected_provider_name: string;
  selected_report_id: string;
  matched_provider_id?: string | null;
  data_endpoint?: string | null;
  selected_template_id: string;
  selected_template_version: string;
  workflow_hash: string;
  resolved_params: Record<string, unknown>;
  bindings: Record<string, unknown>;
  fallback_chain: Array<Record<string, unknown>>;
  mapping_status: string;
  mapping_confidence?: number | null;
}

export interface OpsGapReport {
  gap_type: string;
  summary: string;
  missing_features: string[];
  unmet_constraints: Record<string, unknown>;
  repair_actions: Record<string, unknown>;
  candidate_summaries: Array<Record<string, unknown>>;
}

export interface OpsPlanRequestPayload {
  tenant_id: string;
  project_id: string;
  capability: string;
  tier: "basic" | "standard" | "advanced";
  constraints?: Record<string, unknown>;
  required_features?: string[];
  preferences?: Record<string, unknown>;
  auto_integrate?: boolean;
  validate_connectivity?: boolean;
  initiated_by?: string;
}

export interface OpsPlanResponse {
  status: "planned" | "gap";
  capability: string;
  tier: string;
  requirement_profile: Record<string, unknown>;
  route_plan?: OpsRoutePlan | null;
  gap_report?: OpsGapReport | null;
  integration?: OpsIntegrationVersion | null;
  candidates_considered: number;
}

export interface OpsIntegrationListResponse {
  items: OpsIntegrationVersion[];
}

export interface RuntimeRouteDecisionResponse {
  decision_id: string;
  created_at?: string | null;
  capability_type: string;
  provider_key?: string | null;
  provider_name?: string | null;
  profile_name?: string | null;
  integration_id?: string | null;
  mode?: string | null;
  probe_ok?: boolean | null;
  probe_detail?: string | null;
  probe_latency_ms?: number | null;
  live_ok?: boolean | null;
  live_status_code?: number | null;
  live_latency_ms?: number | null;
}

export interface RuntimeCapabilityStatResponse {
  capability_type: string;
  total_runs: number;
  success_runs: number;
  success_rate: number;
  latest_status: string;
  latest_latency_ms?: number | null;
  latest_provider_name?: string | null;
  latest_at?: string | null;
}

export interface RuntimeRouteItemResponse {
  integration_id: string;
  capability_type: string;
  tier: string;
  provider_key: string;
  provider_name: string;
  version: number;
  status: string;
  mapping_status: string;
  profile_name?: string | null;
  runtime_route_key: string;
  feature_route_key: string;
  applied_profile_name?: string | null;
  applied_route_profile_name?: string | null;
  route_plan: Record<string, unknown>;
  requirement_profile: Record<string, unknown>;
  fallback_chain: Array<Record<string, unknown>>;
  evidence: Record<string, unknown>;
  created_at?: string | null;
}

export interface RuntimeRoutingViewResponse {
  tenant_id: string;
  project_id: string;
  stage_routes: Record<string, unknown>;
  feature_routes: Record<string, unknown>;
  fallback_chain: Record<string, unknown>;
  items: RuntimeRouteItemResponse[];
  recent_decisions: RuntimeRouteDecisionResponse[];
  capability_stats: RuntimeCapabilityStatResponse[];
}

export interface QuickRunResponse {
  mode: string;
  integration: OpsIntegrationVersion;
  runtime_route_key: string;
  profile_name?: string | null;
  request_preview: Record<string, unknown>;
  probe: Record<string, unknown>;
  live_request: Record<string, unknown>;
  live_response: Record<string, unknown>;
  decision_id?: string | null;
}

export interface OpsProviderRow {
  report_id: string;
  provider_key: string;
  provider_name: string;
  capability_type: string;
  capability_tier: "none" | "low" | "medium" | "high";
  min_required_tier: "low" | "medium" | "high";
  meets_minimum: boolean;
  integration_status: string;
  integration_status_label: string;
  matched_provider_id?: string | null;
  matched_provider_name?: string | null;
  endpoint_base_url?: string | null;
  protocol: string;
  openapi_url?: string | null;
  model_catalog: string[];
  last_reported_at?: string | null;
  last_tested_at?: string | null;
  integration_notes?: string | null;
  mapping_status: "pending" | "mapped" | "partial" | "failed";
  mapping_confidence?: number | null;
  request_coverage?: number | null;
  response_coverage?: number | null;
  feature_coverage?: number | null;
  mapping_gaps: string[];
  mapping_generated_at?: string | null;
  connectivity_status: "connected" | "disconnected" | "untested" | "testing";
  connectivity_label: string;
  last_connectivity_detail?: string | null;
  last_checked_url?: string | null;
  last_latency_ms?: number | null;
}

export interface OpsProviderListResponse {
  items: OpsProviderRow[];
}

export interface OpsProviderReportPayload {
  tenant_id: string;
  project_id: string;
  provider_key: string;
  provider_name: string;
  capability_type: string;
  endpoint_base_url?: string;
  protocol?: string;
  openapi_url?: string;
  model_catalog?: string[];
  features?: Record<string, unknown>;
  constraints?: Record<string, unknown>;
  health?: Record<string, unknown>;
  adapter_spec?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface OpsProviderReportUpsertResponse {
  report_id: string;
  provider_key: string;
  capability_type: string;
  capability_tier: "none" | "low" | "medium" | "high";
  integration_status: string;
  matched_provider_id?: string | null;
  meets_minimum: boolean;
  adapter_gap_features: string[];
  mapping_status: "pending" | "mapped" | "partial" | "failed";
  mapping_confidence?: number | null;
  mapping_gaps: string[];
}

export interface OpsProviderTestResponse {
  report_id: string;
  ok: boolean;
  status: string;
  latency_ms?: number | null;
  detail: string;
  checked_url?: string | null;
  connectivity_status: "connected" | "disconnected" | "untested" | "testing";
}

export interface ModelProfileResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  provider_id: string;
  purpose: string;
  name: string;
  params_json: Record<string, unknown>;
  capability_tags?: string[];
  default_params?: Record<string, unknown>;
  cost_rate_limit?: Record<string, unknown>;
  guardrails?: Record<string, unknown>;
  routing_policy?: Record<string, unknown>;
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

export interface RoleProfileResponse {
  tenant_id: string;
  project_id: string;
  role_id: string;
  prompt_style: string;
  default_skills: string[];
  default_knowledge_scopes: string[];
  default_model_profile?: string | null;
  permissions: {
    can_import_data: boolean;
    can_publish_task: boolean;
    can_edit_global_knowledge: boolean;
    can_manage_model_router: boolean;
  };
  enabled: boolean;
  schema_version: string;
  updated_at?: string | null;
}

export interface SkillRegistryResponse {
  tenant_id: string;
  project_id: string;
  skill_id: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  required_knowledge_scopes: string[];
  default_model_profile?: string | null;
  tools_required: string[];
  ui_renderer: string;
  init_template?: string | null;
  enabled: boolean;
  schema_version: string;
  updated_at?: string | null;
}

export interface FeatureRouteMapResponse {
  tenant_id: string;
  project_id: string;
  route_id: string;
  path: string;
  component: string;
  feature_id: string;
  allowed_roles: string[];
  ui_mode: string;
  depends_on: string[];
  enabled: boolean;
  schema_version: string;
  updated_at?: string | null;
}

export interface RoleStudioResolveResponse {
  tenant_id: string;
  project_id: string;
  role_id: string;
  skill_id: string;
  resolved_model_profile: Record<string, unknown>;
  resolved_knowledge_scopes: string[];
  visible_routes: FeatureRouteMapResponse[];
  role_profile: RoleProfileResponse;
  skill_profile: SkillRegistryResponse;
}

export interface RoleStudioRunSkillResponse {
  tenant_id: string;
  project_id: string;
  role_id: string;
  skill_id: string;
  run_id: string;
  execution_mode: string;
  status: string;
  resolved_model_profile: Record<string, unknown>;
  resolved_knowledge_scopes: string[];
  output: Record<string, unknown>;
  logs: Array<Record<string, unknown>>;
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

export interface TelegramSettingsTestResponse {
  delivered: boolean;
  status_code?: number | null;
  latency_ms?: number | null;
  message: string;
  telegram_ok?: boolean | null;
}

export interface BootstrapDefaultsResponse {
  tenant_id: string;
  project_id: string;
  seed_mode: string;
  roles_upserted: number;
  skills_upserted: number;
  routes_upserted: number;
  language_settings_applied: boolean;
  stage_routing_applied: boolean;
  summary: Record<string, unknown>;
}

export interface RagCollectionResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  name: string;
  language_code?: string | null;
  description?: string | null;
  tags_json: string[];
  bind_type?: string | null;
  bind_id?: string | null;
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
  role_id?: string | null;
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

export interface KnowledgePackBootstrapResponse {
  pack_id: string;
  tenant_id: string;
  project_id: string;
  role_id: string;
  pack_name: string;
  collection_id: string;
  kb_version_id: string;
  scope: string;
  created_documents: number;
  chunk_count: number;
  extracted_terms: string[];
  updated_at?: string | null;
}

export interface KnowledgePackItemResponse {
  pack_id: string;
  tenant_id: string;
  project_id: string;
  role_id: string;
  pack_name: string;
  collection_id: string;
  kb_version_id: string;
  scope: string;
  status: string;
  created_documents: number;
  extracted_terms: string[];
  updated_at?: string | null;
}

export interface KnowledgeImportJobResponse {
  import_job_id: string;
  tenant_id: string;
  project_id: string;
  collection_id: string;
  kb_version_id?: string | null;
  source_name: string;
  source_format: string;
  status: string;
  created_documents: number;
  deduplicated_documents: number;
  chunk_count: number;
  extracted_terms: string[];
  affected_roles: string[];
  knowledge_change_report: Record<string, unknown>;
  updated_at?: string | null;
}

export interface UserListItem {
  id: string;
  email: string;
  display_name: string;
  role: string;
  created_at?: string | null;
}

export interface BootstrapPermissionsResponse {
  status: string;
  permissions_written: number;
  permissions: Array<{
    path_prefix: string;
    method: string;
    required_role: string;
  }>;
}

export interface EntityExtractionResponse {
  novel_id: string;
  entities_count: number;
  aliases_count: number;
  events_count: number;
  preview: Record<string, unknown>;
}

export interface NovelRagInitResponse {
  collection_id: string;
  novel_id: string;
  documents_created: number;
  chunks_total: number;
  status: string;
}

export interface CulturePackLlmExtractResponse {
  culture_pack_id: string;
  version: string;
  display_name: string;
  constraints: Record<string, unknown>;
  status: string;
}

export interface BootstrapAllResponse {
  status: string;
  steps: Array<{
    step: string;
    status: string;
    detail?: string;
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

export interface TimelinePatchHistoryItem {
  patch_id: string;
  patch_type: string;
  track?: string | null;
  shot_id?: string | null;
  patch_text?: string | null;
  parent_patch_id?: string | null;
  rollback_to_patch_id?: string | null;
  requested_by?: string | null;
  requested_at?: string | null;
  created_at: string;
}

export interface TimelinePatchRollbackResponse {
  run_id: string;
  rollback_patch_id: string;
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

export async function adminCreateUser(payload: {
  email: string;
  display_name: string;
  password: string;
  role: string;
  tg_chat_id?: string;
}): Promise<{
  user_id: string;
  email: string;
  display_name: string;
  role: string;
  tg_chat_id?: string;
}> {
  const { data } = await http.post("/api/v1/auth/admin/create-user", payload);
  return data;
}

export async function analyzeAutoRoutes(payload: {
  tenant_id: string;
  project_id: string;
  analyzer_provider_id?: string;
}): Promise<any> {
  const { data } = await http.post("/api/v1/config/auto-router/analyze", payload);
  return data;
}

export async function applyAutoRoutes(payload: {
  tenant_id: string;
  project_id: string;
  profiles: any[];
  routes: any[];
}): Promise<any> {
  const { data } = await http.post("/api/v1/config/auto-router/apply", payload);
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

export async function listUsers(tenantId?: string): Promise<UserListItem[]> {
  const { data } = await http.get<UserListItem[]>("/api/v1/auth/users", {
    params: tenantId ? { tenant_id: tenantId } : {},
  });
  return data;
}

export async function updateUser(
  userId: string,
  payload: { display_name?: string; role?: string },
  tenantId?: string
): Promise<UserListItem> {
  const { data } = await http.put<UserListItem>(`/api/v1/auth/users/${userId}`, payload, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });
  return data;
}

export async function deleteUser(userId: string, tenantId?: string): Promise<void> {
  await http.delete(`/api/v1/auth/users/${userId}`, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });
}

export async function resetUserPassword(userId: string, newPassword: string, tenantId?: string): Promise<void> {
  await http.post(`/api/v1/auth/users/${userId}/reset-password`, { new_password: newPassword }, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });
}

export async function initPermissions(
  tenantId?: string,
  projectId?: string
): Promise<BootstrapPermissionsResponse> {
  const { data } = await http.post<BootstrapPermissionsResponse>("/api/v1/auth/init-permissions", null, {
    params: {
      ...(tenantId ? { tenant_id: tenantId } : {}),
      ...(projectId ? { project_id: projectId } : {}),
    },
  });
  return data;
}

export async function extractNovelEntities(
  novelId: string,
  payload: {
    tenant_id: string;
    project_id: string;
    model_provider_id: string;
    chapter_ids?: string[];
  }
): Promise<EntityExtractionResponse> {
  const { data } = await http.post<EntityExtractionResponse>(`/api/v1/novels/${novelId}/extract-entities`, payload, {
    timeout: 120000,
  });
  return data;
}

export async function initNovelRag(
  collectionId: string,
  payload: {
    tenant_id: string;
    project_id: string;
    model_provider_id: string;
    novel_id: string;
    max_tokens?: number;
  }
): Promise<NovelRagInitResponse> {
  const { data } = await http.post<NovelRagInitResponse>(`/api/v1/rag/collections/${collectionId}/novel-init`, payload, {
    timeout: 120000,
  });
  return data;
}

export async function extractCulturePackLlm(payload: {
  tenant_id: string;
  project_id: string;
  model_provider_id: string;
  world_description: string;
  culture_pack_id?: string;
  display_name?: string;
}): Promise<CulturePackLlmExtractResponse> {
  const { data } = await http.post<CulturePackLlmExtractResponse>("/api/v1/culture-packs/llm-extract", payload, {
    timeout: 120000,
  });
  return data;
}

export async function bootstrapAll(payload: {
  tenant_id: string;
  project_id: string;
  model_provider_id?: string;
  force?: boolean;
}): Promise<BootstrapAllResponse> {
  const { data } = await http.post<BootstrapAllResponse>("/api/v1/init/bootstrap-all", payload, {
    timeout: 120000,
  });
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

export async function getChapter(chapterId: string): Promise<ChapterResponse> {
  const { data } = await http.get<ChapterResponse>(`/api/v1/chapters/${chapterId}`);
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

export async function assistExpandChapter(chapterId: string, payload: {
  tenant_id: string;
  project_id: string;
  model_provider_id: string;
  instruction?: string;
  style_hint?: string;
  target_language?: string;
  max_tokens?: number;
}): Promise<ChapterAssistExpandResponse> {
  const { data } = await http.post<ChapterAssistExpandResponse>(`/api/v1/chapters/${chapterId}/ai-expand`, payload, {
    timeout: 120000,  // AI 生成可能需要 60-90s，单独设置更长超时
  });
  return data;
}

export async function listAvailableModels(tenantId: string, projectId: string): Promise<{
  id: string;
  name: string;
  endpoint: string | null;
  auth_mode: string | null;
}[]> {
  const { data } = await http.get(`/api/v1/chapters/available-models`, {
    params: { tenant_id: tenantId, project_id: projectId },
  });
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

export async function getRunDetail(runId: string): Promise<RunDetailResponse> {
  const { data } = await http.get<RunDetailResponse>(`/api/v1/runs/${runId}`);
  return data;
}

export async function getRunPromptPlans(runId: string, params?: {
  limit?: number;
  offset?: number;
}): Promise<PromptPlanReplayItem[]> {
  const { data } = await http.get<PromptPlanReplayItem[]>(`/api/v1/runs/${runId}/prompt-plans`, { params });
  return data;
}

export async function getRunPolicyStacks(runId: string): Promise<PolicyStackReplayItem[]> {
  const { data } = await http.get<PolicyStackReplayItem[]>(`/api/v1/runs/${runId}/policy-stacks`);
  return data;
}

export async function initRunTracks(
  runId: string,
  payload: { track_types?: string[]; recreate?: boolean },
): Promise<InitTracksResponse> {
  const { data } = await http.post<InitTracksResponse>(`/api/v1/runs/${runId}/tracks/init`, payload);
  return data;
}

export async function listRunTracks(runId: string): Promise<TrackSummary[]> {
  const { data } = await http.get<TrackSummary[]>(`/api/v1/runs/${runId}/tracks`);
  return data;
}

export async function listRunTrackUnits(runId: string, trackType: string): Promise<TrackUnitItem[]> {
  const { data } = await http.get<TrackUnitItem[]>(`/api/v1/runs/${runId}/tracks/${trackType}/units`);
  return data;
}

export async function runTrack(
  runId: string,
  trackType: string,
  payload: { unit_ids?: string[]; only_failed?: boolean; force?: boolean } = {},
): Promise<RunTrackResponse> {
  const { data } = await http.post<RunTrackResponse>(`/api/v1/runs/${runId}/tracks/${trackType}/run`, payload);
  return data;
}

export async function retryTrackUnit(
  runId: string,
  unitId: string,
  payload: { patch?: Record<string, unknown> } = {},
): Promise<RetryTrackUnitResponse> {
  const { data } = await http.post<RetryTrackUnitResponse>(
    `/api/v1/runs/${runId}/tracks/units/${unitId}/retry`,
    payload,
  );
  return data;
}

export async function listTrackUnitAttempts(runId: string, unitId: string): Promise<TrackUnitAttemptResponse[]> {
  const { data } = await http.get<TrackUnitAttemptResponse[]>(
    `/api/v1/runs/${runId}/tracks/units/${unitId}/attempts`,
  );
  return data;
}

export async function selectTrackUnitCandidate(
  runId: string,
  unitId: string,
  payload: { artifact_id?: string; candidate_index?: number } = {},
): Promise<SelectTrackUnitCandidateResponse> {
  const { data } = await http.post<SelectTrackUnitCandidateResponse>(
    `/api/v1/runs/${runId}/tracks/units/${unitId}/select-candidate`,
    payload,
  );
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

export async function getOpsCapabilityStandards(): Promise<CapabilityStandardsResponse> {
  const { data } = await http.get<CapabilityStandardsResponse>("/api/v1/ops-bridge/capability-standards");
  return data;
}

export async function getOpsAdapterSpec(): Promise<AdapterSpecResponse> {
  const { data } = await http.get<AdapterSpecResponse>("/api/v1/ops-bridge/adapter-spec");
  return data;
}

export async function getOpsStorageConfig(): Promise<OpsStorageConfigResponse> {
  const { data } = await http.get<OpsStorageConfigResponse>("/api/v1/ops-bridge/storage-config");
  return data;
}

export async function getRequirementTiers(): Promise<RequirementTiersResponse> {
  const { data } = await http.get<RequirementTiersResponse>("/api/v1/requirements/tiers");
  return data;
}

export async function getRequirementSchema(): Promise<RequirementSchemaResponse> {
  const { data } = await http.get<RequirementSchemaResponse>("/api/v1/requirements/schema");
  return data;
}

export async function createOpsPlan(payload: OpsPlanRequestPayload): Promise<OpsPlanResponse> {
  const { data } = await http.post<OpsPlanResponse>("/api/v1/ops/plan", payload);
  return data;
}

export async function listOpsIntegrations(params: {
  tenant_id: string;
  project_id: string;
  capability_type?: string;
}): Promise<OpsIntegrationListResponse> {
  const { data } = await http.get<OpsIntegrationListResponse>("/api/v1/ops/integrations", { params });
  return data;
}

export async function rollbackOpsIntegration(
  integrationId: string,
  payload: { tenant_id: string; project_id: string },
): Promise<{ integration: OpsIntegrationVersion; status: string }> {
  const { data } = await http.post<{ integration: OpsIntegrationVersion; status: string }>(
    `/api/v1/ops/integrations/${integrationId}/rollback`,
    payload,
  );
  return data;
}

export async function getOpsRuntimeRouting(params: {
  tenant_id: string;
  project_id: string;
}): Promise<RuntimeRoutingViewResponse> {
  const { data } = await http.get<RuntimeRoutingViewResponse>("/api/v1/ops/runtime-routing", { params });
  return data;
}

export async function applyOpsRuntimeRouting(payload: {
  tenant_id: string;
  project_id: string;
  integration_id: string;
}): Promise<RuntimeRoutingViewResponse> {
  const { data } = await http.post<RuntimeRoutingViewResponse>("/api/v1/ops/runtime-routing/apply", payload);
  return data;
}

export async function quickRunOpsIntegration(payload: {
  tenant_id: string;
  project_id: string;
  integration_id?: string;
  capability_type?: string;
  sample_input?: Record<string, unknown>;
  probe_connectivity?: boolean;
}): Promise<QuickRunResponse> {
  const { data } = await http.post<QuickRunResponse>("/api/v1/ops/quick-run", payload);
  return data;
}

export async function updateOpsStorageConfig(
  payload: OpsStorageConfigUpdatePayload,
): Promise<OpsStorageConfigResponse> {
  const { data } = await http.put<OpsStorageConfigResponse>("/api/v1/ops-bridge/storage-config", payload);
  return data;
}

export async function getOpsToken(params: {
  tenant_id: string;
  project_id: string;
  name?: string;
}): Promise<OpsTokenResponse> {
  const { data } = await http.get<OpsTokenResponse>("/api/v1/ops-bridge/token", { params });
  return data;
}

export async function revealOpsToken(payload: {
  tenant_id: string;
  project_id: string;
  name?: string;
}): Promise<OpsTokenRevealResponse> {
  const { data } = await http.post<OpsTokenRevealResponse>("/api/v1/ops-bridge/token/reveal", payload);
  return data;
}

export async function regenerateOpsToken(payload: {
  tenant_id: string;
  project_id: string;
  name?: string;
}): Promise<OpsTokenRevealResponse> {
  const { data } = await http.post<OpsTokenRevealResponse>("/api/v1/ops-bridge/token/regenerate", payload);
  return data;
}

export async function reportOpsProvider(
  payload: OpsProviderReportPayload,
  opsToken: string,
): Promise<OpsProviderReportUpsertResponse> {
  const { data } = await http.post<OpsProviderReportUpsertResponse>(
    "/api/v1/ops-bridge/report",
    payload,
    {
      headers: {
        "X-AinerOps-Token": opsToken,
      },
    },
  );
  return data;
}

export async function listOpsProviders(params: {
  tenant_id: string;
  project_id: string;
  capability_type?: string;
  integration_status?: string;
}): Promise<OpsProviderListResponse> {
  const { data } = await http.get<OpsProviderListResponse>("/api/v1/ops-bridge/providers", { params });
  return data;
}

export async function autoBindOpsProvider(reportId: string): Promise<OpsProviderRow> {
  const { data } = await http.post<OpsProviderRow>(`/api/v1/ops-bridge/providers/${reportId}/auto-bind`);
  return data;
}

export async function manualBindOpsProvider(
  reportId: string,
  payload: { provider_id?: string | null; integration_notes?: string },
): Promise<OpsProviderRow> {
  const { data } = await http.post<OpsProviderRow>(`/api/v1/ops-bridge/providers/${reportId}/manual-bind`, payload);
  return data;
}

export async function testOpsProvider(reportId: string): Promise<OpsProviderTestResponse> {
  const { data } = await http.post<OpsProviderTestResponse>(`/api/v1/ops-bridge/providers/${reportId}/test`);
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
  capability_tags?: string[];
  default_params?: Record<string, unknown>;
  cost_rate_limit?: Record<string, unknown>;
  guardrails?: Record<string, unknown>;
  routing_policy?: Record<string, unknown>;
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

export async function upsertRoleProfile(roleId: string, payload: {
  tenant_id: string;
  project_id: string;
  role_id: string;
  prompt_style: string;
  default_skills: string[];
  default_knowledge_scopes: string[];
  default_model_profile?: string;
  permissions: {
    can_import_data: boolean;
    can_publish_task: boolean;
    can_edit_global_knowledge: boolean;
    can_manage_model_router: boolean;
  };
  enabled?: boolean;
  schema_version?: string;
}): Promise<RoleProfileResponse> {
  const { data } = await http.put<RoleProfileResponse>(`/api/v1/config/role-profiles/${roleId}`, payload);
  return data;
}

export async function listRoleProfiles(params: {
  tenant_id: string;
  project_id: string;
  keyword?: string;
}): Promise<RoleProfileResponse[]> {
  const { data } = await http.get<RoleProfileResponse[]>("/api/v1/config/role-profiles", { params });
  return data;
}

export async function deleteRoleProfile(roleId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<void> {
  await http.delete(`/api/v1/config/role-profiles/${roleId}`, { params });
}

export async function upsertSkillRegistry(skillId: string, payload: {
  tenant_id: string;
  project_id: string;
  skill_id: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  required_knowledge_scopes?: string[];
  default_model_profile?: string;
  tools_required?: string[];
  ui_renderer?: string;
  init_template?: string;
  enabled?: boolean;
  schema_version?: string;
}): Promise<SkillRegistryResponse> {
  const { data } = await http.put<SkillRegistryResponse>(`/api/v1/config/skill-registry/${skillId}`, payload);
  return data;
}

export async function listSkillRegistry(params: {
  tenant_id: string;
  project_id: string;
  keyword?: string;
}): Promise<SkillRegistryResponse[]> {
  const { data } = await http.get<SkillRegistryResponse[]>("/api/v1/config/skill-registry", { params });
  return data;
}

export async function deleteSkillRegistry(skillId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<void> {
  await http.delete(`/api/v1/config/skill-registry/${skillId}`, { params });
}

export async function upsertFeatureRouteMap(routeId: string, payload: {
  tenant_id: string;
  project_id: string;
  route_id: string;
  path: string;
  component: string;
  feature_id: string;
  allowed_roles?: string[];
  ui_mode?: string;
  depends_on?: string[];
  enabled?: boolean;
  schema_version?: string;
}): Promise<FeatureRouteMapResponse> {
  const { data } = await http.put<FeatureRouteMapResponse>(`/api/v1/config/feature-route-maps/${routeId}`, payload);
  return data;
}

export async function listFeatureRouteMaps(params: {
  tenant_id: string;
  project_id: string;
  role_id?: string;
  keyword?: string;
}): Promise<FeatureRouteMapResponse[]> {
  const { data } = await http.get<FeatureRouteMapResponse[]>("/api/v1/config/feature-route-maps", { params });
  return data;
}

export async function deleteFeatureRouteMap(routeId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<void> {
  await http.delete(`/api/v1/config/feature-route-maps/${routeId}`, { params });
}

export async function resolveRoleStudioRuntime(payload: {
  tenant_id: string;
  project_id: string;
  role_id: string;
  skill_id: string;
  context?: Record<string, unknown>;
}): Promise<RoleStudioResolveResponse> {
  const { data } = await http.post<RoleStudioResolveResponse>("/api/v1/config/role-studio/resolve", payload);
  return data;
}

export async function runRoleStudioSkill(payload: {
  tenant_id: string;
  project_id: string;
  role_id: string;
  skill_id: string;
  input_payload?: Record<string, unknown>;
  context?: Record<string, unknown>;
  run_id?: string;
  trace_id?: string;
  correlation_id?: string;
  idempotency_key?: string;
  schema_version?: string;
}): Promise<RoleStudioRunSkillResponse> {
  const { data } = await http.post<RoleStudioRunSkillResponse>("/api/v1/config/role-studio/run-skill", payload);
  return data;
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

export async function getStageRouting(tenantId: string, projectId: string): Promise<StageRoutingResponse> {
  const { data } = await http.get<StageRoutingResponse>("/api/v1/config/stage-routing", {
    params: { tenant_id: tenantId, project_id: projectId },
  });
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

export async function testTelegramSettings(payload: {
  tenant_id: string;
  project_id: string;
  message_text?: string;
  bot_token?: string;
  chat_id?: string;
  thread_id?: string;
  parse_mode?: string;
  timeout_ms?: number;
}): Promise<TelegramSettingsTestResponse> {
  const { data } = await http.post<TelegramSettingsTestResponse>("/api/v1/config/telegram-settings/test", payload);
  return data;
}

export async function bootstrapDefaults(payload: {
  tenant_id: string;
  project_id: string;
  seed_mode?: string;
  model_profile_id?: string;
  role_ids?: string[];
  enrich_rounds?: number;
  session_id?: string;
  include_roles?: boolean;
  include_skills?: boolean;
  include_routes?: boolean;
  include_language_settings?: boolean;
  include_stage_routing?: boolean;
}): Promise<BootstrapDefaultsResponse> {
  const { data } = await http.post<BootstrapDefaultsResponse>("/api/v1/config/bootstrap-defaults", payload);
  return data;
}

export async function createRagCollection(payload: {
  tenant_id: string;
  project_id: string;
  name: string;
  language_code?: string;
  description?: string;
  tags_json?: string[];
  bind_type?: string;
  bind_id?: string;
}): Promise<RagCollectionResponse> {
  const { data } = await http.post<RagCollectionResponse>("/api/v1/rag/collections", payload);
  return data;
}

export async function listRagCollections(params: {
  tenant_id: string;
  project_id: string;
  keyword?: string;
  language_code?: string;
  bind_type?: string;
  bind_id?: string;
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
  role_id?: string;
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

export async function bootstrapKnowledgePack(payload: {
  tenant_id: string;
  project_id: string;
  role_id: string;
  pack_name?: string;
  template_key?: string;
  language_code?: string;
  default_knowledge_scope?: string;
}): Promise<KnowledgePackBootstrapResponse> {
  const { data } = await http.post<KnowledgePackBootstrapResponse>("/api/v1/rag/knowledge-packs/bootstrap", payload);
  return data;
}

export async function listKnowledgePacks(params: {
  tenant_id: string;
  project_id: string;
  role_id?: string;
}): Promise<KnowledgePackItemResponse[]> {
  const { data } = await http.get<KnowledgePackItemResponse[]>("/api/v1/rag/knowledge-packs", { params });
  return data;
}

export async function createKnowledgeImportJob(payload: {
  tenant_id: string;
  project_id: string;
  collection_id: string;
  kb_version_id?: string;
  source_format?: string;
  source_name: string;
  content_text: string;
  role_ids?: string[];
  language_code?: string;
  scope?: string;
}): Promise<KnowledgeImportJobResponse> {
  const { data } = await http.post<KnowledgeImportJobResponse>("/api/v1/rag/import-jobs", payload);
  return data;
}

export async function listKnowledgeImportJobs(params: {
  tenant_id: string;
  project_id: string;
  role_id?: string;
}): Promise<KnowledgeImportJobResponse[]> {
  const { data } = await http.get<KnowledgeImportJobResponse[]>("/api/v1/rag/import-jobs", { params });
  return data;
}

export interface BinaryImportJobResponse {
  import_job_id: string;
  tenant_id: string;
  project_id: string;
  collection_id: string;
  file_name: string;
  file_format: string;
  file_size_bytes: number;
  status: string;
  progress_percent: number;
  extracted_text_preview: string;
  extracted_pages: number;
  extracted_tables: number;
  extracted_images: number;
  error_message?: string | null;
}

export async function uploadBinaryFileForImport(
  collectionId: string,
  file: File,
  params: {
    tenant_id: string;
    project_id: string;
    model_provider_id?: string;
    use_vision?: boolean;
  }
): Promise<BinaryImportJobResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await http.post<BinaryImportJobResponse>(
    `/api/v1/rag/collections/${collectionId}/binary-import`,
    formData,
    {
      params: {
        tenant_id: params.tenant_id,
        project_id: params.project_id,
        ...(params.model_provider_id ? { model_provider_id: params.model_provider_id } : {}),
        ...(params.use_vision !== undefined ? { use_vision: params.use_vision } : {}),
      },
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120000,
    }
  );
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

export async function listRunTimelinePatches(runId: string, limit = 50): Promise<TimelinePatchHistoryItem[]> {
  const { data } = await http.get<TimelinePatchHistoryItem[]>(`/api/v1/runs/${runId}/timeline/patches`, {
    params: { limit },
  });
  return data;
}

export async function rollbackRunTimelinePatch(
  runId: string,
  patchId: string,
  payload: {
    tenant_id: string;
    project_id: string;
    requested_by?: string;
  }
): Promise<TimelinePatchRollbackResponse> {
  const { data } = await http.post<TimelinePatchRollbackResponse>(
    `/api/v1/runs/${runId}/timeline/patches/${patchId}/rollback`,
    payload
  );
  return data;
}

// Novel CRUD extensions
export async function updateNovel(novelId: string, payload: {
  tenant_id?: string;
  project_id?: string;
  title?: string;
  summary?: string;
  default_language_code?: string;
}): Promise<NovelResponse> {
  const { data } = await http.put<NovelResponse>(`/api/v1/novels/${novelId}`, payload);
  return data;
}

export async function deleteNovel(novelId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<{ status: string }> {
  const { data } = await http.delete<{ status: string }>(`/api/v1/novels/${novelId}`, { params });
  return data;
}

export async function deleteChapter(chapterId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<{ status: string }> {
  const { data } = await http.delete<{ status: string }>(`/api/v1/chapters/${chapterId}`, { params });
  return data;
}

export async function getNovelTeam(novelId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<NovelTeamResponse> {
  const { data } = await http.get<NovelTeamResponse>(`/api/v1/novels/${novelId}/team`, { params });
  return data;
}

export async function setNovelTeam(novelId: string, payload: {
  tenant_id: string;
  project_id: string;
  team: Record<string, NovelTeamMember>;
}): Promise<NovelTeamResponse> {
  const { data } = await http.put<NovelTeamResponse>(`/api/v1/novels/${novelId}/team`, payload);
  return data;
}

// ── Translation Project Types ─────────────────────────────────────────────────
export interface TranslationProjectResponse {
  id: string;
  novel_id: string;
  source_language_code: string;
  target_language_code: string;
  status: "draft" | "in_progress" | "completed" | "archived";
  consistency_mode: "strict" | "balanced" | "free";
  model_provider_id: string | null;
  term_dictionary_json: Record<string, string> | null;
  stats_json: Record<string, unknown> | null;
  scope_mode: string;
  scope_payload: Record<string, unknown> | null;
  granularity: string;
  batch_size: number;
  max_cost: number | null;
  max_tokens: number | null;
  run_policy: string;
  culture_mode: string;
  culture_packs: Array<Record<string, unknown>> | null;
  temporal_enabled: boolean;
  temporal_layers: Array<Record<string, unknown>> | null;
  temporal_detect_policy: string;
  naming_policy_by_lang: Record<string, string> | null;
  auto_fill_missing_names: boolean;
  created_at: string;
}

export interface TranslationPlanItemResponse {
  id: string;
  scope_type: string;
  chapter_id: string | null;
  scene_id: string | null;
  segment_id: string | null;
  order_no: number;
  item_status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  retry_count: number;
  last_error: string | null;
  last_run_id: string | null;
}

export interface ScriptBlockResponse {
  id: string;
  chapter_id: string;
  seq_no: number;
  block_type: "narration" | "dialogue" | "action" | "heading" | "scene_break";
  source_text: string;
  speaker_tag: string | null;
  translation: TranslationBlockItemResponse | null;
}

export interface TranslationBlockItemResponse {
  id: string;
  translated_text: string | null;
  status: "draft" | "reviewed" | "locked";
  translation_notes: string | null;
}

export interface EntityNameVariantResponse {
  id: string;
  source_name: string;
  canonical_target_name: string;
  is_locked: boolean;
  aliases_json: string[] | null;
  entity_id: string | null;
}

export interface ConsistencyWarningResponse {
  id: string;
  warning_type: "name_drift" | "new_variant" | "cross_chapter";
  source_name: string;
  detected_variant: string;
  expected_canonical: string | null;
  status: "open" | "resolved" | "ignored";
  translation_block_id: string | null;
}

export interface TranslationRunGateResponse {
  ready_to_run: boolean;
  chapter_id: string | null;
  missing: string[];
  stale: string[];
  recommended_actions: string[];
  disabled_reason: string | null;
}

export interface TranslationCreateRunResponse {
  run_id: string | null;
  status: string;
  chapter_id: string | null;
  gate: TranslationRunGateResponse;
  message: string | null;
}

// ── Translation Project Functions ─────────────────────────────────────────────
export async function createTranslationProject(payload: {
  tenant_id?: string;
  project_id?: string;
  novel_id: string;
  source_language_code: string;
  target_language_code: string;
  model_provider_id?: string | null;
  consistency_mode?: string;
  term_dictionary_json?: Record<string, string> | null;
  scope_mode?: string;
  scope_payload?: Record<string, unknown> | null;
  granularity?: string;
  batch_size?: number;
  max_cost?: number | null;
  max_tokens?: number | null;
  run_policy?: string;
  culture_mode?: string;
  culture_packs?: Array<Record<string, unknown>> | null;
  temporal_enabled?: boolean;
  temporal_layers?: Array<Record<string, unknown>> | null;
  temporal_detect_policy?: string;
  naming_policy_by_lang?: Record<string, string> | null;
  auto_fill_missing_names?: boolean;
}): Promise<TranslationProjectResponse> {
  const { data } = await http.post<TranslationProjectResponse>(
    "/api/v1/translations/projects",
    payload,
  );
  return data;
}

export async function listTranslationProjects(params: {
  novel_id?: string;
  tenant_id?: string;
  project_id?: string;
  status?: string;
}): Promise<TranslationProjectResponse[]> {
  const { data } = await http.get<TranslationProjectResponse[]>(
    "/api/v1/translations/projects",
    { params },
  );
  return data;
}

export async function updateTranslationProject(
  projectId: string,
  payload: {
    term_dictionary_json?: Record<string, string> | null;
    consistency_mode?: string;
    model_provider_id?: string | null;
    status?: string;
    scope_mode?: string;
    scope_payload?: Record<string, unknown> | null;
    granularity?: string;
    batch_size?: number;
    max_cost?: number | null;
    max_tokens?: number | null;
    run_policy?: string;
    culture_mode?: string;
    culture_packs?: Array<Record<string, unknown>> | null;
    temporal_enabled?: boolean;
    temporal_layers?: Array<Record<string, unknown>> | null;
    temporal_detect_policy?: string;
    naming_policy_by_lang?: Record<string, string> | null;
    auto_fill_missing_names?: boolean;
  },
): Promise<TranslationProjectResponse> {
  const { data } = await http.put<TranslationProjectResponse>(
    `/api/v1/translations/projects/${projectId}`,
    payload,
  );
  return data;
}

export async function deleteTranslationProject(projectId: string): Promise<{ status: string }> {
  const { data } = await http.delete<{ status: string }>(`/api/v1/translations/projects/${projectId}`);
  return data;
}

export async function segmentChapters(
  projectId: string,
  payload: { tenant_id?: string; project_id?: string; chapter_id?: string | null },
): Promise<{ blocks_created: number }> {
  const { data } = await http.post<{ blocks_created: number }>(
    `/api/v1/translations/projects/${projectId}/segment`,
    payload,
  );
  return data;
}

export async function translateBlocks(
  projectId: string,
  payload: {
    tenant_id?: string;
    project_id?: string;
    chapter_id?: string | null;
    script_block_ids?: string[] | null;
    model_provider_id?: string | null;
    batch_size?: number;
  },
): Promise<{ translated: number; warnings: number }> {
  const { data } = await http.post<{ translated: number; warnings: number }>(
    `/api/v1/translations/projects/${projectId}/translate`,
    payload,
    { timeout: 120000 },
  );
  return data;
}

export async function deleteTranslationBlock(
  projectId: string,
  blockId: string,
): Promise<void> {
  await http.delete(`/api/v1/translations/projects/${projectId}/blocks/${blockId}`);
}

export async function listScriptBlocks(
  projectId: string,
  params: { tenant_id?: string; project_id?: string; chapter_id?: string | null },
): Promise<ScriptBlockResponse[]> {
  const { data } = await http.get<ScriptBlockResponse[]>(
    `/api/v1/translations/projects/${projectId}/blocks`,
    { params },
  );
  return data;
}

export async function updateTranslationBlock(
  projectId: string,
  blockId: string,
  payload: {
    translated_text?: string;
    status?: string;
    translation_notes?: string;
  },
): Promise<TranslationBlockItemResponse> {
  const { data } = await http.patch<TranslationBlockItemResponse>(
    `/api/v1/translations/projects/${projectId}/blocks/${blockId}`,
    payload,
  );
  return data;
}

export async function listEntityVariants(
  projectId: string,
  params: { tenant_id?: string; project_id?: string },
): Promise<EntityNameVariantResponse[]> {
  const { data } = await http.get<EntityNameVariantResponse[]>(
    `/api/v1/translations/projects/${projectId}/entities`,
    { params },
  );
  return data;
}

export async function createEntityVariant(
  projectId: string,
  payload: {
    tenant_id?: string;
    project_id?: string;
    source_name: string;
    canonical_target_name: string;
    aliases_json?: string[];
    entity_id?: string;
  },
): Promise<EntityNameVariantResponse> {
  const { data } = await http.post<EntityNameVariantResponse>(
    `/api/v1/translations/projects/${projectId}/entities`,
    payload,
  );
  return data;
}

export async function lockEntityVariant(
  projectId: string,
  variantId: string,
  payload: { canonical_target_name: string },
): Promise<EntityNameVariantResponse> {
  const { data } = await http.patch<EntityNameVariantResponse>(
    `/api/v1/translations/projects/${projectId}/entities/${variantId}/lock`,
    payload,
  );
  return data;
}

export async function listConsistencyWarnings(
  projectId: string,
  params: { tenant_id?: string; status?: string },
): Promise<ConsistencyWarningResponse[]> {
  const { data } = await http.get<ConsistencyWarningResponse[]>(
    `/api/v1/translations/projects/${projectId}/warnings`,
    { params },
  );
  return data;
}

export async function resolveWarning(
  projectId: string,
  warningId: string,
  payload: { status: "resolved" | "ignored" },
): Promise<ConsistencyWarningResponse> {
  const { data } = await http.patch<ConsistencyWarningResponse>(
    `/api/v1/translations/projects/${projectId}/warnings/${warningId}`,
    payload,
  );
  return data;
}

export async function checkConsistency(projectId: string): Promise<{ warnings_created: number }> {
  const { data } = await http.post<{ warnings_created: number }>(
    `/api/v1/translations/projects/${projectId}/check-consistency`,
  );
  return data;
}

export async function listTranslationPlanItems(
  projectId: string,
  params?: { status?: string },
): Promise<TranslationPlanItemResponse[]> {
  const { data } = await http.get<TranslationPlanItemResponse[]>(
    `/api/v1/translations/projects/${projectId}/plan`,
    { params },
  );
  return data;
}

export async function executeTranslationPlan(
  projectId: string,
  payload: {
    batch_size?: number;
    only_failed?: boolean;
    only_pending?: boolean;
    only_untranslated?: boolean;
    selected_item_ids?: string[];
    model_provider_id?: string | null;
  },
): Promise<{ executed: number; succeeded: number; failed: number; warnings: number }> {
  const { data } = await http.post<{ executed: number; succeeded: number; failed: number; warnings: number }>(
    `/api/v1/translations/projects/${projectId}/plan/execute`,
    payload,
    { timeout: 120000 },
  );
  return data;
}

export async function gateTranslationProjectRun(
  projectId: string,
  payload: { chapter_id?: string | null },
): Promise<TranslationRunGateResponse> {
  const { data } = await http.post<TranslationRunGateResponse>(
    `/api/v1/translations/projects/${projectId}/run-gate`,
    payload,
  );
  return data;
}

export async function createRunFromTranslationProject(
  projectId: string,
  payload: {
    tenant_id?: string;
    project_id?: string;
    chapter_id?: string | null;
    requested_quality?: string;
    language_context?: string | null;
    force_rerun?: boolean;
    use_cache?: boolean;
    dry_run?: boolean;
  },
): Promise<TranslationCreateRunResponse> {
  const { data } = await http.post<TranslationCreateRunResponse>(
    `/api/v1/translations/projects/${projectId}/create-run`,
    payload,
  );
  return data;
}

export async function deleteTranslationJob(
  jobId: string,
  params?: { delete_with_artifacts?: boolean },
): Promise<{ deleted: boolean; job_id: string }> {
  const { data } = await http.delete<{ deleted: boolean; job_id: string }>(
    `/api/v1/translation_jobs/${jobId}`,
    { params },
  );
  return data;
}

export async function batchDeleteTranslationJobs(payload: {
  job_ids: string[];
  delete_with_artifacts?: boolean;
}): Promise<{ deleted: number; skipped: number }> {
  const { data } = await http.post<{ deleted: number; skipped: number }>(
    "/api/v1/translation_jobs/batch_delete",
    payload,
  );
  return data;
}

export async function cancelTranslationJob(jobId: string): Promise<{ canceled: boolean; job_id: string }> {
  const { data } = await http.post<{ canceled: boolean; job_id: string }>(
    `/api/v1/translation_jobs/${jobId}/cancel`,
  );
  return data;
}

export async function batchCancelTranslationJobs(payload: {
  job_ids: string[];
}): Promise<{ canceled: number; skipped: number }> {
  const { data } = await http.post<{ canceled: number; skipped: number }>(
    "/api/v1/translation_jobs/batch_cancel",
    payload,
  );
  return data;
}

export async function batchRetryTranslationJobs(payload: {
  job_ids: string[];
}): Promise<{ retried: number; skipped: number }> {
  const { data } = await http.post<{ retried: number; skipped: number }>(
    "/api/v1/translation_jobs/batch_retry",
    payload,
  );
  return data;
}

export async function listTranslationConflicts(
  projectId: string,
  params?: { lang?: string },
): Promise<ConsistencyWarningResponse[]> {
  const { data } = await http.get<ConsistencyWarningResponse[]>(
    `/api/v1/translations/projects/${projectId}/conflicts`,
    { params },
  );
  return data;
}

export async function listTranslationDrift(
  projectId: string,
  params?: { lang?: string },
): Promise<Array<Record<string, unknown>>> {
  const { data } = await http.get<Array<Record<string, unknown>>>(
    `/api/v1/translations/projects/${projectId}/drift`,
    { params },
  );
  return data;
}

export interface EffectiveKBItem {
  collection_id: string;
  collection_name: string;
  bind_type: string;
  bind_id?: string | null;
  priority: number;
}

export interface EffectiveKBResponse {
  persona_pack_id: string;
  role_id?: string | null;
  novel_id?: string | null;
  effective_collections: EffectiveKBItem[];
}

export async function getEffectiveKb(params: {
  tenant_id: string;
  project_id: string;
  persona_pack_id: string;
  novel_id?: string;
}): Promise<EffectiveKBResponse> {
  const { data } = await http.get<EffectiveKBResponse>("/api/v1/rag/effective-kb", { params });
  return data;
}

// ── KBPack Asset Center Types ──────────────────────────────────────────────────

export interface KBPackResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  name: string;
  description?: string | null;
  language_code?: string | null;
  culture_pack?: string | null;
  version_name: string;
  status: string; // draft | embedded | published | deprecated
  tags_json: string[];
  bind_suggestions_json: string[];
  collection_id?: string | null;
  created_at?: string | null;
}

export interface KBSourceResponse {
  id: string;
  kb_pack_id: string;
  source_type: string;
  source_name?: string | null;
  source_uri?: string | null;
  parse_status: string;
  chunk_count: number;
  created_at?: string | null;
}

export interface KBMapEntry {
  id: string;
  kb_pack_id: string;
  kb_pack_name?: string | null;
  priority: number;
  enabled: boolean;
  note?: string | null;
  created_at?: string | null;
}

export interface KBEffectiveEntry {
  kb_pack_id: string;
  kb_pack_name: string;
  collection_id?: string | null;
  source: string; // novel | role | persona
  priority: number;
  enabled: boolean;
}

export interface KBEffectiveResponse {
  persona_pack_id: string;
  role_id?: string | null;
  novel_id?: string | null;
  effective_packs: KBEffectiveEntry[];
}

// ── KBPack CRUD ────────────────────────────────────────────────────────────────

export async function createKBPack(payload: {
  tenant_id: string;
  project_id: string;
  name: string;
  description?: string;
  language_code?: string;
  culture_pack?: string;
  version_name?: string;
  tags_json?: string[];
  bind_suggestions_json?: string[];
}): Promise<KBPackResponse> {
  const { data } = await http.post<KBPackResponse>("/api/v1/kb/packs", payload);
  return data;
}

export async function listKBPacks(params: {
  tenant_id: string;
  project_id: string;
  keyword?: string;
  language_code?: string;
  culture_pack?: string;
  status?: string;
}): Promise<KBPackResponse[]> {
  const { data } = await http.get<KBPackResponse[]>("/api/v1/kb/packs", { params });
  return data;
}

export async function getKBPack(packId: string): Promise<KBPackResponse> {
  const { data } = await http.get<KBPackResponse>(`/api/v1/kb/packs/${packId}`);
  return data;
}

export async function updateKBPack(packId: string, payload: {
  name?: string;
  description?: string;
  language_code?: string;
  culture_pack?: string;
  version_name?: string;
  status?: string;
  tags_json?: string[];
  bind_suggestions_json?: string[];
}): Promise<KBPackResponse> {
  const { data } = await http.put<KBPackResponse>(`/api/v1/kb/packs/${packId}`, payload);
  return data;
}

export async function deleteKBPack(packId: string, params: {
  tenant_id: string;
  project_id: string;
  force?: boolean;
}): Promise<void> {
  await http.delete(`/api/v1/kb/packs/${packId}`, { params });
}

export async function uploadKBSource(
  packId: string,
  file: File,
  params: {
    tenant_id: string;
    project_id: string;
    bind_role_ids?: string;
  }
): Promise<KBSourceResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await http.post<KBSourceResponse>(
    `/api/v1/kb/packs/${packId}/upload-source`,
    formData,
    {
      params,
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120000,
    }
  );
  return data;
}

export async function listKBSources(packId: string): Promise<KBSourceResponse[]> {
  const { data } = await http.get<KBSourceResponse[]>(`/api/v1/kb/packs/${packId}/sources`);
  return data;
}

export async function triggerKBEmbed(packId: string, params: {
  tenant_id: string;
  project_id: string;
}): Promise<{ kb_pack_id: string; status: string; message: string }> {
  const { data } = await http.post(`/api/v1/kb/packs/${packId}/embed`, null, { params });
  return data;
}

// ── Binding CRUD — Role ────────────────────────────────────────────────────────

export async function createRoleKBBinding(roleId: string, payload: {
  tenant_id: string;
  project_id: string;
  kb_pack_id: string;
  priority?: number;
  enabled?: boolean;
  note?: string;
}): Promise<KBMapEntry> {
  const { data } = await http.post<KBMapEntry>(`/api/v1/kb/bindings/role`, payload, {
    params: { role_id: roleId },
  });
  return data;
}

export async function listRoleKBBindings(params: {
  tenant_id: string;
  project_id: string;
  role_id: string;
}): Promise<KBMapEntry[]> {
  const { data } = await http.get<KBMapEntry[]>("/api/v1/kb/bindings/role", { params });
  return data;
}

export async function updateRoleKBBinding(bindingId: string, payload: {
  priority?: number;
  enabled?: boolean;
  note?: string;
}): Promise<KBMapEntry> {
  const { data } = await http.put<KBMapEntry>(`/api/v1/kb/bindings/role/${bindingId}`, payload);
  return data;
}

export async function deleteRoleKBBinding(bindingId: string): Promise<void> {
  await http.delete(`/api/v1/kb/bindings/role/${bindingId}`);
}

// ── Binding CRUD — Persona ─────────────────────────────────────────────────────

export async function createPersonaKBBinding(personaPackId: string, payload: {
  tenant_id: string;
  project_id: string;
  kb_pack_id: string;
  priority?: number;
  enabled?: boolean;
  note?: string;
}): Promise<KBMapEntry> {
  const { data } = await http.post<KBMapEntry>("/api/v1/kb/bindings/persona", payload, {
    params: { persona_pack_id: personaPackId },
  });
  return data;
}

export async function listPersonaKBBindings(params: {
  tenant_id: string;
  project_id: string;
  persona_pack_id: string;
}): Promise<KBMapEntry[]> {
  const { data } = await http.get<KBMapEntry[]>("/api/v1/kb/bindings/persona", { params });
  return data;
}

export async function updatePersonaKBBinding(bindingId: string, payload: {
  priority?: number;
  enabled?: boolean;
  note?: string;
}): Promise<KBMapEntry> {
  const { data } = await http.put<KBMapEntry>(`/api/v1/kb/bindings/persona/${bindingId}`, payload);
  return data;
}

export async function deletePersonaKBBinding(bindingId: string): Promise<void> {
  await http.delete(`/api/v1/kb/bindings/persona/${bindingId}`);
}

// ── Binding CRUD — Novel ───────────────────────────────────────────────────────

export async function createNovelKBBinding(novelId: string, payload: {
  tenant_id: string;
  project_id: string;
  kb_pack_id: string;
  priority?: number;
  enabled?: boolean;
  note?: string;
}): Promise<KBMapEntry> {
  const { data } = await http.post<KBMapEntry>("/api/v1/kb/bindings/novel", payload, {
    params: { novel_id: novelId },
  });
  return data;
}

export async function listNovelKBBindings(params: {
  tenant_id: string;
  project_id: string;
  novel_id: string;
}): Promise<KBMapEntry[]> {
  const { data } = await http.get<KBMapEntry[]>("/api/v1/kb/bindings/novel", { params });
  return data;
}

export async function updateNovelKBBinding(bindingId: string, payload: {
  priority?: number;
  enabled?: boolean;
  note?: string;
}): Promise<KBMapEntry> {
  const { data } = await http.put<KBMapEntry>(`/api/v1/kb/bindings/novel/${bindingId}`, payload);
  return data;
}

export async function deleteNovelKBBinding(bindingId: string): Promise<void> {
  await http.delete(`/api/v1/kb/bindings/novel/${bindingId}`);
}

// ── Effective KB ───────────────────────────────────────────────────────────────

export async function getKBEffective(params: {
  tenant_id: string;
  project_id: string;
  persona_pack_id: string;
  novel_id?: string;
}): Promise<KBEffectiveResponse> {
  const { data } = await http.get<KBEffectiveResponse>("/api/v1/kb/effective", { params });
  return data;
}

// ── Script Workflow ─────────────────────────────────────────────────────────────

export interface FormatDetectResponse {
  chapter_id: string;
  format: "novel" | "script" | "unknown";
  confidence: number;
  signals: string[];
  method: "llm" | "regex_fallback";
}

export interface DialogueBlock {
  speaker: string;
  line: string;
}

export interface SceneItem {
  scene_id: string;
  title: string;
  time: string;
  location: string;
  weather: string;
  mood: string;
  narration: string;
  dialogue_blocks: DialogueBlock[];
  actions: string[];
}

export interface ScriptResponse {
  chapter_id: string;
  scenes: SceneItem[];
  summary: string;
  warnings: string[];
  version: number;
  run_id: string | null;
  cached: boolean;
  script_updated_at: string | null;
}

export interface WorldModelCharacter {
  name: string;
  aliases: string[];
  appearance: string;
  signature_features: string;
  voice_hints: string;
  props_on_body: string[];
  evidence: string[];
}

export interface WorldModelLocation {
  name: string;
  type: string;
  visual_keywords: string[];
  ambience: string[];
  mood: string;
  evidence: string[];
}

export interface WorldModelProp {
  name: string;
  type: string;
  material_condition: string;
  owner: string;
  usage: string;
  evidence: string[];
}

export interface WorldModelBeat {
  title: string;
  participants: string[];
  location: string;
  time: string;
  tension_level: number;
  evidence: string[];
}

export interface WorldModelStyleHint {
  lighting_style: string;
  camera_language: string;
  pacing: string;
  genre_tags: string[];
  evidence: string[];
}

export interface WorldModelResponse {
  chapter_id: string;
  characters: WorldModelCharacter[];
  locations: WorldModelLocation[];
  props: WorldModelProp[];
  beats: WorldModelBeat[];
  style_hints: WorldModelStyleHint[];
  version: number;
  run_id: string | null;
  cached: boolean;
  world_model_updated_at: string | null;
}

export async function detectFormat(chapterId: string, payload: {
  tenant_id?: string;
  project_id?: string;
  model_provider_id?: string;
}): Promise<FormatDetectResponse> {
  const { data } = await http.post<FormatDetectResponse>(
    `/api/v1/chapters/${chapterId}/format-detect`,
    payload,
    { timeout: 30000 },
  );
  return data;
}

export async function getScript(chapterId: string): Promise<ScriptResponse> {
  const { data } = await http.get<ScriptResponse>(`/api/v1/chapters/${chapterId}/script`);
  return data;
}

export async function generateScript(chapterId: string, payload: {
  tenant_id?: string;
  project_id?: string;
  model_provider_id: string;
  granularity?: string;
  style_hint?: string;
  force?: boolean;
}): Promise<ScriptResponse> {
  const { data } = await http.post<ScriptResponse>(
    `/api/v1/chapters/${chapterId}/script/generate`,
    payload,
    { timeout: 120000 },
  );
  return data;
}

export async function regenerateScript(chapterId: string, payload: {
  tenant_id?: string;
  project_id?: string;
  model_provider_id: string;
  granularity?: string;
  style_hint?: string;
}): Promise<ScriptResponse> {
  const { data } = await http.post<ScriptResponse>(
    `/api/v1/chapters/${chapterId}/script/regenerate`,
    payload,
    { timeout: 120000 },
  );
  return data;
}

export async function getWorldModel(chapterId: string): Promise<WorldModelResponse> {
  const { data } = await http.get<WorldModelResponse>(`/api/v1/chapters/${chapterId}/world-model`);
  return data;
}

export async function generateWorldModel(chapterId: string, payload: {
  tenant_id?: string;
  project_id?: string;
  model_provider_id: string;
  level?: string;
  force?: boolean;
}): Promise<WorldModelResponse> {
  const { data } = await http.post<WorldModelResponse>(
    `/api/v1/chapters/${chapterId}/world-model/generate`,
    payload,
    { timeout: 120000 },
  );
  return data;
}

export async function regenerateWorldModel(chapterId: string, payload: {
  tenant_id?: string;
  project_id?: string;
  model_provider_id: string;
  level?: string;
}): Promise<WorldModelResponse> {
  const { data } = await http.post<WorldModelResponse>(
    `/api/v1/chapters/${chapterId}/world-model/regenerate`,
    payload,
    { timeout: 120000 },
  );
  return data;
}

// Legacy aliases for backward compatibility
export const convertNovelToScript = generateScript;
export const normalizeScript = regenerateScript;
export const extractWorldModel = generateWorldModel;

// ── Entity Mapping ──────────────────────────────────────────────────────────────

export interface EntityMappingItem {
  id: string;
  novel_id: string | null;
  entity_type: string | null;
  canonical_name: string;
  source_language: string;
  translations_json: Record<string, string> | null;
  aliases_json: string[] | null;
  culture_tags_json: string[] | null;
  world_model_source: string | null;
  anchor_asset_id: string | null;
  continuity_status: string;
  notes: string | null;
  naming_policy: string | null;
  locked: boolean;
  style_tags_json: string[] | null;
  rationale: string | null;
  localization_candidates_json: Array<Record<string, unknown>> | null;
  drift_score: number;
  locked_langs_json: Record<string, boolean> | null;
  naming_policy_by_lang_json: Record<string, string> | null;
  updated_by_ai: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface BuildEntityMappingResponse {
  created: number;
  updated: number;
  total: number;
}

export async function buildEntityMapping(novelId: string, payload: {
  tenant_id?: string;
  project_id?: string;
}): Promise<BuildEntityMappingResponse> {
  const { data } = await http.post<BuildEntityMappingResponse>(
    `/api/v1/novels/${novelId}/entity-mapping/build`,
    payload,
  );
  return data;
}

export async function listEntityMappings(novelId: string, params?: {
  keyword?: string;
  entity_type?: string;
  status?: string;
}): Promise<EntityMappingItem[]> {
  const { data } = await http.get<EntityMappingItem[]>(
    `/api/v1/novels/${novelId}/entity-mapping`,
    { params },
  );
  return data;
}

export async function getEntityMapping(entityUid: string): Promise<EntityMappingItem> {
  const { data } = await http.get<EntityMappingItem>(`/api/v1/entity-mapping/${entityUid}`);
  return data;
}

export async function updateEntityMapping(entityUid: string, payload: {
  canonical_name?: string;
  translations_json?: Record<string, string>;
  aliases_json?: string[];
  culture_tags_json?: string[];
  anchor_asset_id?: string;
  continuity_status?: string;
  notes?: string;
}): Promise<EntityMappingItem> {
  const { data } = await http.patch<EntityMappingItem>(`/api/v1/entity-mapping/${entityUid}`, payload);
  return data;
}

export async function mergeEntityMapping(entityUid: string, targetUid: string): Promise<EntityMappingItem> {
  const { data } = await http.post<EntityMappingItem>(`/api/v1/entity-mapping/${entityUid}/merge`, {
    target_uid: targetUid,
  });
  return data;
}

export async function translateEntityMapping(entityUid: string, payload: {
  tenant_id?: string;
  project_id?: string;
  model_provider_id: string;
  target_languages?: string[];
}): Promise<EntityMappingItem> {
  const { data } = await http.post<EntityMappingItem>(
    `/api/v1/entity-mapping/${entityUid}/translate`,
    payload,
    { timeout: 30000 },
  );
  return data;
}

export async function deleteEntityMapping(entityUid: string): Promise<void> {
  await http.delete(`/api/v1/entity-mapping/${entityUid}`);
}

// ── SkillRun ────────────────────────────────────────────────────────────────────

export interface SkillRunItem {
  id: string;
  skill_id: string;
  chapter_id: string | null;
  novel_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed";
  input_hash: string | null;
  model_provider_id: string | null;
  model_name: string | null;
  token_usage: Record<string, number> | null;
  cost_estimate: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export async function listSkillRuns(params: {
  tenant_id?: string;
  project_id?: string;
  skill_id?: string;
  chapter_id?: string;
  novel_id?: string;
  status?: string;
  limit?: number;
}): Promise<SkillRunItem[]> {
  const { data } = await http.get<SkillRunItem[]>("/api/v1/skill-runs", { params });
  return data;
}

export async function getSkillRun(runId: string): Promise<SkillRunItem> {
  const { data } = await http.get<SkillRunItem>(`/api/v1/skill-runs/${runId}`);
  return data;
}

// ── Name Localization ──────────────────────────────────────────────────────────

export interface NameCandidate {
  name: string;
  naming_policy: "transliteration" | "literal" | "cultural_equivalent" | "hybrid" | "character_driven" | "setting_authentic";
  rationale: string;
}

export interface NameSuggestion {
  entity_id: string;
  canonical_name: string;
  entity_type: string | null;
  candidates: NameCandidate[];
  recommended_name: string | null;
  rationale: string | null;
}

export interface SuggestNameResponse {
  suggestions: NameSuggestion[];
  run_id: string | null;
  total: number;
}

export interface NameLocalizationListItem {
  entity_id: string;
  canonical_name: string;
  entity_type: string | null;
  source_language: string;
  naming_policy: string | null;
  locked: boolean;
  rationale: string | null;
  translations_json: Record<string, string> | null;
  localization_candidates_json: Array<Record<string, unknown>> | null;
  drift_score: number;
  locked_langs_json: Record<string, boolean> | null;
  naming_policy_by_lang_json: Record<string, string> | null;
}

export async function listNameLocalizations(novelId: string, params?: {
  entity_type?: string;
  locked?: boolean;
  target_language?: string;
}): Promise<NameLocalizationListItem[]> {
  const { data } = await http.get<NameLocalizationListItem[]>(
    `/api/v1/novels/${novelId}/name-localization`,
    { params },
  );
  return data;
}

export async function suggestNames(novelId: string, payload: {
  tenant_id?: string;
  project_id?: string;
  model_provider_id: string;
  entity_uids?: string[];
  target_language?: string;
  culture_profile?: string;
  era_profile?: string;
  social_class?: string;
  max_entities?: number;
}): Promise<SuggestNameResponse> {
  const { data } = await http.post<SuggestNameResponse>(
    `/api/v1/novels/${novelId}/name-localization/suggest`,
    payload,
    { timeout: 120000 },
  );
  return data;
}

export async function applyName(novelId: string, payload: {
  entity_uid: string;
  chosen_name: string;
  target_language?: string;
  naming_policy?: string;
  rationale?: string;
  lock?: boolean;
}): Promise<Record<string, unknown>> {
  const { data } = await http.post<Record<string, unknown>>(
    `/api/v1/novels/${novelId}/name-localization/apply`,
    payload,
  );
  return data;
}
