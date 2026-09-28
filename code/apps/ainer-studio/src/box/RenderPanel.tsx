/**
 * 渲染 · 成片：3D-BOX → Blender 控制素材 → LTX 成片。
 *
 * 一次「渲控制素材」= 一个 Blender 任务：按当前场景（脚本＋台上的手动改动）烘焙、Blender 无头渲出
 * 预演 / 白模 / 深度 / 骨架 / 边缘五路视频＋ camera.json / motion.json / scene.blend。
 * 在某次控制素材上「生成成片」= 一个 LTX 任务：提示词由 LLM 按场景协议写（可补充描述）。
 * 任务都在后端单线程队列里一个一个跑；这里只轮询状态。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SceneDoc } from "../scene/types";
import { media } from "../api";
import { director, type Features, type Job, type JobOutput } from "./director";

const PASSES = [
  { id: "preview", zh: "预演" }, { id: "clay", zh: "白模" }, { id: "depth", zh: "深度" },
  { id: "pose", zh: "骨架" }, { id: "canny", zh: "边缘" },
];
const RES = ["1024x576", "768x432", "1280x720", "576x1024"];
// LTX 2.5：Blender 的深度／骨架／边缘同时喂（2.3 Union Control IC-LoRA 挂 2.5），片子自带同步音效
const CONTROL_25 = [
  { id: "union", zh: "深度＋骨架＋边缘", doc: "三路控制一起喂：动作、站位、机位跟预演走，外观按提示词，带同步音效。1024×576 三秒约 6 分钟" },
  { id: "pose", zh: "只用骨架", doc: "只按骨架动作生成（打斗、舞蹈），场景更自由" },
  { id: "depth", zh: "只用深度", doc: "只按空间结构生成（场景、机位），人物动作更自由" },
];
const CONTROL = [
  { id: "v2v", zh: "白模重绘", doc: "预演视频加噪重绘：动作、运镜跟白模走，外观按提示词。本机 2B 可跑，6 秒约 100 秒" },
  { id: "pose", zh: "骨架控制", doc: "IC-LoRA：按骨架动作生成（打斗、舞蹈最稳）。需要 13B 0.9.7 底模" },
  { id: "depth", zh: "深度控制", doc: "IC-LoRA：按空间结构生成（场景、机位最稳）。需要 13B 0.9.7 底模" },
  { id: "canny", zh: "边缘控制", doc: "IC-LoRA：按轮廓生成。需要 13B 0.9.7 底模" },
];
const STAGE: Record<string, string> = {
  build: "建场景", walk: "骨架采样", pose: "骨架图", preview: "渲预演", clay: "渲白模", depth: "渲深度", canny: "边缘图",
  encode: "合成视频", prompt: "写提示词", first_frame: "画首帧", video: "生成视频", done: "完成",
};
const STATUS: Record<Job["status"], string> = { queued: "排队中", running: "进行中", succeeded: "完成", failed: "失败", cancelled: "已取消" };

const out = (j: Job, kind: string): JobOutput | undefined => j.outputs?.find(o => o.kind === kind);
const when = (s: string | null) => (s ? s.replace("T", " ").slice(5, 16) : "");

function Progress({ job }: { job: Job }) {
  const p = job.progress ?? {};
  const pct = job.status === "succeeded" ? 100 : p.percent ?? 0;
  const label = job.status === "running"
    ? `${STAGE[p.stage ?? ""] ?? p.stage ?? "准备"}${p.frame && p.total ? ` ${p.frame}/${p.total}` : ""}${p.task_status ? ` · ${p.task_status}` : ""}${p.elapsed ? ` · ${p.elapsed}s` : ""}${p.retry ? ` · 第 ${p.retry + 1} 次` : ""}`
    : STATUS[job.status];
  return (
    <div className={`rp-progress ${job.status}`}>
      <div className="bar"><i style={{ width: `${job.status === "running" && job.job_type === "final_render" ? 60 : pct}%` }} /></div>
      <span>{label}</span>
    </div>
  );
}

/** 四宫格同步播放：一个播放键管四路，拖动任意一路其余跟着跳 */
function SyncGrid({ job }: { job: Job }) {
  const refs = useRef<(HTMLVideoElement | null)[]>([]);
  const kinds = ["preview", "depth", "pose", "canny"].filter(k => out(job, k));
  const lead = () => refs.current.find(Boolean) ?? null;
  const all = (f: (v: HTMLVideoElement) => void) => refs.current.forEach(v => v && f(v));
  return (
    <div className="rp-grid">
      {kinds.map((k, i) => (
        <figure key={k}>
          <video ref={el => { refs.current[i] = el; }} src={media(out(job, k)!.url)} muted playsInline loop preload="auto"
            onSeeked={e => { const t = e.currentTarget.currentTime; all(v => { if (Math.abs(v.currentTime - t) > 0.05) v.currentTime = t; }); }} />
          <figcaption>{PASSES.find(p => p.id === k)?.zh}</figcaption>
        </figure>
      ))}
      <div className="rp-grid-bar">
        <button onClick={() => { const t = lead()?.currentTime ?? 0; all(v => { v.currentTime = t; void v.play(); }); }}>▶ 同步播放</button>
        <button onClick={() => all(v => v.pause())}>❚❚</button>
        <button onClick={() => all(v => { v.pause(); v.currentTime = 0; })}>⟲</button>
      </div>
    </div>
  );
}

function ControlJob({ job, finals, features, onFinal, onCancel }: {
  job: Job; finals: Job[]; features: Features | null;
  onFinal: (body: Parameters<typeof director.final>[1]) => void; onCancel: (id: string) => void;
}) {
  const [view, setView] = useState<string>("grid");
  const [engine, setEngine] = useState<"ltx_25" | "ltx_097">("ltx_25");
  const [ctype, setCtype] = useState("union");
  const [prompt, setPrompt] = useState("");
  const [denoise, setDenoise] = useState(0.92);
  const [seed, setSeed] = useState("");
  const ready = features?.renderers.ltx_097.control_types ?? ["v2v"];
  const files = ["blend", "camera_json", "motion_json", "manifest"].map(k => out(job, k)).filter(Boolean) as JobOutput[];
  const rp = (job.input.render_plan ?? {}) as { output_resolution?: number[]; camera?: string };
  return (
    <div className="rp-job">
      <div className="rp-job-head">
        <b>控制素材</b>
        <small>{when(job.created_at)} · {(rp.output_resolution ?? []).join("×")} · {String(job.input.frames ?? "")} 帧 · {rp.camera === "cut" ? "主机位剪辑" : rp.camera}</small>
        {(job.status === "queued" || job.status === "running") && <button className="ghost" onClick={() => onCancel(job.id)}>取消</button>}
      </div>
      <Progress job={job} />
      {job.error && <div className="rp-err">{job.error}</div>}
      {job.status === "succeeded" && (
        <>
          <div className="rp-tabs">
            <button className={view === "grid" ? "on" : ""} onClick={() => setView("grid")}>四宫格</button>
            {PASSES.filter(p => out(job, p.id)).map(p => (
              <button key={p.id} className={view === p.id ? "on" : ""} onClick={() => setView(p.id)}>{p.zh}</button>
            ))}
          </div>
          {view === "grid" ? <SyncGrid job={job} /> : (
            <video className="rp-video" src={media(out(job, view)?.url)} controls loop autoPlay muted playsInline />
          )}
          <div className="rp-files">
            {files.map(f => <a key={f.kind} href={media(f.url)} download>{f.kind === "blend" ? "scene.blend" : f.path}</a>)}
          </div>

          <div className="rp-final-form">
            <h4>AI 成片</h4>
            <div className="chips">
              <button className={engine === "ltx_25" ? "on" : ""} disabled={!features?.ltx25_enabled}
                title="LTX 2.5：动作跟着预演走，带同步音效" onClick={() => { setEngine("ltx_25"); setCtype("union"); }}>LTX 2.5（带声音）</button>
              <button className={engine === "ltx_097" ? "on" : ""} disabled={!features?.ltx097_enabled}
                title="LTX 0.9.7 2B：白模重绘，快、无声" onClick={() => { setEngine("ltx_097"); setCtype("v2v"); }}>LTX 0.9.7</button>
            </div>
            <div className="chips">
              {(engine === "ltx_25" ? CONTROL_25 : CONTROL).map(c => {
                const ok = engine === "ltx_25" || ready.includes(c.id);
                return (
                  <button key={c.id} className={ctype === c.id ? "on" : ""} disabled={!ok}
                    title={`${c.doc}${ok ? "" : "（本机未就绪）"}`} onClick={() => setCtype(c.id)}>{c.zh}</button>
                );
              })}
            </div>
            <textarea rows={2} placeholder="补充描述（可选，中文也行）：人物长相、服装、场景质感、画风… LLM 会结合场景写成英文提示词"
              value={prompt} onChange={e => setPrompt(e.target.value)} />
            <div className="rp-row">
              {engine === "ltx_097" && ctype === "v2v" && (
                <label title="越大越自由（越不像白模），越小越贴白模">重绘幅度
                  <input type="range" min={0.7} max={1} step={0.01} value={denoise} onChange={e => setDenoise(+e.target.value)} />
                  <em>{denoise.toFixed(2)}</em>
                </label>
              )}
              <label>种子 <input className="seed" value={seed} placeholder="随机" onChange={e => setSeed(e.target.value.replace(/[^0-9]/g, ""))} /></label>
              <button className="primary" disabled={engine === "ltx_25" ? !features?.ltx25_enabled : !features?.ltx097_enabled}
                onClick={() => onFinal({ renderer: engine, control_type: ctype, prompt: prompt.trim() || undefined,
                  denoise: ctype === "v2v" ? denoise : undefined, seed: seed ? Number(seed) : undefined })}>生成成片</button>
            </div>
          </div>
          {finals.map(f => (
            <div key={f.id} className="rp-final">
              <div className="rp-job-head">
                <b>成片</b>
                <small>{when(f.created_at)} · {CONTROL.find(c => c.id === f.input.control_type)?.zh ?? String(f.input.control_type)}
                  {f.input.denoise ? ` · 重绘 ${Number(f.input.denoise).toFixed(2)}` : ""}</small>
                {(f.status === "queued" || f.status === "running") && <button className="ghost" onClick={() => onCancel(f.id)}>取消</button>}
              </div>
              {f.status !== "succeeded" && <Progress job={f} />}
              {f.error && <div className="rp-err">{f.error}</div>}
              {out(f, "final") && <video className="rp-video" src={media(out(f, "final")!.url)} controls loop autoPlay muted playsInline />}
              {typeof f.input.prompt === "string" && (
                <details><summary>提示词（{f.input.prompt_by === "llm" ? "LLM 按场景写" : "模板"}）</summary><p>{f.input.prompt}</p></details>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

export function RenderPanel({ projectId, doc, onClose }: { projectId: string; doc: SceneDoc; onClose: () => void }) {
  const [features, setFeatures] = useState<Features | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [camera, setCamera] = useState("cut");
  const [res, setRes] = useState(RES[0]);
  const [passes, setPasses] = useState<string[]>(PASSES.map(p => p.id));
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => director.jobs(projectId).then(setJobs).catch(e => setErr(String(e.message ?? e))), [projectId]);
  useEffect(() => { director.features().then(setFeatures).catch(e => setErr(String(e.message ?? e))); load(); }, [load]);
  const running = jobs.some(j => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(load, 2000);
    return () => window.clearInterval(t);
  }, [running, load]);

  const controls = useMemo(() => jobs.filter(j => j.job_type === "blender_render"), [jobs]);
  const finalsOf = (id: string) => jobs.filter(j => j.job_type === "final_render" && j.parent_id === id);

  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      const [w, h] = res.split("x").map(Number);
      await director.blender(projectId, { camera, output_resolution: [w, h], passes });
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="render-panel">
      <header>
        <b>渲染 · 成片</b>
        <div className="rp-flags">
          <span className={features?.blender_enabled && features.blender.binary ? "on" : ""} title={features?.blender.version ?? ""}>Blender{features?.blender.version ? ` ${features.blender.version.split(" ")[1]}` : ""}</span>
          <span className={features?.ltx097_enabled ? "on" : ""}>LTX 0.9.7</span>
          <span className={features?.ltx25_enabled ? "on" : ""} title="V1 预埋、未启用">LTX 2.5</span>
          <span className={features?.ue_enabled ? "on" : ""} title="V1 预埋、未启用">UE</span>
        </div>
        <button className="ghost" onClick={onClose} title="关闭">×</button>
      </header>
      <div className="rp-body">
        <section className="rp-form">
          <h4>控制素材 · Blender 无头渲染</h4>
          <div className="rp-row">
            <label>机位
              <select value={camera} onChange={e => setCamera(e.target.value)}>
                <option value="cut">主机位剪辑（按切点）</option>
                {doc.cameras.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label>分辨率
              <select value={res} onChange={e => setRes(e.target.value)}>{RES.map(r => <option key={r} value={r}>{r.replace("x", "×")}</option>)}</select>
            </label>
          </div>
          <div className="chips">
            {PASSES.map(p => (
              <button key={p.id} className={passes.includes(p.id) ? "on" : ""}
                onClick={() => setPasses(s => (s.includes(p.id) ? s.filter(x => x !== p.id) : [...s, p.id]))}>{p.zh}</button>
            ))}
          </div>
          <div className="rp-row">
            <small>{doc.duration}s · {doc.fps}fps · 场景按当前脚本＋台上改动烘焙，一个一个排队渲</small>
            <button className="primary" disabled={busy || !features?.blender_enabled || !passes.length} onClick={submit}>渲染控制素材</button>
          </div>
          {err && <div className="rp-err">{err}</div>}
        </section>
        {controls.map(j => (
          <ControlJob key={j.id} job={j} finals={finalsOf(j.id)} features={features}
            onFinal={async body => {
              try { await director.final(j.id, body); await load(); } catch (e) { setErr((e as Error).message); }
            }}
            onCancel={async id => { await director.cancel(id); await load(); }} />
        ))}
        {!controls.length && <div className="note">还没有渲染过。渲一次控制素材，再从它生成成片。</div>}
      </div>
    </aside>
  );
}
