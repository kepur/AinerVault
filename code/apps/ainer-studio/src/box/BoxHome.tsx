/** 3D-BOX 项目列表：打开已有预演，或从模板／官方示例新建。 */
import { useEffect, useState } from "react";
import { box, workspaceBoxes, createWorkspaceBox, type ProjectRow, type Template } from "./api";
import { media } from "../api";
import { navigate, readCtx } from "../ctx";

export default function BoxHome({ onOpen }: { onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<ProjectRow[]>([]);
  const [tpls, setTpls] = useState<Template[]>([]);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [title, setTitle] = useState("");
  const [showOld, setShowOld] = useState(false);
  // 带着分镜计划进来（从分镜画布 / 创作画布切过来）默认只看本章的白模，可以切到全部
  const [ctx] = useState(readCtx);
  const free=ctx.workspace==='free';

  const load = async () => {
    try{
      const owned=await workspaceBoxes();
      setRows(owned);setErr('');
    }catch(e){setErr(String(e));}
  };
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { box.templates().then(setTpls).catch(e => setErr(String(e))); }, []);

  async function create(t: Template) {
    setBusy(t.key);
    try {
      if(!free&&!ctx.novel)throw new Error('请先选择小说，再创建本版舞台');
      const p = await createWorkspaceBox(title.trim() || (t.key === "blank" ? "新场景" : t.name.replace("【官方示例】", "")), t.key);
      onOpen(p.id);
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy("");
    }
  }

  // 已经有舞台时，自己的舞台排在最前面，模板收进「新建」里 —— 以前 12 个模板占满第一屏，
  // 每次进来都要往下翻才找得到刚做的那一镜
  const templates = (
    <>
      <div className="new-row">
        <input placeholder="新场景名字（可不填）" value={title} onChange={e => setTitle(e.target.value)} />
      </div>
      <div className="tpl-grid">
        {tpls.map(t => (
          <button key={t.key} className={`tpl${t.category === "示例" ? " ex" : ""}`} disabled={!!busy} onClick={() => create(t)}>
            <b>{t.name}</b>
            <small>{t.desc}</small>
            {busy === t.key && <em>创建中…</em>}
          </button>
        ))}
      </div>
    </>
  );
  // 同一镜每次「出视频」都会搭一个新白模：列表里同一镜出现好几张、旧的还没有缩略图，分不清哪张在用。
  // 每镜只放最近改过的那张，旧版本收起来（不删，点开还能看、能删）
  const sorted = [...rows].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
  const seen = new Set<string>();
  const latest: ProjectRow[] = [], older: ProjectRow[] = [];
  for (const r of sorted) {
    if (r.shot_id && seen.has(r.shot_id)) { older.push(r); continue; }
    if (r.shot_id) seen.add(r.shot_id);
    latest.push(r);
  }
  const listed = showOld ? [...latest, ...older] : latest;
  const projects = (
    <>
      <h3>
        {free?'自由创作舞台':'当前小说 · 本版舞台'} <small>{latest.length}</small>
        {older.length > 0 && (
          <button type="button" className="ghost box-old-toggle" onClick={() => setShowOld(v => !v)}
            title="同一镜重新搭过景留下的旧白模">
            {showOld ? "收起旧版本" : `旧版本 ${older.length}`}
          </button>
        )}
      </h3>
      <div className="proj-grid">
        {listed.map(r => (
          <div key={r.id} className={`proj${older.includes(r) ? " is-old" : ""}`} onClick={() => onOpen(r.id)}>
            <div className="thumb">{r.thumb_url ? <img src={media(r.thumb_url)} alt="" /> : <span>⬚</span>}</div>
            <div className="meta">
              <b>{r.title}</b>
              <small>{r.ok === false ? "✗ 脚本有错 · " : ""}{r.objects ?? 0} 物体 · {r.cameras} 机位 · {r.duration ?? "?"}s</small>
              <small>{r.updated_at?.replace("T", " ").slice(0, 16)}</small>
            </div>
            {r.shot_id && (
              <button className="ghost back-shot" title="回到这一镜所在的创作画布"
                onClick={e => { e.stopPropagation(); navigate("flow", { shot: r.shot_id! }); }}>
                镜 {r.shot_order} ↩
              </button>
            )}
            <button className="ghost del" title="删除" onClick={async e => {
              e.stopPropagation();
              if (!window.confirm(`删除「${r.title}」？${r.shot_id ? `\n它是镜 ${r.shot_order} 的白模，删了这一镜要重新搭景。` : ""}`)) return;
              await box.remove(r.id);
              load();
            }}>×</button>
          </div>
        ))}
      </div>
    </>
  );

  return (
    <div className="box-home">
      <section className="hero">
        <h2>3D-BOX 预演</h2>
        <p>{free?'自由创作的独立舞台':`${ctx.medium==='comic'?'动态漫画':'视频'}本版舞台`} · 搭景、站位与运镜，预演素材可以带回无限画布。</p>
        {!rows.length && templates}
      </section>
      {err && <div className="err">{err}</div>}
      {rows.length > 0 && projects}
      {rows.length > 0 && (
        <details className="box-new">
          <summary>＋ 新建舞台（从模板开始）</summary>
          {templates}
        </details>
      )}
      {!rows.length && <div className="note">当前空间还没有舞台。选择上面的模板开始，项目会保存到当前分类。</div>}
    </div>
  );
}
