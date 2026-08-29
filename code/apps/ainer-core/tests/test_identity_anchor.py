"""身份锚 —— 把「同一个人」从文字变成事实。

拿同一句描述生成三次是三张脸，所以跨期同一性的落点是一张共用的参考图。
这里测的是那张图的提示词怎么拼 —— 它错一个词，六个角色的脸就全跑偏。
"""
from __future__ import annotations

import pytest

from app.pipelines.identity import (
    ANCHOR_FRAMING, ANCHOR_NEGATIVE, compose_anchor_prompt, era_phrase,
)


class _Profile:
    def __init__(self, axes):
        self.axes_json = axes


class _Epoch:
    def __init__(self, inv, var=None):
        self.invariant_json = inv
        self.variant_json = var or {}


class TestEraPhrase:
    """「帝俄晚期」在提示词里必须写成 late 19th century Russian ——
    图像模型不认中文，也不认 ru_imperial 这种内部代码。"""

    @pytest.mark.parametrize("axes,expect", [
        ({"region": "RU", "era_span": [1855, 1917]}, "late 19th century Russian"),
        ({"region": "GB", "era_span": [1837, 1901]}, "late 19th century British"),
        ({"region": "JP", "era_span": [1926, 1989]}, "mid 20th century Japanese"),
        ({"region": "US", "era_span": [1920, 1929]}, "early 20th century American"),
    ])
    def test_reads_axes(self, axes, expect):
        assert era_phrase(_Profile(axes)) == expect

    def test_missing_pieces_degrade_gracefully(self):
        assert era_phrase(_Profile({"region": "RU"})) == "Russian"
        assert era_phrase(_Profile({"era_span": [1855, 1917]})) \
            == "late 19th century"
        assert era_phrase(_Profile({})) == ""

    def test_unknown_region_is_dropped_not_guessed(self):
        """猜错族裔比不写更糟 —— 不写模型按其余线索推，写错它就照着错的画。"""
        assert era_phrase(_Profile({"region": "ZZ", "era_span": [1900, 1910]})) \
            == "early 20th century"


class TestAnchorPrompt:
    def test_sex_and_era_lead_the_prompt(self):
        """实跑时沈砚（男，帝俄晚期）的锚图出来是张现代女性的脸 ——
        英文不变项里没有性别词，SD 就自己挑了一个。"""
        p = compose_anchor_prompt(
            _Epoch({"sex": "male", "_en": "square face, thick brows"}),
            _Profile({"region": "RU", "era_span": [1855, 1917]}),
        )
        assert p.startswith("late 19th century Russian man, ")
        assert "square face, thick brows" in p
        assert p.endswith(ANCHOR_FRAMING)

    def test_no_english_means_no_prompt(self):
        """中文喂给 SDXL 出来的是汉字纹样，不是脸 —— 宁可不生成。"""
        assert compose_anchor_prompt(_Epoch({"face_shape": "国字脸"})) == ""

    def test_variant_is_never_included(self):
        """锚会被后续每一期引用。带上第一期的衣着兵器，
        那身衣服会渗进中年的每一张图。"""
        p = compose_anchor_prompt(
            _Epoch({"sex": "male", "_en": "square face"},
                   {"_en": "dark grey escort coat, sabre at the hip"}))
        assert "sabre" not in p and "coat" not in p

    def test_framing_forbids_costume_and_scene(self):
        for word in ("no costume detail", "no props", "plain mid-grey"):
            assert word in ANCHOR_FRAMING
        for word in ("full body", "costume", "weapon", "scenery"):
            assert word in ANCHOR_NEGATIVE

    def test_profile_is_optional(self):
        p = compose_anchor_prompt(_Epoch({"sex": "female", "_en": "round face"}))
        assert p.startswith("woman, round face")


class TestAgeFallback:
    """没有年龄的头肩像，模型一律画成三十岁上下 ——
    于是六十岁的老周和二十岁的裴无咎看着同龄。

    实跑时模型漏填了 age_en（一次调用要两种语言，它会放弃一种），
    但 visual_en 的第一段基本都是年龄，因为提示词就是那么要求的。
    """

    @pytest.mark.parametrize("item,expect", [
        ({"age_en": "late twenties", "visual_en": "x"}, "late twenties"),
        ({"visual_en": "mid-40s, short dark hair"}, "mid-40s"),
        ({"visual_en": "early sixties, grey beard"}, "early sixties"),
        ({"visual_en": "a boy of about twelve, ragged tunic"},
         "a boy of about twelve"),
    ])
    def test_reads_or_recovers(self, item, expect):
        from app.pipelines.entity_epochs import _age_en
        assert _age_en(item) == expect

    def test_non_age_head_is_not_mistaken(self):
        """首段不是年龄时不能硬当年龄用 —— 「短发」当成年龄会毁掉整张脸。"""
        from app.pipelines.entity_epochs import _age_en
        assert _age_en({"visual_en": "short dark hair, grey coat"}) == ""

    def test_age_leads_the_anchor_prompt(self):
        from app.pipelines.entity_epochs import AGE_EN_KEY
        p = compose_anchor_prompt(
            _Epoch({"sex": "male", "_en": "square face"},
                   {AGE_EN_KEY: "early sixties"}),
            _Profile({"region": "RU", "era_span": [1855, 1917]}))
        assert p.startswith("early sixties, late 19th century Russian man")


def test_sex_noun_is_dropped_when_the_age_phrase_already_has_it():
    """年龄短语常常自带 man／woman，再补一个就成了
    「man in his late fifties, … Russian man」—— 读起来像没校对过。"""
    from app.pipelines.entity_epochs import AGE_EN_KEY
    p = compose_anchor_prompt(
        _Epoch({"sex": "male", "_en": "square face"},
               {AGE_EN_KEY: "man in his late fifties"}),
        _Profile({"region": "RU", "era_span": [1855, 1917]}))
    assert p.startswith("man in his late fifties, late 19th century Russian, ")
    assert "Russian man" not in p


def test_sex_noun_survives_when_the_age_phrase_lacks_it():
    from app.pipelines.entity_epochs import AGE_EN_KEY
    p = compose_anchor_prompt(
        _Epoch({"sex": "male", "_en": "square face"},
               {AGE_EN_KEY: "elderly, deeply lined"}),
        _Profile({"region": "RU", "era_span": [1855, 1917]}))
    assert "late 19th century Russian man" in p
