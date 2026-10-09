import type { EdgeTypes } from "@xyflow/react";
import GlowEdge from "./GlowEdge";

/** 画布只有一种边，语义（flow/identity/control/ref/style）放在 edge.data.kind 里，由 GlowEdge 按它着色 */
export const edgeTypes = { glow: GlowEdge } satisfies EdgeTypes;
