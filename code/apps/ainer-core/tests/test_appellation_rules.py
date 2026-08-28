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
