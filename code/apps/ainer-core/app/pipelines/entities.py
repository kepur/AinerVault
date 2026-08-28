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

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    NameType,
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
                    # 靠什么指认它。与 kind 正交，但决定转译路径
                    "name_type": {
                        "type": "string",
                        "enum": ["proper", "role", "epithet", "generic"],
                    },
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    # 称呼变体：谁这么叫、属于哪种语域。
                    # 只收字面会把「小天」和全名压成一个词，关系信息当场丢掉。
                    "appellations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["surface", "register"],
                            "properties": {
                                "surface": {"type": "string"},
                                "register": {
                                    "type": "string",
                                    "enum": [
                                        "formal_full", "formal_title", "respectful",
                                        "intimate", "diminutive", "kinship",
                                        "epithet", "derogatory", "pronoun_like",
                                    ],
                                },
                                "speaker": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                        },
                    },
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
0. **name_type 决定这条实体后面怎么转译，判错的代价最大。**
   proper   有专属名字：沈砚、柳树坳、漕帮、青莲剑
   role     以职务或身份指代：总镖头、掌柜、小二、师父、县令
   epithet  描述性名号：北地剑客、三簧锁、独臂老人
   generic  泛指，不是特定的谁／什么：那个人、店家、一把剑、几个汉子

   判据是**「换一个人／一件物，这个称呼还成立吗」**：
   「掌柜」换个人还是掌柜 → role；「沈砚」换个人就不是沈砚了 → proper。

   为什么要紧：proper 会去目标文化里造一个专名，
   role 走名物词表。给「总镖头」造专名，它就变成了一个凭空出现的角色，
   而译文里「总镖头把镖单推过来」从此由那个人来做。

   **generic 的一律不要收**。「那个人」「一把剑」不是实体，
   收进来只会占着位置、拿到一个不存在的名字。

1. display_name 用原文中最正式的称呼。「李清照」而不是「清照」。
2. aliases 收全同一实体的其他叫法：小名、尊称、绰号、单用的名。
   「李清照 / 易安居士 / 清照 / 李娘子」是同一人，必须并成一条。
   别名收不全，后续占位符就替不干净，人名会漏译成原文。
2a. **「老X」「小X」「阿X」不是本名，是带亲近感的称呼。**
   「老周」= 老 + 姓，本名多半是「周某某」；「小林」「阿强」同理。
   display_name 该填能查到的最正式形式（原文只出现「老周」时就填「老周」，
   不要编一个本名），但必须在 appellations 里把它登记为 intimate ——
   否则这层亲近感在翻译时整个消失：老周译成 Савва Ильич（名+父称）
   信息全在，可读者感觉不到那个「老」字带的熟稔。
   同理「师父」「师娘」是 kinship，「掌柜的」的「的」是口语亲近后缀。

2b. appellations 逐条登记每个称呼**是谁在叫、属于哪种语域**。
   中文里「小天」承载的不是名字是关系 —— 师父叫「小天」是亲昵，
   仇家叫「姓李的」是轻蔑，朝堂上「李大人」是距离。
   全归成一个名字，译文就只剩信息、没有关系，读者会觉得淡而说不出哪淡。
   语域：formal_full 全名／formal_title 头衔式／respectful 敬称／
   intimate 亲昵／diminutive 小名／kinship 以关系代名（师兄、三弟）／
   epithet 名号绰号／derogatory 轻蔑／pronoun_like 指代性称呼。
   同一个字面在不同人嘴里语域不同时，拆成多条，用 speaker 区分。
   speaker 填原文里的称呼者，判断不出就留空。
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
    appellations: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    names: list[str] = field(default_factory=list)
    families: dict[str, list[str]] = field(default_factory=dict)
    by_name_type: dict[str, int] = field(default_factory=dict)
    #: 被判为泛指、未建实体的（「那个人」「一把剑」）
    dropped_generic: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created, "updated": self.updated, "total": self.total,
            "beats": self.beats, "style_hints": self.style_hints,
            "appellations": self.appellations,
            "by_kind": self.by_kind,
            "names": self.names, "families": self.families,
            "by_name_type": self.by_name_type,
            "dropped_generic": self.dropped_generic,
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
    pending_appellations: list[tuple[str, list[dict]]] = []
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
        try:
            name_type = NameType(item.get("name_type") or "proper")
        except ValueError:
            name_type = NameType.proper
        # 泛指不是实体。收进来只会占位置，然后拿到一个不存在的名字
        if name_type is NameType.generic:
            result.dropped_generic.append(name)
            continue

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

        appellations = [
            a for a in (item.get("appellations") or []) if isinstance(a, dict)
        ]
        if appellations:
            pending_appellations.append((key, appellations))

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
            # 老数据一律是默认的 proper。抽取给出非 proper 时以它为准 ——
            # 那是看着原文做的判断，比默认值可信
            if name_type is not NameType.proper and row.name_type is NameType.proper:
                row.name_type = name_type
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
            name_type=name_type,
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
        result.by_name_type[name_type.value] = (
            result.by_name_type.get(name_type.value, 0) + 1
        )

    db.flush()  # 新建实体先拿到 id，称呼才挂得上
    result.appellations = _save_appellations(db, chapter, existing, pending_appellations)
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


def _save_appellations(
    db: Session, chapter: Chapter, by_key: dict[str, WorldEntity],
    pending: list[tuple[str, list[dict]]],
) -> int:
    """登记称呼变体。按 (实体, 字面) 累积，跨章合并出现次数与证据。

    不覆盖已定的 target_surface —— 那是命名阶段与人工审核的产物，
    重跑抽取不该把定好的称呼冲掉。
    """
    from app.models import EntityAppellation, Register

    if not pending:
        return 0
    touched = 0
    for key, items in pending:
        entity = by_key.get(key)
        if entity is None:
            continue
        rows = {
            r.source_surface: r
            for r in db.execute(
                select(EntityAppellation).where(
                    EntityAppellation.entity_id == entity.id,
                    EntityAppellation.transform_id.is_(None),
                )
            ).scalars()
        }
        for item in items:
            surface = str(item.get("surface") or "").strip()
            if not surface:
                continue
            try:
                register = Register(item.get("register") or "formal_full")
            except ValueError:
                register = Register.formal_full
            speaker = (str(item.get("speaker") or "").strip() or None)
            quote = str(item.get("evidence") or "").strip()
            row = rows.get(surface)
            if row is None:
                row = EntityAppellation(
                    id=new_id("ap"), entity_id=entity.id, source_surface=surface,
                    register=register, speaker_hint=speaker, occurrences=1,
                    evidence_json=[{"chapter_id": chapter.id, "quote": quote}] if quote else None,
                )
                db.add(row)
                rows[surface] = row
                touched += 1
                continue
            if row.locked:
                continue
            row.occurrences = (row.occurrences or 0) + 1
            if speaker and not row.speaker_hint:
                row.speaker_hint = speaker
            if quote:
                ev = list(row.evidence_json or [])
                if not any(e.get("chapter_id") == chapter.id for e in ev):
                    ev.append({"chapter_id": chapter.id, "quote": quote})
                    row.evidence_json = ev[:5]
            touched += 1
    db.flush()
    return touched


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


#: 需要专名映射的实体类型。与 naming.suggest_names 处理的范围一致 ——
#: 两处不一致就会出现「命名管线不管、占位符却要求有」的死角。
_NEEDS_PROPER_NAME = frozenset({
    EntityKind.character, EntityKind.location, EntityKind.faction,
})


def placeholder_map(
    db: Session, novel_id: str, transform_id: str, target_language: str
) -> tuple[list[tuple[str, str]], dict[str, str], list[str]]:
    """闸一：构建 原文名→占位符 与 占位符→目标名 两张表。

    继承 v1 四个关键细节：
      · 别名与本名一起替换
      · 按长度倒序替换，防「李清」抢在「李清照」前
      · 占位符 token 稳定，与 entity id 绑定
      · 锁定语言缺译名时硬失败，不静默降级成原文

    第五点是 v1 没有的：**称呼变体各占一个占位符**。
    定了目标形式的称呼拿 {{CHAR:xxx/ap}}，还原成「Tom」而不是「Thomas Ashford」。
    否则师父嘴里的「小天」和叙述里的全名会还原成同一个词，
    亲昵感在替换那一步就没了 —— 后面再怎么改编也救不回来。
    没定目标形式的称呼仍回落到本名，宁可正式，不能漏译成原文。

    返回 (替换表, 还原表, 缺译名的实体名)。
    """
    from app.models import EntityAppellation, EntityWorldName

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
    # 称呼取本映射下已定形的，回落到未绑定映射的登记条目
    appellations: dict[str, list[EntityAppellation]] = {}
    for a in db.execute(
        select(EntityAppellation).where(
            # SQL 里 NULL 不等于任何值，IN (x, NULL) 永远匹配不到未绑定的行。
            # 写成 in_([id, None]) 读着对，跑起来是静默返回空。
            or_(
                EntityAppellation.transform_id == transform_id,
                EntityAppellation.transform_id.is_(None),
            )
        ).order_by(EntityAppellation.transform_id.is_(None))
    ).scalars():
        appellations.setdefault(a.entity_id, []).append(a)

    source_to_ph: list[tuple[str, str]] = []
    ph_to_target: dict[str, str] = {}
    missing: list[str] = []

    for e in entities:
        prefix = kind_prefix.get(e.kind, "ENTITY")
        ph = f"{{{{{prefix}:{e.id[-10:].lower()}}}}}"
        mapped = names.get(e.id)
        if mapped is None or not mapped.target_name:
            # 只有专名类实体缺译名才算问题。道具与风格**本来就不该有人名映射** ——
            # 命名管线压根不处理它们（只做 character/location/faction），
            # 它们由名物词表在翻译时转译：腰刀 → шашка 是名物层的事，
            # 不需要占位符隔离（占位符是为了防人名被音译）。
            # 不区分的话，每次翻译都会报一串「缺译名」，
            # 而那串永远不会消失 —— 报警变成噪声，真正缺译名的角色就被淹掉了。
            # 职务与名号不走专名映射：前者由名物词表转（掌柜 → innkeeper），
            # 后者意译（北地剑客 → the Swordsman of the North）。
            # 把它们算进「缺译名」会得到一串永远消不掉的警告。
            if e.kind in _NEEDS_PROPER_NAME and e.name_type is NameType.proper:
                missing.append(e.display_name)
            continue
        ph_to_target[ph] = mapped.target_name
        # LLM 有时会改写占位符内部 token，多留几个还原键兜底
        for variant in _mutation_variants(prefix, mapped.target_name):
            ph_to_target.setdefault(variant, mapped.target_name)
        # 先放定形的称呼变体。同一字面只认第一条（已按「本映射优先」排过序）。
        claimed: set[str] = set()
        for idx, ap in enumerate(appellations.get(e.id, [])):
            surface = str(ap.source_surface or "").strip()
            if not surface or surface in claimed:
                continue
            claimed.add(surface)
            if not ap.target_surface:
                continue  # 未定形，留给下面按本名兜底
            ap_ph = f"{{{{{prefix}:{e.id[-10:].lower()}/a{idx}}}}}"
            ph_to_target[ap_ph] = ap.target_surface
            for variant in _mutation_variants(f"{prefix}", ap.target_surface):
                ph_to_target.setdefault(variant, ap.target_surface)
            source_to_ph.append((surface, ap_ph))

        for surface in [e.display_name, *(e.aliases_json or [])]:
            surface = str(surface or "").strip()
            if surface and surface not in claimed:
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
