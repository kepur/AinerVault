/**
 * 和场景智能体对话：发一句话 → 后台跑 → SSE 实时显示它在干什么（已执行 x_write…）→ 场景跟着变。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { box, type AgentEvent, type ChatRow, type Sketch } from "./api";

interface Item { key: string; role: "user" | "assistant" | "tool" | "error" | "status"; text: string; ok?: boolean; tool?: string; result?: string }

function fromRows(rows: ChatRow[]): Item[] {
  return rows.map(r => ({
    key: r.id, role: (r.role as Item["role"]) ?? "assistant",
    text: r.role === "tool" ? `${String(r.meta.tool ?? "")} ${String(r.meta.brief ?? "")}` : r.content,
    ok: r.role === "tool" ? Boolean(r.meta.ok) : undefined, tool: String(r.meta.tool ?? ""), result: String(r.meta.result ?? ""),
  }));
}

const SUGGEST = [
  "帮我创建一段警匪在城市街道中飙车对战的预演动画，包含全景、中景、特写等多种镜头",
  "搭一个古代运河小镇，两岸民居、拱桥、乌篷船，给一个 15 秒的连续航拍",
  "两个人在咖啡馆对话，正反打加一个双人中景",
  "把第二台机位改成环绕推近",
];

export function ChatPanel({ projectId, activeRun, selected, selectedLabel, onClearSelected, sketches, onClearSketches,
                            onScene, onDone, models, collapsed, onToggle }: {
  projectId: string; activeRun: string | null;
  selected: string[]; selectedLabel: string; onClearSelected: () => void;
  sketches: Sketch[]; onClearSketches: () => void;
  onScene: () => void; onDone: () => void;
  models: { model: string; default: boolean }[];
  collapsed: boolean; onToggle: () => void;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [text, setText] = useState("");
  const [run, setRun] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [model, setModel] = useState("");
  const [err, setErr] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  const load = useCallback(() => box.messages(projectId).then(r => setItems(fromRows(r))).catch(e => setErr(String(e))), [projectId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { listRef.current?.scrollTo({ top: 1e9, behavior: "smooth" }); }, [items, status]);

  const listen = useCallback((rid: string) => {
    esRef.current?.close();
    setRun(rid);
    const es = new EventSource(box.streamUrl(projectId, rid));
    esRef.current = es;
    let sceneTimer = 0;
    es.onmessage = m => {
      const e = JSON.parse(m.data) as AgentEvent;
      if (e.type === "thinking") setStatus(`第 ${e.step} 轮思考中…`);
      else if (e.type === "status") setStatus(e.text ?? "");
      else if (e.type === "say") setItems(x => [...x, { key: `e${e.seq}`, role: "assistant", text: e.text ?? "" }]);
      else if (e.type === "tool") { setStatus(`执行 ${e.tool} ${e.brief ?? ""}`); }
      else if (e.type === "tool_result") setItems(x => [...x, { key: `e${e.seq}`, role: "tool", text: `${e.tool} ${e.brief ?? ""}`, ok: e.ok, tool: e.tool, result: e.result }]);
      else if (e.type === "scene") { clearTimeout(sceneTimer); sceneTimer = window.setTimeout(onScene, 150); }
      else if (e.type === "error") setItems(x => [...x, { key: `e${e.seq}`, role: "error", text: e.text ?? "出错了" }]);
      else if (e.type === "stopped") setItems(x => [...x, { key: `e${e.seq}`, role: "status", text: "已停止" }]);
      else if (e.type === "done") {
        es.close();
        setRun(null);
        setStatus("");
        onDone();
      }
    };
    es.onerror = () => { /* 断线：EventSource 会自己重连；运行在后台不受影响 */ };
  }, [projectId, onScene, onDone]);

  useEffect(() => { if (activeRun && !run) listen(activeRun); }, [activeRun]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => esRef.current?.close(), []);

  async function send(msg?: string) {
    const m = (msg ?? text).trim();
    if (!m || run) return;
    setErr("");
    setItems(x => [...x, { key: `u${Date.now()}`, role: "user", text: m + (selectedLabel ? `\n〔选中：${selectedLabel}〕` : "") + (sketches.length ? `\n〔草图 ${sketches.length} 笔〕` : "") }]);
    setText("");
    try {
      const r = await box.ask(projectId, { message: m, selected, sketches, model: model || undefined });
      setStatus("已加载 studio-director 工作方法，开始规划…");
      listen(r.run_id);
      onClearSketches();
    } catch (e) {
      setErr(String((e as Error).message));
    }
  }

  if (collapsed) {
    return <button className="chat-fab" onClick={onToggle} title="和 TV Director 对话">✦ 对话{run ? "（工作中）" : ""}</button>;
  }
  return (
    <div className="chat-panel">
      <div className="chat-head">
        <b>✦ TV Director</b>
        <select value={model} onChange={e => setModel(e.target.value)} title="对话模型（都是免费路由）">
          {models.map(m => <option key={m.model} value={m.default ? "" : m.model}>{m.model}{m.default ? "（默认）" : ""}</option>)}
        </select>
        <button className="ghost" onClick={onToggle} title="收起">—</button>
      </div>
      <div className="chat-list" ref={listRef}>
        {!items.length && (
          <div className="chat-empty">
            <p>描述你想要的场景，我来搭白模、编动作、设计机位和剪辑。</p>
            {SUGGEST.map(s => <button key={s} className="sugg" onClick={() => send(s)}>{s}</button>)}
          </div>
        )}
        {items.map(it => (
          it.role === "tool"
            ? <details key={it.key} className={`chat-tool${it.ok ? "" : " bad"}`}>
                <summary>{it.ok ? "✓" : "✗"} 已执行 {it.text}</summary>
                {it.result && <pre>{it.result}</pre>}
              </details>
            : <div key={it.key} className={`chat-msg ${it.role}`}>{it.text}</div>
        ))}
        {status && <div className="chat-status"><span className="spin" /> {status}</div>}
      </div>
      {err && <div className="err" style={{ padding: "0 10px" }}>{err}</div>}
      <div className="chat-input">
        {(selectedLabel || sketches.length > 0) && (
          <div className="chips">
            {selectedLabel && <span className="chip">◎ {selectedLabel} <button onClick={onClearSelected}>×</button></span>}
            {sketches.length > 0 && <span className="chip">✎ 草图 {sketches.length} 笔 <button onClick={onClearSketches}>×</button></span>}
          </div>
        )}
        <textarea value={text} placeholder={selectedLabel ? "描述要怎么调整选中的元素或机位…" : "自由描述你想搭建的场景…"}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} />
        <div className="chat-actions">
          <span className="stat">Enter 发送 · Shift+Enter 换行</span>
          {run
            ? <button className="stop" onClick={() => box.stop(projectId, run)}>■ 停止</button>
            : <button className="primary" disabled={!text.trim()} onClick={() => send()}>发送</button>}
        </div>
      </div>
    </div>
  );
}
