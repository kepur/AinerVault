/**
 * 顶栏：左边品牌 + 面包屑（小说 › 章节 › 分镜 vN，每段都能点开换），右边保存状态、任务、整理、导出、视图。
 * 整条是透明的、只有胶囊接鼠标（pointer-events），画布在它下面照样能拖。
 */
import { navigate, readCtx } from "../../ctx";
import { comicSources } from "../comic";
import { useReactFlow } from "@xyflow/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { freeRef, taskOpen } from "../actions";
import { cv, HttpError, media } from "../api";
import type { SaveState } from "../contract";
import {
  DOC_SCHEMA, isDerived, type CanvasDoc, type CanvasMeta, type CEdge, type CNode, type DocNode, type RunItem, type RunOptions,
  type RunState, type TaskKind, type TrackedTask,
} from "../model";
import { useCanvas } from "../store";
import { errText, Icon, MenuList, Popover, Spinner, useLatest, type MenuItem } from "./Overlays";
import { NewCanvasModal } from "./NewCanvasModal";
import {ShotManager} from './ShotManager';

const SAVE: Record<SaveState, { text: string; tone: string; title: string } | null> = {
  idle: null,
  saving: { text: "保存中…", tone: "", title: "改动正在存到后端" },
  saved: { text: "已保存", tone: "ok", title: "画布布局已存到后端（只存位置和引用，内容每次现取）" },
  local: {
    text: "仅存本机", tone: "warn",
    title: "后端还没有画布接口：布局存在这台电脑的浏览器里，换电脑或清缓存就没了",
  },
  conflict: { text: "有冲突", tone: "err", title: "画布在别处被改过：点一下丢掉这里的改动、载入远端" },
  error: { text: "保存失败", tone: "err", title: "没存上：看看后端是否在线；继续改动会再试" },
};

const KIND_CN: Record<TaskKind, string> = {
  comic: "漫剧制作", director: "导演出片", ltx25: "文字出片", gen: "生成", blender: "渲控制素材", box_agent: "搭景", run: "一键出片", quick: "快速成片",
};
const STATUS_CN: Record<TrackedTask["status"], string> = {
  queued: "排队中", running: "进行中", succeeded: "完成", failed: "失败", cancelled: "已取消",
};

/** 面包屑的一段：点开是可筛选的列表（footer：列表下面的操作，比如「新建画布」） */
function Crumb({ label, title, items, empty, footer }: {
  label: ReactNode;
  title: string;
  items: { id: string; text: string; hint?: string; active: boolean; onPick: () => void }[];
  empty: string;
  footer?: (close: () => void) => ReactNode;
}) {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [q, setQ] = useState("");
  const shown = q ? items.filter(i => i.text.toLowerCase().includes(q.toLowerCase())) : items;
  return (
    <>
      <button type="button" className={`cv-crumb${el ? " is-open" : ""}`} title={title}
        onClick={e => { setQ(""); setEl(el ? null : e.currentTarget); }}>
        <span>{label}</span><Icon name="down" size={12} />
      </button>
      {el && (
        <Popover anchor={el} onClose={() => setEl(null)} className="cv-crumb-pop">
          {items.length > 10 && (
            <input className="cv-input" autoFocus placeholder="筛选…" value={q} onChange={e => setQ(e.target.value)} />
          )}
          <MenuList empty={empty} onPicked={() => setEl(null)}
            items={shown.map<MenuItem>(i => ({ id: i.id, label: i.text, hint: i.hint, active: i.active, onPick: i.onPick }))} />
          {footer?.(() => setEl(null))}
        </Popover>
      )}
    </>
  );
}

/** 导出用的文档：和 store 存后端的同一个形状（派生节点只留引用和视图状态，铁律 1） */
function exportDoc(nodes: CNode[], edges: CEdge[], viewport: CanvasDoc["viewport"]): CanvasDoc {
  const node = (n: CNode): DocNode => {
    const d = n.data;
    let data: DocNode["data"];
    if (isDerived(d.ref)) {
      data = { ref: d.ref, title: d.title };
      if (d.role) data.role = d.role;
      if (d.camera !== undefined) data.camera = d.camera;
      if (d.pinned) data.pinned = true;
      if (d.live) data.live = true;
    } else {
      data = { ...d };
      delete (data as Record<string, unknown>).orphan;
      if(d.comic){delete data.comicLive;delete data.media;delete data.text;}
    }
    return { id: n.id, type: n.type ?? "text", position: { x: Math.round(n.position.x), y: Math.round(n.position.y) }, data };
  };
  return {
    schema: DOC_SCHEMA,
    viewport,
    nodes: nodes.map(node),
    edges: edges.filter(e => !e.data?.derived).map(e => ({
      id: e.id, source: e.source, target: e.target,
      sourceHandle: e.sourceHandle ?? null, targetHandle: e.targetHandle ?? null,
      data: e.data ?? { kind: "ref" },
    })),
  };
}

const KIND_TAG: Record<CanvasMeta["kind"], string> = { plan: "总览", scene: "场次", custom: "自建" };

function boardLabel(b: CanvasMeta): string {
  return `${KIND_TAG[b.kind]} · ${b.title}${b.stale ? "（分镜已重编，对不上了）" : ""}`;
}

/** 画布列表下面：把选中的镜头单独建一张、新建空白画布、重新按场次分 */
function BoardActions({ close, onOpenNew }: { close: () => void; onOpenNew?: () => void }) {
  const s = useCanvas();
  const latest = useLatest(s);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState("");
  const shotIds = s.nodes.filter(n => n.selected && n.data.ref.kind === "shot").map(n => n.data.ref.id);
  const create = async (withShots: boolean) => {
    setBusy(withShots ? "shots" : "blank");
    try {
      const st = latest.current;
      if (withShots) {
        const b = await cv.canvasCreate({
          title: title.trim() || `精修 · ${shotIds.length} 镜`,
          plan_id: st.planId, chapter_id: st.chapterId || null, novel_id: st.novelId || null,
          shot_ids: shotIds,
        });
        await st.reloadBoards();
        st.pick.setBoard(b.id);
      } else {
        await st.createCanvas({ title: title.trim() || "空白画布", blank: true, chapter: false });
      }
      close();
    } catch (e) {
      latest.current.toast(`新建画布失败：${errText(e)}`, "err");
    } finally {
      setBusy("");
    }
  };
  const split = async () => {
    setBusy("split");
    try {
      await cv.canvasSplit(latest.current.planId);
      await latest.current.reloadBoards();
      latest.current.toast("已按场次重新分好（已有画布的布局保留）", "ok");
    } catch (e) {
      latest.current.toast(`重新分画布失败：${errText(e)}`, "err");
    } finally {
      setBusy("");
    }
  };
  return (
    <div className="cv-board-actions">
      <input className="cv-input" placeholder="新画布名字（可不填）" value={title} onChange={e => setTitle(e.target.value)} />
      <div className="cv-board-actions__row">
        <button type="button" className="cv-mini-btn" aria-disabled={!shotIds.length || !!busy}
          title={shotIds.length ? `把选中的 ${shotIds.length} 个镜头单独建一张画布（精修、单独出片）` : "先在画布上选中几个镜头（Shift 拖框选）"}
          onClick={() => { if (shotIds.length && !busy) void create(true); }}>
          {busy === "shots" ? <Spinner size={11} /> : <Icon name="plus" size={13} />}选中的 {shotIds.length} 镜
        </button>
        <button type="button" className="cv-mini-btn" aria-disabled={!!busy}
          title="不挂分镜的空白画布：旅拍、相册、自己的素材，用生成面板出图出视频"
          onClick={() => { if (!busy) void create(false); }}>
          {busy === "blank" ? <Spinner size={11} /> : <Icon name="plus" size={13} />}空白画布
        </button>
        {onOpenNew && (
          <button type="button" className="cv-mini-btn"
            title="从有限素材与故事想法一键生成分镜网络（DAG 架构）"
            onClick={() => { close(); onOpenNew(); }}>
            <Icon name="sparkle" size={13} />想法生分镜
          </button>
        )}
        <button type="button" className="cv-mini-btn" aria-disabled={!s.planId || !!busy}
          title="分镜重编译之后、或想重新切段时：按场次重新分（24 镜以上的场次切段），已有画布按场次认回、布局不丢"
          onClick={() => { if (s.planId && !busy) void split(); }}>
          {busy === "split" ? <Spinner size={11} /> : <Icon name="refresh" size={13} />}重新分
        </button>
      </div>
    </div>
  );
}

const STEP_CN: Record<string, string> = { previs: "Blender 预演", identity: "身份首帧", queued: "排队", final: "LTX 2.5 成片", chain: "挂回" };
/** 一镜大约几分钟：关键帧（FLUX 约半分钟）＋ LTX 768×448 约 3–4 分钟；白模多一次 LLM 搭景、Blender 预演、身份首帧 */
function perShotMin(o: RunOptions): number {
  if (o.method === "director") return o.profile === "fast" ? 6 : 10;
  if (o.engine === "cloud") return 3;
  return o.profile === "fast" ? 4 : 7;
}
const FLOW_TEXT: Record<string, string> = {
  "keyframe:local": "导演审片（谁是谁、首帧描述、运动描述）→ 补配音 → 本章定妆照＋场景图 → FLUX.2 画关键帧（出 2 张挑 1）→ LTX 2.5 钉住关键帧出片 → 挂回镜头",
  "keyframe:cloud": "补配音 → 本章定妆照＋场景图 → 通义图像编辑画关键帧 → 万相图生视频 → 挂回镜头（付费）",
  director: "补配音 → LLM 搭白模/运镜 → Blender 预演 → 身份首帧 → LTX 2.5 按白模控制出片 → 挂回镜头",
};

function itemText(i: RunItem & { director?: { step: string; percent: number | null } | null }): string {
  if (i.status === "succeeded") return i.stopped === "frame" ? "分镜图好了（审过再出视频）" : "已挂回";
  if (i.status === "failed") return i.error || "失败";
  if (i.status === "skipped") return "跳过";
  if (i.status === "pending") return "排队";
  if (i.step === "audio") return "按角色音色配音中";
  if (i.step === "frame") return "画关键帧（定妆照＋场景图）";
  if (i.step === "video") return i.frame === "reused" ? "沿用关键帧，出视频中" : "从关键帧出视频";
  const d = i.director;
  return d ? `${STEP_CN[d.step] ?? d.step}${d.percent != null ? ` ${Math.round(d.percent)}%` : ""}` : "LLM 搭白模、定运镜";
}

/**
 * 一键出片：画布范围内的镜头按顺序 补配音 → LLM 搭白模/运镜 → Blender 预演 → 人物卡身份首帧 → LTX 2.5 → 挂回。
 * 后端一镜一镜排队（一块 GPU），出完一镜挂一镜，分镜画布上同步看得到。
 */
function RunPill() {
  const s = useCanvas();
  const latest = useLatest(s);
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [opts, setOpts] = useState<RunOptions>({
    method: "keyframe", engine: "local", profile: "fast", audio: "auto", only_missing: true, reuse_scene: true, reuse_frames: true,
    stop_after: "frame", review: true, candidates: 2,
  });
  const [onlySelected, setOnlySelected] = useState(true);
  const b = s.board;
  if (!b?.plan_id) return null;
  const run = s.run;
  const active = !!run && (run.status === "queued" || run.status === "running");
  // 画布上选中了镜头：默认只出这几镜
  const picked = s.nodes.filter(x => x.selected && x.data.ref.kind === "shot").map(x => x.data.ref.id);
  const usePicked = onlySelected && picked.length > 0;
  const total = usePicked ? picked.length : b.shots ?? 0;
  const n = usePicked ? picked.length : opts.only_missing ? Math.max(0, total - (b.videos ?? 0)) : total;
  const done = run ? run.summary.succeeded + run.summary.failed : 0;

  const start = async () => {
    setBusy(true);
    try {
      const st = await latest.current.startRun(usePicked ? { ...opts, shot_ids: picked, only_missing: false } : opts);
      latest.current.toast(`一键出片开始：${st.summary.total} 镜排队${st.queued_behind ? `（前面还有 ${st.queued_behind} 个工作流）` : ""}`, "ok");
    } catch (e) {
      const d = e instanceof HttpError ? (e.detail as { message?: string } | undefined) : undefined;
      latest.current.toast(d?.message || `没开始：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const cur = run?.summary.current;
  return (
    <>
      <button type="button" className={`cv-pill cv-glass cv-run${active ? " is-busy" : ""}${el ? " is-open" : ""}`}
        title="画布范围内的镜头一键出片：补配音 → 关键帧 → 视频 → 挂回（也可以选 3D 白模控制）"
        onClick={e => setEl(el ? null : e.currentTarget)}>
        {active ? <Spinner size={12} /> : <Icon name="play" size={13} />}
        {active ? `出片中 ${done}/${run!.summary.total}` : "一键出片"}
      </button>
      {el && (
        <Popover anchor={el} placement="bottom-end" onClose={() => setEl(null)} className="cv-runpop" role="dialog">
          <div className="cv-pop-title">一键出片<span>{b.title}</span></div>
          {active && run ? (
            <div className="cv-run-live">
              <div className="cv-run-bar"><i style={{ width: `${run.summary.total ? (done / run.summary.total) * 100 : 0}%` }} /></div>
              <div className="cv-run-meta">
                {run.options.method === "director" ? "3D 白模" : run.options.engine === "cloud" ? "关键帧 · 云端" : "关键帧 · 本机"} ·{" "}
                {run.profile === "fast" ? "快速 768×448" : "高清 1024×576"} · 已完成 {run.summary.succeeded}
                {run.summary.failed ? ` · 失败 ${run.summary.failed}` : ""} · 共 {run.summary.total} 镜
              </div>
              {cur && <div className="cv-run-cur">镜 {cur.order_no}：{itemText(cur)}</div>}
              <RunItems run={run} />
              <button type="button" className="cv-mini-btn is-danger" onClick={() => void latest.current.cancelRun()}>
                <Icon name="close" size={12} />停止（正在出的这一镜也取消）
              </button>
            </div>
          ) : (
            <div className="cv-run-form">
              <label className="cv-run-row"><span>方案</span>
                <span className="cv-seg cv-seg-sm">
                  <button type="button" className={opts.method === "keyframe" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, method: "keyframe" }))}
                    title="借鉴纳逗：本章定妆照＋场景图先画出关键帧（人像、服装、场景都定死），视频模型钉住它只管动。最快，默认">关键帧</button>
                  <button type="button" className={opts.method === "director" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, method: "director" }))}
                    title="LLM 搭 3D 白模定站位和运镜，按白模控制出片。站位、机位必须严格照预演走的镜头用（打斗、复杂调度）；台词音色保证不了">3D 白模</button>
                </span>
              </label>
              {opts.method === "keyframe" && (
                <label className="cv-run-row"><span>引擎</span>
                  <span className="cv-seg cv-seg-sm">
                    <button type="button" className={opts.engine === "local" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, engine: "local" }))}
                      title="本机：FLUX.2-klein 画关键帧 → LTX 2.5 出片，免费">本机</button>
                    <button type="button" className={opts.engine === "cloud" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, engine: "cloud" }))}
                      title="云端：通义图像编辑 Max 画关键帧（吃多张参考图）→ 万相 2.7 图生视频。付费：后台要给这两个用途标好计费并批准">云端</button>
                  </span>
                </label>
              )}
              <label className="cv-run-row"><span>出到</span>
                <span className="cv-seg cv-seg-sm">
                  <button type="button" className={opts.stop_after === "frame" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, stop_after: "frame" }))}
                    title="先只出分镜图（关键帧），在画布上逐镜审过、不对的重画，再出视频。推荐">分镜图（先审）</button>
                  <button type="button" className={opts.stop_after === "video" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, stop_after: "video" }))}
                    title="一路出到视频（已经画好的关键帧会沿用）">视频</button>
                </span>
              </label>
              <label className="cv-run-row"><span>档位</span>
                <span className="cv-seg cv-seg-sm">
                  <button type="button" className={opts.profile === "fast" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, profile: "fast" }))}
                    title="768×448（LTX 2.5 最快那档，Q8 流式权重）：一镜约 6 分钟">快速 768×448</button>
                  <button type="button" className={opts.profile === "hd" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, profile: "hd" }))}
                    title="1024×576：一镜约 10 分钟">高清 1024×576</button>
                </span>
              </label>
              <label className="cv-run-row"><span>声音</span>
                <span className="cv-seg cv-seg-sm">
                  <button type="button" className={opts.audio === "auto" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, audio: "auto" }))}
                    title="有台词：先按角色库定的音色配音，再用配音驱动口型（音色前后一致）；没台词：现场生成环境声">角色配音</button>
                  <button type="button" className={opts.audio === "generate" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, audio: "generate" }))}
                    title="模型现场生成声音（脚步、环境声；台词音色不保证一致）">现场生成</button>
                  <button type="button" className={opts.audio === "none" ? "is-on" : ""} onClick={() => setOpts(o => ({ ...o, audio: "none" }))}
                    title="只出画面">不要声音</button>
                </span>
              </label>
              {picked.length > 0 && (
                <label className="cv-run-check">
                  <input type="checkbox" checked={onlySelected} onChange={e => setOnlySelected(e.target.checked)} />
                  只出画布上选中的 {picked.length} 镜
                </label>
              )}
              {!usePicked && (
                <label className="cv-run-check">
                  <input type="checkbox" checked={opts.only_missing} onChange={e => setOpts(o => ({ ...o, only_missing: e.target.checked }))} />
                  只补还没出片的（关掉 = 范围内全部重出）
                </label>
              )}
              {opts.method === "director" ? (
                <label className="cv-run-check">
                  <input type="checkbox" checked={opts.reuse_scene} onChange={e => setOpts(o => ({ ...o, reuse_scene: e.target.checked }))} />
                  沿用 3D-BOX 里调过的白模（关掉 = LLM 重新搭景、定运镜）
                </label>
              ) : (
                <>
                  <label className="cv-run-check">
                    <input type="checkbox" checked={opts.reuse_frames} onChange={e => setOpts(o => ({ ...o, reuse_frames: e.target.checked }))} />
                    已经画好的关键帧沿用（关掉 = 重画；分镜流水线的旧首帧一律重画）
                  </label>
                  <label className="cv-run-check" title="本机 LM Studio 把这场戏的镜头连起来看一遍：谁是谁（领头少年到底是谁）、去掉重复镜、把每镜拆成首帧静态描述和 LTX 运动描述。不改分镜原文">
                    <input type="checkbox" checked={opts.review !== false} onChange={e => setOpts(o => ({ ...o, review: e.target.checked }))} />
                    出图前导演审片（本机，约 1–2 分钟）
                  </label>
                  <label className="cv-run-check" title="每镜出几张候选，本机视觉模型对着定妆照挑：人数对、没多出手脚、脸和衣服对得上。出图时间按张数翻倍">
                    <input type="checkbox" checked={(opts.candidates ?? 2) > 1} onChange={e => setOpts(o => ({ ...o, candidates: e.target.checked ? 2 : 1 }))} />
                    每镜出 2 张，视觉模型挑 1 张
                  </label>
                </>
              )}
              <div className="cv-run-flow">{FLOW_TEXT[opts.method === "director" ? "director" : `keyframe:${opts.engine}`]}</div>
              <div className="cv-run-foot">
                <span>{n} 镜 · 约 {opts.stop_after === "frame"
                  // 实测本机一张关键帧 85–135 秒；出 2 张挑 1 翻倍
                  ? Math.max(1, Math.round(n * (opts.method === "director" ? 3 : 1.7 * Math.max(1, opts.candidates ?? 2))))
                  : n * perShotMin(opts)} 分钟 · {opts.method === "keyframe" && opts.engine === "cloud" ? "云端付费" : "本机免费"}</span>
                <button type="button" className="cv-mini-btn is-primary" aria-disabled={!n || busy}
                  title={n ? "开始（一镜一镜排队，出完一镜挂一镜）" : "范围内的镜头都出过片了"}
                  onClick={() => { if (n && !busy) void start(); }}>
                  {busy ? <Spinner size={11} /> : <Icon name="play" size={12} />}开始
                </button>
              </div>
              {run && <LastRun run={run} />}
            </div>
          )}
        </Popover>
      )}
    </>
  );
}

/**
 * 执行画布（DAG 生成）：按配方拓扑顺序在服务端生成定妆照、分镜图与视频。
 * 用于自建画布、想法一键生成分镜网络（DAG）等带有配方的节点。
 */
function ExecutePill() {
  const s = useCanvas();
  const latest = useLatest(s);
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [force, setForce] = useState(false);
  const [onlySelected, setOnlySelected] = useState(false);

  const recipeNodes = s.nodes.filter(n => !!n.data.recipe);
  if (!recipeNodes.length) return null;

  const ex = s.exec;
  const active = !!ex && (ex.status === "queued" || ex.status === "running");
  const selectedRunnables = s.nodes.filter(n => n.selected && !!n.data.recipe);
  const done = ex?.done ?? 0;
  const total = ex?.total ?? recipeNodes.length;

  const start = async () => {
    setBusy(true);
    try {
      await latest.current.execute({
        force,
        node_ids: onlySelected && selectedRunnables.length ? selectedRunnables.map(n => n.id) : undefined,
      });
      latest.current.toast("画布开始执行：按依赖顺序自动生成各节点", "ok");
      setEl(null);
    } catch {
      // toast is already handled inside store.execute
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    try {
      await latest.current.stopExecute();
      setEl(null);
    } catch {
      // toast handled
    }
  };

  const runningNode = ex?.running ? s.nodes.find(n => n.id === ex.running) : null;

  return (
    <>
      <button
        type="button"
        className={`cv-pill cv-glass cv-exec-btn${active ? " is-busy" : ""}${el ? " is-open" : ""}`}
        title="执行画布（DAG 生成）：按配方拓扑顺序在服务端生成定妆照、分镜图与视频"
        onClick={e => setEl(el ? null : e.currentTarget)}
      >
        {active ? <Spinner size={12} /> : <Icon name="sparkle" size={13} />}
        {active ? `执行中 ${done}/${total}` : "✦ 执行画布"}
      </button>
      {el && (
        <Popover anchor={el} placement="bottom-end" onClose={() => setEl(null)} className="cv-runpop" role="dialog">
          <div className="cv-pop-title">
            执行画布 (DAG 生成)<span>{s.board?.title || "当前画布"}</span>
          </div>
          {active && ex ? (
            <div className="cv-run-live">
              <div className="cv-run-bar">
                <i style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
              </div>
              <div className="cv-run-meta">
                状态：{ex.status === "running" ? "生成中" : "排队中"} · 已完成 {done} / {total}
                {ex.failed ? ` · 失败 ${ex.failed}` : ""}
              </div>
              {runningNode && (
                <div className="cv-run-cur">
                  正在生成：{runningNode.data.title || runningNode.id}
                </div>
              )}
              <button type="button" className="cv-mini-btn is-danger" onClick={stop}>
                <Icon name="close" size={12} />停止执行
              </button>
            </div>
          ) : (
            <div className="cv-run-form">
              <div className="cv-run-flow">
                按配方拓扑依赖（定妆照 → 换装 → 场景板 → 导演分镜 → 逐镜视频 → 成片拼接）在服务端按序生成。
              </div>
              <div style={{ fontSize: 12, color: "var(--cv-muted)", marginTop: 6, marginBottom: 8 }}>
                共 <b>{recipeNodes.length}</b> 个生成节点。
              </div>
              <label className="cv-run-check" style={{ marginBottom: 6 }}>
                <input type="checkbox" checked={force} onChange={e => setForce(e.target.checked)} />
                强制全部重新生成（跳过已有产物）
              </label>
              {selectedRunnables.length > 0 && (
                <label className="cv-run-check" style={{ marginBottom: 6 }}>
                  <input type="checkbox" checked={onlySelected} onChange={e => setOnlySelected(e.target.checked)} />
                  仅执行选中的 {selectedRunnables.length} 个节点
                </label>
              )}
              <div className="cv-run-foot" style={{ marginTop: 12 }}>
                <span>本机免费出片</span>
                <button
                  type="button"
                  className="cv-mini-btn is-primary"
                  disabled={busy}
                  onClick={start}
                >
                  {busy ? <Spinner size={11} /> : <Icon name="play" size={12} />}开始执行
                </button>
              </div>
            </div>
          )}
        </Popover>
      )}
    </>
  );
}

function RunItems({ run }: { run: RunState }) {
  const s = useCanvas();
  return (
    <div className="cv-run-items">
      {run.items.map(i => (
        <button key={i.shot_id} type="button" className={`cv-run-item st-${i.status}`}
          title={i.note || i.error || undefined}
          onClick={() => { s.focusNode(`shot:${i.shot_id}`); s.select(`shot:${i.shot_id}`); }}>
          <span className="cv-task-dot" />
          <b>镜 {i.order_no}</b>
          <span>{itemText(i.status === "running" && run.summary.current?.shot_id === i.shot_id ? run.summary.current : i)}</span>
          {i.audio === "drive" && <em title="台词按角色音色配音，口型跟着配音走">角色配音</em>}
        </button>
      ))}
    </div>
  );
}

function LastRun({ run }: { run: RunState }) {
  const failed = run.items.filter(i => i.status === "failed");
  const rv = (run.options as { review_result?: ReviewResult }).review_result;
  const picks = run.items.filter(i => i.pick && i.pick.of > 1 && i.pick.best > 0);
  return (
    <div className="cv-run-last">
      上次：{run.status === "cancelled" ? "已停止" : run.status === "succeeded" ? "全部完成" : "有失败"} · 成功 {run.summary.succeeded} 镜
      {failed.length > 0 && <> · 失败 {failed.length} 镜</>}
      {failed.slice(0, 4).map(i => <div key={i.shot_id} className="cv-run-err">镜 {i.order_no}：{i.error}</div>)}
      {rv && (
        <div className="cv-run-review">
          导演审片：审了 {rv.reviewed} 镜{rv.errors.length ? `，${rv.errors.length} 批没审成（按分镜原文出）` : ""}
          {rv.continuity.slice(0, 2).map((c, k) => <div key={`c${k}`}>· {c}</div>)}
          {rv.issues.slice(0, 5).map(x => <div key={x.order_no}>镜 {x.order_no}：{x.issues.join("；")}</div>)}
        </div>
      )}
      {picks.length > 0 && <div className="cv-run-review">挑图换掉了第一张：{picks.map(i => `镜 ${i.order_no}`).join("、")}</div>}
    </div>
  );
}

interface ReviewResult {
  reviewed: number; skipped: number; errors: string[]; continuity: string[];
  issues: { order_no: number; issues: string[] }[];
}

/** 合成章节视频：整章时间线（有视频用视频，没有用首尾帧溶解）导成一支 mp4，就是分镜画布那条线 */
function FilmButton() {
  const s = useCanvas();
  const latest = useLatest(s);
  const [busy, setBusy] = useState(false);
  if (!s.planId) return null;
  const go = async () => {
    setBusy(true);
    latest.current.toast("正在合成章节视频（整章时间线，可能要几分钟）…", "info");
    try {
      const res = await cv.film(latest.current.planId);
      const url = res.url.startsWith("data:") ? res.url : media(res.url) ?? res.url;
      latest.current.openOverlay({ kind: "media", url, video: true });
      latest.current.toast(
        `章节视频合成好了：${res.shots} 镜有动态画面，${(res.duration_ms / 1000).toFixed(0)} 秒${res.quality_blockers.length ? `；还差：${res.quality_blockers[0]}` : ""}`,
        res.production_ready ? "ok" : "info");
    } catch (e) {
      const d = e instanceof HttpError ? (e.detail as { message?: string } | string | undefined) : undefined;
      latest.current.toast(`合成失败：${typeof d === "string" ? d : d?.message || errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button type="button" className="cv-pg-btn" aria-disabled={busy}
      title="把整章（不只这张画布）的镜头按时间线合成一支 mp4：有视频用视频，没出片的用首尾帧溶解；对白、音效、环境声分轨混好"
      onClick={() => { if (!busy) void go(); }}>
      {busy ? <Spinner size={13} /> : <Icon name="video" size={14} />}合成章节
    </button>
  );
}

function ago(ms: number): string {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  return s < 60 ? `${s} 秒` : s < 3600 ? `${Math.round(s / 60)} 分钟` : `${(s / 3600).toFixed(1)} 小时`;
}

function TasksPill() {
  const s = useCanvas();
  const [el, setEl] = useState<HTMLElement | null>(null);
  if (!s.tasks.length) return null;
  const running = s.tasks.filter(taskOpen);
  const list = [...s.tasks].sort((a, b) => b.startedAt - a.startedAt);
  return (
    <>
      <button type="button" className={`cv-pill cv-glass${running.length ? " is-busy" : ""}${el ? " is-open" : ""}`}
        title="画布上提交的长任务（出片、生成、渲染、搭景）" onClick={e => setEl(el ? null : e.currentTarget)}>
        {running.length ? <Spinner size={12} /> : <Icon name="activity" size={14} />}
        {running.length ? `进行中 ${running.length}` : `任务 ${s.tasks.length}`}
      </button>
      {el && (
        <Popover anchor={el} placement="bottom-end" onClose={() => setEl(null)} className="cv-tasks">
          <div className="cv-pop-title">任务<span>点一项飞到它的节点</span></div>
          {list.map(t => (
            <button key={t.key} type="button" className={`cv-task st-${t.status}`} onClick={() => {
              s.focusNode(t.nodeId);
              s.select(t.nodeId);
              setEl(null);
            }}>
              <span className="cv-task-dot" />
              <span className="cv-task-main">
                <b>{t.label}</b>
                <span>{KIND_CN[t.kind]} · {STATUS_CN[t.status]}{t.progress != null && taskOpen(t) ? ` ${Math.round(t.progress)}%` : ""} · {ago(t.startedAt)}前</span>
                {t.error && <em>{t.error}</em>}
              </span>
            </button>
          ))}
        </Popover>
      )}
    </>
  );
}

export function TopBar({ nav, initialManager=false, initialAssemble=false, onManual }: { nav?: ReactNode;initialManager?:boolean;initialAssemble?:boolean;onManual:(id:string,manual?:boolean)=>void }) {
  const s = useCanvas();
  const rf = useReactFlow<CNode, CEdge>();
  const [viewEl, setViewEl] = useState<HTMLElement | null>(null);
  const [newCanvasOpen, setNewCanvasOpen] = useState(false);
  const [managerOpen,setManagerOpen]=useState(initialManager);
  const [manualEl,setManualEl]=useState<HTMLElement|null>(null);
  const { pick } = s;

  const novel = pick.novels.find(n => n.id === s.novelId);
  const chapter = pick.chapters.find(c => c.id === s.chapterId);
  const plan = pick.plans.find(p => p.id === s.planId);
  const save = SAVE[s.save];
  const comic=readCtx().medium==='comic';
  const editNode=(id:string,manual=true)=>{s.select(id);s.focusNode(id);onManual(id,manual);};
  const assemblyOpened=useRef(false);
  useEffect(()=>{if(initialAssemble&&!assemblyOpened.current&&!s.loading){const n=s.nodes.find(n=>n.data.comic?.step==='assemble');if(n){assemblyOpened.current=true;editNode(n.id,false);}}},[initialAssemble,s.loading,s.nodes]);
  const manualComic=()=>{
    const selected=s.selected?.data.comic;
    const linked=s.edges.filter(e=>e.source===s.selected?.id).map(e=>s.nodes.find(n=>n.id===e.target)).find(n=>n?.data.comic?.step==='video');
    const node=(selected?.step==='video'?s.selected:null)||linked||s.nodes.find(n=>n.data.comic?.step==='video'&&n.data.comic.source_id===selected?.source_id)||s.nodes.find(n=>n.data.comic?.step==='video');
    if(node)editNode(node.id);else setManagerOpen(true);
  };

  const doExport = async () => {
    const doc = exportDoc(s.nodes, s.edges, rf.getViewport());
    if(comic&&readCtx().production){const p=(await comicSources(readCtx().production!)).production;doc.production={id:p.id,medium:'comic',script_doc_id:p.script_doc_id};}
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `canvas-${s.planId || "draft"}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <header className={`cv-topbar${comic?' is-comic':''}`}>
      <div className="cv-topbar-side">
        <div className="cv-brand cv-glass">Ainer <b>Studio</b><span>{comic?'动态漫画':'创作画布'}</span></div>
        <button type="button" className="cv-pill cv-glass" onClick={() => comic?navigate('hub',{hub:'production'}):s.openHome()} title={comic?'当前制作项目的流程与状态':'打开所有画布'}>
          <Icon name="grid" size={13} />{comic?'制作总览':'我的画布'}
        </button>
        <nav className="cv-crumbs cv-glass" aria-label="小说、章节、分镜">
          <Crumb label={novel?.title || s.live.novelTitle || "选小说"} title="换一本小说" empty="还没有小说"
            items={pick.novels.map(n => ({ id: n.id, text: n.title, active: n.id === s.novelId, onPick: () => pick.setNovel(n.id) }))} />
          <span className="cv-crumb-sep">›</span>
          <Crumb label={chapter?.title || s.live.chapterTitle || "选章节"} title="换一章" empty="这本小说还没有章节"
            items={pick.chapters.map(c => ({ id: c.id, text: c.title || `第 ${c.order_no} 章`, hint: `#${c.order_no}`, active: c.id === s.chapterId, onPick: () => pick.setChapter(c.id) }))} />
          <span className="cv-crumb-sep">›</span>
          {!comic&&<><Crumb label={plan ? `分镜 v${plan.version}` : "选分镜"} title="换一份分镜计划（画布挂在分镜计划上）" empty="这一章还没有分镜计划"
            items={pick.plans.map(p => ({
              id: p.id, text: `分镜 v${p.version}`, active: p.id === s.planId, onPick: () => pick.setPlan(p.id),
              hint: `${p.shots} 镜${p.sample ? " · 试片" : ""}`,
            }))} /><span className="cv-crumb-sep">›</span></>}
          <Crumb label={s.board?.title || "选画布"} title="所有画布：自由画布、分镜画布和按场次创建的画布" empty="还没有画布，可以直接新建"
            items={s.boards.map(b => ({
              id: b.id, text: boardLabel(b), active: b.id === s.boardId, onPick: () => pick.setBoard(b.id),
              hint: b.shots != null ? `${b.videos ?? 0}/${b.shots} 镜` : b.purpose || "空白",
            }))}
            footer={comic?undefined:close => <BoardActions close={close} onOpenNew={() => setNewCanvasOpen(true)} />} />
        </nav>
        {!comic&&<button type="button" className="cv-pill cv-glass"
          title="新建空白画布，自由添加素材、文字、分组和连线"
          onClick={() => setNewCanvasOpen(true)}>
          <Icon name="plus" size={13} />新建画布
        </button>}
        {s.demo && <span className="cv-demo-pill" title="?demo=1：没连后端，数据是内置的演示故事；改动只存在这个浏览器里">演示数据</span>}
        {s.loading && <span className="cv-pill cv-glass"><Spinner size={12} />载入中</span>}
        {s.error && <span className="cv-pill cv-glass is-err" title={s.error}><Icon name="warn" size={14} />载入失败</span>}
      </div>

      <div className="cv-topbar-side">
        <button type="button" className="cv-pill cv-glass" disabled={!s.board||s.loading} onClick={e=>{if(comic)manualComic();else setManualEl(e.currentTarget);}} title={comic?'直接编辑当前镜头的方案、帧率、动作与音效':'在画布上手动制作图片或视频'}><Icon name="plus" size={14}/>{comic?'手动出片':'手动创作'}</button>
        <button type="button" className="cv-pill cv-glass" aria-expanded={managerOpen} onClick={()=>setManagerOpen(!managerOpen)} title="在画布内管理首帧、视频与镜头状态"><Icon name="grid" size={14}/>分镜管理</button>
        <button type="button" className="cv-pill cv-glass" title="带着当前作品和章节进入翻译工作台" onClick={() => navigate("translation")}>翻译</button>
        <button type="button" className="cv-pill cv-glass" title="切换制作类型并打开各自的画布" onClick={() => navigate("flow",{medium:comic?'video':'comic'})}>{comic?'视频制作':'动态漫画'}</button>
        {save && (
          s.save === "conflict"
            ? <button type="button" className={`cv-pill cv-glass cv-save t-${save.tone}`} title={save.title} onClick={() => s.reloadCanvas()}>
              <span className="cv-save-dot" />{save.text} · 载入远端
            </button>
            : <span className={`cv-pill cv-glass cv-save t-${save.tone}`} title={save.title}>
              {s.save === "saving" ? <Spinner size={11} /> : <span className="cv-save-dot" />}{save.text}
            </span>
        )}
        <TasksPill />
        {!comic&&<><ExecutePill /><RunPill /></>}
        <div className="cv-pillgroup cv-glass">
          <button type="button" className="cv-pg-btn" disabled={!s.board || s.demo}
            title={s.demo ? "共享舞台需要真实画布；演示模式不连接后端" : "自己搭舞台，多个镜头复用站位、动作和机位"}
            onClick={() => s.openOverlay({ kind: "shared_stage" })}>共享舞台</button>
          {!comic&&<FilmButton />}
          <button type="button" className="cv-pg-btn" title="按流程排列节点，避免重合；钉住的与分组保留" onClick={() => s.relayout()}>
            <Icon name="grid" size={14} />整理布局
          </button>
          <button type="button" className="cv-pg-btn" title={`下载画布文档 canvas-${s.planId || "draft"}.json（只含布局和引用）`} onClick={doExport}>
            <Icon name="download" size={14} />导出
          </button>
          {nav && (
            <button type="button" className={`cv-pg-btn${viewEl ? " is-open" : ""}`} title="按故事翻译、角色素材、画布导演、漫剧成片切换工作台"
              onClick={e => setViewEl(viewEl ? null : e.currentTarget)}>
              <Icon name="layout" size={14} />工作台<Icon name="down" size={12} />
            </button>
          )}
        </div>
      </div>
      {viewEl && nav && (
        <Popover anchor={viewEl} placement="bottom-end" onClose={() => setViewEl(null)} className="cv-viewmenu">
          {/* nav 是 Root 传进来的现成 <Nav>；点任意一项都会切走，顺手把弹层关掉 */}
          <div onClick={() => setViewEl(null)}>{nav}</div>
        </Popover>
      )}
      {newCanvasOpen && <NewCanvasModal onClose={() => setNewCanvasOpen(false)} />}
      {managerOpen&&<ShotManager onClose={()=>setManagerOpen(false)} onEdit={editNode}/>}
      {manualEl&&<Popover anchor={manualEl} placement="bottom-end" onClose={()=>setManualEl(null)}><MenuList items={[
        {id:'video',label:'手动视频',hint:'模型、帧率、参考与运镜参数',onPick:()=>{const id=s.addNode('video',{ref:freeRef(),title:'',role:'generated'});editNode(id);setManualEl(null);}},
        {id:'image',label:'手动图片',hint:'基础卡、首帧与参考图编辑',onPick:()=>{const id=s.addNode('image',{ref:freeRef(),title:'',role:'generated'});editNode(id);setManualEl(null);}},
        ...(s.selected?[{id:'selected',label:'编辑选中节点',hint:s.selected.data.title,onPick:()=>{editNode(s.selected!.id);setManualEl(null);}}]:[]),
      ]}/></Popover>}

    </header>
  );
}
