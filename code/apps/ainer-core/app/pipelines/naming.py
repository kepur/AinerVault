"""L1 人名映射：按家族整族生成，而不是逐个独立生成。

逐个生成时，李清照与其父李格非会被映射成两个毫不相干的姓 ——
模型看不到它们的亲属关系。整族一次喂进去，模型自己就会保证共姓。

生成后还要过两道校验：
  拼音检测   「Li Bai」这种音译直接判废（v1 只有 30 词黑名单，Xiao/Rong 全漏网）
  家族一致   同 family_key 的姓氏必须相同
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    EntityKind, EntityWorldName, NamingPolicy, ReviewStatus, WorldEntity,
    WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError, chat_json
from app.worldview import naming as nm

log = logging.getLogger(__name__)

NAME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["groups"],
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["family_key", "surname", "members"],
                "properties": {
                    "family_key": {"type": "string"},
                    "surname": {"type": "string"},
                    "surname_reading": {"type": "string"},
                    "members": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["entity_id", "target_name", "rationale"],
                            "properties": {
                                "entity_id": {"type": "string"},
                                "target_name": {"type": "string"},
                                "target_reading": {"type": "string"},
                                "rationale": {"type": "string"},
                                "alternatives": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "reading": {"type": "string"},
                                            "rationale": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
    },
}

NAME_SYSTEM = """你是跨文化影视本地化的命名顾问，专长是【文化等效命名】。

核心任务：把源世界观的人名，换成目标世界观母语者听来自然的本土名字。

铁律：
1. 【禁止音译】绝不使用拼音、罗马字转写或片假名音译。
   「李清照」不能变成 Li Qingzhao、リ・セイショウ 这类 —— 那是转写不是命名。
   要找的是「在目标文化里，一个同等身份、同等气质的人会叫什么」。
2. 【家族共姓】同一 family_key 的成员必须共用同一个姓（surname 字段），
   只有名不同。父女、兄妹的姓必须一致。
3. 【身份匹配】判断原名透出的社会阶层、年代、性别、气质，在目标文化中找对应。
   书香门第与市井混混的名字风格必须不同。
4. 【时代匹配】名字要属于目标世界观的年代。昭和日本不能用平成才流行的名字，
   中世纪欧洲不能用现代教名。
5. 每人给 2–3 个备选（alternatives），各有侧重。
6. rationale 说明为什么这个名字在目标文化里等效，不要泛泛而谈。"""


@dataclass
class NamingResult:
    created: int = 0
    updated: int = 0
    skipped_locked: int = 0
    rejected: list[dict] = field(default_factory=list)
    families: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created, "updated": self.updated,
            "skipped_locked": self.skipped_locked,
            "rejected": self.rejected, "families": self.families,
        }


def suggest_names(
    db: Session, transform: WorldTransform, *,
    entity_ids: list[str] | None = None, limit: int = 60,
) -> NamingResult:
    """为实体生成目标世界观译名。按 family_key 分组，整族一次生成。"""
    src = db.get(WorldProfile, transform.source_profile_id)
    tgt = db.get(WorldProfile, transform.target_profile_id)
    if src is None or tgt is None:
        raise PipelineError("world profile 缺失")

    q = select(WorldEntity).where(
        WorldEntity.novel_id == transform.novel_id,
        WorldEntity.kind.in_([EntityKind.character, EntityKind.location,
                              EntityKind.faction]),
    )
    if entity_ids:
        q = q.where(WorldEntity.id.in_(entity_ids))
    entities = list(db.execute(q.limit(limit)).scalars())
    if not entities:
        raise PipelineError("没有可命名的实体，请先抽取实体")

    existing = {
        n.entity_id: n
        for n in db.execute(
            select(EntityWorldName).where(
                EntityWorldName.transform_id == transform.id
            )
        ).scalars()
    }

    result = NamingResult()
    pending = []
    for e in entities:
        cur = existing.get(e.id)
        if cur is not None and cur.locked:
            result.skipped_locked += 1
            continue
        pending.append(e)
    if not pending:
        return result

    # 按家族分组；无家族的各自成组，保证结构统一
    groups: dict[str, list[WorldEntity]] = {}
    for e in pending:
        groups.setdefault(e.family_key or f"solo:{e.id}", []).append(e)

    payload = [
        {
            "family_key": key,
            "members": [
                {
                    "entity_id": e.id,
                    "source_name": e.display_name,
                    "kind": e.kind.value,
                    "aliases": e.aliases_json or [],
                    "summary": e.summary or "",
                }
                for e in members
            ],
        }
        for key, members in groups.items()
    ]

    lang_cfg = tgt.language_json or {}
    axes = tgt.axes_json or {}
    data, _task = chat_json(
        db,
        [
            {"role": "system", "content": NAME_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"【源世界观】{src.display_name}\n"
                    f"【目标世界观】{tgt.display_name}\n"
                    f"【目标语言】{transform.target_language_code}\n"
                    f"【姓名格式】{lang_cfg.get('name_pattern', 'family_given')}"
                    f" / 书写系统 {lang_cfg.get('name_script', '?')}\n"
                    f"【年代】{axes.get('era_span', '')} 社会背景 "
                    f"{axes.get('social_context', '')}\n\n"
                    f"【待命名分组】\n"
                    f"{_dump(payload)}"
                ),
            },
        ],
        NAME_SCHEMA,
        purpose="naming",
        novel_id=transform.novel_id,
        ref_kind="naming",
        ref_id=transform.id,
    )

    pattern = str(lang_cfg.get("name_pattern") or "family_given")
    by_id = {e.id: e for e in pending}

    for group in data.get("groups") or []:
        family_key = str(group.get("family_key") or "")
        surname = str(group.get("surname") or "").strip()
        if family_key and not family_key.startswith("solo:"):
            result.families[family_key] = surname

        for member in group.get("members") or []:
            eid = str(member.get("entity_id") or "")
            entity = by_id.get(eid)
            if entity is None:
                continue
            target_name = str(member.get("target_name") or "").strip()

            ok, why = nm.validate_localized_name(
                target_name, transform.target_language_code
            )
            if not ok:
                # 从备选里找一个合格的
                picked = None
                for alt in member.get("alternatives") or []:
                    cand = str(alt.get("name") or "").strip()
                    if nm.validate_localized_name(
                        cand, transform.target_language_code
                    )[0]:
                        picked = (cand, str(alt.get("reading") or ""))
                        break
                if picked is None:
                    fb_name, fb_reading = nm.deterministic_fallback_name(
                        entity.id, transform.id, transform.target_language_code
                    )
                    picked = (fb_name, fb_reading)
                    result.rejected.append({
                        "entity": entity.display_name,
                        "proposed": target_name,
                        "reason": why,
                        "fallback": fb_name,
                    })
                else:
                    result.rejected.append({
                        "entity": entity.display_name,
                        "proposed": target_name,
                        "reason": why,
                        "used_alternative": picked[0],
                    })
                target_name, reading = picked
            else:
                reading = str(member.get("target_reading") or "")

            row = existing.get(eid)
            candidates = [
                {"name": str(a.get("name") or ""), "reading": str(a.get("reading") or ""),
                 "rationale": str(a.get("rationale") or "")}
                for a in (member.get("alternatives") or [])
                if a.get("name")
            ]
            if row is None:
                row = EntityWorldName(
                    id=new_id("wn"), entity_id=eid, transform_id=transform.id,
                    target_name=target_name, target_reading=reading or None,
                    family_key=entity.family_key,
                    family_surname=nm.split_surname(target_name, pattern)[0],
                    naming_policy=NamingPolicy.cultural_equivalent,
                    candidates_json=candidates,
                    rationale=str(member.get("rationale") or "") or None,
                    status=ReviewStatus.candidate,
                )
                db.add(row)
                existing[eid] = row
                result.created += 1
            else:
                row.target_name = target_name
                row.target_reading = reading or None
                row.family_surname = nm.split_surname(target_name, pattern)[0]
                row.candidates_json = candidates
                row.rationale = str(member.get("rationale") or "") or None
                row.status = ReviewStatus.candidate
                result.updated += 1

    db.flush()
    return result


def _dump(payload: list[dict]) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False, indent=1)
