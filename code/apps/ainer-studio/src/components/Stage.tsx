import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { OrthographicCamera, RoundedBox, useTexture } from "@react-three/drei";
import * as THREE from "three";
import { api, media } from "../api";
import type { Blocking, CastMember, Figure, ShotCard } from "../types";

/**
 * 3D 导演台 v0。
 *
 * 台上摆的就是送进模型的那张「空景＋人偶」：人偶的比例和服务端渲染器
 * （pipelines/blocking.py 的 _mannequin）一致 —— 头占身高 7.5%、躯干到 52%，
 * 正交相机正对空景，所以这里看到的位置 = 出图时人站的位置。
 *
 * 数据全部按画面比例存（x 身体中线、top/bottom 头顶/脚底、width 肩宽），
 * 与分辨率无关；世界坐标只是把它映射到一块宽 W 的背板上。
 */

const W = 10;

interface Props {
  planId: string;
  shot: ShotCard;
  cast: CastMember[];
  onClose: () => void;
  onChanged: () => void;
}

export default function Stage({ planId, shot, cast, onClose, onChanged }: Props) {
  const [blocking, setBlocking] = useState<Blocking | null>(null);
  const [figs, setFigs] = useState<Figure[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [aspect, setAspect] = useState(800 / 480);
  const [showPreview, setShowPreview] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const dirty = useRef(false);

  const load = () => api.blocking(shot.id).then(b => {
    setBlocking(b);
    setFigs(b.figures);
    setSel(b.figures[0]?.entity_id ?? null);
    dirty.current = false;
  }).catch(e => setMsg(String(e)));
  useEffect(() => { load(); }, [shot.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const update = (id: string, patch: Partial<Figure>) => {
    dirty.current = true;
    setFigs(fs => fs.map(f => (f.entity_id === id ? { ...f, ...patch } : f)));
  };

  /** 远近：以脚底为锚整体缩放 —— 人往远处走是变小，不是飘起来。 */
  const scale = (f: Figure, k: number) => {
    const h = (f.bottom - f.top) * k;
    update(f.entity_id, { top: f.bottom - h, width: f.width * k });
  };

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setMsg("");
    try {
      await fn();
      setMsg(`${label}：完成`);
      onChanged();
    } catch (e) {
      setMsg(`${label}失败：${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }

  const save = () => act("保存站位", async () => {
    const b = await api.saveBlocking(shot.id, figs);
    dirty.current = false;
    setBlocking(prev => (prev ? { ...prev, source: b.source, figures: b.figures } : prev));
  });
  const saveAndRender = () => act("保存并重出首帧", async () => {
    await api.saveBlocking(shot.id, figs);
    dirty.current = false;
    await api.firstFrame(planId, shot.id);
  });
  const reset = () => act("恢复自动摆位", async () => {
    await api.resetBlocking(shot.id);
    await load();
  });

  const faceOf = (f: Figure) =>
    media(cast.find(c => c.entity_id === f.entity_id)?.views.bust ?? f.face_url);

  return (
    <div className="stage-wrap">
      <div className="stage-canvas">
        {/* 按需渲染：站位变了、拖动了才重画。导演台大部分时间是静止的，
            一直 60fps 空转既费电，也让无头截图等不到「页面静下来」 */}
        <Canvas dpr={[1, 2]} frameloop="demand" onPointerMissed={() => setSel(null)}>
          <color attach="background" args={["#0c0c0f"]} />
          <ambientLight intensity={0.55} />
          <directionalLight position={[4, 6, 8]} intensity={1.3} />
          <directionalLight position={[-6, 2, 5]} intensity={0.35} />
          <Suspense fallback={null}>
            {blocking?.plate_url && (
              <Scene
                plate={media(showPreview && blocking.preview_url ? blocking.preview_url : blocking.plate_url)!}
                figs={showPreview ? [] : figs}
                sel={sel}
                onSelect={setSel}
                onMove={update}
                onAspect={setAspect}
                aspect={aspect}
              />
            )}
          </Suspense>
        </Canvas>
        <div className="stage-hint">
          拖动人偶改站位（左右＝位置，上下＝地面线）· 右侧滑块调远近 · Esc 关闭
          {blocking?.source === "stage" && " · 当前是手摆站位"}
        </div>
      </div>

      <aside className="stage-side">
        <h3>3D 导演台 · 镜 {shot.order_no}</h3>
        <div className="stat">{shot.shot_size.toUpperCase()} · {figs.length} 人 · 站位来源：
          {blocking?.source === "stage" ? "手摆" : "按表演单自动"}</div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, color: "var(--muted)" }}>
          <input type="checkbox" checked={showPreview} disabled={!blocking?.preview_url}
            onChange={e => setShowPreview(e.target.checked)} />
          看上次出图用的服务端预览
        </label>

        {figs.map(f => {
          const h = f.bottom - f.top;
          return (
            <div key={f.entity_id} className={`fig-row${sel === f.entity_id ? " on" : ""}`}
              onClick={() => setSel(f.entity_id)}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {faceOf(f) && <img src={faceOf(f)} alt="" style={{ width: 34, height: 34, borderRadius: 6, objectFit: "cover" }} />}
                <b>{f.name}</b>
              </div>
              <label>位置
                <input type="range" min={0.05} max={0.95} step={0.005} value={f.x}
                  onChange={e => update(f.entity_id, { x: +e.target.value })} />
              </label>
              <label>远近
                <input type="range" min={0.3} max={2.2} step={0.01} value={h}
                  onChange={e => scale(f, +e.target.value / h)} />
              </label>
              <label>地面
                <input type="range" min={0.4} max={2} step={0.005} value={f.bottom}
                  onChange={e => update(f.entity_id, { top: +e.target.value - h, bottom: +e.target.value })} />
              </label>
            </div>
          );
        })}

        <div className="actions">
          <button className="primary" disabled={!!busy || !figs.length} onClick={saveAndRender}>
            {busy === "保存并重出首帧" ? "提交中…" : "保存并重出首帧"}
          </button>
          <button disabled={!!busy || !figs.length} onClick={save}>保存站位</button>
          <button disabled={!!busy || blocking?.source !== "stage"} onClick={reset}>恢复自动</button>
          <button onClick={onClose}>关闭</button>
        </div>
        {msg && <div className={msg.includes("失败") ? "err" : "note"}>{msg}</div>}
        <div className="note">
          只能挪人，不能加人：每个人的区域要带他自己的参考脸和外观描述。
          要加人先改表演单再重新绑定。
        </div>
      </aside>
    </div>
  );
}

interface SceneProps {
  plate: string;
  figs: Figure[];
  sel: string | null;
  aspect: number;
  onSelect: (id: string) => void;
  onMove: (id: string, patch: Partial<Figure>) => void;
  onAspect: (a: number) => void;
}

function Scene({ plate, figs, sel, aspect, onSelect, onMove, onAspect }: SceneProps) {
  const tex = useTexture(plate);
  const H = W / aspect;
  const { size } = useThree();
  const drag = useRef<{ id: string; dx: number; dy: number; h: number } | null>(null);

  useEffect(() => {
    tex.colorSpace = THREE.SRGBColorSpace;
    const img = tex.image as HTMLImageElement | undefined;
    if (img?.width && img?.height) onAspect(img.width / img.height);
  }, [tex, onAspect]);

  // 背板正好塞满画布（留一点边）
  const zoom = Math.min(size.width / W, size.height / H) * 0.92;

  // 画面比例 ↔ 世界坐标
  const toWorldX = (x: number) => (x - 0.5) * W;
  const toWorldY = (y: number) => (0.5 - y) * H;
  const fromWorld = (p: THREE.Vector3) => ({ x: p.x / W + 0.5, y: 0.5 - p.y / H });

  const onPlateMove = (e: ThreeEvent<PointerEvent>) => {
    const d = drag.current;
    if (!d) return;
    const p = fromWorld(e.point);
    const x = Math.min(0.97, Math.max(0.03, p.x - d.dx));
    const bottom = Math.min(2, Math.max(0.3, p.y - d.dy));
    onMove(d.id, { x, bottom, top: bottom - d.h });
  };

  useEffect(() => {
    const up = () => { drag.current = null; };
    window.addEventListener("pointerup", up);
    return () => window.removeEventListener("pointerup", up);
  }, []);

  return (
    <>
      <OrthographicCamera makeDefault position={[0, 0, 20]} zoom={zoom} />
      <mesh position={[0, 0, 0]} onPointerMove={onPlateMove}>
        <planeGeometry args={[W, H]} />
        <meshBasicMaterial map={tex} toneMapped={false} />
      </mesh>
      {[...figs].sort((a, b) => a.bottom - b.bottom).map((f, i) => (
        <Mannequin
          key={f.entity_id}
          f={f}
          z={0.5 + i * 0.4}
          selected={sel === f.entity_id}
          toWorldX={toWorldX}
          toWorldY={toWorldY}
          W={W}
          H={H}
          onDown={(e) => {
            e.stopPropagation();
            onSelect(f.entity_id);
            const p = fromWorld(e.point);
            drag.current = { id: f.entity_id, dx: p.x - f.x, dy: p.y - f.bottom, h: f.bottom - f.top };
          }}
          onMovePointer={onPlateMove}
        />
      ))}
    </>
  );
}

interface MannequinProps {
  f: Figure;
  z: number;
  selected: boolean;
  W: number;
  H: number;
  toWorldX: (x: number) => number;
  toWorldY: (y: number) => number;
  onDown: (e: ThreeEvent<PointerEvent>) => void;
  onMovePointer: (e: ThreeEvent<PointerEvent>) => void;
}

/** 与服务端 _mannequin 同一套比例：头 7.5%，躯干到身高 52%，两条腿到脚底。 */
function Mannequin({ f, z, selected, W, H, toWorldX, toWorldY, onDown, onMovePointer }: MannequinProps) {
  const h = (f.bottom - f.top) * H;
  const w = f.width * W;
  const cx = toWorldX(f.x);
  const top = toWorldY(f.top);
  const hr = h * 0.075;
  const torsoTop = top - 2 * hr - h * 0.01;
  const torsoBottom = top - h * 0.52;
  const legBottom = toWorldY(f.bottom);
  const color = selected ? "#8f82ff" : "#8a8a92";
  const mat = useMemo(() => new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0.05 }), [color]);

  // 躯干和腿用圆角盒，不用胶囊：服务端画进预览的是圆角矩形（圆角半径＝肩宽 1/4），
  // 胶囊在矮胖的人身上会鼓成一个球 —— 台上看到的轮廓必须和送进模型的一样
  const torsoLen = Math.max(0.02, torsoTop - torsoBottom);
  const legLen = Math.max(0.02, torsoBottom - legBottom);
  const legW = Math.max(0.02, w / 2 - 0.02);

  return (
    <group onPointerDown={onDown} onPointerMove={onMovePointer}>
      <mesh position={[cx, top - hr, z]} material={mat}>
        <sphereGeometry args={[hr, 24, 16]} />
      </mesh>
      <RoundedBox args={[w, torsoLen, w * 0.55]} radius={Math.min(w * 0.25, torsoLen / 2) * 0.98}
        smoothness={4} position={[cx, (torsoTop + torsoBottom) / 2, z]} material={mat} />
      {[-1, 1].map(side => (
        <RoundedBox key={side} args={[legW, legLen, legW * 0.9]} radius={Math.min(legW * 0.3, legLen / 2) * 0.98}
          smoothness={4} position={[cx + side * (w / 4), (torsoBottom + legBottom) / 2, z]} material={mat} />
      ))}
    </group>
  );
}
