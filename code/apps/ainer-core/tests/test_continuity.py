"""场记（跨镜连续性）的测试。

这类错误的共同点是**每一镜自己都完全合理** ——
主光从左前打过来没问题，下一镜从右前打过来也没问题，
可放在同一场戏里，观众会觉得太阳在两秒里转了半圈。

单镜测试永远测不出这些，所以用例都是成对的镜头。
"""
from __future__ import annotations

import pytest

from app.worldview.continuity import (
    _azimuth, check_axis, check_gaze, check_lighting, check_props,
    check_scene, summarize,
)


def _shot(order, **kw):
    base = {
        "order": order, "key_light": "", "color_temp": "",
        "positions": {}, "facing": {}, "gaze": {}, "props": {}, "actions": {},
    }
    base.update(kw)
    return base


class TestAzimuth:
    @pytest.mark.parametrize("text,expect", [
        ("左前方 45 度硬光", -45),
        ("右前方 45 度", 45),
        ("右后方 30 度硬光", 135),
        ("逆光勾出轮廓", 180),
        ("正面 0 度柔光", 0),
    ])
    def test_reads_direction(self, text, expect):
        assert _azimuth(text) == expect

    def test_word_wins_over_number(self):
        """「左前方 45 度」里的 45 是对方位词的细化，不是独立角度。

        只认数字会把它读成正右 45，于是与「右前方 45 度」完全一样，
        跳变就漏检了 —— 而那正是最该抓的一种。
        """
        assert _azimuth("左前方 45 度") == -45
        assert _azimuth("右前方 45 度") == 45
        assert _azimuth("左前方 45 度") != _azimuth("右前方 45 度")

    @pytest.mark.parametrize("text", ["月光", "柔光", "", "强度中等"])
    def test_unreadable_returns_none(self, text):
        """读不出就返回 None，让检查跳过 —— 不能瞎猜一个角度出来。"""
        assert _azimuth(text) is None


class TestLighting:
    def test_direction_jump_caught(self):
        issues = check_lighting(
            _shot(1, key_light="左前方 45 度硬光"),
            _shot(2, key_light="右前方 45 度硬光"),
        )
        assert any(i.kind == "light_direction_jump" and i.severity == "high"
                   for i in issues)

    def test_small_shift_is_fine(self):
        """小幅调整是正常的，同一场戏里主光会微调。"""
        issues = check_lighting(
            _shot(1, key_light="左前方 45 度"),
            _shot(2, key_light="正左 90 度"),
        )
        assert not [i for i in issues if i.kind == "light_direction_jump"]

    def test_color_temp_jump(self):
        issues = check_lighting(
            _shot(1, color_temp="月光偏青 7000K"),
            _shot(2, color_temp="烛光 2700K"),
        )
        assert any(i.kind == "color_temp_jump" for i in issues)

    def test_missing_data_yields_nothing(self):
        """没有灯光数据时不报 —— 报了也是瞎报。"""
        assert not check_lighting(_shot(1), _shot(2))


class TestAxis:
    def test_flip_caught(self):
        """A 在左 B 在右，下一镜反过来 —— 观众会以为他们换了位置。"""
        issues = check_axis(
            _shot(1, positions={"甲": "left", "乙": "right"}),
            _shot(2, positions={"甲": "right", "乙": "left"}),
        )
        assert any(i.kind == "axis_flip" and i.severity == "high" for i in issues)

    def test_same_side_is_fine(self):
        issues = check_axis(
            _shot(1, positions={"甲": "left", "乙": "right"}),
            _shot(2, positions={"甲": "far_left", "乙": "center_right"}),
        )
        assert not issues

    def test_center_is_not_a_flip(self):
        """有人站到正中时左右关系无从谈起，不该报。"""
        issues = check_axis(
            _shot(1, positions={"甲": "left", "乙": "right"}),
            _shot(2, positions={"甲": "center", "乙": "right"}),
        )
        assert not issues

    def test_only_shared_characters_compared(self):
        """只比两镜都有的人 —— 新入画的人没有「上一镜的位置」。"""
        issues = check_axis(
            _shot(1, positions={"甲": "left"}),
            _shot(2, positions={"乙": "right"}),
        )
        assert not issues


class TestGaze:
    def test_wrong_facing_caught(self):
        """甲在左看向右边的乙，却是左侧脸 —— 两人不像在交流。"""
        issues = check_gaze(_shot(
            1, positions={"甲": "left", "乙": "right"},
            facing={"甲": "profile_left"}, gaze={"甲": "乙"},
        ))
        assert any(i.kind == "gaze_mismatch" for i in issues)

    def test_correct_facing_passes(self):
        issues = check_gaze(_shot(
            1, positions={"甲": "left", "乙": "right"},
            facing={"甲": "profile_right"}, gaze={"甲": "乙"},
        ))
        assert not issues

    def test_to_camera_is_not_judged(self):
        """正对镜头、四分之三侧都不属于「朝错了方向」。"""
        issues = check_gaze(_shot(
            1, positions={"甲": "left", "乙": "right"},
            facing={"甲": "to_camera"}, gaze={"甲": "乙"},
        ))
        assert not issues

    def test_gaze_at_object_ignored(self):
        """看向道具而非人物时没有相向可言。"""
        issues = check_gaze(_shot(
            1, positions={"甲": "left"}, facing={"甲": "profile_left"},
            gaze={"甲": "那把锁"},
        ))
        assert not issues


class TestProps:
    def test_vanished_caught(self):
        issues = check_props(
            _shot(1, props={"甲": ["腰刀"]}),
            _shot(2, props={"甲": []}, actions={"甲": "沉默不语"}),
        )
        assert any(i.kind == "prop_vanished" for i in issues)

    def test_explained_by_action_is_fine(self):
        """动作里交代了就不是问题 —— 放下、收起、扔出都算。"""
        issues = check_props(
            _shot(1, props={"甲": ["腰刀"]}),
            _shot(2, props={"甲": []}, actions={"甲": "把腰刀放在桌上"}),
        )
        assert not issues

    def test_appeared_is_lower_severity(self):
        """多出东西比少了东西轻 —— 可能只是上一镜没入画。"""
        issues = check_props(
            _shot(1, props={"甲": []}),
            _shot(2, props={"甲": ["灯笼"]}, actions={"甲": "站定"}),
        )
        assert issues and issues[0].severity == "low"


class TestScene:
    def test_full_scene(self):
        shots = [
            _shot(1, key_light="左前方 45 度硬光", color_temp="月光 7000K",
                  positions={"甲": "left", "乙": "right"},
                  facing={"甲": "profile_right"}, gaze={"甲": "乙"},
                  props={"甲": ["腰刀"]}, actions={"甲": "握刀"}),
            _shot(2, key_light="右前方 45 度硬光", color_temp="烛光 2700K",
                  positions={"甲": "right", "乙": "left"},
                  facing={"甲": "profile_left"}, gaze={"甲": "乙"},
                  props={"甲": []}, actions={"甲": "沉默"}),
        ]
        out = summarize(check_scene(shots))
        kinds = set(out["by_kind"])
        assert {"light_direction_jump", "axis_flip", "color_temp_jump",
                "prop_vanished"} <= kinds
        # 高危排在前面 —— 翻轴和光位跳是观众一眼能看出的
        assert out["items"][0]["severity"] == "high"

    def test_clean_scene_yields_nothing(self):
        shots = [
            _shot(1, key_light="左前方 45 度", color_temp="月光 7000K",
                  positions={"甲": "left", "乙": "right"},
                  facing={"甲": "profile_right"}, gaze={"甲": "乙"},
                  props={"甲": ["腰刀"]}, actions={"甲": "握刀"}),
            _shot(2, key_light="左前方 30 度", color_temp="月光 6800K",
                  positions={"甲": "center_left", "乙": "right"},
                  facing={"甲": "profile_right"}, gaze={"甲": "乙"},
                  props={"甲": ["腰刀"]}, actions={"甲": "抬眼"}),
        ]
        assert not check_scene(shots)

    def test_single_shot_scene(self):
        assert not check_scene([_shot(1, key_light="左前方 45 度")])
