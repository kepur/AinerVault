import { ComicLibrary } from "./ComicPanel";
/**
 * 资产抽屉（左侧 340px）：角色 / 媒体 / 白模三页，点一下放到画布上；画布上已经有了就飞过去。
 *
 * 开关状态放在模块里（契约没有这一项）：底栏的「资产管理」按钮调 toggleAssets()。
 * 角色视角图按引用放（entity_view，派生节点，铁律 1）；媒体按 asset 放（已落库的 /media 地址，铁律 2）。
 */
import { hrefFor, navigate, readCtx } from "../../ctx";
import { useEffect, useState, useSyncExternalStore } from "react";
import type { ProjectRow } from "../../box/api";
import { prod, viewRef, viewSrc, SHEET_SECTIONS, VIEW_LABELS, type ResourceItem, type EpochOption, type CanonicalPack } from "../../production/api";
import { cv, media, missing, type MediaItem } from "../api";
import { comicRequest } from "../../workbench/api";
import { nodeIdOf, type CNodeData, type NodeKind, type NodeRef } from "../model";
import { useCanvas } from "../store";
import { errText, Icon, Spinner, useLatest } from "./Overlays";

let open = false;
const subs = new Set<() => void>();
export function setAssetsOpen(v: boolean) {
  if (open === v) return;
  open = v;
  subs.forEach(f => f());
}
export function toggleAssets() { setAssetsOpen(!open); }
export function useAssetsOpen(): boolean {
  return useSyncExternalStore(cb => { subs.add(cb); return () => { subs.delete(cb); }; }, () => open);
}

type Tab = "cast" | "media" | "box";

const VIEWS: { key: string; label: string }[] = [
  { key: "front", label: "正面" },
  { key: "three_quarter_left", label: "3/4 侧" },
  { key: "profile_left", label: "侧面" },
  { key: "back", label: "背面" },
  { key: "bust", label: "半身" },
  { key: "sheet", label: "设定图" },
];

/** 已经在画布上就飞过去，否则在视口中心放一个新节点并选中 */
function useCommit() {
  const s = useCanvas();
  const latest = useLatest(s);
  return (type: NodeKind, data: CNodeData) => {
    const st = latest.current;
    const id = nodeIdOf(data.ref);
    const existing = st.nodes.find(n => nodeIdOf(n.data.ref) === id);
    if (existing) {
      st.focusNode(existing.id);
      st.select(existing.id);
      return;
    }
    st.addNode(type, data);
    if (data.ref.kind === "box_project") void st.loadBoxDoc(data.ref.id, true);
  };
}

function LegacyCastTab() {
  const s = useCanvas();
  const commit = useCommit();
  const onCanvas = new Set(s.nodes.map(n => n.id));
  if (!s.live.cast.length) {
    return <div className="cv-drawer-empty">这份分镜还没有出场角色（或角色还没出定妆照）。角色在后台的角色库里建。</div>;
  }
  return (
    <div className="cv-cast">
      {s.live.cast.map(m => {
        const views = VIEWS.filter(v => m.views[v.key]);
        return (
          <div key={m.entity_id} className="cv-cast-row">
            <div className="cv-cast-head">
              <b>{m.name}</b>
              {m.epoch && <em className="cv-tag">{m.epoch}</em>}
              <span>{m.shots} 镜</span>
            </div>
            {views.length ? (
              <div className="cv-cast-views">
                {views.map(v => {
                  const ref: NodeRef = { kind: "entity_view", id: m.entity_id, view: v.key };
                  const here = onCanvas.has(nodeIdOf(ref));
                  const sheet = v.key === "sheet";
                  return (
                    <button key={v.key} type="button" className={`cv-cast-view${sheet ? " is-sheet" : ""}${here ? " is-here" : ""}`}
                      title={here ? `${v.label}：已在画布上，点一下飞过去` : `${v.label}：放到画布上`}
                      onClick={() => commit("image", {
                        ref,
                        title: sheet ? `多角度定妆照 · ${m.name}` : `定妆照 · ${m.name} · ${v.label}`,
                        role: sheet ? "sheet" : "view",
                      })}>
                      <img src={media(m.views[v.key])} alt="" loading="lazy" draggable={false} />
                      <span>{v.label}</span>
                    </button>
                  );
                })}
              </div>
            ) : <div className="cv-drawer-note">还没有定妆照（去角色库生成）</div>}
          </div>
        );
      })}
      <a className="cv-drawer-link" href={hrefFor("characters")}
        onClick={e => { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); navigate("characters"); } }}>
        角色外观在角色库的造型室里改 ↗
      </a>
    </div>
  );
}

function LegacyMediaTab() {
  const s = useCanvas();
  const commit = useCommit();
  const [items, setItems] = useState<MediaItem[] | null>(null);
  const [err, setErr] = useState("");
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!s.novelId) { setItems([]); return; }
    let alive = true;
    setItems(null);
    setErr("");
    cv.media(s.novelId).then(
      r => { if (alive) setItems(r); },
      e => { if (alive) { setItems([]); setErr(missing(e) ? "后端没有媒体列表接口" : `媒体拉不下来：${errText(e)}`); } },
    );
    return () => { alive = false; };
  }, [s.novelId, nonce]);

  if (items === null) return <div className="cv-drawer-empty"><Spinner /> 载入中…</div>;
  if (err) return <div className="cv-drawer-empty">{err}<button type="button" className="cv-link" onClick={() => setNonce(n => n + 1)}>重试</button></div>;
  if (!items.length) return <div className="cv-drawer-empty">这本小说还没有媒体文件</div>;

  const groups = new Map<string, MediaItem[]>();
  for (const it of items) {
    const g = it.use_cn || it.use || "其他";
    groups.set(g, [...(groups.get(g) ?? []), it]);
  }
  const onCanvas = new Set(s.nodes.map(n => n.id));
  return (
    <div className="cv-media">
      {[...groups].map(([g, list]) => (
        <section key={g}>
          <h4>{g}<span>{list.length}</span></h4>
          <div className="cv-media-grid">
            {list.map(it => {
              const isVideo = it.kind === "video" || !!it.mime?.startsWith("video/");
              const isImage = it.kind === "image" || !!it.mime?.startsWith("image/");
              const ref: NodeRef = { kind: "asset", id: it.id };
              const here = onCanvas.has(nodeIdOf(ref));
              const name = it.label || it.asset_name || it.speaker || it.use_cn || "素材";
              const url = media(it.url) ?? it.url;
              const off = !isVideo && !isImage ? "画布还没有音频节点" : false;
              return (
                <button key={it.id} type="button" className={`cv-media-item${here ? " is-here" : ""}${off ? " is-off" : ""}`}
                  aria-disabled={!!off} title={off || (here ? `${name}：已在画布上` : `${name}：放到画布上`)}
                  onClick={() => {
                    if (off) return;
                    commit(isVideo ? "video" : "image", {
                      ref, title: name, role: isVideo ? "generated" : "upload",
                      media: { url, asset_id: it.id, mime: it.mime ?? (isVideo ? "video/mp4" : null) },
                    });
                  }}>
                  {isImage ? <img src={url} alt="" loading="lazy" draggable={false} />
                    : isVideo ? <video src={`${url}#t=0.05`} muted playsInline preload="metadata" />
                      : <span className="cv-media-audio"><Icon name="mic" size={18} /></span>}
                  {isVideo && <span className="cv-media-play"><Icon name="play" size={10} /></span>}
                  <span className="cv-media-name">{name}</span>
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

/** 真实工作区素材的分页入口，独立画布无需绑定小说。 */
function LibraryTab({ mediaOnly = false }: { mediaOnly?: boolean }) {
  const s = useCanvas();
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [query, setQuery] = useState("");
  const [comicAssets,setComicAssets]=useState<Set<string>>(new Set());
  const [scopeReady,setScopeReady]=useState(!mediaOnly);
  const commit = useCommit();
  const boardId = s.boardId;
  const load = async (offset = 0) => {
    if (!boardId) return;
    setBusy(true); setErr("");
    try {
      const result = await prod.resources(boardId, mediaOnly ? "asset" : "entity", offset);
      setItems(cur => offset ? [...cur, ...result.data.items] : result.data.items);
      setNext(result.data.next_offset);
    } catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    let alive = true;
    setItems([]); setNext(null); setErr("");
    if (!boardId) return;
    setBusy(true);
    prod.resources(boardId, mediaOnly ? "asset" : "entity").then(result => {
      if (!alive) return;
      setItems(result.data.items); setNext(result.data.next_offset);
    }).catch(e => { if (alive) setErr(errText(e)); }).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [boardId, mediaOnly]);
  useEffect(()=>{
    let alive=true;
    if(!mediaOnly){setScopeReady(true);return;}
    setScopeReady(false);
    comicRequest<{items:{asset_id:string;medium:string}[]}>('/studio/v1/productions/asset-ownership').then(d=>{
      if(alive){setComicAssets(new Set(d.items.filter(a=>a.medium==='comic').map(a=>a.asset_id)));setScopeReady(true);}
    }).catch(()=>{if(alive)setErr('素材版本检查未连接，请启动本地漫剧执行层后重开素材库。');});
    return()=>{alive=false;};
  },[boardId,mediaOnly]);
  if (!boardId) return <div className="cv-drawer-empty">先打开或新建一张画布，再引用素材。</div>;
  const filtered = items.filter(it => (readCtx().workspace!=='free'||!it.resource?.novel_id) && (!mediaOnly || !comicAssets.has(it.ref.id)) && (!query || [it.resource?.name, it.resource?.screen_name, it.ref.id].some(v => v?.toLowerCase().includes(query.toLowerCase()))));
  return <div className="cv-library">
    <div className="cv-drawer-note">{s.board?.novel_id ? "当前小说的素材" : "自由创作的独立素材"}</div>
    <input className="cv-input" aria-label="筛选已载入素材" placeholder="筛选已载入的名称或编号" value={query} onChange={e => setQuery(e.target.value)} />
    {err && <div className="cv-drawer-note" role="alert">{err}<button className="cv-link" type="button" onClick={() => void load()}>重试</button></div>}
    {!items.length && !busy && !err && <div className="cv-drawer-empty">还没有素材。可上传文件，或到角色库创建。</div>}
    {filtered.map(it => {
      const resource = it.resource;
      if (!resource) return null;
      if (!mediaOnly) return <EntityAssets key={it.ref.id} item={it} />;
      const src = resource.media?.url ? media(resource.media.url) : null;
      const kind = resource.kind;
      const supported = scopeReady && ["image", "video", "audio"].includes(kind || "") && !!src;
      return <button key={it.ref.id} className="cv-box-row" type="button" disabled={!supported}
        title={supported ? "引用到画布，保留素材版本" : "该文件暂不能作为画布节点"}
        onClick={() => { if (supported) commit(kind as NodeKind, { ref: it.ref, title: resource.name || it.ref.id, role: kind === "image" ? "upload" : undefined }); }}>
        {kind === "image" && src ? <img src={src} alt="" loading="lazy" /> : <span className="cv-box-ph"><Icon name={kind === "audio" ? "mic" : "image"} size={18} /></span>}
        <span className="cv-box-main"><b>{resource.name || it.ref.id}</b><span>{kind} · {resource.novel_id ? "小说素材" : "独立素材"}</span></span>
      </button>;
    })}
    {busy && <div className="cv-drawer-note"><Spinner size={14} /> 载入中…</div>}
    {next !== null && <button type="button" className="cv-btn" disabled={busy} onClick={() => void load(next)}>加载更多</button>}
    <a className="cv-drawer-link" href={hrefFor("characters")}>打开角色库 ↗</a>
  </div>;
}

function EntityAssets({ item }: { item: ResourceItem }) {
  const s = useCanvas();
  const commit = useCommit();
  const [expanded, setExpanded] = useState(false);
  const [epochs, setEpochs] = useState<EpochOption[]>([]);
  const [epoch, setEpoch] = useState("");
  const [pack, setPack] = useState<CanonicalPack | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!expanded) return;
    let alive = true;
    setBusy(true); setErr(""); setEpoch(""); setPack(null);
    prod.epochs(item.ref.id, s.boardId).then(r => {
      if (!alive) return;
      setEpochs(r.data.items);
      // Single unambiguous existing option may be chosen automatically; multiple periods stay explicit.
      if (r.data.items.length === 1) setEpoch(r.data.items[0].id);
    }).catch(e => { if (alive) setErr(errText(e)); }).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [expanded, item.ref.id, s.boardId]);
  useEffect(() => {
    const option = epochs.find(e => e.id === epoch);
    setPack(null);
    if (!option) return;
    let alive = true;
    setBusy(true); setErr("");
    prod.canonicalPack(item.ref.id, option.world_profile_id, option.id).then(r => {
      if (alive) setPack(r.data);
    }).catch(e => { if (alive) setErr(errText(e)); }).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [epoch, epochs, item.ref.id]);
  const name = item.resource?.screen_name || item.resource?.name || item.ref.id;
  return <section className="cv-cast-row">
    <button className="cv-btn" type="button" onClick={() => setExpanded(v => !v)}>{name}<span>{expanded ? "收起" : "选择素材"}</span></button>
    {expanded && <>
      <select className="cv-input" aria-label={`${name} 的世界与造型时期`} value={epoch} onChange={e => setEpoch(e.target.value)}>
        <option value="">选择世界观与造型时期</option>
        {epochs.map(e => <option key={e.id} value={e.id}>{e.world_name} · {e.name || e.epoch_key}</option>)}
      </select>
      {busy && <div className="cv-drawer-note"><Spinner size={14} /> 载入中…</div>}
      {err && <div className="cv-drawer-note" role="alert">{err}</div>}
      {!busy && !err && !epochs.length && <div className="cv-drawer-note">还没有已保存的造型时期。<a href={hrefFor("characters", { char: `e:${item.ref.id}` })}>去角色库创建 ↗</a></div>}
      {pack && (pack.entity_kind === "character" ? SHEET_SECTIONS : [{ title: "标准参考图", keys: Object.keys(pack.views) }]).map(section => <div key={section.title}>
        <h4>{section.title}</h4><div className="cv-cast-views">
          {section.keys.map(key => {
            const view = pack.views[key]; const src = viewSrc(view);
            return <button key={key} type="button" className="cv-cast-view" disabled={!src || !view}
              title={!src ? "缺少该视图，需在角色库生成或绑定" : view.status === "legacy_approximate" ? "旧视图近似映射，尚需审核" : "引用这个标准视图"}
              onClick={() => { if (view && src) commit("image", { ref: viewRef(pack, view), title: `${name} · ${VIEW_LABELS[key]}`, role: "view" }); }}>
              {src ? <img src={src} alt="" loading="lazy" /> : <span>缺图</span>}
              <span>{VIEW_LABELS[key]}{view?.status === "legacy_approximate" ? "（近似）" : ""}</span>
            </button>;
          })}
        </div>
      </div>)}
    </>}
  </section>;
}

function BoxTab() {
  const s = useCanvas();
  const latest = useLatest(s);
  const commit = useCommit();
  const [rows, setRows] = useState<ProjectRow[] | null>(null);
  const [err, setErr] = useState("");
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    let alive = true;
    cv.boxList().then(
      r => { if (alive) setRows(r); },
      e => { if (alive) { setRows([]); setErr(`3D-BOX 项目拉不下来：${errText(e)}`); } },
    );
    return () => { alive = false; };
  }, []);

  const create = async () => {
    setCreating(true);
    try {
      const p = await cv.boxCreate("新白模", "blank");
      commit("box3d", { ref: { kind: "box_project", id: p.id }, title: `3D 白模 · ${p.title}` });
    } catch (e) {
      latest.current.toast(`新建白模失败：${errText(e)}`, "err");
    } finally {
      setCreating(false);
    }
  };

  const onCanvas = new Set(s.nodes.map(n => n.id));
  return (
    <div className="cv-boxes">
      <button type="button" className="cv-box-new" aria-disabled={creating} onClick={() => { if (!creating) void create(); }}>
        {creating ? <Spinner size={14} /> : <Icon name="plus" size={16} />}新建空白白模
      </button>
      {rows === null ? <div className="cv-drawer-empty"><Spinner /> 载入中…</div>
        : err ? <div className="cv-drawer-empty">{err}</div>
          : !rows.length ? <div className="cv-drawer-empty">还没有 3D-BOX 项目</div>
            : rows.map(p => {
              const here = onCanvas.has(nodeIdOf({ kind: "box_project", id: p.id }));
              return (
                <button key={p.id} type="button" className={`cv-box-row${here ? " is-here" : ""}`}
                  title={here ? "已在画布上，点一下飞过去" : "放到画布上"}
                  onClick={() => commit("box3d", { ref: { kind: "box_project", id: p.id }, title: `3D 白模 · ${p.title}` })}>
                  {p.thumb_url ? <img src={media(p.thumb_url)} alt="" loading="lazy" /> : <span className="cv-box-ph"><Icon name="cube" size={20} /></span>}
                  <span className="cv-box-main">
                    <b>{p.title}</b>
                    <span>
                      {[p.objects != null ? `${p.objects} 物体` : "", `${p.cameras} 机位`, p.duration != null ? `${p.duration.toFixed(1)}s` : ""]
                        .filter(Boolean).join(" · ")}
                      {p.ok === false && <em className="cv-tag err">编译失败</em>}
                    </span>
                  </span>
                </button>
              );
            })}
    </div>
  );
}

export function AssetsDrawer() {
  const s=useCanvas(),isOpen=useAssetsOpen();
  const [tab,setTab]=useState<Tab>("cast");
  if(!isOpen || s.overlay)return null;
  const comic=readCtx().medium==="comic" || s.nodes.some(n=>n.data.comic);
  return <aside className="cv-drawer cv-glass" aria-label="资产管理" onWheel={e=>e.stopPropagation()}>
    <div className="cv-drawer-head"><b>{comic?'漫剧素材库':'资产管理'}</b><button type="button" className="cv-ibtn" title="关闭" onClick={()=>setAssetsOpen(false)}><Icon name="close" size={16}/></button></div>
    {comic?<ComicLibrary/>:<><div className="cv-seg cv-drawer-tabs">
      <button type="button" className={tab==='cast'?'is-on':''} onClick={()=>setTab('cast')}>角色与场景</button>
      <button type="button" className={tab==='media'?'is-on':''} onClick={()=>setTab('media')}>媒体</button>
      <button type="button" className={tab==='box'?'is-on':''} onClick={()=>setTab('box')}>白模</button>
    </div><div className="cv-drawer-body">{tab==='cast'?(s.demo?<LegacyCastTab/>:<LibraryTab/>):tab==='media'?(s.demo?<LegacyMediaTab/>:<LibraryTab mediaOnly/>):<BoxTab/>}</div></>}
  </aside>;
}
