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
        "高渐离", "莫大先生", "于正", "李向东", "王真", "张曾",
    ])
    def test_never_kills_a_real_name(self, raw):
        """禁用字表只放铁定不能入名的字。

        「渐」「正」「刚」「曾」「于」「莫」「真」「向」都是常见名字用字。
        把它们列进禁用表会把真人名判成 None —— 而**误杀比漏挡更糟**：
        漏挡的碎片还有后面几道检查，误杀的人名直接就没了，且沿途不报错。
        """
        assert trim_speaker(raw) == raw

    @pytest.mark.parametrize("raw", [
        "走到日头偏西",                      # 强动词开头 = 动词短语
        "摸出个油纸包",
    ])
    def test_rejects_verb_phrases(self, raw):
        assert trim_speaker(raw) is None

    def test_only_first_clause_considered(self):
        """冒号前有多个分句时只认第一句。

        说话人可能在任何一句：「总镖头把镖单推过来，指节在桌上敲了两下」
        在第一句，「走到日头偏西，前头出现一片屋檐。老周勒住马」在最后一句。
        逐句试会挑中错的 —— 第二例的第二句能产出「前头」，
        形状上完全合法，规则层面无从否定；「指节」同理。

        所以宁可只认第一句：说话人不在第一句时返回 None，
        由 speakers:resolve 用上下文补。漏一个可以补，错一个会一路传下去。
        """
        assert trim_speaker("总镖头把镖单推过来，指节在桌上敲了两下") == "总镖头"
        assert trim_speaker("走到日头偏西，前头出现一片屋檐。老周勒住马") is None

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

    @pytest.mark.parametrize("name,kind", [
        ("Волчья балка", "location"),
        ("Гостиный двор", "location"),
        ("Артель Каменева", "faction"),
    ])
    def test_place_and_faction_skip_person_name_shape(self, name, kind):
        """段数要求只对人物生效。

        地点与组织有自己的命名规范 ——「Гостиный двор」是完整的客栈名。
        按「名+父称+姓」判会拒掉它，然后回落到**人名**兜底池，
        于是端到端跑出了「镖局」= Николай Андреевич Лебедев，
        译文里「镖局的院子」成了「尼古拉·安德烈耶维奇·列别捷夫的院子」。
        """
        ok, why = validate_localized_name(
            name, "ru-RU", "given_patronymic_family", kind=kind)
        assert ok, why

    def test_script_still_enforced_for_places(self):
        """放宽段数不等于放宽书写系统 —— 俄语世界观里的地名仍须是西里尔。"""
        ok, why = validate_localized_name(
            "Roland Whitfield", "ru-RU", None, kind="location")
        assert not ok
        assert "cyrillic" in why

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


# ── 职务型实体不该走人名命名 ──────────────────────────────────────────────────

from app.pipelines.naming import role_term_hit


class TestRoleTermSplit:
    """名物词表里已有的实体是职务／身份，不是人名。

    不分流的后果是端到端第二跑抓到的那个：
    模型给「总镖头」提了 старшой（俄语「老大」），
    被「必须名+父称+姓」的规则判不合格，回落到兜底池，
    于是这个职务变成了 Дарья Ивановна Орлова —— 一个凭空出现的女角色，
    而译文里「总镖头把镖单推过来」从此由她来做。
    """

    LEX = {"总镖头", "掌柜", "小二", "客栈", "捕快"}

    def test_pure_role_term_skipped(self):
        assert role_term_hit({"总镖头"}, None, self.LEX) == "总镖头"

    def test_named_person_still_gets_a_name(self):
        """有家族键说明它是个有姓的人，仍要生成人名。"""
        assert role_term_hit({"柳三娘"}, "柳_family", self.LEX) is None

    def test_role_term_with_family_key_still_named(self):
        """既在词表里又有姓 —— 以人名为准，宁可多给不可漏给。"""
        assert role_term_hit({"掌柜", "柳三娘"}, "柳_family", self.LEX) is None

    def test_unknown_entity_gets_a_name(self):
        assert role_term_hit({"沈砚"}, "沈_family", self.LEX) is None
        assert role_term_hit({"裴无咎"}, None, self.LEX) is None

    def test_alias_hit_counts(self):
        """别名命中词表也算 —— 实体可能以本名登记、以职务被引用。"""
        assert role_term_hit({"周老板", "掌柜"}, None, self.LEX) == "掌柜"

    def test_empty_lexicon_names_everything(self):
        """名物勘探还没跑时不该误跳过任何实体。"""
        assert role_term_hit({"总镖头"}, None, set()) is None


class TestPlaceholderScope:
    """占位符表与命名管线的范围必须一致。

    不一致的表现是每次翻译都报一串「缺译名」，而那串永远不会消失 ——
    因为命名管线压根不处理 prop/style，占位符却要求它们有译名。
    报警变成噪声，真正缺译名的角色就被淹掉了。

    第二轮端到端每章都报 ['镖单','镖箱','三簧锁','镖旗','镖车','腰牌','腰刀']，
    七个全是道具。
    """

    def test_scopes_match(self):
        from app.pipelines.entities import _NEEDS_PROPER_NAME as A
        from app.pipelines.naming import _NEEDS_PROPER_NAME as B

        assert A is B, "两处必须共用同一份定义，不能各写各的"

    def test_props_excluded(self):
        from app.models import EntityKind
        from app.pipelines.entities import _NEEDS_PROPER_NAME

        # 道具走名物词表（腰刀 → шашка），不需要占位符隔离 ——
        # 占位符是为了防人名被音译
        assert EntityKind.prop not in _NEEDS_PROPER_NAME
        assert EntityKind.style not in _NEEDS_PROPER_NAME

    def test_proper_nouns_included(self):
        from app.models import EntityKind
        from app.pipelines.entities import _NEEDS_PROPER_NAME

        for k in (EntityKind.character, EntityKind.location, EntityKind.faction):
            assert k in _NEEDS_PROPER_NAME
