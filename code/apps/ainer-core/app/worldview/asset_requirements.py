"""各类素材的必填结构化字段 —— 完整度检查的依据。

SKILL_33 的主张：素材要结构化，不塞整段自然语言。
「材质=木綿、廓形=着流し、时代记号=昭和初期」比「一件昭和时期的棉布和服」
更可控、可比对、可局部改写，也才能判断「这条素材到底完整没有」。

world_profile 可以在 axes/visual 里覆写自己的要求（如中世纪欧洲额外要求 dye_source）。
"""
from __future__ import annotations

from typing import Any

from app.models import AssetKindSpec

#: kind → 必填字段 → 中文说明（说明会进 LLM prompt，让它知道要填什么）
BASE_REQUIREMENTS: dict[str, dict[str, str]] = {
    AssetKindSpec.costume.value: {
        "silhouette": "廓形与穿着方式",
        "fabric": "材质",
        "color": "主色与配色",
        "social_marker": "透露的身份/阶层标记",
        "era_marker": "时代记号（能一眼认出年代的细节）",
    },
    AssetKindSpec.prop.value: {
        "material": "材质",
        "size": "尺寸感",
        "wear": "使用痕迹/新旧",
        "era_marker": "时代记号",
    },
    AssetKindSpec.location.value: {
        "architecture": "建筑/空间结构",
        "materials": "主要材质",
        "lighting": "常态光源",
        "props": "标志性陈设",
        "era_marker": "时代记号",
    },
    AssetKindSpec.expression.value: {
        "facial": "面部特征",
        "intensity": "强度",
    },
    AssetKindSpec.action.value: {
        "posture": "姿态",
        "motion": "动作要点",
    },
    AssetKindSpec.ambience.value: {
        "time_of_day": "时段",
        "weather": "天气",
        "light_quality": "光质",
        "mood": "情绪基调",
    },
    AssetKindSpec.style.value: {
        "medium": "媒介感（胶片/数码/绘画）",
        "palette": "色板",
        "grain": "颗粒/质感",
    },
    AssetKindSpec.creature.value: {
        "species": "种类",
        "size": "体型",
        "markings": "标记/毛色",
    },
    # ── 音频素材 ──
    AssetKindSpec.voice.value: {
        "timbre": "音色质地（清亮/沙哑/低沉）",
        "age_range": "听感年龄",
        "pace": "语速与节奏",
        "register": "语体（正式/市井/文雅）",
        "emotional_baseline": "常态情绪基调",
    },
    AssetKindSpec.sfx.value: {
        "source": "发声物",
        "texture": "质感（干脆/闷响/绵长）",
        "duration_hint": "典型时长",
    },
    AssetKindSpec.bgm.value: {
        "instrumentation": "配器",
        "tempo": "速度",
        "mood": "情绪",
        "era_marker": "时代记号（乐器与和声要属于该年代）",
    },
    AssetKindSpec.room_tone.value: {
        "space": "空间类型（室内/街巷/旷野）",
        "layers": "构成层次（雨声/人语/器物声）",
        "loudness": "响度基准",
    },
}

#: 音频类素材。参考物是音频而非图片，生成走 TTS / music / sfx 而非 t2i。
AUDIO_KINDS: frozenset[str] = frozenset({
    AssetKindSpec.voice.value,
    AssetKindSpec.sfx.value,
    AssetKindSpec.bgm.value,
    AssetKindSpec.room_tone.value,
})


def is_audio_kind(kind: str) -> bool:
    return kind in AUDIO_KINDS


def requirements_for(kind: str, world_profile: Any | None = None) -> dict[str, str]:
    """取某类素材的必填字段。world_profile 可追加自己的要求。"""
    base = dict(BASE_REQUIREMENTS.get(kind, {}))
    if world_profile is not None:
        extra = ((world_profile.visual_json or {}).get("asset_requirements") or {})
        base.update(extra.get(kind) or {})
    return base


def check_completeness(
    kind: str, structured: dict[str, Any] | None, world_profile: Any | None = None
) -> list[str]:
    """返回缺失的必填字段。空列表 = 完整。"""
    required = requirements_for(kind, world_profile)
    data = structured or {}
    return [
        key for key in required
        if not str(data.get(key) or "").strip()
    ]


def diagnose(kind: str, structured: dict[str, Any] | None,
             world_profile: Any | None = None) -> str | None:
    """缺项时说清楚是**哪一种**缺，而不只是列出字段名。

    有一种「缺」特别耽误人：答案全在，只是被塞进了一个以类别名为键的
    字符串里 ——

        {"ambience": "night, heavy_snowfall, gas_lamp_glow, serene_eerie"}

    四项一个不少，而报表说「缺 time_of_day / weather / light_quality」。
    照着这条去查，会以为模型没答、去调提示词的措辞、去换模型 ——
    实际上要改的只是键名。**报「缺」而不说是哪一种缺，会把人引向错的方向。**
    """
    missing = check_completeness(kind, structured, world_profile)
    if not missing:
        return None
    data = structured or {}
    if str(data.get(kind) or "").strip():
        return (f"答案挤在 structured[\"{kind}\"] 这一个键里了，"
                f"应拆成 {'/'.join(missing)} 各一个键")
    echoed = [k for k in missing if str(data.get(k) or "").strip() == k]
    if echoed:
        return f"{'/'.join(echoed)} 把字段名当成了值"
    return None
