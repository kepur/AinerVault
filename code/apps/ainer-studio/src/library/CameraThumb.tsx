/**
 * 运镜缩略图：用 3D-BOX 同一套运镜预设实算一遍机位轨迹，画成俯视图（上 = 人物前方 +Z）。
 * 鼠标悬停时机位沿轨迹跑、人物跟着走（跟拍类的人物会往前走），右侧竖条是机位高度，底部是焦段变化。
 * 纯前端计算：场景运行时不依赖 three，这里不会把 3D 引擎拉进来。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { makeBuilder } from "../scene/runtime";
import { SceneEval } from "../scene/evaluate";
import type { Vec3 } from "../scene/types";

const DUR = 4;
const N = 48;
const WALKING = /follow|first_person|top_to_follow|front_to_back|side_follow|drone/;

interface Track { cam: Vec3[]; look: Vec3[]; lens: number[]; who: Vec3[] }

const cache = new Map<string, Track | null>();

function compute(preset: string): Track | null {
  if (cache.has(preset)) return cache.get(preset)!;
  let out: Track | null = null;
  try {
    const b = makeBuilder({ seed: 1 });
    const S = b.S as unknown as Record<string, (...a: unknown[]) => { id: string }>;
    const who = S.character("人", { body: "male", at: [0, 0], facing: 0 });
    if (WALKING.test(preset)) S.moveTo(who, [0, 5], { t: 0, duration: DUR });
    const cam = S.camera("c", { lens: 35 });
    S.cameraPreset(cam, preset, { target: who, start: 0, duration: DUR });
    const { doc } = b.finish();
    const ev = new SceneEval(doc);
    const c = doc.cameras[0];
    out = { cam: [], look: [], lens: [], who: [] };
    for (let i = 0; i <= N; i++) {
      const t = (i / N) * DUR;
      const p = ev.camera(c, t);
      out.cam.push(p.pos); out.look.push(p.look); out.lens.push(p.lens);
      out.who.push(ev.world(who.id, t).pos);
    }
  } catch {
    out = null;
  }
  cache.set(preset, out);
  return out;
}

export function CameraThumb({ preset, className }: { preset: string; className?: string }) {
  const tr = useMemo(() => compute(preset), [preset]);
  const [i, setI] = useState(0);
  const [hover, setHover] = useState(false);
  const raf = useRef(0);
  useEffect(() => {
    if (!hover || !tr) { setI(0); return; }
    const t0 = performance.now();
    const loop = (now: number) => {
      const u = (((now - t0) / 1000) % (DUR + 0.6)) / DUR;
      setI(Math.min(N, Math.round(Math.min(1, u) * N)));
      raf.current = requestAnimationFrame(loop);
    };
    raf.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf.current);
  }, [hover, tr]);

  if (!tr) return <div className={`cam-thumb empty ${className ?? ""}`}>—</div>;
  // 俯视：x 右，z 前（向上）
  const pts = [...tr.cam, ...tr.who];
  const xs = pts.map(p => p[0]), zs = pts.map(p => p[2]);
  let x0 = Math.min(...xs), x1 = Math.max(...xs), z0 = Math.min(...zs), z1 = Math.max(...zs);
  const span = Math.max(4, x1 - x0, z1 - z0) * 1.25;
  const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
  x0 = cx - span / 2; x1 = cx + span / 2; z0 = cz - span / 2; z1 = cz + span / 2;
  const W = 160, H = 110;
  const sx = (x: number) => ((x - x0) / (x1 - x0)) * (W - 20) + 10;
  const sy = (z: number) => H - (((z - z0) / (z1 - z0)) * (H - 16) + 8);
  const path = tr.cam.map((p, k) => `${k ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[2]).toFixed(1)}`).join("");
  const walk = tr.who.map((p, k) => `${k ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[2]).toFixed(1)}`).join("");
  const c = tr.cam[i], l = tr.look[i], w = tr.who[i];
  const dx = l[0] - c[0], dz = l[2] - c[2];
  const len = Math.hypot(dx, dz) || 1;
  const ux = dx / len, uz = dz / len;
  // 机位视锥：朝看向点张开 ±(半水平视场)
  const half = Math.atan(18 / tr.lens[i]);
  const ray = (a: number) => {
    const rx = ux * Math.cos(a) - uz * Math.sin(a), rz = ux * Math.sin(a) + uz * Math.cos(a);
    return `${sx(c[0] + rx * span * 0.22).toFixed(1)},${sy(c[2] + rz * span * 0.22).toFixed(1)}`;
  };
  const ys = tr.cam.map(p => p[1]);
  const ymax = Math.max(3, ...ys);
  const hgt = (c[1] / ymax) * (H - 20);
  const lens0 = Math.round(tr.lens[0]), lens1 = Math.round(tr.lens[N]);
  return (
    <div className={`cam-thumb ${className ?? ""}`} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
        <defs>
          <pattern id="ct-grid" width="16" height="16" patternUnits="userSpaceOnUse">
            <path d="M16 0H0V16" fill="none" stroke="rgba(255,255,255,.05)" />
          </pattern>
        </defs>
        <rect width={W} height={H} fill="url(#ct-grid)" />
        {walk && tr.who[0] !== tr.who[N] && <path d={walk} className="ct-walk" />}
        <path d={path} className="ct-path" />
        <polygon points={`${sx(c[0]).toFixed(1)},${sy(c[2]).toFixed(1)} ${ray(-half)} ${ray(half)}`} className="ct-fov" />
        <circle cx={sx(w[0])} cy={sy(w[2])} r={4.5} className="ct-who" />
        <line x1={sx(w[0])} y1={sy(w[2])} x2={sx(w[0])} y2={sy(w[2]) - 7} className="ct-who-dir" />
        <circle cx={sx(c[0])} cy={sy(c[2])} r={3.5} className="ct-cam" />
        <rect x={W - 6} y={H - 10 - hgt} width={3} height={Math.max(1, hgt)} className="ct-height" />
      </svg>
      {lens0 !== lens1 && <span className="ct-lens">{lens0}→{lens1}mm</span>}
    </div>
  );
}
