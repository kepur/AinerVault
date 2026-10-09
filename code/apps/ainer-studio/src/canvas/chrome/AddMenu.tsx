/**
 * 新增节点菜单：底栏大「＋」或节点两侧的「+」打开（s.addMenu）。
 * 从节点侧边打开时（from），新节点放在那一侧并连线，连线语义和拖线一样推断（inferEdgeKind）。
 *
 * 文件选择框要等用户选完才回调，所以 <input type=file> 一直挂着（菜单关了它也在），
 * 「从哪个节点、哪一侧」在点菜单项那一刻记下来。
 */
import { useEffect, useRef, useState } from "react";
import type { ProjectRow, Template } from "../../box/api";
import { freeRef, inferEdgeKind, placeBeside } from "../actions";
import { cv, media, missing } from "../api";
import type { CanvasStore } from "../contract";
import { nodeIdOf, type CNodeData, type NodeKind } from "../model";
import { useCanvas } from "../store";
import { errText, Icon, MenuList, Popover, Spinner, useLatest, type MenuItem } from "./Overlays";

type From = { nodeId: string; side: "left" | "right" } | null;

const NEW_SIZE: Record<NodeKind, { w: number; h: number }> = {
  stage: { w: 300, h: 300 }, coverage: { w: 300, h: 300 }, audio: { w: 300, h: 110 }, text: { w: 260, h: 140 }, image: { w: 220, h: 220 }, video: { w: 280, h: 200 }, box3d: { w: 300, h: 230 }, group: { w: 520, h: 360 },
};

/**
 * 放一个新节点：有 from 就放在那一侧并连线（右侧 = from → 新；左侧 = 新 → from），否则交给 store 放视口中心。
 * 返回新节点 id（已在画布上的真身直接飞过去，返回它的 id）。
 */
function place(s: CanvasStore, type: NodeKind, data: CNodeData, from: From): string {
  const existing = nodeIdOf(data.ref);
  if (data.ref.kind !== "free" && s.nodes.some(n => n.id === existing)) {
    s.focusNode(existing);
    s.select(existing);
    return existing;
  }
  const anchor = from ? s.nodes.find(n => n.id === from.nodeId) : undefined;
  if (!anchor || !from) return s.addNode(type, data);
  const me = { type, role: data.role };
  const it = { type: anchor.type, role: anchor.data.role };
  if (from.side === "right") {
    return s.addNode(type, data, undefined, { source: anchor.id, kind: inferEdgeKind(it, me) });
  }
  const at = placeBeside(s.nodes, anchor, "left", NEW_SIZE[type])[0];
  const id = s.addNode(type, data, at);
  s.connect(id, anchor.id, inferEdgeKind(me, it));
  return id;
}

export function AddMenu() {
  const s = useCanvas();
  const latest = useLatest(s);
  const fileRef = useRef<HTMLInputElement>(null);
  const pendingFrom = useRef<From>(null);
  const [page, setPage] = useState<"main" | "box">("main");
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [projects, setProjects] = useState<ProjectRow[] | null>(null);
  const [boxErr, setBoxErr] = useState("");
  const [working, setWorking] = useState("");
  const menu = s.addMenu;

  useEffect(() => { if (!menu) setPage("main"); }, [menu]);

  // 进「3D 白模」二级页时才拉模板和项目列表
  useEffect(() => {
    if (page !== "box") return;
    let alive = true;
    setBoxErr("");
    cv.boxTemplates().then(r => { if (alive) setTemplates(r); }, () => { if (alive) setTemplates([]); });
    cv.boxList().then(r => { if (alive) setProjects(r); }, e => { if (alive) { setProjects([]); setBoxErr(errText(e)); } });
    return () => { alive = false; };
  }, [page]);

  const close = () => latest.current.closeAddMenu();
  const from: From = menu?.from ?? null;
  const fromNode = from ? s.nodes.find(n => n.id === from.nodeId) : undefined;

  const add = (type: NodeKind, data: CNodeData) => {
    place(latest.current, type, data, from);
    close();
  };

  const newBox = async (title: string, template: string) => {
    setWorking(template);
    try {
      const p = await cv.boxCreate(title, template);
      const st = latest.current;
      place(st, "box3d", { ref: { kind: "box_project", id: p.id }, title: `3D 白模 · ${p.title}` }, from);
      close();
      await st.loadBoxDoc(p.id, true);
    } catch (e) {
      latest.current.toast(`新建白模失败：${errText(e)}`, "err");
    } finally {
      setWorking("");
    }
  };

  const onFile = async (f: File) => {
    const fr = pendingFrom.current;
    try {
      const res = await cv.upload(f);
      const mime = res.mime ?? f.type;
      const isVideo = mime.startsWith("video/");
      place(latest.current, mime.startsWith("audio/") ? "audio" : isVideo ? "video" : "image", {
        ref: { kind: "asset", id: res.asset_id },
        title: f.name.replace(/\.[^.]+$/, "") || "上传",
        role: isVideo ? "generated" : "upload",
        media: { url: media(res.url) ?? res.url, asset_id: res.asset_id, mime },
      }, fr);
    } catch (e) {
      latest.current.toast(missing(e) ? "后端还没有上传接口（/api/v2/studio/uploads）" : `上传失败：${errText(e)}`, "err");
    }
  };

  const main: MenuItem[] = [
    { id: "note", label: "文本", icon: <Icon name="text" />, hint: "笔记、剧本片段", onPick: () => add("text", { ref: freeRef(), title: "文本", role: "note", text: "" }) },
    { id: "prompt", label: "提示词", icon: <Icon name="prompt" />, hint: "可 @ 上游节点", onPick: () => add("text", { ref: freeRef(), title: "提示词", role: "prompt", text: "" }) },
    {
      id: "upload", label: "图片（上传）", icon: <Icon name="upload" />, hint: "也可以传视频",
      onPick: () => { pendingFrom.current = from; fileRef.current?.click(); },
    },
    { id: "box", label: "3D 白模", icon: <Icon name="cube" />, badge: "NEW", hint: "空白 / 模板 / 已有项目", more: true, onPick: () => setPage("box") },
    {
      id: "quick", label: "快速成片", icon: <Icon name="sparkle" />, badge: "NEW", hint: "照片＋一句话",
      title: "一张人物照片＋一句想法（服装照、场景图可选）→ 定妆照 → 分镜图 → 2–4 镜短片，全部本机",
      onPick: () => latest.current.openOverlay({ kind: "quick" }),
    },
    { id: "gen_video", label: "视频生成", icon: <Icon name="video" />, onPick: () => add("video", { ref: freeRef(), title: "视频生成", role: "generated" }) },
    { id: "gen_image", label: "图片生成", icon: <Icon name="image" />, onPick: () => add("image", { ref: freeRef(), title: "图片生成", role: "generated" }) },
  ];

  const onCanvas = new Set(s.nodes.map(n => n.id));
  const boxItems: MenuItem[] = [
    {
      id: "blank", label: "新建空白", icon: working === "blank" ? <Spinner size={13} /> : <Icon name="plus" />,
      hint: "之后在生成面板里跟智能体说要搭什么",
      disabled: working ? "正在新建…" : false, onPick: () => void newBox("新白模", "blank"),
    },
  ];

  return (
    <>
      <input ref={fileRef} type="file" accept="image/*,video/*,audio/*" hidden
        onChange={e => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void onFile(f); }} />
      {menu && (
        <Popover anchor={{ x: menu.anchor.x, y: menu.anchor.y }} placement={menu.from ? "bottom-start" : "top"} offset={10}
          onClose={close} className="cv-addmenu">
          <div className="cv-pop-title">
            {page === "box"
              ? <button type="button" className="cv-pop-back" onClick={() => setPage("main")}><Icon name="left" size={14} />3D 白模</button>
              : fromNode ? <>新增并连到<span className="cv-pop-from">{from?.side === "left" ? "← " : ""}{fromNode.data.title}{from?.side === "right" ? " →" : ""}</span></>
                : "新增节点"}
          </div>
          {page === "main" ? <MenuList items={main} onPicked={close} /> : (
            <div className="cv-addmenu-box">
              <MenuList items={boxItems} />
              <div className="cv-pop-sub">从模板</div>
              {templates === null ? <div className="cv-menu-empty"><Spinner /> 载入中…</div> : (
                <MenuList empty="没有模板"
                  items={templates.map(t => ({
                    id: `tpl:${t.key}`, label: t.name, title: t.desc, hint: t.category,
                    icon: working === t.key ? <Spinner size={13} /> : <Icon name="cube" />,
                    disabled: working ? "正在新建…" : false,
                    onPick: () => void newBox(t.name, t.key),
                  }))} />
              )}
              <div className="cv-pop-sub">已有 3D-BOX 项目</div>
              {projects === null ? <div className="cv-menu-empty"><Spinner /> 载入中…</div> : (
                <MenuList empty={boxErr ? `拉不下来：${boxErr}` : "还没有项目"} onPicked={close}
                  items={projects.map(p => ({
                    id: `prj:${p.id}`, label: p.title,
                    icon: p.thumb_url ? <img className="cv-menu-thumb" src={media(p.thumb_url)} alt="" /> : <Icon name="cube" />,
                    hint: onCanvas.has(nodeIdOf({ kind: "box_project", id: p.id })) ? "已在画布" : `${p.cameras} 机位`,
                    onPick: () => {
                      const st = latest.current;
                      place(st, "box3d", { ref: { kind: "box_project", id: p.id }, title: `3D 白模 · ${p.title}` }, from);
                      void st.loadBoxDoc(p.id, true);
                    },
                  }))} />
              )}
            </div>
          )}
        </Popover>
      )}
    </>
  );
}
