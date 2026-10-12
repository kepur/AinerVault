/**
 * 创作画布（?view=flow）的数据契约。
 *
 * 一张画布挂在一份分镜计划（ShotPlan）上。节点分两种：
 *   派生节点 —— 真身在后端（剧本场次、镜头、角色视角图、3D-BOX 项目、导演产物），
 *              画布文档只存「位置 + 引用」，内容每次现取（HANDOVER §3.2：存了就要有人读，
 *              画布不当第二份数据源）。
 *   自由节点 —— 用户自己加的文字、上传的图、自由生成的产物，内容存在画布文档里。
 *
 * 画布文档 schema = "ainer.board/v1"，后端 core.studio_boards.doc_json 原样存。
 */
import type { ComicBinding, ComicLive } from "./comic";
import type { ResourceRef, ResourceItem, Resource } from "../production/api";
import type { Edge, Node } from "@xyflow/react";
import type { Board, CastMember, DirectorRun, ShotCard } from "../types";
import type { SceneDoc } from "../scene/types";

export const DOC_SCHEMA = "ainer.board/v1" as const;

/* ───────────────────────── 节点 ───────────────────────── */

/** group = 分组框（纳逗的「分组 4」）：子节点用 xyflow 的 parentId 挂在它里面，整组一起拖；@分组 = 组里所有图 */
export type NodeKind = "text" | "image" | "video" | "audio" | "box3d" | "group" | "stage" | "coverage";

/** 节点的真身在哪。id 规则见 nodeIdOf()：同一个真身在一张画布上只有一个节点。 */
export type NodeRef =
  /** 章节梗概（chapter id） */
  | { kind: "story"; id: string }
  /** 剧本场次（script Scene.id = ShotCard.scene_id） */
  | { kind: "scene"; id: string }
  /** 分镜镜头（Shot.id） */
  | { kind: "shot"; id: string }
  /** 角色某一视角的图：view = front | three_quarter_left | profile_left | back | bust | sheet */
  | { kind: "entity_view"; id: string; view: string }
  /** 3D-BOX 项目（scene_projects.id，前缀 sc） */
  | { kind: "box_project"; id: string }
  /** 导演任务的一个产物：job = director_jobs.id，output = preview|clay|depth|pose|canny|first_frame|final */
  | { kind: "director_output"; id: string; job: string; output: string }
  /** 已落库的媒体（上传或生成后本地化的 Asset） */
  | { kind: "asset"; id: string }
  /** 用户自由节点（内容在 data 里） */
  | { kind: "free"; id: string }
  | ResourceRef;

export function isProductionRef(ref: NodeRef): ref is ResourceRef {
  return "mode" in ref && ref.mode === "reference" && !!ref.revision;
}

/** 图片节点的角色：决定标题、工具条和连线默认语义 */
export type ImageRole = "character" | "prop" | "sheet" | "prop_sheet" | "view" | "upload" | "generated" | "frame" | "control" | "scene" | "style";
/** 视频节点的角色 */
export type VideoRole = "shot" | "generated" | "previs" | "control";
/** 文字节点的角色 */
export type TextRole = "story" | "scene" | "note" | "prompt";

/** 自由生成任务在节点上的状态（产物节点先建出来占位，任务跑完把 media 填上） */
export interface GenState {
  task_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress?: number | null;
  error?: string | null;
  model?: string | null;
  /** 发出去时的提示词（给人看；不回读当输入，HANDOVER §4.2） */
  prompt?: string | null;
}

export interface MediaRef {
  /** 只存 /media/… 同源地址或 data:；网关临时地址不许进文档（会变死链） */
  url: string;
  asset_id?: string | null;
  mime?: string | null;
  w?: number | null;
  h?: number | null;
  duration?: number | null;
}

/** xyflow 要求 data 是 Record<string, unknown> */
export interface CNodeData extends Record<string, unknown> {
  comic?: ComicBinding;
  comicLive?: ComicLive;
  ref: NodeRef;
  /** 节点上方的小标题（纳逗式：「定妆照」「多角度定妆照」「镜头 3」） */
  title: string;
  role?: ImageRole | VideoRole | TextRole;
  /** 自由文字节点的正文 */
  text?: string;
  /** 自由图片/视频节点的媒体（派生节点不用，现取） */
  media?: MediaRef | null;
  /** 自由生成产物的任务状态 */
  gen?: GenState | null;
  /** Editable manual panel draft, distinct from the submitted task snapshot. */
  manualDraft?:{prompt:PromptSeg[];settings:Record<string,unknown>;roles:Record<string,RefRole>;excluded:string[]};
  /** 3D 白模节点：当前看哪台机位（null = 按剪辑表） */
  camera?: string | null;
  /** 用户钉住：自动整理不挪它 */
  pinned?: boolean;
  /** 3D 白模节点：没选中也保持实时渲染（仍受同屏实时视口上限约束） */
  live?: boolean;
  /**
   * 生成配方（纳逗式）：这个节点怎么来的 —— 提示词（含 @引用）、参考节点和各自角色、模型与参数。
   * 有配方的节点能在生成面板里改了重跑；服务端执行器（/studio/canvases/{id}:execute）按它跑，
   * 结果先进 node-runs，store 再填回 media。只存在自由节点上。
   */
  recipe?: Recipe | null;
  /** 重新生成前的旧结果（最近的在前，最多 12 个）：节点工具条「历史」里换回 */
  history?: MediaRef[];
  /** 运行时算出、不进文档：真身找不到了（分镜重编译后的旧镜头等） */
  orphan?: boolean;
}

export type CNode = Node<CNodeData, NodeKind>;

/* ───────────────────────── 连线 ───────────────────────── */

/**
 * 连线语义（颜色也按它分）：
 *   flow     剧本场次 → 镜头（派生，暗线）
 *   identity 定妆照/设定图 → 镜头或白模（谁的脸）
 *   control  3D 白模/控制素材 → 视频（构图、站位、运镜、动作）
 *   ref      一般参考（图、文字、视频）
 *   style    风格参考
 */
export type EdgeKind = "flow" | "identity" | "control" | "ref" | "style";

export interface CEdgeData extends Record<string, unknown> {
  kind: EdgeKind;
  /** 能从后端关系推出来的边：每次载入现算，不进文档 */
  derived?: boolean;
}

export type CEdge = Edge<CEdgeData, "glow">;

/* ───────────────────────── 文档 ───────────────────────── */

export interface DocNode {
  id: string;
  type: NodeKind;
  /** 在哪个分组里（xyflow parentId；position 相对分组左上角） */
  parentId?: string | null;
  position: { x: number; y: number };
  width?: number;
  height?: number;
  data: Omit<CNodeData, "orphan">;
}

export interface DocEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  data: CEdgeData;
}

export interface CreateCanvasOptions {
  title: string; doc?: CanvasDoc | null; chapter?: boolean;
  blank?: boolean; purpose?: "general" | "assets" | "directing" | "finishing";
}

export interface CanvasDoc {
  production?: {id:string;medium:"comic";script_doc_id:string};
  schema: typeof DOC_SCHEMA;
  viewport: { x: number; y: number; zoom: number };
  nodes: DocNode[];
  /** 只存用户连的边；derived 边不存 */
  edges: DocEdge[];
  /** 用户从画布上拿掉的派生节点 id（真身还在后端，下次载入不再自动长回来） */
  hidden?: string[];
}

/** 同一个真身 → 同一个节点 id（自由节点用自己的随机 id） */
export function nodeIdOf(ref: NodeRef): string {
  if (isProductionRef(ref)) return `${ref.kind}:${ref.id}:${ref.revision}`;
  switch (ref.kind) {
    case "entity_view": return `entity:${ref.id}:${ref.view}`;
    case "director_output": return `dout:${ref.job}:${ref.output}`;
    case "free": return ref.id;
    default: return `${ref.kind}:${ref.id}`;
  }
}

/** 是否派生节点（真身在后端；删除只是从画布上拿掉，不删真身） */
export function isDerived(ref: NodeRef): boolean {
  return !isProductionRef(ref) && ref.kind !== "free" && ref.kind !== "asset";
}

/* ───────────────────────── 现取的后端数据 ───────────────────────── */

export interface ScriptBlock {
  id: string;
  type: string; // narration|dialogue|action|signage|title|inner_monolog|heading|scene_break
  text: string;
  speaker?: string | null;
}

export interface ScriptScene {
  id: string;
  order_no: number;
  title: string | null;
  time_of_day: string | null;
  location_text: string | null;
  summary?: string | null;
  blocks: ScriptBlock[];
}

/** 3D-BOX 项目的轻量信息；doc 按需载入（只有被激活的白模节点才拉全量） */
export interface BoxInfo {
  id: string;
  title: string;
  thumb_url: string | null;
  updated_at: string | null;
  ok?: boolean | null;
  duration?: number | null;
  cameras?: { id: string; name: string }[];
  /** 编译好的场景（null = 还没载入或编译失败） */
  doc?: SceneDoc | null;
  /** 智能体正在改它（对话搭景中） */
  active_run?: string | null;
}

/* ───────────────────────── 一章多张画布 ───────────────────────── */

/** plan = 整章总览（一份分镜一张）；scene = 按场次自动分的（长场次切段）；custom = 自建（任意镜头 / 空白画布） */
export type BoardKind = "plan" | "scene" | "custom";

/** 画布列表里的一行（后端 canvas.board_meta） */
export interface CanvasMeta {
  id: string;
  kind: BoardKind;
  title: string;
  source: "auto" | "user" | "api";
  sort: number;
  plan_id: string | null;
  chapter_id: string | null;
  novel_id: string | null;
  scope: { key?: string; scene_ids?: string[]; shot_ids?: string[]; purpose?: string; stale?: boolean };
  purpose?: string | null;
  /** 分镜重编译后对不上了（布局动过所以没删） */
  stale: boolean;
  version: number;
  updated_at: string | null;
  /** 这张画布管的镜头数、已出视频数（没挂分镜为 null） */
  shots: number | null;
  videos: number | null;
}

/** 角色的音色（配音表里定的；出片时台词按它配、再驱动口型） */
export interface VoiceInfo { describe: string; engine: string | null; has_ref: boolean }

/** 画布要现取的范围：null = 整章全部 */
export interface CanvasContext {
  shot_ids: string[] | null;
  cast_ids: string[] | null;
  voices: Record<string, VoiceInfo>;
}

/** 一键出片工作流（后端 canvas_run.run_out） */
export interface RunItem {
  shot_id: string;
  order_no: number;
  step: "audio" | "frame" | "video" | "director" | "done";
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  error?: string | null;
  note?: string | null;
  audio?: "drive" | "generate" | "none" | null;
  reused?: boolean;
  /** 关键帧方案：沿用了已经画好的关键帧 */
  frame?: "reused";
  /** 先出分镜图：停在了关键帧 */
  stopped?: "frame";
  /** 几张候选里挑了哪张、为什么（本机视觉模型） */
  pick?: { best: number; of: number; reason: string } | null;
}

export interface RunState {
  id: string;
  board_id: string | null;
  plan_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  profile: "fast" | "hd";
  options: Partial<RunOptions>;
  items: RunItem[];
  summary: {
    total: number; pending: number; running: number; succeeded: number; failed: number; skipped: number;
    current: (RunItem & { director?: DirectorRun | null }) | null;
  };
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  queued_behind?: number;
}

export interface RunOptions {
  /** keyframe = 关键帧方案（默认，借鉴纳逗：定妆照＋场景图 → 关键帧 → 视频模型钉住它出片）；director = 3D 白模控制 */
  method: "keyframe" | "director";
  /** 本机（FLUX.2-klein → LTX 2.5）/ 云端（通义图像编辑 → 万相图生视频，付费）；只对关键帧方案有效 */
  engine: "local" | "cloud";
  profile: "fast" | "hd";
  audio: "auto" | "generate" | "none";
  only_missing: boolean;
  reuse_scene: boolean;
  reuse_frames: boolean;
  /** frame = 只出分镜图（关键帧 / 身份首帧），审过再出视频；video = 一路出到视频 */
  stop_after: "frame" | "video";
  /** 关键帧方案：出图前先导演审片（本机 LM Studio 把这场戏连起来看：谁是谁、首帧静态描述、LTX 运动描述）。后端默认开 */
  review?: boolean;
  /** 已经审过的也重审（重画分镜图时后端自动重审） */
  re_review?: boolean;
  /** 每镜出几张关键帧候选，>1 时本机视觉模型对着定妆照挑一张。后端默认 2 */
  candidates?: number;
  shot_ids?: string[];
}

export interface LiveSources {
  resources?: Record<string, ResourceItem>;
  board: Board | null;
  cast: CastMember[];
  script: ScriptScene[];
  /** key = box project id */
  boxes: Record<string, BoxInfo>;
  /** key = shot id：导演出片进度（只有在跑的才有） */
  runs: Record<string, DirectorRun | null>;
  chapterTitle: string;
  novelTitle: string;
  /** 这张画布的范围（null = 整章）：导入时只摆范围内的镜头、场次和出场人物 */
  scope: { shotIds: Set<string> | null; castIds: Set<string> | null };
  /** entity_id → 音色 */
  voices: Record<string, VoiceInfo>;
}

/** 现取一个节点真身的结果（渲染节点时用；找不到 = orphan） */
export type Resolved =
  | { kind: "story"; title: string; text: string }
  | { kind: "scene"; scene: ScriptScene }
  | { kind: "shot"; shot: ShotCard; run: DirectorRun | null }
  | { kind: "entity_view"; member: CastMember; url: string | null; voice: VoiceInfo | null }
  | { kind: "box_project"; box: BoxInfo }
  | { kind: "stage_resource"; resource: Resource }
  | { kind: "media"; media: MediaRef }
  | { kind: "text"; text: string }
  | { kind: "missing"; reason?: string };

/* ───────────────────────── 任务 ───────────────────────── */

/**
 * 画布上所有长任务统一登记，由 store 里唯一一个轮询器推进（不许每个节点自己 setInterval）。
 *   director  导演出片（:render）           GET /director/shots/{shot}/run
 *   ltx25     文字出片（videos:ltx25）       刷 board，看 video_url 变没变
 *   gen       自由生成（studio/generate）    GET /studio/generate/{task}
 *   blender   白模渲控制素材                GET /director/jobs/{job}
 *   box_agent 智能体搭景/改景               GET /scene3d/projects/{pid}（active_run 清空即完成）
 *   run       一键出片工作流（一组镜头）     GET /studio/runs/{run}
 */
export type TaskKind = "director" | "ltx25" | "gen" | "blender" | "box_agent" | "run" | "quick" | "comic";

/** 快速成片（纳逗式一条龙）的进度：/api/v2/studio/quick-films/{id} */
export interface QuickFilmJob {
  id: string;
  state: "running" | "done" | "failed";
  /** plan / look / outfit / scene / frame:N / video / video:N / concat / done */
  step: string;
  error: string | null;
  plan: { title: string; scene: string; shots: { size: string; first_frame: string; motion: string; seconds: number }[] } | null;
  /** 按出来的顺序：定妆照、换装定妆照、场景图、分镜 N、镜头 N、成片 */
  outputs: { kind: "look" | "scene" | "frame" | "clip" | "video"; title: string; asset_id: string; url: string;
    shot?: number; pick?: { best: number; of: number; reason: string } }[];
}

export interface QuickFilmIn {
  idea: string;
  person: { asset_id?: string; url?: string };
  outfit?: { asset_id?: string; url?: string } | null;
  scene?: { asset_id?: string; url?: string } | null;
  shots: number;
  mode: "one_take" | "cuts";
  candidates?: number;
}

export interface TrackedTask {
  /** 唯一键：`${kind}:${远端 id}` */
  key: string;
  kind: TaskKind;
  /** 远端 id：shot id / gen task id / director job id / box project id */
  remote: string;
  /** 结果挂到哪个节点上（或从哪个节点长出新节点） */
  nodeId: string;
  label: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress?: number | null;
  error?: string | null;
  startedAt: number;
  /** ltx25 用：提交前的 video_url，变了就算完成 */
  baseline?: string | null;
}

/* ───────────────────────── 生成面板 ───────────────────────── */

/** 提示词 = 文字片段 + @引用（引用只引用，不复制对方的提示词进来 —— 铁律 5） */
export type PromptSeg = { t: "text"; text: string } | { t: "ref"; node: string; label: string };

/** 参考在生成里扮演的角色（发给 /studio/generate 的 refs[].role） */
export type RefRole =
  | "character" | "prop" | "first_frame" | "last_frame" | "style" | "scene"
  | "reference_sheet" | "control_video" | "base" | "reference";

export interface ModelOption {
  endpoint_id: string | null;
  model: string;
  label: string;
  capability: string; // image.text_to_image | image.image_to_image | video.text_to_video | video.image_to_video …
  media: "image" | "video";
  ready: boolean;
  local: boolean;
  cost: number;
  estimated_ms: number | null;
  limits: {
    fps?:number[];
    sizes?: [number, number][];
    max_duration_ms?: number | null;
    max_ref_images?: number | null;
    max_count?: number | null;
  };
  supports?: Record<string, unknown>;
}

export interface GenerateBody {
  media: "image" | "video";
  endpoint_id?: string | null;
  model?: string | null;
  prompt: string;
  negative_prompt?: string | null;
  refs: { node_id: string; url: string; asset_id?: string | null; production_ref?: ResourceRef; kind: "image" | "video" | "audio"; role: RefRole; tag?: string }[];
  aspect_ratio: string; // "16:9" | "9:16" | "1:1" | "4:3" | "3:4"
  resolution: string; // "480p" | "720p" | "1080p"
  duration_ms?: number | null;
  video_fps?:number;
  count: number;
  seed?: number | null;
  target?: { board_id?: string; plan_id: string | null; node_id: string } | null;
}

export interface GenerateResult {
  tasks: { id: string; status: GenState["status"] }[];
  resolved: { endpoint_id: string | null; model: string; width: number; height: number; duration_ms: number | null };
  warnings: string[];
  estimated_cost: number;
  requires_confirm: boolean;
}

export interface GenTaskState {
  id: string;
  status: GenState["status"];
  progress: number | null;
  error: string | null;
  assets: { asset_id: string; url: string; kind: "image" | "video" | "audio"; mime?: string | null }[];
}

/* ───────────────────────── 工具条动作 ───────────────────────── */

export interface CanvasAction {
  id: string;
  label: string;
  /** 一个字或一个符号的图标（不引图标库） */
  icon?: string;
  badge?: "NEW";
  /** 不可用时写明原因（显示在 tooltip 上）；可用为 false/undefined */
  disabled?: string | false;
  title?: string;
  /** 二级菜单（有 menu 时点主按钮展开） */
  menu?: CanvasAction[];
  run?: () => void | Promise<unknown>;
}

/* ───────────────────────── 生成配方与服务端执行器 ───────────────────────── */

/**
 * 配方的动作。执行器按 op 分派：
 *   image      出图：有 role=base 的参考走图像编辑（flux2-klein-4b-edit），没有走文生图（flux2-klein-4b）
 *   video      出视频：LTX 2.5（ltx-2.5-22b-distilled）图生视频，role=first_frame 的参考钉第 0 帧；默认 768×448、带声音
 *   sheet      标准定妆照：全身三视图（前/后/侧）+ 面部四角度（正/左/右/后脑）+ 九宫格表情，拼成一张设定图
 *   concat     把 refs 里的几条视频按顺序接成一支
 *   last_frame 取上游视频的最后一帧当图（下一镜首帧接上一镜结尾，首尾呼应）
 *   one_take   几张分镜图按 segments 钉在一次 LTX 生成里各自的起点（一次成片）
 */
export type RecipeOp = "image" | "video" | "sheet" | "prop_sheet" | "concat" | "last_frame" | "one_take";

export interface RecipeRef {
  /** 画布节点 id：执行时取它当前的 media（sheet 节点展开成关键面板；分组展开成组里的图） */
  node: string;
  role: RefRole;
  /** 引用的是标准定妆照节点里的某一格（body_front / body_side / body_back / face_front …）；不给 = 按角色自动挑 */
  panel?: string | null;
}

export interface Recipe {
  op: RecipeOp;
  /** 提示词：文字片段 + @引用 chip（chip 只是标签，真正的参考在 refs 里） */
  prompt: PromptSeg[];
  refs: RecipeRef[];
  /** 不给 = 按 op 用本机默认模型 */
  model?: string | null;
  endpoint_id?: string | null;
  aspect_ratio?: string | null;
  resolution?: string | null;
  /** 显式像素，优先于 aspect_ratio/resolution */
  width?: number | null;
  height?: number | null;
  duration_ms?: number | null;
  seed?: number | null;
  /** 出几张/条：第一张填进本节点，其余在旁边长兄弟节点 */
  count?: number | null;
  /** 视频：环境声/音效描述（LTX 2.5 自带同步音轨） */
  audio?: string | null;
  /** op=sheet：standard = 16 格标准设定图；quick = 三视图 + 正脸；prop = 道具展台 */
  sheet?: { preset: "standard" | "quick" | "prop"; name?: string | null; look?: string | null } | null;
  /** op=one_take：各分镜钉在第几毫秒，和这一段的动作描述 */
  segments?: { node: string; at_ms: number; motion: string }[] | null;
}

/** 执行器里一个节点最近一次运行（GET /studio/canvases/{id}/node-runs） */
export interface NodeRun {
  id: string;
  node_id: string;
  status: "queued" | "waiting" | "running" | "succeeded" | "failed" | "cancelled" | "skipped";
  op: RecipeOp;
  /** 0–100 */
  progress: number | null;
  /** 给人看的当前步骤：「三视图 2/3」「等上游：分镜 1」 */
  step: string | null;
  error: string | null;
  /** 主产物（填进节点 media） */
  media: MediaRef | null;
  /** count>1 的其余产物、sheet 的各面板 */
  extra: { label: string; media: MediaRef }[];
  /** 跑的是哪一版配方（配方改了就该重跑） */
  recipe_hash: string | null;
  updated_at: string | null;
}

export interface ExecuteOptions {
  /** 只跑这些节点；不给 = 整张画布里有配方、还没出过（或配方改过）的 */
  node_ids?: string[] | null;
  /** 连同下游一起（改了上游后重跑） */
  downstream?: boolean;
  /** 已经出过也重跑 */
  force?: boolean;
}

export interface ExecuteState {
  board_id: string;
  status: "idle" | "queued" | "running" | "succeeded" | "failed" | "cancelled";
  /** 还没跑的节点 id，按执行顺序 */
  queued: string[];
  running: string | null;
  done: number;
  failed: number;
  total: number;
  error: string | null;
}

/** 想法 → 导演分镜（POST /studio/film-plans，本机 LLM） */
export interface FilmPlan {
  title: string;
  scene: string;
  look: string;
  audio: string;
  shots: {
    size: string; angle?: string; camera_move?: string; transition?: "cut" | "continuation";
    first_frame: string; motion: string; seconds: number;
  }[];
}

/** 画布首页的一行（GET /studio/canvases） */
export interface CanvasCard extends CanvasMeta {
  /** 封面：文档里第一张有图的节点 */
  cover: string | null;
  nodes: number;
  novel_title: string | null;
  chapter_title: string | null;
}

export interface ScreenplayExpandIn {
  idea: string;
  genre?: string;
  background?: string[];
  characters?: string[];
  highlights?: string[];
  style?: string;
  episodes?: number;
  structure?: string;
  mode?: "domestic" | "faithful_export" | "world_adaptation";
  target_world?: string;
}

export interface ScreenplayResult {
  title: string;
  logline: string;
  genre?: string;
  episodes?: number;
  structure?: string;
  mode: "domestic" | "faithful_export" | "world_adaptation";
  core_conflict?: string;
  cultural_notes?: string;
  target_world?: string;
  target_world_info?: {
    code: string;
    name: string;
    description: string;
  };
  worldview_mapping?: {
    concept_mappings?: { original_cn: string; adapted_target: string; rationale?: string }[];
    character_mappings?: { original_cn: string; adapted_name: string; identity?: string; rationale?: string }[];
    setting_mappings?: string;
  };
  episodes_outline: { episode: string; title: string; summary: string }[];
  sample_scene: {
    scene_heading: string;
    description: string;
    beats: { type: "action" | "dialogue"; speaker?: string; content: string }[];
  };
  visual_prompt?: string;
  model_used?: string;
}
