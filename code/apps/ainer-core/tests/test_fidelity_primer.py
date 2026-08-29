"""转译力度与导读篇。

这一层的错都**不会报错**，只会让读者读不懂：
  力度选错   存真档没配导读，读者撞上一堆没有来处的词
  导读不回流 正文照旧逐处解释，读者读完导读又被解释一遍
  导读过长   没人读，而正文按「已经讲过」来写
"""
from __future__ import annotations

import pytest

from app.models import (
    CulturalLoad, DeviceStrategy, Fidelity, PlotLoad, Volatility,
    apply_fidelity, choose_strategy,
)
from app.models.narrative_device import _DOMESTICATION


class TestFidelityBias:
    """力度不替代九档阶梯，只给阶梯一个偏置。"""

    def test_preserve_world_pulls_back_toward_the_original(self):
        assert apply_fidelity(DeviceStrategy.substitute,
                              Fidelity.preserve_world) is DeviceStrategy.preserve
        assert apply_fidelity(DeviceStrategy.naturalize,
                              Fidelity.preserve_world) is DeviceStrategy.transplant

    def test_transplant_world_pushes_toward_the_target(self):
        assert apply_fidelity(DeviceStrategy.preserve,
                              Fidelity.transplant_world) is DeviceStrategy.substitute
        assert apply_fidelity(DeviceStrategy.transplant,
                              Fidelity.transplant_world) is DeviceStrategy.naturalize

    def test_anchored_changes_nothing(self):
        for s in DeviceStrategy:
            assert apply_fidelity(s, Fidelity.anchored) is s

    def test_the_ladder_has_ends(self):
        """两端不能越界 —— 越界会拿到一个不存在的档。"""
        assert apply_fidelity(DeviceStrategy.preserve,
                              Fidelity.preserve_world) is DeviceStrategy.preserve
        assert apply_fidelity(DeviceStrategy.naturalize,
                              Fidelity.transplant_world) is DeviceStrategy.naturalize

    def test_only_the_domestication_ladder_shifts(self):
        """解释类与止损类不在这条线上 —— 它们回答的是别的问题。"""
        assert DeviceStrategy.gloss_inline not in _DOMESTICATION
        assert DeviceStrategy.footnote not in _DOMESTICATION
        assert DeviceStrategy.omit not in _DOMESTICATION


class TestExplainedByPrimer:
    """导读讲过的词，正文里直接用原物。

    不接这一步的话，导读写了也白写：读者读完导读，正文里又被解释一遍。
    """

    def test_gloss_becomes_preserve(self):
        assert apply_fidelity(DeviceStrategy.gloss_inline, Fidelity.preserve_world,
                              explained=True) is DeviceStrategy.preserve

    def test_footnote_becomes_preserve(self):
        assert apply_fidelity(DeviceStrategy.footnote, Fidelity.anchored,
                              explained=True) is DeviceStrategy.preserve

    def test_unexplained_keeps_the_gloss(self):
        """没讲过就还得就地解释 —— 少了它读者一脸茫然。"""
        assert apply_fidelity(DeviceStrategy.gloss_inline, Fidelity.preserve_world,
                              explained=False) is DeviceStrategy.gloss_inline

    def test_transplant_world_replaces_instead_of_explaining(self):
        """移植档不解释，直接换成目标文化里的东西。"""
        assert apply_fidelity(DeviceStrategy.gloss_inline,
                              Fidelity.transplant_world) is DeviceStrategy.transplant


class TestSalvageUnderPreserve:
    """存真档的取向是「宁可出戏也不丢」。"""

    @pytest.mark.parametrize("s", [DeviceStrategy.compensate,
                                   DeviceStrategy.relocate, DeviceStrategy.omit])
    def test_salvage_is_lifted_to_a_footnote(self, s):
        assert apply_fidelity(s, Fidelity.preserve_world) is DeviceStrategy.footnote

    @pytest.mark.parametrize("s", [DeviceStrategy.compensate,
                                   DeviceStrategy.relocate, DeviceStrategy.omit])
    def test_transplant_leaves_salvage_alone(self, s):
        """已经决定认赔的地方，再归化也救不回来。"""
        assert apply_fidelity(s, Fidelity.transplant_world) is s


class TestThreeAxesStillDecide:
    """力度只回答「往哪边挪一格」，不回答「这处该怎么办」。"""

    def test_pivot_survives_every_fidelity(self):
        """情节转折靠它，无论哪一档都不能舍。"""
        for fid in Fidelity:
            out = choose_strategy(CulturalLoad.high, PlotLoad.pivot,
                                  Volatility.evergreen, fid)
            assert out is not DeviceStrategy.omit

    def test_short_lived_meme_is_never_preserved_literally(self):
        """三年后源文化自己都没人懂的梗，不值得目标读者去考古。"""
        out = choose_strategy(CulturalLoad.high, PlotLoad.none,
                              Volatility.months, Fidelity.preserve_world)
        assert out is not DeviceStrategy.preserve

    def test_same_input_three_fidelities_three_answers(self):
        args = (CulturalLoad.medium, PlotLoad.flavor, Volatility.evergreen)
        got = [choose_strategy(*args, f) for f in Fidelity]
        assert len(set(got)) == 3, "三档给出同一个答案，等于力度没生效"


class TestPrimerNeed:
    def test_preserve_world_requires_a_primer(self):
        """这一档的整个前提就是「术语原样保留，读者靠导读挂靠」。"""
        from app.pipelines.primer import NEEDS_PRIMER
        assert NEEDS_PRIMER[Fidelity.preserve_world] == "required"

    def test_transplant_world_needs_none(self):
        """体系已经换成目标文化的了，没有新东西要交代。"""
        from app.pipelines.primer import NEEDS_PRIMER
        assert NEEDS_PRIMER[Fidelity.transplant_world] == "unnecessary"

    def test_every_fidelity_is_covered(self):
        from app.pipelines.primer import NEEDS_PRIMER
        for f in Fidelity:
            assert f in NEEDS_PRIMER, f"{f.value} 没说要不要导读"


class TestPrimerTrim:
    """太长就砍整节，不按比例压缩每一节。

    压缩会把每节都讲成半截，而半截的体系说明比没有更糟 ——
    读者以为自己懂了。
    """

    def _sec(self, kind, words, heading="h"):
        from app.pipelines.primer import _trim
        return {"kind": kind, "heading": heading,
                "body": "word " * words, "covers": []}

    def test_short_input_is_untouched(self):
        from app.pipelines.primer import _trim
        secs = [self._sec("system", 100), self._sec("address", 100)]
        kept, dropped = _trim(secs)
        assert len(kept) == 2 and dropped == []

    def test_least_important_section_goes_first(self):
        """体系最要紧，类型约定最次要。"""
        from app.pipelines.primer import _trim, MAX_WORDS
        secs = [self._sec("convention", MAX_WORDS, "约定"),
                self._sec("system", MAX_WORDS, "体系")]
        kept, dropped = _trim(secs)
        assert [k["heading"] for k in kept] == ["体系"]
        assert dropped == ["约定"]

    def test_at_least_one_section_survives(self):
        """全砍光等于没写 —— 再长也要留下最要紧的那一节。"""
        from app.pipelines.primer import _trim, MAX_WORDS
        kept, _ = _trim([self._sec("system", MAX_WORDS * 3)])
        assert len(kept) == 1


class TestWordCount:
    def test_cjk_counted_by_character(self):
        """两种文字的「一个词」不是一回事，混着数会得出没意义的数字。"""
        from app.pipelines.primer import _words
        assert _words("修行分九境，前三境是凡人可及的") == 14
        assert _words("the cultivation path has nine stages") == 6


class TestHybridSourceWorlds:
    """穿越小说一本书横跨两个圈层。

    「先生」在古代场是老师，在现代场是 Mr.。
    同名词条并存，查的时候按场景所属的圈层消歧。
    """

    def _row(self, term, profile, target):
        from types import SimpleNamespace
        return SimpleNamespace(source_term=term, source_profile_id=profile,
                               target_term=target, source_aliases=None)

    def test_scene_profile_wins_over_generic(self):
        from app.worldview.preflight import _disambiguate
        rows = [self._row("先生", None, "sir"),
                self._row("先生", "wp_ancient", "teacher")]
        out = _disambiguate(rows, "wp_ancient")
        assert len(out) == 1 and out[0].target_term == "teacher"

    def test_other_profiles_are_dropped_not_ranked(self):
        """现代场译成「老师」不是不够好，是错的 ——
        而错在这一层看不出来，要到读者读到才发现。"""
        from app.worldview.preflight import _disambiguate
        rows = [self._row("先生", "wp_ancient", "teacher")]
        assert _disambiguate(rows, "wp_modern") == []

    def test_generic_survives_when_no_scene_profile(self):
        from app.worldview.preflight import _disambiguate
        rows = [self._row("客栈", None, "inn")]
        out = _disambiguate(rows, None)
        assert len(out) == 1 and out[0].target_term == "inn"

    def test_without_a_profile_only_generic_entries_are_used(self):
        """不传圈层时不能「随便挑一条」—— 挑中哪一条取决于查询返回顺序，
        同一段文本两次跑可能译出两个词。"""
        from app.worldview.preflight import _disambiguate
        rows = [self._row("先生", "wp_ancient", "teacher"),
                self._row("先生", "wp_modern", "mister")]
        assert _disambiguate(rows, None) == []
