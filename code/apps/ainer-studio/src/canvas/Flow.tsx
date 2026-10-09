/**
 * 受控的 <ReactFlow>：nodes/edges 来自 store 的 GraphCtx（每帧变，只有这里订阅），回调全走 store。
 * children 渲染在 <ReactFlow> 里面 —— 底栏、小地图、节点工具条（NodeToolbar）都要 xyflow 的上下文。
 */
import { Background, BackgroundVariant, ReactFlow, type DefaultEdgeOptions, type ProOptions } from "@xyflow/react";
import { useState, type ReactNode } from "react";
import { ContextMenu, type CtxTarget } from "./chrome/ContextMenu";
import { edgeTypes } from "./edges";
import type { CEdge, CNode } from "./model";
import { nodeTypes } from "./nodes";
import { useCanvas, useFlowBinding } from "./store";

// 模块级常量：xyflow 每次渲染拿到新对象会以为配置变了
const EDGE_OPTIONS: DefaultEdgeOptions = { type: "glow" };
const PRO: ProOptions = { hideAttribution: true };

export function Flow({ children }: { children?: ReactNode }) {
  const s = useCanvas();
  const g = useFlowBinding();
  const [ctx, setCtx] = useState<CtxTarget | null>(null);
  return (
    <div className="cv-flow">
      <ReactFlow<CNode, CEdge>
        nodes={g.nodes}
        edges={g.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={EDGE_OPTIONS}
        onNodesChange={s.onNodesChange}
        onEdgesChange={s.onEdgesChange}
        onConnect={s.onConnect}
        isValidConnection={g.isValidConnection}
        onMoveEnd={g.onMoveEnd}
        onPaneClick={g.onPaneClick}
        // 只有人拖动 / 滚动画布才收菜单；选中节点后的自动平移（让开 Dock）event 是 null，不能把刚弹出的菜单关掉
        onMoveStart={e => { if (e) setCtx(null); }}
        // 右键：节点 / 多选框 / 连线 / 空白处各一份菜单（chrome/ContextMenu）
        onNodeContextMenu={(e, node) => {
          e.preventDefault();
          const multi = node.selected && s.nodes.filter(n => n.selected).length > 1;
          if (!multi) s.select(node.id);
          setCtx(multi ? { kind: "selection", x: e.clientX, y: e.clientY } : { kind: "node", id: node.id, x: e.clientX, y: e.clientY });
        }}
        onSelectionContextMenu={e => { e.preventDefault(); setCtx({ kind: "selection", x: e.clientX, y: e.clientY }); }}
        onEdgeContextMenu={(e, edge) => { e.preventDefault(); setCtx({ kind: "edge", id: edge.id, x: e.clientX, y: e.clientY }); }}
        onPaneContextMenu={e => { e.preventDefault(); s.select(null); setCtx({ kind: "pane", x: e.clientX, y: e.clientY }); }}
        colorMode="dark"
        minZoom={0.05}
        maxZoom={2.5}
        onlyRenderVisibleElements
        // 触控板：两指滑 = 平移，捏合 / ⌘+滚轮 = 缩放（纳逗、Figma 的手感）
        panOnScroll
        zoomOnPinch
        zoomActivationKeyCode="Meta"
        selectionKeyCode="Shift"
        multiSelectionKeyCode={["Meta", "Control"]}
        // 删除由 store 处理：派生节点只从画布拿掉，不能交给 xyflow 直接删
        deleteKeyCode={null}
        connectionRadius={28}
        proOptions={PRO}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1.2} color="var(--cv-dot)" />
        {children}
      </ReactFlow>
      <EmptyState />
      {ctx && !s.overlay && <ContextMenu at={ctx} onClose={() => setCtx(null)} />}
    </div>
  );
}

/** 编辑自由画布不依赖小说或分镜；首页列出同一工作区的画布。 */
function EmptyState() {
  const s = useCanvas();
  if (s.loading || (s.boardId && s.nodes.length && !s.error)) return null;
  if (s.error) return <div className="cv-empty cv-glass" role="alert"><b>载入失败</b><p>{s.error}</p></div>;
  if (s.boardId) return (
    <div className="cv-empty cv-glass" role="status">
      <b>从空白开始</b><p>点击底部「＋」自由添加文字、素材或白模，再拖动、连线与分组。修改会自动保存。</p>
      <div className="cv-empty__acts"><button type="button" className="cv-btn" onClick={() => s.openAddMenu({ x: innerWidth / 2, y: innerHeight / 2 })}>添加节点</button></div>
    </div>
  );
  return (
    <div className="cv-empty cv-glass cv-board-home">
      <b>我的画布</b><p>在顶部新建空白画布，或打开已有画布继续创作。</p>
      <div className="cv-board-home-list">
        {s.boards.map(b => <button key={b.id} type="button" className="cv-btn" onClick={() => s.openBoard(b.id)}>
          {b.title}<span>{b.plan_id ? "分镜" : "自由画布"}</span>
        </button>)}
        {!s.boards.length && <p>还没有画布。可以直接新建，无需小说或分镜。</p>}
      </div>
    </div>
  );
}
