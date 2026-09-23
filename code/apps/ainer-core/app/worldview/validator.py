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
                # 说清是**原文哪个词**不该这么译，并把词条的理由带上。
                # 只说「Mom 不属于该世界观」时模型无从下手 ——
                # 它不知道这条针对的是「草你妈的」，也不知道那是句骂人的
                # 固定说法而不是在叫妈。实跑里它照着改了一版
                # 「Fuck you, Mom」→「Shit, Mom」，两版都留着 Mom。
                why = (getattr(r.row, "rationale", None) or "").strip()
                out.append(Violation(
                    kind="forbidden_token", severity="high", detected=token,
                    expected=r.target_term,
                    suggested_fix=(
                        f"原文的「{r.source_term}」不能译出「{token}」，"
                        f"应整体译作「{r.target_term}」"
                        + (f"（{why}）" if why else "")
                    ),
                    evidence={"block_id": block_id, "source_term": r.source_term},
                ))
    # profile 级禁用词。若该词恰好是某条词条的源词，顺带给出正确译法 ——
    # 「衙门」既是禁用词（译文不该留中文原词），也是「衙门→役所」的源词。
    by_surface: dict[str, str] = {}
    for r in hits:
        if not r.target_term:
            continue
        for surface in list(getattr(r, "surfaces", None) or [r.source_term]):
            by_surface.setdefault(surface, r.target_term)

    for token in profile_forbidden:
        if token in checked:
            continue
        checked.add(token)
        if contains_token(translated_text, token):
            expected = by_surface.get(token)
            fix = (
                f"「{token}」不属于该世界观，应使用「{expected}」" if expected
                else f"「{token}」被目标世界观列为禁用词"
            )
            out.append(Violation(
                kind="forbidden_token", severity="high", detected=token,
                expected=expected, suggested_fix=fix,
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
        surfaces = list(getattr(r, "surfaces", None) or [r.source_term])
        shown = "/".join(surfaces)
        out.append(Violation(
            kind="lexicon_miss", severity="medium", detected=shown,
            expected=r.target_term,
            suggested_fix=f"原文含「{shown}」，译文应出现「{r.target_term}」",
            evidence={"block_id": block_id, "surfaces": surfaces},
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
            # suggested_fix 里带着原文哪个词、为什么 —— 比「不得使用 Mom」
            # 有用得多，模型照后者改只会换一个词继续留着 Mom
            fix = v.suggested_fix or (
                f"不得使用「{v.detected}」，应改为「{v.expected}」")
            lines.append(f"  · {fix}")
        elif v.kind == "lexicon_miss":
            lines.append(f"  · 原文的「{v.detected}」必须译为「{v.expected}」")
        elif v.kind == "name_drift":
            lines.append(f"  · 「{v.detected}」的固定译名是「{v.expected}」，不可改动")
    return "\n".join(lines)


#: 被当成称谓塞进来的那几个词。只处理呼语形态 —— 真的在跟母亲说话时
#: 「Mom」是对的，那种句子不会命中「草你妈的」这类词条。
_VOCATIVE = r"(?:Mom|Mum|Mommy|Mother|Mama)"


def repair_forbidden(text: str, violations: Sequence[Violation]) -> tuple[str, list[str]]:
    """把模型改不掉的禁用词按词条表直接改掉。

    **模型不认这一条，试过三次。** 提示词里写了「骂人的虚词不是称谓」，
    词条表里登记了「草你妈的 → Fuck you，禁用 Mom」，strict 还会带着
    违规反馈重译一次 —— 五个块里仍有四个把「妈」译成了 Mom：

        「草你妈的，别和我罗嗦」 → "Fuck you, Mom! Stop rambling"
        「妈的，给你脸你不要脸」 → "Mom's, you don't know when..."
        「我去你妈的吧」         → "Damn it, Mom! Set the other stuff aside"

    改法是确定的，不需要再问模型 —— 词条表已经写明了正确译法：

        译文里已经有正确译法（"Fuck you" 在）→ 那个 Mom 是多出来的呼语，
                                              连同它的逗号一起删掉
        没有正确译法（"Mom's" 就是 妈的 本身）→ 整段换成词条的译法

    只动 high 级的 forbidden_token，且只动呼语形态。真在跟母亲说话的
    句子不会命中「草你妈的」这类词条，也就走不到这里。
    """
    if not text:
        return text, []
    fixed = text
    notes: list[str] = []
    for v in violations:
        if v.kind != "forbidden_token" or v.severity != "high":
            continue
        if not re.fullmatch(_VOCATIVE, v.detected, re.I):
            continue
        want = (v.expected or "").strip()
        before = fixed
        if want and contains_token(fixed, want):
            # 正确译法已经在句子里了 —— Mom 是多出来的一声称呼
            fixed = re.sub(rf",\s*{_VOCATIVE}\b", "", fixed)
            fixed = re.sub(rf"\b{_VOCATIVE}\b\s*[,，]\s*", "", fixed)
            fixed = re.sub(rf"\s*[—–-]\s*{_VOCATIVE}\b", "", fixed)
            fixed = re.sub(rf"\s+{_VOCATIVE}\b(?=[!?.])", "", fixed)
        elif want:
            # 「Mom's」这类是「妈的」本身被逐字搬过来了，整段换掉
            fixed = re.sub(rf"\b{_VOCATIVE}(?:'s)?\b", want, fixed, count=1)
        if fixed != before:
            notes.append(f"{v.detected} → {want or '（删去呼语）'}")
    if fixed != text:
        fixed = re.sub(r"\s{2,}", " ", fixed).replace(" !", "!").replace(" ?", "?")
    return fixed, notes
