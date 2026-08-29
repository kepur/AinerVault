"""名物类别与成语识别的规则测试。

和称呼规则同一个思路：**能查表确定的，不交给模型判**。
让模型判「腰刀是什么类」，换个模型可能判成 other，
而 category 决定了这条词在提示词里怎么呈现、审计时怎么比对。
"""
from __future__ import annotations

import pytest

from app.models import LexiconCategory as C
from app.worldview import idiom_rules as ir
from app.worldview import lexicon_rules as lr


class TestLexiconCategory:
    @pytest.mark.parametrize("term,cat", [
        ("腰刀", C.weapon), ("长剑", C.weapon),
        ("蓑衣", C.garment), ("直裰", C.garment),
        ("客栈", C.place), ("酒楼", C.place), ("镖局", C.place),
        ("门槛", C.architecture),
        ("镖车", C.vehicle), ("马车", C.vehicle),
        ("县令", C.office), ("都尉", C.office), ("捕快", C.office),
        ("铜钱", C.currency), ("银子", C.currency),
        ("公子", C.honorific), ("客官", C.honorific),
    ])
    def test_suffix_rules(self, term, cat):
        v = lr.classify(term)
        assert v and v.category is cat and v.decisive, f"{term} → {v}"

    @pytest.mark.parametrize("term", [
        "三千里", "半盏茶", "一炷香", "小半个时辰", "十丈", "三尺",
    ])
    def test_numeral_plus_unit_is_measure(self, term):
        """数量 + 量词说的是度量不是实物。

        「半盏茶」指一段时间，端到端跑出过把它译成「没喝完半杯茶」——
        category 判对了（measure）却仍译了字面，
        所以规则要连同判据一起写进提示词。
        """
        v = lr.classify(term)
        assert v and v.category is C.measure and v.decisive

    @pytest.mark.parametrize("term", ["五两银子", "几吊钱", "三锭银"])
    def test_currency_beats_measure(self, term):
        """「两」既是重量也是货币单位 —— 带「银子」的先判货币。"""
        v = lr.classify(term)
        assert v and v.category is C.currency

    def test_bare_single_char_is_soft(self):
        """孤零零一个「刀」可能是泛指，不该硬覆盖模型。"""
        v = lr.classify("刀")
        assert v and v.category is C.weapon and not v.decisive

    def test_complete_word_equal_to_suffix_is_hard(self):
        """「蓑衣」整词等于后缀，恰恰说明它就是那个完整的词。"""
        v = lr.classify("蓑衣")
        assert v and v.decisive

    def test_non_chinese_defers(self):
        """别的语言各有构词法，硬套会把 doublet 判成 other。"""
        assert lr.classify("doublet") is None
        assert lr.classify("шашка") is None

    def test_unknown_defers(self):
        assert lr.classify("镖旗") is None

    def test_brief_matches_rules(self):
        brief = lr.brief_for_prompt()
        for token in ("weapon", "garment", "place", "measure", "currency"):
            assert token in brief
        assert "半盏茶" in brief


class TestIdioms:
    @pytest.mark.parametrize("text", ["破釜沉舟", "塞翁失马", "卧薪尝胆", "唇亡齿寒"])
    def test_table_hit_is_decisive(self, text):
        v = ir.classify(text)
        assert v and v.kind == "idiom" and v.decisive

    def test_set_phrase(self):
        v = ir.classify("人在江湖身不由己")
        assert v and v.kind == "set_phrase" and v.decisive

    @pytest.mark.parametrize("text", ["推开客栈", "雪夜奔波", "三簧铜锁"])
    def test_four_char_is_only_a_hint(self, text):
        """四字格不下结论 —— 「推开客栈」也是四字，结构分不出来。

        判成成语的代价是它被强制标为 high 文化依赖，
        然后走 compensate 被改写掉，而它本来只是句普通描述。
        """
        v = ir.classify(text)
        assert v and v.kind == "four_char" and not v.decisive

    def test_find_in_text(self):
        txt = "他知道这是背水一战，可行走江湖多年，早明白人在江湖身不由己。"
        found = dict(ir.find_in_text(txt))
        assert "背水一战" in found
        assert "人在江湖身不由己" in found

    def test_find_returns_nothing_for_plain_text(self):
        assert ir.find_in_text("他推开门，雪还在下。") == []

    def test_brief_empty_when_no_hits(self):
        """没扫到就不占提示词的位置。"""
        assert ir.brief_for_prompt([]) == ""

    def test_brief_states_the_consequence(self):
        brief = ir.brief_for_prompt([("破釜沉舟", "idiom")])
        assert "破釜沉舟" in brief
        assert "idiom" in brief and "high" in brief
