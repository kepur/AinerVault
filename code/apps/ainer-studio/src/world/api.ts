/** world-greybox（可选路径）接口。默认路径是原动态漫剧管线；这里只在用户打开开关后才产生作用。 */
const BASE = "/api/v2/world-greybox";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : j.detail?.message ?? JSON.stringify(j.detail ?? j); } catch { /* keep statusText */ }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export type Scope = "novel" | "chapter" | "production" | "plan" | "shot";
export interface Switch { scope_kind: Scope; scope_id: string; enabled: boolean; fallback_to_original: boolean; note?: string | null }
export interface Run {
  id: string; world_id: string; scope_kind: Scope; scope_id: string; title: string | null; status: string; progress: number;
  error: string | null; running: boolean; out_dir: string;
  report?: { greybox_passed: number; used_greybox: number; used_original: number; total: number } | null;
  final?: { video: string; probe: { duration_s: number } } | null;
}
export interface ShotRow {
  shot: number; kind: string; move: string; mood: string | null; dur_s: number; fps: number; attempts: number;
  greybox_pass: boolean; source: "greybox" | "original" | null; pass: boolean | null; failed: string[]; why: string | null;
  route: string | null; strategy: string | null; post: string[]; approved: boolean;
  override: { source: string; attempt_index?: number | null } | null;
  camera_fit: { error?: number; how?: string; world_conflict_hidden?: string[]; world_actors_off_frame?: string[]; skipped?: string };
  greybox_video: string | null; clay: string | null; original_video: string | null; final_video: string | null;
  metrics: Record<string, unknown>;
}
export interface WorldMap {
  world: { id: string; title: string }; version: number;
  regions: { key: string; name: string; kind: string; bounds_aabb: { min: number[]; max: number[] } }[];
  chunks: { region: string; cx: number; cy: number; ix?: number; iy?: number }[];
  instances: { region: string; key: string; kind: string; aabb: { min: number[]; max: number[] }; collision: boolean }[];
  landmarks: { region: string; key: string; pos: number[] }[];
  performances: { id: string; scene_key: string; region_key: string; duration_ms: number; rev: number; check_ok: boolean | null;
    tracks: Record<string, { keys: { t_ms: number; pos: number[] }[]; clips: { clip: string; start_ms: number; end_ms: number }[] }>;
    takes: { n: number; start_ms: number; end_ms: number; camera: { pos: number[]; target: number[]; move?: { type: string } } }[] }[];
}

export const wg = {
  flag: () => call<{ world_greybox_enabled: boolean }>("GET", "/flag"),
  switches: (scopeId?: string) => call<{ switches: Switch[]; flag: boolean }>("GET", `/switches${scopeId ? `?scope_id=${encodeURIComponent(scopeId)}` : ""}`),
  setSwitch: (s: Switch) => call<Switch>("PUT", "/switches", s),
  runs: (scopeId?: string) => call<{ runs: Run[] }>("GET", `/runs${scopeId ? `?scope_id=${encodeURIComponent(scopeId)}` : ""}`),
  run: (id: string) => call<Run>("GET", `/runs/${id}`),
  start: (id: string) => call<Run>("POST", `/runs/${id}:start`),
  shots: (id: string) => call<{ shots: ShotRow[]; running: boolean }>("GET", `/runs/${id}/shots`),
  rerender: (id: string, n: number) => call<Run>("POST", `/runs/${id}/shots/${n}:rerender`),
  select: (id: string, n: number, body: { source: "greybox" | "original" | "auto"; attempt_index?: number | null; approve?: boolean }) =>
    call("POST", `/runs/${id}/shots/${n}:select`, body),
  world: (id: string) => call<WorldMap>("GET", `/runs/${id}/world`),
  file: (id: string, path: string | null | undefined) => path ? `${BASE}/runs/${id}/file?path=${encodeURIComponent(path)}` : undefined,
};
