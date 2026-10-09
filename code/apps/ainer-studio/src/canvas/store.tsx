/**
 * 创作画布的 store：载入、受控图、现取真身、保存、唯一轮询器、快捷键。
 *
 * 渲染性能的取舍（200+ 镜要撑住）：
 *   - 拖动节点时 nodes 每帧都变。如果 store 这个 context 跟着变，所有 useCanvas() 的组件
 *     （每个节点、每条边、外壳）每帧都重渲染，memo 拦不住 context。
 *   - 所以 nodes/edges 放在只给 <Flow> 用的 GraphCtx 里；store 只在「结构变化」（增删、改 data、
 *     选中、连线、live/任务/提示/浮层变化）时换新对象。纯位置/尺寸变化不换。
 *   - store 上的 nodes/edges/live/tasks/selected 等字段是 getter，读的是 ref 里的最新值：
 *     动作函数（three/actions 等）跨 await 拿着旧的 s 也读得到最新数据。
 *
 * Provider 必须包在 ReactFlowProvider 里面（用到 useReactFlow）。
 */
import { prod } from "../production/api";
import { readCtx, writeCtx } from "../ctx";
import {
  createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react";
import {
  applyEdgeChanges, applyNodeChanges, useNodesData, useNodesInitialized, useReactFlow,
  type Connection, type EdgeChange, type IsValidConnection, type NodeChange, type OnConnect,
  type OnEdgesChange, type OnMove, type OnNodesChange, type XYPosition,
} from "@xyflow/react";
import { cv, HttpError, media, missing, useDemoApi, type DemoApi } from "./api";
import type { CanvasStore, SaveState, Toast } from "./contract";
import {
  DOC_SCHEMA, isDerived, isProductionRef, nodeIdOf,
  type BoxInfo, type CanvasDoc, type CreateCanvasOptions, type CanvasMeta, type CEdge, type CNode, type CNodeData, type DocNode, type EdgeKind,
  type ExecuteOptions, type ExecuteState, type GenState, type GenTaskState, type LiveSources, type MediaRef, type NodeKind,
  type NodeRef, type NodeRun, type Recipe, type Resolved, type RunOptions, type RunState, type ScriptScene, type TrackedTask,
} from "./model";
import {
  autoLayout, buildGraph, derivedGraph, estimateSize, findFreeSpot, introNodeIds, rectOf, resolveRef, resolvedText, syncDerived,
} from "./importer";
import { isEmptyGen } from "./actions";
import { addCharacterToBox, askBox, onBlenderDone, onBoxAgentDone } from "./three/actions";
import { directorPending } from "../shotStatus";
import type { Board, CastMember } from "../types";

/* ───────────────────────── 常量与小工具 ───────────────────────── */

/** SearchPalette 监听它：⌘K / 「/」由 store 统一判断（浮层、输入框里不触发），再广播出去 */
export const SEARCH_EVENT = "cv:search";

const SAVE_DEBOUNCE = 1000;
const TASK_EVERY = 4000;
const BOARD_EVERY = 6000;
const LTX_TIMEOUT = 20 * 60 * 1000;
const LONG_TIMEOUT = 45 * 60 * 1000;
const LOCAL_KEY = (board: string) => `ainer.canvas.v2.${board}`;

const FINISHED = new Set<TrackedTask["status"]>(["succeeded", "failed", "cancelled"]);
const isLive = (s: TrackedTask["status"]) => !FINISHED.has(s);
const MISSING: Resolved = { kind: "missing" };
const EMPTY_LIVE: LiveSources = {
  board: null, cast: [], script: [], boxes: {}, runs: {}, chapterTitle: "", novelTitle: "",
  scope: { shotIds: null, castIds: null }, voices: {},
};
const ACTIVE_RUN = new Set<RunState["status"]>(["queued", "running"]);

/** 服务端执行器：多久拉一次 node-runs（规格 3 秒；轮询器每秒 tick 一次，到点才发） */
const EXEC_EVERY = 3000;
const RUN_LIVE = new Set<NodeRun["status"]>(["queued", "waiting", "running"]);
const EXEC_LIVE = new Set<ExecuteState["status"]>(["queued", "running"]);
/** 执行器建的 run id 前缀（be-exec 约定）；载入时用它认出「不是 /studio/generate 的任务」，免得旧轮询去查 */
const EXEC_RUN_PREFIX = "nrun";
/** 重新生成前的旧结果最多留几个（model.ts CNodeData.history） */
const HISTORY_MAX = 12;
/** 编组：包围盒四周外扩、上方再给子节点的小标题留一条 */
const GROUP_PAD = 24;
const GROUP_HEAD = 28;
/** 没给尺寸的分组（新增菜单直接加的空分组）默认多大 */
const GROUP_SIZE = { w: 520, h: 360 };
/** 自动命名（纳逗式「图片 13」「分组 4」） */
const TITLE_PREFIX: Record<NodeKind, string> = { stage: "舞台", coverage: "镜头", image: "图片", video: "视频", audio: "音频", text: "文本", group: "分组", box3d: "白模" };
/** 复制出来的节点相对原节点往右下错开多少 */
const COPY_OFFSET = 40;

/** 默认打开哪张：第一张场次画布（整章总览镜头多，留给需要看全局的时候）；没有就整章总览 */
function defaultBoard(list: CanvasMeta[]): CanvasMeta | null {
  const live = list.filter(b => !b.stale);
  return live.find(b => b.kind === "scene") ?? live.find(b => b.kind === "plan") ?? live[0] ?? list[0] ?? null;
}

/** 快速成片各步大致进度（百分比） */
const QUICK_STEP: Record<string, number> = { plan: 5, look: 15, outfit: 25, scene: 35, frame: 55, video: 80, concat: 95, done: 100 };
function quickStepText(step: string): string {
  const [k, n] = step.split(":");
  const zh: Record<string, string> = { plan: "拆分镜", look: "定妆照", outfit: "换装定妆照", scene: "场景图", frame: "分镜图", video: "出视频", concat: "拼接", done: "完成" };
  return `${zh[k] ?? k}${n ? ` ${n}` : ""}`;
}

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));
const round = (v: number, d = 1) => Math.round(v * 10 ** d) / 10 ** d;
const uniq = <T,>(xs: (T | null | undefined)[]) => [...new Set(xs.filter((x): x is T => x != null && x !== ""))];

/**
 * 地址栏记住当前选择（ctx.ts 的约定，和分镜画布、3D-BOX、角色库共用）：刷新、分享、顶部 Nav 切视图都回到同一处。
 * 换书 / 换章 / 换计划时 writeCtx 级联清掉下级（旧的 plan、canvas、shot 不残留）。
 */
function remember(key: "novel" | "chapter" | "plan" | "canvas" | "shot", value: string | null) {
  try { writeCtx({ [key]: value }); } catch { /* 沙箱里没有 history 也不影响画布 */ }
}

/**
 * 一次写好几项：打开别的章的画布时书/章/计划/画布要一起换。
 * 分开写的话，先写的 novel 会按级联规则把 chapter/plan/canvas 从地址栏清掉，后面的载入链就读不到 canvas 了。
 */
function rememberAll(patch: { project?: string | null; novel?: string | null; chapter?: string | null; plan?: string | null; canvas?: string | null; shot?: string | null }) {
  try { writeCtx(patch); } catch { /* 同上 */ }
}

/** /media 地址比较：后端有时给 http://localhost:8100/media/…，有时给 /media/… */
const sameUrl = (a: string | null | undefined, b: string | null | undefined) => !!a && !!b && (media(a) ?? a) === (media(b) ?? b);

function readLocal(board: string): CanvasDoc | null {
  try {
    const raw = localStorage.getItem(LOCAL_KEY(board));
    return raw ? validDoc(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

function writeLocal(board: string, doc: CanvasDoc): boolean {
  try {
    localStorage.setItem(LOCAL_KEY(board), JSON.stringify(doc));
    return true;
  } catch {
    return false;
  }
}

function validDoc(doc: unknown): CanvasDoc | null {
  if (!doc) return null;
  const d = doc as CanvasDoc;
  if (d.schema === DOC_SCHEMA && Array.isArray(d.nodes) && Array.isArray(d.edges)) return d;
  console.warn("[canvas] 画布文档格式不认识，按空画布载入", doc);
  return null;
}

/** 文档里只许 /media 同源地址或 data:（铁律 2）；网关临时地址进不了文档 */
function docMedia(m: MediaRef): MediaRef | null {
  const url = m.url.startsWith("data:") ? m.url : media(m.url);
  if (!url || !(url.startsWith("/media/") || url.startsWith("data:"))) {
    console.warn("[canvas] 非同源媒体地址不进文档：", m.url);
    return null;
  }
  return url === m.url ? m : { ...m, url };
}

/**
 * dropGen：这个节点的 gen 是服务端执行器的进度（store 从 node-runs 抄过来的），不进文档 ——
 * 进度的真身在 studio_node_runs，下次载入现拉；存进文档的话载入时还会被当成 /studio/generate 的任务去轮询。
 */
function toDocNode(n: CNode, dropGen = false): DocNode {
  const d = n.data;
  let data: DocNode["data"];
  if (isDerived(d.ref) || isProductionRef(d.ref)) {
    // 派生节点只存指针和少量视图状态（铁律 1）
    data = { ref: d.ref, title: d.title };
    if (d.role) data.role = d.role;
    if (d.camera !== undefined) data.camera = d.camera;
    if (d.pinned) data.pinned = true;
    if (d.live) data.live = true;
    // 导演产物没有「按 job+output 现取」的接口，它的 /media 地址就是指针本身
    if (d.ref.kind === "director_output" && d.media) data.media = docMedia(d.media);
  } else {
    const { orphan, gen, ...rest } = d;
    void orphan;
    data = dropGen || gen === undefined ? rest : { ...rest, gen };
    if (rest.media) data = { ...data, media: docMedia(rest.media) };
    // 历史里的旧图同样只许同源地址（铁律 2）
    if (rest.history) data = { ...data, history: rest.history.map(docMedia).filter((m): m is MediaRef => !!m) };
  }
  const out: DocNode = { id: n.id, type: n.type ?? "text", position: { x: round(n.position.x), y: round(n.position.y) }, data };
  // 分组里的节点：position 是相对分组左上角的（xyflow parentId）
  if (n.parentId) out.parentId = n.parentId;
  if (n.width) out.width = n.width;
  if (n.height) out.height = n.height;
  return out;
}

/**
 * 文档 → xyflow 节点之后补上分组关系（importer.buildGraph 只认位置和 data）：
 *   - 子节点挂回 parentId；拖到边上时分组跟着长大（expandParent）
 *   - xyflow 要求父节点在数组里排在子节点前面：分组一律放最前（也让分组框垫在最底下）
 * 分组不在了的孤儿子节点保持原样（位置是相对坐标，会偏，但不丢）。
 */
function adoptGroups(nodes: CNode[], saved: { id: string; parentId?: string | null }[]): CNode[] {
  const groups = nodes.filter(n => n.type === "group");
  if (!groups.length) return nodes;
  const groupIds = new Set(groups.map(n => n.id));
  const parentOf = new Map(saved.filter(n => n.parentId).map(n => [n.id, n.parentId as string]));
  const rest = nodes.filter(n => n.type !== "group").map(n => {
    const p = parentOf.get(n.id);
    return p && groupIds.has(p) ? { ...n, parentId: p, expandParent: true } : n;
  });
  return [...groups, ...rest];
}

/** 配方里引用的节点改名（复制一组节点时，组内互相引用的指向复制品） */
function remapRecipe(rc: Recipe, idMap: Map<string, string>): Recipe {
  const to = (id: string) => idMap.get(id) ?? id;
  return {
    ...rc,
    refs: rc.refs.map(x => ({ ...x, node: to(x.node) })),
    prompt: rc.prompt.map(sg => (sg.t === "ref" ? { ...sg, node: to(sg.node) } : sg)),
    segments: rc.segments ? rc.segments.map(sg => ({ ...sg, node: to(sg.node) })) : rc.segments,
  };
}

/** 「图片 3」→「图片 3 拷贝1」；再复制「图片 3 拷贝1」→「图片 3 拷贝2」（不叠成「拷贝1 拷贝1」） */
function copyTitle(base: string, taken: Set<string>): string {
  const root = base.replace(/\s*拷贝\s*\d*$/, "") || base;
  for (let k = 1; ; k++) {
    const t = `${root} 拷贝${k}`;
    if (!taken.has(t)) return t;
  }
}

/** 执行器的 op → 产物是图还是视频（节点类型跟着产物走） */
const OP_VIDEO = new Set<NodeRun["op"]>(["video", "concat", "one_take"]);

/** 执行器报错的人话：后端 detail 可能是字符串，也可能是 {message} */
function execError(e: unknown): string {
  if (e instanceof HttpError) {
    const d = e.detail as { message?: string } | string | undefined;
    if (typeof d === "string") return d;
    if (d?.message) return d.message;
  }
  return msg(e);
}

const boxOfShot = (s: Board["shots"][number]) => s.director?.run?.box_project_id ?? null;

/** 要拿轻量信息的白模：画布范围内导演链搭的 + 画布上自己加的（AssetsDrawer、AddMenu 拖进来的） */
function boxIdsOf(board: Board | null, nodes: ReadonlyArray<{ data: unknown }>, scope: Set<string> | null = null): string[] {
  return uniq<string>([
    ...(board?.shots ?? []).filter(s => !scope || scope.has(s.id)).map(boxOfShot),
    ...nodes.map(n => {
      const ref = (n.data as { ref?: NodeRef } | null)?.ref;
      return ref?.kind === "box_project" ? ref.id : null;
    }),
  ]);
}

async function pool<T>(items: T[], n: number, fn: (x: T) => Promise<void>) {
  let i = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (i < items.length) await fn(items[i++]);
  }));
}

/** 批量拿白模轻量信息。404 = 项目真没了（节点会标失效）；其它错误给个占位，等 loadBoxDoc 再试 */
async function fetchBoxes(ids: string[]): Promise<Record<string, BoxInfo>> {
  const out: Record<string, BoxInfo> = {};
  await pool(ids, 6, async id => {
    try {
      out[id] = await cv.boxInfo(id);
    } catch (e) {
      if (!missing(e)) out[id] = { id, title: "3D 白模", thumb_url: null, updated_at: null, doc: null };
    }
  });
  return out;
}

/** 后端的 doc 可能不带（轻量接口）：不带就保留已经载入的那份 */
function mergeBoxes(cur: Record<string, BoxInfo>, got: Record<string, BoxInfo>): Record<string, BoxInfo> {
  const ids = Object.keys(got);
  if (!ids.length) return cur;
  const next = { ...cur };
  for (const id of ids) next[id] = { ...cur[id], ...got[id], doc: got[id].doc ?? cur[id]?.doc ?? null };
  return next;
}

function guessMime(url: string, kind: string): string {
  const data = /^data:([^;,]+)/.exec(url);
  if (data) return data[1];
  const ext = /\.([a-z0-9]+)(?:[?#]|$)/i.exec(url)?.[1]?.toLowerCase();
  const map: Record<string, string> = {
    png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", gif: "image/gif", svg: "image/svg+xml",
    mp4: "video/mp4", webm: "video/webm", mov: "video/quicktime", mp3: "audio/mpeg", wav: "audio/wav",
  };
  return (ext && map[ext]) || (kind === "video" ? "video/mp4" : kind === "audio" ? "audio/mpeg" : "image/png");
}

const sameGen = (a: GenState | null | undefined, b: GenState) =>
  !!a && a.status === b.status && a.progress === b.progress && a.error === b.error && a.task_id === b.task_id;

const IDENTITY_IMAGE = new Set(["character", "sheet", "view", "upload", "generated"]);

/**
 * 连线语义按两端推断（onConnect 与 AddMenu 的「接在这一侧」共用）：
 *   定妆照/设定图/上传/生成的图 → 视频或白模 = identity（谁的脸）
 *   白模 → 视频、预演/控制素材 → 视频 = control（构图、站位、运镜）
 *   其余 = ref
 */
export function inferEdgeKind(source: Pick<CNode, "type" | "data">, target: Pick<CNode, "type">): EdgeKind {
  const t = target.type;
  const role = source.data.role ?? "";
  if (source.type === "image" && IDENTITY_IMAGE.has(role) && (t === "video" || t === "box3d")) return "identity";
  if (source.type === "stage" || source.type === "coverage") return "control";
  if (source.type === "box3d" && t === "video") return "control";
  // 控制素材（深度/姿态/线稿）有的是图、有的是视频，都按 control 接
  if ((source.type === "video" || source.type === "image") && (role === "previs" || role === "control") && t === "video") return "control";
  return "ref";
}

/** 读写同时要「立刻拿到最新值」（ref）和「触发渲染」（state） */
function useRefState<T>(init: T): [T, { current: T }, (v: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(init);
  const ref = useRef<T>(value);
  const [set] = useState(() => (v: T | ((prev: T) => T)) => {
    const next = typeof v === "function" ? (v as (prev: T) => T)(ref.current) : v;
    if (Object.is(next, ref.current)) return;
    ref.current = next;
    setValue(next);
  });
  return [value, ref, set];
}

/* ───────────────────────── 演示模式 ───────────────────────── */

const readDemo = () => {
  try { return new URLSearchParams(location.search).get("demo") === "1"; } catch { return false; }
};

let demoApi: DemoApi | null = null;
/** demo.ts 只在 ?demo=1 时才加载：真实模式的包里不带演示数据和场景编译器 */
async function loadDemo(): Promise<DemoApi> {
  const api = demoApi ?? (await import("./demo")).createDemoApi();
  demoApi = api;
  return api;
}

/* ───────────────────────── context ───────────────────────── */

const StoreCtx = createContext<CanvasStore | null>(null);

interface LiveCtxValue { live: LiveSources; nodeData(id: string): CNodeData | undefined }
const LiveCtx = createContext<LiveCtxValue | null>(null);

/** 只给 <Flow> 用：受控 nodes/edges（每帧变）和几个 ReactFlow 回调 */
export interface FlowBinding {
  nodes: CNode[];
  edges: CEdge[];
  onMoveEnd: OnMove;
  isValidConnection: IsValidConnection<CEdge>;
  onPaneClick(): void;
}
const GraphCtx = createContext<FlowBinding | null>(null);

export function useCanvas(): CanvasStore {
  const s = useContext(StoreCtx);
  if (!s) throw new Error("useCanvas() 要在 <CanvasProvider> 里用");
  return s;
}

export function useFlowBinding(): FlowBinding {
  const g = useContext(GraphCtx);
  if (!g) throw new Error("useFlowBinding() 要在 <CanvasProvider> 里用");
  return g;
}

/**
 * 按节点 id 现取真身。订阅的是这个节点自己的 data（xyflow 的 useNodesData）和 live：
 * 拖别的节点、选中变化都不会让它重算。
 */
export function useNodeResolved(id: string): Resolved {
  const ctx = useContext(LiveCtx);
  if (!ctx) throw new Error("useNodeResolved() 要在 <CanvasProvider> 里用");
  const fromFlow = useNodesData<CNode>(id);
  const data = (fromFlow?.data as CNodeData | undefined) ?? ctx.nodeData(id);
  return useMemo(() => (data ? resolveRef(ctx.live, data.ref, data) : MISSING), [ctx.live, data]);
}

/* ───────────────────────── Provider ───────────────────────── */

type PlanRow = CanvasStore["pick"]["plans"][number];
type Overlay = CanvasStore["overlay"];
type AddMenu = CanvasStore["addMenu"];
/** demo：这张画布是不是演示模式（取 Provider 的地址栏标记）。卸载时演示接口先被摘掉、存盘后到，不记的话最后一次存盘会漏到真后端 */
interface Snap { board: string; doc: CanvasDoc; local: boolean; demo: boolean }

export function CanvasProvider({ children }: { children: ReactNode }) {
  const rf = useReactFlow<CNode, CEdge>();
  const rfRef = useRef(rf);
  rfRef.current = rf;

  const [resourceNonce, setResourceNonce] = useState(0);
  const [demo] = useState(readDemo);
  const [demoReady, setDemoReady] = useState(!demo);

  const q = useMemo(() => new URLSearchParams(location.search), []);
  /**
   * 画布首页：地址栏既没有 canvas 也没有书/章/计划时显示（不再默认跳第一本书 ——
   * 自由画布（旅拍、相册、一个想法）和小说章节画布是平级的入口）。
   */
  const [home, homeRef, setHome] = useRefState(!q.get("canvas") && !q.get("novel") && !q.get("chapter") && !q.get("plan"));
  const [novelId, novelIdRef, setNovelId] = useRefState(q.get("novel") ?? "");
  const [chapterId, chapterIdRef, setChapterId] = useRefState(q.get("chapter") ?? "");
  const [planId, planIdRef, setPlanId] = useRefState(q.get("plan") ?? "");
  /** 当前这张画布（一章多张：整章总览 / 场次 / 自建） */
  const [boardId, boardIdRef, setBoardId] = useRefState(q.get("canvas") ?? "");
  const [boards, boardsRef, setBoards] = useRefState<CanvasMeta[]>([]);
  /** 这张画布上最近一次「一键出片」 */
  const [flowRun, flowRunRef, setFlowRun] = useRefState<RunState | null>(null);
  /** 带过来的镜头（?shot=，旧链接 ?focus=）：落在它所在的场次画布，载入后飞过去并选中（只用一次） */
  const focusRef = useRef(readCtx().shot ?? "");
  const [novels, novelsRef, setNovels] = useRefState<{ id: string; title: string }[]>([]);
  const [chapters, chaptersRef, setChapters] = useRefState<{ id: string; order_no: number; title: string }[]>([]);
  const [plans, , setPlans] = useRefState<PlanRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [nodes, nodesRef, setNodes] = useRefState<CNode[]>([]);
  const [edges, edgesRef, setEdges] = useRefState<CEdge[]>([]);
  /** 结构版本：只有它变，store 才换新对象（见文件头） */
  const [rev, setRev] = useState(0);
  const [live, liveRef, setLive] = useRefState<LiveSources>(EMPTY_LIVE);
  const [tasks, tasksRef, setTasks] = useRefState<TrackedTask[]>([]);
  const [toasts, toastsRef, setToasts] = useRefState<Toast[]>([]);
  const [overlay, overlayRef, setOverlay] = useRefState<Overlay>(null);
  const [addMenu, addMenuRef, setAddMenu] = useRefState<AddMenu>(null);
  const [save, saveRef, setSave] = useRefState<SaveState>("idle");
  /** 当前画布的元信息（canvasGet 带回来的）：自由画布不在任何章节的列表里，顶栏的标题、类型从这里拿 */
  const [meta, , setMeta] = useRefState<CanvasMeta | null>(null);
  /** 服务端执行器：这张画布的执行状态、各节点最近一次运行 */
  const [, execRef, setExec] = useRefState<ExecuteState | null>(null);
  const [, nodeRunsRef, setNodeRuns] = useRefState<Record<string, NodeRun>>({});
  const [pendingFit, setPendingFit] = useState<{ ids: string[] | null; select?: string } | null>(null);

  const r = useRef({
    hidden: new Set<string>(),
    /** 当前这张图属于哪份计划（载入中为空：这时不存盘） */
    loadedPlan: "",
    /** 当前这张画布（存盘按它；切画布时先存旧的） */
    loadedBoard: "",
    /** 工作流已经看到成功了几镜：多了就刷 board，新片子马上挂上 */
    runSeen: new Map<string, number>(),
    /** 快速成片：每个任务已经长到画布上的产物数、最后一个产物节点（下一个接在它后面） */
    quickSeen: new Map<string, { n: number; last: string; look: string | null }>(),
    versions: new Map<string, number>(),
    local: false,
    dirty: false,
    blocked: false,
    saveTimer: 0,
    pendingSnap: null as Snap | null,
    /** 正在发的那一串 PUT（flushSave 要能 await 到「这一刻的快照存好了」） */
    pumpP: null as Promise<void> | null,
    loadToken: 0,
    navigationToken: 0,
    /** 地址栏 / 首页直接打开、但 404 了的画布：章节列表到了按默认那张开，别再「留着它」 */
    loadFailed: "",
    /** 画布列表是哪一章的（404 时判断「列表已经到了、确实没有可退的」） */
    boardsFor: "",
    /* 服务端执行器 */
    lastExecTick: 0,
    execBusy: false,
    execErrors: 0,
    /** 连续查不到 / 后端没有这个接口：不再轮询，直到下一次 execute */
    execGiveUp: false,
    /** 这次会话里见过在跑的 run：只有它们失败才盖到已经有图的节点上（旧的失败不挡住旧图） */
    runLiveSeen: new Set<string>(),
    /** store 抄进节点 gen 的 run id：存盘时剥掉，不当成 /studio/generate 的任务 */
    execGenIds: new Set<string>(),
    suppressMoveUntil: 0,
    boxInflight: new Map<string, Promise<void>>(),
    reload: null as { p: Promise<void>; full: boolean } | null,
    ticking: false,
    lastTaskTick: 0,
    lastBoardTick: 0,
    boardBusy: false,
    seenActive: new Set<string>(),
    pollErrors: new Map<string, number>(),
    toastSeq: 0,
    mapCache: { arr: null as CNode[] | null, map: new Map<string, CNode>() },
    store: null as CanvasStore | null,
  }).current;

  /* 方法：只建一次，全部读 ref，所以对外稳定（不会因为 store 换对象而变） */
  const m = useMemo(() => {
    const S = () => r.store!;
    const bump = () => setRev(v => v + 1);

    function nodeMap(): Map<string, CNode> {
      const arr = nodesRef.current;
      if (r.mapCache.arr !== arr) r.mapCache = { arr, map: new Map(arr.map(n => [n.id, n])) };
      return r.mapCache.map;
    }
    const nodeById = (id: string) => nodeMap().get(id);

    /* ── 提示 ── */
    function dismissToast(id: number) {
      setToasts(p => (p.some(t => t.id === id) ? p.filter(t => t.id !== id) : p));
    }
    function toast(text: string, tone: Toast["tone"] = "info", action?: Toast["action"]) {
      const last = toastsRef.current.at(-1);
      // 轮询报错之类的同一句话不刷屏
      if (last && last.text === text && !action && !last.action) return;
      const id = ++r.toastSeq;
      // 消失计时在 chrome/Toasts 里（鼠标停在上面时暂停，免得正要点「撤销」它就没了）
      setToasts(p => [...p.slice(-4), { id, text, tone, action }]);
    }

    /* ── 保存 ── */
    /** 节点上的 gen 是执行器进度（不是 /studio/generate 的任务） */
    const execGen = (g: GenState | null | undefined) =>
      !!g && (r.execGenIds.has(g.task_id) || g.task_id.startsWith(EXEC_RUN_PREFIX));

    function serialize(): CanvasDoc {
      const vp = rfRef.current.getViewport();
      return {
        schema: DOC_SCHEMA,
        viewport: { x: round(vp.x), y: round(vp.y), zoom: round(vp.zoom, 3) },
        nodes: nodesRef.current.map(n => toDocNode(n, execGen(n.data.gen))),
        edges: edgesRef.current.filter(e => !e.data?.derived).map(e => ({
          id: e.id, source: e.source, target: e.target,
          sourceHandle: e.sourceHandle ?? null, targetHandle: e.targetHandle ?? null,
          data: { kind: e.data?.kind ?? "ref" },
        })),
        hidden: [...r.hidden],
      };
    }

    function scheduleSave() {
      if (!r.loadedBoard) return;
      r.dirty = true;
      window.clearTimeout(r.saveTimer);
      r.saveTimer = window.setTimeout(flushSave, SAVE_DEBOUNCE);
    }

    /**
     * 立刻存：快照在这一刻拍下（换计划前调用，旧计划的改动不会丢）。
     * 返回的 Promise 在这份快照（和排在它前面的）发完后才 resolve —— 服务端执行器读的是库里的文档，
     * execute 之前必须等它真的存上。存失败不 reject（保存状态和提示照旧走 save），调用方自己看 save。
     */
    function flushSave(): Promise<void> {
      window.clearTimeout(r.saveTimer);
      if (!r.dirty || r.blocked || !r.loadedBoard) return r.pumpP ?? Promise.resolve();
      r.dirty = false;
      r.pendingSnap = { board: r.loadedBoard, doc: serialize(), local: r.local, demo };
      return pump();
    }

    /** 串行发送：同一时刻只有一个 PUT 在飞，后面的快照只留最新一份（排进来的快照由正在跑的这一串顺手发掉） */
    function pump(): Promise<void> {
      if (r.pumpP) return r.pumpP;
      let taskPromise: Promise<void> = Promise.resolve();
      taskPromise = (async () => {
        // 先让出一拍：保证 r.pumpP 已经赋上，finally 清掉的是它自己
        await Promise.resolve();
        try {
          while (r.pendingSnap) {
            const snap = r.pendingSnap;
            r.pendingSnap = null;
            await putSnap(snap);
          }
        } finally {
          if (r.pumpP === taskPromise) r.pumpP = null;
        }
      })();
      r.pumpP = taskPromise;
      return taskPromise;
    }

    async function putSnap(snap: Snap) {
      const current = () => r.loadedBoard === snap.board;
      if (snap.local) {
        const ok = writeLocal(snap.board, snap.doc);
        if (current()) setSave(ok ? "local" : "error");
        return;
      }
      if (current()) setSave("saving");
      try {
        // 演示快照只交给演示接口（demoApi 装上后不会清掉）；它不在了就丢弃，绝不发给真后端
        if (snap.demo && !demoApi) return;
        const rec = snap.demo
          ? await demoApi!.canvasSave(snap.board, r.versions.get(snap.board) ?? 0, snap.doc)
          : await cv.canvasSave(snap.board, r.versions.get(snap.board) ?? 0, snap.doc);
        r.versions.set(snap.board, rec.version);
        if (current()) setSave(r.dirty ? "saving" : "saved");
      } catch (e) {
        if (e instanceof HttpError && e.status === 409) {
          if (!current()) { console.warn("[canvas] 切走的那张画布存盘冲突，已放弃", snap.board); return; }
          r.blocked = true;
          setSave("conflict");
          toast("画布在别处被改过", "err", { label: "载入远端", run: () => S().reloadCanvas() });
        } else if (missing(e)) {
          // 后端还没有画布接口：这份计划转本地模式
          writeLocal(snap.board, snap.doc);
          if (current()) {
            r.local = true;
            setSave("local");
            toast("后端还没有画布接口，画布先存在本机浏览器里", "info");
          }
        } else if (current()) {
          r.dirty = true;
          setSave("error");
          toast(`画布保存失败：${msg(e)}`, "err");
          window.clearTimeout(r.saveTimer);
          r.saveTimer = window.setTimeout(flushSave, 8000);
        }
      }
    }

    /* ── 图的受控回调 ── */
    const onNodesChange: OnNodesChange<CNode> = (changes: NodeChange<CNode>[]) => {
      const removes: string[] = [];
      const rest: NodeChange<CNode>[] = [];
      for (const c of changes) (c.type === "remove" ? removes.push(c.id) : rest.push(c));
      if (rest.length) {
        // 纯位置/尺寸变化不算结构变化（拖动时每帧都有，不能让整个 store 换对象）
        const structural = rest.some(c => c.type !== "position" && c.type !== "dimensions");
        // 分组框拖手柄改大小：松手那一下（resizing=false）才存
        const persist = rest.some(c => (c.type === "position" && c.dragging === false) || c.type === "add" || c.type === "replace"
          || (c.type === "dimensions" && c.resizing === false));
        setNodes(applyNodeChanges(rest, nodesRef.current));
        if (structural) bump();
        if (persist) scheduleSave();
        if (rest.some(c => c.type === "select")) noteShot();
      }
      // 删节点一律走 removeNodes：派生节点只隐藏
      if (removes.length) removeNodes(removes);
    };

    const onEdgesChange: OnEdgesChange<CEdge> = (changes: EdgeChange<CEdge>[]) => {
      const drop = new Set<string>();
      const rest: EdgeChange<CEdge>[] = [];
      let blockedDerived = false;
      for (const c of changes) {
        if (c.type !== "remove") { rest.push(c); continue; }
        const e = edgesRef.current.find(x => x.id === c.id);
        if (e?.data?.derived) blockedDerived = true;
        else if (e) drop.add(c.id);
      }
      let next = rest.length ? applyEdgeChanges(rest, edgesRef.current) : edgesRef.current;
      if (drop.size) next = next.filter(e => !drop.has(e.id));
      setEdges(next);
      if (drop.size || rest.some(c => c.type !== "select")) bump();
      if (drop.size) scheduleSave();
      if (blockedDerived) toast("这条线来自分镜关系（场次→镜头、白模→镜头），不能删", "info");
    };

    function addEdge(source: string, target: string, kind: EdgeKind, sourceHandle?: string | null, targetHandle?: string | null): boolean {
      if (source === target || !nodeById(source) || !nodeById(target)) return false;
      if (edgesRef.current.some(e => e.source === source && e.target === target)) return false;
      const e: CEdge = {
        id: `u:${source}>${target}`, source, target, type: "glow",
        sourceHandle: sourceHandle ?? null, targetHandle: targetHandle ?? null, data: { kind },
      };
      setEdges([...edgesRef.current, e]);
      bump();
      scheduleSave();
      return true;
    }

    const isValidConnection: IsValidConnection<CEdge> = c =>
      c.source !== c.target && !edgesRef.current.some(e => e.source === c.source && e.target === c.target);

    /** 连好以后告诉人这条线意味着什么（连线本身不改后端；要改就点提示里的动作） */
    function hintAfterConnect(src: CNode, dst: CNode) {
      const lv = liveRef.current;
      if (dst.type === "box3d" && dst.data.ref.kind === "box_project") {
        const boxId = dst.data.ref.id;
        if (src.type === "image") {
          const res = resolveRef(lv, src.data.ref, src.data);
          if (res.kind === "entity_view") {
            const view = src.data.ref.kind === "entity_view" ? src.data.ref.view : undefined;
            toast(`「${res.member.name}」连到了白模`, "info", {
              label: "放进白模",
              run: () => { addCharacterToBox(S(), boxId, res.member, view).catch(e => toast(`放进白模失败：${msg(e)}`, "err")); },
            });
          } else {
            toast("已连上。白模里的人偶只认角色库的角色（连定妆照节点才能放进去）", "info");
          }
        } else if (src.type === "text") {
          const text = resolvedText(resolveRef(lv, src.data.ref, src.data)).trim();
          if (text) {
            toast("要按这段文字改白模吗？", "info", {
              label: "按这段改景",
              run: () => { askBox(S(), dst.id, boxId, text).catch(e => toast(`改景失败：${msg(e)}`, "err")); },
            });
          }
        }
      } else if (src.type === "image" && dst.type === "video" && dst.data.ref.kind === "shot") {
        toast("已作为参考；导演出片的脸来自角色库", "info");
      }
    }

    const onConnect: OnConnect = (c: Connection) => {
      const src = nodeById(c.source);
      const dst = nodeById(c.target);
      if (!src || !dst) return;
      if (!addEdge(c.source, c.target, inferEdgeKind(src, dst), c.sourceHandle, c.targetHandle)) return;
      hintAfterConnect(src, dst);
    };

    /* ── 选中与编辑 ── */
    function select(id: string | null) {
      let changed = false;
      const next = nodesRef.current.map(n => {
        const want = n.id === id;
        if (Boolean(n.selected) === want) return n;
        changed = true;
        return { ...n, selected: want };
      });
      let edgeChanged = false;
      const nextEdges = edgesRef.current.map(e => (e.selected ? ((edgeChanged = true), { ...e, selected: false }) : e));
      if (changed) setNodes(next);
      if (edgeChanged) setEdges(nextEdges);
      if (changed || edgeChanged) bump();
      if (changed) noteShot();
    }

    /** 选中的是一个镜头：写进地址栏 ?shot=，切到分镜画布 / 后台时定位到这一镜 */
    function noteShot() {
      const sel = nodesRef.current.filter(n => n.selected);
      if (sel.length === 1 && sel[0].data.ref.kind === "shot") remember("shot", sel[0].data.ref.id);
    }

    /** 画布绝对坐标：分组里的节点 position 是相对分组的（分组不嵌套，只有一层） */
    function absPos(n: CNode): XYPosition {
      const p = n.parentId ? nodeById(n.parentId) : undefined;
      return p ? { x: p.position.x + n.position.x, y: p.position.y + n.position.y } : n.position;
    }

    function focusNode(id: string) {
      const n = nodeById(id);
      if (!n) return;
      const box = rectOf(n);
      const at = absPos(n);
      const f = rfRef.current;
      void f.setCenter(at.x + box.w / 2, at.y + (box.h - 24) / 2, {
        zoom: Math.max(f.getZoom(), 0.8), duration: 450,
      });
    }

    const newFreeId = () => `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

    /** 下一个自动标题：扫画布上「图片 N」这类标题取最大号 +1（「图片 3 拷贝1」也算 3） */
    function nextTitle(kind: NodeKind): string {
      const prefix = TITLE_PREFIX[kind] ?? "节点";
      const re = new RegExp(`^${prefix}\\s*(\\d+)`);
      let max = 0;
      for (const n of nodesRef.current) {
        const hit = re.exec(n.data.title ?? "");
        if (hit) max = Math.max(max, Number(hit[1]));
      }
      return `${prefix} ${max + 1}`;
    }

    function addNode(type: NodeKind, data: CNodeData, at?: XYPosition, connectFrom?: { source: string; kind: EdgeKind }): string {
      let ref = data.ref;
      if (ref.kind === "free" && !ref.id) ref = { kind: "free", id: newFreeId() };
      // 纳逗式自动命名：没给标题就按类型编号
      if (!data.title?.trim()) data = { ...data, title: nextTitle(type) };
      const id = nodeIdOf(ref);
      // 同一个真身一张画布上只有一个节点：已经在了就选中它、飞过去
      if (nodeById(id)) {
        select(id);
        focusNode(id);
        if (connectFrom) addEdge(connectFrom.source, id, connectFrom.kind);
        return id;
      }
      r.hidden.delete(id);
      const size = type === "group" ? GROUP_SIZE : estimateSize(type, data.role);
      let pos: XYPosition;
      const src = connectFrom ? nodeById(connectFrom.source) : undefined;
      if (at) {
        pos = at;
      } else if (src) {
        const sr = rectOf(src);
        pos = findFreeSpot(nodesRef.current, { x: src.position.x + Math.max(360, sr.w + 60), y: src.position.y }, size);
      } else {
        const c = rfRef.current.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
        pos = findFreeSpot(nodesRef.current, { x: c.x - size.w / 2, y: c.y - size.h / 2 }, size);
      }
      const { orphan, ...clean } = data;
      void orphan;
      const node: CNode = { id, type, position: { x: pos.x, y: pos.y }, data: { ...clean, ref }, selected: true };
      const others = nodesRef.current.map(n => (n.selected ? { ...n, selected: false } : n));
      if (type === "group") {
        // 空分组：给个默认框（分组的大小就是 width/height，不靠内容撑），排最前垫在最底下
        node.width = GROUP_SIZE.w;
        node.height = GROUP_SIZE.h;
        setNodes([node, ...others]);
      } else {
        setNodes([...others, node]);
      }
      bump();
      if (connectFrom) addEdge(connectFrom.source, id, connectFrom.kind);
      if (ref.kind === "box_project" && !liveRef.current.boxes[ref.id]) void loadBoxDoc(ref.id);
      scheduleSave();
      return id;
    }

    function updateNodeData(id: string, patch: Partial<CNodeData>) {
      if (!nodeById(id)) return;
      setNodes(nodesRef.current.map(n => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));
      bump();
      scheduleSave();
    }

    /**
     * 把这些分组里的节点放出来：换回绝对坐标、去掉 parentId（删分组、解散分组共用）。
     * 只改子节点，分组节点本身由调用方处理。
     */
    function detachChildren(groupIds: Set<string>) {
      if (!groupIds.size || !nodesRef.current.some(n => n.parentId && groupIds.has(n.parentId))) return;
      setNodes(nodesRef.current.map(n => {
        if (!n.parentId || !groupIds.has(n.parentId)) return n;
        const { parentId, expandParent, extent, ...rest } = n;
        void parentId; void expandParent; void extent;
        return { ...rest, position: absPos(n) };
      }));
    }

    function removeNodes(ids: string[]) {
      const set = new Set(ids.filter(id => nodeById(id)));
      if (!set.size) return;
      // 删分组 = 先解散（子节点留在原地，撤销时只回来一个空框，子节点不会跟着「消失」）
      detachChildren(new Set([...set].filter(id => nodeById(id)?.type === "group")));
      // 撤销按「同一张画布」判断：一章十几张画布共用一份分镜计划，按计划判会把 A 的节点撤销进 B
      const board = r.loadedBoard;
      const removed = nodesRef.current.filter(n => set.has(n.id));
      const removedEdges = edgesRef.current.filter(e => set.has(e.source) || set.has(e.target));
      const derived = removed.filter(n => isDerived(n.data.ref));
      for (const n of derived) r.hidden.add(n.id);
      setNodes(nodesRef.current.filter(n => !set.has(n.id)));
      setEdges(edgesRef.current.filter(e => !set.has(e.source) && !set.has(e.target)));
      bump();
      // 删除是结构变化，立刻存：不等 1 秒防抖（删完马上刷新页面，删除会丢）
      r.dirty = true;
      flushSave();
      const undo = () => {
        if (r.loadedBoard !== board) return;
        for (const n of derived) r.hidden.delete(n.id);
        const have = new Set(nodesRef.current.map(n => n.id));
        const back = removed.filter(n => !have.has(n.id)).map(n => ({ ...n, selected: false }));
        for (const n of back) have.add(n.id);
        const haveE = new Set(edgesRef.current.map(e => e.id));
        const backE = removedEdges.filter(e => !haveE.has(e.id) && have.has(e.source) && have.has(e.target));
        setNodes([...nodesRef.current, ...back]);
        setEdges([...edgesRef.current, ...backE]);
        bump();
        scheduleSave();
      };
      const free = removed.length - derived.length;
      const text = !derived.length ? (free > 1 ? `已删除 ${free} 个节点` : "已删除")
        : !free ? "已从画布拿掉，后端里还在"
        : `已删除 ${free} 个、拿掉 ${derived.length} 个（后端里还在）`;
      toast(text, "info", { label: "撤销", run: undo });
    }

    function connect(source: string, target: string, kind: EdgeKind) {
      addEdge(source, target, kind);
    }

    function upstream(id: string) {
      const by = nodeMap();
      return edgesRef.current.filter(e => e.target === id)
        .flatMap(edge => { const node = by.get(edge.source); return node ? [{ node, edge }] : []; });
    }
    function downstream(id: string) {
      const by = nodeMap();
      return edgesRef.current.filter(e => e.source === id)
        .flatMap(edge => { const node = by.get(edge.target); return node ? [{ node, edge }] : []; });
    }

    /* ── 纳逗式编辑：复制、编组、解散 ── */

    /**
     * 一个节点复制成什么：自由节点连 media、配方、正文一起深拷贝（生成状态、历史不带 —— 那是原节点自己的）；
     * 派生节点拷成一张静态的自由节点（镜头取视频或首帧、角色视角取图、剧本取文字），
     * 真身还是后端那一个，复制品不跟着后端变。拿不出画面的（白模、还没出片的镜头）返回 null。
     */
    function copyOf(n: CNode): { type: NodeKind; data: CNodeData } | null {
      const d = n.data;
      const type: NodeKind = n.type ?? "text";
      if (!isDerived(d.ref)) {
        const { gen, history, orphan, pinned, ...rest } = d;
        void gen; void history; void orphan; void pinned;
        return { type, data: structuredClone(rest) };
      }
      const res = resolveRef(liveRef.current, d.ref, d);
      const still = (url: string | null | undefined, role: CNodeData["role"]) => {
        const m = url ? docMedia({ url: media(url) ?? url, mime: guessMime(url, "image") }) : null;
        return m ? { type: "image" as const, data: { ref: d.ref, title: d.title, role, media: m } } : null;
      };
      switch (res.kind) {
        case "shot": {
          const v = res.shot.video_url;
          const m = v ? docMedia({ url: media(v) ?? v, mime: guessMime(v, "video") }) : null;
          if (m) return { type: "video", data: { ref: d.ref, title: d.title, role: "generated", media: m } };
          return still(res.shot.first?.url ?? res.shot.last?.url, "frame");
        }
        case "entity_view":
          return still(res.url, d.role === "sheet" ? "sheet" : "character");
        case "media": {
          const m = docMedia(res.media);
          return m ? { type, data: { ref: d.ref, title: d.title, role: d.role, media: m } } : null;
        }
        case "story":
        case "scene":
          return { type: "text", data: { ref: d.ref, title: d.title, role: "note", text: resolvedText(res) } };
        default:
          return null;
      }
    }

    /**
     * 复制（⌘D）：标题「图片 3 拷贝1」，往右下错开 40px，选中复制品。
     * 选了分组 = 连组里的节点一起复制；一起复制的节点之间的配方引用、连线指向复制品，
     * 引用组外的照旧指向原上游（同一套参考出另一版）。有配方的复制品把上游连线也带上（连线 = 配方引用）。
     */
    function duplicate(ids: string[]): string[] {
      const by = nodeMap();
      const want = uniq<string>(ids).map(id => by.get(id)).filter((n): n is CNode => !!n);
      if (!want.length) return [];
      const groupIds = new Set(want.filter(n => n.type === "group").map(n => n.id));
      const members = nodesRef.current.filter(n => n.parentId && groupIds.has(n.parentId) && !want.includes(n));
      const src = [...want, ...members];
      const idMap = new Map<string, string>();
      const made: { from: CNode; node: CNode }[] = [];
      const skipped: string[] = [];
      for (const n of src) {
        const c = copyOf(n);
        if (!c) { skipped.push(n.data.title || n.id); continue; }
        const cloneId = newFreeId();
        const ref: NodeRef = isProductionRef(n.data.ref) ? structuredClone(n.data.ref) : { kind: "free", id: cloneId };
        idMap.set(n.id, cloneId);
        made.push({ from: n, node: { id: cloneId, type: c.type, position: n.position, data: { ...c.data, ref } } });
      }
      if (!made.length) {
        toast(`${skipped.join("、")} 拿不出画面，不能复制（白模、还没出片的镜头）`, "info");
        return [];
      }
      const taken = new Set(nodesRef.current.map(n => n.data.title));
      const wantIds = new Set(want.map(n => n.id));
      for (const { from, node } of made) {
        const d = node.data;
        if (d.recipe) d.recipe = remapRecipe(d.recipe, idMap);
        d.title = copyTitle(from.data.title || nextTitle(node.type ?? "text"), taken);
        taken.add(d.title);
        const newParent = from.parentId ? idMap.get(from.parentId) : undefined;
        if (newParent) {
          // 跟着复制的分组走：相对位置不变
          node.parentId = newParent;
          node.expandParent = true;
        } else {
          if (from.parentId) { node.parentId = from.parentId; node.expandParent = true; }
          node.position = { x: from.position.x + COPY_OFFSET, y: from.position.y + COPY_OFFSET };
        }
        if (from.type === "group") {
          node.width = from.width ?? from.measured?.width ?? GROUP_SIZE.w;
          node.height = from.height ?? from.measured?.height ?? GROUP_SIZE.h;
        }
        // 只选中「要复制的」那几个的复制品（组里的跟着分组走，不另外选）
        node.selected = wantIds.has(from.id);
      }
      const groupsMade = made.filter(x => x.node.type === "group").map(x => x.node);
      const restMade = made.filter(x => x.node.type !== "group").map(x => x.node);
      const others = nodesRef.current.map(n => (n.selected ? { ...n, selected: false } : n));
      // 父节点排在子节点前面（xyflow 要求）：新分组放最前
      setNodes([...groupsMade, ...others, ...restMade]);
      // 连线：组内互连的照搬到复制品之间；有配方的复制品带上从组外连进来的线
      const add: CEdge[] = [];
      const have = new Set(edgesRef.current.map(e => `${e.source}>${e.target}`));
      for (const e of edgesRef.current) {
        const t = idMap.get(e.target);
        if (!t) continue;
        const s = idMap.get(e.source);
        if (!s && !nodeMap().get(t)?.data.recipe) continue;
        const source = s ?? e.source;
        const k = `${source}>${t}`;
        if (have.has(k)) continue;
        have.add(k);
        add.push({
          id: `u:${k}`, source, target: t, type: "glow", sourceHandle: e.sourceHandle ?? null, targetHandle: e.targetHandle ?? null,
          data: { kind: e.data?.kind ?? "ref" },
        });
      }
      if (add.length) setEdges([...edgesRef.current, ...add]);
      bump();
      scheduleSave();
      if (skipped.length) toast(`${skipped.join("、")} 拿不出画面，没复制`, "info");
      return want.flatMap(n => idMap.get(n.id) ?? []);
    }

    /**
     * 编组（⌘G）：选中的非分组节点包进一个「分组 N」框。分组位置 = 包围盒外扩 24px、上方再留 28px
     * 给子节点的小标题；子节点改成相对分组的坐标。已经在别的组里的节点挪到新组。
     */
    function groupSelected(): string | null {
      const sel = nodesRef.current.filter(n => n.selected && n.type !== "group");
      if (!sel.length) return null;
      let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
      const abs = new Map<string, XYPosition>();
      for (const n of sel) {
        const p = absPos(n);
        abs.set(n.id, p);
        const est = estimateSize(n.type, n.data.role);
        const w = n.measured?.width ?? n.width ?? est.w;
        const h = n.measured?.height ?? n.height ?? est.h;
        minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x + w); maxY = Math.max(maxY, p.y + h);
      }
      const id = newFreeId();
      const pos = { x: round(minX - GROUP_PAD), y: round(minY - GROUP_PAD - GROUP_HEAD) };
      const group: CNode = {
        id, type: "group", position: pos,
        width: round(maxX - minX + GROUP_PAD * 2), height: round(maxY - minY + GROUP_PAD * 2 + GROUP_HEAD),
        data: { ref: { kind: "free", id }, title: nextTitle("group") }, selected: true,
      };
      const inSel = new Set(sel.map(n => n.id));
      const rest = nodesRef.current.map(n => {
        if (!inSel.has(n.id)) return n.selected ? { ...n, selected: false } : n;
        const p = abs.get(n.id)!;
        return { ...n, parentId: id, expandParent: true, selected: false, position: { x: round(p.x - pos.x), y: round(p.y - pos.y) } };
      });
      // xyflow 要求父节点在数组里排在子节点前面：分组放最前（也垫在最底下）
      setNodes([group, ...rest]);
      bump();
      scheduleSave();
      return id;
    }

    /** 解散分组（⇧⌘G）：子节点换回绝对坐标留在原地，分组框删掉（连在分组上的线一起去掉） */
    function ungroup(groupId: string) {
      const g = nodeById(groupId);
      if (!g || g.type !== "group") return;
      detachChildren(new Set([groupId]));
      setNodes(nodesRef.current.filter(n => n.id !== groupId));
      setEdges(edgesRef.current.filter(e => e.source !== groupId && e.target !== groupId));
      bump();
      scheduleSave();
    }

    function relayout() {
      const pos = autoLayout(liveRef.current);
      let moved = 0;
      setNodes(nodesRef.current.map(n => {
        // 编进分组的不动：自动布局给的是绝对坐标，分组里的是相对坐标
        const p = !n.data.pinned && !n.parentId ? pos.get(n.id) : undefined;
        if (!p || (p.x === n.position.x && p.y === n.position.y)) return n;
        moved++;
        return { ...n, position: { x: p.x, y: p.y } };
      }));
      bump();
      if (moved) scheduleSave();
      window.requestAnimationFrame(() => { void rfRef.current.fitView({ padding: 0.1, duration: 400 }); });
      toast(moved ? "已整理（钉住的和自己加的节点没动）" : "已经是整理好的样子", "ok");
    }

    function syncGraph() {
      const res = syncDerived(liveRef.current, nodesRef.current, edgesRef.current, r.hidden);
      if (!res) return;
      setNodes(res.nodes);
      setEdges(res.edges);
      bump();
      if (res.added) scheduleSave();
    }

    /* ── 现取数据 ── */
    async function reloadLiveImpl(full: boolean): Promise<void> {
      const plan = r.loadedPlan;
      if (!plan) return;
      if (r.reload) {
        if (!full || r.reload.full) return r.reload.p;
        await r.reload.p.catch(() => undefined);
      }
      const p = (async () => {
        const prev = liveRef.current;
        const board = await cv.board(plan);
        let cast: CastMember[] = prev.cast;
        let script: ScriptScene[] = prev.script;
        if (full) {
          const chap = chapterIdRef.current || board.chapter?.id || "";
          [cast, script] = await Promise.all([
            cv.cast(plan).catch(() => prev.cast),
            chap ? cv.script(plan, chap).catch(() => prev.script) : Promise.resolve(prev.script),
          ]);
        }
        if (r.loadedPlan !== plan) return;
        const want = boxIdsOf(board, nodesRef.current, liveRef.current.scope.shotIds);
        const ids = full ? want : want.filter(id => !liveRef.current.boxes[id]);
        const got = ids.length ? await fetchBoxes(ids) : {};
        if (r.loadedPlan !== plan) return;
        setLive(cur => ({
          ...cur, board, cast, script, boxes: mergeBoxes(cur.boxes, got),
          chapterTitle: board.chapter?.title || cur.chapterTitle,
        }));
        syncGraph();
      })();
      r.reload = { p, full };
      try {
        await p;
      } finally {
        if (r.reload?.p === p) r.reload = null;
      }
    }

    async function reloadLive(): Promise<void> {
      try {
        await reloadLiveImpl(true);
      } catch (e) {
        toast(`刷新分镜失败：${msg(e)}`, "err");
      }
    }

    function mergeBox(info: BoxInfo) {
      setLive(cur => ({ ...cur, boxes: mergeBoxes(cur.boxes, { [info.id]: info }) }));
    }

    function loadBoxDoc(id: string, force = false): Promise<void> {
      if (!force && liveRef.current.boxes[id]?.doc) return Promise.resolve();
      const inflight = r.boxInflight.get(id);
      if (inflight && !force) return inflight;
      const p: Promise<void> = (async () => {
        try {
          let info = await cv.boxInfo(id);
          // 轻量接口可能不带 doc：退回全量项目取一次
          if (!info.doc) {
            const pj = await cv.boxGet(id);
            info = { ...info, doc: pj.doc, active_run: pj.active_run, ok: pj.ok };
          }
          mergeBox(info);
          syncGraph();
        } catch (e) {
          toast(`白模载入失败：${msg(e)}`, "err");
        }
      })().finally(() => {
        if (r.boxInflight.get(id) === p) r.boxInflight.delete(id);
      });
      r.boxInflight.set(id, p);
      return p;
    }

    /* ── 任务：唯一轮询器 ── */
    function track(t: Omit<TrackedTask, "startedAt" | "status"> & { status?: TrackedTask["status"] }) {
      const task: TrackedTask = { ...t, status: t.status ?? "running", startedAt: Date.now() };
      if (task.kind === "ltx25" && task.baseline === undefined) {
        task.baseline = liveRef.current.board?.shots.find(s => s.id === task.remote)?.video_url ?? null;
      }
      r.seenActive.delete(task.key);
      r.pollErrors.delete(task.key);
      setTasks(prev => {
        const rest = prev.filter(x => x.key !== task.key);
        // 结束了的只留最近 30 条（顶栏任务列表看个大概就够）
        const done = rest.filter(x => !isLive(x.status)).slice(-30);
        return [...rest.filter(x => isLive(x.status)), ...done, task];
      });
    }

    function patchTask(key: string, patch: Partial<TrackedTask>) {
      setTasks(prev => {
        const i = prev.findIndex(t => t.key === key);
        if (i < 0) return prev;
        const cur = prev[i];
        if (Object.entries(patch).every(([k, v]) => cur[k as keyof TrackedTask] === v)) return prev;
        const next = prev.slice();
        next[i] = { ...cur, ...patch };
        return next;
      });
    }

    function failTask(t: TrackedTask, error: string) {
      patchTask(t.key, { status: "failed", error });
      toast(`${t.label}失败：${error}`, "err");
    }

    function setRun(shotId: string, run: LiveSources["runs"][string]) {
      const cur = liveRef.current.runs[shotId];
      if (JSON.stringify(cur ?? null) === JSON.stringify(run ?? null)) return;
      setLive(p => ({ ...p, runs: { ...p.runs, [shotId]: run } }));
    }

    async function advanceDirector(t: TrackedTask) {
      const run = await cv.directorRun(t.remote);
      setRun(t.remote, run);
      const age = Date.now() - t.startedAt;
      if (!run) {
        if (age > LONG_TIMEOUT) failTask(t, "超时，没查到导演任务");
        return;
      }
      const ended = run.done || run.status === "failed" || run.status === "cancelled";
      if (!ended) {
        r.seenActive.add(t.key);
        patchTask(t.key, { status: run.status === "queued" ? "queued" : "running", progress: run.percent });
        if (age > LONG_TIMEOUT) failTask(t, "超时");
        return;
      }
      // 刚提交时可能还读到上一次的结果：没见它跑过、且开始时间比登记早很多，先当旧的
      const started = run.started_at ? Date.parse(run.started_at) : NaN;
      const fresh = r.seenActive.has(t.key) || !Number.isFinite(started) || started >= t.startedAt - 5 * 60 * 1000;
      if (!fresh && age < 3 * 60 * 1000) return;
      if (run.done) {
        patchTask(t.key, { status: "succeeded", progress: 100 });
        toast(`${t.label}：完成`, "ok");
        await reloadLiveImpl(false);
      } else {
        failTask(t, run.error || (run.status === "cancelled" ? "已取消" : "失败"));
      }
    }

    function advanceLtx(t: TrackedTask) {
      const shot = liveRef.current.board?.shots.find(s => s.id === t.remote);
      const now = shot?.video_url ?? null;
      if (now && now !== (t.baseline ?? null)) {
        patchTask(t.key, { status: "succeeded", progress: 100 });
        toast(`${t.label}：完成`, "ok");
      } else if (Date.now() - t.startedAt > LTX_TIMEOUT) {
        failTask(t, "超时");
      }
    }

    /** 生成结果写回节点：第一个产物填进这个节点，其余在它下面长兄弟节点（连同样的上游） */
    function applyGen(t: TrackedTask, st: GenTaskState) {
      const node = nodeById(t.nodeId);
      if (!node) return;
      const gen: GenState = { ...(node.data.gen ?? { task_id: t.remote }), task_id: t.remote, status: st.status, progress: st.progress, error: st.error };
      const patch: Partial<CNodeData> = {};
      if (!sameGen(node.data.gen, gen)) patch.gen = gen;
      const assets = st.status === "succeeded" ? st.assets.filter(a => a.kind === "image" || a.kind === "video") : [];
      let type = node.type;
      const fill = assets.length > 0 && !node.data.media;
      if (fill) {
        const a = assets[0];
        const url = a.url.startsWith("data:") ? a.url : media(a.url) ?? a.url;
        patch.media = { url, asset_id: a.asset_id, mime: a.mime ?? guessMime(url, a.kind) };
        if (type === "image" || type === "video") type = a.kind as "image" | "video";
      }
      if (!Object.keys(patch).length && type === node.type) return;
      setNodes(nodesRef.current.map(n => (n.id === node.id ? { ...n, type, data: { ...n.data, ...patch } } : n)));
      bump();
      if (fill || !isLive(gen.status)) scheduleSave();
      if (!fill) return;
      const incoming = edgesRef.current.filter(e => e.target === node.id);
      let below = { x: node.position.x, y: node.position.y + rectOf(node).h + 16 };
      assets.slice(1).forEach((a, i) => {
        const ref: NodeRef = { kind: "asset", id: a.asset_id };
        if (nodeById(nodeIdOf(ref))) return;
        const url = a.url.startsWith("data:") ? a.url : media(a.url) ?? a.url;
        const kind = a.kind as "image" | "video";
        const spot = findFreeSpot(nodesRef.current, below, estimateSize(kind, "generated"));
        const id = nodeIdOf(ref);
        setNodes([...nodesRef.current, {
          id, type: kind, position: spot,
          // 原节点在分组里：兄弟也长在同一个组里（坐标同是相对分组的）
          ...(node.parentId ? { parentId: node.parentId, expandParent: true } : {}),
          data: {
            ref, title: `${node.data.title} · ${i + 2}`, role: "generated",
            media: { url, asset_id: a.asset_id, mime: a.mime ?? guessMime(url, a.kind) },
            gen: { ...gen, status: "succeeded" },
          },
        }]);
        below = { x: spot.x, y: spot.y + estimateSize(kind, "generated").h + 40 };
        for (const e of incoming) addEdge(e.source, id, e.data?.kind ?? "ref");
      });
      bump();
    }

    async function advanceGen(t: TrackedTask) {
      const st = await cv.genTask(t.remote);
      applyGen(t, st);
      if (st.status === "succeeded") {
        if (st.assets.length) patchTask(t.key, { status: "succeeded", progress: 100 });
        else if (Date.now() - t.startedAt > LONG_TIMEOUT) failTask(t, "产物没落库");
        else patchTask(t.key, { status: "running" });
      } else if (st.status === "failed" || st.status === "cancelled") {
        if (st.status === "cancelled") patchTask(t.key, { status: "cancelled", error: st.error });
        else failTask(t, st.error || "生成失败");
      } else {
        patchTask(t.key, { status: st.status, progress: st.progress });
      }
    }

    async function advanceBlender(t: TrackedTask) {
      const job = await cv.job(t.remote);
      if (job.status === "succeeded") {
        patchTask(t.key, { status: "succeeded", progress: 100 });
        try {
          onBlenderDone(S(), { ...t, status: "succeeded" }, job);
        } catch (e) {
          toast(`控制素材渲好了，但长节点出错：${msg(e)}`, "err");
        }
      } else if (job.status === "failed" || job.status === "cancelled") {
        failTask(t, job.error || (job.status === "cancelled" ? "已取消" : "渲染失败"));
      } else {
        patchTask(t.key, { status: job.status, progress: job.progress?.percent ?? null });
        if (Date.now() - t.startedAt > LONG_TIMEOUT) failTask(t, "超时");
      }
    }

    async function advanceBoxAgent(t: TrackedTask) {
      const info = await cv.boxInfo(t.remote);
      mergeBox(info);
      if (!info.active_run) {
        patchTask(t.key, { status: "succeeded", progress: 100 });
        try {
          onBoxAgentDone(S(), { ...t, status: "succeeded" });
        } catch (e) {
          toast(`白模改好了，但刷新出错：${msg(e)}`, "err");
        }
      } else if (Date.now() - t.startedAt > LONG_TIMEOUT) {
        failTask(t, "超时");
      }
    }

    async function advanceRun(t: TrackedTask) {
      const st = await cv.runGet(t.remote);
      if (st.board_id === r.loadedBoard) setFlowRun(st);
      // 正在导演出片的那一镜：进度挂到镜头节点上（三步条、流光），不用另外登记导演任务
      const cur = st.summary.current;
      if (cur && cur.director !== undefined) setRun(cur.shot_id, cur.director ?? null);
      const ok = st.summary.succeeded;
      if (ok !== r.runSeen.get(st.id)) {
        r.runSeen.set(st.id, ok);
        await reloadLiveImpl(false).catch(() => undefined);   // 新挂回的片子马上换上
      }
      if (ACTIVE_RUN.has(st.status)) {
        const total = st.summary.total || 1;
        patchTask(t.key, { status: "running", progress: Math.round(((st.summary.succeeded + st.summary.failed) / total) * 100) });
        return;
      }
      const status = st.status === "succeeded" ? "succeeded" : st.status === "cancelled" ? "cancelled" : "failed";
      patchTask(t.key, { status, progress: 100, error: status === "failed" ? `${st.summary.failed} 镜失败` : null });
      toast(st.status === "succeeded" ? `一键出片完成：${st.summary.succeeded} 镜都挂回了`
        : st.status === "cancelled" ? "一键出片已取消"
          : `一键出片结束：成功 ${st.summary.succeeded} 镜，失败 ${st.summary.failed} 镜`,
      st.status === "succeeded" ? "ok" : "err");
      await reloadLiveImpl(false).catch(() => undefined);
      void reloadBoards().catch(() => undefined);              // 画布列表上的「已出 N」跟着变
    }

    /** 快速成片：产物按出来的顺序长成画布节点（定妆照 → 换装 → 场景 → 分镜 N → 成片），连成一条线 */
    async function advanceQuick(t: TrackedTask) {
      const job = await cv.quickGet(t.remote);
      const seen = r.quickSeen.get(job.id) ?? { n: 0, last: t.nodeId, look: null };
      const keep = nodesRef.current.filter(n => n.selected).map(n => n.id);
      for (const o of job.outputs.slice(seen.n)) {
        const video = o.kind === "clip" || o.kind === "video";
        const url = media(o.url) ?? o.url;
        const id = addNode(video ? "video" : "image", {
          ref: { kind: "asset", id: o.asset_id }, title: o.title, role: o.kind === "look" ? "character" : "generated",
          media: { url, asset_id: o.asset_id, mime: video ? "video/mp4" : "image/png" },
        }, undefined, { source: seen.last, kind: o.kind === "frame" && seen.look ? "identity" : "ref" });
        if (o.kind === "look") seen.look = id;
        if (o.kind === "frame" && seen.look && seen.look !== seen.last) addEdge(seen.look, id, "identity");
        seen.last = id;
        seen.n += 1;
      }
      r.quickSeen.set(job.id, seen);
      // 长新节点会抢选中；还给用户原来选的
      if (keep.length) setNodes(nodesRef.current.map(n => ({ ...n, selected: keep.includes(n.id) })));
      if (job.state === "running") {
        patchTask(t.key, { status: "running", progress: QUICK_STEP[job.step.split(":")[0]] ?? null, label: `快速成片 · ${quickStepText(job.step)}` });
        return;
      }
      if (job.state === "done") {
        patchTask(t.key, { status: "succeeded", progress: 100 });
        const film = job.outputs.find(o => o.kind === "video");
        toast(`快速成片完成：${job.plan?.title ?? ""}`, "ok",
          film ? { label: "播放", run: () => setOverlay({ kind: "media", url: media(film.url) ?? film.url, video: true }) } : undefined);
      } else {
        failTask(t, job.error || "快速成片失败");
      }
      scheduleSave();
    }

    /* ── 服务端执行器：按节点配方在后端跑，结果从 node-runs 合回节点 ── */

    /** 一个 run 的产物额外几张（count>1）：在节点下面长兄弟节点，连同样的上游。每个 run 只在主产物填进去的那一刻长一次 */
    function spawnExtras(node: CNode, run: NodeRun) {
      const incoming = edgesRef.current.filter(e => e.target === node.id);
      let below = { x: node.position.x, y: node.position.y + rectOf(node).h + 16 };
      run.extra.forEach((x, i) => {
        const m = x.media?.url ? docMedia(x.media) : null;
        if (!m) return;
        const ref: NodeRef = m.asset_id ? { kind: "asset", id: m.asset_id } : { kind: "free", id: `${run.id}_${i + 2}` };
        const id = nodeIdOf(ref);
        if (nodeById(id)) return;
        const kind = (m.mime ?? guessMime(m.url, OP_VIDEO.has(run.op) ? "video" : "image")).startsWith("video") ? "video" : "image";
        const size = estimateSize(kind, "generated");
        const spot = findFreeSpot(nodesRef.current, below, size);
        setNodes([...nodesRef.current, {
          id, type: kind, position: spot,
          ...(node.parentId ? { parentId: node.parentId, expandParent: true } : {}),
          data: { ref, title: `${node.data.title} · ${i + 2}`, role: "generated", media: m },
        }]);
        below = { x: spot.x, y: spot.y + size.h + 40 };
        for (const e of incoming) addEdge(e.source, id, e.data?.kind ?? "ref");
      });
    }

    /**
     * node-runs → 节点（规格 4.1）：
     *   在跑（queued/waiting/running）→ data.gen 显示进度（节点组件现成的生成中样式）
     *   成功且产物换了 → 旧 media 进 history（最多 12），新的填进来，清 gen；count>1 的其余产物长兄弟节点
     *     （产物已经在当前 media 或 history 里 = 用户见过、可能「换回」过，不再覆盖）
     *   失败/跳过/取消 → gen 标失败写原因（已经有图的节点只在这次会话亲眼看着它跑时才盖，旧失败不挡旧图）
     */
    function applyRuns(runs: NodeRun[], ex: ExecuteState | null) {
      const prev = execRef.current;
      const map: Record<string, NodeRun> = {};
      for (const run of runs) {
        const cur = map[run.node_id];
        // 后端每个节点只给最近一次；保险起见同一节点取更新的那条
        if (!cur || (run.updated_at ?? "") >= (cur.updated_at ?? "")) map[run.node_id] = run;
        if (RUN_LIVE.has(run.status)) r.runLiveSeen.add(run.id);
      }
      if (JSON.stringify(map) !== JSON.stringify(nodeRunsRef.current)) setNodeRuns(map);
      if (JSON.stringify(ex) !== JSON.stringify(prev)) setExec(ex);

      let changed = false;
      let persist = false;
      const fills: { id: string; run: NodeRun }[] = [];
      const next = nodesRef.current.map((n): CNode => {
        const run = map[n.id];
        if (!run) return n;
        const d = n.data;
        const ownGen = execGen(d.gen);
        if (RUN_LIVE.has(run.status)) {
          const gen: GenState = {
            task_id: run.id, status: run.status === "running" ? "running" : "queued",
            progress: run.progress, error: null, model: null, prompt: null,
          };
          r.execGenIds.add(run.id);
          if (sameGen(d.gen, gen)) return n;
          changed = true;
          return { ...n, data: { ...d, gen } };
        }
        const fresh = r.runLiveSeen.has(run.id);
        if (run.status === "succeeded" && run.media?.url) {
          const kind: NodeKind = OP_VIDEO.has(run.op) ? "video" : "image";
          const m = docMedia({ ...run.media, mime: run.media.mime ?? guessMime(run.media.url, kind) });
          if (!m) return n;
          const seen = sameUrl(d.media?.url, m.url) || (d.history ?? []).some(h => sameUrl(h.url, m.url));
          if (seen) {
            if (!ownGen) return n;
            changed = true;
            return { ...n, data: { ...d, gen: null } };
          }
          const history = d.media ? [d.media, ...(d.history ?? []).filter(h => !sameUrl(h.url, d.media!.url))].slice(0, HISTORY_MAX) : d.history;
          changed = true;
          persist = true;
          if (run.op !== "sheet" && run.extra.length) fills.push({ id: n.id, run });
          // 产物是视频就把图片节点换成视频节点（反之亦然）；文字、白模、分组不动
          const type: NodeKind = (n.type === "image" || n.type === "video") ? kind : (n.type as NodeKind ?? "text");
          return { ...n, type, data: { ...d, media: m, history, gen: null } };
        }
        // 失败 / 跳过 / 取消（或「成功」却没有产物）
        if (!fresh && d.media && !ownGen) return n;
        const gen: GenState = {
          task_id: run.id, status: run.status === "cancelled" ? "cancelled" : "failed", progress: null,
          error: run.error || (run.status === "skipped" ? "跳过了（上游没出来）" : run.status === "succeeded" ? "没有产物" : null),
          model: null, prompt: null,
        };
        r.execGenIds.add(run.id);
        if (sameGen(d.gen, gen)) return n;
        changed = true;
        return { ...n, data: { ...d, gen } };
      });
      if (changed) {
        setNodes(next);
        bump();
      }
      // 只改了进度（gen 不进文档）不存盘；换了产物才存
      if (persist) scheduleSave();
      for (const f of fills) {
        const node = nodeById(f.id);
        if (node) spawnExtras(node, f.run);
      }

      const wasLive = !!prev && EXEC_LIVE.has(prev.status);
      if (wasLive && ex && !EXEC_LIVE.has(ex.status)) {
        if (ex.status === "succeeded") toast(`画布跑完了：${ex.done} 个节点都出好了`, "ok");
        else if (ex.status === "cancelled") toast(`已停止：出好了 ${ex.done} 个`, "info");
        else toast(`画布运行结束：成功 ${ex.done} 个，失败 ${ex.failed} 个${ex.error ? `（${ex.error}）` : ""}`, "err");
      }
    }

    /** 拉一次 node-runs（唯一轮询器到点调；execute、载入画布时各主动拉一次） */
    async function pollRuns(): Promise<void> {
      const board = r.loadedBoard;
      if (!board) return;
      try {
        const res = await cv.nodeRuns(board);
        if (r.loadedBoard !== board) return;
        r.execErrors = 0;
        applyRuns(res.runs ?? [], res.exec ?? null);
      } catch (e) {
        if (r.loadedBoard !== board) return;
        // 后端还没有执行器接口：静默停掉，别每 3 秒报一次错
        if (missing(e)) { r.execGiveUp = true; return; }
        r.execErrors += 1;
        if (r.execErrors >= 5) {
          r.execGiveUp = true;
          toast(`查不到运行进度：${msg(e)}（刷新页面再看）`, "err");
        }
      }
    }

    /**
     * 按配方在服务端跑：先把画布存好（执行器读的是库里的文档），再提交，然后由唯一轮询器跟进度。
     * 目标画布用 boardIdRef（不是 loadedBoard）：「想法 → 整张画布」建完马上 execute，那时新画布可能还在载入，
     * 它的文档已经由 createCanvas 存进库了，直接交就行。失败会 toast 一句人话再抛出，调用方不用再提示。
     */
    async function execute(opts: ExecuteOptions = {}): Promise<void> {
      const board = boardIdRef.current;
      try {
        if (!board) throw new Error("还没打开画布");
        if (r.loadedBoard === board) {
          await flushSave();
          if (r.local) throw new Error("画布只存在这台电脑的浏览器里，服务端读不到");
          if (r.blocked || saveRef.current === "conflict") throw new Error("画布在别处被改过：先「载入远端」再运行");
          if (saveRef.current === "error") throw new Error("画布没存上（服务端按存好的那份跑），等保存恢复再试");
        }
        const st = await cv.execute(board, opts);
        r.execGiveUp = false;
        r.execErrors = 0;
        if (boardIdRef.current !== board) return;
        setExec(st);
        r.lastExecTick = Date.now();
        // 马上拉一次：要跑的节点立刻显示「排队中」，不用等 3 秒
        await pollRuns();
      } catch (e) {
        toast(`运行没开始：${execError(e)}`, "err");
        throw e;
      }
    }

    async function stopExecute(): Promise<void> {
      const board = r.loadedBoard || boardIdRef.current;
      if (!board) return;
      try {
        const st = await cv.stopExecute(board);
        if (r.loadedBoard === board) setExec(st);
        toast("已停止：排队的不跑了，正在出的这一个出完为止", "info");
        await pollRuns();
      } catch (e) {
        toast(`停止失败：${execError(e)}`, "err");
      }
    }

    async function advanceOne(t: TrackedTask) {
      try {
        if (t.kind === "run") await advanceRun(t);
        else if (t.kind === "quick") await advanceQuick(t);
        else if (t.kind === "director") await advanceDirector(t);
        else if (t.kind === "ltx25") advanceLtx(t);
        else if (t.kind === "gen") await advanceGen(t);
        else if (t.kind === "blender") await advanceBlender(t);
        else if (t.kind === "box_agent") await advanceBoxAgent(t);
        r.pollErrors.delete(t.key);
      } catch (e) {
        // 网络抖一下不算失败；连续 5 次查不到才放弃
        const n = (r.pollErrors.get(t.key) ?? 0) + 1;
        r.pollErrors.set(t.key, n);
        if (n >= 5) failTask(t, `查不到进度：${msg(e)}`);
      }
    }

    async function advanceTasks() {
      // 刚登记的任务给后端一点时间（box_agent 刚提交时 active_run 可能还没写上）
      const active = tasksRef.current.filter(t => isLive(t.status) && Date.now() - t.startedAt > 1500);
      if (!active.length) return;
      if (active.some(t => t.kind === "ltx25")) {
        r.lastBoardTick = Date.now();
        await reloadLiveImpl(false).catch(() => undefined);
      }
      await pool(active, 6, advanceOne);
    }

    async function tick() {
      if (r.ticking) return;
      r.ticking = true;
      try {
        if (!r.execGiveUp && (execRef.current ? EXEC_LIVE.has(execRef.current.status) : false) && Date.now() - (r.lastExecTick || 0) >= EXEC_EVERY) {
          r.lastExecTick = Date.now();
          await pollRuns();
        }
        if (tasksRef.current.some(t => isLive(t.status)) && Date.now() - r.lastTaskTick >= TASK_EVERY) {
          r.lastTaskTick = Date.now();
          await advanceTasks();
        }
        // 有镜头在出（首尾帧生成中、导演出片未挂回）时刷 board，结果挂回来卡片就能换上（同 App.tsx）
        if (r.boardBusy && Date.now() - r.lastBoardTick >= BOARD_EVERY) {
          r.lastBoardTick = Date.now();
          await reloadLiveImpl(false).catch(() => undefined);
        }
      } finally {
        r.ticking = false;
      }
    }

    /* ── 载入 ── */
    function resetGraph() {
      r.loadedPlan = "";
      r.loadedBoard = "";
      r.hidden = new Set();
      r.local = false;
      r.blocked = false;
      r.dirty = false;
      r.seenActive.clear();
      r.pollErrors.clear();
      setNodes([]);
      setEdges([]);
      setLive(EMPTY_LIVE);
      setTasks([]);
      setFlowRun(null);
      // 切画布：带「撤销」的旧提示一起清掉（撤销的是上一张画布的节点）
      setToasts(p => p.filter(t => !t.action));
      setOverlay(null);
      setAddMenu(null);
      setSave("idle");
      setPendingFit(null);
      bump();
    }

    function applySaved(liveNow: LiveSources, saved: CanvasDoc | null, focus?: string) {
      r.hidden = new Set(saved?.hidden ?? []);
      const g = buildGraph(liveNow, saved);
      const adoptedNodes = saved?.nodes ? adoptGroups(g.nodes, saved.nodes) : g.nodes;
      setNodes(adoptedNodes);
      setEdges(g.edges);
      bump();
      r.suppressMoveUntil = Date.now() + 1500;
      if (focus && adoptedNodes.some(n => n.id === focus)) setPendingFit({ ids: [focus], select: focus });
      else if (g.viewport) void rfRef.current.setViewport(g.viewport);
      else setPendingFit({ ids: introNodeIds(liveNow) });
      return g;
    }

    function trackRun(st: RunState) {
      r.runSeen.set(st.id, st.summary.succeeded);
      const title = boardsRef.current.find(b => b.id === st.board_id)?.title;
      track({ key: `run:${st.id}`, kind: "run", remote: st.id, nodeId: "", label: title ? `一键出片 · ${title}` : "一键出片" });
    }

    async function loadBoard(boardId: string, token: number) {
      const stale = () => token !== r.loadToken;
      try {
        let rec;
        try {
          rec = await cv.canvasGet(boardId);
        } catch (e) {
          if (stale()) return;
          // 画布删了、地址栏里是别的章的旧 id：退回这一章默认的那张
          const fallback = missing(e) ? defaultBoard(boardsRef.current.filter(b => b.id !== boardId)) : null;
          if (fallback) {
            setBoardId(fallback.id);
            return;
          }
          throw e;
        }
        if (stale()) return;
        const plan = rec.plan_id ?? "";
        const chap = rec.chapter_id || "";
        const [board, cast, script] = plan ? await Promise.all([
          cv.board(plan),
          cv.cast(plan).catch(() => [] as CastMember[]),
          chap ? cv.script(plan, chap).catch(() => [] as ScriptScene[]) : Promise.resolve([] as ScriptScene[]),
        ]) : [null, [] as CastMember[], [] as ScriptScene[]];
        if (stale()) return;
        r.versions.set(boardId, rec.version);
        r.local = false;
        setMeta(rec);
        setNovelId(rec.novel_id ?? "");
        setChapterId(rec.chapter_id ?? "");
        setPlanId(rec.plan_id ?? "");
        rememberAll({ project: null, novel: rec.novel_id, chapter: rec.chapter_id, plan: rec.plan_id, canvas: rec.id, shot: null });
        const saved = rec.version ? validDoc(rec.doc) : null;
        const ctx = rec.context;
        const scope = { shotIds: ctx.shot_ids ? new Set(ctx.shot_ids) : null, castIds: ctx.cast_ids ? new Set(ctx.cast_ids) : null };
        const boxes = await fetchBoxes(boxIdsOf(board, saved?.nodes ?? [], scope.shotIds));
        if (stale()) return;
        const liveNow: LiveSources = {
          board, cast, script, boxes, runs: {}, scope, voices: ctx.voices ?? {},
          chapterTitle: board?.chapter?.title || chaptersRef.current.find(c => c.id === rec.chapter_id)?.title || "",
          novelTitle: novelsRef.current.find(n => n.id === (board?.chapter?.novel_id || rec.novel_id))?.title ?? "",
        };
        setLive(liveNow);
        const focus = focusRef.current;
        focusRef.current = "";
        if (focus) remember("shot", focus); // 旧的 ?focus= 统一改写成 ?shot=
        const g = applySaved(liveNow, saved, focus ? nodeIdOf({ kind: "shot", id: focus }) : undefined);
        r.loadedPlan = plan;
        r.loadedBoard = boardId;
        setSave(saved ? "saved" : "idle");
        // 任务不进文档：自由生成占位节点上的 gen 状态、范围内在跑的导演出片、没跑完的一键出片，就是续上轮询的线索
        for (const n of g.nodes) {
          const gen = n.data.gen;
          if (gen && isLive(gen.status)) track({ key: `gen:${gen.task_id}`, kind: "gen", remote: gen.task_id, nodeId: n.id, label: n.data.title || "生成" });
        }
        for (const s of board?.shots ?? []) {
          if ((scope.shotIds && !scope.shotIds.has(s.id)) || !directorPending(s)) continue;
          track({ key: `director:${s.id}`, kind: "director", remote: s.id, nodeId: nodeIdOf({ kind: "shot", id: s.id }), label: `镜 ${s.order_no} 导演出片` });
        }
        if (plan) {
          cv.runList(boardId).then(list => {
            if (stale()) return;
            const latest = list[0] ?? null;
            setFlowRun(latest);
            if (latest && ACTIVE_RUN.has(latest.status)) trackRun(latest);
          }, () => undefined);
        }
      } catch (e) {
        if (!stale()) setError(`载入画布失败：${msg(e)}`);
      } finally {
        if (!stale()) setLoading(false);
      }
    }

    /** 一键出片：画布范围内的镜头排队 补配音 → 搭白模/运镜 → 预演 → 身份首帧 → LTX 2.5 → 挂回 */
    async function startRun(opts: RunOptions): Promise<RunState> {
      const board = r.loadedBoard;
      if (!board) throw new Error("画布还没载入");
      const st = await cv.runStart(board, opts);
      if (r.loadedBoard === board) {
        setFlowRun(st);
        trackRun(st);
      }
      return st;
    }

    async function cancelRun() {
      const cur = flowRunRef.current;
      if (!cur || !ACTIVE_RUN.has(cur.status)) return;
      const st = await cv.runCancel(cur.id);
      if (r.loadedBoard === st.board_id) setFlowRun(st);
    }

    async function reloadBoards() {
      const chap = chapterIdRef.current;
      const [all, list] = await Promise.all([
        cv.canvasAll({ limit: 500 }),
        chap ? cv.canvasList(chap, planIdRef.current || null) : Promise.resolve(null),
      ]);
      setBoards([...new Map([...(list?.canvases ?? []), ...all].map(b => [b.id, b])).values()]);
    }

    async function reloadCanvas() {
      const board = r.loadedBoard;
      if (!board) return;
      window.clearTimeout(r.saveTimer);
      r.dirty = false;
      r.pendingSnap = null;
      try {
        let saved: CanvasDoc | null;
        if (r.local) {
          saved = readLocal(board);
        } else {
          const rec = await cv.canvasGet(board);
          r.versions.set(board, rec.version);
          saved = rec.version ? validDoc(rec.doc) : null;
        }
        if (r.loadedBoard !== board) return;
        const need = boxIdsOf(null, saved?.nodes ?? []).filter(id => !liveRef.current.boxes[id]);
        if (need.length) {
          const got = await fetchBoxes(need);
          if (r.loadedBoard !== board) return;
          setLive(cur => ({ ...cur, boxes: mergeBoxes(cur.boxes, got) }));
        }
        applySaved(liveRef.current, saved);
        setResourceNonce(n => n + 1);
        r.blocked = false;
        r.dirty = false;
        setSave(r.local ? "local" : "saved");
        toast("已按远端重新载入画布", "ok");
      } catch (e) {
        toast(`载入远端画布失败：${msg(e)}`, "err");
      }
    }

    async function saveBeforeLeaving(): Promise<boolean> {
      do {
        await flushSave();
        if (r.blocked || saveRef.current === "error") {
          toast("当前画布未保存成功，请先处理保存错误再切换", "err");
          return false;
        }
      } while (r.dirty);
      return true;
    }

    /* ── 选书选章选计划 ── */
    async function setNovel(id: string) {
      if (id === novelIdRef.current) return;
      const token = ++r.navigationToken;
      if (!await saveBeforeLeaving() || token !== r.navigationToken) return;
      setHome(false);
      setNovelId(id);
      setChapterId("");
      setChapters([]);
      setPlans([]);
      setPlanId("");
      setBoards([]);
      setBoardId("");
      setLoading(true);
    }
    async function setChapter(id: string) {
      if (id === chapterIdRef.current) return;
      const token = ++r.navigationToken;
      if (!await saveBeforeLeaving() || token !== r.navigationToken) return;
      setChapterId(id);
      setPlans([]);
      setPlanId("");
      setBoards([]);
      setBoardId("");
      setLoading(true);
    }
    async function setPlan(id: string) {
      if (id === planIdRef.current) return;
      const token = ++r.navigationToken;
      if (!await saveBeforeLeaving() || token !== r.navigationToken) return;
      setPlanId(id);
      setBoards([]);
      setBoardId("");
    }
    function setBoard(id: string) {
      if (id === boardIdRef.current) return;
      focusRef.current = "";
      rememberAll({ canvas: id, shot: null });
      setHome(false);
      setMeta(null);
      setBoardId(id);
    }

    async function openBoard(id: string) {
      const token = ++r.navigationToken;
      if (!await saveBeforeLeaving() || token !== r.navigationToken) return;
      setBoard(id);
    }

    async function openHome() {
      const token = ++r.navigationToken;
      if (!await saveBeforeLeaving() || token !== r.navigationToken) return;
      setHome(true);
      focusRef.current = "";
      rememberAll({ project: null, novel: null, chapter: null, plan: null, canvas: null, shot: null });
      setNovelId(""); setChapterId(""); setPlanId("");
      setChapters([]); setPlans([]); setMeta(null); setError("");
      setBoardId("");
    }

    async function createCanvas(opts: CreateCanvasOptions): Promise<string> {
      if (!await saveBeforeLeaving()) throw new Error("当前画布未保存成功，请先处理保存错误");
      const title = opts.title.trim() || "空白画布";
      const blank = opts.blank ?? !opts.doc;
      const attachChap = opts.chapter === true && !!chapterIdRef.current;
      const b = await cv.canvasCreate({
        title, blank, purpose: opts.purpose ?? "general",
        chapter_id: attachChap ? chapterIdRef.current : null,
        novel_id: attachChap ? novelIdRef.current : null,
        plan_id: !blank && attachChap ? (planIdRef.current || null) : null,
        shot_ids: [],
        source: "user",
      });
      if (opts.doc) {
        await cv.canvasSave(b.id, b.version, opts.doc);
      }
      setBoards(cur => [b, ...cur.filter(x => x.id !== b.id)]);
      await openBoard(b.id);
      toast(`已新建画布「${title}」`, "ok");
      return b.id;
    }

    /* ── 快捷键 ── */
    /** 从画布拿掉的派生节点（剧本、镜头、定妆照、白模），底栏「已拿掉」和搜索里能放回 */
    function hiddenList(): { id: string; type: NodeKind; title: string }[] {
      if (!r.hidden.size) return [];
      return derivedGraph(liveRef.current).nodes
        .filter(n => r.hidden.has(n.id))
        .map(n => ({ id: n.id, type: n.type, title: n.data.title }));
    }

    /** 放回：从 hidden 去掉再同步一次，派生节点按自动布局长回来，派生连线一起回来 */
    function restoreHidden(ids?: string[]) {
      const want = ids ?? [...r.hidden];
      let n = 0;
      for (const id of want) if (r.hidden.delete(id)) n++;
      if (!n) return;
      syncGraph();
      bump();
      r.dirty = true;
      flushSave();
      toast(n > 1 ? `放回了 ${n} 个节点` : "放回了", "ok", ids?.length === 1 ? { label: "看看", run: () => focusNode(ids[0]) } : undefined);
    }

    /** 一键清理误加的空生成节点（点了「生成」却没发过提示词的），可以一次撤销 */
    function pruneEmpty(): number {
      const ids = nodesRef.current.filter(n => isEmptyGen(n, { tasks: tasksRef.current })).map(n => n.id);
      if (ids.length) removeNodes(ids);
      return ids.length;
    }

    function deleteSelection() {
      const ids = nodesRef.current.filter(n => n.selected).map(n => n.id);
      const sel = edgesRef.current.filter(e => e.selected);
      if (ids.length) removeNodes(ids);
      if (sel.length) onEdgesChange(sel.map(e => ({ type: "remove", id: e.id })));
    }

    function onKey(e: KeyboardEvent) {
      if (overlayRef.current || e.defaultPrevented) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      const mod = e.metaKey || e.ctrlKey;
      if ((mod && e.key.toLowerCase() === "k") || (!mod && !e.altKey && e.key === "/")) {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent(SEARCH_EVENT));
        return;
      }
      if (mod && (e.key === "Delete" || e.key === "Backspace")) {
        e.preventDefault();
        if (!addMenuRef.current) deleteSelection();
        return;
      }
      if (mod && e.key.toLowerCase() === "a") {
        e.preventDefault();
        setNodes(nodesRef.current.map(n => (n.selected ? n : { ...n, selected: true })));
        bump();
        return;
      }
      if (mod || e.altKey) return;
      if (e.key === "Escape") {
        if (addMenuRef.current) setAddMenu(null);
        else select(null);
      } else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        // 新增菜单开着时 ⌫ 不删：用户多半是想关菜单，删掉的却是后面选中的节点
        if (!addMenuRef.current) deleteSelection();
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        void rfRef.current.fitView({ padding: 0.1, duration: 300 });
      }
    }

    return {
      bump, toast, dismissToast, flushSave, scheduleSave, onNodesChange, onEdgesChange, onConnect, isValidConnection,
      select, focusNode, addNode, updateNodeData, removeNodes, connect, upstream, downstream, relayout,
      reloadLive, loadBoxDoc, track, tick, resetGraph, loadBoard, reloadCanvas, setNovel, setChapter, setPlan, setBoard,
      openBoard, openHome, createCanvas, duplicate, groupSelected, ungroup, nextTitle, execute, stopExecute, onKey,
      hiddenList, restoreHidden, pruneEmpty,
      startRun, cancelRun, reloadBoards,
      nodeData: (id: string) => nodeById(id)?.data,
      openAddMenu: (anchor: { x: number; y: number }, from?: { nodeId: string; side: "left" | "right" } | null) =>
        setAddMenu({ anchor, from: from ?? null }),
      closeAddMenu: () => setAddMenu(null),
      openOverlay: (o: Overlay) => { setOverlay(o); if (o) setAddMenu(null); },
      onMoveEnd: () => { if (Date.now() >= r.suppressMoveUntil) scheduleSave(); },
      onPaneClick: () => { if (addMenuRef.current) setAddMenu(null); },
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── 演示模式：先装好 demo api，子组件和载入才开始（保证没有一次调用漏到真后端） ── */
  useEffect(() => {
    if (!demo) return;
    let alive = true;
    void loadDemo().then(api => {
      if (!alive) return;
      useDemoApi(api);
      setDemoReady(true);
    });
    return () => { alive = false; useDemoApi(null); };
  }, [demo]);

  /* ── 载入链：小说 → 章节 → 计划 → 画布 ── */
  useEffect(() => {
    if (!demoReady) return;
    let alive = true;
    cv.novels().then(rows => {
      if (!alive) return;
      setNovels(rows);
      if (!boardIdRef.current && !homeRef.current && !rows.some(n => n.id === novelIdRef.current)) setNovelId(rows[0]?.id ?? "");
      if (!rows.length) setLoading(false);
    }).catch(e => { if (alive) {
      if (boardIdRef.current || homeRef.current) m.toast(`小说列表暂不可用：${msg(e)}`, "err");
      else setError(`读不到小说列表：${msg(e)}`);
      setLoading(false);
    } });
    return () => { alive = false; };
  }, [demoReady]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!demoReady || !novelId) return;
    remember("novel", novelId);
    let alive = true;
    cv.chapters(novelId).then(rows => {
      if (!alive) return;
      setChapters(rows);
      if (!boardIdRef.current && !rows.some(c => c.id === chapterIdRef.current)) setChapterId(rows[0]?.id ?? "");
      if (!rows.length) { setPlans([]); setPlanId(""); setLoading(false); }
    }).catch(e => { if (alive) { setError(`读不到章节：${msg(e)}`); setLoading(false); } });
    return () => { alive = false; };
  }, [demoReady, novelId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!demoReady || !chapterId) return;
    remember("chapter", chapterId);
    let alive = true;
    cv.plans(chapterId).then(d => {
      if (!alive) return;
      const rows: PlanRow[] = d.plans.map(p => ({ id: p.id, version: p.version, shots: p.shots, sample: p.sample, status: p.status }));
      setPlans(rows);
      if (!boardIdRef.current && !rows.some(p => p.id === planIdRef.current)) {
        // 默认看最近一份正式分镜；试片计划只有几镜，不适合当画布的起点（同 App.tsx）
        const main = rows.find(p => !p.sample && p.shots > 0) ?? rows[0];
        setPlanId(main?.id ?? "");
      }
      if (!rows.length) setLoading(false);
    }).catch(e => { if (alive) { setError(`读不到分镜计划：${msg(e)}`); setLoading(false); } });
    return () => { alive = false; };
  }, [demoReady, chapterId]); // eslint-disable-line react-hooks/exhaustive-deps

  /* 全部画布平级可见；带章节入口时才请求自动分镜布局。 */
  useEffect(() => {
    if (!demoReady) return;
    let alive = true;
    Promise.all([
      cv.canvasAll({ limit: 500 }),
      chapterId && planId ? cv.canvasList(chapterId, planId) : Promise.resolve(null),
    ]).then(async ([all, list]) => {
      if (!alive) return;
      const rows = [...new Map([...(list?.canvases ?? []), ...all].map(b => [b.id, b])).values()];
      setBoards(rows);
      // Existing canvas IDs are authoritative, including a canvas from another chapter.
      let want = boardIdRef.current;
      if (focusRef.current && list) {
        const cur = rows.find(b => b.id === want);
        if (!cur || !cur.scope?.shot_ids?.includes(focusRef.current)) {
          want = await cv.shotCanvas(focusRef.current).then(b => b.id, () => want);
        }
      }
      if (!alive) return;
      if (!want && !homeRef.current && list) want = defaultBoard(list.canvases)?.id ?? "";
      if (want) setBoardId(want);
      else setLoading(false);
    }).catch(e => { if (alive) { setError(`读不到画布列表：${msg(e)}`); setLoading(false); } });
    return () => { alive = false; };
  }, [demoReady, chapterId, planId]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── 画布 → 载入（换画布前先把旧的存掉，快照此刻拍下） ── */
  useEffect(() => {
    if (!demoReady) return;
    m.flushSave();
    m.resetGraph();
    if (!boardId) return;
    remember("canvas", boardId);
    setError("");
    setLoading(true);
    const token = ++r.loadToken;
    void m.loadBoard(boardId, token);
  }, [demoReady, boardId]); // eslint-disable-line react-hooks/exhaustive-deps

  const resourceSignature = JSON.stringify(nodes.filter(n => isProductionRef(n.data.ref)).map(n => n.data.ref));
  useEffect(() => {
    if (!demoReady || demo || !boardId || loading) return;
    const refs = nodesRef.current.map(n => n.data.ref).filter(isProductionRef);
    if (!refs.length) return;
    let alive = true;
    const selectedBoard = boardId;
    void prod.context(boardId).then(async c => {
      const batches = [];
      for (let i = 0; i < refs.length; i += 100) batches.push(prod.resolve(c.data.context, refs.slice(i, i + 100)));
      const results = await Promise.all(batches);
      return { data: { items: results.flatMap(result => result.data.items) } };
    }).then(result => {
      if (!alive || r.loadedBoard !== selectedBoard) return;
      const resources = Object.fromEntries(result.data.items.map(it => [nodeIdOf(it.ref), it]));
      setLive(cur => ({ ...cur, resources }));
    }).catch(e => {
      if (!alive || r.loadedBoard !== selectedBoard) return;
      const resources = Object.fromEntries(refs.map(ref => [nodeIdOf(ref), {
        ref, status: "unresolved", resource: null, issues: [{ code: "resolve_failed", message: msg(e) }],
      }]));
      setLive(cur => ({ ...cur, resources }));
    });
    return () => { alive = false; };
  }, [demoReady, demo, boardId, loading, resourceSignature, resourceNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── 首屏视口：节点量完尺寸才能 fitView（没保存过视口时飞到前两场） ── */
  const initialized = useNodesInitialized();
  useEffect(() => {
    if (!pendingFit || !initialized) return;
    const have = new Set(nodesRef.current.map(n => n.id));
    const ids = pendingFit.ids?.filter(id => have.has(id));
    r.suppressMoveUntil = Date.now() + 1500;
    void rf.fitView({ nodes: ids?.length ? ids.map(id => ({ id })) : undefined, padding: 0.12, maxZoom: 1 });
    if (pendingFit.select && have.has(pendingFit.select)) m.select(pendingFit.select);
    setPendingFit(null);
  }, [pendingFit, initialized]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── 唯一轮询器 ── */
  const boardBusy = useMemo(() => live.board?.shots.some(s =>
    s.first?.status === "generating" || s.last?.status === "generating" || directorPending(s)) ?? false, [live.board]);
  r.boardBusy = boardBusy;
  const hasActive = tasks.some(t => isLive(t.status));
  useEffect(() => {
    if (!hasActive && !boardBusy) return;
    const timer = window.setInterval(() => { void m.tick(); }, 2000);
    return () => window.clearInterval(timer);
  }, [hasActive, boardBusy, m]);

  /* ── 快捷键、离开前存盘 ── */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => m.onKey(e);
    const onLeave = () => m.flushSave();
    window.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onLeave);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", onLeave);
      m.flushSave();
    };
  }, [m]);

  /* ── 对外的 store：结构变化才换对象；常读字段走 getter 拿最新 ── */
  const store = useMemo<CanvasStore>(() => {
    const selectedNodes = () => nodesRef.current.filter(n => n.selected);
    return {
      novelId, chapterId, planId, boardId, demo,
      pick: { novels, chapters, plans, setNovel: m.setNovel, setChapter: m.setChapter, setPlan: m.setPlan, setBoard: id => { void m.openBoard(id); } },
      boards,
      board: boards.find(b => b.id === boardId) ?? meta ?? null,
      home,
      openHome: () => { void m.openHome(); },
      openBoard: (id: string) => { void m.openBoard(id); },
      createCanvas: m.createCanvas,
      duplicate: m.duplicate,
      groupSelected: m.groupSelected,
      ungroup: m.ungroup,
      nextTitle: m.nextTitle,
      get exec() { return execRef.current; },
      get nodeRuns() { return nodeRunsRef.current; },
      execute: m.execute,
      stopExecute: m.stopExecute,
      flushSave: m.flushSave,
      run: flowRun,
      startRun: m.startRun,
      get hidden() { return m.hiddenList(); },
      restoreHidden: m.restoreHidden,
      pruneEmpty: m.pruneEmpty,
      cancelRun: m.cancelRun,
      reloadBoards: m.reloadBoards,
      loading, error,
      get nodes() { return nodesRef.current; },
      get edges() { return edgesRef.current; },
      onNodesChange: m.onNodesChange,
      onEdgesChange: m.onEdgesChange,
      onConnect: m.onConnect,
      get live() { return liveRef.current; },
      resolve: (ref: NodeRef, data?: CNodeData) => resolveRef(liveRef.current, ref, data),
      reloadLive: m.reloadLive,
      loadBoxDoc: m.loadBoxDoc,
      get selectedId() { const s = selectedNodes(); return s.length === 1 ? s[0].id : null; },
      get selected() { const s = selectedNodes(); return s.length === 1 ? s[0] : null; },
      select: m.select,
      addNode: m.addNode,
      updateNodeData: m.updateNodeData,
      removeNodes: m.removeNodes,
      connect: m.connect,
      upstream: m.upstream,
      downstream: m.downstream,
      relayout: m.relayout,
      focusNode: m.focusNode,
      get tasks() { return tasksRef.current; },
      track: m.track,
      get addMenu() { return addMenuRef.current; },
      openAddMenu: m.openAddMenu,
      closeAddMenu: m.closeAddMenu,
      toast: m.toast,
      get toasts() { return toastsRef.current; },
      dismissToast: m.dismissToast,
      get overlay() { return overlayRef.current; },
      openOverlay: m.openOverlay,
      save,
      reloadCanvas: () => { void m.reloadCanvas(); },
    };
    // rev / live / tasks / toasts / overlay / addMenu 只用来触发换对象（字段本身走 getter）
  }, [rev, live, tasks, toasts, overlay, addMenu, save, loading, error, novelId, chapterId, planId, boardId, boards, flowRun, novels, chapters, plans, demo, home, meta, m]); // eslint-disable-line react-hooks/exhaustive-deps
  r.store = store;

  const liveValue = useMemo<LiveCtxValue>(() => ({ live, nodeData: m.nodeData }), [live, m]);
  const graphValue = useMemo<FlowBinding>(() => ({
    nodes, edges, onMoveEnd: m.onMoveEnd, isValidConnection: m.isValidConnection, onPaneClick: m.onPaneClick,
  }), [nodes, edges, m]);

  return (
    <StoreCtx.Provider value={store}>
      <LiveCtx.Provider value={liveValue}>
        <GraphCtx.Provider value={graphValue}>
          {demoReady ? children : <div className="cv-boot">载入演示数据…</div>}
        </GraphCtx.Provider>
      </LiveCtx.Provider>
    </StoreCtx.Provider>
  );
}
