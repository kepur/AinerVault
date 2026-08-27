"""闸二反向校验：译文出来立刻扫，不等人工。

三类检查，对应 world_violations 的三种 kind：
  forbidden_token  译文出现禁用词（昭和世界观里冒出 "inn"）      severity=high
  lexicon_miss     原文命中了词条，译文却找不到对应译法          severity=medium
  name_drift       人名与锁定值不符                            severity=high

strict 模式下 forbidden_token 触发自动重译（带违规反馈重试一次），仍失败才落告警。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from app.worldview.injector import LexRow


@dataclass(slots=True)
class Violation:
    kind: str
    severity: str
    detected: str
    expected: str | None = None
    suggested_fix: str | None = None
    evidence: dict = field(default_factory=dict)


def contains_token(text: str, token: str) -> bool:
    """CJK 直接子串匹配；拉丁词加词边界，避免 "inn" 命中 "beginning"。"""
    if not token or not text:
        return False
    if token.isascii():
        return re.search(rf"\b{re.escape(token)}\b", text, re.IGNORECASE) is not None
    return token in text


def check_translation(
    *,
    translated_text: str,
    hits: Sequence[LexRow],
    profile_forbidden: Sequence[str] = (),
    locked_names: dict[str, str] | None = None,
    source_text: str = "",
    block_id: str | None = None,
) -> list[Violation]:
    """对单个块做三类检查。hits 是本块原文命中的词条。"""
    out: list[Violation] = []
    if not translated_text:
        return out

    # ① 禁用词
    checked: set[str] = set()
    for r in hits:
        for token in r.forbidden_targets or []:
            if token in checked:
                continue
            checked.add(token)
            if contains_token(translated_text, token):
                out.append(Violation(
                    kind="forbidden_token", severity="high", detected=token,
                    expected=r.target_term,
                    suggested_fix=f"「{token}」不属于该世界观，应使用「{r.target_term}」",
                    evidence={"block_id": block_id, "source_term": r.source_term},
                ))
    for token in profile_forbidden:
        if token in checked:
            continue
        checked.add(token)
        if contains_token(translated_text, token):
            out.append(Violation(
                kind="forbidden_token", severity="high", detected=token,
                suggested_fix=f"「{token}」被目标世界观列为禁用词",
                evidence={"block_id": block_id, "source": "profile"},
            ))

    # ② 名物漏译
    for r in hits:
        if not r.target_term:
            continue
        if contains_token(translated_text, r.target_term):
            continue
        if r.target_reading and contains_token(translated_text, r.target_reading):
            continue
        out.append(Violation(
            kind="lexicon_miss", severity="medium", detected=r.source_term,
            expected=r.target_term,
            suggested_fix=f"原文含「{r.source_term}」，译文应出现「{r.target_term}」",
            evidence={"block_id": block_id},
        ))

    # ③ 人名漂移
    for source_name, expected in (locked_names or {}).items():
        if source_name in source_text and not contains_token(translated_text, expected):
            out.append(Violation(
                kind="name_drift", severity="high", detected=source_name,
                expected=expected,
                suggested_fix=f"「{source_name}」的锁定译名为「{expected}」",
                evidence={"block_id": block_id},
            ))
    return out


def build_retry_feedback(violations: Sequence[Violation]) -> str:
    """把违规转成给模型的重译指令。strict 模式下附在原 prompt 后重试一次。"""
    if not violations:
        return ""
    lines = ["上一版译文存在以下问题，请修正后重新输出（其余内容尽量保持不变）："]
    for v in violations:
        if v.kind == "forbidden_token":
            lines.append(f"  · 不得使用「{v.detected}」，应改为「{v.expected}」")
        elif v.kind == "lexicon_miss":
            lines.append(f"  · 原文的「{v.detected}」必须译为「{v.expected}」")
        elif v.kind == "name_drift":
            lines.append(f"  · 「{v.detected}」的固定译名是「{v.expected}」，不可改动")
    return "\n".join(lines)
