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
from app.pipelines.base import PipelineError, chat_json, as_text, as_items
from app.pipelines.entities import _NEEDS_PROPER_NAME
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
3. 【身份匹配】判断原名透出的社会阶层、年代、气质，在目标文化中找对应。
   **性别以 sex 字段为准**，没给 sex 才从上下文推断 —— 目标语言的人名
   多带性别形态（父称与姓氏尾缀），配错一眼就能看出来。
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
    names: set[str], family_key: str | None, lex_terms: set[str],
    name_type: "NameType | None" = None,
) -> str | None:
    """这个实体是不是「职务／身份」而非人名。返回判定依据，否则 None。

    **优先看 name_type** —— 那是抽取时看着原文做的判断，
    比事后反推可信。反推靠「名字在不在名物词表里」，
    可名物勘探跑在命名之前也可能没跑，那时反推不出任何东西。

    name_type 缺失（老数据一律是默认的 proper）时才回落到词表反推。
    有 family_key 的一律当人：「柳三娘」既是称呼也带姓氏，仍要生成人名。
    """
    from app.models import NameType

    if family_key:
        return None
    if name_type is NameType.role:
        return "name_type=role"
    hit = {n for n in names if n} & lex_terms
    return sorted(hit)[0] if hit else None


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
    #: 性别取不到的角色。**不要静静地替他挑一个** ——
    #: 「灰衣汉子」抽到 Анна Петровна Волкова，数据上完全合法，
    #: 只有读正文的人会发现那是个女名
    unknown_sex: list[str] = field(default_factory=list)
    families: dict[str, str] = field(default_factory=dict)

    def verdict(self) -> str | None:
        """整体判断。

        **一条条列拒绝，看着像正常质检；说出「几乎全被拒、同一个理由」，
        才看得出是这一步整体没生效。** 模型每次都提音译而这个圈层要
        文化等效名，全书角色就会一个不落地落进兜底池 ——
        而兜底池只有四个男名，长篇会直接抽干，
        于是十几个角色共用四个名字，且沿途不报任何错。
        """
        total = self.created + self.updated
        # 阈值取 0.6 而不是 0.8：分母里混着地点与组织（它们很少被拒），
        # 按全体算会把「全部角色都被拒」稀释成看着正常的比例。
        # 宁可偶尔多报一次 —— 漏报的代价是整本书共用四个兜底名。
        if not total or len(self.rejected) < max(3, total * 0.6):
            return None
        reasons = [str(r.get("reason") or "") for r in self.rejected]
        top = max(set(reasons), key=reasons.count) if reasons else ""
        if reasons.count(top) < len(reasons) * 0.6:
            return None
        return (f"{len(self.rejected)}/{total} 条被拒且理由集中"
                f"（{top[:40]}）—— 这不是个别失手，"
                f"是提示词或圈层的 name_pattern 配置对不上，"
                f"角色会整批落进兜底池")

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created, "updated": self.updated,
            "skipped_locked": self.skipped_locked,
            "appellations": self.appellations,
            "as_role_term": self.as_role_term,
            "rejected": self.rejected, "families": self.families,
            "unknown_sex": self.unknown_sex,
            "verdict": self.verdict(),
        }



#: 性别 → 给命名提示词的说法。**目标语言的人名多数带性别形态**
#: （俄语的父称与姓氏尾缀、西语的词尾），配错一眼就能看出来。
_SEX_CN = {"male": "男", "female": "女"}


def known_sex(db: Session, entity: WorldEntity) -> str | None:
    """这个角色的性别，取得到就取，取不到返回 None。

    **不要让模型从汉字去猜。** 提示词原来写的是「判断原名透出的……性别」，
    于是「三娘」被判成男、「沈砚」被判成女 —— 一个中文母语者一眼的事，
    模型在跨语言命名的语境里做不稳。而系统里其实是知道的：
    配音表按声部记着（三娘是女声），视觉侧的不变项也记着。

    两个来源都查，视觉侧优先 —— 它是画面的依据，与看到的脸必须一致。
    """
    from app.models import EntityWorldVisual, VoiceCasting
    from app.worldview.voice import VoiceSpec, to_tts_params

    vis = db.execute(
        select(EntityWorldVisual).where(EntityWorldVisual.entity_id == entity.id)
    ).scalars().first()
    sex = str(((vis.invariant_json or {}) if vis else {}).get("sex") or "").lower()
    if sex in _SEX_CN:
        return sex

    cast = db.execute(
        select(VoiceCasting).where(VoiceCasting.entity_id == entity.id)
    ).scalars().first()
    if cast is not None and cast.timbre_json:
        got = str(to_tts_params(VoiceSpec.from_json(cast.timbre_json)).get("gender") or "")
        if got in _SEX_CN:
            return got
    return None

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
        # 与 entities._NEEDS_PROPER_NAME 共用同一份定义 ——
        # 两处各写一份就会出现「命名管线不管、占位符却要求有」的死角，
        # 表现是每次翻译都报一串永远消不掉的「缺译名」。
        WorldEntity.kind.in_(sorted(_NEEDS_PROPER_NAME, key=lambda k: k.value)),
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
        hit = role_term_hit(names, e.family_key, lex_terms, e.name_type)
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
                    # 性别作为**事实**传下去，不让模型从汉字猜。
                    # 取不到时不填 —— 填一个「未知」会被当成一种性别用
                    **({"sex": _SEX_CN[sx]} if (sx := known_sex(db, e)) else {}),
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

    # 已占用的译名，**跨批次共享**。分批时不同批的模型看不到彼此的产出，
    # 撞名正是这么来的；库里已有的也要算进去，否则新命名会撞上老命名。
    taken: dict[str, str] = {
        n.target_name: n.entity_id for n in existing.values() if n.target_name
    }
    for batch in batches:
        _name_one_batch(
            db, transform, src, tgt, lang_cfg, axes, batch,
            by_id, existing, pattern, result, taken,
        )
    db.flush()
    return result


#: 音译圈层的命名指令。与文化等效命名**方向相反** ——
#: 存真档要的是原名的读音，不是目标文化里的等效名字。
#: 用错这一条的后果实测过：一本仙侠里主角叫 Ethan Ashford。
TRANSLIT_SYSTEM = """你是跨文化出版的命名顾问，这一本走的是【音译保名】。

核心任务：把源世界观的人名**按读音转写**成目标语言的文字，
**不要**换成目标文化里的本土名字。

  ✓ 林昭 → Lin Zhao　　苏晚 → Su Wan　　青云宗 → Qingyun Sect
  ✗ 林昭 → Ethan Ashford —— 那是换了个人，不是译名

为什么：这本书的世界观原样保留（境界体系、宗门、灵石都在），
只有语言换了。给这个世界里的人配一个英美名字，
读者会觉得这些人不属于这个世界。

规则：
1. 姓在前名在后，按原文顺序转写，两段之间空一格。
2. 同一个字在全书用同一种转写，不要一处 Zhao 一处 Chao。
3. 称号与宗门名可以「音译 + 意译」并存：青云宗 → Qingyun Sect
   （专名音译，通名意译）。
4. 不要加声调符号 —— 目标读者读不出来，只会碍眼。
5. 别名与本名分开转写，不要合并。"""


def _system_for(name_pattern: str) -> str:
    """按命名规范选提示词。

    音译与文化等效是两件相反的事，一段提示词做不到两件 ——
    而规则层只会把不合规范的产出全部拒掉，报一堆
    「不是原名的音译」，看着像模型不听话，
    其实是根本没告诉过它这一本要音译。
    """
    from app.worldview.naming import wants_transliteration

    return TRANSLIT_SYSTEM if wants_transliteration(name_pattern) else NAME_SYSTEM


#: 单次命名调用的成员数上限。输出含备选与称呼，比输入长几倍。
_NAMING_BATCH_MEMBERS = 8


def _name_one_batch(
    db: Session, transform: WorldTransform, src: WorldProfile, tgt: WorldProfile,
    lang_cfg: dict, axes: dict, payload: list[dict],
    by_id: dict[str, WorldEntity], existing: dict[str, EntityWorldName],
    pattern: str, result: NamingResult, taken: dict[str, str],
) -> None:
    data, _task = chat_json(
        db,
        [
            {"role": "system", "content": _system_for(pattern)},
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

    for group in as_items(data, "groups"):
        family_key = str(group.get("family_key") or "")
        surname = as_text(group.get("surname"))
        if family_key and not family_key.startswith("solo:"):
            result.families[family_key] = surname

        for member in as_items(group, "members"):
            eid = str(member.get("entity_id") or "")
            entity = by_id.get(eid)
            if entity is None:
                continue
            target_name = as_text(member.get("target_name"))

            ok, why = nm.validate_localized_name(
                target_name, transform.target_language_code, pattern,
                kind=entity.kind.value,
            )
            if not ok:
                # 从备选里找一个合格的
                picked = None
                for alt in as_items(member, "alternatives"):
                    cand = as_text(alt.get("name"))
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
                            entity.id, transform.id, transform.target_language_code,
                            known_sex(db, entity), avoid=set(taken),
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

            # ── 撞名 ──
            # **两个角色不能同名。** 实跑里「三娘」与「裴无咎」拿到了
            # 同一个 Павел Сергеевич Морозов —— 数据上两行都合法、
            # 校验也都通过，只有读到正文的人会发现两个人叫一个名字。
            # 分批生成时尤其容易：不同批次之间模型看不到彼此的产出。
            if target_name and target_name in taken and taken[target_name] != eid:
                try:
                    fb_name, fb_reading = nm.deterministic_fallback_name(
                        entity.id, transform.id, transform.target_language_code,
                        known_sex(db, entity), avoid=set(taken),
                    )
                    result.rejected.append({
                        "entity": entity.display_name,
                        "proposed": target_name,
                        "reason": f"与「{by_id[taken[target_name]].display_name}」重名",
                        "fallback": fb_name,
                    })
                    target_name, reading = fb_name, fb_reading
                except nm.NoFallbackPool:
                    result.rejected.append({
                        "entity": entity.display_name,
                        "proposed": target_name,
                        "reason": "重名且该语言没有兜底池",
                        "fallback": None,
                        "action": "需人工指定译名",
                    })
                    continue
            if target_name:
                taken[target_name] = eid
            if (entity.kind is EntityKind.character
                    and known_sex(db, entity) is None
                    and entity.display_name not in result.unknown_sex):
                result.unknown_sex.append(entity.display_name)

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
    # 同一个称呼可能同时存在两行：**本映射的**和**未绑定的**（跨映射的源）。
    # 按 source_surface 建索引时必须让本映射那一行胜出 ——
    # 留到未绑定那一行的话，下面会走「另存一条」的分支，
    # 再插一条 (entity, transform, surface) 完全相同的行，撞唯一键。
    # 第一次跑不会有事（那时只有未绑定的），**第二次跑必然 500**。
    rows: dict[str, EntityAppellation] = {}
    for r in db.execute(
        select(EntityAppellation).where(
            EntityAppellation.entity_id == entity.id,
            or_(
                EntityAppellation.transform_id == transform.id,
                EntityAppellation.transform_id.is_(None),
            ),
        )
    ).scalars():
        prev = rows.get(r.source_surface)
        if prev is None or (prev.transform_id is None and r.transform_id):
            rows[r.source_surface] = r
    roots = {t.lower() for t in re.findall(r"[A-Za-z]{3,}", base_name)}
    free = {Register.kinship, Register.pronoun_like, Register.epithet}
    n = 0
    for item in items:
        surface = as_text(item.get("source_surface"))
        target = as_text(item.get("target_surface"))
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
