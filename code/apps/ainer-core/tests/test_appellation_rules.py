"""中文称呼构词规则的测试。

这一层存在的理由是**不赌模型的判断力**：
让 LLM 判「老周是专名还是名号」，换个模型就可能换个答案 ——
minimax 判成 epithet，那会走意译译出 Old Zhou。
管线的正确率不该随模型漂移。

所以这些用例既是规则的回归，也是「哪些情况必须由系统兜住」的清单。
"""
from __future__ import annotations

import pytest

from app.models import EntityKind, NameType
from app.worldview.appellation_rules import brief_for_prompt, classify


def _t(name, kind=EntityKind.character):
    return classify(name, kind)


class TestProperNames:
    @pytest.mark.parametrize("name", ["老周", "小林", "老张", "小陈"])
    def test_intimate_prefix_plus_surname(self, name):
        """「老X」指特定的那个人 —— 换个姓就是另一个人，所以是专名。

        判成 epithet 会走意译，译出 Old Zhou 这种东西；
        正确做法是给他一个目标文化的名字，再把「老周」登记成亲昵称呼。
        """
        v = _t(name)
        assert v and v.name_type is NameType.proper and v.decisive

    def test_a_prefix_uses_given_name_not_surname(self):
        """「阿X」的 X 通常是名不是姓，不能查姓氏表。"""
        v = _t("阿强")
        assert v and v.name_type is NameType.proper

    @pytest.mark.parametrize("name", ["张老", "李公"])
    def test_surname_plus_respect_suffix(self, name):
        v = _t(name)
        assert v and v.name_type is NameType.proper and v.decisive

    def test_derogatory_still_points_at_a_person(self):
        v = _t("姓沈的")
        assert v and v.name_type is NameType.proper

    @pytest.mark.parametrize("name", ["沈砚", "裴无咎", "欧阳锋"])
    def test_full_names(self, name):
        v = _t(name)
        assert v and v.name_type is NameType.proper


class TestRoles:
    @pytest.mark.parametrize("name", [
        "掌柜", "镖头", "县令", "捕快", "趟子手", "小二", "师父",
    ])
    def test_role_words(self, name):
        v = _t(name)
        assert v and v.name_type is NameType.role and v.decisive

    @pytest.mark.parametrize("name", ["总镖头", "副将", "大掌柜"])
    def test_prefixed_roles(self, name):
        """「总镖头」正是端到端跑出 Дарья Ивановна Орлова 的那一个。"""
        v = _t(name)
        assert v and v.name_type is NameType.role and v.decisive


class TestEpithetsAndGeneric:
    @pytest.mark.parametrize("name", ["灰衣汉子", "独臂老人", "白衣女子"])
    def test_feature_plus_person_noun(self, name):
        """靠特征指认，换个人仍然成立 —— 这才是名号。"""
        v = _t(name)
        assert v and v.name_type is NameType.epithet

    @pytest.mark.parametrize("name", ["那个人", "几个汉子", "一个书生"])
    def test_generic_leads(self, name):
        v = _t(name)
        assert v and v.name_type is NameType.generic and v.decisive


class TestScopeLimits:
    def test_non_chinese_returns_none(self):
        """别的语言各有各的构词法，硬套中文规则会把 Sir Thomas 判成职务。"""
        assert _t("Sir Thomas") is None
        assert _t("Фёдор Ильич") is None

    def test_person_rules_do_not_apply_to_places(self):
        """姓名构词只对人物生效。"""
        assert classify("老周", EntityKind.location) is None

    def test_role_words_apply_to_any_kind(self):
        """职务词表不限人物 —— 它先于 kind 判定。"""
        v = classify("掌柜", EntityKind.location)
        assert v and v.name_type is NameType.role

    def test_unknown_defers_to_model(self):
        assert _t("三娘客栈", EntityKind.location) is None


class TestPromptAlignment:
    def test_brief_covers_every_rule_family(self):
        """提示词与规则必须共用一套判据。

        两边各写各的，模型会按一套标准判、系统按另一套复核，
        冲突时谁也说不清该信谁。
        """
        brief = brief_for_prompt()
        for token in ("老周", "掌柜", "灰衣汉子", "那个人", "姓沈的"):
            assert token in brief, f"提示词里缺少 {token} 这一族的判据"
        for t in ("proper", "role", "epithet", "generic"):
            assert t in brief


class TestBarePronounsAreNotPlaceholders:
    """代词是语法成分，不是称呼。

    占位符会把它们锁成一个固定形式，于是译文在任何句法位置都用主格。
    实跑出过：

        "crouched beside he"                 ← 该是 him
        "you has good innate potential"      ← 主谓不一致
        「你不知道。」→ "I don't know."        ← 人称全反了

    最后那条最能说明问题：占位符挡住了原文，模型看不出这句是对谁说的。
    代词本来就不需要跨文化映射。
    """

    def test_bare_pronouns_are_recognised(self):
        from app.pipelines.entities import _is_bare_pronoun
        for w in ("你", "他", "她", "您", "我们", "他们", "自己"):
            assert _is_bare_pronoun(w), w

    def test_pronoun_with_a_head_noun_is_a_real_appellation(self):
        """「你师姐」里的「师姐」是真正的称呼，需要跨文化映射 ——
        排除它等于把亲属称谓一起丢了。"""
        from app.pipelines.entities import _is_bare_pronoun
        for w in ("你师姐", "他师父", "你师门", "我家老爷"):
            assert not _is_bare_pronoun(w), w

    def test_placeholder_map_skips_them(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "pipelines" / "entities.py").read_text("utf-8")
        body = src[src.index("def placeholder_map"):]
        assert "Register.pronoun_like" in body
        assert "_is_bare_pronoun(surface)" in body
