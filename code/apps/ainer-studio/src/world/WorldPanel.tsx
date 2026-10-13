/**
 * World / Greybox 面板（可选路径）。
 *
 * 默认路径永远是原动态漫剧管线：这里先给一个“为本章启用 world-greybox”的开关（默认关，总开关在
 * configs/director/feature_flags.yaml 的 world_greybox_enabled）。打开后才能看运行、逐镜对比原管线成片与
 * greybox 成片、看白模、QA 徽章、单镜重渲、人工选用哪一版。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { readCtx } from "../ctx";
import { wg, type Run, type ShotRow, type Switch, type WorldMap } from "./api";
import "./world.css";

const GATES = ["positions", "camera", "motion", "audio", "mood"] as const;
const COLORS = ["#4c8dff", "#3ec46d", "#ef5b5b", "#e8c547", "#b77cff", "#47d3e8"];

function Badge({ ok, label }: { ok: boolean | null | undefined; label: string }) {
  return <span className={`wg-badge ${ok == null ? "na" : ok ? "ok" : "bad"}`}>{label}</span>;
}

function OptIn({ scopeKind, scopeId, flag, sw, onChange }: { scopeKind: Switch["scope_kind"]; scopeId: string; flag: boolean; sw: Switch | null; onChange: () => void }) {
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const set = async (patch: Partial<Switch>) => {
    setBusy(true); setErr("");
    try { await wg.setSwitch({ scope_kind: scopeKind, scope_id: scopeId, enabled: sw?.enabled ?? false, fallback_to_original: sw?.fallback_to_original ?? true, ...patch }); onChange(); }
    catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="wg-optin">
      <label><input type="checkbox" disabled={busy} checked={!!sw?.enabled} onChange={e => set({ enabled: e.target.checked })} />
        为本{scopeKind === "chapter" ? "章" : "项目"}启用 world-greybox（实验，可选）</label>
      <label><input type="checkbox" disabled={busy || !sw?.enabled} checked={sw?.fallback_to_original ?? true} onChange={e => set({ fallback_to_original: e.target.checked })} />
        闸门不过的镜头自动回退原管线成片</label>
      {!flag && <small className="wg-warn">总开关 world_greybox_enabled 关着（feature_flags.yaml）：开关可以先设好，但不会生效。</small>}
      <small>默认仍走原动态漫剧管线；关掉开关即恢复原样。</small>
      {err && <small className="wg-err">{err}</small>}
    </div>
  );
}

function MapView({ map, perfIdx, take }: { map: WorldMap; perfIdx: number; take: number | null }) {
  const perf = map.performances[perfIdx];
  const region = map.regions.find(r => r.key === perf?.region_key) ?? map.regions.find(r => r.key.includes("/")) ?? map.regions[0];
  if (!region) return <div className="wg-empty">世界里还没有区域</div>;
  const [x0, y0] = region.bounds_aabb.min, [x1, y1] = region.bounds_aabb.max;
  const W = 640, s = W / Math.max(0.1, x1 - x0), H = Math.max(120, (y1 - y0) * s);
  const px = (x: number) => (x - x0) * s, py = (y: number) => H - (y - y0) * s;
  const tk = perf?.takes.find(t => t.n === take);
  const actorNames = Object.keys(perf?.tracks ?? {});
  return (
    <svg className="wg-map" viewBox={`-10 -10 ${W + 20} ${H + 20}`}>
      <rect x={0} y={0} width={W} height={H} className="wg-region" />
      {map.chunks.filter(c => c.region === region.key).map((c, i) => {
        const cs = 8 * s, cx = (c.cx ?? c.ix ?? 0) * 8, cy = (c.cy ?? c.iy ?? 0) * 8;
        return <rect key={i} x={px(cx)} y={py(cy + 8)} width={cs} height={cs} className="wg-chunk" />;
      })}
      {map.instances.filter(i => i.region === region.key && i.aabb).map(i => (
        <rect key={i.key} x={px(i.aabb.min[0])} y={py(i.aabb.max[1])} width={(i.aabb.max[0] - i.aabb.min[0]) * s}
          height={(i.aabb.max[1] - i.aabb.min[1]) * s} className={i.collision ? "wg-inst" : "wg-inst soft"}><title>{i.key}</title></rect>
      ))}
      {map.landmarks.filter(l => l.region === region.key).map(l => <circle key={l.key} cx={px(l.pos[0])} cy={py(l.pos[1])} r={4} className="wg-landmark"><title>{l.key}</title></circle>)}
      {actorNames.map((a, k) => {
        const keys = perf.tracks[a].keys.filter(q => !tk || (q.t_ms >= tk.start_ms - 1 && q.t_ms <= tk.end_ms + 1));
        const all = perf.tracks[a].keys;
        return <g key={a}>
          <polyline points={all.map(q => `${px(q.pos[0])},${py(q.pos[1])}`).join(" ")} stroke={COLORS[k % COLORS.length]} className="wg-track faint" />
          <polyline points={keys.map(q => `${px(q.pos[0])},${py(q.pos[1])}`).join(" ")} stroke={COLORS[k % COLORS.length]} className="wg-track" />
          {all[0] && <text x={px(all[0].pos[0]) + 5} y={py(all[0].pos[1]) - 5} fill={COLORS[k % COLORS.length]}>{a}</text>}
        </g>;
      })}
      {tk && <g className="wg-cam">
        <circle cx={px(tk.camera.pos[0])} cy={py(tk.camera.pos[1])} r={6} />
        <line x1={px(tk.camera.pos[0])} y1={py(tk.camera.pos[1])} x2={px(tk.camera.target[0])} y2={py(tk.camera.target[1])} />
      </g>}
    </svg>
  );
}

function ShotCard({ run, row, onAct }: { run: Run; row: ShotRow; onAct: (fn: () => Promise<unknown>) => void }) {
  const f = (p: string | null) => wg.file(run.id, p);
  const failed = new Set(row.failed);
  return (
    <div className={`wg-shot ${row.source === "original" ? "fallback" : ""}`}>
      <div className="wg-shot-title">
        <b>镜 {row.shot} · {row.kind} · {row.move}</b>
        <small>{row.dur_s.toFixed(2)}s @{row.fps}fps · {row.attempts} 次 · {row.strategy ?? "—"}</small>
      </div>
      <div className="wg-badges">
        {GATES.map(g => <Badge key={g} label={g} ok={row.attempts ? !failed.has(g) || (row.greybox_pass && row.source === "greybox") : null} />)}
        <Badge label={row.source === "original" ? "用原管线" : row.source === "greybox" ? "用 greybox" : "未选"} ok={row.source === "greybox" ? !!row.pass : null} />
        {row.approved && <Badge label="已审批" ok />}
      </div>
      {row.camera_fit?.world_conflict_hidden?.length ? <small className="wg-warn">与原首帧冲突、白模中未画：{row.camera_fit.world_conflict_hidden.join(", ")}（世界里仍在原位）</small> : null}
      <div className="wg-media">
        <figure><video src={f(row.original_video)} controls muted preload="metadata" /><figcaption>原管线</figcaption></figure>
        <figure><video src={f(row.clay)} controls muted preload="metadata" /><figcaption>白模（world greybox）</figcaption></figure>
        <figure><video src={f(row.greybox_video)} controls preload="metadata" /><figcaption>greybox 成片</figcaption></figure>
      </div>
      {row.why && <small>{row.why}{row.post.length ? ` · 后处理：${row.post.join(", ")}` : ""}</small>}
      <div className="wg-actions">
        <button disabled={run.running} onClick={() => onAct(() => wg.rerender(run.id, row.shot))}>重渲这一镜</button>
        <button disabled={run.running || !row.original_video} onClick={() => onAct(() => wg.select(run.id, row.shot, { source: "original", approve: true }))}>选原管线</button>
        <button disabled={run.running || !row.greybox_video} onClick={() => onAct(() => wg.select(run.id, row.shot, { source: "greybox", attempt_index: row.attempts - 1, approve: true }))}>选 greybox</button>
        <button disabled={run.running || !row.override} onClick={() => onAct(() => wg.select(run.id, row.shot, { source: "auto" }))}>恢复自动</button>
      </div>
    </div>
  );
}

export default function WorldPanel() {
  const ctx = readCtx();
  const scopeKind = ctx.chapter ? "chapter" : "production";
  const scopeId = ctx.chapter || ctx.production || "";
  const [flag, setFlag] = useState(false), [sw, setSw] = useState<Switch | null>(null);
  const [runs, setRuns] = useState<Run[]>([]), [runId, setRunId] = useState<string | null>(null);
  const [rows, setRows] = useState<ShotRow[]>([]), [map, setMap] = useState<WorldMap | null>(null);
  const [perfIdx, setPerfIdx] = useState(0), [take, setTake] = useState<number | null>(null);
  const [error, setError] = useState(""), [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick(t => t + 1), []);
  useEffect(() => {
    let alive = true;
    Promise.all([wg.flag(), scopeId ? wg.switches(scopeId) : Promise.resolve({ switches: [] as Switch[], flag: false }), wg.runs(scopeId || undefined)])
      .then(([f, s, r]) => {
        if (!alive) return;
        setFlag(f.world_greybox_enabled);
        setSw(s.switches.find(x => x.scope_kind === scopeKind) ?? null);
        setRuns(r.runs);
        setRunId(id => id ?? r.runs[0]?.id ?? null);
      }).catch(e => alive && setError(String(e)));
    return () => { alive = false; };
  }, [scopeId, scopeKind, tick]);
  const run = useMemo(() => runs.find(r => r.id === runId) ?? null, [runs, runId]);
  useEffect(() => {
    if (!runId) return;
    let alive = true;
    wg.shots(runId).then(d => alive && setRows(d.shots)).catch(e => alive && setError(String(e)));
    wg.world(runId).then(m => alive && setMap(m)).catch(() => undefined);
    return () => { alive = false; };
  }, [runId, tick]);
  useEffect(() => { if (!run?.running) return; const t = setInterval(refresh, 15000); return () => clearInterval(t); }, [run?.running, refresh]);
  const act = (fn: () => Promise<unknown>) => { setError(""); fn().then(refresh).catch(e => setError(String(e))); };
  const perfOfTake = (n: number) => map?.performances.findIndex(p => p.takes.some(t => t.n === n)) ?? -1;

  return (
    <div className="wg-panel">
      <header>
        <h2>World / Greybox <span>可选路径 · 默认关闭</span></h2>
        {scopeId ? <OptIn scopeKind={scopeKind} scopeId={scopeId} flag={flag} sw={sw} onChange={refresh} /> : <small>先在顶部选一个章节或漫剧项目。</small>}
      </header>
      {error && <div className="wg-err">{error}</div>}
      {!sw?.enabled && !runs.length ? <div className="wg-empty">本{scopeKind === "chapter" ? "章" : "项目"}没有启用 world-greybox：成片照常由原动态漫剧管线生成。</div> : (
        <div className="wg-body">
          <aside>
            <div className="wg-runs">
              {runs.map(r => (
                <button key={r.id} className={r.id === runId ? "on" : ""} onClick={() => setRunId(r.id)}>
                  <b>{r.title || r.id}</b>
                  <small>{r.status}{r.running ? ` · ${(r.progress * 100).toFixed(0)}%` : ""}{r.report ? ` · greybox ${r.report.greybox_passed}/${r.report.total} 过闸，用原管线 ${r.report.used_original}` : ""}</small>
                </button>
              ))}
            </div>
            {run && <div className="wg-run-actions">
              <button disabled={run.running} onClick={() => act(() => wg.start(run.id))}>{run.status === "done" ? "重拼成片 / 续跑" : "开始 / 续跑"}</button>
              {run.final && <a href={wg.file(run.id, run.final.video)} target="_blank" rel="noreferrer">成片 {run.final.probe.duration_s.toFixed(1)}s</a>}
              {run.error && <small className="wg-err">{run.error.split("\n")[0]}</small>}
            </div>}
            {map && <>
              <div className="wg-perfs">
                {map.performances.map((p, i) => (
                  <button key={p.id} className={i === perfIdx ? "on" : ""} onClick={() => { setPerfIdx(i); setTake(null); }}>
                    {p.region_key} · {(p.duration_ms / 1000).toFixed(1)}s · rev {p.rev} {p.check_ok ? "✓" : "✗"}
                  </button>
                ))}
              </div>
              <MapView map={map} perfIdx={perfIdx} take={take} />
              <small>世界 v{map.version} · 区域 {map.regions.length} · 实例 {map.instances.length}。点镜头卡片高亮该镜时间窗与机位。</small>
            </>}
          </aside>
          <section className="wg-shots">
            {rows.map(r => (
              <div key={r.shot} onMouseEnter={() => { const i = perfOfTake(r.shot); if (i >= 0) { setPerfIdx(i); setTake(r.shot); } }}>
                {run && <ShotCard run={run} row={r} onAct={act} />}
              </div>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}
