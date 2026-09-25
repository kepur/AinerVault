// 预设广场（风格／运镜／特效／爆款题材）与角色库、造型室的接口：/api/v2/presets/*、/api/v2/characters/*

const BASE = "/api/v2";

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

const qs = (o: Record<string, unknown>) =>
  Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "" && v !== false)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");

export type PresetKind = "style" | "camera_move" | "effect" | "genre" | "hairstyle" | "outfit" | "expression" | "character";

export interface Preset {
  id: string;
  kind: PresetKind;
  key: string;
  name: string;
  category: string | null;
  cover_url: string | null;
  payload: Record<string, unknown> & { prompt?: string; render?: string; negative?: string; cover?: string; preset?: string;
    fields?: Record<string, string>; prefill?: string };
  tags: string[];
  author: string | null;
  official: boolean;
  commercial: boolean;
  uses: number;
  favorite: boolean;
}

export interface CharTags { gender?: string; age?: string; culture?: string; era?: string }

export interface CharCard {
  id: string;
  source: "novel" | "official" | "mine";
  name: string;
  novel?: string | null;
  tags: CharTags;
  cover?: string | null;
  views: Record<string, unknown>;
  look?: string | null;
  identity?: string | null;
  voice?: { voice_id: string; name: string } | null;
  category?: string | null;
  pending?: number;
  entity_id?: string;
}

export interface Voice {
  voice_id: string;
  name: string;
  gender: string | null;
  age: string | null;
  languages: string[];
  tags: string[];
  preview_url: string | null;
}

export interface JobInfo { id: string; status: "queued" | "running" | "done" | "failed" | "skipped"; url: string | null; error: string | null; title: string; group?: string }

export interface RestyleBody {
  base_url?: string;
  hairstyle?: string | null;
  outfit?: string | null;
  skin: Record<string, number>;
  blemish: boolean;
  features: Record<string, string>;
  body: Record<string, number>;
  extra: string;
}

export const lib = {
  presets: (kind: PresetKind, o: { category?: string; q?: string; mark?: string; commercial?: boolean } = {}) =>
    call<Preset[]>("GET", `/presets?${qs({ kind, ...o })}`),
  categories: (kind: PresetKind) => call<{ category: string; count: number }[]>("GET", `/presets/categories?kind=${kind}`),
  favorite: (id: string) => call<{ favorite: boolean }>("POST", `/presets/${id}:favorite`),
  use: (id: string) => call<Preset>("POST", `/presets/${id}:use`),
  covers: () => call<{ queued: number; pending: number }>("POST", "/presets:covers", { kind: "style", limit: 60 }),
  jobs: (group?: string) => call<JobInfo[]>("GET", `/presets/jobs${group ? `?group=${encodeURIComponent(group)}` : ""}`),
  planStyle: (planId: string) => call<{ plan_id: string; version: number; style_preset: { id: string; name: string; render: string } | null }>(
    "GET", `/presets/plan-style?plan_id=${encodeURIComponent(planId)}`),
  applyStyle: (planId: string, presetId: string | null) =>
    call<{ plan_id: string; style_preset: unknown }>("POST", "/presets:apply-style", { plan_id: planId, preset_id: presetId }),

  characters: (scope: "official" | "mine", f: { gender?: string; age?: string; culture?: string; q?: string } = {}) =>
    call<CharCard[]>("GET", `/characters?${qs({ scope, ...f })}`),
  character: (cid: string) => call<CharCard>("GET", `/characters/${cid}`),
  voices: () => call<Voice[]>("GET", "/characters/voices"),
  generate: (cid: string, what: "all" | "front" | "views" | "expressions") =>
    call<{ queued: number; pending: number }>("POST", `/characters/${cid}:generate`, { what }),
  restyle: (cid: string, body: RestyleBody) => call<{ job_id: string; prompt: string }>("POST", `/characters/${cid}/restyle`, body),
  job: (id: string) => call<JobInfo>("GET", `/characters/jobs/${id}`),
  saveLook: (cid: string, body: { url: string; name?: string; generate_assets: boolean }) =>
    call<CharCard & { queued: number }>("POST", `/characters/${cid}/save-look`, body),
  setVoice: (cid: string, voice_id: string, name: string) => call<{ voice: unknown }>("POST", `/characters/${cid}/voice`, { voice_id, name }),
  previewVoice: (voice_id: string, text?: string) => call<{ job_id: string }>("POST", "/characters/voices:preview", { voice_id, text }),
};

/** 等一个本机出图／配音任务跑完（队列一个一个跑，前面有活的话要排一会儿）。 */
export async function waitJob(id: string, onTick?: (j: JobInfo) => void, timeoutMs = 15 * 60 * 1000): Promise<JobInfo> {
  const t0 = Date.now();
  for (;;) {
    const j = await lib.job(id);
    onTick?.(j);
    if (j.status === "done" || j.status === "failed" || j.status === "skipped") return j;
    if (Date.now() - t0 > timeoutMs) throw new Error("等太久了：任务还在队列里");
    await new Promise(r => setTimeout(r, 2000));
  }
}

/** 角色标签 → 3D-BOX 人偶体型 */
export function bodyOf(tags: CharTags): string {
  if (tags.age === "儿童") return "child";
  if (tags.age === "少年") return "teen";
  if (tags.age === "老年") return "elder";
  return tags.gender === "女" ? "female" : "male";
}
