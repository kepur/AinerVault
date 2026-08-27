"""内置导演包 —— 镜头语言与视觉叙事的风格档案。

与 world_profile 正交：
  world_profile     决定「画面里有什么」（名物、服饰、建筑）
  director_profile  决定「怎么拍」（景别、运镜、节奏、构图、光线）
同一个昭和日本，可以配小津式静态长镜，也可以配黑泽式动态多机位。

shot_sizes 的分布是关键参数：它直接决定分镜生成时切多少个镜头、切成什么景别。
"""
from __future__ import annotations

from typing import Any

DIRECTOR_PROFILES: list[dict[str, Any]] = [
    {
        "code": "static_contemplative",
        "display_name": "静观式 · 固定长镜",
        "summary": "低机位、固定不动、构图对称，让人物进出画框。"
                   "情绪靠停顿与留白，不靠运镜推动。适合家庭剧、文学改编。",
        "camera": {
            "shot_sizes": {"ecu": 0.02, "cu": 0.15, "ms": 0.38, "fs": 0.25,
                           "ws": 0.18, "els": 0.02},
            "movement": {"static": 0.82, "pan": 0.10, "push_in": 0.05, "handheld": 0.0,
                         "orbit": 0.03},
            "angle_bias": "low_eye_level",
            "lens_mm": 50,
            "height": "tatami_level",
        },
        "editing": {
            "avg_shot_ms": 7500, "rhythm": "slow_even",
            "transitions": ["cut"], "scene_open_with": "empty_frame",
            "scene_close_with": "empty_frame_after_exit",
        },
        "composition": {
            "framing": "centered_symmetric", "symmetry": 0.8, "headroom": "generous",
            "depth": "layered_doorframes", "negative_space": 0.4,
        },
        "lighting": {"key_ratio": "soft_2:1", "color_temp": "warm_tungsten",
                     "contrast": "low", "palette": ["sepia", "indigo", "off_white"],
                     "grain": "fine_film"},
        "avoid": ["handheld_shake", "crash_zoom", "dutch_angle", "fast_cutting"],
    },
    {
        "code": "kinetic_ensemble",
        "display_name": "动势式 · 多机位群戏",
        "summary": "长焦压缩、多机位同时记录、横向运动强烈。"
                   "群戏与动作场面的调度感，天气与人群参与叙事。",
        "camera": {
            "shot_sizes": {"ecu": 0.05, "cu": 0.2, "ms": 0.3, "fs": 0.2,
                           "ws": 0.2, "els": 0.05},
            "movement": {"static": 0.35, "pan": 0.25, "push_in": 0.15,
                         "handheld": 0.15, "orbit": 0.10},
            "angle_bias": "eye_level_to_low",
            "lens_mm": 135,
            "height": "standing",
        },
        "editing": {
            "avg_shot_ms": 3200, "rhythm": "accelerating",
            "transitions": ["cut", "wipe"], "scene_open_with": "wide_establishing",
            "scene_close_with": "action_beat",
        },
        "composition": {
            "framing": "dynamic_diagonal", "symmetry": 0.25, "headroom": "tight",
            "depth": "telephoto_compression", "negative_space": 0.15,
        },
        "lighting": {"key_ratio": "hard_4:1", "color_temp": "neutral_daylight",
                     "contrast": "high", "palette": ["ash_grey", "mud_brown", "steel"],
                     "grain": "coarse"},
        "avoid": ["flat_lighting", "static_only_coverage", "pastel_palette"],
    },
    {
        "code": "noir_mood",
        "display_name": "情绪式 · 光影叙事",
        "summary": "低照度、强对比、局部照亮。大量前景遮挡与反射。"
                   "情绪先于信息，人物常被环境吞没。",
        "camera": {
            "shot_sizes": {"ecu": 0.12, "cu": 0.3, "ms": 0.28, "fs": 0.15,
                           "ws": 0.13, "els": 0.02},
            "movement": {"static": 0.5, "pan": 0.15, "push_in": 0.25,
                         "handheld": 0.05, "orbit": 0.05},
            "angle_bias": "canted_and_high",
            "lens_mm": 35,
            "height": "varied",
        },
        "editing": {
            "avg_shot_ms": 5000, "rhythm": "irregular",
            "transitions": ["cut", "dissolve"], "scene_open_with": "detail_insert",
            "scene_close_with": "fade_to_shadow",
        },
        "composition": {
            "framing": "off_center_obstructed", "symmetry": 0.15,
            "headroom": "cramped", "depth": "foreground_occlusion",
            "negative_space": 0.55,
        },
        "lighting": {"key_ratio": "hard_8:1", "color_temp": "cool_with_warm_practicals",
                     "contrast": "very_high", "palette": ["ink_black", "amber", "teal"],
                     "grain": "heavy"},
        "avoid": ["even_fill_light", "bright_daylight_exterior", "symmetrical_framing"],
    },
    {
        "code": "documentary_plain",
        "display_name": "纪实式 · 素朴记录",
        "summary": "自然光、中景为主、少修饰。镜头像旁观者而非叙述者。"
                   "适合写实题材与冷静叙事。",
        "camera": {
            "shot_sizes": {"ecu": 0.03, "cu": 0.18, "ms": 0.42, "fs": 0.22,
                           "ws": 0.13, "els": 0.02},
            "movement": {"static": 0.6, "pan": 0.2, "push_in": 0.05,
                         "handheld": 0.15, "orbit": 0.0},
            "angle_bias": "eye_level",
            "lens_mm": 35,
            "height": "standing",
        },
        "editing": {
            "avg_shot_ms": 4500, "rhythm": "even",
            "transitions": ["cut"], "scene_open_with": "medium_context",
            "scene_close_with": "cut_on_action",
        },
        "composition": {
            "framing": "rule_of_thirds", "symmetry": 0.35, "headroom": "natural",
            "depth": "moderate", "negative_space": 0.25,
        },
        "lighting": {"key_ratio": "available_light", "color_temp": "mixed_natural",
                     "contrast": "medium", "palette": ["desaturated_natural"],
                     "grain": "moderate"},
        "avoid": ["theatrical_lighting", "extreme_angles", "stylized_color_grade"],
    },
]
