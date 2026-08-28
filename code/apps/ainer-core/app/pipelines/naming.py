"""L1 人名映射：按家族整族生成，而不是逐个独立生成。

逐个生成时，李清照与其父李格非会被映射成两个毫不相干的姓 ——
模型看不到它们的亲属关系。整族一次喂进去，模型自己就会保证共姓。

生成后还要过两道校验：
  拼音检测   「Li Bai」这种音译直接判废（v1 只有 30 词黑名单，Xiao/Rong 全漏网）
  家族一致   同 family_key 的姓氏必须相同
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
    WorldLexicon,
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
                                "appellations": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["source_surface", "target_surface"],
                                        "properties": {
                                            "source_surface": {"type": "string"},
                                            "target_surface": {"type": "string"},
                                            "relation_note": {"type": "string"},
                                        },
                                    },
                                },
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
5. 【称呼同源】成员若带 appellations 清单，必须逐条给出目标形式。
   这些不是另一个名字，是同一个人的不同叫法，**必须与 target_name 同源**：
   Thomas → Tom / Tommy / Master Ashford，绝不能冒出个 Jack —— 那就成两个人了。
   给的是目标文化里承担同样社交功能的形式，按每条标注的语域来定：
     formal_full 全名　formal_title 头衔+姓，有距离
     respectful 敬而不远　intimate 亲昵短形，只有亲近的人这样叫
     diminutive 昵称小形，带幼时残留　kinship 以关系代名，不用本名
     epithet 名号绰号，按目标文化的名号习惯重铸、不音译
     derogatory 要能读出敌意　pronoun_like 指代性称呼，不点名
   中文的「小天」承载的是关系不是信息。全部译成全名，
   译文照样通顺，但读者感觉不到亲疏 —— 这种丢失不报错，只会让书变淡。
   relation_note 一句话说明它与本名的关系，供人工审核一眼判断是否同源。
6. 每人给 2–3 个备选（alternatives），各有侧重。
7. rationale 说明为什么这个名字在目标文化里等效，不要泛泛而谈。"""


def role_term_hit(
    names: set[str], family_key: str | None, lex_terms: set[str]
) -> str | None:
    """这个实体是不是「职务／身份」而非人名。返回命中的词条，否则 None。

    判据两条：名字在名物词表里，且没有家族键。
    有 family_key 说明它确实是个有姓的人 —— 「柳三娘」既是称呼也带姓氏，
    那种仍要生成人名；纯职务词（总镖头、掌柜、小二）才跳过。
    """
    hit = {n for n in names if n} & lex_terms
    if hit and not family_key:
        return sorted(hit)[0]
    return None


def _pending_appellations(
    db: Session, transform: WorldTransform, entity_ids: list[str],
) -> dict[str, list[dict]]:
    """取还没定目标形式的称呼，连语域说明一起交给模型。

    已定形且锁定的不再送 —— 人工定过的称呼不能被重跑改掉。
    """
    from app.models import REGISTER_BRIEF, EntityAppellation

    if not entity_ids:
        return {}
    out: dict[str, list[dict]] = {}
    for a in db.execute(
        select(EntityAppellation).where(
            EntityAppellation.entity_id.in_(entity_ids),
            EntityAppellation.locked.is_(False),
        )
    ).scalars():
        if a.transform_id not in (None, transform.id):
            continue
        out.setdefault(a.entity_id, []).append({
            "source_surface": a.source_surface,
            "register": a.register.value,
            "register_brief": REGISTER_BRIEF.get(a.register, ""),
            "speaker": a.speaker_hint or "",
            "occurrences": a.occurrences,
        })
    return out


@dataclass
class NamingResult:
    created: int = 0
    updated: int = 0
    skipped_locked: int = 0
    appellations: int = 0
    #: 按职务/身份处理、不生成人名的实体
    as_role_term: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    families: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created, "updated": self.updated,
            "skipped_locked": self.skipped_locked,
            "appellations": self.appellations,
            "as_role_term": self.as_role_term,
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

    # 名物词表里已有的实体是**职务／身份**而非人名：总镖头、掌柜、小二、师父。
    # 给它们生成人名的后果很实：模型给「总镖头」提了 старшой（俄语「老大」），
    # 被「必须是名+父称+姓」的规则判不合格，回落到兜底池，
    # 于是这个职务变成了 Дарья Ивановна Орлова —— 一个凭空出现的女角色，
    # 而译文里「总镖头把镖单推过来」从此由她来做。
    #
    # 判据用名物词表而不是新加字段：词表里有的**就是**名物，这是它的定义。
    # 顺序也对得上 —— 名物勘探在命名之前跑。
    lex_terms: set[str] = set()
    for row in db.execute(
        select(WorldLexicon).where(WorldLexicon.transform_id == transform.id)
    ).scalars():
        lex_terms.add(row.source_term)
        lex_terms.update(row.source_aliases or [])

    result = NamingResult()
    pending = []
    for e in entities:
        cur = existing.get(e.id)
        if cur is not None and cur.locked:
            result.skipped_locked += 1
            continue
        names = {e.display_name, *(e.aliases_json or [])}
        hit = role_term_hit(names, e.family_key, lex_terms)
        if hit:
            result.as_role_term.append({
                "entity": e.display_name,
                "lexicon_term": hit,
                "note": "按名物词表处理，不生成人名",
            })
            continue
        pending.append(e)
    if not pending:
        return result

    # 按家族分组；无家族的各自成组，保证结构统一
    groups: dict[str, list[WorldEntity]] = {}
    for e in pending:
        groups.setdefault(e.family_key or f"solo:{e.id}", []).append(e)

    aps = _pending_appellations(db, transform, [e.id for e in pending])
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
                    **({"appellations": aps[e.id]} if aps.get(e.id) else {}),
                }
                for e in members
            ],
        }
        for key, members in groups.items()
    ]

    lang_cfg = tgt.language_json or {}
    axes = tgt.axes_json or {}
    pattern = str(lang_cfg.get("name_pattern") or "family_given")
    by_id = {e.id: e for e in pending}

    # 分批：一次一族、累计成员到上限即发。
    # 整本书一次性塞进去必然撞 max_tokens —— 每人还要带备选与称呼，
    # 输出量是输入的好几倍，60 个实体一次调用一定被截断。
    # 家族不能拆：整族一起才谈得上共姓，那是这个 pipeline 存在的理由。
    batches: list[list[dict]] = []
    cur: list[dict] = []
    cur_n = 0
    for group in payload:
        n = len(group["members"])
        if cur and cur_n + n > _NAMING_BATCH_MEMBERS:
            batches.append(cur)
            cur, cur_n = [], 0
        cur.append(group)
        cur_n += n
    if cur:
        batches.append(cur)

    for batch in batches:
        _name_one_batch(
            db, transform, src, tgt, lang_cfg, axes, batch,
            by_id, existing, pattern, result,
        )
    db.flush()
    return result


#: 单次命名调用的成员数上限。输出含备选与称呼，比输入长几倍。
_NAMING_BATCH_MEMBERS = 8


def _name_one_batch(
    db: Session, transform: WorldTransform, src: WorldProfile, tgt: WorldProfile,
    lang_cfg: dict, axes: dict, payload: list[dict],
    by_id: dict[str, WorldEntity], existing: dict[str, EntityWorldName],
    pattern: str, result: NamingResult,
) -> None:
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
        max_tokens=16384,
        novel_id=transform.novel_id,
        ref_kind="naming",
        ref_id=transform.id,
    )

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
                target_name, transform.target_language_code, pattern,
                kind=entity.kind.value,
            )
            if not ok:
                # 从备选里找一个合格的
                picked = None
                for alt in member.get("alternatives") or []:
                    cand = str(alt.get("name") or "").strip()
                    if nm.validate_localized_name(
                        cand, transform.target_language_code, pattern,
                        kind=entity.kind.value,
                    )[0]:
                        picked = (cand, str(alt.get("reading") or ""))
                        break
                if picked is None and entity.kind is not EntityKind.character:
                    # 地点与组织没有兜底池，也不该借用人名池 ——
                    # 那正是「镖局」变成一个人名的由来。留空待人工处理。
                    log.warning("%s（%s）译名不合格且无兜底：%s",
                                entity.display_name, entity.kind.value, why)
                    result.rejected.append({
                        "entity": entity.display_name,
                        "kind": entity.kind.value,
                        "proposed": target_name,
                        "reason": why,
                        "fallback": None,
                        "action": "非人物实体不套用人名兜底，需人工指定",
                    })
                    continue
                if picked is None:
                    try:
                        fb_name, fb_reading = nm.deterministic_fallback_name(
                            entity.id, transform.id, transform.target_language_code
                        )
                    except nm.NoFallbackPool as exc:
                        # 该语言没有兜底池。跳过这个实体而不是硬塞一个
                        # 别的语言的名字 —— 那会一路用下去且沿途不报错。
                        log.warning("%s 无法命名：%s", entity.display_name, exc)
                        result.rejected.append({
                            "entity": entity.display_name,
                            "proposed": target_name,
                            "reason": why,
                            "fallback": None,
                            "action": "已跳过，需人工指定译名",
                        })
                        continue
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

            result.appellations += _apply_appellations(
                db, transform, entity, target_name, member.get("appellations") or []
            )


def _apply_appellations(
    db: Session, transform: WorldTransform, entity: WorldEntity,
    base_name: str, items: list[dict],
) -> int:
    """把称呼的目标形式落到本映射下。

    这里**不做**字面同源校验。英语的昵称与本名常常没有共同词根 ——
    John→Jack、Edward→Ned、Margaret→Peggy 都是标准形式，
    按前缀比对会把它们全判成「另一个人」，同时又拦不住真正的乱配。
    字面判不了，只能靠文化知识判，那就不是正则的活。

    所以策略是标记而非拦截：字面无关联的记一条 risk_note，
    留给二次审核（模型判 + 人工过目）。宁可多看一眼，不可误杀。
    kinship / pronoun_like / epithet 天然不含本名（brother、那位公子、
    北地剑客），连标记都不需要。
    """
    from app.models import EntityAppellation, Register

    if not items:
        return 0
    rows = {
        r.source_surface: r
        for r in db.execute(
            select(EntityAppellation).where(
                EntityAppellation.entity_id == entity.id,
                or_(
                    EntityAppellation.transform_id == transform.id,
                    EntityAppellation.transform_id.is_(None),
                ),
            )
        ).scalars()
    }
    roots = {t.lower() for t in re.findall(r"[A-Za-z]{3,}", base_name)}
    free = {Register.kinship, Register.pronoun_like, Register.epithet}
    n = 0
    for item in items:
        surface = str(item.get("source_surface") or "").strip()
        target = str(item.get("target_surface") or "").strip()
        row = rows.get(surface)
        if not surface or not target or row is None or row.locked:
            continue
        risk = None
        if row.register not in free and roots and not _shares_root(target, roots):
            risk = (
                f"「{target}」与本名「{base_name}」无字面关联。"
                f"若是目标语言里的标准昵称形式（如 John→Jack）属正常，"
                f"若是另起的名字则会被读者当成另一个角色 —— 请确认。"
            )
        if row.transform_id is None:
            # 未绑定的登记条目留作跨映射的源，本映射另存一条
            row = EntityAppellation(
                id=new_id("ap"), entity_id=entity.id, transform_id=transform.id,
                source_surface=surface, register=row.register,
                speaker_hint=row.speaker_hint, occurrences=row.occurrences,
                evidence_json=row.evidence_json,
            )
            db.add(row)
        row.target_surface = target
        row.relation_note = str(item.get("relation_note") or "") or None
        row.risk_note = risk
        row.status = ReviewStatus.candidate
        n += 1
    return n


def _shares_root(target: str, roots: set[str]) -> bool:
    """目标称呼与本名是否有字面关联（共同前缀 ≥3 字，或整词包含）。

    只用于决定要不要提请人工看一眼，**不用于拒绝**。
    Master Ashford 含 Ashford → 有关联；Tom 与 Thomas 无共同前缀 → 没关联，
    但那是正确的昵称 —— 所以这个函数返回 False 只意味着「值得确认」。
    """
    for token in re.findall(r"[A-Za-z]{2,}", target.lower()):
        for root in roots:
            if token == root or token in root or root in token:
                return True
            common = 0
            for a, b in zip(token, root):
                if a != b:
                    break
                common += 1
            if common >= 3:
                return True
    return False


def _dump(payload: list[dict]) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False, indent=1)
