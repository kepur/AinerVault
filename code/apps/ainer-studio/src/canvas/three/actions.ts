/**
 * 白模节点的动作与白模相关的写回（画布 → 3D-BOX 项目 / 导演链）。
 *
 * 这里不 import three，也不 import store（只用传进来的 CanvasStore）：工具条、Dock、store 的轮询器都会调这些函数，
 * 它们在主画布首包里；3D 引擎只在白模真正实时渲染时才加载（BoxPreview 是 lazy 的）。
 *
 * 错误约定：失败一律抛出「给人看的一句原因」，不在这里 toast —— 调用方（store 的连线提示、NodeActions、Dock）
 * 都会 catch 后拼成「xx 失败：<原因>」toast 出来；这里再 toast 就重复了。抛出也让调用方能跳过成功提示、保住草稿。
 */
import { cv, HttpError, media } from "../api";
import type { CanvasStore } from "../contract";
import type { BoxInfo, CanvasAction, CNode, MediaRef, TrackedTask } from "../model";
import { nodeIdOf } from "../model";
import type { Job, JobOutput } from "../../box/director";
import type { CastMember, ShotCard } from "../../types";
import { clear as clearPosters } from "./posters";

/* ───────────────────────── 小工具 ───────────────────────── */

/** Blender 渲出的几路（名字以 box/RenderPanel.tsx 的 PASSES 与 ainer-core director/blender_adapter.py 的 PASSES 为准） */
const PASSES = [
  { id: "preview", zh: "预演" }, { id: "clay", zh: "白模" }, { id: "depth", zh: "深度" },
  { id: "pose", zh: "骨架" }, { id: "canny", zh: "边缘" },
] as const;

/** 3D-BOX 智能体一次最多收 4000 字（scene3d.py AgentIn.message）；剧本太长就截断，留点余量给前缀 */
const ASK_MAX = 3800;

const running = (t: TrackedTask) => t.status === "queued" || t.status === "running";

function boxIdOf(node: CNode): string | null {
  return node.data.ref.kind === "box_project" ? node.data.ref.id : null;
}

function boxOf(s: CanvasStore, node: CNode): BoxInfo | null {
  const r = s.resolve(node.data.ref, node.data);
  return r.kind === "box_project" ? r.box : null;
}

/** 改 3D-BOX 项目时的错误 → 一句人话。409 = 智能体正在跑（scene3d.py：运行中不许改文件、不许再叫） */
function boxError(e: unknown): Error {
  if (e instanceof HttpError && e.status === 409) return new Error("智能体正在改这个白模，等它改完再试", { cause: e });
  return e instanceof Error ? e : new Error(String(e));
}

/** 显示/存档用的地址：/media 一律转同源（铁律 2）；data:/blob: 原样（base64 里碰巧有 "/media/" 会被 media() 截坏） */
function sameOrigin(url: string): string {
  if (url.startsWith("data:") || url.startsWith("blob:")) return url;
  return media(url) ?? url;
}

/** 按扩展名（或 data: 头）推 mime：Blender 产物是 mp4，演示模式的产物是 SVG data URI */
function mimeOf(url: string): string {
  const d = /^data:([^;,]+)/.exec(url);
  if (d) return d[1];
  const ext = /\.([a-z0-9]+)(?:[?#]|$)/i.exec(url)?.[1]?.toLowerCase() ?? "";
  const table: Record<string, string> = {
    mp4: "video/mp4", webm: "video/webm", mov: "video/quicktime", png: "image/png", jpg: "image/jpeg",
    jpeg: "image/jpeg", webp: "image/webp", svg: "image/svg+xml", gif: "image/gif",
  };
  return table[ext] ?? "video/mp4";
}

/** 白模画幅是竖的就渲竖的（RenderPanel 也给了 576×1024 这一档）；其余按 LTX 的 1024×576 */
function resolutionFor(box: BoxInfo | null): [number, number] {
  const a = box?.doc?.aspect ?? 16 / 9;
  return a < 1 ? [576, 1024] : [1024, 576];
}

/**
 * 从 (x0, y) 起往右找 n 块放得下 w×h 的空位（避开已有节点的包围盒），排成一行。
 * 为什么横排：导入时白模单独占镜头上方的一行（importer 的 BOX_ABOVE），往右是空的；
 * 竖着往下会撞上同一行的镜头，一路跳到下一条泳道去。
 * 为什么不交给 addNode 自动排：一次长出五个节点时，store 的 nodes 还没刷新，连续几次会算到同一个位置。
 */
function freeRow(s: CanvasStore, x0: number, y: number, w: number, h: number, n: number): { x: number; y: number }[] {
  const GAP = 24;
  const rects = s.nodes.map(m => ({
    x: m.position.x, y: m.position.y,
    w: m.measured?.width ?? m.width ?? 280, h: m.measured?.height ?? m.height ?? 200,
  }));
  const hit = (x: number) => rects.some(r => x < r.x + r.w + GAP && x + w + GAP > r.x && y < r.y + r.h + GAP && y + h + GAP > r.y);
  const out: { x: number; y: number }[] = [];
  let x = x0;
  while (out.length < n) {
    let guard = 0;
    while (hit(x) && guard++ < 800) x += 24;
    out.push({ x, y });
    rects.push({ x, y, w, h });
    x += w + GAP;
  }
  return out;
}

/* ───────────────────────── 录预演（实时视口里录） ───────────────────────── */

const recorders = new Map<string, () => void>();

/** Box3DNode 订阅：工具条点「录预演」时由它在自己的实时视口里录。返回取消订阅 */
export function onRecordRequest(nodeId: string, fn: () => void): () => void {
  recorders.set(nodeId, fn);
  return () => { if (recorders.get(nodeId) === fn) recorders.delete(nodeId); };
}

/** 发出录制请求；节点不在屏上（被 onlyRenderVisibleElements 卸掉了）就返回 false */
export function dispatchRecord(nodeId: string): boolean {
  const fn = recorders.get(nodeId);
  if (!fn) return false;
  fn();
  return true;
}

/** 「录预演」：Box3DNode 订阅后在实时视口里录（没有实时视口时节点自己 toast 提示） */
export function requestRecord(nodeId: string): void {
  dispatchRecord(nodeId);
}

/* ───────────────────────── 工具条 ───────────────────────── */

export function box3dActions(node: CNode, s: CanvasStore): CanvasAction[] {
  const boxId = boxIdOf(node);
  const box = boxOf(s, node);
  const gone = !boxId || !box ? (node.data.orphan ? "这个白模在 3D-BOX 里找不到了" : "白模还没载入") : false;
  const mine = s.tasks.filter(t => t.nodeId === node.id && running(t));
  const agentBusy = !!box?.active_run || mine.some(t => t.kind === "box_agent");
  const rendering = mine.some(t => t.kind === "blender");
  const cams = box?.doc?.cameras ?? box?.cameras ?? [];
  const cur = node.data.camera ?? null;
  const curName = cur ? cams.find(c => c.id === cur)?.name ?? "已删的机位" : "按剪辑";

  return [
    {
      id: "live", label: node.data.live ? "实时 · 开" : "实时", icon: node.data.live ? "◉" : "○",
      title: "没选中也保持实时渲染（同屏最多 2 个实时视口，多出来的显示海报）",
      disabled: gone,
      run: () => s.updateNodeData(node.id, { live: !node.data.live }),
    },
    {
      id: "orbit", label: node.data.orbit ? "自由视角 · 开" : "自由视角", icon: "🔄",
      title: node.data.orbit ? "切回机位视角" : "自由观察视角（可在视口内直接拖拽旋转、右键平移、滚轮缩放查看 3D 白模）",
      disabled: gone,
      run: () => {
        const next = !node.data.orbit;
        s.updateNodeData(node.id, { orbit: next, live: next ? true : node.data.live });
      },
    },
    {
      id: "camera", label: `机位 · ${curName}`, icon: "◎",
      title: "节点里看哪台机位；「按剪辑」= 按主机位时间表切换（渲控制素材也用它）",
      disabled: gone || (cams.length ? false : "白模还没有机位：让智能体加一台，或在 3D-BOX 里加"),
      menu: [
        { id: "camera:cut", label: "按剪辑", icon: cur === null ? "✓" : undefined, run: () => s.updateNodeData(node.id, { camera: null, orbit: false }) },
        ...cams.map(c => ({
          id: `camera:${c.id}`, label: c.name, icon: cur === c.id ? "✓" : undefined,
          run: () => s.updateNodeData(node.id, { camera: c.id, orbit: false }),
        })),
      ],
    },
    {
      id: "regenerate", label: "重新搭景", icon: "↻",
      title: "让智能体按镜头剧本重新规划与搭建 3D 白模场景（更新人物站位、动作与机位）",
      disabled: gone || (agentBusy ? "智能体正在搭景" : false) || (rendering ? "正在渲染中" : false),
      run: async () => {
        try {
          await regenerateBox(s, node);
        } catch (e) {
          s.toast(`重新搭景失败：${(e as Error).message}`, "err");
        }
      },
    },
    {
      id: "record", label: "录预演", icon: "●", badge: "NEW",
      title: "在节点的实时视口里按当前机位从头录一遍（浏览器录画布，约 1024 宽 webm），存进 3D-BOX 项目，长成一个预演视频节点",
      disabled: gone || (typeof MediaRecorder === "undefined" ? "这个浏览器不支持录制画布（MediaRecorder）" : false),
      run: () => {
        if (!dispatchRecord(node.id)) s.toast("先选中白模，等它实时渲染后再录", "info");
      },
    },
    {
      id: "blender", label: "渲控制素材", icon: "◫",
      title: "Blender 无头渲：预演 / 白模 / 深度 / 骨架 / 边缘五路视频，渲完长在白模右边（单线程队列，排队时间看前面有几个）",
      disabled: gone
        || (box?.ok === false ? "白模脚本有错，先在 3D-BOX 里修好" : false)
        || (agentBusy ? "智能体正在改景，等它改完再渲" : false)
        || (rendering ? "正在渲染，等这一轮完成" : false),
      run: async () => {
        if (!boxId) return;
        const job = await cv.blenderRender(boxId, {
          camera: node.data.camera ?? "cut",
          output_resolution: resolutionFor(box),
          passes: PASSES.map(p => p.id),
        });
        s.track({ key: `blender:${job.id}`, kind: "blender", remote: job.id, nodeId: node.id, label: "渲控制素材" });
        s.toast(`已排进 Blender 队列：${PASSES.map(p => p.zh).join(" / ")}`, "info");
      },
    },
    filmAction(node, s, boxId, gone),
    {
      // id 用 fullscreen：外壳把它当图标按钮排到分隔线后面（canvas/actions.ts 的 ICON_ONLY）
      id: "fullscreen", label: "打开 3D-BOX", icon: "⛶",
      title: s.demo ? "全屏看白模（演示模式：完整编辑器要连上后端）" : "全屏打开 3D-BOX 编辑器（双击节点也行）",
      disabled: boxId ? false : "白模还没建好",
      run: () => { if (boxId) s.openOverlay({ kind: "box", id: boxId }); },
    },
  ];
}

/**
 * 「用白模出片」：只有这个白模就是那一镜导演链搭的（shot.director.run.box_project_id），才能直接 :render 重出 ——
 * 后端会先 export_box 把 3D-BOX 里的手改带进去。任意白模驱动任意镜头要扩展 render-final（控制视频只取父 Blender 任务自己的产物）。
 */
function filmAction(node: CNode, s: CanvasStore, boxId: string | null, gone: string | false): CanvasAction {
  const base = { id: "film", label: "用白模出片", icon: "▶" } as const;
  if (gone) return { ...base, disabled: gone };
  const shots = s.downstream(node.id)
    .filter(d => d.edge.data?.kind === "control" && d.node.data.ref.kind === "shot")
    .map(d => {
      const r = s.resolve(d.node.data.ref, d.node.data);
      return r.kind === "shot" ? { node: d.node, shot: r.shot } : null;
    })
    .filter((x): x is { node: CNode; shot: ShotCard } => !!x);
  if (!shots.length) return { ...base, disabled: "先把白模连到一个镜头（白模 → 镜头，青色控制线）" };

  const one = (x: { node: CNode; shot: ShotCard }): CanvasAction => {
    const { shot } = x;
    const run = shot.director?.run;
    const label = `镜 ${shot.order_no}`;
    const live = s.live.runs[shot.id];
    const busy = (live && !live.done) || s.tasks.some(t => t.kind === "director" && t.remote === shot.id && running(t));
    const disabled = !run || run.box_project_id !== boxId
      ? "这个白模不是该镜导演链搭的；任意白模驱动任意镜头要等后端扩展 render-final（P1）"
      : busy ? `${label}正在出片` : false;
    return {
      id: `film:${shot.id}`, label, disabled,
      title: "按这个白模（含 3D-BOX 里的手改）重出：Blender 预演 → 身份首帧 → LTX 2.5，约 8 分钟",
      run: async () => {
        if (!run) return;
        await cv.directorShot(shot.id, run.scene_id);
        s.track({ key: `director:${shot.id}`, kind: "director", remote: shot.id, nodeId: x.node.id, label: `用白模出片 · ${label}` });
        s.toast(`${label}按白模重出了：预演 → 身份首帧 → 成片，约 8 分钟`, "info", { label: "看镜头", run: () => s.focusNode(x.node.id) });
      },
    };
  };

  if (shots.length === 1) {
    const a = one(shots[0]);
    return { ...base, title: a.title, disabled: a.disabled, run: a.run };
  }
  const items = shots.map(one);
  return {
    ...base,
    disabled: items.every(a => a.disabled) ? items[0].disabled : false,
    title: "连着好几个镜头：选一镜出",
    menu: items,
  };
}

/* ───────────────────────── 写回 3D-BOX ───────────────────────── */

const VIEW_ZH: Record<string, string> = {
  front: "正面", three_quarter_left: "四分之三侧", profile_left: "侧面", back: "背面", bust: "半身", sheet: "设定图",
};

/**
 * 白模人偶的体型。CastMember 不带性别年龄（角色库卡片上的 tags 是后端从英文描述里推的，画布这边拿不到），
 * 只能从 look（服装/外观描述，多为英文）里粗推；推不出就 male。
 * 体型只影响人偶身高胖瘦，放错了在 3D-BOX 里改一个词即可；身份（脸）靠的是 ref，不靠体型。
 */
function bodyOf(m: CastMember): string {
  const t = (m.look ?? "").toLowerCase();
  if (/\b(child|kid|toddler|little (girl|boy))\b|儿童|孩子|女童|男童/.test(t)) return "child";
  if (/\b(teen|teenage|teenager|schoolgirl|schoolboy|adolescent)\b|少年|少女|学生/.test(t)) return "teen";
  if (/\b(old|elderly|aged|grey-haired|gray-haired)\b|老人|老年|白发/.test(t)) return "elder";
  if (/\b(woman|women|girl|female|lady|she|her|dress|skirt)\b|女/.test(t)) return "female";
  return "male";
}

/**
 * 把一个角色放进白模：照 library/Characters.tsx 的 AddToBox —— 在 scene.js 末尾追加一个人偶，
 * ref 用角色库认得的 id（小说角色 = "e:<entity_id>"，见 ainer-core characters.py 的卡片 id；
 * 导演链 render_shot 也按 character_ref=e:<id> 绑定演员）。
 * 已经在白模里（同一个 ref）就不重复加。成功不 toast（调用方自己说「已放进…」）。
 */
export async function addCharacterToBox(s: CanvasStore, boxId: string, member: CastMember, view?: string): Promise<void> {
  try {
    const p = await cv.boxGet(boxId);
    const ref = `e:${member.entity_id}`;
    const objs = p.doc?.objects ?? [];
    if (objs.some(o => o.ref === ref)) return;
    const code = p.files["scene.js"] ?? "";
    // 按场景里已有的人数往旁边错开 1.5 米：别和已有的人（常在原点附近）叠在一起
    const n = objs.filter(o => o.kind === "character").length;
    const from = view ? `（画布 · ${VIEW_ZH[view] ?? view}）` : "（画布）";
    const line = `// 角色库：${member.name}${from}\nS.character(${JSON.stringify(member.name)}, { body: "${bodyOf(member)}", ref: ${JSON.stringify(ref)}, at: [${(n * 1.5).toFixed(1)}, 0], facing: 180 });\n`;
    await cv.boxWriteFile(boxId, "scene.js", `${code.trimEnd()}\n\n${line}`);
  } catch (e) {
    throw boxError(e);
  }
  clearPosters(boxId);
  await s.loadBoxDoc(boxId, true);
}

/**
 * 「搭白模」：新建一个空白 3D-BOX 项目 → 长在源节点右边（ref 线）→ 让智能体按这段剧本搭场景。
 * 返回新白模节点 id。智能体是异步跑的：登记成 box_agent 任务，store 的轮询器看 active_run 清空就算完成。
 */
export async function buildBoxFromText(s: CanvasStore, sourceNodeId: string, title: string, text: string): Promise<string> {
  const name = (title || "白模").trim();
  let nodeId = "";
  try {
    const p = await cv.boxCreate(s.live.chapterTitle ? `${s.live.chapterTitle} · ${name}` : name, "blank");
    nodeId = s.addNode("box3d", { ref: { kind: "box_project", id: p.id }, title: `3D 白模 · ${name}` },
      undefined, { source: sourceNodeId, kind: "ref" });
    // 先把轻量信息拉进 live.boxes，节点才解析得到真身（否则会先闪一下「载入中」）
    await s.loadBoxDoc(p.id, true).catch(() => undefined);
    const body = text.trim().slice(0, ASK_MAX);
    await cv.boxAsk(p.id, `按这段剧本搭场景（人物、站位、动作、机位）：\n${body}`);
    s.track({ key: `box_agent:${p.id}`, kind: "box_agent", remote: p.id, nodeId, label: "搭白模" });
    s.toast("智能体在搭景…（搭好了白模会自己刷新）", "info");
    return nodeId;
  } catch (e) {
    const err = boxError(e);
    throw nodeId ? new Error(`白模建好了，但智能体没叫起来：${err.message}`, { cause: e }) : err;
  }
}

/** Dock 对白模节点发话：让 3D-BOX 智能体按这句话改景（只走 /scene3d/…/agent 这一个真源，见调研 critic §C） */
export async function askBox(s: CanvasStore, nodeId: string, boxId: string, message: string): Promise<void> {
  const msg = message.trim().slice(0, ASK_MAX);
  if (!msg) return;
  try {
    await cv.boxAsk(boxId, msg);
  } catch (e) {
    throw boxError(e);
  }
  s.track({ key: `box_agent:${boxId}`, kind: "box_agent", remote: boxId, nodeId, label: "改白模" });
  s.toast("智能体在改景…（改好了白模会自己刷新）", "info");
}

/**
 * 重新生成 3D 白模：优先按关联镜头的剧本要求通过 Director LLM Planner 重新规划并写入，
 * 如果是未连镜头的白模，则让 3D-BOX 智能体按要求重新搭景。
 */
export async function regenerateBox(s: CanvasStore, node: CNode, instruction?: string): Promise<void> {
  const boxId = boxIdOf(node);
  if (!boxId) return;

  // 找相连的镜头（优先通过 downstream control 线，或者通过 board 中的 director.run.box_project_id）
  const downShots = s.downstream(node.id)
    .filter(d => d.edge.data?.kind === "control" && d.node.data.ref.kind === "shot");
  const linkedShotId = downShots[0]?.node?.data?.ref?.id
    ?? s.live.board?.shots.find(sh => sh.director?.run?.box_project_id === boxId)?.id;

  s.track({ key: `box_agent:${boxId}`, kind: "box_agent", remote: boxId, nodeId: node.id, label: "重新搭景" });
  s.toast("智能体正在重新规划与搭景…", "info");

  try {
    if (linkedShotId) {
      await cv.directorPlanScene(linkedShotId, instruction);
    } else {
      await cv.boxRegenerate(boxId, instruction);
    }
    clearPosters(boxId);
    await s.loadBoxDoc(boxId, true);
    void s.reloadLive();
    s.toast("3D 白模已重新生成！", "ok");
  } catch (e) {
    throw boxError(e);
  }
}

/* ───────────────────────── 轮询器回调 ───────────────────────── */

/**
 * Blender 渲完：每一路（预演/白模/深度/骨架/边缘）长一个视频节点，竖着排在白模右边，青色控制线连回白模。
 * 节点 ref 用产物落库后的 Asset（自由节点，media 进文档；地址是 /media 同源的稳定地址）——
 * 不用 director_output：派生节点存档时只留 ref，现取又没有「按产物查」的接口，重载后会变成失效节点。
 */
export function onBlenderDone(s: CanvasStore, task: TrackedTask, job: Job): void {
  const outs = PASSES
    .map(p => ({ pass: p, out: (job.outputs ?? []).find((o: JobOutput) => o.kind === p.id) }))
    .filter((x): x is { pass: (typeof PASSES)[number]; out: JobOutput } => !!x.out?.url);
  if (!outs.length) {
    s.toast("控制素材渲完了，但没拿到可用的产物（看看 3D-BOX 的渲染面板）", "err");
    return;
  }
  const boxNode = s.nodes.find(n => n.id === task.nodeId) ?? null;
  const rp = (job.input?.render_plan ?? {}) as { output_resolution?: number[] };
  const [w, h] = rp.output_resolution ?? [1024, 576];
  const dur = typeof job.input?.duration === "number" ? job.input.duration : null;
  const cardH = Math.round(280 * (h / w)) + 52; // 视频节点宽 280 + 底下两行描述
  const slots = boxNode
    ? freeRow(s, boxNode.position.x + (boxNode.measured?.width ?? 300) + 60, boxNode.position.y, 280, cardH, outs.length)
    : [];
  // 后台任务渲完不抢选中：addNode 会选中新节点，长完把选中还给当时选着的那个（Dock 不会突然跳成别的节点）
  const keep = s.selectedId;

  const made: string[] = [];
  for (const [i, { pass, out }] of outs.entries()) {
    const ref = out.asset_id ? { kind: "asset" as const, id: out.asset_id } : { kind: "free" as const, id: `dout-${job.id}-${pass.id}` };
    const id = nodeIdOf(ref);
    if (s.nodes.some(n => n.id === id)) { made.push(id); continue; } // 轮询器重放同一个任务时别长两遍
    const mediaRef: MediaRef = { url: sameOrigin(out.url), asset_id: out.asset_id, mime: mimeOf(out.url), w, h, duration: dur };
    made.push(s.addNode("video", {
      ref, title: pass.id === "preview" ? "Blender 预演" : `控制素材 · ${pass.zh}`,
      role: pass.id === "preview" ? "previs" : "control", media: mediaRef,
    }, slots[i], boxNode ? { source: boxNode.id, kind: "control" } : undefined));
  }
  s.select(keep);
  const go = made[0];
  s.toast(`控制素材渲好了：${outs.map(o => o.pass.zh).join(" / ")}`, "ok", go ? { label: "看看", run: () => s.focusNode(go) } : undefined);
}

/** 智能体搭景/改景结束：海报作废、重拉场景 */
export function onBoxAgentDone(s: CanvasStore, task: TrackedTask): void {
  clearPosters(task.remote);
  void s.loadBoxDoc(task.remote, true).catch(() => undefined);
  s.toast("白模更新了", "ok", { label: "看看", run: () => { s.focusNode(task.nodeId); s.select(task.nodeId); } });
}
