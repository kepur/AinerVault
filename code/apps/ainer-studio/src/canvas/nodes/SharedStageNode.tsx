import { lazy, memo, Suspense, useEffect, useState } from "react";
import type { NodeProps } from "@xyflow/react";
import { Clock } from "../../box/clock";
import type { SceneDoc } from "../../scene/types";
import { sharedStages } from "../../production/stages";
import { isProductionRef, type CNode } from "../model";
import { useNodeResolved } from "../store";
import { LIVE_PRIORITY, useLiveSlot } from "../three/liveBudget";
import { NodeShell, useLazyStore } from "./NodeShell";

const Preview = lazy(() => import("../three/BoxPreview"));

function SharedStageNode({ id, data, selected }: NodeProps<CNode>) {
  const [tap, getStore] = useLazyStore();
  const boardId = getStore()?.boardId ?? "";
  const resolved = useNodeResolved(id);
  const resource = resolved.kind === "stage_resource" ? resolved.resource : null;
  const ref = isProductionRef(data.ref) ? data.ref : null;
  const signature = JSON.stringify(ref);
  const [preview, setPreview] = useState<{ key: string; doc: SceneDoc } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [clock] = useState(() => new Clock());
  const slot = useLiveSlot(id, !!selected && !!resource, LIVE_PRIORITY.selected);
  const doc = preview?.key === signature && resource ? preview.doc : null;
  const coverage = resource?.coverage;
  useEffect(() => {
    let alive = true;
    if (!slot || !ref || !resource || !boardId) return;
    setError("");
    sharedStages.referencePreview(boardId, ref).then(value => {
      if (!alive) return;
      clock.pause(); clock.duration = value.doc.duration;
      clock.seek((value.resource.coverage?.scene_start_ms ?? 0) / 1000);
      setPreview({ key: signature, doc: value.doc });
    }).catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; clock.pause(); };
    // Source identity and selected live slot govern loading; geometry stays in the source.
  }, [signature, slot, boardId, resource?.revision, clock]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => clock.pause(), [clock]);
  const exportControl = async () => {
    if (!ref) return;
    setBusy(true); setError("");
    try {
      const value = await sharedStages.referenceBake(boardId, ref);
      const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = `coverage-${id}.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const sourceId = resource?.stage_id ?? (ref?.kind === "coverage" ? ref.id.split(":", 1)[0] : ref?.id);
  const open = () => { if (sourceId) getStore()?.openOverlay({ kind: "shared_stage", id: sourceId }); };
  return <NodeShell id={id} kind={ref?.kind === "coverage" ? "coverage" : "stage"} data={data} selected={!!selected}
    width={300} onOpen={open} badges={resource ? <span>版本 {resource.stage_version}</span> : null}>
    {tap}<div className="cv-stage-ref nodrag nowheel">
      <div className="cv-stage-ref-preview">
        {slot && doc ? <Suspense fallback={<span>载入预演…</span>}><Preview doc={doc} clock={clock}
          camId={coverage?.camera_id ?? null} /></Suspense> : <span>{resolved.kind === "missing" ? resolved.reason : "选中查看共享舞台"}</span>}
      </div>
      {coverage && <small>{coverage.camera_id} · {coverage.clip_duration_ms / 1000}s · 场景 {coverage.scene_start_ms / 1000} → {coverage.scene_end_ms / 1000}s</small>}
      {resource && <small>引用素材 {resource.dependencies?.length ?? 0} 项 · {resource.coverages?.length ?? 0} 个镜头</small>}
      {coverage && <div>{[0, 0.5, 1].map((fraction, i) => <button key={i} disabled={!doc || !slot}
        onClick={() => clock.seek((coverage.scene_start_ms + (coverage.scene_end_ms - coverage.scene_start_ms) * fraction) / 1000)}>{["首", "中", "尾"][i]}帧</button>)}</div>}
      <div><button disabled={!sourceId} onClick={open}>编辑来源舞台</button>
        {coverage && <button disabled={busy || !resource} onClick={() => void exportControl()}>{busy ? "导出中…" : "导出镜头控制"}</button>}</div>
      {error && <small role="alert">{error}</small>}
    </div>
  </NodeShell>;
}
export default memo(SharedStageNode);
