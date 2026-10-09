/**
 * 快速成片（纳逗式一条龙）：一张人物照片 + 一句想法（+ 服装照片 / 场景图，可选）→ 定妆照 → 分镜图 → 2–4 镜短片。
 * 不需要小说和分镜表；全部本机出。产物按出来的顺序长在画布上（store 的 advanceQuick），这里只收输入、发起任务。
 */
import { useRef, useState } from "react";
import { cv, media } from "../api";
import { freeRef } from "../actions";
import { useCanvas } from "../store";
import { errText, Icon, Spinner, useLatest } from "./Overlays";

type Slot = "person" | "outfit" | "scene";
const SLOT: Record<Slot, { label: string; hint: string }> = {
  person: { label: "人物照片", hint: "一张就够：正脸、光线清楚" },
  outfit: { label: "服装照片（可选）", hint: "有就先出换装定妆照，比如滑雪服" },
  scene: { label: "场景图（可选）", hint: "没有就按想法生成一张空镜" },
};

export function QuickFilm({ onClose }: { onClose: () => void }) {
  const s = useCanvas();
  const latest = useLatest(s);
  const [idea, setIdea] = useState("");
  const [shots, setShots] = useState(3);
  const [mode, setMode] = useState<"one_take" | "cuts">("one_take");
  const [pickTwo, setPickTwo] = useState(true);
  const [imgs, setImgs] = useState<Partial<Record<Slot, { asset_id: string; url: string }>>>({});
  const [uploading, setUploading] = useState<Slot | null>(null);
  const [busy, setBusy] = useState(false);
  const files = useRef<Partial<Record<Slot, HTMLInputElement | null>>>({});

  const upload = async (slot: Slot, f: File) => {
    setUploading(slot);
    try {
      const res = await cv.upload(f);
      setImgs(m => ({ ...m, [slot]: { asset_id: res.asset_id, url: media(res.url) ?? res.url } }));
    } catch (e) {
      latest.current.toast(`上传失败：${errText(e)}`, "err");
    } finally {
      setUploading(null);
    }
  };

  const start = async () => {
    if (!imgs.person || idea.trim().length < 2 || busy) return;
    setBusy(true);
    try {
      const job = await cv.quickStart({
        idea: idea.trim(), person: { asset_id: imgs.person.asset_id },
        outfit: imgs.outfit ? { asset_id: imgs.outfit.asset_id } : null,
        scene: imgs.scene ? { asset_id: imgs.scene.asset_id } : null,
        shots, mode, candidates: pickTwo ? 2 : 1,
      });
      const st = latest.current;
      // 想法放成一个提示词节点，人物照片接在它后面；产物从照片往右长
      const ideaId = st.addNode("text", { ref: freeRef(), title: "快速成片 · 想法", role: "prompt", text: idea.trim() });
      const photoId = st.addNode("image", {
        ref: { kind: "asset", id: imgs.person.asset_id }, title: "人物照片", role: "upload",
        media: { url: imgs.person.url, asset_id: imgs.person.asset_id },
      }, undefined, { source: ideaId, kind: "ref" });
      st.track({ key: `quick:${job.id}`, kind: "quick", remote: job.id, nodeId: photoId, label: "快速成片 · 拆分镜" });
      st.toast("快速成片开始了：拆分镜 → 定妆照 → 分镜图 → 视频，出一样长一样（本机约 15–25 分钟）", "ok");
      onClose();
    } catch (e) {
      latest.current.toast(`没开始：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const minutes = Math.round(4 + shots * (pickTwo ? 3.4 : 1.7) + (mode === "one_take" ? 5 : shots * 4));
  const ready = !!imgs.person && idea.trim().length >= 2;
  return (
    <div className="cv-modal-back" onPointerDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="cv-quick cv-glass" role="dialog" aria-label="快速成片">
        <header>
          <b>快速成片</b>
          <span>一张照片＋一句话 → 定妆照 → 分镜图 → {shots} 镜短片（本机）</span>
          <button type="button" className="cv-quick-x" onClick={onClose} title="关闭"><Icon name="close" size={16} /></button>
        </header>
        <textarea value={idea} onChange={e => setIdea(e.target.value)} rows={3} autoFocus
          placeholder="想法：她第一次滑雪，在坡顶紧张地往下看，鼓起勇气冲下去，摔了一跤又笑着爬起来比了个耶" />
        <div className="cv-quick-slots">
          {(Object.keys(SLOT) as Slot[]).map(k => (
            <button key={k} type="button" className={`cv-quick-slot${imgs[k] ? " is-set" : ""}`} title={SLOT[k].hint}
              onClick={() => files.current[k]?.click()}>
              {imgs[k] ? <img src={imgs[k]!.url} alt="" /> : uploading === k ? <Spinner size={16} /> : <Icon name="upload" size={18} />}
              <span>{SLOT[k].label}</span>
              <input ref={el => { files.current[k] = el; }} type="file" accept="image/*" hidden
                onChange={e => { const f = e.target.files?.[0]; if (f) void upload(k, f); e.target.value = ""; }} />
            </button>
          ))}
        </div>
        <div className="cv-quick-row">
          <span>镜头</span>
          <div className="cv-seg">
            {[2, 3, 4].map(n => <button key={n} type="button" className={shots === n ? "is-on" : ""} onClick={() => setShots(n)}>{n} 镜</button>)}
          </div>
          <span>视频</span>
          <div className="cv-seg">
            <button type="button" className={mode === "one_take" ? "is-on" : ""} onClick={() => setMode("one_take")}
              title="几镜叠在一次 LTX 生成里：每镜分镜图钉在它开始那一帧，镜头之间自然衔接">一次成片</button>
            <button type="button" className={mode === "cuts" ? "is-on" : ""} onClick={() => setMode("cuts")}
              title="逐镜出再拼接：每镜单独钉首帧，硬切">逐镜拼接</button>
          </div>
        </div>
        <label className="cv-run-check">
          <input type="checkbox" checked={pickTwo} onChange={e => setPickTwo(e.target.checked)} />
          每镜分镜图出 2 张，本机视觉模型对着定妆照挑 1 张
        </label>
        <footer>
          <span>约 {minutes} 分钟 · 本机免费</span>
          <button type="button" className="cv-mini-btn is-primary" aria-disabled={!ready || busy}
            title={ready ? "开始" : "先写一句想法、传一张人物照片"} onClick={() => void start()}>
            {busy ? <Spinner size={11} /> : <Icon name="play" size={12} />}开始
          </button>
        </footer>
      </div>
    </div>
  );
}
