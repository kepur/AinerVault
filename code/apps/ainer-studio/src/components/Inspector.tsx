import { useState } from "react";
import { api, media } from "../api";
import type { ShotCard } from "../types";
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

export default function Inspector({ planId, shot, onStage, onChanged }: Props) {
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  async function run(label: string, fn: () => Promise<unknown>) {
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

  const frame = (label: string, f: ShotCard["first"]) => (
    <figure>
      {f?.url ? <img src={media(f.url)} alt={label} /> : <div style={{ aspectRatio: "5 / 3", background: "#0b0b0d", borderRadius: 6 }} />}
      <figcaption>
        {label} · {STATUS[f?.status ?? "pending"] ?? f?.status}
        {f?.url && f.stale ? " · 旧图（制作单变了）" : ""}
      </figcaption>
    </figure>
  );

  return (
    <div className="inspector">
      <h3>镜 {shot.order_no} · {shot.shot_size.toUpperCase()} · {(shot.duration_ms / 1000).toFixed(1)}s</h3>
      <div className="desc">{shot.description}</div>
      <div className="frames">
        {frame("首帧", shot.first)}
        {frame("尾帧", shot.last)}
      </div>
      {shot.video_url && <video key={shot.video_url} src={media(shot.video_url)} controls loop muted />}

      <div className="actions">
        <button className="primary" onClick={onStage}
          title={shot.regional ? "摆站位、定机位与运镜" : "这一镜首帧走单主体路径：导演台在这里只定运镜"}>
          3D 导演台
        </button>
        <button disabled={!!busy} onClick={() => run("重出首帧", () => api.firstFrame(planId, shot.id))}>
          {busy === "重出首帧" ? "提交中…" : "重出首帧"}
        </button>
        <button disabled={!!busy || !shot.first?.url} onClick={() => run("出尾帧", () => api.lastFrame(planId, shot.id))}>
          出尾帧
        </button>
        <button disabled={!!busy || !shot.last?.url} onClick={() => run("出视频", () => api.video(planId, shot.id))}>
          出视频
        </button>
      </div>
      {err && <div className="err">{err}</div>}

      <div className="note">
        {shot.regional
          ? <>这一镜是<b>分区身份</b>出的图：{shot.regional.people} 个人各自带着自己的参考脸，
              站位{shot.regional.source === "stage" ? "由导演在 3D 台上手摆" : "按表演单自动摆位"}。</>
          : <>这一镜走单主体路径（特写或单人）。</>}
        {" "}运镜：{shot.camera.rig?.move ? `${moveLabel(shot.camera.rig.move as MoveKind)}（导演台）` : shot.camera.move ?? "—"}
        {" "}· 运动：{shot.camera.motion_decision ?? shot.camera.motion_kind ?? "—"}
        {shot.dialogue_lines > 0 && <> · 台词 {shot.dialogue_lines} 句</>}
      </div>
    </div>
  );
}
