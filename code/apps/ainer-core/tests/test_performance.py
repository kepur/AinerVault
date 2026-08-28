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


# ── 策略文案完整性 ────────────────────────────────────────────────────────────

from app.models import DeviceStrategy, STRATEGY_BRIEF, strategy_brief


class TestStrategyBrief:
    @pytest.mark.parametrize("s", list(DeviceStrategy))
    def test_every_strategy_has_a_brief(self, s):
        """每一档都要有说明文本。

        这条测试是被一次线上崩溃逼出来的：策略从 5 档扩到 9 档时，
        devices.py 和 translate.py 各存了一份 5 档的映射，
        而它们用 `[key]` 索引 —— 漏一档不是显示不全，
        是 KeyError 把整次翻译打挂，且只有真跑到那一档才会炸。
        """
        assert s.value in STRATEGY_BRIEF, f"{s.value} 缺说明文本"

    def test_unknown_strategy_degrades_not_crashes(self):
        """取不到时降级返回枚举值本身，不抛异常。"""
        fake = SimpleNamespace(value="some_future_strategy")
        assert strategy_brief(fake) == "some_future_strategy"

    def test_target_display_interpolated(self):
        out = strategy_brief(DeviceStrategy.substitute, "摄政英国")
        assert "摄政英国" in out


# ── 同步调用的传输重试 ────────────────────────────────────────────────────────

import httpx

from app.capability.dialects import _Caller
from app.capability.errors import CapErrorCode, CapabilityError


class _FlakyTransport:
    """前 n 次抛传输错误，之后正常返回。"""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.calls = 0
        self.exc = exc or httpx.ReadError("peer closed connection")

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"},
                                    "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
            request=httpx.Request("POST", url),
        )


class TestTransportRetry:
    """跑一本书是上百次调用，网络抖一下就让整步失败太脆 ——
    而失败的那一步可能已经烧了三分钟。
    """

    def _caller(self, transport):
        return _Caller(transport, "http://x", {}, "m", 5)

    def test_recovers_after_transient_failures(self, monkeypatch):
        monkeypatch.setattr("app.capability.dialects.time.sleep", lambda _s: None)
        t = _FlakyTransport(fail_times=2)
        out = self._caller(t)([{"role": "user", "content": "hi"}],
                              temperature=0, max_tokens=16, json_mode=False)
        assert out == "ok"
        assert t.calls == 3

    def test_gives_up_after_max_attempts(self, monkeypatch):
        monkeypatch.setattr("app.capability.dialects.time.sleep", lambda _s: None)
        t = _FlakyTransport(fail_times=99)
        with pytest.raises(CapabilityError) as ei:
            self._caller(t)([{"role": "user", "content": "hi"}],
                            temperature=0, max_tokens=16, json_mode=False)
        assert ei.value.code == CapErrorCode.TRANSPORT_ERROR
        assert t.calls == 3          # 不该无限重试

    def test_does_not_retry_client_errors(self, monkeypatch):
        """4xx 重试多少次都是一样的结果，只是白烧配额。"""
        monkeypatch.setattr("app.capability.dialects.time.sleep", lambda _s: None)

        class _Bad:
            calls = 0

            def post(self, url, json=None, headers=None, timeout=None):
                _Bad.calls += 1
                return httpx.Response(400, json={"error": {"message": "bad"}},
                                      request=httpx.Request("POST", url))

        with pytest.raises(CapabilityError):
            self._caller(_Bad())([{"role": "user", "content": "hi"}],
                                 temperature=0, max_tokens=16, json_mode=False)
        assert _Bad.calls == 1


# ── 画面文字与块类型规则 ──────────────────────────────────────────────────────

from app.pipelines.frame_compose import _signage_prompt
from app.pipelines.translate import _KIND_RULES, _kind_brief
from app.models import BlockType, TRANSLATABLE_TYPES


class TestKindRules:
    def test_every_translatable_type_has_a_rule(self):
        """每种可翻译的块类型都要有处理说明。

        kind 一直传给模型，却从没告诉它那意味着什么 ——
        于是六种要求完全不同的文本走同一套处理：
        招牌被当成句子翻译、内心独白被加上「他想」、
        对白被补上原文里另起一块的引导语。
        """
        for t in TRANSLATABLE_TYPES:
            assert t.value in _KIND_RULES, f"{t.value} 没有处理说明"

    def test_only_present_kinds_injected(self):
        """只注入本批出现的类型 —— 全量注入会淹掉真正相关的那两条。"""
        out = _kind_brief({"dialogue"})
        assert "dialogue" in out
        assert "signage" not in out

    def test_non_translatable_kind_yields_nothing(self):
        assert _kind_brief({"action"}) == ""
        assert _kind_brief(set()) == ""


class _SignDB:
    """按查询顺序返回：先 ScriptBlock，再 TranslationBlock。"""

    def __init__(self, blocks, trans):
        self._queue = [blocks, trans]

    def execute(self, _stmt):
        return SimpleNamespace(scalars=lambda: self._queue.pop(0))


class TestSignagePrompt:
    def _profile(self, **rules):
        return SimpleNamespace(visual_json={"signage_rules": rules})

    def test_uses_translation_not_source(self):
        """画面属于目标世界观，招牌上该是目标语言。"""
        blk = SimpleNamespace(id="b1", block_type=BlockType.signage)
        tr = SimpleNamespace(script_block_id="b1",
                             translated_text='трактиръ «Пьяный ангелъ»')
        out = _signage_prompt(
            _SignDB([blk], [tr]),
            SimpleNamespace(block_ids_json=["b1"]),
            self._profile(script="cyrillic", style="旧俄花体", material="漆木"),
        )
        assert "Пьяный" in out
        assert "cyrillic" in out and "漆木" in out

    def test_blank_rather_than_source_language(self):
        """没有译文时宁可留白 ——
        把源语言的字画进目标世界观的街道是一眼可见的穿帮。
        """
        blk = SimpleNamespace(id="b1", block_type=BlockType.signage)
        out = _signage_prompt(
            _SignDB([blk], []),
            SimpleNamespace(block_ids_json=["b1"]),
            self._profile(script="cyrillic"),
        )
        assert out == "no legible text on signage"
        assert "醉仙楼" not in out

    def test_no_signage_blocks_yields_nothing(self):
        out = _signage_prompt(
            _SignDB([], []),
            SimpleNamespace(block_ids_json=["b1"]),
            self._profile(),
        )
        assert out == ""
