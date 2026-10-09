/**
 * 右键菜单：节点、多选、连线、空白处各一份。
 * 菜单项和工具条同源（actionsFor / removeAction / startFrames），右键只是换个入口，不另起一套逻辑。
 */
import type { CanvasAction } from "../model";
import { actionsFor, isEmptyGen, removeAction, startFrames } from "../actions";
import { SEARCH_EVENT, useCanvas } from "../store";
import type { CanvasStore } from "../contract";
import { errText, Icon, MenuList, Popover, type MenuItem } from "./Overlays";

export type CtxTarget =
  | { kind: "node"; id: string; x: number; y: number }
  | { kind: "selection"; x: number; y: number }
  | { kind: "edge"; id: string; x: number; y: number }
  | { kind: "pane"; x: number; y: number };

export function ContextMenu({ at, onClose }: { at: CtxTarget; onClose: () => void }) {
  const s = useCanvas();
  const items = itemsFor(at, s);
  return (
    <Popover anchor={{ x: at.x, y: at.y }} placement="bottom-start" offset={2} onClose={onClose} className="cv-ctx">
      <MenuList items={items} onPicked={onClose} empty="这里没有可做的操作" />
    </Popover>
  );
}

function runner(s: CanvasStore, a: CanvasAction) {
  return () => {
    if (!a.run) return;
    Promise.resolve(a.run()).catch(e => s.toast(`${a.label}失败：${errText(e)}`, "err"));
  };
}

function asItem(s: CanvasStore, a: CanvasAction, hint?: string): MenuItem {
  return {
    id: a.id, label: a.label, hint,
    icon: a.id === "remove" ? <Icon name="trash" size={14} /> : a.icon,
    badge: a.badge, disabled: a.disabled, title: a.title,
    onPick: runner(s, a),
  };
}

function itemsFor(at: CtxTarget, s: CanvasStore): MenuItem[] {
  if (at.kind === "node") {
    const node = s.nodes.find(n => n.id === at.id);
    if (!node) return [];
    const out: MenuItem[] = [];
    for (const a of actionsFor(node, s)) {
      if (a.id === "remove") continue; // 放最后
      if (a.menu) {
        // 二级菜单摊平；「更多」里还没接后端的（灰的）右键里不列，工具条上看得到原因
        for (const m of a.menu) {
          if (a.id === "more" && m.disabled) continue;
          out.push(asItem(s, { ...m, id: `${a.id}/${m.id}` }));
        }
      } else {
        out.push(asItem(s, a));
      }
    }
    const pinned = !!node.data.pinned;
    out.push(
      { id: "__focus", label: "居中显示", icon: <Icon name="expand" size={14} />, onPick: () => s.focusNode(node.id) },
      { id: "__pin", label: pinned ? "取消钉住" : "钉住（自动整理不挪它）", icon: <Icon name="pin" size={14} />, onPick: () => s.updateNodeData(node.id, { pinned: !pinned }) },
      asItem(s, removeAction(s, [node]), "⌫"),
    );
    return out;
  }

  if (at.kind === "selection") {
    const nodes = s.nodes.filter(n => n.selected);
    const shots = nodes.filter(n => n.data.ref.kind === "shot").map(n => n.data.ref.id);
    const allPinned = nodes.length > 0 && nodes.every(n => n.data.pinned);
    const out: MenuItem[] = [];
    if (shots.length && s.board?.plan_id) {
      out.push({
        id: "__frames", label: `出分镜图（${shots.length} 镜）`, icon: "▶",
        title: "只给选中的这几镜出关键帧（本章定妆照＋场景图），审过再出视频",
        onPick: () => void startFrames(s, shots),
      });
    }
    out.push(
      { id: "__pin", label: allPinned ? "全部取消钉住" : "全部钉住", icon: <Icon name="pin" size={14} />, onPick: () => nodes.forEach(n => s.updateNodeData(n.id, { pinned: !allPinned })) },
      { id: "__none", label: "取消选择", icon: <Icon name="close" size={14} />, hint: "Esc", onPick: () => s.select(null) },
      asItem(s, removeAction(s, nodes), "⌫"),
    );
    return out;
  }

  if (at.kind === "edge") {
    const e = s.edges.find(x => x.id === at.id);
    return [{
      id: "__unlink", label: "删除这条连线", icon: <Icon name="trash" size={14} />,
      disabled: e?.data?.derived ? "这条线来自分镜关系（场次→镜头、白模→镜头），不能删" : false,
      onPick: () => s.onEdgesChange([{ type: "remove", id: at.id }]),
    }];
  }

  const hidden = s.hidden;
  const empties = s.nodes.filter(n => isEmptyGen(n, s)).length;
  const out: MenuItem[] = [
    { id: "__add", label: "添加节点…", icon: <Icon name="plus" size={14} />, onPick: () => s.openAddMenu({ x: at.x, y: at.y }, null) },
    { id: "__search", label: "搜索节点", icon: <Icon name="search" size={14} />, hint: "⌘K", onPick: () => window.dispatchEvent(new CustomEvent(SEARCH_EVENT)) },
    { id: "__layout", label: "自动整理", icon: <Icon name="layout" size={14} />, title: "按场次重排（钉住的不动）", onPick: () => s.relayout() },
  ];
  if (s.nodes.length) {
    out.push({ id: "__all", label: "全选", hint: "⌘A", icon: <Icon name="check" size={14} />, onPick: () => s.onNodesChange(s.nodes.map(n => ({ type: "select", id: n.id, selected: true }))) });
  }
  if (hidden.length) {
    out.push({ id: "__restore", label: `放回拿掉的节点（${hidden.length}）`, icon: <Icon name="undo" size={14} />, onPick: () => s.restoreHidden() });
  }
  if (empties) {
    out.push({ id: "__prune", label: `清理空节点（${empties}）`, icon: <Icon name="trash" size={14} />, onPick: () => { s.pruneEmpty(); } });
  }
  return out;
}
