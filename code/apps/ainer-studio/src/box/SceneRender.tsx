/**
 * 场景文档 → three 场景：环境、灯光、物体（预制件部件、基本体、人偶、地面带）、动画。
 *
 * 动画不走 React：Animator 在 useFrame 里按 clock.t 直接改各物体组的位姿，
 * 60fps 回放不会让整棵组件树重渲染。编辑器和机位视角共用这一个组件。
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useTexture } from "@react-three/drei";
import * as THREE from "three";
import type { SceneDoc, SceneObject } from "../scene/types";
import { PREFABS } from "../scene/prefabs";
import { localPose, type SceneEval } from "../scene/evaluate";
import type { Clock } from "./clock";
import { dashGeometry, GROUND, material, partColor, partScale, SKY, STRIP_COLOR, stripGeometry, unitGeometry } from "./geom";
import { Mannequin, type MannequinHandle } from "./Mannequin";

const rad = THREE.MathUtils.degToRad;

export interface RenderOpts {
  /** 编辑器：隐藏的物体画成半透明、标记显示；成片：隐藏的和标记都不画 */
  editor: boolean;
  selected?: string | null;
  onSelect?: (id: string | null, e: ThreeEvent<MouseEvent>) => void;
  /** 编辑器要拿到物体组去挂变换手柄 */
  register?: (id: string, o: THREE.Object3D | null) => void;
  shadows?: boolean;
}

interface Anim { obj: SceneObject; group: THREE.Group | null; man: MannequinHandle | null }

/** 正在被变换手柄拖着的物体：动画别在拖的时候把它拽回轨道上 */
export const DRAGGING = new Set<string>();

export function SceneRender({ doc, ev, clock, opts }: { doc: SceneDoc; ev: SceneEval; clock: Clock; opts: RenderOpts }) {
  const kids = useMemo(() => {
    const m = new Map<string | undefined, SceneObject[]>();
    for (const o of doc.objects) {
      const k = o.parent && ev.byId.has(o.parent) ? o.parent : undefined;
      m.set(k, [...(m.get(k) ?? []), o]);
    }
    return m;
  }, [doc, ev]);
  const anims = useRef(new Map<string, Anim>());
  anims.current.clear();

  return (
    <>
      <EnvironmentView doc={doc} shadows={opts.shadows ?? true} editor={opts.editor} />
      {(kids.get(undefined) ?? []).map(o => <ObjectNode key={o.id} obj={o} kids={kids} opts={opts} anims={anims.current} />)}
      <Animator ev={ev} clock={clock} anims={anims.current} />
    </>
  );
}

function Animator({ ev, clock, anims }: { ev: SceneEval; clock: Clock; anims: Map<string, Anim> }) {
  const invalidate = useThree(s => s.invalidate);
  useEffect(() => clock.subscribe(() => invalidate()), [clock, invalidate]);
  useFrame(() => {
    const t = clock.t;
    for (const [id, a] of anims) {
      const o = a.obj;
      if (o.track && a.group && !DRAGGING.has(id)) {
        const lp = localPose(o, t);
        a.group.position.set(lp.pos[0], lp.pos[1], lp.pos[2]);
        a.group.rotation.set(rad(lp.rot[0]), rad(lp.rot[1]), rad(lp.rot[2]));
        a.group.scale.set(lp.scale[0], lp.scale[1], lp.scale[2]);
      }
      if (a.man) {
        let pose = o.poses?.[0]?.pose ?? "stand";
        for (const p of o.poses ?? []) if (p.t <= t + 1e-6) pose = p.pose;
        const g = o.track ? ev.gait(id, t) : { phase: 0, speed: 0 };
        a.man.animate(pose, g.phase, g.speed);
      }
    }
  });
  return null;
}

function ObjectNode({ obj, kids, opts, anims }: { obj: SceneObject; kids: Map<string | undefined, SceneObject[]>; opts: RenderOpts; anims: Map<string, Anim> }) {
  const hidden = obj.tags.includes("hidden");
  const marker = obj.prefab === "marker" || obj.prefab === "arrow";
  if ((hidden || marker) && !opts.editor) return null;
  const t = obj.transform;
  const entry: Anim = { obj, group: null, man: null };
  if (obj.track || obj.kind === "character") anims.set(obj.id, entry);
  const sel = opts.selected === obj.id;
  return (
    <group
      ref={g => { entry.group = g; opts.register?.(obj.id, g); }}
      position={t.pos} rotation={[rad(t.rot[0]), rad(t.rot[1]), rad(t.rot[2])]} scale={t.scale}
      userData={{ sceneId: obj.id }}
      onClick={opts.onSelect ? (e => { e.stopPropagation(); opts.onSelect!(obj.id, e); }) : undefined}
    >
      <ObjectBody obj={obj} selected={sel} ghost={hidden} shadows={opts.shadows ?? true}
        onMannequin={m => { entry.man = m; }} />
      {(kids.get(obj.id) ?? []).map(k => <ObjectNode key={k.id} obj={k} kids={kids} opts={opts} anims={anims} />)}
    </group>
  );
}

function ObjectBody({ obj, selected, ghost, shadows, onMannequin }: {
  obj: SceneObject; selected: boolean; ghost: boolean; shadows: boolean; onMannequin: (m: MannequinHandle | null) => void;
}) {
  const parts = useMemo(() => (obj.kind === "prefab" && obj.prefab && PREFABS[obj.prefab] ? PREFABS[obj.prefab].build(obj.params) : []), [obj]);
  if (obj.kind === "character") {
    return <Mannequin ref={onMannequin} body={obj.body ?? "male"} height={obj.size[1]} color={obj.color} selected={selected} ghost={ghost} />;
  }
  if (obj.kind === "strip" && obj.strip) return <Strip obj={obj} selected={selected} />;
  if (obj.kind === "prim" && obj.prim) {
    const p = { prim: obj.prim, size: obj.size, pos: [0, 0, 0] as [number, number, number], segments: 16 };
    return (
      <mesh geometry={unitGeometry(p)} material={material(obj.color ?? "#c9cdd4", { selected, ghost })}
        scale={partScale(p)} castShadow={shadows} receiveShadow={shadows} />
    );
  }
  return (
    <>
      {parts.map((p, i) => (
        <mesh key={i} geometry={unitGeometry(p)} position={p.pos} scale={partScale(p)}
          rotation={p.rot ? [rad(p.rot[0]), rad(p.rot[1]), rad(p.rot[2])] : undefined}
          material={material(partColor(p, obj), { glow: p.glow, opacity: p.opacity, selected, ghost })}
          castShadow={shadows && !p.opacity} receiveShadow={shadows} />
      ))}
      {obj.prefab === "image_board" && typeof obj.params.url === "string" && obj.params.url && (
        <BoardImage url={obj.params.url} w={Number(obj.params.width) || 4} h={Number(obj.params.height) || 3} />
      )}
    </>
  );
}

function BoardImage({ url, w, h }: { url: string; w: number; h: number }) {
  const tex = useTexture(url);
  tex.colorSpace = THREE.SRGBColorSpace;
  return (
    <mesh position={[0, h / 2, 0.035]}>
      <planeGeometry args={[w * 0.96, h * 0.96]} />
      <meshBasicMaterial map={tex} toneMapped={false} />
    </mesh>
  );
}

function Strip({ obj, selected }: { obj: SceneObject; selected: boolean }) {
  const s = obj.strip!;
  const y = s.kind === "water" ? 0.012 : 0.02;
  const geo = useMemo(() => stripGeometry(s.points, s.width, y), [s, y]);
  const dash = useMemo(() => (s.lines ? dashGeometry(s.points, y + 0.006) : null), [s, y]);
  return (
    <>
      <mesh geometry={geo} material={material(STRIP_COLOR[s.kind] ?? "#9aa0a8", { selected, opacity: s.kind === "water" ? 0.92 : 1 })} receiveShadow />
      {dash && <mesh geometry={dash} material={material("#f4f4f2")} />}
    </>
  );
}

function EnvironmentView({ doc, shadows, editor }: { doc: SceneDoc; shadows: boolean; editor: boolean }) {
  const env = doc.env;
  const sky = SKY[env.sky] ?? SKY.day;
  const size = env.groundSize;
  const hasSun = doc.lights.some(l => l.kind === "sun");
  const hasAmbient = doc.lights.some(l => l.kind === "ambient");
  const fogNear = size * (0.35 - env.fog * 0.3), fogFar = size * (1.4 - env.fog * 0.9);
  const shadowSpan = Math.min(160, size * 0.6);
  const sunProps = (dir: [number, number, number] | undefined, color: string, intensity: number, key: string) => {
    const d = new THREE.Vector3(...(dir ?? [-0.6, -1.4, -0.5])).normalize();
    const pos = d.clone().multiplyScalar(-80);
    return (
      <directionalLight key={key} position={pos.toArray()} color={color} intensity={intensity} castShadow={shadows}
        shadow-mapSize={[2048, 2048]} shadow-bias={-0.0004}
        shadow-camera-left={-shadowSpan} shadow-camera-right={shadowSpan} shadow-camera-top={shadowSpan}
        shadow-camera-bottom={-shadowSpan} shadow-camera-near={1} shadow-camera-far={260} />
    );
  };
  return (
    <>
      <color attach="background" args={[sky.bg]} />
      {/* 雾是成片的气氛；调度时要看清整个场地，不加 */}
      {env.fog > 0 && !editor && <fog attach="fog" args={[sky.bg, fogNear, fogFar]} />}
      <hemisphereLight args={[sky.hemiSky, sky.hemiGround, hasAmbient ? 0.55 : 0.85]} />
      {!hasSun && sunProps(undefined, sky.sun, sky.sunI, "default-sun")}
      {doc.lights.map(l => {
        if (l.kind === "sun") return sunProps(l.dir, l.color, l.intensity, l.id);
        if (l.kind === "ambient") return <ambientLight key={l.id} color={l.color} intensity={l.intensity} />;
        if (l.kind === "spot") return <spotLight key={l.id} position={l.at ?? [0, 5, 0]} color={l.color} intensity={l.intensity * 20} distance={l.range ?? 20} angle={0.6} penumbra={0.5} castShadow={shadows} />;
        return <pointLight key={l.id} position={l.at ?? [0, 3, 0]} color={l.color} intensity={l.intensity * 10} distance={l.range ?? 12} decay={2} />;
      })}
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[size, size]} />
        <meshStandardMaterial color={GROUND[env.ground] ?? GROUND.grid} roughness={1} />
      </mesh>
      {(env.ground === "grid" || editor) && (
        <gridHelper args={[size, Math.round(size / 2), "#8f959f", "#aeb3bb"]} position={[0, 0.004, 0]}
          material-transparent material-opacity={env.ground === "grid" ? 0.9 : 0.22} />
      )}
    </>
  );
}
