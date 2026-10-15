import { ComicDock } from "./ComicPanel";
import {ConcatPanel} from './ConcatPanel';
/**
 * 生成面板（Dock）：恰好选中一个「能生成」的节点时浮在底部中间。三种模式：
 *   box   白模节点：跟 3D-BOX 智能体对话改景（askBox）
 *   shot  镜头节点：「出片到镜头」（导演链 / 文字出片，结果挂回这一镜）｜「自由生成」（候选，长在镜头右边）
 *   gen   自由生成：生成节点、note/prompt 文字、上传图、预演/控制素材 → /studio/generate
 *
 * 能力不支持的一律灰掉写原因（铁律 3）；参数按所选模型的 limits 夹取并把「按多少出」写在面板上。
 * 生成任务只 s.track 登记，进度由 store 的唯一轮询器推进（铁律 6）。
 */
import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { useReactFlow } from "@xyflow/react";
import { cv, HttpError, media, missing } from "../api";
import {
  freeRef, GLYPH, inferEdgeKind, orchestrateDirectorShots, placeBeside, productSize, refMediaOf, shotBusy, shotMethods, taskOpen, thumbOf,
  type RefMedia,
} from "../actions";
import { isProductionRef } from "../model";
import type { CanvasStore } from "../contract";
import {
  isDerived, nodeIdOf, type CNode, type EdgeKind, type GenerateBody, type GenerateResult, type GenState, type ModelOption,
  type NodeKind, type NodeRef, type PromptSeg, type RefRole,
} from "../model";
import { useCanvas, useNodeResolved } from "../store";
import { askBox, regenerateBox } from "../three/actions";
import { errText, Icon, MenuList, Popover, Spinner, useLatest, type MenuItem } from "./Overlays";
import { PRESETS_TOP8 } from "./ScreenplayConfigModal";
import {
  PromptEditor, segsEmpty, segsFromText, segsToPrompt, segsToText, type MentionItem, type PromptEditorHandle,
} from "./PromptEditor";

type Media = "image" | "video";
type DockMode = "box" | "shot" | "gen";
type RefMode = "multi" | "first" | "control";

const ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4"];
const RESOLUTIONS = ["480p", "720p", "1080p"];
const DURATIONS = [3, 5, 8, 10, 15];
const COUNTS = [1, 2, 4];
const RES_SHORT: Record<string, number> = { "480p": 480, "720p": 720, "1080p": 1080 };

const ROLE_LABEL: Record<RefRole, string> = {
  character: "👤 角色身份",
  prop: "🗡️ 道具参考",
  first_frame: "🎬 镜头首帧",
  last_frame: "🏁 镜头尾帧",
  style: "👗 服饰/风格",
  scene: "🏞️ 场景环境",
  reference_sheet: "📋 综合定妆照",
  control_video: "🎥 运镜控制",
  base: "🖼️ 构图底图",
  reference: "📎 一般参考",
};
const EDGE_LABEL: Record<EdgeKind, string> = { identity: "身份", control: "控制", style: "风格", flow: "剧本", ref: "参考" };
const REF_MODES: { id: RefMode; label: string; hint: string }[] = [
  { id: "multi", label: "多参考", hint: "按连线：定妆照当身份、控制线当控制、其余当参考" },
  { id: "first", label: "首帧", hint: "第一张图当首帧（出图时当底图），其余按连线" },
  { id: "control", label: "白模控制", hint: "视频参考（白模预演、控制素材）一律当控制视频" },
];

/** 这个节点选中时 Dock 用哪种模式；null = 不出 Dock（定妆照、剧本场次只读，动作在工具条上） */
function modeOf(n: CNode): DockMode | null {
  if (n.type === "box3d") return "box";
  if (n.type === "video") return n.data.role === "shot" ? "shot" : "gen";
  if (n.type === "image") return n.data.role === "generated" || n.data.role === "upload" || n.data.role === "frame" ? "gen" : null;
  if (n.type === "text") return n.data.role === "note" || n.data.role === "prompt" ? "gen" : null;
  return null;
}

/* ───────────────────────── 面板设置（每个浏览器记一份，属于个人习惯） ───────────────────────── */

interface GenOpts {
  /** 输出类型：只在目标允许选时生效（文字、上传图、控制素材） */
  media: Media;
  /** 每种媒体上次选的模型（endpoint|model） */
  model: Partial<Record<Media, string>>;
  aspect: string;
  resolution: string;
  durationS: number;
  count: number;
  refMode: RefMode;
  fps:number;
  controlType:string|null;
}
const OPTS_KEY = "ainer.canvas.dock.v2";
const DEFAULT_OPTS: GenOpts = { media: "video", model: {}, aspect: "16:9", resolution: "480p", durationS: 5, count: 1, refMode: "multi",fps:24,controlType:null };

function loadOpts(): GenOpts {
  try {
    const raw = localStorage.getItem(OPTS_KEY) || localStorage.getItem("ainer.canvas.dock.v1");
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<GenOpts>;
      // 本地模型默认速度为王：若仍为旧的 720p 默认值，直接自动对齐极速 480p (768/832x448)
      return { ...DEFAULT_OPTS, ...parsed, resolution: parsed.resolution === "720p" ? "480p" : (parsed.resolution || "480p") };
    }
  } catch { /* 隐私模式 / 被清掉：用默认 */ }
  return DEFAULT_OPTS;
}
function saveOpts(o: GenOpts) {
  try { localStorage.setItem(OPTS_KEY, JSON.stringify(o)); } catch { /* 存不了就算了 */ }
}
function loadCollapsed(): boolean {
  try { return localStorage.getItem(OPTS_KEY + ".collapsed") === "1"; } catch { return false; }
}
function saveCollapsed(v: boolean) {
  try { localStorage.setItem(OPTS_KEY + ".collapsed", v ? "1" : "0"); } catch { /* 同上 */ }
}

/* ───────────────────────── 模型列表与 limits 夹取 ───────────────────────── */

const modelKey = (m: ModelOption) => `${m.endpoint_id ?? ""}|${m.model}`;

/** 每种媒体只拉一次（失败的不缓存，下次打开再试） */
const modelCache = new Map<Media, Promise<ModelOption[]>>();
function useModels(m: Media): { list: ModelOption[] | null; error: string } {
  const [st, setSt] = useState<{ m: Media; list: ModelOption[] | null; error: string }>({ m, list: null, error: "" });
  useEffect(() => {
    let alive = true;
    let p = modelCache.get(m);
    if (!p) {
      p = cv.models(m);
      modelCache.set(m, p);
      p.catch(() => modelCache.delete(m));
    }
    p.then(
      list => { if (alive) setSt({ m, list, error: "" }); },
      e => {
        if (!alive) return;
        setSt({ m, list: [], error: missing(e) ? "模型列表不可用（后端没有 /studio/models）" : `模型列表拉不下来：${errText(e)}` });
      },
    );
    return () => { alive = false; };
  }, [m]);
  return st.m === m ? st : { list: null, error: "" };
}

function wantSize(aspect: string, res: string): [number, number] {
  const [a, b] = aspect.split(":").map(Number);
  const short = RES_SHORT[res] ?? 720;
  return a >= b ? [Math.round((short * a) / b), short] : [short, Math.round((short * b) / a)];
}

/** 按模型支持的尺寸夹取：同画幅里取不超过目标的最大一档；返回要写在面板上的提示（不用夹就 null） */
function sizeNote(aspect: string, res: string, sizes?: [number, number][]): string | null {
  if (!sizes?.length) return null;
  const want = wantSize(aspect, res);
  const ar = want[0] / want[1];
  const area = (s: [number, number]) => s[0] * s[1];
  const off = (s: [number, number]) => Math.abs(s[0] / s[1] - ar) / ar;
  const same = sizes.filter(s => off(s) < 0.04).sort((a, b) => area(b) - area(a));
  if (same.some(s => s[0] === want[0] && s[1] === want[1])) return null;
  if (same.length) {
    const fit = same.find(s => area(s) <= area(want));
    if (!fit) return `该模型最小 ${same[same.length - 1][0]}×${same[same.length - 1][1]}，按此出`;
    // 只差在对齐 64 像素（480p → 768×448 这类）不算「被改了」：黄色警告会让人以为参数选错了
    if (Math.min(...fit) >= Math.min(...want) * 0.85) return null;
    return fit === same[0] ? `该模型最大 ${fit[0]}×${fit[1]}，按此出` : `按 ${fit[0]}×${fit[1]} 出`;
  }
  const best = [...sizes].sort((a, b) => off(a) - off(b) || area(b) - area(a))[0];
  return `该模型没有 ${aspect}，按 ${best[0]}×${best[1]} 出`;
}

function estimateText(m: ModelOption | null, count: number): string {
  if (!m) return "";
  const money = m.cost === 0 ? (m.local ? "本机 · 免费" : "免费") : `≈ ¥${(m.cost * count).toFixed(2)}`;
  if (m.estimated_ms == null) return money;
  // 本机队列是串行的：N 条就是 N 倍
  const ms = m.estimated_ms * count;
  return `${money} · ${ms < 60_000 ? "不到 1 分钟" : `约 ${Math.round(ms / 60_000)} 分钟`}`;
}

/* ───────────────────────── 参考 ───────────────────────── */

interface RefItem {
  key: string;
  node: CNode;
  self: boolean;
  edge: EdgeKind | null;
  thumb: { img?: string; video?: string; glyph: string };
  m: RefMedia;
  role: RefRole | null;
  include: boolean;
  /** 不发的原因（⚠ 提示） */
  why: string | null;
}

function roleOptions(kind: Media, out: Media): RefRole[] {
  if (kind === "video") return ["control_video", "reference"];
  return out === "video"
    ? ["first_frame", "character", "prop", "reference_sheet", "style", "scene", "reference", "last_frame"]
    : ["base", "character", "prop", "style", "scene", "reference"];
}

function defaultRole(kind: Media, edge: EdgeKind | null, mode: RefMode, out: Media, firstImage: boolean, self: CNode | null): RefRole {
  if (self?.data.role === "prop") return "prop";
  if (kind === "video") {
    if (self) return self.data.role === "previs" || self.data.role === "control" ? "control_video" : "reference";
    return edge === "control" || mode === "control" ? "control_video" : "reference";
  }
  if (self || (mode === "first" && firstImage)) return out === "image" ? "base" : "first_frame";
  if (edge === "identity") return "character";
  if (edge === "style") return "style";
  return "reference";
}

/** 目标自己有媒体（上传图、控制素材、镜头首帧）时，自己也算一张参考 */
function selfRefMedia(node: CNode, s: CanvasStore): RefMedia | null {
  if (node.data.role === "generated" || node.type === "text") return null;
  const r = s.resolve(node.data.ref, node.data);
  // 镜头拿首帧当首帧最自然；没首帧再退到视频
  if (r.kind === "shot" && r.shot.first?.url) return { url: media(r.shot.first.url)!, kind: "image" };
  const m = refMediaOf(node, r, s);
  return "url" in m ? m : null;
}

/** 空的生成占位节点（「生成」动作新建、还没跑过）：第一条结果直接填进它自己 */
function isEmptyPlaceholder(n: CNode): boolean {
  const g = n.data.gen;
  return n.data.role === "generated" && !n.data.media && (!g || g.status === "failed" || g.status === "cancelled");
}

function Thumb({ t, size = 64 }: { t: { img?: string; video?: string; glyph: string }; size?: number }) {
  const [bad, setBad] = useState(false);
  const style = { width: size, height: size };
  if (t.img && !bad) return <img className="cv-thumb" style={style} src={t.img} alt="" draggable={false} onError={() => setBad(true)} />;
  if (t.video && !bad) {
    return <video className="cv-thumb" style={style} src={`${t.video}#t=0.05`} muted playsInline preload="metadata" onError={() => setBad(true)} />;
  }
  return <span className="cv-thumb cv-thumb-glyph" style={style}>{t.glyph}</span>;
}

/* ───────────────────────── 小控件 ───────────────────────── */

/** 底行参数胶囊里的一段：点开向上弹菜单 */
function CapSeg({ label, title, items, off }: { label: ReactNode; title?: string; items: MenuItem[]; off?: string | false }) {
  const [el, setEl] = useState<HTMLElement | null>(null);
  return (
    <>
      <button type="button" className={`cv-cap-seg${off ? " is-off" : ""}${el ? " is-open" : ""}`} aria-disabled={!!off}
        title={off || title} onClick={e => { if (!off) setEl(el ? null : e.currentTarget); }}>
        {label}
      </button>
      {el && (
        <Popover anchor={el} placement="top-start" onClose={() => setEl(null)}>
          <MenuList items={items} onPicked={() => setEl(null)} />
        </Popover>
      )}
    </>
  );
}

function PillPick({ label, items, title }: { label: ReactNode; items: MenuItem[]; title?: string }) {
  const [el, setEl] = useState<HTMLElement | null>(null);
  return (
    <>
      <button type="button" className={`cv-dock-pill${el ? " is-open" : ""}`} title={title}
        onClick={e => setEl(el ? null : e.currentTarget)}>
        {label}<Icon name="down" size={12} />
      </button>
      {el && (
        <Popover anchor={el} placement="top-start" onClose={() => setEl(null)}>
          <MenuList items={items} onPicked={() => setEl(null)} />
        </Popover>
      )}
    </>
  );
}

function SendButton({ busy, off, onClick, label }: { busy: boolean; off: string | false; onClick: () => void; label?: string }) {
  return (
    <button type="button" className={`cv-send${off || busy ? " is-off" : ""}${label ? " has-label" : ""}`}
      aria-disabled={!!off || busy} aria-label={label ?? "发送"} title={off || (busy ? "提交中…" : "发送（⌘Enter）")}
      onClick={() => { if (!off && !busy) onClick(); }}>
      {busy ? <Spinner size={16} /> : label ? <span>{label}</span> : <Icon name="send" size={18} />}
    </button>
  );
}

/* ───────────────────────── 预设（风格 / 运镜） ───────────────────────── */

interface PresetRow { id: string; name: string; category: string | null; cover_url: string | null; payload: { prompt?: string } }
const presetCache = new Map<string, Promise<PresetRow[]>>();

/**
 * 预设库没有进 cv（契约里没有这个接口），这里直连 /api/v2/presets；
 * 演示模式接管不了它，所以演示模式下按钮直接禁用（见 PresetButton）。
 */
function loadPresets(kind: "style" | "camera_move"): Promise<PresetRow[]> {
  let p = presetCache.get(kind);
  if (!p) {
    p = fetch(`/api/v2/presets?kind=${kind}&category=${encodeURIComponent("推荐")}`).then(async r => {
      if (!r.ok) throw new Error(`${r.status}`);
      return (await r.json()) as PresetRow[];
    });
    presetCache.set(kind, p);
    p.catch(() => presetCache.delete(kind));
  }
  return p;
}

function PresetButton({ demo, onPick }: { demo: boolean; onPick: (text: string) => void }) {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [kind, setKind] = useState<"style" | "camera_move">("style");
  const [rows, setRows] = useState<PresetRow[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!el) return;
    let alive = true;
    setRows(null);
    setErr("");
    loadPresets(kind).then(
      r => { if (alive) setRows(r.filter(x => x.payload?.prompt).slice(0, 40)); },
      e => { if (alive) setErr(`预设库不可用（${errText(e)}）`); },
    );
    return () => { alive = false; };
  }, [el, kind]);
  const off = demo ? "演示模式没有预设库（要连上后端）" : false;
  return (
    <>
      <button type="button" className={`cv-tool${off ? " is-off" : ""}${el ? " is-open" : ""}`} aria-disabled={!!off}
        title={off || "风格 / 运镜预设：把预设的提示词接到末尾"} onClick={e => { if (!off) setEl(el ? null : e.currentTarget); }}>
        预设
      </button>
      {el && (
        <Popover anchor={el} placement="top-end" onClose={() => setEl(null)} className="cv-presets">
          <div className="cv-seg cv-seg-sm">
            <button type="button" className={kind === "style" ? "is-on" : ""} onClick={() => setKind("style")}>风格</button>
            <button type="button" className={kind === "camera_move" ? "is-on" : ""} onClick={() => setKind("camera_move")}>运镜</button>
          </div>
          {err ? <div className="cv-menu-empty">{err}</div>
            : !rows ? <div className="cv-menu-empty"><Spinner /> 载入中…</div>
              : !rows.length ? <div className="cv-menu-empty">这一类还没有预设</div>
                : (
                  <div className="cv-preset-grid">
                    {rows.map(p => (
                      <button key={p.id} type="button" className="cv-preset" title={p.payload.prompt}
                        onClick={() => {
                          onPick(p.payload.prompt ?? "");
                          // 记一笔「最近使用」，失败无所谓
                          fetch(`/api/v2/presets/${p.id}:use`, { method: "POST" }).catch(() => undefined);
                          setEl(null);
                        }}>
                        {p.cover_url ? <img src={media(p.cover_url)} alt="" /> : <span className="cv-preset-ph">{p.name.slice(0, 1)}</span>}
                        <span>{p.name}</span>
                      </button>
                    ))}
                  </div>
                )}
        </Popover>
      )}
    </>
  );
}

/** 提示词右下角的小工具：预设、润色、语音、@ */
function EditorTools({ demo, ed, onPreset }: {
  demo: boolean;
  ed: RefObject<PromptEditorHandle | null>;
  onPreset: (text: string) => void;
}) {
  return (
    <>
      <PresetButton demo={demo} onPick={onPreset} />
      <button type="button" className="cv-tool is-off" aria-disabled title="还没有提示词润色接口"><Icon name="sparkle" size={14} />润色</button>
      <button type="button" className="cv-tool cv-tool-icon is-off" aria-disabled title="画布还没接语音输入"><Icon name="mic" size={14} /></button>
      <button type="button" className="cv-tool cv-tool-icon" title="引用上游节点（也可以直接输入 @）"
        onMouseDown={e => e.preventDefault()} onClick={() => ed.current?.openMention()}>
        <Icon name="at" size={14} />
      </button>
    </>
  );
}

/* ───────────────────────── 自由生成 ───────────────────────── */

function GenPanel({ node, opts:defaults, setOpts:onOptions, drafts }: {
  node: CNode;
  opts: GenOpts;
  setOpts: (p: Partial<GenOpts>) => void;
  drafts: Map<string, PromptSeg[]>;
}) {
  const s = useCanvas();
  const latest = useLatest(s);
  const ed = useRef<PromptEditorHandle>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [opts,setLocalOpts]=useState<GenOpts>(()=>({...defaults,...node.data.manualDraft?.settings as Partial<GenOpts>}));
  const setOpts=(patch:Partial<GenOpts>)=>{setLocalOpts(p=>({...p,...patch}));onOptions(patch);};
  const [roles, setRoles] = useState<Record<string, RefRole>>(()=>node.data.manualDraft?.roles||{});
  const [excluded, setExcluded] = useState<Set<string>>(() => new Set(node.data.manualDraft?.excluded||[]));
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [confirm, setConfirm] = useState<number | null>(null);
  const [addEl, setAddEl] = useState<HTMLElement | null>(null);
  const [addQ, setAddQ] = useState("");

  // 输出类型：生成节点 / 镜头跟着自己的类型走；文字、上传图、控制素材可以选
  const fixed: Media | null = node.data.role === "generated" || node.data.role === "shot"
    ? (node.type === "image" ? "image" : "video") : null;
  const out: Media = fixed ?? opts.media;

  const up = s.upstream(node.id);
  const mentions: MentionItem[] = up.map(({ node: n, edge }) => {
    const t = thumbOf(n, s.resolve(n.data.ref, n.data));
    return { id: n.id, label: n.data.title, kind: n.type ?? "image", thumb: t.img ?? null, hint: EDGE_LABEL[edge.data?.kind ?? "ref"] };
  });

  const isText = node.type === "text";
  const [segs, setSegs] = useState<PromptSeg[]>(() =>
    drafts.get(node.id) ?? node.data.manualDraft?.prompt ?? (isText ? segsFromText(node.data.text ?? "", mentions) : []));
  useEffect(()=>{
    if(isDerived(node.data.ref))return;
    latest.current.updateNodeData(node.id,{manualDraft:{prompt:segs,settings:{...opts},roles,excluded:[...excluded]}});
  },[segs,opts,roles,excluded]);

  // note/prompt 节点：提示词就是它的正文，防抖写回 data.text；卸载时把没写的补上
  const pendingText = useRef<string | null>(null);
  const timer = useRef(0);
  useEffect(() => () => {
    window.clearTimeout(timer.current);
    if (pendingText.current != null) latest.current.updateNodeData(node.id, { text: pendingText.current });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const onChange = (v: PromptSeg[]) => {
    setSegs(v);
    setConfirm(null);
    if (!isText) { drafts.set(node.id, v); return; }
    pendingText.current = segsToText(v);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      if (pendingText.current == null) return;
      latest.current.updateNodeData(node.id, { text: pendingText.current });
      pendingText.current = null;
    }, 400);
  };

  /* 模型 */
  const { list: models, error: modelErr } = useModels(out);
  const model = useMemo(() => {
    if (!models?.length) return null;
    const want = opts.model[out];
    const chosen = models.find(m => modelKey(m) === want && m.ready);
    return chosen ?? models.find(m => m.ready && m.local) ?? models.find(m => m.ready) ?? null;
  }, [models, opts.model, out]);
  const limits = model?.limits ?? {};
  const fpsChoices=limits.fps?.length?limits.fps:[24];
  const controlChoices=Array.isArray(model?.supports?.control_types)?model.supports.control_types as string[]:[];
  const controlType=opts.controlType||(controlChoices.includes('layout')?'layout':controlChoices[0]||'');

  /* 参考 */
  const self = selfRefMedia(node, s);
  const entries: { node: CNode; edge: EdgeKind | null; self: boolean; m: RefMedia }[] = [
    ...(self ? [{ node, edge: null, self: true, m: self }] : []),
    ...up.map(u => ({ node: u.node, edge: u.edge.data?.kind ?? "ref", self: false, m: refMediaOf(u.node, s.resolve(u.node.data.ref, u.node.data), s) })),
  ];
  let firstImageSeen = false;
  let imagesSent = 0;
  const maxImages = limits.max_ref_images ?? null;
  const refs: RefItem[] = entries.map(e => {
    const key = e.self ? `self:${e.node.id}` : e.node.id;
    const thumb = e.self && "url" in e.m
      ? (e.m.kind === "image" ? { img: e.m.url, glyph: GLYPH[e.node.type ?? "image"] } : { video: e.m.url, glyph: GLYPH[e.node.type ?? "video"] })
      : thumbOf(e.node, s.resolve(e.node.data.ref, e.node.data));
    if (!("url" in e.m)) return { key, node: e.node, self: e.self, edge: e.edge, thumb, m: e.m, role: null, include: false, why: e.m.warn };
    const isFirstImage = e.m.kind === "image" && !firstImageSeen;
    if (e.m.kind === "image") firstImageSeen = true;
    const opts2 = roleOptions(e.m.kind, out);
    const picked = roles[key];
    const role = picked && opts2.includes(picked) ? picked : defaultRole(e.m.kind, e.edge, opts.refMode, out, isFirstImage, e.self ? e.node : null);
    let include = !excluded.has(key);
    let why: string | null = include ? null : "已设为不发（点缩略图切换）";
    if (include && e.m.kind === "image") {
      if (maxImages != null && imagesSent >= maxImages) { include = false; why = `超出该模型的参考图上限（${maxImages} 张）`; }
      else imagesSent++;
    }
    return { key, node: e.node, self: e.self, edge: e.edge, thumb, m: e.m, role, include, why };
  });
  const sending = refs.filter(r => r.include);
  const wantsControl=sending.some(r=>r.role==='control_video');
  /** 能发、只是用户点掉了（空心圈）；别的不发都是 ⚠ */
  const userOff = (r: RefItem) => "url" in r.m && excluded.has(r.key);

  /* 夹取提示（铁律 3） */
  const maxS = limits.max_duration_ms ? Math.floor(limits.max_duration_ms / 1000) : null;
  const durationS = out === "video" ? (maxS != null ? Math.min(opts.durationS, maxS) : opts.durationS) : null;
  const maxCount = limits.max_count ?? null;
  const count = maxCount != null ? Math.max(1, Math.min(opts.count, maxCount)) : opts.count;
  const notes: string[] = [];
  const sn = sizeNote(opts.aspect, opts.resolution, limits.sizes);
  if (sn) notes.push(sn);
  if (out === "video" && maxS != null && opts.durationS > maxS) notes.push(`最长 ${maxS}s，按 ${maxS}s 出`);
  if (maxCount != null && opts.count > maxCount) notes.push(`一次最多 ${maxCount} 条`);
  if (maxImages != null && refs.some(r => r.why?.startsWith("超出"))) notes.push(`该模型最多 ${maxImages} 张参考图，多出的不发`);
  if (modelErr) notes.push(modelErr);

  const promptText = segsToPrompt(segs);
  const stageControl = up.some(u => u.node.data.ref.kind === "stage" || u.node.data.ref.kind === "coverage");
  const off: string | false =
    stageControl ? "当前生成器尚未支持共享舞台控制，请先导出镜头预演控制"
      :out==='video'&&!model?'先选择已接入的视频模型'
      :out==='video'&&!fpsChoices.includes(opts.fps)?`所选模型不支持 ${opts.fps} 帧／秒，请选择支持的帧率`
      :out==='video'&&wantsControl&&!controlChoices.includes(controlType)?'所选模型不支持当前白模控制方式，请更换模型或控制方式'
      : model && !model.ready ? "这个模型还没接入"
      : !promptText && !sending.length ? "先写提示词，或连一张参考"
        : false;

  /* 发送 */
  const send = async (confirmCost = false) => {
    const st = latest.current;

    if(off){st.toast(off,'info');return;}

    const body: GenerateBody = {
      media: out,
      endpoint_id: model?.endpoint_id ?? null,
      model: model?.model ?? null,
      prompt: promptText,
      refs: sending.flatMap(r => ("url" in r.m && r.role ? [{
        node_id: r.node.id, url: r.m.url, asset_id: r.m.asset_id ?? null, kind: r.m.kind, role: r.role, tag: r.role==='control_video'?controlType:r.node.data.title,
        ...(isProductionRef(r.node.data.ref) ? { production_ref: r.node.data.ref } : {}),
      }] : [])),
      aspect_ratio: opts.aspect,
      resolution: opts.resolution,
      duration_ms: durationS != null ? durationS * 1000 : null,
      ...(out==='video'?{video_fps:opts.fps}:{}),
      count,
      seed: null,
      target: { board_id: st.boardId, plan_id: st.planId || null, node_id: node.id },
    };
    setBusy(true);
    try {
      const res = await cv.generate(confirmCost ? ({ ...body, confirm_cost: true } as GenerateBody) : body);
      if (res.requires_confirm && !res.tasks.length) { setConfirm(res.estimated_cost); return; }
      placeProducts(latest.current, node, res, out, promptText, opts.aspect);
      for (const w of res.warnings) latest.current.toast(w, "info");
      setConfirm(null);
    } catch (e) {
      const d = e instanceof HttpError ? (e.detail as { code?: string; estimated_cost?: number } | undefined) : undefined;
      if (e instanceof HttpError && e.status === 409 && d?.code === "COST_CONFIRM_REQUIRED") setConfirm(d.estimated_cost ?? 0);
      else if (missing(e)) latest.current.toast("后端还没有通用生成接口（/api/v2/studio/generate）", "err");
      else latest.current.toast(`生成没提交上：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  };

  /* 上传：新建一个 asset 节点放在目标左边并连过来 */
  const onFile = async (f: File) => {
    setUploading(true);
    try {
      const res = await cv.upload(f);
      const st = latest.current;
      const ref: NodeRef = { kind: "asset", id: res.asset_id };
      const mime = res.mime ?? f.type;
      const type: NodeKind = mime.startsWith("video/") ? "video" : "image";
      const role = type === "image" ? "upload" as const : undefined;
      let id = nodeIdOf(ref);
      if (!st.nodes.some(n => n.id === id)) {
        const at = placeBeside(st.nodes, node, "left", type === "video" ? { w: 280, h: 200 } : { w: 220, h: 220 })[0];
        id = st.addNode(type, {
          ref, title: f.name.replace(/\.[^.]+$/, "") || "上传", role,
          media: { url: media(res.url) ?? res.url, asset_id: res.asset_id, mime },
        }, at);
      }
      st.connect(id, node.id, inferEdgeKind({ type, role }, { type: node.type, role: node.data.role }));
      st.select(node.id);
    } catch (e) {
      latest.current.toast(missing(e) ? "后端还没有上传接口（/api/v2/studio/uploads）" : `上传失败：${errText(e)}`, "err");
    } finally {
      setUploading(false);
    }
  };

  /* 「＋ 参考」候选：画布上其余的图/视频/白模 */
  const upIds = new Set(up.map(u => u.node.id));
  const q = addQ.trim().toLowerCase();
  const candidates = addEl
    ? s.nodes.filter(n => n.id !== node.id && !upIds.has(n.id) && (n.type === "image" || n.type === "video" || n.type === "box3d")
      && (!q || n.data.title.toLowerCase().includes(q))).slice(0, 60)
    : [];

  return (
    <>
      <div className="cv-refs">
        {refs.map(r => (
          <div key={r.key} className={`cv-ref${r.include ? " is-on" : ""}${r.why ? " is-warn" : ""}${r.role ? "" : " is-text"}`}>
            <button type="button" className="cv-ref-pic"
              title={`${r.self ? "本节点 · " : ""}${r.node.data.title}${r.why ? `\n⚠ ${r.why}` : r.include ? "\n会发给模型（点一下设为不发）" : ""}`}
              onClick={() => {
                if (!("url" in r.m)) { s.focusNode(r.node.id); return; }
                setExcluded(prev => {
                  const n = new Set(prev);
                  if (n.has(r.key)) n.delete(r.key); else n.add(r.key);
                  return n;
                });
              }}>
              <Thumb t={r.thumb} />
              {!r.role && <span className="cv-ref-name">{r.node.data.title}</span>}
              <span className={`cv-ref-badge ${r.include ? "ok" : userOff(r) ? "off" : "warn"}`}>
                {r.include ? <Icon name="check" size={10} /> : userOff(r) ? null : "!"}
              </span>
              {r.self && <span className="cv-ref-self">本节点</span>}
            </button>
            {r.role && "url" in r.m ? (
              <select className="cv-ref-role" value={r.role} title="这张参考在生成里当什么用"
                onChange={e => setRoles(p => ({ ...p, [r.key]: e.target.value as RefRole }))}>
                {roleOptions(r.m.kind, out).map(o => <option key={o} value={o}>{ROLE_LABEL[o]}</option>)}
              </select>
            ) : <span className="cv-ref-role is-text" title={r.why ?? ""}>{r.node.type === "text" ? "只拼标题" : "不发"}</span>}
          </div>
        ))}
        <button type="button" className={`cv-ref-add${addEl ? " is-open" : ""}`} title="把画布上的图、视频、白模连过来当参考"
          onClick={e => { setAddQ(""); setAddEl(addEl ? null : e.currentTarget); }}>
          <Icon name="plus" size={18} /><span>参考</span>
        </button>
        <button type="button" className={`cv-ref-add${uploading ? " is-off" : ""}`} aria-disabled={uploading}
          title="上传图片或视频，长成一个节点连过来" onClick={() => { if (!uploading) fileRef.current?.click(); }}>
          {uploading ? <Spinner size={16} /> : <Icon name="upload" size={18} />}<span>{uploading ? "上传中" : "上传"}</span>
        </button>
        <input ref={fileRef} type="file" accept="image/*,video/*" hidden
          onChange={e => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void onFile(f); }} />
        {!refs.length && <div className="cv-refs-tip">连一张定妆照、白模预演或任意图进来当参考；也可以直接写提示词</div>}
      </div>
      {addEl && (
        <Popover anchor={addEl} placement="top-start" onClose={() => setAddEl(null)} className="cv-addref">
          <input className="cv-input" autoFocus placeholder="按标题筛选…" value={addQ} onChange={e => setAddQ(e.target.value)} />
          {candidates.length ? (
            <div className="cv-addref-list">
              {candidates.map(n => (
                <button key={n.id} type="button" className="cv-addref-item" onClick={() => {
                  latest.current.connect(n.id, node.id, inferEdgeKind({ type: n.type, role: n.data.role }, { type: node.type, role: node.data.role }));
                  setAddEl(null);
                }}>
                  <Thumb t={thumbOf(n, s.resolve(n.data.ref, n.data))} size={34} />
                  <span>{n.data.title}</span>
                  <em>{GLYPH[n.type ?? "image"]}</em>
                </button>
              ))}
            </div>
          ) : <div className="cv-menu-empty">画布上没有别的图、视频或白模了</div>}
        </Popover>
      )}

      {isText && (
        <div className="cv-dock-script-bar">
          <button
            type="button"
            className="cv-dock-script-btn"
            title="打开剧本设定器：爆款预设、5维精细设定与跨文化世界观转译"
            onClick={() => s.openOverlay({ kind: "screenplay_config", nodeId: node.id })}
          >
            <Icon name="sparkle" size={13} />
            <span>✨ 剧本设定器</span>
          </button>
          <span className="cv-dock-script-sep" />
          <span className="cv-dock-script-title">预设:</span>
          {PRESETS_TOP8.map(p => (
            <button
              key={p.id}
              type="button"
              className="cv-dock-script-chip"
              title={`点击应用《${p.name}》预设`}
              onClick={() => s.openOverlay({ kind: "screenplay_config", nodeId: node.id, presetId: p.id })}
            >
              #{p.name.slice(0, 4)}
            </button>
          ))}
        </div>
      )}

      <PromptEditor
        ref={ed}
        docKey={node.id}
        value={segs}
        onChange={onChange}
        mentions={mentions}
        placeholder={isText ? "写提示词，输入 @ 引用上游节点；会存成这个节点的正文" : "描述你想要的画面，输入 @ 引用上游的图或视频…"}
        onSubmit={() => { if (!off && !busy) void send(confirm != null); }}
        onChipClick={id => s.focusNode(id)}
        tools={<EditorTools demo={s.demo} ed={ed} onPreset={t => ed.current?.insertText(segsEmpty(segs) ? t : `，${t}`)} />}
      />

      {(notes.length > 0 || confirm != null) && (
        <div className="cv-dock-notes">
          {confirm != null && <span className="cv-note-cost">付费模型：这次约 ¥{confirm.toFixed(2)}，再点一次发送确认</span>}
          {notes.map(n => <span key={n}><Icon name="warn" size={12} />{n}</span>)}
        </div>
      )}

      <div className="cv-dock-bottom">
        <PillPick label={REF_MODES.find(m => m.id === opts.refMode)?.label ?? "多参考"} title="参考的默认用法（单张可以在缩略图下面改）"
          items={REF_MODES.map(m => ({ id: m.id, label: m.label, title: m.hint, hint: m.hint, active: m.id === opts.refMode, onPick: () => { setRoles({}); setOpts({ refMode: m.id }); } }))} />
        {!fixed && (
          <div className="cv-seg">
            <button type="button" className={out === "image" ? "is-on" : ""} onClick={() => setOpts({ media: "image" })}><Icon name="image" size={13} />图片</button>
            <button type="button" className={out === "video" ? "is-on" : ""} onClick={() => setOpts({ media: "video" })}><Icon name="video" size={13} />视频</button>
          </div>
        )}
        <div className="cv-cap">
          <CapSeg
            label={<>{model ? model.label : models === null && !modelErr ? "载入模型…" : "自动选模型"}{model?.local && <em className="cv-tag">本机</em>}</>}
            title={model ? `${model.label} · ${model.capability}` : modelErr || "后端按参考自动选"}
            items={(models ?? []).map(m => ({
              id: modelKey(m), label: m.label, active: model ? modelKey(m) === modelKey(model) : false,
              hint: <>{m.local && <em className="cv-tag">本机</em>}{m.cost === 0 ? "免费" : `¥${m.cost}`}</>,
              disabled: m.ready ? false : "未接入（后端没有这个模型的适配器）",
              onPick: () => setOpts({ model: { ...opts.model, [out]: modelKey(m) } }),
            }))}
            off={!models?.length ? (modelErr || (models === null ? "模型列表载入中" : "没有可选的模型")) : false}
          />
          <CapSeg label={opts.aspect} title="画幅" items={ASPECTS.map(a => ({ id: a, label: a, active: a === opts.aspect, onPick: () => setOpts({ aspect: a }) }))} />
          <CapSeg label={opts.resolution} title="分辨率（按模型支持的尺寸夹取）"
            items={RESOLUTIONS.map(r => ({ id: r, label: r, active: r === opts.resolution, hint: sizeNote(opts.aspect, r, limits.sizes) ?? undefined, onPick: () => setOpts({ resolution: r }) }))} />
          {out === "video" && (
            <CapSeg label={`${durationS}s`} title="时长"
              items={DURATIONS.map(d => ({
                id: String(d), label: `${d}s`, active: d === durationS,
                disabled: maxS != null && d > maxS ? `该模型最长 ${maxS}s` : false,
                onPick: () => setOpts({ durationS: d }),
              }))} />
          )}
          {out==='video'&&<CapSeg label={`${opts.fps} 帧／秒`} title="模型原生生成帧率" items={fpsChoices.map(f=>({id:String(f),label:`${f} 帧／秒`,active:opts.fps===f,onPick:()=>setOpts({fps:f})}))}/>}
          {out==='video'&&wantsControl&&<CapSeg label={`白模 · ${controlType||'不支持'}`} title="控制视频按所选方式驱动机位与动作" off={!controlChoices.length?'所选模型没有声明可用的控制视频方式':false} items={controlChoices.map(t=>({id:t,label:t==='layout'?'Layout · 白模运镜与走位':t,active:controlType===t,onPick:()=>setOpts({controlType:t})}))}/>}
          <CapSeg label={`${count}${out === "video" ? "条" : "张"}`} title="一次出几个（逐个排队，每个换一个种子）"
            items={COUNTS.map(c => ({
              id: String(c), label: `${c} ${out === "video" ? "条" : "张"}`, active: c === count,
              disabled: maxCount != null && c > maxCount ? `该模型一次最多 ${maxCount} 个` : false,
              onPick: () => setOpts({ count: c }),
            }))} />
        </div>
        <span className="cv-dock-spacer" />
        <span className="cv-estimate">{estimateText(model, count)}</span>
        {out === "video" && (isText || up.some(u => u.node.type === "box3d" || u.node.data.ref?.kind === "box_project" || u.node.data.role === "sheet" || u.node.data.title.includes("定妆照") || u.node.type === "text")) && (
          <button
            type="button"
            className="cv-dock-btn is-accent"
            style={{ marginRight: 8, fontWeight: 600, padding: "0 12px", background: "linear-gradient(135deg, #4f46e5, #7c3aed)", color: "#fff", borderRadius: 8, height: 32, border: "none", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4 }}
            title="遵循 ABCD 规范：拆解 2~3 个分镜头，分别利用白模机位与定妆照身份，首尾帧过渡批次生成并拼接成片"
            onClick={() => void orchestrateDirectorShots(latest.current, node)}
          >
            🎬 导演多镜成片 (ABCD规范)
          </button>
        )}
        <SendButton busy={busy} off={off} onClick={() => void send(confirm != null)} />
      </div>
    </>
  );
}

/** 每个任务一个产物节点（竖排在目标右边、连 ref 边）；空占位节点自己接第一条 */
function placeProducts(s: CanvasStore, target: CNode, res: GenerateResult, out: Media, prompt: string, aspect: string) {
  const n = res.tasks.length;
  if (!n) return;
  const fillSelf = isEmptyPlaceholder(target) && target.type === out;
  const extra = n - (fillSelf ? 1 : 0);
  const size = productSize(out, aspect);
  const spots = extra > 0 ? placeBeside(s.nodes, target, "right", size, extra) : [];
  let k = 0;
  res.tasks.forEach((t, i) => {
    const gen: GenState = { task_id: t.id, status: t.status, model: res.resolved.model, prompt };
    const title = n > 1 ? `${target.data.title} 生成 ${i + 1}/${n}` : `${target.data.title} 生成`;
    let id: string;
    if (i === 0 && fillSelf) {
      s.updateNodeData(target.id, { gen });
      id = target.id;
    } else {
      id = s.addNode(out, { ref: freeRef(), title, role: "generated", gen }, spots[k++], { source: target.id, kind: "ref" });
    }
    s.track({ key: `gen:${t.id}`, kind: "gen", remote: t.id, nodeId: id, label: fillSelf && i === 0 ? target.data.title : title, status: t.status });
  });
  // addNode 会选中新节点；回到目标上，Dock 不跟着跳走，方便接着改提示词再出
  s.select(target.id);
  s.toast(n > 1 ? `已提交 ${n} 个生成任务` : "已提交生成", "ok");
}

/* ───────────────────────── 出片到镜头 ───────────────────────── */

const RUN_STEP: Record<string, string> = { previs: "预演", identity: "身份首帧", queued: "身份首帧", final: "成片", chain: "成片" };

function ShotPanel({ node }: { node: CNode }) {
  const s = useCanvas();
  const r = useNodeResolved(node.id);
  const latest = useLatest(s);
  const [method, setMethod] = useState("keyframe");
  const [busy, setBusy] = useState(false);

  if (r.kind !== "shot") {
    return <div className="cv-dock-empty">这一镜在当前分镜里找不到了（可能重编译过），出不了片。可以从画布上拿掉它。</div>;
  }
  const shot = r.shot;
  const methods = shotMethods(s, node, shot);
  const cur = methods.find(m => m.id === method && !m.disabled) ?? methods.find(m => !m.disabled) ?? methods[0];
  const running = shotBusy(s, node.id, shot);
  const run = s.live.runs[shot.id];
  const up = s.upstream(node.id);
  const director = cur.id === "director" || cur.id === "director_rerun";
  const adminHref = `/admin?${new URLSearchParams({ novel: s.novelId, chapter: s.chapterId, page: "chapter" })}`;

  const send = async () => {
    if (!cur.run || cur.disabled) return;
    setBusy(true);
    try { await cur.run(); } catch (e) { latest.current.toast(`${cur.label}没提交上：${errText(e)}`, "err"); } finally { setBusy(false); }
  };

  return (
    <>
      <div className="cv-refs is-readonly">
        {up.map(({ node: n, edge }) => (
          <div key={n.id} className="cv-ref is-on" title={n.data.title}>
            <button type="button" className="cv-ref-pic" onClick={() => s.focusNode(n.id)}>
              <Thumb t={thumbOf(n, s.resolve(n.data.ref, n.data))} />
              {n.type === "text" && <span className="cv-ref-name">{n.data.title}</span>}
            </button>
            <span className={`cv-ref-tag k-${edge.data?.kind ?? "ref"}`}>{EDGE_LABEL[edge.data?.kind ?? "ref"]}</span>
          </div>
        ))}
        <div className="cv-refs-tip">
          {up.length ? "分镜图按本章定妆照和场景图画；连进来的图只作参考" : "镜头的人物和场面由分镜决定；脸和造型来自本章定妆照"}
        </div>
      </div>

      <div className="cv-shot-desc">
        <div className="cv-shot-meta">
          镜 {shot.order_no} · {shot.shot_size.toUpperCase()} · {(shot.duration_ms / 1000).toFixed(1)}s
          {shot.dialogue_lines > 0 && ` · 对白 ${shot.dialogue_lines} 句`}
          {shot.video_url && <em className="cv-tag ok">已出片</em>}
        </div>
        <p>{shot.description || "（这一镜没有描述）"}</p>
        <a className="cv-shot-hint" href={adminHref} target="_blank" rel="noreferrer">镜头内容来自分镜，去后台工作台改 ↗</a>
      </div>

      {running && (
        <div className="cv-dock-notes is-progress">
          <Spinner size={12} />
          出片中{run ? ` · ${RUN_STEP[run.step] ?? run.step}${run.percent != null ? ` ${Math.round(run.percent)}%` : ""}` : ""}
          {run?.error && <span className="cv-note-err">{run.error}</span>}
        </div>
      )}

      <div className="cv-dock-bottom">
        <div className="cv-seg cv-seg-methods">
          {methods.map(m => (
            <button key={m.id} type="button" className={`${m.id === cur.id ? "is-on" : ""}${m.disabled ? " is-off" : ""}`}
              aria-disabled={!!m.disabled} title={m.disabled || m.title}
              onClick={() => { if (!m.disabled) setMethod(m.id); }}>
              {m.label}
            </button>
          ))}
        </div>
        <span className="cv-dock-spacer" />
        <span className="cv-estimate">{director ? "本机 · 免费 · 约 8 分钟" : cur.id === "keyframe" ? "本机 · 免费 · 约 1–2 分钟" : cur.id === "keyframe_video" ? "本机 · 免费 · 约 4–6 分钟" : "本机 · 免费"}</span>
        <SendButton busy={busy} off={running ? "这一镜正在出片，等它跑完" : cur.disabled || false} onClick={() => void send()}
          label={running ? "出片中…" : undefined} />
      </div>
    </>
  );
}

/* ───────────────────────── 对白模说话 ───────────────────────── */

const BOX_SUGGEST = ["加一台从背后跟拍的机位", "人物从画面左边走到右边", "把光改成黄昏", "镜头时长改成 8 秒"];

function BoxPanel({ node, drafts }: { node: CNode; drafts: Map<string, PromptSeg[]> }) {
  const s = useCanvas();
  const r = useNodeResolved(node.id);
  const latest = useLatest(s);
  const ed = useRef<PromptEditorHandle>(null);
  const [segs, setSegs] = useState<PromptSeg[]>(() => drafts.get(node.id) ?? []);
  const [busy, setBusy] = useState(false);
  const box = r.kind === "box_project" ? r.box : null;
  const boxId = node.data.ref.kind === "box_project" ? node.data.ref.id : null;
  const running = !!box?.active_run || s.tasks.some(t => t.nodeId === node.id && t.kind === "box_agent" && taskOpen(t));
  const text = segsToPrompt(segs);
  const objects = box?.doc?.objects.length;
  const cams = box?.cameras?.length ?? box?.doc?.cameras.length;
  const off: string | false = !boxId || !box ? "白模找不到了" : running ? "智能体正在改这个白模" : !text ? "先说说要怎么改" : false;

  const send = async () => {
    if (off || busy || !boxId) return;
    setBusy(true);
    try {
      await askBox(latest.current, node.id, boxId, text);
      drafts.delete(node.id);
      ed.current?.clear();
    } catch (e) {
      latest.current.toast(`没发出去：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const doRegenerate = async () => {
    if (running || busy || !boxId) return;
    setBusy(true);
    try {
      await regenerateBox(latest.current, node, text || undefined);
      if (text) {
        drafts.delete(node.id);
        ed.current?.clear();
      }
    } catch (e) {
      latest.current.toast(`重新搭景失败：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="cv-box-sub">
        <span>{box?.title ?? node.data.title}</span>
        {objects != null && <span>{objects} 个物体</span>}
        {cams != null && <span>{cams} 台机位</span>}
        {box?.duration != null && <span>{box.duration.toFixed(1)}s</span>}
        {running && <span className="cv-tag warn"><Spinner size={10} /> 搭景中</span>}
      </div>
      <div className="cv-suggest">
        {BOX_SUGGEST.map(t => (
          <button key={t} type="button" onMouseDown={e => e.preventDefault()} onClick={() => ed.current?.insertText(t)}>{t}</button>
        ))}
      </div>
      <PromptEditor
        ref={ed}
        docKey={node.id}
        value={segs}
        onChange={v => { setSegs(v); drafts.set(node.id, v); }}
        placeholder="跟 3D-BOX 智能体说要怎么改：加人、挪站位、换机位、改动作…（⌘Enter 发送）"
        disabled={!boxId}
        onSubmit={() => void send()}
      />
      <div className="cv-dock-bottom">
        <button
          type="button"
          className="cv-btn-sub"
          disabled={busy || running || !boxId}
          onClick={() => void doRegenerate()}
          title="按镜头剧本让智能体重新搭景（若在上方写了要求，会一并带入）"
        >
          <span style={{ marginRight: 4 }}>↻</span>
          {text ? "按要求重新搭景" : "按镜头重新搭景"}
        </button>
        <span className="cv-dock-spacer" />
        <span className="cv-dock-hint">改动 scene.js，改完白模自动刷新</span>
        <SendButton busy={busy} off={off} onClick={() => void send()} label={running ? "搭景中…" : undefined} />
      </div>
    </>
  );
}

/* ───────────────────────── 外壳 ───────────────────────── */

/** 顶栏底边以下、Dock 顶边以上、左右各留一点：选中的节点（连同上方工具条）要落在这块里 */
const SAFE = { top: 60, gap: 16, side: 16 };

/**
 * 选中节点后，如果它被 Dock 挡住、被顶栏压住、或者工具条伸出了屏幕，平移画布让它露出来。
 * 只在「选中谁」变化（和 Dock 展开收起）时看一次；正在拖的节点不动视口，否则节点会从鼠标底下跑掉。
 * 量的是 DOM：节点卡片、标题（卡片上方 22px）、工具条（.cv-ntb）、Dock 自己。
 */
function useKeepSelectedVisible(selectedId: string | null, collapsed: boolean) {
  const rf = useReactFlow();
  useEffect(() => {
    if (!selectedId) return;
    const timer = window.setTimeout(() => {
      const el = document.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(selectedId)}"]`);
      if (!el || el.classList.contains("dragging") || !el.classList.contains("selected")) return;
      const r = el.getBoundingClientRect();
      const tb = document.querySelector(".cv-ntb")?.getBoundingClientRect();
      const dock = document.querySelector(".cv-dock")?.getBoundingClientRect();
      const top = Math.min(r.top - 22, tb?.top ?? Infinity);
      const left = Math.min(r.left, tb?.left ?? Infinity);
      const right = Math.max(r.right, tb?.right ?? -Infinity);
      const floor = (dock ? dock.top : window.innerHeight - 80) - SAFE.gap;
      let dy = 0;
      if (r.bottom > floor) dy = floor - r.bottom;
      // 节点比可用高度还高时，宁可让底部被挡，也要让标题和工具条露出来
      if (top + dy < SAFE.top) dy = SAFE.top - top;
      let dx = 0;
      if (left < SAFE.side) dx = SAFE.side - left;
      else if (right > window.innerWidth - SAFE.side) dx = Math.max(window.innerWidth - SAFE.side - right, SAFE.side - left);
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      const vp = rf.getViewport();
      void rf.setViewport({ x: vp.x + dx, y: vp.y + dy, zoom: vp.zoom }, { duration: 280 });
    }, 480); // 等 Dock 和工具条挂上、量得到尺寸；错开单击后紧跟的拖动，也等搜索「飞过去」的动画（450ms）走完
    return () => window.clearTimeout(timer);
  }, [selectedId, collapsed, rf]);
}

export function Dock({manualRequest}:{manualRequest?:{id:string;revision:number;manual?:boolean}|null}) {
  const s = useCanvas();
  const node = s.selected;
  const mode = node ? modeOf(node) : null;
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const [opts, setOptsState] = useState<GenOpts>(loadOpts);
  const [tabs, setTabs] = useState<Record<string, "shot" | "free">>({});
  // 每个目标节点的提示词草稿（note/prompt 节点直接写回 data.text，不进这里）
  const drafts = useRef(new Map<string, PromptSeg[]>()).current;
  useEffect(()=>{if(manualRequest){setCollapsed(false);saveCollapsed(false);setTabs(t=>({...t,[manualRequest.id]:manualRequest.manual?'free':'shot'}));}},[manualRequest]);

  const setOpts = (p: Partial<GenOpts>) => setOptsState(prev => {
    const next = { ...prev, ...p };
    saveOpts(next);
    return next;
  });
  const toggle = () => setCollapsed(c => { saveCollapsed(!c); return !c; });
  useKeepSelectedVisible(s.selectedId, collapsed);

  if(node?.data.comic) return <ComicDock key={node.id} node={node}/>;
  if(node?.data.recipe?.op==='concat')return <ConcatPanel key={node.id} node={node}/>;
  if (!node || !mode || !s.selectedId) return null;
  const tab = mode === "shot" ? tabs[node.id] ?? "shot" : null;
  const title = mode === "box" ? "对白模说话" : mode === "shot" ? null : "自由生成";

  if (collapsed) {
    return (
      <div className="cv-dock is-collapsed cv-glass" role="region" aria-label="生成面板">
        <button type="button" className="cv-dock-bar" onClick={toggle} title="展开生成面板">
          <span className="cv-dock-glyph">{GLYPH[node.type ?? "text"]}</span>
          <span>{title ?? (tab === "free" ? "自由生成" : "出片到镜头")}</span>
          <b>{node.data.title}</b>
          <Icon name="up" size={16} />
        </button>
      </div>
    );
  }

  return (
    <div className="cv-dock cv-glass" role="region" aria-label="生成面板" onWheel={e => e.stopPropagation()}>
      <div className="cv-dock-head">
        {mode === "shot" ? (
          <div className="cv-seg">
            <button type="button" className={tab === "shot" ? "is-on" : ""} onClick={() => setTabs(t => ({ ...t, [node.id]: "shot" }))}
              title="导演链或文字出片，结果挂回这一镜">出片到镜头</button>
            <button type="button" className={tab === "free" ? "is-on" : ""} onClick={() => setTabs(t => ({ ...t, [node.id]: "free" }))}
              title="自由生成候选，长在镜头右边，不替换这一镜的视频">自由生成</button>
          </div>
        ) : <div className="cv-dock-title">{title}</div>}
        <span className="cv-dock-target" title={node.data.title}>
          <span className="cv-dock-glyph">{GLYPH[node.type ?? "text"]}</span>{node.data.title}
        </span>
        <span className="cv-dock-spacer" />
        <button type="button" className="cv-ibtn" onClick={toggle} title="收起成一条"><Icon name="down" size={16} /></button>
      </div>
      {mode === "box" ? <BoxPanel key={node.id} node={node} drafts={drafts} />
        : mode === "shot" && tab === "shot" ? <ShotPanel key={node.id} node={node} />
          : <GenPanel key={node.id} node={node} opts={opts} setOpts={setOpts} drafts={drafts} />}
    </div>
  );
}
