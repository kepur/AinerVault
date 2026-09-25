/**
 * 时间轴：刻度、主机位剪辑块（按机位着色，点一下选中那台机位）、选中机位的关键帧、播放头。
 */
import { useRef } from "react";
import type { SceneDoc } from "../scene/types";
import type { Clock } from "./clock";
import { useClock } from "./clock";
import { camColor, type Sel } from "./EditorView";

const fmt = (t: number) => `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

export function Timeline({ doc, clock, sel, onSelect }: {
  doc: SceneDoc; clock: Clock; sel: Sel | null; onSelect: (s: Sel) => void;
}) {
  useClock(clock, 50);
  const bar = useRef<HTMLDivElement>(null);
  const D = Math.max(0.5, doc.duration);
  const pct = (t: number) => `${(Math.min(D, Math.max(0, t)) / D) * 100}%`;
  const seekAt = (clientX: number) => {
    const r = bar.current!.getBoundingClientRect();
    clock.pause();
    clock.seek(((clientX - r.left) / r.width) * D);
  };
  const cuts = doc.cuts.length ? doc.cuts : doc.cameras[0] ? [{ t: 0, camera: doc.cameras[0].id }] : [];
  const selCam = sel && sel.kind !== "object" ? doc.cameras.find(c => c.id === sel.id) : null;
  const step = D > 40 ? 5 : D > 16 ? 2 : 1;
  const ticks = Array.from({ length: Math.floor(D / step) + 1 }, (_, i) => i * step);
  return (
    <div className="box-timeline">
      <button className="play" onClick={() => clock.toggle()} title="空格">{clock.playing ? "❚❚" : "▶"}</button>
      <div className="tc">{fmt(clock.t)} / {fmt(D)}</div>
      <div className="tl-body" ref={bar}
        onPointerDown={e => { (e.target as HTMLElement).setPointerCapture(e.pointerId); seekAt(e.clientX); }}
        onPointerMove={e => { if (e.buttons === 1) seekAt(e.clientX); }}>
        <div className="ruler">
          {ticks.map(t => <span key={t} style={{ left: pct(t) }}>{t}s</span>)}
        </div>
        <div className="cuts">
          {cuts.map((c, i) => {
            const end = cuts[i + 1]?.t ?? D;
            const cam = doc.cameras.find(x => x.id === c.camera);
            return (
              <div key={i} className={`cut${sel && sel.kind !== "object" && sel.id === c.camera ? " on" : ""}`}
                style={{ left: pct(c.t), width: `calc(${pct(end)} - ${pct(c.t)})`, background: camColor(doc, c.camera) }}
                title={`${cam?.name ?? c.camera} · ${c.t}s–${end}s`}
                onPointerDown={e => { e.stopPropagation(); onSelect({ kind: "camera", id: c.camera }); clock.pause(); clock.seek(c.t); }}>
                {cam?.name ?? c.camera}
              </div>
            );
          })}
        </div>
        {selCam && (
          <div className="keys">
            {selCam.keys.map((k, i) => (
              <span key={i} className={`key${sel?.kind === "key" && sel.index === i ? " on" : ""}`} style={{ left: pct(k.t) }}
                title={`${k.t.toFixed(2)}s（${k.follow ? "跟随" : k.orbit ? "环绕" : "世界坐标"}）`}
                onPointerDown={e => { e.stopPropagation(); onSelect({ kind: "key", id: selCam.id, index: i }); clock.pause(); clock.seek(k.t); }} />
            ))}
          </div>
        )}
        <div className="playhead" style={{ left: pct(clock.t) }} />
      </div>
    </div>
  );
}
