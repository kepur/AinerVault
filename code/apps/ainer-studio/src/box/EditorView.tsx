/**
 * 场景调度视图：自由视角看整个场景，点选物体、拖变换手柄、拖机位关键帧。
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Line, OrbitControls, PerspectiveCamera, TransformControls } from "@react-three/drei";
import * as THREE from "three";
import type { CameraDef, SceneDoc, Vec3 } from "../scene/types";
import type { SceneEval } from "../scene/evaluate";
import type { Clock } from "./clock";
import { DRAGGING, SceneRender } from "./SceneRender";
import type { Sketch } from "./api";

export const CAM_COLORS = ["#3ecf8e", "#ff9f43", "#4aa3ff", "#ff6bcb", "#ffd166", "#9b8cff", "#5ce1e6", "#f2685c"];
export const camColor = (doc: SceneDoc, id: string) => CAM_COLORS[Math.max(0, doc.cameras.findIndex(c => c.id === id)) % CAM_COLORS.length];

export type Sel =
  | { kind: "object"; id: string }
  | { kind: "camera"; id: string }
  | { kind: "key"; id: string; index: number };

export interface EditorApi {
  /** 编辑器相机此刻的位置与注视点（「应用当前视角到此机位」） */
  view(): { pos: Vec3; look: Vec3; fov: number };
  /** 屏幕坐标（0–1）→ 地面点（手绘标注投到地上） */
  ground(u: number, v: number): [number, number] | null;
  canvas(): HTMLCanvasElement | null;
}

interface Props {
  doc: SceneDoc;
  ev: SceneEval;
  clock: Clock;
  sel: Sel | null;
  onSelect: (s: Sel | null) => void;
  gizmo: "translate" | "rotate" | "scale";
  onObjectEdit: (id: string, t: { pos: Vec3; rot: Vec3; scale: Vec3 }) => void;
  onKeyEdit: (camId: string, index: number, pos: Vec3) => void;
  fitKey: number;
  sketches: Sketch[];
  apiRef: React.MutableRefObject<EditorApi | null>;
}

function sceneBounds(doc: SceneDoc, ev: SceneEval) {
  const xs: number[] = [], zs: number[] = [];
  for (const o of doc.objects) {
    if (o.prefab === "mountain") continue;
    if (o.strip) for (const p of o.strip.points) { xs.push(p[0]); zs.push(p[1]); }
    else { const w = ev.world(o.id, 0).pos; xs.push(w[0]); zs.push(w[2]); }
  }
  if (!xs.length) return { c: [0, 0, 0] as Vec3, span: 12 };
  const x0 = Math.min(...xs), x1 = Math.max(...xs), z0 = Math.min(...zs), z1 = Math.max(...zs);
  return { c: [(x0 + x1) / 2, 0, (z0 + z1) / 2] as Vec3, span: Math.max(10, x1 - x0, z1 - z0) };
}

function Rig({ doc, ev, fitKey, apiRef }: { doc: SceneDoc; ev: SceneEval; fitKey: number; apiRef: Props["apiRef"] }) {
  const cam = useRef<THREE.PerspectiveCamera>(null!);
  const { controls, gl, invalidate } = useThree();
  const ctl = controls as unknown as { target: THREE.Vector3; update(): void } | null;
  useLayoutEffect(() => {
    const { c, span } = sceneBounds(doc, ev);
    const d = span * 0.95 + 8;
    cam.current.position.set(c[0] + d * 0.55, d * 0.55, c[2] + d * 0.75);
    cam.current.lookAt(c[0], 0, c[2]);
    if (ctl?.target) { ctl.target.set(c[0], 0, c[2]); ctl.update(); }
    invalidate();
  }, [fitKey, ctl]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    apiRef.current = {
      view: () => {
        const t = ctl?.target ?? new THREE.Vector3();
        return { pos: cam.current.position.toArray() as Vec3, look: t.toArray() as Vec3, fov: cam.current.fov };
      },
      ground: (u, v) => {
        const ray = new THREE.Raycaster();
        ray.setFromCamera(new THREE.Vector2(u * 2 - 1, 1 - v * 2), cam.current);
        const hit = new THREE.Vector3();
        return ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hit) ? [hit.x, hit.z] : null;
      },
      canvas: () => gl.domElement,
    };
  });
  return <PerspectiveCamera ref={cam} makeDefault fov={50} near={0.1} far={3000} />;
}

/** 机位图示：机身＋视锥，跟着时间走；主机位此刻用的那台加粗。 */
function CamGlyph({ cam, ev, clock, color, selected, onSelect, k }: {
  cam: CameraDef; ev: SceneEval; clock: Clock; color: string; selected: boolean; onSelect: (e: ThreeEvent<MouseEvent>) => void; k: number;
}) {
  const g = useRef<THREE.Group>(null);
  const reach = 1.6;
  const frame = useMemo(() => {
    const aspect = ev.doc.aspect;
    // 全画幅 36mm 宽：水平半视场的正切 = 18/焦段，垂直的再除以画幅比
    const w = (18 / cam.lens) * reach;
    const h = w / aspect;
    const c: Vec3[] = [[-w, h, reach], [w, h, reach], [w, -h, reach], [-w, -h, reach]];
    return c;
  }, [cam.lens, ev.doc.aspect]);
  useFrame(() => {
    if (!g.current) return;
    const p = ev.camera(cam, clock.t);
    g.current.position.set(...p.pos);
    g.current.lookAt(new THREE.Vector3(...p.look));
    g.current.rotateZ(THREE.MathUtils.degToRad(-(p.roll ?? 0)));
    const active = ev.activeCamera(clock.t)?.id === cam.id;
    g.current.scale.setScalar((active ? 1.35 : 1) * k);
  });
  return (
    <group ref={g} onClick={onSelect}>
      <mesh>
        <boxGeometry args={[0.45, 0.32, 0.55]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={selected ? 0.6 : 0.2} />
      </mesh>
      <mesh position={[0, 0, 0.36]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.12, 0.16, 0.2, 12]} />
        <meshStandardMaterial color={color} />
      </mesh>
      {frame.map((p, i) => <Line key={i} points={[[0, 0, 0], p]} color={color} lineWidth={selected ? 2 : 1} />)}
      <Line points={[...frame, frame[0]]} color={color} lineWidth={selected ? 2.4 : 1.4} />
    </group>
  );
}

function CamPath({ cam, ev, color, sel, onSelect, keyRefs, k }: {
  cam: CameraDef; ev: SceneEval; color: string; sel: Sel | null; onSelect: (s: Sel) => void;
  keyRefs: Map<string, THREE.Object3D>; k: number;
}) {
  const trail = useMemo(() => ev.cameraTrail(cam, 120), [cam, ev]);
  const selected = sel && sel.id === cam.id;
  return (
    <group>
      {trail.length > 1 && <Line points={trail} color={color} lineWidth={selected ? 2.5 : 1.3} dashed={!selected} dashSize={0.5 * k} gapSize={0.3 * k} />}
      {cam.keys.map((key, i) => {
        const p = ev.keyWorld(key);
        const on = sel?.kind === "key" && sel.id === cam.id && sel.index === i;
        return (
          <mesh key={i} position={p} ref={m => { if (m) keyRefs.set(`${cam.id}#${i}`, m); }}
            onClick={e => { e.stopPropagation(); if (e.delta > 4) return; onSelect({ kind: "key", id: cam.id, index: i }); }}>
            <octahedronGeometry args={[(on ? 0.42 : 0.3) * k]} />
            <meshStandardMaterial color={on ? "#ffffff" : color} emissive={color} emissiveIntensity={0.5} />
          </mesh>
        );
      })}
    </group>
  );
}

export function EditorView(p: Props) {
  // 机位图示、关键帧菱形随场地放大：30m 的场地原大，150m 的放大 5 倍
  const k = useMemo(() => Math.min(6, Math.max(1, sceneBounds(p.doc, p.ev).span / 30)), [p.doc, p.ev]);
  const objects = useRef(new Map<string, THREE.Object3D>());
  const keyRefs = useRef(new Map<string, THREE.Object3D>());
  const [, force] = useState(0);
  const lastDrag = useRef(0);
  const selectObj = (id: string | null, e: ThreeEvent<MouseEvent>) => {
    if (e.delta > 4 || performance.now() - lastDrag.current < 300) return;   // 拖视角、拖手柄都不算点选
    p.onSelect(id ? { kind: "object", id } : null);
  };
  // 选中后下一帧才有物体引用：挂手柄前刷一次
  useEffect(() => { const id = requestAnimationFrame(() => force(n => n + 1)); return () => cancelAnimationFrame(id); }, [p.sel]);

  const target = p.sel?.kind === "object" ? objects.current.get(p.sel.id)
    : p.sel?.kind === "key" ? keyRefs.current.get(`${p.sel.id}#${p.sel.index}`) : undefined;

  const endDrag = () => {
    lastDrag.current = performance.now();
    const s = p.sel;
    if (!s || !target) return;
    if (s.kind === "object") {
      DRAGGING.delete(s.id);
      const o = target;
      p.onObjectEdit(s.id, {
        pos: o.position.toArray().map(v => +v.toFixed(3)) as Vec3,
        rot: [o.rotation.x, o.rotation.y, o.rotation.z].map(v => +THREE.MathUtils.radToDeg(v).toFixed(1)) as Vec3,
        scale: o.scale.toArray().map(v => +v.toFixed(3)) as Vec3,
      });
    } else if (s.kind === "key") {
      p.onKeyEdit(s.id, s.index, target.position.toArray().map(v => +v.toFixed(3)) as Vec3);
    }
  };

  return (
    <Canvas shadows frameloop="demand" dpr={[1, 2]} onPointerMissed={e => {
      if (performance.now() - lastDrag.current < 300 || (e as MouseEvent).button !== 0) return;
      p.onSelect(null);
    }}>
      <Rig doc={p.doc} ev={p.ev} fitKey={p.fitKey} apiRef={p.apiRef} />
      <OrbitControls makeDefault maxPolarAngle={Math.PI / 2 - 0.01} />
      <SceneRender doc={p.doc} ev={p.ev} clock={p.clock} opts={{
        editor: true, selected: p.sel?.kind === "object" ? p.sel.id : null,
        onSelect: selectObj, register: (id, o) => { if (o) objects.current.set(id, o); else objects.current.delete(id); },
      }} />
      {p.doc.cameras.map((c, i) => {
        const color = CAM_COLORS[i % CAM_COLORS.length];
        return (
          <group key={c.id}>
            <CamGlyph cam={c} ev={p.ev} clock={p.clock} color={color} k={k}
              selected={!!p.sel && p.sel.kind !== "object" && p.sel.id === c.id}
              onSelect={e => { e.stopPropagation(); if (e.delta > 4) return; p.onSelect({ kind: "camera", id: c.id }); }} />
            <CamPath cam={c} ev={p.ev} color={color} sel={p.sel} onSelect={p.onSelect} keyRefs={keyRefs.current} k={k} />
          </group>
        );
      })}
      {p.sketches.map((s, i) => s.points.length > 1 && (
        <Line key={i} points={s.points.map(([x, z]) => [x, 0.08, z] as Vec3)} color={s.color} lineWidth={3} />
      ))}
      {target && (
        <TransformControls object={target} mode={p.sel?.kind === "key" ? "translate" : p.gizmo}
          size={0.8}
          onMouseDown={() => { if (p.sel?.kind === "object") DRAGGING.add(p.sel.id); }}
          onMouseUp={endDrag} />
      )}
    </Canvas>
  );
}
