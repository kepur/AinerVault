/**
 * 顶部导航：A 故事与世界 / B 素材与场景 / C 导演与分镜 / D 成片与剪辑（planA.md §2）。
 *
 * 阶段是分组，不是新视图：现有的 5 个视图降为阶段里的面板，`?view=` 原样保留，老深链照旧能开。
 * `?stage=` 只是显示用的分组标记；没给时由 view 反推，所以不带 stage 的旧链接也落在对的阶段上。
 *
 * 切阶段**不清**任何上下文 ID —— A→B→C 的意义就是带着同一本书、同一章、同一画布走（契约 §2）。
 */
import { readCtx } from "./ctx";

export type View = "canvas" | "flow" | "box" | "characters" | "styles";
export type Stage = "a" | "b" | "c" | "d";

export const VIEWS: { id: View; label: string }[] = [
  { id: "canvas", label: "分镜画布" },
  { id: "flow", label: "创作画布" },
  { id: "box", label: "3D-BOX 预演" },
  { id: "characters", label: "角色库" },
  { id: "styles", label: "风格广场" },
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
  { id: "a", label: "A 故事与世界", hint: "原文、译本、实体、时期、剧本", views: [], adminPage: "chapter" },
  { id: "b", label: "B 素材与场景", hint: "角色、道具、地点、造型与标准素材", views: ["characters", "styles"] },
  { id: "c", label: "C 导演与分镜", hint: "剧情事件、舞台、机位、分镜", views: ["canvas", "flow", "box"] },
  { id: "d", label: "D 成片与剪辑", hint: "出片、声音、剪辑、导出", views: [], adminPage: "handoff" },
];

const STAGE_OF: Record<View, Stage> = {
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
const ADMIN_PAGE: Partial<Record<View, string>> = { canvas: "storyboard", flow: "chapter", characters: "model", box: "chapter" };

export function adminHref(page?: string | null): string {
  const c = readCtx();
  const out = new URLSearchParams();
  if (c.novel) out.set("novel", c.novel);
  if (c.chapter) {
    out.set("chapter", c.chapter);
    out.set("page", page || "chapter");
    if (c.plan) out.set("plan", c.plan);
    if (c.shot) out.set("shot", c.shot);
  }
  return "/admin" + (out.toString() ? `?${out}` : "");
}

export function Nav({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const cur = stageOfView(view);
  const panels = stageDef(cur).views;
  const fresh = (page?: string | null) => (e: { currentTarget: HTMLAnchorElement }) => {
    e.currentTarget.href = adminHref(page ?? ADMIN_PAGE[view]);
  };

  return (
    <div className="nav-wrap">
      <nav className="nav nav-stage" aria-label="制作阶段">
        {STAGES.map(s => {
          // 没有前端面板的阶段（A、D）本批直接去后台，不做一个空壳页假装已经有了
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
                  onChange(s.views[0]);
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
          后台 ↗
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
