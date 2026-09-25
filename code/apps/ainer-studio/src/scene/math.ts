/** 场景运行时的数学小工具：纯函数，不依赖 three（要在后端的 vm 沙箱里跑）。 */
import type { Vec2, Vec3 } from "./types";

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
export const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const len = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);
export const dist = (a: Vec3, b: Vec3) => len(sub(a, b));
export const norm = (a: Vec3): Vec3 => { const l = len(a) || 1; return scale(a, 1 / l); };
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const lerp3 = (a: Vec3, b: Vec3, t: number): Vec3 =>
  [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
export const rad = (d: number) => (d * Math.PI) / 180;
export const deg = (r: number) => (r * 180) / Math.PI;
export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** 物体朝向（yaw，度）→ 前方单位向量。yaw 0 = +Z，yaw 90 = +X。 */
export const forwardOf = (yaw: number): Vec3 => [Math.sin(rad(yaw)), 0, Math.cos(rad(yaw))];
/** 物体自己的右手方向（面向 +Z 时右手在 -X）。 */
export const rightOf = (yaw: number): Vec3 => [-Math.cos(rad(yaw)), 0, Math.sin(rad(yaw))];
/** 从 a 看向 b 的 yaw（度）。 */
export const yawTo = (a: Vec3, b: Vec3) => deg(Math.atan2(b[0] - a[0], b[2] - a[2]));

/** 目标局部偏移（x 右、y 上、z 前）→ 世界偏移。 */
export function localToWorld(offset: Vec3, yaw: number): Vec3 {
  const f = forwardOf(yaw);
  const r = rightOf(yaw);
  return [r[0] * offset[0] + f[0] * offset[2], offset[1], r[2] * offset[0] + f[2] * offset[2]];
}

/** 世界偏移 → 目标局部偏移（localToWorld 的逆）。 */
export function worldToLocal(v: Vec3, yaw: number): Vec3 {
  const f = forwardOf(yaw);
  const r = rightOf(yaw);
  return [v[0] * r[0] + v[2] * r[2], v[1], v[0] * f[0] + v[2] * f[2]];
}

export function easeInOut(t: number) {
  t = clamp(t, 0, 1);
  return t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
}

/** 可复现的随机数（mulberry32）：同一个 seed，脚本每次跑出同一个场景。 */
export function rng(seed: number) {
  let a = seed >>> 0 || 1;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 均匀 Catmull-Rom：p1→p2 之间的 u（0–1）。 */
export function catmull(p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, u: number): Vec3 {
  const u2 = u * u;
  const u3 = u2 * u;
  const f = (a: number, b: number, c: number, d: number) =>
    0.5 * (2 * b + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u2 + (-a + 3 * b - 3 * c + d) * u3);
  return [f(p0[0], p1[0], p2[0], p3[0]), f(p0[1], p1[1], p2[1], p3[1]), f(p0[2], p1[2], p2[2], p3[2])];
}

/** 折线总长与按弧长取点。 */
export function polyLength(pts: Vec3[]) {
  let s = 0;
  for (let i = 1; i < pts.length; i++) s += dist(pts[i - 1], pts[i]);
  return s;
}

export function samplePoly(pts: Vec3[], s: number): { p: Vec3; dir: Vec3 } {
  if (pts.length === 1) return { p: pts[0], dir: [0, 0, 1] };
  let acc = 0;
  for (let i = 1; i < pts.length; i++) {
    const seg = dist(pts[i - 1], pts[i]);
    if (acc + seg >= s || i === pts.length - 1) {
      const u = seg > 0 ? clamp((s - acc) / seg, 0, 1) : 0;
      return { p: lerp3(pts[i - 1], pts[i], u), dir: norm(sub(pts[i], pts[i - 1])) };
    }
    acc += seg;
  }
  return { p: pts[pts.length - 1], dir: [0, 0, 1] };
}

/** 把一串控制点加密成平滑曲线（Catmull-Rom，每段 n 个点）。 */
export function smoothPath(pts: Vec3[], n = 8): Vec3[] {
  if (pts.length < 3) return pts.slice();
  const out: Vec3[] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    for (let k = 0; k < n; k++) out.push(catmull(p0, pts[i], pts[i + 1], p3, k / n));
  }
  out.push(pts[pts.length - 1]);
  return out;
}

export const v2to3 = (p: Vec2 | Vec3): Vec3 => (p.length === 2 ? [p[0], 0, p[1]] : [p[0], p[1], p[2]]);
