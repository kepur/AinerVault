import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, media } from "../api";
import type { Blocking, CastMember, ShotCard } from "../types";
import {
  ANGLES, SIZES, actorsFromFigures, angleShot, applyMove, axisSide, centroid, crossesAxis, describe, ease,
  forServer, frameShot, framingOf, lerp3, MOVE_GROUPS, moveLabel, newRig, overShoulder, projectActors,
  sizeLabel, snapArcEnd, solveStart, sweepFromEnd, videoMove, yawToward,
  type Actor, type CamPose, type Easing, type PathKind, type Rig, type ShotSize, type Stage3D, type Vec3,
} from "../stage/model";
import { Curves } from "../stage/Curves";
import { CameraView, FreeView, leads, SideView, TopView, type Handle } from "../stage/Views";

/**
 * 3D 导演台。
 *
 * 版式照主流预演工具：左边大的是机位视角（透过这一镜的相机、按焦段看，
 * 叠监视器读数），下面是时间轴；中间一列是俯视平面图（演员、机位、视场、
 * 轨迹、180° 轴线，全部可拖）和侧视立面图／自由视角；右边是运镜、
 * 关键帧与演员的参数，最下面是「交给出图的」编译结果。
 *
 * 保存时两件事：
 *   起幅相机下把演员投影成屏幕空间站位 → 分区身份出首帧（与服务端人偶同一套比例）
 *   整段运镜 → 结构化机位＋英文描述 → 视频的 camera 参数与尾帧的镜头变化
 */

interface Props {
  planId: string;
  shot: ShotCard;
  cast: CastMember[];
  onClose: () => void;
  onChanged: () => void;
}

const PATHS: { kind: PathKind; label: string }[] = [
  { kind: "linear", label: "直线" },
  { kind: "arc", label: "环绕弧线" },
  { kind: "parabola", label: "抛物线" },
  { kind: "bezier", label: "贝塞尔" },
];
const EASINGS: { kind: Easing; label: string }[] = [
  { kind: "ease_in_out", label: "缓入缓出" },
  { kind: "linear", label: "匀速" },
  { kind: "ease_in", label: "缓入" },
  { kind: "ease_out", label: "缓出" },
];
const PRIMES = [14, 18, 24, 35, 50, 85, 135];
const STOPS = [1.4, 2.8, 5.6, 11];

const round = (v: number, k = 100) => Math.round(v * k) / k;
const ASPECT = 800 / 480;

/** 关键帧的「相对注视点」参数：距离、方位角、高度 —— 预演软件里调机位的常用手感。 */
function polar(p: CamPose) {
  const dx = p.pos[0] - p.target[0];
  const dz = p.pos[2] - p.target[2];
  return { dist: Math.hypot(dx, dz), az: (Math.atan2(dz, dx) * 180) / Math.PI, height: p.pos[1] };
}
function fromPolar(p: CamPose, dist: number, az: number, height: number): CamPose {
  const a = (az * Math.PI) / 180;
  return { ...p, pos: [p.target[0] + dist * Math.cos(a), height, p.target[2] + dist * Math.sin(a)] };
}

/** 服务端的站位 → 3D 场面。存过的场面按最新的出场名单对一遍。 */
function stageFrom(b: Blocking, shot: ShotCard): Stage3D {
  const cast = b.cast?.length ? b.cast : b.figures;
  if (b.stage3d && b.stage3d.version === 1) {
    // 表演单删掉的人拿掉，新加的人按自动摆位补进来；脸与外观跟设定走
    const fresh = new Map(cast.map(f => [f.entity_id, f]));
    const kept = b.stage3d.actors.filter(a => fresh.has(a.entity_id)).map(a => {
      const f = fresh.get(a.entity_id)!;
      return { ...a, name: f.name, face_url: f.face_url, prompt: f.prompt };
    });
    // 新加的人按自动摆位补：和第一次打开时同一台反解相机，世界坐标对得上
    const missing = cast.filter(f => !kept.some(a => a.entity_id === f.entity_id));
    const solved = solveStart(cast, b.stage3d.aspect);
    return { ...b.stage3d, actors: [...kept, ...actorsFromFigures(missing, b.stage3d.aspect, solved)] };
  }
  const start = solveStart(cast, ASPECT);
  const actors = actorsFromFigures(cast, ASPECT, start);
  const rig = newRig(actors, shot.camera?.move, shot.duration_ms, start);
  if (!b.regional && actors.length) {
    // 单人、特写：首帧不按站位出，起幅按分镜的景别把相机推到位，看到的才是这一镜
    const size = (SIZES.find(s => s.kind === shot.shot_size)?.kind ?? "ms") as ShotSize;
    const start = frameShot({ ...rig.start, target: centroid(actors) }, size, actors[0], actors, ASPECT);
    const moved = applyMove({ ...rig, start }, rig.move, centroid(actors));
    return { version: 1, aspect: ASPECT, actors, rig: { ...moved, duration_ms: rig.duration_ms } };
  }
  return { version: 1, aspect: ASPECT, actors, rig };
}

/** 缓动曲线小图：横轴时间、纵轴运动进度，红点是当前时刻。 */
function EaseCurve({ easing, t }: { easing: Easing; t: number }) {
  const pts = Array.from({ length: 33 }, (_, i) => {
    const x = i / 32;
    return `${(x * 56 + 2).toFixed(1)},${(30 - ease(x, easing) * 26).toFixed(1)}`;
  }).join(" ");
  return (
    <svg className="ease" width="60" height="34" viewBox="0 0 60 34">
      <rect x="1" y="3" width="58" height="28" rx="3" />
      <polyline points={pts} />
      <circle cx={t * 56 + 2} cy={30 - ease(t, easing) * 26} r="2.6" />
    </svg>
  );
}

export default function Stage({ planId, shot, cast, onClose, onChanged }: Props) {
  const [stage, setStage] = useState<Stage3D | null>(null);
  const [regional, setRegional] = useState(true);
  const [plate, setPlate] = useState<string | undefined>();
  const [source, setSource] = useState<string | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [key, setKey] = useState<"start" | "end">("start");
  const [sel, setSel] = useState<Handle | null>(null);
  const [lower, setLower] = useState<"side" | "free">("side");
  const [fitKey, setFitKey] = useState(0);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");

  // ── 撤销／重做：连续拖动合成一步（停手 350ms 才记一笔）──
  const committed = useRef<Stage3D | null>(null);
  const past = useRef<Stage3D[]>([]);
  const future = useRef<Stage3D[]>([]);
  const restoring = useRef(false);
  const [, bump] = useState(0);

  const load = useCallback(() => api.blocking(shot.id).then(b => {
    setPlate(media(b.plate_url));
    setSource(b.source);
    setRegional(!!b.regional);
    const next = stageFrom(b, shot);
    committed.current = next;
    past.current = [];
    future.current = [];
    restoring.current = true;
    setStage(next);
    setFitKey(k => k + 1);
  }).catch(e => setMsg(String(e))), [shot]);

  useEffect(() => { load(); }, [shot.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!stage) return;
    if (restoring.current) { restoring.current = false; return; }
    const id = window.setTimeout(() => {
      if (committed.current && committed.current !== stage) {
        past.current.push(committed.current);
        if (past.current.length > 100) past.current.shift();
        future.current = [];
        bump(n => n + 1);
      }
      committed.current = stage;
    }, 350);
    return () => window.clearTimeout(id);
  }, [stage]);

  const undo = () => {
    if (stage && committed.current && committed.current !== stage) {
      past.current.push(committed.current);
      future.current = [];
      committed.current = stage;
    }
    const prev = past.current.pop();
    if (!prev || !committed.current) return;
    future.current.push(committed.current);
    committed.current = prev;
    restoring.current = true;
    setStage(prev);
    bump(n => n + 1);
  };
  const redo = () => {
    const next = future.current.pop();
    if (!next || !committed.current) return;
    past.current.push(committed.current);
    committed.current = next;
    restoring.current = true;
    setStage(next);
    bump(n => n + 1);
  };
  const hot = useRef({ undo, redo, onClose });
  hot.current = { undo, redo, onClose };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (e.key === "Escape") hot.current.onClose();
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) hot.current.redo(); else hot.current.undo();
        return;
      }
      if (tag === "INPUT" || tag === "SELECT") return;
      if (e.key === " ") { e.preventDefault(); setPlaying(p => !p); }
      if (e.key === "f" || e.key === "F") setFitKey(k => k + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // 回放：按真实时长走完 0→1
  const raf = useRef(0);
  useEffect(() => {
    if (!playing || !stage) return;
    let last = performance.now();
    let cur = t >= 1 ? 0 : t;
    const tick = (now: number) => {
      cur += (now - last) / stage.rig.duration_ms;
      last = now;
      if (cur >= 1) { setT(1); setPlaying(false); return; }
      setT(cur);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [playing]); // eslint-disable-line react-hooks/exhaustive-deps

  const subject = useMemo<Vec3>(() => (stage ? centroid(stage.actors) : [0, 1.2, 0]), [stage]);

  /** 起幅变了：预设运镜按新起幅重算落幅，保住用户调过的扫角、峰高、节奏与抖动。 */
  const withStart = useCallback((rig: Rig, start: CamPose): Rig => {
    if (rig.move === "custom") return rig.path === "arc" ? snapArcEnd({ ...rig, start }) : { ...rig, start };
    // 环绕以注视点为圆心：用起幅的注视点，不然调注视点高度会被预设改回去
    const next = applyMove({ ...rig, start }, rig.move, rig.path === "arc" ? start.target : subject);
    const kept: Rig = {
      ...next,
      sweep: rig.path === "arc" ? rig.sweep : next.sweep,
      peak: rig.path === "parabola" ? rig.peak : next.peak,
      duration_ms: rig.duration_ms, easing: rig.easing, shake: rig.shake,
    };
    return kept.path === "arc" ? snapArcEnd(kept) : kept;
  }, [subject]);

  const setRig = (fn: (r: Rig) => Rig) => setStage(s => (s ? { ...s, rig: fn(s.rig) } : s));
  const setActor = (id: string, fn: (a: Actor) => Actor) =>
    setStage(s => (s ? { ...s, actors: s.actors.map(a => (a.entity_id === id ? fn(a) : a)) } : s));

  const onDrag = useCallback((h: Handle, p: Vec3) => {
    setStage(s => {
      if (!s) return s;
      const r = s.rig;
      const up = (y: number) => Math.max(0.05, y);
      switch (h.kind) {
        case "actor":
          return { ...s, actors: s.actors.map(a => (a.entity_id === h.id ? { ...a, pos: [p[0], p[2]] as [number, number] } : a)) };
        case "actorYaw":
          return { ...s, actors: s.actors.map(a => (a.entity_id === h.id ? { ...a, yaw: Math.round(yawToward(a, p[0], p[2]) / 5) * 5 } : a)) };
        case "camStart":
          return { ...s, rig: withStart(r, { ...r.start, pos: [p[0], up(p[1]), p[2]] }) };
        case "camEnd": {
          const end = { ...r.end, pos: [p[0], up(p[1]), p[2]] as Vec3 };
          if (r.path === "arc") {
            const sweep = sweepFromEnd({ ...r, end });
            const move = r.move === "orbit_left" || r.move === "orbit_right"
              ? (sweep >= 0 ? "orbit_left" as const : "orbit_right" as const) : "custom" as const;
            return { ...s, rig: { ...r, end, sweep, move } };
          }
          return { ...s, rig: { ...r, end, move: "custom" } };
        }
        case "target": {
          const tgt: Vec3 = [p[0], Math.max(0, p[1]), p[2]];
          const base = r.path === "arc" ? { ...r, center: [p[0], 0, p[2]] as Vec3 } : r;
          const nr = withStart(base, { ...r.start, target: tgt });
          return { ...s, rig: nr.path === "arc" ? snapArcEnd({ ...nr, end: { ...nr.end, target: tgt } }) : nr };
        }
        case "control":
          return { ...s, rig: { ...r, control: [p[0], up(p[1]), p[2]], move: "custom" } };
        case "center":
          return { ...s, rig: snapArcEnd({ ...r, center: [p[0], 0, p[2]] }) };
        case "apex": {
          const mid = lerp3(r.start.pos, r.end.pos, 0.5);
          return { ...s, rig: { ...r, peak: round(p[1] - mid[1], 20) } };
        }
      }
      return s;
    });
  }, [withStart]);

  if (!stage) {
    return <div className="stage-wrap2"><div className="empty-state">{msg || "载入导演台…"}</div></div>;
  }

  const rig = stage.rig;
  const pose = key === "start" ? rig.start : rig.end;
  const pp = polar(pose);
  const editPose = (next: CamPose) => {
    if (key === "start") setRig(r => withStart(r, next));
    else setRig(r => (r.path === "arc"
      ? { ...r, end: next, sweep: sweepFromEnd({ ...r, end: next }) }
      : { ...r, end: next, move: "custom" }));
  };
  const selectedActor = sel?.kind === "actor" || sel?.kind === "actorYaw" ? sel.id : null;
  const byId = (id: string | null | undefined) => stage.actors.find(a => a.entity_id === id) ?? null;
  // 单人景别对准谁：选中的人 > 这一帧的焦点 > 第一位
  const who = byId(selectedActor) ?? byId(pose.focus) ?? stage.actors[0] ?? null;

  const startFigs = projectActors(stage.actors, rig.start, stage.aspect);
  const framed = framingOf(startFigs);
  const pair = leads(stage);
  const crossing = pair ? crossesAxis(rig, pair[0], pair[1]) : false;
  const ctx = { actors: stage.actors, aspect: stage.aspect };
  const english = describe(rig, ctx);
  const label = t === 0 ? "起幅" : t === 1 ? "落幅" : `${(t * rig.duration_ms / 1000).toFixed(2)}s`;

  async function act(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setMsg("");
    try {
      await fn();
      setMsg(`${name}：完成`);
      onChanged();
    } catch (e) {
      setMsg(`${name}失败：${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }
  const payload = () => ({
    figures: regional ? forServer(startFigs) : [],
    stage3d: stage,
    camera: {
      move: rig.move, video_move: videoMove(rig), description_en: english, shot_size: framed,
      path: rig.path, sweep: round(rig.sweep, 10), peak: round(rig.peak),
      lens_start: round(rig.start.lens), lens_end: round(rig.end.lens),
      roll_start: round(rig.start.roll ?? 0, 10), roll_end: round(rig.end.roll ?? 0, 10),
      aperture: rig.aperture ?? 4, focus_start: rig.start.focus ?? null, focus_end: rig.end.focus ?? null,
      duration_ms: rig.duration_ms, easing: rig.easing, shake: rig.shake, crosses_axis: crossing,
    },
  });
  const save = () => act("保存", async () => {
    const r = await api.saveStage(shot.id, payload());
    setSource(r.source);
  });
  const saveAndRender = () => act(regional ? "保存并重出首帧" : "保存并重出尾帧", async () => {
    await api.saveStage(shot.id, payload());
    if (regional) {
      setSource("stage");
      await api.firstFrame(planId, shot.id);
    } else {
      await api.lastFrame(planId, shot.id);
    }
  });
  const reset = () => act("恢复自动", async () => {
    await api.resetBlocking(shot.id);
    await load();
  });

  const face = (id: string) => media(cast.find(c => c.entity_id === id)?.views.bust);
  const otsSide = (a: Actor, b: Actor): 1 | -1 => {
    // 过肩机位留在当前机位这一侧，不越轴
    const cur = axisSide(a, b, pose.pos) || 1;
    return axisSide(a, b, overShoulder(pose, a, b, 1).pos) === cur ? 1 : -1;
  };

  return (
    <div className="stage-wrap2">
      <header className="stage-head">
        <b>3D 导演台</b>
        <span className="stat">镜 {shot.order_no} · 分镜 {sizeLabel(shot.shot_size)} · {stage.actors.length} 人 ·
          {regional ? ` 站位：${source === "stage" ? "导演台" : "按表演单自动"}` : " 单主体镜头：只定运镜"}</span>
        <div className="spacer" />
        <button disabled={!past.current.length && committed.current === stage} onClick={undo} title="⌘Z">撤销</button>
        <button disabled={!future.current.length} onClick={redo} title="⇧⌘Z">重做</button>
        <button onClick={() => setFitKey(k => k + 1)} title="F">适配视图</button>
        <span className="stat">空格 播放 · Esc 关闭</span>
        <button onClick={onClose}>关闭</button>
      </header>

      <div className="stage-grid">
        <section className="pane cam-pane">
          <div className="pane-title">机位视角 <small>{label} · {moveLabel(rig.move)} · 所见即首帧构图（t=0）</small></div>
          <div className="cam-holder">
            <CameraView stage={stage} t={t} plate={plate} selected={selectedActor} label={label} />
          </div>
          <Curves rig={rig} t={t} onSeek={v => { setPlaying(false); setT(v); }} />
          <div className="timeline">
            <button className="play" onClick={() => setPlaying(p => !p)}>{playing ? "❚❚" : "▶"}</button>
            <button className={`kf start${key === "start" ? " on" : ""}`} onClick={() => { setKey("start"); setT(0); setPlaying(false); }}>◆ 起幅</button>
            <div className="scrub">
              <input type="range" min={0} max={1} step={0.001} value={t}
                onChange={e => { setPlaying(false); setT(+e.target.value); }} />
              <div className="ticks" style={{ backgroundSize: `${100 / Math.max(1, rig.duration_ms / 500)}% 100%` }} />
            </div>
            <button className={`kf end${key === "end" ? " on" : ""}`} onClick={() => { setKey("end"); setT(1); setPlaying(false); }}>落幅 ◆</button>
            <EaseCurve easing={rig.easing} t={t} />
            <span className="stat tc">{(t * rig.duration_ms / 1000).toFixed(2)} / {(rig.duration_ms / 1000).toFixed(1)}s</span>
          </div>
        </section>

        <section className="pane top-pane">
          <div className="pane-title">俯视图 <small>拖人、橙点转身 · 绿起幅 橙落幅 · 黄注视点 · 红区越轴</small></div>
          <div className="view-holder">
            <TopView stage={stage} t={t} selected={sel} fitKey={fitKey} onGrab={setSel} onDrag={onDrag} />
          </div>
        </section>

        <section className="pane low-pane">
          <div className="pane-title tabs2">
            <button className={lower === "side" ? "on" : ""} onClick={() => setLower("side")}>侧视图</button>
            <button className={lower === "free" ? "on" : ""} onClick={() => setLower("free")}>3D 自由视角</button>
            <small>{lower === "side" ? "拖机位改高度与纵深 · 粉点调弧顶" : "左键转 · 右键平移 · 滚轮缩放"}</small>
          </div>
          <div className="view-holder">
            {lower === "side"
              ? <SideView stage={stage} t={t} selected={sel} fitKey={fitKey} onGrab={setSel} onDrag={onDrag} />
              : <FreeView stage={stage} t={t} plate={plate} fitKey={fitKey} />}
          </div>
        </section>

        <aside className="pane side-pane">
          <h4>运镜 <small>当前：{moveLabel(rig.move)}</small></h4>
          <div className="move-groups">
            {MOVE_GROUPS.map(g => (
              <div key={g.title} className="move-group">
                <span className="g">{g.title}</span>
                <div className="move-grid">
                  {g.moves.map(m => (
                    <button key={m.kind} title={m.hint} className={rig.move === m.kind ? "on" : ""}
                      onClick={() => setRig(r => applyMove(r, m.kind,
                        m.kind === "orbit_left" || m.kind === "orbit_right" ? [subject[0], r.start.target[1], subject[2]] : subject))}>
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <h4>轨迹与节奏</h4>
          <div className="seg">
            {PATHS.map(p => (
              <button key={p.kind} className={rig.path === p.kind ? "on" : ""}
                onClick={() => setRig(r => {
                  const n: Rig = { ...r, path: p.kind, move: "custom" };
                  if (p.kind === "arc") return snapArcEnd({ ...n, center: [subject[0], 0, subject[2]], sweep: r.sweep || 45 });
                  if (p.kind === "parabola") return { ...n, peak: r.peak || 1.2 };
                  if (p.kind === "bezier") {
                    const mid: Vec3 = [(r.start.pos[0] + r.end.pos[0]) / 2 + 1.5, (r.start.pos[1] + r.end.pos[1]) / 2,
                      (r.start.pos[2] + r.end.pos[2]) / 2 - 1.5];
                    return { ...n, control: mid };
                  }
                  return n;
                })}>
                {p.label}
              </button>
            ))}
          </div>
          {rig.path === "arc" && (
            <label className="row">环绕角度 <b>{Math.round(rig.sweep)}°</b>
              <input type="range" min={-360} max={360} step={1} value={rig.sweep}
                onChange={e => setRig(r => snapArcEnd({ ...r, sweep: +e.target.value,
                  move: r.move === "orbit_left" || r.move === "orbit_right" || r.move === "custom"
                    ? (+e.target.value >= 0 ? "orbit_left" : "orbit_right") : r.move }))} />
            </label>
          )}
          {rig.path === "parabola" && (
            <label className="row">弧顶高度 <b>{rig.peak.toFixed(1)} m</b>
              <input type="range" min={-2} max={6} step={0.1} value={rig.peak}
                onChange={e => setRig(r => ({ ...r, peak: +e.target.value }))} />
            </label>
          )}
          {rig.path === "bezier" && (
            <label className="row">控制点高度 <b>{rig.control[1].toFixed(1)} m</b>
              <input type="range" min={0.2} max={8} step={0.1} value={rig.control[1]}
                onChange={e => setRig(r => ({ ...r, control: [r.control[0], +e.target.value, r.control[2]] }))} />
            </label>
          )}
          <label className="row">时长 <b>{(rig.duration_ms / 1000).toFixed(1)} s</b>
            <input type="range" min={500} max={10000} step={100} value={rig.duration_ms}
              onChange={e => setRig(r => ({ ...r, duration_ms: +e.target.value }))} />
          </label>
          <label className="row">手持晃动 <b>{Math.round(rig.shake * 100)}%</b>
            <input type="range" min={0} max={1} step={0.05} value={rig.shake}
              onChange={e => setRig(r => ({ ...r, shake: +e.target.value }))} />
          </label>
          <div className="seg">
            {EASINGS.map(x => (
              <button key={x.kind} className={rig.easing === x.kind ? "on" : ""}
                onClick={() => setRig(r => ({ ...r, easing: x.kind }))}>{x.label}</button>
            ))}
          </div>

          <h4>关键帧</h4>
          <div className="seg kseg">
            <button className={key === "start" ? "on start" : ""} onClick={() => { setKey("start"); setT(0); setPlaying(false); }}>◆ 起幅</button>
            <button className={key === "end" ? "on end" : ""} onClick={() => { setKey("end"); setT(1); setPlaying(false); }}>落幅 ◆</button>
          </div>
          <div className="sub">景别 <small>{who ? `（特写到中景对准 ${who.name}，全景以上框全体）` : ""}</small></div>
          <div className="chips">
            {SIZES.map(s => (
              <button key={s.kind} onClick={() => editPose(frameShot(pose, s.kind, who, stage.actors, stage.aspect))}>{s.label}</button>
            ))}
          </div>
          <div className="sub">角度</div>
          <div className="chips">
            {ANGLES.map(a => (
              <button key={a.kind} onClick={() => editPose(angleShot(pose, a.deg))}>{a.label}</button>
            ))}
          </div>
          {pair && (
            <>
              <div className="sub">过肩 <small>（机位留在轴线同侧）</small></div>
              <div className="chips">
                <button onClick={() => editPose(overShoulder(pose, pair[0], pair[1], otsSide(pair[0], pair[1])))}>过 {pair[1].name} 肩看 {pair[0].name}</button>
                <button onClick={() => editPose(overShoulder(pose, pair[1], pair[0], otsSide(pair[1], pair[0])))}>过 {pair[0].name} 肩看 {pair[1].name}</button>
              </div>
            </>
          )}
          <div className="sub">焦段</div>
          <div className="chips primes">
            {PRIMES.map(l => (
              <button key={l} className={Math.round(pose.lens) === l ? "on" : ""} onClick={() => editPose({ ...pose, lens: l })}>{l}</button>
            ))}
          </div>
          <label className="row">焦段 <b>{Math.round(pose.lens)} mm</b>
            <input type="range" min={14} max={135} step={1} value={pose.lens}
              onChange={e => editPose({ ...pose, lens: +e.target.value })} />
          </label>
          <label className="row">距离 <b>{pp.dist.toFixed(1)} m</b>
            <input type="range" min={0.5} max={30} step={0.1} value={pp.dist}
              onChange={e => editPose(fromPolar(pose, +e.target.value, pp.az, pp.height))} />
          </label>
          <label className="row">方位角 <b>{Math.round(pp.az)}°</b>
            <input type="range" min={-180} max={180} step={1} value={pp.az}
              onChange={e => editPose(fromPolar(pose, pp.dist, +e.target.value, pp.height))} />
          </label>
          <label className="row">机位高度 <b>{pp.height.toFixed(2)} m</b>
            <input type="range" min={0.1} max={12} step={0.05} value={pp.height}
              onChange={e => editPose(fromPolar(pose, pp.dist, pp.az, +e.target.value))} />
          </label>
          <label className="row">注视点高 <b>{pose.target[1].toFixed(2)} m</b>
            <input type="range" min={0} max={3} step={0.05} value={pose.target[1]}
              onChange={e => editPose({ ...pose, target: [pose.target[0], +e.target.value, pose.target[2]] })} />
          </label>
          <label className="row">荷兰角 <b>{Math.round(pose.roll ?? 0)}°</b>
            <input type="range" min={-45} max={45} step={1} value={pose.roll ?? 0}
              onChange={e => editPose({ ...pose, roll: +e.target.value })} />
          </label>
          <label className="row">焦点
            <select value={pose.focus ?? ""} onChange={e => {
              const focus = e.target.value || null;
              // 焦点不是运镜：只改这一帧的焦点，不把预设改成自定义
              setRig(r => (key === "start" ? { ...r, start: { ...r.start, focus } } : { ...r, end: { ...r.end, focus } }));
            }}>
              <option value="">不指定</option>
              {stage.actors.map(a => <option key={a.entity_id} value={a.entity_id}>{a.name}</option>)}
            </select>
          </label>
          <div className="sub">光圈 <small>（越小景深越浅）</small></div>
          <div className="chips primes">
            {STOPS.map(f => (
              <button key={f} className={(rig.aperture ?? 4) === f ? "on" : ""} onClick={() => setRig(r => ({ ...r, aperture: f }))}>f/{f}</button>
            ))}
            <button className={(rig.aperture ?? 4) === 4 ? "on" : ""} onClick={() => setRig(r => ({ ...r, aperture: 4 }))}>默认</button>
          </div>

          <h4>演员 {stage.actors.length > 1 && (
            <span className="h-actions">
              <button onClick={() => {
                if (!pair) return;
                const [a, b] = pair;
                setActor(a.entity_id, x => ({ ...x, yaw: Math.round(yawToward(x, b.pos[0], b.pos[1])) }));
                setActor(b.entity_id, x => ({ ...x, yaw: Math.round(yawToward(x, a.pos[0], a.pos[1])) }));
              }}>两人相对</button>
              <button onClick={() => stage.actors.forEach(a =>
                setActor(a.entity_id, x => ({ ...x, yaw: Math.round(yawToward(x, rig.start.pos[0], rig.start.pos[2])) })))}>面向机位</button>
            </span>
          )}</h4>
          {!stage.actors.length && <div className="note">表演单里这一镜没有在画面里的人。</div>}
          {stage.actors.map(a => (
            <div key={a.entity_id} className={`fig-row${selectedActor === a.entity_id ? " on" : ""}`}
              onClick={() => setSel({ kind: "actor", id: a.entity_id })}>
              <div className="fig-head">
                {face(a.entity_id) && <img src={face(a.entity_id)} alt="" className="face" />}
                <b>{a.name}</b>
                <span className="stat" style={{ marginLeft: "auto" }}>
                  {startFigs.some(f => f.entity_id === a.entity_id) ? "在起幅画面内" : "出画"}
                </span>
              </div>
              <label className="row">朝向 <b>{Math.round(a.yaw)}°</b>
                <input type="range" min={-180} max={180} step={5} value={a.yaw}
                  onChange={e => setActor(a.entity_id, x => ({ ...x, yaw: +e.target.value }))} />
              </label>
              <label className="row">身高 <b>{a.height.toFixed(2)} m</b>
                <input type="range" min={1.1} max={2.1} step={0.01} value={a.height}
                  onChange={e => setActor(a.entity_id, x => ({ ...x, height: +e.target.value }))} />
              </label>
            </div>
          ))}

          <h4>交给出图的</h4>
          <div className="compile">
            {regional
              ? <div>首帧：起幅画面里 <b>{startFigs.length}</b> 人按站位分区出图
                  {startFigs.length < 2 && <span className="warn">（少于 2 人，首帧不走分区身份）</span>}</div>
              : <div>首帧：单主体镜头，按分镜景别与主体参考出图；这里的运镜交给视频与尾帧</div>}
            <div>起幅取景：<b>{sizeLabel(framed)}</b>
              {framed && framed !== shot.shot_size && <span className="warn">（分镜写的是{sizeLabel(shot.shot_size)}{regional ? "，首帧提示词按台上的取景写" : ""}）</span>}</div>
            {crossing && <div className="warn">运镜越过了 {pair?.[0].name}—{pair?.[1].name} 的 180° 轴线：前后镜的左右关系会反，确认是有意为之</div>}
            <div className="en">{english}</div>
            <div>视频运镜参数：{videoMove(rig) ? <code>{videoMove(rig)}</code> : <span className="muted">工作台无对应词，只靠英文描述</span>}</div>
            <div>视频约束：{rig.move === "static" || rig.move === "handheld"
              ? "首帧＋尾帧"
              : <span>只给首帧＋运镜描述<span className="muted">（本机尾帧是编辑首帧得来的，挪不动机位，拿它钉结尾会把运镜压掉）</span></span>}</div>
          </div>
          <div className="actions">
            <button className="primary" disabled={!!busy} onClick={saveAndRender}>
              {busy.startsWith("保存并") ? "提交中…" : regional ? "保存并重出首帧" : "保存并重出尾帧"}
            </button>
            <button disabled={!!busy} onClick={save}>保存</button>
            <button disabled={!!busy || (source !== "stage" && !shot.camera?.rig)} onClick={reset}>恢复自动</button>
          </div>
          {msg && <div className={msg.includes("失败") ? "err" : "note"}>{msg}</div>}
        </aside>
      </div>
    </div>
  );
}
