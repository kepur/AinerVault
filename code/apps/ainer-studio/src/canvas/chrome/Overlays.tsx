/**
 * 浮层：媒体灯箱、导演台（Stage）；外加外壳各处共用的弹出层（Popover / 菜单 / 图标 / 转圈）。
 *
 * 弹出层为什么一律 portal 到 .cv-root：Dock、顶栏胶囊、节点工具条都用了 backdrop-filter，
 * 它会让 position:fixed 的后代改以它为包含块 —— 菜单会被关在卡片里、被圆角裁掉。
 * 挂到 .cv-root 下既逃开这个坑，又还在 tokens.css 的变量作用域里。
 */
import { QuickFilm } from "./QuickFilm";
import { ScreenplayConfigModal } from "./ScreenplayConfigModal";
import {
  lazy, Suspense, useEffect, useLayoutEffect, useRef, useState,
  type ReactNode, type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { useCanvas } from "../store";

// 导演台带着 three（stage/model 顶层 import THREE），点开才加载，主画布首包不带
const SharedStageWorkspace = lazy(() => import("../../production/SharedStageWorkspace"));
const Stage = lazy(() => import("../../components/Stage"));

/* ───────────────────────── 小工具 ───────────────────────── */

/** 异步回调里拿「最新的」值（store 每次渲染都是新对象，闭包里那份会过期） */
export function useLatest<T>(v: T): RefObject<T> {
  const r = useRef(v);
  r.current = v;
  return r;
}

export function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** 焦点在可输入的地方：画布快捷键（⌘K、/ 等）不能抢 */
export function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable;
}

export function host(): HTMLElement {
  return (document.querySelector(".cv-root") as HTMLElement | null) ?? document.body;
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <span className="cv-spin" style={{ width: size, height: size }} aria-label="进行中" />;
}

/* ───────────────────────── 图标（不引图标库，24 栅格描边） ───────────────────────── */

const PATHS = {
  plus: <path d="M12 5v14M5 12h14" />,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.5 4.5" /></>,
  grid: <><rect x="4" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" /></>,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9.3a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.2-2.5 3.8M12 17.2v.1" /></>,
  map: <><path d="M9 4 3.5 6v14L9 18l6 2 5.5-2V4L15 6 9 4Z" /><path d="M9 4v14M15 6v14" /></>,
  fit: <path d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4" />,
  down: <path d="m6 9 6 6 6-6" />,
  up: <path d="m6 15 6-6 6 6" />,
  right: <path d="m9 6 6 6-6 6" />,
  left: <path d="m15 6-6 6 6 6" />,
  send: <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />,
  upload: <><path d="M12 15V4M7.5 8.5 12 4l4.5 4.5" /><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></>,
  download: <><path d="M12 4v11M7.5 10.5 12 15l4.5-4.5" /><path d="M4 17v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1" /></>,
  sparkle: <><path d="m12 3.5 1.8 5 5 1.8-5 1.8-1.8 5-1.8-5-5-1.8 5-1.8 1.8-5Z" /><path d="m18.5 15 .7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8Z" /></>,
  mic: <><rect x="9" y="3.5" width="6" height="11" rx="3" /><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5" /></>,
  at: <><circle cx="12" cy="12" r="3.6" /><path d="M15.6 12v1.4a2.6 2.6 0 0 0 5.2 0V12a8.8 8.8 0 1 0-3.4 6.9" /></>,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  expand: <path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" />,
  pin: <><path d="M9 4h6l-1 5 3 3v1.5H7V12l3-3-1-5Z" /><path d="M12 13.5V20" /></>,
  layers: <><path d="m12 4 8.5 4.5L12 13 3.5 8.5 12 4Z" /><path d="m3.5 12.5 8.5 4.5 8.5-4.5" /></>,
  cube: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" /><path d="M12 12 4 7.5M12 12l8-4.5M12 12v9" /></>,
  image: <><rect x="3.5" y="5" width="17" height="14" rx="2.5" /><circle cx="9" cy="10" r="1.6" /><path d="m4 17 5-4.5 4 3.5 3-2.5 4.5 3.5" /></>,
  video: <><rect x="3.5" y="6" width="12.5" height="12" rx="2.5" /><path d="m16 10.5 4.5-2.5v8l-4.5-2.5" /></>,
  text: <path d="M5 6.5h14M5 11h14M5 15.5h9" />,
  prompt: <><path d="M4 6.5h16M4 11h9" /><path d="m13.5 19 .9-3.4 5-5 2.5 2.5-5 5-3.4.9Z" /></>,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  warn: <><path d="M12 4 2.8 19.5h18.4L12 4Z" /><path d="M12 10v4.5M12 17.2v.1" /></>,
  activity: <path d="M3.5 12h4l2.5-6 4 12 2.5-6h4" />,
  layout: <><rect x="3.5" y="4" width="17" height="16" rx="2.5" /><path d="M3.5 9.5h17M9.5 9.5V20" /></>,
  play: <path d="M8 5.5v13l10.5-6.5L8 5.5Z" />,
  refresh: <><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" /><path d="M19.5 4.5v4h-4" /></>,
  out: <><path d="M14 4h6v6M20 4l-8.5 8.5" /><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" /></>,
  copy: <><rect x="8.5" y="8.5" width="11" height="11" rx="2" /><path d="M15.5 8.5v-2a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2" /></>,
  user: <><circle cx="12" cy="8.5" r="3.8" /><path d="M4.5 20a7.5 7.5 0 0 1 15 0" /></>,
  folder: <path d="M3.5 7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7Z" />,
  trash: <><path d="M4.5 7h15M9.5 7V5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v2" /><path d="M6.5 7l.8 12a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4L17.5 7M10 11v6M14 11v6" /></>,
  undo: <><path d="M9 7 4.5 11.5 9 16" /><path d="M5 11.5h9a5 5 0 0 1 0 10h-2" /></>,
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg className={className ? `cv-ico ${className}` : "cv-ico"} width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {PATHS[name]}
    </svg>
  );
}

/* ───────────────────────── 弹出层 ───────────────────────── */

export type Anchor = HTMLElement | { x: number; y: number; w?: number; h?: number };
export type Placement = "bottom-start" | "bottom" | "bottom-end" | "top-start" | "top" | "top-end" | "right-start";

function rectOf(a: Anchor): { left: number; top: number; right: number; bottom: number; width: number } {
  if (a instanceof HTMLElement) {
    const r = a.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width };
  }
  const w = a.w ?? 0;
  const h = a.h ?? 0;
  return { left: a.x, top: a.y, right: a.x + w, bottom: a.y + h, width: w };
}

/**
 * 锚在一个元素（或屏幕上的一个点）旁边的弹出层：下面放不下就翻到上面，左右夹在视口里。
 * 点外面 / Esc 关闭；Esc 在捕获阶段截住，免得画布把它当成「取消选中」把 Dock 也关了。
 * 锚是元素时每帧跟一下位置（节点工具条会随画布平移）。
 */
export function Popover({ anchor, onClose, placement = "bottom-start", offset = 8, className, children, role = "menu" }: {
  anchor: Anchor;
  onClose: () => void;
  placement?: Placement;
  offset?: number;
  className?: string;
  children: ReactNode;
  role?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const close = useLatest(onClose);
  const key = anchor instanceof HTMLElement ? anchor : `${anchor.x},${anchor.y},${anchor.w ?? 0},${anchor.h ?? 0}`;

  useLayoutEffect(() => {
    let last = "";
    const place = () => {
      const el = ref.current;
      if (!el) return;
      const a = rectOf(anchor);
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const m = 8;
      const [side, align = "center"] = placement.split("-") as [string, string?];
      let left: number;
      let top: number;
      if (side === "right") {
        left = a.right + offset;
        if (left + w > vw - m) left = a.left - offset - w;
        top = a.top;
      } else {
        const below = a.bottom + offset;
        const above = a.top - offset - h;
        if (side === "top") top = above >= m ? above : below;
        else top = below + h <= vh - m || above < m ? below : above;
        left = align === "start" ? a.left : align === "end" ? a.right - w : a.left + a.width / 2 - w / 2;
      }
      left = Math.max(m, Math.min(left, vw - w - m));
      top = Math.max(m, Math.min(top, vh - h - m));
      const k = `${Math.round(left)},${Math.round(top)}`;
      if (k !== last) { last = k; setPos({ left, top }); }
    };
    place();
    let raf = 0;
    const follow = () => { place(); raf = requestAnimationFrame(follow); };
    if (anchor instanceof HTMLElement) raf = requestAnimationFrame(follow);
    const ro = new ResizeObserver(place);
    if (ref.current) ro.observe(ref.current);
    window.addEventListener("resize", place);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); window.removeEventListener("resize", place); };
    // key 已经编码了 anchor 的身份
  }, [key, placement, offset]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const down = (e: PointerEvent) => {
      const t = e.target as Node | null;
      if (!t) return;
      if (ref.current?.contains(t)) return;
      if (anchor instanceof HTMLElement && anchor.contains(t)) return; // 让锚按钮自己切换开关
      if ((t as Element).closest?.(".cv-pop")) return; // 叠着的二级弹层
      close.current();
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      close.current();
    };
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("keydown", esc, true);
    return () => {
      window.removeEventListener("pointerdown", down, true);
      window.removeEventListener("keydown", esc, true);
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  return createPortal(
    <div ref={ref} role={role} className={`cv-pop cv-glass${className ? ` ${className}` : ""}`}
      style={{ left: pos?.left ?? -9999, top: pos?.top ?? -9999, visibility: pos ? "visible" : "hidden" }}
      onWheel={e => e.stopPropagation()}>
      {children}
    </div>,
    host(),
  );
}

export interface MenuItem {
  id: string;
  label: ReactNode;
  icon?: ReactNode;
  /** 右侧的小字（快捷键、数量、「本机」） */
  hint?: ReactNode;
  badge?: "NEW";
  /** 不可用的原因：灰掉，并把原因直接写在下面一行（tooltip 不一定有人去悬停） */
  disabled?: string | false;
  title?: string;
  active?: boolean;
  /** 有下一级（只画个 ›，展开由调用方处理） */
  more?: boolean;
  onPick?: () => void;
}

export function MenuList({ items, empty, onPicked }: { items: MenuItem[]; empty?: ReactNode; onPicked?: () => void }) {
  if (!items.length) return <div className="cv-menu-empty">{empty ?? "没有可选的"}</div>;
  return (
    <div className="cv-menu">
      {items.map(it => (
        <button key={it.id} type="button" role="menuitem"
          className={`cv-menu-item${it.active ? " is-active" : ""}${it.disabled ? " is-off" : ""}`}
          aria-disabled={!!it.disabled}
          title={it.disabled || it.title || undefined}
          onClick={() => {
            if (it.disabled) return;
            it.onPick?.();
            if (!it.more) onPicked?.();
          }}>
          {it.icon != null && <span className="cv-menu-icon">{it.icon}</span>}
          <span className="cv-menu-main">
            <span className="cv-menu-label">
              {it.label}
              {it.badge && <span className="cv-new">{it.badge}</span>}
            </span>
            {it.disabled && <span className="cv-menu-why">{it.disabled}</span>}
          </span>
          {it.hint != null && <span className="cv-menu-hint">{it.hint}</span>}
          {it.active && <Icon name="check" size={14} className="cv-menu-check" />}
          {it.more && <Icon name="right" size={14} className="cv-menu-more" />}
        </button>
      ))}
    </div>
  );
}

/* ───────────────────────── 全屏浮层 ───────────────────────── */

export function Overlays() {
  const s = useCanvas();
  const o = s.overlay;
  const latest = useLatest(s);
  const shot = o?.kind === "stage" ? s.live.board?.shots.find(x => x.id === o.shotId) ?? null : null;
  const stageMissing = o?.kind === "stage" && !shot;

  // 灯箱 Esc 关（导演台自己在 window 上听 Esc）
  useEffect(() => {
    if (o?.kind !== "media") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      latest.current.openOverlay(null);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [o?.kind]); // eslint-disable-line react-hooks/exhaustive-deps

  // 镜头在重载后不在了（分镜重编译）：别留一个空浮层挡住画布
  useEffect(() => {
    if (!stageMissing) return;
    latest.current.toast("这一镜已经不在当前分镜里了，导演台打不开", "err");
    latest.current.openOverlay(null);
  }, [stageMissing]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!o) return null;
  const close = () => s.openOverlay(null);

  if (o.kind === "shared_stage") return <Suspense fallback={<div className="cv-pill cv-glass">载入共享舞台…</div>}>
    <SharedStageWorkspace key={`${s.boardId}:${o.id ?? ""}`} boardId={s.boardId} initialStageId={o.id} onClose={close} />
  </Suspense>;

  if (o.kind === "quick") return <QuickFilm onClose={close} />;
  if (o.kind === "screenplay_config") return <ScreenplayConfigModal nodeId={o.nodeId} presetId={o.presetId} onClose={close} />;

  if (o.kind === "media") {
    return (
      <div className="cv-lightbox" onClick={close} role="dialog" aria-label="查看媒体">
        <button type="button" className="cv-lightbox-close" onClick={close} title="关闭（Esc）"><Icon name="close" size={18} /></button>
        <div className="cv-lightbox-stage" onClick={e => e.stopPropagation()}>
          {o.video
            ? <video key={o.url} src={o.url} controls autoPlay playsInline loop />
            : <img src={o.url} alt="" />}
        </div>
      </div>
    );
  }

  if (o.kind === "stage" && shot) {
    // 导演台是现成组件、靠全局 styles.css 的 button/select 样式；放在 .cv-root 里会被画布的按钮复位抹掉，
    // 所以挂到 body 下（它自己是 fixed 全屏、z-index 50）
    return createPortal(
      <Suspense fallback={<div className="stage-wrap"><div className="empty-state">载入 3D 导演台…</div></div>}>
        <Stage shot={shot} cast={s.live.cast} onClose={close} onChanged={() => void latest.current.reloadLive()} />
      </Suspense>,
      document.body,
    );
  }
  // kind === "box" 由 three/BoxOverlay 负责
  return null;
}
