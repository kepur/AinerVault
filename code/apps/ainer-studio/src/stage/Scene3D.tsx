import { useMemo } from "react";
import { Html, Line, RoundedBox, useTexture } from "@react-three/drei";
import * as THREE from "three";
import type { Actor, CamPose, Rig, Vec3 } from "./model";
import { axisSide, hfov, makeCamera, sample, trail, vfov } from "./model";

/** 演员人偶：与服务端预览同一套比例（头 15%，躯干到 52%，其下是腿），真实身高。 */
export function Mannequin({ a, selected, label, dim }: {
  a: Actor; selected?: boolean; label?: boolean; dim?: boolean;
}) {
  const h = a.height;
  const w = h * 0.27 * a.girth;
  const hr = h * 0.075;
  const legTop = h * 0.48;
  const torsoTop = h * 0.84;
  const color = selected ? "#8f82ff" : "#9a9aa4";
  const mat = useMemo(() => new THREE.MeshStandardMaterial({
    color, roughness: 0.75, transparent: !!dim, opacity: dim ? 0.35 : 1,
  }), [color, dim]);
  const legW = w / 2 - 0.015;
  return (
    <group position={[a.pos[0], 0, a.pos[1]]} rotation={[0, THREE.MathUtils.degToRad(a.yaw), 0]}>
      <mesh position={[0, h - hr, 0]} material={mat}>
        <sphereGeometry args={[hr, 24, 16]} />
      </mesh>
      {/* 鼻尖：一眼看出朝向 */}
      <mesh position={[0, h - hr, hr * 0.95]}>
        <coneGeometry args={[hr * 0.22, hr * 0.5, 12]} />
        <meshStandardMaterial color="#ffb86b" />
      </mesh>
      <RoundedBox args={[w, torsoTop - legTop, w * 0.55]} radius={w * 0.2} smoothness={3}
        position={[0, (torsoTop + legTop) / 2, 0]} material={mat} />
      {[-1, 1].map(s => (
        <RoundedBox key={s} args={[legW, legTop, legW * 0.9]} radius={legW * 0.3} smoothness={3}
          position={[s * w / 4, legTop / 2, 0]} material={mat} />
      ))}
      {label && (
        <Html position={[0, h + 0.18, 0]} center zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
          <div className="stage-label">{a.name}</div>
        </Html>
      )}
    </group>
  );
}

/**
 * 背景板：空景贴在一张竖立的板上，放在演员身后，从起幅机位看过去正好铺满画面。
 * 这是预演里的标准做法（background plate card）—— 起幅构图所见即所得；
 * 机位一动，板的边缘会露出来，正好提醒这一镜要补哪一侧的景。
 */
export function BackdropCard({ plate, pose, aspect, actors }: {
  plate: string; pose: CamPose; aspect: number; actors: Actor[];
}) {
  const tex = useTexture(plate);
  tex.colorSpace = THREE.SRGBColorSpace;
  const { position, quaternion, size } = useMemo(() => {
    const cam = makeCamera(pose, aspect);
    const dir = new THREE.Vector3();
    cam.getWorldDirection(dir);
    // 放在最远的演员之后 3 米
    const far = Math.max(8, ...actors.map(a =>
      new THREE.Vector3(a.pos[0], 1, a.pos[1]).sub(cam.position).dot(dir))) + 3;
    const hgt = 2 * far * Math.tan(THREE.MathUtils.degToRad(vfov(pose.lens, aspect)) / 2);
    const p = cam.position.clone().addScaledVector(dir, far);
    return { position: p, quaternion: cam.quaternion.clone(), size: [hgt * aspect, hgt] as [number, number] };
  }, [pose, aspect, actors]);
  return (
    <mesh position={position} quaternion={quaternion}>
      <planeGeometry args={size} />
      <meshBasicMaterial map={tex} toneMapped={false} side={THREE.DoubleSide} />
    </mesh>
  );
}

export function Floor({ size = 40 }: { size?: number }) {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[size, size]} />
        <meshStandardMaterial color="#1c1c22" roughness={1} />
      </mesh>
      <gridHelper args={[size, size, "#3a3a48", "#2a2a33"]} position={[0, 0.002, 0]} />
    </group>
  );
}

/** 相机图示：机身＋视锥四条棱＋画框（画框上沿加一个小三角标出「上」，看得出滚转）。 */
export function CameraGlyph({ pose, aspect, color, reach = 2.2, opacity = 1 }: {
  pose: CamPose; aspect: number; color: string; reach?: number; opacity?: number;
}) {
  const { body, corners, quat, up } = useMemo(() => {
    const cam = makeCamera(pose, aspect);
    const hh = Math.tan(THREE.MathUtils.degToRad(vfov(pose.lens, aspect)) / 2) * reach;
    const hw = hh * aspect;
    const w = (x: number, y: number) => new THREE.Vector3(x, y, -reach).applyMatrix4(cam.matrixWorld);
    const local = [w(-hw, hh), w(hw, hh), w(hw, -hh), w(-hw, -hh)];
    const tri = [w(-hw * 0.18, hh), w(0, hh * 1.25), w(hw * 0.18, hh)];
    return { body: cam.position.clone(), corners: local, quat: cam.quaternion.clone(), up: tri };
  }, [pose, aspect, reach]);
  const o: Vec3 = [body.x, body.y, body.z];
  const c = corners.map(v => [v.x, v.y, v.z] as Vec3);
  const t = up.map(v => [v.x, v.y, v.z] as Vec3);
  const faded = opacity < 1;
  return (
    <group>
      <mesh position={body} quaternion={quat}>
        <boxGeometry args={[0.28, 0.2, 0.36]} />
        <meshStandardMaterial color={color} transparent={faded} opacity={opacity} />
      </mesh>
      {c.map((p, i) => <Line key={i} points={[o, p]} color={color} lineWidth={1.2} transparent opacity={0.8 * opacity} />)}
      <Line points={[...c, c[0]]} color={color} lineWidth={1.6} transparent={faded} opacity={opacity} />
      <Line points={t} color={color} lineWidth={1.4} transparent={faded} opacity={opacity} />
    </group>
  );
}

/** 运镜轨迹：空中的实线＋地面投影虚线＋每一段落地的竖线（看得出高度变化）。 */
export function TrailLine({ rig, color = "#ffd166", ground = true }: { rig: Rig; color?: string; ground?: boolean }) {
  const pts = useMemo(() => trail(rig), [rig]);
  const drops = useMemo(() => (ground ? pts.filter((_, i) => i % 8 === 0) : []), [pts, ground]);
  return (
    <group>
      <Line points={pts} color={color} lineWidth={2.4} />
      {ground && <Line points={pts.map(p => [p[0], 0.01, p[2]] as Vec3)} color={color} lineWidth={1}
        dashed dashSize={0.18} gapSize={0.12} transparent opacity={0.6} />}
      {drops.map((p, i) => (
        <Line key={i} points={[p, [p[0], 0.01, p[2]]]} color={color} lineWidth={0.8} transparent opacity={0.3} />
      ))}
    </group>
  );
}

/** 当前时刻的相机（回放时在俯视图／侧视图／自由视角里跟着走）。 */
export function LiveCamera({ rig, t, aspect }: { rig: Rig; t: number; aspect: number }) {
  const pose = useMemo(() => sample(rig, t), [rig, t]);
  return <CameraGlyph pose={pose} aspect={aspect} color="#ffffff" reach={1.4} />;
}

/** 轨迹上的幽灵机位（¼、½、¾ 处）：一眼看出运镜途中镜头朝哪。 */
export function GhostCameras({ rig, aspect, reach = 0.9 }: { rig: Rig; aspect: number; reach?: number }) {
  const poses = useMemo(() => (rig.move === "static" ? [] :
    [0.25, 0.5, 0.75].map(t => sample({ ...rig, shake: 0 }, t))), [rig]);
  return <>{poses.map((p, i) => <CameraGlyph key={i} pose={p} aspect={aspect} color="#c9c9d6" reach={reach} opacity={0.35} />)}</>;
}

/** 俯视图里的水平视场扇形：看得出这一镜的画面宽度覆盖了谁。 */
export function FovWedge({ pose, color, reach = 9 }: { pose: CamPose; color: string; reach?: number }) {
  const pts = useMemo(() => {
    const dx = pose.target[0] - pose.pos[0];
    const dz = pose.target[2] - pose.pos[2];
    const a = Math.atan2(dz, dx);
    const half = THREE.MathUtils.degToRad(hfov(pose.lens)) / 2;
    const o: Vec3 = [pose.pos[0], 0.02, pose.pos[2]];
    const p = (ang: number): Vec3 => [pose.pos[0] + Math.cos(ang) * reach, 0.02, pose.pos[2] + Math.sin(ang) * reach];
    return [p(a - half), o, p(a + half)];
  }, [pose, reach]);
  return <Line points={pts} color={color} lineWidth={1.2} transparent opacity={0.55} dashed dashSize={0.25} gapSize={0.15} />;
}

/**
 * 180° 轴线：两位主角的连线延长出去，起幅机位对面的半场铺一层红 ——
 * 机位进了红区就是越轴，前后镜的左右关系会反。
 */
export function AxisLine({ a, b, camAt, warn }: { a: Actor; b: Actor; camAt: Vec3; warn: boolean }) {
  const geo = useMemo(() => {
    const d = new THREE.Vector2(b.pos[0] - a.pos[0], b.pos[1] - a.pos[1]);
    if (d.lengthSq() < 1e-6) return null;
    d.normalize();
    const mid = new THREE.Vector2((a.pos[0] + b.pos[0]) / 2, (a.pos[1] + b.pos[1]) / 2);
    const L = 40;
    const p0: Vec3 = [mid.x - d.x * L, 0.03, mid.y - d.y * L];
    const p1: Vec3 = [mid.x + d.x * L, 0.03, mid.y + d.y * L];
    // 红区在机位的对面。n 这一侧在 axisSide 里是 +1，机位在 +1 就往 -n 铺
    const n = new THREE.Vector2(-d.y, d.x);
    const k = axisSide(a, b, camAt) > 0 ? -1 : 1;
    const W = 40;
    const quad = new THREE.BufferGeometry();
    const v = [
      [p0[0], p0[2]], [p1[0], p1[2]],
      [p1[0] + n.x * W * k, p1[2] + n.y * W * k], [p0[0] + n.x * W * k, p0[2] + n.y * W * k],
    ];
    quad.setAttribute("position", new THREE.Float32BufferAttribute(
      [v[0], v[1], v[2], v[0], v[2], v[3]].flatMap(([x, z]) => [x, 0.015, z]), 3));
    return { p0, p1, quad };
  }, [a, b, camAt]);
  if (!geo) return null;
  return (
    <group>
      <mesh geometry={geo.quad}>
        <meshBasicMaterial color="#ff5d5d" transparent opacity={warn ? 0.16 : 0.08} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      <Line points={[geo.p0, geo.p1]} color="#ff6b6b" lineWidth={warn ? 2.4 : 1.4} dashed dashSize={0.4} gapSize={0.25} />
    </group>
  );
}
