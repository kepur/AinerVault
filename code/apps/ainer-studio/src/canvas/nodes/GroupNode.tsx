import { memo, useState } from "react";
import { NodeResizer, type NodeProps } from "@xyflow/react";
import type { CNode } from "../model";
import { useLazyStore } from "./NodeShell";

/**
 * 分组框（纳逗的「分组 4」）：子节点用 parentId 挂在它里面，整组一起拖；@分组 = 组里所有图。
 * 以前没注册这个类型，xyflow 用自带的浅灰色板子画，在深色画布上像一块没加载出来的图，也没有标题。
 * 标题双击改名；选中时四边可拉伸（子节点不动）。
 */
function GroupNode({ id, data, selected }: NodeProps<CNode>) {
  const [tap, getStore] = useLazyStore();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const commit = () => {
    const t = draft.trim();
    if (t && t !== data.title) getStore()?.updateNodeData(id, { title: t });
    setEditing(false);
  };
  return (
    <div className={`cv-group${selected ? " is-selected" : ""}`}>
      <NodeResizer isVisible={selected} minWidth={160} minHeight={120} lineClassName="cv-group__line" handleClassName="cv-group__handle" />
      <div className="cv-group__head">
        <span className="cv-node__glyph" style={{ ["--cv-kc" as string]: "var(--cv-muted)" }}>组</span>
        {editing ? (
          <input className="cv-group__input nodrag" autoFocus value={draft}
            onChange={e => setDraft(e.target.value)} onBlur={commit}
            onKeyDown={e => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); e.stopPropagation(); }} />
        ) : (
          <span className="cv-group__title" title="双击改名" onDoubleClick={() => { setDraft(data.title || ""); setEditing(true); }}>
            {data.title || "分组"}
          </span>
        )}
      </div>
      {tap}
    </div>
  );
}

export default memo(GroupNode);
