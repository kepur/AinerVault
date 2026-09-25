/**
 * 机位运镜预设：一个名字 → 一串关键帧。
 *
 * 覆盖 LibTV 导演台的 24 个（背跟、正面跟、侧跟推近、顶拍转跟随、大远景到特写、
 * 螺旋上升、环绕两周…）、运镜广场的常用项（前推后移、上下摇、左右移、盘旋、
 * 无人机、高空航拍、滚筒旋转、柯克变焦…）和我们导演台原有的。
 *
 * 预设在场景脚本跑完之后才展开（运行时 finish 里），所以能跟住脚本后面才加了动画的目标。
 * 跟拍类用相对目标的关键帧（follow/orbit），目标跑，机位跟着跑。
 */
import type { CamKey, Vec3 } from "./types";
import { add, forwardOf, rightOf, scale } from "./math";

export interface PresetCtx {
  target: string | null;
  start: number;
  duration: number;
  /** 1 = 目标右侧，-1 = 左侧 */
  side: 1 | -1;
  lens: number;
  /** 目标的特征尺寸（人＝身高，车＝车长） */
  size: number;
  /** 瞄准高度（离目标脚底） */
  aim: number;
  /** 起始角度（度，相对目标正面） */
  angle: number;
  distance?: number;
  height?: number;
  posAt(t: number): Vec3;
  yawAt(t: number): number;
}

export interface PresetResult {
  keys: CamKey[];
  shake?: number;
  ease?: "linear" | "smooth";
  path?: "linear" | "curve";
}

export interface CameraPreset {
  id: string;
  zh: string;
  group: "固定" | "推拉" | "摇" | "移" | "跟拍" | "环绕" | "航拍" | "特殊";
  doc: string;
  build(c: PresetCtx): PresetResult;
}

/** 景别 → 35mm 下离目标的水平距离（以 1.75m 的人为 1）。 */
export const SHOT_DIST: Record<string, number> = { els: 30, ws: 11, fs: 5.2, mls: 3.6, ms: 2.8, mcu: 1.9, cu: 1.3, ecu: 0.7 };

export function shotDistance(size: string, c: { size: number; lens: number }, k = 1) {
  const base = SHOT_DIST[size] ?? 2.8;
  return base * Math.max(1, c.size / 1.75) * (c.lens / 35) * k;
}

// ── 关键帧小工具 ─────────────────────────────────────────

const at = (c: PresetCtx, u: number) => c.start + c.duration * u;

/** 绕目标的关键帧（有目标）或绕点的世界坐标关键帧（没目标）。 */
function orb(c: PresetCtx, u: number, angle: number, radius: number, height: number, extra: Partial<CamKey> = {}): CamKey {
  const t = at(c, u);
  if (c.target) return { t, orbit: c.target, angle, radius, height, ...extra };
  const p = c.posAt(t);
  const a = (angle * Math.PI) / 180;
  return { t, at: [p[0] + Math.sin(a) * radius, p[1] + height, p[2] + Math.cos(a) * radius], look: [p[0], p[1] + c.aim, p[2]], ...extra };
}

/** 跟随目标的关键帧：offset 在目标局部系（x 右手、y 上、z 前方）。 */
function fol(c: PresetCtx, u: number, offset: Vec3, extra: Partial<CamKey> = {}): CamKey {
  const t = at(c, u);
  if (c.target) return { t, follow: c.target, offset, ...extra };
  const p = c.posAt(t);
  return { t, at: add(p, [-offset[0], offset[1], offset[2]]), look: [p[0], p[1] + c.aim, p[2]], ...extra };
}

/** 世界坐标关键帧，看向 look（默认看目标瞄准点）。 */
function world(c: PresetCtx, u: number, pos: Vec3, look?: Vec3, extra: Partial<CamKey> = {}): CamKey {
  const t = at(c, u);
  const p = c.posAt(t);
  return { t, at: pos, look: look ?? (c.target ?? [p[0], p[1] + c.aim, p[2]]), ...extra } as CamKey;
}

/** 起幅机位：目标正前方偏 angle 度、给定距离与高度处的世界坐标。 */
function framing(c: PresetCtx, dist: number, height: number, angle = c.angle): { pos: Vec3; look: Vec3; right: Vec3; fwd: Vec3 } {
  const p = c.posAt(c.start);
  const yaw = c.yawAt(c.start) + angle;
  const fwd = forwardOf(yaw);
  const pos: Vec3 = [p[0] + fwd[0] * dist, p[1] + height, p[2] + fwd[2] * dist];
  const look: Vec3 = [p[0], p[1] + c.aim, p[2]];
  // 机位自己的右手：机位朝向是 -fwd
  const camRight = rightOf(yaw + 180);
  return { pos, look, right: camRight, fwd };
}

const D = (c: PresetCtx, size: string, k = 1) => c.distance ?? shotDistance(size, c, k);
const H = (c: PresetCtx, dflt: number) => c.height ?? dflt;

export const CAMERA_PRESETS: CameraPreset[] = [
  // ── 固定 ──
  { id: "static", zh: "固定镜头", group: "固定", doc: "机位不动，中景对着目标",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ms"), H(c, c.aim))] }) },
  { id: "handheld", zh: "手持拍摄", group: "固定", doc: "手持晃动，略微前移",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle + 4, D(c, "ms", 0.9), H(c, c.aim))], shake: 0.6, ease: "linear" }) },
  { id: "dutch", zh: "荷兰角", group: "固定", doc: "画面倾斜 15° 的固定机位，制造不安",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim), { roll: 15 }), orb(c, 1, c.angle, D(c, "ms"), H(c, c.aim), { roll: 15 })] }) },

  // ── 推拉 ──
  { id: "push_in", zh: "推近", group: "推拉", doc: "镜头前推：从全景推到中景",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ms", 0.85), H(c, c.aim))] }) },
  { id: "pull_out", zh: "拉远", group: "推拉", doc: "镜头后移：从中景拉到远景",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ws"), H(c, c.aim + 1))] }) },
  { id: "dolly_to_medium", zh: "推轨至中景", group: "推拉", doc: "轨道推进，从远景推到中景",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "ws"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ms"), H(c, c.aim))] }) },
  { id: "dolly_in", zh: "推轨", group: "推拉", doc: "轨道平稳推进一段",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "fs", 0.6), H(c, c.aim))], ease: "linear" }) },
  { id: "wide_push_in", zh: "远景推近", group: "推拉", doc: "从高处远景推到全景",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "ws", 1.4), H(c, 4)), orb(c, 1, c.angle, D(c, "fs"), H(c, c.aim))] }) },
  { id: "extreme_wide_to_close", zh: "大远景到特写", group: "推拉", doc: "从大远景一路推到脸部特写",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "els"), H(c, 14)), orb(c, 0.7, c.angle, D(c, "ms"), c.aim + 0.4), orb(c, 1, c.angle, D(c, "cu"), c.aim)], path: "curve" }) },
  { id: "medium_to_wide", zh: "中景到远景", group: "推拉", doc: "从中景拉开到远景，交代环境",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ws", 1.3), H(c, 4))] }) },
  { id: "zoom_in", zh: "变焦推进", group: "推拉", doc: "机位不动，焦段 35→85",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim), { lens: 35 }), orb(c, 1, c.angle, D(c, "fs"), H(c, c.aim), { lens: 85 })] }) },
  { id: "zoom_out", zh: "变焦拉远", group: "推拉", doc: "机位不动，焦段 85→30",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim), { lens: 85 }), orb(c, 1, c.angle, D(c, "fs"), H(c, c.aim), { lens: 30 })] }) },
  { id: "dolly_zoom", zh: "柯克变焦", group: "推拉", doc: "推轨变焦（希区柯克）：边推边拉焦，主体大小不变、背景被拉远",
    build: c => {
      const d0 = D(c, "ms", 1.8), d1 = D(c, "ms", 0.8);
      return { keys: [orb(c, 0, c.angle, d0, H(c, c.aim), { lens: 60 }), orb(c, 1, c.angle, d1, H(c, c.aim), { lens: 60 * (d1 / d0) })], ease: "linear" };
    } },

  // ── 摇 ──
  ...(["pan_left", "pan_right"] as const).map(id => ({
    id, zh: id === "pan_left" ? "镜头左摇" : "镜头右摇", group: "摇" as const, doc: "机位不动，镜头水平转 35°",
    build: (c: PresetCtx): PresetResult => {
      const f = framing(c, D(c, "fs"), H(c, c.aim));
      const dir = id === "pan_left" ? -1 : 1;
      return { keys: [world(c, 0, f.pos, f.look), world(c, 1, f.pos, add(f.look, scale(f.right, dir * D(c, "fs") * 0.7)))] };
    },
  })),
  ...(["tilt_up", "tilt_down"] as const).map(id => ({
    id, zh: id === "tilt_up" ? "镜头上摇" : "镜头下摇", group: "摇" as const, doc: "机位不动，镜头上抬／下压",
    build: (c: PresetCtx): PresetResult => {
      const f = framing(c, D(c, "fs"), H(c, 1.2));
      const low = add(f.look, [0, -c.aim + 0.1, 0]), high = add(f.look, [0, c.size * 1.5 + 2, 0]);
      return { keys: id === "tilt_up" ? [world(c, 0, f.pos, low), world(c, 1, f.pos, high)] : [world(c, 0, f.pos, high), world(c, 1, f.pos, low)] };
    },
  })),
  { id: "whip_pan", zh: "甩镜", group: "摇", doc: "极快横摇 80°（转场用，时长会压到 0.8 秒内）",
    build: c => {
      const f = framing(c, D(c, "fs"), H(c, c.aim));
      const d = Math.min(c.duration, 0.8);
      const k0 = world(c, 0, f.pos, f.look);
      return { keys: [k0, { ...world(c, 0, f.pos, add(f.look, scale(f.right, D(c, "fs") * 1.2))), t: c.start + d }], ease: "smooth" };
    } },

  // ── 移 ──
  ...(["truck_left", "truck_right"] as const).map(id => ({
    id, zh: id === "truck_left" ? "镜头左移" : "横移", group: "移" as const, doc: "机位沿轨道横向平移 3m，朝向不变",
    build: (c: PresetCtx): PresetResult => {
      const f = framing(c, D(c, "fs"), H(c, c.aim));
      const m = scale(f.right, (id === "truck_left" ? -1 : 1) * 3);
      return { keys: [world(c, 0, f.pos, f.look), world(c, 1, add(f.pos, m), add(f.look, m))], ease: "linear" };
    },
  })),
  ...(["pedestal_up", "pedestal_down"] as const).map(id => ({
    id, zh: id === "pedestal_up" ? "镜头上升" : "镜头下降", group: "移" as const, doc: "机位垂直升／降 2.5m，朝向不变",
    build: (c: PresetCtx): PresetResult => {
      const f = framing(c, D(c, "fs"), H(c, id === "pedestal_up" ? 1 : 3.5));
      const m: Vec3 = [0, id === "pedestal_up" ? 2.5 : -2.5, 0];
      return { keys: [world(c, 0, f.pos, f.look), world(c, 1, add(f.pos, m), add(f.look, m))] };
    },
  })),
  { id: "crane_up", zh: "摇臂上升", group: "移", doc: "摇臂从低处升到高处，始终对着目标",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), 0.8), orb(c, 1, c.angle, D(c, "fs", 1.3), H(c, 6))] }) },
  { id: "jib", zh: "摇臂", group: "移", doc: "抛物线：摇臂升起越过再落到新构图",
    build: c => ({ keys: [orb(c, 0, c.angle - 20, D(c, "fs"), 1), orb(c, 0.5, c.angle, D(c, "fs"), H(c, 5)), orb(c, 1, c.angle + 25, D(c, "ms"), c.aim)], path: "curve" }) },

  // ── 跟拍 ──
  { id: "follow", zh: "跟随拍摄", group: "跟拍", doc: "跟在目标身后中景跟拍",
    build: c => ({ keys: [fol(c, 0, [0, H(c, c.aim + 0.2), -D(c, "ms", 1.3)]), fol(c, 1, [0, H(c, c.aim + 0.2), -D(c, "ms", 1.3)])], ease: "linear" }) },
  { id: "follow_back", zh: "背跟", group: "跟拍", doc: "身后跟拍",
    build: c => ({ keys: [fol(c, 0, [0, H(c, c.aim + 0.3), -D(c, "fs", 0.8)]), fol(c, 1, [0, H(c, c.aim + 0.3), -D(c, "fs", 0.8)])], ease: "linear" }) },
  { id: "follow_back_close", zh: "背跟特写", group: "跟拍", doc: "贴着肩后跟拍",
    build: c => ({ keys: [fol(c, 0, [0.35 * c.side, H(c, c.aim), -D(c, "cu")]), fol(c, 1, [0.35 * c.side, H(c, c.aim), -D(c, "cu")])], ease: "linear" }) },
  { id: "follow_front", zh: "正面跟", group: "跟拍", doc: "在目标前方倒退着跟拍",
    build: c => ({ keys: [fol(c, 0, [0, H(c, c.aim), D(c, "ms", 1.3)]), fol(c, 1, [0, H(c, c.aim), D(c, "ms", 1.3)])], ease: "linear" }) },
  { id: "follow_front_wide", zh: "正面跟远景", group: "跟拍", doc: "前方远处高位跟拍",
    build: c => ({ keys: [fol(c, 0, [0, H(c, 3), D(c, "ws")]), fol(c, 1, [0, H(c, 3), D(c, "ws")])], ease: "linear" }) },
  { id: "follow_side_push", zh: "侧跟推近", group: "跟拍", doc: "侧面跟拍并逐渐推近",
    build: c => ({ keys: [fol(c, 0, [D(c, "fs") * c.side, H(c, c.aim), 0.4]), fol(c, 1, [D(c, "ms", 0.8) * c.side, H(c, c.aim), 0.3])] }) },
  { id: "follow_wide", zh: "远景跟随", group: "跟拍", doc: "侧后方高位远景跟随",
    build: c => ({ keys: [fol(c, 0, [D(c, "ws", 0.7) * c.side, H(c, 5), -D(c, "ws", 0.7)]), fol(c, 1, [D(c, "ws", 0.7) * c.side, H(c, 5), -D(c, "ws", 0.7)])], ease: "linear" }) },
  { id: "front_to_back", zh: "正面转背跟", group: "跟拍", doc: "从正面绕到背后继续跟",
    build: c => ({ keys: [orb(c, 0, 0, D(c, "ms", 1.2), H(c, c.aim)), orb(c, 1, 180 * c.side, D(c, "ms", 1.2), H(c, c.aim))] }) },
  { id: "top_to_follow", zh: "顶拍转跟随", group: "跟拍", doc: "先正上方俯拍，再降到身后跟拍",
    build: c => {
      const p = c.posAt(c.start);
      return { keys: [world(c, 0, [p[0], p[1] + 16, p[2] + 0.1]), fol(c, 0.6, [0, 2.2, -D(c, "fs")]), fol(c, 1, [0, H(c, c.aim + 0.3), -D(c, "fs", 0.8)])], path: "curve" };
    } },
  { id: "first_person", zh: "第一视角", group: "跟拍", doc: "从目标眼睛的位置往前看（主观镜头）",
    build: c => {
      const eye = c.size * 0.93;
      const key = (u: number) => fol(c, u, [0, eye, 0.2], c.target ? { look: { target: c.target, offset: [0, eye * 0.95, 10] } } : {});
      return { keys: [key(0), key(1)], ease: "linear", shake: 0.25 };
    } },

  // ── 环绕 ──
  { id: "orbit_left", zh: "左环绕", group: "环绕", doc: "绕目标向左（机位自己的左手）走 120°",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs", 0.9), H(c, c.aim)), orb(c, 1, c.angle + 120, D(c, "fs", 0.9), H(c, c.aim))] }) },
  { id: "orbit_right", zh: "右环绕", group: "环绕", doc: "绕目标向右走 120°",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs", 0.9), H(c, c.aim)), orb(c, 1, c.angle - 120, D(c, "fs", 0.9), H(c, c.aim))] }) },
  { id: "orbit", zh: "环绕", group: "环绕", doc: "绕目标一整圈",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs", 0.9), H(c, c.aim)), orb(c, 1, c.angle + 360 * c.side, D(c, "fs", 0.9), H(c, c.aim))], ease: "linear" }) },
  { id: "half_arc", zh: "半弧", group: "环绕", doc: "绕目标半圈（180°）",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs", 0.9), H(c, c.aim)), orb(c, 1, c.angle + 180 * c.side, D(c, "fs", 0.9), H(c, c.aim))] }) },
  { id: "orbit_twice", zh: "环绕两周", group: "环绕", doc: "绕目标两整圈",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs", 0.9), H(c, c.aim)), orb(c, 1, c.angle + 720 * c.side, D(c, "fs", 0.9), H(c, c.aim))], ease: "linear" }) },
  { id: "orbit_push", zh: "环绕推近", group: "环绕", doc: "边绕 90° 边推到中近景",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle + 90 * c.side, D(c, "mcu"), c.aim)] }) },
  { id: "spiral_up", zh: "螺旋上升", group: "环绕", doc: "盘旋抬升：绕一圈同时升高拉远",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle + 360 * c.side, D(c, "ws", 0.8), 9)] }) },
  { id: "spiral_down", zh: "盘旋下降", group: "环绕", doc: "从高处绕一圈降下来推近",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "ws", 0.8), 9), orb(c, 1, c.angle + 360 * c.side, D(c, "fs"), H(c, c.aim))] }) },
  { id: "push_turn_left", zh: "推近左转", group: "环绕", doc: "推近的同时向左转 45°",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim)), orb(c, 1, c.angle + 45, D(c, "ms"), c.aim)] }) },

  // ── 航拍 ──
  { id: "drone", zh: "无人机", group: "航拍", doc: "无人机从后上方高速掠过目标",
    build: c => {
      const p0 = c.posAt(c.start), p1 = c.posAt(c.start + c.duration);
      const f = forwardOf(c.yawAt(c.start));
      return { keys: [world(c, 0, add(p0, [-f[0] * 25, 14, -f[2] * 25])), world(c, 0.5, add(p0, [0, 9, 0.5])), world(c, 1, add(p1, [f[0] * 20, 7, f[2] * 20]))], path: "curve", ease: "linear" };
    } },
  { id: "aerial_high", zh: "高空航拍", group: "航拍", doc: "正上方高空俯拍，缓慢升高",
    build: c => {
      const p = c.posAt(c.start);
      return { keys: [world(c, 0, [p[0], p[1] + 40, p[2] + 0.1], undefined, { lens: 28 }), world(c, 1, [p[0], p[1] + 55, p[2] + 0.1], undefined, { lens: 28 })] };
    } },
  { id: "aerial_rise", zh: "航拍拉升", group: "航拍", doc: "从中景拉升后退到高空全景",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "ms"), H(c, c.aim)), orb(c, 1, c.angle, D(c, "ws", 1.6), 16)] }) },

  // ── 特殊 ──
  { id: "roll", zh: "滚筒旋转", group: "特殊", doc: "机位不动，画面绕光轴转一整圈",
    build: c => ({ keys: [orb(c, 0, c.angle, D(c, "fs"), H(c, c.aim), { roll: 0 }), orb(c, 1, c.angle, D(c, "fs"), H(c, c.aim), { roll: 360 })], ease: "linear" }) },
];

export const PRESET_IDS = CAMERA_PRESETS.map(p => p.id);

export function presetDoc() {
  return CAMERA_PRESETS.map(p => ({ id: p.id, zh: p.zh, group: p.group, doc: p.doc }));
}
