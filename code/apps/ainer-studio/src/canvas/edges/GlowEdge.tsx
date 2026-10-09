import { memo, type CSSProperties } from "react";
import {
  BaseEdge, EdgeLabelRenderer, getBezierPath, useStore, type EdgeProps,
} from "@xyflow/react";
import type { CEdge, EdgeKind } from "../model";
import { useCanvas } from "../store";

/** 缩到这个比例以下，剧本→镜头的派生暗线就不画了：全是线，看不清节点 */
const FLOW_HIDE_ZOOM = 0.25;

/**
 * 发光连线：底层一条粗而淡的光晕 + 上层一根细芯线，颜色按语义（--cv-edge-<kind>）。
 * 和选中节点相连、或这条边自己被选中时整体提亮；目标节点有任务在跑时芯线上流动虚线。
 */
function GlowEdge({
  id, source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected,
}: EdgeProps<CEdge>) {
  const kind: EdgeKind = data?.kind ?? "ref";
  // 直接读 xyflow 自己的节点表（布尔选择器），不订阅整块画布 store：拖动时几百条边不跟着重渲染。
  // 多选时与任一选中节点相连的边都会亮 —— 框选一组节点时这正是想看的。
  const near = useStore(s => !!(s.nodeLookup.get(source)?.selected || s.nodeLookup.get(target)?.selected));
  const hidden = useStore(s => kind === "flow" && s.transform[2] < FLOW_HIDE_ZOOM);
  if (hidden) return null;

  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const active = near || !!selected;
  const cls = `cv-edge--${kind}${active ? " is-active" : ""}`;
  const style = { "--cv-e": `var(--cv-edge-${kind})` } as CSSProperties;

  return (
    <>
      <path className={`cv-edge__halo ${cls}`} d={path} style={style} />
      <BaseEdge id={id} path={path} className={`cv-edge__core ${cls}`} style={style} interactionWidth={18} />
      <RunDash target={target} path={path} style={style} />
      {selected && !data?.derived && <EdgeDelete id={id} x={labelX} y={labelY} />}
    </>
  );
}

export default memo(GlowEdge);

/** 目标节点在跑任务（store.tasks 里挂着、还没结束）：芯线上叠一层流动虚线，看得出「料正往那边送」 */
function RunDash({ target, path, style }: { target: string; path: string; style: CSSProperties }) {
  const s = useCanvas();
  const running = s.tasks.some(t => t.nodeId === target && (t.status === "queued" || t.status === "running"));
  return running ? <path className="cv-edge__run" d={path} style={style} /> : null;
}

/** 用户连的边选中时在中点出一个「×」；派生边（剧本→镜头、白模→本镜）是后端关系，不让删 */
function EdgeDelete({ id, x, y }: { id: string; x: number; y: number }) {
  const s = useCanvas();
  return (
    <EdgeLabelRenderer>
      <button
        type="button"
        className="cv-edge__del nodrag nopan"
        style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
        title="删掉这条线"
        onClick={(e) => {
          e.stopPropagation();
          s.onEdgesChange([{ id, type: "remove" }]);
        }}
      >
        ×
      </button>
    </EdgeLabelRenderer>
  );
}
