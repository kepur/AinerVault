/**
 * 搜索面板：⌘K 或 / 打开，按标题、剧本正文、镜头描述、角色名筛节点，回车飞过去并选中。
 *
 * 开关状态放在模块里而不是 store：契约（contract.ts）没有这一项，
 * 底栏的搜索按钮调 openSearch()；store 想从别处打开也可以 dispatch 一个 "cv:search" 事件。
 */
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { GLYPH, resolvedText, thumbOf } from "../actions";
import type { CNode } from "../model";
import { useCanvas } from "../store";
import { Icon, isTyping, useLatest } from "./Overlays";

let open = false;
const subs = new Set<() => void>();
function setOpen(v: boolean) {
  if (open === v) return;
  open = v;
  subs.forEach(f => f());
}
export function openSearch() { setOpen(true); }
export function closeSearch() { setOpen(false); }
function useOpen() {
  return useSyncExternalStore(cb => { subs.add(cb); return () => { subs.delete(cb); }; }, () => open);
}

interface Row { node: CNode; hay: string; text: string; thumb: { img?: string; video?: string; glyph: string }; hidden?: boolean }

/** 命中处前后各截一点给人看 */
function snippet(text: string, q: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (!q) return flat.slice(0, 70);
  const i = flat.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return flat.slice(0, 70);
  const a = Math.max(0, i - 24);
  return `${a > 0 ? "…" : ""}${flat.slice(a, i + q.length + 46)}`;
}

export function SearchPalette() {
  const s = useCanvas();
  const latest = useLatest(s);
  const isOpen = useOpen();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  // ⌘K / 「/」：浮层打开时、焦点在输入框里时都不抢
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (latest.current.overlay) return;
      const k = e.key.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && k === "k") {
        e.preventDefault();
        setOpen(!open);
        return;
      }
      if (k === "/" && !e.metaKey && !e.ctrlKey && !e.altKey && !open && !isTyping(e.target)) {
        e.preventDefault();
        setOpen(true);
      }
    };
    const onEvt = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("cv:search", onEvt);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("cv:search", onEvt);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!isOpen) return;
    setQ("");
    setActive(0);
    requestAnimationFrame(() => input.current?.focus());
  }, [isOpen]);

  // 只在打开时建索引；节点内容现取（剧本正文、镜头描述、角色名都不在 node.data 里）
  const rows = useMemo<Row[]>(() => {
    if (!isOpen) return [];
    return s.nodes.map(n => {
      const r = s.resolve(n.data.ref, n.data);
      const text = resolvedText(r);
      const extra = r.kind === "entity_view" ? r.member.name : r.kind === "shot" ? `镜 ${r.shot.order_no}` : "";
      return { node: n, text, thumb: thumbOf(n, r), hay: `${n.data.title}\n${extra}\n${text}`.toLowerCase() };
    }).concat(
      // 已拿掉的也搜得到：选中就放回画布
      s.hidden.map(h => ({
        node: { id: h.id, type: h.type, position: { x: 0, y: 0 }, data: { title: h.title } } as unknown as CNode,
        text: "已从画布拿掉 · 回车放回", thumb: { glyph: GLYPH[h.type] }, hay: `${h.title}\n已拿掉`.toLowerCase(), hidden: true,
      })),
    );
  }, [isOpen, s.nodes, s.live]); // eslint-disable-line react-hooks/exhaustive-deps

  const terms = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const hits = useMemo(() => {
    const m = terms.length ? rows.filter(r => terms.every(t => r.hay.includes(t))) : rows;
    // 标题命中的排前面
    return [...m].sort((a, b) => {
      const ta = terms.length && a.node.data.title.toLowerCase().includes(terms[0]) ? 0 : 1;
      const tb = terms.length && b.node.data.title.toLowerCase().includes(terms[0]) ? 0 : 1;
      return ta - tb;
    }).slice(0, 60);
  }, [rows, q]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    list.current?.querySelector<HTMLElement>(".is-active")?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!isOpen) return null;

  const go = (n: CNode, hidden?: boolean) => {
    setOpen(false);
    if (hidden) s.restoreHidden([n.id]);
    s.focusNode(n.id);
    s.select(n.id);
  };

  return (
    <div className="cv-search-back" onPointerDown={e => { if (e.target === e.currentTarget) setOpen(false); }}>
      <div className="cv-search cv-glass" role="dialog" aria-label="搜索节点">
        <div className="cv-search-input">
          <Icon name="search" size={17} />
          <input ref={input} value={q} placeholder="搜标题、剧本、镜头描述、角色名…" aria-label="搜索"
            onChange={e => { setQ(e.target.value); setActive(0); }}
            onKeyDown={e => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === "ArrowDown") { e.preventDefault(); setActive(i => Math.min(i + 1, hits.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setActive(i => Math.max(i - 1, 0)); }
              else if (e.key === "Enter") { e.preventDefault(); const h = hits[active]; if (h) go(h.node, h.hidden); }
              else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); }
            }} />
          <kbd>Esc</kbd>
        </div>
        <div className="cv-search-list" ref={list} role="listbox">
          {hits.length ? hits.map((h, i) => (
            <button key={h.node.id} type="button" role="option" aria-selected={i === active}
              className={`cv-search-item${i === active ? " is-active" : ""}${h.hidden ? " is-hidden" : ""}`}
              onMouseEnter={() => setActive(i)} onClick={() => go(h.node, h.hidden)}>
              {h.thumb.img ? <img src={h.thumb.img} alt="" /> : <i className={`k-${h.node.type ?? "text"}`}>{h.thumb.glyph}</i>}
              <span className="cv-search-main">
                <b>{h.node.data.title}</b>
                {h.text && h.text !== h.node.data.title && <span>{snippet(h.text, terms[0] ?? "")}</span>}
              </span>
              <em>{GLYPH[h.node.type ?? "text"]}</em>
            </button>
          )) : <div className="cv-menu-empty">{rows.length ? "没有匹配的节点" : "画布上还没有节点"}</div>}
        </div>
      </div>
    </div>
  );
}
