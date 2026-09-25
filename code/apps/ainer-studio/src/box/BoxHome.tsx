/** 3D-BOX 项目列表：打开已有预演，或从模板／官方示例新建。 */
import { useEffect, useState } from "react";
import { box, type ProjectRow, type Template } from "./api";
import { media } from "../api";

export default function BoxHome({ onOpen }: { onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<ProjectRow[]>([]);
  const [tpls, setTpls] = useState<Template[]>([]);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [title, setTitle] = useState("");

  const load = () => box.projects().then(setRows).catch(e => setErr(String(e)));
  useEffect(() => { load(); box.templates().then(setTpls).catch(e => setErr(String(e))); }, []);

  async function create(t: Template) {
    setBusy(t.key);
    try {
      const p = await box.create(title.trim() || (t.key === "blank" ? "新场景" : t.name.replace("【官方示例】", "")), t.key);
      onOpen(p.id);
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="box-home">
      <section className="hero">
        <h2>3D-BOX 预演</h2>
        <p>用一句话让智能体搭白模场景、编排人车动作、设计机位运镜和剪辑；在台上拖一拖、画一画再让它改。</p>
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
      </section>
      {err && <div className="err">{err}</div>}
      <h3>我的预演 <small>{rows.length}</small></h3>
      <div className="proj-grid">
        {rows.map(r => (
          <div key={r.id} className="proj" onClick={() => onOpen(r.id)}>
            <div className="thumb">{r.thumb_url ? <img src={media(r.thumb_url)} alt="" /> : <span>⬚</span>}</div>
            <div className="meta">
              <b>{r.title}</b>
              <small>{r.ok === false ? "✗ 脚本有错 · " : ""}{r.objects ?? 0} 物体 · {r.cameras} 机位 · {r.duration ?? "?"}s</small>
              <small>{r.updated_at?.replace("T", " ").slice(0, 16)}</small>
            </div>
            <button className="ghost del" title="删除" onClick={async e => {
              e.stopPropagation();
              if (!window.confirm(`删除「${r.title}」？`)) return;
              await box.remove(r.id);
              load();
            }}>×</button>
          </div>
        ))}
        {!rows.length && <div className="note">还没有预演。点上面的模板或官方示例开始。</div>}
      </div>
    </div>
  );
}
