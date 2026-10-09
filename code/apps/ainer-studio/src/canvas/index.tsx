/**
 * 创作画布（?view=flow）：纳逗式节点画布，把剧本场次、镜头、定妆照和 3D 白模摆在一张图上。
 * Root 里 lazy 加载：分镜画布、3D-BOX 等别的视图不带它。
 */
import { Component, type ErrorInfo, type ReactNode } from "react";
import { ReactFlowProvider } from "@xyflow/react";
// xyflow 自己的样式在 main.tsx 全局引过了
import "./tokens.css";
import "./core.css";
import "./nodes.css";
import "./three.css";
import "./chrome.css";
import { AddMenu } from "./chrome/AddMenu";
import { AssetsDrawer } from "./chrome/AssetsDrawer";
import { BottomBar } from "./chrome/BottomBar";
import { Dock } from "./chrome/Dock";
import { NodeActions } from "./chrome/NodeActions";
import { Overlays } from "./chrome/Overlays";
import { SearchPalette } from "./chrome/SearchPalette";
import { Toasts } from "./chrome/Toasts";
import { TopBar } from "./chrome/TopBar";
import { Flow } from "./Flow";
import { CanvasProvider } from "./store";
import { BoxOverlay } from "./three/BoxOverlay";

/**
 * 画布里任何一处渲染出错（某个节点拿到了意外的数据等）都会让整个 React 树卸掉、整页黑屏。
 * 兜一层：说清楚出了什么错，给「重新载入」；画布布局已经存过盘，重载不丢东西。
 */
class CanvasBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("[canvas] 渲染出错", error, info.componentStack); }
  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="cv-empty cv-glass" role="alert">
        <b>画布出错了</b>
        <p>{error.message || String(error)}</p>
        <div className="cv-empty__acts">
          <a href={location.href} onClick={e => { e.preventDefault(); location.reload(); }}>重新载入</a>
        </div>
      </div>
    );
  }
}

export default function CreativeCanvas({ nav }: { nav?: ReactNode }) {
  return (
    <div className="cv-root">
      <CanvasBoundary>
        <ReactFlowProvider>
          <CanvasProvider>
            <Flow>
              <NodeActions />
              <BottomBar />
            </Flow>
            <TopBar nav={nav} />
            <Dock />
            <AddMenu />
            <SearchPalette />
            <AssetsDrawer />
            <Toasts />
            <Overlays />
            <BoxOverlay />
          </CanvasProvider>
        </ReactFlowProvider>
      </CanvasBoundary>
    </div>
  );
}
