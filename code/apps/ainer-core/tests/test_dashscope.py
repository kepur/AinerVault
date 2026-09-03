"""dashscope 方言、身份锚 i2i、重出与负面词守门。

这里每一条对应的坑，共同点是**症状与起因隔得很远**：
时长写错一层结构，表现是「镜头长度回填全程跳过」；
幂等键没错开，表现是「重新生成按钮点了没反应」。
没有测试的话，下次改动把它们碰回去，也是同样地悄无声息。
"""
from __future__ import annotations

import pytest  # noqa: F401  —— 保留给后续用例


class TestDashscopeDialect:
    def test_tts_body_uses_style_prompt_as_instruct(self):
        """配音表算出的中性描述存在 style_prompt。方言要认这个键，
        否则「配音表 → 引擎」之间还得再写一层数值映射。"""
        from app.capability.dialects import _ds_tts_body

        warns: list[str] = []
        body = _ds_tts_body(
            {"text": "你来晚了。", "language": "zh-CN", "voice_id": "Ethan",
             "params": {"style_prompt": "低沉沙哑"}},
            "qwen3-tts-instruct-flash", warns)
        assert body["input"]["instruct"] == "低沉沙哑"
        assert body["parameters"]["language_type"] == "Chinese"
        assert not warns

    def test_non_instruct_model_warns_instead_of_silently_dropping(self):
        from app.capability.dialects import _ds_tts_body

        warns: list[str] = []
        _ds_tts_body({"text": "喂", "language": "zh", "voice_id": "Ethan",
                      "params": {"style_prompt": "低沉沙哑"}},
                     "qwen3-tts-flash", warns)
        assert any("表演指示" in w for w in warns)

    def test_missing_voice_warns(self):
        """整章都用兜底音色时，听起来像「配音没生效」而不像「缺配置」。"""
        from app.capability.dialects import _DS_FALLBACK_VOICE, _ds_tts_body

        warns: list[str] = []
        body = _ds_tts_body({"text": "喂", "language": "zh", "params": {}},
                            "qwen3-tts-flash", warns)
        assert body["input"]["voice"] == _DS_FALLBACK_VOICE
        assert warns

    def test_empty_text_rejected(self):
        from app.capability.dialects import _ds_tts_body
        from app.capability.errors import CapabilityError

        with pytest.raises(CapabilityError):
            _ds_tts_body({"text": "   ", "language": "zh"}, "qwen3-tts-flash", [])

    def test_wav_duration_goes_into_meta_not_top_level(self):
        """产物落库时只有 item["meta"] 会进 Asset.meta_json，
        而回挂音频时长读的正是那一处。写在顶层的话，
        音频生成得好好的，唯独时长永远是 None。"""
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects.dashscope_invoke)
        assert 'setdefault("meta", {})["duration_ms"]' in src
        assert '\n            media["duration_ms"]' not in src

    def test_dialect_registered_as_sync_only(self):
        """百炼没有我们这套任务队列，必须走同步分支。"""
        from app.capability.dialects import (
            DIALECT_DASHSCOPE, DIALECTS, SYNC_ONLY_DIALECTS,
        )

        assert DIALECT_DASHSCOPE in DIALECTS
        assert DIALECT_DASHSCOPE in SYNC_ONLY_DIALECTS

    def test_catalog_marks_edit_models_for_i2i(self):
        """身份锚跨期保脸依赖编辑模型。目录里 i2i 只能指向编辑模型 ——
        指到文生图模型上，参考图会被静默忽略。"""
        import httpx

        from app.capability.dialects import dashscope_catalog
        from app.capability.schemas import Capability

        with httpx.Client() as c:
            cat = dashscope_catalog(c, "https://x", {}, 1)
        i2i = cat.get(Capability.image_i2i)
        assert i2i is not None
        assert all("-edit" in m.id for m in i2i.models)

    def test_edit_model_receives_size(self):
        """不传画幅时输出跟随底图，而身份锚是方形头肩像 ——
        16:9 的交付里会混进一批 1:1 的镜头。"""
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects._ds_image_body)
        assert 'if w and h:' in src
        assert '"-edit" not in model' not in src.split('params["size"]')[0][-200:]


class TestIdentityAnchorRouting:
    def test_character_ref_becomes_base_image(self):
        """带身份锚的首帧要走编辑能力，锚本身当底图 ——
        纯文生图模型没有读参考图的通道，挂着也白挂。"""
        from app.pipelines.frame_compose import _split_identity_anchor

        refs = [
            {"role": "style", "ref": {"url": "s.png"}},
            {"role": "character", "ref": {"url": "face.png"}, "tag": "沈砚"},
            {"role": "character", "ref": {"url": "face2.png"}},
        ]
        base, rest = _split_identity_anchor(refs)
        assert base == {"url": "face.png"}
        # 其余参考图仍要带下去，多人同框才不会丢人
        assert len(rest) == 2
        assert {"role": "style", "ref": {"url": "s.png"}} in rest

    def test_style_ref_is_not_a_base_image(self):
        """拿风格参考当底图，出来的是「那张风格图被改了几笔」，不是这一镜。"""
        from app.pipelines.frame_compose import _split_identity_anchor

        base, rest = _split_identity_anchor([{"role": "style", "ref": {"url": "s.png"}}])
        assert base is None
        assert len(rest) == 1

    def test_edit_strength_leaves_room_for_scene(self):
        """锚是灰底头肩像，要变成带服装环境光线的完整画面。
        尾帧那种 0.35 会把人留在棚里；给到 1 就等于重画，脸会丢。"""
        from app.pipelines.frame_compose import IDENTITY_EDIT_STRENGTH

        assert 0.6 < IDENTITY_EDIT_STRENGTH < 0.9


class TestRegenerateActuallyRegenerates:
    def test_submit_task_accepts_force(self):
        """管线的 regenerate 只做到「不跳过已有产物」，
        到了 submit_task 又被幂等命中挡回去：任务不重跑、产物不变，
        界面却报「已提交 30 条」。"""
        import inspect

        from app.capability.service import submit_task

        assert "force" in inspect.signature(submit_task).parameters

    def test_pipelines_pass_regenerate_through(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent / "app" / "pipelines"
        wired = {
            p.name for p in root.glob("*.py")
            if "force=regenerate" in p.read_text(encoding="utf-8")
        }
        # 四条会重出的产线都要接上，漏一条就是「那一种重出点了没反应」
        assert {"frame_compose.py", "audio_compose.py",
                "audiobook.py", "asset_refs.py"} <= wired


class TestNegativePromptGuard:
    def test_negative_side_is_checked_for_cjk(self):
        """从前只查正向提示词，文化包的中文 visual_dont 一路直达模型 ——
        既起不到排除作用，还可能被当成要画的内容，
        而正向那边的报表全绿。"""
        import inspect

        from app.pipelines import frame_compose

        src = inspect.getsource(frame_compose)
        assert "cjk_segments(neg)" in src
        assert '"side": "negative"' in src


class TestVideoPayload:
    """图生视频的入参形状是探出来的，这里钉住。

    踩了两层：传地址字符串被拒（错误指向 Java 的类型系统，
    看不出缺的是 type 键）；传 {"type":"image","image":...} 提交时回
    **200 PENDING**，执行时才 FAILED —— 那次的错误信息里才说出合法取值。
    这个端点是异步校验的，200 不代表形状对。
    """

    def _body(self, **extra):
        import httpx

        from app.capability.dialects import _ds_video_body

        payload = {"first_frame": {"b64": "AAAA", "mime": "image/png"},
                   "prompt": "slow push in", "duration_ms": 5000, **extra}
        with httpx.Client() as c:
            return _ds_video_body(c, payload, "wan2.7-i2v", 5)

    def test_media_items_carry_role_and_url(self):
        body = self._body()
        assert body["input"]["media"] == [
            {"type": "first_frame", "url": "data:image/png;base64,AAAA"}]

    def test_last_frame_gets_its_own_role(self):
        """first/last 两张图靠 type 区分，不靠数组顺序 ——
        顺序型接口在只有尾帧时会把它当首帧用。"""
        body = self._body(last_frame={"b64": "BBBB", "mime": "image/png"})
        roles = [m["type"] for m in body["input"]["media"]]
        assert roles == ["first_frame", "last_frame"]

    def test_duration_converts_to_whole_seconds(self):
        assert self._body(duration_ms=5000)["parameters"]["duration"] == 5
        assert self._body(duration_ms=4400)["parameters"]["duration"] == 4

    def test_missing_first_frame_rejected_before_the_call(self):
        """没有首帧就别提交 —— 提交了也是 200 PENDING 然后 FAILED，
        白等一轮轮询。"""
        import httpx

        from app.capability.dialects import _ds_video_body
        from app.capability.errors import CapabilityError

        with httpx.Client() as c, pytest.raises(CapabilityError):
            _ds_video_body(c, {"prompt": "x"}, "wan2.7-i2v", 5)

    def test_failure_keeps_provider_wording_and_task_id(self):
        """入参形状错只在轮询结果里说得清。截断供应商原话，
        就只剩「任务失败」—— 而合法取值是什么，只有那句话里有。"""
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects._ds_await_video)
        assert "task_id={task_ref}" in src
        assert "CapErrorCode.INVALID_REQUEST" in src
