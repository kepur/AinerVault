import VideoFrame from "./VideoFrame";
import { hrefFor, navigate } from "../ctx";
import { useEffect, useRef, useState } from "react";
import { api, media } from "../api";
import type { DirectorRun, ShotCard } from "../types";
import { moveLabel, type MoveKind } from "../stage/moves";

interface Props {
  planId: string;
  shot: ShotCard;
  onStage: () => void;
  onChanged: () => void;
}

const STATUS: Record<string, string> = {
  pending: "未出", generating: "生成中", ready: "就绪", approved: "已通过", failed: "失败", skipped: "跳过",
};

/** 导演出片的三步（run.step 为 queued 时是「从身份首帧接着跑」刚排上队） */
const STEPS: { key: DirectorRun["step"]; label: string }[] = [
  { key: "previs", label: "预演" }, { key: "identity", label: "身份首帧" }, { key: "final", label: "成片" },
];
const RUN_STATUS: Record<string, string> = {
  queued: "排队中", running: "进行中", submitted: "已提交", succeeded: "完成", failed: "失败", cancelled: "已取消",
};

/** 轮询这一镜的导演出片进度；出完且挂回镜头后通知画布刷新（换上新视频） */
function useDirectorRun(shot: ShotCard, onDone: () => void) {
  const [run, setRun] = useState<DirectorRun | null>(null);
  const [nonce, setNonce] = useState(0);
  const done = useRef(onDone);
  done.current = onDone;
  const runId = shot.director?.run?.blender_job_id;
  const boundId = shot.director?.done?.blender_job_id;
  useEffect(() => {
    if (!runId) { setRun(null); return; }
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const r = (await api.directorRun(shot.id)).run;
        if (!alive) return;
        setRun(r);
        if (r?.done) {
          if (r.blender_job_id !== boundId) done.current();
        } else if (r && !["failed", "cancelled"].includes(r.status)) {
          timer = window.setTimeout(tick, 5000);
        }
      } catch {
        if (alive) timer = window.setTimeout(tick, 10000);
      }
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [shot.id, runId, boundId, nonce]);
  return { run, refresh: () => setNonce(n => n + 1) };
}

/** 创作画布的地址：带上当前小说、章节、这份分镜和这一镜（画布按它找到所在的场次画布并选中） */
/** 应用内跳转（不整页刷新）；⌘/Ctrl/中键点仍按普通链接开新标签 */
function inApp(e: React.MouseEvent<HTMLAnchorElement>, go: () => void) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  go();
}

export default function Inspector({ planId, shot, onStage, onChanged }: Props) {
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  async function run_(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setErr("");
    try {
      await fn();
      onChanged();
    } catch (e) {
      setErr(`${label}失败：${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }

  const { run, refresh } = useDirectorRun(shot, onChanged);

  // 首尾帧图已作废：有视频就取视频自己的第一帧／最后一帧，旧图只在没视频时兜底
  const frame = (label: string, f: ShotCard["first"], at: "start" | "end") => (
    <figure>
      {shot.video_url
        ? <VideoFrame className="frame-video" src={media(shot.video_url)} at={at} />
        : f?.url
          ? <img src={media(f.url)} alt={label} />
          : <div style={{ aspectRatio: "5 / 3", background: "#0b0b0d", borderRadius: 6 }} />}
      <figcaption>
        {label} · {shot.video_url ? "取自视频" : f?.url ? `旧图 · ${STATUS[f?.status ?? "pending"] ?? f?.status}` : "未出"}
      </figcaption>
    </figure>
  );

  const box = shot.director?.run?.box_project_id;
  const stepIdx = run ? Math.max(0, STEPS.findIndex(x => x.key === (run.step === "queued" ? "identity" : run.step))) : -1;

  return (
    <div className="inspector">
      <h3>镜 {shot.order_no} · {shot.shot_size.toUpperCase()} · {(shot.duration_ms / 1000).toFixed(1)}s</h3>
      <div className="desc">{shot.description}</div>
      <div className="frames">
        {frame("首帧", shot.first, "start")}
        {frame("尾帧", shot.last, "end")}
      </div>
      {shot.video_url && <video key={shot.video_url} src={media(shot.video_url)} controls loop muted />}

      <div className="actions">
        <button className="primary" disabled={!!busy}
          title="LLM 按这一镜搭 3D 场景（人物、站位、动作、机位）→ Blender 预演 → 身份首帧（角色库的脸，写实）→ LTX 2.5 按预演出片（带声音），出完自动挂回这一镜（一镜约 8 分钟）"
          onClick={() => run_("出视频", () => api.directorShot(shot.id))}>
          {busy === "出视频" ? "搭景中…" : shot.video_url ? "重出视频" : "出视频"}
        </button>
        {box && <a className="btn" href={hrefFor("box", { box, from: "canvas", shot: shot.id })}
          onClick={e => inApp(e, () => navigate("box", { box, from: "canvas", shot: shot.id }))}
          title="打开这一镜 LLM 搭好的 3D 场景：拖站位、改动作、调机位；左上「← 分镜画布」回来，再点「按调整后的场景重出」">
          在 3D-BOX 里调整
        </a>}
        {box && <button disabled={!!busy} title="用 3D-BOX 里改过的场景重出（不重新搭景、不自动换机位）"
          onClick={() => run_("按场景重出", () => api.directorShot(shot.id, shot.director?.run?.scene_id))}>
          {busy === "按场景重出" ? "提交中…" : "按调整后的场景重出"}
        </button>}
        <button onClick={onStage}
          title={shot.regional ? "摆站位、定机位与运镜（下一次「出视频」时交给 LLM 照着搭景）" : "这一镜是单主体：导演台在这里只定运镜"}>
          导演台
        </button>
        <a className="btn" href={hrefFor("flow", { plan: planId, shot: shot.id })}
          onMouseDown={e => { e.currentTarget.href = hrefFor("flow", { plan: planId, shot: shot.id }); }}
          onClick={e => inApp(e, () => navigate("flow", { plan: planId, shot: shot.id }))}
          title="到这一镜所在的场次画布：定妆照、场次、3D 白模、分镜图都在上面，可以出分镜图、一键出片、连线生成">
          进入创作画布
        </a>
      </div>
      {run && (
        <div className={`director-run ${run.status}`}>
          <div className="steps">
            {STEPS.map((x, i) => (
              <span key={x.key} className={run.done || i < stepIdx ? "ok" : i === stepIdx
                ? (["failed", "cancelled"].includes(run.status) ? "bad" : "now") : ""}>{x.label}</span>
            ))}
          </div>
          <div className="line">
            {run.done
              ? "已挂回这一镜"
              : `${STEPS[stepIdx]?.label ?? run.step} · ${RUN_STATUS[run.status] ?? run.status}`
                + (run.percent != null && !["failed", "cancelled"].includes(run.status) ? ` ${Math.round(run.percent)}%` : "")}
            {run.first_frame_url && <> · <a href={media(run.first_frame_url)} target="_blank" rel="noreferrer">看身份首帧</a></>}
          </div>
          {run.error && <div className="err">{run.error}</div>}
          {run.can_continue && (
            <button disabled={!!busy} title="预演已经渲好，不重新搭景：从失败的那一步接着跑"
              onClick={() => run_("重试", async () => { await api.directorContinue(run.blender_job_id); refresh(); })}>
              {busy === "重试" ? "提交中…" : "从失败处重试"}
            </button>
          )}
        </div>
      )}
      <details className="more">
        <summary>不搭景、只按文字出（快，人物长相没保证）</summary>
        <div className="actions">
          <button disabled={!!busy} title="只跑第一阶段：半分辨率、约一半时间；满意再点「文字出片」从同一结果续跑"
            onClick={() => run_("预览", () => api.video(planId, shot.id, "preview"))}>
            {busy === "预览" ? "提交中…" : "文字预览"}
          </button>
          <button disabled={!!busy} title="LTX 2.5 纯文字出片，带声音；不钉角色库的脸，可能出卡通或别人的脸"
            onClick={() => run_("文字出片", () => api.video(planId, shot.id))}>
            {busy === "文字出片" ? "提交中…" : "文字出片"}
          </button>
        </div>
      </details>
      {err && <div className="err">{err}</div>}

      <div className="note">
        {shot.regional
          ? <>{shot.regional.people} 人同框，站位{shot.regional.source === "stage" ? "由导演在导演台上手摆（出视频时照着搭景）" : "由 LLM 按剧情搭景时摆"}。</>
          : <>单主体镜头（特写或单人）。</>}
        {" "}运镜：{shot.camera.rig?.move ? `${moveLabel(shot.camera.rig.move as MoveKind)}（导演台）` : shot.camera.move ?? "—"}
        {" "}· 运动：{shot.camera.motion_decision ?? shot.camera.motion_kind ?? "—"}
        {shot.dialogue_lines > 0 && <> · 台词 {shot.dialogue_lines} 句</>}
      </div>
    </div>
  );
}
