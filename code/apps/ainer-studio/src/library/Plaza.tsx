/**
 * 预设广场：风格 / 运镜 / 特效 / 爆款题材。
 *
 * 风格：卡片 = 本机出的封面＋名字＋作者＋用过几次＋可商用；收藏、最近使用；一键套到当前分镜
 *      （之后出的首帧、尾帧都带上这个风格；已出的图不动，重出才生效）。
 * 运镜：卡片是按 3D-BOX 同一套预设实算的机位轨迹（悬停播放），可复制提示词或 3D-BOX 代码。
 * 特效、爆款题材：提示词模板与剧本设定，一键复制。
 * 当前分镜取地址栏的 ?plan=（分镜画布会记在那里）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { media } from "../api";
import { CameraThumb } from "./CameraThumb";
import { lib, type JobInfo, type Preset, type PresetKind } from "./api";

const KINDS: { id: PresetKind; zh: string; hint: string }[] = [
  { id: "style", zh: "风格广场", hint: "套到分镜上，之后出的画面都按这个风格" },
  { id: "camera_move", zh: "运镜广场", hint: "机位怎么动：俯视轨迹悬停播放" },
  { id: "effect", zh: "特效广场", hint: "视频提示词模板" },
  { id: "genre", zh: "爆款题材", hint: "剧本设定器的起点" },
];
const MARKS = [{ id: "", zh: "广场" }, { id: "favorite", zh: "我的收藏" }, { id: "recent", zh: "最近使用" }];
const RENDER_ZH: Record<string, string> = { photoreal: "写实", anime: "动漫", cinematic: "电影感", auto: "自由" };

const planId = () => new URLSearchParams(location.search).get("plan") ?? "";

function hue(s: string) {
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

function copy(text: string, done: (m: string) => void, what = "已复制") {
  navigator.clipboard?.writeText(text).then(() => done(what)).catch(() => done("复制失败：浏览器不让写剪贴板"));
}

function Placeholder({ name, busy }: { name: string; busy?: boolean }) {
  const h = hue(name);
  return (
    <div className="ph" style={{ background: `linear-gradient(145deg, hsl(${h} 35% 26%), hsl(${(h + 50) % 360} 40% 14%))` }}>
      <b>{name}</b>
      {busy && <em>封面生成中…</em>}
    </div>
  );
}

function StyleCard({ p, busy, current, onOpen, onFav, onApply }: {
  p: Preset; busy: boolean; current: boolean; onOpen: () => void; onFav: () => void; onApply: (() => void) | null;
}) {
  return (
    <div className={`p-card style${current ? " current" : ""}`} onClick={onOpen}>
      <div className="cover">
        {p.cover_url ? <img src={media(p.cover_url)} alt={p.name} loading="lazy" /> : <Placeholder name={p.name} busy={busy} />}
        <button className={`fav${p.favorite ? " on" : ""}`} title={p.favorite ? "取消收藏" : "收藏"}
          onClick={e => { e.stopPropagation(); onFav(); }}>{p.favorite ? "★" : "☆"}</button>
        {current && <span className="badge now">当前分镜在用</span>}
        {onApply && (
          <div className="hover">
            <button className="primary" onClick={e => { e.stopPropagation(); onApply(); }}>{current ? "取消套用" : "套用到分镜"}</button>
          </div>
        )}
      </div>
      <div className="meta">
        <b>{p.name}</b>
        <small>{p.author ?? "官方"} · 用过 {p.uses} 次</small>
        <div className="tags">
          {p.commercial && <span>可商用</span>}
          <span>{RENDER_ZH[String(p.payload.render)] ?? "自由"}</span>
        </div>
      </div>
    </div>
  );
}

function Detail({ p, current, onClose, onApply, onCover, say }: {
  p: Preset; current: boolean; onClose: () => void; onApply: (() => void) | null; onCover: () => void; say: (m: string) => void;
}) {
  return (
    <aside className="plaza-detail">
      <header><b>{p.name}</b><button className="ghost" onClick={onClose}>×</button></header>
      <div className="big">{p.cover_url ? <img src={media(p.cover_url)} alt={p.name} /> : <Placeholder name={p.name} />}</div>
      <dl>
        <dt>分类</dt><dd>{p.category}</dd>
        <dt>基础画风</dt><dd>{RENDER_ZH[String(p.payload.render)] ?? "自由"}（{String(p.payload.render ?? "auto")}）</dd>
        <dt>风格描述</dt><dd className="mono">{String(p.payload.prompt ?? "")}</dd>
        {p.payload.negative ? <><dt>反向词</dt><dd className="mono">{String(p.payload.negative)}</dd></> : null}
      </dl>
      <div className="row">
        {onApply ? <button className="primary" onClick={onApply}>{current ? "取消套用" : "套用到当前分镜"}</button>
          : <small className="note">先在「分镜画布」里选一份分镜，再回来套用</small>}
        <button onClick={() => copy(String(p.payload.prompt ?? ""), say, "风格描述已复制")}>复制风格描述</button>
        {!p.cover_url && <button onClick={onCover}>生成封面</button>}
      </div>
      <small className="note">套用后，这份分镜之后出的首帧、尾帧都带上这个风格；已经出好的图不会变，重出才生效。</small>
    </aside>
  );
}

export default function Plaza() {
  const [kind, setKind] = useState<PresetKind>("style");
  const [mark, setMark] = useState("");
  const [category, setCategory] = useState("推荐");
  const [q, setQ] = useState("");
  const [commercial, setCommercial] = useState(false);
  const [rows, setRows] = useState<Preset[]>([]);
  const [cats, setCats] = useState<{ category: string; count: number }[]>([]);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [open, setOpen] = useState<Preset | null>(null);
  const [plan, setPlan] = useState<{ id: string; style: { id: string; name: string } | null } | null>(null);
  const [msg, setMsg] = useState("");
  const pid = planId();

  const load = useCallback(() => {
    lib.presets(kind, { category: mark ? undefined : category, q: q.trim() || undefined, mark: mark || undefined, commercial })
      .then(setRows).catch(e => setMsg(String(e.message ?? e)));
  }, [kind, mark, category, q, commercial]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    setCategory(kind === "style" ? "推荐" : "");
    setMark("");
    lib.categories(kind).then(setCats).catch(() => setCats([]));
  }, [kind]);
  useEffect(() => {
    if (!pid) { setPlan(null); return; }
    lib.planStyle(pid).then(r => setPlan({ id: r.plan_id, style: r.style_preset })).catch(() => setPlan(null));
  }, [pid]);

  // 封面在本机一张一张出：有排队的就定时刷新
  const coverJobs = useMemo(() => jobs.filter(j => j.group === "covers"), [jobs]);
  const pendingCovers = coverJobs.filter(j => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (kind !== "style") return;
    let alive = true;
    const tick = () => lib.jobs("covers").then(j => { if (alive) setJobs(j); }).catch(() => {});
    tick();
    const t = window.setInterval(() => { tick(); load(); }, 6000);
    return () => { alive = false; window.clearInterval(t); };
  }, [kind, load]);
  const busyOf = (p: Preset) => pendingCovers.some(j => j.title === `风格封面·${p.name}`);

  const say = (m: string) => { setMsg(m); window.setTimeout(() => setMsg(x => (x === m ? "" : x)), 2500); };

  const fav = async (p: Preset) => {
    const r = await lib.favorite(p.id);
    setRows(rs => rs.map(x => (x.id === p.id ? { ...x, favorite: r.favorite } : x)));
    if (open?.id === p.id) setOpen({ ...p, favorite: r.favorite });
  };
  const apply = pid ? async (p: Preset) => {
    const off = plan?.style?.id === p.id;
    const r = await lib.applyStyle(pid, off ? null : p.id);
    setPlan({ id: pid, style: (r.style_preset as { id: string; name: string } | null) ?? null });
    say(off ? `已取消「${p.name}」` : `已套用「${p.name}」：之后出的首帧、尾帧都按这个风格`);
    load();
  } : null;
  const makeCovers = async () => {
    const r = await lib.covers();
    say(r.queued ? `已排队 ${r.queued} 张封面（本机一张一张出，约 20 秒一张）` : "没有缺封面的风格");
    setJobs(await lib.jobs("covers"));
  };
  const missing = rows.filter(p => !p.cover_url).length;

  return (
    <div className="lib-page plaza">
      <div className="lib-head">
        <div className="seg big">
          {KINDS.map(k => <button key={k.id} className={kind === k.id ? "on" : ""} onClick={() => setKind(k.id)}>{k.zh}</button>)}
        </div>
        <small className="hint">{KINDS.find(k => k.id === kind)?.hint}</small>
        <div className="spacer" />
        {kind === "style" && (
          <div className="plan-state">
            {pid
              ? plan?.style ? <>当前分镜在用：<b>{plan.style.name}</b> <button className="ghost" onClick={async () => {
                  await lib.applyStyle(pid, null); setPlan({ id: pid, style: null }); say("已取消套用"); load();
                }}>取消</button></> : <>当前分镜还没套风格</>
              : <>先在「分镜画布」选一份分镜，才能套用</>}
          </div>
        )}
      </div>

      <div className="lib-bar">
        {kind === "style" && (
          <div className="seg">
            {MARKS.map(m => <button key={m.id} className={mark === m.id ? "on" : ""} onClick={() => setMark(m.id)}>{m.zh}</button>)}
          </div>
        )}
        <input className="search" placeholder={kind === "style" ? "搜索风格名称／作者" : "搜索"} value={q} onChange={e => setQ(e.target.value)} />
        {kind === "style" && (
          <label className="check"><input type="checkbox" checked={commercial} onChange={e => setCommercial(e.target.checked)} /> 仅看可商用</label>
        )}
        <div className="spacer" />
        {kind === "style" && (
          <span className="cover-state">
            {pendingCovers.length ? `封面出图中：还剩 ${pendingCovers.length} 张` : missing ? `${missing} 个风格还没封面` : "封面都齐了"}
            {!!missing && !pendingCovers.length && <button onClick={makeCovers}>生成缺的封面</button>}
          </span>
        )}
      </div>

      {!mark && (
        <div className="chips cats">
          {kind === "style" && <button className={category === "推荐" ? "on" : ""} onClick={() => setCategory("推荐")}>推荐</button>}
          {kind !== "style" && <button className={!category ? "on" : ""} onClick={() => setCategory("")}>全部</button>}
          {cats.map(c => (
            <button key={c.category} className={category === c.category ? "on" : ""} onClick={() => setCategory(c.category)}>
              {c.category} <small>{c.count}</small>
            </button>
          ))}
        </div>
      )}

      {kind === "style" && (
        <div className="card-grid styles">
          {rows.map(p => (
            <StyleCard key={p.id} p={p} busy={busyOf(p)} current={plan?.style?.id === p.id} onOpen={() => setOpen(p)}
              onFav={() => fav(p)} onApply={apply ? () => apply(p) : null} />
          ))}
        </div>
      )}

      {kind === "camera_move" && (
        <div className="card-grid moves">
          {rows.map(p => {
            const id = String(p.payload.preset ?? p.key);
            return (
              <div key={p.id} className="p-card move">
                <CameraThumb preset={id} />
                <div className="meta">
                  <b>{p.name}</b><small>{p.category} · {id}</small>
                  <p>{String(p.payload.prompt ?? "")}</p>
                  <div className="row">
                    <button onClick={() => copy(String(p.payload.prompt ?? ""), say, "运镜提示词已复制")}>复制提示词</button>
                    <button onClick={() => copy(`S.cameraPreset(cam, "${id}", { target: 人物, start: 0, duration: 4 });`, say, "3D-BOX 代码已复制")}>复制 3D-BOX 代码</button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {kind === "effect" && (
        <div className="card-grid effects">
          {rows.map(p => (
            <div key={p.id} className="p-card effect">
              <div className="fx" style={{ background: `radial-gradient(circle at 30% 30%, hsl(${hue(p.name)} 70% 55% / .55), transparent 60%), #16161b` }}>
                <b>{p.name}</b>
              </div>
              <div className="meta">
                <p>{String(p.payload.prompt ?? "")}</p>
                <button onClick={() => copy(String(p.payload.prompt ?? ""), say, "特效提示词已复制")}>复制提示词</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {kind === "genre" && (
        <div className="card-grid genres">
          {rows.map(p => (
            <div key={p.id} className="p-card genre">
              <div className="meta">
                <b>{p.name}</b>
                <dl>
                  {Object.entries(p.payload.fields ?? {}).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
                </dl>
                <button onClick={() => copy(String(p.payload.prefill ?? ""), say, "题材设定已复制，可以贴进剧本设定器或对话框")}>复制设定</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {!rows.length && <div className="note center">{mark === "favorite" ? "还没收藏" : mark === "recent" ? "还没用过" : "没有匹配的"}</div>}
      {open && kind === "style" && (
        <Detail p={open} current={plan?.style?.id === open.id} onClose={() => setOpen(null)}
          onApply={apply ? () => apply(open) : null} onCover={makeCovers} say={say} />
      )}
      {msg && <div className="lib-toast" onClick={() => setMsg("")}>{msg}</div>}
    </div>
  );
}
