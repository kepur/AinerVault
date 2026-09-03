"""小说 → 剧本：把一段话拆成台词与动作。

**这是整条影片线的关键一步，而它原来不存在。**
块级分类只回答「这一段是不是对白段」，回答不了「哪几个字是说出口的」。
于是配音把整段都念了 —— 包括「老周把碗放在栏杆上」。
听起来就是有旁白，而数据上这一条明明标着 dialogue。
"""
from __future__ import annotations

from app.pipelines import screenplay as sp


class TestQuoteSplit:
    def test_speech_and_action_interleaved(self):
        """小说里台词和叙述是混在一起的，一段可能有两句台词夹一个动作。"""
        s = sp.split_speech("「镖师不跑。」老周把碗放在栏杆上。「要跑，第一趟就跑了。」")
        assert s.speech == ["镖师不跑。", "要跑，第一趟就跑了。"]
        assert "老周把碗放在栏杆上" in s.action
        assert not s.uncertain

    def test_russian_guillemets(self):
        s = sp.split_speech(
            "«Охранник не убегает». Старый Чжоу поставил чашку. «Если бы бежал».")
        assert len(s.speech) == 2
        assert "поставил чашку" in s.action

    def test_english_double_quotes(self):
        s = sp.split_speech('"The box will not open," he said, setting down the crowbar.')
        assert s.speech and "box will not open" in s.speech[0]
        assert "crowbar" in s.action

    def test_pure_narration_has_no_speech(self):
        """整段没有引号 —— 这不是「拆不动」，它拆得很干净：没人说话。"""
        s = sp.split_speech("沈砚没点灯。他把腰刀横在膝上，坐在门后听。")
        assert s.speech == []
        assert s.action.startswith("沈砚没点灯")
        assert not s.uncertain

    def test_unclosed_quote_does_not_swallow_the_rest(self):
        """有左引号无右引号时不能猜到段尾 ——
        那会把后面的动作描写整段算成台词，配音就把它念出来。"""
        s = sp.split_speech("「他说了什么 然后老周转身走了。")
        assert "老周转身走了" not in " ".join(s.speech)

    def test_empty(self):
        assert sp.split_speech("").speech == []
        assert sp.split_speech(None).action == ""


class TestDashSplit:
    def test_attribution_marks_the_boundary(self):
        """破折号体里，归属小句是唯一可靠的边界信号。"""
        s = sp.split_speech("— Не здорово, — отозвался Шень Янь. — Ты здесь третий день.")
        assert s.speech == ["Не здорово"]
        assert "отозвался" in s.action

    def test_leading_dash_is_skipped_before_searching(self):
        """不跳过行首那个破折号的话，正则会咬住它，
        head 变成空串、台词整句丢掉，而报出来的理由指向完全错误的地方。"""
        s = sp.split_speech("— Это я, — сказал он.")
        assert s.speech == ["Это я"]

    def test_no_attribution_is_reported_not_guessed(self):
        """拆不动就说拆不动 —— 猜一个然后让配音念错更糟。"""
        s = sp.split_speech("— Просто иду мимо.")
        assert s.speech == []
        assert "归属小句" in s.uncertain

    def test_trailing_dash_content_is_flagged(self):
        """归属之后还有破折号：可能是第二句台词，也可能是「不是」的意思。
        分不开，说出来。"""
        s = sp.split_speech("— Это я, — сказал он. — А он — нет.")
        assert s.uncertain


class TestShotDuration:
    """首尾帧之间超过五秒就会审美疲劳 —— 走路、海浪、粒子，
    五秒之内是一个动作，五秒之后是同一个动作重复。
    这不是审美偏好，是 i2v 的能力边界。"""

    def test_static_capped_at_five(self):
        ms, why = sp.clamp_shot_ms(9800, action=False)
        assert ms == sp.STATIC_MAX_MS
        assert "疲劳" in why

    def test_action_capped_shorter(self):
        ms, _ = sp.clamp_shot_ms(4200, action=True)
        assert ms == sp.ACTION_MAX_MS
        assert sp.ACTION_MAX_MS < sp.STATIC_MAX_MS

    def test_too_short_is_lifted(self):
        ms, why = sp.clamp_shot_ms(400, action=False)
        assert ms == sp.MIN_MS and "看清" in why

    def test_in_range_untouched(self):
        assert sp.clamp_shot_ms(3800, action=False) == (3800, "")

    def test_action_words_both_languages(self):
        """分镜的描述可能是中文也可能是英文。"""
        assert sp.is_action_beat("裴无咎挥刀砍下")
        assert sp.is_action_beat("he leaps across the gap")
        assert not sp.is_action_beat("沈砚坐在门后听")


class TestJunkGuard:
    """解析成功不等于内容干净。"""

    def test_model_invented_placeholder(self):
        """我们给它 {{CHAR:xxx}}，它还回来 ⟦E1⟧ ——
        restore_placeholders 只认 {{}}，还原不了，垃圾直接进成品。"""
        assert "⟦E1⟧" in sp.translation_junk("— Это я. ⟦E1⟧ сказал.")

    def test_json_skeleton_fragment(self):
        """JSON 解出来了、字段也在，只是值里混进了骨架本身。
        逐条看译文时眼睛会自动跳过句尾那串括号。"""
        assert sp.translation_junk("Он шагнул вперёд. }]}]}]}")

    def test_unrestored_own_placeholder(self):
        assert sp.translation_junk("Он сказал {{CHAR:abc123}} тихо.")

    def test_clean_text_passes(self):
        assert sp.translation_junk("Он поставил чашку на перила.") == []


class TestQuoteLossInTranslation:
    """中译英之后「不巧。」变成了裸的 Not so fortunate. —— 引号没了。

    拆不出台词的后果是这条对白**一句配音都没有**，
    比混进旁白更糟：观众只会觉得这个角色突然哑了。
    """

    def test_dialogue_without_quotes_becomes_speech(self):
        s = sp.split_speech("Not so fortunate.", is_dialogue=True, source="「不巧。」")
        assert s.speech == ["Not so fortunate."]
        assert s.uncertain

    def test_lost_quotes_are_named_as_a_translation_defect(self):
        """原文有引号而译文没有 —— 那是译文的问题，不是「这段没人说话」。"""
        s = sp.split_speech("Not so fortunate.", is_dialogue=True, source="「不巧。」")
        assert "译文丢了引号" in s.uncertain

    def test_source_without_quotes_reads_differently(self):
        s = sp.split_speech("He said nothing.", is_dialogue=True,
                            source="他什么也没说。")
        assert s.speech and "译文丢了引号" not in s.uncertain

    def test_narration_block_is_unaffected(self):
        """非对白块没有引号就是真的没人说话，不该被当成台词。"""
        s = sp.split_speech("沈砚没点灯。他把腰刀横在膝上。")
        assert s.speech == [] and not s.uncertain

    def test_has_quotes_helper(self):
        assert sp.has_quotes("「不巧。」")
        assert sp.has_quotes('"Not so fortunate."')
        assert not sp.has_quotes("Not so fortunate.")
