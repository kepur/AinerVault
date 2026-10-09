import type { ResourceRef } from "./api";
import type { SceneDoc, Vec3 } from "../scene/types";

export interface StageActor {
  id: string; name?: string; type: "human" | "vehicle" | "animal"; model_ref: string;
  character_ref?: string | null; appearance: { height_m?: number; color?: string; [key: string]: unknown };
  spawn: { position: Vec3; rotation: Vec3; scale: Vec3 }; pose?: string | null;
}
export interface StageCamera {
  id: string; name?: string; lens_mm: number;
  keys: { t: number; position?: Vec3; look_at?: Vec3 | string | Record<string, unknown>; [key: string]: unknown }[];
}
export interface StageProtocol {
  protocol: "ainer.scene/v1"; scene_id: string;
  meta: { title: string; duration_sec: number; fps: number; aspect: number; [key: string]: unknown };
  actors: StageActor[];
  props: { id: string; name?: string; primitive?: string; size?: Vec3; spawn: { position: Vec3; rotation: Vec3; scale: Vec3 }; [key: string]: unknown }[];
  cameras: StageCamera[]; timeline: Record<string, unknown>[];
  [key: string]: unknown;
}
export interface StageCoverage {
  id: string; title: string; camera_id: string; clip_duration_ms: number;
  scene_start_ms: number; scene_end_ms: number; fps: number; intent: string;
  participants: string[]; must_show: string[]; offscreen: string[];
  transition: "cut" | "continuous" | "dissolve" | "jump";
}
export interface StageContent {
  protocol: StageProtocol; bindings: Record<string, ResourceRef>;
  initial_state: Record<string, Record<string, unknown>>;
  events: Record<string, unknown>[]; coverages: StageCoverage[];
}
export interface SharedStage extends StageContent {
  id: string; title: string; version: number; revision: string; box_project_id: string;
  board_ids: string[]; source_board_id: string; coverage_count: number;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api/v2/production/stages${path}`, {
    method, headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const raw = await r.text();
  let json: { data?: T; detail?: { message?: string } | string } = {};
  try { json = JSON.parse(raw); } catch { /* Keep an actionable status if response is not JSON. */ }
  if (!r.ok) throw new Error(typeof json.detail === "string" ? json.detail : json.detail?.message || `请求失败 ${r.status}`);
  return json.data as T;
}

const query = (board: string) => `board_id=${encodeURIComponent(board)}`;
export const sharedStages = {
  referencePreview: (board: string, ref: ResourceRef) => call<{ doc: SceneDoc; resource: import("./api").Resource }>("POST", "/reference-preview", { board_id: board, ref }),
  referenceBake: (board: string, ref: ResourceRef) => call<Record<string, unknown>>("POST", "/reference-bake", { board_id: board, ref }),
  list: (board: string) => call<{ items: SharedStage[] }>("GET", `?${query(board)}`),
  create: (board: string) => call<SharedStage>("POST", "", { board_id: board }),
  get: (board: string, id: string) => call<SharedStage>("GET", `/${encodeURIComponent(id)}?${query(board)}`),
  save: (board: string, stage: SharedStage, content: StageContent) =>
    call<SharedStage>("PUT", `/${encodeURIComponent(stage.id)}?${query(board)}`, { ...content, base_version: stage.version }),
  link: (board: string, stage: SharedStage) => call<SharedStage>("POST", `/${encodeURIComponent(stage.id)}/boards`, { board_id: board, base_version: stage.version }),
  adoptProjection: (board: string, stage: SharedStage) => call<SharedStage>("POST", `/${encodeURIComponent(stage.id)}/adopt-projection?${query(board)}`, { base_version: stage.version }),
  preview: (board: string, stage: SharedStage) => call<{ doc: SceneDoc }>("GET",
    `/${encodeURIComponent(stage.id)}/preview?${query(board)}&base_version=${stage.version}`),
  sample: (board: string, stage: SharedStage, time: number, camera: string | null) => call<Record<string, unknown>>("POST",
    `/${encodeURIComponent(stage.id)}/sample?${query(board)}`, { base_version: stage.version, time_ms: Math.round(time * 1000), camera_id: camera }),
  bake: (board: string, stage: SharedStage, coverage: string) => call<Record<string, unknown>>("POST",
    `/${encodeURIComponent(stage.id)}/coverages/${encodeURIComponent(coverage)}/bake?${query(board)}`, { base_version: stage.version }),
};

export function stageContent(stage: SharedStage): StageContent {
  const { protocol, bindings, initial_state, events, coverages } = stage;
  return structuredClone({ protocol, bindings, initial_state, events, coverages });
}
