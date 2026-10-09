/**
 * 把「现取的后端数据」铺成画布：派生节点全集、自动布局、与保存过的文档合并。
 *
 * 纯函数，不碰 React、不碰网络：store 载入、刷新 board、整理时都调这里。
 * 节点 data 里只放 ref/title/role 这类「指针」，真身每次用 resolveRef 现取 ——
 * 这样 board 每 6 秒刷新一次也不用重建 nodes 数组（200+ 镜时节点组件 memo 才拦得住）。
 */
import type { XYPosition } from "@xyflow/react";
import { media } from "./api";
import type { CastMember, ShotCard } from "../types";
import {
  isDerived, isProductionRef, nodeIdOf,
  type CanvasDoc, type CEdge, type CNode, type CNodeData, type EdgeKind, type LiveSources, type NodeKind,
  type NodeRef, type Resolved, type ScriptScene,
} from "./model";

/* ───────────────────────── 尺寸与布局常量（px） ───────────────────────── */

/**
 * 各类节点的估计外框：节点还没被 xyflow 量过（刚建、或离屏没渲染）时，布局和找空位用它。
 * 宽度与 nodes/* 实际渲染的宽度一致；高度是常见内容的估值。
 */
const EST: Record<string, { w: number; h: number }> = {
  story: { w: 260, h: 200 },
  scene: { w: 300, h: 290 },
  note: { w: 260, h: 120 },
  prompt: { w: 260, h: 120 },
  character: { w: 150, h: 200 },
  sheet: { w: 300, h: 150 },
  image: { w: 220, h: 170 },
  video: { w: 280, h: 210 },
  stage: { w: 300, h: 300 }, coverage: { w: 300, h: 300 }, box3d: { w: 300, h: 230 },
};

export function estimateSize(type: NodeKind | undefined, role?: string): { w: number; h: number } {
  if (role && EST[role] && (type === "text" || type === "image")) return EST[role];
  if (type === "text") return EST.note;
  if (type === "image") return EST.image;
  if (type === "video") return EST.video;
  if (type === "audio") return { w: 300, h: 110 };
  if (type === "box3d") return EST.box3d;
  return EST.image;
}

const BAND_X = 340;       // 角色带从 x=340 起（左边是故事梗概）
const BAND_GAP = 48;   // 标题在卡片上方、和卡片等宽省略；间距太窄时相邻两张的标题读起来像连在一起
const LANE_GAP = 120;     // 角色带与场景泳道、泳道与泳道之间
const SHOT_X = 400;       // 场景文字节点宽 300，镜头从 x=400 起
const SHOT_W = 280;
const SHOT_GAP = 40;
/**
 * 每行几个镜头：按最大一场的镜头数开方，夹在 4–10 之间，全图统一（列对齐好读）。
 * 固定 4 个的话，一章 200 多镜会排成一根细长条，全图缩到 5% 还是一条线。
 */
const perRowOf = (maxLane: number) => Math.max(4, Math.min(10, Math.ceil(Math.sqrt(maxLane * 0.9))));
const ROW_H = 260;
/**
 * 一行镜头里有白模时，白模放在镜头正上方占的额外高度。
 * 规格写 +220，但白模节点（300 宽 16:9 画面 + 底部时间轴）实测约 210 高，
 * 再加镜头节点上方 22px 的标题会压到一起，所以放宽到 250。
 */
export const BOX_ABOVE = 250;

/* ───────────────────────── 派生节点全集 ───────────────────────── */

interface DerivedNode { id: string; type: NodeKind; data: CNodeData }
interface Lane { sceneId: string | null; shots: ShotCard[] }

/** 编号统一从 1 起：后端 order_no 有的从 0 有的从 1 */
function numberer(orders: number[]): (n: number) => number {
  const min = orders.length ? Math.min(...orders) : 1;
  return n => (min <= 0 ? n + 1 : n);
}

/** 每个镜头关联的白模（导演链搭的 3D-BOX 项目） */
const boxOf = (s: ShotCard): string | null => s.director?.run?.box_project_id || null;

/**
 * 这张画布范围内的镜头和出场人物（live.scope 为 null = 整章总览，全部）。
 * 一章拆成几张场次画布后，每张只摆自己那几镜、那几个人 —— 镜头编号仍按整章算，和分镜画布对得上。
 */
function inScope(live: LiveSources): { shots: ShotCard[]; cast: CastMember[]; scoped: boolean } {
  const { shotIds, castIds } = live.scope;
  const shots = live.board?.shots ?? [];
  return {
    shots: shotIds ? shots.filter(s => shotIds.has(s.id)) : shots,
    cast: castIds ? live.cast.filter(m => castIds.has(m.entity_id)) : live.cast,
    scoped: shotIds !== null,
  };
}

/**
 * 场景泳道：有剧本按剧本场次（任意版本都能对上 shots[].scene_id）；
 * board 里有、剧本里没有但挂着镜头的场次也补一条（id 对不上时不至于把镜头全扔进「未分场」）；
 * 没剧本就用 board.scenes。归属不到任何场次的镜头放最后的「未分场」泳道。
 */
function lanesOf(live: LiveSources): Lane[] {
  const board = live.board;
  if (!board) return [];
  const scope = inScope(live);
  const shots = [...scope.shots].sort((a, b) => a.order_no - b.order_no);
  const scenes: { id: string; order: number; script: boolean }[] = live.script.map(s => ({ id: s.id, order: s.order_no, script: true }));
  const inScript = new Set(scenes.map(s => s.id));
  const withShots = new Set(shots.map(s => s.scene_id).filter(Boolean) as string[]);
  for (const sc of board.scenes) {
    if (inScript.has(sc.id)) continue;
    if (live.script.length && !withShots.has(sc.id)) continue;
    scenes.push({ id: sc.id, order: sc.order_no, script: false });
  }
  scenes.sort((a, b) => a.order - b.order || Number(b.script) - Number(a.script));
  const known = new Set(scenes.map(s => s.id));
  const lanes: Lane[] = scenes.map(s => ({ sceneId: s.id, shots: shots.filter(x => x.scene_id === s.id) }));
  const loose = shots.filter(x => !x.scene_id || !known.has(x.scene_id));
  if (loose.length) lanes.push({ sceneId: null, shots: loose });
  // 场次画布只要自己那几场；整章总览连没镜头的场次也摆出来（看得到这一章讲了什么）
  return scope.scoped ? lanes.filter(l => l.shots.length) : lanes;
}

/** 角色定妆照用哪个视角：正面 → 四分之三侧 → 半身，第一个有图的；都没有就挂正面（节点显示「图挂了」） */
const PORTRAIT_VIEWS = ["front", "three_quarter_left", "bust"] as const;

function storyRef(live: LiveSources): NodeRef | null {
  const b = live.board;
  if (!b) return null;
  return { kind: "story", id: b.chapter?.id ?? b.plan.id };
}

export function derivedGraph(live: LiveSources): { nodes: DerivedNode[]; edges: CEdge[]; lanes: Lane[] } {
  const nodes: DerivedNode[] = [];
  const edges: CEdge[] = [];
  const board = live.board;
  if (!board) return { nodes, edges, lanes: [] };
  const scope = inScope(live);
  // 用户自建空白画布或无镜头范围的自由画布，不自动注入任何派生节点（如故事梗概、全章人物）
  if (scope.scoped && scope.shots.length === 0) {
    return { nodes, edges, lanes: [] };
  }
  const push = (type: NodeKind, data: CNodeData) => nodes.push({ id: nodeIdOf(data.ref), type, data });
  const edge = (source: string, target: string, kind: EdgeKind) =>
    edges.push({ id: `d:${source}>${target}`, source, target, type: "glow", data: { kind, derived: true }, deletable: false });

  const story = storyRef(live)!;
  push("text", { ref: story, title: "故事梗概", role: "story" });

  for (const m of inScope(live).cast) {
    const view = PORTRAIT_VIEWS.find(v => m.views[v]) ?? "front";
    push("image", { ref: { kind: "entity_view", id: m.entity_id, view }, title: `定妆照 · ${m.name}`, role: "character" });
    if (m.views.sheet) {
      push("image", { ref: { kind: "entity_view", id: m.entity_id, view: "sheet" }, title: `多角度定妆照 · ${m.name}`, role: "sheet" });
    }
  }

  const lanes = lanesOf(live);
  const sceneNo = numberer([...live.script.map(s => s.order_no), ...board.scenes.map(s => s.order_no)]);
  const sceneOrder = new Map<string, number>([
    ...board.scenes.map(s => [s.id, s.order_no] as const),
    ...live.script.map(s => [s.id, s.order_no] as const),
  ]);
  const shotNo = numberer(board.shots.map(s => s.order_no));
  const boxDone = new Set<string>();
  for (const lane of lanes) {
    const sceneNode = lane.sceneId ? nodeIdOf({ kind: "scene", id: lane.sceneId }) : null;
    if (lane.sceneId) {
      push("text", { ref: { kind: "scene", id: lane.sceneId }, title: `场景 ${sceneNo(sceneOrder.get(lane.sceneId) ?? 0)}`, role: "scene" });
    }
    for (const s of lane.shots) {
      const shotNode = nodeIdOf({ kind: "shot", id: s.id });
      push("video", { ref: { kind: "shot", id: s.id }, title: `镜头 ${shotNo(s.order_no)}`, role: "shot" });
      if (sceneNode) edge(sceneNode, shotNode, "flow");
      const box = boxOf(s);
      if (box) {
        const boxNode = nodeIdOf({ kind: "box_project", id: box });
        // 同一个白模被几镜共用时只出一个节点（同一真身一个节点），控制线连到每一镜
        if (!boxDone.has(box)) {
          boxDone.add(box);
          push("box3d", { ref: { kind: "box_project", id: box }, title: `3D 白模 · 镜 ${shotNo(s.order_no)}` });
        }
        edge(boxNode, shotNode, "control");
      }
    }
  }
  return { nodes, edges, lanes };
}

/* ───────────────────────── 自动布局 ───────────────────────── */

/** 派生节点的自动布局位置（自由节点不在里面）。relayout 与新长出来的派生节点用它。 */
export function autoLayout(live: LiveSources): Map<string, XYPosition> {
  const pos = new Map<string, XYPosition>();
  const board = live.board;
  if (!board) return pos;
  const { lanes } = derivedGraph(live);

  const story = storyRef(live)!;
  pos.set(nodeIdOf(story), { x: 0, y: 0 });
  let x = BAND_X;
  let bandH = EST.story.h;
  for (const m of inScope(live).cast) {
    const view = PORTRAIT_VIEWS.find(v => m.views[v]) ?? "front";
    pos.set(nodeIdOf({ kind: "entity_view", id: m.entity_id, view }), { x, y: 0 });
    x += EST.character.w + BAND_GAP;
    bandH = Math.max(bandH, EST.character.h);
    if (m.views.sheet) {
      pos.set(nodeIdOf({ kind: "entity_view", id: m.entity_id, view: "sheet" }), { x, y: 0 });
      x += EST.sheet.w + BAND_GAP;
      bandH = Math.max(bandH, EST.sheet.h);
    }
  }

  // 白模跟它第一次出现的那一镜走
  const boxHome = new Map<string, string>();
  for (const s of [...board.shots].sort((a, b) => a.order_no - b.order_no)) {
    const b = boxOf(s);
    if (b && !boxHome.has(b)) boxHome.set(b, s.id);
  }

  const PER_ROW = perRowOf(Math.max(0, ...lanes.map(l => l.shots.length)));
  let y = bandH + LANE_GAP;
  for (const lane of lanes) {
    if (lane.sceneId) pos.set(nodeIdOf({ kind: "scene", id: lane.sceneId }), { x: 0, y });
    let rowY = y;
    for (let i = 0; i < lane.shots.length; i += PER_ROW) {
      const row = lane.shots.slice(i, i + PER_ROW);
      const hasBox = row.some(s => { const b = boxOf(s); return b !== null && boxHome.get(b) === s.id; });
      const shotY = rowY + (hasBox ? BOX_ABOVE : 0);
      row.forEach((s, c) => {
        const sx = SHOT_X + c * (SHOT_W + SHOT_GAP);
        pos.set(nodeIdOf({ kind: "shot", id: s.id }), { x: sx, y: shotY });
        const b = boxOf(s);
        if (b && boxHome.get(b) === s.id) pos.set(nodeIdOf({ kind: "box_project", id: b }), { x: sx, y: rowY });
      });
      rowY = shotY + ROW_H;
    }
    const laneH = Math.max(rowY - y, lane.sceneId ? EST.scene.h : 0);
    y += laneH + LANE_GAP;
  }
  return pos;
}

/** 首屏 fitView 的范围：前两场（场景文字 + 它们的镜头和白模）；没有场次就是 null（看全部） */
export function introNodeIds(live: LiveSources): string[] | null {
  const { lanes } = derivedGraph(live);
  const first = lanes.slice(0, 2);
  if (!first.length) return null;
  const ids: string[] = [];
  for (const lane of first) {
    if (lane.sceneId) ids.push(nodeIdOf({ kind: "scene", id: lane.sceneId }));
    for (const s of lane.shots) {
      ids.push(nodeIdOf({ kind: "shot", id: s.id }));
      const b = boxOf(s);
      if (b) ids.push(nodeIdOf({ kind: "box_project", id: b }));
    }
  }
  return ids;
}

/* ───────────────────────── 现取真身 ───────────────────────── */

const MISSING: Resolved = { kind: "missing" };

/** 场次对不上剧本时退到 board.scenes：只有标题、地点、时间，没有正文 */
function sceneFromBoard(live: LiveSources, id: string): ScriptScene | null {
  const sc = live.board?.scenes.find(s => s.id === id);
  if (!sc) return null;
  return { id: sc.id, order_no: sc.order_no, title: sc.title, time_of_day: sc.time_of_day, location_text: sc.location, summary: null, blocks: [] };
}

/**
 * 章节梗概：后端没有章节级梗概字段，用剧本各场的 summary 拼；
 * 剧本也没有就列场次标题（至少让人知道这一章讲哪几场）。
 */
function storyText(live: LiveSources): string {
  const withSummary = live.script.filter(s => s.summary?.trim());
  if (withSummary.length) return withSummary.map(s => s.summary!.trim()).join("\n");
  const scenes = live.board?.scenes ?? [];
  return scenes.map(s => [s.title, s.location, s.time_of_day].filter(Boolean).join(" · ")).filter(Boolean).join("\n");
}

const safeMedia = <T extends { url: string }>(m: T): T => {
  const url = m.url.startsWith("data:") ? m.url : media(m.url) ?? m.url;
  return url === m.url ? m : { ...m, url };
};

/** 节点真身：派生节点从 live 里找，自由节点读 data。找不到 = missing（节点标 orphan） */
export function resolveRef(live: LiveSources, ref: NodeRef, data?: CNodeData): Resolved {
  if (isProductionRef(ref)) {
    const item = live.resources?.[nodeIdOf(ref)];
    if (item?.status === "resolved" && item.resource && (ref.kind === "stage" || ref.kind === "coverage")) {
      return { kind: "stage_resource", resource: item.resource };
    }
    if (item?.status === "resolved" && item.resource?.media?.url) {
      return { kind: "media", media: safeMedia(item.resource.media) };
    }
    return { kind: "missing", reason: item?.issues?.map(i => i.message).join("；") || "正在读取原素材…" };
  }
  switch (ref.kind) {
    case "story": {
      if (!live.board) return MISSING;
      return { kind: "story", title: live.chapterTitle || live.board.chapter?.title || "", text: storyText(live) };
    }
    case "scene": {
      const sc = live.script.find(s => s.id === ref.id) ?? sceneFromBoard(live, ref.id);
      return sc ? { kind: "scene", scene: sc } : MISSING;
    }
    case "shot": {
      const shot = live.board?.shots.find(s => s.id === ref.id);
      return shot ? { kind: "shot", shot, run: live.runs[ref.id] ?? null } : MISSING;
    }
    case "entity_view": {
      const member = live.cast.find(m => m.entity_id === ref.id);
      if (!member) return MISSING;
      return { kind: "entity_view", member, url: media(member.views[ref.view] ?? null) ?? null, voice: live.voices[ref.id] ?? null };
    }
    case "box_project": {
      const box = live.boxes[ref.id];
      return box ? { kind: "box_project", box } : MISSING;
    }
    case "director_output":
    case "asset":
      return data?.media?.url ? { kind: "media", media: safeMedia(data.media) } : MISSING;
    case "free":
      // 自由节点内容就在自己身上：还没出图的生成占位、空便签都不算「失效」
      if (data?.media?.url) return { kind: "media", media: safeMedia(data.media) };
      return { kind: "text", text: data?.text ?? "" };
    default: return MISSING;
  }
}

/** 真身的纯文字（搭白模、按这段改景、搜索、文字参考拼提示词都用它） */
export function resolvedText(r: Resolved): string {
  switch (r.kind) {
    case "story": return [r.title, r.text].filter(Boolean).join("\n");
    case "scene": {
      const sc = r.scene;
      const head = [sc.title, sc.time_of_day, sc.location_text].filter(Boolean).join("－");
      const body = sc.blocks
        .filter(b => b.text.trim() && b.type !== "heading" && b.type !== "scene_break")
        .map(b => (b.type === "dialogue" && b.speaker ? `${b.speaker}：${b.text}` : b.text));
      return [head, ...(body.length ? body : sc.summary ? [sc.summary] : [])].filter(Boolean).join("\n");
    }
    case "shot": return r.shot.description ?? "";
    case "text": return r.text;
    case "entity_view": return [r.member.name, r.member.look].filter(Boolean).join("：");
    case "box_project": return r.box.title;
    default: return "";
  }
}

/* ───────────────────────── 几何：找空位 ───────────────────────── */

interface Rect { x: number; y: number; w: number; h: number }

/** 节点占的矩形（含卡片上方 22px 的标题），量过就用量的，没量过用估计值 */
export function rectOf(n: CNode): Rect {
  const est = estimateSize(n.type, n.data.role);
  const w = n.measured?.width ?? n.width ?? est.w;
  const h = n.measured?.height ?? n.height ?? est.h;
  return { x: n.position.x, y: n.position.y - 24, w, h: h + 24 };
}

const hits = (a: Rect, b: Rect, pad: number) =>
  a.x < b.x + b.w + pad && a.x + a.w + pad > b.x && a.y < b.y + b.h + pad && a.y + a.h + pad > b.y;

/** 从 at 起同一列往下找一个不压住任何已有节点的位置 */
export function findFreeSpot(nodes: CNode[], at: XYPosition, size: { w: number; h: number }): XYPosition {
  const rects = nodes.map(rectOf);
  let y = at.y;
  for (let i = 0; i < 400; i++) {
    const r: Rect = { x: at.x, y: y - 24, w: size.w, h: size.h + 24 };
    const blocker = rects.find(o => hits(r, o, 20));
    if (!blocker) return { x: at.x, y };
    y = blocker.y + blocker.h + 24 + 36;
  }
  return { x: at.x, y };
}

/* ───────────────────────── 建图与合并 ───────────────────────── */

function makeNode(id: string, type: NodeKind, position: XYPosition, data: CNodeData, size?: { width?: number; height?: number }): CNode {
  const n: CNode = { id, type, position: { x: position.x, y: position.y }, data };
  if (size?.width) n.width = size.width;
  if (size?.height) n.height = size.height;
  return n;
}

const pairKey = (source: string, target: string) => `${source}>${target}`;

/**
 * 载入时建图：派生全集 × 保存的文档。
 *   - 保存过的节点用保存的位置和 data（ref 以现算的为准，防止旧文档 ref 写坏）
 *   - hidden 里的派生节点不出
 *   - 保存了但真身找不到的派生节点保留并标 orphan（分镜重编译后的旧镜头等，给人看见、自己决定删不删）
 *   - 新出现的派生节点用自动布局位置
 *   - 保存的用户边两端都在才接；与派生边重复的不接
 */
export function buildGraph(live: LiveSources, saved: CanvasDoc | null): { nodes: CNode[]; edges: CEdge[]; viewport: CanvasDoc["viewport"] | null } {
  const d = derivedGraph(live);
  const pos = autoLayout(live);
  const hidden = new Set(saved?.hidden ?? []);
  const savedById = new Map((saved?.nodes ?? []).filter(n => n?.id && n.data?.ref).map(n => [n.id, n]));
  const nodes: CNode[] = [];
  const present = new Set<string>();

  for (const dn of d.nodes) {
    if (hidden.has(dn.id)) continue;
    const sn = savedById.get(dn.id);
    const data: CNodeData = sn ? { ...dn.data, ...sn.data, ref: dn.data.ref } : dn.data;
    delete data.orphan;
    nodes.push(makeNode(dn.id, dn.type, sn?.position ?? pos.get(dn.id) ?? { x: 0, y: 0 }, data, sn));
    present.add(dn.id);
  }
  for (const sn of savedById.values()) {
    if (present.has(sn.id) || hidden.has(sn.id)) continue;
    const data: CNodeData = { ...(sn.data as CNodeData) };
    if ((isDerived(data.ref) || isProductionRef(data.ref)) && resolveRef(live, data.ref, data).kind === "missing") data.orphan = true;
    else delete data.orphan;
    nodes.push(makeNode(sn.id, sn.type, sn.position ?? { x: 0, y: 0 }, data, sn));
    present.add(sn.id);
  }

  const edges: CEdge[] = [];
  const pairs = new Set<string>();
  for (const e of d.edges) {
    if (!present.has(e.source) || !present.has(e.target)) continue;
    edges.push(e);
    pairs.add(pairKey(e.source, e.target));
  }
  for (const se of saved?.edges ?? []) {
    if (!se?.id || se.data?.derived) continue;
    if (!present.has(se.source) || !present.has(se.target) || se.source === se.target) continue;
    const k = pairKey(se.source, se.target);
    if (pairs.has(k)) continue;
    pairs.add(k);
    edges.push({
      id: se.id, source: se.source, target: se.target, type: "glow",
      sourceHandle: se.sourceHandle ?? null, targetHandle: se.targetHandle ?? null,
      data: { kind: se.data?.kind ?? "ref" },
    });
  }
  return { nodes, edges, viewport: saved?.viewport ?? null };
}

/**
 * board/cast 刷新后的增量同步（不重建整张图）：
 *   - 新出现的派生节点长出来（白模长在它那一镜正上方，其余按自动布局位置，压到东西就往下挪）
 *   - 派生节点的 orphan 标记按现取结果翻转
 *   - 派生边按新关系增删（重新搭景换了白模，旧的控制线就断开；旧白模节点本身留着当历史版本）
 * 没有任何变化返回 null，调用方就不必 setState。
 */
export function syncDerived(live: LiveSources, nodes: CNode[], edges: CEdge[], hidden: Set<string>): { nodes: CNode[]; edges: CEdge[]; added: number } | null {
  if (!live.board) return null;
  const d = derivedGraph(live);
  let changed = false;
  let added = 0;
  const out: CNode[] = nodes.map(n => {
    if (!isDerived(n.data.ref)) return n;
    const orphan = resolveRef(live, n.data.ref, n.data).kind === "missing";
    if (Boolean(n.data.orphan) === orphan) return n;
    changed = true;
    const data = { ...n.data };
    if (orphan) data.orphan = true; else delete data.orphan;
    return { ...n, data };
  });
  const have = new Map(out.map(n => [n.id, n]));
  let pos: Map<string, XYPosition> | null = null;
  for (const dn of d.nodes) {
    if (have.has(dn.id) || hidden.has(dn.id)) continue;
    pos ??= autoLayout(live);
    let at = pos.get(dn.id) ?? { x: 0, y: 0 };
    if (dn.type === "box3d") {
      const shot = d.edges.find(e => e.source === dn.id && have.has(e.target));
      const sn = shot ? have.get(shot.target)! : null;
      if (sn) at = { x: sn.position.x, y: sn.position.y - BOX_ABOVE };
    }
    const size = estimateSize(dn.type, dn.data.role);
    const n = makeNode(dn.id, dn.type, findFreeSpot(out, at, size), dn.data);
    out.push(n);
    have.set(n.id, n);
    added++;
    changed = true;
  }

  const want = new Map(d.edges.filter(e => have.has(e.source) && have.has(e.target)).map(e => [e.id, e]));
  const outEdges = edges.filter(e => !e.data?.derived || want.has(e.id));
  if (outEdges.length !== edges.length) changed = true;
  const ids = new Set(outEdges.map(e => e.id));
  const pairs = new Set(outEdges.map(e => pairKey(e.source, e.target)));
  for (const e of want.values()) {
    if (ids.has(e.id) || pairs.has(pairKey(e.source, e.target))) continue;
    outEdges.push(e);
    changed = true;
  }
  return changed ? { nodes: out, edges: outEdges, added } : null;
}
