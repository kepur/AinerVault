import { memo } from "react";
import type { NodeProps } from "@xyflow/react";
import { isProductionRef, type CNode } from "../model";
import { useNodeResolved } from "../store";
import { NodeShell, mediaSrc } from "./NodeShell";

function AudioNode({ id, data, selected }: NodeProps<CNode>) {
  const r = useNodeResolved(id);
  const m = r.kind === "media" ? r.media : isProductionRef(data.ref) ? null : data.media;
  const src = mediaSrc(m?.url);
  return <NodeShell id={id} kind="audio" data={data} selected={selected} width={300}>
    <div className="cv-audio nodrag nopan">
      {src ? <audio controls preload="metadata" src={src} /> : <p>{r.kind === "missing" ? r.reason || "找不到音频" : "还没有音频"}</p>}
    </div>
  </NodeShell>;
}
export default memo(AudioNode);
