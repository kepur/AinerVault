/**
 * 白模的实时视口：节点里（按机位/剪辑表透过镜头看）和演示模式的全屏浮层（orbit 自由看）共用。
 *
 * 只能 lazy 加载（three / R3F 只从这里进主画布）。为什么不直接嵌 box/CameraView：
 * 它写死了阴影（每个上下文一张 2048² 阴影图）和 preserveDrawingBuffer，节点里用不起；
 * 而且 xyflow 节点处在 CSS scale 里，R3F 默认按 getBoundingClientRect 量尺寸会被缩放算两遍，
 * 这里用 offsetSize 量。Driver 照抄 CameraView 的（那边没导出，box/ 下的文件不改）。
 *
 * 海报：暂停时、卸载前（失去实时槽、取消选中、拖出视口）各截一帧给 onPoster。
 * 卸载时这里的 cleanup 先于 Canvas 拆渲染器执行（父组件的 cleanup 先跑），所以 gl 还活着。
 */
import { memo, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type ComponentRef, type RefObject } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { SceneEval } from "../../scene/evaluate";
import type { SceneDoc } from "../../scene/types";
import type { Clock } from "../../box/clock";
import { SceneRender, type RenderOpts } from "../../box/SceneRender";

// 模块级常量：R3F 每次渲染都会拿 props 去 configure，新对象会让它以为配置变了
const DPR: [number, number] = [1, 1.5];
const GL = { antialias: true, powerPreference: "low-power" } as const;
const RESIZE = { offsetSize: true };
const CAMERA = { fov: 40, near: 0.08, far: 3000, position: [0, 12, 30] as [number, number, number] };
const OPTS: RenderOpts = { editor: false, shadows: false };
/** 录制时最多把像素比拉到 4（300px 宽的节点 → 1200px），再高显卡吃不消 */
const MAX_REC_DPR = 4;

/** 全画幅 36mm 的竖直视场角（和 CameraView 一致） */
const vfov = (lens: number, aspect: number) => THREE.MathUtils.radToDeg(2 * Math.atan(18 / lens / aspect));

export interface BoxPreviewProps {
  doc: SceneDoc;
  clock: Clock;
  /** null = 按剪辑表（主机位时间表）切 */
  camId: string | null;
  /** 自由看（OrbitControls）：演示模式的全屏浮层用；节点里为假，画布不接指针，节点照样能拖 */
  orbit?: boolean;
  /** 拿到/失去画布（录预演要它） */
  onCanvas?: (c: HTMLCanvasElement | null) => void;
  /** 截到一帧海报（JPEG data URL） */
  onPoster?: (dataUrl: string) => void;
  className?: string;
  /** 录预演时把画布像素宽度临时拉到这个值：节点 CSS 只有 300px，直接录太糊（BoxPreview 规格之外的可选扩展） */
  recordWidth?: number | null;
  /** WebGL 上下文被浏览器收走了（上下文超限、GPU 重置）：调用方退回海报（规格之外的可选扩展） */
  onLost?: () => void;
}

interface Grab { gl: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.Camera; ready: boolean }

/** 现画一帧再立刻取像素：不开 preserveDrawingBuffer 也取得到（同一个任务里，缓冲区还没被合成清掉） */
function snap(g: Grab | null): string | null {
  if (!g?.ready) return null;
  try {
    if (g.gl.getContext().isContextLost()) return null;
    g.gl.render(g.scene, g.camera);
    return g.gl.domElement.toDataURL("image/jpeg", 0.82);
  } catch {
    return null;
  }
}

function BoxPreview({ doc, clock, camId, orbit = false, onCanvas, onPoster, className, recordWidth, onLost }: BoxPreviewProps) {
  const ev = useMemo(() => new SceneEval(doc), [doc]);
  const wrap = useRef<HTMLDivElement>(null);
  const grab = useRef<Grab | null>(null);
  const alive = useRef(true);
  // 回调放 ref：父组件每次渲染给新函数也不该重挂订阅
  const cb = useRef({ onCanvas, onPoster, onLost });
  cb.current = { onCanvas, onPoster, onLost };

  // 暂停时截一张：等按需渲染把暂停那一刻画完（下一帧）再截
  useEffect(() => {
    let was = clock.playing;
    let raf = 0;
    const off = clock.subscribe(() => {
      if (was && !clock.playing) {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => {
          raf = requestAnimationFrame(() => {
            const u = snap(grab.current);
            if (u) cb.current.onPoster?.(u);
          });
        });
      }
      was = clock.playing;
    });
    return () => { off(); cancelAnimationFrame(raf); };
  }, [clock]);

  // 卸载前截一张。layout cleanup：在 Canvas 拆掉渲染器、强制丢上下文之前跑
  useLayoutEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      const u = snap(grab.current);
      if (u) cb.current.onPoster?.(u);
      cb.current.onCanvas?.(null);
    };
  }, []);

  // 录制时按目标宽度算像素比；必须走 Canvas 的 dpr prop（R3F 每次渲染都按 prop 重设 dpr，单独 setDpr 会被冲掉）
  const [recDpr, setRecDpr] = useState<number | null>(null);
  useLayoutEffect(() => {
    const w = wrap.current?.offsetWidth ?? 0;
    setRecDpr(recordWidth && w > 0 ? Math.min(MAX_REC_DPR, Math.max(1, recordWidth / w)) : null);
  }, [recordWidth]);

  return (
    <div ref={wrap} className={`cv-3d-canvas${orbit ? " is-orbit" : ""}${className ? ` ${className}` : ""}`}>
      <Canvas
        frameloop="demand" dpr={recDpr ?? DPR} shadows={false} gl={GL} resize={RESIZE} camera={CAMERA}
        style={{ pointerEvents: orbit ? "auto" : "none" }}
      >
        <Tap grab={grab} alive={alive} cb={cb} />
        {orbit ? <OrbitRig ev={ev} clock={clock} camId={camId} /> : <Driver ev={ev} clock={clock} camId={camId} aspect={doc.aspect} />}
        {/* image_board 的贴图会挂起：挂起期间别截海报（Ready 只在内容就绪后才挂上） */}
        <Suspense fallback={null}>
          <SceneRender doc={doc} ev={ev} clock={clock} opts={OPTS} />
          <Ready grab={grab} />
        </Suspense>
      </Canvas>
    </div>
  );
}

export default memo(BoxPreview);

/** 拿渲染器、场景、相机给截图用；交出画布；盯着上下文丢失 */
function Tap({ grab, alive, cb }: {
  grab: RefObject<Grab | null>;
  alive: RefObject<boolean>;
  cb: RefObject<Pick<BoxPreviewProps, "onCanvas" | "onPoster" | "onLost">>;
}) {
  const gl = useThree(s => s.gl);
  const scene = useThree(s => s.scene);
  const camera = useThree(s => s.camera);
  useEffect(() => {
    grab.current = { gl, scene, camera, ready: grab.current?.ready ?? false };
  }, [gl, scene, camera, grab]);
  useEffect(() => {
    const el = gl.domElement;
    cb.current.onCanvas?.(el);
    // 正常卸载时 R3F 也会 forceContextLoss —— 那时 alive 已经是 false，不算「丢了」
    const lost = () => { if (alive.current) cb.current.onLost?.(); };
    el.addEventListener("webglcontextlost", lost);
    return () => el.removeEventListener("webglcontextlost", lost);
  }, [gl, alive, cb]);
  return null;
}

function Ready({ grab }: { grab: RefObject<Grab | null> }) {
  useFrame(() => { if (grab.current) grab.current.ready = true; });
  return null;
}

/** 照抄 box/CameraView.tsx 的 Driver：每帧把相机摆到机位（指定的一台，或剪辑表当前那台）在 clock.t 的位置 */
function Driver({ ev, clock, camId, aspect }: { ev: SceneEval; clock: Clock; camId: string | null; aspect: number }) {
  const camera = useThree(s => s.camera);
  const invalidate = useThree(s => s.invalidate);
  useEffect(() => clock.subscribe(() => invalidate()), [clock, invalidate]);
  // 换机位、换场景时补画一帧（时钟停着的时候没人 invalidate）
  useEffect(() => { invalidate(); }, [ev, camId, invalidate]);
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

/** 自由看：从当前机位的位置出发，绕它看向的点转。换机位、换场景时重置回那台机位 */
function OrbitRig({ ev, clock, camId }: { ev: SceneEval; clock: Clock; camId: string | null }) {
  const camera = useThree(s => s.camera) as THREE.PerspectiveCamera;
  const invalidate = useThree(s => s.invalidate);
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null);
  useEffect(() => clock.subscribe(() => invalidate()), [clock, invalidate]);
  useLayoutEffect(() => {
    const cam = camId ? ev.doc.cameras.find(c => c.id === camId) : ev.activeCamera(clock.t);
    const target = new THREE.Vector3(0, 1, 0);
    if (cam) {
      const p = ev.camera(cam, clock.t);
      camera.position.set(...p.pos);
      target.set(...p.look);
      camera.fov = vfov(p.lens, camera.aspect || 16 / 9);
    } else {
      camera.position.set(0, 12, 30);
    }
    camera.up.set(0, 1, 0);
    camera.near = 0.08;
    camera.far = 3000;
    camera.updateProjectionMatrix();
    controls.current?.target.copy(target);
    controls.current?.update();
    invalidate();
    // clock.t 故意不进依赖：只取「切换那一刻」的值，播放时不跟着重置视角
  }, [ev, camId, camera, invalidate]);
  return <OrbitControls ref={controls} makeDefault enableDamping={false} onChange={() => invalidate()} />;
}
