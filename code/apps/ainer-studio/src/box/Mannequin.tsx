/**
 * 带关节的人偶：九种体型。姿势、步态、动作（出拳、闪避、倒地……）都在 scene/rig.ts 里算，
 * 这里只按算好的 JointState 摆关节 —— Blender 渲染读的是同一份，预览和渲染对得上。
 *
 * 关节约定见 rig.ts（人面朝局部 +Z，他的左手在 +X）。
 */
import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";
import * as THREE from "three";
import { JOINTS, mannequinDims, type JointState, type Rot } from "../scene/rig";
import { material } from "./geom";

const r = (d: number) => THREE.MathUtils.degToRad(d);
const setRot = (o: THREE.Object3D | null, v: Rot | undefined) => { if (o) o.rotation.set(r(v?.[0] ?? 0), r(v?.[1] ?? 0), r(v?.[2] ?? 0)); };

export interface MannequinHandle {
  /** 每帧调：rig.jointsAt 算出的骨架状态 */
  animate(state: JointState): void;
}

interface Props { body: string; height?: number; color?: string; selected?: boolean; ghost?: boolean }

export const Mannequin = forwardRef<MannequinHandle, Props>(function Mannequin({ body, height, color, selected, ghost }, ref) {
  const dims = useMemo(() => mannequinDims(body, height), [body, height]);
  const mat = material(color ?? "#bcc0c8", { selected, ghost });
  const joint = material("#9aa0aa", { selected, ghost });
  const nose = material("#ffb86b", { ghost });

  const refs = {
    move: useRef<THREE.Group>(null), root: useRef<THREE.Group>(null), pelvis: useRef<THREE.Group>(null), spine: useRef<THREE.Group>(null), head: useRef<THREE.Group>(null),
    lSh: useRef<THREE.Group>(null), lEl: useRef<THREE.Group>(null), rSh: useRef<THREE.Group>(null), rEl: useRef<THREE.Group>(null),
    lHip: useRef<THREE.Group>(null), lKn: useRef<THREE.Group>(null), rHip: useRef<THREE.Group>(null), rKn: useRef<THREE.Group>(null),
  };

  useImperativeHandle(ref, () => ({
    animate(st) {
      const mv = refs.move.current;
      if (mv) { mv.position.set(st.offset[0], st.offset[1], st.offset[2]); mv.rotation.set(0, r(st.yaw), 0); }
      setRot(refs.root.current, st.root);
      // 躺：整体转 90° 后身体厚度的一半要抬离地面（抬根节点，不能抬盆骨 —— 盆骨的 y 转完成了 z）
      if (refs.root.current) refs.root.current.position.y = st.rootY;
      if (refs.pelvis.current) refs.pelvis.current.position.y = st.pelvisY;
      for (const j of JOINTS) setRot(refs[j].current, st.joints[j]);
    },
  }), []); // eslint-disable-line react-hooks/exhaustive-deps

  const d = dims;
  const limb = (len: number, w: number) => (
    <mesh position={[0, -len / 2, 0]} material={mat} castShadow>
      <capsuleGeometry args={[w, Math.max(0.01, len - w * 2), 3, 8]} />
    </mesh>
  );
  return (
    <group ref={refs.move}>
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
    </group>
  );
});
