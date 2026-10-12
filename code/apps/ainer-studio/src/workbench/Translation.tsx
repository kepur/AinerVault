import { useCallback, useEffect, useMemo, useState } from "react";
import { adminHref } from "../Nav";
import { navigate, readCtx, writeCtx } from "../ctx";
import { download, request, submit } from "./api";
import { ProjectPicker, TaskList, useEngine, useProject } from "./shared";
import { translationIssues } from "./quality";

interface Block { block_id: string; seq_no: number; type: string; speaker: string | null; source: string; target: string | null; translation_id: string | null; status: string | null; locked: boolean; translatable: boolean; lexicon_hits: { source: string; target: string }[] }
interface TranslationData { stats: { translatable: number; translated: number; reviewed: number; locked: number }; blocks: Block[] }
interface Transform { id: string; target_language_code: string; status: string; version: number; target: { display_name: string } }
interface Gate { ready: boolean; issues: { severity: string; message?: string; detail?: string; code?: string }[]; coverage: { violations?: { high: number; medium: number }; names?: { mapped: number; entities: number } } }

function readDraft(key: string, fallback: string) { try { return sessionStorage.getItem(key) ?? fallback; } catch { return fallback; } }
function BlockEditor({ b, locale, reload }: { b: Block; locale: string; reload: () => void }) {
  const key = `ainer-translation-draft:${locale}:${b.block_id}`;
  const [text, setText] = useState(() => readDraft(key, b.target || ""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dirty = text !== (b.target || "");
  useEffect(() => { setText(readDraft(key, b.target || "")); }, [key, b.target]);
  const edit = (v: string) => { setText(v); try { sessionStorage.setItem(key, v); } catch {} };
  const discard = () => { setText(b.target || ""); try { sessionStorage.removeItem(key); } catch {} };
  const action = async (verb: "save" | "lock" | "unlock") => {
    if (!b.translation_id) return;
    setBusy(true); setError("");
    try {
      if (verb === "save") {
        await request(`/api/v2/translation-blocks/${b.translation_id}`, { translated_text: text, status: "reviewed" }, "PATCH");
        try { sessionStorage.removeItem(key); } catch {}
      } else await request(`/api/v2/translation-blocks/${b.translation_id}:${verb}`, {});
      reload();
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  return <article className={`wb-line${b.locked ? " is-locked" : ""}`}>
    <div className="wb-line-number">{b.seq_no}<small>{b.type === "dialogue" ? "对白" : "原文"}</small></div>
    <div className="wb-source">{b.speaker && <span className="wb-tag">{b.speaker}</span>}<p>{b.source}</p>
      {b.lexicon_hits.length > 0 && <div className="wb-terms">{b.lexicon_hits.map((h, i) => <span key={i}>{h.source} → {h.target}</span>)}</div>}
    </div>
    <div className="wb-target">
      {b.locked ? <p>{b.target}</p> : <textarea aria-label={`第 ${b.seq_no} 段译文`} value={text} rows={4} onChange={e => edit(e.target.value)} disabled={!b.translation_id || busy} placeholder="尚未生成译文" />}
      {error && <div className="wb-error" role="alert">{error}</div>}
      {translationIssues(b.target).map((issue, i) => <p className="wb-notice" key={i}>{issue}</p>)}
      <div className="wb-line-actions"><span className="wb-muted">{b.locked ? "已定稿" : dirty ? "草稿未保存" : b.status === "reviewed" ? "已校对" : b.target ? "待校对" : "待翻译"}</span>
        {dirty && <button disabled={busy} onClick={discard}>放弃草稿</button>}
        {!b.locked && <button disabled={!b.translation_id || !dirty || busy || !text.trim()} onClick={() => action("save")}>保存译文</button>}
        <button disabled={!b.translation_id || busy || dirty || !b.target} onClick={() => action(b.locked ? "unlock" : "lock")}>{b.locked ? "解锁修改" : "锁定定稿"}</button>
      </div>
    </div>
  </article>;
}

export default function Translation() {
  const p = useProject();
  const engine = useEngine();
  const [locale, setLocale] = useState(() => readCtx().locale || "en-US");
  const [transforms, setTransforms] = useState<Transform[]>([]);
  const [data, setData] = useState<TranslationData | null>(null);
  const [gate, setGate] = useState<Gate | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [filter, setFilter] = useState("all");
  const [mode, setMode] = useState("literal");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const active = transforms.find(t => t.target_language_code === locale && t.status === "active");
  const reload = useCallback(() => setRevision(v => v+1), []);
  const tasks = engine.tasks.filter(t => t.context?.chapter_id === p.chapter && t.capability === "hub.translate_chapter");
  const finished = tasks.filter(t => t.status === "succeeded").map(t => `${t.task_id}:${t.attempt}`).join(",");
  useEffect(reload, [finished, reload]);
  useEffect(() => {
    let live = true; setTransforms([]); setGate(null); setData(null);
    if (!p.novel) return;
    request<Transform[]>(`/api/v2/novels/${p.novel}/transforms`).then(d => {
      if (!live) return;
      setTransforms(d);
      if (!d.some(t => t.target_language_code === locale) && d.some(t => t.status === "active")) {
        const v = d.find(t => t.status === "active")!.target_language_code;
        setLocale(v); writeCtx({ locale: v });
      }
    }).catch(e => live && setError(String(e)));
    return () => { live = false; };
  }, [p.novel]);
  useEffect(() => {
    writeCtx({ locale });
    let live = true; setGate(null);
    if (!active) return;
    request<Gate>(`/api/v2/transforms/${active.id}/preflight`).then(d => live && setGate(d)).catch(e => live && setError(String(e)));
    return () => { live = false; };
  }, [active?.id, locale]);
  useEffect(() => {
    let live = true; setData(null); setError("");
    if (!p.chapter || !p.chapters.some(c => c.id === p.chapter)) return;
    setLoading(true);
    request<TranslationData>(`/api/v2/chapters/${p.chapter}/translation/${encodeURIComponent(locale)}`).then(d => live && setData(d))
      .catch(e => live && setError(String(e))).finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [p.chapter, p.chapters, locale, revision]);
  const locales = [...new Set([...transforms.map(t => t.target_language_code), "en-US", "es-419", "ja-JP", "ko-KR"])];
  const shown = useMemo(() => data?.blocks.filter(b => b.translatable &&
    (filter === "all" || filter === "issues" && translationIssues(b.target).length > 0 || filter === "missing" && !b.target || filter === "review" && !b.locked || filter === "dialogue" && b.type === "dialogue") &&
    (!query || `${b.source} ${b.target || ""} ${b.speaker || ""}`.toLowerCase().includes(query.toLowerCase()))) || [], [data, filter, query]);
  const run = async () => {
    setBusy(true); setError("");
    try { await submit("hub.translate_chapter", { chapter_id: p.chapter, locale, mode, only_missing: true, batch_size: 10 }); await engine.reload(); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const exportText = async () => {
    try {
      const d = await request<{ title: string; content: string }>(`/api/v2/chapters/${p.chapter}/prose/${encodeURIComponent(locale)}/export?fmt=markdown`);
      download(`${d.title || p.chapter}-${locale}.md`, d.content, "text/markdown;charset=utf-8");
    } catch (e) { setError(String(e)); }
  };
  const running = tasks.some(t => ["queued", "running"].includes(t.status));
  return <main className="wb-page">
    <div className="wb-heading"><div><span className="wb-eyebrow">故事 → 文化 → 译文 → 定稿</span><h1>翻译工作台</h1><p>沿用这本作品的世界观、人名和称谓。定稿后进入本版画布继续制作。</p></div><button onClick={() => navigate("flow")}>进入制作画布 →</button></div>
    <div className="wb-toolbar"><ProjectPicker project={p} /><label>目标语言<select aria-label="目标语言" value={locale} onChange={e => { setLocale(e.target.value); writeCtx({ locale: e.target.value }); }}>{locales.map(l => <option key={l} value={l}>{l}{!transforms.some(t => t.target_language_code === l && t.status === "active") ? " · 未配置世界观" : ""}</option>)}</select></label></div>
    {(p.error || error) && <div className="wb-error" role="alert">{p.error || error}</div>}
    {engine.error && <div className="wb-notice">{engine.error}</div>}
    <div className="wb-layout"><section className="wb-main">
      <div className="wb-stats">{[["已翻译", data?.stats.translated], ["总段落", data?.stats.translatable], ["已定稿", data?.stats.locked]].map(([label, value]) => <div key={label}><span>{label}</span><b>{value ?? "—"}</b></div>)}<div><span>目标文化</span><strong>{active?.target.display_name || "尚未配置"}</strong></div></div>
      <div className="wb-actions wb-filter"><select aria-label="段落筛选" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部段落</option><option value="dialogue">只看对白</option><option value="review">待定稿</option><option value="issues">疑似称谓问题</option><option value="missing">缺失译文</option></select><input aria-label="搜索原文和译文" placeholder="搜索原文、译文或说话人" value={query} onChange={e => setQuery(e.target.value)} /><button onClick={reload}>刷新译文</button><button disabled={!data?.stats.translated} onClick={exportText}>导出译本</button></div>
      <div className="wb-column-labels"><span /> <span>原文</span><span>译文 · {locale}</span></div>
      {loading ? <div className="wb-empty">载入译文…</div> : shown.length ? shown.map(b => <BlockEditor key={`${locale}:${b.block_id}`} b={b} locale={locale} reload={reload} />) : <div className="wb-empty">{data ? "当前筛选没有段落" : "选择已导入并生成原文剧本的章节；可在后台继续导入与整理。"}</div>}
    </section><aside className="wb-side">
      <section className="wb-card"><h3>世界观与翻译检查</h3><p className={gate?.ready ? "wb-ok" : "wb-muted"}>{!active ? "这门语言还没有已启用的世界观映射" : !gate ? "正在检查世界观映射…" : gate.ready ? "翻译前置检查已通过" : "需先处理以下问题"}</p>
        {gate?.issues?.slice(0, 6).map((i, n) => <p className="wb-notice" key={n}>{i.message || i.detail || i.code || JSON.stringify(i)}</p>)}
        {gate?.coverage.violations && (gate.coverage.violations.high > 0 || gate.coverage.violations.medium > 0) && <p className="wb-notice">已有世界观检查记录：{gate.coverage.violations.high} 项高风险，{gate.coverage.violations.medium} 项中风险。请在文化审查中核对，前置通过不代表成片验收。</p>}
        <div className="wb-actions"><a href={adminHref("world")}>世界观与术语 ↗</a><a href={adminHref("prose")}>审核与回译 ↗</a><a href={adminHref("culture")}>文化梗与表达 ↗</a><a href={adminHref("script")}>目标剧本 ↗</a></div>
      </section>
      <section className="wb-card"><h3>补译未完成的段落</h3><label>翻译方式<select value={mode} onChange={e => setMode(e.target.value)}><option value="literal">逐段对应</option><option value="adaptive">按剧情效果改写</option></select></label><p className="wb-muted">使用后台现有模型路由。已定稿段落保持锁定；任务结果仍写回同一份译本。</p>
        <button className="primary" disabled={busy || running || !gate?.ready || !data || !active || !!engine.error || data.stats.translated === data.stats.translatable} onClick={run}>{running ? "翻译进行中…" : busy ? "提交中…" : "补译缺失段落"}</button>
        {data && data.stats.translated === data.stats.translatable && <p className="wb-ok">译文已齐，可逐段校对和锁定。</p>}
      </section><TaskList tasks={tasks} reload={engine.reload} />
    </aside></div>
  </main>;
}
