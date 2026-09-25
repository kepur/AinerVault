/**
 * 白模色板：天空、地面、道路、部件主色。纯数据 —— 前端渲染、后端烘焙（给 Blender）共用，
 * 两边颜色一致，预览和 Blender 渲出来的白模看起来一样。
 */
import type { Part } from "./prefabs";
import type { SceneObject } from "./types";

/** 这些是「主色」：物体设了 color 时换掉它们；玻璃、轮胎、灯保留。 */
const MAIN = new Set(["#eceef1", "#dfe3e8", "#b8bec6", "#f7f7f8", "#cdb99e", "#c3c9d1"]);
export function partColor(p: Part, obj: SceneObject): string {
  const base = p.color ?? "#dfe3e8";
  if (obj.color && MAIN.has(base.toLowerCase())) return obj.color;
  return base;
}

export const STRIP_COLOR: Record<string, string> = {
  asphalt: "#8e949c", stone: "#cbc6bc", dirt: "#c4ae8e", water: "#9dbad1", grass: "#a3bb97", sand: "#dccb9f",
};

export const SKY: Record<string, { bg: string; hemiSky: string; hemiGround: string; sun: string; sunI: number }> = {
  day: { bg: "#cfdcea", hemiSky: "#e8f1ff", hemiGround: "#8b8f96", sun: "#ffffff", sunI: 1.2 },
  dawn: { bg: "#e7d4cc", hemiSky: "#ffe6d8", hemiGround: "#80828a", sun: "#ffd7b5", sunI: 0.9 },
  dusk: { bg: "#d9c3b6", hemiSky: "#ffd8bd", hemiGround: "#6f727c", sun: "#ffc190", sunI: 0.9 },
  night: { bg: "#23283a", hemiSky: "#5a6a90", hemiGround: "#1d2029", sun: "#a9b8e6", sunI: 0.35 },
  overcast: { bg: "#c9ccd1", hemiSky: "#eceef2", hemiGround: "#8d9096", sun: "#ffffff", sunI: 0.6 },
  studio: { bg: "#9ea2aa", hemiSky: "#f2f2f4", hemiGround: "#7d8088", sun: "#ffffff", sunI: 1 },
};

export const GROUND: Record<string, string> = {
  grid: "#d9dce1", asphalt: "#a7abb2", grass: "#b6c7ab", sand: "#e2d6b6", snow: "#f2f4f7",
  water: "#a9c2d6", stone: "#d3cfc7", floor: "#d9d2c6", dirt: "#cdbb9d",
};
