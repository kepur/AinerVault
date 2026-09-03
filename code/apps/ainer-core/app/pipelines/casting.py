"""配音 —— 给全书的说话角色定音色，并检查听不听得出区别。

## 为什么整本一起配，而不是遇到一个配一个

**可辨识是角色之间的关系，不是单个角色的属性。**
一次配一个的话，每一个单看都合格，放在一起五个人同一把嗓子 ——
问题只有在比较时才存在，所以决策也必须在能比较的时候做。

于是配音的输入是「全书说过话的角色 + 谁跟谁同场」，
一次给出全部，且把已定的音色作为约束带进后续批次。

## 规则与模型各管什么

模型只做它真正判断不了的那一件事：从原文里看这个人该是什么嗓子。
其余全部是规则：

    取值必须落在术语表里            —— 表即白名单，越界当场判不合格
    撞声检测                        —— 声部音区音质都是有限取值，两两可比
    撞声消解                        —— 沿最有余量的维度挪，且只挪次要角色
    时期推导                        —— 年龄对嗓子的影响是规律的，不必问模型
    声线漂移检测                    —— 跨时期 identity 必须逐字一致

这样换任何一家模型，结果的下限都由规则托着。

## 撞声消解为什么只动次要角色

主角的嗓子是锚。观众对主角的声音记得最牢，改它等于换主演；
而配角改了没人察觉。所以按台词量排序，台词多的先定、不再变动。
"""
from __future__ import annotations

import hashlib

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    AssetEpoch, AssetSpec, Chapter, EntityKind, ReviewStatus, Scene, ScriptBlock,
    ScriptDoc, VoiceCasting, WorldEntity, WorldProfile,
)
from app.models.script import BlockType
from app.pipelines.base import PipelineError, as_items, as_text, chat_json
from app.worldview.voice import (
    EPOCH_FIELDS, IDENTITY_FIELDS, ORDERED, VOCAB, Collision, VoiceSpec,
    check_collisions, check_identity_drift, derive_epoch_voice, distinctness,
    field_label, to_tts_params, vocab_brief,
)

log = logging.getLogger(__name__)

#: 旁白的伪角色 key。旁白也要配 —— 它是全片出现最多的那把嗓子，
#: 跟任何主要角色撞了都比两个配角撞更刺耳。
NARRATOR = "__narrator__"

#: 一批最多配几个。批太大模型会开始敷衍，后半批全是「中位圆润男声」；
#: 批太小则同批内可比的对象太少，撞声要靠后面的规则兜。
BATCH = 10

CAST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["voices"],
    "properties": {
        "voices": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key"] + list(IDENTITY_FIELDS + EPOCH_FIELDS),
                "properties": {
                    "key": {"type": "string"},
                    **{f: {"type": "string"} for f in IDENTITY_FIELDS + EPOCH_FIELDS},
                    "speech_habits": {"type": "string"},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}

CAST_SYSTEM = """你是选角导演，要给一本小说里的角色定音色。

音色的作用有两个，缺一不可：
  **贴人物** —— 嗓子要对得上这个人的年龄、身份、经历、性情
  **能分辨** —— 同一场戏里的人，观众闭着眼也要知道是谁在说话

第二条比第一条更容易被忽略。给三个江湖汉子都配「低沉浑厚的男声」，
每一个单看都对，凑到一场戏里就成了一个人自言自语。
所以拿到名单后先看谁和谁同场，同场的必须在声部、音区、音质上明显岔开。

%s

另外两项：
  speech_habits  这个人说话的习惯：口头禅、句式长短、爱用什么称呼。
                 它影响的是**词句**不是嗓子，但同样是辨识度的一部分。
  rationale      一句话说明为什么是这个嗓子，要落在原文给的信息上。

旁白（key 为 __narrator__）也要配。它是全片出现最多的那把嗓子，
必须和每一个主要角色都拉开距离。旁白通常中位、圆润、语速中等 ——
它不该抢戏，但也不能和主角一个声音。"""


@dataclass
class CastResult:
    cast: int = 0
    skipped_locked: int = 0
    reused: int = 0
    collisions: list[dict[str, Any]] = field(default_factory=list)
    resolved: list[dict[str, Any]] = field(default_factory=list)
    invalid: list[dict[str, Any]] = field(default_factory=list)
    no_speech: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cast": self.cast, "skipped_locked": self.skipped_locked,
            "reused": self.reused, "no_speech": self.no_speech,
            "collisions": self.collisions, "resolved": self.resolved,
            "invalid": self.invalid,
        }


# ── 从剧本取事实 ──────────────────────────────────────────────────────────────

#: 没有分场信息时，把相邻的这么多条对白算作「听得见彼此」。
#: 真正决定会不会听混的，是两个人有没有前后脚说话 ——
#: 分场只是这件事的一个近似，而且是恰好可用时才有的那个近似。
TURN_WINDOW = 6


def speaking_roles(db: Session, novel_id: str) -> tuple[
    dict[str, int], list[tuple[str, list[str]]], str
]:
    """谁说过话、说了多少句，以及谁跟谁前后脚说话。

    台词量既是重要度的代理，也是撞声消解时「谁不许动」的依据。

    同场关系优先按 scene 算 —— 一章里前后两场戏的人未必碰面，
    按整章算会把不相干的角色算成同场，逼出根本不需要的区分。

    **但剧本未必分过场**：散文线的 script_block.scene_id 是空的，
    而配音不该因此退化成只有宽阈值 —— 那样五个角色同一把嗓子也不报警。
    此时改用相邻发言窗口：连着几轮对白里出现的人，观众就是连着听到的。
    返回第三项说明用了哪种，好让审核报表说实话。
    """
    doc_ids = [
        d.id for d in db.execute(
            select(ScriptDoc).join(Chapter, ScriptDoc.chapter_id == Chapter.id)
            .where(Chapter.novel_id == novel_id)
        ).scalars()
    ]
    if not doc_ids:
        return {}, [], "none"

    rows = list(db.execute(
        select(ScriptBlock).where(
            ScriptBlock.script_doc_id.in_(doc_ids),
            ScriptBlock.block_type == BlockType.dialogue,
        ).order_by(ScriptBlock.script_doc_id, ScriptBlock.seq_no)
    ).scalars())

    lines: dict[str, int] = defaultdict(int)
    by_scene: dict[str, set[str]] = defaultdict(set)
    for b in rows:
        eid = b.speaker_entity_id
        if not eid:
            continue
        lines[eid] += 1
        if b.scene_id:
            by_scene[b.scene_id].add(eid)

    if by_scene:
        scenes = {
            s.id: s for s in db.execute(
                select(Scene).where(Scene.id.in_(list(by_scene)))
            ).scalars()
        }
        groups = [
            ((scenes[sid].title or scenes[sid].location_text
              or f"第{scenes[sid].order_no}场") if sid in scenes else sid, ms)
            for sid, ms in by_scene.items()
        ]
        basis = "scene"
    else:
        # 滑窗：同一 doc 内连续 TURN_WINDOW 条对白算一组
        groups, basis = [], "turn_window"
        cur_doc, window = None, []
        for b in rows:
            if b.script_doc_id != cur_doc:
                cur_doc, window = b.script_doc_id, []
            if not b.speaker_entity_id:
                continue
            window.append((b.seq_no, b.speaker_entity_id))
            window[:] = window[-TURN_WINDOW:]
            members = {e for _, e in window}
            if len(members) > 1:
                groups.append((f"第 {window[0][0]}–{b.seq_no} 句对白", members))

    co: list[tuple[str, list[str]]] = []
    for label, members in groups:
        if len(members) < 2:
            continue
        # 旁白与任何一组里的人都算同场 —— 它在每一场都出声
        co.append((label, sorted(members) + [NARRATOR]))
    return dict(lines), co, basis


def _entity_brief(e: WorldEntity, lines: int) -> str:
    bits = [f"- key={e.id}｜{e.display_name}｜台词 {lines} 句"]
    if e.summary:
        bits.append(f"  简介：{e.summary}")
    if e.voice_hints:
        bits.append(f"  原文里的声音描写：{e.voice_hints}")
    if e.appearance:
        bits.append(f"  外貌：{e.appearance[:120]}")
    return "\n".join(bits)


# ── 校验与消解 ────────────────────────────────────────────────────────────────

def _normalize(item: dict[str, Any]) -> tuple[VoiceSpec, list[str]]:
    """把模型的一条产出收进术语表，并报告越界项。

    越界不当场丢弃 —— 「低沉的」比「低沉」多一个字，丢掉会让整条作废，
    而它显然想说的是「低沉」。先做包含匹配，匹配不上才算越界。
    """
    spec = VoiceSpec()
    bad: list[str] = []
    for f in IDENTITY_FIELDS + EPOCH_FIELDS:
        raw = as_text(item.get(f)).strip()
        terms = VOCAB.get(f)
        if not terms:
            setattr(spec, f, raw[:32])
            continue
        if raw in terms:
            setattr(spec, f, raw)
            continue
        hit = next((t for t in terms if t and t in raw), "")
        if hit:
            setattr(spec, f, hit)
        elif raw:
            bad.append(f"{field_label(f)}={raw}")
    return spec, bad


def _headroom(f: str, value: str, taken: set[str]) -> str | None:
    """在某个维度上挪一格，挑一个没被同场占用的取值。

    有序维度优先挪到相邻档再往外扩 —— 挪得越少越贴近原判断；
    无序维度按表序找第一个空位。
    """
    terms = VOCAB.get(f)
    if not terms:
        return None
    if f in ORDERED and value in terms:
        i = terms.index(value)
        order = sorted(range(len(terms)), key=lambda j: (abs(j - i), j))
    else:
        order = list(range(len(terms)))
    for j in order:
        if terms[j] != value and terms[j] not in taken:
            return terms[j]
    return None


#: 消解时的挪动顺序。先挪音质 —— 它对辨识度贡献大，且不像声部那样
#: 一改就变成另一个人；音区其次；实在不行才动共鸣。
#: **不挪声部**：把一个男角色改成女声不是消解撞声，是改人物。
_RESOLVE_ORDER = ("texture", "pitch", "resonance", "tempo")


def resolve_collisions(
    voices: dict[str, VoiceSpec],
    weights: dict[str, int],
    co_occurrence: list[tuple[str, list[str]]],
    *,
    labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """把撞在一起的音色拉开。台词多的不动，少的让路。

    每次只改一个维度、改完立刻重测 —— 一次改三项会过度偏离
    模型基于原文做出的判断，而那份判断多数时候是对的，
    只是没考虑到旁边还站着一个人。
    """
    changes: list[dict[str, Any]] = []
    labels = labels or {}
    for _ in range(6):
        cols = check_collisions(voices, labels={k: k for k in voices},
                                co_occurrence=co_occurrence)
        if not cols:
            break
        col = cols[0]
        a, b = col.left, col.right
        # 台词少的那个让路；旁白权重按最高算，它不该被挪
        loser = b if weights.get(a, 0) >= weights.get(b, 0) else a
        keeper = a if loser == b else b
        peers = {
            m for where, ms in co_occurrence if loser in ms for m in ms
        } - {loser}
        moved = False
        for f in _RESOLVE_ORDER:
            taken = {getattr(voices[p], f) for p in peers if p in voices}
            nv = _headroom(f, getattr(voices[loser], f), taken)
            if not nv:
                continue
            old = getattr(voices[loser], f)
            setattr(voices[loser], f, nv)
            if distinctness(voices[loser], voices[keeper])[0] <= col.score:
                setattr(voices[loser], f, old)   # 没拉开，还原换下一个维度
                continue
            changes.append({
                "entity": labels.get(loser, loser),
                "against": labels.get(keeper, keeper),
                "field": f, "from": old, "to": nv,
                "detail": (
                    f"{labels.get(loser, loser)} 与 {labels.get(keeper, keeper)}"
                    f"音色太近，把{field_label(f)}从「{old}」改为「{nv}」"
                ),
            })
            moved = True
            break
        if not moved:
            break
    return changes


# ── 主流程 ────────────────────────────────────────────────────────────────────

def cast_voices(
    db: Session, novel_id: str, profile: WorldProfile, *,
    entity_ids: list[str] | None = None, force: bool = False,
) -> CastResult:
    """给全书说过话的角色定音色。"""
    lines, co, _basis = speaking_roles(db, novel_id)
    result = CastResult()
    if not lines:
        result.no_speech = 1
        return result

    ents = {
        e.id: e for e in db.execute(
            select(WorldEntity).where(
                WorldEntity.novel_id == novel_id,
                WorldEntity.kind == EntityKind.character,
                WorldEntity.id.in_(list(lines)),
            )
        ).scalars()
    }
    existing = {
        c.cast_key: c for c in db.execute(
            select(VoiceCasting).where(
                VoiceCasting.world_profile_id == profile.id,
                VoiceCasting.epoch_key == "baseline",
            )
        ).scalars()
    }

    # 台词多的先配 —— 先定的成为后定的约束，而主角的嗓子最该先定死
    todo = sorted(ents, key=lambda k: -lines.get(k, 0))
    if entity_ids:
        todo = [k for k in todo if k in set(entity_ids)]
    if NARRATOR not in existing or force:
        todo = [NARRATOR] + todo

    labels = {k: (ents[k].display_name if k in ents else "旁白") for k in
              list(ents) + [NARRATOR]}
    weights = dict(lines)
    weights[NARRATOR] = max(lines.values()) + 1  # 旁白不让路

    voices: dict[str, VoiceSpec] = {}
    habits: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for k, c in existing.items():
        if k in labels:
            voices[k] = VoiceSpec.from_json(c.timbre_json)

    pending = []
    for k in todo:
        row = existing.get(k)
        if row is not None and not force:
            if row.locked or row.status is ReviewStatus.locked:
                result.skipped_locked += 1
                continue
            if row.timbre_json:
                result.reused += 1
                continue
        pending.append(k)

    axes = profile.axes_json or {}
    lang = profile.language_json or {}
    world = (
        f"【目标圈层】{profile.display_name}"
        f"（{axes.get('era_span') or ''} {axes.get('social_context') or ''}）\n"
        f"口音要写这个圈层里真实存在的层次，不要写原文文化里的方言。\n"
        f"【语域】{lang.get('register') or '未定'}"
    )

    model_name = None
    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        roster = []
        for k in batch:
            if k == NARRATOR:
                roster.append(f"- key={NARRATOR}｜旁白｜贯穿全书")
            else:
                roster.append(_entity_brief(ents[k], lines.get(k, 0)))
        taken = [
            f"  {labels.get(k, k)}：{v.describe()}"
            for k, v in voices.items() if k not in batch
        ]
        pairs = [
            f"  {sc}：{'、'.join(labels.get(m, m) for m in ms if m in labels)}"
            for sc, ms in co[:20]
            if any(m in batch for m in ms)
        ]
        user = world + "\n\n【本批要配的角色】\n" + "\n".join(roster)
        if pairs:
            user += "\n\n【同场关系 —— 这些人会在同一场戏里说话，必须能听辨】\n" \
                    + "\n".join(pairs)
        if taken:
            user += "\n\n【已定的音色，不要与之雷同】\n" + "\n".join(taken)

        try:
            data, task = chat_json(
                db,
                [{"role": "system", "content": CAST_SYSTEM % vocab_brief()},
                 {"role": "user", "content": user}],
                CAST_SCHEMA, purpose="casting", novel_id=novel_id,
                ref_kind="voice_casting", ref_id=profile.id,
            )
        except PipelineError as exc:
            log.warning("配音批次失败：%s", exc)
            continue
        model_name = task.model

        got = {}
        for item in as_items(data, "voices"):
            key = as_text(item.get("key")).strip()
            if key not in batch:
                # 模型可能回名字而不是 key，按名字兜一次
                key = next((k for k in batch if labels.get(k) == key), "")
                if not key:
                    continue
            spec, bad = _normalize(item)
            miss = spec.missing()
            if bad or miss:
                result.invalid.append({
                    "entity": labels.get(key, key),
                    "off_vocab": bad, "missing": [field_label(m) for m in miss],
                })
            got[key] = spec
            habits[key] = as_text(item.get("speech_habits"))[:500]
            reasons[key] = as_text(item.get("rationale"))[:500]
        voices.update(got)
        for k in batch:
            if k not in got:
                result.invalid.append({"entity": labels.get(k, k),
                                       "missing": ["模型没有返回这个角色"]})

    # 规则兜底：模型看过同场关系仍可能撞，这里按规则拉开
    result.resolved = resolve_collisions(voices, weights, co, labels=labels)
    result.collisions = [
        c.as_dict() for c in check_collisions(voices, labels=labels,
                                              co_occurrence=co)
    ]

    for k, spec in voices.items():
        if k not in pending:
            continue
        row = existing.get(k)
        if row is None:
            row = VoiceCasting(
                id=new_id("vc"), cast_key=k,
                entity_id=None if k == NARRATOR else k,
                world_profile_id=profile.id, epoch_key="baseline",
            )
            db.add(row)
            existing[k] = row
        row.timbre_json = spec.as_dict()
        row.speech_habits = habits.get(k) or row.speech_habits
        row.rationale = reasons.get(k) or row.rationale
        row.model = model_name
        row.status = ReviewStatus.candidate
        result.cast += 1

    db.flush()
    return result


#: AssetEpoch.kind → 音色推导用的类型
_KIND_MAP = {"age": "age", "injury": "injury", "status": "age",
             "gear": "age", "season": "age", "ruin": "age", "disguise": "age"}


def cast_epoch_voices(
    db: Session, novel_id: str, profile: WorldProfile,
) -> dict[str, Any]:
    """按素材时期推出各期音色。**不调模型。**

    年龄对嗓子的影响是规律的：少年到壮年音区下沉力度上升，
    老年音区回升但力度与语速都下来。规律的部分交给规则，
    模型省下来只做它真正判断不了的事。

    identity 五项从基准逐字复制 —— 这是「同一个嗓子」的唯一保证，
    也是这里必须用规则而不能重新问一遍模型的原因：
    再问一遍，模型会重新描述一遍嗓子，于是漂了。
    """
    base = {
        c.cast_key: c for c in db.execute(
            select(VoiceCasting).where(
                VoiceCasting.world_profile_id == profile.id,
                VoiceCasting.epoch_key == "baseline",
            )
        ).scalars()
    }
    if not base:
        raise PipelineError("还没有基准音色，先跑一次配音")

    # 人物时期直接挂在人物上（subject_key = entity_id）。
    # 绑在这个角色身上的素材（他的行装、他的刀）分期时，同样是这个人变了，
    # 所以两条都算 —— 但音色只跟人走，同角色多份按 (角色,期) 去重
    rows = list(db.execute(
        select(AssetEpoch, AssetEpoch.entity_id)
        .where(
            AssetEpoch.world_profile_id == profile.id,
            AssetEpoch.entity_id.in_(list(base)),
        ).order_by(AssetEpoch.from_chapter_order)
    ).all()) + list(db.execute(
        select(AssetEpoch, AssetSpec.entity_id)
        .join(AssetSpec, AssetEpoch.asset_spec_id == AssetSpec.id)
        .where(
            AssetEpoch.world_profile_id == profile.id,
            AssetSpec.entity_id.in_(list(base)),
        ).order_by(AssetEpoch.from_chapter_order)
    ).all())

    existing = {
        (c.cast_key, c.epoch_key): c for c in db.execute(
            select(VoiceCasting).where(
                VoiceCasting.world_profile_id == profile.id,
            )
        ).scalars()
    }
    made, skipped, orphaned = 0, 0, 0
    seen: set[tuple[str, str]] = set()
    for ep, eid in rows:
        key = ep.epoch_key
        if key in (None, "", "baseline") or (eid, key) in seen:
            continue
        seen.add((eid, key))
        row = existing.get((eid, key))
        if row is not None and (row.locked or row.status is ReviewStatus.locked):
            skipped += 1
            continue
        b = VoiceSpec.from_json(base[eid].timbre_json)
        age = str(((ep.variant_json or {}).get("age_look") or "")).strip()
        spec = derive_epoch_voice(
            b, age_feel=_age_term(age) or b.age_feel,
            kind=_KIND_MAP.get(getattr(ep.kind, "value", str(ep.kind)), "age"),
        )
        if row is None:
            row = VoiceCasting(
                id=new_id("vc"), cast_key=eid, entity_id=eid,
                world_profile_id=profile.id, epoch_key=key,
            )
            db.add(row)
            existing[(eid, key)] = row
        row.timbre_json = spec.as_dict()
        row.rationale = f"由基准音色按「{ep.display_name or key}」推导，声线本体不变"
        row.status = ReviewStatus.candidate
        made += 1
    # 时期没了，它的音色行也该走。留着的后果不只是脏数据 ——
    # 审核时排不出这几期的先后（章节序号已经查不到了），
    # 于是退回按 key 的字母序，报出方向完全相反的假漂移
    live = {(eid, k) for eid, k in seen}
    for (ck, ek), row in list(existing.items()):
        if ek == "baseline" or (ck, ek) in live:
            continue
        if row.locked or row.status is ReviewStatus.locked:
            continue
        db.delete(row)
        orphaned += 1
    db.flush()
    return {"derived": made, "skipped_locked": skipped, "epochs": len(seen),
            "orphaned_removed": orphaned}


#: 原文里的年龄说法 → 年龄感术语。素材时期的 age_look 是自由文本，
#: 「二十出头」「而立之年」都要能落到量表上。
_AGE_HINT: tuple[tuple[tuple[str, ...], str], ...] = (
    (("童", "幼", "孩", "垂髫"), "童年"),
    (("少年", "十来岁", "十几岁", "总角", "束发"), "少年"),
    (("青年", "弱冠", "二十", "年轻"), "青年"),
    (("壮年", "而立", "三十", "盛年"), "壮年"),
    (("中年", "不惑", "四十", "五十", "知天命"), "中年"),
    (("老", "暮年", "花甲", "耄耋", "六十", "七十"), "老年"),
)


def _age_term(text: str) -> str:
    for keys, term in _AGE_HINT:
        if any(k in text for k in keys):
            return term
    return ""


def audit_casting(
    db: Session, novel_id: str, profile: WorldProfile,
) -> dict[str, Any]:
    """查全书配音：撞声、声线漂移、缺项、没配到的说话人。

    与场记同一条规矩：**把没能检查的也报出来**。
    报「0 处问题」而不说哪些没查过，会让人以为查过了。
    """
    lines, co, basis = speaking_roles(db, novel_id)
    rows = list(db.execute(
        select(VoiceCasting).where(VoiceCasting.world_profile_id == profile.id)
    ).scalars())
    ents = {
        e.id: e for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == novel_id)
        ).scalars()
    }
    label = lambda k: "旁白" if k == NARRATOR else (  # noqa: E731
        ents[k].display_name if k in ents else k)

    base = {r.cast_key: r for r in rows if r.epoch_key == "baseline"}
    voices = {k: VoiceSpec.from_json(r.timbre_json) for k, r in base.items()}
    cols = check_collisions(
        voices, labels={k: label(k) for k in voices}, co_occurrence=co)

    drift: list[dict[str, Any]] = []
    by_entity: dict[str, list[VoiceCasting]] = defaultdict(list)
    for r in rows:
        by_entity[r.cast_key].append(r)
    kinds, order_of = {}, {}
    pairs = list(db.execute(
        select(AssetEpoch, AssetEpoch.entity_id)
        .where(AssetEpoch.world_profile_id == profile.id,
               AssetEpoch.entity_id.isnot(None))
    ).all()) + list(db.execute(
        select(AssetEpoch, AssetSpec.entity_id)
        .join(AssetSpec, AssetEpoch.asset_spec_id == AssetSpec.id)
        .where(AssetEpoch.world_profile_id == profile.id)
    ).all())
    for e, eid in pairs:
        kinds[(eid, e.epoch_key)] = getattr(e.kind, "value", str(e.kind))
        order_of[(eid, e.epoch_key)] = e.from_chapter_order

    unorderable: list[str] = []
    for eid, group in by_entity.items():
        if len(group) < 2:
            continue
        # 排不出先后就不查 —— 拿字母序当时间序，「断腕后沙哑」会被读成
        # 「少年时嗓子好端端地变回来了」，报出方向完全相反的假漂移。
        # 报不出来比报错的好：错的告警会让人去改本来对的东西
        if any(r.epoch_key != "baseline" and (eid, r.epoch_key) not in order_of
               for r in group):
            unorderable.append(label(eid))
            continue
        # **按章节先后排，不能按 key 的字母序。** 按字母序会拿「wounded」
        # 去比「youth」—— 顺序反了，于是「断腕后沙哑」被读成
        # 「少年时嗓子好端端地变回来了」，报出一个方向完全相反的假漂移。
        ordered = sorted(group, key=lambda r: (
            r.epoch_key != "baseline",
            order_of.get((eid, r.epoch_key), 10 ** 6), r.epoch_key))
        seq = [(r.epoch_key, kinds.get((eid, r.epoch_key), "age"),
                VoiceSpec.from_json(r.timbre_json)) for r in ordered]
        for issue in check_identity_drift(seq):
            issue["entity"] = label(eid)
            drift.append(issue)

    incomplete = []
    for k, r in base.items():
        spec = VoiceSpec.from_json(r.timbre_json)
        miss = [field_label(m) for m in spec.missing()] + spec.off_vocab()
        if miss:
            incomplete.append({"entity": label(k), "problems": miss})

    uncast = [label(k) for k in lines if k not in base]

    not_checked: list[str] = []
    if not co:
        not_checked.append("没有同场关系（说话人未解析），"
                           "撞声只按全书宽阈值判，同场的严格阈值没生效")
    elif basis == "turn_window":
        not_checked.append(
            f"剧本没有分场，同场关系按「相邻 {TURN_WINDOW} 条对白」近似。"
            "跑一次剧本转换分出场次后，这一项会更准")
    if unorderable:
        not_checked.append(
            "以下角色的时期音色找不到对应的素材时期，排不出先后，"
            "声线漂移未检查：" + "、".join(unorderable)
            + "（跑一次「按时期推导」会清掉这些孤儿行）")
    if not any(len(g) > 1 for g in by_entity.values()):
        # len(by_entity) == len(base) 判不出来：一个角色有四条时期，
        # by_entity 里仍然只是一个 key
        not_checked.append("没有任何角色建了时期音色，声线漂移未检查")

    return {
        "cast": len(base), "epoch_rows": len(rows) - len(base),
        "speaking_roles": len(lines),
        "co_occurrence_basis": basis,
        "collisions": [c.as_dict() for c in cols],
        "identity_drift": drift,
        "incomplete": incomplete,
        "uncast": uncast,
        "not_checked": not_checked,
    }


def voice_for(
    db: Session, cast_key: str | None, profile_id: str, *,
    epoch_key: str = "baseline",
) -> VoiceCasting | None:
    """取某角色在某圈层下该用的音色行。找不到时回落到基准期。

    **旁白必须显式传 NARRATOR，不能靠「传空就是旁白」。**
    「这是旁白」和「说话人没解析出来」是两件事，混在一起的后果很实：
    实跑时九条说话人未知的对白全都静悄悄拿了旁白的音色，
    missing_voice 还报空 —— 数据上一切正常，听起来是旁白在自问自答。
    传空一律返回 None，让调用方自己把这条记进缺项。
    """
    if not cast_key:
        return None
    key = cast_key
    row = db.execute(
        select(VoiceCasting).where(
            VoiceCasting.cast_key == key,
            VoiceCasting.world_profile_id == profile_id,
            VoiceCasting.epoch_key == epoch_key,
        )
    ).scalars().first()
    if row is None and epoch_key != "baseline":
        row = db.execute(
            select(VoiceCasting).where(
                VoiceCasting.cast_key == key,
                VoiceCasting.world_profile_id == profile_id,
                VoiceCasting.epoch_key == "baseline",
            )
        ).scalars().first()
    return row


def casting_params(row: VoiceCasting | None) -> dict[str, Any]:
    """配音行 → TTS 参数。中性描述在这里才落成某次调用的取值。"""
    if row is None:
        return {}
    spec = VoiceSpec.from_json(row.timbre_json)
    params = to_tts_params(spec, voice_ref=row.voice_ref)
    params["voice_casting_id"] = row.id
    # 引擎上的落地。没有就不填 —— 让方言层的兜底逻辑去警告，
    # 而不是在这里悄悄编一个 voice id 出来
    if row.voice_ref:
        params["voice_id"] = row.voice_ref
        params["voice_engine"] = row.voice_engine
    if row.speech_habits:
        params["speech_habits"] = row.speech_habits
    return params


# ── 落到具体引擎 ──────────────────────────────────────────────────────────────
#
# 配音表的权威是 timbre_json 那份声学描述，不是某家引擎的 voice id ——
# 存 voice id 当权威会锁死在一家引擎上，换 TTS 就等于换一套演员。
# 但描述本身不能直接调用，中间必须有一次落地：把「中年男声中位圆润」
# 对到这家引擎某个具体音色上。这就是 voice_ref / voice_engine 两列的用途。

#: 落地时最要紧的一条：**同一个角色永远拿同一把嗓子**。
#: 用 cast_key 的哈希取模来选，而不是按遍历顺序 ——
#: 顺序会随「今天有几个角色开口」变化，换一章重跑就换了声音。


def bind_engine_voices(
    db: Session, *, novel_id: str, profile_id: str, engine: str,
    voices: Sequence[Any], overwrite: bool = False,
    free_only: bool = True,
) -> dict[str, Any]:
    """把配音表的中性描述落到某家引擎的具体音色上。

    voices 是该引擎的音色清单（capability 契约的 Voice）。
    性别是唯一硬约束 —— 把男角色配成女声，听一句就知道错了，
    而音区、音质这些维度靠引擎的表演指示去逼近，不靠挑音色。

    同性别的角色之间尽量不撞：先按哈希定位，占用了就顺延。
    撞不开时（角色比音色多）允许重复，但报出来 —— 让人知道
    「这两个人声音一样」是资源不足，不是配错了。
    """
    from app.models import VoiceCasting, WorldEntity

    # 配音表只按圈层建，没有 novel_id 这一列 —— 同一个目标圈层可以服务多部小说。
    # 所以按小说收窄要走实体：本书的角色，加上旁白（旁白没有实体）。
    mine = {e.id for e in db.execute(
        select(WorldEntity).where(WorldEntity.novel_id == novel_id)).scalars()}
    rows = [
        r for r in db.execute(
            select(VoiceCasting).where(VoiceCasting.world_profile_id == profile_id)
            .order_by(VoiceCasting.cast_key, VoiceCasting.epoch_key)
        ).scalars()
        if r.entity_id is None or r.entity_id in mine
    ]
    if not rows:
        return {"bound": 0, "skipped": 0, "collisions": [], "no_voice_for": []}

    # **免费额度的排在前面，其余按字母。**
    #
    # 原来是整池 sort()，把清单里「免费档在前」的顺序抹平了 ——
    # 于是英伦线六个角色里五个落到了付费那一族。
    # 一本长篇几千句对白，默认落在付费上是一笔不该花的钱，
    # 而这笔钱是**静默**花掉的：数据上完全正常，音频也正常出。
    #
    # 判据用音色自带的 tags，不在这里硬编模型名 ——
    # 哪些免费是供应商的事，会变。
    def _free(v: Any) -> bool:
        return "free-tier" in (getattr(v, "tags", None) or [])

    pool: dict[str, list[str]] = {}
    for v in sorted(voices, key=lambda x: (not _free(x),
                                           getattr(x, "voice_id", "") or "")):
        pool.setdefault((getattr(v, "gender", None) or "any").lower(), []).append(
            getattr(v, "voice_id", None) or str(v))

    # 一个角色的多个时期共用同一把嗓子 —— 时期变的是年龄感与状态，
    # 不是声部。按 cast_key 分配一次，所有时期沿用
    by_key: dict[str, list[VoiceCasting]] = {}
    for row in rows:
        by_key.setdefault(row.cast_key, []).append(row)

    taken: set[str] = set()
    if not overwrite:
        taken = {r.voice_ref for r in rows
                 if r.voice_ref and r.voice_engine == engine}

    free_ids = {getattr(v, "voice_id", None) for v in voices
                if "free-tier" in (getattr(v, "tags", None) or [])}
    paid_fallback: list[dict[str, Any]] = []
    #: 因为免费档不够而与他人共用嗓子的角色
    reused: list[dict[str, Any]] = []
    bound = skipped = 0
    collisions: list[str] = []
    missing: list[str] = []
    assigned: dict[str, str] = {}

    for key in sorted(by_key):
        group = by_key[key]
        current = next((r.voice_ref for r in group
                        if r.voice_ref and r.voice_engine == engine), None)
        if current and not overwrite:
            assigned[key] = current
            skipped += len(group)
            continue
        spec = VoiceSpec.from_json(group[0].timbre_json)
        gender = to_tts_params(spec).get("gender") or "any"
        candidates = pool.get(gender) or pool.get("any") or []
        if not candidates:
            missing.append(f"{key}（需要 {gender} 音色，清单里没有）")
            continue
        # **分段找：先在免费池里找，找不到才去付费池。**
        #
        # 原来把两族拼成一个列表、按 cast_key 的哈希取起点再顺延。
        # 排序里「免费在前」于是完全失效 —— 起点是哈希决定的，
        # 直接落在付费段就从付费段开始拿。实跑六个角色全落付费，
        # 而免费的 sambert-brian 一次都没被用到。
        #
        # 排序只在「从头开始扫」时才有意义。要优先就得分段。
        free_pool = [c for c in candidates if c in free_ids]
        paid_pool = [c for c in candidates if c not in free_ids]
        # **默认只用免费档。**
        #
        # 付费是要人明确说「可以花钱」才发生的事，不是「免费的用完了就自动
        # 顺延」。顺延是静默的：数据正常、音频正常出，只有账单会说话。
        # 免费不够时宁可复用同一把嗓子并报出来 ——
        # 「两个配角声音一样」是看得见的取舍，「这个月扣了十美元」不是。
        tiers = (free_pool,) if free_only else (free_pool, paid_pool)
        pick = None
        for tier in tiers:
            if not tier:
                continue
            start = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(tier)
            for offset in range(len(tier)):
                cand = tier[(start + offset) % len(tier)]
                if cand not in taken:
                    pick = cand
                    break
            if pick is not None:
                break
        # **免费档不够用时会静默顺延到付费档。**
        #
        # 英语的免费男声只有 sambert-brian-v1 一个，而一章可能有五个男角色 ——
        # 顺延之后五个人里四个落在付费池上，数据完全正常、音频也正常出，
        # 只有月底账单会说话。这是真实的资源约束不是 bug，
        # 但它必须被看见：报出来，让人决定「复用同一把嗓子」还是「付费」。
        if pick is not None and pick not in free_ids and any(
                c in free_ids for c in candidates):
            paid_fallback.append({
                "cast_key": key, "picked": pick, "gender": gender,
                "why": f"{gender} 的免费音色已被占满"
                       f"（共 {sum(1 for c in candidates if c in free_ids)} 个），"
                       f"这一位落到了付费档",
            })
        if pick is None and free_only and free_pool:
            # 免费档占满了：复用一把，而不是去付费池。
            # 用哈希选复用哪一把 —— 至少让重复分散开，
            # 不至于所有配角都撞同一个声音
            pick = free_pool[
                int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(free_pool)]
            reused.append({
                "cast_key": key, "voice": pick, "gender": gender,
                "why": f"{gender} 的免费音色只有 {len(free_pool)} 个且已全部占用，"
                       f"这一位与他人共用同一把嗓子；"
                       f"要各不相同需开通付费或换供应商",
            })
        if pick is None:
            pick = candidates[0] if candidates else None
            if pick is None:
                missing.append(f"{key}（{gender} 没有任何可用音色）")
                continue
            collisions.append(f"{key} → {pick}（{gender} 音色不够，与他人重复）")
        taken.add(pick)
        assigned[key] = pick
        for row in group:
            row.voice_ref = pick
            row.voice_engine = engine
            bound += 1

    db.flush()
    return {
        "bound": bound, "skipped": skipped, "engine": engine,
        "assigned": assigned,
        "collisions": collisions,
        "no_voice_for": missing,
        "paid_fallback": paid_fallback,
        "reused_voices": reused,
        "free_only": free_only,
        "free_voices": len(free_ids),
        # 报清楚哪一部分没查 —— 只报「0 处冲突」会让人以为全查过了
        "not_checked": [
            "音色的性别是按厂商命名推断的，没有实听；"
            "配错了要人听过之后在配音表里改",
        ],
    }
