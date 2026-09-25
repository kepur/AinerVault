/**
 * 右侧面板：项目资产树／属性／源码。
 */
import { useMemo, useState } from "react";
import type { CamKey, Cut, Overrides, SceneDoc, SceneObject, Vec3 } from "../scene/types";
import type { SceneEval } from "../scene/evaluate";
import { PREFABS } from "../scene/prefabs";
import { CAMERA_PRESETS } from "../scene/cameraPresets";
import type { Project } from "./api";
import type { Clock } from "./clock";
import { useClock } from "./clock";
import { camColor, type EditorApi, type Sel } from "./EditorView";
import { mergeKeys, presetKeys } from "./presets";

type Tab = "assets" | "props" | "code";

const GROUP_ORDER = ["机位", "人物", "交通", "建筑", "街道", "自然", "室内", "道具", "动物", "标记", "地面带", "基本体", "组"];
function groupOf(o: SceneObject): string {
  if (o.kind === "character") return "人物";
  if (o.kind === "strip") return "地面带";
  if (o.kind === "prim") return "基本体";
  if (o.kind === "group") return "组";
  return PREFABS[o.prefab ?? ""]?.category ?? "道具";
}

interface Props {
  project: Project;
  doc: SceneDoc;
  ev: SceneEval;
  clock: Clock;
  sel: Sel | null;
  onSelect: (s: Sel | null) => void;
  overrides: Overrides;
  setOverrides: (o: Overrides, note: string) => void;
  editorApi: React.MutableRefObject<EditorApi | null>;
  onRunCode: (code: string) => Promise<void>;
  onRestore: (index: number) => Promise<void>;
  tab: Tab;
  setTab: (t: Tab) => void;
}

export function SidePanel(p: Props) {
  return (
    <aside className="box-side">
      <div className="tabs">
        <button className={p.tab === "assets" ? "on" : ""} onClick={() => p.setTab("assets")}>项目资产</button>
        <button className={p.tab === "props" ? "on" : ""} onClick={() => p.setTab("props")}>属性</button>
        <button className={p.tab === "code" ? "on" : ""} onClick={() => p.setTab("code")}>源码</button>
      </div>
      {p.tab === "assets" && <Assets {...p} />}
      {p.tab === "props" && <Props_ {...p} />}
      {p.tab === "code" && <Code {...p} />}
    </aside>
  );
}

function Assets({ doc, sel, onSelect, overrides, setOverrides, setTab }: Props) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({ 机位: true, 人物: true, 交通: true });
  const groups = useMemo(() => {
    const m = new Map<string, SceneObject[]>();
    for (const o of doc.objects) {
      if (q && !(o.id.includes(q) || o.name.includes(q) || (o.prefab ?? "").includes(q))) continue;
      const g = groupOf(o);
      m.set(g, [...(m.get(g) ?? []), o]);
    }
    return m;
  }, [doc, q]);
  const hidden = (id: string) => !!overrides.objects?.[id]?.hidden;
  const toggleHidden = (id: string) => {
    const objs = { ...(overrides.objects ?? {}) };
    const cur = { ...(objs[id] ?? {}) };
    cur.hidden = !cur.hidden;
    if (!cur.hidden) delete cur.hidden;
    if (Object.keys(cur).length) objs[id] = cur; else delete objs[id];
    setOverrides({ ...overrides, objects: objs }, cur.hidden ? `隐藏 ${id}` : `显示 ${id}`);
  };
  const cams = doc.cameras.filter(c => !q || c.name.includes(q) || c.id.includes(q));
  return (
    <div className="assets">
      <input className="search" placeholder="搜索名字 / 预制件" value={q} onChange={e => setQ(e.target.value)} />
      <div className="grp">
        <button className="grp-h" onClick={() => setOpen(o => ({ ...o, 机位: !o.机位 }))}>{open.机位 ? "▾" : "▸"} 机位 <small>{cams.length}</small></button>
        {open.机位 && cams.map(c => (
          <div key={c.id} className={`row${sel && sel.kind !== "object" && sel.id === c.id ? " on" : ""}`}
            onClick={() => { onSelect({ kind: "camera", id: c.id }); setTab("props"); }}>
            <i className="dot" style={{ background: camColor(doc, c.id) }} /> {c.name}
            <small>{c.lens}mm · {c.keys.length} 帧</small>
          </div>
        ))}
      </div>
      {GROUP_ORDER.filter(g => groups.has(g)).map(g => (
        <div key={g} className="grp">
          <button className="grp-h" onClick={() => setOpen(o => ({ ...o, [g]: !o[g] }))}>{open[g] ? "▾" : "▸"} {g} <small>{groups.get(g)!.length}</small></button>
          {open[g] && groups.get(g)!.map(o => (
            <div key={o.id} className={`row${sel?.kind === "object" && sel.id === o.id ? " on" : ""}${hidden(o.id) ? " hid" : ""}`}
              onClick={() => { onSelect({ kind: "object", id: o.id }); }}>
              <span className="nm">{o.name !== o.id && !o.id.startsWith(o.name) ? `${o.name}` : o.id}</span>
              <small>{o.kind === "prefab" ? PREFABS[o.prefab!]?.zh : o.kind === "character" ? o.body : ""}{o.track ? " · 动" : ""}</small>
              <button className="eye" title={hidden(o.id) ? "显示" : "隐藏"} onClick={e => { e.stopPropagation(); toggleHidden(o.id); }}>{hidden(o.id) ? "◌" : "●"}</button>
            </div>
          ))}
        </div>
      ))}
      {!doc.objects.length && <div className="note">场景还是空的：在下面的对话框里描述你想要的场景。</div>}
    </div>
  );
}

function Num({ label, value, step = 0.1, onChange }: { label: string; value: number; step?: number; onChange: (v: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <label className="num">
      <span>{label}</span>
      <input type="number" step={step} value={draft ?? String(+value.toFixed(3))}
        onChange={e => setDraft(e.target.value)}
        onBlur={() => { if (draft !== null && draft !== "" && Number.isFinite(+draft)) onChange(+draft); setDraft(null); }}
        onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
    </label>
  );
}

function Props_(p: Props) {
  const { sel, doc } = p;
  if (!sel) return <div className="note" style={{ padding: 12 }}>在场景里点一个物体或机位，或者在「项目资产」里选。</div>;
  if (sel.kind === "object") {
    const o = doc.objects.find(x => x.id === sel.id);
    return o ? <ObjectProps {...p} o={o} /> : <div className="note">已不存在</div>;
  }
  const c = doc.cameras.find(x => x.id === sel.id);
  return c ? <CameraProps {...p} camId={c.id} /> : <div className="note">已不存在</div>;
}

function ObjectProps({ o, overrides, setOverrides }: Props & { o: SceneObject }) {
  const t = o.transform;
  const set = (patch: { pos?: Vec3; rot?: Vec3; scale?: Vec3; color?: string }, note: string) => {
    const objs = { ...(overrides.objects ?? {}) };
    objs[o.id] = { ...(objs[o.id] ?? {}), ...patch };
    setOverrides({ ...overrides, objects: objs }, note);
  };
  const reset = () => {
    const objs = { ...(overrides.objects ?? {}) };
    delete objs[o.id];
    setOverrides({ ...overrides, objects: objs }, `恢复 ${o.id}`);
  };
  const def = o.prefab ? PREFABS[o.prefab] : null;
  return (
    <div className="props">
      <h4>{o.name} <small>{o.id}</small></h4>
      <div className="note">{def ? `${def.zh} · ${def.doc}` : o.kind === "character" ? `人物 · ${o.body}` : o.kind}</div>
      <div className="sub">位置</div>
      <div className="vec">
        {(["X", "Y", "Z"] as const).map((l, i) => <Num key={l} label={l} value={t.pos[i]} onChange={v => { const q = [...t.pos] as Vec3; q[i] = v; set({ pos: q }, `移动 ${o.id}`); }} />)}
      </div>
      <div className="sub">缩放</div>
      <div className="vec">
        {(["X", "Y", "Z"] as const).map((l, i) => <Num key={l} label={l} value={t.scale[i]} step={0.05} onChange={v => { const q = [...t.scale] as Vec3; q[i] = v; set({ scale: q }, `缩放 ${o.id}`); }} />)}
      </div>
      <div className="sub">旋转（度）</div>
      <div className="vec">
        {(["X", "Y", "Z"] as const).map((l, i) => <Num key={l} label={l} value={t.rot[i]} step={5} onChange={v => { const q = [...t.rot] as Vec3; q[i] = v; set({ rot: q }, `旋转 ${o.id}`); }} />)}
      </div>
      {o.kind !== "strip" && (
        <label className="row-inline">颜色 <input type="color" value={o.color ?? "#dfe3e8"} onChange={e => set({ color: e.target.value }, `改色 ${o.id}`)} /></label>
      )}
      {o.track && <div className="note">这个物体有动画：拖动或改位置会整体平移它的路线。</div>}
      {overrides.objects?.[o.id] && <button onClick={reset}>恢复脚本里的样子</button>}
    </div>
  );
}

function CameraProps({ camId, doc, ev, clock, overrides, setOverrides, editorApi, onSelect, sel }: Props & { camId: string }) {
  useClock(clock, 200);
  const cam = doc.cameras.find(c => c.id === camId)!;
  const [preset, setPreset] = useState("orbit_left");
  const [target, setTarget] = useState<string>(() => doc.objects.find(o => o.kind === "character")?.id ?? doc.objects.find(o => o.track)?.id ?? "");
  const [dur, setDur] = useState(3);
  const setCam = (patch: { keys?: CamKey[]; lens?: number; ease?: "linear" | "smooth"; path?: "linear" | "curve" }, note: string) => {
    const cams = { ...(overrides.cameras ?? {}) };
    cams[camId] = { keys: cam.keys, ...(cams[camId] ?? {}), ...patch };
    setOverrides({ ...overrides, cameras: cams }, note);
  };
  const applyView = () => {
    const v = editorApi.current?.view();
    if (!v) return;
    const t = +clock.t.toFixed(2);
    setCam({ keys: mergeKeys(cam.keys, [{ t, at: v.pos.map(x => +x.toFixed(2)) as Vec3, look: v.look.map(x => +x.toFixed(2)) as Vec3 }]) }, `机位 ${cam.name} 在 ${t}s 加关键帧`);
  };
  const cuts: Cut[] = overrides.cuts ?? doc.cuts;
  const cutHere = () => {
    const t = +clock.t.toFixed(2);
    const next = [...cuts.filter(c => Math.abs(c.t - t) > 0.05), { t, camera: camId }].sort((a, b) => a.t - b.t);
    setOverrides({ ...overrides, cuts: next }, `${t}s 切到 ${cam.name}`);
  };
  const targets = doc.objects.filter(o => o.kind === "character" || o.track || (o.kind === "prefab" && o.name !== o.prefab));
  return (
    <div className="props">
      <h4><i className="dot" style={{ background: camColor(doc, camId) }} /> {cam.name} <small>机位</small></h4>
      <label className="row-inline">焦段 <b>{cam.lens}mm</b>
        <input type="range" min={14} max={135} value={cam.lens} onChange={e => setCam({ lens: +e.target.value }, `焦段 ${e.target.value}mm`)} />
      </label>
      <div className="seg">
        <button className={cam.ease === "smooth" ? "on" : ""} onClick={() => setCam({ ease: "smooth" }, "缓入缓出")}>缓入缓出</button>
        <button className={cam.ease === "linear" ? "on" : ""} onClick={() => setCam({ ease: "linear" }, "匀速")}>匀速</button>
        <button className={cam.path === "curve" ? "on" : ""} onClick={() => setCam({ path: "curve" }, "曲线轨迹")}>曲线</button>
        <button className={cam.path === "linear" ? "on" : ""} onClick={() => setCam({ path: "linear" }, "直线轨迹")}>直线</button>
      </div>
      <div className="sub">关键帧 <small>（时间轴上的菱形；场景里的菱形可以拖）</small></div>
      <div className="keylist">
        {cam.keys.map((k, i) => (
          <div key={i} className={`key-row${sel?.kind === "key" && sel.index === i ? " on" : ""}`} onClick={() => { onSelect({ kind: "key", id: camId, index: i }); clock.pause(); clock.seek(k.t); }}>
            <Num label="t" value={k.t} step={0.1} onChange={v => setCam({ keys: cam.keys.map((x, j) => (j === i ? { ...x, t: Math.max(0, v) } : x)).sort((a, b) => a.t - b.t) }, "改关键帧时间")} />
            <span className="kind">{k.follow ? `跟随 ${k.follow}` : k.orbit ? `环绕 ${k.orbit} ${Math.round(k.angle ?? 0)}°` : "世界坐标"}</span>
            <button className="ghost" title="删掉这个关键帧" onClick={e => { e.stopPropagation(); setCam({ keys: cam.keys.filter((_, j) => j !== i) }, "删关键帧"); }}>×</button>
          </div>
        ))}
      </div>
      <button onClick={applyView} title="C">◆ 应用当前视角到此机位（{clock.t.toFixed(1)}s）</button>
      <button onClick={cutHere}>✂ 从 {clock.t.toFixed(1)}s 起切到这台机位</button>
      <div className="sub">运镜预设</div>
      <select value={preset} onChange={e => setPreset(e.target.value)}>
        {["固定", "推拉", "摇", "移", "跟拍", "环绕", "航拍", "特殊"].map(g => (
          <optgroup key={g} label={g}>
            {CAMERA_PRESETS.filter(p => p.group === g).map(p => <option key={p.id} value={p.id}>{p.zh}</option>)}
          </optgroup>
        ))}
      </select>
      <div className="note">{CAMERA_PRESETS.find(x => x.id === preset)?.doc}</div>
      <label className="row-inline">目标
        <select value={target} onChange={e => setTarget(e.target.value)}>
          <option value="">（场景中心）</option>
          {targets.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      </label>
      <label className="row-inline">时长 <Num label="" value={dur} step={0.5} onChange={v => setDur(Math.max(0.3, v))} /> 秒，从 {clock.t.toFixed(1)}s 开始</label>
      <button className="primary" onClick={() => {
        const r = presetKeys(ev, cam, preset, target || null, +clock.t.toFixed(2), dur);
        setCam({ keys: mergeKeys(cam.keys, r.keys), ...(r.ease ? { ease: r.ease } : {}), ...(r.path ? { path: r.path } : {}) },
          `${cam.name} 套用 ${CAMERA_PRESETS.find(x => x.id === preset)?.zh}`);
      }}>套用预设</button>
      {overrides.cameras?.[camId] && <button onClick={() => { const cams = { ...(overrides.cameras ?? {}) }; delete cams[camId]; setOverrides({ ...overrides, cameras: cams }, "恢复机位"); }}>恢复脚本里的机位</button>}
    </div>
  );
}

function Code({ project, onRunCode, onRestore }: Props) {
  // 没改过就一直显示服务器上的最新版（智能体改了脚本，这里跟着变）；改过才是草稿
  const server = project.files["scene.js"] ?? "";
  const [draft, setDraft] = useState<string | null>(null);
  const code = draft ?? server;
  const setCode = (v: string) => setDraft(v === server ? null : v);
  const [busy, setBusy] = useState(false);
  const dirty = draft !== null && draft !== server;
  const d = project.diagnostics;
  return (
    <div className="code">
      <div className="code-bar">
        <b>scene.js</b>{dirty && <small>（未运行）</small>}
        <div className="spacer" />
        {dirty && <button onClick={() => setDraft(null)}>放弃</button>}
        <button className="primary" disabled={!dirty || busy} onClick={async () => { setBusy(true); try { await onRunCode(code); setDraft(null); } finally { setBusy(false); } }}>运行</button>
      </div>
      <textarea spellCheck={false} value={code} onChange={e => setCode(e.target.value)} />
      <div className="diag">
        {d.ok ? <div className="ok">✓ 编译通过（{d.ms}ms）</div> : d.errors.map((e, i) => <div key={i} className="bad">✗ {e.line ? `第 ${e.line} 行：` : ""}{e.message}</div>)}
        {d.warnings.map((w, i) => <div key={i} className="warn">⚠ {w}</div>)}
      </div>
      {project.files["notes.md"] && <details><summary>导演笔记 notes.md</summary><pre className="notes">{project.files["notes.md"]}</pre></details>}
      <details>
        <summary>版本历史（{project.versions.length}）</summary>
        {project.versions.slice().reverse().map(v => (
          <div key={v.index} className="ver">
            <span>{v.at.replace("T", " ").slice(5, 16)} · {v.by === "agent" ? "智能体" : "手改"} · {v.note}</span>
            <button onClick={() => onRestore(v.index)}>回到这版</button>
          </div>
        ))}
      </details>
    </div>
  );
}
