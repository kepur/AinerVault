"""画面质感的规则测试 —— 「塑料感」不是审美问题，是几处漏接线。

实跑一张首帧的提示词长这样：

    a man seated behind a door, ...六十个词的脸型体型衣着...,
    seen from behind, expressionless face, cold gaze, looking at offscreen,
    wide shot, canted and high, 35mm lens, off center obstructed,
    key ratio: hard_8:1, color temp: cool_with_warm_practicals,
    contrast: very_high, grain: heavy
  negative: ..., 美式元素, 现代都市, 东亚建筑, 工业流水线, text, watermark

三处硬伤，每一处都不报错：
  · 灯光是内部枚举，模型读不懂就当噪声跳过 —— 灯实际上没打
  · 负向里整条中文，那几条约束从来没生效过
  · 背对镜头却写着表情与视线，模型只能折中出一张似正似背的脸
"""
from __future__ import annotations

import pytest


class TestDirectorEnumsBecomeEnglish:
    def test_key_ratio_reads_like_a_gaffer_wrote_it(self):
        from app.worldview.cinematography import render_lighting

        got = " | ".join(render_lighting({"key_ratio": "hard_8:1"}))
        assert "hard key light" in got
        assert "hard_8:1" not in got, "内部枚举不能原样送给模型"

    def test_palette_is_actually_sent(self):
        """palette 从建库那天起就没有任何地方读过它。"""
        from app.worldview.cinematography import render_lighting

        got = " | ".join(render_lighting(
            {"palette": ["ink_black", "amber", "teal"]}))
        assert "ink black" in got and "amber" in got and "teal" in got

    def test_palette_is_capped_at_three(self):
        """颜色给多了等于没给 —— 模型会把它们平均成灰。"""
        from app.worldview.cinematography import render_lighting

        got = " | ".join(render_lighting(
            {"palette": ["a", "b", "c", "d", "e"]}))
        assert "d" not in got.split("colour palette of ")[-1]

    def test_unknown_enum_is_carried_through_not_dropped(self):
        """表里没有的新枚举要原样带过。

        静默丢掉的代价大得多：档案里加了一条摄影意图，
        表里忘了补，这条从此不再出现，而没有任何地方会报错。
        """
        from app.worldview.cinematography import render_lighting

        assert "some new look" in " | ".join(
            render_lighting({"contrast": "some_new_look"}))

    def test_avoid_list_becomes_real_words(self):
        from app.worldview.cinematography import render_avoid

        got = render_avoid(["handheld_shake", "crash_zoom"])
        assert "handheld camera shake" in got
        assert all("_" not in g for g in got)


class TestPlasticNegatives:
    def test_the_plastic_look_is_named_and_blocked(self):
        from app.worldview.cinematography import PLASTIC_NEGATIVES

        joined = " ".join(PLASTIC_NEGATIVES)
        for term in ("plastic 3d render", "airbrushed skin", "flat even lighting"):
            assert term in joined

    def test_grade_anchor_asks_for_a_photograph_not_a_render(self):
        from app.worldview.cinematography import GRADE_ANCHOR

        assert "film still" in GRADE_ANCHOR
        assert "skin texture" in GRADE_ANCHOR


class TestNoChineseInImagePrompts:
    def test_compose_filters_cjk_from_both_sides(self):
        """负向里的整条中文一直在，等于那几条约束从没生效过。"""
        import inspect

        from app.pipelines import frame_compose

        src = inspect.getsource(frame_compose.compose_frame_prompt)
        pos_line = [ln for ln in src.split("\n") if "pos = " in ln][0]
        neg_line = [ln for ln in src.split("\n") if "neg = " in ln][0]
        assert "_CJK.search" in pos_line
        assert "_CJK.search" in src[src.index(neg_line):src.index(neg_line) + 200]


class TestFacingContradiction:
    def test_no_expression_when_seen_from_behind(self):
        import inspect

        from app.pipelines import frame_compose

        src = inspect.getsource(frame_compose._staging_prompt)
        assert "Facing.away" in src
        assert "face_visible" in src


class TestCameraReachesTheMotionDirector:
    def test_shot_context_carries_the_camera_move(self):
        """分镜按导演档案给每一镜定了运镜，而这份运镜以前一个字都没往下传。

        提示词又写着「静止也要明写机位固定」，于是每一镜都写机位固定，
        送进 i2v 的是三十段锁死机位的片子 —— 那正是「像 PPT」。
        """
        import inspect

        from app.pipelines import crew_sheets

        src = inspect.getsource(crew_sheets._shot_context)
        assert "camera_json" in src
        assert "运镜" in src

    @pytest.mark.parametrize("move,expect", [
        ("push_in", "推进"), ("orbit", "环绕"), ("handheld", "手持"),
        ("static", "机位固定"),
    ])
    def test_moves_are_translated_for_a_chinese_prompt(self, move, expect):
        """给动作导演的那份提示词是中文的；塞 push_in 进去它只会原样抄回来。"""
        from app.pipelines.crew_sheets import _CAMERA_MOVE_CN

        assert expect in _CAMERA_MOVE_CN[move]


class TestEnFieldsMustBeEnglish:
    @pytest.mark.parametrize("value,keep", [
        ("Hands lift from the box edges", True),
        ("匀速，动作流畅但略显无奈，节奏平稳", False),
        ("steady pace 匀速", False),
        ("", False),
    ])
    def test_cjk_in_an_en_field_counts_as_unfilled(self, value, keep):
        from app.pipelines.crew_sheets import _en_only

        assert bool(_en_only(value)) is keep

    def test_video_gate_refuses_a_chinese_motion_prompt(self):
        """检查一直在报「英文运动提示词混入中文」，但只是报 ——
        行照样入库，i2v 只看非空，中文一路送进视频模型。"""
        import inspect

        from app.pipelines import cut

        src = inspect.getsource(cut.generate_videos)
        assert "_CJK.search(motion.motion_prompt_en" in src
