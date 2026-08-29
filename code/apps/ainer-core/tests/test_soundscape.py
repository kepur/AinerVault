"""声景编译。

这一层修的是一处「存了没人读」：声音制作单里每一镜都写清了
环境底噪、音效点、画外声、配乐，而音频编译走的是另一条路 ——
它去找音频素材，找不到就静默跳过。全库跑下来 AudioSpec 里
只有对白和旁白，而制作单里明明写着。
"""
from __future__ import annotations

import pytest

from app.pipelines.soundscape import _at_ms, _is_none, _split_cues


class TestTiming:
    """时间点是这一声有没有对上画面的全部区别。"""

    @pytest.mark.parametrize("text,ms", [
        ("第 2 秒，油布被掀开的窸窣", 2000),
        ("第2秒 刀出鞘", 2000),
        ("1.5s scabbard scrape", 1500),
        ("at 0:03 the door creaks", 3000),
        ("第 12 秒", 12000),
    ])
    def test_reads_a_cue_time(self, text, ms):
        assert _at_ms(text) == ms

    def test_no_time_means_no_time(self):
        """**宁可没有也不要编一个** —— 编错的时间点会让音效对不上画面，
        而那比没有音效更刺耳。"""
        assert _at_ms("门被推开的声音") is None
        assert _at_ms("") is None

    def test_a_bare_number_is_not_a_timestamp(self):
        """「三个人的脚步」里的三不是时间。"""
        assert _at_ms("三个人的脚步声") is None


class TestNegation:
    """「不要配乐」是决定，不是缺项。

    当成缺项处理会得到一段谁也没要的背景音乐，
    而静默常常是设计的一部分。
    """

    @pytest.mark.parametrize("text", [
        "无", "不用配乐", "没有环境音", "none", "no music", "silence",
    ])
    def test_negations_are_recognised(self, text):
        assert _is_none(text)

    @pytest.mark.parametrize("text", [
        "风声，远处的更漏", "low wind and distant drum", "",
    ])
    def test_real_content_is_not_negation(self, text):
        assert not _is_none(text)


class TestCueSplit:
    def test_splits_on_semicolons_and_newlines(self):
        out = _split_cues("第2秒 刀出鞘；第5秒 门轴吱呀\n第8秒 脚步远去")
        assert len(out) == 3

    def test_does_not_split_on_commas(self):
        """「油布被掀开的窸窣，很轻」里的逗号是修饰 ——
        拆了会得到半句话。"""
        out = _split_cues("油布被掀开的窸窣，很轻")
        assert out == ["油布被掀开的窸窣，很轻"]

    def test_empty_yields_nothing(self):
        assert _split_cues("") == []
        assert _split_cues("；；") == []


class TestDimensionKeys:
    """维度键取自规格，规格改了这里要跟着改 ——
    对不上就会静默读到空值，而「没有环境音」和「读不到环境音」
    在结果上完全一样。"""

    def test_keys_exist_in_the_sound_spec(self):
        from app.pipelines.crew_sheets import _dim_key
        from app.pipelines.soundscape import (
            K_AMBIENCE, K_MUSIC, K_OFFSCREEN, K_SFX, K_SILENCE, SOUND,
        )
        keys = {_dim_key(d) for d in SOUND.dimensions}
        for k in (K_AMBIENCE, K_SFX, K_OFFSCREEN, K_SILENCE, K_MUSIC):
            assert k in keys, k

    def test_ambience_and_music_are_scene_level(self):
        """同一场只出一段环境床 —— 每镜各生成一段，
        剪在一起会听见底噪在跳，而观众对空间的连续性
        比对画面还敏感。"""
        import inspect

        from app.pipelines.soundscape import compile_soundscape

        src = inspect.getsource(compile_soundscape)
        assert "shot_id=None, scene_id=sid" in src


class TestNotDone:
    """报「0 段环境音」而不说原因，会让人以为这一场真的不需要环境音。"""

    def test_reports_missing_scenes(self):
        import inspect

        from app.pipelines.soundscape import compile_soundscape

        src = inspect.getsource(compile_soundscape)
        assert "not_done.append" in src
        assert "散文线" in src and "script:generate" in src

    def test_reports_missing_sheets_and_untimed_cues(self):
        import inspect

        from app.pipelines.soundscape import compile_soundscape

        src = inspect.getsource(compile_soundscape)
        assert "没有声音制作单" in src
        assert "没有时间点" in src
