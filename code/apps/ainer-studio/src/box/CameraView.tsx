/**
 * 机位视角：按主机位时间表（或指定的一台机位）透过镜头看。
 * 画中画预览和「成片预演」都用它；成片预演还能把画布录成视频导出。
 */
import { useEffect, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import type { SceneDoc } from "../scene/types";
import type { SceneEval } from "../scene/evaluate";
import type { Clock } from "./clock";
import { useClock } from "./clock";
import { SceneRender } from "./SceneRender";

const vfov = (lens: number, aspect: number) => THREE.MathUtils.radToDeg(2 * Math.atan(18 / lens / aspect));

function Driver({ ev, clock, camId, aspect }: { ev: SceneEval; clock: Clock; camId?: string | null; aspect: number }) {
  const { camera, invalidate } = useThree();
  useEffect(() => clock.subscribe(() => invalidate()), [clock, invalidate]);
  useFrame(() => {
    const cam = camId ? ev.doc.cameras.find(c => c.id === camId) : ev.activeCamera(clock.t);
    const c = camera as THREE.PerspectiveCamera;
    if (!cam) { c.position.set(0, 12, 30); c.lookAt(0, 0, 0); return; }
    const p = ev.camera(cam, clock.t);
    c.position.set(...p.pos);
    c.up.set(0, 1, 0);
    c.lookAt(new THREE.Vector3(...p.look));
    if (p.roll) c.rotateZ(THREE.MathUtils.degToRad(p.roll));
    c.fov = vfov(p.lens, aspect);
    c.aspect = aspect;
    c.near = 0.08;
    c.far = 3000;
    c.updateProjectionMatrix();
  }, -1);
  return null;
}

export interface CameraViewHandle { canvas: HTMLCanvasElement | null }

export function CameraView({ doc, ev, clock, camId, hud = true, handle, className }: {
  doc: SceneDoc; ev: SceneEval; clock: Clock; camId?: string | null; hud?: boolean;
  handle?: React.MutableRefObject<CameraViewHandle | null>; className?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  return (
    <div className={`cam-view ${className ?? ""}`} ref={wrap} style={{ aspectRatio: String(doc.aspect) }}>
      <Canvas shadows frameloop="demand" dpr={[1, 2]} gl={{ preserveDrawingBuffer: true }}
        onCreated={s => { if (handle) handle.current = { canvas: s.gl.domElement }; }}>
        <Driver ev={ev} clock={clock} camId={camId} aspect={doc.aspect} />
        <SceneRender doc={doc} ev={ev} clock={clock} opts={{ editor: false }} />
      </Canvas>
      {hud && <Hud doc={doc} ev={ev} clock={clock} camId={camId} />}
    </div>
  );
}

function Hud({ doc, ev, clock, camId }: { doc: SceneDoc; ev: SceneEval; clock: Clock; camId?: string | null }) {
  useClock(clock, 100);
  const cam = camId ? doc.cameras.find(c => c.id === camId) : ev.activeCamera(clock.t);
  const p = cam ? ev.camera(cam, clock.t) : null;
  const t = clock.t;
  const tc = `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}:${String(Math.floor((t % 1) * doc.fps)).padStart(2, "0")}`;
  return (
    <>
      <div className="hud tl">{cam?.name ?? "无机位"}{p ? ` · ${Math.round(p.lens)}mm` : ""}</div>
      <div className="hud tr">{tc}</div>
    </>
  );
}

/** 从头播到尾，同时把画布录成 webm。onProgress 给 0–1。 */
export async function recordCanvas(canvas: HTMLCanvasElement, clock: Clock, fps: number,
                                   onProgress?: (u: number) => void): Promise<Blob> {
  const stream = canvas.captureStream(fps);
  const type = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find(t => MediaRecorder.isTypeSupported(t)) ?? "";
  const rec = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 8_000_000 });
  const chunks: Blob[] = [];
  rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  const done = new Promise<void>(res => { rec.onstop = () => res(); });
  clock.pause();
  clock.seek(0);
  await new Promise(r => setTimeout(r, 120));
  rec.start(200);
  clock.play();
  await new Promise<void>(res => {
    const off = clock.subscribe(() => {
      onProgress?.(clock.t / clock.duration);
      if (!clock.playing) { off(); res(); }
    });
  });
  await new Promise(r => setTimeout(r, 150));
  rec.stop();
  await done;
  stream.getTracks().forEach(t => t.stop());
  return new Blob(chunks, { type: type.split(";")[0] || "video/webm" });
}
