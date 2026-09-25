/**
 * 人偶骨架与动作库：姿势、步态、动作片段（出拳、踢腿、闪避、格挡、受击、倒地、起身……）。
 *
 * 纯函数、不引 three：3D-BOX 预览（Mannequin）每帧调，后端烘焙（bake）逐帧调，
 * Blender 按烘焙结果摆 —— 三处同一份动作，预览里看到的就是 Blender 渲出来的。
 *
 * 关节约定（人面朝局部 +Z，他的左手在 +X）：
 *   肩、髋绕 X 负角 = 往前摆（抬臂、抬腿）；膝正角 = 小腿往后折；肘负角 = 小臂往前折
 *   脊柱 X 正 = 前倾、负 = 后仰；脊柱/头 Y 正 = 转向自己的左边（右肩往前）
 *   脊柱 Z 负 = 向自己的左边侧倾；左肩 Z 正、右肩 Z 负 = 手臂往外张
 * 欧拉角是度、XYZ 次序（three 默认）。
 */
import type { ActionKey, SceneObject, Vec3 } from "./types";
import { BODIES } from "./prefabs";

export type Rot = [number, number, number];
export const JOINTS = ["spine", "head", "lSh", "lEl", "rSh", "rEl", "lHip", "lKn", "rHip", "rKn"] as const;
export type Joint = typeof JOINTS[number];

export interface PoseDef {
  /** 盆骨下沉（按腿长比例）：坐、蹲 */
  lift?: number;
  /** 整体旋转（绕脚底）：躺 */
  root?: Rot;
  spine?: Rot; head?: Rot;
  lSh?: Rot; lEl?: Rot; rSh?: Rot; rEl?: Rot;
  lHip?: Rot; lKn?: Rot; rHip?: Rot; rKn?: Rot;
}

export const POSE_DEFS: Record<string, PoseDef> = {
  stand: { lSh: [0, 0, 8], rSh: [0, 0, -8] },
  walk: { lSh: [0, 0, 6], rSh: [0, 0, -6] },
  run: { spine: [12, 0, 0], lSh: [0, 0, 8], rSh: [0, 0, -8], lEl: [-80, 0, 0], rEl: [-80, 0, 0] },
  sit: { lift: 0.52, lHip: [-90, 0, 4], rHip: [-90, 0, -4], lKn: [90, 0, 0], rKn: [90, 0, 0], lSh: [-20, 0, 6], rSh: [-20, 0, -6], lEl: [-40, 0, 0], rEl: [-40, 0, 0] },
  drive: { lift: 0.52, lHip: [-90, 0, 4], rHip: [-90, 0, -4], lKn: [80, 0, 0], rKn: [80, 0, 0], lSh: [-65, 0, 8], rSh: [-65, 0, -8], lEl: [-25, 0, 0], rEl: [-25, 0, 0] },
  crouch: { lift: 0.45, spine: [25, 0, 0], lHip: [-110, 0, 8], rHip: [-110, 0, -8], lKn: [130, 0, 0], rKn: [130, 0, 0], lSh: [-30, 0, 10], rSh: [-30, 0, -10], lEl: [-40, 0, 0], rEl: [-40, 0, 0] },
  kneel: { lift: 0.3, lHip: [-90, 0, 4], lKn: [90, 0, 0], rHip: [0, 0, -4], rKn: [90, 0, 0], lSh: [0, 0, 8], rSh: [0, 0, -8] },
  point: { lSh: [0, 0, 8], rSh: [-88, 0, -4] },
  wave: { lSh: [0, 0, 8], rSh: [0, 0, -150], rEl: [0, 0, -30] },
  fight: { lHip: [-10, 0, 10], rHip: [10, 0, -10], lKn: [20, 0, 0], rKn: [15, 0, 0], lSh: [-60, 0, 20], rSh: [-45, 0, -20], lEl: [-110, 0, 0], rEl: [-120, 0, 0], spine: [8, -15, 0] },
  lie: { root: [-90, 0, 0], lSh: [0, 0, 12], rSh: [0, 0, -12] },
  phone: { lSh: [0, 0, 8], rSh: [-25, 0, -35], rEl: [-140, 0, 0] },
  arms_crossed: { lSh: [-35, -25, 10], rSh: [-35, 25, -10], lEl: [-110, 0, 0], rEl: [-110, 0, 0] },
  hands_up: { lSh: [0, 0, 160], rSh: [0, 0, -160], lEl: [0, 0, 20], rEl: [0, 0, -20] },
  aim: { lSh: [-88, -18, 0], rSh: [-88, 18, 0], spine: [0, 10, 0] },
  bow: { spine: [45, 0, 0], head: [10, 0, 0], lSh: [-15, 0, 4], rSh: [-15, 0, -4] },
};

// ── 尺寸 ────────────────────────────────────────────────

export interface MannequinDims {
  head: number; leg: number; torso: number; neck: number; shoulder: number; hip: number;
  upperArm: number; foreArm: number; limb: number; chest: number;
}

/** 人偶各段尺寸（米）。预览的网格和 Blender 的网格都按它建。 */
export function mannequinDims(body: string, height?: number): MannequinDims {
  const b = BODIES[body] ?? BODIES.male;
  const H = height ?? b.height;
  const chibi = body === "chibi";
  return {
    head: (chibi ? 0.2 : 0.066 * b.head) * H,
    leg: (chibi ? 0.34 : 0.47) * H,
    torso: chibi ? 0.24 * H : 0.3 * H,
    neck: 0.03 * H,
    shoulder: 0.115 * H * b.width * (chibi ? 1.2 : 1),
    hip: 0.055 * H * b.width,
    upperArm: (chibi ? 0.13 : 0.17) * H,
    foreArm: (chibi ? 0.12 : 0.16) * H,
    limb: 0.045 * H * b.width,
    chest: 0.2 * H * b.width,
  };
}

// ── 通道：姿势混合用的扁平表示 ─────────────────────────────

interface Channels { lift: number; root: Rot; joints: Record<Joint, Rot> }

const Z: Rot = [0, 0, 0];

function channels(def: PoseDef): Channels {
  const joints = {} as Record<Joint, Rot>;
  for (const j of JOINTS) joints[j] = (def[j] ?? Z).slice() as Rot;
  return { lift: def.lift ?? 0, root: (def.root ?? Z).slice() as Rot, joints };
}

const lerpRot = (a: Rot, b: Rot, w: number): Rot => [a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w, a[2] + (b[2] - a[2]) * w];

function mix(a: Channels, b: Channels, w: number, mask?: readonly Joint[] | null): Channels {
  if (w <= 0) return a;
  const joints = { ...a.joints };
  for (const j of JOINTS) if (!mask || mask.includes(j)) joints[j] = lerpRot(a.joints[j], b.joints[j], w);
  // 局部动作（只动上身）不碰盆骨高度和整体旋转
  if (mask) return { lift: a.lift, root: a.root, joints };
  return { lift: a.lift + (b.lift - a.lift) * w, root: lerpRot(a.root, b.root, w), joints };
}

const smooth = (x: number) => { const u = Math.min(1, Math.max(0, x)); return u * u * (3 - 2 * u); };

// ── 动作库 ──────────────────────────────────────────────

export interface MotionKey {
  u: number;
  pose: PoseDef;
  /** 位移（人自己的局部系：x 他的左手、z 前方，米） */
  offset?: Vec3;
  /** 转身（度，正 = 向左转） */
  yaw?: number;
}

export interface MotionDef {
  zh: string;
  group: "基础" | "移动" | "格斗" | "受击" | "倒地";
  doc: string;
  /** 默认时长（秒） */
  duration: number;
  keys: MotionKey[];
  /** 只动这些关节（其余照旧，比如边走边回头） */
  mask?: readonly Joint[];
  /** 结束后保持最后的姿势（倒地），直到下一个动作或 S.pose 换姿势 */
  hold?: boolean;
  /** 结束后位移、转身保留（闪避、被打退、转身） */
  keep?: boolean;
  loop?: boolean;
  /** 有 target 时先转身面向目标（出拳、踢腿） */
  aim?: boolean;
  /** 不是关节动作：运行时换成移动轨迹（往前走/跑） */
  locomotion?: { speed: number; action: "walk" | "run" };
}

const GUARD = POSE_DEFS.fight;
const g = (extra: PoseDef): PoseDef => ({ ...GUARD, ...extra });

const UPPER: readonly Joint[] = ["spine", "head", "lSh", "lEl", "rSh", "rEl"];
const LEGS: readonly Joint[] = ["lHip", "lKn", "rHip", "rKn"];

/** 左右镜像：左右关节互换，Y/Z 取反，横向位移、转身取反。 */
function mirrorPose(p: PoseDef): PoseDef {
  const f = (r?: Rot): Rot | undefined => (r ? [r[0], -r[1], -r[2]] : undefined);
  const out: PoseDef = { lift: p.lift, root: f(p.root), spine: f(p.spine), head: f(p.head) };
  const pairs: [keyof PoseDef, keyof PoseDef][] = [["lSh", "rSh"], ["lEl", "rEl"], ["lHip", "rHip"], ["lKn", "rKn"]];
  for (const [l, r] of pairs) {
    (out as Record<string, Rot | undefined>)[l] = f(p[r] as Rot | undefined);
    (out as Record<string, Rot | undefined>)[r] = f(p[l] as Rot | undefined);
  }
  for (const k of Object.keys(out) as (keyof PoseDef)[]) if (out[k] === undefined) delete out[k];
  return out;
}

function mirror(def: MotionDef, zh: string, doc: string): MotionDef {
  return {
    ...def, zh, doc,
    keys: def.keys.map(k => ({
      u: k.u, pose: mirrorPose(k.pose),
      offset: k.offset ? [-k.offset[0], k.offset[1], k.offset[2]] : undefined,
      yaw: k.yaw !== undefined ? -k.yaw : undefined,
    })),
  };
}

const RIGHT_PUNCH: MotionDef = {
  zh: "右直拳", group: "格斗", doc: "护架 → 收肩蓄力 → 右拳直出 → 收回护架", duration: 0.6, aim: true,
  keys: [
    { u: 0, pose: GUARD },
    { u: 0.28, pose: g({ spine: [6, -22, 0], rSh: [-35, 0, -25], rEl: [-135, 0, 0] }) },
    { u: 0.5, pose: g({ spine: [10, 28, 0], rSh: [-88, 0, -6], rEl: [-8, 0, 0], lSh: [-50, 0, 22], lEl: [-120, 0, 0] }), offset: [0, 0, 0.12] },
    { u: 0.72, pose: g({ spine: [10, 26, 0], rSh: [-86, 0, -6], rEl: [-12, 0, 0], lSh: [-50, 0, 22], lEl: [-120, 0, 0] }), offset: [0, 0, 0.12] },
    { u: 1, pose: GUARD, offset: [0, 0, 0] },
  ],
};

const DODGE_LEFT: MotionDef = {
  zh: "左闪", group: "格斗", doc: "屈膝侧倾，往自己的左边闪开 0.6 米", duration: 0.5, keep: true,
  keys: [
    { u: 0, pose: GUARD },
    { u: 0.45, pose: g({ lift: 0.1, spine: [10, 0, -20], head: [0, 0, 10], lHip: [-10, 0, 22], rHip: [10, 0, -5], lKn: [35, 0, 0], rKn: [30, 0, 0] }), offset: [0.55, 0, -0.05] },
    { u: 1, pose: GUARD, offset: [0.6, 0, 0] },
  ],
};

const TURN_LEFT: MotionDef = {
  zh: "左转身", group: "移动", doc: "原地向左转 90°（小碎步）", duration: 0.8, keep: true, mask: LEGS,
  keys: [
    { u: 0, pose: POSE_DEFS.stand, yaw: 0 },
    { u: 0.25, pose: { lHip: [-18, 0, 4], rKn: [22, 0, 0] }, yaw: 30 },
    { u: 0.5, pose: POSE_DEFS.stand, yaw: 55 },
    { u: 0.75, pose: { rHip: [-18, 0, -4], lKn: [22, 0, 0] }, yaw: 80 },
    { u: 1, pose: POSE_DEFS.stand, yaw: 90 },
  ],
};

const HIT_LEFT: MotionDef = {
  zh: "受击左偏", group: "受击", doc: "右侧挨了一下：头和上身甩向自己的左边，退半步", duration: 0.6, keep: true,
  keys: [
    { u: 0, pose: POSE_DEFS.stand },
    { u: 0.2, pose: { spine: [5, 25, -18], head: [0, 35, -15], lSh: [-20, 0, 35], rSh: [-30, 0, -50], lKn: [15, 0, 0], rKn: [20, 0, 0] }, offset: [0.25, 0, 0] },
    { u: 0.5, pose: { spine: [3, 12, -8], head: [0, 15, -5], lSh: [-10, 0, 20], rSh: [-15, 0, -25], lKn: [12, 0, 0], rKn: [12, 0, 0] }, offset: [0.3, 0, 0] },
    { u: 1, pose: GUARD, offset: [0.3, 0, 0] },
  ],
};

export const MOTIONS: Record<string, MotionDef> = {
  idle: {
    zh: "待机", group: "基础", doc: "站着轻微呼吸起伏（循环）", duration: 2, loop: true, mask: UPPER,
    keys: [
      { u: 0, pose: POSE_DEFS.stand },
      { u: 0.5, pose: { spine: [2, 0, 0], head: [-3, 0, 0], lSh: [2, 0, 9], rSh: [2, 0, -9] } },
      { u: 1, pose: POSE_DEFS.stand },
    ],
  },
  walk_forward: { zh: "向前走", group: "移动", doc: "朝当前方向走 duration 秒（1.4 米/秒）", duration: 2, keys: [], locomotion: { speed: 1.4, action: "walk" } },
  run_forward: { zh: "向前跑", group: "移动", doc: "朝当前方向跑 duration 秒（4.5 米/秒）", duration: 1.5, keys: [], locomotion: { speed: 4.5, action: "run" } },
  turn_left: TURN_LEFT,
  turn_right: mirror(TURN_LEFT, "右转身", "原地向右转 90°（小碎步）"),
  turn_to: {
    zh: "转向目标", group: "移动", doc: "原地转身面向 target（S.face / look_at 用）", duration: 0.5, keep: true, aim: true, mask: LEGS,
    keys: [{ u: 0, pose: POSE_DEFS.stand }, { u: 0.5, pose: { lHip: [-12, 0, 4], rKn: [15, 0, 0] } }, { u: 1, pose: POSE_DEFS.stand }],
  },
  look_back: {
    zh: "回头看", group: "基础", doc: "扭头越过右肩往身后看，再转回来（可边走边做）", duration: 1.6, mask: ["spine", "head"],
    keys: [
      { u: 0, pose: {} },
      { u: 0.3, pose: { spine: [0, -28, 0], head: [5, -70, 0] } },
      { u: 0.75, pose: { spine: [0, -28, 0], head: [5, -72, 0] } },
      { u: 1, pose: {} },
    ],
  },
  right_punch: RIGHT_PUNCH,
  left_punch: mirror(RIGHT_PUNCH, "左直拳", "护架 → 收肩蓄力 → 左拳直出 → 收回护架"),
  front_kick: {
    zh: "前踢", group: "格斗", doc: "右腿提膝 → 前蹬伸直 → 收回", duration: 0.8, aim: true,
    keys: [
      { u: 0, pose: GUARD },
      { u: 0.3, pose: g({ spine: [-6, 0, 0], rHip: [-75, 0, -6], rKn: [95, 0, 0], lKn: [12, 0, 0] }) },
      { u: 0.5, pose: g({ spine: [-12, 0, 0], rHip: [-88, 0, -4], rKn: [4, 0, 0], lKn: [10, 0, 0], lSh: [-40, 0, 30], rSh: [-30, 0, -35] }), offset: [0, 0, 0.08] },
      { u: 0.7, pose: g({ spine: [-6, 0, 0], rHip: [-70, 0, -6], rKn: [90, 0, 0] }), offset: [0, 0, 0.05] },
      { u: 1, pose: GUARD, offset: [0, 0, 0] },
    ],
  },
  dodge_left: DODGE_LEFT,
  dodge_right: mirror(DODGE_LEFT, "右闪", "屈膝侧倾，往自己的右边闪开 0.6 米"),
  block_high: {
    zh: "高位格挡", group: "格斗", doc: "双臂上架护住头（腿照旧）", duration: 0.8, mask: UPPER,
    keys: [
      { u: 0, pose: { spine: [8, 0, 0], head: [10, 0, 0], lSh: [-150, 0, 40], lEl: [-70, 0, 0], rSh: [-150, 0, -40], rEl: [-70, 0, 0] } },
      { u: 1, pose: { spine: [8, 0, 0], head: [10, 0, 0], lSh: [-150, 0, 40], lEl: [-70, 0, 0], rSh: [-150, 0, -40], rEl: [-70, 0, 0] } },
    ],
  },
  hit_react_back: {
    zh: "受击后仰", group: "受击", doc: "正面挨打：上身后仰、双臂甩开，被打退 0.4 米", duration: 0.7, keep: true,
    keys: [
      { u: 0, pose: { spine: [-5, 0, 0] } },
      { u: 0.2, pose: { spine: [-28, 0, 0], head: [-25, 0, 0], lSh: [-35, 0, 40], rSh: [-35, 0, -40], lEl: [-40, 0, 0], rEl: [-40, 0, 0], lHip: [8, 0, 4], rHip: [-6, 0, -4], lKn: [15, 0, 0], rKn: [25, 0, 0] }, offset: [0, 0, -0.25] },
      { u: 0.5, pose: { lift: 0.05, spine: [-15, 0, 0], head: [-8, 0, 0], lSh: [-20, 0, 25], rSh: [-20, 0, -25], lKn: [20, 0, 0], rKn: [20, 0, 0] }, offset: [0, 0, -0.4] },
      { u: 1, pose: GUARD, offset: [0, 0, -0.4] },
    ],
  },
  hit_react_left: HIT_LEFT,
  fall_backward: {
    zh: "向后倒地", group: "倒地", doc: "后仰失衡、屈膝、仰面倒地并躺着（直到 stand_up）", duration: 1.2, hold: true, keep: true,
    keys: [
      { u: 0, pose: { spine: [-10, 0, 0] } },
      { u: 0.25, pose: { lift: 0.15, spine: [-30, 0, 0], head: [-20, 0, 0], lSh: [-60, 0, 45], rSh: [-60, 0, -45], lKn: [40, 0, 0], rKn: [40, 0, 0] }, offset: [0, 0, -0.2] },
      { u: 0.55, pose: { lift: 0.4, root: [-50, 0, 0], spine: [-10, 0, 0], lSh: [-90, 0, 40], rSh: [-90, 0, -40], lHip: [-40, 0, 5], rHip: [-40, 0, -5], lKn: [60, 0, 0], rKn: [60, 0, 0] }, offset: [0, 0, -0.5] },
      { u: 0.8, pose: { root: [-90, 0, 0], lSh: [-20, 0, 30], rSh: [-20, 0, -30], lHip: [-20, 0, 6], rHip: [-15, 0, -6], lKn: [25, 0, 0], rKn: [15, 0, 0] }, offset: [0, 0, -0.7] },
      { u: 1, pose: { root: [-90, 0, 0], lSh: [0, 0, 14], rSh: [0, 0, -14], lHip: [0, 0, 5], rHip: [0, 0, -5] }, offset: [0, 0, -0.75] },
    ],
  },
  stand_up: {
    zh: "起身", group: "倒地", doc: "从躺着坐起 → 蹲 → 站直", duration: 1.4, keep: true,
    keys: [
      { u: 0, pose: { root: [-90, 0, 0], lSh: [0, 0, 14], rSh: [0, 0, -14] } },
      { u: 0.3, pose: { lift: 0.5, root: [-60, 0, 0], spine: [40, 0, 0], lSh: [-30, 0, 20], rSh: [-30, 0, -20], lHip: [-60, 0, 5], rHip: [-60, 0, -5], lKn: [100, 0, 0], rKn: [100, 0, 0] }, offset: [0, 0, -0.3] },
      { u: 0.6, pose: { ...POSE_DEFS.crouch }, offset: [0, 0, -0.75] },
      { u: 1, pose: POSE_DEFS.stand, offset: [0, 0, -0.8] },
    ],
  },
};

export const MOTION_IDS = Object.keys(MOTIONS);

export function motionDoc() {
  return Object.entries(MOTIONS).map(([id, m]) => ({ id, zh: m.zh, group: m.group, doc: m.doc, duration: m.duration, target: !!m.aim }));
}

function sampleMotion(def: MotionDef, u: number): { ch: Channels; offset: Vec3; yaw: number } {
  const keys = def.keys;
  const x = def.loop ? u - Math.floor(u) : Math.min(1, Math.max(0, u));
  let i = 0;
  while (i < keys.length - 2 && x > keys[i + 1].u) i++;
  const a = keys[i], b = keys[Math.min(keys.length - 1, i + 1)];
  const w = b.u - a.u > 1e-6 ? smooth((x - a.u) / (b.u - a.u)) : 1;
  const ca = channels(a.pose), cb = channels(b.pose);
  const off = (k: MotionKey) => k.offset ?? [0, 0, 0];
  const oa = off(a), ob = off(b);
  return {
    ch: mix(ca, cb, w),
    offset: [oa[0] + (ob[0] - oa[0]) * w, oa[1] + (ob[1] - oa[1]) * w, oa[2] + (ob[2] - oa[2]) * w],
    yaw: (a.yaw ?? 0) + ((b.yaw ?? 0) - (a.yaw ?? 0)) * w,
  };
}

function motionEnd(def: MotionDef) {
  const last = def.keys[def.keys.length - 1];
  return { ch: channels(last?.pose ?? {}), offset: last?.offset ?? ([0, 0, 0] as Vec3), yaw: last?.yaw ?? 0 };
}

// ── 求一帧 ────────────────────────────────────────────────

/** 一帧的骨架状态：Mannequin 和 Blender 都按它摆。 */
export interface JointState {
  /** 动作带来的位移（人自己的局部系，米）与转身（度）—— 挂在人偶最外层 */
  offset: Vec3;
  yaw: number;
  /** 整体旋转（躺、倒地）与为它抬起的高度（米） */
  root: Rot;
  rootY: number;
  /** 盆骨离地高度（米） */
  pelvisY: number;
  joints: Record<Joint, Rot>;
}

export type { ActionKey };

/** 人偶求值需要的场景信息（SceneEval 满足它；这里不直接引 evaluate，免得循环依赖）。 */
export interface RigWorld {
  world(id: string, t: number): { pos: Vec3; rot: Vec3; speed: number };
  gait(id: string, t: number): { phase: number; speed: number };
}

const wrap180 = (a: number) => ((((a + 180) % 360) + 360) % 360) - 180;

/** 基础姿势＋步态（原 Mannequin.animate 的逻辑）。 */
function baseChannels(pose: string, phase: number, speed: number): { ch: Channels; bob: number } {
  const moving = speed > 0.15 && (pose === "stand" || pose === "walk" || pose === "run");
  const run = speed > 2.6;
  const ch = channels(POSE_DEFS[moving ? (run ? "run" : "walk") : pose] ?? POSE_DEFS.stand);
  let bob = 0;
  if (moving) {
    const s = Math.sin(phase * Math.PI * 2);
    const A = run ? 50 : 28;
    const add = (j: Joint, dx: number) => { ch.joints[j] = [ch.joints[j][0] + dx, ch.joints[j][1], ch.joints[j][2]]; };
    add("lHip", -A * s); add("rHip", A * s);
    add("lKn", Math.max(0, s) * (run ? 90 : 45)); add("rKn", Math.max(0, -s) * (run ? 90 : 45));
    add("lSh", A * 0.8 * s); add("rSh", -A * 0.8 * s);
    bob = Math.abs(Math.cos(phase * Math.PI * 2)) * (run ? 0.05 : 0.025);
  }
  return { ch, bob };
}

/**
 * 人物 obj 在 t 秒的骨架状态。
 *
 * 叠加次序：S.pose 的基础姿势 → 走跑步态 → 已结束动作留下的（倒地的躺姿、闪避后的位移、转身）
 * → 正在做的动作（按包络淡入淡出）。有 target 的出拳、踢腿先转身面向目标。
 */
export function jointsAt(w: RigWorld, obj: SceneObject, t: number, dims: MannequinDims): JointState {
  let pose = obj.poses?.[0]?.pose ?? "stand";
  let poseT = -Infinity;
  for (const p of obj.poses ?? []) if (p.t <= t + 1e-6) { pose = p.pose; poseT = p.t; }
  const g0 = obj.track ? w.gait(obj.id, t) : { phase: 0, speed: 0 };
  const moving = g0.speed > 0.15;
  let { ch, bob } = baseChannels(pose, g0.phase, g0.speed);

  let offset: Vec3 = [0, 0, 0];
  let yaw = 0;
  let hold: Channels | null = null;
  const acts = (obj.actions ?? []).slice().sort((a, b) => a.t - b.t);
  let active: { def: MotionDef; a: ActionKey; aimDelta: number } | null = null;

  for (const a of acts) {
    const def = MOTIONS[a.name];
    if (!def || def.locomotion || a.t > t + 1e-6) continue;
    let aimDelta = 0;
    if (def.aim && a.target) {
      const me = w.world(obj.id, a.t), tg = w.world(a.target, a.t);
      const dx = tg.pos[0] - me.pos[0], dz = tg.pos[2] - me.pos[2];
      if (Math.hypot(dx, dz) > 0.05) aimDelta = wrap180((Math.atan2(dx, dz) * 180) / Math.PI - (me.rot[1] + yaw));
    }
    const end = a.t + a.duration;
    if (t >= end - 1e-6 && !def.loop) {
      const e = motionEnd(def);
      if (def.keep) {
        offset = [offset[0] + e.offset[0], offset[1] + e.offset[1], offset[2] + e.offset[2]];
        yaw += e.yaw + aimDelta;
      } else if (def.aim) {
        yaw += aimDelta;     // 出拳之后还面向对手
      }
      hold = def.hold ? e.ch : null;
    } else if (t < end || def.loop) {
      active = { def, a, aimDelta };
    }
  }
  // S.pose 在倒地之后换了姿势，就不再躺着
  if (hold && poseT > -Infinity) {
    const lastHold = acts.filter(a => MOTIONS[a.name]?.hold && a.t + a.duration <= t + 1e-6).pop();
    if (lastHold && poseT >= lastHold.t + lastHold.duration - 1e-6) hold = null;
  }
  if (hold) { ch = hold; bob = 0; }

  if (active) {
    const { def, a, aimDelta } = active;
    const u = (t - a.t) / Math.max(1e-3, a.duration);
    const s = sampleMotion(def, u);
    const fadeIn = Math.min(0.15, a.duration * 0.25), fadeOut = Math.min(0.2, a.duration * 0.3);
    const el = t - a.t, left = a.t + a.duration - t;
    const env = def.loop ? smooth(el / fadeIn) : smooth(el / fadeIn) * (def.hold ? 1 : smooth(left / fadeOut));
    ch = mix(ch, s.ch, env, def.mask ?? null);
    if (!def.mask) bob *= 1 - env;
    offset = [offset[0] + s.offset[0], offset[1] + s.offset[1], offset[2] + s.offset[2]];
    yaw += s.yaw + aimDelta * smooth(el / 0.15);
  }
  // 走起来以后朝向由路径决定：原地转身、面向对手只在停着的时候算数
  if (moving && obj.track?.face === "path") yaw = 0;

  const lie = Math.min(1, Math.abs(ch.root[0]) / 90);
  return {
    offset, yaw,
    root: ch.root,
    rootY: dims.chest * 0.28 * lie,
    pelvisY: dims.leg * (1 - ch.lift) + bob,
    joints: ch.joints,
  };
}

// ── 骨架层级：给 Blender、姿态骨架图用 ─────────────────────

/**
 * 关节层级（与 Mannequin 的组嵌套一一对应）：
 *   move（offset、yaw）→ root（root、rootY）→ pelvis（pelvisY）→ lHip→lKn、rHip→rKn、spine→head、spine→lSh→lEl、spine→rSh→rEl
 * pos 是在父节点里的位置（米）。
 */
export function rigLayout(d: MannequinDims) {
  return {
    lHip: { parent: "pelvis", pos: [d.hip, 0, 0] as Vec3 },
    rHip: { parent: "pelvis", pos: [-d.hip, 0, 0] as Vec3 },
    lKn: { parent: "lHip", pos: [0, -d.leg * 0.5, 0] as Vec3 },
    rKn: { parent: "rHip", pos: [0, -d.leg * 0.5, 0] as Vec3 },
    spine: { parent: "pelvis", pos: [0, 0, 0] as Vec3 },
    head: { parent: "spine", pos: [0, d.torso + d.neck, 0] as Vec3 },
    lSh: { parent: "spine", pos: [d.shoulder, d.torso * 0.94, 0] as Vec3 },
    rSh: { parent: "spine", pos: [-d.shoulder, d.torso * 0.94, 0] as Vec3 },
    lEl: { parent: "lSh", pos: [0, -d.upperArm, 0] as Vec3 },
    rEl: { parent: "rSh", pos: [0, -d.upperArm, 0] as Vec3 },
  };
}

/**
 * OpenPose（COCO 18 点）关键点挂在哪个关节上、偏多少。R = 他的右边（-X）。
 * 顺序就是 OpenPose 的顺序：0 鼻 1 颈 2 右肩 3 右肘 4 右腕 5 左肩 6 左肘 7 左腕
 * 8 右髋 9 右膝 10 右踝 11 左髋 12 左膝 13 左踝 14 右眼 15 左眼 16 右耳 17 左耳
 */
export function poseKeypoints(d: MannequinDims): { name: string; joint: Joint | "pelvis"; pos: Vec3 }[] {
  const h = d.head;
  return [
    { name: "nose", joint: "head", pos: [0, h, h] },
    { name: "neck", joint: "spine", pos: [0, d.torso * 0.97, 0] },
    { name: "r_shoulder", joint: "rSh", pos: [0, 0, 0] },
    { name: "r_elbow", joint: "rEl", pos: [0, 0, 0] },
    { name: "r_wrist", joint: "rEl", pos: [0, -d.foreArm, 0] },
    { name: "l_shoulder", joint: "lSh", pos: [0, 0, 0] },
    { name: "l_elbow", joint: "lEl", pos: [0, 0, 0] },
    { name: "l_wrist", joint: "lEl", pos: [0, -d.foreArm, 0] },
    { name: "r_hip", joint: "rHip", pos: [0, 0, 0] },
    { name: "r_knee", joint: "rKn", pos: [0, 0, 0] },
    { name: "r_ankle", joint: "rKn", pos: [0, -d.leg * 0.5 + 0.04, 0] },
    { name: "l_hip", joint: "lHip", pos: [0, 0, 0] },
    { name: "l_knee", joint: "lKn", pos: [0, 0, 0] },
    { name: "l_ankle", joint: "lKn", pos: [0, -d.leg * 0.5 + 0.04, 0] },
    { name: "r_eye", joint: "head", pos: [-h * 0.38, h * 1.18, h * 0.86] },
    { name: "l_eye", joint: "head", pos: [h * 0.38, h * 1.18, h * 0.86] },
    { name: "r_ear", joint: "head", pos: [-h * 0.97, h * 1.05, 0] },
    { name: "l_ear", joint: "head", pos: [h * 0.97, h * 1.05, 0] },
  ];
}
