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
        """加一个维度不该需要另外改 schema —— 两边会走偏。

        每个维度两份：中文给人审核，`_en` 给图像模型。
        """
        spec = CREW_BY_ROLE["lighting"]
        schema = _spec_schema(spec)
        assert len(schema["properties"]) == len(spec.dimensions) * 2
        assert all(f"{k}_en" in schema["properties"]
                   for k in schema["properties"] if not k.endswith("_en"))
        assert set(schema["required"]) == set(schema["properties"])
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


class TestAcceptanceBalance:
    """验收要卡住空洞，但**不能误伤精确的短答案**。

    实跑抓到过：摄影报缺「景别／机位高度／机位方位」，
    而产出里明明是「中近景」「平视」「正面」—— 最小长度 6 字
    把这套规格最想要的那种回答全判成了缺失。

    术语表在生成时是给模型的词汇，在验收时是白名单 —— 一物两用。
    """

    CASES = {
        "lighting": ["前侧光 硬光", "无补光", "无", "月光", "5600K", "高反差"],
        "cinematography": ["中近景", "低于视平线", "正面", "50mm 浅景深",
                           "固定", "居中"],
        "editing": ["1.9 秒，对白长度", "静止起幅", "切在动作中", "硬切",
                    "比前镜快"],
    }

    @pytest.mark.parametrize("role", list(CASES))
    def test_short_but_precise_passes(self, role):
        spec = CREW_BY_ROLE[role]
        payload = {
            _dim_key(d): v for d, v in zip(spec.dimensions, self.CASES[role])
        }
        missing, _ = _check(spec, payload)
        assert not missing, f"{role} 误判了精确的短答案：{missing}"

    def test_explicit_negative_is_a_decision(self):
        """「无补光」「机位固定」是做出了决定，不是没填。

        「有没有」类的维度本来就允许回答「没有」。
        """
        spec = CREW_BY_ROLE["lighting"]
        payload = {_dim_key(d): "有内容占位符" for d in spec.dimensions}
        payload[_dim_key(spec.dimensions[1])] = "无"
        missing, _ = _check(spec, payload)
        assert not missing

    def test_vague_still_caught(self):
        """放宽短答案不等于放过空洞的 —— 两者必须都成立。"""
        spec = CREW_BY_ROLE["lighting"]
        payload = {
            _dim_key(d): v for d, v in zip(
                spec.dimensions,
                ["柔和侧光", "适当补光", "有", "", "暖", "明暗对比强烈"])
        }
        missing, _ = _check(spec, payload)
        assert missing, "空洞回答不该通过"

    @pytest.mark.parametrize("spec", CREW, ids=lambda s: s.role)
    def test_lexicon_covers_dimension_options(self, spec):
        """维度里列举的选项必须在术语表里有一份。

        列在维度描述里而术语表没有，那些回答就会因为太短被判缺失 ——
        「正面」「低于视平线」都栽在这上面过。
        """
        flat = {w for words in spec.lexicon.values() for w in words}
        missing = []
        for dim in spec.dimensions:
            tail = dim.split("：")[-1]
            # 「从哪个动作／状态开始」是一句说明，不是选项表 ——
            # 两段都很短，光看长度分不出来。可靠的判据是**疑问词**：
            # 枚举项不会含「哪个」「什么」「是否」。
            # 分不出来的代价是逼人往术语表里塞「状态开始」这种垃圾，
            # 而术语表同时是验收白名单，塞进垃圾等于放宽验收。
            if any(q in tail for q in ("哪个", "哪些", "什么", "是否", "多少",
                                       "为什么", "有没有", "怎么")):
                continue
            parts = [o.strip() for o in tail.replace("／", "/").split("/")]
            if len(parts) < 2 or any(len(p) > 8 for p in parts):
                continue
            for opt in parts:
                if 2 <= len(opt) <= 6 and not any(
                    opt in w or w in opt for w in flat
                ):
                    missing.append(opt)
        assert not missing, f"{spec.role} 维度里列举但术语表缺：{missing}"


class TestBilingualLexicon:
    """术语表双语，一物三用。

    给模型的词汇 / 验收白名单 / 英译对照 —— 三件事一份数据。
    模型现翻会得到「medium close shot」与「medium close-up」混用，
    而下游按字面匹配的工具会当成两个不同的值。
    """

    @pytest.mark.parametrize("spec", list(CREW))
    def test_every_term_has_an_english_side(self, spec):
        for cn, en in spec.glossary().items():
            assert en and en != cn, f"{spec.role} 的「{cn}」没有英译"

    @pytest.mark.parametrize("spec", list(CREW))
    def test_english_side_is_latin(self, spec):
        from app.pipelines.frame_compose import cjk_segments
        for cn, en in spec.glossary().items():
            assert not cjk_segments(en), f"{spec.role} 的「{cn}」英译里有中文：{en}"

    @pytest.mark.parametrize("spec", list(CREW))
    def test_terms_are_still_the_acceptance_whitelist(self, spec):
        """双语化不能让白名单失效 —— 「中近景」这种精确回答
        会因为太短被判缺失，全靠术语表救。"""
        from app.pipelines.crew_sheets import _is_term
        for term in spec.terms()[:5]:
            assert _is_term(spec, term), f"{spec.role} 的「{term}」不再被认作术语"

    def test_bilingual_brief_asks_for_two_fields(self):
        """双语版要说清两份产出的分工，并给出英译对照。"""
        spec = CREW_BY_ROLE["lighting"]
        bi, mono = spec.brief(bilingual=True), spec.brief(bilingual=False)
        assert "_en" in bi and "不认中文" in bi
        assert "_en" not in mono
        # 对照表只在双语版里给出，单语版仍是纯中文词表
        assert "hard light" in bi and "hard light" not in mono


class TestComposeEnglish:
    """英文那一份直接进出图提示词。"""

    def test_no_dimension_labels(self):
        """「Framing: medium close-up」里的 Framing 对图像模型没有意义，
        它只会把这个词也画进去。逗号分隔的短语串才是提示词的样子。"""
        from app.pipelines.crew_sheets import _compose_en, _dim_key
        spec = CREW_BY_ROLE["lighting"]
        payload = {f"{_dim_key(d)}_en": "hard key light from the left"
                   for d in spec.dimensions}
        out = _compose_en(spec, payload)
        assert "：" not in out and ":" not in out
        assert out.count(",") >= len(spec.dimensions) - 1

    def test_falls_back_to_the_glossary(self):
        """英文缺了就拿中文查表兜一下 —— 拿得到多少是多少，
        剩下的由 cjk 守门报出来，而不是静默留一段中文进提示词。"""
        from app.pipelines.crew_sheets import _compose_en, _dim_key
        spec = CREW_BY_ROLE["cinematography"]
        key = _dim_key(spec.dimensions[0])
        out = _compose_en(spec, {key: "中近景，主体居中"})
        assert "medium close-up" in out

    def test_output_is_latin_only(self):
        from app.pipelines.crew_sheets import _compose_en, _dim_key
        from app.pipelines.frame_compose import cjk_segments
        spec = CREW_BY_ROLE["editing"]
        payload = {f"{_dim_key(d)}_en": "hard cut on action"
                   for d in spec.dimensions}
        assert not cjk_segments(_compose_en(spec, payload))


class TestNewRoles:
    """三个新工种。"""

    @pytest.mark.parametrize("role", ["costume_makeup", "color_grading", "vfx"])
    def test_exists_with_full_spec(self, role):
        spec = CREW_BY_ROLE[role]
        assert len(spec.dimensions) >= 5
        assert spec.criteria and spec.bad and spec.lexicon

    def test_color_grading_comes_after_lighting(self):
        """调色是对灯光结果的再处理 —— 排在灯光之前，
        它就不知道自己在处理什么。"""
        order = [c.role for c in CREW]
        assert order.index("color_grading") > order.index("lighting")

    def test_vfx_knows_the_lighting(self):
        """光照匹配是特效成败的第一位。"""
        order = [c.role for c in CREW]
        assert order.index("vfx") > order.index("lighting")

    def test_vfx_can_say_no(self):
        """多数镜头不需要视效，而无中生有的特效是成本也是风险。"""
        spec = CREW_BY_ROLE["vfx"]
        assert "无" in spec.glossary()
        assert "不要就明说不要" in "".join(spec.dimensions)


class TestDeliveryCarriesEverything:
    """交付清单是最终出口 —— 前面做的东西不进清单，等于没做。"""

    def _src(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parent.parent
                / "app" / "pipelines" / "delivery.py").read_text("utf-8")

    def test_crew_sheets_are_in_the_manifest(self):
        """原来清单里只有首尾帧与运动，**没有制作单** ——
        下游拿不到灯光方位、材质、色调、服化、视效，只能自己猜，
        而猜出来的东西跨镜不一致。"""
        src = self._src()
        assert '"crew": _crew_block' in src

    def test_manifest_motion_is_english(self):
        """视频模型和图像模型一样不认中文。"""
        src = self._src()
        body = src[src.index("def _motion_prompt"):src.index("def _crew_block")]
        assert "motion_prompt_en" in body
        # 只看代码，不看 docstring —— 那里正解释着「为什么不回落到中文描述」
        code = "\n".join(
            ln for ln in body.splitlines()
            if not ln.strip().startswith(("#", '"""', "**", "而", "宁可", "优先", "没有"))
        )
        assert "shot.description" not in code, \
            "回落到中文描述会让清单里掺一段模型读不懂的文字"

    def test_frame_prompts_travel_with_the_images(self):
        """只给一张图的 URL，下游要改图时改不动。"""
        src = self._src()
        assert "first_frame_prompt" in src and "last_frame_prompt" in src


class TestMotionEnglish:
    def test_schema_asks_for_both(self):
        from app.pipelines.crew_sheets import MOTION_SCHEMA
        req = set(MOTION_SCHEMA["required"])
        for k in ("start_frame", "camera_move", "deltas"):
            assert k in req and f"{k}_en" in req, k

    def test_missing_english_is_reported(self):
        import inspect

        from app.pipelines.crew_sheets import generate_motion

        src = inspect.getsource(generate_motion)
        assert "没有英文运动描述" in src
