import { memo, useEffect, useMemo } from "react";
import {
  Background, BackgroundVariant, Controls, Handle, MiniMap, Position, ReactFlow,
  ReactFlowProvider, useReactFlow, type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import { media } from "../api";
import type { Board, SceneInfo, ShotCard } from "../types";

type ShotNodeT = Node<{ shot: ShotCard; selected: boolean }, "shot">;
type SceneNodeT = Node<{ scene: SceneInfo; count: number }, "scene">;

const CARD_W = 196;
const CARD_H = 172;
const GAP_X = 28;
const GAP_Y = 30;
const PER_ROW = 8;
const LANE_GAP = 70;

function frameDot(f: ShotCard["first"]) {
  if (!f) return "dot";
  if (f.status === "generating") return "dot run";
  if (f.url && f.stale) return "dot stale";
  if (f.url) return "dot ok";
  return "dot";
}

const ShotNode = memo(function ShotNode({ data }: NodeProps<ShotNodeT>) {
  const s = data.shot;
  const thumb = media(s.first?.url ?? s.last?.url);
  return (
    <div className={`shot-node${data.selected ? " selected" : ""}`}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      {thumb
        ? <img className="thumb" src={thumb} loading="lazy" alt="" />
        : <div className="thumb empty">未出首帧</div>}
      <div className="meta">
        <span className="no">{s.order_no}</span>
        <span className="size">{s.shot_size}</span>
        {s.regional && <span className="badge">分区 {s.regional.people} 人</span>}
        <span className="dur">{(s.duration_ms / 1000).toFixed(1)}s</span>
      </div>
      <div className="dots" title="首帧 · 尾帧 · 视频">
        <span className={frameDot(s.first)} />
        <span className={frameDot(s.last)} />
        <span className={s.video_url ? "dot ok" : "dot"} />
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
});

const SceneNode = memo(function SceneNode({ data }: NodeProps<SceneNodeT>) {
  return (
    <div className="scene-node">
      <div className="t">{data.scene.order_no}. {data.scene.title}</div>
      <div className="s">{data.scene.location} · {data.scene.time_of_day} · {data.count} 镜</div>
    </div>
  );
});

const nodeTypes = { shot: ShotNode, scene: SceneNode };

/** 每场一条泳道：场景标签在最左，镜头按顺序往右排、满 8 张换行。时间从左往右流。 */
function layout(board: Board, selected: string | null) {
  const nodes: (ShotNodeT | SceneNodeT)[] = [];
  const edges: Edge[] = [];
  let y = 0;
  const lanes = board.scenes.length
    ? board.scenes
    : [{ id: "_", order_no: 1, title: "全部镜头", location: "", time_of_day: "" }];
  for (const sc of lanes) {
    const shots = board.shots.filter(s => (sc.id === "_" ? true : s.scene_id === sc.id));
    if (!shots.length) continue;
    nodes.push({
      id: `scene:${sc.id}`, type: "scene", position: { x: 0, y },
      data: { scene: sc, count: shots.length }, draggable: false, selectable: false,
    });
    shots.forEach((s, i) => {
      nodes.push({
        id: s.id, type: "shot",
        position: {
          x: CARD_W + 60 + (i % PER_ROW) * (CARD_W + GAP_X),
          y: y + Math.floor(i / PER_ROW) * (CARD_H + GAP_Y),
        },
        data: { shot: s, selected: s.id === selected },
      });
      if (i > 0) {
        edges.push({
          id: `${shots[i - 1].id}->${s.id}`, source: shots[i - 1].id, target: s.id,
          type: "smoothstep", style: { stroke: "#3a3a46", strokeWidth: 1.2 },
        });
      }
    });
    y += Math.ceil(shots.length / PER_ROW) * (CARD_H + GAP_Y) + LANE_GAP;
  }
  return { nodes, edges };
}

function Flow({ board, selected, onSelect, focusScene }: Props) {
  const { nodes, edges } = useMemo(() => layout(board, selected), [board, selected]);
  const flow = useReactFlow();

  // 默认定位到第一场的前两行：两百多镜全塞进一屏，卡片小得看不清
  const target = focusScene ?? board.scenes[0]?.id ?? null;
  useEffect(() => {
    if (!target) return;
    const ids = board.shots.filter(s => s.scene_id === target).map(s => ({ id: s.id }));
    if (!ids.length) return;
    const t = setTimeout(() => flow.fitView({
      nodes: [{ id: `scene:${target}` }, ...ids.slice(0, PER_ROW * 2)],
      duration: focusScene ? 450 : 0, padding: 0.12,
    }), 0);
    return () => clearTimeout(t);
  }, [target, focusScene, board.plan.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, n) => { if (n.type === "shot") onSelect(n.id); }}
      onlyRenderVisibleElements
      minZoom={0.05}
      maxZoom={2.5}
      proOptions={{ hideAttribution: true }}
      nodesConnectable={false}
      colorMode="dark"
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#2c2c34" />
      <MiniMap pannable zoomable nodeColor={n => (n.type === "scene" ? "#7c6cff" : "#44444f")}
        maskColor="rgba(10,10,12,.7)" style={{ background: "#16161a" }} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

interface Props {
  board: Board;
  selected: string | null;
  onSelect: (id: string) => void;
  focusScene: string | null;
}

export default function Canvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}
