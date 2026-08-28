"""翻译 prompt 的世界观四段注入 —— v1 断链的修复点。

v1 的 translate_blocks 只注入了「源→目标语言 + 占位符 + 保持文学风格 + 术语表」，
world_transform 的信息存进了库却从不进 prompt。以下四段就是缺的那部分：
  ② 世界观声明   ③ 称谓对照   ④ 名物对照   ⑤ 禁用词

只注入本批文本命中的词条，不是整张词表 —— 一本书几百条词，一批文本通常只命中几条。
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence


class LexRow(Protocol):
    """鸭子类型：ORM 的 WorldLexicon 与测试用的轻量对象都满足。"""

    source_term: str
    target_term: str
    target_reading: str | None
    forbidden_targets: list[str] | None


def build_world_declaration(
    source_display: str,
    target_display: str,
    *,
    target_axes: dict[str, Any] | None = None,
    register: str | None = None,
    forbidden_things: Sequence[str] | None = None,
) -> str:
    """② 世界观声明。

    forbidden_things 来自档案的 visual_dont。名字带 visual 是历史包袱 ——
    它约束的其实是**名物**：摄政英国不该有电灯，中世纪欧洲不该有火器。
    这类错误比译名漂移更刺眼（读者一眼看出年代穿帮），
    而档案里早就写好了，之前只是没往提示词里送。
    """
    axes = target_axes or {}
    span = axes.get("era_span")
    # display_name 里可能已带年份，避免「昭和 (1926–1989)（1926–1989）」这种重复
    era = ""
    if isinstance(span, list) and len(span) == 2 and str(span[0]) not in target_display:
        era = f"（{span[0]}–{span[1]}）"
    social = axes.get("social_context")
    social_note = f"，社会背景为 {social}" if social else ""
    lines = [
        f"【世界观转译】源世界观：{source_display} → 目标世界观：{target_display}{era}{social_note}。",
        "译文须让目标世界观的读者感到本土自然，而非翻译腔。"
        "凡涉及场所、职官、称谓、服饰、饮食、货币、度量、兵器、交通的名词，"
        "一律按下方对照表转译，不得直译。",
    ]
    if register:
        lines.append(f"文体层级：{register}。")
    if forbidden_things:
        lines.append(
            "该世界观里**不存在**这些东西，译文不得出现，也不得用它们作比喻："
            + "、".join(str(x) for x in list(forbidden_things)[:20])
            + "。原文出现对应事物时，换成该世界观里功能相当的物件。"
        )
    return "\n".join(lines)


def build_honorific_section(honorifics: dict[str, str] | None, *, limit: int = 30) -> str:
    """③ 称谓对照。"""
    if not honorifics:
        return ""
    pairs = "、".join(f"{k}→{v}" for k, v in list(honorifics.items())[:limit])
    return f"【称谓对照】{pairs}"


def build_lexicon_section(rows: Sequence[LexRow], *, max_entries: int = 60) -> str:
    """④ 名物对照。

    左列用**原文实际出现的字面**，而不是词条主名 ——
    原文写「差役」而词条主名是「捕快」时，写「捕快→巡査」等于没写，
    模型在正文里找不到「捕快」，自然不会替换。
    """
    usable = [r for r in rows if r.target_term]
    if not usable:
        return ""
    lines = ["【名物对照】以下词语必须使用右列译法："]
    emitted: set[str] = set()
    for r in usable:
        reading = f"（{r.target_reading}）" if r.target_reading else ""
        # LexHit 带 surfaces（实际命中的字面）；普通词条退回主名
        surfaces = list(getattr(r, "surfaces", None) or [r.source_term])
        for surface in surfaces:
            if surface in emitted:
                continue
            emitted.add(surface)
            lines.append(f"  {surface} → {r.target_term}{reading}")
            if len(emitted) >= max_entries:
                return "\n".join(lines)
    return "\n".join(lines)


def build_forbidden_section(
    rows: Sequence[LexRow], profile_forbidden: Sequence[str] = ()
) -> str:
    """⑤ 禁用词。闸二反向校验的另一半。"""
    tokens: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for f in r.forbidden_targets or []:
            if f and f not in seen:
                seen.add(f)
                tokens.append(f)
    for f in profile_forbidden:
        if f and f not in seen:
            seen.add(f)
            tokens.append(f)
    if not tokens:
        return ""
    return "【禁用词】译文中不得出现：" + "、".join(tokens)


PLACEHOLDER_RULE = (
    "【占位符】形如 {{CHAR:xxx}} / {{LOC:xxx}} 的占位符必须原样保留，"
    "不得翻译、改写或删除。"
)


def compose_system_prompt(
    *,
    source_display: str,
    target_display: str,
    target_language: str,
    hits: Sequence[LexRow],
    target_axes: dict[str, Any] | None = None,
    target_visual: dict[str, Any] | None = None,
    language_cfg: dict[str, Any] | None = None,
    glossary_lines: str = "",
    style_prompt: str | None = None,
) -> str:
    """组装完整 system prompt。①–⑤ 加术语表、风格与占位符规则。"""
    cfg = language_cfg or {}
    parts = [
        f"你是专业文学译者，从 {source_display} 的原文译为 {target_language}。"
        "逐块对齐翻译，保持文学性，不增删情节。",
        build_world_declaration(
            source_display, target_display,
            target_axes=target_axes, register=cfg.get("register"),
            forbidden_things=(target_visual or {}).get("visual_dont"),
        ),
        build_honorific_section(cfg.get("honorifics")),
        build_lexicon_section(hits),
        build_forbidden_section(hits, cfg.get("forbidden_tokens") or []),
    ]
    if glossary_lines:
        parts.append(f"【术语表】必须严格遵守，不得改动：\n{glossary_lines}")
    if style_prompt:
        parts.append(f"【风格】{style_prompt}")
    parts.append(PLACEHOLDER_RULE)
    return "\n\n".join(p for p in parts if p)
