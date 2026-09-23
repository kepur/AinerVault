"""剪辑台 —— 第三种投影：给眼睛和耳朵。

它回答的是前两种（给程序的 JSON、给人手搓的提示词）回答不了的那个问题：
**拼起来到底是什么样**。分镜看着合理、每张图单看都不错、每句配音单听都对，
连起来却可能这一镜停三秒没事发生、下一镜台词还没说完就切了。
"""
from __future__ import annotations

import pathlib

import pytest

from app.pipelines import cut








class TestSampleDoesNotStealActive:
    """试片是侧产物，不能顶掉这一章的正式方案。

    踩过：给坏蛋第一章做了个 30 秒试片，215 镜的完整方案被归档，
    后台从此显示「这一章 2 个分镜 / 6.4 秒」，进度、渲染、交付全都
    转去跟那 2 镜走。做试片的人只是想看一眼效果，却把整章降级了。
    """

    def test_sample_is_draft_and_leaves_others_alone(self):
        import inspect

        from app.pipelines import sample

        src = inspect.getsource(sample.create_sample)
        assert "plan.status = DocStatus.draft" in src
        # 绝不能再有「把现有 active 全部归档」那段
        assert "DocStatus.archived" not in src, "试片不该归档别的方案"
        assert "plan.status = DocStatus.active" not in src, "试片不该占 active"


class TestPurgeOrphansDryRun:
    """试运行必须报出真跑会删的那一份。

    踩过：dry_run 报的是 freed（孤儿 asset 带走的文件），
    而真跑删的是 freed ∪ unreferenced。孤儿 asset 为 0 时，
    试运行显示「释放 0 个」，真跑却删掉 21 个文件 89MB。
    照着试运行的结论做决定的人会中招，而这正是试运行存在的唯一理由。
    """

    def test_dry_run_and_real_run_use_the_same_set(self):
        import inspect

        from app.api.v2 import library

        src = inspect.getsource(library.purge_orphans)
        # 两边都必须用 to_remove，不能各算各的
        assert "to_remove = sorted(set(freed) | set(unreferenced))" in src
        assert '"files_freed_by_purge": len(to_remove)' in src
        assert "_purge_media([f\"/media/{n}\" for n in to_remove])" in src

    def test_unowned_dead_rows_are_detected(self):
        """novel_id 为空的 asset，delete_novel 按 novel_id 删永远捞不到。

        实测库里积了 63 条（59 图 5 音频，跨越近一个月），全部无人引用，
        对应文件一直躺在磁盘上。
        """
        import inspect

        from app.api.v2 import library

        src = inspect.getsource(library.purge_orphans)
        assert "a.novel_id IS NULL" in src
        assert "stale_unowned_assets" in src
        # 引用检查必须连 JSON 数组一起查，只查标量列会误删还在用的
        assert "jsonb_array_elements_text(ref_asset_ids)" in src
        # 留缓冲，别删刚生成还没落引用的
        assert "interval '1 hour'" in src


class TestNotApplicableFields:
    """「不适用」是合法答案，不是空着。

    vfx 规格自己写着「多数镜头不需要视效，不要就明说不要」。
    模型照做：需求判定写「不需要视效…」，元素写「无」，其余四项写「不适用」。
    结果「无」过了（命中 _NEGATIVE 前缀），「不适用」没过
    —— 它只有 3 个字，短于 _MIN_LEN=6，而当时表里没有它。
    一份完全正确的单子被判成缺四个维度，连带整镜首帧生成被挡住。
    """

    def test_not_applicable_counts_as_a_real_answer(self):
        from app.pipelines.crew_sheets import _check
        from app.worldview.crew import CREW_BY_ROLE

        spec = CREW_BY_ROLE["vfx"]
        payload = {
            "需求判定": "不需要视效。本镜头为固定机位实拍，无合成元素。",
            "元素": "无", "接合": "不适用", "光照匹配": "不适用",
            "运动匹配": "不适用", "时间性": "不适用",
        }
        missing, rejected = _check(spec, payload)
        assert missing == [] and rejected == [], (missing, rejected)

    def test_blank_is_still_missing(self):
        """「不适用」可以，真空着不可以 —— 两者含义不同。"""
        from app.pipelines.crew_sheets import _check
        from app.worldview.crew import CREW_BY_ROLE

        spec = CREW_BY_ROLE["vfx"]
        payload = {"需求判定": "不需要视效。本镜头为固定机位实拍，无合成元素。",
                   "元素": "无", "接合": "", "光照匹配": "不适用",
                   "运动匹配": "不适用", "时间性": "不适用"}
        missing, _rejected = _check(spec, payload)
        assert "接合" in missing, missing


class TestEmptyWordRejection:
    """空洞词判定要看「这个词是不是在承担信息量」，不是「出现了没有」。

    踩过：调色单写「肤色保护，在冷光下保持苍白但自然的肉色，避免发绿或死灰」，
    因为含「自然的」被整条拒收 —— 可这句话里「在冷光下保持苍白」
    和「避免发绿或死灰」都是可执行的具体指令。
    35 镜里 7 镜卡在这，连带首帧生成整体被挡。
    """

    def test_concrete_prohibition_waives_the_empty_word(self):
        from app.pipelines.crew_sheets import _check
        from app.worldview.crew import CREW_BY_ROLE

        spec = CREW_BY_ROLE["color_grading"]
        key = spec.dimensions[0].split("：")[0].split(":")[0]
        payload = {k.split("：")[0].split(":")[0]: "占位内容够长了" for k in spec.dimensions}
        payload[key] = "在冷光下保持苍白但自然的肉色，避免发绿或死灰"
        _missing, rejected = _check(spec, payload)
        assert not any("自然的" in r for r in rejected), rejected

    def test_pure_hollow_answer_is_still_rejected(self):
        """豁免不等于放弃：整句都是空话的照样要拦。"""
        from app.pipelines.crew_sheets import _check
        from app.worldview.crew import CREW_BY_ROLE

        spec = CREW_BY_ROLE["color_grading"]
        key = spec.dimensions[0].split("：")[0].split(":")[0]
        payload = {k.split("：")[0].split(":")[0]: "占位内容够长了" for k in spec.dimensions}
        payload[key] = "适当调整，保持自然的整体观感"
        _missing, rejected = _check(spec, payload)
        assert any(key in r for r in rejected), rejected


class TestMotionSheetVisibility:
    """运动单的可见性验收：逐条判 deltas，别把长文拼起来判。

    is_visible_change 是为一句话的 derive_instruction 写的，它**先**查
    「明说不动」的词。那个顺序在一句话上对（「油布掀开…沈砚依然静坐」
    虽有「掀开」但整句是没变），套到运动单上就失灵：

      · subject_move 是两百字结构化描述，「从静止状态开始迈步」里的
        「静止」说的是起始状态
      · deltas 里常有一条连续性说明（「衣摆从静止垂落变为向后飘动」），
        拼成一串后那一个词把整组判死

    实测：35 镜里通过数从 8 提到 24，之前那 16 条全是误报。
    """

    def test_one_no_change_delta_does_not_poison_the_rest(self):
        from app.pipelines.crew_sheets import _motion_issues

        data = {
            "deltas": [
                "腿部姿态：从双脚站立变为右脚支撑、左脚抬起迈步",
                "衣摆状态：从静止垂落变为轻微向后飘动",   # 带「静止」的那条
            ],
            "subject_move": "老沃尔特从静止状态开始迈步",
            "camera_move": "固定机位",
        }
        issues = _motion_issues(data, "animate")
        assert not any("没有可见位移" in i for i in issues), issues

    def test_hold_shot_skips_movement_checks(self):
        """hold 是「这一镜就该不动」的明示判断，不是缺陷。"""
        from app.pipelines.crew_sheets import _motion_issues

        data = {"deltas": [], "subject_move": "保持静止", "camera_move": "固定机位",
                "start_frame": "同一画面", "end_frame": "同一画面"}
        issues = _motion_issues(data, "hold")
        assert not any("没有可见位移" in i for i in issues), issues
        assert not any("起幅与落幅相同" in i for i in issues), issues
        assert not any("差异少于 2 项" in i for i in issues), issues

    def test_animate_shot_with_truly_no_movement_still_flagged(self):
        """放宽不等于放弃：真的没动作还是要报出来。"""
        from app.pipelines.crew_sheets import _motion_issues

        data = {"deltas": ["表情保持不变", "姿态保持不变"],
                "subject_move": "他依然静坐", "camera_move": "机位不动"}
        issues = _motion_issues(data, "animate")
        assert any("没有可见位移" in i for i in issues), issues


class TestMotionKindPerShot:
    """出视频时每一镜都要按自己的动静类型构造 payload。

    踩过：`motion_kind` 在「构建 todo」的循环里算，却在「提交任务」的
    循环里用 —— 跑到那里只剩最后一镜的值，全部镜头共用同一个类型。
    最后一镜是 camera 就全体丢尾帧（首尾帧控制整批失效），
    是 animate 就给 camera 镜塞上不该有的尾帧。两种都不报错。
    """

    def test_second_loop_recomputes_motion_kind(self):
        import inspect

        from app.pipelines import cut

        src = inspect.getsource(cut.generate_videos)
        submit_at = src.index("submitted = []")
        tail = src[submit_at:]
        # 提交循环里必须自己算一次，不能吃上一个循环的残留
        assert "motion_kind = _motion_kind(shot)" in tail, (
            "提交任务的循环没有重算 motion_kind，会沿用上一个循环的残留值")


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

    def test_long_film_is_not_quieter_than_a_short_one(self, tmp_path,
                                                        monkeypatch):
        """**片子越长不该越小声。**

        amix 默认把每一路都除以输入数 —— 它假设这些路是同时在响的
        背景音。可时间线上的每一条都排在自己的时间码上，同一刻真正
        重叠的最多三条（对白＋环境声＋配乐）。

        于是整章 232 镜、上百条片段时，每条被压掉 1/n：实测混出来
        mean −57.4dB，而源文件是 −16.3dB —— 整片等于静音。
        这一路上没有任何一步报错：ffmpeg 成功、成片里有 aac 轨、
        时间线报「四条轨就绪」，只是听不见。

        两条镜头的小样反而是好的（n=2 只掉 6dB），所以试片时发现不了。
        这条测试因此必须比出「多片段 vs 少片段」，光验一次电平没用。
        """
        import re
        import subprocess

        if not cut.ffmpeg_available():
            pytest.skip("这台机器上没有 ffmpeg")

        import app.capability.mediastore as mediastore

        work = tmp_path
        monkeypatch.setattr(mediastore, "media_root", lambda: str(work))
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=0.5", str(work / "tone.wav")],
            check=True)

        def mean_db(clip_count: int) -> float:
            tl = {"tracks": [{"id": "dialogue", "layer": "audio", "clips": [
                {"start_ms": i * 500, "url": "http://x/media/tone.wav"}
                for i in range(clip_count)]}]}
            outdir = work / f"m{clip_count}"
            outdir.mkdir()
            # 超时给宽一点：这条要起真 ffmpeg，机器上同时在出图出声时
            # 120 秒会被挤爆 —— 那是机器忙，不是混音坏了
            out = cut._mix_audio(tl, outdir, 600, clip_count * 0.5)
            probe = subprocess.run(
                ["ffmpeg", "-hide_banner", "-i", str(out),
                 "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True).stderr
            return float(re.search(r"mean_volume: (-?[\d.]+) dB", probe)[1])

        short, long = mean_db(2), mean_db(40)
        assert abs(long - short) < 3.0, (
            f"40 段混出来 {long:.1f}dB，2 段是 {short:.1f}dB —— "
            "amix 又按输入数把整片压平了")

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

    def test_true_hold_skips_i2v_but_camera_shot_does_not(self):
        import inspect

        class _Shot:
            def __init__(self, camera):
                self.camera_json = camera

        assert cut._motion_kind(_Shot({"motion_kind": "hold"})) == "hold"
        assert cut._motion_kind(_Shot({"motion_kind": "camera",
                                      "frame_mode": "first_only"})) == "camera"
        src = inspect.getsource(cut.generate_videos)
        assert "真正静态镜由最终渲染器直接保持首帧" in src
        assert 'payload["motion"] = "animate"' in src


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
