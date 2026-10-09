import { Fragment, memo, useState, type ReactNode } from "react";
import type { NodeProps } from "@xyflow/react";
import VideoFrame from "../../components/VideoFrame";
import { directorPending } from "../../shotStatus";
import type { DirectorRun, ShotCard } from "../../types";
import type { CNode, CNodeData, MediaRef, VideoRole } from "../model";
import { isProductionRef } from "../model";
import { useCanvas, useNodeResolved } from "../store";
import { GenPending, NodeShell, mediaSrc, pct, useLazyStore } from "./NodeShell";

const WIDTH = 280;

/** 导演出片三步（照 components/Inspector.tsx 的 STEPS；run.step=queued 是「从身份首帧接着跑」刚排上队） */
const STEPS: { key: DirectorRun["step"]; label: string }[] = [
  { key: "previs", label: "预演" }, { key: "identity", label: "身份首帧" }, { key: "final", label: "成片" },
];
const RUN_STATUS: Record<string, string> = {
  queued: "排队中", running: "进行中", submitted: "已提交", succeeded: "完成", failed: "失败", cancelled: "已取消",
};
const ROLE_CHIP: Partial<Record<VideoRole, string>> = { previs: "预演", control: "控制素材" };

const runFailed = (run: DirectorRun) => run.status === "failed" || run.status === "cancelled";

function roleOf(data: CNodeData): VideoRole {
  const r = data.role;
  if (r === "shot" || r === "generated" || r === "previs" || r === "control") return r;
  return data.ref.kind === "shot" ? "shot" : "generated";
}

/**
 * 视频节点：分镜镜头（派生，内容现取 board + 导演进度）和自由产物（生成的、白模预演、控制素材）。
 * 平时只挂第一帧当海报，鼠标悬停才真正播放 —— 200 个镜头同时 autoplay 浏览器扛不住。
 */
function VideoNode({ id, data, selected }: NodeProps<CNode>) {
  const r = useNodeResolved(id);
  const [tap, getStore] = useLazyStore();
  const role = roleOf(data);
  const open = (url: string | undefined, video: boolean) =>
    url ? () => getStore()?.openOverlay({ kind: "media", url, video }) : undefined;

  if (r.kind === "shot") {
    const { shot, run } = r;
    const video = mediaSrc(shot.video_url);
    const still = mediaSrc(shot.first?.url ?? shot.last?.url);
    const running = !!run && !run.done && !runFailed(run);
    const pending = running || directorPending(shot)
      || shot.first?.status === "generating" || shot.last?.status === "generating";
    return (
      <NodeShell
        id={id} kind="video" data={data} selected={selected} width={WIDTH}
        busy={pending}
        footer={run && !run.done ? <DirectorSteps run={run} /> : undefined}
        onOpen={video ? open(video, true) : open(still, false)}
      >
        <PlanFrame>
          {video
            ? <HoverVideo src={video} />
            : still
              ? <img className="cv-vid__media" src={still} alt="" draggable={false} decoding="async" />
              : (
                <div className="cv-vid__empty">
                  <span>未出片</span>
                  {pending && <em>出片中…</em>}
                </div>
              )}
          <span className="cv-vid__tag">{shotTag(shot)}</span>
          <span className="cv-vid__flags">
            {pending
              ? <span className="cv-chip is-now">出片中</span>
              : shot.director?.done && (
                <span className="cv-chip" title="LLM 搭白模 → Blender 预演 → 角色库的脸 → LTX 2.5">3D 导演</span>
              )}
          </span>
        </PlanFrame>
        {shot.description && <div className="cv-vid__desc" title={shot.description}>{shot.description}</div>}
        {tap}
      </NodeShell>
    );
  }

  // 自由产物：生成的视频、白模预演、控制素材（演示模式的产物是 SVG，按 mime 当图显示）
  const m: MediaRef | null = r.kind === "media" ? r.media : isProductionRef(data.ref) ? null : data.media ?? null;
  const src = mediaSrc(m?.url);
  const isImage = !!m?.mime?.startsWith("image/");
  const gen = data.gen;
  const pending = gen && (gen.status !== "succeeded" || !src) ? gen : null;
  const chip = ROLE_CHIP[role];
  // 产物自己量得到尺寸就按它（生成时可能选了 9:16），否则跟计划画幅
  const ratio = m?.w && m?.h ? `${m.w} / ${m.h}` : null;

  let content: ReactNode;
  if (pending) content = <GenPending gen={pending} />;
  else if (!src) content = <div className="cv-vid__empty"><span>{r.kind === "missing" && r.reason ? r.reason : data.orphan ? "找不到这段视频了" : "还没有视频"}</span></div>;
  else if (isImage) content = <img className="cv-vid__media" src={src} alt="" draggable={false} decoding="async" />;
  else content = <HoverVideo src={src} />;

  return (
    <NodeShell
      id={id} kind="video" data={data} selected={selected} width={WIDTH}
      badges={gen?.model ? <span className="cv-badge">{gen.model}</span> : undefined}
      onOpen={pending ? undefined : open(src, !isImage)}
    >
      <PlanFrame ratio={ratio}>
        {content}
        {chip && <span className="cv-vid__flags"><span className="cv-chip is-control">{chip}</span></span>}
      </PlanFrame>
      {tap}
    </NodeShell>
  );
}

export default memo(VideoNode);

/** 「镜 3 · MS · 3.5s」 */
function shotTag(shot: ShotCard): string {
  const parts = [`镜 ${shot.order_no}`];
  if (shot.shot_size) parts.push(shot.shot_size.toUpperCase());
  parts.push(`${(shot.duration_ms / 1000).toFixed(1)}s`);
  return parts.join(" · ");
}

/** "16:9" → CSS "16 / 9"；写坏了按 16:9 */
function cssRatio(a: string | null | undefined): string {
  const m = /^\s*(\d+(?:\.\d+)?)\s*[:/x×]\s*(\d+(?:\.\d+)?)\s*$/.exec(a ?? "");
  return m && Number(m[1]) > 0 && Number(m[2]) > 0 ? `${m[1]} / ${m[2]}` : "16 / 9";
}

/**
 * 画面框：比例跟分镜计划的画幅走（board.plan.aspect_ratio）。
 * 单独成组件订阅 store：store 一变只有这个框重渲染，children 是父组件给的同一批元素，React 直接跳过。
 */
function PlanFrame({ ratio, children }: { ratio?: string | null; children: ReactNode }) {
  const s = useCanvas();
  return (
    <div className="cv-vid" style={{ aspectRatio: ratio ?? cssRatio(s.live.board?.plan.aspect_ratio) }}>
      {children}
    </div>
  );
}

/**
 * 平时是 VideoFrame（只拉元数据、停在第一帧）；悬停时在上面叠一个真在播的 <video>，
 * 开始播放后再淡入 —— 直接替换会先黑一下。离开就卸掉，不留解码器。
 */
function HoverVideo({ src }: { src: string }) {
  const [hot, setHot] = useState(false);
  const [playing, setPlaying] = useState(false);
  return (
    <div
      className="cv-vid__media"
      onMouseEnter={() => setHot(true)}
      onMouseLeave={() => { setHot(false); setPlaying(false); }}
    >
      <VideoFrame src={src} at="start" className="cv-vid__poster" />
      {hot && (
        <video
          className={`cv-vid__play${playing ? " is-on" : ""}`}
          src={src}
          muted
          loop
          playsInline
          autoPlay
          onPlaying={() => setPlaying(true)}
        />
      )}
    </div>
  );
}

function DirectorSteps({ run }: { run: DirectorRun }) {
  const failed = runFailed(run);
  const idx = Math.max(0, STEPS.findIndex(x => x.key === (run.step === "queued" ? "identity" : run.step)));
  const p = failed ? null : pct(run.percent);
  // 整体进度：前面做完的步 + 当前步的百分比（run.percent 是当前这一步的）
  const overall = ((idx + (p ?? 0) / 100) / STEPS.length) * 100;
  const status = failed
    ? (run.status === "cancelled" ? "已取消" : "失败")
    : p != null ? `${p}%` : RUN_STATUS[run.status] ?? run.status;
  return (
    <div className={`cv-steps${failed ? " is-bad" : ""}`} title={run.error ?? undefined}>
      <div className="cv-steps__row">
        {STEPS.map((x, i) => (
          <Fragment key={x.key}>
            {i > 0 && <span className="cv-steps__sep">→</span>}
            <span className={i < idx ? "is-ok" : i === idx ? (failed ? "is-bad" : "is-now") : undefined}>{x.label}</span>
          </Fragment>
        ))}
        <span className="cv-steps__pct">{status}</span>
      </div>
      {!failed && <i className="cv-steps__bar" style={{ width: `${overall.toFixed(1)}%` }} />}
      {failed && run.error && <div className="cv-steps__err">{run.error}</div>}
    </div>
  );
}
