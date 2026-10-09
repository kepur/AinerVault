/**
 * 白模全屏浮层（s.overlay.kind === "box"）：双击白模节点或工具条「打开 3D-BOX」进来。
 *
 * - 真实模式：直接挂现成的 3D-BOX 编辑器（box/BoxEditor，lazy）。它靠全局 styles.css 的按钮/表单样式，
 *   放进 .cv-root 会被画布的按钮复位抹掉，所以和导演台一样 portal 到 body。
 *   编辑器自己用 Esc 取消选中，这里不抢 Esc；关掉走它左上角的「←」。
 *   关掉时场景可能被手改过：海报作废、重拉 doc。
 * - 演示模式：编辑器直连后端用不了 —— 给一个能自由转着看的大视口（BoxPreview orbit）+ 机位、播放。
 *
 * 打开期间暂停画布里所有实时视口（suspendLive）：编辑器自己就要 2 个 WebGL 上下文，GPU 让给它。
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Clock, useClock } from "../../box/clock";
import { useCanvas } from "../store";
import { suspendLive } from "./liveBudget";
import { posters } from "./posters";

const BoxEditor = lazy(() => import("../../box/BoxEditor"));
const BoxPreview = lazy(() => import("./BoxPreview"));

export function BoxOverlay() {
  const s = useCanvas();
  const o = s.overlay;
  const id = o?.kind === "box" ? o.id : null;

  useEffect(() => (id ? suspendLive() : undefined), [id]);

  if (!id) return null;

  if (s.demo) {
    const close = () => s.openOverlay(null);
    return <DemoBox id={id} onClose={close} />;
  }

  const back = () => {
    s.openOverlay(null);
    posters.clear(id);
    void s.loadBoxDoc(id, true);
  };
  return createPortal(
    <div className="cv-boxhost">
      <Suspense fallback={<div className="cv-boxhost__wait">载入 3D-BOX 编辑器…</div>}>
        <BoxEditor id={id} onBack={back} />
      </Suspense>
    </div>,
    document.body,
  );
}

/** 演示模式的全屏白模：自由视角 + 机位 + 播放；Esc 关 */
function DemoBox({ id, onClose }: { id: string; onClose: () => void }) {
  const s = useCanvas();
  const box = s.live.boxes[id] ?? null;
  const doc = box?.doc ?? null;
  const [clock] = useState(() => new Clock());
  const [camId, setCamId] = useState<string | null>(null);
  useClock(clock, 80);

  useEffect(() => {
    if (!doc) void s.loadBoxDoc(id);
  }, [id, doc]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!doc) return;
    clock.duration = Math.max(0.1, doc.duration);
    if (clock.t > clock.duration) clock.seek(clock.duration);
  }, [doc, clock]);
  useEffect(() => () => clock.pause(), [clock]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const cams = doc?.cameras ?? [];
  return (
    <div className="cv-3dov" role="dialog" aria-label="3D 白模">
      <header className="cv-3dov__bar cv-glass">
        <b>{box?.title ?? "3D 白模"}</b>
        <span className="cv-3dov__note">演示模式：完整 3D-BOX 编辑器需要连上后端。这里可以拖动旋转、滚轮缩放看白模。</span>
        <span className="cv-3dov__spacer" />
        <button type="button" className="cv-3dov__btn" onClick={() => clock.toggle()} disabled={!doc}>
          {clock.playing ? "暂停" : "播放"}
        </button>
        <input className="cv-3d__seek" type="range" min={0} max={clock.duration} step={0.01} value={clock.t} disabled={!doc}
          aria-label="时间轴" onChange={e => { clock.pause(); clock.seek(Number(e.target.value)); }} />
        <select className="cv-3d__cam" value={camId ?? ""} onChange={e => setCamId(e.target.value || null)}
          title="从哪台机位的位置开始看（之后可以自由拖）">
          <option value="">按剪辑</option>
          {cams.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button type="button" className="cv-3dov__btn" onClick={onClose} title="关闭（Esc）">关闭</button>
      </header>
      <div className="cv-3dov__stage">
        {doc ? (
          <Suspense fallback={<div className="cv-3dov__wait">载入 3D 引擎…</div>}>
            <BoxPreview doc={doc} clock={clock} camId={camId} orbit />
          </Suspense>
        ) : <div className="cv-3dov__wait">{box ? "载入场景…" : "找不到这个白模"}</div>}
      </div>
    </div>
  );
}
