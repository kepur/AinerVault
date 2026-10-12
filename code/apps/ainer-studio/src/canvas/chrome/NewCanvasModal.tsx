/**
 * 新建画布弹窗：
 * 1. 🌟 从素材与想法一键生成分镜网络（有限素材到无限分镜 DAG 架构 - 纳逗/钟馗式）：
 *    基础人物照片（+可选服装与场景）+ 故事想法 → 本机 Qwen 35B 拆导演分镜 → buildIdeaGraph 铺设完整 DAG → createCanvas
 * 2. 📄 空白画布：自由放置节点、自由生成
 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cv, media } from "../api";
import { buildIdeaGraph, type IdeaInputs } from "../idea/buildIdeaGraph";
import type { MediaRef } from "../model";
import { useCanvas } from "../store";
import {readCtx} from "../../ctx";
import { errText, host, Icon, Spinner, useLatest } from "./Overlays";

type Tab = "idea" | "blank";
type Slot = "person" | "outfit" | "scene";

interface PresetIdea {
  id: string;
  name: string;
  label: string;
  idea: string;
  shots: number;
  mode: "cuts" | "one_take";
  sheetPreset: "standard" | "quick";
  charName: string;
  personUrl: string;
  outfitUrl?: string;
  sceneUrl?: string;
}

const PRESETS: PresetIdea[] = [
  {
    id: "skiing",
    label: "🎿 滑雪测试 ·《滑雪少女的穿越》",
    name: "滑雪测试",
    idea: "年轻女孩第一次在阿尔卑斯雪山滑雪，在雪道高速疾驰，突然滑雪板失控滑向粉雪堆摔倒，挣扎着坐起身抹掉脸上的雪花，抬头迎着阳光露出灿烂微笑。",
    shots: 3,
    mode: "cuts",
    sheetPreset: "quick",
    charName: "滑雪少女",
    personUrl: "http://localhost:8100/media/44b506a260360b2c628b635fc019f1cfcbcd025350e6745f63a2b7bc314f1180.png",
    outfitUrl: "http://localhost:8100/media/44b506a260360b2c628b635fc019f1cfcbcd025350e6745f63a2b7bc314f1180.png",
    sceneUrl: "http://localhost:8100/media/efc8b461b2f7e11a88ebe35581c6ff791e2ab998563a038d3c9913d5dd2eb12c.png",
  },
  {
    id: "zhongkui",
    label: "🥋 钟馗测试 ·《地府遗忘酒馆》",
    name: "钟馗酒馆",
    idea: "天师钟馗手持宝剑推开遗忘酒馆大门，在酒馆喧闹中疲惫地瘫坐在桌前，猛拍桌子要最强失忆套餐洗去上班的疲劳。",
    shots: 3,
    mode: "cuts",
    sheetPreset: "standard",
    charName: "钟馗",
    personUrl: "http://localhost:8100/media/efc8b461b2f7e11a88ebe35581c6ff791e2ab998563a038d3c9913d5dd2eb12c.png",
  },
  {
    id: "coffee",
    label: "☕ 都市日常 ·《雨天咖啡馆回眸》",
    name: "咖啡馆回眸",
    idea: "细雨朦胧的街头咖啡馆外，短发职场女性收起透明雨伞，转过身向镜头微微一笑，眼神温暖从容。",
    shots: 2,
    mode: "cuts",
    sheetPreset: "quick",
    charName: "苏晴",
    personUrl: "http://localhost:8100/media/44b506a260360b2c628b635fc019f1cfcbcd025350e6745f63a2b7bc314f1180.png",
  },
];

export function NewCanvasModal({ onClose }: { onClose: () => void }) {
  const s = useCanvas();
  const latest = useLatest(s);
  const [tab, setTab] = useState<Tab>("blank");

  /* ── 空白画布表单 ── */
  const [blankTitle, setBlankTitle] = useState("");
  const [attachChapter, setAttachChapter] = useState(readCtx().workspace!=='free');

  /* ── 想法 → DAG 表单 ── */
  const [idea, setIdea] = useState("");
  const [shots, setShots] = useState(PRESETS[0].shots);
  const [mode, setMode] = useState<"cuts" | "one_take">(PRESETS[0].mode);
  const [sheetPreset, setSheetPreset] = useState<"standard" | "quick">(PRESETS[0].sheetPreset);
  const [charName, setCharName] = useState("");

  // 素材槽位：人物（必填）、服装（可选）、场景（可选）
  const [personRef, setPersonRef] = useState<MediaRef>({ url: "" });
  const [outfitRef, setOutfitRef] = useState<MediaRef | null>(null);
  const [sceneRef, setSceneRef] = useState<MediaRef | null>(null);

  const [uploadingSlot, setUploadingSlot] = useState<Slot | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInputs = useRef<Record<Slot, HTMLInputElement | null>>({ person: null, outfit: null, scene: null });

  // Esc 键关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose, busy]);

  const applyPreset = (p: PresetIdea) => {
    setIdea(p.idea);
    setShots(p.shots);
    setMode(p.mode);
    setSheetPreset(p.sheetPreset);
    setCharName(p.charName);
    setPersonRef({ url: p.personUrl });
    setOutfitRef(p.outfitUrl ? { url: p.outfitUrl } : null);
    setSceneRef(p.sceneUrl ? { url: p.sceneUrl } : null);
  };

  const uploadFile = async (slot: Slot, file: File) => {
    setUploadingSlot(slot);
    try {
      const res = await cv.upload(file);
      const ref: MediaRef = { url: media(res.url) ?? res.url, asset_id: res.asset_id };
      if (slot === "person") setPersonRef(ref);
      else if (slot === "outfit") setOutfitRef(ref);
      else setSceneRef(ref);
      latest.current.toast(`素材「${file.name}」已上传`, "ok");
    } catch (e) {
      latest.current.toast(`素材上传失败：${errText(e)}`, "err");
    } finally {
      setUploadingSlot(null);
    }
  };

  /* ── 提交：创建空白画布 ── */
  const submitBlank = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await latest.current.createCanvas({
        title: blankTitle.trim() || "空白画布",
        chapter: attachChapter,
        blank: true,
      });
      onClose();
    } catch (e) {
      latest.current.toast(`新建空白画布失败：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  };

  /* ── 提交：生成分镜网络画布 ── */
  const submitIdea = async () => {
    if (busy) return;
    const trimmedIdea = idea.trim();
    if (!trimmedIdea) {
      latest.current.toast("请填写故事想法描述", "info");
      return;
    }
    if (!personRef?.url) {
      latest.current.toast("请上传或指定基础人物照片", "info");
      return;
    }
    setBusy(true);
    latest.current.toast("正在由本机大模型拆解导演分镜并铺设 DAG 网络…", "info");
    try {
      const plan = await cv.filmPlan({
        idea: trimmedIdea,
        shots,
        has_outfit: !!outfitRef?.url,
        has_scene: !!sceneRef?.url,
      });
      const inputs: IdeaInputs = {
        idea: trimmedIdea,
        person: personRef,
        outfit: outfitRef?.url ? outfitRef : null,
        scene: sceneRef?.url ? sceneRef : null,
        mode,
        sheetPreset,
        name: charName.trim() || undefined,
      };
      const graphDoc = buildIdeaGraph(plan, inputs);
      const title = plan.title || charName.trim() || "故事分镜网络";
      await latest.current.createCanvas({
        title,
        doc: graphDoc,
        chapter: false,
        blank: true,
      });
      latest.current.toast(`分镜网络画布「${title}」创建成功！已建立规划和待生成节点，素材与视频尚未生成`, "ok");
      onClose();
    } catch (e) {
      latest.current.toast(`生成分镜画布失败：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  };

  return createPortal(
    <div className="cv-modal-back" onPointerDown={e => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className="cv-newcanvas-modal cv-glass" role="dialog" aria-label="新建画布">
        {/* 头部标题与 Tab 切换 */}
        <header className="cv-newcanvas-header">
          <div className="cv-newcanvas-tabs">
            <button
              type="button"
              className={`cv-newcanvas-tab${tab === "blank" ? " is-active" : ""}`}
              onClick={() => setTab("blank")}
            >
              <Icon name="plus" size={14} />
              <span>空白画布</span>
            </button>
            <button
              type="button"
              className={`cv-newcanvas-tab${tab === "idea" ? " is-active" : ""}`}
              onClick={() => setTab("idea")}
            >
              <Icon name="sparkle" size={14} />
              <span>AI 辅助规划（可选）</span>
              <span className="cv-new">DAG</span>
            </button>
          </div>
          <button type="button" className="cv-newcanvas-close" onClick={onClose} title="关闭 (Esc)">
            <Icon name="close" size={16} />
          </button>
        </header>

        {tab === "idea" ? (
          <div className="cv-newcanvas-body">
            <div className="cv-newcanvas-tip">
              从提供的<b>有限基础素材</b>（人物照片、可选服装和场景底图）出发，由本机大模型自动拆解摄影机调度与首尾衔接，铺设纳逗/钟馗式 <b>DAG 分镜生成网络</b>。
            </div>

            {/* 快速预设按钮组 */}
            <div className="cv-newcanvas-presets">
              <span className="cv-newcanvas-sublabel">快速预设案例：</span>
              {PRESETS.map(p => (
                <button
                  key={p.id}
                  type="button"
                  className={`cv-mini-btn${idea === p.idea ? " is-active" : ""}`}
                  onClick={() => applyPreset(p)}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {/* 故事想法输入 */}
            <div className="cv-newcanvas-field">
              <label>故事想法 / 剧情描述</label>
              <textarea
                value={idea}
                onChange={e => setIdea(e.target.value)}
                rows={3}
                placeholder="例如：年轻女孩在雪道高速疾驰，突然滑雪板失控滑向雪堆摔倒，坐起身抹掉雪花抬头露出灿烂微笑…"
              />
            </div>

            {/* 镜头设置栏 */}
            <div className="cv-newcanvas-row">
              <div className="cv-newcanvas-field cv-field-sm">
                <label>镜头数量</label>
                <div className="cv-seg">
                  {[2, 3, 4].map(n => (
                    <button
                      key={n}
                      type="button"
                      className={shots === n ? "is-on" : ""}
                      onClick={() => setShots(n)}
                    >
                      {n} 镜
                    </button>
                  ))}
                </div>
              </div>

              <div className="cv-newcanvas-field cv-field-sm">
                <label>出片模式</label>
                <div className="cv-seg">
                  <button
                    type="button"
                    className={mode === "cuts" ? "is-on" : ""}
                    onClick={() => setMode("cuts")}
                    title="逐镜出片后拼接（推荐：第 2 镜接上一镜尾帧，动量自然过渡）"
                  >
                    逐镜拼接 (接尾帧)
                  </button>
                  <button
                    type="button"
                    className={mode === "one_take" ? "is-on" : ""}
                    onClick={() => setMode("one_take")}
                    title="一次成片：多张分镜图钉在单段 LTX 视频内"
                  >
                    一次成片
                  </button>
                </div>
              </div>

              <div className="cv-newcanvas-field cv-field-sm">
                <label>定妆照规格</label>
                <div className="cv-seg">
                  <button
                    type="button"
                    className={sheetPreset === "quick" ? "is-on" : ""}
                    onClick={() => setSheetPreset("quick")}
                    title="快速 4 格：前 / 侧 / 后 / 正脸"
                  >
                    快速 4 格
                  </button>
                  <button
                    type="button"
                    className={sheetPreset === "standard" ? "is-on" : ""}
                    onClick={() => setSheetPreset("standard")}
                    title="标准 16 格：三视图 + 四角度 + 九宫格表情"
                  >
                    标准 16 格
                  </button>
                </div>
              </div>

              <div className="cv-newcanvas-field cv-field-sm">
                <label>角色名称</label>
                <input
                  className="cv-input"
                  value={charName}
                  onChange={e => setCharName(e.target.value)}
                  placeholder="如：滑雪少女"
                />
              </div>
            </div>

            {/* 核心：基础素材槽位 (仅有素材) */}
            <div className="cv-newcanvas-slots-section">
              <label className="cv-newcanvas-sublabel">
                基础素材（仅有素材，所有分镜与视频均基于此生成）：
              </label>
              <div className="cv-newcanvas-slots">
                {/* 槽位 1：人物照片 (必填) */}
                <div className={`cv-newcanvas-slot${personRef?.url ? " is-set" : ""}`}>
                  <div className="cv-newcanvas-slot-head">
                    <b>人物正脸照片</b>
                    <span className="cv-tag ok">必选</span>
                  </div>
                  <div className="cv-newcanvas-slot-preview" onClick={() => fileInputs.current.person?.click()}>
                    {personRef?.url ? (
                      <img src={personRef.url} alt="人物" />
                    ) : uploadingSlot === "person" ? (
                      <Spinner size={20} />
                    ) : (
                      <div className="cv-newcanvas-slot-ph">
                        <Icon name="upload" size={20} />
                        <span>点击上传正脸照片</span>
                      </div>
                    )}
                  </div>
                  <input
                    ref={el => { fileInputs.current.person = el; }}
                    type="file"
                    accept="image/*"
                    hidden
                    onChange={e => {
                      const f = e.target.files?.[0];
                      if (f) void uploadFile("person", f);
                      e.target.value = "";
                    }}
                  />
                  <input
                    className="cv-input cv-slot-url"
                    placeholder="或粘贴图片 URL"
                    value={personRef?.url || ""}
                    onChange={e => setPersonRef({ url: e.target.value.trim() })}
                  />
                </div>

                {/* 槽位 2：服装照片 (可选) */}
                <div className={`cv-newcanvas-slot${outfitRef?.url ? " is-set" : ""}`}>
                  <div className="cv-newcanvas-slot-head">
                    <b>服装参考</b>
                    <span className="cv-tag">可选换装</span>
                  </div>
                  <div className="cv-newcanvas-slot-preview" onClick={() => fileInputs.current.outfit?.click()}>
                    {outfitRef?.url ? (
                      <img src={outfitRef.url} alt="服装" />
                    ) : uploadingSlot === "outfit" ? (
                      <Spinner size={20} />
                    ) : (
                      <div className="cv-newcanvas-slot-ph">
                        <Icon name="upload" size={20} />
                        <span>如滑雪服、道袍等</span>
                      </div>
                    )}
                  </div>
                  <input
                    ref={el => { fileInputs.current.outfit = el; }}
                    type="file"
                    accept="image/*"
                    hidden
                    onChange={e => {
                      const f = e.target.files?.[0];
                      if (f) void uploadFile("outfit", f);
                      e.target.value = "";
                    }}
                  />
                  <div className="cv-slot-actions">
                    <input
                      className="cv-input cv-slot-url"
                      placeholder="或粘贴服装图 URL"
                      value={outfitRef?.url || ""}
                      onChange={e => setOutfitRef(e.target.value.trim() ? { url: e.target.value.trim() } : null)}
                    />
                    {outfitRef?.url && (
                      <button type="button" className="cv-mini-btn" onClick={() => setOutfitRef(null)}>
                        清除
                      </button>
                    )}
                  </div>
                </div>

                {/* 槽位 3：场景底图 (可选) */}
                <div className={`cv-newcanvas-slot${sceneRef?.url ? " is-set" : ""}`}>
                  <div className="cv-newcanvas-slot-head">
                    <b>场景底图</b>
                    <span className="cv-tag">可选底图</span>
                  </div>
                  <div className="cv-newcanvas-slot-preview" onClick={() => fileInputs.current.scene?.click()}>
                    {sceneRef?.url ? (
                      <img src={sceneRef.url} alt="场景" />
                    ) : uploadingSlot === "scene" ? (
                      <Spinner size={20} />
                    ) : (
                      <div className="cv-newcanvas-slot-ph">
                        <Icon name="upload" size={20} />
                        <span>不填则按场景生成空镜</span>
                      </div>
                    )}
                  </div>
                  <input
                    ref={el => { fileInputs.current.scene = el; }}
                    type="file"
                    accept="image/*"
                    hidden
                    onChange={e => {
                      const f = e.target.files?.[0];
                      if (f) void uploadFile("scene", f);
                      e.target.value = "";
                    }}
                  />
                  <div className="cv-slot-actions">
                    <input
                      className="cv-input cv-slot-url"
                      placeholder="或粘贴场景图 URL"
                      value={sceneRef?.url || ""}
                      onChange={e => setSceneRef(e.target.value.trim() ? { url: e.target.value.trim() } : null)}
                    />
                    {sceneRef?.url && (
                      <button type="button" className="cv-mini-btn" onClick={() => setSceneRef(null)}>
                        清除
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* 底部按钮栏 */}
            <footer className="cv-newcanvas-footer">
              <div className="cv-newcanvas-desc">
                生成的网络结构：素材节点 $\to$ 定妆照板 $\to$ 导演分镜表 $\to$ 分镜图组（{shots} 镜） $\to$ LTX-2.5 视频节点 $\to$ 成片拼接
              </div>
              <div className="cv-newcanvas-actions">
                <button type="button" className="cv-btn" onClick={onClose} disabled={busy}>
                  取消
                </button>
                <button
                  type="button"
                  className="cv-btn is-primary cv-submit-dag-btn"
                  onClick={submitIdea}
                  disabled={busy || !idea.trim() || !personRef?.url}
                >
                  {busy ? <Spinner size={13} /> : <Icon name="sparkle" size={14} />}
                  <span>✨ 生成分镜网络画布</span>
                </button>
              </div>
            </footer>
          </div>
        ) : (
          /* 空白画布 Tab */
          <div className="cv-newcanvas-body">
            <div className="cv-newcanvas-tip">
              创建一张完全自由的空白画布。适合用于相册、旅拍设计，或手动添加文本、图片与视频生成节点自由连线创作。
            </div>
            <div className="cv-newcanvas-field">
              <label>画布名称</label>
              <input
                className="cv-input"
                autoFocus
                placeholder="例如：滑雪自由创作板、精修分镜"
                value={blankTitle}
                onChange={e => setBlankTitle(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") void submitBlank(); }}
              />
            </div>
            {s.chapterId && (
              <label className="cv-check" style={{ marginTop: 8 }}>
                <input
                  type="checkbox"
                  checked={attachChapter}
                  disabled={readCtx().workspace!=='free'}
                  onChange={e => setAttachChapter(e.target.checked)}
                />
                <span>关联到当前章节（可在该章节画布列表中随时切换）</span>
              </label>
            )}
            <footer className="cv-newcanvas-footer" style={{ marginTop: 24 }}>
              <div />
              <div className="cv-newcanvas-actions">
                <button type="button" className="cv-btn" onClick={onClose} disabled={busy}>
                  取消
                </button>
                <button
                  type="button"
                  className="cv-btn is-primary"
                  onClick={submitBlank}
                  disabled={busy}
                >
                  {busy ? <Spinner size={13} /> : <Icon name="plus" size={14} />}
                  <span>创建空白画布</span>
                </button>
              </div>
            </footer>
          </div>
        )}
      </div>
    </div>,
    host(),
  );
}
