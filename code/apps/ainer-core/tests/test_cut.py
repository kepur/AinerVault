"""剪辑台 —— 第三种投影：给眼睛和耳朵。

它回答的是前两种（给程序的 JSON、给人手搓的提示词）回答不了的那个问题：
**拼起来到底是什么样**。分镜看着合理、每张图单看都不错、每句配音单听都对，
连起来却可能这一镜停三秒没事发生、下一镜台词还没说完就切了。
"""
from __future__ import annotations

from app.pipelines import cut


class TestTracks:
    def test_film_has_no_narration_track(self):
        """完整朗读只属于有声书；电影叙述必须转成画面。"""
        ids = [t[0] for t in cut.TRACKS]
        assert "dialogue" in ids
        assert "narration" not in ids

    def test_visual_track_comes_first(self):
        """先画面后声音，声音里对白在最上层 —— 剪辑软件也是这么排的。"""
        assert cut.TRACKS[0][0] == "video"
        assert cut.TRACKS[0][2] == "visual"
        assert all(t[2] == "audio" for t in cut.TRACKS[1:])

    def test_bgm_sits_at_the_bottom(self):
        ids = [t[0] for t in cut.TRACKS]
        assert ids[-1] == "bgm"


class TestBeat:
    """旁白拿掉后，只有旁白的镜头失去了时长依据。"""

    class _Shot:
        duration_ms = 9000

    class _Motion:
        camera_move = "slow push in"
        subject_move = None

    def test_beat_is_within_watchable_range(self):
        """低于两秒观众来不及看清，高于五秒开始觉得卡住。"""
        ms = cut._beat_ms(self._Shot(), None)
        assert cut._BEAT_MIN <= ms <= cut._BEAT_MAX

    def test_existing_story_information_is_not_crushed_to_default(self):
        """分镜已经按译本信息量估出 9 秒，不能退回固定 2.6 秒；
        单镜上限由后面的拆机位规则处理。"""
        assert cut._beat_ms(self._Shot(), self._Motion()) == cut._BEAT_MAX

    def test_thousand_units_targets_three_to_ten_minutes(self):
        pace = cut.runtime_window("字" * 1000)
        assert pace["min_ms"] == 180_000
        assert pace["max_ms"] == 600_000


class TestMixLevels:
    def test_dialogue_is_the_loudest(self):
        """环境声与配乐若不压，对白会被盖住 ——
        而对白是唯一承载信息的一轨。"""
        g = cut._GAIN_DB
        assert g["dialogue"] == 0.0
        for other in ("sfx", "ambience", "bgm"):
            assert g[other] < g["dialogue"]

    def test_beds_are_well_below_speech(self):
        assert cut._GAIN_DB["ambience"] <= -12
        assert cut._GAIN_DB["bgm"] <= -12


class TestRenderContract:
    def test_audio_is_padded_not_video_truncated(self):
        """最后一句台词往往在片尾之前就说完了，音轨于是比画面短。
        用 -shortest 会把结尾几镜整个切掉 —— 而被切掉的恰恰是安静的
        收尾镜，不播到最后根本发现不了。实跑里 168.7s 被切成 161.9s。
        """
        import inspect

        # **只看真正的代码行。** 注释里也写着「不能用 -shortest」，
        # 整段源码去 in 的话会被自己的解释文字撞上 ——
        # 这个坑之前在 shot.description 撞 docstring 上踩过一次
        code = [ln for ln in inspect.getsource(cut.render).splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        src = "\n".join(code)
        assert "-shortest" not in src
        assert "total_s" in src and '"-t"' in src
        assert "apad" in inspect.getsource(cut._mix_audio)

    def test_adelay_is_given_per_channel(self):
        """adelay 只给一个值时，立体声素材只有左声道被延迟，
        右声道从 0 开始 —— 听起来像回声，而时间码看着完全正确。"""
        import inspect

        src = inspect.getsource(cut._mix_audio)
        assert "adelay={delay}|{delay}" in src

    def test_only_local_media_is_used(self):
        """外部地址一律不下载 —— 导出要在几分钟内跑完，
        一条外链卡住就是整段导出卡住，且看不出卡在哪个素材上。"""
        import inspect

        src = inspect.getsource(cut._local)
        assert '"/media/" not in url' in src

    def test_black_shots_are_reported(self):
        """一支片子里几秒黑屏很容易被当成转场，
        而它其实是「这一镜什么都没有」。"""
        import inspect

        src = inspect.getsource(cut.render)
        assert "black_shots" in src

    def test_preview_cannot_masquerade_as_final(self):
        """静帧交叉溶解可以审节奏，但不是电影成片。"""
        import inspect

        from app.api.v2 import audio

        src = inspect.getsource(audio.render_cut)
        assert "NOT_FINAL_READY" in src
        assert "production_ready" in src

    def test_render_is_persisted_as_chapter_output(self):
        import inspect

        src = inspect.getsource(cut.render)
        assert '"purpose": "final_cut"' in src
        assert "asset_id" in src


class TestVideoGenerationGate:
    def test_video_never_falls_back_to_camera_only(self):
        import inspect

        src = inspect.getsource(cut.generate_videos)
        assert "缺经验收的英文物理运动" in src
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.strip().startswith("#"))
        assert "or _camera_text" not in code


class TestFilmProjection:
    def test_old_voiceover_calls_are_rejected(self):
        import inspect

        assert "电影时间线不允许旁白" in inspect.getsource(cut.build_timeline)

    def test_final_quality_reads_production_inputs(self):
        import inspect

        src = inspect.getsource(cut.build_timeline)
        assert "incomplete_crew" in src
        assert "invalid_motion" in src
        assert "stale_prompts" in src


class TestAtMs:
    class _Spec:
        def __init__(self, at):
            self.params_json = {"at_ms": at} if at is not None else {}

    def test_clamped_into_the_shot(self):
        assert cut._at_ms(self._Spec(99999), 4000) <= 3800

    def test_missing_position_goes_to_the_head(self):
        """取不到就放开头 —— 不要编一个位置出来。"""
        assert cut._at_ms(self._Spec(None), 4000) == 0

    def test_garbage_does_not_raise(self):
        assert cut._at_ms(self._Spec("早一点"), 4000) == 0
