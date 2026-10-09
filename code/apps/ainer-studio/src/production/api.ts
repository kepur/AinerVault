/**
 * 生产契约客户端（ainer.production/v0.1）。
 *
 * 契约 `docs/studio/planA_contracts.md` 由 Codex 维护，本文件只做严格搬运：
 * - 生产接口统一信封 `{schema_version, data, issues}`；旧 studio/stage 接口保持各自原形状，不在这里混用。
 * - 上下文以 `data.context` 为权威，**不由前端拼装**（拼装等于前端第二份事实来源）。
 * - 本批后端只支持 `mode: "reference"`；snapshot / derived / 历史回退没有存储，UI 必须隐藏而不是做成假按钮。
 */
import { media } from "../canvas/api";
import type { StageCoverage } from "./stages";

export const SCHEMA = "ainer.production/v0.1";

/* ───────────────────────── 契约类型 ───────────────────────── */

/** 响应里逐项的问题；不吞掉，UI 照原样显示 code 与 message */
export interface Issue {
  code: string;
  message: string;
  [k: string]: unknown;
}

export interface Envelope<T> {
  schema_version: string;
  data: T;
  issues: Issue[];
}

export type Purpose = "assets" | "directing" | "finishing" | "general";

export interface ProductionContext {
  schema_version: string;
  project_id: string | null;
  board_id: string | null;
  novel_id: string | null;
  chapter_id: string | null;
  plan_id: string | null;
  script_doc_id: string | null;
  source_revision: string | null;
  transform_id: string | null;
  world_profile_id: string | null;
  production_language: string | null;
  purpose: Purpose | null;
  scope: { kind?: string; chapter_ids?: string[]; scene_ids?: string[]; shot_ids?: string[] } | null;
}

export interface MediaRef {
  asset_id?: string | null;
  url: string;
  mime?: string | null;
  metadata?: { width?: number; height?: number; [k: string]: unknown } | null;
}

/**
 * 单格状态，取值来自后端 `app/production/canonical.py`，前端不自造：
 *   legacy_mapped       旧键精确映射（front→body_front）
 *   legacy_approximate  旧键近似映射（bust 当 face_front、profile_left 当 body_side）——必须和上一种视觉区分
 *   bound_unreviewed    已绑定但未经视觉审核
 */
export type ViewStatus = "legacy_mapped" | "legacy_approximate" | "bound_unreviewed" | string;

export interface CanonicalView {
  view_key: string;
  /** 资源稳定标识，形如 `<epoch_id>:<view_key>`；建引用用它，不用 asset_id */
  id: string;
  revision: string;
  asset_id?: string | null;
  kind?: string;
  media?: MediaRef | null;
  status: ViewStatus;
  /** 由哪个旧键映射来；没有表示是原生标准格 */
  legacy_key?: string | null;
  side?: string | null;
  provenance?: Record<string, unknown> | null;
}

export interface CanonicalPack {
  id: string;
  revision: string;
  entity_id: string;
  entity_kind: string;
  world_profile_id: string;
  epoch_id: string | null;
  epoch_key: string | null;
  views: Record<string, CanonicalView>;
  /** 后端算好的缺格清单，前端不自己减集合 */
  missing: string[];
  physical: { height_m?: number | null; build?: string | null; source?: string } | null;
  identity_anchor?: { media?: MediaRef | null } | null;
  /** 拼版：展示与导出用，不是消费源（契约 §4） */
  sheet?: { id?: string; revision?: string; media?: MediaRef | null } | null;
  locked?: boolean;
  review_status?: string | null;
  issues?: Issue[];
}

/** 契约 §3 的资源引用。本批只用 mode=reference */
export interface ResourceRef {
  kind: "canonical_view" | "entity" | "asset" | "variant" | "canonical_pack" | "audio" | "event" | "stage" | "coverage" | "run_output";
  id: string;
  revision?: string | null;
  binding?: {
    entity_id?: string | null;
    world_profile_id?: string | null;
    epoch_id?: string | null;
    view_key?: string | null;
    instance_id?: string | null;
  };
  mode: "reference";
}

export interface Resource {
  id: string; revision: string; kind?: string; name?: string; screen_name?: string | null;
  novel_id?: string | null; media?: MediaRef | null;
  stage_id?: string; stage_version?: number; stage_revision?: string;
  coverage?: StageCoverage | null; coverages?: StageCoverage[];
  dependencies?: { instance_id: string; ref: ResourceRef; resource_revision: string }[];
}
export interface ResourceItem { ref: ResourceRef; resource: Resource | null; status?: string; issues?: Issue[] }
export interface EpochOption {
  id: string; epoch_key: string; name: string; world_profile_id: string; world_name: string;
  from_chapter_order: number; to_chapter_order: number | null;
}

/* ───────────────────────── 16 格标准 ───────────────────────── */

/** 三分区固定键，顺序即展示顺序。以契约 §4 为准（后端已做 expr_sorrow→expr_sad 等别名适配，前端不建别名表） */
export const SHEET_SECTIONS: { title: string; keys: string[] }[] = [
  { title: "角色全景前后侧三视图", keys: ["body_front", "body_back", "body_side"] },
  { title: "角色面部多视角特写", keys: ["face_front", "face_left", "face_right", "face_back"] },
  {
    title: "九宫格表情特写",
    keys: ["expr_joy", "expr_anger", "expr_sad", "expr_laugh", "expr_surprise", "expr_fear",
      "expr_think", "expr_disgust", "expr_doubt"],
  },
];

export const VIEW_LABELS: Record<string, string> = {
  body_front: "前视图", body_back: "后视图", body_side: "侧视图",
  face_front: "正面特写", face_left: "左侧特写", face_right: "右侧特写", face_back: "后脑特写",
  expr_joy: "喜", expr_anger: "怒", expr_sad: "哀", expr_laugh: "乐", expr_surprise: "惊",
  expr_fear: "恐", expr_think: "思", expr_disgust: "厌", expr_doubt: "疑",
};

export const ALL_VIEW_KEYS: string[] = SHEET_SECTIONS.flatMap(s => s.keys);

/** 近似映射要让人看出来：拿头肩近景当正脸特写是将就，不是真的那一格 */
export function isApproximate(v: CanonicalView | undefined): boolean {
  return v?.status === "legacy_approximate";
}

/** 单格 → 画布可用的引用。id/revision 用格子自己的，不用 asset_revision（Codex 交接 §2） */
export function viewRef(pack: CanonicalPack, v: CanonicalView): ResourceRef {
  return {
    kind: "canonical_view", id: v.id, revision: v.revision,
    binding: {
      entity_id: pack.entity_id, world_profile_id: pack.world_profile_id,
      epoch_id: pack.epoch_id, view_key: v.view_key,
    },
    mode: "reference",
  };
}

/** 媒体地址统一过同源化；后端给的是 http://localhost:8100/media/…，换部署地址就坏 */
export function viewSrc(v: CanonicalView | undefined): string | null {
  const u = v?.media?.url;
  return u ? media(u) ?? u : null;
}

/* ───────────────────────── 调用 ───────────────────────── */

export class ProductionError extends Error {
  constructor(readonly status: number, readonly code: string, message: string, readonly issues: Issue[] = []) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<Envelope<T>> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let json: unknown = null;
  try { json = text ? JSON.parse(text) : null; } catch { /* 非 JSON：下面按状态码报 */ }
  if (!res.ok) {
    // 新接口 detail 至少含 code/message/issues；旧字符串 detail 也要能显示（契约 §5）
    const d = (json as { detail?: unknown } | null)?.detail;
    const o = (d && typeof d === "object" ? d : {}) as { code?: string; message?: string; issues?: Issue[] };
    const msg = typeof d === "string" ? d : o.message || `${res.status} ${path}`;
    throw new ProductionError(res.status, o.code || String(res.status), msg, o.issues ?? []);
  }
  return json as Envelope<T>;
}

/** 当前生产上下文。自由画布也需要真实 board_id（CR-07 裁定），不传 null 伪装存在 */
export const prod = {
  context: (boardId: string) =>
    call<{ context: ProductionContext; readiness?: Record<string, unknown>; issues?: Issue[] }>(
      "GET", `/api/v2/production/context?board_id=${encodeURIComponent(boardId)}`),

  /** 标准素材包。无章且多时期时后端要求显式指定 epoch_id，缺了会在 issues 里说明 */
  canonicalPack: (entityId: string, worldProfileId: string, epochId?: string | null) => {
    const q = new URLSearchParams({ world_profile_id: worldProfileId });
    if (epochId) q.set("epoch_id", epochId);
    return call<CanonicalPack>("GET", `/api/v2/production/entities/${encodeURIComponent(entityId)}/canonical-pack?${q}`);
  },

  /** 逐项对齐输入 refs，失败项保留位置不被删掉（契约 §5） */
  resolve: (context: { board_id?: string | null }, refs: ResourceRef[]) =>
    call<{ items: ResourceItem[] }>(
      "POST", "/api/v2/production/resources:resolve", { context, refs }),

  epochs: (entityId: string, boardId?: string | null) =>
    call<{ items: EpochOption[] }>("GET", `/api/v2/production/entities/${encodeURIComponent(entityId)}/epochs${boardId ? `?board_id=${encodeURIComponent(boardId)}` : ""}`),

  addReference: (boardId: string, baseVersion: number, ref: ResourceRef, title?: string) =>
    call<{ node_id: string; board_version: number; reused: boolean }>("POST",
      `/api/v2/production/canvases/${encodeURIComponent(boardId)}/references`, { base_version: baseVersion, ref, title }),

  bindPack: (entityId: string, pack: CanonicalPack, views: Record<string, string>, sheetAssetId?: string | null) =>
    call<CanonicalPack>("PATCH", `/api/v2/production/entities/${encodeURIComponent(entityId)}/canonical-pack`, {
      epoch_id: pack.epoch_id, base_revision: pack.revision, views, ...(sheetAssetId ? { sheet_asset_id: sheetAssetId } : {}),
    }),

  resources: (boardId: string, kind?: string, offset = 0, limit = 50, entityKind?: string) => {
    const q = new URLSearchParams({ board_id: boardId, offset: String(offset), limit: String(limit) });
    if (kind) q.set("kind", kind);
    if (entityKind) q.set("entity_kind", entityKind);
    return call<{ items: ResourceItem[]; next_offset: number | null }>("GET", `/api/v2/production/resources?${q}`);
  },
};

/* ───────────────────────── 整包生成（过渡方案） ───────────────────────── */

/**
 * 16 格整包生成。CR-04 裁定：`production/prepare` 当前只做规划、不提交任务，
 * 单格补建没有实现，所以缺格只能整包重出，走已有的 `POST /studio/char-sheets`。
 * 调用方必须把按钮文案写成「整包生成」，不能说成「补这一格」。
 */
export interface SheetJob {
  id: string;
  state: "running" | "done" | "failed";
  progress?: number | null;
  step?: string | null;
  error?: string | null;
  sheet?: { asset_id: string; url: string } | null;
  panels?: { key: string; view_key?: string; asset_id: string; url: string }[];
  missing?: { key: string; error: string }[];
}

export const charSheets = {
  /** person 用定妆照里已有的一格（通常 body_front 或身份锚）当底 */
  start: async (personAssetId: string, name?: string, look?: string, binding?: { entity_id: string; epoch_id: string; base_revision: string }): Promise<SheetJob> => {
    const res = await fetch("/api/v2/studio/char-sheets", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ person: { asset_id: personAssetId }, name: name || "", look: look || "", preset: "standard", ...(binding ? { binding } : {}) }),
    });
    if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 200)}`);
    return res.json() as Promise<SheetJob>;
  },
  get: async (id: string): Promise<SheetJob> => {
    const res = await fetch(`/api/v2/studio/char-sheets/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json() as Promise<SheetJob>;
  },
};
