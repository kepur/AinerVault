"""实体抽取：从剧本里找出人物、地点、道具，建成稳定的 world_entities。

实体是两件事的前置：
  占位符防漂移  —— 人名替换成 {{CHAR:xxx}} 后才进 LLM，人名根本不参与翻译
  家族姓氏一致  —— 同 family_key 的角色整族一起命名，父女不会变成两个姓

canonical_key 一旦建立就不再变，跨章节复用；别名归并保证「李清照 / 易安 / 清照」
指向同一个实体，这是占位符能替干净的前提。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, DocStatus, EntityKind, ScriptBlock, ScriptDoc, WorldEntity,
)
from app.pipelines.base import PipelineError, chat_json
from app.worldview.naming import cn_surname, infer_family_key

log = logging.getLogger(__name__)

#: 世界模型抽离的完整产出。五类，每类都带原文证据 ——
#: 任何判断都要能回到原文复核，不能只给一个结论。
EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["entities"],
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["display_name", "kind"],
                "properties": {
                    "display_name": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["character", "location", "prop", "faction"],
                    },
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                    "family_hint": {"type": "string"},
                    "importance": {"type": "integer"},
                    # 人物
                    "appearance": {"type": "string"},
                    "voice_hints": {"type": "string"},
                    # 场景
                    "visual_keywords": {"type": "array", "items": {"type": "string"}},
                    # 道具
                    "owner": {"type": "string"},
                    "usage": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["order", "title", "tension_level"],
                "properties": {
                    "order": {"type": "integer"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "tension_level": {"type": "integer"},
                    "location": {"type": "string"},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "style_hints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lighting_style": {"type": "string"},
                    "color_palette": {"type": "array", "items": {"type": "string"}},
                    "mood": {"type": "string"},
                    "camera_hint": {"type": "string"},
                    "texture": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

EXTRACT_SYSTEM = """你是小说的世界模型抽离专家。从文本中抽出后续制作要用的全部结构。

要抽五类：

entities — 需要在全书保持一致的实体
  character  有名有姓的人物，以及有稳定称呼的角色
  location   具体地名，不要抽「屋里」「街上」这类泛指
  prop       有身份的器物，不要抽「一把剑」这类泛指
  faction    门派、家族、组织

beats — 剧情节拍
  把这一章切成若干叙事单元，每个给出张力值 1–5。
  张力决定分镜密度：5 的段落要切碎，1 的段落可以给长镜头。

style_hints — 风格提示
  这一章的光影、色调、情绪、镜头感。通常一条，最多两条。

关键要求：
1. display_name 用原文中最正式的称呼。「李清照」而不是「清照」。
2. aliases 收全同一实体的其他叫法：小名、尊称、绰号、单用的名。
   「李清照 / 易安居士 / 清照 / 李娘子」是同一人，必须并成一条。
   别名收不全，后续占位符就替不干净，人名会漏译成原文。
3. 人物必须填 appearance（原文里的外貌描写）与 voice_hints
   （语气、语速、口头禅）—— 前者是画面的输入，后者是配音的输入。
   原文没写就留空，不要编。
4. 场景填 visual_keywords；道具填 owner 与 usage。
5. family_hint 填该人物所属家族的姓（如「李」），无法判断留空。
6. importance 1–5，5 为主角。
7. **每一条都要给 evidence**：摘 1–2 句原文原话作为依据。
   没有原文支撑的判断不要写 —— 审校时要能逐条回到原文复核。"""


@dataclass
class ExtractResult:
    created: int = 0
    updated: int = 0
    total: int = 0
    beats: int = 0
    style_hints: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    names: list[str] = field(default_factory=list)
    families: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created, "updated": self.updated, "total": self.total,
            "beats": self.beats, "style_hints": self.style_hints,
            "by_kind": self.by_kind,
            "names": self.names, "families": self.families,
        }


def _canonical_key(name: str, kind: str) -> str:
    """稳定标识。同名同类型跨章节复用同一条实体。"""
    slug = re.sub(r"\s+", "_", name.strip())
    slug = re.sub(r"[^\w一-鿿-]", "", slug)
    return f"{kind}.{slug}" if slug else f"{kind}.{abs(hash(name)) % 10**8}"


def _blocks_text(db: Session, chapter: Chapter, limit: int = 8000) -> tuple[str, list[str]]:
    """取该章 active 剧本的正文，以及出现过的 speaker 标签。

    speaker_tag 是 script_build 按原文称呼原样填的，是实体抽取的高质量线索。
    """
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id, ScriptDoc.status == DocStatus.active
        )
    ).scalars().first()
    if doc is None:
        return (chapter.content or "")[:limit], []

    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )
    speakers = sorted({b.speaker_tag for b in blocks if b.speaker_tag})
    text = "\n".join(b.source_text for b in blocks if b.source_text)
    return text[:limit], speakers


def extract_entities(
    db: Session, chapter: Chapter, *, min_importance: int = 2
) -> ExtractResult:
    """抽取一章的实体并合并进 world_entities。

    幂等：已存在的 canonical_key 只补别名，不覆盖已锁定的实体。
    """
    text, speakers = _blocks_text(db, chapter)
    if not text.strip():
        raise PipelineError("章节没有正文，无法抽取实体")

    hint = f"\n\n【已识别的说话人】{', '.join(speakers)}" if speakers else ""
    data, _task = chat_json(
        db,
        [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": f"【原文】\n{text}{hint}"},
        ],
        EXTRACT_SCHEMA,
        purpose="extract",
        novel_id=chapter.novel_id,
        chapter_id=chapter.id,
        ref_kind="entity_extract",
        ref_id=chapter.id,
    )

    existing = {
        e.canonical_key: e
        for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)
        ).scalars()
    }

    result = ExtractResult()
    for item in data.get("entities") or []:
        name = str(item.get("display_name") or "").strip()
        if not name:
            continue
        if int(item.get("importance") or 3) < min_importance:
            continue
        try:
            kind = EntityKind(item.get("kind") or "character")
        except ValueError:
            kind = EntityKind.character

        key = _canonical_key(name, kind.value)
        aliases = [
            str(a).strip() for a in (item.get("aliases") or [])
            if str(a).strip() and str(a).strip() != name
        ]

        family_key = None
        if kind == EntityKind.character:
            hint_surname = str(item.get("family_hint") or "").strip()
            family_key = (
                f"{hint_surname}_family" if hint_surname and cn_surname(hint_surname + "某")
                else infer_family_key(name)
            )

        extra = {
            "appearance": (item.get("appearance") or "").strip() or None,
            "voice_hints": (item.get("voice_hints") or "").strip() or None,
            "visual_keywords": [
                str(k).strip() for k in (item.get("visual_keywords") or [])
                if str(k).strip()
            ] or None,
            "owner_hint": (item.get("owner") or "").strip() or None,
            "usage_hint": (item.get("usage") or "").strip() or None,
            "evidence_json": [
                str(e).strip() for e in (item.get("evidence") or []) if str(e).strip()
            ][:3] or None,
        }

        row = existing.get(key)
        if row is not None:
            changed = False
            if row.locked:
                continue
            # 已有实体只补空缺，不覆盖已填的 —— 人工改过的不能被重跑吃掉
            for field_name, value in extra.items():
                if value and not getattr(row, field_name, None):
                    setattr(row, field_name, value)
                    changed = True
            merged = sorted(set(row.aliases_json or []) | set(aliases))
            changed = changed or merged != (row.aliases_json or [])
            row.aliases_json = merged
            if family_key and not row.family_key:
                row.family_key = family_key
                changed = True
            if not row.summary and item.get("summary"):
                row.summary = item["summary"]
                changed = True
            chapters = set(row.appear_chapters_json or [])
            if chapter.id not in chapters:
                chapters.add(chapter.id)
                row.appear_chapters_json = sorted(chapters)
                changed = True
            if changed:
                result.updated += 1
            continue

        row = WorldEntity(
            id=new_id("we"), novel_id=chapter.novel_id, kind=kind,
            canonical_key=key, display_name=name, aliases_json=aliases,
            summary=item.get("summary") or None, family_key=family_key,
            first_seen_chapter_order=chapter.order_no,
            appear_chapters_json=[chapter.id],
            **extra,
        )
        db.add(row)
        existing[key] = row
        result.created += 1
        result.names.append(name)
        result.by_kind[kind.value] = result.by_kind.get(kind.value, 0) + 1

    result.beats = _save_beats(db, chapter, data.get("beats") or [])
    result.style_hints = _save_style_hints(db, chapter, data.get("style_hints") or [])
    db.flush()

    all_rows = list(
        db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)
        ).scalars()
    )
    result.total = len(all_rows)
    for e in all_rows:
        if e.family_key:
            result.families.setdefault(e.family_key, []).append(e.display_name)
    return result


def _save_beats(db: Session, chapter: Chapter, items: list[dict]) -> int:
    """剧情节拍。重跑覆盖整章 —— 节拍是对全章的解读，不是逐条累积的。"""
    from app.models import StoryBeat

    if not items:
        return 0
    for old in db.execute(
        select(StoryBeat).where(StoryBeat.chapter_id == chapter.id)
    ).scalars().all():
        db.delete(old)
    db.flush()

    n = 0
    for i, item in enumerate(sorted(items, key=lambda x: int(x.get("order") or 0)), 1):
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        tension = int(item.get("tension_level") or 3)
        db.add(StoryBeat(
            id=new_id("bt"), chapter_id=chapter.id, order_no=i, title=title,
            summary=(item.get("summary") or "").strip() or None,
            tension_level=max(1, min(tension, 5)),
            location_text=(item.get("location") or "").strip() or None,
            entity_names=[str(e) for e in (item.get("entities") or [])] or None,
            evidence_json=[
                str(e).strip() for e in (item.get("evidence") or []) if str(e).strip()
            ][:3] or None,
        ))
        n += 1
    return n


def _save_style_hints(db: Session, chapter: Chapter, items: list[dict]) -> int:
    from app.models import StyleHint

    if not items:
        return 0
    for old in db.execute(
        select(StyleHint).where(StyleHint.chapter_id == chapter.id)
    ).scalars().all():
        db.delete(old)
    db.flush()

    n = 0
    for item in items:
        if not any(str(item.get(k) or "").strip()
                   for k in ("lighting_style", "mood", "camera_hint", "texture")):
            continue
        db.add(StyleHint(
            id=new_id("sh"), chapter_id=chapter.id,
            lighting_style=(item.get("lighting_style") or "").strip() or None,
            color_palette=[str(c) for c in (item.get("color_palette") or [])] or None,
            mood=(item.get("mood") or "").strip() or None,
            camera_hint=(item.get("camera_hint") or "").strip() or None,
            texture=(item.get("texture") or "").strip() or None,
            evidence_json=[
                str(e).strip() for e in (item.get("evidence") or []) if str(e).strip()
            ][:3] or None,
        ))
        n += 1
    return n


def placeholder_map(
    db: Session, novel_id: str, transform_id: str, target_language: str
) -> tuple[list[tuple[str, str]], dict[str, str], list[str]]:
    """闸一：构建 原文名→占位符 与 占位符→目标名 两张表。

    继承 v1 四个关键细节：
      · 别名与本名一起替换
      · 按长度倒序替换，防「李清」抢在「李清照」前
      · 占位符 token 稳定，与 entity id 绑定
      · 锁定语言缺译名时硬失败，不静默降级成原文

    返回 (替换表, 还原表, 缺译名的实体名)。
    """
    from app.models import EntityWorldName

    kind_prefix = {
        EntityKind.character: "CHAR", EntityKind.location: "LOC",
        EntityKind.prop: "PROP", EntityKind.faction: "ORG",
        EntityKind.style: "STYLE",
    }

    entities = list(
        db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == novel_id)
        ).scalars()
    )
    names = {
        n.entity_id: n
        for n in db.execute(
            select(EntityWorldName).where(EntityWorldName.transform_id == transform_id)
        ).scalars()
    }

    source_to_ph: list[tuple[str, str]] = []
    ph_to_target: dict[str, str] = {}
    missing: list[str] = []

    for e in entities:
        prefix = kind_prefix.get(e.kind, "ENTITY")
        ph = f"{{{{{prefix}:{e.id[-10:].lower()}}}}}"
        mapped = names.get(e.id)
        if mapped is None or not mapped.target_name:
            missing.append(e.display_name)
            continue
        ph_to_target[ph] = mapped.target_name
        # LLM 有时会改写占位符内部 token，多留几个还原键兜底
        for variant in _mutation_variants(prefix, mapped.target_name):
            ph_to_target.setdefault(variant, mapped.target_name)
        for surface in [e.display_name, *(e.aliases_json or [])]:
            surface = str(surface or "").strip()
            if surface:
                source_to_ph.append((surface, ph))

    source_to_ph.sort(key=lambda kv: len(kv[0]), reverse=True)
    return source_to_ph, ph_to_target, missing


def _mutation_variants(prefix: str, target_name: str) -> list[str]:
    """模型可能把 {{CHAR:abc}} 写成 {{CHAR:Mason}}，预留兼容键。"""
    base = str(target_name or "").strip()
    if not base:
        return []
    compact = re.sub(r"[^\w一-鿿]+", "_", base).strip("_")
    out = {f"{{{{{prefix}:{base}}}}}", f"{{{{{prefix}:{base.lower()}}}}}"}
    if compact:
        out.add(f"{{{{{prefix}:{compact}}}}}")
        out.add(f"{{{{{prefix}:{compact.lower()}}}}}")
    return list(out)


def apply_placeholders(text: str, source_to_ph: list[tuple[str, str]]) -> str:
    out = text
    for surface, ph in source_to_ph:
        out = out.replace(surface, ph)
    return out


def restore_placeholders(text: str, ph_to_target: dict[str, str]) -> str:
    out = text
    for ph, target in sorted(ph_to_target.items(), key=lambda kv: len(kv[0]), reverse=True):
        out = out.replace(ph, target)
    return out
