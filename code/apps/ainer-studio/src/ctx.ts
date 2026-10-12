/**
 * 地址栏上下文：所有视图（分镜画布、创作画布、3D-BOX、角色库、风格广场）共用一套参数，顶部 Nav 切换时原样带过去。
 *
 *   view      当前视图
 *   novel / chapter / plan   书、章、分镜计划
 *   canvas    当前创作画布（板）
 *   shot      当前镜头（取代旧的 focus，focus 继续兼容读取）
 *   box       白模项目
 *   char      角色卡（e:<实体id> 或 preset id）
 *   from      3D-BOX 编辑器「←」回哪个视图
 *
 * 换上级时级联清空下级：换书清章/计划/画布/镜头，换章清计划/画布/镜头，换计划清画布/镜头。
 * 不然地址栏会残留上一章的 plan，风格广场「套用到当前分镜」就套错计划。
 */
import { stageOfView, type View } from "./Nav";

export type CtxKey = "view" | "stage" | "project" | "novel" | "chapter" | "plan" | "canvas" | "shot" | "box" | "char" | "from" | "locale" | "medium" | "production" | "workspace" | "hub";
export type Ctx = Record<CtxKey, string | null>;
export type CtxPatch = Partial<Record<CtxKey, string | null>>;

const KEYS: CtxKey[] = ["view", "stage", "project", "novel", "chapter", "plan", "canvas", "shot", "box", "char", "from", "locale", "medium", "production", "workspace", "hub"];

// 换上级清下级。注意 stage 不在表里：切阶段是带着同一上下文走，不是换上下文（planA.md §2）
const CASCADE: Partial<Record<CtxKey, CtxKey[]>> = {
  project: ["novel", "chapter", "plan", "canvas", "shot", "char", "box", "production"],
  novel: ["chapter", "plan", "canvas", "shot", "char", "box", "production"],
  chapter: ["plan", "canvas", "shot", "char", "box", "production"],
  plan: ["canvas", "shot"],
};

/** 现读地址栏（每次挂载时读，不能在模块级缓存：Nav 用 pushState 切视图不会重新加载模块） */
export function readCtx(): Ctx {
  const q = new URLSearchParams(location.search);
  const out = {} as Ctx;
  for (const k of KEYS) out[k] = q.get(k) || null;
  out.shot = out.shot ?? (q.get("focus") || null);
  out.workspace = out.workspace === "free" ? "free" : "novel";
  if (out.workspace === "free") {
    for (const k of ["project", "novel", "chapter", "plan", "shot", "char", "production"] as CtxKey[]) out[k] = null;
    out.medium = "video";
    if(!['flow','box','styles','hub'].includes(out.view||''))out.view='flow';
    if(out.view==='hub'&&!['tasks','settings','library','prompts'].includes(out.hub||''))out.view='flow';
    return out;
  }
  if (out.medium === "comic" || out.view === "comic" || out.view === "comic-assets") {
    out.medium = "comic";
    for (const k of ["plan", "shot", "char"] as CtxKey[]) out[k] = null;
    if(out.view!=="box")out.box=null;
  }
  return out;
}

/** 在 params 上应用 patch：值变了的上级把下级清掉（patch 里同时给了的下级以 patch 为准） */
function apply(q: URLSearchParams, patch: CtxPatch) {
  for (const [k, v] of Object.entries(patch) as [CtxKey, string | null | undefined][]) {
    if (v === undefined) continue;
    const old = q.get(k);
    if (v) q.set(k, v); else q.delete(k);
    if (old && old !== v) {
      for (const d of CASCADE[k] ?? []) if (!(d in patch)) q.delete(d);
    }
  }
  if ("shot" in patch) q.delete("focus");
}

/** 写回地址栏（replaceState，不进历史）；值为 null 删掉 */
export function writeCtx(patch: CtxPatch) {
  const u = new URL(location.href);
  const before = u.search;
  apply(u.searchParams, patch);
  if (u.search !== before) {
    history.replaceState(history.state, "", u);
    window.dispatchEvent(new Event("studio:context"));
  }
}

/** 在当前上下文基础上合并 patch，生成去某个视图的地址 */
export function hrefFor(view: View, patch: CtxPatch = {}): string {
  const u = new URL(location.href);
  const oldMedium = u.searchParams.get("medium") || (u.searchParams.get("view")?.startsWith("comic") ? "comic" : "video");
  const nextMedium = "medium" in patch ? patch.medium || "video" : view === "comic" || view === "comic-assets" ? "comic" : ["translation", "flow", "canvas", "box", "hub"].includes(view) ? oldMedium : "video";
  if (nextMedium !== oldMedium) {
    for (const k of ["plan", "canvas", "shot", "char", "box", "production", "focus"]) u.searchParams.delete(k);
  }
  if (nextMedium === "comic") for (const k of ["plan", "shot", "char", "box", "focus"]) u.searchParams.delete(k);
  u.searchParams.set("medium", nextMedium);
  apply(u.searchParams, { ...patch, view, stage: stageOfView(view) });
  // 换视图时 3D-BOX 专用的参数不跟着走（除非明确给了）
  if (view !== "box") {
    if (!("box" in patch)) u.searchParams.delete("box");
    if (!("from" in patch)) u.searchParams.delete("from");
  }
  return `${u.pathname}${u.search}`;
}

/** 应用内跳转：pushState 后派发 popstate（Root 在听），不整页刷新 */
export function navigate(view: View, patch: CtxPatch = {}) {
  history.pushState(null, "", hrefFor(view, patch));
  window.dispatchEvent(new PopStateEvent("popstate"));
}
