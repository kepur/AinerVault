import {
  useCallback, useLayoutEffect, useRef, useState, type MouseEvent, type ReactElement,
} from "react";
import { Handle, Position, useConnection } from "@xyflow/react";
import { media } from "../api";
import type { CanvasStore, NodeShellProps } from "../contract";
import type { GenState, NodeKind, TrackedTask } from "../model";
import { useCanvas } from "../store";

/** 标题左边的类型字（颜色在 nodes.css 里按类型给） */
export const KIND_GLYPH: Record<NodeKind, string> = { stage: "台", coverage: "镜", text: "文", image: "图", video: "影", audio: "音", box3d: "3D", group: "组" };

/**
 * 节点外壳：卡片上方的小标题、左右端口、选中光圈、流光 busy、「已失效」角标、选中时两侧的「+」。
 * 外壳本身不订阅 store —— 只有真正要读 store 的小块（流光、「+」）各自订阅，
 * 这样拖动别的节点时 store 变了，外壳和卡片内容不跟着重渲染。
 */
export function NodeShell({ id, kind, data, selected, width, children, badges, footer, busy, onOpen }: NodeShellProps) {
  // 连线进行中：除了起点自己，所有节点都亮出入口端口，省得用户先悬停才找得到落点
  const linking = useConnection(c => c.inProgress && c.fromNode?.id !== id);
  const cls = ["cv-node", `cv-node--${kind}`];
  if (selected) cls.push("is-selected");
  if (data.orphan) cls.push("is-orphan");
  if (linking) cls.push("is-linking");

  return (
    <div className={cls.join(" ")} style={{ width }}>
      <div className="cv-node__head">
        <span className="cv-node__glyph">{KIND_GLYPH[kind]}</span>
        <span className="cv-node__title" title={data.title}>{data.title || "未命名"}</span>
        {data.pinned && <PinMark />}
        {badges && <span className="cv-node__badges">{badges}</span>}
      </div>
      <div
        className="cv-card"
        onDoubleClick={onOpen ? (e) => { e.stopPropagation(); onOpen(); } : undefined}
      >
        {children}
        {(footer||data.comicLive)&&<div className="cv-card__foot">{footer}{data.comicLive&&<span className={`cv-comic-node-state${data.comicLive.stale||data.comic?.dirty?' is-stale':''}`}>{['queued','running'].includes(data.gen?.status||'')?'镜头制作中':data.comic?.dirty?'参数或引用已更改，待重新制作':data.comicLive.state}</span>}{data.comicLive?.asset?.route_reason&&!data.comic?.dirty&&!['queued','running'].includes(data.gen?.status||'')&&<span className="cv-comic-node-state" title={data.comicLive.asset.route_reason}>实际 {data.comicLive.asset.inference_fps} 帧/秒{data.comicLive.asset.width&&data.comicLive.asset.height?` · ${data.comicLive.asset.width}×${data.comicLive.asset.height}`:''} · {data.comicLive.asset.route_reason}</span>}</div>}
      </div>
      <BusyRing id={id} busy={!!busy} />
      {data.orphan && (
        <span className="cv-node__orphan" title="后端里找不到它了（分镜重编译后的旧镜头等），可以从画布上拿掉">
          已失效
        </span>
      )}
      <Handle type="target" position={Position.Left} className="cv-handle" />
      <Handle type="source" position={Position.Right} className="cv-handle" />
      {selected && <SidePlus id={id} />}
    </div>
  );
}

function PinMark() {
  return (
    <svg className="cv-node__pin" viewBox="0 0 12 12" aria-label="已钉住">
      <title>已钉住：自动整理不挪它</title>
      <path d="M4 1h4l-.6 3.2L9.5 6.5H6.6V11L6 11.6 5.4 11V6.5H2.5l2.1-2.3z" fill="currentColor" />
    </svg>
  );
}

/**
 * 边框流光。调用方给的 busy（生成中、导演在跑、白模搭景中）之外，
 * store.tasks 里挂在这个节点上的未结束任务也算 —— 这样任何节点登记了任务就自动有流光，
 * 不用每种节点各写一遍。单独成组件：只有它订阅 tasks。
 */
function BusyRing({ id, busy }: { id: string; busy: boolean }) {
  const s = useCanvas();
  const on = busy || s.tasks.some(t => t.nodeId === id && taskLive(t.status));
  return on ? <span className="cv-node__flow" aria-hidden /> : null;
}

/** 选中节点两侧的「+」：左边往上游加（新节点连进来），右边往下游加（从它接出去） */
function SidePlus({ id }: { id: string }) {
  const s = useCanvas();
  const open = (side: "left" | "right") => (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    const r = e.currentTarget.getBoundingClientRect();
    s.openAddMenu({ x: r.left + r.width / 2, y: r.top + r.height / 2 }, { nodeId: id, side });
  };
  return (
    <>
      <button type="button" className="cv-node__plus cv-node__plus--left nodrag nopan"
        title="往上游加一个节点（连进来）" onClick={open("left")}>
        <PlusIcon />
      </button>
      <button type="button" className="cv-node__plus cv-node__plus--right nodrag nopan"
        title="往下游加一个节点（从这里接出去）" onClick={open("right")}>
        <PlusIcon />
      </button>
    </>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 12 12" aria-hidden>
      <path d="M6 2v8M2 6h8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/* ───────────────────────── 节点之间共用的小件 ───────────────────────── */

/** 任务/生成状态里「还没结束」的那几种 */
export function taskLive(status: TrackedTask["status"] | GenState["status"]): boolean {
  return status === "queued" || status === "running";
}

/**
 * 显示用的媒体地址：/media 地址一律过 media()（铁律 2：后端常给 http://localhost:8100/media/…）。
 * data:/blob: 原样返回 —— base64 里碰巧出现 "/media/" 时 media() 会把它截坏。
 */
export function mediaSrc(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (url.startsWith("data:") || url.startsWith("blob:")) return url;
  return media(url);
}

/** 进度统一成 0–100：生成任务的 progress 有的后端给 0–1，有的给百分数 */
export function pct(p: number | null | undefined): number | null {
  if (p == null || !Number.isFinite(p)) return null;
  return Math.max(0, Math.min(100, Math.round(p <= 1 ? p * 100 : p)));
}

/**
 * 只在事件里才用得到 store 的节点用它（双击开浮层、存文字、删边）。
 * 为什么不直接 useCanvas()：store 是一整块 context，拖动任何一个节点它都会变，
 * 节点直接订阅 = 200+ 个 memo 节点每帧全部重渲染（memo 拦不住 context）。
 * 这里让一个什么都不画的子组件去订阅、把最新 store 放进 ref；它重渲染几乎不花钱，节点本身不动。
 * 用法：`const [tap, getStore] = useLazyStore();` 把 tap 放进 JSX 任意位置，事件里 `getStore()?.xxx`。
 */
export function useLazyStore(): [tap: ReactElement, get: () => CanvasStore | null] {
  const ref = useRef<CanvasStore | null>(null);
  // 同一个元素对象每次原样返回：父组件重渲染时 React 直接跳过 Tap
  const [tap] = useState(() => <StoreTap into={ref} />);
  const get = useCallback(() => ref.current, []);
  return [tap, get];
}

function StoreTap({ into }: { into: { current: CanvasStore | null } }) {
  const s = useCanvas();
  useLayoutEffect(() => { into.current = s; });
  return null;
}

/**
 * 自由生成产物还没出来时的占位：流光底 + 进度 + 模型名；失败写红字原因。
 * 图片、视频节点共用（外层容器负责宽高比）。
 */
export function GenPending({ gen }: { gen: GenState }) {
  const failed = gen.status === "failed" || gen.status === "cancelled";
  const p = pct(gen.progress);
  return (
    <div className={`cv-gen${failed ? " is-bad" : ""}`}>
      {failed ? (
        <span className="cv-gen__err" title={gen.error ?? undefined}>
          {gen.status === "cancelled" ? "已取消" : `生成失败${gen.error ? `：${gen.error}` : ""}`}
        </span>
      ) : (
        <>
          <span className="cv-gen__pct">
            {gen.status === "succeeded" ? "取回中…" : gen.status === "queued" ? "排队中" : p != null ? `${p}%` : "生成中…"}
          </span>
          {gen.model && <span className="cv-gen__model">{gen.model}</span>}
          {p != null && gen.status === "running" && <i className="cv-gen__bar" style={{ width: `${p}%` }} />}
        </>
      )}
    </div>
  );
}
