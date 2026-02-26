import { http } from "@/api/http";

export interface PreviewEntity {
  entity_id: string;
  label: string;
  entity_type: string;
  continuity_status: string;
  locked_variant_id?: string | null;
  latest_variant_id?: string | null;
  latest_variant_status?: string | null;
  voice_binding_id?: string | null;
  voice_id?: string | null;
}

export interface PreviewVariant {
  variant_id: string;
  run_id: string;
  entity_id: string;
  entity_label: string;
  view_angle: string;
  generation_backend: string;
  status: string;
  dispatch_job_id?: string | null;
  artifact_id?: string | null;
  artifact_uri?: string | null;
  prompt_text?: string | null;
  negative_prompt_text?: string | null;
  review_note?: string | null;
  created_at: string;
}

export interface VoiceBinding {
  id: string;
  entity_id: string;
  project_id: string;
  language_code: string;
  voice_id: string;
  tts_model: string;
  provider: string;
  locked: boolean;
  notes?: string | null;
}

export async function listPreviewEntities(runId: string): Promise<PreviewEntity[]> {
  const { data } = await http.get<PreviewEntity[]>(`/api/v1/runs/${runId}/preview/entities`);
  return data;
}

export async function listPreviewVariants(runId: string, entityId?: string): Promise<PreviewVariant[]> {
  const { data } = await http.get<PreviewVariant[]>(`/api/v1/runs/${runId}/preview/variants`, {
    params: entityId ? { entity_id: entityId } : undefined,
  });
  return data;
}

export async function generatePreviewVariants(
  runId: string,
  entityId: string,
  payload?: Partial<{ prompt_text: string; negative_prompt_text: string; view_angles: string[] }>
): Promise<void> {
  await http.post(`/api/v1/runs/${runId}/preview/entities/${entityId}/generate`, payload ?? {});
}

export async function reviewPreviewVariant(
  variantId: string,
  decision: "approve" | "reject" | "regenerate",
  note?: string
): Promise<void> {
  await http.post(`/api/v1/preview/variants/${variantId}/review`, { decision, note });
}

export async function getVoiceBinding(
  projectId: string,
  entityId: string,
  languageCode = "zh-CN"
): Promise<VoiceBinding> {
  const { data } = await http.get<VoiceBinding>(
    `/api/v1/projects/${projectId}/entities/${entityId}/voice-binding`,
    { params: { language_code: languageCode } }
  );
  return data;
}

export async function upsertVoiceBinding(
  projectId: string,
  entityId: string,
  payload: {
    language_code: string;
    voice_id: string;
    tts_model: string;
    provider: string;
    locked: boolean;
    notes?: string;
  }
): Promise<VoiceBinding> {
  const { data } = await http.put<VoiceBinding>(
    `/api/v1/projects/${projectId}/entities/${entityId}/voice-binding`,
    payload
  );
  return data;
}
