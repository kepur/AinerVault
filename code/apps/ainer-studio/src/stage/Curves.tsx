import { useMemo, type MouseEvent } from "react";
import type { CamPose, Rig } from "./model";
import { deg, len, sample, sub } from "./model";

/**
 * 运镜曲线：机位的几个量随时间怎么变 —— 预演软件曲线编辑器的只读版。
 * 抛物线摇臂在「高度」里是一道拱，推拉在「距离」里是一条斜线，缓动在
 * 斜线两头的弯里，变焦在「焦段」里；点曲线跳到那一刻。
 */
const TRACKS: { label: string; unit: string; digits: number; get: (p: CamPose) => number }[] = [
  { label: "机位高度", unit: "m", digits: 2, get: p => p.pos[1] },
  { label: "距离", unit: "m", digits: 2, get: p => len(sub(p.target, p.pos)) },
  { label: "焦段", unit: "mm", digits: 0, get: p => p.lens },
  { label: "方位", unit: "°", digits: 0, get: p => deg(Math.atan2(p.pos[2] - p.target[2], p.pos[0] - p.target[0])) },
  { label: "滚转", unit: "°", digits: 0, get: p => p.roll ?? 0 },
];

const N = 60;

export function Curves({ rig, t, onSeek }: { rig: Rig; t: number; onSeek: (t: number) => void }) {
  const rows = useMemo(() => {
    const poses = Array.from({ length: N + 1 }, (_, i) => sample({ ...rig, shake: 0 }, i / N));
    return TRACKS.map(tr => {
      let vals = poses.map(tr.get);
      if (tr.label === "方位") {
        // 角度解卷：跨过 ±180° 时不要画成一道竖线
        vals = vals.reduce<number[]>((out, v, i) => {
          if (!i) return [v];
          let x = v;
          while (x - out[i - 1] > 180) x -= 360;
          while (x - out[i - 1] < -180) x += 360;
          return [...out, x];
        }, []);
      }
      const lo = Math.min(...vals);
      const hi = Math.max(...vals);
      const flat = hi - lo < 1e-3;
      const pad = flat ? 1 : (hi - lo) * 0.12;
      const y = (v: number) => 22 - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * 20;
      const pts = vals.map((v, i) => `${((i / N) * 100).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
      return { ...tr, pts, lo, hi, flat, y, vals };
    });
  }, [rig]);
  const now = sample({ ...rig, shake: 0 }, t);
  const pick = (e: MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    onSeek(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)));
  };
  return (
    <div className="curves">
      {rows.map(r => {
        const v = r.get(now);
        return (
          <div key={r.label} className={`curve-row${r.flat ? " flat" : ""}`}>
            <span className="k">{r.label}</span>
            <svg viewBox="0 0 100 24" preserveAspectRatio="none" onMouseDown={pick}>
              <line x1="0" x2="100" y1="23.5" y2="23.5" className="base" />
              <polyline points={r.pts} />
              <line x1={t * 100} x2={t * 100} y1="0" y2="24" className="now" />
            </svg>
            <b>{r.flat ? `${r.lo.toFixed(r.digits)}` : `${v.toFixed(r.digits)}`}<small>{r.unit}</small></b>
            <span className="range">{r.flat ? "不变" : `${r.lo.toFixed(r.digits)}–${r.hi.toFixed(r.digits)}`}</span>
          </div>
        );
      })}
    </div>
  );
}
