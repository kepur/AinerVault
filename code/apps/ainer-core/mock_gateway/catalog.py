"""Discovery 目录。param_schema 是后台自动渲染参数表单的依据。"""
from __future__ import annotations

CONTRACT_VERSION = "1.0"

_IMAGE_PARAMS = {
    "type": "object",
    "properties": {
        "steps": {"type": "integer", "minimum": 1, "maximum": 50, "default": 28,
                  "title": "采样步数"},
        "cfg": {"type": "number", "minimum": 1, "maximum": 20, "default": 7.5,
                "title": "提示词强度"},
        "seed": {"type": "integer", "title": "随机种子",
                 "description": "留空则随机；首尾帧应使用同一 seed"},
    },
}

CATALOG = {
    "capability_version": CONTRACT_VERSION,
    "capabilities": [
        {
            "capability": "text.chat",
            "models": [{
                "id": "mock-llm-1", "display_name": "Mock LLM", "default": True,
                "async_only": False, "estimated_ms": 800,
                "pricing": {"unit": "1k_tokens", "cost": 0.0, "currency": "USD"},
                "limits": {"max_tokens": 32768},
                "param_schema": {
                    "type": "object",
                    "properties": {
                        "temperature": {"type": "number", "minimum": 0, "maximum": 2,
                                        "default": 0.7, "title": "温度"},
                    },
                },
            }],
        },
        {
            "capability": "text.translate",
            "models": [{
                "id": "mock-translator-1", "display_name": "Mock Translator", "default": True,
                "async_only": False, "estimated_ms": 900,
                "pricing": {"unit": "1k_tokens", "cost": 0.0, "currency": "USD"},
                "limits": {"max_segments": 100},
                "param_schema": {"type": "object", "properties": {}},
            }],
        },
        {
            "capability": "image.text_to_image",
            "models": [{
                "id": "mock-image-1", "display_name": "Mock Image", "default": True,
                "async_only": True, "estimated_ms": 2500,
                "pricing": {"unit": "image", "cost": 0.032, "currency": "USD"},
                "limits": {
                    "max_prompt_chars": 2000, "max_ref_images": 4,
                    "sizes": ["1024x1024", "1280x720", "720x1280", "1920x1080"],
                },
                "param_schema": _IMAGE_PARAMS,
            }],
        },
        {
            "capability": "image.image_to_image",
            "models": [{
                "id": "mock-image-1", "display_name": "Mock Image", "default": True,
                "async_only": True, "estimated_ms": 2200,
                "pricing": {"unit": "image", "cost": 0.028, "currency": "USD"},
                "limits": {"max_ref_images": 4},
                "param_schema": {
                    "type": "object",
                    "properties": {
                        **_IMAGE_PARAMS["properties"],
                        "strength": {
                            "type": "number", "minimum": 0, "maximum": 1, "default": 0.35,
                            "title": "改动幅度",
                            "description": "0 保持原图，1 完全重绘。尾帧推荐 0.25–0.45",
                        },
                    },
                },
            }],
        },
        {
            "capability": "audio.tts",
            "models": [{
                "id": "mock-tts-1", "display_name": "Mock TTS", "default": True,
                "async_only": True, "estimated_ms": 1200,
                "pricing": {"unit": "1k_chars", "cost": 0.015, "currency": "USD"},
                "limits": {"max_chars": 5000, "formats": ["wav", "mp3"]},
                "param_schema": {
                    "type": "object",
                    "properties": {
                        "speed": {"type": "number", "minimum": 0.5, "maximum": 2.0,
                                  "default": 1.0, "title": "语速"},
                        "pitch": {"type": "number", "minimum": -12, "maximum": 12,
                                  "default": 0, "title": "音高（半音）"},
                        "emotion": {"type": "string", "title": "情绪",
                                    "enum": ["neutral", "calm", "happy", "sad", "angry", "tense"],
                                    "default": "neutral"},
                    },
                },
            }],
        },
        {
            "capability": "audio.voice_list",
            "models": [{"id": "mock-tts-1", "display_name": "Mock TTS", "default": True,
                        "param_schema": {"type": "object", "properties": {}}}],
        },
        {
            "capability": "audio.music",
            "models": [{
                "id": "mock-music-1", "display_name": "Mock Music", "default": True,
                "async_only": True, "estimated_ms": 4000,
                "pricing": {"unit": "clip", "cost": 0.05, "currency": "USD"},
                "param_schema": {"type": "object", "properties": {}},
            }],
        },
        {
            "capability": "audio.sfx",
            "models": [{
                "id": "mock-sfx-1", "display_name": "Mock SFX", "default": True,
                "async_only": True, "estimated_ms": 1500,
                "pricing": {"unit": "clip", "cost": 0.01, "currency": "USD"},
                "param_schema": {"type": "object", "properties": {}},
            }],
        },
        {
            "capability": "video.image_to_video",
            "models": [{
                "id": "mock-video-1", "display_name": "Mock Video", "default": True,
                "async_only": True, "estimated_ms": 9000,
                "pricing": {"unit": "second", "cost": 0.12, "currency": "USD"},
                "limits": {"max_duration_ms": 10000, "fps": [24, 30]},
                "param_schema": {
                    "type": "object",
                    "properties": {
                        "motion_strength": {"type": "number", "minimum": 0, "maximum": 1,
                                            "default": 0.5, "title": "运动强度"},
                        "seed": {"type": "integer", "title": "随机种子"},
                    },
                },
            }],
        },
    ],
}

VOICES = [
    {"voice_id": "mock_male_calm", "display_name": "Ren · 沉稳男声",
     "languages": ["ja-JP", "zh-CN", "en-US"], "gender": "male", "age": "adult",
     "tags": ["calm", "narration"],
     "supports": {"clone": False, "emotion": True, "timestamps": True}},
    {"voice_id": "mock_female_soft", "display_name": "Shizuka · 温柔女声",
     "languages": ["ja-JP", "zh-CN"], "gender": "female", "age": "adult",
     "tags": ["soft", "dialogue"],
     "supports": {"clone": False, "emotion": True, "timestamps": True}},
    {"voice_id": "mock_male_rough", "display_name": "Gorou · 粗粝男声",
     "languages": ["ja-JP"], "gender": "male", "age": "middle",
     "tags": ["rough", "villain"],
     "supports": {"clone": False, "emotion": True, "timestamps": False}},
    {"voice_id": "mock_narrator_en", "display_name": "Ethan · 英语旁白",
     "languages": ["en-US", "en-GB"], "gender": "male", "age": "adult",
     "tags": ["narration"],
     "supports": {"clone": False, "emotion": False, "timestamps": True}},
]
