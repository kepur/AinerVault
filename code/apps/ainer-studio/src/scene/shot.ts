/**
 * 镜头报告：某台机位在某一刻「画面里有谁、在哪、多大、被谁挡住」。
 *
 * 智能体看不到画面，改完机位只能靠这个确认效果 —— 没有它，它会把同一个改动
 * 反复提交（实测一次运行里同一个 set_camera 连发 14 遍，直到步数用完）。
 */
import type { SceneDoc, SceneObject, Vec3 } from "./types";
import { SceneEval } from "./evaluate";
import { PREFABS } from "./prefabs";
import * as M from "./math";

const IMPORTANT = new Set(["car", "police_car", "truck", "bus", "motorcycle", "bicycle", "boat", "helicopter", "horse", "horse_cart", "bird", "dog"]);

function describePos(x: number, y: number) {
  const h = x < -0.33 ? "左" : x > 0.33 ? "右" : "中";
  const v = y > 0.33 ? "上" : y < -0.33 ? "下" : "中";
  return h === "中" && v === "中" ? "画面正中" : `画面${v === "中" ? "" : v}${h === "中" ? "中" : h}${v === "中" ? "侧" : ""}`;
}

function sizeWord(frac: number) {
  if (frac > 1.2) return "大特写（画不下）";
  if (frac > 0.75) return "特写";
  if (frac > 0.45) return "近景";
  if (frac > 0.25) return "中景";
  if (frac > 0.1) return "全景";
  if (frac > 0.03) return "远景";
  return "极小";
}

/** 包围球（半径、中心）：挡没挡住用它判断就够了 */
function sphere(ev: SceneEval, o: SceneObject, t: number): { c: Vec3; r: number } {
  const w = ev.world(o.id, t);
  const s = o.size;
  const k = Math.max(w.scale[0], w.scale[1], w.scale[2]);
  return { c: [w.pos[0], w.pos[1] + (s[1] * w.scale[1]) / 2, w.pos[2]], r: (Math.max(s[0], s[2], s[1] * 0.6) * k) / 2 };
}

export function shotReport(doc: SceneDoc, camId: string, t: number): string {
  const ev = new SceneEval(doc);
  const cam = doc.cameras.find(c => c.id === camId || c.name === camId);
  if (!cam) return `没有机位「${camId}」`;
  const p = ev.camera({ ...cam, shake: 0 }, t);
  const fwd = M.norm(M.sub(p.look, p.pos));
  const right: Vec3 = M.norm([-fwd[2], 0, fwd[0]]);   // f × up
  const up: Vec3 = [right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2], right[0] * fwd[1] - right[1] * fwd[0]];
  const tanH = 18 / p.lens, tanV = tanH / doc.aspect;
  const pitch = M.deg(Math.asin(M.clamp(fwd[1], -1, 1)));
  const lines = [
    `机位「${cam.name}」在 ${t.toFixed(1)}s：位置 [${p.pos.map(v => v.toFixed(1)).join(", ")}]，看向 [${p.look.map(v => v.toFixed(1)).join(", ")}]，` +
    `${Math.round(p.lens)}mm，${pitch < -35 ? "大俯拍" : pitch < -10 ? "俯拍" : pitch > 20 ? "大仰拍" : pitch > 6 ? "仰拍" : "平视"}（俯仰 ${pitch.toFixed(0)}°）`,
  ];
  const cands = doc.objects.filter(o => !o.tags.includes("hidden") && o.kind !== "strip" && o.kind !== "group" && o.prefab !== "mountain" && o.prefab !== "marker");
  const spheres = new Map(cands.map(o => [o.id, sphere(ev, o, t)]));
  const seen: { o: SceneObject; x: number; y: number; frac: number; dist: number; occ: string[] }[] = [];
  for (const o of cands) {
    const s = spheres.get(o.id)!;
    const rel = M.sub(s.c, p.pos);
    const z = M.dot(rel, fwd);
    if (z < 0.3) continue;
    const x = M.dot(rel, right) / (z * tanH), y = M.dot(rel, up) / (z * tanV);
    const hFrac = (o.size[1] * ev.world(o.id, t).scale[1]) / (2 * z * tanV);
    if (Math.abs(x) - (s.r / (z * tanH)) > 1 || Math.abs(y) - (s.r / (z * tanV)) > 1) continue;
    seen.push({ o, x, y, frac: hFrac, dist: z, occ: [] });
  }
  // 值得报告的：人物、载具、起了名字的物体（批量摆放出来的树和路灯只计数）
  const named = (o: SceneObject) => o.kind === "character" || IMPORTANT.has(o.prefab ?? "") || (!/#\d+$/.test(o.id) && o.name !== o.prefab);
  // 遮挡：从机位到目标中心的线段，被更近的包围球切到就算挡住
  const important = seen.filter(v => named(v.o));
  for (const v of important) {
    const target = spheres.get(v.o.id)!;
    const seg = M.sub(target.c, p.pos);
    const L = M.len(seg);
    const d = M.scale(seg, 1 / L);
    for (const other of seen) {
      if (other.o.id === v.o.id || other.dist >= v.dist) continue;
      const s = spheres.get(other.o.id)!;
      const along = M.dot(M.sub(s.c, p.pos), d);
      if (along <= 0 || along >= L - target.r) continue;
      const closest = M.add(p.pos, M.scale(d, along));
      if (M.dist(closest, s.c) < s.r * 0.85) v.occ.push(other.o.name);
    }
  }
  const rows = seen.filter(v => named(v.o)).sort((a, b) => b.frac - a.frac).slice(0, 12);
  if (!rows.length) lines.push("画面里没有人物、载具或起了名字的物体（可能对着空地、天空或墙）");
  for (const v of rows) {
    const kind = v.o.kind === "character" ? "人物" : PREFABS[v.o.prefab ?? ""]?.zh ?? v.o.kind;
    lines.push(`- ${v.o.name}（${kind}）：${describePos(v.x, v.y)}（x ${Math.round((v.x + 1) * 50)}%，y ${Math.round((1 - v.y) * 50)}%），` +
      `高度占画面 ${Math.round(v.frac * 100)}%（${sizeWord(v.frac)}），距离 ${v.dist.toFixed(1)}m` +
      (v.occ.length ? `；被挡住：${[...new Set(v.occ)].slice(0, 3).join("、")}` : ""));
  }
  const bg = seen.filter(v => !named(v.o));
  if (bg.length) {
    const counts: Record<string, number> = {};
    for (const v of bg) { const k = PREFABS[v.o.prefab ?? ""]?.zh ?? v.o.kind; counts[k] = (counts[k] ?? 0) + 1; }
    lines.push(`背景里还有：${Object.entries(counts).map(([k, n]) => `${k}×${n}`).join("、")}`);
  }
  return lines.join("\n");
}
