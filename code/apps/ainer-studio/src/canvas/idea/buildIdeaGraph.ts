/**
 * 想法 → 整张画布（纳逗式）：把本机 LLM 拆好的导演分镜（FilmPlan）摆成一张「完整画布」。
 *
 * 为什么在前端摆而不是后端一条流水线跑完：用户要的是纳逗那样的画布 —— 每一步都是独立节点，
 * 带着自己的配方（提示词 + @引用 + 参考角色 + 参数），看得见、改得了、能单独重跑；
 * 所以这里只「摆」：节点、配方、连线（连线 = 配方引用），存盘后交给服务端执行器按拓扑序一个个出。
 *
 * 一行一类，从左往右（行与行之间的连线都是往下走的，不会横穿别的节点）：
 *   素材   想法（文字）· 人物照片 · 服装照片（可选）· 场景图（上传了的话）
 *   设定   定妆照（op=sheet，标准 16 格 / 快速 4 格）· 换装定妆照（有服装照时）· 场景图（没上传就文生图）
 *   分镜   导演分镜（文字，给人看）· 分组「分镜图」：分镜 1..N（接上一镜尾帧的那镜换成「镜 N 首帧」op=last_frame）
 *   视频   逐镜拼接：视频 1..N → 成片（op=concat）；一次成片：一个 op=one_take 节点
 *
 * 纯函数：不碰 React、不碰网络、不读 window（视口按默认屏幕算，调用方可以用 fitViewport 按真实窗口重算）。
 *
 * 单测思路（前端没有测试框架；集成者可以 esbuild 转成 JS 在 node 里断言）：
 *   1. 3 镜 cuts、无服装无场景：节点 = 想法、人物照片、定妆照、场景图（op=image 文生图）、导演分镜、分组、
 *      分镜 1..3、视频 1..3、成片；镜 2 transition=continuation → 没有「分镜 2」，有「镜 2 首帧」op=last_frame，
 *      refs=[{视频 1, reference}]，视频 2 的 first_frame 引用它。
 *   2. 有服装照：换装定妆照 refs[0] = {定妆照, base, panel: body_front}、refs[1] = {服装照片, reference}；
 *      分镜的 character 引用换装定妆照；定妆照 recipe.sheet.look 为空（衣服交给换装那一步）。
 *   3. 上传了场景图：场景图是 asset 节点（有 media、没有 recipe）；分镜 refs[0] = {场景图, base}。
 *   4. one_take：只有一个「一次成片」节点；refs 全是 first_frame；segments.at_ms 从 0 起递增，总长 ≤ 19000；
 *      continuation 的镜头照样画分镜图（一次生成里镜头本来就是连着的，没有上一条视频可取尾帧）。
 *   5. 每条边两端都在 nodes 里；每个配方 ref 都有一条 ref.node → 本节点 的边，kind = edgeKindOfRole(role, op)
 *      （人物照片 → 定妆照 是 identity，分镜 → 视频 是 control）；另有一条 想法 → 导演分镜 的 ref 边（不是配方引用）。
 *   6. 分组节点排在它所有子节点之前（xyflow 要求）；子节点 parentId = 分组 id、position 是相对坐标。
 *   7. 节点 id 稳定：idea:idea / idea:photo / idea:sheet / idea:outfit_photo / idea:outfit / idea:scene / idea:plan /
 *      idea:frames / idea:frame:N / idea:video:N / idea:film；配方引用图无环。
 */
import {
  DOC_SCHEMA,
  type CanvasDoc, type DocEdge, type DocNode, type EdgeKind, type FilmPlan, type ImageRole, type MediaRef, type NodeKind,
  type PromptSeg, type Recipe, type RecipeOp, type RefRole, type TextRole, type VideoRole,
} from "../model";

export interface IdeaInputs {
  idea: string;
  /** 人物照片（必填；/media/… 同源地址） */
  person: MediaRef;
  /** 服装照片：有就先出「换装定妆照」 */
  outfit?: MediaRef | null;
  /** 场景图：没有就按 plan.scene 文生图一张空镜 */
  scene?: MediaRef | null;
  /** cuts = 逐镜出再拼接；one_take = 几张分镜图钉在一次 LTX 生成里 */
  mode: "cuts" | "one_take";
  sheetPreset: "standard" | "quick";
  /** 角色名（写进定妆照拼版标题） */
  name?: string;
}

/** 稳定的节点 id（便于测试、便于集成者在画布上认节点） */
export const IDEA_IDS = {
  idea: "idea:idea",
  photo: "idea:photo",
  sheet: "idea:sheet",
  outfitPhoto: "idea:outfit_photo",
  outfit: "idea:outfit",
  scene: "idea:scene",
  plan: "idea:plan",
  frames: "idea:frames",
  frame: (n: number) => `idea:frame:${n}`,
  video: (n: number) => `idea:video:${n}`,
  film: "idea:film",
} as const;

/**
 * 配方里参考的角色 → 连线语义（连线颜色跟着它走，画布上一眼看出「谁的脸」「钉哪一帧」）：
 * 身份 → identity，首帧/尾帧/控制视频 → control，风格 → style，其余（底图、参考）→ ref；
 * 例外：定妆照（op=sheet）的底图 = 人物照片，算身份。
 */
export function edgeKindOfRole(role: RefRole, op?: RecipeOp): EdgeKind {
  // 定妆照的底图就是「这个人是谁」：人物照片 → 定妆照 画成身份线
  if (role === "character" || role === "reference_sheet" || (op === "sheet" && role === "base")) return "identity";
  if (role === "first_frame" || role === "last_frame" || role === "control_video") return "control";
  if (role === "style") return "style";
  return "ref";
}

/* ───────────────────────── 尺寸（和执行器、本机模型对齐） ───────────────────────── */

/** 分镜图：flux2-klein-4b-edit 的 800×480 档（快、和视频画幅接近） */
const FRAME = { w: 800, h: 480 };
/** 全身照：edit 模型的竖档 */
const PORTRAIT = { w: 512, h: 768 };
/** LTX 2.5 本机最快的一档 */
const VIDEO = { w: 768, h: 448 };
/** 一次成片的总长上限（LTX 2.5 一次生成 ≤ 19 秒；和 quick_film.MAX_TAKE_MS 一致） */
export const MAX_TAKE_MS = 19000;

/* ───────────────────────── 布局（px，与 nodes/* 实际渲染宽度一致） ───────────────────────── */

const NODE_W: Record<"text" | "image" | "sheet" | "video", number> = { text: 260, image: 220, sheet: 300, video: 280 };
/** 布局估高：没出图时占位卡按默认比例画，出了图按原图比例 —— 取两者里大的，免得出图后压到下一行 */
const NODE_H: Record<"text" | "image" | "sheet" | "video" | "portrait", number> = {
  text: 160, image: 170, sheet: 170, video: 210, portrait: 300,
};
const GAP_X = 80;
/** 行距：上一行最高的卡 + 小标题 22px + 留白 */
const ROW_Y = [0, 400, 800];
/** 分组内边距：左右下 24，上面多留 28 给子节点卡片上方的小标题 */
const GROUP_PAD = 24;
const GROUP_TOP = GROUP_PAD + 28;
/** 镜头一列宽：视频卡 280 + 间距 60，分镜图和视频上下对齐 */
const SHOT_PITCH = 340;

/* ───────────────────────── 文字 ───────────────────────── */

const SIZE_EN: Record<string, string> = {
  els: "Extreme wide shot", ws: "Wide shot", fs: "Full shot", ms: "Medium shot", mcu: "Medium close-up",
  cu: "Close-up", ecu: "Extreme close-up",
};
const SIZE_ZH: Record<string, string> = { els: "大远景", ws: "远景", fs: "全景", ms: "中景", mcu: "近景", cu: "特写", ecu: "大特写" };
const ANGLE_ZH: Record<string, string> = { eye_level: "平视", low_angle: "仰拍", high_angle: "俯拍", dutch: "斜角" };
const MOVE_ZH: Record<string, string> = {
  handheld_tracking: "手持跟拍", slow_push_in: "缓推", dolly_pull_out: "后拉", low_angle_pan: "低角度摇", static_lock_off: "固定机位",
};

const text = (t: string): PromptSeg => ({ t: "text", text: t });
const chip = (node: string, label: string): PromptSeg => ({ t: "ref", node, label });
const clean = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
/** 句末补句号：LLM 给的片段有的带有的不带，拼起来要像一句话 */
const sentence = (s: string) => {
  const t = clean(s);
  return !t ? "" : /[.!?。！？]$/.test(t) ? t : `${t}.`;
};

/** 定格画面的写实收尾（和 keyframe_prompt 一致：不许拼版、不许字，klein 才不会画成设定图） */
const STILL_TAIL = "Photorealistic cinematic film still, natural light, real skin texture, exactly one person, one single image, "
  + "no text, no captions, no split screen, no collage.";

/** 第 i 镜实际用的转场：第 1 镜没有上一镜，一律当切 */
function transitionOf(plan: FilmPlan, i: number): "cut" | "continuation" {
  return i > 0 && plan.shots[i].transition === "continuation" ? "continuation" : "cut";
}

/** 一次成片各镜的起点（毫秒）：按秒数累加，总长超上限按比例压（同 quick_film.take_layout） */
export function takeLayout(seconds: number[], maxMs = MAX_TAKE_MS): { at: number; end: number }[] {
  const total = seconds.reduce((a, b) => a + b, 0) * 1000;
  const k = total > 0 ? Math.min(1, maxMs / total) : 1;
  const out: { at: number; end: number }[] = [];
  let t = 0;
  for (const s of seconds) {
    const d = Math.round(s * 1000 * k);
    out.push({ at: t, end: t + d });
    t += d;
  }
  return out;
}

function planNote(plan: FilmPlan, inputs: IdeaInputs): string {
  const lines = [
    `《${clean(plan.title) || "想法画布"}》 · ${plan.shots.length} 镜 · ${inputs.mode === "one_take" ? "一次成片" : "逐镜拼接"}`,
  ];
  if (clean(plan.scene)) lines.push(`场景：${clean(plan.scene)}`);
  if (clean(plan.look)) lines.push(`外观：${clean(plan.look)}`);
  if (clean(plan.audio)) lines.push(`声音：${clean(plan.audio)}`);
  plan.shots.forEach((s, i) => {
    const size = (s.size ?? "").toLowerCase();
    const head = [
      `镜 ${i + 1}`,
      SIZE_ZH[size] ?? size.toUpperCase(),
      s.angle ? ANGLE_ZH[s.angle] ?? s.angle : "",
      s.camera_move ? MOVE_ZH[s.camera_move] ?? s.camera_move : "",
      `${s.seconds} 秒`,
      transitionOf(plan, i) === "continuation" ? (inputs.mode === "cuts" ? "接上一镜尾帧" : "接上一镜") : i > 0 ? "切" : "",
    ].filter(Boolean).join(" · ");
    lines.push("", head, `首帧：${clean(s.first_frame)}`);
    if (clean(s.motion)) lines.push(`动作：${clean(s.motion)}`);
  });
  lines.push("", "（这是拆好的导演分镜，给人看；改它不会自动重拆。要改哪一镜，直接改那一镜的分镜图 / 视频节点的提示词再重跑）");
  return lines.join("\n");
}

/* ───────────────────────── 主函数 ───────────────────────── */

type Role = ImageRole | VideoRole | TextRole;

export function buildIdeaGraph(plan: FilmPlan, inputs: IdeaInputs): CanvasDoc {
  const nodes: DocNode[] = [];
  const edges: DocEdge[] = [];
  const ids = IDEA_IDS;

  const link = (source: string, target: string, kind: EdgeKind) => {
    if (source === target || edges.some(e => e.source === source && e.target === target)) return;
    // id 和 store.addEdge 同一个格式：用户边 u:源>目标
    edges.push({ id: `u:${source}>${target}`, source, target, sourceHandle: null, targetHandle: null, data: { kind } });
  };

  /** 节点 ref：上传的素材有 asset_id 就记成 asset（资产管理里认得出来），否则和生成节点一样是自由节点 */
  const put = (
    id: string, type: NodeKind, title: string, role: Role | undefined, at: { x: number; y: number },
    extra: Partial<DocNode["data"]> = {}, asset?: string | null, box?: { parentId?: string; width?: number; height?: number },
  ) => {
    const node: DocNode = {
      id, type, position: { x: at.x, y: at.y },
      data: { ref: asset ? { kind: "asset", id: asset } : { kind: "free", id }, title, ...(role ? { role } : {}), ...extra },
    };
    if (box?.parentId) node.parentId = box.parentId;
    if (box?.width) node.width = box.width;
    if (box?.height) node.height = box.height;
    nodes.push(node);
    return id;
  };

  /** 配方节点：按 refs 连边（连线 = 配方引用） */
  const putRecipe = (
    id: string, type: NodeKind, title: string, role: Role, at: { x: number; y: number }, recipe: Recipe, parentId?: string,
  ) => {
    put(id, type, title, role, at, { recipe }, null, parentId ? { parentId } : undefined);
    for (const r of recipe.refs) link(r.node, id, edgeKindOfRole(r.role, recipe.op));
    return id;
  };

  const shots = plan.shots;
  const hasOutfit = !!inputs.outfit?.url;
  const hasScene = !!inputs.scene?.url;
  const name = clean(inputs.name) || null;

  /* ── 第 1 行：素材 ── */
  let x = 0;
  put(ids.idea, "text", "想法", "prompt", { x, y: ROW_Y[0] }, { text: inputs.idea.trim() });
  x += NODE_W.text + GAP_X;
  const photoX = x;
  put(ids.photo, "image", "人物照片", "upload", { x, y: ROW_Y[0] }, { media: inputs.person }, inputs.person.asset_id);
  x += NODE_W.image + GAP_X;
  if (hasOutfit) {
    put(ids.outfitPhoto, "image", "服装照片", "upload", { x, y: ROW_Y[0] }, { media: inputs.outfit! }, inputs.outfit!.asset_id);
    x += NODE_W.image + GAP_X;
  }
  if (hasScene) put(ids.scene, "image", "场景图", "upload", { x, y: ROW_Y[0] }, { media: inputs.scene! }, inputs.scene!.asset_id);

  /* ── 第 2 行：设定（定妆照、换装、场景） ── */
  x = photoX;
  putRecipe(ids.sheet, "image", "定妆照", "sheet", { x, y: ROW_Y[1] }, {
    op: "sheet", prompt: [], refs: [{ node: ids.photo, role: "base" }],
    // 有服装照时衣服交给「换装定妆照」那一步；这里只保留人本来的样子（同 quick_film：有服装照就不写 look）
    sheet: { preset: inputs.sheetPreset, name, look: hasOutfit ? null : clean(plan.look) || null },
  });
  x += NODE_W.sheet + GAP_X;
  if (hasOutfit) {
    putRecipe(ids.outfit, "image", "换装定妆照", "generated", { x, y: ROW_Y[1] }, {
      op: "image",
      prompt: [
        text("Change only the clothes. The person in "), chip(ids.sheet, "定妆照"),
        text(" now wears exactly the outfit from "), chip(ids.outfitPhoto, "服装照片"),
        text(". Remove the old clothes completely. Keep the same face, hairstyle, skin tone and body. Full body from head to shoes, "
          + "standing naturally facing the camera, arms relaxed at the sides, plain light grey seamless background, soft even light. "
          + "One single person, no text."),
      ],
      // 底图是定妆照的全身正面（管脸和身形），服装照只当参考（管衣服）
      refs: [{ node: ids.sheet, role: "base", panel: "body_front" }, { node: ids.outfitPhoto, role: "reference" }],
      width: PORTRAIT.w, height: PORTRAIT.h,
    });
    x += NODE_W.image + GAP_X;
  }
  if (!hasScene) {
    putRecipe(ids.scene, "image", "场景图", "generated", { x, y: ROW_Y[1] }, {
      op: "image",
      prompt: [text(`${sentence(plan.scene) || "An empty location that fits the idea."} Wide establishing shot, empty, no people, `
        + "photorealistic film still, natural light, no text.")],
      refs: [],
      // 和分镜图同画幅：它要当分镜图的底图，画幅一致才不会被裁
      width: FRAME.w, height: FRAME.h,
    });
  }

  /* ── 第 3 行：导演分镜 + 分组「分镜图」 ── */
  put(ids.plan, "text", "导演分镜", "note", { x: 0, y: ROW_Y[2] }, { text: planNote(plan, inputs) });
  // 不是配方引用，只是告诉人「分镜是从这句想法拆出来的」（文字节点不进执行器）
  link(ids.idea, ids.plan, "ref");

  const who = hasOutfit ? { id: ids.outfit, label: "换装定妆照" } : { id: ids.sheet, label: "定妆照" };
  const groupX = NODE_W.text + GAP_X;
  const groupH = GROUP_TOP + NODE_H.image + GROUP_PAD + 4;
  const groupW = GROUP_PAD * 2 + Math.max(0, shots.length - 1) * SHOT_PITCH + NODE_W.video;
  // xyflow 要求父节点排在子节点前面
  put(ids.frames, "group", "分镜图", undefined, { x: groupX, y: ROW_Y[2] }, {}, null, { width: groupW, height: groupH });

  /** 每镜钉首帧的那张图（分镜 N 或 镜 N 首帧） */
  const firstFrames: { id: string; label: string }[] = [];
  const videoY = ROW_Y[2] + groupH + 110;
  const colX = (i: number) => groupX + GROUP_PAD + i * SHOT_PITCH;

  shots.forEach((s, i) => {
    const n = i + 1;
    const rel = { x: GROUP_PAD + i * SHOT_PITCH, y: GROUP_TOP };
    // 逐镜拼接时「接上一镜」= 拿上一条视频的最后一帧当这一镜首帧（动量、光影连续）；一次成片本来就连着，照样画分镜图
    if (inputs.mode === "cuts" && transitionOf(plan, i) === "continuation") {
      const id = putRecipe(ids.frame(n), "image", `镜 ${n} 首帧`, "frame", rel, {
        op: "last_frame", prompt: [], refs: [{ node: ids.video(n - 1), role: "reference" }],
      }, ids.frames);
      firstFrames.push({ id, label: `镜 ${n} 首帧` });
      return;
    }
    const size = SIZE_EN[(s.size ?? "").toLowerCase()];
    const id = putRecipe(ids.frame(n), "image", `分镜 ${n}`, "frame", rel, {
      op: "image",
      prompt: [
        text("Use "), chip(ids.scene, "场景图"), text(" as the set and keep it recognisable. Place the same person as "),
        chip(who.id, who.label),
        text(` in the scene, keeping the face, hairstyle and outfit exactly. ${size ? `${size}. ` : ""}${sentence(s.first_frame)} ${STILL_TAIL}`),
      ],
      // 场景图当底图（edit 模式，场景可认）；人从定妆照来（sheet 不指定面板 = 执行器按「身份」自动挑全身正面、正脸、侧身）
      refs: [{ node: ids.scene, role: "base" }, { node: who.id, role: "character" }],
      width: FRAME.w, height: FRAME.h,
    }, ids.frames);
    firstFrames.push({ id, label: `分镜 ${n}` });
  });

  /* ── 第 4 行：视频 ── */
  const audio = clean(plan.audio) || null;
  if (inputs.mode === "cuts") {
    shots.forEach((s, i) => {
      const n = i + 1;
      const cont = transitionOf(plan, i) === "continuation";
      const motion = clean(s.motion) || clean(s.first_frame);
      putRecipe(ids.video(n), "video", `视频 ${n}`, "generated", { x: colX(i), y: videoY }, {
        op: "video",
        prompt: [text(cont ? `The action continues seamlessly from the initial frame. ${motion}` : motion)],
        refs: [{ node: firstFrames[i].id, role: "first_frame" }],
        duration_ms: Math.round(Math.max(2, Math.min(20, s.seconds || 3)) * 1000),
        width: VIDEO.w, height: VIDEO.h, audio,
      });
    });
    if (shots.length) {
      putRecipe(ids.film, "video", "成片", "generated", { x: colX(shots.length) + 40, y: videoY }, {
        op: "concat", prompt: [], refs: shots.map((_, i) => ({ node: ids.video(i + 1), role: "reference" as const })),
      });
    }
  } else if (shots.length) {
    const spans = takeLayout(shots.map(s => s.seconds || 3));
    const motions = shots.map(s => clean(s.motion) || clean(s.first_frame));
    putRecipe(ids.film, "video", "一次成片", "generated", { x: colX(0) + ((shots.length - 1) * SHOT_PITCH) / 2, y: videoY }, {
      op: "one_take",
      prompt: [text(motions.join(" "))],
      refs: firstFrames.map(f => ({ node: f.id, role: "first_frame" as const })),
      segments: firstFrames.map((f, i) => ({ node: f.id, at_ms: spans[i].at, motion: motions[i] })),
      duration_ms: spans[spans.length - 1].end,
      width: VIDEO.w, height: VIDEO.h, audio,
    });
  }

  const doc: CanvasDoc = { schema: DOC_SCHEMA, viewport: { x: 0, y: 0, zoom: 1 }, nodes, edges };
  doc.viewport = fitViewport(doc, 1440, 860);
  return doc;
}

/* ───────────────────────── 视口 ───────────────────────── */

function estSize(n: DocNode): { w: number; h: number } {
  if (n.width && n.height) return { w: n.width, h: n.height };
  if (n.type === "text") return { w: NODE_W.text, h: NODE_H.text };
  if (n.type === "video") return { w: NODE_W.video, h: NODE_H.video };
  if (n.data.role === "sheet") return { w: NODE_W.sheet, h: NODE_H.sheet };
  // DocNode.data 是 Omit<…, "orphan">，带索引签名的接口经 Omit 后字段都成了 unknown，这里按契约收回类型
  const r = n.data.recipe as Recipe | null | undefined;
  // 上传的照片多半是竖图；配方写明竖幅的（全身照）同理
  if (n.data.role === "upload" || (r?.width && r.height && r.height > r.width)) return { w: NODE_W.image, h: NODE_H.portrait };
  return { w: NODE_W.image, h: NODE_H.image };
}

/**
 * 让整张图落在一块 w×h 的屏幕里（顶栏 64px、底栏 90px 让开）。
 * 为什么文档里要带视口：store 载入有视口的文档就直接用它，不再自动 fit —— 给个合适的，进来就看到全貌。
 */
export function fitViewport(doc: CanvasDoc, w: number, h: number): CanvasDoc["viewport"] {
  const byId = new Map(doc.nodes.map(n => [n.id, n]));
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of doc.nodes) {
    const p = n.parentId ? byId.get(n.parentId) : undefined;
    const ax = n.position.x + (p?.position.x ?? 0);
    const ay = n.position.y + (p?.position.y ?? 0);
    const s = estSize(n);
    minX = Math.min(minX, ax);
    minY = Math.min(minY, ay - 26); // 卡片上方的小标题
    maxX = Math.max(maxX, ax + s.w);
    maxY = Math.max(maxY, ay + s.h);
  }
  if (!Number.isFinite(minX)) return { x: 0, y: 0, zoom: 1 };
  const top = 64, bottom = 90, side = 40;
  const bw = maxX - minX, bh = maxY - minY;
  const zoom = Math.max(0.2, Math.min(1, (w - side * 2) / bw, (h - top - bottom) / bh));
  const round = (v: number) => Math.round(v * 10) / 10;
  return {
    x: round((w - bw * zoom) / 2 - minX * zoom),
    y: round(top + (h - top - bottom - bh * zoom) / 2 - minY * zoom),
    zoom: Math.round(zoom * 1000) / 1000,
  };
}
