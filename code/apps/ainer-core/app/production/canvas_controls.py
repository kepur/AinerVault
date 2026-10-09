"""Prevent typed stage controls being silently dropped by media-only generators."""

from app.pipelines.base import as_items

MESSAGE = "当前生成器尚未消费共享舞台控制，请先导出镜头预演控制；连线不会被当作已执行的站位或运镜。"


def stage_inputs(doc, node_id):
    doc = doc if isinstance(doc, dict) else {}
    nodes = {n["id"]: n for n in as_items(doc, "nodes") if isinstance(n, dict) and isinstance(n.get("id"), str)}
    targets, seen, refs = {node_id}, set(), []
    parent = nodes.get(node_id, {}).get("parentId")
    while parent in nodes and parent not in targets:
        targets.add(parent)
        parent = nodes[parent].get("parentId")

    def visit(key):
        if key in seen or key not in nodes:
            return
        seen.add(key)
        node = nodes[key]
        ref = (node.get("data") or {}).get("ref") or {}
        if ref.get("kind") in {"stage", "coverage"}:
            refs.append(ref)
        if node.get("type") == "group":
            for cid, child in nodes.items():
                if child.get("parentId") == key:
                    visit(cid)

    for edge in as_items(doc, "edges"):
        if isinstance(edge, dict) and edge.get("target") in targets:
            visit(edge.get("source"))
    return refs
