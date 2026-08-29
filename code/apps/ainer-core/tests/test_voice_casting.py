"""配音的测试。

音色的对错不在单个角色身上 —— 每个角色单看都能配得头头是道，
问题出在放到一起的时候：三个人同一把嗓子，或者少年到中年换了个演员。
所以用例都是成组的。
"""
from __future__ import annotations

import pytest

from app.pipelines.casting import (
    _RESOLVE_ORDER, _age_term, _headroom, _normalize, resolve_collisions,
)
from app.worldview.voice import (
    BOOK_MIN, IDENTITY_FIELDS, SAME_SCENE_MIN, VOCAB, VoiceSpec,
    check_collisions, check_identity_drift, derive_epoch_voice, distinctness,
    to_tts_params, vocab_brief,
)


def v(**kw) -> VoiceSpec:
    base = dict(voice_type="男声", pitch="中位", texture="圆润",
                resonance="胸腔", accent="", age_feel="青年",
                tempo="中等", energy="沉稳", condition="健康")
    base.update(kw)
    return VoiceSpec(**base)


class TestDistinctness:
    def test_identical_scores_zero(self):
        assert distinctness(v(), v())[0] == 0

    def test_voice_type_is_the_strongest_signal(self):
        """声部换了立刻能分 —— 它一项就该顶过阈值。"""
        score, _ = distinctness(v(), v(voice_type="女声"))
        assert score >= SAME_SCENE_MIN

    def test_one_step_counts_half(self):
        """音区差一档还可能混，差两档基本不会。

        不分档的话「中位 vs 偏高」会拿到和「低沉 vs 明亮高」一样的分，
        于是一堆实际听起来很像的组合被判成安全。
        """
        near = distinctness(v(pitch="中位"), v(pitch="偏高"))[0]
        far = distinctness(v(pitch="低沉"), v(pitch="明亮高"))[0]
        assert 0 < near < far

    def test_reports_where_the_difference_is(self):
        """只说「撞了」没有可操作性，要说清差在哪一项。"""
        _, diffs = distinctness(v(), v(texture="沙哑"))
        assert any("音质" in d for d in diffs)

    def test_empty_field_is_not_a_difference(self):
        """一边没填不能算「不一样」—— 那会把缺项伪装成区分度。"""
        assert distinctness(v(accent=""), v(accent=""))[0] == 0
        assert distinctness(v(accent=""), v(accent="外省口音"))[0] == 0


class TestCollisions:
    def test_same_scene_is_stricter_than_book(self):
        """第三章的店小二和第二十章的船夫撞了没人察觉，
        同一场戏里的两个人撞了立刻露馅。"""
        voices = {"a": v(), "b": v(texture="沙哑")}
        assert distinctness(voices["a"], voices["b"])[0] < SAME_SCENE_MIN
        assert distinctness(voices["a"], voices["b"])[0] >= BOOK_MIN

        assert check_collisions(voices) == []
        cols = check_collisions(voices, co_occurrence=[("酒肆", ["a", "b"])])
        assert len(cols) == 1
        assert cols[0].scope == "same_scene"
        assert cols[0].where == "酒肆"

    def test_identical_voices_always_collide(self):
        cols = check_collisions({"a": v(), "b": v()})
        assert len(cols) == 1 and cols[0].score == 0
        assert "各维度完全相同" in cols[0].as_dict()["detail"]

    def test_a_pair_is_reported_once(self):
        """同一对角色在三场戏里都同场，是一个问题不是三个。"""
        cols = check_collisions(
            {"a": v(), "b": v()},
            co_occurrence=[("一", ["a", "b"]), ("二", ["a", "b"]),
                           ("三", ["a", "b"])],
        )
        assert len(cols) == 1

    def test_solo_scene_needs_no_distinction(self):
        """一个人的场次不产生同场约束。"""
        cols = check_collisions({"a": v(), "b": v(texture="沙哑")},
                                co_occurrence=[("独白", ["a"])])
        assert cols == []

    def test_worst_pair_comes_first(self):
        voices = {"a": v(), "b": v(), "c": v(texture="沙哑")}
        cols = check_collisions(
            voices, co_occurrence=[("堂上", ["a", "b", "c"])])
        assert cols[0].score == 0


class TestIdentityDrift:
    def _seq(self, *specs):
        return [(f"e{i}", kind, s) for i, (kind, s) in enumerate(specs)]

    def test_gear_epoch_may_not_move_the_register(self):
        """换了把刀嗓子不会变。只有年龄和伤病能动音区。"""
        issues = check_identity_drift(
            self._seq(("gear", v()), ("gear", v(pitch="低沉"))))
        assert len(issues) == 1 and issues[0]["field"] == "pitch"

    def test_age_may_move_the_register(self):
        """男孩变声后降下去 —— 判成漂移的话，
        「少年林凡」到「中年林凡」会被当成两个人，
        而那恰恰是配得对的情况。"""
        assert check_identity_drift(
            self._seq(("age", v(pitch="偏高")), ("age", v(pitch="低沉")))) == []

    def test_texture_change_without_injury_is_drift(self):
        issues = check_identity_drift(
            self._seq(("age", v()), ("age", v(texture="沙哑"))))
        assert len(issues) == 1
        assert issues[0]["field"] == "texture"

    def test_injury_may_change_texture(self):
        """断喉之后嗓子哑了是演化，不是配错人。"""
        assert check_identity_drift(
            self._seq(("age", v()), ("injury", v(texture="沙哑")))) == []

    def test_age_may_change_voice_type(self):
        """变声期是唯一允许声部变的情形。"""
        assert check_identity_drift(
            self._seq(("age", v(voice_type="童声")),
                      ("age", v(voice_type="男声")))) == []

    def test_epoch_fields_never_count_as_drift(self):
        """年龄感、语速、力度本来就该随时期变。"""
        assert check_identity_drift(
            self._seq(("age", v(age_feel="少年", tempo="偏快", energy="充沛")),
                      ("age", v(age_feel="老年", tempo="偏慢",
                                energy="虚弱")))) == []

    def test_compares_adjacent_not_against_baseline(self):
        """变声之后就该以变声后的为准。都跟童声比会一直报警。"""
        assert check_identity_drift(
            self._seq(("age", v(voice_type="童声")),
                      ("age", v(voice_type="男声")),
                      ("age", v(voice_type="男声")))) == []


class TestEpochDerivation:
    def test_identity_is_copied_verbatim(self):
        """**这是「同一个嗓子」的唯一保证。**

        重新问一遍模型的话，它会重新描述一遍嗓子，于是漂了 ——
        三个时期下来就是三个演员。
        """
        base = v(texture="沙哑", resonance="喉音", accent="乡音")
        out = derive_epoch_voice(base, age_feel="中年")
        for f in IDENTITY_FIELDS:
            if f == "pitch":
                continue          # 音区随年龄走，见下一条
            assert getattr(out, f) == getattr(base, f), f

    def test_age_lowers_pitch_and_slows_down(self):
        old = derive_epoch_voice(v(age_feel="青年"), age_feel="老年")
        assert VOCAB["pitch"].index(old.pitch) < VOCAB["pitch"].index("中位")
        assert VOCAB["tempo"].index(old.tempo) < VOCAB["tempo"].index("中等")
        assert VOCAB["energy"].index(old.energy) < VOCAB["energy"].index("沉稳")

    def test_youth_raises_pitch(self):
        young = derive_epoch_voice(v(age_feel="青年"), age_feel="少年")
        assert VOCAB["pitch"].index(young.pitch) > VOCAB["pitch"].index("中位")

    def test_childhood_switches_voice_type(self):
        """变声前后确实是两种声部 —— 这也正是漂移检测放行 age 改声部的原因。"""
        kid = derive_epoch_voice(v(voice_type="男声"), age_feel="童年")
        assert kid.voice_type == "童声"
        assert kid.pitch == "明亮高"       # 童声本来就在高音区
        assert check_identity_drift(
            [("child", "age", kid), ("adult", "age", v())]) == []

    def test_injury_roughens_and_weakens(self):
        hurt = derive_epoch_voice(v(), age_feel="壮年", kind="injury")
        assert hurt.texture == "沙哑"
        assert hurt.condition == "带伤"

    def test_derivation_never_runs_off_the_scale(self):
        """老年 + 已经最低的音区，不该越界。"""
        out = derive_epoch_voice(v(pitch="低沉", tempo="迟缓", energy="虚弱"),
                                 age_feel="老年")
        assert out.pitch in VOCAB["pitch"]
        assert out.tempo in VOCAB["tempo"]
        assert out.energy in VOCAB["energy"]


class TestResolve:
    def test_leading_role_never_moves(self):
        """主角的嗓子是锚。改它等于换主演，而改配角没人察觉。"""
        voices = {"hero": v(), "extra": v()}
        before = voices["hero"].as_dict()
        changes = resolve_collisions(
            voices, {"hero": 200, "extra": 3},
            [("客栈", ["hero", "extra"])],
        )
        assert voices["hero"].as_dict() == before
        assert changes and changes[0]["entity"] == "extra"

    def test_resolution_actually_separates(self):
        voices = {"a": v(), "b": v(), "c": v()}
        resolve_collisions(voices, {"a": 90, "b": 50, "c": 10},
                           [("堂上", ["a", "b", "c"])])
        assert check_collisions(voices,
                                co_occurrence=[("堂上", ["a", "b", "c"])]) == []

    def test_voice_type_is_never_touched(self):
        """把男角色改成女声不是消解撞声，是改人物。"""
        assert "voice_type" not in _RESOLVE_ORDER
        voices = {"a": v(), "b": v()}
        resolve_collisions(voices, {"a": 9, "b": 1}, [("场", ["a", "b"])])
        assert voices["b"].voice_type == "男声"

    def test_each_step_moves_exactly_one_dimension(self):
        """一步改三项会过度偏离模型基于原文的判断 ——
        那份判断多半是对的，只是没考虑到旁边还站着一个人。

        两个**完全相同**的音色确实需要挪两下才够拉开，
        但每一下都是单独一项、改完立刻重测，而不是一把梭。
        """
        voices = {"a": v(), "b": v()}
        changes = resolve_collisions(voices, {"a": 9, "b": 1},
                                     [("场", ["a", "b"])])
        assert all(isinstance(c["field"], str) for c in changes)
        assert len({c["field"] for c in changes}) == len(changes)

    def test_stops_as_soon_as_separated(self):
        """够了就停，不继续改 —— 每多改一项就离原判断更远一点。"""
        voices = {"a": v(), "b": v(texture="沙哑")}
        changes = resolve_collisions(voices, {"a": 9, "b": 1},
                                     [("场", ["a", "b"])])
        assert len(changes) == 1

    def test_headroom_avoids_values_taken_by_peers(self):
        assert _headroom("texture", "圆润", {"沙哑", "清亮"}) not in (
            "沙哑", "清亮", "圆润")

    def test_headroom_prefers_the_nearest_step(self):
        """有序维度挪得越少越贴近原判断。"""
        assert _headroom("pitch", "中位", set()) in ("偏低", "偏高")


class TestNormalize:
    def test_keeps_exact_terms(self):
        spec, bad = _normalize({"voice_type": "男声", "pitch": "低沉"})
        assert spec.voice_type == "男声" and not bad

    def test_recovers_a_term_buried_in_prose(self):
        """「低沉的」比「低沉」多一个字，丢掉会让整条作废。"""
        spec, bad = _normalize({"pitch": "低沉的嗓音"})
        assert spec.pitch == "低沉" and not bad

    def test_reports_genuinely_unknown_values(self):
        _, bad = _normalize({"texture": "空灵飘渺"})
        assert bad and "音质" in bad[0]

    def test_accent_is_free_text(self):
        """口音没有固定表 —— 「外省口音」在帝俄晚期和维多利亚英国
        不是同一个东西。"""
        spec, bad = _normalize({"accent": "外省口音"})
        assert spec.accent == "外省口音" and not bad

    def test_missing_lists_only_required_fields(self):
        """口音留空和状态正常都是有效答案，写「无」反而是噪声。"""
        spec = VoiceSpec(voice_type="男声", pitch="中位", texture="圆润",
                         resonance="胸腔", age_feel="青年", tempo="中等",
                         energy="沉稳")
        assert spec.missing() == []


class TestTtsParams:
    def test_offsets_are_relative_not_absolute(self):
        """绝对值绑定采样率与引擎默认音高，换引擎就全错。"""
        assert to_tts_params(v(pitch="中位"))["pitch_shift"] == 0.0
        assert to_tts_params(v(pitch="低沉"))["pitch_shift"] < 0
        assert to_tts_params(v(tempo="中等"))["rate"] == 1.0
        assert to_tts_params(v(tempo="急促"))["rate"] > 1.0

    def test_style_prompt_carries_the_full_description(self):
        p = to_tts_params(v(texture="沙哑", accent="乡音"))
        assert "沙哑" in p["style_prompt"] and "乡音" in p["style_prompt"]

    def test_voice_id_only_when_bound_to_an_engine(self):
        """没绑引擎时不该凭空给一个 voice_id。"""
        assert "voice_id" not in to_tts_params(v())
        assert to_tts_params(v(), voice_ref="qwen-female-3")["voice_id"] == \
            "qwen-female-3"

    def test_child_maps_to_child_not_a_gender(self):
        assert to_tts_params(v(voice_type="童声"))["gender"] == "child"


class TestAgeTerm:
    @pytest.mark.parametrize("text,expect", [
        ("弱冠之年", "青年"), ("而立", "壮年"), ("不惑之年", "中年"),
        ("垂髫小儿", "童年"), ("十六七岁的少年", "少年"), ("花甲老者", "老年"),
    ])
    def test_reads_classical_age_words(self, text, expect):
        assert _age_term(text) == expect

    def test_unknown_returns_empty_not_a_guess(self):
        """猜错年龄会把音区、语速、力度一起带偏。宁可不改。"""
        assert _age_term("身形挺拔") == ""


def test_vocab_brief_lists_every_field():
    """术语表同时是给模型的词汇和验收白名单 —— 漏一项，
    那一项就会既没词可选、又通不过验收。"""
    brief = vocab_brief()
    for f in VOCAB:
        assert f in brief


class TestTurnWindow:
    """剧本没分场时的同场近似。

    散文线的 script_block.scene_id 是空的。若因此退化成只有宽阈值，
    五个角色同一把嗓子也不会报警 —— 而那正是最该报的情况。
    """

    def test_window_groups_are_pairwise_usable(self):
        """相邻发言窗口产出的组，能让同场阈值真正生效。"""
        voices = {"a": v(), "b": v(texture="沙哑")}
        assert check_collisions(voices) == []          # 宽阈值放行
        cols = check_collisions(
            voices, co_occurrence=[("第 3–8 句对白", ["a", "b"])])
        assert len(cols) == 1 and cols[0].scope == "same_scene"


class TestVoiceTypeStaysASexCategory:
    """声部只回答「哪一类嗓子」。

    这里曾经有一项「苍老中性」，实跑时老周（一个男人）被配成它，
    落到 TTS 就是 gender=neutral —— 按语音库选声的引擎可能给他一把女声。
    苍老由年龄感、音质、共鸣表达，那三项本来就在表里。
    """

    def test_every_voice_type_maps_to_a_definite_category(self):
        from app.worldview.voice import VOICE_TYPES, _GENDER
        for t in VOICE_TYPES:
            assert t in _GENDER, f"{t} 没有对应的选声类别"
            assert _GENDER[t] != "neutral", f"{t} 映到 neutral 等于不选"

    def test_old_age_is_expressible_without_a_neutral_type(self):
        old = v(voice_type="男声", age_feel="老年", texture="干涩",
                resonance="喉音")
        assert to_tts_params(old)["gender"] == "male"
        assert "老年" in old.describe() and "干涩" in old.describe()


class TestEpochOrdering:
    """时期必须按章节先后比，不能按 key 的字母序。

    实跑时沈砚有 baseline / prime / wounded / youth 四期。
    按字母序会拿「wounded」去比「youth」—— 顺序反了，
    「断腕后沙哑」被读成「少年时嗓子好端端地变回来了」，
    报出一个方向完全相反的假漂移。
    """

    def test_chronological_order_finds_no_drift(self):
        seq = [
            ("youth", "age", v(age_feel="少年", texture="浑厚")),
            ("prime", "age", v(age_feel="壮年", texture="浑厚")),
            ("wounded", "injury", v(age_feel="中年", texture="沙哑")),
        ]
        assert check_identity_drift(seq) == []

    def test_alphabetical_order_would_report_a_phantom(self):
        """把同样三期按字母序排，就会报出假漂移 —— 这是排序错时的症状。"""
        seq = [
            ("prime", "age", v(age_feel="壮年", texture="浑厚")),
            ("wounded", "injury", v(age_feel="中年", texture="沙哑")),
            ("youth", "age", v(age_feel="少年", texture="浑厚")),
        ]
        assert len(check_identity_drift(seq)) == 1


class TestVoiceForKeying:
    """`voice_for` 传空必须返回 None，不能当成旁白。

    「这是旁白」和「说话人没解析出来」是两件事。实跑时把两者混在一起，
    九条说话人未知的对白全都静悄悄拿了旁白的音色，missing_voice 还报空 ——
    数据上一切正常，听起来是旁白在自问自答。
    """

    def test_empty_key_returns_none(self):
        from app.pipelines.casting import voice_for
        assert voice_for(None, "", "wp_x") is None
        assert voice_for(None, None, "wp_x") is None

    def test_callers_name_the_narrator_explicitly(self):
        """两条产线都必须显式传 NARRATOR，靠传空是查不出来的写法。"""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent / "app" / "pipelines"
        for name in ("audio_compose.py", "audiobook.py"):
            src = (root / name).read_text(encoding="utf-8")
            assert "casting.NARRATOR," in src, name


class TestUnorderableEpochsAreNotJudged:
    """排不出先后就不查漂移。

    素材时期被删后，音色行成了孤儿：章节序号查不到，排序退回字母序，
    于是「断腕后沙哑」被读成「少年时嗓子好端端地变回来了」，
    报出方向完全相反的假漂移。
    报不出来比报错的好 —— 错的告警会让人去改本来对的东西。
    """

    def test_audit_skips_and_says_so(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "pipelines" / "casting.py").read_text("utf-8")
        body = src[src.index("def audit_casting"):]
        assert "unorderable" in body
        assert "排不出先后" in body

    def test_derive_removes_orphan_rows(self):
        """时期没了，它的音色行也该走。"""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "pipelines" / "casting.py").read_text("utf-8")
        body = src[src.index("def cast_epoch_voices"):]
        assert "orphaned" in body and "db.delete(row)" in body
