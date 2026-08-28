"""说话人提取的规则测试。

这一层规则密集且**错了不报错** —— 一个半句话被当成说话人，
会一路污染实体表、TTS 音色和分镜的对话指向，沿途没有任何一处会失败。
所以每条规则都要有测试钉住，后续改动才不会悄悄退化。
"""
from __future__ import annotations

import pytest

from app.models import BlockType
from app.pipelines.prose import classify_paragraph, trim_speaker


class TestTrimSpeaker:
    @pytest.mark.parametrize("raw,expect", [
        ("沈砚", "沈砚"),
        ("老周", "老周"),
        ("柳三娘", "柳三娘"),
        ("总镖头", "总镖头"),
        ("裴无咎", "裴无咎"),
        ("小二哥", "小二哥"),
        ("大内总管", "大内总管"),
    ])
    def test_clean_names_pass_through(self, raw, expect):
        """干净的称呼原样通过，不能被规则误伤。"""
        assert trim_speaker(raw) == expect

    @pytest.mark.parametrize("raw,expect", [
        # 动词切
        ("李格非从里屋走出", "李格非"),
        ("老周凑过来，压低了声音", "老周"),
        ("裴无咎把铁钎往地上一杵", "裴无咎"),
        # 虚词切 —— 动词表切完还剩半句的那类
        ("总镖头把镖单推过来，指节在桌上敲了两下", "总镖头"),
        ("三娘的眼睛在镖旗上停了半息", "三娘"),
        # 数词切 —— 前两刀都切不动
        ("三娘四十上下，手上一直捏着块抹布", "三娘"),
    ])
    def test_narrative_trimmed_to_name(self, raw, expect):
        assert trim_speaker(raw) == expect

    @pytest.mark.parametrize("raw", [
        "他", "她", "众人", "有人",          # 代词不指向具体角色
        "老周慢悠悠",                        # 叠字是副词特征
        "把镖单推过来",                      # 虚词开头 = 整段不是称呼
        "留",                                # 裁完过短
        "",
        None,
    ])
    def test_rejects_rather_than_guesses(self, raw):
        """宁可没有说话人，也不要一个错的。

        缺失可由 speakers:resolve 用 LLM 补上；错的会一路污染下游。
        """
        assert trim_speaker(raw) is None


class TestClassifyParagraph:
    def test_prefix_dialogue(self):
        t, _, sp = classify_paragraph("裴无咎把铁钎往地上一杵：「巧。」")
        assert t is BlockType.dialogue
        assert sp == "裴无咎"

    def test_long_prefix_still_dialogue(self):
        """冒号前是长叙述句时仍是对白 —— 卡在 20 字会让整段对白丢失。"""
        t, _, sp = classify_paragraph(
            "三娘四十上下，手上一直捏着块抹布，见人进门先笑：「客官，住店还是打尖？」"
        )
        assert t is BlockType.dialogue
        assert sp == "三娘"

    def test_suffix_speaker(self):
        t, _, sp = classify_paragraph("「我是。」老周说，「他不是。」")
        assert t is BlockType.dialogue
        assert sp == "老周"

    def test_suffix_picks_first_valid_not_last_fragment(self):
        """句中有多个引号时不能匹配到末尾的片段。

        「周叔，」沈砚打断他，「…留到路上再说。」
        末尾的「留到路上再」+「说」也能匹配后缀模式，
        取到它就等于凭空造了个叫「留到路上再」的角色。
        """
        t, _, sp = classify_paragraph(
            "「周叔，」沈砚打断他，「您那句『这地方不对』，留到路上再说。」"
        )
        assert t is BlockType.dialogue
        assert sp == "沈砚"

    def test_quote_at_start_is_dialogue_even_without_speaker(self):
        t, _, sp = classify_paragraph("「就这儿。」他说。")
        assert t is BlockType.dialogue
        assert sp is None          # 代词不算说话人

    def test_mid_sentence_quote_is_narration(self):
        """段中的引用不是谁在讲话 —— 靠引号位置判，不靠占比。"""
        t, _, sp = classify_paragraph("所谓『人在江湖』大抵如此，他心里想。")
        assert t is BlockType.narration
        assert sp is None

    def test_plain_narration(self):
        t, _, sp = classify_paragraph("沈砚在窗边坐下来，从缝里往外看。")
        assert t is BlockType.narration
        assert sp is None

    def test_heading(self):
        t, txt, _ = classify_paragraph("第三章 雪夜")
        assert t is BlockType.heading
        assert txt == "第三章 雪夜"


# ── 命名验证：书写系统与姓名格式 ──────────────────────────────────────────────

from app.worldview.naming import (
    NoFallbackPool, deterministic_fallback_name, validate_localized_name,
)


class TestNameValidation:
    """按目标语言的**书写系统**判定，而非硬编码拉丁字母。

    只认拉丁的后果：俄语的 Фёдор、印地语的 अजय、阿拉伯语的 يوسف
    全被判不合格，然后回落到兜底池 —— 而兜底池只有英语，
    俄语角色会拿到一个英文名，且下游全链路都会用它、沿途不报错。
    """

    @pytest.mark.parametrize("name,lang,pattern", [
        ("Фёдор Степанович Рукавишников", "ru-RU", "given_patronymic_family"),
        ("Edmund Ashcroft", "en-GB", "given_family"),
        ("अजय शर्मा", "hi-IN", "given_title"),
        ("يوسف بن إبراهيم", "ar-SA", "given_patronymic"),
        ("佐藤 健一", "ja-JP", None),
        ("Étienne Duval", "fr-FR", "given_family"),
    ])
    def test_accepts_correct_script(self, name, lang, pattern):
        ok, why = validate_localized_name(name, lang, pattern)
        assert ok, why

    def test_rejects_wrong_script(self):
        """给俄语世界观一个英文名 —— 比没有名字更糟。"""
        ok, why = validate_localized_name(
            "Roland Whitfield", "ru-RU", "given_patronymic_family")
        assert not ok
        assert "cyrillic" in why

    def test_patronymic_needs_three_parts(self):
        """俄语正式姓名是「名 + 父称 + 姓」，按两段判会误杀正确答案。"""
        ok, why = validate_localized_name(
            "Фёдор Соколов", "ru-RU", "given_patronymic_family")
        assert not ok
        assert "父称" in why

    def test_two_parts_enough_without_patronymic(self):
        ok, _ = validate_localized_name("Edmund Ashcroft", "en-GB", "given_family")
        assert ok

    def test_rejects_pinyin_transliteration(self):
        ok, why = validate_localized_name("Li Qingzhao", "en-GB", "given_family")
        assert not ok
        assert "拼音" in why


class TestFallbackPool:
    @pytest.mark.parametrize("lang", [
        "en-GB", "ru-RU", "ja-JP", "es-ES", "fr-FR", "pt-PT",
        "ar-SA", "hi-IN", "bn-IN",
    ])
    def test_every_pool_entry_matches_target_language(self, lang):
        """池子里**每一项**都要能通过该语言的校验。

        只测一个索引是不够的 —— 这条测试第一版就是那么写的，
        于是漏掉了葡语池里一个把 So 打成西里尔 Со 的名字。
        肉眼看不出差别，验证器看得出，但只有遍历整池才会撞上。
        """
        from app.worldview.naming import _FALLBACK_POOLS

        pattern = "given_patronymic_family" if lang.startswith("ru") else None
        pool = _FALLBACK_POOLS[lang[:2].lower()]
        for name, _reading in pool:
            ok, why = validate_localized_name(name, lang, pattern)
            assert ok, f"{lang} 的兜底名「{name}」不合格：{why}"

    def test_deterministic(self):
        """同一实体在任何进程、任何时刻结果恒定 —— v1 用 hash() 每次重启换名字。"""
        a = deterministic_fallback_name("we_1", "tf_1", "ru-RU")
        b = deterministic_fallback_name("we_1", "tf_1", "ru-RU")
        assert a == b

    def test_refuses_unknown_language(self):
        """没有该语言的池子时报错，而不是发一个英文名。"""
        with pytest.raises(NoFallbackPool):
            deterministic_fallback_name("we_x", "tf_x", "sw-KE")
