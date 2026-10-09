/**
 * 生成面板的提示词编辑器：contentEditable，@引用渲染成不可编辑的 chip（contenteditable=false，data-node）。
 *
 * 为什么做成「半受控」：contentEditable 每次按 value 重画会把光标和输入法组合打断。
 * 所以只在 docKey 变（换了目标节点）时按 value 重建一次 DOM，之后 DOM 就是真身，
 * 每次输入读回 PromptSeg[] 交给 onChange。外部要往里插东西（预设、建议语、@）走 ref 句柄。
 *
 * @引用只引用（铁律 4/5）：chip 只带节点 id 和标题，不把对方的提示词复制进来；
 * 发出去时 chip 拼成「标题」。
 */
import {
  useEffect, useImperativeHandle, useLayoutEffect, useRef, useState,
  type KeyboardEvent, type ReactNode, type Ref,
} from "react";
import { GLYPH } from "../actions";
import type { NodeKind, PromptSeg } from "../model";
import { Popover, useLatest } from "./Overlays";

export interface MentionItem {
  id: string;
  label: string;
  kind: NodeKind;
  /** 已过 media() 的缩略图地址 */
  thumb?: string | null;
  /** 列表里右侧的小字（「身份」「控制」…） */
  hint?: string;
}

export interface PromptEditorHandle {
  focus(): void;
  /** 在光标处（没有光标就在末尾）插入纯文字 */
  insertText(text: string): void;
  /** 插一个 @ 并弹出上游节点列表 */
  openMention(): void;
  clear(): void;
}

/* ───────────────────────── 序列化 ───────────────────────── */

export function segsEmpty(segs: PromptSeg[]): boolean {
  return !segs.some(s => s.t === "ref" || s.text.trim());
}

/** 发给模型的提示词：chip →「标题」，文字原样（铁律 5：用户写的原样发） */
export function segsToPrompt(segs: PromptSeg[]): string {
  return segs.map(s => (s.t === "ref" ? `「${s.label}」` : s.text)).join("").trim();
}

/** 写回 note/prompt 节点 data.text 的形式：chip → @标题（节点上直接可读，下次打开再按上游标题认回 chip） */
export function segsToText(segs: PromptSeg[]): string {
  return segs.map(s => (s.t === "ref" ? `@${s.label}` : s.text)).join("").replace(/\s+$/, "");
}

/** data.text → 片段：只把「@上游节点标题」认成 chip（长标题优先，免得「定妆照」吃掉「多角度定妆照」） */
export function segsFromText(text: string, items: MentionItem[]): PromptSeg[] {
  if (!text) return [];
  const known = [...items].filter(i => i.label).sort((a, b) => b.label.length - a.label.length);
  const out: PromptSeg[] = [];
  let buf = "";
  let i = 0;
  while (i < text.length) {
    if (text[i] === "@") {
      const hit = known.find(k => text.startsWith(k.label, i + 1));
      if (hit) {
        if (buf) { out.push({ t: "text", text: buf }); buf = ""; }
        out.push({ t: "ref", node: hit.id, label: hit.label });
        i += hit.label.length + 1;
        continue;
      }
    }
    buf += text[i];
    i++;
  }
  if (buf) out.push({ t: "text", text: buf });
  return out;
}

/* ───────────────────────── DOM ↔ 片段 ───────────────────────── */

function makeChip(id: string, label: string, item: MentionItem | undefined): HTMLElement {
  const el = document.createElement("span");
  el.className = item ? "cv-chip" : "cv-chip is-stale";
  el.contentEditable = "false";
  el.dataset.node = id;
  el.dataset.label = label;
  el.title = item ? label : `${label}（已不在上游：发送时只拼标题）`;
  if (item?.thumb) {
    const img = document.createElement("img");
    img.src = item.thumb;
    img.alt = "";
    img.draggable = false;
    el.append(img);
  } else {
    const g = document.createElement("i");
    g.textContent = GLYPH[item?.kind ?? "image"];
    el.append(g);
  }
  const t = document.createElement("span");
  t.textContent = label;
  el.append(t);
  return el;
}

function appendText(parent: HTMLElement, text: string) {
  text.split("\n").forEach((part, i) => {
    if (i) parent.append(document.createElement("br"));
    if (part) parent.append(document.createTextNode(part));
  });
}

function buildDom(root: HTMLElement, segs: PromptSeg[], items: MentionItem[]) {
  root.replaceChildren();
  for (const sg of segs) {
    if (sg.t === "ref") root.append(makeChip(sg.node, sg.label, items.find(i => i.id === sg.node)));
    else appendText(root, sg.text);
  }
}

function readSegs(root: HTMLElement): PromptSeg[] {
  const out: PromptSeg[] = [];
  const text = (raw: string) => {
    const t = raw.replace(/​/g, "").replace(/ /g, " ");
    if (!t) return;
    const last = out[out.length - 1];
    if (last?.t === "text") last.text += t;
    else out.push({ t: "text", text: t });
  };
  const walk = (n: Node) => {
    n.childNodes.forEach(c => {
      if (c.nodeType === Node.TEXT_NODE) text(c.textContent ?? "");
      else if (c instanceof HTMLElement) {
        if (c.dataset.node) out.push({ t: "ref", node: c.dataset.node, label: c.dataset.label ?? "" });
        else if (c.tagName === "BR") text("\n");
        else {
          // 有的浏览器回车会包一层 div/p：当成换行
          if ((c.tagName === "DIV" || c.tagName === "P") && out.length) text("\n");
          walk(c);
        }
      }
    });
  };
  walk(root);
  // 末尾那个 <br> 是浏览器为了让光标落到新的一行补的，不算内容
  const last = out[out.length - 1];
  if (last?.t === "text" && last.text.endsWith("\n")) {
    last.text = last.text.slice(0, -1);
    if (!last.text) out.pop();
  }
  return out;
}

interface MentionState {
  node: Text;
  start: number;
  end: number;
  query: string;
  rect: { x: number; y: number; w: number; h: number };
}

/** 光标前面是不是正在打「@xxx」 */
function caretMention(root: HTMLElement): MentionState | null {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !sel.isCollapsed) return null;
  const n = sel.anchorNode;
  if (!n || n.nodeType !== Node.TEXT_NODE || !root.contains(n)) return null;
  const off = sel.anchorOffset;
  const m = /@([^\s@「」]{0,24})$/.exec((n.textContent ?? "").slice(0, off));
  if (!m) return null;
  const r = document.createRange();
  r.setStart(n, off - m[0].length);
  r.setEnd(n, off);
  const b = r.getBoundingClientRect();
  return { node: n as Text, start: off - m[0].length, end: off, query: m[1], rect: { x: b.left, y: b.top, w: b.width, h: b.height } };
}

function caretToEnd(root: HTMLElement) {
  const sel = window.getSelection();
  if (!sel) return;
  if (sel.rangeCount && root.contains(sel.anchorNode)) return;
  const r = document.createRange();
  r.selectNodeContents(root);
  r.collapse(false);
  sel.removeAllRanges();
  sel.addRange(r);
}

/** execCommand 能进撤销栈；不支持时退回手动插节点 */
function insertPlain(root: HTMLElement, text: string) {
  if (document.execCommand("insertText", false, text)) return;
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) { appendText(root, text); return; }
  const r = sel.getRangeAt(0);
  r.deleteContents();
  const t = document.createTextNode(text);
  r.insertNode(t);
  r.setStartAfter(t);
  r.collapse(true);
  sel.removeAllRanges();
  sel.addRange(r);
}

function insertBreak(root: HTMLElement) {
  if (document.execCommand("insertLineBreak")) return;
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) return;
  const r = sel.getRangeAt(0);
  r.deleteContents();
  const br = document.createElement("br");
  r.insertNode(br);
  // 换行在最末尾时要再补一个 <br>，光标才落得到新行上
  if (!br.nextSibling) br.after(document.createElement("br"));
  r.setStartAfter(br);
  r.collapse(true);
  sel.removeAllRanges();
  sel.addRange(r);
  root.dispatchEvent(new Event("input", { bubbles: true }));
}

/* ───────────────────────── 组件 ───────────────────────── */

export function PromptEditor({
  ref, docKey, value, onChange, mentions, placeholder, disabled, onSubmit, onChipClick, tools, className,
}: {
  ref?: Ref<PromptEditorHandle>;
  /** 换了这个值才按 value 重建内容（一般 = 目标节点 id） */
  docKey: string;
  value: PromptSeg[];
  onChange: (segs: PromptSeg[]) => void;
  /** 可以 @ 的节点；不传 = 这个编辑器不支持 @（白模对话） */
  mentions?: MentionItem[] | null;
  placeholder?: string;
  disabled?: boolean;
  /** ⌘/Ctrl + Enter */
  onSubmit?: () => void;
  onChipClick?: (nodeId: string) => void;
  /** 右下角的小按钮（预设、润色、@） */
  tools?: ReactNode;
  className?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [empty, setEmpty] = useState(() => segsEmpty(value));
  const [mention, setMention] = useState<MentionState | null>(null);
  const [active, setActive] = useState(0);
  const composing = useRef(false);
  const cb = useLatest({ onChange, onSubmit, onChipClick, mentions });

  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;
    buildDom(el, value, mentions ?? []);
    setEmpty(segsEmpty(value));
    setMention(null);
  }, [docKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // 上游变了：已经不在上游的 chip 标成「失效」（发送时仍只拼标题，不会出错）
  useEffect(() => {
    const el = root.current;
    if (!el || !mentions) return;
    const ids = new Set(mentions.map(m => m.id));
    el.querySelectorAll<HTMLElement>(".cv-chip").forEach(c => {
      c.classList.toggle("is-stale", !ids.has(c.dataset.node ?? ""));
    });
  }, [mentions]);

  const emit = () => {
    const el = root.current;
    if (!el) return;
    const segs = readSegs(el);
    setEmpty(segsEmpty(segs));
    cb.current.onChange(segs);
  };
  const detect = () => {
    const el = root.current;
    if (!el || !cb.current.mentions) { setMention(null); return; }
    const m = caretMention(el);
    if (!m || m.query !== mention?.query) setActive(0);
    setMention(m);
  };

  const options = mention
    ? (mentions ?? []).filter(i => !mention.query || i.label.toLowerCase().includes(mention.query.toLowerCase())).slice(0, 12)
    : [];

  const pick = (item: MentionItem) => {
    const el = root.current;
    if (!el || !mention) return;
    const r = document.createRange();
    r.setStart(mention.node, mention.start);
    r.setEnd(mention.node, Math.min(mention.end, mention.node.length));
    r.deleteContents();
    const chip = makeChip(item.id, item.label, item);
    const space = document.createTextNode(" ");
    r.insertNode(space);
    r.insertNode(chip);
    const sel = window.getSelection();
    const after = document.createRange();
    after.setStartAfter(space);
    after.collapse(true);
    sel?.removeAllRanges();
    sel?.addRange(after);
    setMention(null);
    emit();
  };

  useImperativeHandle(ref, () => ({
    focus: () => { const el = root.current; if (el) { el.focus(); caretToEnd(el); } },
    insertText: (text: string) => {
      const el = root.current;
      if (!el || disabled) return;
      el.focus();
      caretToEnd(el);
      insertPlain(el, text);
      emit();
    },
    openMention: () => {
      const el = root.current;
      if (!el || disabled || !cb.current.mentions) return;
      el.focus();
      caretToEnd(el);
      insertPlain(el, "@");
      emit();
      detect();
    },
    clear: () => {
      const el = root.current;
      if (!el) return;
      el.replaceChildren();
      setMention(null);
      emit();
    },
  }));

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.nativeEvent.isComposing || composing.current) return;
    if (mention && options.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(i => (i + 1) % options.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setActive(i => (i - 1 + options.length) % options.length); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pick(options[Math.min(active, options.length - 1)]); return; }
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (e.metaKey || e.ctrlKey) { setMention(null); cb.current.onSubmit?.(); return; }
      if (root.current) insertBreak(root.current);
    }
  };

  return (
    <div className={`cv-pe${disabled ? " is-off" : ""}${className ? ` ${className}` : ""}`}>
      <div
        ref={root}
        className={`cv-pe-input nowheel${empty ? " is-empty" : ""}`}
        contentEditable={!disabled}
        suppressContentEditableWarning
        role="textbox"
        aria-multiline
        aria-label="提示词"
        data-placeholder={placeholder}
        spellCheck={false}
        onInput={() => { if (composing.current) return; emit(); detect(); }}
        onCompositionStart={() => { composing.current = true; }}
        onCompositionEnd={() => { composing.current = false; emit(); detect(); }}
        onKeyDown={onKeyDown}
        onKeyUp={e => { if (mention && (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "Home" || e.key === "End")) detect(); }}
        onPaste={e => {
          // 只收纯文字：网页上复制来的富文本会把样式和奇怪的节点带进来
          e.preventDefault();
          const t = e.clipboardData.getData("text/plain");
          if (t && root.current) { insertPlain(root.current, t); emit(); }
        }}
        onDrop={e => e.preventDefault()}
        onClick={e => {
          const chip = (e.target as HTMLElement).closest<HTMLElement>(".cv-chip");
          if (chip?.dataset.node) cb.current.onChipClick?.(chip.dataset.node);
          else if (mention) detect();
        }}
      />
      {tools && <div className="cv-pe-tools">{tools}</div>}
      {mention && (
        <Popover anchor={mention.rect} placement="top-start" offset={6} onClose={() => setMention(null)} className="cv-mention" role="listbox">
          <div className="cv-mention-head">引用上游节点{mention.query ? ` · “${mention.query}”` : ""}</div>
          {options.length ? options.map((o, i) => (
            <button key={o.id} type="button" role="option" aria-selected={i === active}
              className={`cv-mention-item${i === active ? " is-active" : ""}`}
              onMouseDown={e => e.preventDefault() /* 别让编辑器失焦，光标位置还要用 */}
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(o)}>
              {o.thumb ? <img src={o.thumb} alt="" /> : <i>{GLYPH[o.kind]}</i>}
              <span className="cv-mention-label">{o.label}</span>
              {o.hint && <span className="cv-mention-hint">{o.hint}</span>}
            </button>
          )) : (
            <div className="cv-mention-empty">
              {(mentions ?? []).length ? "没有匹配的上游节点" : "上游还没有节点：先把图、视频连进来，或点「＋ 参考」"}
            </div>
          )}
        </Popover>
      )}
    </div>
  );
}
