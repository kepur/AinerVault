"""影视工种规格与验收的测试。

这套规格存在的理由是一次 A/B：同一道灯光题、同一个弱模型
    无规格  「柔和侧光」「低对比度」「阴暗、紧张」
    有规格  「后方 60 度硬光」「月光 7000K，窗内漏灯 2700K」「高反差，暗部细节保留」

前者对图像生成没有任何指导价值 —— 它没说光从哪来、有多硬、照到什么。
差别不在模型，在**有没有人告诉它「柔和侧光」不算一个灯光方案**。
"""
from __future__ import annotations

import pytest

from app.pipelines.crew_sheets import _check, _compose, _dim_key, _spec_schema
from app.worldview.crew import CREW, CREW_BY_ROLE, brief_for


class TestSpecShape:
    @pytest.mark.parametrize("spec", CREW, ids=lambda s: s.role)
    def test_every_spec_is_complete(self, spec):
        """四件事缺一不可：维度定义要填什么，判据定义什么算合格，
        反例定义什么不合格，术语给弱模型一份词汇表。
        """
        assert spec.dimensions, f"{spec.role} 没有必填维度"
        assert spec.criteria, f"{spec.role} 没有合格判据"
        assert spec.bad, f"{spec.role} 没有反例 —— 只说「要具体」没用"
        assert spec.purpose, f"{spec.role} 没说清自己在解决什么问题"

    @pytest.mark.parametrize("spec", CREW, ids=lambda s: s.role)
    def test_brief_carries_everything(self, spec):
        """提示词里必须带上反例。规格与提示词共用一份定义 ——
        分开写会变成「按一套标准生成、按另一套验收」。
        """
        brief = spec.brief()
        assert spec.dimensions[0].split("：")[0] in brief
        assert spec.bad[0][:8] in brief

    @pytest.mark.parametrize("spec", CREW, ids=lambda s: s.role)
    def test_dimension_keys_are_unique(self, spec):
        """维度是 schema 的唯一来源，键撞了会让字段互相覆盖。"""
        keys = [_dim_key(d) for d in spec.dimensions]
        assert len(keys) == len(set(keys)), f"{spec.role} 的维度键有重复：{keys}"

    def test_schema_follows_dimensions(self):
        """加一个维度不该需要另外改 schema —— 两边会走偏。"""
        spec = CREW_BY_ROLE["lighting"]
        schema = _spec_schema(spec)
        assert len(schema["properties"]) == len(spec.dimensions)
        assert schema["required"] == list(schema["properties"])


class TestAcceptance:
    LIGHTING = CREW_BY_ROLE["lighting"]

    def _payload(self, **over):
        base = {
            _dim_key(d): "左前方 45 度硬光，只扫过刀身"
            for d in self.LIGHTING.dimensions
        }
        base.update(over)
        return base

    def test_complete_payload_passes(self):
        missing, rejected = _check(self.LIGHTING, self._payload())
        assert not missing and not rejected

    def test_missing_dimension_is_caught(self):
        p = self._payload()
        p[_dim_key(self.LIGHTING.dimensions[0])] = ""
        missing, _ = _check(self.LIGHTING, p)
        assert len(missing) == 1

    def test_too_short_counts_as_missing(self):
        """「有」「无」这种回答等于没填。"""
        p = self._payload(**{_dim_key(self.LIGHTING.dimensions[2]): "有"})
        missing, _ = _check(self.LIGHTING, p)
        assert missing

    @pytest.mark.parametrize("val", [
        "适当的补光让画面更自然", "营造电影感的光影效果", "根据需要调整明暗",
    ])
    def test_empty_words_are_rejected(self, val):
        """空洞形容词看着像描述，实际不含信息。

        「适当」「电影感」「根据需要」—— 下游拿到它们
        跟没拿到一样，而那时已经花掉了图像模型的钱。
        """
        p = self._payload(**{_dim_key(self.LIGHTING.dimensions[1]): val})
        _, rejected = _check(self.LIGHTING, p)
        assert rejected

    def test_concrete_value_is_not_rejected(self):
        p = self._payload(**{
            _dim_key(self.LIGHTING.dimensions[1]): "无补光，暗部保留轮廓细节"})
        _, rejected = _check(self.LIGHTING, p)
        assert not rejected

    def test_missing_payload_entirely(self):
        missing, _ = _check(self.LIGHTING, {})
        assert len(missing) == len(self.LIGHTING.dimensions)


class TestCompose:
    def test_follows_dimension_order(self):
        """拼接顺序跟着维度声明走，不跟着模型返回的键序 ——
        否则同一份数据两次拼出的提示词不同，图就不稳。
        """
        spec = CREW_BY_ROLE["cinematography"]
        payload = {_dim_key(d): f"值{i}" for i, d in enumerate(spec.dimensions)}
        out = _compose(spec, payload)
        assert out.index("值0") < out.index("值1")

    def test_skips_blank(self):
        spec = CREW_BY_ROLE["editing"]
        payload = {_dim_key(spec.dimensions[0]): "3.2 秒，对白长度决定"}
        out = _compose(spec, payload)
        assert "3.2 秒" in out
        assert out.count("；") == 0
