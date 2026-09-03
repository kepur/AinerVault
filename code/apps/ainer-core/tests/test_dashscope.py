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


class TestErrorMapping:
    """供应商的错误码只能观察，不能猜。

    我在方言里预判过「免费额度用尽」这个失败形态，还专门写了分支 ——
    但码名是猜的（Arrearage / InsufficientQuota / FreeQuotaExhausted），
    真实的是 AllocationQuota.FreeTierOnly。于是 403 那一支先命中，
    报成 UNAUTHORIZED，把人送去查 API key，而 key 是好的。
    """

    def _err(self, status: int, code: str, msg: str = "x"):
        import json

        import httpx

        from app.capability.dialects import _ds_error

        resp = httpx.Response(
            status, content=json.dumps({"code": code, "message": msg}).encode(),
            headers={"content-type": "application/json"})
        return _ds_error(resp)

    def test_quota_is_not_unauthorized(self):
        from app.capability.errors import CapErrorCode

        e = self._err(403, "AllocationQuota.FreeTierOnly", "Free quota exhausted")
        assert e.code == CapErrorCode.UPSTREAM_ERROR
        assert "额度" in str(e)

    def test_quota_is_not_retryable(self):
        """重试只会把同一个错再撞一遍，而每次重试都要等一轮退避。"""
        e = self._err(403, "AllocationQuota.FreeTierOnly")
        assert not e.retryable

    def test_arrearage_also_matches(self):
        from app.capability.errors import CapErrorCode

        assert self._err(403, "Arrearage").code == CapErrorCode.UPSTREAM_ERROR

    def test_real_auth_failure_still_maps_to_unauthorized(self):
        """额度那一支不能吃掉真正的鉴权错 —— 那时确实该去查 key。"""
        from app.capability.errors import CapErrorCode

        assert self._err(401, "InvalidApiKey").code == CapErrorCode.UNAUTHORIZED
        assert self._err(403, "Forbidden").code == CapErrorCode.UNAUTHORIZED

    def test_rate_limit_stays_retryable(self):
        from app.capability.errors import CapErrorCode

        e = self._err(429, "Throttling.RateQuota")
        assert e.code == CapErrorCode.RATE_LIMITED and e.retryable

    def test_default_t2i_model_has_room(self):
        """默认文生图不能是免费额度只有 10 张的那个 ——
        出一整本的素材参考图动辄几十张，会在半路撞额度。"""
        import httpx

        from app.capability.dialects import dashscope_catalog
        from app.capability.schemas import Capability

        with httpx.Client() as c:
            cat = dashscope_catalog(c, "https://x", {}, 1)
        entry = cat.get(Capability.image_t2i)
        assert entry.default_model().id == "qwen-image-2.0-pro-2026-06-22"


class TestTimeoutFloors:
    """端点上那个 timeout_sec 是按文本调用配的（默认 60）。

    套在图像上必然不够 —— 出一张图 60–90 秒是常态。于是每次调用都读超时、
    重试、再超时，而日志里看到的是「超时」，很容易当成网络问题去查，
    实际是一个给聊天配的数字被用在了完全不同量级的任务上。
    """

    def test_image_and_video_get_more_than_text(self):
        from app.capability.client import timeout_for
        from app.capability.schemas import Capability

        text = timeout_for(Capability.text_chat, 300_000, 60)
        image = timeout_for(Capability.image_t2i, 300_000, 60)
        video = timeout_for(Capability.video_i2v, 300_000, 60)
        assert text == 60
        assert image > text
        assert video > image

    def test_generous_endpoint_config_wins(self):
        """只抬下限，不压上限 —— 端点配得比这更宽就听端点的。"""
        from app.capability.client import timeout_for
        from app.capability.schemas import Capability

        assert timeout_for(Capability.image_t2i, 3_000_000, 900) == 900

    def test_caller_budget_is_the_ceiling(self):
        """抬下限不该突破调用方明确设定的天花板 ——
        谁写了 30 秒预算，就是不想等更久。"""
        from app.capability.client import timeout_for
        from app.capability.schemas import Capability

        assert timeout_for(Capability.image_t2i, 30_000, 60) == 30.0


class TestSyncRetry:
    def test_media_calls_go_through_backoff(self):
        """退避原来只接在文本调用上。图像／语音／视频这条路一次都没经过它 ——
        错误码里明明标了 retryable，却没有任何地方读它。
        结果是整批出图撞上一次瞬时限流就整批失败，
        而批量恰恰是最容易撞限流、失败代价也最高的场景。"""
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects._ds_post)
        assert "retrying(" in src

    def test_retry_honours_provider_retry_after(self):
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects.retrying)
        assert 'getattr(exc, "retry_after", None)' in src
        assert "RETRY_BACKOFF_SEC" in src

    def test_non_retryable_is_not_retried(self):
        """额度耗尽重试三次只是把同一个错撞三遍，还白等两轮退避。"""
        from app.capability.dialects import retrying
        from app.capability.errors import CapabilityError, CapErrorCode

        calls = []

        def boom():
            calls.append(1)
            raise CapabilityError(CapErrorCode.UPSTREAM_ERROR, "quota", retryable=False)

        try:
            retrying(boom, what="test")
        except CapabilityError:
            pass
        assert len(calls) == 1


class TestEpochPromptWithAnchor:
    """有锚时文字不该再描述脸。

    实跑：镜 6 的提示词是「a man seated behind a door」加六十个词的
    脸型体型衣着 —— 场景四个词对人物六十个词，出来的是一张灰底棚拍立姿，
    而这一镜的描述是「沈砚推门而出，起身迎敌」。
    """

    class _Epoch:
        locked = False
        identity_ref_asset_id = "as_x"
        invariant_json = {
            "_en": "square face, thick brows, bronze skin, sturdy build, 178cm",
            "sex": "male", "build": "结实匀称", "features": "浓眉，细长眼",
        }
        variant_json = {
            "_en": "man in his mid-twenties, grey padded coat, sabre at the hip",
            "_age_en": "man in his mid-twenties",
        }

    def test_anchor_drops_the_face_description(self):
        from app.pipelines.epochs import compose_epoch_prompt

        out = compose_epoch_prompt(self._Epoch(), "character", has_anchor=True)
        assert "square face" not in out
        assert "grey padded coat" in out

    def test_sex_survives(self):
        """锚里看得出性别，但写出来能防模型跑偏。"""
        from app.pipelines.epochs import compose_epoch_prompt

        assert "male" in compose_epoch_prompt(
            self._Epoch(), "character", has_anchor=True)

    def test_no_chinese_leaks_in(self):
        """单个字段存的是中文（build=结实匀称），`_en` 才是英文整段。
        逐字段拼会把中文拼进提示词，而图像模型不认中文。"""
        import re

        from app.pipelines.epochs import compose_epoch_prompt

        for anchored in (True, False):
            out = compose_epoch_prompt(self._Epoch(), "character",
                                       has_anchor=anchored)
            assert not re.search(r"[一-鿿]", out), out

    def test_anchored_prompt_is_much_shorter(self):
        from app.pipelines.epochs import compose_epoch_prompt

        a = compose_epoch_prompt(self._Epoch(), "character", has_anchor=True)
        b = compose_epoch_prompt(self._Epoch(), "character", has_anchor=False)
        assert len(a) < len(b)

    def test_stored_prompt_no_longer_short_circuits(self):
        """`epoch.visual_prompt or compose_...` 让 has_anchor 那条逻辑
        永远不执行 —— 预存的一存在就短路了。写了没接线的又一例。"""
        import inspect

        from app.pipelines import frame_compose

        src = inspect.getsource(frame_compose._entity_look)
        assert "epoch.locked or not anchor" in src


class TestVideoDurationBounds:
    def test_clamped_to_model_limits(self):
        """模型自己有下限（wan 是 2–15 秒）。上游算出 1.3 秒的快切镜头
        完全合理，但发过去会在轮询阶段失败，
        报一句和剪辑无关的话（duration should be between 2 and 15）。"""
        import httpx

        from app.capability.dialects import (
            _DS_VIDEO_MAX_S, _DS_VIDEO_MIN_S, _ds_video_body,
        )

        with httpx.Client() as c:
            short = _ds_video_body(
                c, {"first_frame": {"b64": "AA", "mime": "image/png"},
                    "duration_ms": 1300}, "wan2.7-i2v", 5)
            long = _ds_video_body(
                c, {"first_frame": {"b64": "AA", "mime": "image/png"},
                    "duration_ms": 60000}, "wan2.7-i2v", 5)
        assert short["parameters"]["duration"] == _DS_VIDEO_MIN_S
        assert long["parameters"]["duration"] == _DS_VIDEO_MAX_S


class TestStreamingWavDuration:
    def test_placeholder_data_size_is_clamped_to_file_bytes(self, tmp_path, monkeypatch):
        """流式 WAV 的 data 长度可能是 0x7fffff9b 占位值。

        若相信文件头，86KB 音频会被算成 18.6 小时，并一路放大整片时长。
        真正可读的数据只能到文件末尾，所以必须取声明值与实际值的较小者。
        """
        import struct

        from app.capability import dialects

        pcm = b"\x00\x00" * 16000  # 16kHz / mono / 16-bit = 1 秒
        fmt = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)
        raw = (
            b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
            + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", 2147483547) + pcm
        )
        media = tmp_path / "streaming.wav"
        media.write_bytes(raw)
        monkeypatch.setattr(dialects, "media_root", lambda: tmp_path, raising=False)

        # _wav_duration_ms currently imports media_root inside the function, so expose
        # this file through the configured media directory instead of trusting the header.
        from app.capability import mediastore
        monkeypatch.setattr(mediastore, "media_root", lambda: tmp_path)
        got = dialects._wav_duration_ms({"url": "http://localhost/media/streaming.wav"})
        assert 995 <= got <= 1005

    def test_mp3_frames_are_counted_without_guessing_bitrate(self):
        """cosyvoice 返回 MP3；只会算 WAV 会让免费音色在时间轴里变成 0 秒。"""
        from app.capability.dialects import _mp3_duration_ms

        # MPEG-1 Layer III, 128kbps, 44.1kHz，无 padding：每帧 417 字节/1152 samples。
        header = bytes.fromhex("fffb9000")
        frame = header + b"\x00" * (417 - 4)
        got = _mp3_duration_ms(frame * 100)
        assert got is not None
        assert 2600 <= got <= 2620


class TestFreeTierVoices:
    """sambert 那一批有免费额度（各 3 万），qwen3-tts 没有。
    一本长篇几千句对白，默认落在付费档上是一笔不该花的钱 ——
    而这笔钱是**静默**花掉的：数据正常、音频也正常出，只有账单会说话。
    """

    def test_free_tier_is_tagged(self):
        """免费档现在有两族：sambert（音色即模型名）与 cosyvoice（模型+voice）。
        判据用 tags，不在调用方硬编模型名 —— 哪些免费是供应商的事，会变。"""
        from app.capability.dialects import dashscope_voices

        free = [v for v in dashscope_voices() if "free-tier" in (v.tags or [])]
        assert free
        assert all(v.voice_id.startswith(("sambert-", "cosyvoice-v1:"))
                   for v in free)
        assert any(v.voice_id.startswith("sambert-") for v in free)
        assert any(v.voice_id.startswith("cosyvoice-v1:") for v in free)

    def test_cosyvoice_widens_the_free_male_pool(self):
        """英语的免费男声原来只有 sambert-brian 一个，而一章可能有五个男角色 ——
        不把 cosyvoice 算进来就只能落到付费档。
        cosyvoice 是「一个模型 + voice 参数」，与 sambert 的「音色即模型名」
        是同一族里的两种约定，写成 `cosyvoice-v1:longcheng` 塞进同一个格子。
        """
        from app.capability.dialects import dashscope_voices

        males = [v for v in dashscope_voices(language="en-GB", gender="male")
                 if "free-tier" in (v.tags or [])]
        assert len(males) > 1
        assert any(v.voice_id.startswith("cosyvoice-v1:") for v in males)

    def test_free_only_never_reaches_paid(self):
        """付费是要人明确说「可以花钱」才发生的事，
        不是「免费的用完了就自动顺延」—— 顺延是静默的。"""
        import inspect

        from app.pipelines import casting

        src = inspect.getsource(casting.bind_engine_voices)
        assert "free_only: bool = True" in inspect.getsource(casting.bind_engine_voices)
        assert "reused.append" in src

    def test_language_filter_excludes_wrong_accent(self):
        """不过滤的话英文剧本会配上中文音色 —— sambert-zhida 念英语能出声，
        只是口音重到听不出在说什么，而数据上完全正常。"""
        from app.capability.dialects import dashscope_voices

        en = {v.voice_id for v in dashscope_voices(language="en-GB")}
        assert "sambert-beth-v1" in en
        assert "sambert-zhida-v1" not in en

    def test_free_tier_is_tried_first(self):
        """排序只在「从头开始扫」时才有意义。原来把两族拼成一个列表、
        按哈希取起点再顺延 —— 起点直接落在付费段就从付费段开始拿，
        实跑六个角色全落付费，而唯一的免费男声一次都没被用到。"""
        import inspect

        from app.pipelines import casting

        src = inspect.getsource(casting.bind_engine_voices)
        assert "free_pool" in src and "paid_pool" in src
        assert "tiers = (free_pool,) if free_only else" in src

    def test_paid_fallback_is_reported(self):
        """免费档不够用是真实的资源约束，不是 bug ——
        但它必须被看见，让人决定「复用同一把嗓子」还是「付费」。"""
        import inspect

        from app.pipelines import casting

        assert "paid_fallback" in inspect.getsource(casting.bind_engine_voices)

    def test_sambert_voice_is_the_model_name(self):
        """与 qwen3-tts 的「一个模型 + voice 参数」相反 ——
        路由上写死一个模型等于写死一把嗓子。"""
        import inspect

        from app.capability import dialects

        assert "音色就是模型名" in inspect.getsource(dialects._sambert_invoke)

    def test_style_prompt_loss_is_warned(self):
        """sambert 没有表演指示通道。默默丢掉的话所有角色听起来一个样，
        而没有任何地方说过为什么。"""
        import inspect

        from app.capability import dialects

        assert "不接受表演指示" in inspect.getsource(dialects._sambert_invoke)
