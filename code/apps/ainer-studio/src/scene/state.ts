/** Arbitrary-time state uses the exact evaluator and rig used by preview and bake. */
import { SceneEval } from "./evaluate";
import { jointsAt, mannequinDims } from "./rig";
import type { SceneDoc } from "./types";

export function stateAt(doc: SceneDoc, t: number, cameraId?: string | null) {
  if (!Number.isFinite(t) || t < 0 || t > doc.duration) throw new Error("场景时间超出舞台范围");
  const ev = new SceneEval(doc);
  const camera = cameraId ? doc.cameras.find(c => c.id === cameraId) : ev.activeCamera(t);
  if (cameraId && !camera) throw new Error("机位不存在");
  return {
    time_ms: t * 1000,
    coordinate_system: { unit: "meter", up: "+Y", forward: "+Z", handedness: "right" },
    instances: doc.objects.map(o => ({
      id: o.id, kind: o.kind, ref: o.ref ?? null, parent: o.parent ?? null,
      world: ev.world(o.id, t),
      rig: o.kind === "character" ? jointsAt(ev, o, t, mannequinDims(o.body ?? "male", o.size[1])) : null,
    })),
    camera: camera ? { id: camera.id, ...ev.camera(camera, t) } : null,
  };
}
