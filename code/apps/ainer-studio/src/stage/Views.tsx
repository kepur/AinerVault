import { Suspense, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { Html, Line, MapControls, OrbitControls, OrthographicCamera, PerspectiveCamera } from "@react-three/drei";
import * as THREE from "three";
import type { Actor, Stage3D, Vec3 } from "./model";
import {
  add, basis, crossesAxis, dot, extent, framingOf, moveLabel, pathPoint, pitchOf, projectActors, rad, sample,
  scale, sizeLabel, sub, trail, vfov,
} from "./model";
import { AxisLine, BackdropCard, CameraGlyph, Floor, FovWedge, GhostCameras, LiveCamera, Mannequin, TrailLine } from "./Scene3D";

export type Handle =
  | { kind: "actor"; id: string } | { kind: "actorYaw"; id: string }
  | { kind: "camStart" } | { kind: "camEnd" } | { kind: "target" } | { kind: "control" }
  | { kind: "center" } | { kind: "apex" };

/** 手柄当前的世界坐标。 */
export function handleAt(stage: Stage3D, h: Handle): Vec3 {
  const r = stage.rig;
  switch (h.kind) {
    case "actor":
    case "actorYaw": {
      const a = stage.actors.find(x => x.entity_id === h.id);
      return a ? [a.pos[0], 0, a.pos[1]] : [0, 0, 0];
    }
    case "camStart": return r.start.pos;
    case "camEnd": return r.end.pos;
    case "target": return r.start.target;
    case "control": return r.control;
    case "center": return r.center;
    case "apex": return pathPoint(r, 0.5);
  }
}

const same = (a: Handle | null, b: Handle) => !!a && a.kind === b.kind &&
  (!("id" in b) || ("id" in a && a.id === b.id));

/** 两位主角（前两个演员）——轴线就画在他们之间。 */
export const leads = (s: Stage3D): [Actor, Actor] | null =>
  s.actors.length >= 2 ? [s.actors[0], s.actors[1]] : null;

function Lights() {
  return (
    <>
      <ambientLight intensity={0.6} />
      <directionalLight position={[6, 10, 8]} intensity={1.2} />
      <directionalLight position={[-8, 5, -4]} intensity={0.35} />
    </>
  );
}

/**
 * 拖动：按下手柄时关掉视图的平移缩放，移动时把指针落点换算成手柄的新世界坐标。
 * project 决定哪几个分量跟指针走（俯视图改 x/z，侧视图改纵深与高度）。
 */
function useDrag(stage: Stage3D, onGrab: (h: Handle) => void, onDrag: (h: Handle, p: Vec3) => void,
                 project: (h: Handle, hit: THREE.Vector3, at: Vec3) => Vec3) {
  const dragging = useRef<Handle | null>(null);
  const controls = useRef<{ enabled: boolean } | null>(null);
  const live = useRef(stage);
  live.current = stage;
  useEffect(() => {
    const up = () => {
      dragging.current = null;
      if (controls.current) controls.current.enabled = true;
    };
    window.addEventListener("pointerup", up);
    return () => window.removeEventListener("pointerup", up);
  }, []);
  const grab = (h: Handle) => (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    dragging.current = h;
    if (controls.current) controls.current.enabled = false;
    onGrab(h);
  };
  const move = (e: ThreeEvent<PointerEvent>) => {
    const h = dragging.current;
    if (h) onDrag(h, project(h, e.point, handleAt(live.current, h)));
  };
  return { grab, move, controls };
}

// ── 机位视角 ──────────────────────────────────────────────

function CamDriver({ stage, t }: { stage: Stage3D; t: number }) {
  const { camera, invalidate } = useThree();
  const pose = useMemo(() => sample(stage.rig, t), [stage.rig, t]);
  useLayoutEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    cam.position.set(...pose.pos);
    cam.fov = vfov(pose.lens, stage.aspect);
    cam.aspect = stage.aspect;
    cam.near = 0.05;
    cam.far = 500;
    cam.up.set(0, 1, 0);
    cam.lookAt(new THREE.Vector3(...pose.target));
    if (pose.roll) cam.rotateZ(rad(pose.roll));
    cam.updateProjectionMatrix();
    invalidate();
  }, [pose, stage.aspect, camera, invalidate]);
  return null;
}

/**
 * 透过这一镜的相机看：t=0 就是首帧的构图，拖时间轴看运镜途中任意时刻。
 * 叠在上面的是监视器那一套：三分线、安全框、中心十字、焦点框和机位读数。
 */
export function CameraView({ stage, t, plate, selected, label }: {
  stage: Stage3D; t: number; plate?: string; selected?: string | null; label: string;
}) {
  const pose = sample(stage.rig, t);
  const figs = projectActors(stage.actors, pose, stage.aspect);
  const focus = figs.find(f => f.entity_id === pose.focus);
  const pitch = pitchOf(pose);
  const roll = Math.round(pose.roll ?? 0);
  return (
    <div className="cam-frame" style={{ aspectRatio: String(stage.aspect) }}>
      <Canvas frameloop="demand" dpr={[1, 2]} camera={{ fov: 40, position: [0, 1.5, 6] }}>
        <color attach="background" args={["#0e0e12"]} />
        <Lights />
        <CamDriver stage={stage} t={t} />
        <Floor />
        <Suspense fallback={null}>
          {plate && <BackdropCard plate={plate} pose={stage.rig.start} aspect={stage.aspect} actors={stage.actors} />}
        </Suspense>
        {stage.actors.map(a => <Mannequin key={a.entity_id} a={a} selected={selected === a.entity_id} />)}
      </Canvas>
      <div className="thirds" />
      <div className="safe" />
      <div className="cross" />
      {focus && (
        <div className="af" style={{
          left: `${(focus.x - focus.width * 0.45) * 100}%`, width: `${focus.width * 90}%`,
          top: `${focus.top * 100}%`, height: `${(focus.bottom - focus.top) * 17}%`,
        }} />
      )}
      <div className="hud tl">{Math.round(pose.lens)}mm · f/{stage.rig.aperture ?? 4}</div>
      <div className="hud tr">{sizeLabel(framingOf(figs))} · {label}</div>
      <div className="hud bl">
        机位高 {pose.pos[1].toFixed(2)}m · {pitch > 1 ? `俯 ${pitch.toFixed(0)}°` : pitch < -1 ? `仰 ${(-pitch).toFixed(0)}°` : "平视"}
        {roll ? ` · 滚转 ${roll}°` : ""}
      </div>
      <div className="hud br">{moveLabel(stage.rig.move)}</div>
    </div>
  );
}

// ── 俯视图 ────────────────────────────────────────────────

/**
 * 俯视图的手柄。看得见的是圆点或圆环；接指针的是一块更大的透明实心圆 ——
 * 圆环中间是空的，点在环心正好落进洞里，拖动就变成了平移视图。
 */
function Dot({ at, color, r = 0.16, onDown, ring }: {
  at: Vec3; color: string; r?: number; ring?: boolean;
  onDown?: (e: ThreeEvent<PointerEvent>) => void;
}) {
  return (
    <group position={[at[0], 0.05, at[2]]} rotation={[-Math.PI / 2, 0, 0]}>
      <mesh>
        {ring ? <ringGeometry args={[r * 0.6, r, 32]} /> : <circleGeometry args={[r, 32]} />}
        <meshBasicMaterial color={color} transparent opacity={0.95} />
      </mesh>
      {onDown && (
        <mesh position={[0, 0, 0.01]} onPointerDown={onDown}>
          <circleGeometry args={[r * 1.4, 24]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      )}
    </group>
  );
}

function TopActor({ a, selected, onDown, onYaw }: {
  a: Actor; selected: boolean;
  onDown: (e: ThreeEvent<PointerEvent>) => void; onYaw: (e: ThreeEvent<PointerEvent>) => void;
}) {
  const r = 0.28 * a.girth;
  // 朝向向量 = (sin yaw, cos yaw)，与人偶绕 Y 轴旋转的约定一致：yaw 0 面向 +Z
  const yaw = THREE.MathUtils.degToRad(a.yaw);
  const c: Vec3 = [a.pos[0], 0.06, a.pos[1]];
  const tip: Vec3 = [a.pos[0] + Math.sin(yaw) * r * 2.4, 0.06, a.pos[1] + Math.cos(yaw) * r * 2.4];
  return (
    <group>
      <mesh position={[a.pos[0], 0.04, a.pos[1]]} rotation={[-Math.PI / 2, 0, 0]} onPointerDown={onDown}>
        <circleGeometry args={[r, 32]} />
        <meshBasicMaterial color={selected ? "#8f82ff" : "#8a8a96"} />
      </mesh>
      <Line points={[c, tip]} color="#ffb86b" lineWidth={3} />
      {/* 拖这个橙点转身 */}
      <mesh position={tip} rotation={[-Math.PI / 2, 0, 0]} onPointerDown={onYaw}>
        <circleGeometry args={[r * 0.34, 16]} />
        <meshBasicMaterial color="#ffb86b" />
      </mesh>
      <Html position={[a.pos[0], 0, a.pos[1] + r + 0.45]} center zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
        <div className="stage-label">{a.name}</div>
      </Html>
    </group>
  );
}

/** 正上方的正交相机；fitKey 变了就重新框住全部演员与机位。 */
function TopCam({ stage, fitKey }: { stage: Stage3D; fitKey: number }) {
  const cam = useRef<THREE.OrthographicCamera>(null!);
  const { size, controls, invalidate } = useThree();
  useLayoutEffect(() => {
    const { center, size: ext } = extent(stage);
    const c = cam.current;
    // up = -Z：画面上方是舞台深处，机位在下方 —— 平面图的惯例
    c.up.set(0, 0, -1);
    c.position.set(center[0], 60, center[2]);
    c.zoom = Math.max(4, Math.min(size.width / (ext[0] * 1.2 + 1.6), size.height / (ext[2] * 1.2 + 1.6)));
    c.lookAt(center[0], 0, center[2]);
    c.updateProjectionMatrix();
    const ctl = controls as unknown as { target?: THREE.Vector3; update?: () => void } | null;
    if (ctl?.target) { ctl.target.set(center[0], 0, center[2]); ctl.update?.(); }
    invalidate();
  }, [fitKey, size.width, size.height, controls]); // eslint-disable-line react-hooks/exhaustive-deps
  return <OrthographicCamera ref={cam} makeDefault near={0.1} far={200} />;
}

/** 平面图：演员（带朝向）、起幅/落幅机位与视场、轨迹、注视点、180° 轴线。全部可拖。 */
export function TopView({ stage, t, selected, fitKey, onGrab, onDrag }: {
  stage: Stage3D; t: number; selected: Handle | null; fitKey: number;
  onGrab: (h: Handle) => void; onDrag: (h: Handle, p: Vec3) => void;
}) {
  // 俯视只改地面坐标，手柄的高度不变
  const { grab, move, controls } = useDrag(stage, onGrab, onDrag, (_h, hit, at) => [hit.x, at[1], hit.z]);
  const r = stage.rig;
  const pair = leads(stage);
  const crossing = pair ? crossesAxis(r, pair[0], pair[1]) : false;
  return (
    <Canvas frameloop="demand" dpr={[1, 2]}>
      <color attach="background" args={["#121218"]} />
      <TopCam stage={stage} fitKey={fitKey} />
      <MapControls ref={controls as never} enableRotate={false} screenSpacePanning makeDefault />
      <ambientLight intensity={1} />
      <Floor size={80} />
      {/* 接指针的地面：拖动时在这里取落点 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.001, 0]} onPointerMove={move}>
        <planeGeometry args={[400, 400]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
      {pair && <AxisLine a={pair[0]} b={pair[1]} camAt={r.start.pos} warn={crossing} />}
      <TrailLine rig={r} ground={false} />
      <FovWedge pose={r.start} color="#3ecf8e" />
      {r.move !== "static" && <FovWedge pose={r.end} color="#ff9f43" />}
      <GhostCameras rig={r} aspect={stage.aspect} reach={0.7} />
      <CameraGlyph pose={r.start} aspect={stage.aspect} color="#3ecf8e" reach={0.9} />
      {r.move !== "static" && <CameraGlyph pose={r.end} aspect={stage.aspect} color="#ff9f43" reach={0.9} />}
      <LiveCamera rig={r} t={t} aspect={stage.aspect} />
      <Line points={[[r.start.pos[0], 0.03, r.start.pos[2]], [r.start.target[0], 0.03, r.start.target[2]]]}
        color="#ffd166" lineWidth={1} dashed dashSize={0.2} gapSize={0.15} transparent opacity={0.5} />
      <Dot at={r.start.pos} color="#3ecf8e" r={0.3} ring={!same(selected, { kind: "camStart" })} onDown={grab({ kind: "camStart" })} />
      {r.move !== "static" && (
        <Dot at={r.end.pos} color="#ff9f43" r={0.3} ring={!same(selected, { kind: "camEnd" })} onDown={grab({ kind: "camEnd" })} />
      )}
      <Dot at={r.start.target} color="#ffd166" r={0.18} onDown={grab({ kind: "target" })} />
      {r.path === "bezier" && <Dot at={r.control} color="#ff6bcb" r={0.22} onDown={grab({ kind: "control" })} />}
      {r.path === "arc" && <Dot at={r.center} color="#6bd5ff" r={0.16} ring onDown={grab({ kind: "center" })} />}
      {stage.actors.map(a => (
        <TopActor key={a.entity_id} a={a} selected={same(selected, { kind: "actor", id: a.entity_id })}
          onDown={grab({ kind: "actor", id: a.entity_id })} onYaw={grab({ kind: "actorYaw", id: a.entity_id })} />
      ))}
    </Canvas>
  );
}

// ── 侧视图 ────────────────────────────────────────────────

/**
 * 沿起幅机位的右手方向看过去的立面图：横轴是机位的水平视线方向（相机在左、
 * 被摄在右），竖轴是高度。机位高度、俯仰、摇臂抛物线的弧顶、升降的落差，
 * 只有这里看得准。轴向在「适配」时按当时的机位定下，拖动时不跟着转。
 */
function SideCam({ stage, fitKey, axis }: { stage: Stage3D; fitKey: number; axis: { right: Vec3; flat: Vec3 } }) {
  const cam = useRef<THREE.OrthographicCamera>(null!);
  const { size, controls, invalidate } = useThree();
  useLayoutEffect(() => {
    const pts: Vec3[] = [...stage.actors.map(a => [a.pos[0], a.height, a.pos[1]] as Vec3), [0, 0, 0] as Vec3,
      stage.rig.start.pos, stage.rig.end.pos, stage.rig.start.target, ...trail(stage.rig, 16)];
    const fs = pts.map(p => dot(p, axis.flat));
    const ys = pts.map(p => p[1]).concat([0]);
    const f0 = Math.min(...fs), f1 = Math.max(...fs);
    const y1 = Math.max(...ys, 2);
    const mid = pts.reduce((s, p) => add(s, p), [0, 0, 0] as Vec3);
    const c3 = scale(mid, 1 / pts.length);
    const along = (f0 + f1) / 2 - dot(c3, axis.flat);
    const look = add(add(c3, scale(axis.flat, along)), [0, y1 / 2 - c3[1], 0]);
    const c = cam.current;
    c.up.set(0, 1, 0);
    c.position.set(...add(look, scale(axis.right, 60)));
    c.zoom = Math.max(4, Math.min(size.width / ((f1 - f0) * 1.2 + 2.5), size.height / (y1 * 1.25 + 1.2)));
    c.lookAt(...look);
    c.updateProjectionMatrix();
    const ctl = controls as unknown as { target?: THREE.Vector3; update?: () => void } | null;
    if (ctl?.target) { ctl.target.set(...look); ctl.update?.(); }
    invalidate();
  }, [fitKey, size.width, size.height, controls, axis]); // eslint-disable-line react-hooks/exhaustive-deps
  return <OrthographicCamera ref={cam} makeDefault near={0.1} far={400} />;
}

function Knob({ at, color, r = 0.16, onDown, ring }: {
  at: Vec3; color: string; r?: number; ring?: boolean; onDown?: (e: ThreeEvent<PointerEvent>) => void;
}) {
  return (
    <mesh position={at} onPointerDown={onDown}>
      <sphereGeometry args={[r, 20, 14]} />
      <meshBasicMaterial color={color} transparent opacity={ring ? 0.55 : 0.95} />
    </mesh>
  );
}

export function SideView({ stage, t, selected, fitKey, onGrab, onDrag }: {
  stage: Stage3D; t: number; selected: Handle | null; fitKey: number;
  onGrab: (h: Handle) => void; onDrag: (h: Handle, p: Vec3) => void;
}) {
  // 轴向只在适配时取一次：拖着机位时视图不跟着转
  const axis = useMemo(() => { const b = basis(stage.rig.start); return { right: b.right, flat: b.flat }; },
    [fitKey]); // eslint-disable-line react-hooks/exhaustive-deps
  // 侧视只改纵深与高度，左右位置保持：新位置 = 落点 + 右向 ×（原位置 − 落点）·右向
  const { grab, move, controls } = useDrag(stage, onGrab, onDrag,
    (_h, hit, at) => { const p: Vec3 = [hit.x, hit.y, hit.z]; return add(p, scale(axis.right, dot(sub(at, p), axis.right))); });
  const r = stage.rig;
  const q = useMemo(() => new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1),
    new THREE.Vector3(...axis.right)), [axis]);
  const back = scale(axis.right, -30);   // 标尺放在所有东西后面
  const rulers = useMemo(() => Array.from({ length: 11 }, (_, y) => {
    const o = add(back, [0, y, 0]);
    return [add(o, scale(axis.flat, -80)), add(o, scale(axis.flat, 80))] as [Vec3, Vec3];
  }), [axis]); // eslint-disable-line react-hooks/exhaustive-deps
  const labelAt = (y: number): Vec3 => add(add(r.start.pos, scale(axis.flat, -1.4)), [0, y - r.start.pos[1], 0]);
  return (
    <Canvas frameloop="demand" dpr={[1, 2]}>
      <color attach="background" args={["#121218"]} />
      <SideCam stage={stage} fitKey={fitKey} axis={axis} />
      <MapControls ref={controls as never} enableRotate={false} screenSpacePanning makeDefault />
      <Lights />
      {rulers.map(([a, b], y) => (
        <Line key={y} points={[a, b]} color={y === 0 ? "#6a6a7a" : "#2c2c36"} lineWidth={y === 0 ? 2 : 1} />
      ))}
      {[1, 2, 3, 5].map(y => (
        <Html key={y} position={labelAt(y)} center zIndexRange={[5, 0]} style={{ pointerEvents: "none" }}>
          <div className="ruler-label">{y}m</div>
        </Html>
      ))}
      <mesh position={stage.actors.length ? [stage.actors[0].pos[0], 1, stage.actors[0].pos[1]] : [0, 1, 0]}
        quaternion={q} onPointerMove={move}>
        <planeGeometry args={[400, 400]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
      {stage.actors.map(a => <Mannequin key={a.entity_id} a={a} selected={same(selected, { kind: "actor", id: a.entity_id })} />)}
      <TrailLine rig={r} ground={false} />
      <GhostCameras rig={r} aspect={stage.aspect} reach={0.7} />
      <CameraGlyph pose={r.start} aspect={stage.aspect} color="#3ecf8e" reach={1.6} />
      {r.move !== "static" && <CameraGlyph pose={r.end} aspect={stage.aspect} color="#ff9f43" reach={1.6} />}
      <LiveCamera rig={r} t={t} aspect={stage.aspect} />
      <Line points={[r.start.pos, r.start.target]} color="#ffd166" lineWidth={1} dashed dashSize={0.2} gapSize={0.15} transparent opacity={0.6} />
      <Knob at={r.start.pos} color="#3ecf8e" r={0.2} ring={!same(selected, { kind: "camStart" })} onDown={grab({ kind: "camStart" })} />
      {r.move !== "static" && (
        <Knob at={r.end.pos} color="#ff9f43" r={0.2} ring={!same(selected, { kind: "camEnd" })} onDown={grab({ kind: "camEnd" })} />
      )}
      <Knob at={r.start.target} color="#ffd166" r={0.13} onDown={grab({ kind: "target" })} />
      {r.path === "parabola" && <Knob at={pathPoint(r, 0.5)} color="#ff6bcb" r={0.17} onDown={grab({ kind: "apex" })} />}
      {r.path === "bezier" && <Knob at={r.control} color="#ff6bcb" r={0.17} onDown={grab({ kind: "control" })} />}
    </Canvas>
  );
}

// ── 自由视角 ──────────────────────────────────────────────

function FreeCam({ stage, fitKey }: { stage: Stage3D; fitKey: number }) {
  const cam = useRef<THREE.PerspectiveCamera>(null!);
  const { controls, invalidate } = useThree();
  useLayoutEffect(() => {
    const { center, size: ext } = extent(stage);
    const R = Math.max(ext[0], ext[2], ext[1] * 1.5, 4);
    const dir = new THREE.Vector3(0.75, 0.62, 1).normalize();
    const look = new THREE.Vector3(center[0], Math.min(center[1], 1.4), center[2]);
    cam.current.position.copy(look.clone().addScaledVector(dir, R * 1.35 + 4));
    cam.current.lookAt(look);
    const ctl = controls as unknown as { target?: THREE.Vector3; update?: () => void } | null;
    if (ctl?.target) { ctl.target.copy(look); ctl.update?.(); }
    invalidate();
  }, [fitKey, controls]); // eslint-disable-line react-hooks/exhaustive-deps
  return <PerspectiveCamera ref={cam} makeDefault fov={40} near={0.1} far={500} />;
}

/** 可以绕着看的 3D：抛物线摇臂的高度、环绕的半径、运镜途中镜头的朝向，一眼全看到。 */
export function FreeView({ stage, t, plate, fitKey }: { stage: Stage3D; t: number; plate?: string; fitKey: number }) {
  const r = stage.rig;
  const pair = leads(stage);
  return (
    <Canvas frameloop="demand" dpr={[1, 2]}>
      <color attach="background" args={["#0e0e12"]} />
      <FreeCam stage={stage} fitKey={fitKey} />
      <OrbitControls makeDefault maxPolarAngle={Math.PI / 2 - 0.02} />
      <Lights />
      <Floor size={80} />
      <Suspense fallback={null}>
        {plate && <BackdropCard plate={plate} pose={r.start} aspect={stage.aspect} actors={stage.actors} />}
      </Suspense>
      {pair && <AxisLine a={pair[0]} b={pair[1]} camAt={r.start.pos} warn={crossesAxis(r, pair[0], pair[1])} />}
      {stage.actors.map(a => <Mannequin key={a.entity_id} a={a} label />)}
      <TrailLine rig={r} />
      <GhostCameras rig={r} aspect={stage.aspect} />
      <CameraGlyph pose={r.start} aspect={stage.aspect} color="#3ecf8e" />
      {r.move !== "static" && <CameraGlyph pose={r.end} aspect={stage.aspect} color="#ff9f43" />}
      <LiveCamera rig={r} t={t} aspect={stage.aspect} />
    </Canvas>
  );
}
