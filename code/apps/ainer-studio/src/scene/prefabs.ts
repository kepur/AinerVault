/**
 * 预制件库：程序化的低多边形白模。
 *
 * 每个预制件是一张「部件表」：几个基本体拼起来，局部坐标、底面落在 y=0、正面朝 +Z。
 * 同一份部件表三处用：前端渲染成网格、运行时算包围盒、给 LLM 的目录（catalogDoc）。
 * 不引 three —— 这份代码也要在后端的 vm 沙箱里跑。
 */
import type { ParamValue, PrimKind, Vec3 } from "./types";

export interface Part {
  prim: PrimKind;
  /** box/prism：[宽 x, 高 y, 深 z]；cylinder/cone：[直径, 高, 直径]；sphere：三轴直径；torus：[直径, 管径, _] */
  size: Vec3;
  /** 部件中心（局部坐标） */
  pos: Vec3;
  rot?: Vec3;
  color?: string;
  segments?: number;
  /** 圆柱／圆锥／圆环的弧：[起始角, 弧长]（度） */
  arc?: [number, number];
  /** 发光（灯） */
  glow?: boolean;
  /** 半透明（标记、玻璃） */
  opacity?: number;
}

export interface ParamDef {
  default: ParamValue;
  doc: string;
  options?: string[];
}

export interface PrefabDef {
  zh: string;
  category: "建筑" | "街道" | "交通" | "自然" | "室内" | "道具" | "标记" | "动物";
  doc: string;
  params?: Record<string, ParamDef>;
  build: (p: Record<string, ParamValue>) => Part[];
}

/** 白模色板：整体偏白，只用色相区分类别，好认不抢戏。 */
export const C = {
  wall: "#eceef1", wall2: "#dfe3e8", roof: "#c3c9d1", roofDark: "#8f97a3", dark: "#6b727d",
  glass: "#a9bccd", wood: "#cdb99e", woodDark: "#9b8468", metal: "#b8bec6", foliage: "#a3b8a6",
  foliageDark: "#86a08d", trunk: "#a8927c", water: "#a9c0d3", red: "#d65a55", blue: "#3f6fd8",
  yellow: "#e6c34a", orange: "#e8894a", white: "#f7f7f8", black: "#40444b", light: "#fff4d6",
};

const n = (v: ParamValue | undefined, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const s = (v: ParamValue | undefined, d: string) => (typeof v === "string" && v ? v : d);
const b = (v: ParamValue | undefined, d: boolean) => (typeof v === "boolean" ? v : d);

const box = (size: Vec3, pos: Vec3, color?: string, rot?: Vec3): Part => ({ prim: "box", size, pos, color, rot });
const cyl = (d: number, h: number, pos: Vec3, color?: string, rot?: Vec3, segments = 10): Part =>
  ({ prim: "cylinder", size: [d, h, d], pos, color, rot, segments });
const cone = (d: number, h: number, pos: Vec3, color?: string, segments = 8, rot?: Vec3): Part =>
  ({ prim: "cone", size: [d, h, d], pos, color, segments, rot });
const ball = (size: Vec3, pos: Vec3, color?: string, segments = 8): Part => ({ prim: "sphere", size, pos, color, segments });
/** 三角棱柱：三角形在 XY 面（底宽 size[0]、高 size[1]），沿 Z 拉伸 size[2]。 */
const prism = (size: Vec3, pos: Vec3, color?: string, rot?: Vec3): Part => ({ prim: "prism", size, pos, color, rot });
/** 四坡屋顶：底面是 w×d 的矩形的四棱锥。 */
const pyramid = (w: number, h: number, d: number, pos: Vec3, color?: string): Part =>
  ({ prim: "cone", size: [w * Math.SQRT2, h, d * Math.SQRT2], pos, color, segments: 4, arc: [45, 360] });
const wheel = (d: number, w: number, pos: Vec3): Part => cyl(d, w, pos, C.black, [0, 0, 90], 12);

/** 双坡屋顶：屋脊沿 X（面阔方向），前后两坡。 */
function gable(w: number, d: number, h: number, y: number, color: string, over = 0.5): Part[] {
  return [prism([d + over * 2, h, w + over * 2], [0, y + h / 2, 0], color, [0, 90, 0])];
}

export const PREFABS: Record<string, PrefabDef> = {
  // ── 建筑 ────────────────────────────────────────────────
  house: {
    zh: "民居", category: "建筑",
    doc: "一栋房子，正门朝 +Z。宽 width（沿 X）× 深 depth（沿 Z），每层 3m",
    params: {
      width: { default: 6, doc: "面阔（米）" }, depth: { default: 5, doc: "进深（米）" },
      floors: { default: 1, doc: "层数" },
      roof: { default: "gable", doc: "屋顶", options: ["gable", "hip", "flat"] },
      style: { default: "modern", doc: "风格", options: ["modern", "ancient"] },
    },
    build: p => {
      const w = n(p.width, 6), d = n(p.depth, 5), f = Math.max(1, Math.round(n(p.floors, 1)));
      const ancient = s(p.style, "modern") === "ancient";
      const H = 3 * f;
      const parts: Part[] = [];
      if (ancient) parts.push(box([w + 0.8, 0.35, d + 0.8], [0, 0.175, 0], C.roof));
      const y0 = ancient ? 0.35 : 0;
      parts.push(box([w, H, d], [0, y0 + H / 2, 0], C.wall));
      const roof = s(p.roof, "gable");
      if (roof === "flat") parts.push(box([w + 0.3, 0.3, d + 0.3], [0, y0 + H + 0.15, 0], C.roof));
      else if (roof === "hip") parts.push(pyramid(w + (ancient ? 1.6 : 0.6), ancient ? 2.2 : 1.6, d + (ancient ? 1.6 : 0.6), [0, y0 + H + (ancient ? 1.1 : 0.8), 0], ancient ? C.roofDark : C.roof));
      else parts.push(...gable(w, d, ancient ? 2 : 1.5, y0 + H, ancient ? C.roofDark : C.roof, ancient ? 0.9 : 0.4));
      if (ancient && roof !== "flat") parts.push(box([w + 1.8, 0.22, 0.3], [0, y0 + H + 2, 0], C.dark));
      parts.push(box([1.1, 2.1, 0.08], [0, y0 + 1.05, d / 2 + 0.04], C.woodDark));
      for (let i = 0; i < f; i++) {
        for (const x of [-w * 0.3, w * 0.3]) parts.push(box([0.95, 0.95, 0.06], [x, y0 + 1.7 + 3 * i, d / 2 + 0.03], ancient ? C.wood : C.glass));
      }
      if (ancient) for (const x of [-w / 2 + 0.2, w / 2 - 0.2]) parts.push(cyl(0.28, H, [x, y0 + H / 2, d / 2 + 0.35], C.woodDark));
      return parts;
    },
  },
  building: {
    zh: "楼房", category: "建筑",
    doc: "多层楼，正面朝 +Z，每层 3.2m，有横向窗带",
    params: {
      width: { default: 10, doc: "宽（米）" }, depth: { default: 10, doc: "深（米）" }, floors: { default: 6, doc: "层数" },
    },
    build: p => {
      const w = n(p.width, 10), d = n(p.depth, 10), f = Math.max(1, Math.round(n(p.floors, 6)));
      const H = 3.2 * f;
      const parts: Part[] = [box([w, H, d], [0, H / 2, 0], C.wall2), box([w + 0.3, 0.5, d + 0.3], [0, H + 0.25, 0], C.roof)];
      for (let i = 0; i < f; i++) {
        const y = 3.2 * i + 1.8;
        parts.push(box([w * 0.9, 1.1, 0.06], [0, y, d / 2 + 0.03], C.glass), box([w * 0.9, 1.1, 0.06], [0, y, -d / 2 - 0.03], C.glass));
        parts.push(box([0.06, 1.1, d * 0.9], [w / 2 + 0.03, y, 0], C.glass), box([0.06, 1.1, d * 0.9], [-w / 2 - 0.03, y, 0], C.glass));
      }
      parts.push(box([2.2, 2.6, 0.1], [0, 1.3, d / 2 + 0.05], C.dark));
      return parts;
    },
  },
  skyscraper: {
    zh: "摩天楼", category: "建筑", doc: "高层塔楼（默认 30 层约 100m），竖向窗条",
    params: { width: { default: 16, doc: "宽" }, depth: { default: 16, doc: "深" }, floors: { default: 30, doc: "层数" } },
    build: p => {
      const w = n(p.width, 16), d = n(p.depth, 16), H = 3.3 * Math.max(5, n(p.floors, 30));
      const parts: Part[] = [box([w, H, d], [0, H / 2, 0], C.wall2), box([w * 0.7, 4, d * 0.7], [0, H + 2, 0], C.roof), cyl(0.3, 12, [0, H + 10, 0], C.metal)];
      for (let i = 0; i < 5; i++) {
        const t = -w / 2 + (w / 5) * (i + 0.5);
        parts.push(box([w / 10, H * 0.96, 0.1], [t, H / 2, d / 2 + 0.05], C.glass), box([w / 10, H * 0.96, 0.1], [t, H / 2, -d / 2 - 0.05], C.glass));
        const z = -d / 2 + (d / 5) * (i + 0.5);
        parts.push(box([0.1, H * 0.96, d / 10], [w / 2 + 0.05, H / 2, z], C.glass), box([0.1, H * 0.96, d / 10], [-w / 2 - 0.05, H / 2, z], C.glass));
      }
      return parts;
    },
  },
  shop: {
    zh: "商铺", category: "建筑", doc: "临街小店：一层、平顶、门前遮阳篷和招牌，门朝 +Z",
    params: { width: { default: 6, doc: "宽" }, depth: { default: 6, doc: "深" }, color: { default: "#d65a55", doc: "遮阳篷颜色" } },
    build: p => {
      const w = n(p.width, 6), d = n(p.depth, 6);
      return [
        box([w, 3.6, d], [0, 1.8, 0], C.wall), box([w + 0.2, 0.3, d + 0.2], [0, 3.75, 0], C.roof),
        box([w * 0.8, 2.4, 0.06], [0, 1.4, d / 2 + 0.03], C.glass),
        box([w, 0.08, 1.5], [0, 2.95, d / 2 + 0.7], s(p.color, C.red), [-14, 0, 0]),
        box([w * 0.8, 0.6, 0.12], [0, 3.35, d / 2 + 0.06], C.dark),
      ];
    },
  },
  pagoda: {
    zh: "塔", category: "建筑", doc: "多层古塔，每层一圈四坡檐",
    params: { tiers: { default: 5, doc: "层数" }, width: { default: 7, doc: "底层宽" } },
    build: p => {
      const t = Math.max(1, Math.round(n(p.tiers, 5))), w0 = n(p.width, 7);
      const parts: Part[] = [box([w0 + 2, 0.6, w0 + 2], [0, 0.3, 0], C.roof)];
      let y = 0.6;
      for (let i = 0; i < t; i++) {
        const w = w0 * (1 - i * 0.12), h = i === 0 ? 3.4 : 2.6;
        parts.push(box([w, h, w], [0, y + h / 2, 0], C.wall));
        parts.push(pyramid(w + 2, 1.2, w + 2, [0, y + h + 0.3, 0], C.roofDark));
        y += h + 0.6;
      }
      parts.push(cone(0.5, 3, [0, y + 1.5, 0], C.dark, 6));
      return parts;
    },
  },
  pavilion: {
    zh: "亭子", category: "建筑", doc: "四柱攒尖亭，四面通透",
    params: { width: { default: 4, doc: "宽" } },
    build: p => {
      const w = n(p.width, 4);
      const parts: Part[] = [box([w + 0.8, 0.4, w + 0.8], [0, 0.2, 0], C.roof)];
      for (const x of [-w / 2, w / 2]) for (const z of [-w / 2, w / 2]) parts.push(cyl(0.26, 3, [x, 1.9, z], C.woodDark));
      parts.push(pyramid(w + 1.6, 1.8, w + 1.6, [0, 4.3, 0], C.roofDark), ball([0.4, 0.4, 0.4], [0, 5.3, 0], C.dark));
      return parts;
    },
  },
  gate: {
    zh: "牌坊", category: "建筑", doc: "门楼/牌坊：两柱一楣一顶，门洞朝 Z 方向可穿过",
    params: { width: { default: 6, doc: "宽" }, height: { default: 5, doc: "高" } },
    build: p => {
      const w = n(p.width, 6), h = n(p.height, 5);
      return [
        cyl(0.45, h, [-w / 2, h / 2, 0], C.woodDark), cyl(0.45, h, [w / 2, h / 2, 0], C.woodDark),
        box([w + 1, 0.5, 0.5], [0, h - 0.6, 0], C.red), box([w * 0.6, 0.8, 0.2], [0, h - 1.5, 0], C.dark),
        ...gable(w + 0.6, 1, 0.9, h - 0.3, C.roofDark, 0.5),
      ];
    },
  },
  wall: {
    zh: "墙", category: "建筑", doc: "一段墙，沿 X 方向延伸 length 米",
    params: {
      length: { default: 6, doc: "长" }, height: { default: 2.5, doc: "高" }, thickness: { default: 0.3, doc: "厚" },
      style: { default: "modern", doc: "风格（ancient 带瓦顶）", options: ["modern", "ancient"] },
    },
    build: p => {
      const l = n(p.length, 6), h = n(p.height, 2.5), t = n(p.thickness, 0.3);
      const parts: Part[] = [box([l, h, t], [0, h / 2, 0], C.wall2)];
      if (s(p.style, "modern") === "ancient") parts.push(prism([t + 0.5, 0.4, l + 0.2], [0, h + 0.2, 0], C.roofDark, [0, 90, 0]));
      return parts;
    },
  },
  fence: {
    zh: "栅栏", category: "建筑", doc: "栅栏，沿 X 方向延伸 length 米",
    params: { length: { default: 6, doc: "长" }, height: { default: 1, doc: "高" } },
    build: p => {
      const l = n(p.length, 6), h = n(p.height, 1);
      const parts: Part[] = [];
      const k = Math.max(2, Math.round(l / 1.5) + 1);
      for (let i = 0; i < k; i++) parts.push(box([0.1, h, 0.1], [-l / 2 + (l / (k - 1)) * i, h / 2, 0], C.wood));
      parts.push(box([l, 0.08, 0.05], [0, h * 0.8, 0], C.wood), box([l, 0.08, 0.05], [0, h * 0.35, 0], C.wood));
      return parts;
    },
  },
  bridge: {
    zh: "桥", category: "建筑", doc: "桥，桥身沿 X 方向（左右）跨越 span 米；arch=true 是拱桥",
    params: { span: { default: 12, doc: "跨度" }, width: { default: 4, doc: "桥面宽" }, arch: { default: true, doc: "拱桥" }, rise: { default: 2.2, doc: "拱高" } },
    build: p => {
      const L = n(p.span, 12), W = n(p.width, 4), arch = b(p.arch, true), rise = arch ? n(p.rise, 2.2) : 0;
      const parts: Part[] = [];
      const seg = arch ? 10 : 1;
      for (let i = 0; i < seg; i++) {
        const u0 = i / seg, u1 = (i + 1) / seg;
        const x0 = -L / 2 + L * u0, x1 = -L / 2 + L * u1;
        const y0 = rise * Math.sin(Math.PI * u0) + 0.6, y1 = rise * Math.sin(Math.PI * u1) + 0.6;
        const ang = (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI;
        const lenSeg = Math.hypot(x1 - x0, y1 - y0);
        const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
        parts.push(box([lenSeg + 0.05, 0.35, W], [cx, cy, 0], C.roof, [0, 0, ang]));
        for (const z of [-W / 2, W / 2]) parts.push(box([lenSeg + 0.05, 0.7, 0.15], [cx, cy + 0.5, z], C.wall2, [0, 0, ang]));
      }
      if (!arch) for (const x of [-L / 2 + 0.5, L / 2 - 0.5]) parts.push(box([0.6, 0.6, W], [x, 0.3, 0], C.roof));
      return parts;
    },
  },
  stairs: {
    zh: "台阶", category: "建筑", doc: "台阶，从 +Z 一侧往 -Z 升高",
    params: { steps: { default: 8, doc: "级数" }, width: { default: 3, doc: "宽" }, rise: { default: 0.18, doc: "每级高" }, run: { default: 0.3, doc: "每级深" } },
    build: p => {
      const k = Math.max(1, Math.round(n(p.steps, 8))), w = n(p.width, 3), r = n(p.rise, 0.18), d = n(p.run, 0.3);
      const parts: Part[] = [];
      for (let i = 0; i < k; i++) parts.push(box([w, r * (i + 1), d], [0, (r * (i + 1)) / 2, (k / 2 - i - 0.5) * d], C.roof));
      return parts;
    },
  },
  column: {
    zh: "柱子", category: "建筑", doc: "圆柱",
    params: { height: { default: 4, doc: "高" }, radius: { default: 0.3, doc: "半径" } },
    build: p => [cyl(n(p.radius, 0.3) * 2, n(p.height, 4), [0, n(p.height, 4) / 2, 0], C.wall2, undefined, 14)],
  },
  stall: {
    zh: "摊位", category: "建筑", doc: "集市摊位：桌台、四根杆、顶棚，摊主一侧在 -Z",
    params: { width: { default: 2.6, doc: "宽" }, color: { default: "#e8894a", doc: "顶棚颜色" } },
    build: p => {
      const w = n(p.width, 2.6);
      const parts: Part[] = [box([w, 0.9, 1.1], [0, 0.45, 0], C.wood)];
      for (const x of [-w / 2, w / 2]) for (const z of [-0.6, 0.6]) parts.push(cyl(0.08, 2.4, [x, 1.2, z], C.woodDark, undefined, 6));
      parts.push(box([w + 0.4, 0.1, 1.8], [0, 2.45, 0], s(p.color, C.orange), [-8, 0, 0]));
      return parts;
    },
  },
  well: {
    zh: "水井", category: "建筑", doc: "带辘轳架的井",
    build: () => [
      cyl(1.4, 0.8, [0, 0.4, 0], C.roof, undefined, 12), cyl(1.1, 0.82, [0, 0.42, 0], C.dark, undefined, 12),
      box([0.12, 2, 0.12], [-0.8, 1, 0], C.woodDark), box([0.12, 2, 0.12], [0.8, 1, 0], C.woodDark),
      box([1.8, 0.12, 0.12], [0, 1.9, 0], C.woodDark), ...gable(1.9, 1.2, 0.5, 2, C.roofDark, 0.1),
    ],
  },

  // ── 街道 ────────────────────────────────────────────────
  streetlamp: {
    zh: "路灯", category: "街道", doc: "路灯，灯头伸向 +Z",
    params: { height: { default: 4.5, doc: "高" }, style: { default: "modern", doc: "风格", options: ["modern", "ancient"] } },
    build: p => {
      const h = n(p.height, 4.5);
      if (s(p.style, "modern") === "ancient") {
        return [box([0.18, h, 0.18], [0, h / 2, 0], C.woodDark), box([0.12, 0.12, 0.8], [0, h - 0.2, 0.35], C.woodDark),
          { ...ball([0.45, 0.6, 0.45], [0, h - 0.6, 0.7], C.red), glow: true }];
      }
      return [cyl(0.16, h, [0, h / 2, 0], C.metal, undefined, 8), box([0.1, 0.1, 1.2], [0, h, 0.55], C.metal),
        { ...box([0.4, 0.12, 0.5], [0, h - 0.08, 1.05], C.light), glow: true }];
    },
  },
  traffic_light: {
    zh: "红绿灯", category: "街道", doc: "红绿灯，灯面朝 +Z",
    build: () => [
      cyl(0.16, 3.2, [0, 1.6, 0], C.dark, undefined, 8), box([0.45, 1.2, 0.35], [0, 3.6, 0], C.black),
      { ...ball([0.26, 0.26, 0.1], [0, 4, 0.18], C.red), glow: true }, ball([0.26, 0.26, 0.1], [0, 3.6, 0.18], C.yellow),
      ball([0.26, 0.26, 0.1], [0, 3.2, 0.18], "#4caf50"),
    ],
  },
  bench: {
    zh: "长椅", category: "街道", doc: "长椅，坐的人面朝 +Z",
    params: { length: { default: 1.8, doc: "长" } },
    build: p => {
      const l = n(p.length, 1.8);
      return [box([l, 0.08, 0.45], [0, 0.45, 0], C.wood), box([l, 0.45, 0.06], [0, 0.72, -0.22], C.wood, [-10, 0, 0]),
        box([0.08, 0.45, 0.45], [-l / 2 + 0.1, 0.22, 0], C.dark), box([0.08, 0.45, 0.45], [l / 2 - 0.1, 0.22, 0], C.dark)];
    },
  },
  trash_bin: { zh: "垃圾桶", category: "街道", doc: "垃圾桶", build: () => [cyl(0.5, 0.9, [0, 0.45, 0], C.dark, undefined, 10), cyl(0.54, 0.06, [0, 0.92, 0], C.black, undefined, 10)] },
  sign: {
    zh: "指示牌", category: "街道", doc: "立杆指示牌，牌面朝 +Z",
    build: () => [cyl(0.08, 2.6, [0, 1.3, 0], C.metal, undefined, 6), box([1, 0.6, 0.06], [0, 2.4, 0.05], C.blue)],
  },
  barrier: { zh: "路障", category: "街道", doc: "水马路障，沿 X 方向 2m", build: () => [box([2, 0.8, 0.45], [0, 0.4, 0], C.orange), box([2.02, 0.18, 0.47], [0, 0.55, 0], C.white)] },
  traffic_cone: { zh: "锥桶", category: "街道", doc: "交通锥", build: () => [box([0.4, 0.04, 0.4], [0, 0.02, 0], C.black), cone(0.34, 0.7, [0, 0.39, 0], C.orange, 10)] },
  hydrant: { zh: "消防栓", category: "街道", doc: "消防栓", build: () => [cyl(0.28, 0.6, [0, 0.3, 0], C.red, undefined, 8), ball([0.28, 0.2, 0.28], [0, 0.65, 0], C.red)] },
  bus_stop: {
    zh: "公交站", category: "街道", doc: "公交候车亭，候车一侧朝 +Z",
    build: () => [
      box([4, 0.12, 1.6], [0, 2.6, 0], C.roof), box([4, 2.3, 0.06], [0, 1.3, -0.75], C.glass),
      cyl(0.1, 2.6, [-1.9, 1.3, -0.7], C.metal, undefined, 6), cyl(0.1, 2.6, [1.9, 1.3, -0.7], C.metal, undefined, 6),
      box([3, 0.08, 0.4], [0, 0.45, -0.5], C.wood),
    ],
  },

  // ── 交通 ────────────────────────────────────────────────
  car: {
    zh: "轿车", category: "交通", doc: "轿车，车头朝 +Z（yaw 0 时往 +Z 开），长 4.5m",
    params: { color: { default: "#b8bec6", doc: "车身颜色" } },
    build: p => carParts(s(p.color, C.metal)),
  },
  police_car: {
    zh: "警车", category: "交通", doc: "警车（白蓝涂装＋警灯），车头朝 +Z",
    build: () => [
      ...carParts(C.white), box([1.84, 0.22, 2.2], [0, 0.62, 0.1], C.blue),
      { ...box([0.45, 0.16, 0.32], [-0.24, 1.53, -0.2], C.red), glow: true }, { ...box([0.45, 0.16, 0.32], [0.24, 1.53, -0.2], C.blue), glow: true },
    ],
  },
  truck: {
    zh: "货车", category: "交通", doc: "厢式货车，车头朝 +Z，长约 8m",
    params: { color: { default: "#e2e5e9", doc: "货厢颜色" } },
    build: p => [
      box([2.3, 2.2, 2.1], [0, 1.6, 2.7], C.blue), box([2.1, 0.9, 0.05], [0, 2.1, 3.76], C.glass),
      box([2.45, 2.9, 5.4], [0, 2.05, -1.2], s(p.color, C.wall2)), box([2.2, 0.4, 7.8], [0, 0.55, 0.3], C.dark),
      wheel(1, 0.4, [-1.05, 0.5, 2.6]), wheel(1, 0.4, [1.05, 0.5, 2.6]), wheel(1, 0.4, [-1.05, 0.5, -2.2]),
      wheel(1, 0.4, [1.05, 0.5, -2.2]), wheel(1, 0.4, [-1.05, 0.5, -3.3]), wheel(1, 0.4, [1.05, 0.5, -3.3]),
    ],
  },
  bus: {
    zh: "公交车", category: "交通", doc: "公交车，车头朝 +Z，长 11m",
    params: { color: { default: "#3f9d6b", doc: "车身颜色" } },
    build: p => [
      box([2.5, 2.9, 11], [0, 1.85, 0], s(p.color, "#3f9d6b")), box([2.52, 1, 10.2], [0, 2.35, -0.2], C.glass),
      box([2.3, 1.3, 0.05], [0, 2.2, 5.51], C.glass),
      wheel(1, 0.35, [-1.1, 0.5, 3.6]), wheel(1, 0.35, [1.1, 0.5, 3.6]), wheel(1, 0.35, [-1.1, 0.5, -3.4]), wheel(1, 0.35, [1.1, 0.5, -3.4]),
    ],
  },
  motorcycle: {
    zh: "摩托车", category: "交通", doc: "摩托车，车头朝 +Z",
    params: { color: { default: "#d65a55", doc: "颜色" } },
    build: p => [
      box([0.34, 0.45, 1.2], [0, 0.75, 0], s(p.color, C.red)), box([0.3, 0.1, 0.6], [0, 1.02, -0.2], C.black),
      box([0.7, 0.05, 0.05], [0, 1.08, 0.55], C.metal), wheel(0.64, 0.14, [0, 0.32, 0.72]), wheel(0.64, 0.14, [0, 0.32, -0.72]),
    ],
  },
  bicycle: {
    zh: "自行车", category: "交通", doc: "自行车，车头朝 +Z",
    build: () => [
      { prim: "torus", size: [0.68, 0.05, 0.68], pos: [0, 0.34, 0.52], rot: [0, 90, 0], color: C.black, segments: 16 },
      { prim: "torus", size: [0.68, 0.05, 0.68], pos: [0, 0.34, -0.52], rot: [0, 90, 0], color: C.black, segments: 16 },
      box([0.05, 0.05, 1.0], [0, 0.62, 0], C.red, [20, 0, 0]), box([0.05, 0.55, 0.05], [0, 0.6, -0.2], C.red),
      box([0.2, 0.05, 0.25], [0, 0.9, -0.22], C.black), box([0.55, 0.04, 0.04], [0, 0.98, 0.45], C.metal),
    ],
  },
  boat: {
    zh: "船", category: "交通", doc: "小船，船头朝 +Z。style=canopy 是带篷的乌篷船",
    params: { length: { default: 6, doc: "长" }, style: { default: "canopy", doc: "样式", options: ["rowboat", "canopy"] } },
    build: p => {
      const L = n(p.length, 6);
      // 船身＋尖船头（三棱柱放平，尖朝 +Z）
      const parts: Part[] = [
        box([1.6, 0.6, L * 0.75], [0, 0.3, -L * 0.075], C.wood),
        prism([1.6, L * 0.25, 0.6], [0, 0.3, L * 0.425], C.wood, [90, 0, 0]),
      ];
      if (s(p.style, "canopy") === "canopy") parts.push({ prim: "cylinder", size: [1.5, L * 0.4, 1.5], pos: [0, 0.6, -L * 0.05], rot: [90, 0, 0], color: C.dark, segments: 10, arc: [90, 180] });
      return parts;
    },
  },
  helicopter: {
    zh: "直升机", category: "交通", doc: "直升机，机头朝 +Z",
    build: () => [
      ball([1.8, 1.7, 3.4], [0, 1.6, 0.4], C.dark), box([0.3, 0.4, 3.6], [0, 1.9, -2.6], C.dark),
      box([0.08, 0.06, 9], [0, 2.65, 0.3], C.black), box([9, 0.06, 0.08], [0, 2.65, 0.3], C.black),
      box([0.08, 1.2, 0.4], [0, 2.2, -4.3], C.dark), box([0.08, 0.08, 2.6], [-0.7, 0.4, 0.3], C.metal), box([0.08, 0.08, 2.6], [0.7, 0.4, 0.3], C.metal),
    ],
  },
  horse_cart: {
    zh: "马车", category: "交通", doc: "带篷的马车（不含马），车辕朝 +Z",
    build: () => [
      box([1.6, 0.25, 2.4], [0, 0.9, 0], C.wood), box([1.6, 1.3, 2.2], [0, 1.7, -0.05], C.roofDark),
      wheel(1.3, 0.12, [-0.9, 0.65, 0]), wheel(1.3, 0.12, [0.9, 0.65, 0]),
      box([0.08, 0.08, 2.4], [-0.35, 0.85, 2.1], C.woodDark), box([0.08, 0.08, 2.4], [0.35, 0.85, 2.1], C.woodDark),
    ],
  },

  // ── 自然 ────────────────────────────────────────────────
  tree: {
    zh: "树", category: "自然", doc: "树。kind：round 阔叶、pine 松、palm 椰、willow 柳",
    params: { height: { default: 5, doc: "高" }, kind: { default: "round", doc: "树种", options: ["round", "pine", "palm", "willow"] } },
    build: p => {
      const H = n(p.height, 5), k = s(p.kind, "round");
      if (k === "pine") return [cyl(0.3, H * 0.3, [0, H * 0.15, 0], C.trunk, undefined, 6),
        cone(H * 0.55, H * 0.45, [0, H * 0.45, 0], C.foliageDark, 7), cone(H * 0.42, H * 0.4, [0, H * 0.68, 0], C.foliageDark, 7),
        cone(H * 0.28, H * 0.3, [0, H * 0.88, 0], C.foliageDark, 7)];
      if (k === "palm") {
        const parts: Part[] = [cyl(0.28, H, [0, H / 2, 0], C.trunk, [3, 0, 0], 6)];
        for (let i = 0; i < 6; i++) parts.push(box([0.5, 0.06, H * 0.45], [Math.sin(i) * H * 0.18, H - 0.1, Math.cos(i) * H * 0.18], C.foliage, [-25, (i * 360) / 6, 0]));
        return parts;
      }
      if (k === "willow") return [cyl(0.4, H * 0.5, [0, H * 0.25, 0], C.trunk, undefined, 6),
        ball([H * 0.7, H * 0.45, H * 0.7], [0, H * 0.7, 0], C.foliage), cone(H * 0.75, H * 0.55, [0, H * 0.35, 0], C.foliage, 9, [180, 0, 0])];
      return [cyl(0.32, H * 0.45, [0, H * 0.225, 0], C.trunk, undefined, 6), ball([H * 0.55, H * 0.5, H * 0.55], [0, H * 0.68, 0], C.foliage, 7)];
    },
  },
  bush: { zh: "灌木", category: "自然", doc: "一丛灌木", params: { size: { default: 1.2, doc: "大小" } },
    build: p => { const k = n(p.size, 1.2); return [ball([k * 1.3, k * 0.8, k * 1.1], [0, k * 0.4, 0], C.foliageDark, 6), ball([k * 0.8, k * 0.7, k * 0.8], [k * 0.4, k * 0.45, k * 0.2], C.foliage, 6)]; } },
  rock: { zh: "石头", category: "自然", doc: "一块石头", params: { size: { default: 1, doc: "大小" } },
    build: p => { const k = n(p.size, 1); return [ball([k * 1.2, k * 0.75, k], [0, k * 0.3, 0], C.roofDark, 5)]; } },
  mountain: { zh: "远山", category: "自然", doc: "远景的山（很大，放远处当背景）", params: { height: { default: 30, doc: "高" }, width: { default: 70, doc: "底宽" } },
    build: p => [cone(n(p.width, 70), n(p.height, 30), [0, n(p.height, 30) / 2, 0], "#c7ced7", 7)] },
  flower_bed: { zh: "花坛", category: "自然", doc: "方形花坛", params: { width: { default: 2, doc: "宽" } },
    build: p => { const w = n(p.width, 2); return [box([w, 0.4, w], [0, 0.2, 0], C.wall2), ball([w * 0.9, 0.5, w * 0.9], [0, 0.5, 0], "#c98fa0", 6)]; } },

  // ── 室内 ────────────────────────────────────────────────
  table: {
    zh: "桌子", category: "室内", doc: "桌子。shape：square 方桌、round 圆桌",
    params: { shape: { default: "square", doc: "形状", options: ["square", "round"] }, width: { default: 1.2, doc: "宽/直径" } },
    build: p => {
      const w = n(p.width, 1.2);
      if (s(p.shape, "square") === "round") return [cyl(w, 0.06, [0, 0.76, 0], C.wood, undefined, 16), cyl(0.12, 0.73, [0, 0.37, 0], C.woodDark, undefined, 8), cyl(0.6, 0.04, [0, 0.02, 0], C.woodDark, undefined, 12)];
      return [box([w, 0.06, w * 0.8], [0, 0.76, 0], C.wood), ...[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([x, z]) => box([0.06, 0.73, 0.06], [x * (w / 2 - 0.08), 0.37, z * (w * 0.4 - 0.08)], C.woodDark))];
    },
  },
  chair: {
    zh: "椅子", category: "室内", doc: "椅子，坐的人面朝 +Z",
    build: () => [box([0.48, 0.06, 0.46], [0, 0.46, 0], C.wood), box([0.48, 0.55, 0.05], [0, 0.76, -0.21], C.wood),
      ...[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([x, z]) => box([0.05, 0.44, 0.05], [x * 0.2, 0.22, z * 0.19], C.woodDark))],
  },
  stool: { zh: "凳子", category: "室内", doc: "圆凳", build: () => [cyl(0.36, 0.05, [0, 0.45, 0], C.wood, undefined, 10), cyl(0.3, 0.42, [0, 0.21, 0], C.woodDark, undefined, 8)] },
  sofa: {
    zh: "沙发", category: "室内", doc: "三人沙发，坐的人面朝 +Z",
    params: { color: { default: "#9aa6b8", doc: "颜色" } },
    build: p => { const c = s(p.color, "#9aa6b8"); return [box([2.1, 0.45, 0.9], [0, 0.22, 0], c), box([2.1, 0.5, 0.2], [0, 0.7, -0.35], c), box([0.2, 0.3, 0.9], [-0.95, 0.55, 0], c), box([0.2, 0.3, 0.9], [0.95, 0.55, 0], c)]; },
  },
  bed: { zh: "床", category: "室内", doc: "双人床，床头在 -Z",
    build: () => [box([1.6, 0.35, 2.1], [0, 0.18, 0], C.woodDark), box([1.5, 0.2, 2], [0, 0.45, 0.02], C.white), box([1.6, 0.9, 0.08], [0, 0.6, -1.04], C.woodDark), box([1.2, 0.12, 0.4], [0, 0.61, -0.75], C.wall2)] },
  desk: { zh: "书桌", category: "室内", doc: "书桌／办公桌。人一般坐在它的 -Z 一侧、面朝 +Z", build: () => [box([1.4, 0.05, 0.7], [0, 0.75, 0], C.wood), box([0.05, 0.73, 0.68], [-0.66, 0.37, 0], C.woodDark), box([0.05, 0.73, 0.68], [0.66, 0.37, 0], C.woodDark)] },
  shelf: { zh: "书架", category: "室内", doc: "靠墙书架，正面朝 +Z",
    build: () => { const parts: Part[] = [box([1.2, 2, 0.35], [0, 1, 0], C.wood)]; for (let i = 1; i < 5; i++) parts.push(box([1.1, 0.26, 0.05], [0, 0.4 * i, 0.16], C.woodDark)); return parts; } },
  door: { zh: "门", category: "室内", doc: "门框＋门扇，门扇朝 +Z", params: { width: { default: 1, doc: "宽" }, height: { default: 2.1, doc: "高" } },
    build: p => { const w = n(p.width, 1), h = n(p.height, 2.1); return [box([w + 0.2, h + 0.1, 0.12], [0, (h + 0.1) / 2, 0], C.wall2), box([w, h, 0.06], [0, h / 2, 0.06], C.woodDark)]; } },
  window: { zh: "窗", category: "室内", doc: "窗框（挂在墙上用 y 调高度）", params: { width: { default: 1.2, doc: "宽" }, height: { default: 1.2, doc: "高" } },
    build: p => { const w = n(p.width, 1.2), h = n(p.height, 1.2); return [box([w, h, 0.08], [0, h / 2, 0], C.wall2), box([w * 0.85, h * 0.85, 0.1], [0, h / 2, 0.01], C.glass)]; } },
  counter: { zh: "柜台", category: "室内", doc: "柜台，客人一侧朝 +Z", params: { length: { default: 2.4, doc: "长" } },
    build: p => { const l = n(p.length, 2.4); return [box([l, 1.05, 0.6], [0, 0.52, 0], C.wood), box([l + 0.1, 0.05, 0.7], [0, 1.08, 0], C.woodDark)]; } },
  screen: { zh: "屏风", category: "室内", doc: "四扇屏风，沿 X 展开",
    build: () => [-1.2, -0.4, 0.4, 1.2].map((x, i) => box([0.78, 1.8, 0.04], [x, 0.95, i % 2 ? 0.08 : -0.08], C.wood, [0, i % 2 ? 12 : -12, 0])) },
  cabinet: { zh: "柜子", category: "室内", doc: "立柜，正面朝 +Z", build: () => [box([1, 1.9, 0.55], [0, 0.95, 0], C.wood), box([0.02, 1.7, 0.02], [0, 0.95, 0.28], C.woodDark)] },
  floor_lamp: { zh: "落地灯", category: "室内", doc: "落地灯", build: () => [cyl(0.3, 0.04, [0, 0.02, 0], C.dark, undefined, 10), cyl(0.04, 1.5, [0, 0.77, 0], C.dark, undefined, 6), { ...cone(0.45, 0.35, [0, 1.6, 0], C.light, 10), glow: true }] },

  // ── 道具 ────────────────────────────────────────────────
  crate: { zh: "木箱", category: "道具", doc: "木箱", params: { size: { default: 0.8, doc: "边长" } },
    build: p => { const k = n(p.size, 0.8); return [box([k, k, k], [0, k / 2, 0], C.wood), box([k + 0.02, 0.08, k + 0.02], [0, k * 0.8, 0], C.woodDark)]; } },
  barrel: { zh: "木桶", category: "道具", doc: "木桶",
    build: () => [cyl(0.6, 0.9, [0, 0.45, 0], C.wood, undefined, 12), cyl(0.63, 0.06, [0, 0.2, 0], C.dark, undefined, 12), cyl(0.63, 0.06, [0, 0.7, 0], C.dark, undefined, 12)] },
  sack: { zh: "麻袋", category: "道具", doc: "装满的麻袋", build: () => [ball([0.6, 0.7, 0.45], [0, 0.35, 0], C.wood, 6)] },
  cart: { zh: "手推车", category: "道具", doc: "两轮手推车，把手朝 -Z",
    build: () => [box([1, 0.35, 1.3], [0, 0.75, 0], C.wood), wheel(0.9, 0.08, [-0.58, 0.45, 0.1]), wheel(0.9, 0.08, [0.58, 0.45, 0.1]),
      box([0.06, 0.06, 1.1], [-0.35, 0.75, -1.1], C.woodDark), box([0.06, 0.06, 1.1], [0.35, 0.75, -1.1], C.woodDark)] },
  lantern: { zh: "灯笼", category: "道具", doc: "红灯笼（用 at 的 y 挂到高处，比如 [x, 3, z]）",
    build: () => [{ ...ball([0.45, 0.55, 0.45], [0, 0.35, 0], C.red, 10), glow: true }, cyl(0.2, 0.06, [0, 0.64, 0], C.yellow, undefined, 8), cyl(0.2, 0.06, [0, 0.06, 0], C.yellow, undefined, 8)] },
  flag: { zh: "旗帜", category: "道具", doc: "旗杆＋旗面（旗面朝 +X 展开）", params: { color: { default: "#d65a55", doc: "旗色" }, height: { default: 4, doc: "杆高" } },
    build: p => { const h = n(p.height, 4); return [cyl(0.08, h, [0, h / 2, 0], C.metal, undefined, 6), box([1.3, 0.8, 0.03], [0.68, h - 0.45, 0], s(p.color, C.red))]; } },
  weapon_rack: { zh: "兵器架", category: "道具", doc: "兵器架（几根长杆斜靠）",
    build: () => [box([1.6, 0.1, 0.4], [0, 0.05, 0], C.woodDark), box([1.6, 0.1, 0.1], [0, 1.2, -0.15], C.woodDark),
      ...[-0.6, -0.2, 0.2, 0.6].map(x => box([0.05, 2.2, 0.05], [x, 1.1, 0], C.dark, [8, 0, 0]))] },

  // ── 标记 ────────────────────────────────────────────────
  marker: { zh: "区域标记", category: "标记", doc: "地面上的半透明色块（标出区域，不出现在成片里）",
    params: { width: { default: 4, doc: "宽" }, depth: { default: 4, doc: "深" }, color: { default: "#4aa3ff", doc: "颜色" } },
    build: p => [{ ...box([n(p.width, 4), 0.02, n(p.depth, 4)], [0, 0.02, 0], s(p.color, "#4aa3ff")), opacity: 0.35 }] },
  arrow: { zh: "方向箭头", category: "标记", doc: "地面箭头，指向 +Z", params: { length: { default: 3, doc: "长" }, color: { default: "#ffb400", doc: "颜色" } },
    build: p => { const l = n(p.length, 3), c = s(p.color, "#ffb400"); return [box([0.3, 0.03, l * 0.7], [0, 0.03, -l * 0.15], c), prism([1, l * 0.3, 0.06], [0, 0.03, l * 0.35], c, [90, 0, 0])]; } },
  image_board: { zh: "图片板", category: "标记", doc: "竖立的图片板（url 贴图，正面朝 +Z），可当背景或参考",
    params: { width: { default: 4, doc: "宽" }, height: { default: 3, doc: "高" }, url: { default: "", doc: "图片地址" } },
    build: p => { const w = n(p.width, 4), h = n(p.height, 3); return [box([w, h, 0.06], [0, h / 2, 0], C.white)]; } },

  // ── 动物 ────────────────────────────────────────────────
  bird: { zh: "鸟", category: "动物", doc: "飞鸟（展翅），头朝 +Z；用 at 的 y 放到空中",
    build: () => [ball([0.3, 0.3, 0.7], [0, 0, 0], C.dark, 6), box([1.2, 0.03, 0.35], [0, 0.05, 0], C.dark, [0, 0, 8]), cone(0.1, 0.2, [0, 0, 0.43], C.yellow, 5, [90, 0, 0])] },
  horse: { zh: "马", category: "动物", doc: "马，头朝 +Z",
    build: () => [
      box([0.6, 0.7, 1.7], [0, 1.35, 0], C.woodDark), box([0.35, 0.8, 0.4], [0, 1.85, 0.85], C.woodDark, [30, 0, 0]),
      box([0.3, 0.35, 0.65], [0, 2.2, 1.2], C.woodDark), ...[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([x, z]) => box([0.14, 1, 0.14], [x * 0.2, 0.5, z * 0.65], C.woodDark)),
      box([0.08, 0.6, 0.08], [0, 1.2, -0.95], C.dark, [-30, 0, 0]),
    ] },
  dog: { zh: "狗", category: "动物", doc: "狗，头朝 +Z",
    build: () => [box([0.3, 0.3, 0.7], [0, 0.45, 0], C.wood), box([0.25, 0.25, 0.3], [0, 0.65, 0.42], C.wood),
      ...[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([x, z]) => box([0.08, 0.32, 0.08], [x * 0.1, 0.16, z * 0.25], C.wood))] },
};

function carParts(color: string): Part[] {
  return [
    box([1.8, 0.7, 4.5], [0, 0.6, 0], color), box([1.6, 0.62, 2.3], [0, 1.25, -0.25], "#cfd8e2"),
    box([1.62, 0.1, 2.32], [0, 1.58, -0.25], color),
    wheel(0.66, 0.26, [-0.86, 0.33, 1.45]), wheel(0.66, 0.26, [0.86, 0.33, 1.45]),
    wheel(0.66, 0.26, [-0.86, 0.33, -1.45]), wheel(0.66, 0.26, [0.86, 0.33, -1.45]),
    { ...box([0.42, 0.14, 0.05], [-0.6, 0.7, 2.26], C.light), glow: true }, { ...box([0.42, 0.14, 0.05], [0.6, 0.7, 2.26], C.light), glow: true },
    box([0.42, 0.14, 0.05], [-0.6, 0.7, -2.26], C.red), box([0.42, 0.14, 0.05], [0.6, 0.7, -2.26], C.red),
  ];
}

/** 部件表的包围盒（局部，粗略：只考虑绕 Y 转 90° 的换轴）。 */
export function partsBounds(parts: Part[]): { min: Vec3; max: Vec3 } {
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const p of parts) {
    let [sx, sy, sz] = p.size;
    // 圆环默认躺在 XY 面（绕 Z 轴一圈）
    if (p.prim === "torus") { sx = p.size[0]; sy = p.size[0]; sz = p.size[1]; }
    const ry = Math.abs(((p.rot?.[1] ?? 0) % 180 + 180) % 180);
    if (ry > 45 && ry < 135) [sx, sz] = [sz, sx];
    const rx = Math.abs(((p.rot?.[0] ?? 0) % 180 + 180) % 180);
    if (rx > 45 && rx < 135) [sy, sz] = [sz, sy];
    const half: Vec3 = [sx / 2, sy / 2, sz / 2];
    for (let i = 0; i < 3; i++) {
      min[i] = Math.min(min[i], p.pos[i] - half[i]);
      max[i] = Math.max(max[i], p.pos[i] + half[i]);
    }
  }
  if (!Number.isFinite(min[0])) return { min: [0, 0, 0], max: [0, 0, 0] };
  return { min, max };
}

export function prefabDefaults(name: string): Record<string, ParamValue> {
  const def = PREFABS[name];
  const out: Record<string, ParamValue> = {};
  for (const [k, v] of Object.entries(def?.params ?? {})) out[k] = v.default;
  return out;
}

// ── 人物 ────────────────────────────────────────────────

/** 体型：身高（米）与比例。渲染用同一张表。 */
export const BODIES: Record<string, { zh: string; height: number; width: number; head: number }> = {
  male: { zh: "标准男性", height: 1.75, width: 1, head: 1 },
  female: { zh: "标准女性", height: 1.65, width: 0.9, head: 1 },
  teen: { zh: "少年", height: 1.6, width: 0.88, head: 1.04 },
  child: { zh: "儿童", height: 1.25, width: 0.8, head: 1.18 },
  chibi: { zh: "二头身", height: 1.05, width: 0.95, head: 1.9 },
  slim: { zh: "纤细", height: 1.72, width: 0.8, head: 1 },
  muscular: { zh: "健硕", height: 1.82, width: 1.22, head: 1 },
  broad: { zh: "宽厚", height: 1.76, width: 1.3, head: 1.02 },
  elder: { zh: "老人", height: 1.62, width: 0.95, head: 1 },
};

export const POSES: Record<string, string> = {
  stand: "站立", walk: "行走", run: "奔跑", sit: "坐", crouch: "蹲", kneel: "跪",
  point: "指向前方", wave: "挥手", fight: "格斗架势", lie: "躺", phone: "打电话",
  arms_crossed: "抱臂", hands_up: "举手投降", drive: "开车（坐姿，双手前伸）", aim: "举枪瞄准", bow: "鞠躬",
};

/** 给 LLM 和界面用的目录：预制件、体型、姿势。 */
export function catalogDoc() {
  return {
    prefabs: Object.entries(PREFABS).map(([name, d]) => {
      const bb = partsBounds(d.build(prefabDefaults(name)));
      return {
        name, zh: d.zh, category: d.category, doc: d.doc,
        size: [0, 1, 2].map(i => +(bb.max[i] - bb.min[i]).toFixed(2)),
        params: Object.fromEntries(Object.entries(d.params ?? {}).map(([k, v]) =>
          [k, { default: v.default, doc: v.doc, ...(v.options ? { options: v.options } : {}) }])),
      };
    }),
    bodies: Object.entries(BODIES).map(([name, v]) => ({ name, zh: v.zh, height: v.height })),
    poses: Object.entries(POSES).map(([name, zh]) => ({ name, zh })),
  };
}
