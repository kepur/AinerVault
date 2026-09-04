"""基础素材包：抽离 → 世界观变体 → 完整度 → 增量补全。

依赖方向是单向的：
    小说原文 → AssetSpec（世界观无关的语义）
    AssetSpec × 目标世界观 → AssetVariant（具体形态 + 参考图）
    Shot 只引用 AssetVariant，自己不描述外观

小说会更新、抽取会不全，所以 ensure_variants 是常态操作而非一次性初始化：
缺什么就按当前目标世界观的标准补什么，已锁定的一律不动。
"""
from __future__ import annotations

import json

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    AssetKindSpec, AssetOrigin, AssetSpec, AssetVariant, Chapter, DocMode, DocStatus,
    ReviewStatus, ScriptBlock, ScriptDoc, WorldEntity, WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError, chat_json, as_text, as_items
from app.worldview.asset_requirements import check_completeness, diagnose, requirements_for

log = logging.getLogger(__name__)


# ── 抽离 ──────────────────────────────────────────────────────────────────────

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["assets"],
    "properties": {
        "assets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["canonical_key", "kind", "display_name"],
                "properties": {
                    "canonical_key": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [k.value for k in AssetKindSpec],
                    },
                    "display_name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                    "owner_entity": {"type": "string"},
                    "excerpt": {"type": "string"},
                    "importance": {"type": "integer"},
                },
            },
        }
    },
}

EXTRACT_SYSTEM = """你是影视美术指导。从小说文本中抽离出【基础素材】——
后续所有分镜画面都由这些素材拼装，镜头本身不再描述外观。

要抽的类别：
  costume    服装（按穿着者身份归类，如「文士长袍」「捕快公服」）
  prop       道具（有画面意义的器物）
  location   场景（客栈大堂、城门、后院这类可复用的空间）
  ambience   氛围（夜雨、晨雾、烛光这类反复出现的光线天气）
  creature   非人角色与坐骑
  style      全书统一的画风基调（通常只有一条）

关键要求：
1. canonical_key 用「类别.英文语义」格式，如 costume.scholar_robe、
   location.inn_hall、prop.longsword。**这是跨世界观稳定的语义标识**，
   同一件东西在不同目标文化下会有不同外观，但 key 不变。
2. 抽【可复用】的素材，不抽一次性描述。
   「客栈大堂」要抽（后面还会用），「他手边那只缺口的碗」不抽。
3. display_name 用原文的说法。
4. owner_entity 填该素材专属的人物名（如青莲剑属于李白）；通用素材留空。
5. excerpt 摘一句原文作为依据。
6. importance 1–5，5 为全书反复出现的核心素材。
7. 不要抽人物本身 —— 人物走实体抽取，这里只抽他们穿的、拿的、所处的。"""


@dataclass
class ExtractPackResult:
    created: int = 0
    updated: int = 0
    #: 靠中文名兜住的次数 —— 模型没沿用旧 key 的那些。
    #: **要报出来**：这个数字长期不降，说明提示词那一半没起作用，
    #: 而只看 created/updated 是看不出来的
    merged_by_name: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    names: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"created": self.created, "updated": self.updated,
                "merged_by_name": self.merged_by_name,
                "by_kind": self.by_kind, "names": self.names}


def _chapter_text(db: Session, chapter: Chapter, limit: int = 8000) -> str:
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id,
            ScriptDoc.doc_mode == DocMode.prose,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()
    if doc is None:
        return (chapter.content or "")[:limit]
    blocks = db.execute(
        select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
        .order_by(ScriptBlock.seq_no)
    ).scalars()
    return "\n".join(b.source_text for b in blocks if b.source_text)[:limit]


def extract_assets(
    db: Session, chapter: Chapter, *, min_importance: int = 2
) -> ExtractPackResult:
    """从一章抽离基础素材。幂等 —— 已存在的 canonical_key 只补别名与出处。"""
    text = _chapter_text(db, chapter)
    if not text.strip():
        raise PipelineError("章节没有正文，无法抽离素材")

    entities = {
        e.display_name: e
        for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)
        ).scalars()
    }
    known = ", ".join(sorted(entities)[:40])

    # **把已抽出的素材摆给模型看。**
    # canonical_key 是模型自己编的英文 slug，而它每章独立跑一次 ——
    # 同一把「三簧锁」第一章编成 lock_triple_spring、第二章 door_lock、
    # 第三章 lock_three_spring，于是库里躺着三把锁，
    # 各拿一张参考图，同一扇门在三章里长得不一样。
    # 让模型跨独立调用复现同一个任意 slug 是在要求它做不到的事，
    # 但把已有的列给它看、要求"同一件东西沿用同一个 key"，它能做到。
    prior = list(db.execute(
        select(AssetSpec).where(AssetSpec.novel_id == chapter.novel_id)
        .order_by(AssetSpec.importance.desc()).limit(120)).scalars())
    prior_txt = "；".join(
        f"{a.display_name}={a.canonical_key}" for a in prior) or "（暂无）"

    data, _ = chat_json(
        db,
        [
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user",
             "content": (f"【已知人物】{known}\n"
                         f"【已抽出的素材 · 同一件东西必须沿用同一个 key】"
                         f"{prior_txt}\n\n【原文】\n{text}")},
        ],
        EXTRACT_SCHEMA,
        purpose="extract",
        novel_id=chapter.novel_id, chapter_id=chapter.id,
        ref_kind="asset_extract", ref_id=chapter.id,
    )

    # 两条索引：key 一条，(类别, 中文名) 一条。
    # **中文名才是稳定的那一个** —— 它逐字来自原文，模型没有发挥余地；
    # 英文 key 是模型现编的，同一件东西每次编得不一样。
    # 提示词已经让模型沿用旧 key，这一层是它没照做时的兜底。
    existing: dict[str, AssetSpec] = {}
    by_name: dict[tuple[str, str], AssetSpec] = {}
    for a in db.execute(
        select(AssetSpec).where(AssetSpec.novel_id == chapter.novel_id)
    ).scalars():
        existing[a.canonical_key] = a
        by_name[(getattr(a.kind, "value", str(a.kind)), a.display_name)] = a
        for alias in a.aliases_json or []:
            by_name.setdefault(
                (getattr(a.kind, "value", str(a.kind)), str(alias)), a)

    out = ExtractPackResult()
    for item in as_items(data, "assets"):
        key = as_text(item.get("canonical_key"))
        name = as_text(item.get("display_name"))
        if not key or not name:
            continue
        if int(item.get("importance") or 3) < min_importance:
            continue
        try:
            kind = AssetKindSpec(item.get("kind") or "prop")
        except ValueError:
            kind = AssetKindSpec.prop

        aliases = [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()]
        owner = entities.get(as_text(item.get("owner_entity")))
        excerpt = as_text(item.get("excerpt"))

        row = existing.get(key)
        if row is None:
            # key 对不上就按中文名找。命中时把模型这次编的 key 收成别名 ——
            # 下一章它可能又编回这个，收下来就认得出
            row = by_name.get((kind.value, name))
            if row is not None and key not in (row.aliases_json or []):
                aliases = [*aliases, key]
                out.merged_by_name += 1
        if row is not None:
            merged = sorted(set(row.aliases_json or []) | set(aliases))
            ev = dict(row.evidence_json or {})
            chapters = set(ev.get("chapter_ids") or [])
            excerpts = list(ev.get("excerpts") or [])
            changed = merged != (row.aliases_json or [])
            row.aliases_json = merged
            if chapter.id not in chapters:
                chapters.add(chapter.id)
                changed = True
            if excerpt and excerpt not in excerpts:
                excerpts.append(excerpt)
                changed = True
            ev["chapter_ids"] = sorted(chapters)
            ev["excerpts"] = excerpts[:5]
            row.evidence_json = ev
            if owner and not row.entity_id:
                row.entity_id = owner.id
                changed = True
            if changed:
                out.updated += 1
            continue

        row = AssetSpec(
            id=new_id("as"), novel_id=chapter.novel_id, kind=kind,
            canonical_key=key, display_name=name, aliases_json=aliases,
            summary=item.get("summary") or None,
            entity_id=owner.id if owner else None,
            evidence_json={"chapter_ids": [chapter.id],
                           "excerpts": [excerpt] if excerpt else []},
            first_seen_chapter_order=chapter.order_no,
            importance=int(item.get("importance") or 3),
            source=AssetOrigin.mined,
        )
        db.add(row)
        existing[key] = row
        out.created += 1
        out.names.append(name)
        out.by_kind[kind.value] = out.by_kind.get(kind.value, 0) + 1

    db.flush()
    return out


# ── 世界观变体 ────────────────────────────────────────────────────────────────

VARIANT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["variants"],
    "properties": {
        "variants": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["canonical_key", "target_name", "visual_prompt",
                             "structured", "rationale"],
                "properties": {
                    "canonical_key": {"type": "string"},
                    "target_name": {"type": "string"},
                    "target_reading": {"type": "string"},
                    "visual_prompt": {"type": "string"},
                    "negative_prompt": {"type": "string"},
                    "structured": {"type": "object"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}


def _variant_system(profile: WorldProfile, kinds: Sequence[str]) -> str:
    visual = profile.visual_json or {}
    axes = profile.axes_json or {}
    do = "、".join(visual.get("visual_do") or [])
    dont = "、".join(visual.get("visual_dont") or [])
    # **给字面的 JSON 骨架，不要写成「类别: 字段一、字段二」。**
    #
    # 原来那种写法（`ambience: time_of_day（时段）、weather（天气）…`）
    # 读起来就是「键: 值」，模型照着产出了
    #   {"ambience": "night, heavy_snowfall, gas_lamp_glow, serene_eerie"}
    # —— 四个答案一个不少，全挤在一个以**类别名**为键的字符串里。
    # 完整度检查于是报「缺 time_of_day/weather/light_quality」，
    # 而人照着这条去找，会以为模型没答，实际上答案就在眼前。
    # 骨架是逐字可照抄的，歧义没有落脚处。
    req_lines = []
    for kind in sorted(set(kinds)):
        fields = requirements_for(kind, profile)
        if not fields:
            continue
        skeleton = json.dumps({k: f"<{v}>" for k, v in fields.items()},
                              ensure_ascii=False)
        req_lines.append(f"  kind = {kind} 时：structured = {skeleton}")
    reqs = "\n".join(req_lines)

    return f"""你是影视美术指导，负责把素材落地到指定的目标世界观。

【目标世界观】{profile.display_name}
【年代】{axes.get('era_span', '')}　【地域】{axes.get('region', '')}　\
【社会背景】{axes.get('social_context', '')}
【视觉宜】{do}
【视觉忌】{dont}

任务：为每条素材给出该世界观下的具体形态。

铁律：
1. 【功能等价而非直译】目标世界观里没有对应物时，换成功能等价的东西，
   而不是硬造一个时代外的物件。中世纪欧洲没有茶，就不要出现茶具。
2. 【时代必须对】年代之外的元素一律不要。昭和日本不出现江户的髷与佩刀，
   中世纪盛期不出现板甲与火器。
3. 【结构化填写】structured 的**键必须与下面的骨架逐字一致**：
   不要用类别名当键，不要嵌套，不要把几项并成一个字符串，
   不要把字段名当成值填进去。每项一个短语，不要写整句。
{reqs}
4. visual_prompt 用英文写，是给图像模型的正向描述，
   包含材质、颜色、廓形、光线，30–60 词。
5. negative_prompt 写该素材最容易出错的方向。
6. target_name 用目标语言的本地说法。
7. rationale 一句话说明为什么这个形态在该世界观里成立。"""


@dataclass
class VariantResult:
    created: int = 0
    updated: int = 0
    skipped_locked: int = 0
    incomplete: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"created": self.created, "updated": self.updated,
                "skipped_locked": self.skipped_locked,
                "incomplete": self.incomplete}


def ensure_variants(
    db: Session,
    transform: WorldTransform,
    *,
    asset_ids: Sequence[str] | None = None,
    only_missing: bool = True,
    batch: int = 12,
) -> VariantResult:
    """确保素材在目标世界观下都有变体。缺什么补什么。

    这是常态操作而非一次性初始化 —— 小说在更新、抽取会不全，
    每次编译分镜前调一次，按当前目标世界观的标准把缺口补上。
    已锁定的变体一律不动。
    """
    profile = db.get(WorldProfile, transform.target_profile_id)
    if profile is None:
        raise PipelineError("目标世界观档案缺失")

    q = select(AssetSpec).where(AssetSpec.novel_id == transform.novel_id)
    if asset_ids:
        q = q.where(AssetSpec.id.in_(list(asset_ids)))
    specs = list(db.execute(q.order_by(AssetSpec.importance.desc())).scalars())
    if not specs:
        return VariantResult()

    existing = {
        v.asset_spec_id: v
        for v in db.execute(
            select(AssetVariant).where(
                AssetVariant.world_profile_id == profile.id,
                AssetVariant.asset_spec_id.in_([s.id for s in specs]),
            )
        ).scalars()
    }

    result = VariantResult()
    pending: list[AssetSpec] = []
    for s in specs:
        cur = existing.get(s.id)
        if cur is not None and cur.status == ReviewStatus.locked:
            result.skipped_locked += 1
            continue
        if only_missing and cur is not None and cur.visual_prompt and not cur.missing_fields:
            continue
        pending.append(s)
    if not pending:
        return result

    by_key = {s.canonical_key: s for s in pending}
    # **按类别分批。**
    #
    # 一批里混着服装、场景、道具、环境声时，提示词的「必填字段」那一段
    # 会同时列出好几套（服装要 silhouette/fabric/color…，场景要
    # architecture/materials/lighting…），而模型只认真填了其中一套 ——
    # 实跑 29 件漏了 15 件，且**漏的方式整齐得可疑**：
    # 四个场景全缺同样五项、四件服装全缺同样五项、四条环境声全缺同样四项。
    # 那不是模型不行，是这一批的要求本身就是多义的。
    #
    # 一类一批之后，要求块里只剩一套字段，批内每一件要填的东西完全相同。
    # 代价是请求数变多（类别数 × 批次），换来的是不用回头补 structured。
    by_kind: dict[str, list[AssetSpec]] = {}
    for s in pending:
        by_kind.setdefault(s.kind.value, []).append(s)
    chunks = [c for kind in sorted(by_kind)
              for c in _chunks(by_kind[kind], batch)]
    for chunk in chunks:
        payload = [
            {
                "canonical_key": s.canonical_key,
                "kind": s.kind.value,
                "source_name": s.display_name,
                "aliases": s.aliases_json or [],
                "summary": s.summary or "",
                "excerpt": ((s.evidence_json or {}).get("excerpts") or [""])[0],
            }
            for s in chunk
        ]
        data, _ = chat_json(
            db,
            [
                {"role": "system",
                 "content": _variant_system(profile, [s.kind.value for s in chunk])},
                {"role": "user", "content": _dump(payload)},
            ],
            VARIANT_SCHEMA,
            purpose="asset_variant",
            novel_id=transform.novel_id,
            ref_kind="asset_variant", ref_id=transform.id,
        )

        for item in as_items(data, "variants"):
            key = as_text(item.get("canonical_key"))
            spec = by_key.get(key)
            if spec is None:
                continue
            structured = item.get("structured") or {}
            missing = check_completeness(spec.kind.value, structured, profile)
            if missing:
                row_out = {"canonical_key": key,
                           "display_name": spec.display_name, "missing": missing}
                why = diagnose(spec.kind.value, structured, profile)
                if why:
                    row_out["why"] = why
                result.incomplete.append(row_out)

            row = existing.get(spec.id)
            values = dict(
                target_name=str(item.get("target_name") or spec.display_name),
                target_reading=str(item.get("target_reading") or "") or None,
                visual_prompt=str(item.get("visual_prompt") or "") or None,
                negative_prompt=str(item.get("negative_prompt") or "") or None,
                structured_json=structured,
                missing_fields=missing,
                confidence=float(item.get("confidence") or 0.7),
                rationale=str(item.get("rationale") or "") or None,
                source=AssetOrigin.llm,
                status=ReviewStatus.candidate,
            )
            if row is None:
                row = AssetVariant(
                    id=new_id("av"), asset_spec_id=spec.id,
                    world_profile_id=profile.id, **values,
                )
                db.add(row)
                existing[spec.id] = row
                result.created += 1
            else:
                for k, v in values.items():
                    setattr(row, k, v)
                result.updated += 1

    db.flush()
    return result


def pack_status(
    db: Session, transform: WorldTransform, *, chapter_ids: Sequence[str] | None = None
) -> dict[str, Any]:
    """基础素材包的完整度总览。分镜编译前看这一屏。"""
    profile = db.get(WorldProfile, transform.target_profile_id)
    specs = list(
        db.execute(
            select(AssetSpec).where(AssetSpec.novel_id == transform.novel_id)
        ).scalars()
    )
    variants = {
        v.asset_spec_id: v
        for v in db.execute(
            select(AssetVariant).where(AssetVariant.world_profile_id == profile.id)
        ).scalars()
    }

    by_kind: dict[str, dict[str, int]] = {}
    missing_variant: list[dict] = []
    incomplete: list[dict] = []
    no_ref: list[dict] = []

    for s in specs:
        bucket = by_kind.setdefault(
            s.kind.value,
            {"total": 0, "has_variant": 0, "complete": 0, "approved": 0,
             "locked": 0, "with_ref": 0},
        )
        bucket["total"] += 1
        v = variants.get(s.id)
        if v is None:
            missing_variant.append({"id": s.id, "canonical_key": s.canonical_key,
                                    "display_name": s.display_name,
                                    "kind": s.kind.value})
            continue
        bucket["has_variant"] += 1
        if not v.missing_fields:
            bucket["complete"] += 1
        else:
            incomplete.append({"id": v.id, "canonical_key": s.canonical_key,
                               "display_name": s.display_name,
                               "missing": v.missing_fields})
        if v.status == ReviewStatus.approved:
            bucket["approved"] += 1
        if v.status == ReviewStatus.locked:
            bucket["locked"] += 1
        if v.ref_asset_ids:
            bucket["with_ref"] += 1
        else:
            no_ref.append({"id": v.id, "display_name": s.display_name,
                           "kind": s.kind.value})

    total = len(specs)
    ready = total - len(missing_variant) - len(incomplete)
    return {
        "transform_id": transform.id,
        "world_profile": {"id": profile.id, "code": profile.code,
                          "display_name": profile.display_name},
        "totals": {
            "specs": total,
            "with_variant": total - len(missing_variant),
            "complete": ready,
            "missing_variant": len(missing_variant),
            "incomplete": len(incomplete),
            "without_reference_image": len(no_ref),
        },
        "by_kind": by_kind,
        "missing_variant": missing_variant[:30],
        "incomplete": incomplete[:30],
        "without_reference_image": no_ref[:30],
        "ready_for_shots": not missing_variant and not incomplete,
    }


def _chunks(items: Sequence[Any], size: int):
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def _dump(payload: Any) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False, indent=1)


def prompt_ledger(
    db: Session, transform: WorldTransform, *,
    kind: str | None = None, q: str | None = None,
) -> dict[str, Any]:
    """生图提示词台账：每条素材的提示词、来源、状态、被哪些镜头用到。

    提示词散在各条素材记录里就等于没有 —— 改一条之前必须先知道
    它会影响哪些镜头，否则是盲改：一个道具的描述改了，
    可能连带十几个镜头的画面全变，而改的人完全不知情。

    所以台账把三件事拼在一起：
        提示词本身      改什么
        来源与证据      为什么是这样（原文哪句支持）
        被谁引用        改了会影响什么
    """
    from app.models import FrameSpec, Shot, ShotAssetBinding, ShotPlan

    profile = db.get(WorldProfile, transform.target_profile_id)
    if profile is None:
        raise PipelineError("目标世界观档案缺失")

    rows = list(db.execute(
        select(AssetSpec, AssetVariant)
        .outerjoin(
            AssetVariant,
            (AssetVariant.asset_spec_id == AssetSpec.id)
            & (AssetVariant.world_profile_id == profile.id),
        )
        .where(AssetSpec.novel_id == transform.novel_id)
        .order_by(AssetSpec.kind, AssetSpec.display_name)
    ))

    # 引用计数：一条素材被多少个镜头绑定。改之前要知道波及面
    usage: dict[str, int] = {}
    for b in db.execute(select(ShotAssetBinding)).scalars():
        if b.asset_spec_id:
            usage[b.asset_spec_id] = usage.get(b.asset_spec_id, 0) + 1

    items: list[dict[str, Any]] = []
    for spec, var in rows:
        if kind and spec.kind.value != kind:
            continue
        if q:
            hay = " ".join(filter(None, [
                spec.display_name, spec.canonical_key,
                var.target_name if var else "",
                var.visual_prompt if var else "",
            ])).lower()
            if q.lower() not in hay:
                continue
        items.append({
            "spec_id": spec.id,
            "variant_id": var.id if var else None,
            "kind": spec.kind.value,
            "canonical_key": spec.canonical_key,
            "source_name": spec.display_name,
            "target_name": var.target_name if var else None,
            "visual_prompt": var.visual_prompt if var else None,
            "negative_prompt": var.negative_prompt if var else None,
            "structured": (var.structured_json if var else None) or {},
            "ref_count": len(var.ref_asset_ids or []) if var else 0,
            "status": var.status.value if var else "missing",
            # AssetVariant 用 status=locked 表示锁定，没有独立的 locked 布尔
            "locked": bool(var and var.status is ReviewStatus.locked),
            # 完整度检查留下的缺项。有缺项的提示词生成出来会缺关键描述
            "missing_fields": (var.missing_fields if var else None) or [],
            "rationale": var.rationale if var else None,
            # 证据链：这条素材的依据是原文哪几句。
            # evidence_json 是 {chapter_ids, excerpts} 而不是列表 ——
            # 当成列表取会静默得到一个 dict，前端渲染成一堆键名
            "evidence": (spec.evidence_json or {}).get("excerpts") or [],
            "from_chapters": (spec.evidence_json or {}).get("chapter_ids") or [],
            "aliases": spec.aliases_json or [],
            "importance": spec.importance,
            "origin": spec.source.value,
            "used_by_shots": usage.get(spec.id, 0),
            "prompt_chars": len(var.visual_prompt or "") if var else 0,
        })

    missing = [i for i in items if not i["visual_prompt"]]
    return {
        "transform_id": transform.id,
        "profile": {"id": profile.id, "code": profile.code,
                    "display_name": profile.display_name},
        "total": len(items),
        "with_prompt": len(items) - len(missing),
        "missing_prompt": len(missing),
        "unused": sum(1 for i in items if i["used_by_shots"] == 0),
        "by_kind": {
            k: sum(1 for i in items if i["kind"] == k)
            for k in sorted({i["kind"] for i in items})
        },
        "items": items,
    }


def export_prompts(db: Session, transform: WorldTransform) -> str:
    """把台账导成纯文本，便于贴进别的工具或存档比对。

    只导有提示词的条目 —— 导出一堆空行没有意义。
    """
    led = prompt_ledger(db, transform)
    lines = [
        f"# 生图提示词台账　{led['profile']['display_name']}",
        f"# {led['with_prompt']}/{led['total']} 条已生成",
        "",
    ]
    for kind in sorted(led["by_kind"]):
        group = [i for i in led["items"] if i["kind"] == kind and i["visual_prompt"]]
        if not group:
            continue
        lines.append(f"## {kind}（{len(group)}）")
        for i in group:
            lines.append(f"### {i['source_name']} → {i['target_name'] or '—'}")
            lines.append(i["visual_prompt"])
            if i["negative_prompt"]:
                lines.append(f"[negative] {i['negative_prompt']}")
            lines.append("")
    return "\n".join(lines)
