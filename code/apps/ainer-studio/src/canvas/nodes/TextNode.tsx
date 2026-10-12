import { memo, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { NodeProps } from "@xyflow/react";
import type { CNode, CNodeData, ScriptBlock, ScriptScene, TextRole } from "../model";
import { useNodeResolved } from "../store";
import { NodeShell, useLazyStore } from "./NodeShell";

const WIDTH: Record<TextRole, number> = { story: 260, scene: 300, note: 260, prompt: 260 };

/** 剧本块 → 段首小胶囊；heading/scene_break/title 是结构标记，头部已经写了场次，跳过 */
const BLOCK_TAG: Record<string, string> = {
  action: "画面", dialogue: "对白", narration: "旁白", inner_monolog: "独白", signage: "字幕",
};
const SKIP_BLOCK = new Set(["heading", "scene_break", "title"]);

function roleOf(data: CNodeData): TextRole {
  const r = data.role;
  if (r === "story" || r === "scene" || r === "note" || r === "prompt") return r;
  // 老文档或别人建节点时没写 role：按真身类型推
  if (data.ref.kind === "story") return "story";
  if (data.ref.kind === "scene") return "scene";
  return "note";
}

/** 剧本场次 / 章节梗概 / 自由文字、提示词。派生的两种只读，自由的双击就地编辑。 */
function TextNode({ id, data, selected }: NodeProps<CNode>) {
  const r = useNodeResolved(id);
  const [tap, getStore] = useLazyStore();
  const role = roleOf(data);
  const free = role === "note" || role === "prompt";
  const [editing, setEditing] = useState(false);

  let body: ReactNode;
  if (free) {
    // data.text 是自由节点的真身（编辑直接写它）；resolve 的结果只作兜底
    const text = data.text ?? (r.kind === "text" ? r.text : "");
    body = editing
      ? (
        <TextEditor
          initial={text}
          onDone={(next) => {
            setEditing(false);
            if (next !== text) getStore()?.updateNodeData(id, { text: next });
          }}
        />
      )
      : text.trim()
        ? <Clip selected={selected} sig={text}><div className="cv-text__plain">{text}</div></Clip>
        : <div className="cv-text__empty">双击写点什么…</div>;
  } else if (role === "scene") {
    body = r.kind === "scene"
      ? <SceneBody scene={r.scene} selected={selected} />
      : <div className="cv-text__empty">剧本里找不到这一场了</div>;
  } else {
    body = r.kind === "story"
      ? (
        <>
          {r.title && <div className="cv-text__head">{r.title}</div>}
          {r.text.trim()
            ? <Clip selected={selected} sig={r.text}><div className="cv-text__plain">{r.text}</div></Clip>
            : <div className="cv-text__empty">这一章还没有梗概</div>}
        </>
      )
      : <div className="cv-text__empty">找不到章节梗概</div>;
  }

  return (
    <NodeShell
      id={id}
      kind="text"
      data={data}
      selected={selected}
      width={WIDTH[role]}
      badges={role === "prompt" ? <span className="cv-badge">提示词</span> : undefined}
      onOpen={free && !data.comic ? () => setEditing(true) : undefined}
    >
      <div className={`cv-text cv-text--${role}${editing ? " is-editing" : ""}`}>{body}</div>
      {tap}
    </NodeShell>
  );
}

export default memo(TextNode);

function SceneBody({ scene, selected }: { scene: ScriptScene; selected: boolean }) {
  const meta = [scene.title, scene.time_of_day, scene.location_text].filter(Boolean).join("－");
  const blocks = scene.blocks.filter(b => !SKIP_BLOCK.has(b.type) && b.text.trim());
  return (
    <>
      <div className="cv-text__head">场景 {scene.order_no}{meta ? `：${meta}` : ""}</div>
      {blocks.length > 0 ? (
        <Clip selected={selected} sig={`${scene.id}:${blocks.length}:${blocks.reduce((n, b) => n + b.text.length, 0)}`}>
          {blocks.map(b => <Block key={b.id} b={b} />)}
        </Clip>
      ) : scene.summary ? (
        <Clip selected={selected} sig={scene.summary}><div className="cv-text__plain">{scene.summary}</div></Clip>
      ) : (
        // 退回 board.scenes 时只有标题/地点/时间，没有正文
        <div className="cv-text__empty">只有场次信息，剧本还没拆成段落</div>
      )}
    </>
  );
}

function Block({ b }: { b: ScriptBlock }) {
  const tag = BLOCK_TAG[b.type];
  return (
    <p className={`cv-blk cv-blk--${b.type}`}>
      {tag && <span className="cv-blk__tag">{tag}</span>}
      {b.type === "dialogue" && b.speaker && <b className="cv-blk__who">{b.speaker}：</b>}
      {b.text}
    </p>
  );
}

/**
 * 正文最多 240px：没选中时超出部分底部渐隐；选中后变成可滚动（nowheel：滚轮给正文，不给画布）。
 * 是否溢出只在内容变化时量一次（sig），不挂 ResizeObserver —— 节点宽度固定，只有内容会让它变高。
 */
function Clip({ selected, sig, children }: { selected: boolean; sig: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [over, setOver] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) setOver(el.scrollHeight > el.clientHeight + 1);
  }, [sig]);
  const cls = ["cv-text__body"];
  if (over) cls.push(selected ? "is-scroll" : "is-clipped");
  if (over && selected) cls.push("nowheel");
  return <div ref={ref} className={cls.join(" ")}>{children}</div>;
}

/** 就地编辑：失焦、⌘Enter、Esc 都是「存了退出」—— Esc 丢掉刚打的字太容易误伤 */
function TextEditor({ initial, onDone }: { initial: string; onDone: (text: string) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState(initial);
  const latest = useRef({ value, onDone, done: false });
  latest.current.value = value;
  latest.current.onDone = onDone;

  useEffect(() => {
    const el = ref.current;
    if (el) {
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
    // 编辑中节点被卸载（onlyRenderVisibleElements 把它滚出视口）时不会有 blur，这里补存。
    // 只在改过时存：StrictMode 开发期会先假卸载一次，那时内容没变，不能把编辑框关掉。
    return () => {
      const l = latest.current;
      if (!l.done && l.value !== initial) l.onDone(l.value);
    };
    // 只在挂载时跑：initial 就是打开编辑框那一刻的原文
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 自动增高：先缩回 auto 再取 scrollHeight，否则只会变高不会变矮
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  return (
    <textarea
      ref={ref}
      className="cv-text__edit nodrag nowheel"
      value={value}
      placeholder="双击写点什么…"
      onChange={e => setValue(e.target.value)}
      onBlur={() => { latest.current.done = true; onDone(value); }}
      onKeyDown={e => {
        if (e.key === "Escape" || (e.key === "Enter" && (e.metaKey || e.ctrlKey))) {
          // 不让画布的全局快捷键再收到它（blur 之后焦点已不在输入框，Esc 会被当成「取消选中」）
          e.preventDefault();
          e.stopPropagation();
          e.currentTarget.blur();
        }
      }}
    />
  );
}
