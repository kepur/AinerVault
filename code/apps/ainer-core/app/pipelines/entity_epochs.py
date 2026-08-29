"""人物时期抽取 —— 从全书划出「哪几章的他长什么样」。

## 这一层解决的是什么

小说是沿时间展开的：林凡少年时的脸、衣着、佩刀，和他中年时不是一回事；
但**脸必须是同一张**。做不到这一点，前后两章的同一个人在观众看来
就是两个演员。

而做到这一点的办法不是「每一期都描述得更仔细」，恰恰相反 ——
是每一期都**不要重新描述**不变的部分：

    invariant  骨相、五官、瞳色、疤痕胎记      抽一次，逐字复用
    variant    发型、服装、随身兵器、气质、年龄感   每期各写

每重写一次不变项，它就漂一点：「浓眉」会变成「剑眉」，
「左颊一道旧疤」会变成「脸上有疤」。三期下来就是三个人。

## 模型做什么，规则做什么

模型只做它真正判断不了的事：**从原文看这个人在哪几章变了、变成什么样**。
分期本身、区间是否连续、不变项是否一致，全部由规则兜：

    区间必须铺满全书且不重叠      有缺口的章节取不到素材，回落到全书一个样
    跨期 invariant 逐字一致       抹平到第一期，同一性的锚只能有一个来源
    除第一期外必须写触发事件      没有触发事件的分期无法复核

判据既写进提示词（让模型一次做对），也在规则层覆写（做不对时兜住）。

## 只给主要角色分期

跑龙套的没有时期 —— 他出现两章，分期是噪声。按台词量与出场章数筛，
不够的建一个覆盖全书的基准期就停。这与固定物体（老家、祖传的刀）
走的是同一条路：**不需要变的东西，一期就够。**
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
    INVARIANT_FIELDS, VARIANT_FIELDS, AssetEpoch, Chapter, EntityKind, EpochKind,
    EntityWorldVisual, ReviewStatus, WorldEntity, WorldProfile,
)
from app.pipelines.base import PipelineError, as_items, as_text, chat_json
from app.worldview.epoch_rules import (
    DISTINCTIVE, EpochDraft, apply_rules, max_epochs, normalize_mark,
    resolve_shared_marks,
)

log = logging.getLogger(__name__)

CHAR_INVARIANT = INVARIANT_FIELDS["character"]
#: 英文渲染在 invariant/variant dict 里的键。
#: 用一个不在字段表里的名字，于是它不会被当成结构化字段参与验收，
#: 但会跟着 invariant 一起被「以第一期为准」抹平 —— 而那正是要的：
#: 英文不变项也必须跨期逐字一致，否则脸照样漂
EN_KEY = "_en"
#: 这一期年龄的英文。单独存是因为锚图要用它，而混在 visual_en 里取不出来
AGE_EN_KEY = "_age_en"
CHAR_VARIANT = VARIANT_FIELDS["character"]

_FIELD_CN = {
    "sex": "性别", "face_shape": "脸型骨相", "features": "五官", "eye_color": "瞳色",
    "skin_tone": "肤色", "scars": "疤痕胎记", "build": "体型", "height": "身高",
    "age_look": "年龄感", "hair": "发型", "facial_hair": "须髯",
    "garments": "衣着", "accessories": "配饰", "carried": "随身兵器器物",
    "bearing": "气质仪态", "condition": "身体状态",
}

#: 出场少于这么多章的角色**封顶一期**，但仍然要抽不变项。
#:
#: 一开始这里是「直接跳过、不调模型」，省下了配角的那几次调用 ——
#: 代价是省掉了他们的脸：没有不变项就生成不出脸参考图，
#: 于是灰衣汉子在第一章和第二章是两个人。
#: 凡是会出现在画面里的角色都需要一张稳定的脸，
#: 跑龙套的不需要的是**分期**，不是不变项。
MIN_CHAPTERS_FOR_EPOCHS = 3

EPOCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["invariant", "invariant_en", "epochs"],
    "properties": {
        "invariant": {
            "type": "object",
            "properties": {f: {"type": "string"} for f in CHAR_INVARIANT},
        },
        "invariant_en": {"type": "string"},
        "epochs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["epoch_key", "display_name", "kind",
                             "from_chapter_order", "trigger", "visual_en"],
                "properties": {
                    "epoch_key": {"type": "string"},
                    "display_name": {"type": "string"},
                    "kind": {"type": "string"},
                    "from_chapter_order": {"type": "integer"},
                    "to_chapter_order": {"type": "integer"},
                    "trigger": {"type": "string"},
                    "rationale": {"type": "string"},
                    "visual_en": {"type": "string"},
                    **{f: {"type": "string"} for f in CHAR_VARIANT},
                },
            },
        },
    },
}


def _system(cap_chapters: int, total: int) -> str:
    """cap_chapters 与 total 分开：配角按 1 章封顶（只给一期），
    但区间描述仍然按全书 total 章说 —— 否则模型会以为这本书只有一章。"""
    cap = max_epochs(cap_chapters)
    inv = "\n".join(f"    {f}（{_FIELD_CN.get(f, f)}）" for f in CHAR_INVARIANT)
    var = "\n".join(f"    {f}（{_FIELD_CN.get(f, f)}）" for f in CHAR_VARIANT)
    kinds = "、".join(k.value for k in EpochKind)
    return f"""你要为一个角色划出**时期** —— 全书 {total} 章里，他在哪几章是什么样子。

## 最要紧的一条：不变的部分只写一次

    invariant（只在最外层写一次，各期不要重复）
{inv}

    每一期各自写（这些才是会变的）
{var}

**不要在每一期重新描述长相。** 每重写一次，「浓眉」就会变成「剑眉」，
「左颊一道旧疤」就会变成「脸上有疤」—— 三期下来就是三个人，
而观众会立刻看出这不是同一个演员。
不变项在最外层写一次，各期逐字复用。

## 什么**不是**时期

时期是**长时段的形态**：少年／壮年，布衣／捕快，断臂前／断臂后。
下面这些都不是时期，它们属于单个镜头，不要为它们分期：

  ✗ 头发乱了、出了汗、衣服破了口子、刀出了鞘、脸上沾了血
  ✗ 这一刻紧张／警惕／愤怒 —— 那是表情，不是形态
  ✗ 情节推进到了下一个场面 —— 场面变了不等于人变了

判断标准很简单：**洗把脸、换身干净衣服就能恢复的，都不是时期。**

## 分期按事件，不按章数

不是把章节平均切开，而是看**什么事件让他变了**：
拜师、出师、受伤、得了新兵器、身份转变、大病、丧亲。
trigger 写清是哪件事，且必须是原文里真发生过的 ——
它既是分界依据，也是审核时判断「这里该不该换形态」的凭据。

kind 从这些里选：{kinds}

## 区间

from_chapter_order / to_chapter_order 按章节序号，闭区间。
**必须铺满 1 到 {total} 章，不许有缺口，不许重叠。**
缺口那几章取不到素材，会回落成全书一个样。
最后一期的 to_chapter_order 留空表示延续到全书结束。

**这本书最多给 {cap} 期。**（全书 {total} 章，一期至少要跨两章 ——
一章一期是逐章重画，而重画出来的每一章都会长得不太一样。）

如果这个角色全书就没怎么变（配角、只出场几章），
就只给一期，覆盖全书 —— 一期是完全合格的答案，
硬分成三期反而会让他每次出场都长得不一样。

## 不合格的写法

  ✗ 每期都写一遍「浓眉大眼、身形挺拔」—— 那是不变项，写在外层
  ✗ trigger 写「随着时间推移」「情节发展」—— 那不是事件
  ✗ 「少年（1–10 章）」「中年（15–30 章）」—— 11–14 章空着
  ✗ 衣着写「朴素的衣服」—— 出图时等于没说，要写料子、颜色、形制
  ✗ 给每个人都安一道「左颊刀疤」—— 那是类型套话。
     实跑时六个角色里有四个是它，于是这道疤不再指向任何人。
     **原文没写疤就不要写疤**，scars 留空是完全合格的答案
  ✗ 「腰刀一把，刀鞘为黑色牛皮，刀柄包铜，未出鞘时仅露刀把；随身携带
     一根铁质镖旗杆（可作短棍使用）」—— **这是档案不是提示词**

## 两份产出：中文给人看，英文给图像模型

**两组都要填，而且各写各的语言。** 只给一种的话，
要么人审不了（全英文），要么出不了图（全中文）。
实跑时一次要两种语言，模型把中文那组也写成了英文 —— 不要那样。

    中文那组（face_shape / hair / garments …）：用中文写，给人审核
    英文那组（invariant_en / visual_en）：用英文写，给图像模型

同一件事写两遍不是浪费：中文那遍决定人要不要改，英文那遍决定画出来什么。

中文那几项是**审核用的**，人要能一眼看懂并改。
但图像模型不认中文 —— 实跑时把中文描述直接喂给 SDXL，
出来的是一整版汉字纹样，一张脸都没有。

所以还要写英文：

    sex            male／female／child 三选一。**必填** ——
                   不写的话图像模型自己挑，而它挑的多半是女性，
                   男角色会得到一张女人的脸
    invariant_en   不变项的英文，**一句，写一次，各期共用**。
                   只写脸与体格，不写衣着兵器 —— 它要用来生成
                   一张跨期共用的素颜头肩参考图，带上衣着就会渗进后面每一期。
                   例：square face with high cheekbones, thick brows,
                       narrow dark-brown eyes, weathered tan skin, sturdy build
    visual_en      **这一期**的英文，只写这一期特有的：年龄、发型、
                   衣着、随身器物、气质、状态。不要重复 invariant_en 的内容。

                   **第一段必须是年龄，且要用图像模型认得的说法** ——
                   脸参考图从这里取年龄，而没有年龄的头肩像，
                   模型一律画成三十岁上下。
                     ✓ elderly man in his sixties, deeply lined face, ...
                     ✓ young man in his early twenties, smooth face, ...
                     ✗ late 50s to early 60s —— 数字区间它读不出年纪，
                       实跑时六十岁的角色画出来像四十岁
                   例：man in his early thirties, hair in a low bun,
                       dark grey padded escort coat, black-sheathed sabre at the hip

英文写成逗号分隔的短语，不要写句子，不要写「the man is...」。
人物的族裔与年代按目标圈层写（帝俄晚期就是 late 19th century Russian），
不要写成原文文化的样子。

## 每一项写成一个短语，不超过 20 字

这些字要拼进出图提示词。三个人同框时，每人三百字的详述会把
「谁在做什么」挤出模型的注意力，而「内装火折子和干粮」
在画面里根本看不见。

  ✓ 衣着：深灰棉布镖袍，袖口磨损
  ✓ 随身：黑鞘铜柄腰刀
  ✓ 气质：步伐稳健，话少

只写**看得见**的：料子、颜色、形制、位置。看不见的（里面装了什么、
以前谁给的、可以拿来做什么）一概不要。"""


@dataclass
class MineResult:
    entities: int = 0
    epochs: int = 0
    skipped_minor: list[str] = field(default_factory=list)
    skipped_locked: int = 0
    rule_fixes: list[dict[str, Any]] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "entities": self.entities, "epochs": self.epochs,
            "skipped_minor": self.skipped_minor,
            "skipped_locked": self.skipped_locked,
            "rule_fixes": self.rule_fixes, "failed": self.failed,
        }


def _chapter_digest(chapters: list[Chapter], name: str,
                    aliases: list[str], per_chapter: int = 700) -> str:
    """按章给出这个人出现的片段。

    不给全文 —— 全书塞进一次调用会撞上下文上限，而且模型会开始平均用力。
    只截取提到这个名字的段落，是**为了让每一章的证据都挤得进来**：
    分期靠的是「哪一章他变了」，缺了哪一章就分不出那一期。
    """
    keys = [k for k in [name, *aliases] if k]
    out: list[str] = []
    for ch in chapters:
        text = ch.content or ""
        hits: list[str] = []
        for para in text.split("\n"):
            if any(k in para for k in keys):
                hits.append(para.strip())
            if sum(len(h) for h in hits) > per_chapter:
                break
        if hits:
            body = "".join(hits)[:per_chapter]
            out.append(f"【第 {ch.order_no} 章 {ch.title or ''}】{body}")
    return "\n".join(out)


#: 年龄短语的样子。两类都要认：
#:   带年龄段词的  elderly man in his sixties／middle-aged／young woman
#:   带年岁的      in his early twenties／a boy of about twelve／45 years old
_AGE_WORD = (r"young|old|elderly|middle[\s-]?aged|aged|teenage|adolescent|"
             r"twenties|thirties|forties|fifties|sixties|seventies|eighties|"
             r"\d{1,2}s\b|\d{1,2}\s*(?:years?\s*old|yo)\b|"
             r"boy|girl|child|infant|toddler")
_AGE_EN = re.compile(rf"(?:^|\b)(?:{_AGE_WORD})", re.I)


def _age_en(item: dict[str, Any]) -> str:
    """取这一期的英文年龄。

    正路是 visual_en 的第一段 —— 提示词里要求它写在那里，模型也照做了。
    age_en 是可选的额外字段：**它在 required 里，模型却始终不返回**，
    所以不能把它当主路。跟模型较劲不如建在它可靠做到的那件事上。

    没有年龄的头肩像，模型一律画成三十岁上下，
    于是六十岁的老周和二十岁的裴无咎看着同龄。
    """
    direct = as_text(item.get("age_en")).strip()
    if direct:
        return direct[:48]
    head = as_text(item.get("visual_en")).split(",")[0].strip()
    return head[:48] if head and _AGE_EN.search(head) else ""


def _to_draft(item: dict[str, Any], invariant: dict[str, str]) -> EpochDraft:
    key = as_text(item.get("epoch_key")).strip() or new_id("ep")[-6:]
    try:
        frm = int(item.get("from_chapter_order") or 1)
    except (TypeError, ValueError):
        frm = 1
    to_raw = item.get("to_chapter_order")
    try:
        to = int(to_raw) if to_raw not in (None, "", 0) else None
    except (TypeError, ValueError):
        to = None
    kind = as_text(item.get("kind")).strip()
    if kind not in {k.value for k in EpochKind}:
        kind = "age"
    return EpochDraft(
        epoch_key=key[:64],
        display_name=as_text(item.get("display_name")).strip()[:128] or key,
        kind=kind, from_chapter_order=frm, to_chapter_order=to,
        trigger=as_text(item.get("trigger")).strip()[:500],
        invariant=dict(invariant),
        variant={f: as_text(item.get(f)).strip() for f in CHAR_VARIANT
                 if as_text(item.get(f)).strip()}
        | ({EN_KEY: as_text(item.get("visual_en")).strip()}
           if as_text(item.get("visual_en")).strip() else {})
        | ({AGE_EN_KEY: _age_en(item)} if _age_en(item) else {}),
        rationale=as_text(item.get("rationale")).strip()[:500],
    )


def mine_entity_epochs(
    db: Session, novel_id: str, profile: WorldProfile, *,
    entity_ids: list[str] | None = None, force: bool = False,
) -> MineResult:
    """给主要角色划时期。"""
    chapters = list(db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id)
        .order_by(Chapter.order_no)
    ).scalars())
    if not chapters:
        raise PipelineError("这本书还没有章节")
    total = chapters[-1].order_no

    q = select(WorldEntity).where(
        WorldEntity.novel_id == novel_id,
        WorldEntity.kind == EntityKind.character,
    )
    if entity_ids:
        q = q.where(WorldEntity.id.in_(entity_ids))
    ents = list(db.execute(q).scalars())
    if not ents:
        raise PipelineError("这本书还没有人物实体，先跑一次实体抽取")
    # 出场多的先抽 —— 先定的成为后定的约束，而主角的记号最该先定死。
    # 与配音同一套办法：可辨识是角色之间的关系，一次一个保证不了
    ents.sort(key=lambda e: (-len(e.appear_chapters_json or []), e.display_name))

    existing = {
        (e.subject_key, e.epoch_key): e for e in db.execute(
            select(AssetEpoch).where(
                AssetEpoch.world_profile_id == profile.id,
                AssetEpoch.subject_key.in_([e.id for e in ents]),
            )
        ).scalars()
    }
    visuals = {
        v.entity_id: v for v in db.execute(
            select(EntityWorldVisual).where(
                EntityWorldVisual.world_profile_id == profile.id,
                EntityWorldVisual.entity_id.in_([e.id for e in ents]),
            )
        ).scalars()
    }

    result = MineResult()
    #: 已被占用的辨识记号，作为后续角色的约束
    taken_marks: dict[str, dict[str, str]] = {}
    weights = {e.display_name: len(e.appear_chapters_json or []) for e in ents}
    for ent in ents:
        appear = list(ent.appear_chapters_json or [])
        locked = [r for (k, _), r in existing.items()
                  if k == ent.id and (r.locked or r.status is ReviewStatus.locked)]
        if locked and not force:
            result.skipped_locked += len(locked)
            continue
        if not force and any(k == ent.id for k, _ in existing):
            continue

        minor = bool(appear) and len(appear) < MIN_CHAPTERS_FOR_EPOCHS
        digest = _chapter_digest(chapters, ent.display_name,
                                 [str(a) for a in (ent.aliases_json or [])])
        if not digest.strip():
            result.failed.append(f"{ent.display_name}：原文里找不到他的段落")
            continue
        known = []
        if ent.appearance:
            known.append(f"【原文的外貌描写】{ent.appearance}")
        vis = visuals.get(ent.id)
        if vis is not None and vis.visual_prompt:
            known.append(f"【已定的目标圈层形象】{vis.visual_prompt}")
        axes = profile.axes_json or {}
        # 配角封顶一期：他不需要的是分期，不是不变项
        cap_chapters = 1 if minor else total
        user = (
            f"【角色】{ent.display_name}"
            + (f"（{ent.summary}）" if ent.summary else "")
            + f"\n【目标圈层】{profile.display_name}"
              f"（{axes.get('era_span') or ''} {axes.get('social_context') or ''}）"
            + (f"\n【注意】这个角色全书只出场 {len(appear)} 章，只给一期，"
               f"覆盖全书。但不变项照样要写全 —— 他也要出现在画面里，"
               f"而没有不变项就锁不住他的脸。" if minor else "")
            + ("\n" + "\n".join(known) if known else "")
            + (("\n【已被其他角色占用的辨识特征，不要重复】\n"
                + "\n".join(f"  {n}：{'；'.join(v.values())}"
                             for n, v in taken_marks.items() if v))
               if any(taken_marks.values()) else "")
            + f"\n\n【他在各章出现的段落】\n{digest}"
        )
        try:
            data, _task = chat_json(
                db,
                [{"role": "system", "content": _system(cap_chapters, total)},
                 {"role": "user", "content": user}],
                EPOCH_SCHEMA, purpose="asset_variant", novel_id=novel_id,
                ref_kind="entity_epoch", ref_id=ent.id, max_tokens=12288,
            )
        except PipelineError as exc:
            result.failed.append(f"{ent.display_name}：{exc}")
            continue

        raw_inv = data.get("invariant")
        invariant = {
            f: as_text(raw_inv.get(f)).strip()
            for f in CHAR_INVARIANT
            if isinstance(raw_inv, dict) and as_text(raw_inv.get(f)).strip()
        }
        # 英文不变项与中文一样是跨期恒定的锚，存在同一个 dict 里，
        # 于是 enforce_invariant 的「以第一期为准」自动覆盖它
        inv_en = as_text(data.get("invariant_en")).strip()
        if inv_en:
            invariant[EN_KEY] = inv_en
        items = as_items(data, "epochs")
        if not items:
            result.failed.append(f"{ent.display_name}：模型没有给出任何时期")
            continue
        drafts = [_to_draft(it, invariant) for it in items]
        drafts, notes = apply_rules(
            drafts, fields=CHAR_INVARIANT, total_chapters=cap_chapters)
        if minor:
            # 封顶用的是 1，区间却要覆盖真实的全书章数
            drafts[0].from_chapter_order = 1
            drafts[0].to_chapter_order = None
            result.skipped_minor.append(ent.display_name)

        # 记号占位：先抽的先占，后抽的看得见
        taken_marks[ent.display_name] = {
            f: normalize_mark(invariant.get(f, "")) for f in DISTINCTIVE
            if normalize_mark(invariant.get(f, ""))
        }
        for note in notes:
            note["entity"] = ent.display_name
        result.rule_fixes.extend(notes)

        # 重跑时把这次没给出的旧时期删掉。留着会与新划分重叠 ——
        # 上次三期这次两期，第三期还杵在那里，那几章就取到了两期，
        # 取哪一期看排序，两次跑可能不一样
        keep = {d.epoch_key for d in drafts}
        for (skey, ekey), row in list(existing.items()):
            if skey != ent.id or ekey in keep:
                continue
            if row.locked or row.status is ReviewStatus.locked:
                result.skipped_locked += 1
                continue
            db.delete(row)
            existing.pop((skey, ekey))
            result.rule_fixes.append({
                "type": "stale_epoch_removed", "entity": ent.display_name,
                "epoch": ekey,
                "detail": f"上次划分里的「{row.display_name}」这次没有了，"
                          f"留着会与新划分重叠",
            })

        for order_no, d in enumerate(drafts):
            row = existing.get((ent.id, d.epoch_key))
            if row is not None and (row.locked
                                    or row.status is ReviewStatus.locked):
                continue
            if row is None:
                row = AssetEpoch(
                    id=new_id("ae"), subject_key=ent.id, entity_id=ent.id,
                    asset_spec_id=None, world_profile_id=profile.id,
                    epoch_key=d.epoch_key,
                )
                db.add(row)
                existing[(ent.id, d.epoch_key)] = row
            row.display_name = d.display_name
            row.kind = EpochKind(d.kind)
            row.order_no = order_no
            row.from_chapter_order = d.from_chapter_order
            row.to_chapter_order = d.to_chapter_order
            row.trigger = d.trigger or None
            row.invariant_json = d.invariant or None
            row.variant_json = d.variant or None
            # 英文提示词落到 visual_prompt —— 出图读的是它。
            # 不变项在前、这一期在后，与中文那条同一个顺序理由：
            # 图像模型对前面的词更敏感，同一性锚点要排在衣着道具之前
            # 年龄不在这里单独拼 —— 它本来就是 visual_en 的第一段，
            # 再拼一次就成了「…178cm tall, man in his mid-twenties, hair…」。
            # AGE_EN_KEY 只服务锚图：那里没有 visual_en 可取
            en = ", ".join(x for x in (d.invariant.get(EN_KEY),
                                       d.variant.get(EN_KEY)) if x)
            row.visual_prompt = en or None
            row.rationale = d.rationale or None
            row.status = ReviewStatus.candidate
            # 脸参考跨期共用 —— 换了参考图，脸就跟着漂
            vis = visuals.get(ent.id)
            anchor = (vis.ref_asset_ids or [None])[0] if vis else None
            row.identity_ref_asset_id = anchor or row.identity_ref_asset_id
            result.epochs += 1
        result.entities += 1

    # 规则兜底：模型看过「已占用的记号」仍可能撞（类型套话的引力很强），
    # 这里按重要度让路。清掉而不是另编一个 ——
    # 换一个是凭空发明原文没有的特征，那会变成一个假的辨识依据
    names = {e.display_name: e.id for e in ents}
    rows_of: dict[str, list] = {}
    for (skey, _k), row in existing.items():
        rows_of.setdefault(skey, []).append(row)
    # 每个角色取一份代表性的不变项 —— enforce_invariant 之后各期本就一致
    invariants = {
        name: dict(rows_of[eid][0].invariant_json or {})
        for name, eid in names.items() if rows_of.get(eid)
    }
    result.rule_fixes.extend(resolve_shared_marks(invariants, weights))
    # 抹平后的不变项写回该角色的每一期 —— 不变项跨期必须逐字一致
    for name, inv in invariants.items():
        for row in rows_of.get(names[name], []):
            if row.locked:
                continue
            merged = dict(row.invariant_json or {})
            for f in DISTINCTIVE:
                if f in inv:
                    merged[f] = inv[f]
                else:
                    merged.pop(f, None)
            row.invariant_json = merged or None

    db.flush()
    return result
