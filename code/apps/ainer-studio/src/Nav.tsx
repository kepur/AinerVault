/**
 * 顶部导航：故事与翻译 / 角色与素材 / 画布与导演 / 漫剧与成片。
 *
 * 阶段是分组，不是新视图：现有的 5 个视图降为阶段里的面板，`?view=` 原样保留，老深链照旧能开。
 * `?stage=` 只是显示用的分组标记；没给时由 view 反推，所以不带 stage 的旧链接也落在对的阶段上。
 *
 * 切阶段**不清**任何上下文 ID —— A→B→C 的意义就是带着同一本书、同一章、同一画布走（契约 §2）。
 */
import { readCtx, type CtxPatch } from "./ctx";

export type View = "canvas" | "flow" | "box" | "characters" | "styles" | "translation" | "comic" | "comic-assets" | "hub";
export type Stage = "a" | "b" | "c" | "d";

export const VIEWS: { id: View; label: string }[] = [
  { id: "hub", label: "制作总览" },
  { id: "translation", label: "翻译工作台" },
  { id: "canvas", label: "分镜管理" },
  { id: "flow", label: "无限画布" },
  { id: "box", label: "3D-BOX 预演" },
  { id: "characters", label: "角色库" },
  { id: "styles", label: "风格广场" },
  { id: "comic", label: "动态漫剧" },
  { id: "comic-assets", label: "漫剧人物与素材" },
];

export interface StageDef {
  id: Stage;
  label: string;
  hint: string;
  /** 这个阶段里的面板；空数组 = 本批还没有前端面板，只能去后台 */
  views: View[];
  /** 后台对应页面：没有前端面板时点阶段就去后台 */
  adminPage?: string;
}

export const STAGES: StageDef[] = [
  { id: "a", label: "故事与翻译", hint: "原文、文化映射、译文对照与定稿", views: ["translation"], adminPage: "chapter" },
  { id: "b", label: "角色与素材", hint: "角色、道具、地点、造型与标准素材", views: ["characters", "styles"] },
  { id: "c", label: "画布与导演", hint: "自由创作、舞台、机位与章节分镜", views: ["flow", "canvas", "box"] },
  { id: "d", label: "漫剧与成片", hint: "声音优先、镜头路由、2D 合成与导出", views: ["comic"], adminPage: "handoff" },
];

const STAGE_OF: Record<View, Stage> = {
  hub: "a",
  translation: "a", comic: "d", "comic-assets": "b",
  characters: "b", styles: "b",
  canvas: "c", flow: "c", box: "c",
};

/** 没写 stage 时按当前面板反推，保证旧链接落在对的阶段 */
export function stageOfView(view: View): Stage {
  return STAGE_OF[view] ?? "c";
}

export function stageDef(id: Stage): StageDef {
  return STAGES.find(s => s.id === id) ?? STAGES[2];
}

/**
 * 另一个后台（/admin）的地址：带上当前小说、章节、分镜计划和镜头，按视图落到对应页面
 * （分镜画布 → 分镜全景，创作画布 → 章节工作台，角色库 → 世界模型）。
 * 画布换书换章只改地址栏（replaceState），所以点的那一刻现取，不能在渲染时算好。
 */
const ADMIN_PAGE: Partial<Record<View, string>> = { translation: "prose", comic: "production", "comic-assets": "production", canvas: "storyboard", flow: "production", characters: "model", box: "production" };

export function adminHref(page?: string | null): string {
  const c = readCtx();
  const out = new URLSearchParams();
  if (c.novel) out.set("novel", c.novel);
  if (c.locale) out.set("locale", c.locale);
  out.set("medium", c.medium || "video");
  for (const k of ["production", "canvas"] as const) if(c[k]) out.set(k,c[k]);
  if (page) out.set("page", page);
  if (c.chapter) {
    out.set("chapter", c.chapter);
    out.set("page", page || "production");
    if (c.plan) out.set("plan", c.plan);
    if (c.shot) out.set("shot", c.shot);
  }
  out.set("view", "hub");
  out.set("hub", out.get("page") || "production");
  out.delete("page");
  out.set("workspace", c.workspace || "novel");
  return "/studio/?" + out;
}

export function Nav({ view, onChange }: { view: View; onChange: (v: View, patch?: CtxPatch) => void }) {
  const cur = stageOfView(view);
  const comic = view.startsWith("comic") || readCtx().medium === "comic";
  const stages: StageDef[] = comic
    ? STAGES.map(s => {
        if (s.id === 'a') return { ...s, label: '共享剧本与翻译', views: ['translation'] };
        if (s.id === 'b') return { ...s, label: '漫剧人物与素材', views: ['comic-assets'] };
        if (s.id === 'c') return { ...s, label: '漫剧画布与导演', views: ['flow', 'box'] };
        if (s.id === 'd') return { ...s, label: '镜头与成片', views: ['comic'] };
        return s;
      })
    : STAGES.map(s=>s.id==='d'?{...s,label:'视频成片',views:[],adminPage:'cut'}:s);
  const panels: View[] = comic && cur === "b" ? ["comic-assets"] : comic && cur === "c" ? ["flow", "box"] : comic && cur === "d" ? ["comic"] : stageDef(cur).views;
  const fresh = (page?: string | null) => (e: { currentTarget: HTMLAnchorElement }) => {
    e.currentTarget.href = adminHref(page ?? ADMIN_PAGE[view]);
  };

  return (
    <div className="nav-wrap">
      <nav className="nav nav-panel" aria-label="制作类型">
        <button className={!comic ? 'on' : ''} onClick={() => onChange('flow', { medium: null })}>视频制作</button>
        <button className={comic ? 'on' : ''} onClick={() => onChange('flow', { medium: 'comic' })}>动态漫画</button>
        <span className="wb-muted">共用剧本 · 分开制作素材</span>
      </nav>
      <nav className="nav nav-stage" aria-label="制作阶段">
        {stages.map(s => {
          // 保留后台阶段入口，供尚未接入前端的后续面板使用。
          if (!s.views.length) {
            return (
              <a key={s.id} className="stage-btn is-admin" href="/admin"
                onMouseDown={fresh(s.adminPage)} onClick={fresh(s.adminPage)}
                title={`${s.hint}（本批在后台，Studio 面板待接）`}>
                {s.label} ↗
              </a>
            );
          }
          return (
            <button key={s.id} type="button" className={`stage-btn${cur === s.id ? " on" : ""}`}
              title={s.hint} onClick={() => {
                if (cur !== s.id) {
                  onChange(comic && s.id === "b" ? "comic-assets" : comic && s.id === "c" ? "flow" : comic && s.id === "d" ? "comic" : s.views[0]);
                } else if (s.views.length && view !== s.views[0]) {
                  onChange(s.views[0]);
                }
              }}>
              {s.label}
            </button>
          );
        })}
        <span className="nav-spacer" />
        <a className="nav-admin" href="/admin" onMouseDown={fresh(null)} onClick={fresh(null)}
          title="切到后台（/admin）：世界观、译本、剧本、分镜全景、配音、任务与设置；带着当前小说和章节">
          制作总览 ↗
        </a>
      </nav>
      {panels.length > 1 && (
        <nav className="nav nav-panel" aria-label="面板">
          {panels.map(v => (
            <button key={v} type="button" className={view === v ? "on" : ""} onClick={() => onChange(v)}>
              {VIEWS.find(x => x.id === v)?.label ?? v}
            </button>
          ))}
        </nav>
      )}
    </div>
  );
}
