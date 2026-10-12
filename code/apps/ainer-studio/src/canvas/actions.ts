/**
 * 节点工具条的动作：文字 / 图片 / 视频节点在这里，白模节点交给 three/actions.ts 的 box3dActions。
 * 另外放了外壳几个组件（工具条、Dock、新增菜单、资产抽屉）共用的小函数：
 * 现取节点的文字和媒体、推断连线语义、在节点旁边找空位、镜头出片。
 *
 * 原则（规格 §1）：
 *   - 后端没有的能力照样列出来，但 disabled 写明原因（铁律 3），不假装能用；
 *   - 角色/定妆照只读，「造型室」跳角色库（铁律 4）；
 *   - 长任务只 s.track 登记，由 store 里唯一的轮询器推进（铁律 6）。
 */
import { prod } from "../production/api";
import { navigate } from "../ctx";
import type { XYPosition } from "@xyflow/react";
import type { CastMember, ShotCard } from "../types";
import { directorPending } from "../shotStatus";
import { errText } from "./chrome/Overlays";
import { segsToPrompt } from "./chrome/PromptEditor";
import { cv, media } from "./api";
import type { CanvasStore } from "./contract";
import {
  isDerived, isProductionRef, type CanvasAction, type CNode, type EdgeKind, type NodeKind, type NodeRef, type NodeRun, type PromptSeg,
  type Recipe, type RecipeOp, type RecipeRef, type RefRole, type Resolved, type ScriptScene, type TrackedTask,
} from "./model";
import { edgeKindOfRole } from "./idea/buildIdeaGraph";
import { addCharacterToBox, box3dActions, buildBoxFromText } from "./three/actions";

/** 工具条上只画图标、排在分隔线后面的动作（复制、下载、全屏、删除）。白模的动作想放到末尾也用这几个 id。 */
export const ICON_ONLY: ReadonlySet<string> = new Set(["duplicate", "download", "fullscreen", "remove"]);

/* ───────────────────────── 通用小工具 ───────────────────────── */

export const GLYPH: Record<NodeKind, string> = { stage: "台", coverage: "镜", text: "文", image: "图", video: "影", audio: "音", box3d: "3D", group: "组" };

/** 新节点的默认尺寸（还没被 xyflow 量过时用来找空位） */
const DEFAULT_SIZE: Record<NodeKind, { w: number; h: number }> = {
  text: { w: 260, h: 160 },
  image: { w: 220, h: 220 },
  video: { w: 280, h: 200 },
  audio: { w: 300, h: 110 },
  stage: { w: 300, h: 300 }, coverage: { w: 300, h: 300 }, box3d: { w: 300, h: 230 },
  group: { w: 520, h: 360 },
};

export function nodeSize(n: { type?: NodeKind; measured?: { width?: number; height?: number }; width?: number; height?: number }) {
  const d = DEFAULT_SIZE[n.type ?? "text"];
  return { w: n.measured?.width ?? n.width ?? d.w, h: n.measured?.height ?? n.height ?? d.h };
}

/** 自由节点的 id：nodeIdOf(free) 就是它自己 */
export function freeRef(): NodeRef {
  return { kind: "free", id: `n_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}` };
}

export const taskOpen = (t: TrackedTask) => t.status === "queued" || t.status === "running";

/**
 * 两端节点 → 连线语义。与 store.onConnect 同一套规则（规格 §5.1）：
 * 新增菜单 / 「＋参考」/ 上传 这些不经过拖线的入口也要得到同样的边。
 */
export function inferEdgeKind(
  src: { type?: NodeKind; role?: string | null },
  tgt: { type?: NodeKind; role?: string | null },
): EdgeKind {
  const toMovie = tgt.type === "video" || tgt.type === "box3d";
  if (src.type === "image" && toMovie && ["character", "sheet", "view", "upload", "generated"].includes(src.role ?? "")) return "identity";
  if (tgt.type === "video" && (src.type === "box3d" || (src.type === "video" && (src.role === "previs" || src.role === "control")))) return "control";
  return "ref";
}

/**
 * 在 anchor 左侧或右侧竖着找 count 个空位（避开已有节点的包围盒，含上方小标题那 26px）。
 * store.addNode 自己也会找空位，但连续 addNode 时它看不到同一批刚加的节点，所以批量放置在这里算好。
 */
export function placeBeside(
  nodes: CNode[], anchor: CNode, side: "left" | "right", size: { w: number; h: number }, count = 1, gap = 110,
): XYPosition[] {
  const a = nodeSize(anchor);
  const x = side === "right" ? anchor.position.x + a.w + gap : anchor.position.x - size.w - gap;
  const head = 26;
  const boxes = nodes.filter(n => n.id !== anchor.id).map(n => {
    const z = nodeSize(n);
    return { x: n.position.x, y: n.position.y - head, w: z.w, h: z.h + head };
  });
  const hit = (b: { x: number; y: number; w: number; h: number }, y: number) =>
    x < b.x + b.w + 24 && x + size.w + 24 > b.x && y - head < b.y + b.h + 24 && y + size.h + 24 > b.y;
  const out: XYPosition[] = [];
  let y = anchor.position.y;
  for (let i = 0; i < count; i++) {
    for (let guard = 0; guard < 400 && boxes.some(b => hit(b, y)); guard++) y += 40;
    out.push({ x, y });
    boxes.push({ x, y: y - head, w: size.w, h: size.h + head });
    y += size.h + head + 40;
  }
  return out;
}

/** 生成产物占位卡的大致尺寸（按画幅；只用于找空位） */
export function productSize(type: "image" | "video", aspect: string): { w: number; h: number } {
  const [a, b] = aspect.split(":").map(Number);
  const r = a && b ? a / b : 16 / 9;
  if (type === "video") return { w: 280, h: Math.round(280 / r) + 44 };
  return { w: 220, h: Math.round(Math.min(220 / r, 220 * 4 / 3)) };
}

export function downloadUrl(url: string, title: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = `${title.replace(/[\\/:*?"<>|]+/g, "_") || "media"}.${extOf(url)}`;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function extOf(url: string): string {
  const data = /^data:([a-z]+)\/([a-z0-9.+-]+)/i.exec(url);
  if (data) return data[2] === "svg+xml" ? "svg" : data[2] === "jpeg" ? "jpg" : data[2];
  const m = /\.([a-z0-9]{2,5})$/i.exec(url.split(/[?#]/)[0]);
  return m ? m[1] : "bin";
}

/* ───────────────────────── 现取：文字 / 缩略图 / 媒体 ───────────────────────── */

const BLOCK_TAG: Record<string, string> = {
  action: "【画面】", narration: "【旁白】", inner_monolog: "【独白】", signage: "【字幕】",
};

/** 场次全文（给「搭白模」的智能体、搜索、复制用；格式同 TextNode 的显示） */
export function sceneText(sc: ScriptScene): string {
  const head = [sc.title, sc.time_of_day, sc.location_text].filter(Boolean).join("－");
  const lines = [`场景 ${sc.order_no}${head ? `：${head}` : ""}`];
  for (const b of sc.blocks) {
    if (b.type === "heading" || b.type === "scene_break" || !b.text?.trim()) continue;
    if (b.type === "dialogue") lines.push(`【对白】${b.speaker ? `${b.speaker}：` : ""}${b.text}`);
    else lines.push(`${BLOCK_TAG[b.type] ?? ""}${b.text}`);
  }
  if (lines.length === 1 && sc.summary) lines.push(sc.summary);
  return lines.join("\n");
}

/** 节点现取的文字（文字节点的正文、镜头描述）；没有就空串 */
export function resolvedText(r: Resolved): string {
  switch (r.kind) {
    case "story": return [r.title, r.text].filter(Boolean).join("\n");
    case "scene": return sceneText(r.scene);
    case "text": return r.text;
    case "shot": return r.shot.description ?? "";
    case "entity_view": return r.member.name;
    case "box_project": return r.box.title;
    default: return "";
  }
}

/** 缩略图：img/video 地址都过了 media()（铁律 2） */
export function thumbOf(node: CNode, r: Resolved): { img?: string; video?: string; glyph: string } {
  const glyph = GLYPH[node.type ?? "text"];
  switch (r.kind) {
    case "entity_view": return { img: media(r.url), glyph };
    case "media": {
      const isImg = r.media.mime ? r.media.mime.startsWith("image/") : node.type !== "video";
      return isImg ? { img: media(r.media.url), glyph } : { video: media(r.media.url), glyph };
    }
    case "shot":
      if (r.shot.first?.url) return { img: media(r.shot.first.url), glyph };
      if (r.shot.video_url) return { video: media(r.shot.video_url), glyph };
      return { glyph };
    case "box_project": return { img: media(r.box.thumb_url), glyph };
    default: return { glyph };
  }
}

/** 某节点能当生成参考的媒体；当不了就给原因（显示成 ⚠，不发） */
export type RefMedia =
  | { url: string; kind: "image" | "video"; asset_id?: string | null; mime?: string | null }
  | { warn: string };

export function refMediaOf(node: CNode, r: Resolved, s: CanvasStore): RefMedia {
  if (node.type === "audio") return { warn: "此生成入口尚未支持音频参考，音频节点可播放与编排" };
  if (node.type === "text") return { warn: "文字参考只以「标题」拼进提示词，不当参考图发；要用它的内容请写进提示词" };
  if (node.type === "box3d") {
    // 优先取白模下游最近录好的预演或渲染素材
    const p = s.downstream(node.id).map(d => d.node)
      .filter(n => n.data.role === "previs" && n.data.media?.url).pop();
    if (p?.data.media) {
      const m = p.data.media;
      return { url: media(m.url)!, kind: m.mime?.startsWith("image/") ? "image" : "video", asset_id: m.asset_id, mime: m.mime };
    }
    if (r.kind === "box_project" && r.box?.thumb_url) {
      return { url: media(r.box.thumb_url)!, kind: "image" };
    }
    return { warn: "白模还没保存缩略图或预演，先在 3D-BOX 中保存" };
  }
  const g = node.data.gen;
  if (g && g.status !== "succeeded" && !node.data.media) {
    return { warn: g.status === "failed" || g.status === "cancelled" ? "这一张没生成出来" : "还在生成，出完才能当参考" };
  }
  switch (r.kind) {
    case "entity_view":
      return r.url ? { url: media(r.url)!, kind: "image" } : { warn: "这个视角还没有图" };
    case "media": {
      const m = r.media;
      const kind = m.mime?.startsWith("video/") ? "video" : m.mime?.startsWith("image/") ? "image"
        : node.type === "video" ? "video" : "image";
      return { url: media(m.url)!, kind, asset_id: m.asset_id, mime: m.mime };
    }
    case "shot":
      if (r.shot.video_url) return { url: media(r.shot.video_url)!, kind: "video" };
      if (r.shot.first?.url) return { url: media(r.shot.first.url)!, kind: "image" };
      return { warn: "这一镜还没出片，也没有首帧" };
    case "missing":
      return { warn: "真身找不到了（分镜重编译后的旧节点）" };
    default:
      return { warn: "这个节点还没有内容" };
  }
}

/* ───────────────────────── 新建生成节点 ───────────────────────── */

/**
 * 「生成」：在右边新建一个空的生成节点（纳逗式自动命名「图片 N / 视频 N」），连上 from 当参考；
 * addNode 会选中它，Dock 随即出现配方编辑器（默认配方按这条连线把 from 排进参考）。
 */
export function spawnGen(s: CanvasStore, from: CNode, type: "image" | "video"): string {
  const kind = inferEdgeKind({ type: from.type, role: from.data.role }, { type, role: "generated" });
  return s.addNode(type, { ref: freeRef(), title: s.nextTitle(type), role: "generated" },
    undefined, { source: from.id, kind });
}

function genAction(s: CanvasStore, node: CNode): CanvasAction {
  if (isEmptyGen(node, s)) {
    return {
      id: "gen", label: "生成", icon: "✦",
      disabled: "这个节点还是空的：先在下面的生成面板发送，出了图再接着生成（误加的话直接删掉）",
    };
  }
  return {
    id: "gen", label: "生成", icon: "✦",
    title: "在右边新建一个生成节点，把这个节点连过去当参考",
    menu: [
      { id: "gen_video", label: "视频生成", icon: "影", run: () => { spawnGen(s, node, "video"); } },
      { id: "gen_image", label: "图片生成", icon: "图", run: () => { spawnGen(s, node, "image"); } },
    ],
  };
}

/* ───────────────────────── 镜头出片（工具条和 Dock 共用） ───────────────────────── */

/** 这一镜在不在正跑的整板出片里（关键帧 / 视频还没走完） */
export function inBoardRun(s: Pick<CanvasStore, "run">, shotId: string): boolean {
  const st = s.run;
  if (!st || (st.status !== "queued" && st.status !== "running")) return false;
  return st.items.some(i => i.shot_id === shotId && (i.status === "pending" || i.status === "running"));
}

/** 这一镜是不是正在出片（导演链没跑完、文字出片在等、首帧在生成、整板出片轮到它） */
export function shotBusy(s: CanvasStore, nodeId: string, shot: ShotCard): boolean {
  const run = s.live.runs[shot.id];
  const director = run ? !run.done && run.status !== "failed" && run.status !== "cancelled" : directorPending(shot);
  return director
    || inBoardRun(s, shot.id)
    || shot.first?.status === "generating"
    || s.tasks.some(t => t.nodeId === nodeId && (t.kind === "director" || t.kind === "ltx25") && taskOpen(t));
}

async function runDirector(s: CanvasStore, node: CNode, shot: ShotCard, sceneId?: string) {
  await cv.directorShot(shot.id, sceneId);
  s.track({
    key: `director:${shot.id}`, kind: "director", remote: shot.id, nodeId: node.id,
    label: `${node.data.title} · ${sceneId ? "按白模重出" : "3D 导演出片"}`,
  });
  s.toast(sceneId ? "已提交：按白模重出" : "已提交 3D 导演出片，一镜约 8 分钟", "ok");
  // board 里的 director.run 要刷出来，镜头卡片才会显示「出片中」
  void s.reloadLive();
}

async function runText(s: CanvasStore, node: CNode, shot: ShotCard, quality: "preview" | "final", label: string) {
  await cv.textVideo(s.planId, shot.id, quality);
  s.track({
    key: `ltx25:${shot.id}`, kind: "ltx25", remote: shot.id, nodeId: node.id,
    label: `${node.data.title} · ${label}`, baseline: shot.video_url,
  });
  s.toast(`已提交${label}`, "ok");
}

/** 只给这几镜出分镜图（关键帧，stop_after=frame）：多选工具条、右键菜单、单镜出片共用 */
export async function startFrames(s: CanvasStore, shots: string[]) {
  try {
    const st = await s.startRun({
      method: "keyframe", engine: "local", profile: "fast", audio: "auto", only_missing: false,
      reuse_scene: true, reuse_frames: false, stop_after: "frame", shot_ids: shots,
    });
    s.toast(`这 ${st.summary.total} 镜开始出分镜图（关键帧），出完在画布上审，再出视频`, "ok");
  } catch (e) {
    s.toast(`没开始：${e instanceof Error ? e.message : String(e)}`, "err");
  }
}

/** 用分镜图出视频（没有分镜图就先画）：LTX 2.5 本机 768×448、带声 */
async function keyframeVideo(s: CanvasStore, shotId: string, hasFrame: boolean) {
  await s.startRun({
    method: "keyframe", engine: "local", profile: "fast", audio: "auto", only_missing: false,
    reuse_scene: true, reuse_frames: true, stop_after: "video", shot_ids: [shotId],
  });
  s.toast(hasFrame ? "已提交：用这一镜的分镜图出视频（768×448 带声）" : "已提交：先画分镜图再出视频", "ok");
}

/** 镜头的出片方式：分镜图（关键帧）方案在前，是默认；3D 导演 / 文字出片作备选 */
export function shotMethods(s: CanvasStore, node: CNode, shot: ShotCard): CanvasAction[] {
  const busy = shotBusy(s, node.id, shot) ? "这一镜正在出片，等它跑完" : false;
  const sceneId = shot.director?.run?.scene_id;
  const noBoard = s.boardId ? false : "画布还没存成板，刷新一下再试";
  const hasFrame = !!shot.first?.url;
  return [
    {
      id: "keyframe", label: hasFrame ? "重画分镜图" : "出分镜图", icon: "▣",
      title: "本章定妆照（人物卡）＋场景图 → FLUX 本机画关键帧，约 1–2 分钟；画完挂成这一镜的首帧，审过再出视频",
      disabled: busy || noBoard, run: () => startFrames(s, [shot.id]),
    },
    {
      id: "keyframe_video", label: hasFrame ? "分镜图出片" : "画图并出片", icon: "▶",
      title: hasFrame
        ? "钉住这一镜的分镜图当首帧 → LTX 2.5 本机 768×448 带声出片（有对白先配音再驱动口型）"
        : "先画分镜图（定妆照＋场景图），再用它当首帧 → LTX 2.5 本机 768×448 带声出片",
      disabled: busy || noBoard, run: () => keyframeVideo(s, shot.id, hasFrame),
    },
    {
      id: "director", label: "3D 导演出片", icon: "◰",
      title: "LLM 按这一镜搭 3D 白模 → Blender 预演 → 身份首帧（角色库的脸）→ LTX 2.5 成片，约 8 分钟；出完自动挂回这一镜",
      disabled: busy, run: () => runDirector(s, node, shot),
    },
    {
      id: "director_rerun", label: "按白模重出", icon: "↻",
      title: "用 3D-BOX 里调过的这一镜白模重出（不重新搭景、不换机位）",
      disabled: busy || (sceneId ? false : "这一镜还没走过 3D 导演出片，没有可重出的白模"),
      run: () => runDirector(s, node, shot, sceneId ?? undefined),
    },
    {
      id: "text_preview", label: "文字预览", icon: "◔",
      title: "LTX 2.5 按镜头描述先出一版快速预览（不搭景）",
      disabled: busy, run: () => runText(s, node, shot, "preview", "文字预览"),
    },
    {
      id: "text_final", label: "文字出片", icon: "影",
      title: "LTX 2.5 按镜头描述直接出成片（不搭景；有对白按配音驱动口型）",
      disabled: busy, run: () => runText(s, node, shot, "final", "文字出片"),
    },
  ];
}

/* ───────────────────────── 生成配方（纳逗式：节点带配方，服务端执行器按配方跑） ───────────────────────── */

export const OP_LABEL: Record<RecipeOp, string> = {
  image: "图片生成", video: "视频生成", sheet: "标准定妆照", prop_sheet: "道具定妆照", concat: "视频拼接", last_frame: "取尾帧", one_take: "一次成片",
};

/** 标准定妆照的 16 格与道具 4 角度（键和后端 char_sheet.ALL_LABELS 对齐；执行器 NodeRun.extra[].label 用的是键） */
export const PANEL_LABEL: Record<string, string> = {
  body_front: "前视图", body_back: "后视图", body_side: "侧视图",
  face_front: "正面特写", face_left: "左侧特写", face_right: "右侧特写", face_back: "后脑特写",
  expr_joy: "喜", expr_anger: "怒", expr_sorrow: "哀", expr_happy: "乐", expr_surprise: "惊", expr_fear: "恐",
  expr_think: "思", expr_disgust: "厌", expr_doubt: "疑",
  prop_front: "正立面主视图", prop_side: "侧方位透视", prop_iso: "45°立体全貌", prop_macro: "材质与细节特写",
};
/** 拼版的三个分区（和参考图一致：全景三视图 / 面部多视角 / 九宫格表情） */
export const PANEL_GROUPS: { title: string; keys: string[] }[] = [
  { title: "全景三视图", keys: ["body_front", "body_back", "body_side"] },
  { title: "面部多视角", keys: ["face_front", "face_left", "face_right", "face_back"] },
  {
    title: "九宫格表情",
    keys: ["expr_joy", "expr_anger", "expr_sorrow", "expr_happy", "expr_surprise", "expr_fear", "expr_think", "expr_disgust", "expr_doubt"],
  },
];

export const RUN_STATUS_ZH: Record<NodeRun["status"], string> = {
  queued: "排队中", waiting: "等上游", running: "生成中", succeeded: "已完成", failed: "失败", cancelled: "已停止", skipped: "跳过",
};

/** 执行器里这个节点还没跑完（排队、等上游、在跑） */
export const runBusy = (run: NodeRun | null | undefined): boolean =>
  !!run && (run.status === "queued" || run.status === "waiting" || run.status === "running");

/**
 * 执行器能不能直接拿它当参考：自由节点、上传素材、带 /media 的导演产物、分组（展开成组里的图）可以；
 * 定妆照（角色库现取）、镜头这类派生节点本轮执行器读不到 —— 用之前先复制成静态图（refableId）。
 */
export function execRefable(n: CNode): boolean {
  if (n.type === "box3d") return false;
  const k = n.data.ref.kind;
  return k === "free" || k === "asset" || (k === "director_output" && !!n.data.media?.url);
}

/**
 * Dock 用配方编辑器接管哪些节点：带配方的；或者自由的生成节点（生成 / 分镜 / 定妆照角色，或还没有媒体的图、视频）。
 * 上传的素材（有图、没配方）仍走原来的「自由生成」（以它为参考往外长新节点）；镜头、白模、角色视角不归这里。
 */
export function wantsRecipe(n: CNode): boolean {
  if (n.type !== "image" && n.type !== "video") return false;
  if (n.data.recipe) return true;
  if (n.data.ref.kind !== "free") return false;
  const role = n.data.role;
  return role === "generated" || role === "frame" || role === "sheet" || !n.data.media;
}

const IDENTITY_LIKE = new Set(["character", "sheet", "view"]);
const looksLikeIdentity = (n: CNode) => n.data.recipe?.op === "sheet" || IDENTITY_LIKE.has(n.data.role ?? "");

/**
 * 新加一个参考时默认当什么用（单张可以在参考行里改）：
 *   出图  定妆照类 → 身份；第一张别的图 → 底图（走图像编辑）；再往后 → 参考
 *   出视频 第一张图 → 首帧；定妆照类 → 身份；其余 → 参考
 *   定妆照 第一张图 → 底图（人物照片）；一次成片 → 首帧；拼接 / 取尾帧 → 参考
 * edge 给了（从连线推默认配方时）按连线语义优先。
 */
export function defaultRoleFor(op: RecipeOp, n: CNode, existing: RecipeRef[], edge?: EdgeKind | null): RefRole {
  const has = (r: RefRole) => existing.some(x => x.role === r);
  if (n.type === "video" || op === "concat" || op === "last_frame") return "reference";
  if (op === "one_take") return "first_frame";
  if (op === "sheet") return has("base") ? "reference" : "base";
  if (edge === "identity") return "character";
  if (edge === "style") return "style";
  if (op === "video") {
    if (edge === "control" && !has("first_frame")) return "first_frame";
    if (looksLikeIdentity(n)) return "character";
    return has("first_frame") ? "reference" : "first_frame";
  }
  if (edge === "control" && !has("base")) return "base";
  if (looksLikeIdentity(n)) return "character";
  return has("base") ? "reference" : "base";
}

/**
 * 没有配方的节点第一次编辑时给的默认配方：图片节点 → 出图、视频节点 → 出视频；
 * 连进来的图、视频、分组按连线语义排进参考（执行器读不了的派生节点先不排，参考行里灰着、点一下转成静态图再加）。
 * 提示词：老的自由生成节点把发过的提示词留在 gen.prompt 里，接着用；从文字节点「生成」出来的拿那段文字当起点。
 */
export function defaultRecipe(node: CNode, s: CanvasStore): Recipe {
  const op: RecipeOp = node.type === "video" ? "video" : "image";
  const refs: RecipeRef[] = [];
  const up = s.upstream(node.id);
  for (const { node: u, edge } of up) {
    if (u.type !== "image" && u.type !== "video" && u.type !== "group") continue;
    if (!execRefable(u) || refs.some(r => r.node === u.id)) continue;
    refs.push({ node: u.id, role: defaultRoleFor(op, u, refs, edge.data?.kind ?? null) });
  }
  let prompt: PromptSeg[] = [];
  const old = node.data.gen?.prompt?.trim();
  if (old) prompt = [{ t: "text", text: old }];
  else {
    const t = up.filter(u => u.node.type === "text").map(u => resolvedText(s.resolve(u.node.data.ref, u.node.data)).trim())
      .filter(Boolean).join("\n");
    if (t) prompt = [{ t: "text", text: t }];
  }
  // 默认本机最快的一档：分镜图 800×480、视频 768×448 带声（执行器按所选模型的尺寸再夹一次）
  return op === "video"
    ? { op, prompt, refs, width: 768, height: 448, duration_ms: 4000, count: 1 }
    : { op, prompt, refs, width: 800, height: 480, count: 1 };
}

/** 引用了 id 的配方节点（直接下游）；transitive=true 连下游的下游一起（防成环、算「连下游重跑」的规模） */
export function recipeDependents(nodes: CNode[], id: string, transitive = false): CNode[] {
  const out: CNode[] = [];
  const seen = new Set<string>([id]);
  let frontier = [id];
  while (frontier.length) {
    const next: string[] = [];
    for (const n of nodes) {
      if (seen.has(n.id) || !n.data.recipe?.refs.some(r => frontier.includes(r.node))) continue;
      seen.add(n.id);
      out.push(n);
      next.push(n.id);
    }
    frontier = transitive ? next : [];
  }
  return out;
}

/** 让配方引用和连线保持一致：线的语义跟着参考的角色走（身份 / 首帧 / 风格 / 参考） */
export function syncRefEdge(s: CanvasStore, source: string, target: string, role: RefRole, op?: RecipeOp) {
  const kind = edgeKindOfRole(role, op);
  const e = s.edges.find(x => x.source === source && x.target === target);
  if (e?.data?.kind === kind || e?.data?.derived) return;
  if (e) s.onEdgesChange([{ type: "remove", id: e.id }]);
  s.connect(source, target, kind);
}

/**
 * 让一个节点能进配方参考：执行器读得到的直接返回它；定妆照（角色库）、镜头这类派生节点先复制成一张静态图
 * （store.duplicate 取现取的地址当 media），返回副本 id。复制会选中副本，这里再选回 keep，Dock 不跳走。
 */
export function refableId(s: CanvasStore, n: CNode, keep: string): string | null {
  if (execRefable(n)) return n.id;
  if (n.type !== "image" && n.type !== "video") return null;
  const [copy] = s.duplicate([n.id]);
  if (!copy) return null;
  s.select(keep);
  s.toast(`「${n.data.title}」是从后端现取的，执行器还读不到它：已复制成一张静态图接上`, "info");
  return copy;
}

/** 当前（最新）的节点：动作闭包里拿着的 node 可能是几次渲染前的 */
const fresh = (s: CanvasStore, n: CNode) => s.nodes.find(x => x.id === n.id) ?? n;

/** 按配方在服务端（重新）出这个节点；downstream = 连同引用它的节点按依赖顺序一起重跑 */
export async function runRecipe(s: CanvasStore, node: CNode, opts: { downstream?: boolean; recipe?: Recipe } = {}) {
  const n = fresh(s, node);
  const recipe = opts.recipe ?? n.data.recipe ?? defaultRecipe(n, s);
  // 执行器读的是库里的文档：配方先写回节点，store.execute 会先存盘再提交
  if (recipe !== n.data.recipe) s.updateNodeData(n.id, { recipe });
  await s.execute({ node_ids: [n.id], force: true, downstream: !!opts.downstream });
  const down = opts.downstream ? recipeDependents(s.nodes, n.id, true).length : 0;
  s.toast(down ? `「${n.data.title}」和下游 ${down} 个节点按顺序重跑` : `「${n.data.title}」已交给执行器`, "ok");
}

/** 历史里换回一版：和当前 media 互换（不跑任务） */
export function swapHistory(s: CanvasStore, nodeId: string, index: number) {
  const n = s.nodes.find(x => x.id === nodeId);
  const hist = n?.data.history ?? [];
  const pick = hist[index];
  if (!n || !pick) return;
  const rest = hist.filter((_, i) => i !== index);
  const cur = n.data.media;
  s.updateNodeData(nodeId, { media: pick, history: (cur?.url ? [cur, ...rest] : rest).slice(0, 12), gen: null });
  s.toast("已换回这一版（原来那版进了历史）", "ok");
}

/** 标题不重名：「定妆照」「定妆照 2」…（@引用的 chip 按标题显示，重名分不清） */
export function uniqueTitle(s: CanvasStore, base: string): string {
  const have = new Set(s.nodes.map(n => n.data.title));
  if (!have.has(base)) return base;
  for (let i = 2; ; i++) if (!have.has(`${base} ${i}`)) return `${base} ${i}`;
}

/**
 * 「标准定妆照」：在右边新建一个 op=sheet 的节点（全身三视图 + 面部四角度 + 九宫格表情，拼成一张），
 * 以这张图为底图、连身份线，马上交给执行器。角色库的定妆照（派生）先复制成静态图再用。
 */
export async function spawnSheet(s: CanvasStore, node: CNode, preset: "standard" | "quick" | "prop" = "standard") {
  const r = s.resolve(node.data.ref, node.data);
  const name = r.kind === "entity_view" ? r.member.name : (node.data.title || null);
  const srcId = refableId(s, node, node.id);
  if (!srcId) return;
  const src = s.nodes.find(n => n.id === srcId) ?? node;
  const at = placeBeside(s.nodes, src, "right", { w: 300, h: 170 })[0];
  const isProp = preset === "prop" || node.data.role === "prop";
  const finalPreset = isProp ? "prop" : preset;
  const title = uniqueTitle(s, isProp ? (name ? `道具定妆照 · ${name}` : "道具定妆照") : (name ? `定妆照 · ${name}` : "定妆照"));
  const id = s.addNode("image", {
    ref: freeRef(), title, role: isProp ? "prop_sheet" : "sheet",
    recipe: { op: "sheet", prompt: [], refs: [{ node: srcId, role: "base" }], sheet: { preset: finalPreset, name, look: null } },
  }, at, { source: srcId, kind: edgeKindOfRole("base", isProp ? "prop_sheet" : "sheet") });
  await s.execute({ node_ids: [id] });
  s.toast(finalPreset === "prop"
    ? "道具定妆照开始出：正立面主视图 → 侧方位透视 → 45°立体全貌 → 材质与工艺特写（约 1 分钟）"
    : finalPreset === "standard"
    ? "标准定妆照开始出：全身三视图 → 面部四角度 → 九宫格表情，再拼成一张（本机约 5 分钟）"
    : "快速定妆照开始出：全身前 / 侧 / 后 + 正脸（本机约 1 分钟）", "ok");
}

function sheetAction(s: CanvasStore, node: CNode, url: string | undefined, why: string, label = "定妆照"): CanvasAction {
  const isProp = node.data.role === "prop";
  return {
    id: "sheet", label: isProp ? "道具定妆照" : label, icon: isProp ? "🗡️" : "▦", badge: "NEW",
    title: isProp ? "用这张道具照生成多角度展台定妆照（正立面、侧方位、45°全貌、材质微距）" : "生成角色/道具定妆照，供下游分镜与视频引用",
    disabled: !url ? why : s.demo ? "演示数据不能在服务端执行（要连上后端）" : false,
    menu: [
      {
        id: "sheet_standard", label: "标准角色定妆照（16格）", icon: "👤",
        title: "全身三视图 + 面部四角度 + 九宫格表情（约 5 分钟）",
        run: () => spawnSheet(s, node, "standard"),
      },
      {
        id: "sheet_quick", label: "快速角色定妆照（4格）", icon: "⚡",
        title: "全身前/侧/后 + 正脸特写（约 1 分钟）",
        run: () => spawnSheet(s, node, "quick"),
      },
      {
        id: "sheet_prop", label: "多角度道具定妆照（4展台）", icon: "🗡️",
        title: "正立面主视图 + 侧方位 + 45°立体全貌 + 材质微距特写（约 1 分钟）",
        run: () => spawnSheet(s, node, "prop"),
      },
    ],
    run: () => spawnSheet(s, node, isProp ? "prop" : "standard"),
  };
}

/** 带配方的节点：生成 / 重新生成、连下游重跑、历史 */
function recipeActions(s: CanvasStore, node: CNode): CanvasAction[] {
  const run = s.nodeRuns[node.id];
  const off = s.demo ? "演示数据不能在服务端执行（要连上后端）"
    : runBusy(run) ? `正在跑：${run!.step || RUN_STATUS_ZH[run!.status]}` : false;
  const has = !!node.data.media?.url;
  const down = recipeDependents(s.nodes, node.id, true).length;
  const out: CanvasAction[] = [{
    id: "rerun", label: has ? "重新生成" : "生成", icon: has ? "↻" : "✦",
    title: has ? "按配方重跑，新结果换进这个节点（旧的进历史，可以换回）" : "按配方在服务端出（关了浏览器也照跑）",
    disabled: off, run: () => runRecipe(s, node),
  }];
  if (down) {
    out.push({
      id: "rerun_down", label: "连下游重跑", icon: "⇉",
      title: `这个节点和引用它的 ${down} 个节点按依赖顺序一起重跑（改了上游之后用）`,
      disabled: off, run: () => runRecipe(s, node, { downstream: true }),
    });
  }
  const hist = node.data.history ?? [];
  if (hist.length) {
    out.push({
      id: "history", label: `历史 ${hist.length}`, icon: "◷", title: "之前生成过的结果：换回某一版（不跑任务）",
      menu: hist.map((h, i) => ({
        id: `history:${i}`, label: i === 0 ? "换回上一版" : `换回第 ${i + 1} 版`, icon: "↶", title: h.url,
        run: () => swapHistory(s, node.id, i),
      })),
    });
  }
  return out;
}

/** 分组：解散、组内重跑 */
function groupActions(s: CanvasStore, node: CNode): CanvasAction[] {
  const runnable = s.nodes.filter(n => n.parentId === node.id && n.data.recipe);
  return [
    {
      id: "rerun_group", label: runnable.length ? `组内重跑 ${runnable.length}` : "组内重跑", icon: "↻",
      title: "组里带配方的节点按依赖顺序重新生成",
      disabled: !runnable.length ? "组里没有带配方的节点" : s.demo ? "演示数据不能在服务端执行（要连上后端）" : false,
      run: async () => {
        await s.execute({ node_ids: runnable.map(n => n.id), force: true });
        s.toast(`「${node.data.title}」里 ${runnable.length} 个节点开始重跑`, "ok");
      },
    },
    { id: "ungroup", label: "解散分组", icon: "⊟", title: "子节点留在原地（⇧⌘G）", run: () => { s.ungroup(node.id); } },
  ];
}

function duplicateAction(s: CanvasStore, node: CNode): CanvasAction {
  return {
    id: "duplicate", label: "复制", icon: "⧉",
    title: isDerived(node.data.ref)
      ? "复制成一张静态图 / 视频（⌘D）：可以当配方参考、随便改，后端真身不变"
      : "复制节点，连媒体和配方一起（⌘D），标题「… 拷贝1」",
    run: () => { s.duplicate([node.id]); },
  };
}

/**
 * 多选时的动作（编组、复制几个）。NodeActions 的多选工具条和右键菜单的「多选」不在这个文件里，
 * 由它们调这里接上（⌘G / ⌘D 快捷键在 store）。
 */
export function multiActions(s: CanvasStore, nodes: CNode[]): CanvasAction[] {
  const loose = nodes.filter(n => n.type !== "group");
  const copyable = loose.filter(n => n.type !== "box3d");
  return [
    {
      id: "group", label: "编组", icon: "▢", title: "把选中的节点编成一组（⌘G）：整组一起拖；配方里 @分组 = 组里所有图",
      disabled: loose.length ? false : "选中的都是分组", run: () => { s.groupSelected(); },
    },
    {
      id: "duplicate", label: copyable.length > 1 ? `复制 ${copyable.length} 个` : "复制", icon: "⧉", title: "⌘D",
      disabled: copyable.length ? false : "选中的节点不能复制（分组、白模）", run: () => { s.duplicate(copyable.map(n => n.id)); },
    },
  ];
}

/* ───────────────────────── 各类节点的动作 ───────────────────────── */

function mediaTail(s: CanvasStore, title: string, url: string | undefined, video: boolean, why: string): CanvasAction[] {
  return [
    { id: "download", label: "下载", icon: "⬇", disabled: url ? false : why, run: () => { if (url) downloadUrl(url, title); } },
    { id: "fullscreen", label: "全屏", icon: "⛶", disabled: url ? false : why, run: () => { if (url) s.openOverlay({ kind: "media", url, video }); } },
  ];
}

interface ParsedShot {
  shotNo: number;
  size: string;
  cameraMove: string;
  durationSec: number;
  firstFrame: string;
  motion: string;
}

export function parseDirectorShots(text: string): ParsedShot[] {
  const shots: ParsedShot[] = [];
  const regex = /【镜头\s*(\d+)(?:\s*·\s*([^·\n]+))?(?:\s*·\s*([^·\n]+))?(?:\s*·\s*([\d.]+)\s*s)?\s*】([\s\S]*?)(?=(?:【镜头\s*\d+|$))/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    const shotNo = parseInt(match[1], 10);
    const size = (match[2] || "MS").trim();
    const cameraMove = (match[3] || "固定").trim();
    const durationSec = match[4] ? parseFloat(match[4]) : 3;
    const body = match[5] || "";
    const firstMatch = body.match(/首帧[：:]\s*([^\n]+(?:\n[^\n]+)*?)(?=\n动作[：:]|\n\n|$)/);
    const motionMatch = body.match(/动作[：:]\s*([^\n]+(?:\n[^\n]+)*?)(?=\n【|\n\n|$)/);
    shots.push({
      shotNo,
      size,
      cameraMove,
      durationSec,
      firstFrame: (firstMatch ? firstMatch[1] : body).trim(),
      motion: (motionMatch ? motionMatch[1] : body).trim(),
    });
  }
  return shots;
}

export async function orchestrateDirectorShots(s: CanvasStore, node: CNode) {
  const r = s.resolve(node.data.ref, node.data);
  let text = resolvedText(r).trim();
  if (!text) {
    const p = node.data.recipe?.prompt;
    text = (p ? (typeof p === "string" ? p : segsToPrompt(p as PromptSeg[])) : node.data.gen?.prompt || node.data.text || "").trim();
  }
  if (!text) {
    const upText = s.upstream(node.id).find(u => u.node.type === "text");
    if (upText) text = (upText.node.data.text || "").trim();
  }
  let shots = parseDirectorShots(text);

  if (!shots.length) {
    try {
      s.toast("正在调用导演大师模型规划分镜（SKILL_34）…", "info");
      const plan = await cv.filmPlan({ idea: text || node.data.title || "多镜头分镜短片", shots: 3, has_outfit: false, has_scene: false });
      const shotDesc = plan.shots.map((sh, i) =>
        `【镜头 ${i + 1} · ${sh.size.toUpperCase()} · ${sh.camera_move || "固定"} · ${sh.seconds}s】\n首帧：${sh.first_frame}\n动作：${sh.motion}`
      ).join("\n\n");
      text = `🎬 场景：${plan.scene}\n角色：${plan.look}\n环境音：${plan.audio}\n\n${shotDesc}`;
      if (node.type === "text") {
        s.updateNodeData(node.id, { text });
      }
      shots = parseDirectorShots(text);
    } catch (e) {
      s.toast(`导演分镜规划失败：${errText(e)}`, "err");
      return;
    }
  }

  if (!shots.length) {
    s.toast("未能解析出镜头信息，请确保文本包含【镜头 1 · ...】格式", "err");
    return;
  }

  // 1. 发现角色设定图 / 定妆照：优先取上游连着的，否则在全画布查找
  const upSheets = s.upstream(node.id).map(u => u.node).filter(n => n.type === "image" &&
    (n.data.role === "sheet" || n.data.title.includes("定妆照") || n.data.recipe?.op === "sheet"));
  const sheetNode = upSheets[0] || s.nodes.find(n => n.type === "image" &&
    (n.data.role === "sheet" || n.data.title.includes("定妆照") || n.data.recipe?.op === "sheet"))
    || s.nodes.find(n => n.type === "image" && n.data.media?.url);

  // 2. 发现 3D 白模 与 场景图片：优先取上游连着的，否则取全画布
  const upBoxes = s.upstream(node.id).map(u => u.node).filter(n => n.type === "box3d" || n.data.ref?.kind === "box_project");
  const boxNodes = upBoxes.length ? upBoxes : s.nodes.filter(n => n.type === "box3d" || n.data.ref?.kind === "box_project");
  const upScenes = s.upstream(node.id).map(u => u.node).filter(n => n.type === "image" &&
    n !== sheetNode && (n.data.role === "scene" || n.data.role === "upload" || (!n.data.title.includes("定妆照") && n.data.recipe?.op !== "sheet")));
  const sceneNode = upScenes[0] || s.nodes.find(n => n.type === "image" && n !== sheetNode &&
    (n.data.role === "scene" || n.data.role === "upload" || (!n.data.title.includes("定妆照") && n.data.recipe?.op !== "sheet")));

  // 3. 布局位置计算
  const baseX = node.position.x;
  const baseY = node.position.y;
  const col1X = baseX + 380; // 分镜首帧图
  const col2X = baseX + 720; // 单镜视频
  const col3X = baseX + 1060; // 成片合成

  const shotVideoIds: string[] = [];
  let prevKfId: string | null = null;

  const sceneMatch = text.match(/场景[：:]\s*([^\n]+)/);
  const lookMatch = text.match(/角色[：:]\s*([^\n]+)/);
  const audioMatch = text.match(/环境音[：:]\s*([^\n]+)/);
  const globalScene = sceneMatch ? sceneMatch[1].trim() : "";
  const globalLook = lookMatch ? lookMatch[1].trim() : "";
  const globalAudio = audioMatch ? audioMatch[1].trim() : "";
  const styleAnchor = "Live-action photorealistic cinematic footage, 24fps, natural skin texture, dramatic cinematic lighting.";

  for (let i = 0; i < shots.length; i++) {
    const sh = shots[i];
    const rowY = baseY + i * 260;
    const boxForShot = boxNodes.length > 1
      ? (i < shots.length - 1 ? boxNodes[0] : boxNodes[1])
      : boxNodes[0];

    // ① 创建分镜首帧图节点
    const kfTitle = uniqueTitle(s, `分镜图 · 镜 ${sh.shotNo} (${sh.size})`);
    const kfRefs: RecipeRef[] = [];
    if (sheetNode) kfRefs.push({ node: sheetNode.id, role: "character" });
    if (boxForShot) kfRefs.push({ node: boxForShot.id, role: "scene" });
    else if (sceneNode) kfRefs.push({ node: sceneNode.id, role: "scene" });
    else if (prevKfId) kfRefs.push({ node: prevKfId, role: "scene" });

    const sceneAnchor = globalScene ? `Setting (the same location and lighting for this scene): ${globalScene}.\n` : "";
    const charAnchor = globalLook ? `Character in this scene: ${globalLook}.\n` : "";
    const kfPrompt: PromptSeg[] = [
      { t: "text", text: `${styleAnchor}\n${sceneAnchor}${charAnchor}[Shot ${sh.shotNo} · ${sh.size} · ${sh.cameraMove}] ${sh.firstFrame}` }
    ];
    const kfId = s.addNode("image", {
      ref: freeRef(),
      title: kfTitle,
      role: "frame",
      recipe: {
        op: "image",
        prompt: kfPrompt,
        refs: kfRefs,
      },
    }, { x: col1X, y: rowY });

    // 连线到分镜图
    if (sheetNode) s.connect(sheetNode.id, kfId, "identity");
    if (boxForShot) s.connect(boxForShot.id, kfId, "ref");
    else if (sceneNode) s.connect(sceneNode.id, kfId, "ref");
    else if (prevKfId) s.connect(prevKfId, kfId, "ref");

    // ② 创建单镜视频节点
    const vidTitle = uniqueTitle(s, `视频 · 镜 ${sh.shotNo} (${sh.durationSec}s)`);
    const vidRefs: RecipeRef[] = [{ node: kfId, role: "first_frame" }];
    if (boxForShot) vidRefs.push({ node: boxForShot.id, role: "control_video" });

    const vidPrompt: PromptSeg[] = [
      { t: "text", text: `${styleAnchor}\n${sceneAnchor}${charAnchor}[Camera: ${sh.cameraMove}] ${sh.motion}` }
    ];
    const vidId = s.addNode("video", {
      ref: freeRef(),
      title: vidTitle,
      role: "generated",
      recipe: {
        op: "video",
        duration_ms: Math.round(sh.durationSec * 1000),
        prompt: vidPrompt,
        refs: vidRefs,
        audio: globalAudio || undefined,
      },
    }, { x: col2X, y: rowY });

    // 连线到视频节点
    s.connect(kfId, vidId, "ref");
    if (boxForShot) s.connect(boxForShot.id, vidId, "control");

    shotVideoIds.push(vidId);
    prevKfId = kfId;
  }

  // ③ 创建最终成片合成节点 (Concat)
  const concatTitle = uniqueTitle(s, "成片合成 · 完整故事");
  const concatY = baseY + (shots.length - 1) * 130;
  const concatId = s.addNode("video", {
    ref: freeRef(),
    title: concatTitle,
    role: "generated",
    recipe: {
      op: "concat",
      prompt: [],
      refs: shotVideoIds.map(vid => ({ node: vid, role: "reference" })),
    },
  }, { x: col3X, y: concatY });

  s.toast(`🎬 导演排镜完成：已拆出 ${shots.length} 组分镜头网络，正在启动后端流水线…`, "ok");
  try {
    await s.flushSave();
    await cv.execute(s.boardId, { node_ids: [concatId] });
  } catch (e) {
    s.toast(`排镜已落盘，可点击成片节点运行：${errText(e)}`, "info");
  }
}

function textActions(s: CanvasStore, node: CNode, r: Resolved): CanvasAction[] {
  const text = resolvedText(r);
  return [
    {
      id: "screenplay_config", label: "剧本设定器", icon: "✨", badge: "NEW",
      title: "剧本设定器：Top 8 爆款预设、5维精细设定与跨世界观文化圈层转译",
      run: () => s.openOverlay({ kind: "screenplay_config", nodeId: node.id }),
    },
    {
      id: "director_plan", label: "导演拆分镜", icon: "🎬", badge: "NEW",
      title: "调用系统导演大师 Skill (SKILL_34)：一键将这段文本拆成多镜头专业分镜网络（机位、景别、运镜、首尾帧过渡）",
      disabled: text.trim() ? false : "这个节点还没有文字",
      run: async () => {
        try {
          s.toast("正在调用导演大师模型规划分镜（SKILL_34）…", "info");
          const plan = await cv.filmPlan({ idea: text.trim(), shots: 3, has_outfit: false, has_scene: false });
          const at = placeBeside(s.nodes, node, "right", { w: 320, h: 220 })[0];
          const shotDesc = plan.shots.map((sh, i) =>
            `【镜头 ${i + 1} · ${sh.size.toUpperCase()} · ${sh.camera_move || "固定"} · ${sh.seconds}s】\n首帧：${sh.first_frame}\n动作：${sh.motion}`
          ).join("\n\n");
          const planId = s.addNode("text", {
            ref: freeRef(),
            title: uniqueTitle(s, `导演分镜 · ${plan.title || "分镜大纲"}`),
            role: "note",
            text: `🎬 场景：${plan.scene}\n角色：${plan.look}\n环境音：${plan.audio}\n\n${shotDesc}`,
          }, at, { source: node.id, kind: "ref" });
          s.toast(`已生成电影级导演分镜《${plan.title}》（${plan.shots.length} 镜）`, "ok");
          s.select(planId);
        } catch (e) {
          s.toast(`导演分镜生成失败：${errText(e)}`, "err");
        }
      },
    },
    {
      id: "orchestrate_shots", label: "导演排镜与成片", icon: "🎞", badge: "NEW",
      title: "一键将导演分镜规划拆解成完整 DAG：多镜头分镜图 + 3D白模控制 + 视频生成 + 首尾帧接戏 + 自动缝合 Concat",
      disabled: text.trim() ? false : "这个节点还没有文字",
      run: () => orchestrateDirectorShots(s, node),
    },
    {
      id: "build_box", label: "搭白模", icon: "◰",
      title: "让 3D-BOX 智能体按这段文字搭一个白模（人物、站位、动作、机位），长在右边",
      disabled: text.trim() ? false : "这个节点还没有文字",
      run: () => buildBoxFromText(s, node.id, node.data.title, text),
    },
    genAction(s, node),
    {
      id: "copy", label: "复制文字", icon: "⧉",
      disabled: text.trim() ? false : "没有文字",
      run: async () => {
        await navigator.clipboard.writeText(text);
        s.toast("已复制", "ok");
      },
    },
  ];
}

async function putInBox(s: CanvasStore, node: CNode, boxNode: CNode, member: CastMember, view: string) {
  if (boxNode.data.ref.kind !== "box_project") return;
  await addCharacterToBox(s, boxNode.data.ref.id, member, view);
  if (!s.edges.some(e => e.source === node.id && e.target === boxNode.id)) s.connect(node.id, boxNode.id, "identity");
  s.toast(`已把「${member.name}」放进${boxNode.data.title}`, "ok");
}

async function putInNewBox(s: CanvasStore, node: CNode, member: CastMember, view: string) {
  const p = await cv.boxCreate(`${member.name} · 白模`, "blank");
  s.addNode("box3d", { ref: { kind: "box_project", id: p.id }, title: `3D 白模 · ${member.name}` },
    undefined, { source: node.id, kind: "identity" });
  await s.loadBoxDoc(p.id, true);
  await addCharacterToBox(s, p.id, member, view);
  s.toast(`新建了白模，「${member.name}」已经站进去`, "ok");
}

function imageActions(s: CanvasStore, node: CNode, r: Resolved): CanvasAction[] {
  const role = node.data.role;
  const pending = node.data.gen && node.data.gen.status !== "succeeded" && !node.data.media;
  const url = pending ? undefined
    : r.kind === "entity_view" ? media(r.url) : r.kind === "media" ? media(r.media.url) : undefined;
  const why = pending ? "还在生成" : "还没有图";
  const tail = mediaTail(s, node.data.title, url, false, why);

  // 只认派生的角色视角（角色库现取）；自由节点也可能是 sheet 角色（配方出的标准定妆照），走下面的通用动作
  if ((role === "character" || role === "sheet" || role === "view") && isDerived(node.data.ref)) {
    const member = r.kind === "entity_view" ? r.member : null;
    const view = node.data.ref.kind === "entity_view" ? node.data.ref.view : "front";
    const boxes = s.nodes.filter(n => n.type === "box3d" && n.data.ref.kind === "box_project");
    return [
      {
        id: "to_box", label: "放进白模", icon: "◰",
        title: "在白模的 scene.js 里加一个人偶，带上这个角色的角色库 id",
        disabled: member ? false : "只有角色库里的角色能放进白模（这个节点的角色找不到了）",
        menu: member ? [
          ...boxes.map(b => ({
            id: `to_box:${b.id}`, label: b.data.title, icon: "3D",
            run: () => putInBox(s, node, b, member, view),
          })),
          { id: "to_box:new", label: "新建白模", icon: "＋", run: () => putInNewBox(s, node, member, view) },
        ] : undefined,
      },
      {
        id: "styling", label: "造型室", icon: "↗",
        title: "角色外观只在角色库的造型室里改（画布上的定妆照只读）",
        // 同标签切到角色库并打开这个角色（地址栏带着书、章、画布，角色库「←」/ Nav 能切回来）
        run: () => navigate("characters", { char: member ? `e:${member.entity_id}` : null }),
      },
      genAction(s, node),
      {
        id: "more", label: "更多", icon: "⋯", title: "重出定妆照、多角度、超清",
        menu: [
          {
            id: "redo_refs", label: "重出定妆照", icon: "↻",
            title: "定妆照画坏了（多出手、背景不是灰底、抬着手）就重出：本机先出正面全身，再补齐其余角度和设定图（约 3–5 分钟）；出完重画分镜图才换上",
            disabled: member ? false : "这个节点的角色找不到了",
            run: async () => {
              if (!member) return;
              if (!window.confirm(`重出「${member.name}」的定妆照？正面全身换成新的一张，其余角度跟着重出。`)) return;
              await cv.charRefs(member.entity_id);
              s.toast(`「${member.name}」定妆照重出中：正面全身 → 其余角度 → 设定图；进度在角色库里看`, "ok",
                { label: "去角色库", run: () => navigate("characters", { char: `e:${member.entity_id}` }) });
            },
          },
          // 标准拼版（三视图 + 面部四角度 + 九宫格表情）：先复制成静态图，再交给执行器出
          sheetAction(s, node, url, why, "标准定妆照（拼版）"),
          { id: "upscale", label: "超清", icon: "⇡", disabled: "后端还没有 image.upscale" },
        ],
      },
      ...tail,
    ];
  }
  const isSheet = node.data.recipe?.op === "sheet" || node.data.role === "sheet" || node.data.role === "prop_sheet";
  return [genAction(s, node), ...(isSheet ? [] : [sheetAction(s, node, url, why)]), ...tail];
}

function videoActions(s: CanvasStore, node: CNode, r: Resolved): CanvasAction[] {
  if (node.data.role === "shot" && r.kind === "shot") {
    const shot = r.shot;
    const video = media(shot.video_url);
    const still = media(shot.first?.url);
    const busy = shotBusy(s, node.id, shot);
    return [
      { id: "render", label: "出片", icon: "▶", title: "给这一镜出视频", menu: shotMethods(s, node, shot) },
      { id: "stage", label: "导演台", icon: "⌖", title: "摆站位、定机位与运镜（3D 导演台）", run: () => s.openOverlay({ kind: "stage", shotId: shot.id }) },
      {
        // 做不了的几项收进「更多」：一直灰着摆在工具条上只会挤掉能用的按钮（铁律 3：照样列出、写明原因）
        id: "more", label: "更多", icon: "⋯", title: "选段创作、编辑、声音分离、超清、智能高清",
        menu: [
          {
            id: "hd", label: "智能高清", icon: "✧", title: "从预览潜变量续跑成片",
            disabled: !video ? "还没有视频" : busy ? "这一镜正在出片，等它跑完" : false,
            run: () => runText(s, node, shot, "final", "智能高清"),
          },
          { id: "segment", label: "选段创作", icon: "✂", badge: "NEW", disabled: "后端还没有视频裁剪/抽帧接口" },
          { id: "edit", label: "编辑", icon: "✎", badge: "NEW", disabled: "视频编辑只有 2B v2v，画布未接" },
          { id: "separate", label: "声音分离", icon: "♫", disabled: "后端还没有 audio.separate" },
          { id: "upscale", label: "超清", icon: "⇡", disabled: "后端还没有 video.upscale" },
        ],
      },
      { id: "download", label: "下载", icon: "⬇", disabled: video ? false : "还没出片", run: () => { if (video) downloadUrl(video, node.data.title); } },
      {
        id: "fullscreen", label: "全屏", icon: "⛶", disabled: video || still ? false : "还没出片",
        run: () => {
          if (video) s.openOverlay({ kind: "media", url: video, video: true });
          else if (still) s.openOverlay({ kind: "media", url: still, video: false });
        },
      },
    ];
  }
  const pending = node.data.gen && node.data.gen.status !== "succeeded" && !node.data.media;
  const m = r.kind === "media" ? r.media : null;
  const url = pending ? undefined : media(m?.url);
  const isImage = !!m?.mime?.startsWith("image/");
  const tail = mediaTail(s, node.data.title, url, !isImage, pending ? "还在生成" : "还没有内容");
  const up = s.upstream(node.id);
  const hasBox = up.some(u => u.node.type === "box3d" || u.node.data.ref?.kind === "box_project");
  const hasSheet = up.some(u => u.node.data.role === "sheet" || u.node.data.title.includes("定妆照"));
  const directorAction: CanvasAction = {
    id: "orchestrate_shots", label: "🎬 导演多镜成片 (ABCD规范)", icon: "🎞", badge: "NEW",
    title: "按照 ABCD 规范：拆解 2~3 个分镜头，分别利用白模机位运镜与定妆照身份，首尾帧过渡批次生成并拼接成片",
    run: () => orchestrateDirectorShots(s, node),
  };
  return hasBox || hasSheet ? [directorAction, ...tail] : tail;
}

/** 选中节点的工具条动作 */
export function actionsFor(node: CNode, s: CanvasStore): CanvasAction[] {
  if(node.data.comic) return [
    {id:'comic-edit',label:'制作与修改',run:()=>s.select(node.id)},
    ...(node.data.media?.url ? [{id:'comic-open',label:'查看产物',run:()=>s.openOverlay({kind:'media' as const,url:node.data.media!.url,video:node.type==='video'})}]:[]),
    {id:'comic-delete',label:'移除节点',run:()=>s.removeNodes([node.id])},
  ];
  const r = s.resolve(node.data.ref, node.data);
  let list: CanvasAction[];
  if (node.type === "box3d") list = box3dActions(node, s);
  else if (r.kind === "missing" && isDerived(node.data.ref)) list = [];
  else if (node.type === "text") list = textActions(s, node, r);
  else if (node.type === "image") list = imageActions(s, node, r);
  else if (node.type === "video") list = videoActions(s, node, r);
  else if (node.type === "group") list = groupActions(s, node);
  else list = [];
  if (node.data.recipe && (node.type === "image" || node.type === "video")) {
    // 配方节点：生成 / 重新生成在最前；还没出东西时「生成 ▾（往外长）」是灰的，收掉省地方
    const empty = isEmptyGen(node, s);
    list = [...recipeActions(s, node), ...list.filter(a => !(a.id === "gen" && empty))];
  }
  const ref = node.data.ref;
  if (isProductionRef(ref)) {
    const sourceActions: CanvasAction[] = [
      {
        id: "source:adopt", label: "采用素材最新版本", icon: "↻",
        title: "明确更新这一节点的素材版本；下游在下次运行时重新计算，不自动启动生成",
        run: async () => {
          try {
            const context = await prod.context(s.boardId);
            const result = await prod.resolve(context.data.context, [{ ...ref, revision: null }]);
            const item = result.data.items[0];
            if (!item || item.status !== "resolved") throw new Error(item?.issues?.map(i => i.message).join("；") || "素材不可用");
            s.updateNodeData(node.id, { ref: item.ref });
            s.toast("已采用素材最新版本；需要时手动重跑下游", "ok");
          } catch (e) { s.toast(`更新引用失败：${e instanceof Error ? e.message : String(e)}`, "err"); }
        },
      },
    ];
    if (ref.binding?.entity_id) sourceActions.unshift({
      id: "source:character", label: "打开来源角色", icon: "↗",
      run: () => navigate("characters", { char: `e:${ref.binding?.entity_id}` }),
    });
    list = [...sourceActions, ...list];
  }
  const dup = node.type !== "group" && node.type !== "box3d" ? [duplicateAction(s, node)] : [];
  return [...list.filter(a => a.id !== "remove" && a.id !== "duplicate"), ...dup, removeAction(s, [node])];
}

/** 是不是「点了生成却什么都没发」的空节点（误加的就是它们）：自由节点、没图没字、没有在跑或成功的生成 */
export function isEmptyGen(n: CNode, s: Pick<CanvasStore, "tasks">): boolean {
  if(n.data.comic)return false;
  const d = n.data;
  if (d.ref.kind !== "free" || d.media || (d.text ?? "").trim()) return false;
  if (d.gen && (d.gen.status === "queued" || d.gen.status === "running" || d.gen.status === "succeeded")) return false;
  return !s.tasks.some(t => t.nodeId === n.id && taskOpen(t));
}

/**
 * 删除 / 从画布拿掉（工具条、多选工具条、右键共用）。
 * 自由节点真删；剧本、镜头、定妆照、白模这类派生节点只是从画布拿掉，后端真身不动，底栏「已拿掉」里能放回。
 */
export function removeAction(s: CanvasStore, nodes: CNode[]): CanvasAction {
  const derived = nodes.filter(n => isDerived(n.data.ref)).length;
  const free = nodes.length - derived;
  const running = nodes.some(n => s.tasks.some(t => t.nodeId === n.id && taskOpen(t)));
  const label = nodes.length > 1 ? `删除 ${nodes.length} 个` : derived ? "从画布拿掉" : "删除";
  return {
    id: "remove", label, icon: "🗑",
    title: [
      free ? `删除自由节点${free > 1 ? ` ${free} 个` : ""}（可以撤销）` : "",
      derived ? `从画布拿掉${derived > 1 ? ` ${derived} 个` : ""}：剧本、镜头、定妆照、白模的真身都还在后端，底栏「已拿掉」里能放回` : "",
      running ? "有节点还在生成：结果不会再挂回画布（在资产管理 → 媒体里找）" : "",
      "快捷键 Delete / ⌫",
    ].filter(Boolean).join("\n"),
    run: () => s.removeNodes(nodes.map(n => n.id)),
  };
}
