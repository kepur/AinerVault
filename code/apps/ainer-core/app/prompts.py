"""系统提示词模板。

集中在这里，不散落在 pipeline 里 —— 提示词是要反复调的东西，
散出去以后没人找得到，也没法版本化。
运行时可被 prompt_templates 表覆盖（设置页可编辑可回滚）。
"""
from __future__ import annotations

SCRIPT_BUILD_SYSTEM = """\
你是专业的影视剧本改编师。把小说章节拆解为结构化剧本。

工作原则：
1. 【忠于原文】不增删情节，不改写对白含义。你在做结构化，不是再创作。
2. 【场景切分】以「时间 / 地点 / 在场人物」的变化为界。一个场景通常包含数个到十数个块。
3. 【块类型】严格使用下列之一：
   - narration      旁白/环境描写/叙述
   - dialogue       角色说出口的话（去掉引号，speaker 填说话人）
   - action         角色动作与行为描写
   - inner_monolog  内心独白/心理活动
   - signage        画面中出现的文字：招牌、信件、告示、手机屏幕
   - title          标题
4. 【说话人】dialogue 与 inner_monolog 必须填 speaker，用原文中的称呼原样填写。
   若确实无法判断，填 "未知"。
5. 【顺序】blocks 必须严格按原文出现顺序排列，不得重排。
6. 【完整性】原文的每一句都要落到某个块里，不要遗漏，也不要凭空添加。

场景元信息尽量填写；无法从原文判断时留空字符串，不要编造。
"""

SCRIPT_BUILD_USER = """\
章节标题：{chapter_title}
原文语言：{language}
场景粒度：{granularity}

原文：
---
{content}
---

请输出结构化剧本。"""

#: 剧本的 JSON Schema。契约要求中间层保证按此 schema 返回可解析结果。
SCRIPT_SCHEMA: dict = {
    "type": "object",
    "required": ["scenes"],
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["order", "blocks"],
                "properties": {
                    "order": {"type": "integer", "description": "场景序号，从 1 开始"},
                    "title": {"type": "string", "description": "场景短标题"},
                    "time_of_day": {"type": "string", "description": "晨/日/黄昏/夜等"},
                    "location_text": {"type": "string", "description": "地点"},
                    "weather": {"type": "string"},
                    "mood": {"type": "string", "description": "情绪基调"},
                    "summary": {"type": "string", "description": "一句话概括"},
                    "blocks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type", "text"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "narration", "dialogue", "action",
                                        "inner_monolog", "signage", "title",
                                    ],
                                },
                                "text": {"type": "string"},
                                "speaker": {
                                    "type": "string",
                                    "description": "dialogue/inner_monolog 必填",
                                },
                            },
                        },
                    },
                },
            },
        }
    },
}


ENTITY_EXTRACT_SYSTEM = """\
你从小说剧本中抽取实体，供后续视觉生成与一致性管理使用。

抽取范围：
- character  有名有姓或有固定称呼的人物（路人甲、店小二这类无名角色不抽）
- location   具体地点（长安城、城外客栈；「路上」这类泛指不抽）
- prop       有叙事作用的道具（主角的剑、那封信；桌椅这类背景不抽）
- faction    势力、门派、组织

规则：
1. canonical_key 用小写英文 + 下划线，跨章节稳定（李清照 → li_qingzhao）。
2. aliases 收集原文中出现的所有别称、简称、尊称、绰号。
3. family_key：同族人物填相同的家族标识（李清照与李格非同为 li_family）。
   无法判断亲属关系时留空。这个字段决定跨语言转译时姓氏是否统一，请谨慎填写。
4. summary 一句话，只写原文提供的信息，不要脑补。
"""

ENTITY_SCHEMA: dict = {
    "type": "object",
    "required": ["entities"],
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "canonical_key", "display_name"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["character", "location", "prop", "faction"],
                    },
                    "canonical_key": {"type": "string"},
                    "display_name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "family_key": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        }
    },
}


DEFAULTS: dict[str, str] = {
    "script_build_system": SCRIPT_BUILD_SYSTEM,
    "script_build_user": SCRIPT_BUILD_USER,
    "entity_extract_system": ENTITY_EXTRACT_SYSTEM,
}


def get_prompt(db, key: str) -> str:
    """取提示词。设置页覆盖优先，否则用内置默认。"""
    from sqlalchemy import select

    from app.models import PromptTemplate

    row = db.execute(
        select(PromptTemplate)
        .where(PromptTemplate.key == key, PromptTemplate.active.is_(True))
        .order_by(PromptTemplate.version.desc())
    ).scalars().first()
    if row:
        return row.content
    if key not in DEFAULTS:
        raise KeyError(f"未知提示词 key: {key}")
    return DEFAULTS[key]
