/**
 * 带关节的人偶：九种体型、十六种姿势，走/跑时按走过的距离摆臂迈腿。
 *
 * 关节约定（人面朝局部 +Z）：绕 X 转负角 = 往前摆（抬腿、抬臂向前）；
 * 左侧是 +X（人面朝观众时他的左手在观众右边）。
 */
import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";
import * as THREE from "three";
import { BODIES } from "../scene/prefabs";
import { material } from "./geom";

type Rot = [number, number, number];
interface PoseDef {
  lift?: number;           // 盆骨下沉（米，按腿长比例）：坐、蹲
  root?: Rot;              // 整体旋转：躺
  spine?: Rot; head?: Rot;
  lSh?: Rot; lEl?: Rot; rSh?: Rot; rEl?: Rot;
  lHip?: Rot; lKn?: Rot; rHip?: Rot; rKn?: Rot;
}

const P: Record<string, PoseDef> = {
  stand: { lSh: [0, 0, 8], rSh: [0, 0, -8] },
  walk: { lSh: [0, 0, 6], rSh: [0, 0, -6] },
  run: { spine: [12, 0, 0], lSh: [0, 0, 8], rSh: [0, 0, -8], lEl: [-80, 0, 0], rEl: [-80, 0, 0] },
  sit: { lift: 0.52, lHip: [-90, 0, 4], rHip: [-90, 0, -4], lKn: [90, 0, 0], rKn: [90, 0, 0], lSh: [-20, 0, 6], rSh: [-20, 0, -6], lEl: [-40, 0, 0], rEl: [-40, 0, 0] },
  drive: { lift: 0.52, lHip: [-90, 0, 4], rHip: [-90, 0, -4], lKn: [80, 0, 0], rKn: [80, 0, 0], lSh: [-65, 0, 8], rSh: [-65, 0, -8], lEl: [-25, 0, 0], rEl: [-25, 0, 0] },
  crouch: { lift: 0.45, spine: [25, 0, 0], lHip: [-110, 0, 8], rHip: [-110, 0, -8], lKn: [130, 0, 0], rKn: [130, 0, 0], lSh: [-30, 0, 10], rSh: [-30, 0, -10], lEl: [-40, 0, 0], rEl: [-40, 0, 0] },
  kneel: { lift: 0.3, lHip: [-90, 0, 4], lKn: [90, 0, 0], rHip: [0, 0, -4], rKn: [90, 0, 0], lSh: [0, 0, 8], rSh: [0, 0, -8] },
  point: { lSh: [0, 0, 8], rSh: [-88, 0, -4] },
  wave: { lSh: [0, 0, 8], rSh: [0, 0, -150], rEl: [0, 0, -30] },
  fight: { lHip: [-10, 0, 10], rHip: [10, 0, -10], lKn: [20, 0, 0], rKn: [15, 0, 0], lSh: [-60, 0, 20], rSh: [-45, 0, -20], lEl: [-110, 0, 0], rEl: [-120, 0, 0], spine: [8, -15, 0] },
  lie: { root: [-90, 0, 0], lSh: [0, 0, 12], rSh: [0, 0, -12] },
  phone: { lSh: [0, 0, 8], rSh: [-25, 0, -35], rEl: [-140, 0, 0] },
  arms_crossed: { lSh: [-35, -25, 10], rSh: [-35, 25, -10], lEl: [-110, 0, 0], rEl: [-110, 0, 0] },
  hands_up: { lSh: [0, 0, 160], rSh: [0, 0, -160], lEl: [0, 0, 20], rEl: [0, 0, -20] },
  aim: { lSh: [-88, -18, 0], rSh: [-88, 18, 0], spine: [0, 10, 0] },
  bow: { spine: [45, 0, 0], head: [10, 0, 0], lSh: [-15, 0, 4], rSh: [-15, 0, -4] },
};

const r = (d: number) => THREE.MathUtils.degToRad(d);
const setRot = (o: THREE.Object3D | null, v: Rot | undefined) => { if (o) o.rotation.set(r(v?.[0] ?? 0), r(v?.[1] ?? 0), r(v?.[2] ?? 0)); };

export interface MannequinHandle {
  /** 每帧调：pose 名、步态相位（圈数）、速度（米/秒） */
  animate(pose: string, phase: number, speed: number): void;
}

interface Props { body: string; height?: number; color?: string; selected?: boolean; ghost?: boolean }

export const Mannequin = forwardRef<MannequinHandle, Props>(function Mannequin({ body, height, color, selected, ghost }, ref) {
  const b = BODIES[body] ?? BODIES.male;
  const H = height ?? b.height;
  const chibi = body === "chibi";
  const dims = useMemo(() => {
    const head = (chibi ? 0.2 : 0.066 * b.head) * H;
    const leg = (chibi ? 0.34 : 0.47) * H;
    const torso = chibi ? 0.24 * H : 0.3 * H;
    return {
      head, leg, torso, neck: 0.03 * H,
      shoulder: 0.115 * H * b.width * (chibi ? 1.2 : 1), hip: 0.055 * H * b.width,
      upperArm: (chibi ? 0.13 : 0.17) * H, foreArm: (chibi ? 0.12 : 0.16) * H,
      limb: 0.045 * H * b.width, chest: 0.2 * H * b.width,
    };
  }, [H, b, chibi]);
  const mat = material(color ?? "#bcc0c8", { selected, ghost });
  const joint = material("#9aa0aa", { selected, ghost });
  const nose = material("#ffb86b", { ghost });

  const refs = {
    root: useRef<THREE.Group>(null), pelvis: useRef<THREE.Group>(null), spine: useRef<THREE.Group>(null), head: useRef<THREE.Group>(null),
    lSh: useRef<THREE.Group>(null), lEl: useRef<THREE.Group>(null), rSh: useRef<THREE.Group>(null), rEl: useRef<THREE.Group>(null),
    lHip: useRef<THREE.Group>(null), lKn: useRef<THREE.Group>(null), rHip: useRef<THREE.Group>(null), rKn: useRef<THREE.Group>(null),
  };

  useImperativeHandle(ref, () => ({
    animate(pose, phase, speed) {
      const moving = speed > 0.15 && (pose === "stand" || pose === "walk" || pose === "run");
      const def = P[moving ? (speed > 2.6 ? "run" : "walk") : pose] ?? P.stand;
      setRot(refs.root.current, def.root);
      // 躺：整体转 90° 后身体厚度的一半要抬离地面（抬根节点，不能抬盆骨 —— 盆骨的 y 转完成了 z）
      if (refs.root.current) refs.root.current.position.y = def.root ? dims.chest * 0.28 : 0;
      if (refs.pelvis.current) refs.pelvis.current.position.y = dims.leg * (1 - (def.lift ?? 0));
      setRot(refs.spine.current, def.spine);
      setRot(refs.head.current, def.head);
      for (const k of ["lSh", "lEl", "rSh", "rEl", "lHip", "lKn", "rHip", "rKn"] as const) setRot(refs[k].current, def[k]);
      if (moving) {
        const s = Math.sin(phase * Math.PI * 2);
        const run = speed > 2.6;
        const A = run ? 50 : 28;
        const add = (o: THREE.Object3D | null, dx: number) => { if (o) o.rotation.x += r(dx); };
        add(refs.lHip.current, -A * s); add(refs.rHip.current, A * s);
        add(refs.lKn.current, Math.max(0, s) * (run ? 90 : 45)); add(refs.rKn.current, Math.max(0, -s) * (run ? 90 : 45));
        add(refs.lSh.current, A * 0.8 * s); add(refs.rSh.current, -A * 0.8 * s);
        if (refs.pelvis.current) refs.pelvis.current.position.y += Math.abs(Math.cos(phase * Math.PI * 2)) * (run ? 0.05 : 0.025);
      }
    },
  }), [dims]); // eslint-disable-line react-hooks/exhaustive-deps

  const d = dims;
  const limb = (len: number, w: number) => (
    <mesh position={[0, -len / 2, 0]} material={mat} castShadow>
      <capsuleGeometry args={[w, Math.max(0.01, len - w * 2), 3, 8]} />
    </mesh>
  );
  return (
    <group ref={refs.root}>
      <group ref={refs.pelvis} position={[0, d.leg, 0]}>
        <mesh material={joint} castShadow><boxGeometry args={[d.hip * 2 + d.limb * 2, d.limb * 2.2, d.limb * 2.4]} /></mesh>
        {/* 腿 */}
        {([["lHip", "lKn", 1], ["rHip", "rKn", -1]] as const).map(([hip, knee, side]) => (
          <group key={hip} ref={refs[hip]} position={[side * d.hip, 0, 0]}>
            {limb(d.leg * 0.5, d.limb * 1.1)}
            <group ref={refs[knee]} position={[0, -d.leg * 0.5, 0]}>
              {limb(d.leg * 0.5, d.limb)}
              <mesh position={[0, -d.leg * 0.5 + 0.03, 0.05]} material={joint}><boxGeometry args={[d.limb * 1.8, 0.06, d.limb * 4]} /></mesh>
            </group>
          </group>
        ))}
        {/* 躯干 */}
        <group ref={refs.spine}>
          <mesh position={[0, d.torso / 2, 0]} material={mat} castShadow>
            <boxGeometry args={[d.chest, d.torso, d.chest * 0.55]} />
          </mesh>
          <group ref={refs.head} position={[0, d.torso + d.neck, 0]}>
            <mesh position={[0, d.head, 0]} material={mat} castShadow><sphereGeometry args={[d.head, 16, 12]} /></mesh>
            {/* 鼻尖：一眼看出朝向 */}
            <mesh position={[0, d.head, d.head * 0.95]} rotation={[Math.PI / 2, 0, 0]} material={nose}><coneGeometry args={[d.head * 0.22, d.head * 0.5, 8]} /></mesh>
          </group>
          {([["lSh", "lEl", 1], ["rSh", "rEl", -1]] as const).map(([sh, el, side]) => (
            <group key={sh} ref={refs[sh]} position={[side * d.shoulder, d.torso * 0.94, 0]}>
              {limb(d.upperArm, d.limb * 0.9)}
              <group ref={refs[el]} position={[0, -d.upperArm, 0]}>{limb(d.foreArm, d.limb * 0.8)}</group>
            </group>
          ))}
        </group>
      </group>
    </group>
  );
});
