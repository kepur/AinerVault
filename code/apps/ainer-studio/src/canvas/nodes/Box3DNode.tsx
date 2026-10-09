import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { navigate } from "../../ctx";
import type { NodeProps } from "@xyflow/react";
import { Clock, useClock } from "../../box/clock";
import { cv, media } from "../api";
import type { BoxInfo, CNode } from "../model";
import { useCanvas, useNodeResolved } from "../store";
import { onRecordRequest } from "../three/actions";
import { isLive, LIVE_PRIORITY, useLiveSlot, useLiveWaiting } from "../three/liveBudget";
import { posters, usePoster } from "../three/posters";
import { NodeShell, mediaSrc, useLazyStore } from "./NodeShell";

// three / R3F 只从这里进来：主画布首包不带 3D 引擎（铁律 10）
const BoxPreview = lazy(() => import("../three/BoxPreview"));

const WIDTH = 300;
/** 录预演的像素宽度：节点 CSS 只有 300px，直接录太糊；1024 对齐 LTX 的 1024×576 */
const REC_WIDTH = 1024;
const REC_FPS = 30;

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * 3D-BOX 项目还没有缩略图时，把实时视口截到的第一张海报回存成项目缩略图（和 BoxEditor 关闭时做的一样）。
 * 这样下次打开画布、没选中的白模也显示场景而不是占位网格。每个项目每次打开页面只存一次，失败不打扰人。
 */
const thumbSaved = new Set<string>();
function saveThumb(boxId: string, dataUrl: string) {
  if (thumbSaved.has(boxId)) return;
  thumbSaved.add(boxId);
  void fetch(dataUrl)
    .then(r => r.blob())
    .then(b => cv.boxExport(boxId, b, { kind: "thumb" }))
    .catch(e => { thumbSaved.delete(boxId); console.warn("[canvas] 白模缩略图没存上", boxId, e); });
}
const fmt = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

/**
 * 3D 白模节点：平时是海报（实时视口截的帧 → 3D-BOX 缩略图 → 占位网格），
 * 选中或开了「实时」才向 liveBudget 要一个实时槽（同屏最多 2 个 WebGL 视口），拿到了才挂 BoxPreview。
 * 每个节点自己一个 Clock：播放、拖时间轴不经过 React 状态，也不影响别的节点。
 */
export default function Box3DNode({ id, data, selected }: NodeProps<CNode>) {
  const r = useNodeResolved(id);
  const [tap, getStore] = useLazyStore();
  const box: BoxInfo | null = r.kind === "box_project" ? r.box : null;
  const boxId = data.ref.kind === "box_project" ? data.ref.id : null;
  const doc = box?.doc ?? null;
  const camId = data.camera ?? null;

  const [clock] = useState(() => new Clock());
  const [rec, setRec] = useState<number | null>(null);
  const [lost, setLost] = useState(false);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const recBusy = useRef(false);

  // 场景换了（智能体改完、编辑器关掉）：时长跟着变，播放头别停在新时长外面
  useEffect(() => {
    if (!doc) return;
    clock.duration = Math.max(0.1, doc.duration);
    if (clock.t > clock.duration) clock.seek(clock.duration);
  }, [doc, clock]);
  useEffect(() => () => clock.pause(), [clock]);

  // 上下文被浏览器收走过：重新选中时再试一次
  useEffect(() => { if (selected) setLost(false); }, [selected]);

  const want = !!boxId && !lost && (selected || !!data.live || rec != null);
  const priority = rec != null ? LIVE_PRIORITY.recording : selected ? LIVE_PRIORITY.selected : LIVE_PRIORITY.live;
  const slot = useLiveSlot(id, want, priority);
  const waiting = useLiveWaiting(id);

  // 要实时了才拉完整场景（轻量信息里可能不带 doc）
  const hasDoc = !!doc;
  useEffect(() => {
    if (want && boxId && !hasDoc) void getStore()?.loadBoxDoc(boxId);
  }, [want, boxId, hasDoc, getStore]);

  // 录预演的最新参数放 ref：订阅只挂一次，点录制时读到的是当下的机位、场景
  const latest = useRef({ boxId, camId, doc });
  latest.current = { boxId, camId, doc };

  useEffect(() => onRecordRequest(id, () => {
    const s = getStore();
    const cur = latest.current;
    if (!s || !cur.boxId) return;
    if (recBusy.current) { s.toast("这个白模正在录，等它录完", "info"); return; }
    if (!canvas.current || !isLive(id) || !cur.doc) { s.toast("先选中白模，等它实时渲染后再录", "info"); return; }
    recBusy.current = true;
    setRec(0);
    void (async () => {
      const boxId = cur.boxId!;
      try {
        // 等 BoxPreview 按录制宽度换完像素比（下一帧才生效）再开录
        await new Promise(res => requestAnimationFrame(() => requestAnimationFrame(res)));
        const el = canvas.current;
        if (!el) throw new Error("实时视口没了（节点被拖出屏幕？）");
        // box/CameraView 带着 three：录的时候实时视口已经把 three 载入了，这里动态取不多花钱，首包也不带它
        const { recordCanvas } = await import("../../box/CameraView");
        const blob = await recordCanvas(el, clock, REC_FPS, u => setRec(u));
        const w = el.width;
        const h = el.height;
        const res = await cv.boxExport(boxId, blob, { kind: "preview", camera: cur.camId ?? undefined, duration: clock.duration });
        const url = res.url.startsWith("data:") || res.url.startsWith("blob:") ? res.url : media(res.url) ?? res.url;
        const st = getStore();
        st?.addNode("video", {
          ref: { kind: "asset", id: res.asset_id }, title: "白模预演", role: "previs",
          media: { url, asset_id: res.asset_id, mime: blob.type || "video/webm", w, h, duration: clock.duration },
        }, undefined, { source: id, kind: "control" });
        st?.toast("预演录好了，已接在白模右边（青色控制线）", "ok");
      } catch (e) {
        getStore()?.toast(`录预演失败：${msg(e)}`, "err");
      } finally {
        recBusy.current = false;
        setRec(null);
      }
    })();
  }), [id, clock, getStore]);

  const exact = usePoster(boxId, camId);
  const anyPoster = usePoster(boxId, camId, false);
  const poster = exact ?? anyPoster ?? mediaSrc(box?.thumb_url);

  const cams = doc?.cameras ?? box?.cameras ?? [];
  const objects = doc?.objects.length ?? null;
  const duration = doc?.duration ?? box?.duration ?? null;
  const aspect = doc?.aspect && doc.aspect > 0 ? doc.aspect : 16 / 9;
  const orbit = Boolean(data.orbit);
  const live = slot && !!doc;

  let picture: ReactNode;
  if (!box) {
    picture = (
      <div className="cv-3d__ph">
        <b>3D 白模</b>
        <span>{data.orphan ? "3D-BOX 里找不到这个项目了" : "载入中…"}</span>
      </div>
    );
  } else {
    const still = poster
      ? <img className="cv-3d__poster" src={poster} alt="" draggable={false} decoding="async" />
      : (
        <div className="cv-3d__ph">
          <b>3D 白模</b>
          <span>{[objects != null ? `${objects} 物体` : "", cams.length ? `${cams.length} 机位` : ""].filter(Boolean).join(" · ") || box.title}</span>
        </div>
      );
    picture = (
      <>
        {still}
        {live && (
          <Suspense fallback={null}>
            <BoxPreview
              doc={doc!} clock={clock} camId={camId} orbit={orbit}
              recordWidth={rec != null ? REC_WIDTH : null}
              onCanvas={c => { canvas.current = c; }}
              onPoster={u => {
                if (!boxId) return;
                posters.set(boxId, camId, u);
                if (!box.thumb_url) saveThumb(boxId, u);
              }}
              onLost={() => setLost(true)}
            />
          </Suspense>
        )}
        {orbit && live && (
          <div className="cv-3d__orbit-bar nodrag nopan">
            <span>自由视角（拖拽旋转 · 滚轮缩放）</span>
            <button type="button" onClick={() => getStore()?.updateNodeData(id, { orbit: false })}>复位</button>
          </div>
        )}
        {want && slot && !doc && <span className="cv-3d__load">载入场景…</span>}
      </>
    );
  }

  const chip = ["3D 白模", duration != null ? `${duration.toFixed(1)}s` : "", cams.length ? `${cams.length} 机位` : ""]
    .filter(Boolean).join(" · ");

  return (
    <NodeShell
      id={id} kind="box3d" data={data} selected={selected} width={WIDTH}
      busy={!!box?.active_run || rec != null}
      badges={<Box3DBadges id={id} agent={!!box?.active_run} rec={rec} broken={box?.ok === false} />}
      footer={box && doc ? (
        <BoxFoot clock={clock} cams={cams} camId={camId} live={live} waiting={waiting && !slot} rec={rec}
          orbit={orbit} onOrbit={o => getStore()?.updateNodeData(id, { orbit: o, live: o ? true : data.live })}
          onCam={c => getStore()?.updateNodeData(id, { camera: c, orbit: false })} />
      ) : undefined}
      onOpen={boxId ? () => getStore()?.openOverlay({ kind: "box", id: boxId }) : undefined}
    >
      <div className={`cv-3d${live ? " is-live" : ""}${orbit && live ? " is-orbit nodrag nopan" : ""}`} style={{ aspectRatio: String(aspect) }}>
        {picture}
        <span className="cv-3d__chip">
          <span>{chip}</span>
          {boxId && (
            <button
              type="button"
              className="cv-3d__chip-open nodrag nopan"
              title="切到 3D-BOX 调度编辑器（左上「← 创作画布」回来；双击节点在浮层里打开）"
              onClick={e => { e.stopPropagation(); navigate("box", { box: boxId, from: "flow" }); }}
            >
              调度 ↗
            </button>
          )}
        </span>
      </div>
      {tap}
    </NodeShell>
  );
}

/**
 * 标题行角标：搭景中 / 渲染中 / 录制中 / 脚本有错。
 * 单独成组件才订阅 store（tasks）：store 一变只有这一小块重渲染，节点本体不动。
 */
function Box3DBadges({ id, agent, rec, broken }: { id: string; agent: boolean; rec: number | null; broken: boolean }) {
  const s = useCanvas();
  const mine = s.tasks.filter(t => t.nodeId === id && (t.status === "queued" || t.status === "running"));
  const building = agent || mine.some(t => t.kind === "box_agent");
  const rendering = mine.some(t => t.kind === "blender");
  return (
    <>
      {rec != null && <span className="cv-badge is-bad">录制中 {Math.round(rec * 100)}%</span>}
      {building && <span className="cv-badge is-now">搭景中…</span>}
      {rendering && <span className="cv-badge is-now">渲染中…</span>}
      {broken && <span className="cv-badge is-warn" title="scene.js 编译出错，去 3D-BOX 里看报错">脚本有错</span>}
    </>
  );
}

/**
 * 底部控件：播放/暂停、时间轴、时间码、机位。
 * 单独订阅时钟（节流 80ms）：播放时只有这一条重渲染，3D 视口自己在 useFrame 里读 clock.t。
 */
function BoxFoot({ clock, cams, camId, live, waiting, rec, orbit, onOrbit, onCam }: {
  clock: Clock;
  cams: { id: string; name: string }[];
  camId: string | null;
  live: boolean;
  waiting: boolean;
  rec: number | null;
  orbit: boolean;
  onOrbit: (o: boolean) => void;
  onCam: (c: string | null) => void;
}) {
  useClock(clock, 80);
  const recording = rec != null;
  return (
    <div className="cv-3d__foot nodrag nopan" onDoubleClick={e => e.stopPropagation()}>
      <button type="button" className="cv-3d__play" disabled={recording}
        title={live ? (clock.playing ? "暂停" : "播放") : "选中节点、等它实时渲染后才能播放"}
        aria-label={clock.playing ? "暂停" : "播放"}
        onClick={() => clock.toggle()}>
        {clock.playing
          ? <svg viewBox="0 0 12 12" aria-hidden><path d="M3.5 2.5v7M8.5 2.5v7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
          : <svg viewBox="0 0 12 12" aria-hidden><path d="M3.5 2v8l6.5-4z" fill="currentColor" /></svg>}
      </button>
      <input
        className="cv-3d__seek" type="range" min={0} max={clock.duration} step={0.01} value={clock.t}
        disabled={recording} aria-label="时间轴"
        onChange={e => { clock.pause(); clock.seek(Number(e.target.value)); }}
      />
      <span className="cv-3d__tc">{fmt(clock.t)}</span>
      <button
        type="button"
        className={`cv-3d__orbit-btn${orbit ? " is-on" : ""}`}
        disabled={recording}
        title={orbit ? "当前：自由视角（点击切回机位）" : "切换自由视角（可在视口内拖拽旋转、滚轮缩放）"}
        onClick={() => onOrbit(!orbit)}
      >
        <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
          <path d="M8 2.5a5.5 5.5 0 1 0 5.5 5.5" strokeLinecap="round" />
          <path d="M13.5 4.5l.5 3.5-3.5-.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span>{orbit ? "自由" : "机位"}</span>
      </button>
      <select className="cv-3d__cam" value={camId ?? ""} disabled={recording}
        title="看哪台机位；「按剪辑」= 按主机位时间表切换"
        onChange={e => onCam(e.target.value || null)}>
        <option value="">按剪辑</option>
        {cams.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        {camId && !cams.some(c => c.id === camId) && <option value={camId}>已删的机位</option>}
      </select>
      {(waiting || recording) && (
        <div className="cv-3d__note">
          {recording
            ? `录制中 ${Math.round((rec ?? 0) * 100)}%，别切机位`
            : "同屏实时视口已满（最多 2 个），先取消别的白模的「实时」"}
        </div>
      )}
    </div>
  );
}
