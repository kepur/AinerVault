import { memo } from "react";
import type { NodeTypes } from "@xyflow/react";
import SharedStageNode from "./SharedStageNode";
import AudioNode from "./AudioNode";
import Box3DNode from "./Box3DNode";
import GroupNode from "./GroupNode";
import ImageNode from "./ImageNode";
import TextNode from "./TextNode";
import VideoNode from "./VideoNode";

/**
 * 节点类型表（模块级常量：xyflow 要求引用稳定，每次渲染新建会整张图重挂）。
 * 文字/图片/视频三个已经 memo 过；Box3DNode 约定导出的是普通函数，这里补一层 memo，
 * 保证「节点组件全部 memo」—— 别的节点被拖动时它不跟着重渲染。
 */
export const nodeTypes = {
  text: TextNode,
  image: ImageNode,
  video: VideoNode,
  audio: AudioNode,
  box3d: memo(Box3DNode),
  stage: SharedStageNode, coverage: SharedStageNode,
  group: GroupNode,
} satisfies NodeTypes;
