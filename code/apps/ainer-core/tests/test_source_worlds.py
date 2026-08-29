"""混合源圈层 —— 一本书横跨两个世界。

穿越／双线小说的问题不是「翻译难」，是**同一个词在两个世界里不是一个意思**：

    先生   古代场 = 老师      现代场 = Mr.
    大人   古代场 = my lord   现代场 = adult

靠 (映射, 源词) 唯一是分不开的：后写的覆盖先写的，
而覆盖掉哪一个取决于挖掘顺序 —— 两次跑可能译出两个词。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.worldview.preflight import _disambiguate


def _lex(term, profile, target):
    return SimpleNamespace(source_term=term, source_profile_id=profile,
                           target_term=target, source_aliases=None)


class TestDisambiguate:
    def test_scene_profile_beats_generic(self):
        rows = [_lex("先生", None, "sir"), _lex("先生", "wp_tang", "teacher")]
        out = _disambiguate(rows, "wp_tang")
        assert [r.target_term for r in out] == ["teacher"]

    def test_other_world_entries_are_dropped_not_ranked(self):
        """现代场译成「老师」不是不够好，是错的 ——
        而错在这一层看不出来，要到读者读到才发现。"""
        rows = [_lex("先生", "wp_tang", "teacher")]
        assert _disambiguate(rows, "wp_net") == []

    def test_generic_entries_serve_every_world(self):
        rows = [_lex("案几", None, "low table")]
        assert len(_disambiguate(rows, "wp_tang")) == 1
        assert len(_disambiguate(rows, "wp_net")) == 1

    def test_no_profile_means_generic_only(self):
        """不传圈层时不能「随便挑一条」—— 挑中哪一条取决于查询返回顺序，
        同一段文本两次跑可能译出两个词。"""
        rows = [_lex("先生", "wp_tang", "teacher"),
                _lex("先生", "wp_net", "Mr.")]
        assert _disambiguate(rows, None) == []

    def test_each_term_survives_once(self):
        rows = [_lex("先生", None, "sir"), _lex("先生", "wp_tang", "teacher"),
                _lex("案几", None, "low table")]
        out = _disambiguate(rows, "wp_tang")
        assert len(out) == 2
        assert {r.source_term for r in out} == {"先生", "案几"}


class TestBlockWorldFallback:
    """场没标时回落到主源圈层，**不能返回 None**。

    None 的语义是「只用通用条目」，而那会把所有挂了圈层的条目
    全部排除掉 —— 词表突然少了一半，而没有任何一处会报错。
    """

    def test_falls_back_to_the_main_source(self):
        from app.pipelines.source_worlds import profile_for_block

        class _DB:
            def get(self, _model, _id):
                return None

        tf = SimpleNamespace(source_profile_id="wp_main",
                             extra_source_profiles_json=["wp_other"])
        block = SimpleNamespace(scene_id=None)
        assert profile_for_block(_DB(), tf, block) == "wp_main"


class TestSourceProfiles:
    def test_main_comes_first_and_duplicates_are_dropped(self):
        import app.pipelines.source_worlds as sw

        rows = {"a": SimpleNamespace(id="a"), "b": SimpleNamespace(id="b")}

        class _Res:
            def scalars(self):
                return list(rows.values())

        class _DB:
            def execute(self, _stmt):
                return _Res()

        tf = SimpleNamespace(source_profile_id="a",
                             extra_source_profiles_json=["b", "a"])
        out = sw.source_profiles(_DB(), tf)
        assert [p.id for p in out] == ["a", "b"]


def test_single_world_lexicon_is_not_tagged():
    """单圈层的小说，词条不挂圈层。

    挂上主源圈层反而有害：以后加第二个源圈层时，
    这些老条目会突然变成「只属于第一个世界」，
    而现代场的文本再也查不到它们。
    """
    import inspect

    from app.worldview.survey import _blocks_by_world

    src = inspect.getsource(_blocks_by_world)
    assert "return [(None," in src


class TestCoveredIsPerWorld:
    """已覆盖集合按圈层各算各的。

    共享一个集合的话，古代场挖过「先生」之后，现代场的候选就把它排除了 ——
    而「同一个词在两个世界里译法不同」恰恰是这整套机制存在的理由。
    排除掉它，功能就是死的：库里永远不会出现需要消歧的词条。

    实跑证实过：第一版共享 covered，两章挖出 31 条，
    **一条需要消歧的都没有**，体检直接报「配了多个源圈层但没有任何一个词
    在两个世界里有不同译法」。
    """

    def test_survey_splits_the_covered_set(self):
        import inspect

        from app.worldview.survey import survey_chapter

        src = inspect.getsource(survey_chapter)
        assert "w_covered" in src
        assert "r.source_profile_id in (world_id, None)" in src

    def test_single_world_keeps_the_shared_set(self):
        """单圈层时行为不变 —— 多算一遍是纯浪费。"""
        import inspect

        from app.worldview.survey import survey_chapter

        src = inspect.getsource(survey_chapter)
        assert "if multi else covered" in src
