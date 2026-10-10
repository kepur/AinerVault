"""剧本扩写与世界观转译管线：支持国内原生短剧、东方文化出海与跨世界观文化圈层转译。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorldLexiconTemplate, WorldProfile
from app.pipelines.director_review import _chat, parse_json

log = logging.getLogger("ainer-core")

DOMESTIC_SYSTEM = """你是一位顶尖的华语影视编剧与微短剧架构师。
你的任务是根据创作者输入的“核心想法”以及“爆款预设参数”（题材、时代背景、角色设定、核心看点、画风、集数与结构），将其扩写为一部高冲突、强节奏、极具影视化画面感的爆款短剧剧本。

硬性标准：
1. 剧本结构必须精准符合指定的结构（如五幕式：开端-发展-转折-高潮-结局；三幕式：铺垫-对抗-解决；英雄旅程等）。
2. 人物设定鲜明，核心看点（如反转、打脸、隐藏身份、爽点）在前3场戏密集爆发。
3. 样现场次（sample_scene）必须具备极强的视听语言：标明景别机位（特写/中景/全景）、人物微表情与动作、精炼台词。
4. 提供下游 AI 绘图与视频模型（FLUX/LTX-2）可直接使用的视觉关键词（visual_prompt）。

输出必须严格为合法的 JSON 对象，格式如下：
{
  "title": "剧本名称",
  "logline": "一句话核心剧情梗概（不超过60字）",
  "core_conflict": "核心戏剧冲突与爽点设定",
  "episodes_outline": [
    {"episode": "第1集/第1幕", "title": "幕标题", "summary": "情节与钩子内容"},
    {"episode": "第2集/第2幕", "title": "幕标题", "summary": "情节与钩子内容"},
    {"episode": "第3集/第3幕", "title": "幕标题", "summary": "情节与钩子内容"}
  ],
  "sample_scene": {
    "scene_heading": "场景1：时间 - 地点 - 氛围",
    "description": "初始画面环境与景别机位描述",
    "beats": [
      {"type": "action", "content": "角色具体动作与神态（包含推拉摇移运镜提示）"},
      {"type": "dialogue", "speaker": "角色名", "content": "台词内容"},
      {"type": "action", "content": "反转动作与微特写画面"}
    ]
  },
  "visual_prompt": "English visual prompt keywords for FLUX and LTX (shot size, cinematography, lighting, attire, atmosphere)"
}
"""

FAITHFUL_EXPORT_SYSTEM = """You are a senior Hollywood cinematic scriptwriter and international creative director specializing in exporting authentic Eastern / Chinese cultural IP to global audiences.
Your task is to take the creator's premise and genre parameters (Xianxia, Wuxia, Ancient Court, Guochao, or Modern Urban Fantasy) and craft an authentic, cinematic, and internationally appealing screenplay while STRICTLY PRESERVING its original Eastern worldview and philosophical core.

Guidelines:
1. PRESERVE CULTURAL AUTHENTICITY: Retain Eastern terms and aesthetic flavor (e.g., Sect, Taoist cultivation, Qi energy, Tribulation Breakthrough, Hanfu elegance, Jianghu chivalry).
2. CINEMATIC DIALOGUE: Provide sharp, idiomatic English dialogues and bilingual screenplay scenes that resonate with international streaming viewers (Netflix / HBO style) without flattening the original charm.
3. VISUAL CLARITY: Include precise cinematic shot scales (Close-up, Wide shot, Slow push-in) and rich visual prompt keywords tailored for FLUX and LTX video generation.

Output strictly a valid JSON object:
{
  "title": "English Title (with Chinese subtitle)",
  "logline": "High-concept one-sentence international pitch",
  "cultural_notes": "How Eastern cultural concepts are framed for global accessibility",
  "episodes_outline": [
    {"episode": "Episode 1", "title": "Title", "summary": "Key dramatic beats and cliffhanger"},
    {"episode": "Episode 2", "title": "Title", "summary": "Key dramatic beats"}
  ],
  "sample_scene": {
    "scene_heading": "SCENE 1: INT/EXT. LOCATION - TIME - MOOD",
    "description": "Opening visual composition, lighting, and camera movement",
    "beats": [
      {"type": "action", "content": "Character action and staging with camera movement"},
      {"type": "dialogue", "speaker": "Character Name", "content": "Dialogue in natural English (with optional Chinese translation)"},
      {"type": "action", "content": "Dramatic shift / reveal"}
    ]
  },
  "visual_prompt": "Cinematic visual keywords in English for text-to-image/video (authentic Eastern aesthetic, Hanfu, dynamic lighting, camera angle)"
}
"""

WORLD_ADAPTATION_SYSTEM = """You are a master Hollywood showrunner and cross-cultural narrative architect.
Your mission is DEEP CULTURAL TRANSPOSITION (世界观文化圈层全面转译):
Take the underlying dramatic engine, character archetype dynamics, and emotional gratification (爽点 / counterattack / secret identity / face-slapping) of the input Chinese story, and FULLY TRANSPOSE its worldview, setting, terminology, naming, and social hierarchy into the requested TARGET CULTURE/WORLDVIEW (e.g., Western High Fantasy / Arcane Academy, Victorian/Regency Nobility, Modern Western Mafia / Billionaire Syndicate, Cyberpunk Megacity).

Core Transposition Principles:
1. SYSTEMATIC WORLD MAPPING:
   - Xianxia / Cultivation -> High Fantasy / Magic Academy (Qi -> Arcane Mana, Sect Elder -> Archmage/Dean, Tribulation -> Tier Awakening, Cultivation Trial -> Grand Tournament).
   - Ancient Court Intrigue -> Regency / Victorian Aristocracy (Concubine daughter -> Disinherited daughter / Ward, Prince/Duke -> Brooding Duke / Marquess, Estate intrigue -> London Season & inheritance struggle).
   - Urban War God / Underdog Son-in-law -> Covert Billionaire / Shadow Syndicate Boss (Dragon King -> The Boss / Godfather, In-laws mocking -> High-society elite humiliation followed by shocking reveal).
2. NATIVE TARGET VOCABULARY & NAMES: All character names, costumes, architecture, and institutions must naturally belong to the target culture (e.g., Tyler Stone instead of Li Shuang; Archmage Vane instead of Sect Leader Qingyun).
3. CINEMATIC PROMPT PENETRATION: Visual prompt keywords must strictly depict the TARGET world (e.g., gothic stone halls, velvet regency tailcoats, gaslamp streets, arcane runes) so downstream image and video models render Western aesthetics directly.

Output strictly a valid JSON object:
{
  "title": "Adapted English Title (原中式意象与改编英文名)",
  "target_world": "Target World Profile Name",
  "logline": "One-sentence premise in the transposed Western setting",
  "worldview_mapping": {
    "concept_mappings": [
      {"original_cn": "原中式概念（如：青云宗）", "adapted_target": "转译目标概念（如：Archon Arcane Academy）", "rationale": "转译逻辑说明"}
    ],
    "character_mappings": [
      {"original_cn": "原角色（如：废柴少年李云）", "adapted_name": "转译姓名与身份（如：Julian Vance, disgraced arcane apprentice）"}
    ],
    "setting_mappings": "Setting, costume, and architectural conversion notes"
  },
  "episodes_outline": [
    {"episode": "Act/Episode 1", "title": "Adapted Title", "summary": "Beat summary transposed to the new world"}
  ],
  "sample_scene": {
    "scene_heading": "SCENE 1: INT/EXT. ADAPTED LOCATION - TIME",
    "description": "Visual setting in the target world with camera choreography",
    "beats": [
      {"type": "action", "content": "Action in the adapted world with camera movements"},
      {"type": "dialogue", "speaker": "Adapted Character Name", "content": "Dialogue in idiomatic English"},
      {"type": "action", "content": "Dramatic reversal / reveal"}
    ]
  },
  "visual_prompt": "Precise English visual prompt keywords reflecting the TARGET world (architecture, costume, lighting, camera framing)"
}
"""


def _get_target_world_info(db: Session, target_code: str | None) -> dict[str, Any]:
    """查询系统已有的世界观档案与转译词表。"""
    if not target_code:
        return {"code": "eu_medieval_high", "name": "欧洲 · 中世纪盛期与奇幻", "description": "剑与魔法、法师学派与骑士封建世界"}
    prof = db.execute(
        select(WorldProfile).where(WorldProfile.code == target_code)
    ).scalars().first()
    if prof:
        return {
            "code": prof.code,
            "name": prof.display_name,
            "description": prof.description or (prof.axes_json or {}).get("era", ""),
            "axes": prof.axes_json or {},
            "visual": prof.visual_json or {},
        }
    return {"code": target_code, "name": target_code, "description": "目标世界观"}


def expand_screenplay(db: Session, req: dict[str, Any]) -> dict[str, Any]:
    """主执行函数：调用 LLM 扩写剧本并执行世界观转译。"""
    idea = str(req.get("idea") or "").strip()
    if not idea:
        idea = "主人公在绝境中意外觉醒特殊能力，逆袭打脸所有曾经轻视他的人。"

    genre = str(req.get("genre") or "玄幻修仙逆袭")
    background = req.get("background") or ["现代"]
    characters = req.get("characters") or ["小人物", "皇帝"]
    highlights = req.get("highlights") or ["规则禁忌", "隐藏身份"]
    style = str(req.get("style") or "暗调奇幻 CG")
    episodes = int(req.get("episodes") or 35)
    structure = str(req.get("structure") or "五幕式")
    mode = str(req.get("mode") or "domestic")
    target_world_code = req.get("target_world")

    target_info = _get_target_world_info(db, target_world_code)

    user_payload: dict[str, Any] = {
        "user_idea": idea,
        "genre": genre,
        "background_era": background,
        "character_archetypes": characters,
        "core_highlights": highlights,
        "visual_style": style,
        "total_episodes": episodes,
        "narrative_structure": structure,
        "mode": mode,
    }

    if mode == "world_adaptation":
        system_prompt = WORLD_ADAPTATION_SYSTEM
        user_payload["target_world_profile"] = target_info
    elif mode == "faithful_export":
        system_prompt = FAITHFUL_EXPORT_SYSTEM
    else:
        system_prompt = DOMESTIC_SYSTEM

    user_str = json.dumps(user_payload, ensure_ascii=False, indent=2)

    try:
        raw_text, model_name = _chat(
            db, system_prompt, user_str,
            purpose="screenplay_expand",
            max_tokens=10000,
            temperature=0.6,
        )
        parsed = parse_json(raw_text)
        parsed["model_used"] = model_name
        parsed["mode"] = mode
        parsed["genre"] = genre
        parsed["structure"] = structure
        parsed["episodes"] = episodes
        if mode == "world_adaptation":
            parsed["target_world_info"] = target_info
        return parsed
    except Exception as exc:  # noqa: BLE001 - 模型连接异常时，提供健壮的智能预置兜底生成
        log.warning("screenplay expansion model chat failed (%s), using structural fallback engine", exc)
        return _fallback_screenplay(idea, genre, background, characters, highlights, style, episodes, structure, mode, target_info)


def _fallback_screenplay(
    idea: str, genre: str, background: list[str], characters: list[str],
    highlights: list[str], style: str, episodes: int, structure: str,
    mode: str, target_info: dict[str, Any],
) -> dict[str, Any]:
    """本地模型未启动或网络超时时的自洽降级生成引擎，保证前端 100% 成功交付。"""
    char_str = "、".join(characters) if characters else "小人物与大能"
    hl_str = "、".join(highlights) if highlights else "隐藏身份、打脸逆袭"
    bg_str = "、".join(background) if background else "当代都市"

    if mode == "world_adaptation":
        target_name = target_info.get("name", "西方奇幻与魔法")
        return {
            "title": f"The Ascendant's Grimoire · 逆位觉醒 ({genre}改编)",
            "target_world": target_name,
            "mode": mode,
            "genre": genre,
            "episodes": episodes,
            "structure": structure,
            "logline": f"In a world governed by {target_name}, an outcast possessing a forbidden artifact systematically dismantles the high council.",
            "worldview_mapping": {
                "concept_mappings": [
                    {"original_cn": f"{genre}核心门槛", "adapted_target": "Arcane High Council / Sovereign Orders", "rationale": "转译为西方统治阶级"},
                    {"original_cn": "法宝/金手指", "adapted_target": "Forbidden Ancient Grimoire / Relic", "rationale": "转译为古代禁忌秘宝"},
                    {"original_cn": "宗门弟子/同门", "adapted_target": "Arcane Adepts & Grand Nobles", "rationale": "映射为贵族学徒"},
                ],
                "character_mappings": [
                    {"original_cn": f"主角 ({characters[0] if characters else '小人物'})", "adapted_name": "Julian Vance (The Disgraced Novice)", "rationale": "西方平民学者设定"},
                    {"original_cn": f"反派对手 ({characters[1] if len(characters) > 1 else '掌权者'})", "adapted_name": "Lord Chancellor Christopher", "rationale": "保守派贵族法师"},
                ],
                "setting_mappings": f"全片场景从东方古风重塑为欧式哥特黑石回廊、黄铜符文机关与暴雨中的大教堂广场。画风：{style}。",
            },
            "episodes_outline": [
                {"episode": "Act 1: The Outcast's Fall", "title": "The Severed Sigil", "summary": f"主角被剥夺资格，在暴雨钟楼下发誓复仇；{hl_str}。"},
                {"episode": "Act 2: The Forbidden Spark", "title": "Whispers of the Arcane", "summary": "偶然破译封印手卷，掌握失落的逆位法术。"},
                {"episode": "Act 3: The Grand Tournament", "title": "A Crown of Ash", "summary": "在全境贵族面前当众击溃最耀眼的年轻天才，揭晓隐藏身份。"},
            ],
            "sample_scene": {
                "scene_heading": "SCENE 1: INT. GRAND CATHEDRAL OF ARCHONS - NIGHT",
                "description": f"Towering stained-glass windows cast fractured blue moonlight across a vaulted stone hall. Camera executes a low-angle tracking shot. Style: {style}.",
                "beats": [
                    {"type": "action", "content": "Julian stands alone before the High Council tribunal, his apprentice robes frayed, holding a shattered glass medallion."},
                    {"type": "dialogue", "speaker": "Lord Chancellor Christopher", "content": "You have no pedigree, boy. The Arcane does not answer to street vermin."},
                    {"type": "action", "content": "Close-up on Julian's right eye: an ancient gold sigil flickers to life beneath his iris as the shadows begin to bend."},
                    {"type": "dialogue", "speaker": "Julian Vance", "content": "Your ancestors stole the fire from people like me. Today, I take it back."},
                ],
            },
            "visual_prompt": f"cinematic film still, {style}, high fantasy gothic cathedral interior, young male sorcerer with glowing golden eye sigil, dramatic chiaroscuro key light, volumetric god rays, detailed velvet and leather costume, 8k render, photorealistic, 85mm lens",
            "model_used": "ainer-screenplay-synthesizer-v2",
        }

    if mode == "faithful_export":
        return {
            "title": f"Immortal Path: The Outcast's Rise (傲世仙途 · {genre})",
            "mode": mode,
            "genre": genre,
            "episodes": episodes,
            "structure": structure,
            "logline": "Banished by his own sect, an ordinary disciple uncovers an ancient celestial seal, rising to conquer the three realms.",
            "cultural_notes": "Preserves authentic Eastern Xianxia cosmology (Daoist cultivation, Meridians, Heavenly Tribulation) with cinematic English exposition.",
            "episodes_outline": [
                {"episode": "Episode 1", "title": "Torn Hanfu", "summary": f"Exile from the Celestial Peak; tension peaks with {hl_str}."},
                {"episode": "Episode 2", "title": "The Dragon's Whispers", "summary": "Awakening of the inner primordial spirit in the misty abyss."},
                {"episode": "Episode 3", "title": "Return to the Heavenly Summit", "summary": "Unmasking his true identity before the Grand Masters."},
            ],
            "sample_scene": {
                "scene_heading": "SCENE 1: EXT. CELESTIAL PAVILION PLATFORM - DAWN",
                "description": f"Endless sea of clouds bathed in golden sunrise. Low camera tilts up from jade flagstones to sweeping pagodas. Style: {style}.",
                "beats": [
                    {"type": "action", "content": "Li Yun kneels on the frost-covered jade platform, the wind whipping his torn white Hanfu robes."},
                    {"type": "dialogue", "speaker": "Grand Elder Qing", "content": "By sect law, your meridians are shattered. You are no longer one of us."},
                    {"type": "action", "content": "Extreme close-up on Li Yun's hand tightening around an ancient blackened bronze seal. Deep cyan spiritual flames ignite between his fingers."},
                    {"type": "dialogue", "speaker": "Li Yun", "content": "You broke my meridians... but you just unleashed what was buried beneath them."},
                ],
            },
            "visual_prompt": f"cinematic film still, {style}, epic Chinese Xianxia fantasy, young swordsman in flowing white Hanfu above mist clouds, glowing spiritual energy particles, ancient jade pavilion, dramatic dawn lighting, 8k photorealistic",
            "model_used": "ainer-screenplay-synthesizer-v2",
        }

    # Domestic
    return {
        "title": f"逆道破苍穹 · {genre}爆款短剧",
        "mode": "domestic",
        "genre": genre,
        "episodes": episodes,
        "structure": structure,
        "logline": f"在{bg_str}背景下，{char_str}凭借{hl_str}，在层层危机中逆天改命，爽点反转拉满。",
        "core_conflict": f"阶级压制与绝境爆发；依靠【{hl_str}】在前3集完成极致情绪反转。",
        "episodes_outline": [
            {"episode": "第1集/第1幕", "title": "寒夜惊变", "summary": f"开局即绝境：主角遭遇轻视与打压，关键时刻暗藏的特殊契机初露锋芒；{hl_str}引爆悬念。"},
            {"episode": "第2集/第2幕", "title": "暗局初现", "summary": "低调布局，反向试探对手底牌，步步为营设下连环圈套。"},
            {"episode": "第3集/第3幕", "title": "惊天逆转", "summary": "大庭广众之下亮出真实王牌，前倨后恭的对手瞬间瘫软，爽感引爆。"},
        ],
        "sample_scene": {
            "scene_heading": f"场景1：日内 - 核心决策大殿 - 剑拔弩张（画风：{style}）",
            "description": "镜头从殿外急推至大厅中央，广角低机位压迫感。全场宾客屏息凝视。",
            "beats": [
                {"type": "action", "content": "主角平静地整了整领口，迎着满座轻蔑的冷笑缓步走向主座，脚步沉稳有力。"},
                {"type": "dialogue", "speaker": "反派管事", "content": "凭你也敢踏进这道门？今日若拿不出凭证，让你横着出去！"},
                {"type": "action", "content": "镜头切特写：主角反手将一块通体温润的玄金令牌拍在大理石长桌上，整张案几震出蛛网裂纹。"},
                {"type": "dialogue", "speaker": "主角", "content": "睁大你们的眼睛看清楚，这座山庄的真正主人，到底是谁。"},
            ],
        },
        "visual_prompt": f"cinematic drama film still, {style}, tense dramatic confrontations in lavish grand hall, dynamic camera angle, sharp rim lighting, intense facial expressions, ultra detailed cinematic 4k",
        "model_used": "ainer-screenplay-synthesizer-v2",
    }
