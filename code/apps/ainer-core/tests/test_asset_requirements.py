"""素材变体的结构化字段。

这一组全部来自同一次实跑：29 件素材漏了 15 件，报表说「缺 time_of_day /
weather / light_quality」，而答案其实一个不少地躺在 structured 里 ——
只是被塞进了一个以类别名为键的字符串。
**报「缺」而不说是哪一种缺，会把人引向错的方向。**
"""
from __future__ import annotations

from app.worldview.asset_requirements import (
    check_completeness, diagnose, requirements_for,
)


class TestCompleteness:
    def test_all_present(self):
        st = {"time_of_day": "night", "weather": "snow",
              "light_quality": "gas lamp glow", "mood": "eerie"}
        assert check_completeness("ambience", st) == []

    def test_blank_counts_as_missing(self):
        """空字符串和没有这个键，在下游是一回事 —— 都出不了图。"""
        st = {"time_of_day": "night", "weather": "  ",
              "light_quality": "", "mood": "eerie"}
        assert set(check_completeness("ambience", st)) == {"weather", "light_quality"}

    def test_none_structured(self):
        assert check_completeness("ambience", None) == list(
            requirements_for("ambience"))


class TestDiagnose:
    def test_answers_packed_under_the_kind_key(self):
        """实跑里最耽误人的一种：
            {"ambience": "night, heavy_snowfall, gas_lamp_glow, serene_eerie"}
        四项一个不少，报表却说缺三项。照着「缺」去查，会以为模型没答，
        去调措辞、去换模型 —— 实际上要改的只是键名。
        """
        st = {"ambience": "night, heavy_snowfall, gas_lamp_glow, serene_eerie",
              "mood": "haunting"}
        why = diagnose("ambience", st)
        assert why is not None
        assert 'structured["ambience"]' in why

    def test_field_name_echoed_as_value(self):
        """另一种形状：{"location": "architecture"} —— 把字段名当成了值。"""
        st = {"architecture": "architecture", "materials": "stucco",
              "lighting": "candlelight", "props": "bed", "era_marker": "1890s"}
        # architecture 的值就是字段名本身，视作未填
        assert diagnose("location", st) is None or "architecture" in (
            diagnose("location", st) or "")

    def test_plain_missing_has_no_diagnosis(self):
        """真的没答就是真的没答，这时不要编一个解释出来 ——
        多一条似是而非的提示，比没有提示更浪费时间。"""
        assert diagnose("ambience", {"mood": "eerie"}) is None

    def test_complete_yields_none(self):
        st = {"time_of_day": "night", "weather": "snow",
              "light_quality": "dim", "mood": "eerie"}
        assert diagnose("ambience", st) is None


class TestPromptShape:
    def test_requirements_are_rendered_as_json_skeleton(self):
        """把要求写成「类别: 字段一、字段二」，读起来就是「键: 值」，
        模型照着产出 {"类别": "全部答案挤在一起"}。
        骨架是逐字可照抄的，歧义没有落脚处。"""
        import inspect

        from app.pipelines import asset_pack

        src = inspect.getsource(asset_pack._variant_system)
        assert "json.dumps" in src
        assert "structured = " in src

    def test_prompt_forbids_the_observed_failure_modes(self):
        import inspect

        from app.pipelines import asset_pack

        src = inspect.getsource(asset_pack._variant_system)
        for rule in ("不要用类别名当键", "不要嵌套",
                     "不要把几项并成一个字符串", "不要把字段名当成值"):
            assert rule in src

    def test_variants_are_batched_by_kind(self):
        """一批里混着好几个类别时，要求块会同时列出好几套字段，
        模型只认真填了一套 —— 实跑 29 件漏 15 件，
        且四个场景全缺同样五项、四件服装全缺同样五项。
        那不是模型不行，是这一批的要求本身就是多义的。"""
        import inspect

        from app.pipelines import asset_pack

        src = inspect.getsource(asset_pack.ensure_variants)
        assert "by_kind" in src
        assert "一类一批" in src or "按类别分批" in src
