import { lazy, Suspense, useEffect, useState } from "react";
import App from "./App";
import { hrefFor, readCtx, type CtxPatch } from "./ctx";
import { Nav, stageOfView, VIEWS, type View } from "./Nav";

// 3D-BOX 带着整个 three.js，点进去才加载
const BoxHome = lazy(() => import("./box/BoxHome"));
const BoxEditor = lazy(() => import("./box/BoxEditor"));
// 角色库（含造型室）、风格广场（风格／运镜／特效／题材）
const Characters = lazy(() => import("./library/Characters"));
const Plaza = lazy(() => import("./library/Plaza"));
// 创作画布（纳逗式节点画布 + 3D 白模）：自带全屏外壳，不套 .shell
const CreativeCanvas = lazy(() => import("./canvas"));

function readView(): { view: View; box: string | null; from: View | null } {
  const c = readCtx();
  const known = (v: string | null): v is View => !!v && VIEWS.some(x => x.id === v);
  const view: View = known(c.view) ? c.view : c.box ? "box" : "canvas";
  return { view, box: c.box, from: known(c.from) ? c.from : null };
}

export default function Root() {
  const [{ view, box, from }, setState] = useState(readView);
  useEffect(() => {
    const onPop = () => setState(readView());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  // 切视图：书、章、计划、画布、镜头原样带过去（ctx.ts 的约定），各视图挂载时现读
  const go = (v: View, patch: CtxPatch = {}) => {
    // stage 跟着面板走：地址栏自带阶段，刷新/分享回来还在同一阶段
    history.pushState(null, "", hrefFor(v, { stage: stageOfView(v), ...patch }));
    setState(readView());
  };
  const nav = <Nav view={view} onChange={v => go(v)} />;
  if (view === "canvas") return <App nav={nav} />;
  if (view === "flow") {
    return (
      <Suspense fallback={<div className="empty-state">载入创作画布…</div>}>
        <CreativeCanvas nav={nav} />
      </Suspense>
    );
  }
  return (
    <div className="shell">
      {!(view === "box" && box) && <header className="topbar"><div className="brand">Ainer <b>Studio</b></div>{nav}<div className="spacer" /></header>}
      <Suspense fallback={<div className="empty-state">载入中…</div>}>
        {view === "box" && (box
          // 从画布跳进来的（from=flow/canvas）「←」回原画布，否则回白模列表
          ? <BoxEditor id={box} backLabel={from ? VIEWS.find(x => x.id === from)?.label : undefined}
              onBack={() => (from ? go(from, { box: null, from: null }) : go("box", { box: null }))} />
          : <BoxHome onOpen={id => go("box", { box: id, from: null })} />)}
        {view === "characters" && <Characters onOpenBox={id => go("box", { box: id, from: "characters" })} />}
        {view === "styles" && <Plaza />}
      </Suspense>
    </div>
  );
}
