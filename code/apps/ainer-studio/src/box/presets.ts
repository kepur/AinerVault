/** 在前端直接套运镜预设：和运行时 finish() 展开预设是同一套生成器。 */
import { CAMERA_PRESETS } from "../scene/cameraPresets";
import type { SceneEval } from "../scene/evaluate";
import type { CamKey, CameraDef, Vec3 } from "../scene/types";

export function presetKeys(ev: SceneEval, cam: CameraDef, presetId: string, target: string | null, start: number,
                           duration: number, side: 1 | -1 = 1): { keys: CamKey[]; ease?: "linear" | "smooth"; path?: "linear" | "curve"; shake?: number } {
  const def = CAMERA_PRESETS.find(p => p.id === presetId);
  if (!def) throw new Error(`没有运镜预设 ${presetId}`);
  const obj = target ? ev.byId.get(target) ?? null : null;
  const size = obj ? (obj.kind === "character" ? obj.size[1] : Math.max(obj.size[0], obj.size[2], obj.size[1])) : 1.75;
  const aim = obj ? (obj.kind === "character" ? obj.size[1] * 0.9 : Math.max(0.6, obj.size[1] * 0.55)) : 1.2;
  const point: Vec3 = [0, 0, 0];
  const res = def.build({
    target: obj ? obj.id : null, start, duration, side, lens: cam.lens, size, aim, angle: 15,
    posAt: t => (obj ? ev.world(obj.id, t).pos : point),
    yawAt: t => (obj ? ev.world(obj.id, t).rot[1] : 0),
  });
  return res;
}

/** 把新关键帧并进去：[start, end] 区间里原有的关键帧被替换。 */
export function mergeKeys(old: CamKey[], add: CamKey[]): CamKey[] {
  if (!add.length) return old;
  const t0 = Math.min(...add.map(k => k.t)) - 1e-3, t1 = Math.max(...add.map(k => k.t)) + 1e-3;
  return [...old.filter(k => k.t < t0 || k.t > t1), ...add].sort((a, b) => a.t - b.t);
}
