"""表演层的纯逻辑测试：跳变检测、首尾选择、提示词组装。

这三处的错误都**不会报错**，只会让成片不对：
  跳变漏检   动画里人物凭空换到画面另一边
  首尾取错   首尾帧一模一样，生成出来是两张静止的画
  组装漏项   站位没进提示词，等于这一层白做
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models import Facing, FrameRole, SpeechRole, StagePosition
from app.pipelines.frame_compose import _FACING_EN, _POS_EN, _staging_prompt


def _perf(**kw):
    base = dict(
        position=StagePosition.center, facing=Facing.three_quarter,
        expression=None, expression_end=None, action=None, action_end=None,
        gaze_target=None, props_json=None, speech_role=SpeechRole.listener,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeDB:
    """只需要满足 _staging_prompt 用到的那一次 execute。"""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, _stmt):
        return list(self._rows)


class TestStagingPrompt:
    def test_empty_when_no_cast(self):
        db = _FakeDB([])
        shot = SimpleNamespace(id="sh_1")
        frame = SimpleNamespace(role=FrameRole.first)
        assert _staging_prompt(db, shot, frame) == ""

    def test_first_frame_uses_start_fields(self):
        """首帧必须取 expression/action —— 取成 *_end 就没有运动可言。"""
        rows = [(
            _perf(position=StagePosition.left, facing=Facing.to_camera,
                  expression="calm", expression_end="alarmed",
                  action="seated by the door", action_end="rising to his feet"),
            SimpleNamespace(display_name="沈砚"),
        )]
        out = _staging_prompt(_FakeDB(rows), SimpleNamespace(id="sh_1"),
                              SimpleNamespace(role=FrameRole.first))
        assert "calm" in out and "seated by the door" in out
        assert "alarmed" not in out and "rising" not in out

    def test_last_frame_uses_end_fields(self):
        rows = [(
            _perf(expression="calm", expression_end="alarmed",
                  action="seated", action_end="on his feet"),
            SimpleNamespace(display_name="沈砚"),
        )]
        out = _staging_prompt(_FakeDB(rows), SimpleNamespace(id="sh_1"),
                              SimpleNamespace(role=FrameRole.last))
        assert "alarmed" in out and "on his feet" in out
        assert "calm" not in out

    def test_last_frame_falls_back_to_start_when_end_missing(self):
        """尾帧没填 *_end 时回落到首帧值，而不是留空。

        留空会让尾帧丢掉这个人的表情与动作，i2i 出来是一张走样的脸。
        """
        rows = [(
            _perf(expression="grim", expression_end=None,
                  action="hand on the hilt", action_end=None),
            SimpleNamespace(display_name="老周"),
        )]
        out = _staging_prompt(_FakeDB(rows), SimpleNamespace(id="sh_1"),
                              SimpleNamespace(role=FrameRole.last))
        assert "grim" in out and "hand on the hilt" in out

    def test_offscreen_excluded(self):
        """画外的人不该进画面提示词 —— 在场不等于入画。"""
        rows = [
            (_perf(position=StagePosition.offscreen, expression="angry"),
             SimpleNamespace(display_name="裴无咎")),
            (_perf(position=StagePosition.right, expression="wary"),
             SimpleNamespace(display_name="沈砚")),
        ]
        out = _staging_prompt(_FakeDB(rows), SimpleNamespace(id="sh_1"),
                              SimpleNamespace(role=FrameRole.first))
        assert "angry" not in out
        assert "wary" in out

    def test_gaze_and_position_rendered(self):
        rows = [(
            _perf(position=StagePosition.far_left, facing=Facing.profile_right,
                  gaze_target="the locked chest"),
            SimpleNamespace(display_name="沈砚"),
        )]
        out = _staging_prompt(_FakeDB(rows), SimpleNamespace(id="sh_1"),
                              SimpleNamespace(role=FrameRole.first))
        assert _POS_EN["far_left"] in out
        assert _FACING_EN["profile_right"] in out
        assert "looking at the locked chest" in out

    @pytest.mark.parametrize("pos", list(StagePosition))
    def test_every_position_has_a_phrase(self, pos):
        """新增站位若忘了配英文短语，提示词会静默少一截。"""
        if pos is StagePosition.offscreen:
            return          # 画外不入画，本就没有短语
        assert _POS_EN.get(pos.value), f"{pos.value} 缺英文短语"

    @pytest.mark.parametrize("f", list(Facing))
    def test_every_facing_has_a_phrase(self, f):
        assert _FACING_EN.get(f.value), f"{f.value} 缺英文短语"


from app.pipelines.performance import is_position_jump


class TestPositionJump:
    def test_no_previous_is_not_a_jump(self):
        """第一次出现没有可比对象。"""
        assert not is_position_jump(None, StagePosition.left, moved=False)

    def test_same_position_is_not_a_jump(self):
        assert not is_position_jump(
            StagePosition.left, StagePosition.left, moved=False)

    def test_moved_position_without_action_is_a_jump(self):
        """位置变了却没有走位动作 —— 动画会穿帮。"""
        assert is_position_jump(
            StagePosition.left, StagePosition.right, moved=False)

    def test_moved_position_with_action_is_fine(self):
        """这一镜里人在动，位置变了是合理的。"""
        assert not is_position_jump(
            StagePosition.left, StagePosition.right, moved=True)

    @pytest.mark.parametrize("prev,cur", [
        (StagePosition.offscreen, StagePosition.center),
        (StagePosition.center, StagePosition.offscreen),
    ])
    def test_entering_or_leaving_frame_is_not_a_jump(self, prev, cur):
        """入画与出画是正常调度，不是跳变。

        不排除的话，每个进出场都会报一次警，告警就没人看了。
        """
        assert not is_position_jump(prev, cur, moved=False)
