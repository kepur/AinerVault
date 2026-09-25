/**
 * 手绘标注：在视图上画笔、箭头、圈、框、文字。确认后每一笔投到地面上，
 * 变成世界坐标点列交给智能体（「沿这条线开」「在这里加一排树」「机位从这里绕过去」）。
 */
import { useEffect, useRef, useState } from "react";

export interface Stroke2D {
  tool: "pen" | "arrow" | "circle" | "rect" | "text";
  color: string;
  width: number;
  /** 画面比例坐标（0–1） */
  points: [number, number][];
  text?: string;
}

const COLORS = ["#ff3b30", "#ffcc00", "#34c759", "#0a84ff", "#ffffff", "#8e8e93", "#000000"];
const WIDTHS = [2, 4, 7];
const TOOLS: { id: Stroke2D["tool"] | "eraser"; label: string; title: string }[] = [
  { id: "pen", label: "✎", title: "画笔" }, { id: "arrow", label: "↗", title: "箭头" }, { id: "circle", label: "◯", title: "圈" },
  { id: "rect", label: "▢", title: "框" }, { id: "text", label: "T", title: "文字" }, { id: "eraser", label: "⌫", title: "橡皮（点一笔删掉）" },
];

function shapePoints(tool: Stroke2D["tool"], a: [number, number], b: [number, number], aspect: number): [number, number][] {
  if (tool === "rect") return [a, [b[0], a[1]], b, [a[0], b[1]], a];
  if (tool === "circle") {
    const rx = (b[0] - a[0]), ry = (b[1] - a[1]);
    const r = Math.hypot(rx * aspect, ry);
    return Array.from({ length: 33 }, (_, i) => {
      const t = (i / 32) * Math.PI * 2;
      return [a[0] + (Math.cos(t) * r) / aspect, a[1] + Math.sin(t) * r] as [number, number];
    });
  }
  return [a, b];
}

export function SketchLayer({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: (s: Stroke2D[]) => void }) {
  const cv = useRef<HTMLCanvasElement>(null);
  const [tool, setTool] = useState<Stroke2D["tool"] | "eraser">("pen");
  const [color, setColor] = useState(COLORS[0]);
  const [width, setWidth] = useState(WIDTHS[1]);
  const [strokes, setStrokes] = useState<Stroke2D[]>([]);
  const cur = useRef<Stroke2D | null>(null);
  const [, bump] = useState(0);

  useEffect(() => {
    const c = cv.current!;
    // 尺寸变了只重设画布像素，重画交给下一次渲染（draw 读的是最新的笔画）
    const ro = new ResizeObserver(() => { c.width = c.clientWidth * devicePixelRatio; c.height = c.clientHeight * devicePixelRatio; bump(n => n + 1); });
    ro.observe(c);
    return () => ro.disconnect();
  }, []);

  function draw() {
    const c = cv.current;
    if (!c) return;
    const g = c.getContext("2d")!;
    g.clearRect(0, 0, c.width, c.height);
    const all = cur.current ? [...strokes, cur.current] : strokes;
    for (const s of all) {
      g.strokeStyle = s.color;
      g.fillStyle = s.color;
      g.lineWidth = s.width * devicePixelRatio;
      g.lineCap = "round";
      g.lineJoin = "round";
      const px = s.points.map(([u, v]) => [u * c.width, v * c.height]);
      if (s.tool === "text") {
        g.font = `${14 * devicePixelRatio + s.width * 2}px sans-serif`;
        g.fillText(s.text ?? "", px[0][0], px[0][1]);
        continue;
      }
      g.beginPath();
      px.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
      g.stroke();
      if (s.tool === "arrow" && px.length > 1) {
        const [x0, y0] = px[px.length - 2], [x1, y1] = px[px.length - 1];
        const a = Math.atan2(y1 - y0, x1 - x0), L = 14 * devicePixelRatio + s.width * 2;
        g.beginPath();
        g.moveTo(x1, y1); g.lineTo(x1 - L * Math.cos(a - 0.4), y1 - L * Math.sin(a - 0.4));
        g.moveTo(x1, y1); g.lineTo(x1 - L * Math.cos(a + 0.4), y1 - L * Math.sin(a + 0.4));
        g.stroke();
      }
    }
  }
  useEffect(draw);

  const at = (e: React.PointerEvent): [number, number] => {
    const r = cv.current!.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
  };
  const aspect = () => { const r = cv.current!.getBoundingClientRect(); return r.width / r.height; };

  return (
    <div className="sketch-layer">
      <canvas ref={cv}
        onPointerDown={e => {
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          const p = at(e);
          if (tool === "eraser") {
            const hit = strokes.findIndex(s => s.points.some(q => Math.hypot((q[0] - p[0]) * aspect(), q[1] - p[1]) < 0.02));
            if (hit >= 0) setStrokes(x => x.filter((_, i) => i !== hit));
            return;
          }
          if (tool === "text") {
            const t = window.prompt("标注文字");
            if (t) setStrokes(x => [...x, { tool: "text", color, width, points: [p], text: t }]);
            return;
          }
          cur.current = { tool, color, width, points: [p] };
          bump(n => n + 1);
        }}
        onPointerMove={e => {
          const s = cur.current;
          if (!s || e.buttons !== 1) return;
          const p = at(e);
          if (s.tool === "pen") { const last = s.points[s.points.length - 1]; if (Math.hypot(p[0] - last[0], p[1] - last[1]) > 0.004) s.points.push(p); }
          else s.points = shapePoints(s.tool, s.points[0], p, aspect());
          draw();
        }}
        onPointerUp={() => {
          const s = cur.current;
          cur.current = null;
          if (s && s.points.length > 1) setStrokes(x => [...x, s]);
        }} />
      <div className="sketch-bar">
        <div className="group">
          {WIDTHS.map(w => <button key={w} className={`w${width === w ? " on" : ""}`} onClick={() => setWidth(w)}><i style={{ width: w + 2, height: w + 2 }} /></button>)}
          <span className="sep" />
          {COLORS.map(c => <button key={c} className={`c${color === c ? " on" : ""}`} onClick={() => setColor(c)}><i style={{ background: c }} /></button>)}
        </div>
        <div className="group">
          <button className="x" onClick={onCancel} title="取消">✕</button>
          {TOOLS.map(t => <button key={t.id} className={tool === t.id ? "on" : ""} title={t.title} onClick={() => setTool(t.id)}>{t.label}</button>)}
          <button className="ok" onClick={() => onConfirm(strokes)} title="确认，交给智能体">✓</button>
        </div>
      </div>
      <div className="sketch-tip">在画面上画出路线、区域或机位轨迹，确认后说一句「沿这条线…」</div>
    </div>
  );
}
