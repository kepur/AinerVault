/**
 * 场景脚本运行时：LLM（或人）写的 scene.js 通过这里的 S / V 搭场景。
 *
 * 在后端的 vm 沙箱里执行（见 ainer-core/app/scene3d/runner.mjs）：
 * 没有 DOM、没有网络、没有 eval；Math.random 换成按 seed 可复现的随机数。
 * finish() 产出 SceneDoc（前端渲染）和诊断（报错、警告、概要＋俯视字符地图，回给智能体）。
 */
import type {
  CamKey, CameraDef, Cut, Diagnostics, Environment, GroundKind, LightDef, MoveKey, MoveTrack, Overrides,
  ParamValue, PrimKind, SceneDoc, SceneObject, SceneSummary, Sky, TimelineOp, Vec2, Vec3,
} from "./types";
import { BODIES, POSES, PREFABS, partsBounds, prefabDefaults } from "./prefabs";
import { CAMERA_PRESETS, PRESET_IDS, shotDistance } from "./cameraPresets";
import { localPose, SceneEval } from "./evaluate";
import { MOTION_IDS, MOTIONS } from "./rig";
import * as M from "./math";

export class SceneError extends Error {}

type Handle = { readonly id: string; readonly name: string; readonly kind: string };
type Ref = Handle | string;
type Pos = Vec2 | Vec3;

const MAX_OBJECTS = 5000;
/** 会「朝运动方向」的东西：车、船、动物 */
const STEERED = new Set(["car", "police_car", "truck", "bus", "motorcycle", "bicycle", "boat", "horse", "horse_cart", "helicopter", "bird", "dog", "cart"]);
const SKIES: Sky[] = ["day", "dawn", "dusk", "night", "overcast", "studio"];
const GROUNDS: GroundKind[] = ["grid", "asphalt", "grass", "sand", "snow", "water", "stone", "floor", "dirt"];
const ACTIONS = ["walk", "run", "drive", "fly", "swim"] as const;

function editDistance(a: string, b: string) {
  const dp = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++)
    for (let j = 1; j <= b.length; j++)
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return dp[a.length][b.length];
}

function suggest(name: string, pool: string[], extra?: Record<string, string>) {
  const scored = pool.map(p => ({ p, d: editDistance(name.toLowerCase(), p.toLowerCase()) }));
  if (extra) for (const [k, zh] of Object.entries(extra)) if (zh && (zh.includes(name) || name.includes(zh))) scored.push({ p: k, d: -1 });
  scored.sort((a, b) => a.d - b.d);
  return scored.slice(0, 3).map(x => x.p);
}

export function makeBuilder(opts: { seed?: number; overrides?: Overrides } = {}) {
  const seed = Math.floor(opts.seed ?? 1);
  const random = M.rng(seed);
  const objects: SceneObject[] = [];
  const byId = new Map<string, SceneObject>();
  const cameras: CameraDef[] = [];
  const cuts: Cut[] = [];
  const lights: LightDef[] = [];
  const notes: string[] = [];
  const warnings: string[] = [];
  const presetJobs: { cam: CameraDef; preset: string; opts: Record<string, unknown> }[] = [];
  /** 语义时间线：每个动画调用记一条（协议导出、UE 映射用） */
  const timeline: TimelineOp[] = [];
  const counters = new Map<string, number>();
  let env: Environment = { sky: "day", ground: "grid", groundSize: 120, fog: 0 };
  let duration: number | null = null;
  let fps = 24;
  let aspect = 16 / 9;

  // ── 参数检查：报错要说清哪个函数、哪个参数、给了什么 ──

  const fail = (where: string, msg: string): never => { throw new SceneError(`${where}：${msg}`); };
  const num = (v: unknown, where: string, what: string, dflt?: number): number => {
    if (v === undefined || v === null) {
      if (dflt !== undefined) return dflt;
      fail(where, `缺少 ${what}`);
    }
    if (typeof v !== "number" || !Number.isFinite(v)) fail(where, `${what} 必须是数字，收到 ${JSON.stringify(v)}`);
    return v as number;
  };
  const vec = (v: unknown, where: string, what: string, dflt?: Vec3): Vec3 => {
    if (v === undefined || v === null) {
      if (dflt) return dflt;
      fail(where, `缺少 ${what}`);
    }
    if (!Array.isArray(v) || (v.length !== 2 && v.length !== 3) || !v.every(x => typeof x === "number" && Number.isFinite(x)))
      fail(where, `${what} 要写成 [x, z] 或 [x, y, z]（米），收到 ${JSON.stringify(v)}`);
    return M.v2to3(v as Pos);
  };
  const rot = (v: unknown, where: string, dflt: Vec3 = [0, 0, 0]): Vec3 => {
    if (v === undefined || v === null) return dflt;
    if (typeof v === "number") return [0, num(v, where, "rot"), 0];
    if (Array.isArray(v) && v.length === 3) return [num(v[0], where, "rot[0]"), num(v[1], where, "rot[1]"), num(v[2], where, "rot[2]")];
    return fail(where, `rot 要写成朝向角度（数字，0 = 面向 +Z）或 [x, y, z]，收到 ${JSON.stringify(v)}`);
  };
  const scl = (v: unknown, where: string): Vec3 => {
    if (v === undefined || v === null) return [1, 1, 1];
    if (typeof v === "number") return [v, v, v];
    if (Array.isArray(v) && v.length === 3) return [num(v[0], where, "scale[0]"), num(v[1], where, "scale[1]"), num(v[2], where, "scale[2]")];
    return fail(where, `scale 要写成数字或 [x, y, z]`);
  };
  const color = (v: unknown, where: string): string | undefined => {
    if (v === undefined || v === null) return undefined;
    if (typeof v !== "string" || !/^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(v)) fail(where, `color 要写成 "#rrggbb"，收到 ${JSON.stringify(v)}`);
    return v as string;
  };
  const get = (r: Ref | undefined, where: string): SceneObject => {
    if (r === undefined || r === null) return fail(where, "缺少目标（物体句柄或 id）");
    const id = typeof r === "string" ? r : r.id;
    const o = byId.get(id) ?? objects.find(x => x.name === id);
    if (!o) {
      const cam = cameras.find(c => c.id === id);
      if (cam) fail(where, `「${id}」是机位，这里要的是物体`);
      fail(where, `找不到物体「${id}」。已有的：${objects.slice(0, 12).map(o => o.id).join("、")}${objects.length > 12 ? "…" : ""}`);
    }
    return o as SceneObject;
  };
  const cam = (r: Ref | undefined, where: string): CameraDef => {
    const id = typeof r === "string" ? r : r?.id;
    const c = cameras.find(c => c.id === id || c.name === id);
    if (!c) return fail(where, `找不到机位「${id}」，先用 S.camera(名字) 建一个`);
    return c;
  };

  function newId(base: string, explicit?: unknown): string {
    if (typeof explicit === "string" && explicit) {
      if (byId.has(explicit) || cameras.some(c => c.id === explicit)) fail("id", `「${explicit}」重复了，id 要唯一`);
      return explicit;
    }
    const k = (counters.get(base) ?? 0) + 1;
    counters.set(base, k);
    let id = k === 1 ? base : `${base}#${k}`;
    while (byId.has(id)) id += "'";
    return id;
  }

  function handle(o: { id: string; name: string }, kind: string): Handle {
    return Object.freeze({ id: o.id, name: o.name, kind });
  }

  function push(o: SceneObject): Handle {
    if (objects.length >= MAX_OBJECTS) fail("物体数量", `超过上限 ${MAX_OBJECTS} 个。批量摆放时减少 count，或用更大的预制件`);
    objects.push(o);
    byId.set(o.id, o);
    return handle(o, o.kind);
  }

  const known = new Set(["at", "rot", "scale", "color", "name", "id", "parent", "tags"]);

  function place(kind: SceneObject["kind"], opts: Record<string, unknown>, where: string, extra: Partial<SceneObject>): Handle {
    const name = typeof opts.name === "string" && opts.name ? opts.name : (extra.prefab ?? extra.prim ?? kind);
    const parent = opts.parent !== undefined ? get(opts.parent as Ref, where).id : undefined;
    const o: SceneObject = {
      id: newId(typeof opts.name === "string" && opts.name ? opts.name : name, opts.id),
      name, kind, params: {}, parent,
      color: color(opts.color, where),
      transform: { pos: vec(opts.at, where, "at", [0, 0, 0]), rot: rot(opts.rot, where), scale: scl(opts.scale, where) },
      size: [1, 1, 1],
      tags: Array.isArray(opts.tags) ? (opts.tags as unknown[]).map(String) : [],
      ...extra,
    };
    return push(o);
  }

  // ── S：搭场景 ──────────────────────────────────────────

  const S = {
    /** 时长（秒）、画幅（"16:9"｜"9:16"｜"2.39:1"｜数字）、帧率 */
    setup(o: { duration?: number; aspect?: string | number; fps?: number } = {}) {
      if (o.duration !== undefined) duration = M.clamp(num(o.duration, "S.setup", "duration"), 1, 180);
      if (o.fps !== undefined) fps = M.clamp(Math.round(num(o.fps, "S.setup", "fps")), 12, 60);
      if (o.aspect !== undefined) {
        if (typeof o.aspect === "number") aspect = o.aspect;
        else {
          const m = /^(\d+(?:\.\d+)?)\s*[:：x×]\s*(\d+(?:\.\d+)?)$/.exec(String(o.aspect));
          if (!m) fail("S.setup", `aspect 写成 "16:9" 这样，收到 ${JSON.stringify(o.aspect)}`);
          aspect = Number(m![1]) / Number(m![2]);
        }
      }
    },

    /** 天空、地面、雾 */
    environment(o: { sky?: Sky; ground?: GroundKind; groundSize?: number; fog?: number } = {}) {
      if (o.sky !== undefined && !SKIES.includes(o.sky)) fail("S.environment", `sky 只能是 ${SKIES.join(" / ")}`);
      if (o.ground !== undefined && !GROUNDS.includes(o.ground)) fail("S.environment", `ground 只能是 ${GROUNDS.join(" / ")}`);
      env = {
        sky: o.sky ?? env.sky, ground: o.ground ?? env.ground,
        groundSize: M.clamp(num(o.groundSize, "S.environment", "groundSize", env.groundSize), 10, 2000),
        fog: M.clamp(num(o.fog, "S.environment", "fog", env.fog), 0, 1),
      };
    },

    /** 灯光：sun 太阳（dir 照射方向）、point 点光（at、range）、spot 聚光、ambient 环境光 */
    light(kind: LightDef["kind"], o: { at?: Pos; dir?: Vec3; color?: string; intensity?: number; range?: number; name?: string } = {}) {
      if (!["sun", "point", "spot", "ambient"].includes(kind)) fail("S.light", `kind 只能是 sun / point / spot / ambient`);
      const l: LightDef = {
        id: newId(o.name ?? `light-${kind}`), name: o.name ?? kind, kind,
        color: color(o.color, "S.light") ?? "#ffffff",
        intensity: num(o.intensity, "S.light", "intensity", kind === "ambient" ? 0.4 : 1),
        at: o.at ? vec(o.at, "S.light", "at") : undefined,
        dir: o.dir ? vec(o.dir, "S.light", "dir") : undefined,
        range: o.range !== undefined ? num(o.range, "S.light", "range") : undefined,
      };
      lights.push(l);
      return handle(l, "light");
    },

    /** 放一个预制件（见目录）。其余键是预制件参数，比如 S.add("house", {at:[0,-10], floors:2, style:"ancient"}) */
    add(prefab: string, o: Record<string, unknown> = {}) {
      const where = `S.add("${prefab}")`;
      const def = PREFABS[prefab];
      if (!def) {
        const zh: Record<string, string> = Object.fromEntries(Object.entries(PREFABS).map(([k, v]) => [k, v.zh]));
        fail(where, `没有这个预制件。最接近的：${suggest(prefab, Object.keys(PREFABS), zh).join("、")}。完整目录用 prefabs 工具看`);
      }
      const params: Record<string, ParamValue> = { ...prefabDefaults(prefab) };
      for (const [k, v] of Object.entries(o)) {
        if (known.has(k)) continue;
        if (!(k in (def.params ?? {}))) {
          warnings.push(`${where}：参数「${k}」不认识（可用：${Object.keys(def.params ?? {}).join("、") || "无"}），已忽略`);
          continue;
        }
        const spec = def.params![k];
        if (spec.options && !spec.options.includes(String(v))) fail(where, `${k} 只能是 ${spec.options.join(" / ")}，收到 ${JSON.stringify(v)}`);
        if (typeof spec.default === "number" && (typeof v !== "number" || !Number.isFinite(v))) fail(where, `${k} 要是数字，收到 ${JSON.stringify(v)}`);
        params[k] = v as ParamValue;
      }
      const bb = partsBounds(def.build(params));
      return place("prefab", o, where, { prefab, params, size: M.sub(bb.max, bb.min) as Vec3 });
    },

    /** 基本体：box{size:[w,h,d]}、sphere{r}、cylinder{r,h}、cone{r,h}、plane{size:[w,d]}、torus{r,tube} */
    box: (o: Record<string, unknown> = {}) => prim("box", o),
    sphere: (o: Record<string, unknown> = {}) => prim("sphere", o),
    cylinder: (o: Record<string, unknown> = {}) => prim("cylinder", o),
    cone: (o: Record<string, unknown> = {}) => prim("cone", o),
    plane: (o: Record<string, unknown> = {}) => prim("plane", o),
    torus: (o: Record<string, unknown> = {}) => prim("torus", o),

    /** 空组：把东西挂进去一起移动（其它函数的 parent 参数） */
    group(name: string, o: Record<string, unknown> = {}) {
      return place("group", { ...o, name }, `S.group("${name}")`, { size: [0, 0, 0] });
    },

    /** 人物：body 体型、pose 姿势、facing 朝向（角度、点或物体） */
    character(name: string, o: Record<string, unknown> = {}) {
      const where = `S.character("${name}")`;
      const body = String(o.body ?? "male");
      if (!(body in BODIES)) fail(where, `body 只能是 ${Object.keys(BODIES).join(" / ")}`);
      const pose = String(o.pose ?? "stand");
      if (!(pose in POSES)) fail(where, `pose 只能是 ${Object.keys(POSES).join(" / ")}`);
      const at = vec(o.at, where, "at", [0, 0, 0]);
      let r = rot(o.rot, where);
      if (o.facing !== undefined) r = [0, facingYaw(o.facing, at, where), 0];
      const h = o.height !== undefined ? num(o.height, where, "height") : BODIES[body].height;
      const hdl = place("character", { ...o, name, at, rot: r }, where, {
        body, poses: [{ t: 0, pose }], ref: typeof o.ref === "string" ? o.ref : undefined,
        size: [0.5 * BODIES[body].width, h, 0.3],
      });
      return hdl;
    },

    /** 人物在 t 秒时换姿势（到下一次换之前一直保持） */
    pose(who: Ref, pose: string, t = 0) {
      const o = get(who, "S.pose");
      if (o.kind !== "character") fail("S.pose", `「${o.id}」不是人物`);
      if (!(pose in POSES)) fail("S.pose", `pose 只能是 ${Object.keys(POSES).join(" / ")}`);
      o.poses = [...(o.poses ?? []).filter(p => Math.abs(p.t - t) > 1e-6), { t: num(t, "S.pose", "t"), pose }].sort((a, b) => a.t - b.t);
      timeline.push({ op: "actor.set_pose", t, actor: o.id, pose });
    },

    /**
     * 人物动作（动作库）：right_punch 右直拳、left_punch、front_kick 前踢、dodge_left/right 闪避、block_high 格挡、
     * hit_react_back 受击后仰、hit_react_left、fall_backward 倒地、stand_up 起身、look_back 回头、turn_left/right 转身、
     * walk_forward/run_forward 向前走跑、idle 待机。t 开始（秒）、duration 时长、target 出拳踢腿时面向谁
     */
    action(who: Ref, name: string, o: { t?: number; duration?: number; target?: Ref } = {}) {
      const where = `S.action("${name}")`;
      const obj = get(who, where);
      if (obj.kind !== "character") fail(where, `「${obj.id}」不是人物，动作只给人物用`);
      const def = MOTIONS[name];
      if (!def) {
        // 动作库就十几个：全列出来（带中文），比按拼写猜「最接近的」有用 —— uppercut 猜出来是 idle
        const zh = Object.fromEntries(Object.entries(MOTIONS).map(([k, m]) => [k, m.zh]));
        const near = suggest(name, MOTION_IDS, zh).filter(k => zh[k] && (zh[k].includes(name) || name.includes(zh[k])));
        fail(where, `没有这个动作${near.length ? `（是不是 ${near.join("、")}？）` : ""}。动作库：${MOTION_IDS.filter(k => k !== "turn_to").map(k => `${k} ${zh[k]}`).join("、")}`);
      }
      const t0 = num(o.t, where, "t", 0);
      const dur = num(o.duration, where, "duration", def.duration);
      if (dur <= 0) fail(where, "duration 要大于 0");
      let target: string | undefined;
      if (def.locomotion) {
        const here = localPose(obj, t0);
        const dest = M.add(here.pos, M.scale(M.forwardOf(here.rot[1]), def.locomotion.speed * dur));
        appendMove(obj, t0, dest, { duration: dur, action: def.locomotion.action }, where);
      } else {
        target = o.target !== undefined ? get(o.target, where).id : undefined;
        if (target === obj.id) fail(where, "target 不能是自己");
        obj.actions = [...(obj.actions ?? []), { t: t0, name, duration: dur, ...(target ? { target } : {}) }].sort((a, b) => a.t - b.t);
      }
      timeline.push({ op: "actor.play_action", t: t0, actor: obj.id, action: name, duration: dur, ...(target ? { target_actor: target } : {}) });
    },

    /** 走到／跑到某处：to 目的地，t 出发时间，duration 或 speed（米/秒），action walk｜run。可以连着写好几段 */
    moveTo(what: Ref, to: Pos, o: { t?: number; duration?: number; speed?: number; action?: string; face?: string } = {}) {
      const where = "S.moveTo";
      const obj = get(what, where);
      const t0 = num(o.t, where, "t", 0);
      const dest = vec(to, where, "to");
      const dur = appendMove(obj, t0, dest, o, where);
      timeline.push({ op: `${roleOf(obj)}.move_to`, t: t0, [roleOf(obj)]: obj.id, to: dest, duration: +dur.toFixed(3), action: obj.track?.action });
    },

    /** 转身面向目标（人或物），t 开始，duration 默认 0.5 秒 */
    face(who: Ref, target: Ref, o: { t?: number; duration?: number } = {}) {
      const where = "S.face";
      const obj = get(who, where);
      if (obj.kind !== "character") fail(where, `「${obj.id}」不是人物`);
      const tg = get(target, where);
      const t0 = num(o.t, where, "t", 0);
      const dur = num(o.duration, where, "duration", MOTIONS.turn_to.duration);
      obj.actions = [...(obj.actions ?? []), { t: t0, name: "turn_to", duration: dur, target: tg.id }].sort((a, b) => a.t - b.t);
      timeline.push({ op: "actor.look_at", t: t0, actor: obj.id, target_actor: tg.id, duration: dur });
    },

    // ── 批量摆放 ──

    /** 从 from 到 to 等距摆一排 */
    row(prefab: string, o: Record<string, unknown> & { from: Pos; to: Pos; count: number }) {
      const where = `S.row("${prefab}")`;
      const a = vec(o.from, where, "from"), b = vec(o.to, where, "to");
      const n = Math.round(num(o.count, where, "count"));
      if (n < 1 || n > 500) fail(where, "count 要在 1–500 之间");
      const out: Handle[] = [];
      for (let i = 0; i < n; i++) {
        const u = n === 1 ? 0.5 : i / (n - 1);
        out.push(S.add(prefab, { ...jitter(o, M.lerp3(a, b, u), where), ...(o.facing !== undefined ? { rot: facingYaw(o.facing, M.lerp3(a, b, u), where) } : {}) }));
      }
      return out;
    },

    /** 网格摆放：center 中心、cols×rows、spacing:[dx, dz] */
    grid(prefab: string, o: Record<string, unknown> & { cols: number; rows: number; spacing: number | Vec2 }) {
      const where = `S.grid("${prefab}")`;
      const c = vec(o.center, where, "center", [0, 0, 0]);
      const cols = Math.round(num(o.cols, where, "cols")), rows = Math.round(num(o.rows, where, "rows"));
      if (cols * rows > 1000) fail(where, "cols × rows 不能超过 1000");
      const sp = typeof o.spacing === "number" ? [o.spacing, o.spacing] : (o.spacing as number[] | undefined) ?? [4, 4];
      const out: Handle[] = [];
      for (let i = 0; i < cols; i++)
        for (let j = 0; j < rows; j++) {
          const p: Vec3 = [c[0] + (i - (cols - 1) / 2) * sp[0], c[1], c[2] + (j - (rows - 1) / 2) * sp[1]];
          out.push(S.add(prefab, jitter(o, p, where)));
        }
      return out;
    },

    /** 在矩形区域 area:[x0, z0, x1, z1] 里随机撒 count 个，minGap 最小间距，avoid 避开的矩形 */
    scatter(prefab: string, o: Record<string, unknown> & { area: [number, number, number, number]; count: number }) {
      const where = `S.scatter("${prefab}")`;
      const area = o.area;
      if (!Array.isArray(area) || area.length !== 4) fail(where, "area 要写成 [x0, z0, x1, z1]");
      const n = Math.round(num(o.count, where, "count"));
      if (n > 800) fail(where, "count 不能超过 800");
      const gap = num(o.minGap, where, "minGap", 1.5);
      const avoid = (Array.isArray(o.avoid) ? o.avoid : []) as number[][];
      const pts: Vec3[] = [];
      let tries = 0;
      while (pts.length < n && tries < n * 40) {
        tries++;
        const x = M.lerp(Math.min(area[0], area[2]), Math.max(area[0], area[2]), random());
        const z = M.lerp(Math.min(area[1], area[3]), Math.max(area[1], area[3]), random());
        if (avoid.some(r => x >= Math.min(r[0], r[2]) && x <= Math.max(r[0], r[2]) && z >= Math.min(r[1], r[3]) && z <= Math.max(r[1], r[3]))) continue;
        if (pts.some(p => Math.hypot(p[0] - x, p[2] - z) < gap)) continue;
        pts.push([x, 0, z]);
      }
      if (pts.length < n) warnings.push(`${where}：区域太挤，只放下了 ${pts.length}/${n} 个（加大 area 或减小 minGap）`);
      return pts.map(p => S.add(prefab, { ...jitter({ ...o, rotJitter: o.rotJitter ?? 180 }, p, where) }));
    },

    /** 沿路径每隔 spacing 放一个；side：left/right/both，offset 离路中线距离；facing：path 顺路／in 朝路／out 背路 */
    along(prefab: string, o: Record<string, unknown> & { path: Pos[]; spacing: number }) {
      const where = `S.along("${prefab}")`;
      if (!Array.isArray(o.path) || o.path.length < 2) fail(where, "path 至少两个点 [[x,z], [x,z], …]");
      const pts = (o.path as Pos[]).map((p, i) => vec(p, where, `path[${i}]`));
      const spacing = num(o.spacing, where, "spacing");
      if (spacing <= 0.2) fail(where, "spacing 太小");
      const side = String(o.side ?? "both");
      const off = num(o.offset, where, "offset", 0);
      const facing = String(o.facing ?? "in");
      const total = M.polyLength(pts);
      const out: Handle[] = [];
      for (let s = spacing / 2; s <= total; s += spacing) {
        const { p, dir } = M.samplePoly(pts, s);
        const yawPath = (Math.atan2(dir[0], dir[2]) * 180) / Math.PI;
        const sides = side === "both" ? [-1, 1] : side === "left" ? [-1] : side === "right" ? [1] : [0];
        for (const sd of sides) {
          // 路的左手 = 沿行进方向的左边
          const right = M.rightOf(yawPath);
          const q = M.add(p, M.scale(right, sd * off));
          let yaw = yawPath;
          if (facing === "in") yaw = sd === 0 ? yawPath : yawPath + (sd > 0 ? -90 : 90);
          else if (facing === "out") yaw = sd === 0 ? yawPath : yawPath + (sd > 0 ? 90 : -90);
          out.push(S.add(prefab, jitter({ ...o, rot: yaw }, q, where)));
          if (out.length > 600) fail(where, "摆放数量超过 600，加大 spacing");
        }
      }
      return out;
    },

    /** 道路、河流：地面上的带子。kind：asphalt 柏油、stone 石板、dirt 土路、water 水面；lines 画中线 */
    road(o: { path: Pos[]; width?: number; kind?: string; lines?: boolean; name?: string }) {
      const where = "S.road";
      if (!Array.isArray(o.path) || o.path.length < 2) fail(where, "path 至少两个点");
      const pts = o.path.map((p, i) => vec(p, where, `path[${i}]`));
      const kind = String(o.kind ?? "asphalt");
      if (!["asphalt", "stone", "dirt", "water", "grass", "sand"].includes(kind)) fail(where, "kind 只能是 asphalt / stone / dirt / water / grass / sand");
      const w = num(o.width, where, "width", 8);
      const xs = pts.map(p => p[0]), zs = pts.map(p => p[2]);
      return place("strip", { name: o.name ?? (kind === "water" ? "河" : "路") }, where, {
        strip: { points: pts.map(p => [p[0], p[2]] as Vec2), width: w, kind, lines: o.lines ?? kind === "asphalt" },
        size: [Math.max(...xs) - Math.min(...xs) + w, 0.05, Math.max(...zs) - Math.min(...zs) + w],
      });
    },

    // ── 动画 ──

    /** 关键帧移动：keys = [{t, at, rot?, scale?}, …]；face:"path" 朝运动方向；action：walk/run/drive/fly/swim */
    move(what: Ref, keys: { t: number; at?: Pos; rot?: number | Vec3; scale?: number | Vec3 }[], o: Record<string, unknown> = {}) {
      const where = "S.move";
      const obj = get(what, where);
      if (!Array.isArray(keys) || !keys.length) fail(where, "keys 至少一个 {t, at}");
      const mk: MoveKey[] = keys.map((k, i) => ({
        t: num(k.t, where, `keys[${i}].t`),
        pos: k.at !== undefined ? vec(k.at, where, `keys[${i}].at`) : undefined,
        rot: k.rot !== undefined ? rot(k.rot, where) : undefined,
        scale: k.scale !== undefined ? scl(k.scale, where) : undefined,
      }));
      // 第一帧之前物体停在第一帧的位置；第一帧没写 at 的，从摆放位置出发（见 track）
      obj.track = track(obj, mk, o, where);
      timeline.push({ op: `${roleOf(obj)}.move`, t: obj.track.keys[0].t, [roleOf(obj)]: obj.id,
        keys: obj.track.keys.map(k => ({ t: k.t, at: k.pos, rot: k.rot })), action: obj.track.action });
    },

    /** 沿路径匀速走：path 点列、start 开始时间、speed（米/秒）或 duration */
    moveAlong(what: Ref, o: Record<string, unknown> & { path: Pos[] }) {
      const where = "S.moveAlong";
      const obj = get(what, where);
      if (!Array.isArray(o.path) || o.path.length < 2) fail(where, "path 至少两个点");
      let pts = (o.path as Pos[]).map((p, i) => vec(p, where, `path[${i}]`));
      if (o.curve !== false && pts.length > 2) pts = M.smoothPath(pts, 6);
      const start = num(o.start, where, "start", 0);
      const total = M.polyLength(pts);
      const dflt = obj.kind === "character" ? (o.action === "run" ? 4.5 : 1.4) : 12;
      let dur: number;
      if (o.duration !== undefined) dur = num(o.duration, where, "duration");
      else dur = total / num(o.speed, where, "speed", dflt);
      if (dur <= 0) fail(where, "duration 要大于 0");
      const keys: MoveKey[] = [];
      let acc = 0;
      for (let i = 0; i < pts.length; i++) {
        if (i) acc += M.dist(pts[i - 1], pts[i]);
        keys.push({ t: start + (total > 0 ? (acc / total) * dur : 0), pos: pts[i] });
      }
      obj.transform = { ...obj.transform, pos: pts[0] };
      // 这里的 o.path 是点列，不是插值方式：路径已经加密过，按折线走
      obj.track = track(obj, keys, { face: o.face ?? "path", ease: o.ease ?? "linear", path: "linear", action: o.action }, where);
      timeline.push({ op: `${roleOf(obj)}.move_along`, t: start, [roleOf(obj)]: obj.id,
        path: (o.path as Pos[]).map((p, i) => vec(p, where, `path[${i}]`)), duration: +dur.toFixed(3), action: obj.track.action });
    },

    // ── 机位 ──

    /** 建一台机位：lens 焦段（mm） */
    camera(name: string, o: { lens?: number; shake?: number; id?: string } = {}) {
      const c: CameraDef = {
        id: newId(name || "机位", o.id), name: name || "机位", lens: M.clamp(num(o.lens, "S.camera", "lens", 35), 8, 300),
        keys: [], ease: "smooth", path: "curve", shake: M.clamp(num(o.shake, "S.camera", "shake", 0), 0, 1), presets: [],
      };
      cameras.push(c);
      return handle(c, "camera");
    },

    /**
     * 机位关键帧。每个关键帧位置三选一：
     *   {t, at:[x,y,z], look}                        世界坐标
     *   {t, follow:目标, offset:[右, 上, 前]}          跟着目标走（目标自己的坐标系）
     *   {t, orbit:目标, angle, radius, height}         绕目标（angle 0 正面、90 目标右侧、180 背后）
     * look：点、物体，或 {target, offset}；跟随/环绕时默认看目标
     */
    cameraKeys(which: Ref, keys: CamKey[], o: { ease?: "linear" | "smooth"; path?: "linear" | "curve" } = {}) {
      const where = "S.cameraKeys";
      const c = cam(which, where);
      if (!Array.isArray(keys) || !keys.length) fail(where, "keys 至少一个");
      const norm = keys.map((k, i) => normKey(k as unknown as Record<string, unknown>, `${where} keys[${i}]`));
      for (const k of norm) addKey(c, k);
      if (o.ease) c.ease = o.ease;
      if (o.path) c.path = o.path;
      timeline.push({ op: "camera.keys", t: Math.min(...norm.map(k => k.t)), camera: c.id, keys: norm });
    },

    /** 跟拍：mode = back 背跟／front 正面跟／side 侧跟／top 顶拍／first 第一视角 */
    cameraFollow(which: Ref, target: Ref, o: { mode?: string; distance?: number; height?: number; side?: number; start?: number; end?: number; lens?: number } = {}) {
      const where = "S.cameraFollow";
      const c = cam(which, where);
      const t = get(target, where);
      const mode = String(o.mode ?? "back");
      const d = num(o.distance, where, "distance", t.kind === "character" ? 4 : 8);
      const h = num(o.height, where, "height", t.kind === "character" ? 1.8 : 2.8);
      const side = Math.sign(num(o.side, where, "side", 1)) || 1;
      const offsets: Record<string, Vec3> = {
        back: [0, h, -d], front: [0, h, d], side: [side * d, h, 0], top: [0, h + d * 2.5, -0.1],
        first: [0, t.size[1] * 0.93, 0.2],
      };
      if (!(mode in offsets)) fail(where, `mode 只能是 ${Object.keys(offsets).join(" / ")}`);
      const s0 = num(o.start, where, "start", 0);
      const s1 = o.end !== undefined ? num(o.end, where, "end") : null;
      const look = mode === "first" ? { target: t.id, offset: [0, t.size[1] * 0.9, 12] as Vec3 } : undefined;
      addKey(c, { t: s0, follow: t.id, offset: offsets[mode], lens: o.lens, look });
      addKey(c, { t: s1 ?? s0 + 0.001, follow: t.id, offset: offsets[mode], lens: o.lens, look, ...(s1 === null ? { __open: true } : {}) } as CamKey);
      c.ease = "linear";
      timeline.push({ op: "camera.follow", t: s0, camera: c.id, target_actor: t.id, style: mode, distance: d, height: h, side,
        ...(s1 !== null ? { duration: +(s1 - s0).toFixed(3) } : {}) });
    },

    /** 用预设运镜（见 camera_presets 目录）：target 目标、start/duration 时间段、side 1 右 -1 左、angle 起始角 */
    cameraPreset(which: Ref, preset: string, o: Record<string, unknown> = {}) {
      const where = `S.cameraPreset("${preset}")`;
      const c = cam(which, where);
      if (!PRESET_IDS.includes(preset)) {
        const zh = Object.fromEntries(CAMERA_PRESETS.map(p => [p.id, p.zh]));
        fail(where, `没有这个运镜预设。最接近的：${suggest(preset, PRESET_IDS, zh).join("、")}`);
      }
      if (o.target !== undefined && !Array.isArray(o.target)) get(o.target as Ref, where);
      presetJobs.push({ cam: c, preset, opts: o });
      c.presets.push(preset);
      const tg = o.target === undefined ? undefined : Array.isArray(o.target) ? o.target : get(o.target as Ref, where).id;
      timeline.push({ op: "camera.move", t: typeof o.start === "number" ? o.start : 0, camera: c.id, preset,
        ...(tg !== undefined ? { target: tg } : {}), duration: typeof o.duration === "number" ? o.duration : 4,
        ...(o.side !== undefined ? { side: o.side } : {}), ...(o.angle !== undefined ? { angle: o.angle } : {}) });
    },

    /** 景别取景：在 t 秒给机位一个对准 target 的关键帧。size：els/ws/fs/mls/ms/mcu/cu/ecu */
    frame(which: Ref, t: number, target: Ref, size: string, o: { angle?: number; height?: number; lens?: number } = {}) {
      const where = "S.frame";
      const c = cam(which, where);
      const obj = get(target, where);
      const lens = o.lens ?? c.lens;
      const sz = obj.kind === "character" ? obj.size[1] : Math.max(obj.size[0], obj.size[2]);
      const radius = shotDistance(size, { size: sz, lens });
      const aim = obj.kind === "character" ? obj.size[1] * 0.9 : Math.max(0.6, obj.size[1] * 0.55);
      addKey(c, { t: num(t, where, "t"), orbit: obj.id, angle: o.angle ?? 15, radius, height: o.height ?? aim, lens: o.lens });
      timeline.push({ op: "camera.frame", t, camera: c.id, target: obj.id, size, angle: o.angle ?? 15 });
    },

    /** 主机位时间表：从 t 秒起切到这台机位 */
    cut(t: number, which: Ref) {
      const c = cam(which, "S.cut");
      cuts.push({ t: Math.max(0, num(t, "S.cut", "t")), camera: c.id });
      timeline.push({ op: "camera.cut", t: Math.max(0, t), camera: c.id });
    },

    /** 给导演看的说明（会出现在场景概要里） */
    note(text: string) { notes.push(String(text).slice(0, 300)); },

    /** 按 id 或名字取回已建的物体 */
    get(id: string) { const o = get(id, "S.get"); return handle(o, o.kind); },

    /** 可复现的随机：rand(a, b) 均匀、pick(数组)、chance(p) */
    rand: (a = 0, b = 1) => M.lerp(a, b, random()),
    pick: <T,>(arr: T[]) => arr[Math.floor(random() * arr.length)],
    chance: (p: number) => random() < p,
  };

  function prim(kind: PrimKind, o: Record<string, unknown>): Handle {
    const where = `S.${kind}`;
    let size: Vec3;
    if (kind === "box") size = vec(o.size, where, "size", [1, 1, 1]);
    else if (kind === "plane") { const s2 = (o.size as number[] | undefined) ?? [4, 4]; size = [num(s2[0], where, "size[0]"), 0.02, num(s2[1], where, "size[1]")]; }
    else if (kind === "torus") { const r = num(o.r, where, "r", 1), tube = num(o.tube, where, "tube", 0.2); size = [r * 2, r * 2, tube * 2]; }
    else if (kind === "sphere") { const r = num(o.r, where, "r", 0.5); size = [r * 2, r * 2, r * 2]; }
    else { const r = num(o.r, where, "r", 0.5), h = num(o.h, where, "h", 1); size = [r * 2, h, r * 2]; }
    return place("prim", o, where, { prim: kind, size, params: { size: size.join(",") } });
  }

  function jitter(o: Record<string, unknown>, p: Vec3, where: string): Record<string, unknown> {
    const j = num(o.jitter, where, "jitter", 0);
    const rj = num(o.rotJitter, where, "rotJitter", 0);
    const sj = num(o.scaleJitter, where, "scaleJitter", 0);
    const out: Record<string, unknown> = { ...o };
    for (const k of ["from", "to", "count", "center", "cols", "rows", "spacing", "area", "minGap", "avoid", "jitter", "rotJitter", "scaleJitter", "path", "side", "offset", "facing", "name", "id"]) delete out[k];
    out.at = [p[0] + (j ? (random() - 0.5) * 2 * j : 0), p[1], p[2] + (j ? (random() - 0.5) * 2 * j : 0)];
    const baseYaw = typeof o.rot === "number" ? o.rot : Array.isArray(o.rot) ? (o.rot as number[])[1] : 0;
    if (rj) out.rot = baseYaw + (random() - 0.5) * 2 * rj;
    if (sj) out.scale = 1 + (random() - 0.5) * 2 * sj;
    return out;
  }

  function facingYaw(f: unknown, from: Vec3, where: string): number {
    if (typeof f === "number") return f;
    if (Array.isArray(f)) return M.yawTo(from, vec(f, where, "facing"));
    const o = get(f as Ref, where);
    return M.yawTo(from, o.transform.pos);
  }

  /** 协议里的角色：人、车、动物是 actor，其余是 prop */
  function roleOf(obj: SceneObject): "actor" | "prop" {
    return obj.kind === "character" || STEERED.has(obj.prefab ?? "") ? "actor" : "prop";
  }

  /**
   * 在已有轨迹上接一段「从 t0 此刻所在处 → dest」：这段时间里的旧关键帧作废，之前的保留，之后的原样保留。
   * 返回这段的时长。
   */
  function appendMove(obj: SceneObject, t0: number, dest: Vec3, o: Record<string, unknown>, where: string): number {
    const here = localPose(obj, t0).pos;
    const act = (o.action as string | undefined) ?? obj.track?.action ?? (obj.kind === "character" ? "walk" : undefined);
    const dist = M.dist(here, dest);
    const speed = num(o.speed, where, "speed", act === "run" ? 4.5 : obj.kind === "character" ? 1.4 : 10);
    const dur = o.duration !== undefined ? num(o.duration, where, "duration") : dist / Math.max(0.05, speed);
    if (dur <= 0) fail(where, "duration 要大于 0");
    const old = obj.track?.keys ?? [];
    const keys: MoveKey[] = [
      ...old.filter(k => k.t < t0 - 1e-6),
      { t: t0, pos: here }, { t: t0 + dur, pos: dest },
      ...old.filter(k => k.t > t0 + dur + 1e-6),
    ];
    // 跑过一段就按跑记（步态按瞬时速度算，走跑混着也不乱）
    const action = act === "run" || obj.track?.action === "run" ? "run" : act;
    obj.track = track(obj, keys, {
      face: o.face ?? obj.track?.face, action,
      // 多段移动不能整段缓动：smooth 会把整条轨迹的时间一起重映射，段与段之间的停顿被吃掉
      ease: keys.length > 2 ? "linear" : "smooth", path: "linear",
    }, where);
    return dur;
  }

  function track(obj: SceneObject, keys: MoveKey[], o: Record<string, unknown>, where: string): MoveTrack {
    const action = o.action as MoveTrack["action"] | undefined;
    if (action !== undefined && !ACTIONS.includes(action)) fail(where, `action 只能是 ${ACTIONS.join(" / ")}`);
    const sorted = keys.slice().sort((a, b) => a.t - b.t);
    if (sorted.length > 800) fail(where, "关键帧太多（>800）");
    // 第一帧没写位置的，从物体当前位置出发
    if (!sorted[0].pos) sorted[0] = { ...sorted[0], pos: obj.transform.pos };
    const steered = obj.kind === "character" || STEERED.has(obj.prefab ?? "");
    const face = (o.face ?? (steered ? "path" : "none")) as MoveTrack["face"];
    return {
      keys: sorted,
      ease: (o.ease === "linear" ? "linear" : o.ease === "smooth" ? "smooth" : "smooth") as MoveTrack["ease"],
      path: (o.path === "curve" ? "curve" : "linear") as MoveTrack["path"],
      face: face === "path" ? "path" : "none",
      action: action ?? (obj.kind === "character" ? "walk" : undefined),
    };
  }

  function normKey(k: Record<string, unknown>, where: string): CamKey {
    const out: CamKey = { t: num(k.t, where, "t") };
    const n = (k.at !== undefined ? 1 : 0) + (k.follow !== undefined ? 1 : 0) + (k.orbit !== undefined ? 1 : 0);
    if (n !== 1) fail(where, "位置要在 at / follow / orbit 里三选一");
    if (k.at !== undefined) out.at = vec(k.at, where, "at");
    if (k.follow !== undefined) { out.follow = get(k.follow as Ref, where).id; out.offset = vec(k.offset, where, "offset", [0, 1.7, -4]); }
    if (k.orbit !== undefined) {
      out.orbit = get(k.orbit as Ref, where).id;
      out.angle = num(k.angle, where, "angle", 0); out.radius = num(k.radius, where, "radius", 4); out.height = num(k.height, where, "height", 1.6);
    }
    if (k.look !== undefined) {
      const l = k.look as unknown;
      if (Array.isArray(l)) out.look = vec(l, where, "look");
      else if (typeof l === "string" || (l && typeof l === "object" && "id" in (l as object))) out.look = get(l as Ref, where).id;
      else if (l && typeof l === "object" && "target" in (l as object)) {
        const lo = l as { target: Ref; offset?: Vec3 };
        out.look = { target: get(lo.target, where).id, offset: lo.offset ? vec(lo.offset, where, "look.offset") : undefined };
      } else fail(where, "look 要写成点 [x,y,z]、物体，或 {target, offset}");
    }
    if (k.lens !== undefined) out.lens = M.clamp(num(k.lens, where, "lens"), 8, 300);
    if (k.roll !== undefined) out.roll = num(k.roll, where, "roll");
    return out;
  }

  function addKey(c: CameraDef, k: CamKey) {
    c.keys = [...c.keys.filter(x => Math.abs(x.t - k.t) > 1e-6), k].sort((a, b) => a.t - b.t);
  }

  // ── 收尾：展开预设、补默认、应用手动改动、出诊断 ──

  function finish(error?: { message: string; line?: number; col?: number }): { doc: SceneDoc; diagnostics: Diagnostics } {
    const keyTimes = [
      ...objects.flatMap(o => o.track?.keys.map(k => k.t) ?? []),
      ...cameras.flatMap(c => c.keys.map(k => k.t)),
      ...cuts.map(c => c.t),
      ...presetJobs.map(j => (typeof j.opts.start === "number" ? j.opts.start : 0) + (typeof j.opts.duration === "number" ? j.opts.duration : 4)),
    ].filter(t => Number.isFinite(t));
    const dur = duration ?? M.clamp(Math.max(5, ...keyTimes.map(t => Math.ceil(t))), 1, 180);

    const draft: SceneDoc = {
      version: 1, duration: dur, fps, aspect, seed, env, lights: lights.slice(), objects, cameras, cuts: [], notes,
      timeline: timeline.slice().sort((a, b) => a.t - b.t),
    };
    const ev = new SceneEval(draft);

    for (const job of presetJobs) {
      const o = job.opts;
      const where = `S.cameraPreset("${job.preset}")`;
      try {
        const def = CAMERA_PRESETS.find(p => p.id === job.preset)!;
        let target: string | null = null;
        let point: Vec3 = [0, 0, 0];
        if (Array.isArray(o.target)) point = vec(o.target, where, "target");
        else if (o.target !== undefined) target = get(o.target as Ref, where).id;
        const obj = target ? byId.get(target)! : null;
        const size = obj ? (obj.kind === "character" ? obj.size[1] : Math.max(obj.size[0], obj.size[2], obj.size[1])) : 1.75;
        const aim = obj ? (obj.kind === "character" ? obj.size[1] * 0.9 : Math.max(0.6, obj.size[1] * 0.55)) : 1.2;
        const res = def.build({
          target, start: num(o.start, where, "start", 0), duration: Math.max(0.2, num(o.duration, where, "duration", 4)),
          side: num(o.side, where, "side", 1) < 0 ? -1 : 1, lens: num(o.lens, where, "lens", job.cam.lens),
          size, aim, angle: num(o.angle, where, "angle", 15),
          distance: o.distance !== undefined ? num(o.distance, where, "distance") : undefined,
          height: o.height !== undefined ? num(o.height, where, "height") : undefined,
          posAt: t => (target ? ev.world(target, t).pos : point),
          yawAt: t => (target ? ev.world(target, t).rot[1] : 0),
        });
        for (const k of res.keys) addKey(job.cam, k);
        if (res.shake !== undefined) job.cam.shake = Math.max(job.cam.shake, res.shake);
        if (res.ease) job.cam.ease = res.ease;
        if (res.path) job.cam.path = res.path;
      } catch (e) {
        warnings.push(e instanceof Error ? e.message : String(e));
      }
    }

    // 跟拍没写 end 的，一直跟到片尾
    for (const c of cameras) {
      c.keys = c.keys.map(k => ((k as CamKey & { __open?: boolean }).__open ? { ...k, t: dur, __open: undefined } : k))
        .map(k => { const { __open, ...rest } = k as CamKey & { __open?: boolean }; void __open; return rest; })
        .sort((a, b) => a.t - b.t);
    }

    if (!cameras.length && objects.length) {
      const c = S.camera("默认机位");
      const bb = boundsOf(objects);
      const cx = (bb.min[0] + bb.max[0]) / 2, cz = (bb.min[1] + bb.max[1]) / 2;
      const span = Math.max(10, bb.max[0] - bb.min[0], bb.max[1] - bb.min[1]);
      addKey(cameras[0], { t: 0, at: [cx, span * 0.35, bb.max[1] + span * 0.6], look: [cx, 1, cz] });
      warnings.push(`没有机位：自动放了「${c.name}」俯瞰全场。要出成片请用 S.camera + S.cameraKeys / S.cameraPreset 设计机位`);
    }
    for (const c of cameras) if (!c.keys.length) warnings.push(`机位「${c.name}」没有关键帧（S.cameraKeys / S.cameraPreset / S.frame），成片里会停在默认位置`);

    let finalCuts = cuts.slice().sort((a, b) => a.t - b.t);
    if (!finalCuts.length && cameras.length) finalCuts = [{ t: 0, camera: cameras[0].id }];
    if (finalCuts.length && finalCuts[0].t > 0) finalCuts.unshift({ t: 0, camera: finalCuts[0].camera });
    for (const ct of finalCuts) if (ct.t > dur) warnings.push(`S.cut(${ct.t})：超出片长 ${dur}s`);

    applyOverrides(draft, opts.overrides, warnings);
    const doc: SceneDoc = { ...draft, cuts: opts.overrides?.cuts?.length ? opts.overrides.cuts : finalCuts };

    // 常见问题体检
    for (const o of objects) {
      const p = o.transform.pos;
      if (!o.parent && o.kind !== "strip" && Math.max(Math.abs(p[0]), Math.abs(p[2])) > env.groundSize / 2 + 5 && !(o.prefab === "mountain"))
        warnings.push(`「${o.id}」在地面外（${p[0].toFixed(0)}, ${p[2].toFixed(0)}），地面边长 ${env.groundSize}m；要么挪近，要么加大 S.environment({groundSize})`);
      if (o.track) for (const k of o.track.keys) if (k.t > dur + 1e-6) { warnings.push(`「${o.id}」的动画关键帧 t=${k.t} 超出片长 ${dur}s`); break; }
    }
    const dup = new Map<string, number>();
    for (const o of objects) if (o.kind !== "group" && o.kind !== "strip") {
      const key = `${o.prefab ?? o.prim}@${o.transform.pos.map(v => v.toFixed(1)).join(",")}`;
      dup.set(key, (dup.get(key) ?? 0) + 1);
    }
    const dups = [...dup.entries()].filter(([, k]) => k > 1);
    if (dups.length) warnings.push(`有 ${dups.length} 处同一位置重复摆了同样的东西（比如 ${dups[0][0]}）`);

    // 脚本中途出错也给概要：已经搭好的部分对智能体定位问题有用
    const summary = objects.length || cameras.length ? summarize(doc, ev) : null;
    return {
      doc,
      diagnostics: { ok: !error, errors: error ? [error] : [], warnings: [...new Set(warnings)].slice(0, 40), summary },
    };
  }

  return {
    S,
    /** 给脚本用的向量小工具 */
    V: {
      add: M.add, sub: M.sub, scale: M.scale, len: M.len, dist: M.dist, lerp: M.lerp3, norm: M.norm,
      /** 朝向 yaw（度）的前方向量 */ forward: M.forwardOf,
      /** 从 a 看向 b 的朝向角 */ yawTo: M.yawTo,
      /** 以 center 为圆心、半径 r、角度 deg 处的点（0° = +Z） */
      polar: (center: Pos, r: number, deg: number): Vec3 => { const c = M.v2to3(center); return [c[0] + Math.sin(M.rad(deg)) * r, c[1], c[2] + Math.cos(M.rad(deg)) * r]; },
      /** 圆上等分 n 个点 */
      circle: (center: Pos, r: number, n: number): Vec3[] => Array.from({ length: n }, (_, i) => { const c = M.v2to3(center); const a = (i / n) * Math.PI * 2; return [c[0] + Math.sin(a) * r, c[1], c[2] + Math.cos(a) * r]; }),
    },
    random,
    finish,
  };
}

export function applyOverrides(doc: SceneDoc, ov: Overrides | undefined, warnings: string[] = []) {
  if (!ov) return doc;
  const byId = new Map(doc.objects.map(o => [o.id, o]));
  for (const [id, o] of Object.entries(ov.objects ?? {})) {
    const obj = byId.get(id);
    if (!obj) { warnings.push(`手动改动里的「${id}」在脚本里已经不存在（脚本改名或删掉了），这条改动没生效`); continue; }
    obj.transform = { pos: o.pos ?? obj.transform.pos, rot: o.rot ?? obj.transform.rot, scale: o.scale ?? obj.transform.scale };
    if (o.color) obj.color = o.color;
    if (o.hidden) obj.tags = [...obj.tags.filter(t => t !== "hidden"), "hidden"];
    // 手动挪过的物体，动画的第一帧跟着挪：否则一播放又跳回脚本里的起点
    if (obj.track && o.pos) {
      const first = obj.track.keys[0];
      if (first?.pos) {
        const d = M.sub(o.pos, first.pos);
        obj.track = { ...obj.track, keys: obj.track.keys.map(k => (k.pos ? { ...k, pos: M.add(k.pos, d) } : k)) };
      }
    }
  }
  for (const [id, c] of Object.entries(ov.cameras ?? {})) {
    const cam = doc.cameras.find(x => x.id === id);
    if (!cam) { warnings.push(`手动改动里的机位「${id}」在脚本里已经不存在`); continue; }
    if (c.keys) cam.keys = c.keys.slice().sort((a, b) => a.t - b.t);
    if (c.lens) cam.lens = c.lens;
    if (c.ease) cam.ease = c.ease;
    if (c.path) cam.path = c.path;
  }
  return doc;
}

function boundsOf(objects: SceneObject[]) {
  const xs: number[] = [], zs: number[] = [];
  for (const o of objects) {
    if (o.prefab === "mountain") continue;
    if (o.strip) for (const p of o.strip.points) { xs.push(p[0]); zs.push(p[1]); }
    else { xs.push(o.transform.pos[0]); zs.push(o.transform.pos[2]); }
  }
  if (!xs.length) return { min: [0, 0] as Vec2, max: [0, 0] as Vec2 };
  return { min: [Math.min(...xs), Math.min(...zs)] as Vec2, max: [Math.max(...xs), Math.max(...zs)] as Vec2 };
}

/** 概要＋俯视字符地图：智能体靠它检查布局，不用截图。 */
function summarize(doc: SceneDoc, ev: SceneEval): SceneSummary {
  const counts: Record<string, number> = {};
  for (const o of doc.objects) {
    const k = o.kind === "prefab" ? `${o.prefab}（${PREFABS[o.prefab!]?.zh ?? ""}）` : o.kind === "character" ? "人物" : o.kind === "strip" ? `${o.strip?.kind === "water" ? "河" : "路"}` : o.kind === "prim" ? `基本体 ${o.prim}` : "组";
    counts[k] = (counts[k] ?? 0) + 1;
  }
  const bb = boundsOf(doc.objects);
  const moving = (o: SceneObject) => !!o.track?.keys.length;
  const pos = (o: SceneObject, t: number) => ev.world(o.id, t).pos.map(v => +v.toFixed(1)) as Vec3;
  const lastT = (o: SceneObject) => Math.max(...(o.track?.keys.map(k => k.t) ?? [0]));
  const characters = doc.objects.filter(o => o.kind === "character").map(o => ({
    id: o.id, name: o.name, body: o.body ?? "male", from: pos(o, 0), to: pos(o, moving(o) ? lastT(o) : 0), action: o.track?.action,
  }));
  const VEHICLES = new Set(["car", "police_car", "truck", "bus", "motorcycle", "bicycle", "boat", "helicopter", "horse_cart", "horse"]);
  const vehicles = doc.objects.filter(o => o.prefab && VEHICLES.has(o.prefab)).map(o => ({
    id: o.id, name: o.name, from: pos(o, 0), to: pos(o, moving(o) ? lastT(o) : 0),
  }));
  const cameras = doc.cameras.map(c => ({
    id: c.id, name: c.name, keys: c.keys.length,
    span: [c.keys[0]?.t ?? 0, c.keys[c.keys.length - 1]?.t ?? 0] as [number, number],
    kinds: [...new Set(c.keys.map(k => (k.follow ? "跟随" : k.orbit ? "环绕" : "世界坐标")))],
    presets: c.presets,
  }));
  return {
    duration: doc.duration, objects: doc.objects.length, counts,
    bounds: { min: bb.min.map(v => +v.toFixed(1)) as Vec2, max: bb.max.map(v => +v.toFixed(1)) as Vec2 },
    characters, vehicles, cameras, cuts: doc.cuts, map: asciiMap(doc, ev), notes: doc.notes,
  };
}

function asciiMap(doc: SceneDoc, ev: SceneEval, W = 56, Hh = 26): string {
  const bb = boundsOf(doc.objects);
  const pad = 4;
  const x0 = bb.min[0] - pad, x1 = bb.max[0] + pad, z0 = bb.min[1] - pad, z1 = bb.max[1] + pad;
  const sx = (x1 - x0) / W || 1, sz = (z1 - z0) / Hh || 1;
  const cell = Math.max(sx, sz);
  const cols = Math.min(W, Math.ceil((x1 - x0) / cell) + 1), rows = Math.min(Hh, Math.ceil((z1 - z0) / cell) + 1);
  const grid = Array.from({ length: rows }, () => Array(cols).fill("·"));
  const put = (x: number, z: number, ch: string, force = false) => {
    const c = Math.round((x - x0) / cell), r = Math.round((z - z0) / cell);
    if (r >= 0 && r < rows && c >= 0 && c < cols && (force || grid[r][c] === "·" || grid[r][c] === "=" || grid[r][c] === "~")) grid[r][c] = ch;
  };
  for (const o of doc.objects) if (o.strip) {
    const pts = o.strip.points.map(p => [p[0], 0, p[1]] as Vec3);
    const total = M.polyLength(pts);
    for (let s = 0; s <= total; s += cell * 0.7) { const { p } = M.samplePoly(pts, s); put(p[0], p[2], o.strip.kind === "water" ? "~" : "="); }
  }
  // 按预制件名精确分类 —— 子串匹配会把 streetlamp 当成 tree
  const GLYPH: Record<string, string> = {
    house: "#", building: "#", skyscraper: "#", shop: "#", pagoda: "#", pavilion: "#", gate: "#", well: "#", stall: "#",
    tree: "T", bush: "T", car: "C", police_car: "C", truck: "C", bus: "C", motorcycle: "C", bicycle: "C",
    helicopter: "C", horse_cart: "C", cart: "C", boat: "B", wall: "|", fence: "|", bridge: "H",
    mountain: "", marker: "", arrow: "",
  };
  const glyph = (o: SceneObject): string => {
    if (o.kind === "character") return "@";
    if (o.kind === "group") return "";
    return GLYPH[o.prefab ?? ""] ?? "o";
  };
  for (const o of doc.objects) {
    const g = glyph(o);
    if (!g || o.strip) continue;
    const w = ev.world(o.id, 0).pos;
    put(w[0], w[2], g, g === "@" || g === "C");
  }
  doc.cameras.forEach((c, i) => {
    if (!c.keys.length) return;
    const p = ev.camera(c, c.keys[0].t).pos;
    put(p[0], p[2], String((i + 1) % 10), true);
  });
  const lines = grid.map(r => r.join(""));
  return [
    `俯视图（北 = -Z 在上；每格约 ${cell.toFixed(1)}m；x ${x0.toFixed(0)}→${x1.toFixed(0)}，z ${z0.toFixed(0)}→${z1.toFixed(0)}）`,
    "图例：# 建筑  T 树  C 车  B 船  @ 人物  | 墙栏  H 桥  = 路  ~ 水  o 其它  数字 = 机位起点",
    ...lines,
  ].join("\n");
}

export { PREFABS, BODIES, POSES };
