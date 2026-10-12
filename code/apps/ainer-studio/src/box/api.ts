// 3D-BOX 预演的接口：/api/v2/scene3d/*
import type { CamKey, Diagnostics, Overrides, SceneDoc } from "../scene/types";
import {readCtx} from '../ctx';

const BASE = "/api/v2/scene3d";

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

export interface ProjectRow {
  id: string; title: string; template: string | null; thumb_url: string | null; updated_at: string | null;
  ok: boolean | null; objects: number | null; cameras: number; duration: number | null;
  /** 按分镜筛选时：这个白模属于哪一镜 */
  shot_id?: string | null; shot_order?: number | null;
  novel_id?: string | null; shot_plan_id?: string | null;
  studio_scope?:{medium:string;chapter_id?:string|null};
}
export interface Project extends ProjectRow {
  files: Record<string, string>;
  overrides: Overrides;
  doc: SceneDoc | null;
  diagnostics: Diagnostics & { ms?: number };
  seed: number;
  versions: { index: number; at: string; by: string; note: string }[];
  active_run: string | null;
  settings?: {studio_medium?:string;studio_chapter?:string;[key:string]:unknown};
}
export interface Template { key: string; name: string; category: string; desc: string }
export interface ChatRow { id: string; run_id: string | null; role: string; content: string; meta: Record<string, unknown>; at: string }
export interface AgentEvent {
  seq: number; type: "status" | "thinking" | "say" | "tool" | "tool_result" | "scene" | "error" | "stopped" | "done";
  at: number; text?: string; tool?: string; brief?: string; ok?: boolean; result?: string; final?: boolean; step?: number; status?: string;
}
export interface Catalog {
  prefabs: { name: string; zh: string; category: string; doc: string; size: number[]; params: Record<string, { default: unknown; doc: string; options?: string[] }> }[];
  bodies: { name: string; zh: string; height: number }[];
  poses: { name: string; zh: string }[];
  cameraPresets: { id: string; zh: string; group: string; doc: string }[];
}
export interface Sketch { tool: string; color: string; points: [number, number][] }

export const box = {
  /** planId：只列这份分镜的白模（每项带 shot_id / shot_order） */
  projects: (planId?: string | null) => call<ProjectRow[]>("GET", `/projects${planId ? `?plan_id=${encodeURIComponent(planId)}` : ""}`),
  create: (title: string, template: string, context?:{novel_id?:string|null;shot_plan_id?:string|null}) => call<Project>("POST", "/projects", { title, template, ...context }),
  get: (id: string) => call<Project>("GET", `/projects/${id}`),
  patch: (id: string, body: { title?: string; seed?: number;settings?:Record<string,unknown> }) => call<Project>("PATCH", `/projects/${id}`, body),
  remove: (id: string) => call("DELETE", `/projects/${id}`),
  writeFile: (id: string, path: string, content: string) => call<Project>("PUT", `/projects/${id}/files/${path}`, { content }),
  overrides: (id: string, overrides: Overrides) => call<Project>("PUT", `/projects/${id}/overrides`, { overrides }),
  restore: (id: string, index: number) => call<Project>("POST", `/projects/${id}/versions/${index}:restore`),
  templates: () => call<Template[]>("GET", "/templates"),
  catalog: () => call<Catalog>("GET", "/catalog"),
  models: () => call<{ model: string; billing: string; default: boolean }[]>("GET", "/models"),
  messages: (id: string) => call<ChatRow[]>("GET", `/projects/${id}/messages`),
  ask: (id: string, body: { message: string; selected: string[]; sketches: Sketch[]; model?: string }) =>
    call<{ run_id: string }>("POST", `/projects/${id}/agent`, body),
  stop: (id: string, run: string) => call("POST", `/projects/${id}/agent/${run}:stop`),
  streamUrl: (id: string, run: string, after = 0) => `${BASE}/projects/${id}/agent/${run}/stream?after=${after}`,
  exportFile: async (id: string, blob: Blob, meta: { camera?: string; duration?: number; kind: string }, filename: string) => {
    const fd = new FormData();
    fd.append("file", blob, filename);
    fd.append("camera", meta.camera ?? "");
    fd.append("duration", String(meta.duration ?? 0));
    fd.append("kind", meta.kind);
    const res = await fetch(`${BASE}/projects/${id}/exports`, { method: "POST", body: fd });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json() as Promise<{ asset_id: string; url: string; kind: string }>;
  },
  exports: (id: string) => call<{ asset_id: string; url: string; kind: string; meta: Record<string, unknown>; at: string }[]>("GET", `/projects/${id}/exports`),
};

export async function workspaceBoxes():Promise<ProjectRow[]> {
  const c=readCtx(),rows=await box.projects();
  return rows.filter(p=>c.workspace==='free'?!p.novel_id&&!p.shot_plan_id:
    !!c.novel&&p.novel_id===c.novel&&(p.studio_scope?.medium||'video')===(c.medium||'video')&&(!c.chapter||!p.studio_scope?.chapter_id||p.studio_scope.chapter_id===c.chapter));
}

export async function createWorkspaceBox(title:string,template:string):Promise<Project> {
  const c=readCtx(),free=c.workspace==='free';
  if(!free&&!c.novel)throw new Error('请先选择小说，再创建本版舞台');
  const p=await box.create(title,template,{novel_id:free?null:c.novel,shot_plan_id:free?null:c.plan});
  return box.patch(p.id,{settings:{studio_workspace:free?'free':'novel',studio_medium:c.medium||'video',studio_chapter:free?'':c.chapter||''}});
}

export type { CamKey };
