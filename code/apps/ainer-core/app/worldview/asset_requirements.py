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
}


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
