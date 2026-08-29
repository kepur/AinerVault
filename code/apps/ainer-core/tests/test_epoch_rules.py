"""人物时期的规则层。

分期表面上是个自由创作题，实际有三条完全形式化的约束，
而这三条恰好覆盖了它最常出的错：区间有缺口、不变项每期重写、
分界没有依据。
"""
from __future__ import annotations

from app.worldview.epoch_rules import (
    EpochDraft, apply_rules, check_spans, check_triggers, enforce_invariant,
    fix_coverage, sort_epochs,
)


def d(key, frm, to=None, *, name=None, kind="age", trigger="拜师",
      inv=None, var=None) -> EpochDraft:
    return EpochDraft(
        epoch_key=key, display_name=name or key, kind=kind,
        from_chapter_order=frm, to_chapter_order=to, trigger=trigger,
        invariant=dict(inv or {}), variant=dict(var or {}),
    )


class TestCoverage:
    def test_gap_is_closed_by_extending_the_earlier_epoch(self):
        """「少年 1–10」「中年 15–30」中间空着 11–14。

        补法是把上一期延到下一期开始前，而不是新造一期 ——
        新造等于凭空发明一个模型没说过的形态。
        """
        fixed, notes = fix_coverage([d("youth", 1, 10), d("mid", 15, 30)], 30)
        assert fixed[0].to_chapter_order == 14
        assert any(n["type"] == "gap" for n in notes)

    def test_overlap_is_trimmed(self):
        fixed, notes = fix_coverage([d("a", 1, 20), d("b", 10, 30)], 30)
        assert fixed[0].to_chapter_order == 9
        assert any(n["type"] == "overlap" for n in notes)

    def test_head_is_pulled_back_to_chapter_one(self):
        """前面几章取不到素材，会回落成全书一个样。"""
        fixed, notes = fix_coverage([d("a", 5, 20)], 20)
        assert fixed[0].from_chapter_order == 1
        assert any(n["type"] == "coverage_head" for n in notes)

    def test_last_epoch_always_runs_to_the_end(self):
        fixed, notes = fix_coverage([d("a", 1, 10), d("b", 11, 25)], 40)
        assert fixed[-1].to_chapter_order is None
        assert any(n["type"] == "coverage_tail" for n in notes)

    def test_identical_starts_are_pushed_apart(self):
        """两期同一章开始，取哪一期看排序 —— 两次跑可能不一样。"""
        fixed, _ = fix_coverage([d("a", 5), d("b", 5)], 20)
        assert fixed[0].from_chapter_order < fixed[1].from_chapter_order

    def test_result_is_a_contiguous_chain(self):
        fixed, _ = fix_coverage(
            [d("a", 1, 8), d("c", 20, 25), d("b", 12, 15)], 30)
        ends = [e.to_chapter_order for e in fixed]
        starts = [e.from_chapter_order for e in fixed]
        for end, nxt in zip(ends, starts[1:]):
            assert end + 1 == nxt
        assert starts[0] == 1 and ends[-1] is None

    def test_empty_input_is_not_a_crash(self):
        assert fix_coverage([], 10) == ([], [])


class TestInvariant:
    def test_drift_is_flattened_to_the_first_epoch(self):
        """「浓眉」会变成「剑眉」，三期下来就是三个人。"""
        drafts = [d("a", 1, 10, inv={"features": "浓眉，鼻梁高挺"}),
                  d("b", 11, 20, inv={"features": "剑眉星目"})]
        notes = enforce_invariant(drafts, ("features",))
        assert drafts[1].invariant["features"] == "浓眉，鼻梁高挺"
        assert any(n["type"] == "invariant_drift" for n in notes)

    def test_flatten_not_reject(self):
        """报错的话一处漂就整份作废重跑，而重跑出来的多半是另一处漂。"""
        drafts = [d("a", 1, 10, inv={"scars": "左颊一道旧疤"}),
                  d("b", 11, 20, inv={"scars": "脸上有疤"})]
        enforce_invariant(drafts, ("scars",))
        assert len({x.invariant["scars"] for x in drafts}) == 1

    def test_later_value_backfills_an_empty_first(self):
        """第一期没写、后面写了：补给第一期，别丢信息。"""
        drafts = [d("a", 1, 10, inv={}),
                  d("b", 11, 20, inv={"eye_color": "琥珀色"})]
        notes = enforce_invariant(drafts, ("eye_color",))
        assert drafts[0].invariant["eye_color"] == "琥珀色"
        assert any(n["type"] == "invariant_backfill" for n in notes)

    def test_field_absent_everywhere_stays_absent(self):
        drafts = [d("a", 1, 10), d("b", 11, 20)]
        assert enforce_invariant(drafts, ("scars",)) == []
        assert "scars" not in drafts[1].invariant

    def test_variant_fields_are_untouched(self):
        """衣着本来就该每期不同 —— 抹平它就抹掉了分期的意义。"""
        drafts = [d("a", 1, 10, var={"garments": "粗布短打"}),
                  d("b", 11, 20, var={"garments": "玄色劲装"})]
        enforce_invariant(drafts, ("features",))
        assert drafts[0].variant["garments"] != drafts[1].variant["garments"]


class TestTriggers:
    def test_first_epoch_needs_no_trigger(self):
        assert check_triggers([d("a", 1, 10, trigger="")]) == []

    def test_later_epoch_without_a_trigger_is_reported(self):
        """没有触发事件的分期无法复核 ——
        审核的人看不出这里该不该换形态。"""
        out = check_triggers([d("a", 1, 10), d("b", 11, 20, trigger="")])
        assert len(out) == 1 and out[0]["type"] == "missing_trigger"

    def test_trigger_is_reported_not_invented(self):
        """触发事件是内容，编不出来 —— 只报不改。"""
        drafts = [d("a", 1, 10), d("b", 11, 20, trigger="")]
        check_triggers(drafts)
        assert drafts[1].trigger == ""


class TestSpans:
    def test_single_chapter_epoch_is_flagged(self):
        """一章一期是逐章重画，不是分期。"""
        out = check_spans([d("a", 1, 1), d("b", 2, 20)], 20)
        assert len(out) == 1 and out[0]["type"] == "short_span"

    def test_open_ended_epoch_measures_to_the_book_end(self):
        assert check_spans([d("a", 1, None)], 30) == []

    def test_short_span_is_only_reported(self):
        """真需要单章特写的（易容、重伤当场），人确认后放行。"""
        drafts = [d("a", 1, 1), d("b", 2, 20)]
        check_spans(drafts, 20)
        assert drafts[0].to_chapter_order == 1


class TestApplyRules:
    def test_coverage_runs_before_invariant(self):
        """补区间会改排序，而「以第一期为准」依赖排完序之后的第一期。

        乱序输入下，锚必须是章节最靠前的那一期，不是列表里的第一个。
        """
        drafts = [d("late", 11, 20, inv={"features": "剑眉"}),
                  d("early", 1, 10, inv={"features": "浓眉"})]
        fixed, _notes = apply_rules(drafts, fields=("features",),
                                    total_chapters=20)
        assert all(x.invariant["features"] == "浓眉" for x in fixed)

    def test_returns_everything_that_changed(self):
        fixed, notes = apply_rules(
            [d("a", 3, 10, inv={"scars": "旧疤"}),
             d("b", 15, 20, trigger="", inv={"scars": "疤"})],
            fields=("scars",), total_chapters=25)
        kinds = {n["type"] for n in notes}
        assert "coverage_head" in kinds
        assert "gap" in kinds
        assert "invariant_drift" in kinds
        assert "missing_trigger" in kinds
        assert fixed[0].from_chapter_order == 1


def test_sort_puts_the_narrower_epoch_first_on_a_tie():
    """「断臂之后」应该压过「中年」—— 排序决定 order_no，
    order_no 决定重叠时谁生效。"""
    out = sort_epochs([d("mid", 10, 40), d("armless", 10, 12)])
    assert out[0].epoch_key == "armless"


class TestCapCount:
    """按章数封顶。

    实跑时模型把三章的短篇给沈砚分了三期，每期一章，差别是
    「发辫略显凌乱」→「发辫散乱」、「刀已出鞘，刀身微见血迹」——
    那不是时期，是镜头里的一时状态。留着的后果是他每章被重画一次，
    而分期存在的全部意义就是不要那样。
    """

    def test_three_chapters_allow_only_one_epoch(self):
        from app.worldview.epoch_rules import cap_count, max_epochs
        assert max_epochs(3) == 1
        out, notes = cap_count(
            [d("a", 1, 1), d("b", 2, 2), d("c", 3, 3)], 3)
        assert len(out) == 1 and out[0].epoch_key == "a"
        assert len(notes) == 2

    def test_merged_epoch_absorbs_the_range(self):
        from app.worldview.epoch_rules import cap_count
        out, _ = cap_count([d("a", 1, 1), d("b", 2, 3)], 3)
        assert out[0].to_chapter_order == 3

    def test_the_first_epoch_is_never_merged_away(self):
        """先出现的形态是读者锚定的那个。"""
        from app.worldview.epoch_rules import cap_count
        out, _ = cap_count([d("first", 1, 1), d("second", 2, 20)], 4)
        assert out[0].epoch_key == "first"

    def test_a_long_book_is_left_alone(self):
        """封顶只在模型把短文本切碎时才该生效。"""
        from app.worldview.epoch_rules import cap_count
        drafts = [d("a", 1, 10), d("b", 11, 25), d("c", 26, 40)]
        out, notes = cap_count(drafts, 40)
        assert len(out) == 3 and notes == []

    def test_merge_happens_before_coverage_is_repaired(self):
        """封顶会删掉整期，补区间要在删完之后才接得上。"""
        fixed, notes = apply_rules(
            [d("a", 1, 1), d("b", 2, 2), d("c", 3, 3)],
            fields=("features",), total_chapters=3)
        assert len(fixed) == 1
        assert fixed[0].from_chapter_order == 1
        assert fixed[0].to_chapter_order is None
        assert any(n["type"] == "merged_pseudo_epoch" for n in notes)


class TestSharedMarks:
    """辨识特征撞了 —— 撞声的视觉版。

    实跑时沈砚是「左颊一道细长旧疤」，老周是「左颊一道竖直旧疤」。
    两个人靠同一个记号被认出，等于都没有记号。
    """

    def test_same_scar_in_different_words_is_caught(self):
        from app.worldview.epoch_rules import check_shared_marks
        out = check_shared_marks({
            "沈砚": {"scars": "左颊一道细长旧疤，从鬓角斜至下颌"},
            "老周": {"scars": "左颊一道竖直旧疤，约两寸长"},
        })
        assert len(out) == 1 and out[0]["field"] == "scars"

    def test_different_locations_do_not_collide(self):
        from app.worldview.epoch_rules import check_shared_marks
        assert check_shared_marks({
            "甲": {"scars": "左颊一道旧疤"},
            "乙": {"scars": "右颊一道旧疤"},
        }) == []

    def test_missing_value_is_not_a_match(self):
        """一边没写不能算撞 —— 那会把缺项伪装成问题。"""
        from app.worldview.epoch_rules import check_shared_marks
        assert check_shared_marks({"甲": {"scars": "左颊旧疤"},
                                   "乙": {}}) == []

    def test_hair_and_clothes_are_not_distinctive(self):
        """发型衣着本来就该换，不参与辨识。"""
        from app.worldview.epoch_rules import DISTINCTIVE
        assert "hair" not in DISTINCTIVE and "garments" not in DISTINCTIVE


class TestSharedMarksScope:
    """只查疤痕。

    一开始还查了 features／face_shape，实跑立刻误报：
    「颧骨略高，眉骨凸起，鼻梁挺直」与「浓眉，双眼皮，鼻梁略宽」
    是两张明显不同的脸，只因为都提到鼻梁就被判成撞了。
    报三条假的，人就不看第四条真的了。
    """

    def test_two_different_faces_are_not_flagged(self):
        from app.worldview.epoch_rules import check_shared_marks
        assert check_shared_marks({
            "沈砚": {"features": "颧骨略高，眉骨凸起，鼻梁挺直，嘴角线条紧绷",
                     "face_shape": "方正的国字脸，下颌线硬朗",
                     "scars": "左侧颧骨下方一道浅疤"},
            "老周": {"features": "浓眉，双眼皮，鼻梁略宽，唇线分明",
                     "face_shape": "国字脸，颧骨略高，下颌方正",
                     "scars": "左颊一道竖直旧疤，从鬓角延伸至下颌"},
        }) == []

    def test_the_real_duplicate_scar_still_fires(self):
        from app.worldview.epoch_rules import check_shared_marks
        out = check_shared_marks({
            "沈砚": {"scars": "左颊一道细长旧疤，从鬓角斜至下颌"},
            "老周": {"scars": "左颊一道竖直旧疤，约两寸长"},
        })
        assert len(out) == 1


class TestSingleEpochIsNeverTooShort:
    """一期覆盖全书是配角与固定物体的正确答案。

    对它报「分期过短」是把正确答案判成错的 —— 而人会照着告警去改，
    把本来对的东西改坏。
    """

    def test_lone_epoch_is_not_flagged(self):
        assert check_spans([d("only", 1, None)], 1) == []
        assert check_spans([d("only", 1, 1)], 30) == []

    def test_two_short_epochs_are_still_flagged(self):
        assert len(check_spans([d("a", 1, 1), d("b", 2, 2)], 20)) == 2


class TestResolveSharedMarks:
    """撞了的记号让次要角色让路 —— 清掉，不另编一个。

    实跑时六个角色里有四个是「左颊一道细长旧疤」，武侠的类型套话。
    这道疤于是不再指向任何人。
    """

    def test_less_prominent_character_loses_the_mark(self):
        from app.worldview.epoch_rules import resolve_shared_marks
        inv = {"沈砚": {"scars": "左颊一道细长旧疤，从颧骨延伸至下颌"},
               "灰衣汉子": {"scars": "左颊一道细长旧疤"}}
        fixes = resolve_shared_marks(inv, {"沈砚": 3, "灰衣汉子": 2})
        assert "scars" in inv["沈砚"]
        assert "scars" not in inv["灰衣汉子"]
        assert fixes[0]["entity"] == "灰衣汉子"

    def test_nothing_is_invented(self):
        """换一个是凭空发明原文没有的特征，比没有更糟 ——
        观众会记住一道书里没有的疤。"""
        from app.worldview.epoch_rules import resolve_shared_marks
        inv = {"甲": {"scars": "左颊旧疤"}, "乙": {"scars": "左颊旧疤"}}
        resolve_shared_marks(inv, {"甲": 5, "乙": 1})
        assert inv["乙"].get("scars") in (None, "")

    def test_distinct_marks_survive(self):
        from app.worldview.epoch_rules import resolve_shared_marks
        inv = {"甲": {"scars": "左颊旧疤"}, "乙": {"scars": "右手背烫伤疤"}}
        assert resolve_shared_marks(inv, {"甲": 5, "乙": 1}) == []
        assert inv["乙"]["scars"] == "右手背烫伤疤"

    def test_negation_becomes_empty_not_a_shared_mark(self):
        """「无」落成字面值会变成一个所有人共有的「记号」。"""
        from app.worldview.epoch_rules import normalize_mark, resolve_shared_marks
        assert normalize_mark("无") == ""
        assert normalize_mark("无明显疤痕") == ""
        assert normalize_mark("左颊旧疤") == "左颊旧疤"
        inv = {"甲": {"scars": "无"}, "乙": {"scars": "没有明显疤痕"}}
        assert resolve_shared_marks(inv, {}) == []
        assert "scars" not in inv["甲"] and "scars" not in inv["乙"]
