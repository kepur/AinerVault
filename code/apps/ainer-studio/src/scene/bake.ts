/**
 * 烘焙：场景文档 → 逐帧解算好的「渲染场景」，给 Blender / UE / 任何外部渲染器。
 *
 * 外部渲染器不必懂我们的脚本、运镜预设、动作库：几何是部件表，动画是逐帧位姿，
 * 人偶是逐帧关节角，机位是逐帧的位置＋看向点＋焦段＋滚转。这些都用预览同一套求值器算，
 * 所以 Blender 渲出来的就是 3D-BOX 里看到的。
 *
 * 坐标照旧：Y 向上、米、右手系；物体 yaw 0 面向 +Z；欧拉角是度、XYZ 次序（three 默认）。
 * 机位看向 -Z、上方 +Y；焦段按 36mm 宽的全画幅、水平视场算（tan(半水平视场) = 18 / lens）。
 */
import type { Cut, LightDef, SceneDoc, SceneObject, TimelineOp, Vec2, Vec3 } from "./types";
import { PREFABS, type Part } from "./prefabs";
import { localPose, SceneEval } from "./evaluate";
import { GROUND, partColor, SKY, STRIP_COLOR } from "./palette";
import { JOINTS, jointsAt, mannequinDims, poseKeypoints, rigLayout, type MannequinDims } from "./rig";

export interface BakeOptions {
  fps?: number;
  /** 渲染哪台机位；不填或 "cut" = 按主机位时间表逐帧切 */
  camera?: string;
  /** 帧数；不填 = 按片长凑成 8n+1（视频模型要这种帧数） */
  frames?: number;
  /** 从第几秒开始 */
  t0?: number;
}

export interface BakedObject {
  id: string;
  name: string;
  kind: SceneObject["kind"];
  parent: string | null;
  /** 基础位姿（没有动画时就是它）：pos 米、rot 度（XYZ）、scale */
  pos: Vec3;
  rot: Vec3;
  scale: Vec3;
  /** 有逐帧动画（见 Baked.anim） */
  animated: boolean;
  /** 预制件、基本体：部件表（局部坐标，颜色已按物体主色解析） */
  parts?: Part[];
  /** 道路、河流：地面上的带子 */
  strip?: { points: Vec2[]; width: number; kind: string; lines: boolean; color: string; y: number };
  /** 人偶：体型、尺寸、骨架层级、OpenPose 关键点挂点 */
  character?: {
    body: string; height: number; color: string; joint: string; nose: string;
    dims: MannequinDims;
    layout: ReturnType<typeof rigLayout>;
    keypoints: ReturnType<typeof poseKeypoints>;
    ref?: string;
  };
  /** 图片板：贴图地址 */
  image?: { url: string; width: number; height: number };
  prefab?: string;
  tags: string[];
}

/** 人偶每帧的通道：位移(3) 转身(1) 整体旋转(3) 抬高(1) 盆骨高(1) 十个关节×3 */
export const RIG_CHANNELS = [
  "offset.x", "offset.y", "offset.z", "yaw", "root.x", "root.y", "root.z", "rootY", "pelvisY",
  ...JOINTS.flatMap(j => [`${j}.x`, `${j}.y`, `${j}.z`]),
];
/** 物体每帧：[px,py,pz, rx,ry,rz, sx,sy,sz] */
export const ANIM_STRIDE = 9;
/** 机位每帧：[px,py,pz, lx,ly,lz, lens, roll] */
export const CAM_STRIDE = 8;

export interface Baked {
  version: 1;
  fps: number;
  frames: number;
  t0: number;
  duration: number;
  aspect: number;
  env: {
    sky: string; ground: string; groundSize: number; fog: number;
    bg: string; hemiSky: string; hemiGround: string; groundColor: string;
  };
  lights: LightDef[];
  objects: BakedObject[];
  anim: Record<string, number[]>;
  rigs: Record<string, number[]>;
  rigChannels: string[];
  /** 逐帧实际用的机位（主机位按时间表切过之后的） */
  camera: { frames: number[]; ids: string[] };
  /** 每台机位单独的逐帧轨迹（导出 camera.json 用） */
  cameras: Record<string, { name: string; frames: number[] }>;
  cuts: Cut[];
  timeline: TimelineOp[];
}

const r4 = (x: number) => Math.round(x * 1e4) / 1e4;

export function frameCount(duration: number, fps: number): number {
  const n = Math.max(1, Math.round(duration * fps)) + 1;
  return 8 * Math.ceil((n - 1) / 8) + 1;
}

export function bake(doc: SceneDoc, o: BakeOptions = {}): Baked {
  const fps = o.fps ?? doc.fps ?? 24;
  const t0 = o.t0 ?? 0;
  const frames = o.frames ?? frameCount(Math.max(0.04, doc.duration - t0), fps);
  const ev = new SceneEval(doc);
  const times = Array.from({ length: frames }, (_, i) => t0 + i / fps);

  // 成片里不画的：隐藏的、标记（和它们的子物体）
  const byId = new Map(doc.objects.map(x => [x.id, x]));
  const skipped = (x: SceneObject): boolean => {
    for (let cur: SceneObject | undefined = x, d = 0; cur && d < 16; cur = cur.parent ? byId.get(cur.parent) : undefined, d++) {
      if (cur.tags.includes("hidden") || cur.prefab === "marker" || cur.prefab === "arrow") return true;
    }
    return false;
  };

  const objects: BakedObject[] = [];
  const anim: Record<string, number[]> = {};
  const rigs: Record<string, number[]> = {};
  for (const x of doc.objects) {
    if (skipped(x)) continue;
    const t = x.transform;
    const b: BakedObject = {
      id: x.id, name: x.name, kind: x.kind, parent: x.parent && byId.has(x.parent) ? x.parent : null,
      pos: t.pos.map(r4) as Vec3, rot: t.rot.map(r4) as Vec3, scale: t.scale.map(r4) as Vec3,
      animated: !!x.track?.keys.length, prefab: x.prefab, tags: x.tags,
    };
    if (x.kind === "prefab" && x.prefab && PREFABS[x.prefab]) {
      b.parts = PREFABS[x.prefab].build(x.params).map(p => ({ ...p, color: partColor(p, x) }));
      if (x.prefab === "image_board" && typeof x.params.url === "string" && x.params.url)
        b.image = { url: x.params.url, width: Number(x.params.width) || 4, height: Number(x.params.height) || 3 };
    } else if (x.kind === "prim" && x.prim) {
      b.parts = [{ prim: x.prim, size: x.size, pos: [0, 0, 0], segments: 16, color: x.color ?? "#c9cdd4" }];
    } else if (x.kind === "strip" && x.strip) {
      const s = x.strip;
      b.strip = { ...s, color: STRIP_COLOR[s.kind] ?? "#9aa0a8", y: s.kind === "water" ? 0.012 : 0.02 };
    } else if (x.kind === "character") {
      const body = x.body ?? "male";
      const dims = mannequinDims(body, x.size[1]);
      b.character = {
        body, height: x.size[1], color: x.color ?? "#bcc0c8", joint: "#9aa0aa", nose: "#ffb86b",
        dims, layout: rigLayout(dims), keypoints: poseKeypoints(dims), ref: x.ref,
      };
      const ch: number[] = [];
      for (const tt of times) {
        const st = jointsAt(ev, x, tt, dims);
        ch.push(...st.offset, st.yaw, ...st.root, st.rootY, st.pelvisY);
        for (const j of JOINTS) ch.push(...st.joints[j]);
      }
      rigs[x.id] = ch.map(r4);
    }
    if (b.animated) {
      const a: number[] = [];
      for (const tt of times) {
        const lp = localPose(x, tt);
        a.push(...lp.pos, ...lp.rot, ...lp.scale);
      }
      anim[x.id] = a.map(r4);
    }
    objects.push(b);
  }

  const cams: Baked["cameras"] = {};
  const camPose = (id: string, tt: number) => {
    const c = doc.cameras.find(k => k.id === id)!;
    const p = ev.camera(c, tt);
    return [...p.pos, ...p.look, p.lens, p.roll];
  };
  const fixed = o.camera && o.camera !== "cut" ? doc.cameras.find(c => c.id === o.camera || c.name === o.camera) : undefined;
  if (o.camera && o.camera !== "cut" && !fixed) throw new Error(`没有机位「${o.camera}」`);
  const ids: string[] = [];
  const merged: number[] = [];
  for (const tt of times) {
    const c = fixed ?? ev.activeCamera(tt);
    if (!c) { ids.push(""); merged.push(0, 1.6, 10, 0, 1, 0, 35, 0); continue; }
    ids.push(c.id);
    merged.push(...camPose(c.id, tt));
  }
  for (const id of new Set(ids.filter(Boolean))) {
    const c = doc.cameras.find(k => k.id === id)!;
    cams[id] = { name: c.name, frames: times.flatMap(tt => camPose(id, tt)).map(r4) };
  }

  const sky = SKY[doc.env.sky] ?? SKY.day;
  const lights = doc.lights.some(l => l.kind === "sun") ? doc.lights.slice()
    : [...doc.lights, { id: "__sun", name: "默认日光", kind: "sun" as const, color: sky.sun, intensity: sky.sunI, dir: [-0.6, -1.4, -0.5] as Vec3 }];
  return {
    version: 1, fps, frames, t0, duration: r4((frames - 1) / fps), aspect: doc.aspect,
    env: {
      sky: doc.env.sky, ground: doc.env.ground, groundSize: doc.env.groundSize, fog: doc.env.fog,
      bg: sky.bg, hemiSky: sky.hemiSky, hemiGround: sky.hemiGround, groundColor: GROUND[doc.env.ground] ?? GROUND.grid,
    },
    lights, objects, anim, rigs, rigChannels: RIG_CHANNELS,
    camera: { frames: merged.map(r4), ids },
    cameras: cams,
    cuts: doc.cuts,
    timeline: doc.timeline ?? [],
  };
}
