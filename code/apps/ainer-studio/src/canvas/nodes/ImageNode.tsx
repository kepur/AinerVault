import { memo, useState } from "react";
import type { NodeProps } from "@xyflow/react";
import type { CNode, CNodeData, ImageRole, MediaRef } from "../model";
import { isProductionRef } from "../model";
import { useNodeResolved } from "../store";
import { GenPending, NodeShell, mediaSrc, useLazyStore } from "./NodeShell";

/**
 * 三种版式：
 *   portrait 定妆照：宽 150、固定 3:4、cover（纳逗截图里的竖图）
 *   sheet    多角度设定图：宽 300、按原图比例、contain 黑底（拼版宽度不固定，不能写死比例）
 *   free     其它：宽 220、按原图比例，最高到 4:3 竖图为止，再高就裁成 cover
 */
type Layout = "portrait" | "sheet" | "free";
const WIDTH: Record<Layout, number> = { portrait: 150, sheet: 300, free: 220 };
/** 高/宽 的上下限与没量到原图尺寸时的默认值 */
const RATIO: Record<Layout, { min: number; max: number; def: number }> = {
  portrait: { min: 4 / 3, max: 4 / 3, def: 4 / 3 },
  sheet: { min: 0.2, max: 1.5, def: 0.42 },
  free: { min: 0.25, max: 4 / 3, def: 0.75 },
};

function roleOf(data: CNodeData): ImageRole {
  const r = data.role;
  if (r === "character" || r === "sheet" || r === "view" || r === "upload" || r === "generated" || r === "frame" || r === "control") return r;
  if (data.ref.kind === "entity_view") return data.ref.view === "sheet" ? "sheet" : "character";
  return data.ref.kind === "asset" ? "upload" : "generated";
}

function layoutOf(role: ImageRole): Layout {
  return role === "character" ? "portrait" : role === "sheet" ? "sheet" : "free";
}

/**
 * 图片节点：定妆照、设定图、角色视角图（派生，只读 —— 外观只在造型室改，铁律 4），
 * 上传图、自由生成的图、导演产物里的帧/控制图（自由）。
 * 双击看大图；单击不放大（单击要留给选中和拖动）。
 */
function ImageNode({ id, data, selected }: NodeProps<CNode>) {
  const r = useNodeResolved(id);
  const [tap, getStore] = useLazyStore();
  const role = roleOf(data);
  const layout = layoutOf(role);

  let raw: string | null | undefined;
  let hint: MediaRef | null = null;
  let empty = "还没有图";
  if (r.kind === "entity_view") {
    raw = r.url;
    empty = "这个视角还没出图，去角色库生成";
  } else if (r.kind === "media") {
    raw = r.media.url;
    hint = r.media;
  } else {
    raw = isProductionRef(data.ref) ? null : data.media?.url;
    hint = data.media ?? null;
    if (r.kind === "missing") empty = r.reason || (data.orphan ? "找不到原图了" : empty);
  }
  const src = mediaSrc(raw);
  const gen = data.gen;
  // 生成产物：任务没成功前一律显示进度占位（成功后 store 会把 media 填上，再换成图）
  const pending = gen && (gen.status !== "succeeded" || !src) ? gen : null;
  // 默认期（baseline）不挂角标，只在悬停标题时看得到；非默认期才占标题栏位置
  const epoch = r.kind === "entity_view" && r.member.epoch && r.member.epoch !== "baseline" ? r.member.epoch : null;
  // 音色只挂在主定妆照上（设定图那张不重复挂）：出片时台词按它配音、再驱动口型
  const voice = r.kind === "entity_view" && data.ref.kind === "entity_view" && data.ref.view !== "sheet" ? r.voice : null;

  return (
    <NodeShell
      id={id}
      kind="image"
      data={data}
      selected={selected}
      width={WIDTH[layout]}
      badges={epoch || voice ? (
        <>
          {voice && (
            <span className="cv-badge is-ok is-icon" title={`音色：${voice.describe}${voice.has_ref ? "（有参考音频）" : ""}\n出片时这个人的台词按它配音，再用配音驱动口型`}>
              ♪
            </span>
          )}
          {epoch && <span className="cv-badge" title="角色时期（本章用的是这一期的造型）">{epoch}</span>}
        </>
      ) : undefined}
      onOpen={src && !pending ? () => getStore()?.openOverlay({ kind: "media", url: src, video: false }) : undefined}
    >
      {pending ? (
        <div className={`cv-pic cv-pic--${layout}`} style={{ aspectRatio: aspect(layout, hint) }}>
          <GenPending gen={pending} />
        </div>
      ) : src ? (
        // key：换图时重置加载状态和量到的比例
        <Picture key={src} src={src} layout={layout} hint={hint} />
      ) : (
        <div className={`cv-pic cv-pic--${layout} is-empty`} style={{ aspectRatio: aspect(layout, hint) }}>
          <span className="cv-pic__note">{empty}</span>
        </div>
      )}
      {tap}
    </NodeShell>
  );
}

export default memo(ImageNode);

/** CSS aspect-ratio（宽/高）。比例按版式夹住；没量到原图时用 media 里存的宽高，再没有用默认 */
function aspect(layout: Layout, hint: MediaRef | null, natural?: number | null): string {
  const lim = RATIO[layout];
  let hw = natural ?? (hint?.w && hint?.h ? hint.h / hint.w : lim.def);
  hw = Math.min(lim.max, Math.max(lim.min, hw));
  return `1 / ${hw.toFixed(4)}`;
}

function Picture({ src, layout, hint }: { src: string; layout: Layout; hint: MediaRef | null }) {
  const [state, setState] = useState<"load" | "ok" | "err">("load");
  const [natural, setNatural] = useState<number | null>(null);
  return (
    <div className={`cv-pic cv-pic--${layout} is-${state}`} style={{ aspectRatio: aspect(layout, hint, natural) }}>
      <img
        src={src}
        alt=""
        draggable={false}
        decoding="async"
        onLoad={e => {
          const { naturalWidth: w, naturalHeight: h } = e.currentTarget;
          // 没写宽高的 SVG（演示数据）naturalWidth 可能是 0：沿用默认比例
          if (w > 0 && h > 0) setNatural(h / w);
          setState("ok");
        }}
        onError={() => setState("err")}
      />
      {state === "err" && <span className="cv-pic__note is-bad">图挂了</span>}
    </div>
  );
}
