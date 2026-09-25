import { lazy, Suspense, useEffect, useState } from "react";
import App from "./App";
import { Nav, type View } from "./Nav";

// 3D-BOX 带着整个 three.js，点进去才加载
const BoxHome = lazy(() => import("./box/BoxHome"));
const BoxEditor = lazy(() => import("./box/BoxEditor"));

function readView(): { view: View; box: string | null } {
  const q = new URLSearchParams(location.search);
  const v = (q.get("view") as View) || (q.get("box") ? "box" : "canvas");
  return { view: v, box: q.get("box") };
}

export default function Root() {
  const [{ view, box }, setState] = useState(readView);
  useEffect(() => {
    const onPop = () => setState(readView());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const go = (v: View, boxId: string | null = null) => {
    const u = new URL(location.href);
    u.searchParams.set("view", v);
    if (boxId) u.searchParams.set("box", boxId); else u.searchParams.delete("box");
    history.pushState(null, "", u);
    setState({ view: v, box: boxId });
  };
  const nav = <Nav view={view} onChange={v => go(v)} />;
  if (view === "canvas") return <App nav={nav} />;
  return (
    <div className="shell">
      {!(view === "box" && box) && <header className="topbar"><div className="brand">Ainer <b>Studio</b></div>{nav}<div className="spacer" /></header>}
      <Suspense fallback={<div className="empty-state">载入中…</div>}>
        {view === "box" && (box ? <BoxEditor id={box} onBack={() => go("box")} /> : <BoxHome onOpen={id => go("box", id)} />)}
      </Suspense>
    </div>
  );
}
