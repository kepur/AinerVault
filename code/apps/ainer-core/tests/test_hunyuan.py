"""本机混元网关方言。

**跑在本地不等于免费。** 地址是 127.0.0.1，费用照收 —— 0.2 元/张。
这一点最容易看错，也是这个文件里最要紧的一条断言。
"""
from __future__ import annotations

import pytest

from app.capability.errors import CapabilityError
from app.capability.schemas import Capability


class _Resp:
    def __init__(self, status=200, payload=None, text="", content=b""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text
        #: _ds_fetch 落盘时读 .content —— 少了它整个替身在下载那一步炸
        self.content = content
        self.headers = {"content-type": "image/png"}

    def json(self):
        return self._payload


class _Transport:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload or {
            "url": "http://127.0.0.1:8765/files/x.png",
            "width": 1280, "height": 720, "price_cny": 0.2,
        }

    def post(self, url, *, json=None, headers=None, timeout=None):
        self.calls.append((url, json))
        return _Resp(200, self.payload)

    def get(self, url, **kw):
        # 一个最小的合法 PNG，够 sniff 认出类型
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
               b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
               b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00"
               b"\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
        return _Resp(200, {}, content=png)


class TestRegistration:
    def test_dialect_is_registered_and_sync(self):
        from app.capability.dialects import (
            DIALECT_HUNYUAN, DIALECTS, SYNC_ONLY_DIALECTS)

        assert DIALECT_HUNYUAN in DIALECTS
        assert DIALECT_HUNYUAN in SYNC_ONLY_DIALECTS

    def test_client_dispatches_to_it(self):
        import inspect

        from app.capability import client

        src = inspect.getsource(client)
        assert "hunyuan_invoke(" in src and "hunyuan_health(" in src


class TestCapabilityBoundary:
    @pytest.mark.parametrize("cap", [Capability.video_i2v, Capability.audio_tts])
    def test_non_image_is_refused(self, cap):
        """这个网关只有图像两项 —— 硬接会得到 404，而不是能看懂的报错。"""
        from app.capability.dialects import hunyuan_invoke

        with pytest.raises(CapabilityError) as e:
            hunyuan_invoke(_Transport(), "http://x", {}, capability=cap,
                           payload={"prompt": "a"}, model=None,
                           timeout=10, task_id="t")
        assert "文生图与图生图" in str(e.value)

    def test_i2i_without_a_reference_is_refused(self):
        """没有参考图的 i2i 会静默退化成文生图 —— 那正是脸漂的由来。"""
        from app.capability.dialects import hunyuan_invoke

        with pytest.raises(CapabilityError) as e:
            hunyuan_invoke(_Transport(), "http://x", {},
                           capability=Capability.image_i2i,
                           payload={"prompt": "a"}, model=None,
                           timeout=10, task_id="t")
        assert "需要参考图" in str(e.value)


class TestIdentityLock:
    """派生视角要的是「同一个人同一身衣服，只换角度」。"""

    def _sent(self, payload, cap=Capability.image_i2i):
        from app.capability.dialects import hunyuan_invoke

        t = _Transport()
        hunyuan_invoke(t, "http://x", {}, capability=cap, payload=payload,
                       model=None, timeout=10, task_id="t")
        return t.calls[0][1]

    def test_reference_becomes_images_and_locks_identity(self):
        body = self._sent({"prompt": "转到左前四分之三",
                           "image": {"b64": "aGk=", "mime": "image/png"}})
        assert body["images"] and body["lock_identity"] is True

    def test_revise_is_off_when_a_reference_is_present(self):
        """扩写会把场景改跑 —— 派生视角一介入就可能换个场景重画。"""
        body = self._sent({"prompt": "侧面",
                           "image": {"b64": "aGk=", "mime": "image/png"}})
        assert body["revise"] == 0

    def test_route_can_still_force_revise_on(self):
        body = self._sent({"prompt": "侧面", "params": {"revise": 1},
                           "image": {"b64": "aGk=", "mime": "image/png"}})
        assert body["revise"] == 1

    def test_at_most_three_references(self):
        """服务上限三张，多送会整个请求被拒。"""
        body = self._sent({
            "prompt": "x", "image": {"b64": "aGk=", "mime": "image/png"},
            "reference_images": [{"ref": {"b64": "aGk=", "mime": "image/png"}}
                                 for _ in range(5)]})
        assert len(body["images"]) == 3

    def test_the_three_slots_go_to_faces_not_to_style(self):
        """三张的预算按重要性给，不按上游拼装顺序给。

        上游按「画风 → 场景 → 人物 → 服装道具」拼参考图，从前这里照
        那个顺序取前三张，于是每一镜送出去的都是「身份锚 + 画风图 +
        场景图」—— **人物的脸一张都进不去**。

        实跑的样子：镜 2 里那个金发白人在上一镜还是亚洲脸。查起来极难，
        因为图是好图、构图也对，只是人不对；而参考图在库里挂得好好的，
        谁都以为送进去了。

        画风与场景在提示词里还各有一整段文字，人脸没有替代品。
        """
        import base64

        from app.capability.dialects import hunyuan_invoke
        from app.capability.mediastore import store_b64

        def b64(word: str) -> str:
            return base64.b64encode(word.encode()).decode()

        # 内容不同，落盘的文件名才不同 —— 否则三张参考图在
        # body["images"] 里长得一模一样，断言不了是谁被丢掉的
        def name(word: str) -> str:
            return str(store_b64(b64(word), mime="image/png")["url"]).rsplit("/", 1)[-1]

        def ref(word: str) -> dict:
            return {"b64": b64(word), "mime": "image/png"}

        t = _Transport()
        hunyuan_invoke(
            t, "http://x", {}, capability=Capability.image_i2i, timeout=10,
            model=None, task_id="t",
            payload={
                "prompt": "x",
                "image": ref("anchor"),
                "reference_images": [
                    {"ref": ref("style"), "role": "style", "tag": "world_style"},
                    {"ref": ref("scene"), "role": "scene", "tag": "location.x"},
                    {"ref": ref("face"), "role": "character",
                     "identity": True, "tag": "character.xie"},
                ],
            })
        sent = [str(x).rsplit("/", 1)[-1] for x in t.calls[0][1]["images"]]
        assert len(sent) == 3
        assert name("anchor") in sent      # 身份锚永远第一
        assert name("face") in sent        # 脸没有替代品
        assert name("style") not in sent   # 画风在提示词里还有一整段文字

    def test_t2i_sends_no_images(self):
        body = self._sent({"prompt": "一条走廊"}, cap=Capability.image_t2i)
        assert "images" not in body and "lock_identity" not in body


class TestChineseFirst:
    """服务自己写着 prompt_lang: zh-CN recommended。

    我们合成的帧提示词是英文（CJK 被过滤掉），所以这条线要走另一份 ——
    handoff.compose_image_cn 早就在为「喂国产模型」拼中文那一份了。
    """

    def _sent(self, payload):
        from app.capability.dialects import hunyuan_invoke

        t = _Transport()
        hunyuan_invoke(t, "http://x", {}, capability=Capability.image_t2i,
                       payload=payload, model=None, timeout=10, task_id="t")
        return t.calls[0][1] if t.calls else {}

    def test_chinese_wins_when_present(self):
        body = self._sent({"prompt": "a boy in a hallway",
                           "prompt_cn": "走廊里的少年"})
        assert body["prompt"] == "走廊里的少年"

    def test_falls_back_to_english(self):
        """没有中文那份时不能空手发 —— 英文它也认，只是不擅长。"""
        body = self._sent({"prompt": "a boy in a hallway"})
        assert body["prompt"] == "a boy in a hallway"

    def test_prompt_leaves_room_for_the_gateway_prefix(self):
        """8192 是网关**加完前缀之后**的总长，不是我们能发的长度。

        照 8192 截断的实跑结果：8192 + 69 = 8261，腾讯回
        InvalidParameterValue.TextLengthExceed，整批首帧无声失败 ——
        错误只在网关那侧，我们这边只看到「这一镜没出图」。
        69 是量出来的：发 3 字回 72 字，加的是那句【身份锁定】。
        """
        from app.capability.dialects import _HY_PREFIX_ROOM

        body = self._sent({"prompt_cn": "字" * 9000})
        assert len(body["prompt"]) == 8192 - _HY_PREFIX_ROOM
        assert len(body["prompt"]) + 69 < 8192

    def test_empty_prompt_is_refused(self):
        from app.capability.dialects import hunyuan_invoke

        with pytest.raises(CapabilityError):
            hunyuan_invoke(_Transport(), "http://x", {},
                           capability=Capability.image_t2i,
                           payload={"prompt": "  "}, model=None,
                           timeout=10, task_id="t")


class TestCostIsRecorded:
    def test_local_address_does_not_mean_free(self):
        """地址是 127.0.0.1，费用照收 —— cost 必须如实记，不能是 0。"""
        import inspect

        from app.capability import dialects

        src = inspect.getsource(dialects.hunyuan_invoke)
        assert "cost=0.0" not in src
        assert "_HY_PRICE_CNY" in src and 'currency="CNY"' in src

    def test_price_comes_from_the_response_when_given(self):
        import inspect

        from app.capability import dialects

        assert 'data.get("price_cny")' in inspect.getsource(dialects.hunyuan_invoke)


class TestReferencePriority:
    def test_characters_survive_style_first_order(self, monkeypatch):
        from app.capability import dialects as d
        monkeypatch.setattr(d, '_hy_ref_path', lambda transport, ref, timeout: ref['url'])
        transport = _Transport()
        result = d.hunyuan_invoke(transport, 'http://x', {},
            capability=Capability.image_i2i, model=None, timeout=10, task_id='priority',
            payload={'prompt': 'a scene', 'image': {'url': 'base'}, 'reference_images': [
                {'role': 'style', 'tag': 'style', 'ref': {'url': 'style'}},
                {'role': 'scene', 'tag': 'classroom', 'ref': {'url': 'room'}},
                {'role': 'character', 'identity': True, 'ref': {'url': 'girl'}},
                {'role': 'character', 'identity': True, 'ref': {'url': 'boy'}},
            ]})
        assert transport.calls[0][1]['images'] == ['base', 'girl', 'boy']
        assert any('classroom' in w and 'style' in w for w in result.warnings)
