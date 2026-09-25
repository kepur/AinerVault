/**
 * 3D 导演台的数据模型与数学。
 *
 * 坐标：Y 向上，地面是 XZ 平面，单位米。默认机位在 +Z 一侧朝 -Z 看，
 * 所以演员站在原点附近、脸朝 +Z 就是面对镜头。
 *
 * 一镜 = 演员站位（地面坐标＋朝向＋身高）＋ 一台相机的运动：起幅、落幅两个
 * 关键帧（位置、注视点、焦段、滚转、焦点），中间走哪条轨迹（直线／环绕弧线／
 * 抛物线摇臂／贝塞尔），加缓动、手持抖动与光圈。
 *
 * 这份数据要驱动出图，不只是给人看：
 *   起幅相机 → 把演员投影到画面上 → 屏幕空间站位 → 分区身份出首帧（projectActors）
 *   起幅取景 → 景别（framingOf）→ 首帧提示词里的景别，不再和分镜的字面打架
 *   整段运动 → 结构化运镜＋一句英文描述 → 视频的 camera 参数与尾帧的镜头变化（describe）
 */
import * as THREE from "three";
import type { MoveKind } from "./moves";

export type { MoveDef, MoveKind } from "./moves";
export { MOVE_GROUPS, MOVES, moveLabel } from "./moves";

export type Vec3 = [number, number, number];

export interface Actor {
  entity_id: string;
  name: string;
  /** 地面坐标 x、z（米） */
  pos: [number, number];
  /** 朝向（度）：0 = 面向 +Z（面对默认机位），90 = 面向 +X（画面右） */
  yaw: number;
  /** 身高（米） */
  height: number;
  /** 胖瘦：1 = 标准肩宽 */
  girth: number;
  face_url?: string;
  prompt?: string;
}

export type PathKind = "linear" | "arc" | "parabola" | "bezier";
export type Easing = "linear" | "ease_in" | "ease_out" | "ease_in_out";
export interface CamPose {
  pos: Vec3;
  target: Vec3;
  /** 焦段（mm，全画幅 36mm 宽） */
  lens: number;
  /** 滚转（度）：正 = 画面顺时针倾斜。不为 0 就是荷兰角 */
  roll?: number;
  /** 焦点落在谁身上（entity_id）。起幅落幅不同 = 移焦 */
  focus?: string | null;
}

export interface Rig {
  move: MoveKind;
  start: CamPose;
  end: CamPose;
  path: PathKind;
  /** 环绕：绕 center 扫过的角度（度）。正 = 相机往自己左边绕 */
  sweep: number;
  center: Vec3;
  /** 抛物线：中点额外抬高多少米（负数 = 下探） */
  peak: number;
  /** 贝塞尔：二次控制点 */
  control: Vec3;
  /** 手持抖动 0–1 */
  shake: number;
  easing: Easing;
  duration_ms: number;
  /** 光圈 f 值：越小景深越浅 */
  aperture?: number;
}

export interface Stage3D {
  version: 1;
  aspect: number;
  actors: Actor[];
  rig: Rig;
}

/** 与服务端 blocking.Figure 同构：画面比例坐标。 */
export interface ScreenFigure {
  entity_id: string;
  name: string;
  x: number;
  top: number;
  bottom: number;
  width: number;
}

// ── 向量小工具 ────────────────────────────────────────────
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const lerp3 = (a: Vec3, b: Vec3, t: number): Vec3 =>
  [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
export const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const len = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);
export const norm = (a: Vec3): Vec3 => { const l = len(a) || 1; return scale(a, 1 / l); };
export const rad = (d: number) => (d * Math.PI) / 180;
export const deg = (r: number) => (r * 180) / Math.PI;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const clamp01 = (t: number) => clamp(t, 0, 1);

/** 全画幅 36mm 宽：焦段 → 垂直视场角（度），three.js 的 fov 是垂直的。 */
export function vfov(lens: number, aspect: number) {
  const h = 2 * Math.atan(18 / lens);
  return deg(2 * Math.atan(Math.tan(h / 2) / aspect));
}
export const hfov = (lens: number) => deg(2 * Math.atan(18 / lens));

export function ease(t: number, e: Easing) {
  t = clamp01(t);
  switch (e) {
    case "ease_in": return t * t;
    case "ease_out": return 1 - (1 - t) * (1 - t);
    case "ease_in_out": return t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
    default: return t;
  }
}

/** 环绕弧线：落幅位置由起幅绕 center 转 sweep 度得到，半径与高度按落幅。 */
export function arcPoint(rig: Rig, u: number): Vec3 {
  const s = sub(rig.start.pos, rig.center);
  const e = sub(rig.end.pos, rig.center);
  const r0 = Math.hypot(s[0], s[2]);
  const r1 = Math.hypot(e[0], e[2]);
  // atan2(z, x)：角度增大 = 从 +X 转向 +Z。机位在 +Z 朝 -Z 看时，
  // 相机的左手是 -X，往左绕 = 角度增大，所以 sweep 为正就是往左绕
  const a = Math.atan2(s[2], s[0]) + rad(rig.sweep) * u;
  const r = lerp(r0, r1, u);
  return [rig.center[0] + r * Math.cos(a), lerp(rig.start.pos[1], rig.end.pos[1], u),
          rig.center[2] + r * Math.sin(a)];
}

/** 改了扫角之后，让落幅位置落回弧线终点（半径、高度沿用当前落幅）。 */
export function snapArcEnd(rig: Rig): Rig {
  return { ...rig, end: { ...rig.end, pos: arcPoint(rig, 1) } };
}

/** 在落幅被拖动后反推扫角：保留原来的绕行方向，允许超过 180°。 */
export function sweepFromEnd(rig: Rig): number {
  const s = sub(rig.start.pos, rig.center);
  const e = sub(rig.end.pos, rig.center);
  let d = deg(Math.atan2(e[2], e[0]) - Math.atan2(s[2], s[0]));
  while (d > 180) d -= 360;
  while (d < -180) d += 360;
  // 原来是大角度同方向绕：把 ±180 附近的跳变接回去
  if (Math.sign(d) !== Math.sign(rig.sweep) && Math.abs(rig.sweep) > 150) d += Math.sign(rig.sweep) * 360;
  return d;
}

function shakeAt(u: number, amount: number): Vec3 {
  if (amount <= 0) return [0, 0, 0];
  const t = u * 9.7;
  const k = 0.06 * amount;
  return [k * (Math.sin(t * 3.1) + 0.5 * Math.sin(t * 7.3)),
          k * 0.7 * (Math.sin(t * 4.3 + 1.3) + 0.4 * Math.sin(t * 9.1)),
          k * 0.5 * Math.sin(t * 2.2 + 0.7)];
}

/** 轨迹上 u（已缓动）处的机位，不含抖动。 */
export function pathPoint(rig: Rig, u: number): Vec3 {
  switch (rig.path) {
    case "arc":
      return arcPoint(rig, u);
    case "parabola": {
      const p = lerp3(rig.start.pos, rig.end.pos, u);
      p[1] += rig.peak * 4 * u * (1 - u);
      return p;
    }
    case "bezier":
      return lerp3(lerp3(rig.start.pos, rig.control, u), lerp3(rig.control, rig.end.pos, u), u);
    default:
      return lerp3(rig.start.pos, rig.end.pos, u);
  }
}

/** 单位向量球面插值。 */
function slerp(a: Vec3, b: Vec3, u: number): Vec3 {
  const c = clamp(dot(a, b), -1, 1);
  const w = Math.acos(c);
  if (w < 1e-4) return norm(lerp3(a, b, u));
  const s = Math.sin(w);
  return add(scale(a, Math.sin((1 - u) * w) / s), scale(b, Math.sin(u * w) / s));
}

/**
 * 注视点在 u 处的位置。机位不动的运镜（摇、甩、变焦、旋转）按视线方向的角度
 * 均匀转过去 —— 注视点走直线的话走的是弦，镜头的角速度两头慢中间快，
 * 视线还会在中段离主体近一截。机位在动的（推拉、环绕、摇臂）注视点照直线走。
 */
function aimAt(rig: Rig, u: number, pos: Vec3): Vec3 {
  const fixed = rig.path === "linear" && len(sub(rig.start.pos, rig.end.pos)) < 1e-4;
  if (!fixed) return lerp3(rig.start.target, rig.end.target, u);
  const d0 = sub(rig.start.target, rig.start.pos);
  const d1 = sub(rig.end.target, rig.end.pos);
  return add(pos, scale(slerp(norm(d0), norm(d1), u), lerp(len(d0), len(d1), u)));
}

/** 运镜在时刻 t（0–1）的相机姿态。 */
export function sample(rig: Rig, t: number): CamPose {
  const u = ease(t, rig.easing);
  const jitter = shakeAt(u, rig.shake);
  const at = pathPoint(rig, u);
  return {
    pos: add(at, jitter),
    target: add(aimAt(rig, u, at), scale(jitter, 0.4)),
    lens: lerp(rig.start.lens, rig.end.lens, u),
    roll: lerp(rig.start.roll ?? 0, rig.end.roll ?? 0, u) + jitter[0] * 20 * rig.shake,
    // 移焦在中段完成：前半程对着起幅的人，后半程对着落幅的人
    focus: u < 0.5 ? rig.start.focus : rig.end.focus,
  };
}

/** 轨迹采样点（俯视图、侧视图与 3D 视图画线用）。 */
export function trail(rig: Rig, n = 64): Vec3[] {
  const out: Vec3[] = [];
  for (let i = 0; i <= n; i++) out.push(pathPoint(rig, i / n));
  return out;
}

/** 相机的前、右方向（水平面内）。 */
export function basis(p: CamPose) {
  const f = norm(sub(p.target, p.pos));
  const right = norm([-f[2], 0, f[0]]);   // 水平右手（f × up）
  const flat = norm([f[0], 0, f[2]]);
  return { forward: f, right, flat };
}

/** 俯仰角（度）：正 = 相机在注视点之上、往下看。 */
export function pitchOf(p: CamPose) {
  const d = sub(p.pos, p.target);
  return deg(Math.atan2(d[1], Math.hypot(d[0], d[2])));
}

// ── 运镜预设 ──────────────────────────────────────────────

/**
 * 按预设改写落幅与轨迹。起幅保持不动 —— 导演先定起幅构图，再选怎么动。
 * 落幅的焦点（移焦）不属于运镜预设，换预设时保留。
 */
export function applyMove(rig: Rig, kind: MoveKind, subject: Vec3): Rig {
  const out = presetMove(rig, kind, subject);
  return { ...out, end: { ...out.end, focus: rig.end.focus ?? out.end.focus } };
}

function presetMove(rig: Rig, kind: MoveKind, subject: Vec3): Rig {
  const s = rig.start;
  const { forward, right, flat } = basis(s);
  const dist = len(sub(s.target, s.pos));
  const base: Rig = {
    ...rig, move: kind, path: "linear", shake: 0, peak: 0, sweep: 0,
    center: [subject[0], 0, subject[2]], easing: kind === "handheld" ? "linear" : "ease_in_out",
    end: { ...s, pos: [...s.pos] as Vec3, target: [...s.target] as Vec3 },
  };
  const yawTarget = (d: number): Vec3 => {
    // 以机位为轴水平转 d 度（正 = 向右）
    const v = sub(s.target, s.pos);
    const a = rad(d);
    const x = v[0] * Math.cos(a) - v[2] * Math.sin(a);
    const z = v[0] * Math.sin(a) + v[2] * Math.cos(a);
    return [s.pos[0] + x, s.target[1], s.pos[2] + z];
  };
  switch (kind) {
    case "static":
      return base;
    case "push_in":
      return { ...base, end: { ...s, pos: add(s.pos, scale(forward, dist * 0.45)) } };
    case "pull_out":
      return { ...base, end: { ...s, pos: add(s.pos, scale(forward, -dist * 0.6)) } };
    case "dolly_zoom": {
      // 推到 55% 的距离，焦段按距离同比缩短：主体在画面里的大小 ∝ 焦段 / 距离，保持不变
      const k = 0.55;
      const lens = Math.max(14, s.lens * k);
      const d1 = dist * (lens / s.lens);
      return { ...base, end: { ...s, pos: add(s.target, scale(forward, -d1)), lens } };
    }
    case "pan_left":
      return { ...base, end: { ...s, target: yawTarget(-25) } };
    case "pan_right":
      return { ...base, end: { ...s, target: yawTarget(25) } };
    case "whip_pan":
      return { ...base, easing: "ease_in_out", duration_ms: Math.min(rig.duration_ms, 900),
        end: { ...s, target: yawTarget(75) } };
    case "tilt_up":
      return { ...base, end: { ...s, target: add(s.target, [0, dist * 0.35, 0]) } };
    case "tilt_down":
      return { ...base, end: { ...s, target: add(s.target, [0, -dist * 0.3, 0]) } };
    case "truck_left":
      return { ...base, end: { ...s, pos: add(s.pos, scale(right, -1.6)), target: add(s.target, scale(right, -1.6)) } };
    case "truck_right":
      return { ...base, end: { ...s, pos: add(s.pos, scale(right, 1.6)), target: add(s.target, scale(right, 1.6)) } };
    case "crane_up":
      return { ...base, end: { ...s, pos: add(s.pos, [0, 1.6, 0]) } };
    case "crane_down":
      return { ...base, end: { ...s, pos: add(s.pos, [0, -Math.min(1.0, s.pos[1] - 0.4), 0]) } };
    case "orbit_left":
    case "orbit_right": {
      const r: Rig = { ...base, path: "arc", sweep: kind === "orbit_left" ? 60 : -60,
        center: [subject[0], 0, subject[2]], end: { ...s, target: subject } };
      return snapArcEnd({ ...r, start: { ...s, target: subject } });
    }
    case "jib_arc":
      return { ...base, path: "parabola", peak: 1.4,
        end: { ...s, pos: add(add(s.pos, scale(forward, dist * 0.35)), scale(right, 1.2)) } };
    case "aerial":
      return { ...base, path: "parabola", peak: 0.8, easing: "ease_in_out",
        end: { ...s, pos: add(add(s.pos, scale(flat, -dist * 0.9)), [0, 5.5, 0]), lens: Math.max(18, s.lens * 0.8) } };
    case "zoom_in":
      return { ...base, end: { ...s, lens: Math.min(135, s.lens * 2) } };
    case "zoom_out":
      return { ...base, end: { ...s, lens: Math.max(14, s.lens / 2) } };
    case "roll":
      return { ...base, end: { ...s, roll: (s.roll ?? 0) + 25 } };
    case "handheld":
      return { ...base, shake: 0.5, end: { ...s, pos: add(s.pos, scale(forward, dist * 0.08)) } };
    default:
      return base;
  }
}

// ── 景别、角度、过肩 ─────────────────────────────────────

export type ShotSize = "ecu" | "cu" | "ms" | "fs" | "ws" | "els";
export const SIZES: { kind: ShotSize; label: string; en: string }[] = [
  { kind: "els", label: "大远景", en: "extreme long shot" },
  { kind: "ws", label: "远景", en: "wide shot" },
  { kind: "fs", label: "全景", en: "full shot" },
  { kind: "ms", label: "中景", en: "medium shot" },
  { kind: "cu", label: "特写", en: "close-up" },
  { kind: "ecu", label: "大特写", en: "extreme close-up" },
];
export const sizeLabel = (k: string | null | undefined) => SIZES.find(s => s.kind === k)?.label ?? "—";

/** 景别 → 画面要装下的高度（米，以 1.72m 的人计）。 */
const FRAME_H: Record<ShotSize, number> = { ecu: 0.2, cu: 0.45, ms: 1.05, fs: 2.25, ws: 5.5, els: 16 };

/**
 * 按景别取景：保持当前的方位与俯仰，只改距离与注视点高度。
 * 单人景别（特写到中景）对准 focus 这个人，眼睛落在上三分线；
 * 群像景别（全景以上）对准全体，宽度也要装得下。
 */
export function frameShot(p: CamPose, size: ShotSize, focus: Actor | null, actors: Actor[], aspect: number): CamPose {
  const group = size === "fs" || size === "ws" || size === "els" || !focus;
  const who = group ? actors : [focus!];
  if (!who.length) return p;
  const c = centroid(who);
  const h = who.reduce((s, a) => s + a.height, 0) / who.length;
  const k = h / 1.72;
  const H = FRAME_H[size] * (size === "ws" || size === "els" ? 1 : k);
  const eye = h * 0.93;
  const ty = { ecu: eye - 0.02, cu: eye - H / 6, ms: eye - H / 6, fs: h * 0.5, ws: h * 0.62, els: 1.5 }[size];
  const tanHalf = Math.tan(rad(vfov(p.lens, aspect)) / 2);
  let D = H / (2 * tanHalf);
  if (group && who.length > 1) {
    // 横向也要装得下：人群在相机右方向上的跨度＋两侧各留半米
    const { right } = basis(p);
    const xs = who.map(a => a.pos[0] * right[0] + a.pos[1] * right[2]);
    const spread = Math.max(...xs) - Math.min(...xs) + 1.2;
    D = Math.max(D, spread / (2 * tanHalf * aspect));
  }
  const d = sub(p.pos, p.target);
  const az = Math.atan2(d[2], d[0]);
  const el = Math.atan2(d[1], Math.hypot(d[0], d[2]));
  const target: Vec3 = [c[0], ty, c[2]];
  const pos: Vec3 = [c[0] + D * Math.cos(el) * Math.cos(az), Math.max(0.1, ty + D * Math.sin(el)),
                     c[2] + D * Math.cos(el) * Math.sin(az)];
  return { ...p, pos, target };
}

export type Angle = "eye" | "high" | "low" | "bird" | "worm";
export const ANGLES: { kind: Angle; label: string; deg: number }[] = [
  { kind: "eye", label: "平视", deg: 0 },
  { kind: "high", label: "俯拍", deg: 25 },
  { kind: "low", label: "仰拍", deg: -18 },
  { kind: "bird", label: "鸟瞰", deg: 78 },
  { kind: "worm", label: "虫视", deg: -40 },
];

/** 机位角度：绕注视点在竖直面内转到给定仰角，距离与方位不变。 */
export function angleShot(p: CamPose, elevationDeg: number): CamPose {
  const d = sub(p.pos, p.target);
  const r = len(d);
  const az = Math.atan2(d[2], d[0]);
  const el = rad(elevationDeg);
  let pos: Vec3 = [p.target[0] + r * Math.cos(el) * Math.cos(az), p.target[1] + r * Math.sin(el),
                   p.target[2] + r * Math.cos(el) * Math.sin(az)];
  if (pos[1] < 0.08) {
    // 贴地了：机位压到地面，距离缩短以保持仰角
    const y = 0.08;
    const horiz = (p.target[1] - y) / Math.tan(-el);
    pos = [p.target[0] + horiz * Math.cos(az), y, p.target[2] + horiz * Math.sin(az)];
  }
  return { ...p, pos };
}

/** 过肩：相机在 b 身后偏一侧，越过 b 的肩膀看 a 的脸。side 决定从哪边肩膀 */
export function overShoulder(p: CamPose, a: Actor, b: Actor, side: 1 | -1): CamPose {
  const dir = norm([a.pos[0] - b.pos[0], 0, a.pos[1] - b.pos[1]]);
  const perp: Vec3 = [-dir[2], 0, dir[0]];
  const pos: Vec3 = add(add([b.pos[0], b.height * 0.93, b.pos[1]], scale(dir, -0.8)), scale(perp, 0.42 * side));
  return { ...p, pos, target: [a.pos[0], a.height * 0.9, a.pos[1]], lens: Math.max(p.lens, 50) };
}

/** 180° 轴线：点在 a→b 连线的哪一侧（XZ 平面）。 */
export function axisSide(a: Actor, b: Actor, p: Vec3) {
  const ab = [b.pos[0] - a.pos[0], b.pos[1] - a.pos[1]];
  const ap = [p[0] - a.pos[0], p[2] - a.pos[1]];
  return Math.sign(ab[0] * ap[1] - ab[1] * ap[0]);
}

/** 运镜途中有没有越过两位主角之间的轴线。 */
export function crossesAxis(rig: Rig, a: Actor, b: Actor) {
  const s0 = axisSide(a, b, rig.start.pos);
  return trail(rig, 48).some(p => axisSide(a, b, p) !== s0 && axisSide(a, b, p) !== 0);
}

/** 让演员看向某点：朝向向量 (sin yaw, cos yaw)。 */
export const yawToward = (a: Actor, x: number, z: number) => deg(Math.atan2(x - a.pos[0], z - a.pos[1]));

// ── 描述：交给视频模型与尾帧的一句英文 ────────────────────

function sideWord(f: ScreenFigure | undefined) {
  if (!f) return "the subject";
  return f.x < 0.38 ? "the person on the left" : f.x > 0.62 ? "the person on the right" : "the person in the center";
}

/** 给视频模型和尾帧用的一句英文：这一镜的相机怎么动。 */
export function describe(rig: Rig, ctx?: { actors: Actor[]; aspect: number }): string {
  const dur = (rig.duration_ms / 1000).toFixed(1);
  const d0 = len(sub(rig.start.target, rig.start.pos));
  const d1 = len(sub(rig.end.target, rig.end.pos));
  const pace = rig.easing === "ease_in_out" ? "smoothly" : rig.easing === "linear" ? "at a steady pace" : "";
  const l0 = Math.round(rig.start.lens);
  const l1 = Math.round(rig.end.lens);
  const lens = l0 === l1 ? `${l0}mm lens` : `lens changes from ${l0}mm to ${l1}mm`;
  const r0 = rig.start.roll ?? 0;
  const r1 = rig.end.roll ?? 0;
  const words: Record<MoveKind, string> = {
    static: "Static locked-off camera, no camera movement",
    handheld: "Handheld camera with subtle natural shake, drifting slightly forward",
    push_in: `Camera pushes in ${pace}, from ${d0.toFixed(1)} m to ${d1.toFixed(1)} m from the subject`,
    pull_out: `Camera pulls back ${pace}, from ${d0.toFixed(1)} m to ${d1.toFixed(1)} m from the subject`,
    dolly_zoom: `Dolly zoom (vertigo effect): the camera dollies in while zooming out from ${l0}mm to ${l1}mm, the subject keeps the same size while the background stretches away`,
    pan_left: `Camera pans left ${pace} from a fixed position`,
    pan_right: `Camera pans right ${pace} from a fixed position`,
    whip_pan: "Fast whip pan to the right with strong motion blur",
    tilt_up: `Camera tilts up ${pace} from a fixed position`,
    tilt_down: `Camera tilts down ${pace} from a fixed position`,
    truck_left: `Camera trucks left on a dolly track ${pace}, keeping the same distance`,
    truck_right: `Camera trucks right on a dolly track ${pace}, keeping the same distance`,
    crane_up: `Camera cranes straight up ${pace} by ${(rig.end.pos[1] - rig.start.pos[1]).toFixed(1)} m`,
    crane_down: `Camera cranes down ${pace} by ${(rig.start.pos[1] - rig.end.pos[1]).toFixed(1)} m`,
    orbit_left: `Camera orbits ${Math.abs(Math.round(rig.sweep))} degrees to the left around the subject in a smooth arc`,
    orbit_right: `Camera orbits ${Math.abs(Math.round(rig.sweep))} degrees to the right around the subject in a smooth arc`,
    jib_arc: `Sweeping jib move: the camera rises ${rig.peak.toFixed(1)} m in a parabolic arc and settles on the new framing`,
    aerial: `Aerial drone shot: the camera rises ${(rig.end.pos[1] - rig.start.pos[1]).toFixed(1)} m and pulls back to reveal the whole scene`,
    zoom_in: `Camera zooms in ${pace} without moving`,
    zoom_out: `Camera zooms out ${pace} without moving`,
    roll: `Camera rolls ${Math.abs(Math.round(r1 - r0))} degrees ${r1 > r0 ? "clockwise" : "counter-clockwise"} around the lens axis`,
    custom: `Camera moves along a ${rig.path === "arc" ? `circular arc (${Math.abs(Math.round(rig.sweep))} degrees)` : rig.path === "parabola" ? "parabolic crane arc" : rig.path === "bezier" ? "curved path" : "straight path"}`,
  };
  const parts = [words[rig.move]];
  if (rig.shake > 0 && rig.move !== "handheld") parts.push("slight handheld shake");
  const pitch = pitchOf(rig.start);
  if (pitch > 55) parts.push("overhead bird's-eye view");
  else if (pitch > 12) parts.push("high angle looking down");
  else if (pitch < -25) parts.push("extreme low angle (worm's-eye view)");
  else if (pitch < -8) parts.push("low angle looking up");
  if (rig.move !== "roll" && Math.abs(r0) >= 5 && Math.abs(r1 - r0) < 5) parts.push(`Dutch angle, frame tilted ${Math.abs(Math.round(r0))} degrees`);
  if (rig.move !== "roll" && Math.abs(r1 - r0) >= 5) parts.push(`camera rolls ${Math.abs(Math.round(r1 - r0))} degrees`);
  const f = rig.aperture ?? 4;
  if (f <= 2.8) parts.push(`shallow depth of field (f/${f})`);
  else if (f >= 8) parts.push("deep focus, everything sharp");
  if (ctx && (rig.start.focus || rig.end.focus)) {
    const figs0 = projectActors(ctx.actors, rig.start, ctx.aspect);
    const figs1 = projectActors(ctx.actors, rig.end, ctx.aspect);
    const at0 = figs0.find(x => x.entity_id === rig.start.focus);
    const at1 = figs1.find(x => x.entity_id === rig.end.focus);
    if (rig.start.focus) parts.push(`focus on ${sideWord(at0)}`);
    if (rig.end.focus && rig.end.focus !== rig.start.focus) parts.push(`focus racks to ${sideWord(at1)}`);
  }
  return `${parts.join(", ")}; ${lens}; over ${dur} seconds.`;
}

/** 本机工作台认得的运镜词（cap_api._CAMERA_WORDS）。认不得的只走英文描述。 */
export function videoMove(rig: Rig): string | null {
  const map: Partial<Record<MoveKind, string>> = {
    static: "static", push_in: "push_in", pull_out: "pull_out", pan_left: "pan_left", pan_right: "pan_right",
    tilt_up: "tilt_up", tilt_down: "tilt_down", orbit_left: "orbit_left", orbit_right: "orbit_right",
    handheld: "handheld", zoom_in: "push_in", zoom_out: "pull_out", whip_pan: "pan_right",
  };
  return map[rig.move] ?? null;
}

// ── 投影：起幅相机下，演员在画面里站在哪 ─────────────────

export function makeCamera(p: CamPose, aspect: number): THREE.PerspectiveCamera {
  const cam = new THREE.PerspectiveCamera(vfov(p.lens, aspect), aspect, 0.05, 500);
  cam.position.set(...p.pos);
  cam.lookAt(new THREE.Vector3(...p.target));
  // 正 roll = 画面顺时针：相机本身逆时针转
  if (p.roll) cam.rotateZ(rad(p.roll));
  cam.updateMatrixWorld(true);
  cam.updateProjectionMatrix();
  return cam;
}

const SHOULDER = 0.27; // 肩宽 ≈ 身高 × 0.27，与服务端人偶一致

/** 把演员投影成屏幕空间人偶。站到相机后面或完全出画的不算在画面里。坐标不截断。 */
export function projectActors(actors: Actor[], p: CamPose, aspect: number): ScreenFigure[] {
  const cam = makeCamera(p, aspect);
  const camDir = new THREE.Vector3();
  cam.getWorldDirection(camDir);
  const right = new THREE.Vector3(-camDir.z, 0, camDir.x).normalize();
  const proj = (v: THREE.Vector3) => { const q = v.clone().project(cam); return { x: (q.x + 1) / 2, y: (1 - q.y) / 2 }; };
  const out: ScreenFigure[] = [];
  for (const a of actors) {
    const feet = new THREE.Vector3(a.pos[0], 0, a.pos[1]);
    const head3 = new THREE.Vector3(a.pos[0], a.height, a.pos[1]);
    if (feet.clone().sub(cam.position).dot(camDir) <= 0.2 || head3.clone().sub(cam.position).dot(camDir) <= 0.2) continue; // 在相机后面
    const half = (a.height * SHOULDER * a.girth) / 2;
    const head = proj(head3);
    const foot = proj(feet);
    const l = proj(new THREE.Vector3(a.pos[0], a.height * 0.7, a.pos[1]).addScaledVector(right, -half));
    const r = proj(new THREE.Vector3(a.pos[0], a.height * 0.7, a.pos[1]).addScaledVector(right, half));
    const x = (head.x + foot.x) / 2;
    const width = Math.abs(r.x - l.x);
    const top = Math.min(head.y, foot.y);
    const bottom = Math.max(head.y, foot.y);
    if (x + width / 2 < 0 || x - width / 2 > 1 || bottom < 0 || top > 1) continue;   // 完全出画
    out.push({ entity_id: a.entity_id, name: a.name, x, top, bottom, width });
  }
  return out;
}

/** 交给服务端前按它的取值范围收一下（FigureIn：x∈[0,1]、top∈[-0.5,1.5]、bottom∈[0,3]、width∈(0,1]）。 */
export function forServer(figs: ScreenFigure[]): ScreenFigure[] {
  return figs.map(f => {
    const top = clamp(f.top, -0.5, 1.4);
    return { ...f, x: clamp(f.x, 0, 1), top, bottom: clamp(Math.max(f.bottom, top + 0.02), 0.02, 3),
             width: clamp(f.width, 0.005, 1) };
  });
}

/** 起幅画面的景别：看画面里最大的那个人露出多少身体。 */
export function framingOf(figs: ScreenFigure[]): ShotSize | null {
  if (!figs.length) return null;
  const f = figs.reduce((a, b) => (b.bottom - b.top > a.bottom - a.top ? b : a));
  const h = f.bottom - f.top;
  if (f.bottom <= 1.03) return h < 0.12 ? "els" : h < 0.42 ? "ws" : "fs";
  const vis = (1 - Math.max(0, f.top)) / h;   // 头顶到画框下沿露出的比例
  if (vis < 0.13) return "ecu";
  if (vis < 0.34) return "cu";
  return "ms";
}

/** 默认机位：35mm、机位高 1.5m、离场景中心 6.5m，平视略俯。 */
export const DEFAULT_POSE: CamPose = { pos: [0, 1.5, 6.5], target: [0, 1.15, 0], lens: 35, roll: 0, focus: null };

const FACING_YAW: Record<string, number> = {
  to_camera: 0, away: 180, profile_left: -90, profile_right: 90, three_quarter: 30,
};

type FigureIn = {
  entity_id: string; name: string; x: number; top: number; bottom: number; width: number;
  facing?: string; face_url?: string; prompt?: string; build?: number[];
};

/**
 * 反解起幅机位：服务端的人偶是按景别在画面里排的（地面线＋缩放），没有真相机。
 * 取画面里最大的那个人，他的头顶 t、脚底 b（中景可 >1）和身高 h 定出一台
 * 平视的 35mm 相机 —— 机位高 H 满足 (b−½)/(½−t) = H/(h−H)，距离由脚底那条射线定。
 * 这样第一次打开导演台时，起幅画面和自动摆位的构图一致（头顶、脚底都对得上），
 * 不会把「脚在画内的远景」看成「腿出画的中景」。
 */
export function solveStart(figs: FigureIn[], aspect: number): CamPose {
  const main = figs.reduce<FigureIn | null>((a, b) => (!a || b.bottom - b.top > a.bottom - a.top ? b : a), null);
  if (!main || main.bottom - main.top < 0.05 || main.bottom <= 0.55) return { ...DEFAULT_POSE };
  const tanHalf = Math.tan(rad(vfov(DEFAULT_POSE.lens, aspect)) / 2);
  const h = 1.72 * (main.build?.[0] ?? 1);
  const H = clamp(h * (main.bottom - 0.5) / (main.bottom - main.top), 0.3, 2.4);
  const d = H / ((main.bottom - 0.5) * 2 * tanHalf);
  return { pos: [0, H, d], target: [0, H, 0], lens: DEFAULT_POSE.lens, roll: 0, focus: null };
}

/**
 * 从屏幕空间站位反推 3D 站位（在 solveStart 那台平视相机下）：脚底射线落地定纵深，
 * 身体中线定左右，头顶定身高。脚在画面上半（远处、或排版异常）时退回按人高反推纵深。
 */
export function actorsFromFigures(figs: FigureIn[], aspect: number, pose: CamPose = solveStart(figs, aspect)): Actor[] {
  const tanHalf = Math.tan(rad(vfov(pose.lens, aspect)) / 2);
  const { flat, right } = basis(pose);
  const H = pose.pos[1];
  return figs.map(f => {
    const nominal = 1.72 * (f.build?.[0] ?? 1);
    let depth: number;
    let height = nominal;
    if (f.bottom > 0.55) {
      depth = H / ((f.bottom - 0.5) * 2 * tanHalf);
      height = clamp(H + (0.5 - f.top) * 2 * tanHalf * depth, 1.0, 2.2);
    } else {
      depth = nominal / (2 * tanHalf * Math.max(0.03, f.bottom - f.top));
    }
    const lateral = (f.x * 2 - 1) * depth * tanHalf * aspect;
    const at = add(add([pose.pos[0], 0, pose.pos[2]], scale(flat, depth)), scale(right, lateral));
    return {
      entity_id: f.entity_id, name: f.name,
      pos: [at[0], at[2]] as [number, number],
      yaw: FACING_YAW[f.facing ?? "to_camera"] ?? 0,
      height, girth: f.build?.[1] ?? 1,
      face_url: f.face_url, prompt: f.prompt,
    };
  });
}

export function centroid(actors: Actor[]): Vec3 {
  if (!actors.length) return [0, 1.2, 0];
  const x = actors.reduce((s, a) => s + a.pos[0], 0) / actors.length;
  const z = actors.reduce((s, a) => s + a.pos[1], 0) / actors.length;
  const h = actors.reduce((s, a) => s + a.height, 0) / actors.length;
  return [x, h * 0.65, z];
}

/** 分镜里的运镜词 → 预设（分镜只给了粗类：static/pan/handheld/push_in/orbit）。 */
const STORYBOARD_MOVE: Record<string, MoveKind> = {
  static: "static", pan: "pan_right", handheld: "handheld", push_in: "push_in", pull_out: "pull_out",
  orbit: "orbit_left", tilt: "tilt_up", zoom: "zoom_in", crane: "crane_up", truck: "truck_right",
};

/**
 * 第一次打开导演台时的运镜：起幅就是默认机位（自动摆位反推用的同一台相机，
 * 起幅画面与自动摆位的构图一致），运镜按分镜写的那一类预设，时长按镜头时长。
 */
export function newRig(actors: Actor[], storyboardMove?: string, durationMs?: number,
                       start: CamPose = { ...DEFAULT_POSE }): Rig {
  const subject = centroid(actors);
  const rig: Rig = {
    move: "static", start, end: { ...start }, path: "linear", sweep: 0,
    center: [subject[0], 0, subject[2]], peak: 0, control: [start.pos[0] + 2, start.pos[1], start.pos[2] - 2],
    shake: 0, easing: "ease_in_out", duration_ms: clamp(durationMs || 3000, 500, 10000), aperture: 4,
  };
  const kind = STORYBOARD_MOVE[storyboardMove ?? ""] ?? "static";
  if (kind === "static") return rig;
  const moved = applyMove(rig, kind, subject);
  // 环绕会把起幅注视点改到人群中心；首开要保住与自动摆位一致的起幅，只取落幅与轨迹
  return kind === "orbit_left" ? snapArcEnd({ ...moved, start }) : { ...moved, start };
}

/** 装下全部演员与机位的包围盒（俯视、侧视「适配」用）。 */
export function extent(stage: Stage3D) {
  const pts: Vec3[] = [
    ...stage.actors.map(a => [a.pos[0], a.height, a.pos[1]] as Vec3),
    stage.rig.start.pos, stage.rig.end.pos, stage.rig.start.target, ...trail(stage.rig, 16),
  ];
  const lo: Vec3 = [Infinity, Infinity, Infinity];
  const hi: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const p of pts) for (let i = 0; i < 3; i++) { lo[i] = Math.min(lo[i], p[i]); hi[i] = Math.max(hi[i], p[i]); }
  return { center: lerp3(lo, hi, 0.5), size: sub(hi, lo) };
}
