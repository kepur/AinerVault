import type { ReactNode } from "react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { readCtx, writeCtx } from "./ctx";
import type { Board, CastMember, PlanSummary } from "./types";
import Canvas from "./components/Canvas";
import Inspector from "./components/Inspector";
// 3D 导演台带着整个 three.js（约 1MB），点开时才加载
const Stage = lazy(() => import("./components/Stage"));
import CastPanel from "./components/CastPanel";
import { directorPending } from "./shotStatus";

interface NovelRow { id: string; title: string }
interface ChapterRow { id: string; order_no: number; title: string }

/**
 * 地址栏记住当前选择（ctx.ts 的约定，各视图共用）：刷新、分享链接、顶部 Nav 切视图都回到同一份分镜、同一镜。
 * 换书 / 换章 / 换计划时级联清掉下级参数。
 */
function remember(key: "novel" | "chapter" | "plan" | "shot", value: string | null) {
  writeCtx({ [key]: value });
}

export default function App({ nav }: { nav?: ReactNode }) {
  // 每次挂载现读地址栏：Nav 用 pushState 切回来时模块不会重新执行，模块级缓存的参数是旧的
  const [init] = useState(readCtx);
  const deep = useRef({ shot: init.shot, stage: new URLSearchParams(location.search).get("stage") });
  const [novels, setNovels] = useState<NovelRow[]>([]);
  const [novelId, setNovelId] = useState(init.novel ?? "");
  const [chapters, setChapters] = useState<ChapterRow[]>([]);
  const [chapterId, setChapterId] = useState(init.chapter ?? "");
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [planId, setPlanId] = useState(init.plan ?? "");
  const [board, setBoard] = useState<Board | null>(null);
  const [cast, setCast] = useState<CastMember[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [stageShot, setStageShot] = useState<string | null>(null);
  const [tab, setTab] = useState<"canvas" | "assets">("canvas");
  const [focusScene, setFocusScene] = useState<string | null>(null);
  /** 深链带来的镜头：载入后视口飞到它（只用一次） */
  const [focusShot, setFocusShot] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/v2/console").then(r => r.json()).then(d => {
      const rows: NovelRow[] = (d.novels ?? []).map((n: NovelRow) => ({ id: n.id, title: n.title }));
      setNovels(rows);
      if (!novelId && rows[0]) setNovelId(rows[0].id);
    }).catch(e => setError(String(e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!novelId) return;
    remember("novel", novelId);
    fetch(`/api/v2/novels/${novelId}/chapters?limit=500`).then(r => r.json()).then(d => {
      const rows: ChapterRow[] = (d.items ?? []).map((c: ChapterRow) =>
        ({ id: c.id, order_no: c.order_no, title: c.title }));
      setChapters(rows);
      if (!rows.some(c => c.id === chapterId) && rows[0]) setChapterId(rows[0].id);
    }).catch(e => setError(String(e)));
  }, [novelId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!chapterId) return;
    remember("chapter", chapterId);
    api.plans(chapterId).then(d => {
      setPlans(d.plans);
      if (!d.plans.some(p => p.id === planId)) {
        // 默认看最近一份正式分镜；试片计划只有几镜，不适合当画布的起点
        const main = d.plans.find(p => !p.sample && p.shots > 0) ?? d.plans[0];
        setPlanId(main?.id ?? "");
      }
    }).catch(e => setError(String(e)));
  }, [chapterId]); // eslint-disable-line react-hooks/exhaustive-deps

  const reload = useCallback(() => {
    if (!planId) return;
    api.board(planId).then(b => {
      setBoard(b);
      // 深链：?shot= 选中镜头并飞过去，?stage= 直接打开这一镜的 3D 导演台（只在首次载入时生效）
      const d = deep.current;
      const want = d.stage ?? d.shot;
      if (want && b.shots.some(s => s.id === want)) {
        setSelected(want);
        setFocusShot(want);
        if (d.stage) setStageShot(want);
        deep.current = { shot: null, stage: null };
      }
    }).catch(e => setError(String(e)));
  }, [planId]);

  useEffect(() => {
    if (!planId) return;
    remember("plan", planId);
    setBoard(null);
    setSelected(null);
    reload();
    api.cast(planId).then(d => setCast(d.cast)).catch(() => setCast([]));
  }, [planId, reload]);

  // 选中的镜头写回地址栏：切到创作画布 / 后台时落在这一镜
  useEffect(() => { if (selected) remember("shot", selected); }, [selected]);

  // 出片是异步的：有镜头在生成（含导演出片）时每 6 秒刷新一次，结果挂回来就能在卡片上看到
  const busy = useMemo(() => board?.shots.some(s =>
    s.first?.status === "generating" || s.last?.status === "generating" || directorPending(s) || !!s.canvas_run) ?? false, [board]);
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(reload, 6000);
    return () => clearInterval(t);
  }, [busy, reload]);

  const shot = board?.shots.find(s => s.id === selected) ?? null;
  const ready = board ? {
    video: board.shots.filter(s => s.video_url).length,
    director: board.shots.filter(s => s.director?.done).length,
    pending: board.shots.filter(directorPending).length,
  } : null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Ainer <b>Studio</b></div>
        {nav}
        <select value={novelId} onChange={e => setNovelId(e.target.value)}>
          {novels.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
        </select>
        <select value={chapterId} onChange={e => setChapterId(e.target.value)}>
          {chapters.map(c => <option key={c.id} value={c.id}>{c.order_no}. {c.title}</option>)}
        </select>
        <select value={planId} onChange={e => setPlanId(e.target.value)}>
          {plans.map(p => (
            <option key={p.id} value={p.id}>
              分镜 v{p.version} · {p.shots} 镜{p.sample ? " · 试片" : ""}{p.status === "active" ? " · 当前" : ""}
            </option>
          ))}
        </select>
        <div className="spacer" />
        {ready && board && (
          <div className="stat">
            视频 <b>{ready.video}</b>/{board.shots.length} · 3D 导演 <b>{ready.director}</b>
            {ready.pending > 0 && <> · 出片中 <b>{ready.pending}</b></>}
            {busy && " · 生成中…"}
          </div>
        )}
      </header>

      <div className="main">
        <aside className="left">
          <div className="tabs">
            <button className={tab === "canvas" ? "on" : ""} onClick={() => setTab("canvas")}>画布</button>
            <button className={tab === "assets" ? "on" : ""} onClick={() => setTab("assets")}>资产</button>
          </div>
          {tab === "canvas" && board && (
            <div className="section">
              <h4>场景（点击定位）</h4>
              {board.scenes.map(sc => (
                <button key={sc.id} className="scene-link" onClick={() => setFocusScene(sc.id)}>
                  {sc.order_no}. {sc.title}
                  <small>{board.shots.filter(s => s.scene_id === sc.id).length} 镜</small>
                </button>
              ))}
            </div>
          )}
          {tab === "assets" && <CastPanel cast={cast} />}
        </aside>

        <section className="center">
          {error && <div className="err" style={{ padding: 12 }}>{error}</div>}
          {board
            ? <Canvas board={board} selected={selected} onSelect={setSelected} focusScene={focusScene} focusShot={focusShot} />
            : <div className="empty-state">载入分镜…</div>}
        </section>

        <aside className="right">
          {shot && board
            ? <Inspector planId={board.plan.id} shot={shot} onStage={() => setStageShot(shot.id)} onChanged={reload} />
            : <div className="empty-state">选一个镜头</div>}
        </aside>
      </div>

      {stageShot && board && (
        <Suspense fallback={<div className="stage-wrap"><div className="empty-state">载入 3D 导演台…</div></div>}>
        <Stage
          shot={board.shots.find(s => s.id === stageShot)!}
          cast={cast}
          onClose={() => setStageShot(null)}
          onChanged={reload}
        />
        </Suspense>
      )}
    </div>
  );
}
