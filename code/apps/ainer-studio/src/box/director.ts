// Ainer Director Core 的接口：/api/v2/director/*（Blender 控制素材、LTX 成片、功能开关）

const BASE = "/api/v2/director";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: string;
    try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j); }
    catch { detail = res.statusText; }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export interface Features {
  blender_enabled: boolean;
  ue_enabled: boolean;
  ltx097_enabled: boolean;
  ltx25_enabled: boolean;
  blender: { enabled: boolean; binary: string | null; version: string | null };
  renderers: { ltx_097: { enabled: boolean; control_types: string[] }; ltx_25: { enabled: boolean } };
  ue: { enabled: boolean };
}

export interface JobOutput { kind: string; path: string; url: string; asset_id: string | null; bytes: number | null }

export interface Job {
  id: string;
  scene_id: string | null;
  parent_id: string | null;
  job_type: "blender_render" | "final_render" | "ue_render";
  backend: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: { stage?: string; percent?: number; frame?: number; total?: number; task?: string; task_status?: string; elapsed?: number; retry?: number; last_error?: string };
  error: string | null;
  input: Record<string, unknown>;
  manifest: Record<string, unknown> | null;
  created_at: string | null;
  finished_at: string | null;
  outputs?: JobOutput[];
}

export interface FinalBody {
  renderer?: string;
  control_type?: string;
  prompt?: string;
  seed?: number;
  denoise?: number;
  pin_first?: boolean;
  reference_images?: string[];
  use_llm_prompt?: boolean;
}

export const director = {
  features: () => call<Features>("GET", "/system/features"),
  jobs: (boxProjectId: string) => call<Job[]>("GET", `/jobs?box_project_id=${encodeURIComponent(boxProjectId)}&limit=40`),
  job: (id: string) => call<Job>("GET", `/jobs/${id}`),
  blender: (boxProjectId: string, renderPlan: Record<string, unknown>) =>
    call<Job>("POST", "/jobs/blender-render", { box_project_id: boxProjectId, render_plan: renderPlan }),
  final: (jobId: string, body: FinalBody) => call<Job>("POST", `/jobs/${jobId}/render-final`, body),
  cancel: (id: string) => call<Job>("POST", `/jobs/${id}:cancel`),
};
