/**
 * 3D-BOX 预演编辑器：场景调度／成片预演两种模式。
 *
 * 场景以脚本为准（智能体写、人也能在源码页改）；台上的拖动、改色、机位关键帧、剪辑切点
 * 存成覆盖层，脚本重跑后按 id 叠回去。撤销重做管的是覆盖层；脚本改动在版本历史里回退。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CamKey, Overrides, Vec3 } from "../scene/types";
import { SceneEval, keyFromWorld, localPose } from "../scene/evaluate";
import { box, type Catalog, type Project, type Sketch } from "./api";
import { Clock } from "./clock";
import { EditorView, type EditorApi, type Sel } from "./EditorView";
import { CameraView, recordCanvas, type CameraViewHandle } from "./CameraView";
import { Timeline } from "./Timeline";
import { SidePanel } from "./SidePanel";
import { ChatPanel } from "./ChatPanel";
import { SketchLayer, type Stroke2D } from "./SketchLayer";
import { mergeKeys } from "./presets";

type Mode = "edit" | "preview";

export default function BoxEditor({ id, onBack }: { id: string; onBack: () => void }) {
  const [project, setProject] = useState<Project | null>(null);
  const [overrides, setOv] = useState<Overrides>({});
  const undo = useRef<{ o: Overrides; note: string }[]>([]);
  const redo = useRef<{ o: Overrides; note: string }[]>([]);
  const [mode, setMode] = useState<Mode>("edit");
  const [sel, setSel] = useState<Sel | null>(null);
  const [gizmo, setGizmo] = useState<"translate" | "rotate" | "scale">("translate");
  const [sketching, setSketching] = useState(false);
  const [sketches, setSketches] = useState<Sketch[]>([]);
  const [tab, setTab] = useState<"assets" | "props" | "code">("assets");
  const [chatOpen, setChatOpen] = useState(true);
  const [models, setModels] = useState<{ model: string; default: boolean }[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [fitKey, setFitKey] = useState(0);
  const [msg, setMsg] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const clock = useMemo(() => new Clock(), []);
  const editorApi = useRef<EditorApi | null>(null);
  const pip = useRef<CameraViewHandle | null>(null);
  const big = useRef<CameraViewHandle | null>(null);
  const saveTimer = useRef(0);

  const load = useCallback(async () => {
    const p = await box.get(id);
    setProject(p);
    setOv(p.overrides ?? {});
    return p;
  }, [id]);

  useEffect(() => {
    load().then(() => setFitKey(k => k + 1)).catch(e => setMsg(String(e)));
    box.models().then(setModels).catch(() => setModels([]));
    box.catalog().then(setCatalog).catch(() => setCatalog(null));
  }, [load]);

  const doc = project?.doc ?? null;
  const ev = useMemo(() => (doc ? new SceneEval(doc) : null), [doc]);
  useEffect(() => { if (doc) { clock.duration = doc.duration; if (clock.t > doc.duration) clock.seek(doc.duration); } }, [doc, clock]);

  /** 改覆盖层：先记撤销，再防抖存盘（存盘回来的是重新编译过的场景） */
  const setOverrides = useCallback((o: Overrides, note: string) => {
    setOv(prev => { undo.current.push({ o: prev, note }); redo.current = []; return o; });
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      box.overrides(id, o).then(p => { setProject(p); setMsg(note); }).catch(e => setMsg(`保存失败：${(e as Error).message}`));
    }, 250);
  }, [id]);

  const doUndo = useCallback(() => {
    const last = undo.current.pop();
    if (!last) return;
    setOv(cur => { redo.current.push({ o: cur, note: last.note }); return last.o; });
    box.overrides(id, last.o).then(p => { setProject(p); setMsg(`撤销：${last.note}`); });
  }, [id]);
  const doRedo = useCallback(() => {
    const next = redo.current.pop();
    if (!next) return;
    setOv(cur => { undo.current.push({ o: cur, note: next.note }); return next.o; });
    box.overrides(id, next.o).then(p => { setProject(p); setMsg(`重做：${next.note}`); });
  }, [id]);

  // ── 编辑动作 ──

  const onObjectEdit = useCallback((oid: string, t: { pos: Vec3; rot: Vec3; scale: Vec3 }) => {
    if (!doc || !ev) return;
    const o = doc.objects.find(x => x.id === oid);
    if (!o) return;
    const objs = { ...(overrides.objects ?? {}) };
    if (o.track?.keys.length) {
      // 有动画的物体：拖到哪，整条路线平移多少（覆盖层的 pos 是路线起点）
      const now = localPose(o, clock.t).pos;
      const first = o.track.keys[0].pos ?? o.transform.pos;
      const d: Vec3 = [t.pos[0] - now[0], t.pos[1] - now[1], t.pos[2] - now[2]];
      objs[oid] = { ...(objs[oid] ?? {}), pos: [first[0] + d[0], first[1] + d[1], first[2] + d[2]].map(v => +v.toFixed(3)) as Vec3, scale: t.scale };
    } else {
      objs[oid] = { ...(objs[oid] ?? {}), pos: t.pos, rot: t.rot, scale: t.scale };
    }
    setOverrides({ ...overrides, objects: objs }, `调整 ${o.name}`);
  }, [doc, ev, overrides, setOverrides, clock]);

  const onKeyEdit = useCallback((camId: string, index: number, pos: Vec3) => {
    if (!doc || !ev) return;
    const cam = doc.cameras.find(c => c.id === camId);
    if (!cam) return;
    const keys: CamKey[] = cam.keys.map((k, i) => (i === index ? keyFromWorld(ev, k, pos) : k));
    const cams = { ...(overrides.cameras ?? {}) };
    cams[camId] = { ...(cams[camId] ?? {}), keys };
    setOverrides({ ...overrides, cameras: cams }, `拖动 ${cam.name} 第 ${index + 1} 个关键帧`);
  }, [doc, ev, overrides, setOverrides]);

  const applyViewToCamera = useCallback(() => {
    if (!doc || !sel || sel.kind === "object") return;
    const cam = doc.cameras.find(c => c.id === sel.id);
    const v = editorApi.current?.view();
    if (!cam || !v) return;
    const t = +clock.t.toFixed(2);
    const cams = { ...(overrides.cameras ?? {}) };
    cams[cam.id] = { ...(cams[cam.id] ?? {}), keys: mergeKeys(cam.keys, [{ t, at: v.pos.map(x => +x.toFixed(2)) as Vec3, look: v.look.map(x => +x.toFixed(2)) as Vec3 }]) };
    setOverrides({ ...overrides, cameras: cams }, `${cam.name} 在 ${t}s 用当前视角`);
  }, [doc, sel, overrides, setOverrides, clock]);

  const runCode = useCallback(async (code: string) => {
    const p = await box.writeFile(id, "scene.js", code);
    setProject(p);
    setMsg(p.diagnostics.ok ? "脚本已运行" : `脚本有 ${p.diagnostics.errors.length} 处错误`);
  }, [id]);

  const addPrefab = useCallback(async (kind: "prefab" | "character" | "camera", name: string, zh: string) => {
    if (!project) return;
    const v = editorApi.current?.view();
    const look = v?.look ?? [0, 0, 0];
    const at = `[${look[0].toFixed(1)}, ${look[2].toFixed(1)}]`;
    const code = project.files["scene.js"] ?? "";
    const n = (code.match(new RegExp(zh, "g"))?.length ?? 0) + 1;
    let line: string;
    if (kind === "character") line = `S.character("${zh}${n}", { body: "${name}", at: ${at} });`;
    else if (kind === "camera") {
      const pos = v ? `[${v.pos.map(x => x.toFixed(1)).join(", ")}]` : "[0, 2, 10]";
      const lk = v ? `[${v.look.map(x => x.toFixed(1)).join(", ")}]` : "[0, 1, 0]";
      line = `const 机位${n} = S.camera("机位${n}", { lens: 35 });\nS.cameraKeys(机位${n}, [{ t: ${clock.t.toFixed(1)}, at: ${pos}, look: ${lk} }]);`;
    } else line = `S.add("${name}", { name: "${zh}${n}", at: ${at} });`;
    await runCode(`${code.trimEnd()}\n\n// 手动添加\n${line}\n`);
    setAddOpen(false);
  }, [project, runCode, clock]);

  const exportVideo = useCallback(async () => {
    if (!doc) return;
    setMode("preview");
    await new Promise(r => setTimeout(r, 400));
    const canvas = big.current?.canvas;
    if (!canvas) { setMsg("成片画布还没准备好"); return; }
    try {
      setMsg("录制中 0%…");
      const blob = await recordCanvas(canvas, clock, doc.fps, u => setMsg(`录制中 ${Math.round(u * 100)}%…`));
      setMsg("上传中…");
      const r = await box.exportFile(id, blob, { duration: doc.duration, kind: "preview" }, `${project?.title ?? "预演"}.webm`);
      canvas.toBlob(b => { if (b) box.exportFile(id, b, { kind: "thumb" }, "thumb.png").catch(() => {}); });
      setMsg(`已导出：${r.url}`);
      window.open(r.url.replace(/^https?:\/\/[^/]+/, ""), "_blank");
    } catch (e) {
      setMsg(`导出失败：${(e as Error).message}`);
    }
  }, [doc, clock, id, project]);

  const saveThumb = useCallback(() => {
    const c = pip.current?.canvas;
    if (c) c.toBlob(b => { if (b) box.exportFile(id, b, { kind: "thumb" }, "thumb.png").catch(() => {}); });
  }, [id]);

  const confirmSketch = useCallback((strokes: Stroke2D[]) => {
    const api = editorApi.current;
    const out: Sketch[] = [];
    for (const s of strokes) {
      const pts = s.points.map(([u, v]) => api?.ground(u, v)).filter((p): p is [number, number] => !!p);
      if (pts.length) out.push({ tool: s.tool, color: s.color, points: pts.map(([x, z]) => [+x.toFixed(2), +z.toFixed(2)]) });
    }
    setSketches(x => [...x, ...out]);
    setSketching(false);
    setChatOpen(true);
    setMsg(out.length ? `草图 ${out.length} 笔已投到地面，在对话里告诉智能体它是什么` : "没有画在地面上的笔画");
  }, []);

  // ── 快捷键 ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) doRedo(); else doUndo(); return; }
      if (e.key === " ") { e.preventDefault(); clock.toggle(); }
      else if (e.key === "w" || e.key === "W") setGizmo("translate");
      else if (e.key === "e" || e.key === "E") setGizmo("rotate");
      else if (e.key === "r" || e.key === "R") setGizmo("scale");
      else if (e.key === "c" || e.key === "C") applyViewToCamera();
      else if (e.key === "f" || e.key === "F") setFitKey(k => k + 1);
      else if (e.key === "Escape") { if (sketching) setSketching(false); else setSel(null); }
      else if (e.key === "Tab") { e.preventDefault(); setMode(m => (m === "edit" ? "preview" : "edit")); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clock, doUndo, doRedo, applyViewToCamera, sketching]);

  if (!project || !doc || !ev) {
    return <div className="box-editor"><div className="empty-state">{msg || "载入场景…"}</div></div>;
  }
  const selLabel = !sel ? "" : sel.kind === "object"
    ? doc.objects.find(o => o.id === sel.id)?.name ?? sel.id
    : `${doc.cameras.find(c => c.id === sel.id)?.name ?? sel.id}${sel.kind === "key" ? ` 第 ${sel.index + 1} 帧` : ""}（机位）`;
  const d = project.diagnostics;

  return (
    <div className="box-editor">
      <header className="box-top">
        <button className="ghost" onClick={onBack} title="回到项目列表">←</button>
        {editingTitle
          ? <input className="title-input" autoFocus defaultValue={project.title}
              onBlur={e => { setEditingTitle(false); if (e.target.value.trim() && e.target.value !== project.title) box.patch(id, { title: e.target.value }).then(setProject); }}
              onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
          : <b className="title" onClick={() => setEditingTitle(true)} title="点击改名">{project.title}</b>}
        <div className="seg mode">
          <button className={mode === "edit" ? "on" : ""} onClick={() => setMode("edit")}>⚲ 场景调度</button>
          <button className={mode === "preview" ? "on" : ""} onClick={() => setMode("preview")}>▣ 成片预演</button>
        </div>
        <div className="tools">
          <div className="add-wrap">
            <button onClick={() => setAddOpen(o => !o)} title="添加">＋</button>
            {addOpen && catalog && (
              <div className="add-menu" onMouseLeave={() => setAddOpen(false)}>
                <div className="grp">
                  <b>机位</b><button onClick={() => addPrefab("camera", "", "机位")}>用当前视角新建机位</button>
                </div>
                <div className="grp">
                  <b>人物</b>{catalog.bodies.map(bd => <button key={bd.name} onClick={() => addPrefab("character", bd.name, bd.zh)}>{bd.zh}</button>)}
                </div>
                {["建筑", "街道", "交通", "自然", "室内", "道具", "动物", "标记"].map(cat => (
                  <div key={cat} className="grp"><b>{cat}</b>
                    {catalog.prefabs.filter(pf => pf.category === cat).map(pf => (
                      <button key={pf.name} title={pf.doc} onClick={() => addPrefab("prefab", pf.name, pf.zh)}>{pf.zh}</button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
          <button onClick={doUndo} disabled={!undo.current.length} title="撤销 ⌘Z">↶</button>
          <button onClick={doRedo} disabled={!redo.current.length} title="重做 ⇧⌘Z">↷</button>
          {mode === "edit" && (
            <div className="seg gz">
              {([["translate", "移"], ["rotate", "转"], ["scale", "缩"]] as const).map(([k, l]) => (
                <button key={k} className={gizmo === k ? "on" : ""} onClick={() => setGizmo(k)} title={`${l}（${k === "translate" ? "W" : k === "rotate" ? "E" : "R"}）`}>{l}</button>
              ))}
            </div>
          )}
          {mode === "edit" && <button className={sketching ? "on" : ""} onClick={() => setSketching(s => !s)} title="手绘标注">✎ 标注</button>}
        </div>
        <div className="spacer" />
        <span className={`stat ${d.ok ? "" : "bad"}`}>{d.ok ? `✓ ${d.summary?.objects ?? 0} 个物体 · ${doc.cameras.length} 台机位 · ${doc.duration}s` : `✗ 脚本有错（${d.errors[0]?.line ? `第 ${d.errors[0].line} 行` : ""}）`}</span>
        <button className="primary" onClick={exportVideo} title="按主机位时间表录成视频">⇪ 导出</button>
      </header>

      <div className={`box-main${chatOpen ? "" : " chat-closed"}`}>
        <ChatPanel projectId={id} activeRun={project.active_run}
          selected={sel ? [sel.id] : []} selectedLabel={selLabel} onClearSelected={() => setSel(null)}
          sketches={sketches} onClearSketches={() => setSketches([])}
          onScene={() => { load(); }} onDone={() => { load().then(() => setTimeout(saveThumb, 800)); }}
          models={models} collapsed={!chatOpen} onToggle={() => setChatOpen(o => !o)} />

        <section className="box-view">
          {mode === "edit" ? (
            <>
              <EditorView doc={doc} ev={ev} clock={clock} sel={sel} onSelect={s => { setSel(s); if (s) setTab("props"); }}
                gizmo={gizmo} onObjectEdit={onObjectEdit} onKeyEdit={onKeyEdit} fitKey={fitKey} sketches={sketches} apiRef={editorApi} />
              {sketching && <SketchLayer onCancel={() => setSketching(false)} onConfirm={confirmSketch} />}
              <div className="pip">
                <CameraView doc={doc} ev={ev} clock={clock} handle={pip} />
                <button className="pip-go" onClick={() => setMode("preview")} title="成片预演">⤢</button>
              </div>
              <div className="view-hint">左键转 · 右键平移 · 滚轮缩放 · 点物体选中 · W/E/R 移/转/缩 · C 当前视角进机位 · F 适配 · 空格播放</div>
            </>
          ) : (
            <div className="preview-stage">
              <CameraView doc={doc} ev={ev} clock={clock} handle={big} className="big" />
            </div>
          )}
          {msg && <div className="box-msg" onClick={() => setMsg("")}>{msg}</div>}
        </section>

        <SidePanel project={project} doc={doc} ev={ev} clock={clock} sel={sel} onSelect={setSel}
          overrides={overrides} setOverrides={setOverrides} editorApi={editorApi}
          onRunCode={runCode} onRestore={async i => { setProject(await box.restore(id, i)); }} tab={tab} setTab={setTab} />
      </div>

      <Timeline doc={doc} clock={clock} sel={sel} onSelect={s => { setSel(s); setTab("props"); }} />
    </div>
  );
}
