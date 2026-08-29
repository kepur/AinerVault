"""时期的规则层 —— 让「三个时期不会变成三个人」成为可判定的。

时期划分表面上是个自由创作题：从哪一章开始算中年，谁说了算。
但它有三条完全形式化的约束，而这三条恰好覆盖了它最常出的错：

    覆盖       区间必须铺满全书且不重叠 —— 有缺口的章节取不到素材，
               有重叠的章节取到哪一期看排序，两次跑可能不一样
    同一性     跨期 invariant 必须逐字一致 —— 这是脸不漂的全部依据
    分界依据   除基准期外必须写明触发事件 —— 没有触发事件的分期
               无法复核，人看不出「这里该不该换形态」

模型对这三条的遵守率并不高：它会给出「少年（1-10 章）」「中年（15-30 章）」
这样中间空着五章的划分，也会在每一期重新描述一遍长相。
所以判据既写进提示词（让它一次做对），也在这里做覆写（做不对时兜住）。

## 为什么 invariant 是覆写而不是报错

报错的话，一次划分里有一处描述漂了，整个划分就作废重跑 ——
而重跑出来的多半是另一处漂。以第一期为准直接抹平，
是唯一能收敛的做法：**同一性的锚必须只有一个来源。**
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

#: 分期最少要跨多少章。一章一期不是分期，是逐章重画 ——
#: 那样每章的描述都会漂一点，而分期本来就是为了不漂。
MIN_SPAN = 2


def max_epochs(total_chapters: int) -> int:
    """这本书最多分几期。

    实跑时模型把三章的短篇给沈砚分了三期，每期一章，
    差别是「发辫略显凌乱」→「发辫散乱」、「刀已出鞘，刀身微见血迹」——
    那不是时期，是**镜头里的一时状态**。留着的后果是他每章被重画一次，
    而分期存在的全部意义就是不要那样。

    按章数封顶是这件事唯一能形式化的部分：三章的书分不出两个形态，
    再怎么讲道理模型也会按情节节拍去切。
    """
    return max(1, total_chapters // MIN_SPAN)


@dataclass
class EpochDraft:
    """一期的草案。落库前的形态，规则在这一层生效。"""

    epoch_key: str
    display_name: str
    kind: str = "age"
    from_chapter_order: int = 1
    to_chapter_order: int | None = None
    trigger: str = ""
    invariant: dict[str, Any] = field(default_factory=dict)
    variant: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "epoch_key": self.epoch_key, "display_name": self.display_name,
            "kind": self.kind, "from_chapter_order": self.from_chapter_order,
            "to_chapter_order": self.to_chapter_order, "trigger": self.trigger,
            "invariant": self.invariant, "variant": self.variant,
            "rationale": self.rationale,
        }


def sort_epochs(drafts: Sequence[EpochDraft]) -> list[EpochDraft]:
    """按起始章排。同起点时短的在前 —— 「断臂之后」应该压过「中年」，
    而排序决定了 order_no，order_no 决定重叠时谁生效。"""
    return sorted(drafts, key=lambda d: (
        d.from_chapter_order,
        d.to_chapter_order if d.to_chapter_order is not None else 10 ** 6,
    ))


def fix_coverage(
    drafts: Sequence[EpochDraft], total_chapters: int,
) -> tuple[list[EpochDraft], list[dict[str, Any]]]:
    """把区间补成一条不断的链，并报告改了什么。

    模型给出的区间常有缺口（「少年 1–10」「中年 15–30」，11–14 空着）
    和越界（结束章超过全书）。缺口不能留：那几章取不到素材，
    出图时会回落到基准形态 —— 而基准形态是全书一个样，
    正是分期要解决的问题。

    补法是**把上一期延到下一期开始前**，而不是新造一期：
    新造一期等于凭空发明一个模型没说过的形态，
    延续则只是承认「这几章还没到下一个阶段」。
    """
    out = sort_epochs([d for d in drafts])
    fixes: list[dict[str, Any]] = []
    if not out:
        return out, fixes

    if out[0].from_chapter_order > 1:
        fixes.append({
            "type": "coverage_head", "epoch": out[0].epoch_key,
            "detail": f"第一期从第 {out[0].from_chapter_order} 章才开始，"
                      f"前面几章取不到素材，改为从第 1 章起",
        })
        out[0].from_chapter_order = 1

    for cur, nxt in zip(out, out[1:]):
        if nxt.from_chapter_order <= cur.from_chapter_order:
            nxt.from_chapter_order = cur.from_chapter_order + 1
            fixes.append({
                "type": "overlap_start", "epoch": nxt.epoch_key,
                "detail": f"「{nxt.display_name}」的起始章不晚于上一期，"
                          f"顺延到第 {nxt.from_chapter_order} 章",
            })
        want = nxt.from_chapter_order - 1
        if cur.to_chapter_order != want:
            old = cur.to_chapter_order
            cur.to_chapter_order = want
            fixes.append({
                "type": "gap" if (old or 0) < want else "overlap",
                "epoch": cur.epoch_key,
                "detail": f"「{cur.display_name}」结束于第 {old} 章、"
                          f"下一期从第 {nxt.from_chapter_order} 章起，"
                          f"{'中间几章取不到素材' if (old or 0) < want else '两期重叠'}"
                          f"，改为到第 {want} 章",
            })

    last = out[-1]
    if last.to_chapter_order is not None and last.to_chapter_order < total_chapters:
        fixes.append({
            "type": "coverage_tail", "epoch": last.epoch_key,
            "detail": f"最后一期结束于第 {last.to_chapter_order} 章、全书 "
                      f"{total_chapters} 章，改为延续到全书结束",
        })
    last.to_chapter_order = None      # 末期一律延续到全书结束
    return out, fixes


def cap_count(
    drafts: Sequence[EpochDraft], total_chapters: int,
) -> tuple[list[EpochDraft], list[dict[str, Any]]]:
    """超过上限就合并，从跨度最短的那一期开始。

    **合并而不是只报警。** 三个一章期留在库里，人物就是每章重画一次；
    报了警不改，等于把「明知是错的数据」交给下游。

    并进前一期而不是后一期：先出现的形态是读者锚定的那个，
    而被并掉的那期按定义短到不足以成为一个形态。
    """
    out = sort_epochs(list(drafts))
    cap = max_epochs(total_chapters)
    notes: list[dict[str, Any]] = []
    while len(out) > cap:
        spans = [
            ((d.to_chapter_order if d.to_chapter_order is not None
              else total_chapters) - d.from_chapter_order + 1, i)
            for i, d in enumerate(out)
        ]
        # 第一期不能被并掉 —— 它是锚；同长度时并靠后的
        _span, idx = min((s, i) for s, i in spans if i > 0)
        dropped = out.pop(idx)
        keeper = out[idx - 1]
        keeper.to_chapter_order = dropped.to_chapter_order
        notes.append({
            "type": "merged_pseudo_epoch", "epoch": dropped.epoch_key,
            "detail": f"全书 {total_chapters} 章最多分 {cap} 期，"
                      f"「{dropped.display_name}」并入「{keeper.display_name}」——"
                      f"它描述的是一时的状态（发乱、出汗、衣破），不是形态",
        })
    return out, notes


def enforce_invariant(
    drafts: Sequence[EpochDraft], fields: Sequence[str],
) -> list[dict[str, Any]]:
    """把跨期的不变项抹成同一份，以第一期为准。

    **同一性的锚必须只有一个来源。** 每期各写一遍长相，
    「浓眉、左颊一道旧疤」每写一次就会漂一点，三期下来就是三个人。

    以第一期为准而不是报错：报错的话一处漂就整份作废重跑，
    而重跑出来的多半是另一处漂 —— 那样永远收敛不了。
    """
    out: list[dict[str, Any]] = []
    if not drafts:
        return out
    anchor = drafts[0]
    for f in fields:
        base = str(anchor.invariant.get(f) or "").strip()
        for d in drafts[1:]:
            cur = str(d.invariant.get(f) or "").strip()
            if not base and cur:
                # 第一期没写、后面写了：补给第一期，别丢信息
                anchor.invariant[f] = cur
                base = cur
                out.append({
                    "type": "invariant_backfill", "epoch": anchor.epoch_key,
                    "field": f,
                    "detail": f"「{f}」只有「{d.display_name}」写了，补给基准期",
                })
                continue
            if cur and cur != base:
                out.append({
                    "type": "invariant_drift", "epoch": d.epoch_key, "field": f,
                    "detail": f"「{d.display_name}」把「{f}」写成了「{cur}」，"
                              f"与第一期的「{base}」不同 —— 不变项每重写一次就漂一点，"
                              f"已按第一期抹平",
                })
            if base:
                d.invariant[f] = base
            else:
                d.invariant.pop(f, None)
    return out


def check_triggers(drafts: Sequence[EpochDraft]) -> list[dict[str, Any]]:
    """除第一期外必须写明触发事件。

    不当场改 —— 触发事件是**内容**，编不出来。缺了就报出来让人补：
    没有触发事件的分期无法复核，审核的人看不出这里该不该换形态。
    """
    return [
        {"type": "missing_trigger", "epoch": d.epoch_key,
         "detail": f"「{d.display_name}」没写触发事件 —— "
                   f"分期的依据缺了，审核时看不出这里该不该换形态"}
        for d in drafts[1:] if not (d.trigger or "").strip()
    ]


def check_spans(drafts: Sequence[EpochDraft],
                total_chapters: int) -> list[dict[str, Any]]:
    """太短的分期报出来。

    一章一期不是分期，是逐章重画 —— 每章的描述都会漂一点，
    而分期本来就是为了不漂。真需要单章特写的（易容、重伤当场），
    人确认后放行即可，所以这里只报不改。

    **只有一期时不查。** 补完区间后它必然覆盖全书，
    而「一期覆盖全书」正是配角与固定物体的正确答案 ——
    对它报「分期过短」是把正确答案判成错的。
    """
    out = []
    if len(drafts) < 2:
        return out
    for d in drafts:
        end = d.to_chapter_order if d.to_chapter_order is not None else total_chapters
        span = end - d.from_chapter_order + 1
        if span < MIN_SPAN:
            out.append({
                "type": "short_span", "epoch": d.epoch_key,
                "detail": f"「{d.display_name}」只覆盖 {span} 章 —— "
                          f"一章一期是逐章重画，不是分期",
            })
    return out


#: 只查疤痕胎记这一项。
#:
#: 一开始还查了 features／face_shape／eye_color，实跑立刻误报：
#: 「颧骨略高，眉骨凸起，鼻梁挺直」与「浓眉，双眼皮，鼻梁略宽」
#: 是两张明显不同的脸，只因为都提到鼻梁就被判成撞了。
#: 那是我把为**疤痕**（有位置的离散记号）设计的比较法，
#: 套到了整段外貌描述上 —— 后者要比出异同得靠语义，不是形式判定。
#:
#: 抓不到目标错误的检查比没有更糟，误报的检查同样：
#: 报三条假的，人就不看第四条真的了。
#: 疤痕是这里唯一能形式化的：它有位置、有类型，都是短而封闭的取值。
DISTINCTIVE = ("scars",)


def check_shared_marks(
    invariants: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """两个角色的辨识特征撞了。

    实跑时沈砚是「左颊一道细长旧疤」，老周是「左颊一道竖直旧疤」——
    两个人靠同一个记号被认出，等于都没有记号。
    这是撞声的视觉版：单看每个人的描述都合格，放到一起才露馅，
    而它同样是可判定的 —— 疤痕、瞳色、脸型都是有限的短描述，能两两比。

    比的是**关键词而不是整句**：「左颊一道细长旧疤」与
    「左颊一道竖直旧疤」逐字不同，可观众看到的是同一道疤。
    """
    out: list[dict[str, Any]] = []
    keys = sorted(invariants)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            for f in DISTINCTIVE:
                va = str(invariants[a].get(f) or "").strip()
                vb = str(invariants[b].get(f) or "").strip()
                if not va or not vb:
                    continue
                if _same_mark(va, vb):
                    out.append({
                        "type": "shared_mark", "left": a, "right": b,
                        "field": f,
                        "detail": f"{a} 与 {b} 的「{f}」是同一个记号"
                                  f"（「{va}」／「{vb}」）—— "
                                  f"两个人靠同一处特征被认出，等于都没有特征",
                    })
    return out


#: 记号长在哪。位置是辨识的主要依据 —— 左颊的疤与右颊的疤是两个人。
_MARK_PLACES = ("左颊", "右颊", "额", "眉", "下颌", "鼻梁", "鼻", "唇", "颈",
                "眼角", "耳", "手背", "腕")
#: 是什么记号。
_MARK_KINDS = ("疤", "痣", "胎记", "缺", "断", "纹")


def _same_mark(a: str, b: str) -> bool:
    """两处描述说的是不是同一个记号。

    比**位置与记号类型各自相交**，不比整句、也不比集合相等：
      整句相同几乎不会发生，比了等于不查；
      集合相等又太严 ——「左颊一道细长旧疤，从鬓角斜至下颌」里的下颌
      是疤的走向，不是第二处记号，硬要求集合一致就漏掉了它。

    两边都认不出位置时判为不同：认不出就无从比较，
    此时报出来只是噪声。
    """
    pa = {t for t in _MARK_PLACES if t in a}
    pb = {t for t in _MARK_PLACES if t in b}
    if not pa or not pb:
        return a.strip() == b.strip()
    if not (pa & pb):
        return False
    ka = {t for t in _MARK_KINDS if t in a}
    kb = {t for t in _MARK_KINDS if t in b}
    if not ka or not kb:
        return True          # 同一位置、都没说是什么记号，仍算撞
    return bool(ka & kb)


#: 「没有疤」的各种写法。落成字面值会变成噪声：
#: 它进提示词是「无」，进撞记号检测是一个所有人共有的「记号」。
_NEGATIVE_MARK = ("无", "没有", "未见", "无明显", "无特殊", "没有明显", "－", "-", "—")


def normalize_mark(value: str) -> str:
    """把「无」「没有明显疤痕」这类否定写法归为空。"""
    v = str(value or "").strip()
    if not v:
        return ""
    if v in _NEGATIVE_MARK or any(v.startswith(n) and len(v) <= len(n) + 4
                                  for n in _NEGATIVE_MARK):
        return ""
    return v


def resolve_shared_marks(
    invariants: dict[str, dict[str, Any]], weights: dict[str, int],
) -> list[dict[str, Any]]:
    """撞了的记号，次要角色让路 —— 清掉，不另编一个。

    **清掉而不是换一个。** 换一个是凭空发明原文没有的特征，
    而那会变成一个假的辨识依据，比没有更糟：
    观众记住了一道书里没有的疤。

    清掉是安全的：没有记号只是少一条线索，而共有的记号是**误导** ——
    四个人都是「左颊一道细长旧疤」时，这道疤不再指向任何人。
    （实跑时六个角色里有四个是它 —— 武侠的类型套话。）

    谁让路按台词量／出场章数：主角的疤是观众记得最牢的那个。
    """
    fixes: list[dict[str, Any]] = []
    for f in DISTINCTIVE:
        # 重要度高的先占位
        order = sorted(invariants, key=lambda k: (-weights.get(k, 0), k))
        taken: list[tuple[str, str]] = []
        for name in order:
            val = normalize_mark(invariants[name].get(f, ""))
            if not val:
                invariants[name].pop(f, None)
                continue
            hit = next((o for o, v in taken if _same_mark(v, val)), None)
            if hit is None:
                taken.append((name, val))
                invariants[name][f] = val
                continue
            invariants[name].pop(f, None)
            fixes.append({
                "type": "shared_mark_cleared", "entity": name, "field": f,
                "against": hit,
                "detail": f"{name} 的「{f}」（{val}）与 {hit} 是同一个记号，"
                          f"已清空 —— 共有的记号不再指向任何人，"
                          f"而另编一个是凭空发明原文没有的特征",
            })
    return fixes


def apply_rules(
    drafts: Sequence[EpochDraft], *, fields: Sequence[str], total_chapters: int,
) -> tuple[list[EpochDraft], list[dict[str, Any]]]:
    """三条规则一起过。返回修正后的时期与全部改动／告警。

    顺序有讲究：先封顶、再补区间、最后抹不变项。
    封顶会删掉整期，补区间要在删完之后才接得上；
    而「以第一期为准」依赖的正是排完序、接好区间之后的第一期。
    """
    capped, notes = cap_count(drafts, total_chapters)
    fixed, more = fix_coverage(capped, total_chapters)
    notes += more
    notes += enforce_invariant(fixed, fields)
    notes += check_triggers(fixed)
    notes += check_spans(fixed, total_chapters)
    return fixed, notes
