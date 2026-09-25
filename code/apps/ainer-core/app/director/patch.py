"""JSON Patch（RFC 6902）：前端拖拽、LLM 的小改动都用差量 patch，不整份重生成。

支持 add / remove / replace / move / copy / test；路径是 JSON Pointer（RFC 6901，~0 = ~、~1 = /），
数组末尾追加用 "-"。打完补丁由调用方重新按协议校验。
"""
from __future__ import annotations

import copy
from typing import Any


class PatchError(ValueError):
    pass


def _tokens(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise PatchError(f"路径要以 / 开头：{path!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in path[1:].split("/")]


def _parent(doc: Any, tokens: list[str], path: str) -> tuple[Any, str]:
    cur = doc
    for t in tokens[:-1]:
        if isinstance(cur, list):
            try:
                cur = cur[int(t)]
            except (ValueError, IndexError) as exc:
                raise PatchError(f"路径不存在：{path}") from exc
        elif isinstance(cur, dict):
            if t not in cur:
                raise PatchError(f"路径不存在：{path}")
            cur = cur[t]
        else:
            raise PatchError(f"路径不存在：{path}")
    return cur, tokens[-1]


def _get(doc: Any, path: str) -> Any:
    cur = doc
    for t in _tokens(path):
        if isinstance(cur, list):
            try:
                cur = cur[int(t)]
            except (ValueError, IndexError) as exc:
                raise PatchError(f"路径不存在：{path}") from exc
        elif isinstance(cur, dict) and t in cur:
            cur = cur[t]
        else:
            raise PatchError(f"路径不存在：{path}")
    return cur


def _add(doc: Any, path: str, value: Any) -> Any:
    tokens = _tokens(path)
    if not tokens:
        return value
    parent, key = _parent(doc, tokens, path)
    if isinstance(parent, list):
        if key == "-":
            parent.append(value)
        else:
            try:
                i = int(key)
            except ValueError as exc:
                raise PatchError(f"数组下标不对：{path}") from exc
            if not 0 <= i <= len(parent):
                raise PatchError(f"数组下标越界：{path}")
            parent.insert(i, value)
    elif isinstance(parent, dict):
        parent[key] = value
    else:
        raise PatchError(f"不能往这里加：{path}")
    return doc


def _remove(doc: Any, path: str) -> tuple[Any, Any]:
    tokens = _tokens(path)
    if not tokens:
        raise PatchError("不能删掉整个文档")
    parent, key = _parent(doc, tokens, path)
    if isinstance(parent, list):
        try:
            return doc, parent.pop(int(key))
        except (ValueError, IndexError) as exc:
            raise PatchError(f"路径不存在：{path}") from exc
    if isinstance(parent, dict) and key in parent:
        return doc, parent.pop(key)
    raise PatchError(f"路径不存在：{path}")


def apply(doc: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """按顺序打补丁，返回新文档（原文档不动）。任何一步失败整份作废。"""
    out = copy.deepcopy(doc)
    if not isinstance(ops, list):
        raise PatchError("patch 要是数组")
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or "op" not in op or "path" not in op:
            raise PatchError(f"第 {i} 条缺 op 或 path")
        kind, path = op["op"], op["path"]
        try:
            if kind == "add":
                out = _add(out, path, copy.deepcopy(op["value"]))
            elif kind == "remove":
                out, _ = _remove(out, path)
            elif kind == "replace":
                _get(out, path)
                out, _ = _remove(out, path) if _tokens(path) else (out, None)
                out = _add(out, path, copy.deepcopy(op["value"]))
            elif kind == "move":
                out, v = _remove(out, op["from"])
                out = _add(out, path, v)
            elif kind == "copy":
                out = _add(out, path, copy.deepcopy(_get(out, op["from"])))
            elif kind == "test":
                if _get(out, path) != op.get("value"):
                    raise PatchError(f"test 不通过：{path}")
            else:
                raise PatchError(f"不认识的 op：{kind}")
        except KeyError as exc:
            raise PatchError(f"第 {i} 条缺字段 {exc}") from exc
        except PatchError as exc:
            raise PatchError(f"第 {i} 条（{kind} {path}）：{exc}") from exc
    return out
