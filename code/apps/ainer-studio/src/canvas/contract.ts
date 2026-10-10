/**
 * 创作画布各模块之间的接口约定（store 形状、公共组件 props）。
 * 实现分散在：store.tsx（CanvasStore）、nodes/NodeShell.tsx（NodeShellProps）、
 * actions.ts（actionsFor）、three/*（白模）。改这里 = 改所有人的约定。
 */
import type { ReactNode } from "react";
import type { OnConnect, OnEdgesChange, OnNodesChange, XYPosition } from "@xyflow/react";
import type {
  CreateCanvasOptions, CanvasMeta, CEdge, CNode, CNodeData, EdgeKind, ExecuteOptions, ExecuteState, LiveSources, NodeKind, NodeRef,
  NodeRun, Resolved, RunOptions, RunState, TrackedTask,
} from "./model";

export type SaveState = "idle" | "saving" | "saved" | "local" | "conflict" | "error";

export interface Toast {
  id: number;
  text: string;
  tone: "info" | "ok" | "err";
  action?: { label: string; run: () => void };
}

export interface CanvasStore {
  /* 上下文 */
  novelId: string;
  chapterId: string;
  planId: string;
  /** 当前画布 id（一章多张：整章总览 / 场次 / 自建） */
  boardId: string;
  demo: boolean;
  /** 选书/章/计划（顶栏用）；切换后整张画布重载 */
  pick: {
    novels: { id: string; title: string }[];
    chapters: { id: string; order_no: number; title: string }[];
    plans: { id: string; version: number; shots: number; sample: boolean; status: string }[];
    setNovel(id: string): void;
    setChapter(id: string): void;
    setPlan(id: string): void;
    setBoard(id: string): void;
  };
  /** 这一章（这份分镜）的画布列表 */
  boards: CanvasMeta[];
  board: CanvasMeta | null;
  /** 列表上的镜头数、已出数会变：新建、重新分、一键出片跑完后刷新 */
  reloadBoards(): Promise<void>;

  /** 从画布拿掉的派生节点（剧本、镜头、定妆照、白模）：底栏「已拿掉」、搜索里能放回 */
  readonly hidden: { id: string; type: NodeKind; title: string }[];
  /** 放回（不给 ids = 全部） */
  restoreHidden(ids?: string[]): void;
  /** 清理误加的空生成节点，返回清掉几个（可以撤销） */
  pruneEmpty(): number;

  /* 一键出片（工作流在后端跑，store 的唯一轮询器推进进度） */
  run: RunState | null;
  startRun(opts: RunOptions): Promise<RunState>;
  cancelRun(): Promise<void>;
  loading: boolean;
  error: string;

  /* 图（xyflow 受控） */
  nodes: CNode[];
  edges: CEdge[];
  onNodesChange: OnNodesChange<CNode>;
  onEdgesChange: OnEdgesChange<CEdge>;
  /** 连线：按两端类型推断 EdgeKind；派生关系已存在则不重复建 */
  onConnect: OnConnect;

  /* 现取的后端数据 */
  live: LiveSources;
  /** 节点真身（派生节点从 live 里找；自由节点读 data） */
  resolve(ref: NodeRef, data?: CNodeData): Resolved;
  /** 重新拉 board/cast/script/boxes（出片完成、白模改完后调） */
  reloadLive(): Promise<void>;
  /** 按需载入某个白模的完整 SceneDoc（白模节点激活时调；已载入则直接返回） */
  loadBoxDoc(boxProjectId: string, force?: boolean): Promise<void>;

  /* 选中 */
  selectedId: string | null;
  selected: CNode | null;
  select(id: string | null): void;

  /* 编辑 */
  /** 新建节点；connectFrom 给了就顺手连一条线。返回新节点 id。at 缺省 = 视口中心附近的空位 */
  addNode(type: NodeKind, data: CNodeData, at?: XYPosition, connectFrom?: { source: string; kind: EdgeKind }): string;
  updateNodeData(id: string, patch: Partial<CNodeData>): void;
  /** 从画布上移除（派生节点只是隐藏，不删后端真身；会进文档的 hidden 列表） */
  removeNodes(ids: string[]): void;
  connect(source: string, target: string, kind: EdgeKind): void;
  /** 某节点的上游（连进来的节点 + 边），生成面板的参考就从这里来 */
  upstream(id: string): { node: CNode; edge: CEdge }[];
  downstream(id: string): { node: CNode; edge: CEdge }[];
  /** 自动整理派生节点（钉住的不动） */
  relayout(): void;
  /** 视口飞到某节点 */
  focusNode(id: string): void;

  /* 任务（唯一轮询器） */
  tasks: TrackedTask[];
  track(t: Omit<TrackedTask, "startedAt" | "status"> & { status?: TrackedTask["status"] }): void;

  /* 「新增节点」菜单：底部 + 按钮或节点两侧的 + 打开；from 给了就把新节点接在它那一侧并连线 */
  addMenu: { anchor: { x: number; y: number }; from: { nodeId: string; side: "left" | "right" } | null } | null;
  openAddMenu(anchor: { x: number; y: number }, from?: { nodeId: string; side: "left" | "right" } | null): void;
  closeAddMenu(): void;

  /* 提示 */
  toast(text: string, tone?: Toast["tone"], action?: Toast["action"]): void;
  toasts: Toast[];
  dismissToast(id: number): void;

  /* 全屏浮层（打开时画布暂停自己的快捷键） */
  overlay: { kind: "box"; id: string } | { kind: "stage"; shotId: string } | { kind: "media"; url: string; video: boolean }
    | { kind: "shared_stage"; id?: string } | { kind: "quick" } | { kind: "screenplay_config"; nodeId?: string; presetId?: string } | null;
  openOverlay(o: CanvasStore["overlay"]): void;

  /* 画布首页 / 新建：不挂小说的自由画布（旅拍、相册、一个想法）和章节画布一样能开 */
  /** 正在看画布首页（?view=flow 没有 canvas、或点了顶栏「首页」） */
  home: boolean;
  openHome(): void;
  /** 打开任意一张画布（含不属于当前章节的自由画布）；会先存当前画布 */
  openBoard(id: string): void;
  /**
   * 新建画布并打开，返回 id。chapter=true 挂在当前章节（列在这一章的画布里），否则是自由画布。
   * doc 给了就作为初始文档一次存进去（想法 → 整张画布用这个）。
   */
  createCanvas(opts: CreateCanvasOptions): Promise<string>;

  /* 纳逗式编辑 */
  /** 复制节点（自由节点连 media、配方一起；派生节点复制成一张静态图/视频），标题「图片 3 拷贝1」；返回新 id */
  duplicate(ids: string[]): string[];
  /** 把选中的节点编成一组（⌘G），标题「分组 N」；返回分组 id，少于 1 个可编的返回 null */
  groupSelected(): string | null;
  /** 解散分组：子节点留在原地 */
  ungroup(groupId: string): void;
  /** 下一个自动标题：图片 N / 视频 N / 文本 N / 分组 N（按画布里已有的最大号 +1） */
  nextTitle(kind: NodeKind): string;

  /* 服务端执行器（按节点配方跑；关了浏览器也照跑，结果在 node-runs 里，store 填回节点） */
  exec: ExecuteState | null;
  /** key = 节点 id：最近一次运行 */
  nodeRuns: Record<string, NodeRun>;
  /** 先把画布存好（执行器读的是库里的文档），再提交；不给 opts = 整张画布缺的都跑 */
  execute(opts?: ExecuteOptions): Promise<void>;
  stopExecute(): Promise<void>;
  /** 立刻存盘（不等防抖），等它完成 */
  flushSave(): Promise<void>;

  /* 保存 */
  save: SaveState;
  /** 冲突后丢掉本地改动、按远端重载 */
  reloadCanvas(): void;
}

/** 节点外壳（nodes/NodeShell.tsx）：标题、端口、选中光圈、状态角标、「+」快捷加节点 */
export interface NodeShellProps {
  id: string;
  kind: NodeKind;
  data: CNodeData;
  selected: boolean;
  /** 卡片内容区宽度（px）；高度由内容撑 */
  width: number;
  children: ReactNode;
  /** 标题右侧的小角标（「3D 导演」「出片中」「本机」…） */
  badges?: ReactNode;
  /** 卡片底部状态条（进度、步骤） */
  footer?: ReactNode;
  /** 生成中：边框流光 */
  busy?: boolean;
  /** 双击卡片 */
  onOpen?: () => void;
}
