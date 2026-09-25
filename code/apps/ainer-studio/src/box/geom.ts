/**
 * 白模的几何体与材质缓存：同一种基本体只建一次，按部件尺寸缩放。
 * 几百个预制件、几千个部件共用十几个几何体，渲染和内存都扛得住。
 */
import * as THREE from "three";
import type { Part } from "../scene/prefabs";
import type { Vec2 } from "../scene/types";
export { GROUND, partColor, SKY, STRIP_COLOR } from "../scene/palette";

const geoCache = new Map<string, THREE.BufferGeometry>();

function prismGeometry(): THREE.BufferGeometry {
  // 三角形在 XY 面（底宽 1、高 1，居中），沿 Z 拉伸 1
  const shape = new THREE.Shape();
  shape.moveTo(-0.5, -0.5);
  shape.lineTo(0.5, -0.5);
  shape.lineTo(0, 0.5);
  shape.closePath();
  const g = new THREE.ExtrudeGeometry(shape, { depth: 1, bevelEnabled: false });
  g.translate(0, 0, -0.5);
  return g;
}

/** 单位基本体（尺寸 1），部件用 mesh.scale 撑到自己的大小。 */
export function unitGeometry(p: Part): THREE.BufferGeometry {
  const seg = p.segments ?? 12;
  const arc = p.arc ?? [0, 360];
  const key = p.prim === "torus" ? `torus:${seg}:${(p.size[1] / p.size[0]).toFixed(3)}:${arc[1]}` : `${p.prim}:${seg}:${arc[0]}:${arc[1]}`;
  let g = geoCache.get(key);
  if (g) return g;
  const a0 = THREE.MathUtils.degToRad(arc[0]), al = THREE.MathUtils.degToRad(arc[1]);
  const open = arc[1] < 360;
  switch (p.prim) {
    case "box": case "plane": g = new THREE.BoxGeometry(1, 1, 1); break;
    case "sphere": g = new THREE.SphereGeometry(0.5, Math.max(5, seg), Math.max(4, Math.round(seg * 0.7))); break;
    case "cylinder": g = new THREE.CylinderGeometry(0.5, 0.5, 1, Math.max(3, seg), 1, open, a0, al); break;
    case "cone": g = new THREE.ConeGeometry(0.5, 1, Math.max(3, seg), 1, open, a0, al); break;
    case "capsule": g = new THREE.CapsuleGeometry(0.25, 0.5, 4, Math.max(6, seg)); break;
    case "prism": g = prismGeometry(); break;
    case "torus": {
      // 圆环不能非等比缩放（管会变扁）：按「管径/直径」的比例建一个直径 1 的圆环
      const ratio = p.size[1] / p.size[0];
      g = new THREE.TorusGeometry(0.5, 0.5 * ratio, 8, Math.max(8, seg), al || Math.PI * 2);
      break;
    }
    default: g = new THREE.BoxGeometry(1, 1, 1);
  }
  geoCache.set(key, g);
  return g;
}

/** 部件的网格缩放：圆环按直径等比，其它按三轴尺寸。 */
export function partScale(p: Part): [number, number, number] {
  if (p.prim === "torus") return [p.size[0], p.size[0], p.size[0]];
  return [p.size[0], p.size[1], p.size[2]];
}

const matCache = new Map<string, THREE.Material>();

export function material(color: string, opts: { glow?: boolean; opacity?: number; selected?: boolean; ghost?: boolean } = {}): THREE.Material {
  const key = `${color}|${opts.glow ? 1 : 0}|${opts.opacity ?? 1}|${opts.selected ? 1 : 0}|${opts.ghost ? 1 : 0}`;
  let m = matCache.get(key);
  if (m) return m;
  const c = new THREE.Color(color);
  if (opts.selected) c.lerp(new THREE.Color("#8f82ff"), 0.45);
  m = new THREE.MeshStandardMaterial({
    color: c, flatShading: true, roughness: 0.86, metalness: 0,
    emissive: opts.glow ? c : new THREE.Color("#000000"), emissiveIntensity: opts.glow ? 0.9 : 0,
    transparent: (opts.opacity ?? 1) < 1 || !!opts.ghost, opacity: opts.ghost ? 0.35 : (opts.opacity ?? 1),
    side: THREE.DoubleSide, depthWrite: !((opts.opacity ?? 1) < 1),
  });
  matCache.set(key, m);
  return m;
}


// ── 地面带（道路、河流）────────────────────────────────


/** 沿折线的带子：每个折点取相邻两段法线的平均，拐弯处不断开。 */
export function stripGeometry(points: Vec2[], width: number, y: number): THREE.BufferGeometry {
  const n = points.length;
  const pos: number[] = [];
  const idx: number[] = [];
  const uv: number[] = [];
  let acc = 0;
  for (let i = 0; i < n; i++) {
    const p = points[i];
    const prev = points[Math.max(0, i - 1)], next = points[Math.min(n - 1, i + 1)];
    let dx = next[0] - prev[0], dz = next[1] - prev[1];
    const l = Math.hypot(dx, dz) || 1;
    dx /= l; dz /= l;
    const nx = -dz, nz = dx;
    if (i) acc += Math.hypot(p[0] - points[i - 1][0], p[1] - points[i - 1][1]);
    pos.push(p[0] + nx * width / 2, y, p[1] + nz * width / 2, p[0] - nx * width / 2, y, p[1] - nz * width / 2);
    uv.push(0, acc / width, 1, acc / width);
    if (i < n - 1) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/** 中线虚线：每 6m 一段 3m 的白线。 */
export function dashGeometry(points: Vec2[], y: number): THREE.BufferGeometry {
  const quads: number[] = [];
  const idx: number[] = [];
  let k = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const L = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (L < 0.01) continue;
    const dx = (b[0] - a[0]) / L, dz = (b[1] - a[1]) / L;
    const nx = -dz * 0.08, nz = dx * 0.08;
    for (let s = 1; s + 3 <= L; s += 6) {
      const x0 = a[0] + dx * s, z0 = a[1] + dz * s, x1 = x0 + dx * 3, z1 = z0 + dz * 3;
      quads.push(x0 + nx, y, z0 + nz, x0 - nx, y, z0 - nz, x1 + nx, y, z1 + nz, x1 - nx, y, z1 - nz);
      idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2);
      k += 4;
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(quads, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}


