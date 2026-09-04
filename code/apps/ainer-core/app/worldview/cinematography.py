"""导演档案 → 图像模型看得懂的英文。

**这一层不存在时会发生什么。** 导演档案里躺着完整的摄影意图 ——
键光比、色温、对比度、颗粒、调色板、构图、景深、回避清单 ——
而它们原样拼进提示词，长这样：

    key ratio: hard_8:1, color temp: cool_with_warm_practicals,
    contrast: very_high, grain: heavy

`hard_8:1` 对扩散模型没有任何意义，`cool_with_warm_practicals` 也不是英语。
模型读不懂就当噪声跳过，于是**灯光实际上是模型自己发挥的** ——
画面出来平、亮、干净，一眼的塑料感，而后台报表上「灯光已注入」。
palette 更彻底：从建库那天起就没有任何地方读过它。

所以这里做两件事：把枚举翻成摄影师的说法，把调色板真正送出去。
翻不出来的原样带过 —— 宁可多一个怪词，也不要静默丢掉一条摄影意图。
"""
from __future__ import annotations

from typing import Any, Iterable

#: 键光比。数字比例本身模型读不准，要的是「硬光还是柔光、反差多大」
_KEY_RATIO = {
    "soft_2:1": "soft key light, gentle 2:1 lighting ratio, open shadows",
    "soft_3:1": "soft key light, 3:1 lighting ratio, gentle falloff",
    "hard_4:1": "hard key light, 4:1 lighting ratio, defined shadows",
    "hard_8:1": "hard key light, dramatic 8:1 lighting ratio, deep shadows",
    "available_light": "available light only, no artificial fill, naturalistic",
}

_COLOR_TEMP = {
    "warm_tungsten": "warm tungsten light, amber highlights",
    "neutral_daylight": "neutral daylight balance",
    "cool_with_warm_practicals": "cool ambient light with warm practical lamps in frame",
    "mixed_natural": "mixed natural light sources, unbalanced colour temperature",
    "cool_moonlight": "cool moonlight, blue shadows",
}

_CONTRAST = {
    "low": "low contrast, lifted blacks",
    "medium": "balanced contrast",
    "high": "high contrast",
    "very_high": "very high contrast, crushed blacks, small bright key areas",
}

#: 颗粒是「胶片感」最直接的一刀。数字干净画面正是塑料感的来源之一
_GRAIN = {
    "none": "clean digital capture",
    "fine_film": "fine 35mm film grain",
    "moderate": "moderate film grain",
    "coarse": "coarse film grain, 16mm texture",
    "heavy": "heavy film grain, pushed stock",
}

_FRAMING = {
    "centered_symmetric": "centred symmetrical composition",
    "dynamic_diagonal": "dynamic diagonal composition",
    "off_center_obstructed": "off-centre subject, foreground obstruction",
    "rule_of_thirds": "rule-of-thirds composition",
}

_DEPTH = {
    "layered_doorframes": "layered depth through doorways and frames within the frame",
    "telephoto_compression": "telephoto compression, flattened planes",
    "foreground_occlusion": "foreground occlusion, subject seen past objects",
    "shallow": "shallow depth of field, background falls off",
    "deep_focus": "deep focus, everything sharp",
}

_HEADROOM = {
    "generous": "generous headroom",
    "tight": "tight headroom",
    "cropped": "cropped headroom, subject pressed to the top edge",
}

#: 回避清单进负向提示词。原样丢过去是 `handheld_shake`，
#: 下划线让它变成一个不存在的词
_AVOID = {
    "handheld_shake": "handheld camera shake",
    "crash_zoom": "crash zoom",
    "dutch_angle": "dutch angle",
    "fast_cutting": "fast cutting",
    "flat_lighting": "flat even lighting",
    "static_only_coverage": "static locked-off framing",
    "pastel_palette": "pastel colours",
    "even_fill_light": "even fill light",
    "bright_daylight_exterior": "bright daylight exterior",
    "symmetrical_framing": "symmetrical framing",
}

#: 成片质感锚。没有它，模型默认交付的是「渲染图」而不是「电影画面」——
#: 干净、均匀、无质感，也就是塑料感本身。
#: 放在正向末尾：前面是这一镜要什么，这里是它该长成什么成色。
GRADE_ANCHOR = (
    "cinematic film still, photographic realism, natural skin texture and pores, "
    "physically plausible light falloff, subtle lens imperfections"
)

#: 每一次出图都要挡掉的东西。这不是风格偏好，是**塑料感的清单**：
#: 塑料味的三维渲染、AI 磨皮、过饱和 HDR、均匀无方向的光。
PLASTIC_NEGATIVES = (
    "plastic 3d render", "cgi look", "airbrushed skin", "waxy skin",
    "oversaturated hdr", "flat even lighting", "video game screenshot",
    "smooth doll face", "overly symmetric face",
)


def _phrase(table: dict[str, str], value: Any) -> str:
    """查表；查不到就把下划线拆开原样带过。

    静默丢掉的代价比多一个怪词大得多 —— 档案里加了一个新枚举，
    表里忘了补，结果是这条摄影意图从此不再出现，而没有任何地方会报错。
    """
    key = str(value or "").strip()
    if not key:
        return ""
    return table.get(key) or key.replace("_", " ")


def render_lighting(lighting: dict[str, Any] | None) -> list[str]:
    """灯光 + 调色板。palette 以前一次都没被送出去过。"""
    lit = lighting or {}
    out = [
        _phrase(_KEY_RATIO, lit.get("key_ratio")),
        _phrase(_COLOR_TEMP, lit.get("color_temp")),
        _phrase(_CONTRAST, lit.get("contrast")),
        _phrase(_GRAIN, lit.get("grain")),
    ]
    palette = [str(c).replace("_", " ").strip()
               for c in (lit.get("palette") or []) if str(c).strip()]
    if palette:
        # 只取三个。颜色给多了等于没给 —— 模型会平均成灰
        out.append("colour palette of " + ", ".join(palette[:3]))
    return [x for x in out if x]


def render_composition(composition: dict[str, Any] | None) -> list[str]:
    comp = composition or {}
    return [x for x in (
        _phrase(_FRAMING, comp.get("framing")),
        _phrase(_DEPTH, comp.get("depth")),
        _phrase(_HEADROOM, comp.get("headroom")),
    ) if x]


def render_avoid(avoid: Iterable[Any] | None) -> list[str]:
    return [x for x in (_phrase(_AVOID, a) for a in (avoid or [])) if x]
