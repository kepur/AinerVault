"""pipeline 公共设施。

pipeline 就是普通 Python 函数 —— 没有注册表、没有 stage 事件、没有 orchestrator。
要看流程直接读函数。这是 v1 最大的可读性损失点。
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import submit_task
from app.models import GenTask, TaskStatus


log = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    pass


def as_text(value: Any, *, sep: str = "，", limit: int | None = None) -> str:
    """把 LLM 返回的任意值取成字符串。

    **不能假设模型严格遵守 schema。** schema 写的是 string，
    模型可能返回 ["紧张", "悬疑"]，也可能返回 3 或 null ——
    直接 `.strip()` 会以 AttributeError 把整批任务打挂，
    而调用方看到的只是 500，完全不知道是模型多给了个数组。

    换模型时这类差异最集中：同一份 schema，DeepSeek 老实返回字符串，
    另一个模型顺手给了列表。管线不该因此失败。

    列表拼起来而不是丢掉 —— 模型给数组通常是因为它真有多个值，
    丢掉等于丢信息。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        out = value.strip()
    elif isinstance(value, (list, tuple, set)):
        out = sep.join(as_text(v) for v in value if v is not None).strip(sep)
    elif isinstance(value, dict):
        out = sep.join(as_text(v) for v in value.values() if v is not None).strip(sep)
    elif isinstance(value, bool):
        out = "是" if value else ""
    else:
        out = str(value).strip()
    return out[:limit] if limit else out


def as_list(value: Any, *, limit: int | None = None) -> list[str]:
    """把 LLM 返回的任意值取成字符串列表。

    schema 写 array，模型可能返回单个字符串。反过来也一样 ——
    两个方向都要兜住，否则换个模型就有一半字段取不到。
    """
    if value is None:
        return []
    if isinstance(value, str):
        items = [value.strip()] if value.strip() else []
    elif isinstance(value, (list, tuple, set)):
        items = [t for t in (as_text(v) for v in value) if t]
    elif isinstance(value, dict):
        items = [t for t in (as_text(v) for v in value.values()) if t]
    else:
        items = [str(value).strip()]
    return items[:limit] if limit else items


def as_items(data: Any, key: str) -> list[dict[str, Any]]:
    """从 LLM 结果里取一个对象数组，滤掉不是对象的元素。

    schema 写 array of object，模型有时给一串裸字符串
    （["破釜沉舟", "唇亡齿寒"] 而不是 [{"surface": "..."}]）。
    循环里直接 item.get(...) 会以 AttributeError 变成 500 ——
    这是同一类问题的最后一种形态：前面处理了「字段值的类型」，
    这里是「数组元素的类型」。

    非对象元素丢掉而不是尝试猜它对应哪个字段 ——
    猜错会把一个词写进错误的槽，比少一条更难发现。
    """
    raw = data.get(key) if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    dropped = 0
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        else:
            dropped += 1
    if dropped:
        log.warning("%s 里有 %d 个元素不是对象，已丢弃", key, dropped)
    return out


def as_int(value: Any, default: int = 0, *, lo: int | None = None,
           hi: int | None = None) -> int:
    """取整数并夹到区间。模型给 "3"、3.0、甚至 "三" 都不该让管线崩。"""
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n



def checkpoint(db: Session, *, why: str = "") -> None:
    """把已经完成的那一步立刻落库。

    **同步方言下每次 submit_task 都是一次已经付过费的模型调用。**
    而 `get_db` 只在请求末尾 commit —— 出 30 张图是一次 HTTP 请求里
    串行调 30 次模型、约 40 分钟，其间任何一处异常（哪怕只是客户端
    等不及断开）都会让事务回滚：30 张图全生成、全付费、甚至已经
    落盘到 var/media，但 gen_tasks 与 assets 一条不留，重跑要重新付一遍。

    所以长循环里每完成一项就 checkpoint 一次。代价是三十次 COMMIT，
    换来的是「花掉的钱一定留得住」。

    expire_on_commit=False，所以 commit 之后循环里的对象仍可直接用，
    不会因为 commit 触发一轮重新加载。
    """
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        raise

def fingerprint(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def chat_json(
    db: Session,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    *,
    purpose: str = "*",
    tier: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 8192,
    novel_id: str | None = None,
    chapter_id: str | None = None,
    ref_kind: str | None = None,
    ref_id: str | None = None,
) -> tuple[dict[str, Any], GenTask]:
    """走 text.chat 的 json_schema 模式取结构化结果。

    tier 不传时按 purpose 取默认档 —— 调用方声明这是什么活，
    该用多强的模型交给路由决定，改档位不必碰 pipeline 代码。

    契约要求中间层保证 json_schema 输出可解析（内部重试/修复），
    所以这里不做二次解析兜底 —— 那是中间层的职责，不该在 Core 里重复实现。
    """
    task = submit_task(
        db,
        Capability.text_chat,
        {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "schema": schema},
        },
        purpose=purpose,
        tier=tier,
        sync=True,
        novel_id=novel_id,
        chapter_id=chapter_id,
        ref_kind=ref_kind,
        ref_id=ref_id,
    )
    if task.status != TaskStatus.succeeded:
        err = task.error_json or {}
        raise PipelineError(f"LLM 调用失败 [{err.get('code')}]: {err.get('message')}")

    result = task.result_json or {}
    data = result.get("json")
    if data is None:
        raise PipelineError("中间层未按 json_schema 返回可解析对象（契约 §4.1 要求）")

    # schema 顶层是 object，可模型有时只给数组 —— 尤其在 schema 只有
    # 一个数组字段时（{"terms": [...]} 它直接返回 [...]）。
    # 所有管线都写 data.get(...)，拿到 list 会以 AttributeError 变成 500，
    # 而调用方完全不知道是形状不对。
    # 能对上唯一的数组字段就归位，对不上才报错 —— 报错也要说清收到了什么。
    if isinstance(data, list):
        array_fields = [
            k for k, v in (schema.get("properties") or {}).items()
            if isinstance(v, dict) and v.get("type") == "array"
        ]
        if len(array_fields) == 1:
            log.info("模型返回了裸数组，按唯一的数组字段 %s 归位", array_fields[0])
            data = {array_fields[0]: data}
        else:
            raise PipelineError(
                f"模型返回了数组而 schema 顶层是对象，且无法确定归入哪个字段"
                f"（候选 {array_fields or '无'}）"
            )
    if not isinstance(data, dict):
        raise PipelineError(f"模型返回的顶层不是对象：{type(data).__name__}")
    return data, task
