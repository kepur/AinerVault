/**
 * 选中节点上方的胶囊工具条（纳逗式：「选段创作 NEW ▾｜编辑 NEW ▾｜声音分离｜超清｜…｜📌｜⬇｜⛶」）。
 * 渲染在 <ReactFlow> 里面（NodeToolbar 要读 xyflow 的节点位置），只在恰好选中一个节点时出现。
 *
 * 禁用的按钮不用 disabled 属性：禁用元素在有的浏览器里不出 title 提示，
 * 而「为什么不能用」正是要让人看到的（铁律 3）。
 */
import { NodeToolbar, Position } from "@xyflow/react";
import { useEffect, useState } from "react";
import { actionsFor, ICON_ONLY, removeAction, startFrames } from "../actions";
import type { CanvasAction, CNode } from "../model";
import { useCanvas } from "../store";
import { errText, Icon, MenuList, Popover, Spinner, useLatest } from "./Overlays";

export function NodeActions() {
  const s = useCanvas();
  const latest = useLatest(s);
  const [menu, setMenu] = useState<{ id: string; el: HTMLElement } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const node = s.selected;
  const picked = s.nodes.filter(n => n.selected);

  // 换了选中就把展开的菜单收起来（不然菜单会挂在别的节点头上）
  useEffect(() => { setMenu(null); }, [s.selectedId]);

  if (s.overlay) return null;
  if (!node && picked.length > 1) return <MultiActions nodes={picked} />;
  if (!node || !s.selectedId) return null;

  const actions = actionsFor(node, s);
  const main = actions.filter(a => !ICON_ONLY.has(a.id));
  const icons = actions.filter(a => ICON_ONLY.has(a.id));
  const open = menu ? actions.find(a => a.id === menu.id) : undefined;

  const run = async (a: CanvasAction) => {
    if (!a.run || a.disabled) return;
    setBusy(a.id);
    try {
      await a.run();
    } catch (e) {
      latest.current.toast(`${a.label}失败：${errText(e)}`, "err");
    } finally {
      setBusy(null);
    }
  };

  const click = (a: CanvasAction, el: HTMLElement) => {
    if (a.disabled) return;
    if (a.menu) { setMenu(m => (m?.id === a.id ? null : { id: a.id, el })); return; }
    setMenu(null);
    void run(a);
  };

  const pinned = !!node.data.pinned;
  // offset 34 而不是 16：节点标题绝对定位在卡片上方 22px（不算进节点尺寸），16 会压住标题

  return (
    <NodeToolbar nodeId={node.id} isVisible position={Position.Top} offset={34} className="cv-ntb-wrap nodrag nopan nowheel">
      <div className="cv-ntb cv-glass" role="toolbar" aria-label={`${node.data.title} 的操作`}>
        {main.map(a => (
          <button key={a.id} type="button"
            className={`cv-ntb-btn${a.disabled ? " is-off" : ""}${menu?.id === a.id ? " is-open" : ""}`}
            aria-disabled={!!a.disabled}
            aria-haspopup={a.menu ? "menu" : undefined}
            title={a.disabled || a.title || a.label}
            onClick={e => click(a, e.currentTarget)}>
            {busy === a.id ? <Spinner size={12} /> : a.icon && <span className="cv-ntb-icon">{a.icon}</span>}
            <span>{a.label}</span>
            {a.badge && <span className="cv-new">{a.badge}</span>}
            {a.menu && <Icon name="down" size={12} className="cv-ntb-caret" />}
          </button>
        ))}
        <span className="cv-ntb-sep" />
        <button type="button" className={`cv-ntb-btn is-icon${pinned ? " is-on" : ""}`}
          title={pinned ? "已钉住：自动整理不挪它（点一下取消）" : "钉住：自动整理不挪它"}
          aria-pressed={pinned}
          onClick={() => s.updateNodeData(node.id, { pinned: !pinned })}>
          <Icon name="pin" size={15} />
        </button>
        {icons.map(a => (
          <button key={a.id} type="button" className={`cv-ntb-btn is-icon${a.disabled ? " is-off" : ""}`}
            aria-disabled={!!a.disabled} aria-label={a.label}
            title={a.disabled ? `${a.label}：${a.disabled}` : a.title || a.label}
            onClick={e => click(a, e.currentTarget)}>
            {busy === a.id ? <Spinner size={12} />
              : a.id === "download" ? <Icon name="download" size={15} />
                : a.id === "fullscreen" ? <Icon name="expand" size={15} />
                  : a.id === "remove" ? <Icon name="trash" size={15} />
                  : <span className="cv-ntb-icon">{a.icon ?? a.label.slice(0, 1)}</span>}
          </button>
        ))}
      </div>
      {menu && open?.menu && (
        <Popover anchor={menu.el} placement="bottom-start" onClose={() => setMenu(null)}>
          <MenuList
            onPicked={() => setMenu(null)}
            items={open.menu.map(m => ({
              id: m.id,
              label: m.label,
              icon: busy === m.id ? <Spinner size={12} /> : m.icon,
              badge: m.badge,
              disabled: m.disabled,
              title: m.title,
              onPick: () => void run(m),
            }))}
          />
        </Popover>
      )}
    </NodeToolbar>
  );
}

/**
 * 多选工具条（Shift 框选、⌘ 点选）：删除、全部钉住、只给这几镜出分镜图、取消选择。
 * 浮在选中节点的公共上方（xyflow NodeToolbar 支持传一组 id）。
 */
function MultiActions({ nodes }: { nodes: CNode[] }) {
  const s = useCanvas();
  const latest = useLatest(s);
  const [busy, setBusy] = useState(false);
  const shots = nodes.filter(n => n.data.ref.kind === "shot").map(n => n.data.ref.id);
  const del = removeAction(s, nodes);
  const allPinned = nodes.every(n => n.data.pinned);
  const frames = async () => {
    setBusy(true);
    try { await startFrames(latest.current, shots); } finally { setBusy(false); }
  };
  return (
    <NodeToolbar nodeId={nodes.map(n => n.id)} isVisible position={Position.Top} offset={34} className="cv-ntb-wrap nodrag nopan nowheel">
      <div className="cv-ntb cv-glass" role="toolbar" aria-label={`已选 ${nodes.length} 个节点`}>
        <span className="cv-ntb-count">已选 {nodes.length} 个</span>
        <span className="cv-ntb-sep" />
        {shots.length > 0 && s.board?.plan_id && (
          <button type="button" className="cv-ntb-btn" aria-disabled={busy}
            title="只给选中的这几镜出分镜图（关键帧：本章定妆照＋场景图），审过再出视频"
            onClick={() => { if (!busy) void frames(); }}>
            {busy ? <Spinner size={12} /> : <span className="cv-ntb-icon">▶</span>}<span>出分镜图（{shots.length} 镜）</span>
          </button>
        )}
        <button type="button" className={`cv-ntb-btn${allPinned ? " is-on" : ""}`}
          title={allPinned ? "取消钉住" : "全部钉住：自动整理不挪它们"}
          onClick={() => nodes.forEach(n => s.updateNodeData(n.id, { pinned: !allPinned }))}>
          <Icon name="pin" size={15} /><span>{allPinned ? "取消钉住" : "钉住"}</span>
        </button>
        <button type="button" className="cv-ntb-btn" title="取消选择（Esc）" onClick={() => s.select(null)}>
          <Icon name="close" size={14} /><span>取消选择</span>
        </button>
        <span className="cv-ntb-sep" />
        <button type="button" className="cv-ntb-btn is-danger" title={del.title} onClick={() => void del.run?.()}>
          <Icon name="trash" size={15} /><span>{del.label}</span>
        </button>
      </div>
    </NodeToolbar>
  );
}
