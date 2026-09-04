"""本地 A1111 方言 —— 第一个跑在自己显卡上的方言。

存在的理由很直接：出图是整条产线里最贵的一项。实测账单一天 ¥80，
其中 ¥48 是视频、¥31.5 是 i2i，而剧本、译本、配音加起来不到一块钱。
本地跑一张 1024px 十几秒，出多少张都不花钱。
"""
from __future__ import annotations

import pytest

from app.capability.errors import CapabilityError
from app.capability.schemas import Capability


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _Transport:
    """记下发出去的 body，好断言映射对不对。"""

    def __init__(self, resp=None):
        self.calls = []
        self.resp = resp or _Resp(200, {"images": ["aGVsbG8="]})

    def post(self, url, *, json=None, headers=None, timeout=None):
        self.calls.append((url, json))
        return self.resp

    def get(self, url, **kw):
        return _Resp(200, [])


class TestDialectRegistration:
    def test_sd_is_a_sync_dialect(self):
        """本地推理没有任务队列，一次 HTTP 就是全部。"""
        from app.capability.dialects import DIALECT_SD, DIALECTS, SYNC_ONLY_DIALECTS

        assert DIALECT_SD in DIALECTS
        assert DIALECT_SD in SYNC_ONLY_DIALECTS

    def test_client_dispatches_to_it(self):
        import inspect

        from app.capability import client

        src = inspect.getsource(client)
        assert "sd_invoke(" in src and "sd_health(" in src


class TestCapabilityBoundary:
    @pytest.mark.parametrize("cap", [
        Capability.text_chat, Capability.audio_tts, Capability.video_i2v,
    ])
    def test_non_image_is_refused_clearly(self, cap):
        """A1111 没有文本与音频。硬接会得到 404，而不是能看懂的报错。"""
        from app.capability.dialects import sd_invoke

        with pytest.raises(CapabilityError) as e:
            sd_invoke(_Transport(), "http://x", {}, capability=cap,
                      payload={"prompt": "a"}, model="m", timeout=10, task_id="t")
        assert "只有图像" in str(e.value)


class TestBodyMapping:
    def _body(self, cap, payload, model="anything-v5"):
        from app.capability.dialects import _sd_body

        return _sd_body(_Transport(), payload, model, capability=cap,
                        timeout=10, warnings=[])

    def test_t2i_goes_to_txt2img(self):
        route, body = self._body(Capability.image_t2i,
                                 {"prompt": "a hallway", "width": 768, "height": 448})
        assert route == "txt2img"
        assert body["prompt"] == "a hallway"
        assert (body["width"], body["height"]) == (768, 448)
        assert "init_images" not in body

    def test_i2i_needs_an_image(self):
        with pytest.raises(CapabilityError) as e:
            self._body(Capability.image_i2i, {"prompt": "a"})
        assert "image_to_image" in str(e.value)

    def test_seed_none_becomes_random_not_zero(self):
        """seed=0 是一个**固定**的种子 —— 整批图会一模一样。
        A1111 的随机是 -1。"""
        _, body = self._body(Capability.image_t2i, {"prompt": "a"})
        assert body["seed"] == -1

    def test_seed_is_passed_through(self):
        _, body = self._body(Capability.image_t2i,
                             {"prompt": "a", "params": {"seed": 12345}})
        assert body["seed"] == 12345

    def test_checkpoint_is_not_restored_afterwards(self):
        """每次调用后切回原模型会触发一次重新加载 ——
        一批三十张就是三十次几秒的加载，而下一张八成还用同一个模型。"""
        _, body = self._body(Capability.image_t2i, {"prompt": "a"})
        assert body["override_settings"]["sd_model_checkpoint"] == "anything-v5"
        assert body["override_settings_restore_afterwards"] is False

    def test_no_checkpoint_override_when_route_has_no_model(self):
        """路由没指定模型时用 WebUI 里当前加载的那个，不要硬塞一个空值。"""
        _, body = self._body(Capability.image_t2i, {"prompt": "a"}, model=None)
        assert "override_settings" not in body


class TestReferenceOnly:
    """reference_only **不需要 ControlNet 模型文件** —— 实测模型列表为空
    也能跑通，model 传 "None" 即可。它是这台机器上现成可用的、
    唯一的身份一致性手段：openpose / ip-adapter 那些都要先下模型文件。
    """

    def _units(self, payload):
        from app.capability.dialects import _sd_refs

        return _sd_refs(_Transport(), payload, 10)

    def test_identity_ref_becomes_a_controlnet_unit(self):
        units = self._units({"reference_images": [
            {"ref": {"b64": "aGk="}, "role": "character", "identity": True,
             "weight": 0.8}]})
        assert len(units) == 1
        assert units[0]["module"] == "reference_only"
        assert units[0]["model"] == "None", "reference_only 不挂模型文件"
        assert units[0]["weight"] == 0.8

    def test_only_one_unit_even_with_many_refs(self):
        """参考图里除了人还有画风、场景、服装 —— 全挂上去，
        模型会把场景参考的构图也一起抄过来。"""
        units = self._units({"reference_images": [
            {"ref": {"b64": "aGk="}, "role": "character", "identity": True},
            {"ref": {"b64": "aGk="}, "role": "scene"},
            {"ref": {"b64": "aGk="}, "role": "style"},
        ]})
        assert len(units) == 1

    def test_no_character_ref_means_no_controlnet(self):
        assert self._units({"reference_images": [
            {"ref": {"b64": "aGk="}, "role": "style"}]}) == []


class TestOutput:
    def test_only_the_first_image_is_kept(self):
        """挂了 ControlNet 之后返回里会多出预处理图（reference 的灰度图），
        照单全收会把它也存成产物 —— 资源库里每张人物图旁边多一张没人要的。"""
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects.sd_invoke)
        assert "raw[0]" in src

    def test_local_runs_cost_zero(self):
        """本地跑不花钱 —— cost 必须是 0，别让它混进成本统计。"""
        import inspect

        from app.capability import dialects

        assert "cost=0.0" in inspect.getsource(dialects.sd_invoke)

    def test_connection_failure_says_it_is_local(self):
        """本地服务最常见的失败是没开机或 IP 变了，
        报「上游错误」会让人去查供应商。"""
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects.sd_invoke)
        assert "连不上本地 SD" in src and "--api" in src


class TestPromptStyle:
    """要切换的不是**语言**，是**句式**。

    实跑发给本地 SD 的提示词本来就是全英文的：
      "Create a full-body front-view character model reference of the exact
       same person shown in the input identity portrait. Preserve the exact
       facial identity. Apply only this period-specific body, hair and
       wardrobe design: man in his forties, American, ..."

    百炼的 qwen-image 是指令跟随模型，读得懂这一套；SD1.5 系的动漫底模
    不跟随指令，只认逗号标签 —— 那半句话在它眼里是噪声，把真正描述
    五官衣着的词稀释掉，出来的脸就糊。anything-v5 人脸崩的根因在这里。
    """

    def test_instruction_sentences_are_dropped(self):
        from app.capability.dialects import sd_tagify

        got = sd_tagify(
            "Create a full-body reference of the exact same person. "
            "Preserve the exact facial identity. short neat hair, grey slacks")
        assert "Create" not in got and "Preserve" not in got
        assert "short neat hair" in got and "grey slacks" in got

    def test_colon_keeps_only_the_content(self):
        """「hair and wardrobe design: man in his forties」只留后半 ——
        不切的话前半会作为标签留下，而且让后半躲过去重。"""
        from app.capability.dialects import sd_tagify

        got = sd_tagify("Apply only this design: man in his forties, "
                        "American, man in his forties, short hair")
        assert "wardrobe" not in got and "design" not in got
        assert got.lower().count("man in his forties") == 1

    def test_pure_tags_pass_through(self):
        """已经是标签的不要动 —— 这一层只负责把指令句拆成标签。"""
        from app.capability.dialects import sd_tagify

        tags = "1boy, solo, short hair, school uniform"
        assert sd_tagify(tags) == tags

    def test_empty_stays_empty(self):
        from app.capability.dialects import sd_tagify

        assert sd_tagify("") == ""
        assert sd_tagify(None) == ""

    def test_all_instruction_falls_back_to_original(self):
        """拆不出标签时原样返回 —— 宁可发一条指令式提示词，也不要发空的。"""
        from app.capability.dialects import sd_tagify

        only = "Create an image. Preserve the identity."
        assert sd_tagify(only) == only

    def test_style_is_opt_in_per_route(self):
        """默认 instruction，不改老行为 —— 百炼那条线还要靠它。"""
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects._sd_body)
        assert 'prompt_style' in src and '"tags"' in src


class TestSerialisedLocally:
    """本地推理必须串行。

    A1111 只有一个采样 worker，显存是硬上限。并发发进去不会排队 ——
    它会同时开始、一起抢显存。实测：素材链正在跑的时候另开三个 img2img
    探测，四个请求同时进一块 16G 卡，WebUI 直接崩了（端口都不再监听），
    而客户端这边看到的只是三个 ReadTimeout，什么都查不出来。
    """

    def test_the_post_is_inside_a_lock(self):
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects.sd_invoke)
        i, j = src.index("with _SD_LOCK"), src.index("transport.post")
        assert i < j, "请求必须在锁里发"

    def test_the_lock_is_module_level(self):
        """每次调用新建一把锁等于没有锁。"""
        from app.capability import dialects

        assert isinstance(dialects._SD_LOCK, type(__import__("threading").Lock()))

    def test_cloud_dialects_are_not_serialised(self):
        """云端本来就是一个请求一台机器，串行只会白白拖慢整批。"""
        import inspect

        from app.capability import dialects

        assert "_SD_LOCK" not in inspect.getsource(dialects.dashscope_invoke)
        assert "_SD_LOCK" not in inspect.getsource(dialects.openai_invoke)
