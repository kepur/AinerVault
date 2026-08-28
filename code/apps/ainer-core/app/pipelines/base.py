"""pipeline 公共设施。

pipeline 就是普通 Python 函数 —— 没有注册表、没有 stage 事件、没有 orchestrator。
要看流程直接读函数。这是 v1 最大的可读性损失点。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import submit_task
from app.models import GenTask, TaskStatus


class PipelineError(RuntimeError):
    pass


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
    return data, task
