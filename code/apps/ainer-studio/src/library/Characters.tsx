/**
 * 角色库：我的（小说里的角色＋我存下的造型）/ 官方，按性别、年龄段、文化区域筛。
 * 详情：全身、半身、表情九宫格、三视图（小说角色显示它的多角度参考图）、音色（本机 TTS 现合成试听）、
 * 编辑角色（进造型室）、生成角色资产、添加到画布（放进 3D-BOX 预演，人偶带着角色库 id）。
 * 出图都在本机一张一张跑：有任务在排的卡片定时刷新。
 */
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { media } from "../api";
import { box, type ProjectRow } from "../box/api";
import { bodyOf, lib, waitJob, type CharCard, type Voice } from "./api";

const StylingRoom = lazy(() => import("./StylingRoom"));

const GENDERS = ["男", "女"];
const AGES = ["儿童", "少年", "青年", "中年", "老年"];
const CULTURES = ["东亚", "欧美", "混合"];
const SOURCE_ZH: Record<CharCard["source"], string> = { novel: "小说角色", official: "官方", mine: "我的造型" };

const img = (v: unknown) => (typeof v === "string" && v ? media(v) : undefined);

function Filter({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <div className="filter">
      <span>{label}</span>
      <div className="chips">
        <button className={!value ? "on" : ""} onClick={() => onChange("")}>全部</button>
        {options.map(o => <button key={o} className={value === o ? "on" : ""} onClick={() => onChange(o)}>{o}</button>)}
      </div>
    </div>
  );
}

function CharThumb({ c, onOpen }: { c: CharCard; onOpen: () => void }) {
  const t = c.tags ?? {};
  return (
    <div className="char-card" onClick={onOpen}>
      <div className="pic">
        {img(c.cover) ? <img src={img(c.cover)} alt={c.name} loading="lazy" /> : (
          <div className="silhouette"><span>{c.name.slice(0, 1)}</span>{c.pending ? <em>立绘生成中…</em> : <em>还没有立绘</em>}</div>
        )}
        {!!c.pending && img(c.cover) && <span className="badge busy">出图中 {c.pending}</span>}
      </div>
      <div className="meta">
        <b>{c.name}</b>
        <div className="tags">{[t.gender, t.age, t.culture, t.era].filter(x => x && x !== "未知").map(x => <span key={x}>{x}</span>)}</div>
        <small>{c.source === "novel" ? `《${c.novel ?? ""}》` : SOURCE_ZH[c.source]}</small>
      </div>
    </div>
  );
}

/** 添加到画布：放进某个 3D-BOX 预演（或新建一个），人偶带着角色库 id */
export function AddToBox({ card, onDone, onClose }: { card: CharCard; onDone: (projectId: string) => void; onClose: () => void }) {
  const [rows, setRows] = useState<ProjectRow[]>([]);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { box.projects().then(setRows).catch(e => setErr(String(e.message ?? e))); }, []);
  const add = async (pid: string | null) => {
    setBusy(pid ?? "new");
    try {
      const p = pid ? await box.get(pid) : await box.create(`${card.name} 的预演`, "blank");
      const code = p.files["scene.js"] ?? "";
      // 按场景里已有的人数往旁边错开 1.5 米：别和已有的人（常在原点附近）叠在一起
      const n = (p.doc?.objects ?? []).filter(o => o.kind === "character").length;
      const line = `// 角色库：${card.name}\nS.character(${JSON.stringify(card.name)}, { body: "${bodyOf(card.tags ?? {})}", ref: ${JSON.stringify(card.id)}, at: [${(n * 1.5).toFixed(1)}, 0], facing: 180 });\n`;
      await box.writeFile(p.id, "scene.js", `${code.trimEnd()}\n\n${line}`);
      onDone(p.id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  return (
    <div className="lib-modal" onClick={onClose}>
      <div className="add-box" onClick={e => e.stopPropagation()}>
        <header><b>把「{card.name}」放进 3D-BOX 预演</b><button className="ghost" onClick={onClose}>×</button></header>
        <p className="note">会在场景脚本末尾加一个人偶（体型按角色的性别年龄），带着角色库 id；之后在台上拖到位置、让智能体给它安排动作。</p>
        <button className="primary" disabled={!!busy} onClick={() => add(null)}>{busy === "new" ? "新建中…" : "＋ 新建一个预演"}</button>
        <div className="list">
          {rows.map(r => (
            <button key={r.id} disabled={!!busy} onClick={() => add(r.id)}>
              <b>{r.title}</b><small>{r.objects ?? 0} 个物体 · {r.duration ?? "?"}s</small>{busy === r.id && <em>添加中…</em>}
            </button>
          ))}
        </div>
        {err && <div className="err">{err}</div>}
      </div>
    </div>
  );
}

/** 音色：选一个、试听（本机 TTS 现合成）、存到角色上 */
export function VoicePicker({ voices, value, onChange, sample }: {
  voices: Voice[]; value: string; onChange: (v: Voice) => void; sample?: string;
}) {
  const [playing, setPlaying] = useState("");
  const [busy, setBusy] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);
  const cache = useRef(new Map<string, string>());
  const play = async (v: Voice) => {
    audio.current?.pause();
    let url = v.preview_url ? media(v.preview_url) : cache.current.get(v.voice_id);
    if (!url) {
      setBusy(v.voice_id);
      try {
        const { job_id } = await lib.previewVoice(v.voice_id, sample);
        const j = await waitJob(job_id, undefined, 5 * 60 * 1000);
        url = j.url ? media(j.url) : undefined;
        if (url) cache.current.set(v.voice_id, url);
      } finally {
        setBusy("");
      }
    }
    if (!url) return;
    const a = new Audio(url);
    audio.current = a;
    setPlaying(v.voice_id);
    a.onended = () => setPlaying("");
    void a.play();
  };
  useEffect(() => () => audio.current?.pause(), []);
  return (
    <div className="voice-list">
      {voices.map(v => (
        <div key={v.voice_id} className={`voice${value === v.voice_id ? " on" : ""}`} onClick={() => onChange(v)}>
          <button className="play" title="试听" onClick={e => { e.stopPropagation(); void play(v); }}>
            {busy === v.voice_id ? "…" : playing === v.voice_id ? "❚❚" : "▶"}
          </button>
          <span>{v.name}</span>
          <small>{v.gender === "female" ? "女" : v.gender === "male" ? "男" : ""}</small>
        </div>
      ))}
    </div>
  );
}

const VIEW_TABS = [
  { id: "front", zh: "全身" }, { id: "bust", zh: "半身" }, { id: "expressions", zh: "表情九宫格" }, { id: "turnaround", zh: "三视图" },
];

function Detail({ cid, voices, onClose, onEdit, onAdd, onChanged }: {
  cid: string; voices: Voice[]; onClose: () => void; onEdit: (c: CharCard) => void; onAdd: (c: CharCard) => void; onChanged: () => void;
}) {
  const [c, setC] = useState<CharCard | null>(null);
  const [tab, setTab] = useState("front");
  const [voice, setVoice] = useState("");
  const [msg, setMsg] = useState("");
  const load = useCallback(() => lib.character(cid).then(x => { setC(x); setVoice(v => v || x.voice?.voice_id || ""); }).catch(e => setMsg(String(e.message ?? e))), [cid]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!c?.pending) return;
    const t = window.setInterval(() => { load(); onChanged(); }, 4000);
    return () => window.clearInterval(t);
  }, [c?.pending, load, onChanged]);
  if (!c) return <div className="lib-modal"><div className="char-detail loading">{msg || "载入中…"}</div></div>;
  const v = c.views ?? {};
  const angles = ["front", "three_quarter_left", "profile_left", "back"].filter(k => img(v[k]));
  const show = (id: string) => {
    if (id === "turnaround" && !img(v.turnaround) && angles.length > 1) {
      return <div className="angles">{angles.map(k => <img key={k} src={img(v[k])} alt={k} />)}</div>;
    }
    const u = img(v[id]);
    if (u) return <img src={u} alt={id} />;
    const what = id === "front" ? "front" : id === "expressions" ? "expressions" : "views";
    return (
      <div className="missing">
        <span>{c.pending ? `出图中（还剩 ${c.pending} 张）…` : "还没生成"}</span>
        {!c.pending && (c.source !== "novel" || id === "expressions") && (
          <button onClick={async () => {
            const r = await lib.generate(c.id, what === "views" && !img(v.front) ? "all" : what);
            setMsg(r.queued ? `已排队 ${r.queued} 张（本机一张一张出）` : "已经在出了");
            load();
          }}>生成{VIEW_TABS.find(t => t.id === id)?.zh}</button>
        )}
      </div>
    );
  };
  const t = c.tags ?? {};
  return (
    <div className="lib-modal" onClick={onClose}>
      <div className="char-detail" onClick={e => e.stopPropagation()}>
        <section className="viewer">
          <div className="seg">
            {VIEW_TABS.map(x => <button key={x.id} className={tab === x.id ? "on" : ""} onClick={() => setTab(x.id)}>{x.zh}</button>)}
            {img(v.sheet) && <button className={tab === "sheet" ? "on" : ""} onClick={() => setTab("sheet")}>设定图</button>}
          </div>
          <div className={`stage ${tab}`}>{show(tab)}</div>
        </section>
        <section className="info">
          <header>
            <div>
              <b>{c.name}</b>
              <small>{c.source === "novel" ? `小说《${c.novel ?? ""}》的角色` : SOURCE_ZH[c.source]}</small>
            </div>
            <button className="ghost" onClick={onClose}>×</button>
          </header>
          <div className="tags">{[t.gender, t.age, t.culture, t.era].filter(x => x && x !== "未知").map(x => <span key={x}>{x}</span>)}</div>
          {(c.look || c.identity) && <p className="look">{c.look || c.identity}</p>}
          <h4>选择角色音色</h4>
          <VoicePicker voices={voices} value={voice} sample={`我是${c.name}。`} onChange={async vv => {
            setVoice(vv.voice_id);
            await lib.setVoice(c.id, vv.voice_id, vv.name);
            setMsg(`音色已设为 ${vv.name}`);
          }} />
          <div className="actions">
            <button className="primary" onClick={() => onEdit(c)} disabled={!img(v.front) && !img(c.cover)}
              title={img(v.front) || img(c.cover) ? "进造型室改发型、服装、肤质、身材" : "先生成立绘"}>编辑角色</button>
            <button onClick={() => onAdd(c)}>添加到画布</button>
            {c.source !== "novel" && (
              <button disabled={!!c.pending} onClick={async () => {
                const r = await lib.generate(c.id, "all");
                setMsg(r.queued ? `已排队：立绘→半身→三视图→表情九宫格（本机一张一张出）` : "已经在出了");
                load();
              }}>生成角色资产</button>
            )}
            {c.source !== "novel" && img(v.front) && (
              <button disabled={!!c.pending} title="立绘不满意就重出一张；半身、三视图、九宫格是从旧立绘派生的，会一并作废，需要时再生成"
                onClick={async () => {
                  if (!window.confirm("重新生成立绘？从旧立绘派生的半身、三视图、表情九宫格会一并作废。")) return;
                  const r = await lib.generate(c.id, "front", true);
                  setMsg(r.queued ? "已排队重出立绘（本机约 30 秒）" : "已经在出了");
                  load();
                }}>重新生成立绘</button>
            )}
          </div>
          {msg && <div className="note">{msg}</div>}
        </section>
      </div>
    </div>
  );
}

export default function Characters({ onOpenBox }: { onOpenBox: (id: string) => void }) {
  const [scope, setScope] = useState<"mine" | "official">("official");
  const [gender, setGender] = useState("");
  const [age, setAge] = useState("");
  const [culture, setCulture] = useState("");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<CharCard[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [editing, setEditing] = useState<CharCard | null>(null);
  const [adding, setAdding] = useState<CharCard | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(() => lib.characters(scope, { gender, age, culture, q: q.trim() || undefined })
    .then(setRows).catch(e => setErr(String(e.message ?? e))), [scope, gender, age, culture, q]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { lib.voices().then(setVoices).catch(() => setVoices([])); }, []);
  const pending = rows.some(r => r.pending);
  useEffect(() => {
    if (!pending) return;
    const t = window.setInterval(load, 5000);
    return () => window.clearInterval(t);
  }, [pending, load]);

  return (
    <div className="lib-page chars">
      <div className="lib-head">
        <h2>角色库</h2>
        <div className="seg big">
          <button className={scope === "mine" ? "on" : ""} onClick={() => setScope("mine")}>我的</button>
          <button className={scope === "official" ? "on" : ""} onClick={() => setScope("official")}>官方</button>
        </div>
        <div className="spacer" />
        <input className="search" placeholder="搜索角色名" value={q} onChange={e => setQ(e.target.value)} />
      </div>
      <div className="filters">
        <Filter label="性别" value={gender} options={GENDERS} onChange={setGender} />
        <Filter label="年龄段" value={age} options={AGES} onChange={setAge} />
        <Filter label="文化区域" value={culture} options={CULTURES} onChange={setCulture} />
      </div>
      {err && <div className="err">{err}</div>}
      <div className="card-grid chars">
        {rows.map(c => <CharThumb key={c.id} c={c} onOpen={() => setOpen(c.id)} />)}
      </div>
      {!rows.length && <div className="note center">{scope === "mine" ? "小说里的角色有参考图后会出现在这里；造型室里保存的造型也在这里" : "没有匹配的角色"}</div>}
      {open && !editing && (
        <Detail cid={open} voices={voices} onClose={() => setOpen(null)} onChanged={load}
          onEdit={c => setEditing(c)} onAdd={c => setAdding(c)} />
      )}
      {editing && (
        <Suspense fallback={<div className="lib-modal"><div className="char-detail loading">打开造型室…</div></div>}>
          <StylingRoom card={editing} voices={voices} onClose={() => { setEditing(null); load(); }}
            onSaved={(saved, thenAdd) => {
              setEditing(null);
              setScope("mine");
              setOpen(null);
              load();
              if (thenAdd) setAdding(saved);
            }} />
        </Suspense>
      )}
      {adding && <AddToBox card={adding} onClose={() => setAdding(null)} onDone={pid => { setAdding(null); onOpenBox(pid); }} />}
    </div>
  );
}
