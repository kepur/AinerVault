import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Clock, useClock } from "../box/clock";
import { prod, viewRef, type CanonicalPack, type EpochOption, type ResourceItem, type ResourceRef } from "./api";
import { sharedStages, stageContent, type SharedStage, type StageContent, type StageCoverage } from "./stages";
import type { SceneDoc, Vec3 } from "../scene/types";
import { useCanvas } from "../canvas/store";
import { isProductionRef } from "../canvas/model";
import { hrefFor } from "../ctx";
import "./shared-stage.css";

const Preview = lazy(() => import("../canvas/three/BoxPreview"));
const id = (kind: string) => `${kind}_${crypto.randomUUID().slice(0, 8)}`;
const transform = () => ({ position: [0, 0, 0] as Vec3, rotation: [0, 0, 0] as Vec3, scale: [1, 1, 1] as Vec3 });
const textError = (e: unknown) => e instanceof Error ? e.message : String(e);

function NumberField({ label, value, onChange, step = 0.1 }: { label: string; value: number; onChange: (n: number) => void; step?: number }) {
  return <label>{label}<input type="number" step={step} value={Number.isFinite(value) ? value : ""}
    onChange={e => { if (e.target.value !== "" && Number.isFinite(e.target.valueAsNumber)) onChange(e.target.valueAsNumber); }} /></label>;
}
function VectorField({ label, value, onChange }: { label: string; value: Vec3; onChange: (v: Vec3) => void }) {
  return <div className="ss-vector"><span>{label}</span>{["X", "Y", "Z"].map((axis, i) =>
    <NumberField key={axis} label={axis} value={value[i]} onChange={n => { const v = [...value] as Vec3; v[i] = n; onChange(v); }} />)}</div>;
}

export default function SharedStageWorkspace({ boardId, initialStageId, onClose }: { boardId: string; initialStageId?: string; onClose: () => void }) {
  const canvas = useCanvas();
  const [stages, setStages] = useState<SharedStage[]>([]);
  const [stage, setStage] = useState<SharedStage | null>(null);
  const [draft, setDraft] = useState<StageContent | null>(null);
  const [doc, setDoc] = useState<SceneDoc | null>(null);
  const [camera, setCamera] = useState<string | null>(null);
  const [selectedCoverage, setSelectedCoverage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [advanced, setAdvanced] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [entities, setEntities] = useState<ResourceItem[]>([]);
  const [entityOffset, setEntityOffset] = useState<number | null>(null);
  const [entityQuery, setEntityQuery] = useState("");
  const [entityId, setEntityId] = useState("");
  const [epochs, setEpochs] = useState<EpochOption[]>([]);
  const [epochId, setEpochId] = useState("");
  const [actorId, setActorId] = useState("");
  const clock = useMemo(() => new Clock(), []);
  useClock(clock, 60);
  const dirty = !!stage && !!draft && JSON.stringify(stageContent(stage)) !== JSON.stringify(draft);
  const mutate = (fn: (next: StageContent) => void) => {
    if (!draft || busy) return;
    const next = structuredClone(draft); fn(next); setDraft(next); setResult(null); setMessage("");
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(""); setMessage("");
    try { await fn(); } catch (e) { setError(textError(e)); } finally { setBusy(false); }
  };
  const adopt = async (value: SharedStage) => {
    setStage(value); setDraft(stageContent(value)); setAdvanced(null); setResult(null); setDoc(null);
    setCamera(value.protocol.cameras[0]?.id ?? null); setSelectedCoverage(null);
    clock.pause(); clock.duration = value.protocol.meta.duration_sec; clock.seek(0);
    const preview = await sharedStages.preview(boardId, value); setDoc(preview.doc);
  };
  useEffect(() => {
    let alive = true;
    sharedStages.list(boardId).then(r => { if (alive) setStages(r.items); }).catch(e => { if (alive) setError(textError(e)); });
    // Resource discovery only; optional library input does not gate an empty stage.
    prod.resources(boardId, "entity", 0, 100, "character").then(r => { if (alive) { setEntities(r.data.items); setEntityOffset(r.data.next_offset); } })
      .catch(e => { if (alive) setError(textError(e)); });
    return () => { alive = false; clock.pause(); };
  }, [boardId, clock]);
  useEffect(() => {
    if (initialStageId) void run(async () => { await adopt(await sharedStages.get(boardId, initialStageId)); });
  }, [boardId, initialStageId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let alive = true; setEpochs([]); setEpochId("");
    if (entityId) prod.epochs(entityId, boardId).then(r => { if (alive) setEpochs(r.data.items); })
      .catch(e => { if (alive) setError(textError(e)); });
    return () => { alive = false; };
  }, [boardId, entityId]);

  const save = () => run(async () => {
    if (!stage || !draft) return;
    const saved = await sharedStages.save(boardId, stage, draft);
    await adopt(saved); setStages((await sharedStages.list(boardId)).items); setMessage("舞台已保存，预演采用当前版本");
  });
  const addReferences = (coverageId?: string) => run(async () => {
    if (!stage || dirty || advanced !== null) return;
    await canvas.flushSave();
    const refs: ResourceRef[] = [{ kind: "stage", id: stage.id, mode: "reference" }];
    if (coverageId) refs.push({ kind: "coverage", id: `${stage.id}:${coverageId}`, mode: "reference" });
    const result = await prod.resolve({ board_id: boardId }, refs);
    for (const item of result.data.items) {
      if (item.status !== "resolved" || item.resource?.stage_revision !== stage.revision)
        throw new Error(item.issues?.map(i => i.message).join("；") || "舞台来源已改变，请重新载入后再引用");
    }
    const sourceRefs = Object.values(stage.bindings);
    const atomic = sourceRefs.length ? (await prod.resolve({ board_id: boardId }, sourceRefs)).data.items : [];
    const displays: ResourceRef[] = [];
    for (const item of atomic) {
      if (item.status !== "resolved" || !item.resource)
        throw new Error(item.issues?.map(i => i.message).join("；") || "来源素材已改变");
      if (item.ref.kind === "canonical_pack") {
        const pack = item.resource as unknown as CanonicalPack;
        const view = pack.views.body_front;
        if (view) displays.push(viewRef(pack, view));
      } else if (item.resource.media) displays.push(item.ref);
    }
    const visible = displays.length ? (await prod.resolve({ board_id: boardId }, displays)).data.items : [];
    if (visible.some(item => item.status !== "resolved")) throw new Error("来源视图无法解析，请重新载入素材");
    const ids = result.data.items.map(item => {
      const found = canvas.nodes.find(n => isProductionRef(n.data.ref) && n.data.ref.kind === item.ref.kind &&
        n.data.ref.id === item.ref.id && n.data.ref.revision === item.ref.revision);
      return found?.id ?? canvas.addNode(item.ref.kind === "coverage" ? "coverage" : "stage",
        { ref: item.ref, title: item.resource?.name || item.ref.id });
    });
    if (ids.length === 2) canvas.connect(ids[0], ids[1], "control");
    for (const item of visible) {
      const kind = item.resource?.kind;
      if (kind !== "image" && kind !== "video" && kind !== "audio") continue;
      const found = canvas.nodes.find(n => isProductionRef(n.data.ref) && n.data.ref.kind === item.ref.kind &&
        n.data.ref.id === item.ref.id && n.data.ref.revision === item.ref.revision);
      const source = found?.id ?? canvas.addNode(kind, { ref: item.ref,
        title: item.resource?.name || item.ref.id, role: item.ref.kind === "canonical_view" ? "view" : undefined });
      canvas.connect(source, ids[0], item.ref.kind === "canonical_view" ? "identity" : "ref");
    }
    await canvas.flushSave();
    setMessage("已加入当前画布，保留舞台与镜头版本引用");
  });
  const coverage = draft?.coverages.find(c => c.id === selectedCoverage);
  const seekClip = (ms: number) => {
    if (!coverage) return;
    const t = coverage.scene_start_ms + (coverage.scene_end_ms - coverage.scene_start_ms) * ms / coverage.clip_duration_ms;
    clock.seek(t / 1000); setCamera(coverage.camera_id);
  };
  const selectCoverage = (c: StageCoverage) => { clock.pause(); setSelectedCoverage(c.id); setCamera(c.camera_id); clock.seek(c.scene_start_ms / 1000); };
  const bind = () => run(async () => {
    const epoch = epochs.find(e => e.id === epochId);
    if (!epoch || !entityId || !actorId || !draft) throw new Error("请选择舞台演员、角色与明确的世界/造型时期");
    const pack = (await prod.canonicalPack(entityId, epoch.world_profile_id, epoch.id)).data;
    const next = structuredClone(draft);
    const actor = next.protocol.actors.find(a => a.id === actorId);
    if (!actor) throw new Error("舞台演员已被移除");
    actor.character_ref = `e:${entityId}`;
    if (pack.physical?.height_m) actor.appearance = { ...actor.appearance, height_m: pack.physical.height_m, height_source: pack.physical.source };
    next.bindings[actorId] = { kind: "canonical_pack", id: pack.id, revision: pack.revision, mode: "reference",
      binding: { entity_id: entityId, world_profile_id: pack.world_profile_id, epoch_id: pack.epoch_id } };
    setDraft(next); setMessage("已引用角色素材；保存后参与来源版本检查。估算尺寸仍可手工标定。");
  });
  const download = (payload: Record<string, unknown>) => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `stage-${stage?.id}-${selectedCoverage}.json`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const editList = (s: string) => s.split(/[，,]/).map(x => x.trim()).filter(Boolean);

  return createPortal(<div className="ss-backdrop"><section className="ss-workspace" role="dialog" aria-modal="true" aria-label="共享舞台与镜头">
    <header><div><b>共享舞台与镜头</b><small>同一世界、同一表演；镜头选择机位与时间</small></div>
      <select disabled={busy} value={stage?.id ?? ""} onChange={e => {
        if (dirty || advanced !== null) { setError("当前修改尚未保存，请先保存或放弃修改，再切换舞台"); return; }
        if (e.target.value) void run(async () => adopt(await sharedStages.get(boardId, e.target.value)));
      }}><option value="">选择现有舞台</option>{stages.map(s => <option key={s.id} value={s.id}>{s.title} · {s.board_ids.includes(boardId) ? "本画布" : "可引用"}</option>)}</select>
      <button disabled={busy || dirty || advanced !== null} onClick={() => void run(async () => {
        await adopt(await sharedStages.create(boardId)); setStages((await sharedStages.list(boardId)).items);
      })}>新建空白舞台</button>
      <button disabled={busy || !stage || dirty || advanced !== null} onClick={() => void addReferences()}>加入画布</button>
      <button disabled={busy || !stage || !dirty || advanced !== null} onClick={() => void save()}>保存舞台</button>
      <button disabled={busy || dirty || advanced !== null} onClick={onClose}>关闭</button>
    </header>
    {error && <div className="ss-error" role="alert">{error}</div>}{message && <div className="ss-message">{message}</div>}
    {dirty && <div className="ss-message">预演仍为已保存版本；保存后更新站位和运镜。<button disabled={busy} onClick={() => { if (stage) { setDraft(stageContent(stage)); setAdvanced(null); setError(""); } }}>放弃未保存修改</button></div>}
    {!draft || !stage ? <div className="ss-empty">从空白舞台开始，自己添加人物、物体、机位与动作；也可以引用已有舞台。</div> : <>
      <div className="ss-body"><aside>
        <h3>场景实例</h3><label>舞台名称<input value={draft.protocol.meta.title} onChange={e => mutate(d => { d.protocol.meta.title = e.target.value; })} /></label>
        <NumberField label="场景时长（秒）" value={draft.protocol.meta.duration_sec} onChange={n => mutate(d => { d.protocol.meta.duration_sec = n; })} />
        <div className="ss-row"><button disabled={busy} onClick={() => mutate(d => { d.protocol.actors.push({ id: id("actor"), name: "人物", type: "human", model_ref: "mannequin/male", appearance: {}, spawn: transform() }); })}>＋人物</button>
          <button disabled={busy} onClick={() => mutate(d => { d.protocol.props.push({ id: id("prop"), name: "物体", primitive: "box", size: [1, 1, 1], spawn: transform() }); })}>＋物体</button></div>
        {draft.protocol.actors.map((a, i) => <details key={a.id} open><summary>{a.name || a.id}</summary><small>{a.id} · {draft.bindings[a.id] ? "已引用角色素材" : "未绑定角色"}</small>
          <label>名称<input value={a.name ?? ""} onChange={e => mutate(d => { d.protocol.actors[i].name = e.target.value; })} /></label>
          <NumberField label="身高（米，需填写）" value={a.appearance.height_m ?? NaN} onChange={n => mutate(d => { d.protocol.actors[i].appearance.height_m = n; d.protocol.actors[i].appearance.height_source = "user"; })} />
          <VectorField label="世界位置（米）" value={a.spawn.position} onChange={v => mutate(d => { d.protocol.actors[i].spawn.position = v; })} />
          <NumberField label="朝向（度，0 为 +Z）" value={a.spawn.rotation[1]} onChange={n => mutate(d => { d.protocol.actors[i].spawn.rotation[1] = n; })} />
          <button disabled={busy} onClick={() => mutate(d => { d.protocol.actors.splice(i, 1); delete d.bindings[a.id]; })}>移除人物</button>
        </details>)}
        {draft.protocol.props.map((p, i) => <details key={p.id}><summary>{p.name || p.id}</summary><small>{p.id}</small>
          <label>名称<input value={p.name ?? ""} onChange={e => mutate(d => { d.protocol.props[i].name = e.target.value; })} /></label>
          <VectorField label="尺寸（米）" value={p.size ?? [1, 1, 1]} onChange={v => mutate(d => { d.protocol.props[i].size = v; })} />
          <VectorField label="世界位置（米）" value={p.spawn.position} onChange={v => mutate(d => { d.protocol.props[i].spawn.position = v; })} />
          <button disabled={busy} onClick={() => mutate(d => { d.protocol.props.splice(i, 1); delete d.bindings[p.id]; })}>移除物体</button>
        </details>)}
        <h3>引用角色库</h3><select value={actorId} onChange={e => setActorId(e.target.value)}><option value="">选择舞台演员</option>{draft.protocol.actors.filter(a => a.type === "human").map(a => <option key={a.id} value={a.id}>{a.name || a.id}</option>)}</select>
        <input aria-label="筛选已加载角色" placeholder="筛选已加载角色" value={entityQuery} onChange={e => setEntityQuery(e.target.value)} />
        <select value={entityId} onChange={e => setEntityId(e.target.value)}><option value="">选择角色</option>{entities.filter(e => e.ref.id === entityId || !entityQuery || `${e.resource?.screen_name || ""} ${e.resource?.name || ""} ${e.ref.id}`.toLowerCase().includes(entityQuery.toLowerCase())).map(e => <option key={e.ref.id} value={e.ref.id}>{e.resource?.screen_name || e.resource?.name || e.ref.id}</option>)}</select>
        {entityOffset !== null && <button disabled={busy} onClick={() => void run(async () => { const r = await prod.resources(boardId, "entity", entityOffset, 100, "character"); setEntities(old => [...old, ...r.data.items]); setEntityOffset(r.data.next_offset); })}>加载更多角色</button>}
        <select value={epochId} onChange={e => setEpochId(e.target.value)}><option value="">选择世界 / 造型时期</option>{epochs.map(e => <option key={e.id} value={e.id}>{e.world_name} / {e.name}</option>)}</select>
        <button disabled={busy || !actorId || !epochId} onClick={() => void bind()}>引用素材包</button>
      </aside>
      <main><div className="ss-preview">{doc ? <Suspense fallback={<div>载入白模预演…</div>}><Preview doc={doc} clock={clock} camId={camera} orbit={!camera} /></Suspense> : <div>保存有效舞台后载入预演</div>}</div>
        <div className="ss-row"><button disabled={!doc || dirty || busy} onClick={() => { setSelectedCoverage(null); clock.toggle(); }}>{clock.playing ? "暂停" : "播放舞台"}</button>
          <select value={camera ?? ""} onChange={e => { setCamera(e.target.value || null); setSelectedCoverage(null); }}><option value="">自由查看</option>{draft.protocol.cameras.map(c => <option key={c.id} value={c.id}>{c.name || c.id}</option>)}</select>
          <span>{clock.t.toFixed(2)} / {clock.duration.toFixed(2)} 秒</span></div>
        <input className="ss-seek" aria-label="场景时间" type="range" min={0} max={clock.duration} step={0.001} value={clock.t} disabled={dirty || !doc || busy} onChange={e => { clock.pause(); clock.seek(Number(e.target.value)); }} />
        {coverage && <div className="ss-row"><span>{coverage.title}：成片时间 → 场景时间</span>{[0, coverage.clip_duration_ms / 2, coverage.clip_duration_ms].map((t, i) => <button key={i} disabled={dirty || busy} onClick={() => seekClip(t)}>{["首", "中", "尾"][i]}帧</button>)}
          <button disabled={dirty || busy} onClick={() => void run(async () => { const r = await sharedStages.bake(boardId, stage, coverage.id); setResult(r); download(r); })}>导出逐帧预演数据</button></div>}
        <button disabled={dirty || busy || !doc} onClick={() => void run(async () => { setResult(await sharedStages.sample(boardId, stage, clock.t, camera)); })}>查看此刻站位与剧情状态</button>
        <h3>动作轨</h3><p>动作和位移属于共享舞台，切换机位不会重新摆演员。复杂动作可在结构编辑中编排。</p>
        <button disabled={busy || !draft.protocol.actors.length} onClick={() => mutate(d => {
          const a = d.protocol.actors[0], from = [...a.spawn.position], to = [...a.spawn.position]; to[2] += 1;
          d.protocol.timeline.push({ op: "actor.move", time: 0, actor: a.id, gait: "walk", keys: [{ t: 0, at: from }, { t: d.protocol.meta.duration_sec, at: to }] });
        })}>为首位演员添加位移轨</button>
        {draft.protocol.timeline.map((op, i) => <div className="ss-op" key={i}><span>{String(op.op)} · {String(op.actor || op.prop || op.camera || "")} · {String(op.time)}秒</span><button disabled={busy} onClick={() => mutate(d => { d.protocol.timeline.splice(i, 1); })}>移除</button></div>)}
        <button disabled={busy || advanced !== null} onClick={() => setAdvanced(JSON.stringify(draft, null, 2))}>编辑动作 / 事件 / 完整舞台结构</button>
        {advanced !== null && <div className="ss-advanced"><p>结构编辑保留全部机位和动作。填写 initial_state / events 可以编排前提、持物与伤势；这些状态目前不驱动接触或碰撞。</p><textarea aria-label="完整舞台结构" value={advanced} onChange={e => setAdvanced(e.target.value)} />
          <button disabled={busy} onClick={() => { try { const parsed = JSON.parse(advanced) as StageContent; if (!parsed.protocol || !Array.isArray(parsed.protocol.actors) || !Array.isArray(parsed.protocol.cameras) || !Array.isArray(parsed.protocol.props) || !Array.isArray(parsed.protocol.timeline) || !Array.isArray(parsed.coverages) || !Array.isArray(parsed.events) || !parsed.bindings || !parsed.initial_state) throw new Error("请保留完整舞台结构"); setDraft(parsed); setAdvanced(null); setError(""); } catch (e) { setError(textError(e)); } }}>采用结构修改</button>
          <button onClick={() => setAdvanced(null)}>取消结构编辑</button></div>}
        {result && <details><summary>此刻状态 / 导出记录</summary><pre>{JSON.stringify(result, null, 2).slice(0, 16000)}</pre></details>}
        <p className="ss-limit">当前为白模预演与数据导出。角色身份是素材引用；接触、IK、碰撞和最终视频约束仍待接入，不作为出片质量通过。</p>
      </main>
      <aside><h3>机位与运镜</h3><button disabled={busy} onClick={() => mutate(d => { d.protocol.cameras.push({ id: id("camera"), name: "机位", lens_mm: 35, keys: [{ t: 0, position: [0, 1.6, 5], look_at: [0, 1, 0] }] }); })}>＋机位</button>
        {draft.protocol.cameras.map((c, i) => <details key={c.id} open><summary>{c.name || c.id}</summary><small>{c.id}</small>
          <label>名称<input value={c.name ?? ""} onChange={e => mutate(d => { d.protocol.cameras[i].name = e.target.value; })} /></label>
          <NumberField label="焦距（毫米）" value={c.lens_mm} onChange={n => mutate(d => { d.protocol.cameras[i].lens_mm = n; })} />
          {c.keys.map((k, j) => <div className="ss-key" key={j}><NumberField label={`关键帧 ${j + 1}（秒）`} value={k.t} onChange={n => mutate(d => { d.protocol.cameras[i].keys[j].t = n; })} />
            {k.position && <VectorField label="相机位置" value={k.position} onChange={v => mutate(d => { d.protocol.cameras[i].keys[j].position = v; })} />}
            {Array.isArray(k.look_at) && <VectorField label="看向点" value={k.look_at as Vec3} onChange={v => mutate(d => { d.protocol.cameras[i].keys[j].look_at = v; })} />}
            {!k.position && <small>跟拍或环绕关键帧，可在完整结构中编辑</small>}
            <button disabled={busy} onClick={() => mutate(d => { d.protocol.cameras[i].keys.splice(j, 1); })}>移除关键帧</button></div>)}
          <button disabled={busy} onClick={() => mutate(d => { const last = d.protocol.cameras[i].keys.at(-1); d.protocol.cameras[i].keys.push({ ...(last || { position: [0, 1.6, 5], look_at: [0, 1, 0] }), t: d.protocol.meta.duration_sec }); })}>＋运镜终点</button>
          <button disabled={busy} onClick={() => mutate(d => { d.protocol.cameras.splice(i, 1); })}>移除机位</button>
        </details>)}
        <h3>镜头覆盖</h3><button disabled={busy || !draft.protocol.cameras.length} onClick={() => mutate(d => { const ms = Math.round(d.protocol.meta.duration_sec * 1000); d.coverages.push({ id: id("shot"), title: "镜头", camera_id: d.protocol.cameras[0].id, clip_duration_ms: ms, scene_start_ms: 0, scene_end_ms: ms, fps: d.protocol.meta.fps, intent: "", participants: [], must_show: [], offscreen: [], transition: "cut" }); })}>＋镜头</button>
        {draft.coverages.map((c, i) => <details key={c.id} open><summary onClick={() => { if (!dirty) selectCoverage(c); }}>{c.title}</summary><small>{c.id}</small>
          <label>标题<input value={c.title} onChange={e => mutate(d => { d.coverages[i].title = e.target.value; })} /></label>
          <label>机位<select value={c.camera_id} onChange={e => mutate(d => { d.coverages[i].camera_id = e.target.value; })}>{draft.protocol.cameras.map(cam => <option key={cam.id} value={cam.id}>{cam.name || cam.id}</option>)}</select></label>
          <NumberField label="成片时长（毫秒）" value={c.clip_duration_ms} step={1} onChange={n => mutate(d => { d.coverages[i].clip_duration_ms = n; })} />
          <NumberField label="场景开始（毫秒）" value={c.scene_start_ms} step={1} onChange={n => mutate(d => { d.coverages[i].scene_start_ms = n; })} />
          <NumberField label="场景结束（毫秒）" value={c.scene_end_ms} step={1} onChange={n => mutate(d => { d.coverages[i].scene_end_ms = n; })} />
          <NumberField label="FPS" value={c.fps} step={1} onChange={n => mutate(d => { d.coverages[i].fps = n; })} />
          <label>叙事目的<input value={c.intent} onChange={e => mutate(d => { d.coverages[i].intent = e.target.value; })} /></label>
          <label>必须入画（实例 ID，用逗号分隔）<input value={c.must_show.join(",")} onChange={e => mutate(d => { d.coverages[i].must_show = editList(e.target.value); })} /></label>
          <label>画外（实例 ID）<input value={c.offscreen.join(",")} onChange={e => mutate(d => { d.coverages[i].offscreen = editList(e.target.value); })} /></label>
          <button disabled={dirty || busy || advanced !== null} onClick={() => void addReferences(c.id)}>镜头加入画布</button>
          <button disabled={dirty || busy} onClick={() => selectCoverage(c)}>查看首中尾</button><button disabled={busy} onClick={() => mutate(d => { d.coverages.splice(i, 1); })}>移除镜头</button>
        </details>)}
        {!stage.board_ids.includes(boardId) && <button disabled={busy || dirty} onClick={() => void run(async () => { await adopt(await sharedStages.link(boardId, stage)); setStages((await sharedStages.list(boardId)).items); })}>关联当前画布</button>}
        <a href={hrefFor("box", { box: stage.box_project_id, from: "flow", canvas: boardId })} target="_blank" rel="noreferrer">在白模编辑器中手动拖动 ↗</a>
        <button disabled={busy || dirty || advanced !== null} onClick={() => void run(async () => { await adopt(await sharedStages.adoptProjection(boardId, stage)); setStages((await sharedStages.list(boardId)).items); setMessage("已明确采用白模编辑器的版本，全部镜头复用更新后的舞台"); })}>采用白模编辑器当前版本</button>
        <small>同一舞台可以被多个画布引用，修改会形成共享舞台新版本。</small>
      </aside></div>
    </>}
    <footer>{stage ? `舞台版本 ${stage.version}${dirty ? " · 有未保存修改" : " · 已保存"}` : "未创建舞台"}{(dirty || advanced !== null) && <button disabled={busy} onClick={onClose}>放弃修改并关闭</button>}</footer>
  </section></div>, document.body);
}
