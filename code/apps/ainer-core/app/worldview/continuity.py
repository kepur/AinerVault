"""场记：跨镜连续性检查 —— 单镜看都对，连起来才露馅。

这类错误有个共同点：**每一镜自己都完全合理**。
主光从左前打过来没问题，下一镜从右前打过来也没问题，
可放在同一场戏里，观众会觉得太阳在两秒里转了半圈。

所以它必须跨镜比对，而且**可以形式化判定** —— 不需要模型。
方位、左右关系、视线朝向、道具有无、色温，这些都是能比的量。
让模型看整场戏再问它「有没有跳」，它会给一堆似是而非的提醒，
而真正的翻轴反倒漏掉。

四类检查，只在**同一场景内**的相邻镜之间做 ——
换了场当然可以换光、换位置。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: 方位词 → 水平角度（度）。正前为 0，左为负，右为正。
#: 只取水平分量 —— 上下高度换了不算跳轴，左右换了才是。
_AZIMUTH: dict[str, int] = {
    "左前": -45, "前左": -45, "左侧前": -45,
    "右前": 45, "前右": 45, "右侧前": 45,
    "左后": -135, "后左": -135,
    "右后": 135, "后右": 135,
    "正左": -90, "左侧": -90, "左方": -90,
    "正右": 90, "右侧": 90, "右方": 90,
    "正前": 0, "前方": 0, "正面": 0, "顺光": 0,
    "正后": 180, "后方": 180, "背后": 180, "逆光": 180,
}
_DEG = re.compile(r"(左|右)?\s*(\d{1,3})\s*度")
#: 主光方位跳变超过这个角度即报警。
#: 90 度是经验值：同场戏里光源转过四分之一圈，观众能明确察觉。
_LIGHT_JUMP_DEG = 90

#: 色温跳变阈值（开尔文）。同一场戏跨过这个差值，会被看成换了时间。
_TEMP_JUMP_K = 2000
_KELVIN = re.compile(r"(\d{3,5})\s*[kK]")

#: 站位 → 水平序位。用于判翻轴：同一对角色的左右关系不能反转。
_STAGE_ORDER: dict[str, int] = {
    "far_left": -3, "left": -2, "center_left": -1,
    "center": 0,
    "center_right": 1, "right": 2, "far_right": 3,
}


@dataclass(frozen=True)
class Issue:
    kind: str
    severity: str          # high | medium | low
    shot_from: int
    shot_to: int
    detail: str
    subjects: tuple[str, ...] = ()


def _azimuth(text: str) -> int | None:
    """从一句灯光描述里读出主光的水平方位。读不出返回 None。

    **先认方位词再认度数** —— 「左前方 45 度」里的 45 是对方位词的细化，
    不是独立角度；只认数字会把它读成正右 45，于是与「右前方 45 度」
    完全一样，跳变就漏检了。
    """
    if not text:
        return None
    for word, deg in _AZIMUTH.items():
        if word in text:
            return deg
    m = _DEG.search(text)
    if m:
        side, num = m.group(1), int(m.group(2))
        if side == "左":
            return -num
        return num
    return None


def _kelvin(text: str) -> int | None:
    m = _KELVIN.search(text or "")
    return int(m.group(1)) if m else None


def _angle_delta(a: int, b: int) -> int:
    """两个方位的夹角，取小于 180 的那一侧。"""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def check_lighting(prev: dict, cur: dict) -> list[Issue]:
    """光位与色温的跳变。"""
    out: list[Issue] = []
    pa, ca = _azimuth(prev.get("key_light", "")), _azimuth(cur.get("key_light", ""))
    if pa is not None and ca is not None:
        d = _angle_delta(pa, ca)
        if d >= _LIGHT_JUMP_DEG:
            out.append(Issue(
                "light_direction_jump", "high",
                prev["order"], cur["order"],
                f"主光方位从 {pa}° 跳到 {ca}°（相差 {d}°）—— "
                f"同一场戏里光源不会转这么多，观众会觉得太阳动了",
            ))
    pk, ck = _kelvin(prev.get("color_temp", "")), _kelvin(cur.get("color_temp", ""))
    if pk and ck and abs(pk - ck) >= _TEMP_JUMP_K:
        out.append(Issue(
            "color_temp_jump", "medium", prev["order"], cur["order"],
            f"色温从 {pk}K 跳到 {ck}K —— 同场戏里这个差别会被看成换了时间",
        ))
    return out


def check_axis(prev: dict, cur: dict) -> list[Issue]:
    """翻轴：同一对角色的左右关系不能反转。

    A 在左 B 在右，下一镜变成 A 在右 —— 观众会以为他们换了位置，
    或者以为镜头跳到了对面。这是连续性里最刺眼的一种错，
    也是最容易犯的：单看每一镜的构图都合理。
    """
    out: list[Issue] = []
    pa, ca = prev.get("positions") or {}, cur.get("positions") or {}
    shared = [n for n in pa if n in ca]
    for i, a in enumerate(shared):
        for b in shared[i + 1:]:
            p_rel = _STAGE_ORDER.get(pa[a], 0) - _STAGE_ORDER.get(pa[b], 0)
            c_rel = _STAGE_ORDER.get(ca[a], 0) - _STAGE_ORDER.get(ca[b], 0)
            if p_rel == 0 or c_rel == 0:
                continue
            if (p_rel > 0) != (c_rel > 0):
                out.append(Issue(
                    "axis_flip", "high", prev["order"], cur["order"],
                    f"{a} 与 {b} 的左右关系反转了 —— "
                    f"上一镜 {pa[a]}/{pa[b]}，这一镜 {ca[a]}/{ca[b]}。"
                    f"越轴会让观众以为他们换了位置",
                    (a, b),
                ))
    return out


def check_gaze(cur: dict) -> list[Issue]:
    """对视时视线要相向。

    两个人对话却都看向画面同一侧，观众会觉得他们没在交流 ——
    这是对切镜头最常见的失误，而且在单镜里完全看不出来。
    """
    out: list[Issue] = []
    gaze = cur.get("gaze") or {}
    positions = cur.get("positions") or {}
    for a, target in gaze.items():
        if target not in positions or a not in positions:
            continue
        a_pos = _STAGE_ORDER.get(positions[a], 0)
        t_pos = _STAGE_ORDER.get(positions[target], 0)
        if a_pos == t_pos:
            continue
        facing = (cur.get("facing") or {}).get(a, "")
        # A 在左看向右边的 B，就该是右侧脸；反之亦然
        expect = "profile_right" if t_pos > a_pos else "profile_left"
        wrong = "profile_left" if t_pos > a_pos else "profile_right"
        if facing == wrong:
            out.append(Issue(
                "gaze_mismatch", "medium", cur["order"], cur["order"],
                f"{a} 看向 {target}，但朝向是 {facing} —— "
                f"{target} 在他的{'右' if t_pos > a_pos else '左'}边，"
                f"应该是 {expect}",
                (a, target),
            ))
    return out


def check_props(prev: dict, cur: dict) -> list[Issue]:
    """道具不能凭空出现或消失。

    这一镜手里握着刀，下一镜空手，中间没有放下的动作 ——
    观众未必说得出哪里不对，但会觉得别扭。
    有动作交代（action 里提到）就不算问题。
    """
    out: list[Issue] = []
    pp, cp = prev.get("props") or {}, cur.get("props") or {}
    actions = " ".join((cur.get("actions") or {}).values())
    for who in set(pp) & set(cp):
        gone = set(pp[who]) - set(cp[who])
        came = set(cp[who]) - set(pp[who])
        for item in sorted(gone):
            if item in actions:
                continue          # 动作里交代了（放下、收起、扔出）
            out.append(Issue(
                "prop_vanished", "medium", prev["order"], cur["order"],
                f"{who} 手里的「{item}」不见了，而动作里没有交代",
                (who, item),
            ))
        for item in sorted(came):
            if item in actions:
                continue
            out.append(Issue(
                "prop_appeared", "low", prev["order"], cur["order"],
                f"{who} 手里多了「{item}」，而动作里没有交代",
                (who, item),
            ))
    return out


def check_scene(shots: list[dict]) -> list[Issue]:
    """检查一场戏内的全部镜头。

    只在**同一场景内**相邻比对 —— 换了场当然可以换光、换位置。
    调用方负责按 scene 分组。
    """
    issues: list[Issue] = []
    for cur in shots:
        issues.extend(check_gaze(cur))
    for prev, cur in zip(shots, shots[1:]):
        issues.extend(check_lighting(prev, cur))
        issues.extend(check_axis(prev, cur))
        issues.extend(check_props(prev, cur))
    return issues


_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def summarize(issues: list[Issue]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for i in issues:
        by_kind[i.kind] = by_kind.get(i.kind, 0) + 1
        by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
    return {
        "total": len(issues), "by_kind": by_kind, "by_severity": by_sev,
        "items": [
            {
                "kind": i.kind, "severity": i.severity,
                "shot_from": i.shot_from, "shot_to": i.shot_to,
                "detail": i.detail, "subjects": list(i.subjects),
            }
            for i in sorted(issues, key=lambda x: (
                _SEV_ORDER[x.severity], x.shot_from))
        ],
    }
