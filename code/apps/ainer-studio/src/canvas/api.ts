/**
 * 创作画布用到的全部后端调用，一律从这里走。
 *
 * - 现有接口（board / cast / 导演出片 / 3D-BOX / 导演任务）在这里转一道，
 *   这样演示模式（?demo=1，没有后端也能看）可以整体接管。
 * - 新接口（/api/v2/studio/plans/{id}/canvas、/studio/generate …）后端还没迁移时返回 404，
 *   调用方要能降级（画布存本地、生成面板只给「出片到镜头」）。
 */
import { api as studioApi } from "../api";
import { box, type Project, type ProjectRow, type Template } from "../box/api";
// box/director 只取类型：打包器把它和用到 three 的模块合进了同一个共享块，运行时引它会把 three.js 拖进画布首包
import type { Job } from "../box/director";
import type { Board, CastMember, ChapterPlans, DirectorRun } from "../types";
import type {
  BoxInfo, CanvasCard, CanvasContext, CanvasDoc, CanvasMeta, ExecuteOptions, ExecuteState, FilmPlan, GenerateBody,
  GenerateResult, GenTaskState, ModelOption, NodeRun, QuickFilmIn, QuickFilmJob, RunOptions, RunState,
  ScreenplayExpandIn, ScreenplayResult, ScriptScene,
} from "./model";

export class HttpError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { const j = await res.json(); detail = j.detail ?? j; } catch { /* 不是 JSON */ }
    const msg = typeof detail === "string" ? detail
      : typeof (detail as { message?: string })?.message === "string" ? (detail as { message: string }).message
      : JSON.stringify(detail);
    throw new HttpError(res.status, `${res.status} ${msg}`, detail);
  }
  return res.json() as Promise<T>;
}

/** 404/405：接口还不存在（后端没升级），调用方走降级路径 */
export const missing = (e: unknown) => e instanceof HttpError && (e.status === 404 || e.status === 405);

export interface NovelRow { id: string; title: string }
export interface ChapterRow { id: string; order_no: number; title: string }
export interface MediaItem {
  id: string; url: string; kind: string; mime: string | null; bytes: number | null;
  use: string | null; use_cn: string | null; label: string | null;
  shot: string | null; speaker: string | null; entity: string | null; asset_name: string | null;
}
export interface CanvasRecord { version: number; doc: CanvasDoc | null; updated_at: string | null }
/** 一章的画布列表（第一次打开时后端自动按场次分好） */
export interface CanvasList { chapter: { id: string; title: string; novel_id: string }; plan_id: string | null; canvases: CanvasMeta[] }
/** 一张画布：元信息 + 文档 + 现取用的范围 */
export type BoardRecord = CanvasMeta & CanvasRecord & { context: CanvasContext };
export interface CanvasCreate {
  title: string; blank?: boolean; plan_id?: string | null; chapter_id?: string | null; novel_id?: string | null;
  shot_ids?: string[]; scene_ids?: string[]; purpose?: string | null; source?: "user" | "api";
}
/** 合成章节视频（POST /shot-plans/{plan}/render）的结果 */
export interface FilmResult {
  asset_id: string; url: string; duration_ms: number; shots: number; width: number; height: number;
  grade: string; production_ready: boolean; quality_blockers: string[];
}

/** 演示模式接管的那一组调用（签名与下面 cv.* 一致）。demo.ts 实现它。 */
export interface DemoApi {
  novels(): Promise<NovelRow[]>;
  chapters(novelId: string): Promise<ChapterRow[]>;
  plans(chapterId: string): Promise<ChapterPlans>;
  board(planId: string): Promise<Board>;
  cast(planId: string): Promise<CastMember[]>;
  script(planId: string, chapterId: string): Promise<ScriptScene[]>;
  canvasList(chapterId: string, planId?: string | null): Promise<CanvasList>;
  canvasAll(): Promise<CanvasMeta[]>;
  canvasGet(boardId: string): Promise<BoardRecord>;
  canvasSave(boardId: string, baseVersion: number, doc: CanvasDoc): Promise<CanvasRecord>;
  canvasSplit(planId: string): Promise<{ plan_id: string; canvases: CanvasMeta[] }>;
  canvasCreate(body: CanvasCreate): Promise<CanvasMeta>;
  canvasDelete(boardId: string): Promise<void>;
  shotCanvas(shotId: string): Promise<CanvasMeta>;
  runStart(boardId: string, opts: RunOptions): Promise<RunState>;
  runGet(runId: string): Promise<RunState>;
  runList(boardId: string): Promise<RunState[]>;
  runCancel(runId: string): Promise<RunState>;
  film(planId: string): Promise<FilmResult>;
  boxList(): Promise<ProjectRow[]>;
  boxInfo(id: string): Promise<BoxInfo>;
  boxCreate(title: string, template: string): Promise<Project>;
  boxGet(id: string): Promise<Project>;
  boxWriteFile(id: string, path: string, content: string): Promise<Project>;
  boxAsk(id: string, message: string): Promise<{ run_id: string }>;
  boxTemplates(): Promise<Template[]>;
  boxExport(id: string, blob: Blob, meta: { camera?: string; duration?: number; kind: string }): Promise<{ asset_id: string; url: string; kind: string }>;
  boxRegenerate(boxId: string, instruction?: string): Promise<{ project_id: string; kind: string; run_id?: string; scene_id?: string }>;
  directorShot(shotId: string, sceneId?: string): Promise<{ scene_id: string; blender_job_id: string; duration: number }>;
  directorPlanScene(shotId: string, instruction?: string): Promise<{ shot_id: string; scene_id: string; box_project_id: string; duration: number }>;
  directorRun(shotId: string): Promise<DirectorRun | null>;
  textVideo(planId: string, shotId: string, quality: "preview" | "final"): Promise<unknown>;
  blenderRender(boxProjectId: string, renderPlan: Record<string, unknown>): Promise<Job>;
  job(id: string): Promise<Job>;
  models(media: "image" | "video"): Promise<ModelOption[]>;
  generate(body: GenerateBody): Promise<GenerateResult>;
  genTask(id: string): Promise<GenTaskState>;
  upload(file: File): Promise<{ asset_id: string; url: string; mime: string | null }>;
  media(novelId: string): Promise<MediaItem[]>;
}

let demo: DemoApi | null = null;
/** demo.ts 在 ?demo=1 时调用 */
export function useDemoApi(d: DemoApi | null) { demo = d; }
export const isDemo = () => demo !== null;

export const cv = {
  /* ── 选书选章选计划（现有） ── */
  novels: async (): Promise<NovelRow[]> => demo ? demo.novels()
    : (await call<{ novels: NovelRow[] }>("GET", "/api/v2/console")).novels.map(n => ({ id: n.id, title: n.title })),
  chapters: async (novelId: string): Promise<ChapterRow[]> => demo ? demo.chapters(novelId)
    : (await call<{ items: ChapterRow[] }>("GET", `/api/v2/novels/${novelId}/chapters?limit=500`)).items
      .map(c => ({ id: c.id, order_no: c.order_no, title: c.title })),
  plans: (chapterId: string) => demo ? demo.plans(chapterId) : studioApi.plans(chapterId),
  board: (planId: string) => demo ? demo.board(planId) : studioApi.board(planId),
  cast: async (planId: string) => demo ? demo.cast(planId) : (await studioApi.cast(planId)).cast,

  /**
   * 剧本场次：先走新接口（按计划取，任意版本都对得上）；
   * 没有就退回 /chapters/{id}/script（只认激活剧本），再没有就空。
   */
  script: async (planId: string, chapterId: string): Promise<ScriptScene[]> => {
    if (demo) return demo.script(planId, chapterId);
    try {
      return (await call<{ scenes: ScriptScene[] }>("GET", `/api/v2/studio/plans/${planId}/script`)).scenes;
    } catch (e) {
      if (!missing(e)) throw e;
    }
    try {
      return (await call<{ scenes: ScriptScene[] }>("GET", `/api/v2/chapters/${chapterId}/script`)).scenes;
    } catch {
      return [];
    }
  },

  /* ── 一章多张画布（新） ── */
  /** 这一章的画布：整章总览 + 按场次分的 + 自建的；第一次打开时后端自动分 */
  canvasList: (chapterId: string, planId?: string | null) => demo ? demo.canvasList(chapterId, planId)
    : call<CanvasList>("GET", `/api/v2/studio/chapters/${chapterId}/canvases${planId ? `?plan_id=${encodeURIComponent(planId)}` : ""}`),
  canvasGet: (boardId: string) => demo ? demo.canvasGet(boardId)
    : call<BoardRecord>("GET", `/api/v2/studio/canvases/${boardId}`),
  /** 版本不一致抛 HttpError(409) */
  canvasSave: (boardId: string, baseVersion: number, doc: CanvasDoc) => demo ? demo.canvasSave(boardId, baseVersion, doc)
    : call<CanvasRecord>("PUT", `/api/v2/studio/canvases/${boardId}`, { base_version: baseVersion, doc }),
  /** 重新按场次分（已有画布按场次认回，布局不丢） */
  canvasSplit: (planId: string) => demo ? demo.canvasSplit(planId)
    : call<{ plan_id: string; canvases: CanvasMeta[] }>("POST", `/api/v2/studio/plans/${planId}/canvases:split`, {}),
  canvasCreate: (body: CanvasCreate) => demo ? demo.canvasCreate(body)
    : call<CanvasMeta>("POST", "/api/v2/studio/canvases", { source: "user", ...body }),
  canvasDelete: async (boardId: string) => {
    if (demo) return demo.canvasDelete(boardId);
    const res = await fetch(`/api/v2/studio/canvases/${boardId}`, { method: "DELETE" });
    if (!res.ok) throw new HttpError(res.status, `${res.status} ${await res.text()}`);
  },
  /** 分镜画布「进入创作画布」：这一镜所在的场次画布 */
  shotCanvas: (shotId: string) => demo ? demo.shotCanvas(shotId)
    : call<CanvasMeta>("GET", `/api/v2/studio/shots/${shotId}/canvas`),

  /** 小说角色一键重出定妆照（本机：正面全身 → 其余角度 → 设定图，后台串着跑）；演示模式不支持 */
  charRefs: (entityId: string) => demo ? Promise.reject(new Error("演示数据不能重出定妆照"))
    : call<{ state: string; step: string }>("POST", `/api/v2/characters/e:${entityId}:references`, {}),

  /* ── 画布首页、服务端执行器、想法 → 分镜（新；演示模式不支持） ── */
  /** 全部画布（首页）：最近改过的在前；source=user|api|auto 过滤，free=true 只要不挂章节的 */
  canvasAll: (q: { limit?: number; free?: boolean } = {}) => demo ? demo.canvasAll().then(rows => rows.filter(b => !q.free || (!b.chapter_id && !b.plan_id)).slice(0, q.limit ?? 60).map(b => ({ ...b, cover: null, nodes: 0 })))
    : call<{ canvases: CanvasCard[] }>("GET", `/api/v2/studio/canvases?limit=${q.limit ?? 60}${q.free ? "&free=1" : ""}`)
      .then(r => r.canvases),
  /** 改标题 */
  canvasRename: (boardId: string, title: string) => demo ? Promise.reject(new Error("演示数据不能改名"))
    : call<CanvasMeta>("PATCH", `/api/v2/studio/canvases/${boardId}`, { title }),
  /** 按节点配方在服务端跑（读的是库里那份文档，调用前先存盘） */
  execute: (boardId: string, opts: ExecuteOptions = {}) => demo ? Promise.reject(new Error("演示数据不能在服务端执行"))
    : call<ExecuteState>("POST", `/api/v2/studio/canvases/${boardId}:execute`, opts),
  /** 各节点最近一次运行 + 执行器状态 */
  nodeRuns: (boardId: string) => demo ? Promise.resolve({ runs: [] as NodeRun[], exec: null as ExecuteState | null })
    : call<{ runs: NodeRun[]; exec: ExecuteState | null }>("GET", `/api/v2/studio/canvases/${boardId}/node-runs`),
  stopExecute: (boardId: string) => demo ? Promise.reject(new Error("演示数据不能在服务端执行"))
    : call<ExecuteState>("POST", `/api/v2/studio/canvases/${boardId}:stop`, {}),
  /** 一句想法 → 本机 LLM 拆的导演分镜（场景、人物外观、2–4 镜首帧/运动/时长；镜头首尾呼应） */
  filmPlan: (body: { idea: string; shots: number; has_outfit: boolean; has_scene: boolean }) =>
    demo ? Promise.reject(new Error("演示数据不能拆分镜")) : call<FilmPlan>("POST", "/api/v2/studio/film-plans", body),
  /** 想法/文本 + 设定器参数 → LLM 剧本扩写与世界观转译 */
  screenplayExpand: (body: ScreenplayExpandIn) =>
    demo ? Promise.reject(new Error("演示数据不能扩写剧本")) : call<ScreenplayResult>("POST", "/api/v2/studio/screenplay-expand", body),

  /* ── 快速成片（纳逗式一条龙：照片 + 一句话 → 定妆照 → 分镜图 → 短片），演示模式不支持 ── */
  quickStart: (body: QuickFilmIn) => demo ? Promise.reject(new Error("演示数据不能快速成片"))
    : call<QuickFilmJob>("POST", "/api/v2/studio/quick-films", body),
  quickGet: (id: string) => call<QuickFilmJob>("GET", `/api/v2/studio/quick-films/${id}`),

  /* ── 一键出片工作流（新） ── */
  runStart: (boardId: string, opts: RunOptions) => demo ? demo.runStart(boardId, opts)
    : call<RunState>("POST", `/api/v2/studio/canvases/${boardId}:run`, opts),
  runGet: (runId: string) => demo ? demo.runGet(runId) : call<RunState>("GET", `/api/v2/studio/runs/${runId}`),
  runList: (boardId: string) => demo ? demo.runList(boardId)
    : call<RunState[]>("GET", `/api/v2/studio/canvases/${boardId}/runs?limit=3`),
  runCancel: (runId: string) => demo ? demo.runCancel(runId) : call<RunState>("POST", `/api/v2/studio/runs/${runId}:cancel`, {}),
  /** 合成章节视频：整章时间线（有视频用视频，没有用首尾帧溶解）导成一支 mp4。同步接口，可能要几分钟 */
  film: (planId: string) => demo ? demo.film(planId)
    : call<FilmResult>("POST", `/api/v2/shot-plans/${planId}/render`, {}),

  /* ── 3D-BOX（现有 /scene3d/*；轻量 doc 走新接口，没有就退回全量） ── */
  boxList: () => demo ? demo.boxList() : box.projects(),
  boxInfo: async (id: string): Promise<BoxInfo> => {
    if (demo) return demo.boxInfo(id);
    try {
      return await call<BoxInfo>("GET", `/api/v2/studio/box/${id}/doc`);
    } catch (e) {
      if (!missing(e)) throw e;
    }
    const p = await box.get(id);
    return {
      id: p.id, title: p.title, thumb_url: p.thumb_url, updated_at: p.updated_at, ok: p.ok,
      duration: p.doc?.duration ?? p.duration, doc: p.doc, active_run: p.active_run,
      cameras: (p.doc?.cameras ?? []).map(c => ({ id: c.id, name: c.name })),
    };
  },
  boxCreate: (title: string, template = "blank") => demo ? demo.boxCreate(title, template) : box.create(title, template),
  boxGet: (id: string) => demo ? demo.boxGet(id) : box.get(id),
  boxWriteFile: (id: string, path: string, content: string) =>
    demo ? demo.boxWriteFile(id, path, content) : box.writeFile(id, path, content),
  /** 让 3D-BOX 智能体按一段话搭景/改景（异步；完成看 active_run 清空） */
  boxAsk: (id: string, message: string) => demo ? demo.boxAsk(id, message)
    : box.ask(id, { message, selected: [], sketches: [] }),
  boxTemplates: () => demo ? demo.boxTemplates() : box.templates(),
  /** 录好的白模预演（webm）存回 3D-BOX 项目：kind=preview|thumb */
  boxExport: (id: string, blob: Blob, meta: { camera?: string; duration?: number; kind: string }) =>
    demo ? demo.boxExport(id, blob, meta) : box.exportFile(id, blob, meta, `${meta.kind}.${meta.kind === "thumb" ? "png" : "webm"}`),
  /** 重新生成 3D 白模场景（关联镜头走重新规划，独立项目走智能体） */
  boxRegenerate: (boxId: string, instruction?: string) => demo ? demo.boxRegenerate(boxId, instruction)
    : call<{ project_id: string; kind: string; run_id?: string; scene_id?: string }>(
      "POST", `/api/v2/studio/box/${boxId}:regenerate`, instruction ? { instruction } : {}),

  /* ── 镜头出片（现有） ── */
  /** 导演出片：LLM 搭白模 → Blender 预演 → 身份首帧 → LTX 2.5；sceneId = 用已有导演场景重出 */
  directorShot: (shotId: string, sceneId?: string) => demo ? demo.directorShot(shotId, sceneId) : studioApi.directorShot(shotId, sceneId),
  /** 为镜头重新规划与生成 3D 白模场景（不渲染） */
  directorPlanScene: (shotId: string, instruction?: string) => demo ? demo.directorPlanScene(shotId, instruction)
    : call<{ shot_id: string; scene_id: string; box_project_id: string; duration: number }>(
      "POST", `/api/v2/director/shots/${shotId}:plan-scene`, instruction ? { instruction } : {}),
  directorRun: async (shotId: string) => demo ? demo.directorRun(shotId) : (await studioApi.directorRun(shotId)).run,
  /** 文字出片（LTX 2.5，不搭景） */
  textVideo: (planId: string, shotId: string, quality: "preview" | "final" = "final") =>
    demo ? demo.textVideo(planId, shotId, quality) : studioApi.video(planId, shotId, quality),

  /* ── 白模 → 控制素材（现有 /director/jobs/*） ── */
  blenderRender: (boxProjectId: string, renderPlan: Record<string, unknown>) =>
    demo ? demo.blenderRender(boxProjectId, renderPlan)
      : call<Job>("POST", "/api/v2/director/jobs/blender-render", { box_project_id: boxProjectId, render_plan: renderPlan }),
  job: (id: string) => demo ? demo.job(id) : call<Job>("GET", `/api/v2/director/jobs/${id}`),

  /* ── 自由生成（新） ── */
  models: (media: "image" | "video") => demo ? demo.models(media)
    : call<{ models: ModelOption[] }>("GET", `/api/v2/studio/models?media=${media}`).then(r => r.models),
  generate: (body: GenerateBody) => demo ? demo.generate(body)
    : call<GenerateResult>("POST", "/api/v2/studio/generate", body),
  genTask: (id: string) => demo ? demo.genTask(id)
    : call<GenTaskState>("GET", `/api/v2/studio/generate/${id}`),
  upload: async (file: File) => {
    if (demo) return demo.upload(file);
    const fd = new FormData();
    fd.append("file", file, file.name);
    const res = await fetch("/api/v2/studio/uploads", { method: "POST", body: fd });
    if (!res.ok) throw new HttpError(res.status, `${res.status} ${await res.text()}`);
    return res.json() as Promise<{ asset_id: string; url: string; mime: string | null }>;
  },

  /* ── 资产管理（现有） ── */
  media: async (novelId: string): Promise<MediaItem[]> => demo ? demo.media(novelId)
    : (await call<{ items: MediaItem[] }>("GET", `/api/v2/novels/${novelId}/media?limit=200`)).items,
};

export { media } from "../api";
