/**
 * 3D-BOX 场景文档：场景脚本跑完的产物。
 *
 * 前端只渲染它、不执行脚本；脚本只在后端的沙箱里跑（ainer-core/app/scene3d）。
 * 坐标：Y 向上，单位米，地面 y=0；物体 yaw 0 面向 +Z，yaw 90 面向 +X。
 */

export type Vec3 = [number, number, number];
export type Vec2 = [number, number];

export type Sky = "day" | "dawn" | "dusk" | "night" | "overcast" | "studio";
export type GroundKind = "grid" | "asphalt" | "grass" | "sand" | "snow" | "water" | "stone" | "floor" | "dirt";

export interface Environment {
  sky: Sky;
  ground: GroundKind;
  groundSize: number;
  /** 0–1，越大越雾 */
  fog: number;
}

export interface LightDef {
  id: string;
  name: string;
  kind: "sun" | "point" | "spot" | "ambient";
  color: string;
  intensity: number;
  at?: Vec3;
  /** 太阳光的照射方向（从光源指向地面） */
  dir?: Vec3;
  range?: number;
}

/** rot 是欧拉角（度，XYZ 顺序）；绝大多数物体只用 y（朝向）。 */
export interface Transform {
  pos: Vec3;
  rot: Vec3;
  scale: Vec3;
}

export interface MoveKey {
  t: number;
  pos?: Vec3;
  rot?: Vec3;
  scale?: Vec3;
}

export interface MoveTrack {
  keys: MoveKey[];
  /** smooth = 整段起步缓、收尾缓；中间匀速 */
  ease: "linear" | "smooth";
  /** curve = 过关键点的平滑曲线；linear = 折线 */
  path: "linear" | "curve";
  /** path = 车头／脸朝运动方向 */
  face: "path" | "none";
  /** 人物走/跑时摆臂迈腿；车辆轮子转 */
  action?: "walk" | "run" | "drive" | "fly" | "swim";
}

export interface PoseKey {
  t: number;
  pose: string;
}

/** 人物动作（动作库 scene/rig.ts 的 MOTIONS）：t 开始、duration 时长、target 出拳踢腿时面向谁 */
export interface ActionKey {
  t: number;
  name: string;
  duration: number;
  target?: string;
}

/**
 * 脚本里的语义动作：move_to、play_action、camera.follow……（Ainer Scene Protocol 的 timeline）。
 * 预览和渲染不读它（它们读算好的轨迹、动作）；给协议导出、UE 映射、智能体回看用。
 */
export interface TimelineOp {
  op: string;
  t: number;
  [k: string]: unknown;
}

export type PrimKind = "box" | "sphere" | "cylinder" | "cone" | "plane" | "torus" | "capsule" | "prism";

export type ParamValue = number | string | boolean;

export interface SceneObject {
  id: string;
  name: string;
  kind: "prefab" | "prim" | "character" | "group" | "strip";
  prefab?: string;
  prim?: PrimKind;
  params: Record<string, ParamValue>;
  color?: string;
  parent?: string;
  transform: Transform;
  track?: MoveTrack;
  /** 人物：体型与姿势 */
  body?: string;
  poses?: PoseKey[];
  /** 人物：动作片段（出拳、闪避、倒地……） */
  actions?: ActionKey[];
  /** 关联的角色（角色库里的实体 id） */
  ref?: string;
  /** 局部包围盒（未缩放，米） */
  size: Vec3;
  /** 道路、河流：地面上的带状物 */
  strip?: { points: Vec2[]; width: number; kind: string; lines: boolean };
  tags: string[];
}

/**
 * 机位关键帧。位置三选一：
 *   at            世界坐标
 *   follow+offset 跟着目标走：目标局部系（x 目标的右手、y 上、z 目标前方）
 *   orbit+angle   绕目标：angle 0 = 目标正面、90 = 目标右侧、180 = 背后；radius 水平距离；height 离地高
 * look：点、物体 id，或 {target, offset}；不给就看跟随/环绕的目标。
 */
export interface CamKey {
  t: number;
  at?: Vec3;
  follow?: string;
  offset?: Vec3;
  orbit?: string;
  angle?: number;
  radius?: number;
  height?: number;
  look?: Vec3 | string | { target: string; offset?: Vec3 };
  lens?: number;
  roll?: number;
}

export interface CameraDef {
  id: string;
  name: string;
  lens: number;
  keys: CamKey[];
  ease: "linear" | "smooth";
  path: "linear" | "curve";
  /** 手持晃动 0–1 */
  shake: number;
  /** 用过的运镜预设（给人看） */
  presets: string[];
}

export interface Cut {
  t: number;
  camera: string;
}

export interface SceneDoc {
  version: 1;
  duration: number;
  fps: number;
  aspect: number;
  seed: number;
  env: Environment;
  lights: LightDef[];
  objects: SceneObject[];
  cameras: CameraDef[];
  /** 主机位时间表：t 秒起切到哪台机位 */
  cuts: Cut[];
  notes: string[];
  /** 语义时间线（见 TimelineOp） */
  timeline?: TimelineOp[];
}

/** 导演台上的手动改动：只存与脚本不同的部分，脚本重跑后按 id 覆盖回去。 */
export interface Overrides {
  objects?: Record<string, { pos?: Vec3; rot?: Vec3; scale?: Vec3; color?: string; hidden?: boolean }>;
  cameras?: Record<string, { keys?: CamKey[]; lens?: number; ease?: "linear" | "smooth"; path?: "linear" | "curve" }>;
  cuts?: Cut[];
}

export interface SceneSummary {
  duration: number;
  objects: number;
  counts: Record<string, number>;
  bounds: { min: Vec2; max: Vec2 };
  characters: { id: string; name: string; body: string; from: Vec3; to: Vec3; action?: string }[];
  vehicles: { id: string; name: string; from: Vec3; to: Vec3 }[];
  cameras: { id: string; name: string; keys: number; span: [number, number]; kinds: string[]; presets: string[] }[];
  cuts: Cut[];
  /** 俯视字符地图：北（-Z）在上 */
  map: string;
  notes: string[];
}

export interface Diagnostics {
  ok: boolean;
  errors: { line?: number; col?: number; message: string }[];
  warnings: string[];
  summary: SceneSummary | null;
}
