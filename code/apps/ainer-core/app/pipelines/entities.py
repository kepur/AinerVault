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
                },
            },
        }
    },
}

EXTRACT_SYSTEM = """你是小说实体抽取专家。从文本中找出需要在全书保持一致的实体。

要找的：
  character  有名有姓的人物，以及有稳定称呼的角色（掌柜、小二这类职业称呼若指特定某人也算）
  location   具体地名（长安、玄武门、悦来客栈），不要抽「屋里」「街上」这类泛指
  prop       有身份的器物（青莲剑、传家玉佩），不要抽「一把剑」这类泛指
  faction    门派、家族、组织

关键要求：
1. display_name 用原文中最正式的称呼。「李清照」而不是「清照」。
2. aliases 收全同一实体的其他叫法：小名、尊称、绰号、单用的名。
   「李清照 / 易安居士 / 清照 / 李娘子」是同一人，必须并成一条。
   别名收不全，后续占位符就替不干净，人名会漏译成原文。
3. family_hint 填该人物所属家族的姓（如「李」），无法判断留空。
4. importance 1–5，5 为主角。低于 2 的次要角色可以不抽。
5. 不要抽泛指名词、不要抽情绪与动作。"""


@dataclass
class ExtractResult:
    created: int = 0
    updated: int = 0
    total: int = 0
    names: list[str] = field(default_factory=list)
    families: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created, "updated": self.updated, "total": self.total,
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

        row = existing.get(key)
        if row is not None:
            if row.locked:
                continue
            merged = sorted(set(row.aliases_json or []) | set(aliases))
            changed = merged != (row.aliases_json or [])
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
        )
        db.add(row)
        existing[key] = row
        result.created += 1
        result.names.append(name)

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
