/**
 * 场景求值：任意时刻 t 的物体位姿与机位位姿。纯函数，前端每帧调、运行时出概要也调。
 *
 * 机位关键帧可以相对运动中的目标（跟随／环绕），所以每一帧都现算：
 * 两个关键帧先各自在「此刻」求出位置，再按进度混合 —— 目标在跑，
 * 跟拍的两个关键帧也跟着跑，混出来的机位自然贴着目标。
 */
import type { CameraDef, CamKey, MoveTrack, SceneDoc, SceneObject, Transform, Vec3 } from "./types";
import {
  add, catmull, clamp, easeInOut, forwardOf, lerp, lerp3, localToWorld, norm, rad, sub, yawTo,
} from "./math";

export interface WorldPose {
  pos: Vec3;
  /** 欧拉角（度）；yaw = rot[1] */
  rot: Vec3;
  scale: Vec3;
}

export interface CamPose {
  pos: Vec3;
  look: Vec3;
  lens: number;
  roll: number;
}

const EPS = 1e-4;

function sortedKeys<T extends { t: number }>(keys: T[]): T[] {
  return keys.slice().sort((a, b) => a.t - b.t);
}

/** 把整段时间按缓动重映射：smooth = 整段起步缓、收尾缓，中间各段相对节奏不变。 */
function remap(t: number, t0: number, t1: number, ease: "linear" | "smooth") {
  if (t1 - t0 < EPS || ease === "linear") return t;
  return t0 + easeInOut((t - t0) / (t1 - t0)) * (t1 - t0);
}

function segment<T extends { t: number }>(keys: T[], t: number): { i: number; u: number } {
  if (t <= keys[0].t) return { i: 0, u: 0 };
  const last = keys.length - 1;
  if (t >= keys[last].t) return { i: Math.max(0, last - 1), u: last === 0 ? 0 : 1 };
  for (let i = 0; i < last; i++) {
    const a = keys[i].t, b = keys[i + 1].t;
    if (t >= a && t <= b) return { i, u: b - a < EPS ? 1 : (t - a) / (b - a) };
  }
  return { i: last - 1, u: 1 };
}

// ── 物体 ────────────────────────────────────────────────

interface FilledKey { t: number; pos: Vec3; rot: Vec3; scale: Vec3 }

const filledCache = new WeakMap<MoveTrack, FilledKey[]>();

function filled(track: MoveTrack, base: Transform): FilledKey[] {
  let out = filledCache.get(track);
  if (out) return out;
  let pos = base.pos, rot = base.rot, scale = base.scale;
  out = sortedKeys(track.keys).map(k => {
    pos = k.pos ?? pos; rot = k.rot ?? rot; scale = k.scale ?? scale;
    return { t: k.t, pos, rot, scale };
  });
  filledCache.set(track, out);
  return out;
}

function trackPos(keys: FilledKey[], track: MoveTrack, t: number): Vec3 {
  if (keys.length === 1) return keys[0].pos;
  const tt = remap(t, keys[0].t, keys[keys.length - 1].t, track.ease);
  const { i, u } = segment(keys, tt);
  if (track.path === "curve" && keys.length > 2) {
    const p0 = keys[Math.max(0, i - 1)].pos, p3 = keys[Math.min(keys.length - 1, i + 2)].pos;
    return catmull(p0, keys[i].pos, keys[i + 1].pos, p3, u);
  }
  return lerp3(keys[i].pos, keys[i + 1].pos, u);
}

/** 物体在 t 时刻的局部位姿（动画已作用，父级未合成）。 */
export function localPose(obj: SceneObject, t: number): WorldPose & { speed: number } {
  const base = obj.transform;
  const track = obj.track;
  if (!track || !track.keys.length) return { ...base, speed: 0 };
  const keys = filled(track, base);
  const pos = trackPos(keys, track, t);
  const tt = remap(t, keys[0].t, keys[keys.length - 1].t, track.ease);
  const { i, u } = segment(keys, tt);
  const k0 = keys[i], k1 = keys[Math.min(keys.length - 1, i + 1)];
  let rot = lerp3(k0.rot, k1.rot, u);
  const scale = lerp3(k0.scale, k1.scale, u);
  // 速度（有限差分）：朝向与步态都用它
  const dt = 1 / 30;
  const a = trackPos(keys, track, t - dt), b = trackPos(keys, track, t + dt);
  const v = sub(b, a);
  const speed = Math.hypot(v[0], v[2]) / (2 * dt);
  if (track.face === "path") {
    let yaw: number | null = null;
    if (speed > 0.05) yaw = (Math.atan2(v[0], v[2]) * 180) / Math.PI;
    else {
      // 停着的时候朝最近那段路的方向，而不是突然转回初始朝向
      for (let j = Math.min(i, keys.length - 2); j >= 0 && yaw === null; j--) {
        const d = sub(keys[j + 1].pos, keys[j].pos);
        if (Math.hypot(d[0], d[2]) > EPS) yaw = (Math.atan2(d[0], d[2]) * 180) / Math.PI;
      }
    }
    if (yaw !== null) rot = [rot[0], yaw, rot[2]];
  }
  return { pos, rot, scale, speed };
}

export class SceneEval {
  readonly doc: SceneDoc;
  readonly byId = new Map<string, SceneObject>();
  private gaitTables = new Map<string, { t0: number; dt: number; acc: number[] }>();

  constructor(doc: SceneDoc) {
    this.doc = doc;
    for (const o of doc.objects) this.byId.set(o.id, o);
  }

  /** 世界位姿：父级只合成平移、yaw 与缩放（足够白模预演用）。 */
  world(id: string, t: number, depth = 0): WorldPose & { speed: number } {
    const obj = this.byId.get(id);
    if (!obj) return { pos: [0, 0, 0], rot: [0, 0, 0], scale: [1, 1, 1], speed: 0 };
    const local = localPose(obj, t);
    if (!obj.parent || depth > 8) return local;
    const parent = this.world(obj.parent, t, depth + 1);
    const yaw = parent.rot[1];
    const scaled: Vec3 = [local.pos[0] * parent.scale[0], local.pos[1] * parent.scale[1], local.pos[2] * parent.scale[2]];
    const c = Math.cos(rad(yaw)), s = Math.sin(rad(yaw));
    const rotated: Vec3 = [scaled[0] * c + scaled[2] * s, scaled[1], -scaled[0] * s + scaled[2] * c];
    return {
      pos: add(parent.pos, rotated),
      rot: [local.rot[0], local.rot[1] + yaw, local.rot[2]],
      scale: [local.scale[0] * parent.scale[0], local.scale[1] * parent.scale[1], local.scale[2] * parent.scale[2]],
      speed: Math.max(local.speed, parent.speed),
    };
  }

  /** 看这个物体时该对准的高度：人看眼睛，其它看中部。 */
  aimHeight(id: string): number {
    const o = this.byId.get(id);
    if (!o) return 1;
    const h = o.size[1] * (o.transform.scale[1] || 1);
    return o.kind === "character" ? h * 0.9 : Math.max(0.5, h * 0.55);
  }

  /** 人物步态相位（走过的距离 / 步幅），拖时间轴也确定。 */
  gait(id: string, t: number): { phase: number; speed: number } {
    const o = this.byId.get(id);
    if (!o?.track) return { phase: 0, speed: 0 };
    let table = this.gaitTables.get(id);
    if (!table) {
      const keys = o.track.keys;
      const t0 = Math.min(...keys.map(k => k.t)), t1 = Math.max(...keys.map(k => k.t));
      const dt = 1 / 30;
      const acc = [0];
      let prev = this.world(id, t0).pos;
      for (let x = t0 + dt; x <= t1 + dt; x += dt) {
        const p = this.world(id, x).pos;
        acc.push(acc[acc.length - 1] + Math.hypot(p[0] - prev[0], p[2] - prev[2]));
        prev = p;
      }
      table = { t0, dt, acc };
      this.gaitTables.set(id, table);
    }
    const k = clamp(Math.floor((t - table.t0) / table.dt), 0, table.acc.length - 1);
    const stride = o.track.action === "run" ? 2.4 : 1.4;
    return { phase: table.acc[k] / stride, speed: this.world(id, t).speed };
  }

  // ── 机位 ──────────────────────────────────────────────

  private keyPos(key: CamKey, t: number): Vec3 {
    if (key.follow && this.byId.has(key.follow)) {
      const w = this.world(key.follow, t);
      return add(w.pos, localToWorld(key.offset ?? [0, 1.6, -4], w.rot[1]));
    }
    if (key.orbit && this.byId.has(key.orbit)) return this.orbitPos(key.orbit, key.angle ?? 0, key.radius ?? 4, key.height ?? 1.6, t);
    return key.at ?? [0, 1.6, 8];
  }

  private orbitPos(target: string, angle: number, radius: number, height: number, t: number): Vec3 {
    const w = this.world(target, t);
    // angle 0 = 目标正面；90 = 目标右侧；180 = 背后
    const dir = localToWorld([Math.sin(rad(angle)), 0, Math.cos(rad(angle))], w.rot[1]);
    return [w.pos[0] + dir[0] * radius, w.pos[1] + height, w.pos[2] + dir[2] * radius];
  }

  private keyLook(key: CamKey, t: number, pos: Vec3): Vec3 {
    const look = key.look;
    if (Array.isArray(look)) return look as Vec3;
    if (typeof look === "string" && this.byId.has(look)) {
      const w = this.world(look, t);
      return [w.pos[0], w.pos[1] + this.aimHeight(look), w.pos[2]];
    }
    if (look && typeof look === "object" && !Array.isArray(look) && this.byId.has(look.target)) {
      const w = this.world(look.target, t);
      return add(w.pos, localToWorld(look.offset ?? [0, this.aimHeight(look.target), 0], w.rot[1]));
    }
    const target = key.follow ?? key.orbit;
    if (target && this.byId.has(target)) {
      const w = this.world(target, t);
      return [w.pos[0], w.pos[1] + this.aimHeight(target), w.pos[2]];
    }
    // 没指定就往前看
    return add(pos, [0, -0.1, -5]);
  }

  camera(cam: CameraDef, t: number): CamPose {
    const keys = sortedKeys(cam.keys);
    if (!keys.length) return { pos: [0, 1.6, 10], look: [0, 1, 0], lens: cam.lens, roll: 0 };
    const tt = remap(t, keys[0].t, keys[keys.length - 1].t, cam.ease);
    const { i, u } = segment(keys, tt);
    const k0 = keys[i], k1 = keys[Math.min(keys.length - 1, i + 1)];
    let pos: Vec3;
    if (k0.orbit && k0.orbit === k1.orbit && this.byId.has(k0.orbit)) {
      // 同一目标的两个环绕关键帧：按角度、半径、高度插值 —— 才能绕半圈、两圈
      pos = this.orbitPos(k0.orbit, lerp(k0.angle ?? 0, k1.angle ?? 0, u), lerp(k0.radius ?? 4, k1.radius ?? 4, u),
        lerp(k0.height ?? 1.6, k1.height ?? 1.6, u), t);
    } else if (cam.path === "curve" && keys.length > 2) {
      const p = (j: number) => this.keyPos(keys[clamp(j, 0, keys.length - 1)], t);
      pos = catmull(p(i - 1), p(i), p(i + 1), p(i + 2), u);
    } else {
      pos = lerp3(this.keyPos(k0, t), this.keyPos(k1, t), u);
    }
    const look = lerp3(this.keyLook(k0, t, pos), this.keyLook(k1, t, pos), u);
    const lens = lerp(k0.lens ?? cam.lens, k1.lens ?? cam.lens, u);
    const roll = lerp(k0.roll ?? 0, k1.roll ?? 0, u);
    if (cam.shake > 0) {
      const a = 0.05 * cam.shake;
      const n = (f: number, p: number) => Math.sin(t * f + p) + 0.5 * Math.sin(t * f * 2.3 + p * 1.7);
      pos = add(pos, [a * n(5.1, 0.3), a * 0.7 * n(6.3, 1.1), a * 0.5 * n(4.2, 2.2)]);
      return { pos, look: add(look, [a * 0.6 * n(3.7, 0.9), a * 0.6 * n(4.9, 1.9), 0]), lens, roll: roll + cam.shake * 1.5 * n(2.9, 0.4) };
    }
    return { pos, look, lens, roll };
  }

  /** t 时刻主机位用的是哪台。 */
  activeCamera(t: number): CameraDef | null {
    const cams = this.doc.cameras;
    if (!cams.length) return null;
    let id = this.doc.cuts.length ? this.doc.cuts[0].camera : cams[0].id;
    for (const c of this.doc.cuts) if (c.t <= t + EPS) id = c.camera;
    return cams.find(c => c.id === id) ?? cams[0];
  }

  /** 机位在整段时间里的轨迹（画线用）。 */
  cameraTrail(cam: CameraDef, samples = 90): Vec3[] {
    const keys = sortedKeys(cam.keys);
    if (!keys.length) return [];
    const t0 = keys[0].t, t1 = Math.max(keys[keys.length - 1].t, t0 + EPS);
    const out: Vec3[] = [];
    for (let k = 0; k <= samples; k++) out.push(this.camera({ ...cam, shake: 0 }, t0 + ((t1 - t0) * k) / samples).pos);
    return out;
  }

  /** 关键帧此刻的实际位置（编辑时在视图里画菱形用）。 */
  keyWorld(key: CamKey): Vec3 {
    return this.keyPos(key, key.t);
  }

  keyLookWorld(key: CamKey): Vec3 {
    const p = this.keyPos(key, key.t);
    return this.keyLook(key, key.t, p);
  }
}

/** 从世界坐标位置反推关键帧参数（拖动关键帧后保持它原来的类型）。 */
export function keyFromWorld(ev: SceneEval, key: CamKey, pos: Vec3): CamKey {
  if (key.follow && ev.byId.has(key.follow)) {
    const w = ev.world(key.follow, key.t);
    const d = sub(pos, w.pos);
    const f = forwardOf(w.rot[1]);
    const r: Vec3 = [-f[2], 0, f[0]];   // 目标的右手（= rightOf）
    return { ...key, offset: [d[0] * r[0] + d[2] * r[2], d[1], d[0] * f[0] + d[2] * f[2]] };
  }
  if (key.orbit && ev.byId.has(key.orbit)) {
    const w = ev.world(key.orbit, key.t);
    const d = sub(pos, w.pos);
    const local = [d[0], d[2]];
    const fw = forwardOf(w.rot[1]);
    // 相对目标正面的角度：右手为正
    const right: Vec3 = [-fw[2], 0, fw[0]];
    const x = local[0] * right[0] + local[1] * right[2];
    const z = local[0] * fw[0] + local[1] * fw[2];
    return { ...key, angle: (Math.atan2(x, z) * 180) / Math.PI, radius: Math.hypot(x, z), height: d[1] };
  }
  return { ...key, at: pos };
}

/** 在两点之间看过去的 yaw（给运行时和预设用）。 */
export const lookYaw = (from: Vec3, to: Vec3) => yawTo(from, to);
export const unit = norm;
