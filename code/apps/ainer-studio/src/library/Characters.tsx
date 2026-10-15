/**
 * 角色库：我的（小说里的角色＋我存下的造型）/ 官方，按性别、年龄段、文化区域筛。
 * 详情：全身、半身、表情九宫格、三视图（小说角色显示它的多角度参考图）、音色（本机 TTS 现合成试听）、
 * 编辑角色（进造型室）、生成角色资产、添加到画布（放进 3D-BOX 预演，人偶带着角色库 id）。
 * 出图都在本机一张一张跑：有任务在排的卡片定时刷新。
 */
import { readCtx, writeCtx, navigate } from "../ctx";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { media } from "../api";
import { box, type ProjectRow } from "../box/api";
import { bodyOf, lib, waitJob, type CharCard, type Voice } from "./api";
import { CanonicalSheet } from "../production/CanonicalSheet";
import { prod, type EpochOption, type ResourceRef, type CanonicalView } from "../production/api";
import { cv } from "../canvas/api";
import type { CanvasMeta } from "../canvas/model";
import "../production/production.css";
import { useLocalNames, type LocalNames } from "../production/useLocalNames";

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

/** 小说角色的实体 id（卡片 id 是 e:<实体 id>） */
const entityOf = (c: CharCard) => c.entity_id ?? (c.id.startsWith("e:") ? c.id.slice(2) : null);

function CharThumb({ c, onOpen, names }: { c: CharCard; onOpen: () => void; names: LocalNames }) {
  const t = c.tags ?? {};
  // 英文版剧本里叫 Thomas Ashford、这里存的是原著名「谢文东」：卡片上两个都写，不然对不上剧本里的人
  const local = c.source === "novel" ? names.get(entityOf(c) ?? "") : undefined;
  return (
    <div className="char-card" onClick={onOpen}>
      <div className="pic">
        {img(c.cover) ? <img src={img(c.cover)} alt={c.name} loading="lazy" /> : (
          <div className="silhouette" title={c.missing ?? undefined}><span>{c.name.slice(0, 1)}</span>{c.pending ? <em>立绘生成中…</em> : <em>{c.missing ? "还没有定妆照" : "还没有立绘"}</em>}</div>
        )}
        {!!c.pending && img(c.cover) && <span className="badge busy">出图中 {c.pending}</span>}
      </div>
      <div className="meta">
        <b title={local ? `本版译名 ${local.target}，原名 ${c.name}` : undefined}>{local?.target || c.name}</b>
        {local && local.target !== c.name && <small className="char-orig">原名 {c.name}</small>}
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
  const sheet16 = tab === "sheet16";
  const show = (id: string) => {
    if (id === "sheet16") return c.entity_id ? <SheetBlock entityId={c.entity_id} /> : null;
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
      <div className={`char-detail${sheet16 ? " is-sheet16" : ""}`} onClick={e => e.stopPropagation()}>
        <section className="viewer">
          <div className="seg">
            {VIEW_TABS.map(x => <button key={x.id} className={tab === x.id ? "on" : ""} onClick={() => setTab(x.id)}>{x.zh}</button>)}
            {img(v.sheet) && <button className={tab === "sheet" ? "on" : ""} onClick={() => setTab("sheet")}>设定图</button>}
            {/* 16 格标准包只有小说角色有（官方/我的预设没有世界实体） */}
            {c.source === "novel" && c.entity_id &&
              <button className={tab === "sheet16" ? "on" : ""} onClick={() => setTab("sheet16")}>定妆照 16 格</button>}
          </div>
          <div className={`stage ${tab}`}>{show(tab)}</div>
        </section>
        {!sheet16 && <section className="info">
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
            <button onClick={() => onAdd(c)} title="在 3D-BOX 白模里加一个人偶，带着这个角色的角色库 id">放进 3D-BOX</button>
            {c.source === "novel" && (
              <button disabled={!!c.pending}
                title="定妆照画坏了（多出手、背景不是灰底、抬着手）就重出：本机先出正面全身，再按它补齐左前 3/4、头肩、侧面、背面，最后拼设定图。画布的分镜图都按定妆照画，重出后再画分镜图才换脸"
                onClick={async () => {
                  if (!window.confirm(`重出「${c.name}」的定妆照？正面全身会换成新的一张，其余角度跟着重出（本机约 3–5 分钟）。`)) return;
                  try {
                    await lib.references(c.id);
                    setMsg("已开始：正面全身 → 其余角度 → 设定图（本机一张一张出）");
                  } catch (e) { setMsg(String((e as Error).message ?? e)); }
                  load();
                }}>{c.refs_job?.state === "running" ? "定妆照重出中…" : "一键重出定妆照"}</button>
            )}
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
          {c.refs_job && (
            <div className={`note${c.refs_job.state === "failed" ? " err" : ""}`}>
              定妆照：{c.refs_job.state === "running" ? `重出中 · ${REFS_STEP[c.refs_job.step] ?? c.refs_job.step}`
                : c.refs_job.state === "done" ? "已重出（画布里重画分镜图就用新的）" : `没出成：${c.refs_job.error ?? ""}`}
              {!!c.refs_job.notes?.length && <small style={{ display: "block", opacity: .7 }}>{c.refs_job.notes.join("；")}</small>}
            </div>
          )}
          {msg && <div className="note">{msg}</div>}
        </section>}
      </div>
    </div>
  );
}

/** 选择真实世界/时期，从角色库直接引用到任意画布。 */
function SheetBlock({ entityId }: { entityId: string }) {
  const [epochs, setEpochs] = useState<EpochOption[]>([]);
  const [epoch, setEpoch] = useState("");
  const [boards, setBoards] = useState<CanvasMeta[]>([]);
  const [target, setTarget] = useState(readCtx().canvas || "");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    setLoading(true); setError(""); setEpoch("");
    Promise.all([prod.epochs(entityId), cv.canvasAll({ limit: 500 }), import('../canvas/comic').then(m=>m.comicBoards())]).then(([r, canvases,comicIds]) => {
      if (!alive) return;
      const c=readCtx();
      setEpochs(r.data.items); setBoards(canvases.filter(b=>!comicIds.includes(b.id)&&(c.workspace==='free'?!b.novel_id:b.novel_id===c.novel&&(!c.chapter||b.chapter_id===c.chapter))));
      if (r.data.items.length === 1) setEpoch(r.data.items[0].id);
    }).catch(e => { if (alive) setError(String(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [entityId]);
  const option = epochs.find(e => e.id === epoch);
  const create = async () => {
    setBusy(true); setError("");
    try {
      const b = await cv.canvasCreate({ title: "空白画布", blank: true, purpose: "general", source: "user" });
      setBoards(cur => [b, ...cur]); setTarget(b.id);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const use = async (ref: ResourceRef, view: CanonicalView) => {
    if (!target || busy) return;
    setBusy(true); setError("");
    try {
      const b = await cv.canvasGet(target);
      await prod.addReference(target, b.version, ref, `定妆照 · ${view.view_key}`);
      navigate("flow", { canvas: b.id, novel: b.novel_id, chapter: b.chapter_id, plan: b.plan_id, shot: null });
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  return <div>
    {loading && <div className="cs-loading">载入标准素材…</div>}
    {error && <div className="cs-err" role="alert">{error}</div>}
    <div className="cs-head">
      <select aria-label="选择世界观与造型时期" value={epoch} onChange={e => setEpoch(e.target.value)}>
        <option value="">选择世界观与造型时期</option>
        {epochs.map(e => <option key={e.id} value={e.id}>{e.world_name} · {e.name || e.epoch_key}</option>)}
      </select>
      <select aria-label="引用到哪张画布" value={target} onChange={e => setTarget(e.target.value)} disabled={busy}>
        <option value="">选择目标画布</option>
        {boards.map(b => <option key={b.id} value={b.id}>{b.title}</option>)}
      </select>
      <button type="button" onClick={() => void create()} disabled={busy}>新建空白画布</button>
    </div>
    {!loading && !epochs.length && <div className="cs-err">该角色还没有已保存的造型时期，请先创建角色素材。</div>}
    {option && <CanonicalSheet entityId={entityId} worldProfileId={option.world_profile_id} epochId={option.id}
      onUse={target && !busy ? (ref, view) => { void use(ref, view); } : undefined} />}
    {option && !target && <p>选择目标画布后，可将已有单格直接用到画布。</p>}
  </div>;
}

const REFS_STEP: Record<string, string> = { front: "正面全身", views: "其余角度", sheet: "拼设定图" };

export default function Characters({ onOpenBox }: { onOpenBox: (id: string) => void }) {
  // 带着书进来（地址栏 ?novel=）默认看这本书的角色；?char= 直接打开某个角色
  const [init] = useState(readCtx);
  const novelId = init.novel;
  const [scope, setScope] = useState<"book" | "mine" | "official">(novelId ? "book" : "official");
  const [gender, setGender] = useState("");
  const [age, setAge] = useState("");
  const [culture, setCulture] = useState("");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<CharCard[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [open, setOpenRaw] = useState<string | null>(init.char);
  const setOpen = (id: string | null) => { setOpenRaw(id); writeCtx({ char: id }); };
  const [editing, setEditing] = useState<CharCard | null>(null);
  const [adding, setAdding] = useState<CharCard | null>(null);
  const [err, setErr] = useState("");

  const names = useLocalNames(novelId, init.locale);
  // 本书的角色在前端按「原名 + 本版译名」搜：用户照着英文剧本搜 Thomas，后端只认识「谢文东」
  const localSearch = scope === "book" && names.size > 0;
  const load = useCallback(() => lib.characters(scope, {
    gender, age, culture, q: localSearch ? undefined : q.trim() || undefined, novel_id: scope === "book" ? novelId ?? undefined : undefined,
  }).then(setRows).catch(e => setErr(String(e.message ?? e))), [scope, gender, age, culture, localSearch ? "" : q, novelId, localSearch]); // eslint-disable-line react-hooks/exhaustive-deps
  const needle = q.trim().toLowerCase();
  const shown = localSearch && needle
    ? rows.filter(c => c.name.toLowerCase().includes(needle) || (names.get(entityOf(c) ?? "")?.target ?? "").toLowerCase().includes(needle))
    : rows;
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
          {novelId && <button className={scope === "book" ? "on" : ""} onClick={() => setScope("book")}
            title="这本书的角色（地址栏里的小说），连还没出定妆照的也列出来">本书</button>}
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
        {shown.map(c => <CharThumb key={c.id} c={c} names={names} onOpen={() => setOpen(c.id)} />)}
      </div>
      {!shown.length && <div className="note center">{scope === "book" ? "这本书还没有人物实体：先在后台出世界模型" : scope === "mine" ? "小说里的角色有参考图后会出现在这里；造型室里保存的造型也在这里" : "没有匹配的角色"}</div>}
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
