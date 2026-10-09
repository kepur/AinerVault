import VideoFrame from "./VideoFrame";
import { directorPending } from "../shotStatus";
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

const FLOW_STEP: Record<string, string> = { audio: "配音", frame: "分镜图", video: "出视频", director: "3D 导演" };

const ShotNode = memo(function ShotNode({ data }: NodeProps<ShotNodeT>) {
  const s = data.shot;
  // 视频才是现在的成品（首尾帧已作废）：有视频就取视频自己的第一帧，旧图只在没视频时兜底
  const still = media(s.first?.url ?? s.last?.url);
  const pending = directorPending(s);
  // 创作画布的一键出片 / 出分镜图正跑到这一镜
  const flow = s.canvas_run;
  const flowStep = flow ? (FLOW_STEP[flow.step] ?? flow.step) : "";
  return (
    <div className={`shot-node${data.selected ? " selected" : ""}`}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      {s.video_url
        ? <VideoFrame className="thumb" src={media(s.video_url)} />
        : still
          ? <img className="thumb" src={still} loading="lazy" alt="" />
          : <div className="thumb empty">{pending ? "导演出片中…" : flow ? `创作画布 · ${flowStep}…` : "未出片"}</div>}
      <div className="meta">
        <span className="no">{s.order_no}</span>
        <span className="size">{s.shot_size}</span>
        {pending || flow
          ? <span className="badge now" title={flow ? `创作画布一键出片：${flowStep}${flow.status === "pending" ? "（排队）" : ""}` : undefined}>
            {flow ? (flow.status === "pending" ? "排队" : flowStep) : "出片中"}
          </span>
          : s.director?.done && <span className="badge" title="LLM 搭景 → Blender 预演 → 角色库的脸 → LTX 2.5">3D 导演</span>}
        <span className="dur">{(s.duration_ms / 1000).toFixed(1)}s</span>
      </div>
      <div className="dots" title="视频">
        <span className={pending || flow ? "dot run" : s.video_url ? "dot ok" : "dot"} />
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

function Flow({ board, selected, onSelect, focusScene, focusShot }: Props) {
  const { nodes, edges } = useMemo(() => layout(board, selected), [board, selected]);
  const flow = useReactFlow();

  // 默认定位到第一场的前两行：两百多镜全塞进一屏，卡片小得看不清
  const target = focusScene ?? board.scenes[0]?.id ?? null;
  useEffect(() => {
    if (!target) return;
    if (focusShot && !focusScene) return; // 深链带了镜头：下面那个效果飞到这一镜
    const ids = board.shots.filter(s => s.scene_id === target).map(s => ({ id: s.id }));
    if (!ids.length) return;
    const t = setTimeout(() => flow.fitView({
      nodes: [{ id: `scene:${target}` }, ...ids.slice(0, PER_ROW * 2)],
      duration: focusScene ? 450 : 0, padding: 0.12,
    }), 0);
    return () => clearTimeout(t);
  }, [target, focusScene, board.plan.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // 深链 ?shot=：飞到这一镜（连同同一行的邻镜，别放得太大）
  useEffect(() => {
    if (!focusShot) return;
    const shot = board.shots.find(s => s.id === focusShot);
    if (!shot) return;
    const row = board.shots.filter(s => s.scene_id === shot.scene_id);
    const i = row.findIndex(s => s.id === focusShot);
    const near = row.slice(Math.max(0, i - 1), i + 2).map(s => ({ id: s.id }));
    const t = setTimeout(() => flow.fitView({ nodes: near, duration: 0, padding: 0.2, maxZoom: 1 }), 30);
    return () => clearTimeout(t);
  }, [focusShot, board.plan.id]); // eslint-disable-line react-hooks/exhaustive-deps

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
  focusShot?: string | null;
}

export default function Canvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}
