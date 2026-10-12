import { useCallback, useEffect, useRef, useState } from "react";
import { readCtx, writeCtx } from "../ctx";
import type { PlanSummary } from "../types";
import { comicRequest, request, type Discovery, type EngineTask } from "./api";
import "./workbench.css";

interface Novel { id: string; title: string }
interface Chapter { id: string; title: string; order_no: number }
export function useProject() {
  const [init] = useState(readCtx);
  const [novels, setNovels] = useState<Novel[]>([]);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [novel, setNovel] = useState(init.novel || "");
  const [chapter, setChapter] = useState(init.chapter || "");
  const [plan, setPlan] = useState(init.plan || "");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    request<{ novels: Novel[] }>("/api/v2/console").then(d => {
      if (!live) return;
      setNovels(d.novels);
      if (!d.novels.some(n => n.id === novel)) {
        // An unbound creative canvas must never silently select an unrelated book.
        const selected = (init.medium === 'comic' || init.view?.startsWith('comic')) && d.novels.length === 1 ? d.novels[0].id : '';
        setNovel(selected); setChapter(""); setPlan(""); writeCtx({ novel: selected || null });
      }
    }).catch(e => live && setError(String(e)));
    return () => { live = false; };
  }, []); // Initial context is read at each mount.
  useEffect(() => {
    let live = true;
    setChapters([]); setPlans([]); setError("");
    if (!novel) return;
    request<{ items: Chapter[] }>(`/api/v2/novels/${novel}/chapters?limit=500`).then(d => {
      if (!live) return;
      setChapters(d.items);
      if (!d.items.some(c => c.id === chapter)) {
        const id = d.items[0]?.id || ""; setChapter(id); setPlan(""); writeCtx({ chapter: id || null });
      }
    }).catch(e => live && setError(String(e)));
    return () => { live = false; };
  }, [novel]);
  useEffect(() => {
    let live = true;
    setPlans([]);
    if (init.medium === 'comic' || init.view?.startsWith('comic')) return;
    if (!chapter || !chapters.some(c => c.id === chapter)) return;
    request<{ plans: PlanSummary[] }>(`/api/v2/studio/chapters/${chapter}/plans`).then(d => {
      if (!live) return;
      setPlans(d.plans);
      if (!d.plans.some(p => p.id === plan)) {
        const id = d.plans.find(p => !p.sample && p.status === "active")?.id || d.plans[0]?.id || "";
        setPlan(id); writeCtx({ plan: id || null });
      }
    }).catch(e => live && setError(String(e)));
    return () => { live = false; };
  }, [chapter, chapters]);
  return { novels, chapters, plans, novel, chapter, plan, error,
    setNovel: (v: string) => { setNovel(v); setChapter(""); setPlan(""); writeCtx({ novel: v || null }); },
    setChapter: (v: string) => { setChapter(v); setPlan(""); writeCtx({ chapter: v || null }); },
    setPlan: (v: string) => { setPlan(v); writeCtx({ plan: v || null }); },
  };
}
export type Project = ReturnType<typeof useProject>;
export function ProjectPicker({ project: p, withPlan = false }: { project: Project; withPlan?: boolean }) {
  return <div className="wb-context">
    <label>作品<select aria-label="作品" value={p.novel} onChange={e => p.setNovel(e.target.value)}><option value="">选择作品</option>{p.novels.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}</select></label>
    <label>章节<select aria-label="章节" value={p.chapter} onChange={e => p.setChapter(e.target.value)}><option value="">选择章节</option>{p.chapters.map(c => <option key={c.id} value={c.id}>{c.order_no}. {c.title}</option>)}</select></label>
    {withPlan && <label>分镜<select aria-label="分镜计划" value={p.plan} onChange={e => p.setPlan(e.target.value)}><option value="">尚无分镜计划</option>{p.plans.map(x => <option key={x.id} value={x.id}>v{x.version} · {x.shots} 镜{x.sample ? " · 试片" : ""}</option>)}</select></label>}
  </div>;
}

export function useEngine() {
  const mounted = useRef(true);
  const [tasks, setTasks] = useState<EngineTask[]>([]);
  const [discovery, setDiscovery] = useState<Discovery | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    try {
      const d = await comicRequest<{ items: EngineTask[] }>("/cap/v1/tasks");
      if (mounted.current) { setTasks(d.items); setError(""); }
    } catch { if (mounted.current) setError("本地漫剧执行层未连接；已有译文仍可编辑，画布也可继续使用。"); }
  }, []);
  useEffect(() => {
    mounted.current = true;
    let live = true;
    comicRequest<Discovery>("/cap/v1/capabilities").then(d => live && setDiscovery(d)).catch(() => {});
    reload();
    // One poller for this workbench, including task recovery after page reload.
    const timer = setInterval(reload, 3000);
    return () => { live = false; mounted.current = false; clearInterval(timer); };
  }, [reload]);
  return { tasks, discovery, error, reload };
}
const STATUS: Record<string, string> = { queued: "排队", running: "进行中", succeeded: "完成", failed: "失败", cancelled: "已取消" };
const LABEL: Record<string, string> = { "comic.card":"基础标准卡", "comic.keyframe":"参考分镜图", "comic.ltx":"LTX 动态镜头", "comic.motion_layers":"快速动作 · 单人图层", "comic.render_shot":"镜头方案出片", "comic.extract_foundation":"世界观素材补齐", "comic.animate": "动态漫画镜头", "comic.assemble": "连续镜头预览", "comic.design": "动漫素材生产", "comic.voice": "漫剧配音", "comic.compose_2d": "2D 运镜预览", "comic.route_shots": "镜头路由", "comic.retime": "时间轴规划", "hub.translate_chapter": "章节翻译" };
export function TaskList({ tasks, reload, names={},reviews={} }: { tasks: EngineTask[]; reload: () => void; names?:Record<string,string>;reviews?:Record<string,{accepted:boolean;note:string}> }) {
  const [showHistory,setHistory]=useState(false),[clock,setClock]=useState(Date.now());
  const hasActive=tasks.some(t=>['queued','running'].includes(t.status));
  useEffect(()=>{if(!hasActive)return;const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);},[hasActive]);
  const review=(t:EngineTask)=>reviews[(t.output?.asset as {asset_id?:string}|undefined)?.asset_id||''];
  const visible=showHistory?tasks:tasks.filter(t=>review(t)?.accepted!==false&&t.status!=='cancelled');
  const [error, setError] = useState("");
  const action = async (id: string, verb: string) => {
    try { await comicRequest(`/cap/v1/tasks/${id}:${verb}`, {}); setError(""); reload(); }
    catch (e) { setError(String(e)); }
  };
  return <section className="wb-card wb-tasks"><h3>制作任务</h3>{error && <div className="wb-error" role="alert">{error}</div>}
    {!tasks.length && <p className="wb-muted">提交后会在这里显示进度，刷新页面可继续查看。</p>}
    {visible.slice(0,showHistory?200:8).map(t => <div className="wb-task" key={t.task_id}>
      <div><b>{LABEL[t.capability] || t.capability}{t.context?.source_id&&names[t.context.source_id]?` · ${names[t.context.source_id]}`:''}</b><small>{t.context?.locale || ""} {t.context?.shot_id || ""} · {review(t)?.accepted===false?'生成完成 · 画面不通过':STATUS[t.status]}{t.status === "running" ? ` ${Math.round(t.progress*100)}%` : ""}</small>
        {review(t)?.accepted===false&&<p className="wb-error">{review(t)?.note}</p>}
        {['queued','running'].includes(t.status)&&<small>提交后经过 {Math.max(0,Math.round((clock-Date.parse(t.submitted_at))/1000))} 秒（含等待）</small>}
        {t.error && <p className="wb-error">{t.error.message}</p>}
        {t.usage.duration_ms != null && <small>实际耗时 {(t.usage.duration_ms/1000).toFixed(1)} 秒</small>}
      </div>
      <div className="wb-actions">{["failed", "cancelled"].includes(t.status) && t.error?.retryable !== false && <button onClick={() => action(t.task_id, "retry")}>重试</button>}
        {["queued", "running"].includes(t.status) && !(t.status === "running" && t.capability === "hub.translate_chapter") && <button onClick={() => action(t.task_id, "cancel")}>取消</button>}
      </div>
    </div>)}
    {!!tasks.length&&<button onClick={()=>setHistory(v=>!v)}>{showHistory?'收起历史任务':'查看全部任务与不通过记录'}</button>}
  </section>;
}
