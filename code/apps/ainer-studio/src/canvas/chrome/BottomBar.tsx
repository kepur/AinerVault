/**
 * 底栏：作为 <Flow> 的 children 渲染在 <ReactFlow> 里面（MiniMap、useViewport 都要 xyflow 的上下文）。
 *   左下：资产管理、小地图、适配视图、缩放滑杆
 *   底部居中：大号「＋」、搜索、整理、快捷键帮助
 */
import { MiniMap, Panel, useReactFlow, useViewport } from "@xyflow/react";
import { useState } from "react";
import { GLYPH, isEmptyGen } from "../actions";
import type { CEdge, CNode, NodeKind } from "../model";
import { useCanvas } from "../store";
import { toggleAssets, useAssetsOpen } from "./AssetsDrawer";
import { Icon, MenuList, Popover } from "./Overlays";
import { openSearch } from "./SearchPalette";

const MIN_ZOOM = 0.05;
const MAX_ZOOM = 2.5;

const KIND_COLOR: Record<NodeKind, string> = {
  stage: "var(--cv-kind-box3d)", coverage: "var(--cv-kind-video)", audio: "var(--cv-kind-text)", text: "var(--cv-kind-text)", image: "var(--cv-kind-image)", video: "var(--cv-kind-video)", box3d: "var(--cv-kind-box3d)", group: "var(--cv-muted)",
};

const KEYS: [string, string][] = [
  ["⌘K  或  /", "搜索节点"],
  ["F", "适配视图"],
  ["Delete / ⌫ / ⌘⌫", "删除选中（剧本、镜头、角色只是从画布拿掉，底栏「已拿掉」能放回）"],
  ["右键", "节点、多选、连线、空白处各有菜单"],
  ["⌘A", "全选"],
  ["Esc", "取消选中 / 关菜单"],
  ["Shift + 拖", "框选多个"],
  ["⌘ + 滚轮 / 双指捏合", "缩放"],
  ["双指滑 / 拖空白处", "平移"],
  ["双击节点", "全屏看图、视频；白模进 3D-BOX"],
  ["⌘Enter", "生成面板里发送"],
  ["@", "提示词里引用上游节点"],
];

export function BottomBar() {
  const s = useCanvas();
  const rf = useReactFlow<CNode, CEdge>();
  const { zoom } = useViewport();
  const assetsOpen = useAssetsOpen();
  const [mini, setMini] = useState(false);
  const [helpEl, setHelpEl] = useState<HTMLElement | null>(null);
  const [hiddenEl, setHiddenEl] = useState<HTMLElement | null>(null);
  const hidden = s.hidden;
  const empties = s.nodes.filter(n => isEmptyGen(n, s)).length;

  // 滑杆走对数刻度：5% 到 250% 跨了 50 倍，线性的话 5%–50% 只占一小截，拖不准
  const lo = Math.log(MIN_ZOOM);
  const hi = Math.log(MAX_ZOOM);
  const slider = Math.round(((Math.log(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom))) - lo) / (hi - lo)) * 1000);

  return (
    <>
      <Panel position="bottom-left" className="cv-bb-left nodrag nopan">
        <button type="button" className={`cv-pill cv-glass${assetsOpen ? " is-on" : ""}`} onClick={() => toggleAssets()}
          title="角色、媒体、3D 白模：点一下放到画布上">
          <Icon name="layers" size={15} />资产管理
        </button>
        <div className="cv-pillgroup cv-glass">
          <button type="button" className={`cv-pg-btn is-icon${mini ? " is-on" : ""}`} aria-pressed={mini}
            title={mini ? "收起小地图" : "小地图"} onClick={() => setMini(v => !v)}>
            <Icon name="map" size={15} />
          </button>
          <button type="button" className="cv-pg-btn is-icon" title="适配视图（F）"
            onClick={() => void rf.fitView({ padding: 0.15, duration: 300 })}>
            <Icon name="fit" size={15} />
          </button>
          <span className="cv-pg-sep" />
          <input className="cv-zoom" type="range" min={0} max={1000} step={1} value={slider} aria-label="缩放"
            onChange={e => void rf.zoomTo(Math.exp(lo + (Number(e.target.value) / 1000) * (hi - lo)))} />
          <button type="button" className="cv-zoom-num" title="回到 100%" onClick={() => void rf.zoomTo(1, { duration: 200 })}>
            {Math.round(zoom * 100)}%
          </button>
        </div>
      </Panel>

      {mini && (
        <MiniMap className="cv-minimap" position="bottom-left" pannable zoomable ariaLabel="小地图"
          nodeColor={n => KIND_COLOR[(n.type as NodeKind | undefined) ?? "text"]}
          nodeStrokeWidth={0} nodeBorderRadius={6} />
      )}

      <Panel position="bottom-center" className="cv-bb-center nodrag nopan">
        <div className="cv-bb-dock cv-glass">
          <button type="button" className="cv-bb-plus" title="新增节点：文本、提示词、图片、3D 白模、生成"
            onClick={e => {
              const r = e.currentTarget.getBoundingClientRect();
              s.openAddMenu({ x: r.left + r.width / 2, y: r.top }, null);
            }}>
            <Icon name="plus" size={22} />
          </button>
          <button type="button" className="cv-bb-btn" title="搜索节点（⌘K 或 /）" onClick={() => openSearch()}>
            <Icon name="search" size={17} />
          </button>
          <button type="button" className="cv-bb-btn" title="整理布局：按流程排列（钉住的与分组保留）" onClick={() => s.relayout()}>
            <Icon name="grid" size={17} />
          </button>
          {hidden.length > 0 && (
            <button type="button" className={`cv-bb-chip${hiddenEl ? " is-on" : ""}`}
              title="从画布拿掉的剧本、镜头、定妆照、白模（后端都还在）：点开放回"
              onClick={e => setHiddenEl(hiddenEl ? null : e.currentTarget)}>
              <Icon name="undo" size={14} />已拿掉 {hidden.length}
            </button>
          )}
          {empties > 0 && (
            <button type="button" className="cv-bb-chip"
              title="清理误加的空生成节点（点了「生成」却没发过提示词的）；可以撤销"
              onClick={() => { const n = s.pruneEmpty(); if (!n) s.toast("没有空节点了", "info"); }}>
              <Icon name="trash" size={14} />清理空节点 {empties}
            </button>
          )}
          <button type="button" className={`cv-bb-btn${helpEl ? " is-on" : ""}`} title="快捷键"
            onClick={e => setHelpEl(helpEl ? null : e.currentTarget)}>
            <Icon name="help" size={17} />
          </button>
        </div>
      </Panel>

      {hiddenEl && (
        <Popover anchor={hiddenEl} placement="top" offset={12} onClose={() => setHiddenEl(null)} className="cv-hidden-pop">
          <div className="cv-pop-title">已拿掉<span>后端都还在，放回后按自动布局长回原位</span></div>
          <MenuList empty="没有拿掉的节点" onPicked={() => setHiddenEl(null)}
            items={[
              ...hidden.map(h => ({
                id: h.id, label: h.title, icon: <span className="cv-menu-glyph">{GLYPH[h.type]}</span>, hint: "放回",
                onPick: () => s.restoreHidden([h.id]),
              })),
              ...(hidden.length > 1 ? [{ id: "__all", label: `全部放回（${hidden.length}）`, icon: <Icon name="undo" size={14} />, onPick: () => s.restoreHidden() }] : []),
            ]} />
        </Popover>
      )}
      {helpEl && (
        <Popover anchor={helpEl} placement="top" offset={12} onClose={() => setHelpEl(null)} className="cv-help" role="dialog">
          <div className="cv-pop-title">快捷键<span>焦点在输入框里时不生效</span></div>
          <dl>
            {KEYS.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
          </dl>
        </Popover>
      )}
    </>
  );
}
