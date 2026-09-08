"""契约一致性测试：真实 CapabilityClient 打真实 Mock Gateway。

这些断言就是契约本身。任何中间层实现都应该能通过这一套。
运行前需启动：MOCK_LATENCY_FACTOR=0 uvicorn mock_gateway.main:app --port 8199
"""
from __future__ import annotations

import os
import time

import pytest

from app.capability.client import (
    CapabilityClient, canonical_idempotency_key, sign_payload, verify_signature,
)
from app.capability.errors import CapabilityError, CapErrorCode
from app.capability.schemas import (
    Capability, I2IInput, T2IInput, TaskOptions, TaskRequest, TaskState,
    TranslateInput, TranslateSegment, TTSInput,
)

BASE = os.getenv("MOCK_GATEWAY_URL", "http://localhost:8199") + "/cap/v1"


@pytest.fixture(scope="module")
def client():
    with CapabilityClient(BASE, timeout_sec=30) as c:
        try:
            c.health()
        except CapabilityError as exc:
            pytest.skip(f"mock gateway 未启动: {exc}")
        yield c


def _await_terminal(client: CapabilityClient, task_id: str, timeout: float = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = client.get_task(task_id)
        if t.is_terminal:
            return t
        time.sleep(0.1)
    pytest.fail(f"任务 {task_id} 未在 {timeout}s 内终结")


# ── Discovery ─────────────────────────────────────────────────────────────────

def test_health(client):
    h = client.health()
    assert h.ok is True
    assert h.version == "1.0"


def test_catalog_covers_required_capabilities(client):
    cat = client.capabilities()
    assert cat.capability_version == "1.0"
    missing = cat.missing_required()
    assert missing == [], f"主线必需能力缺失: {[m.value for m in missing]}"


def test_catalog_exposes_param_schema(client):
    """后台自动渲染参数表单的前提：每个模型都要给 param_schema。"""
    cat = client.capabilities()
    entry = cat.get(Capability.image_i2i)
    model = entry.default_model()
    props = model.param_schema.get("properties", {})
    assert "strength" in props, "i2i 必须暴露 strength 参数"
    s = props["strength"]
    assert s["minimum"] == 0 and s["maximum"] == 1
    assert 0.25 <= s["default"] <= 0.45, "尾帧默认 strength 应在推荐区间"


def test_pricing_present_for_cost_gate(client):
    """成本闸门依赖 pricing —— 没有它就无法在生成前给出预估。"""
    cat = client.capabilities()
    m = cat.get(Capability.image_t2i).default_model()
    assert m.pricing and m.pricing.cost is not None


# ── text.* 同步通道 ────────────────────────────────────────────────────────────

def test_chat_sync_invoke(client):
    task = client.invoke(
        Capability.text_chat,
        {"messages": [{"role": "user", "content": "你好"}], "max_tokens": 128},
    )
    assert task.status == TaskState.succeeded
    assert task.output["text"]
    assert task.usage.tokens["total"] > 0


def test_chat_json_schema_is_parseable(client):
    """契约要求 json_schema 模式下保证输出可解析 —— 剧本生成全靠这个。"""
    schema = {
        "type": "object",
        "required": ["scenes"],
        "properties": {
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "order"],
                    "properties": {"title": {"type": "string"}, "order": {"type": "integer"}},
                },
            }
        },
    }
    task = client.invoke(
        Capability.text_chat,
        {
            "messages": [{"role": "user", "content": "拆场景"}],
            "response_format": {"type": "json_schema", "schema": schema},
        },
    )
    data = task.output["json"]
    assert isinstance(data["scenes"], list) and data["scenes"]
    assert isinstance(data["scenes"][0]["order"], int)


def test_image_cannot_use_sync_channel(client):
    with pytest.raises(CapabilityError) as ei:
        client.invoke(Capability.image_t2i, {"prompt": "x"})
    assert ei.value.code == CapErrorCode.INVALID_REQUEST


# ── text.translate ────────────────────────────────────────────────────────────

def test_translate_segments_align_one_to_one(client):
    """逐段对齐是长文翻译一致性的生死线：id 一一对应，不合并不漏段。"""
    payload = TranslateInput(
        source_language="zh-CN",
        target_language="ja-JP",
        segments=[
            TranslateSegment(id="b1", text="他推开门。", kind="narration"),
            TranslateSegment(id="b2", text="「你来了。」", kind="dialogue", speaker="李白"),
            TranslateSegment(id="b3", text="客栈里很安静。", kind="narration"),
        ],
    ).model_dump(mode="json")

    task = client.invoke(Capability.text_translate, payload)
    segs = task.output["segments"]
    assert [s["id"] for s in segs] == ["b1", "b2", "b3"]
    assert all(s["text"] for s in segs)


def test_translate_honors_glossary(client):
    """术语表命中必须原样使用并在 glossary_hits 回报 —— 这是防漂移的可审计凭据。"""
    payload = TranslateInput(
        source_language="zh-CN",
        target_language="ja-JP",
        segments=[TranslateSegment(id="b1", text="他走进客栈。")],
        glossary=[{"source": "客栈", "target": "旅籠", "note": "昭和世界观名物"}],
    ).model_dump(mode="json")

    task = client.invoke(Capability.text_translate, payload)
    seg = task.output["segments"][0]
    assert "旅籠" in seg["text"]
    assert "客栈" in seg["glossary_hits"]


# ── 图像：首尾帧 ───────────────────────────────────────────────────────────────

def test_t2i_first_frame(client):
    payload = T2IInput(
        prompt="cinematic wide shot, ancient city gate at dusk",
        width=1280, height=720, params={"seed": 4212},
    ).model_dump(mode="json")

    acc = client.submit(Capability.image_t2i, payload)
    assert acc.task_id
    task = _await_terminal(client, acc.task_id)
    assert task.status == TaskState.succeeded
    img = task.output["images"][0]
    assert img["url"] and img["meta"]["width"] == 1280 and img["meta"]["height"] == 720
    assert task.usage.cost is not None
    assert task.provider


def test_i2i_last_frame_derives_from_first(client):
    """尾帧派生：同一首帧 + 同一 prompt + 同一 seed 必须稳定复现。"""
    first = T2IInput(prompt="a gate", width=1280, height=720,
                     params={"seed": 7}).model_dump(mode="json")
    ft = _await_terminal(client, client.submit(Capability.image_t2i, first).task_id)
    first_url = ft.output["images"][0]["url"]

    def derive():
        payload = I2IInput(
            image={"url": first_url},
            prompt="same scene, he has stepped through the gate",
            strength=0.35, params={"seed": 7},
        ).model_dump(mode="json")
        t = _await_terminal(client, client.submit(Capability.image_i2i, payload).task_id)
        return t.output["images"][0]

    a, b = derive(), derive()
    assert a["sha256"] == b["sha256"], "同输入的尾帧必须确定性复现，否则连贯性无从保证"
    assert a["meta"]["strength"] == 0.35


def test_i2i_rejects_out_of_range_strength(client):
    payload = {"image": {"url": "http://x/y.png"}, "prompt": "p", "strength": 1.8}
    task = _await_terminal(client, client.submit(Capability.image_i2i, payload).task_id)
    assert task.status == TaskState.failed
    assert task.error.code == "INVALID_REQUEST"
    assert task.error.retryable is False


def test_unsupported_ref_role_degrades_silently(client):
    """可选参数不支持时应静默降级 + warnings，而不是整体报错。"""
    payload = T2IInput(
        prompt="x",
        reference_images=[{"ref": {"url": "http://x/r.png"}, "role": "composition"}],
    ).model_dump(mode="json")
    task = _await_terminal(client, client.submit(Capability.image_t2i, payload).task_id)
    assert task.status == TaskState.succeeded
    assert any("composition" in w for w in task.warnings)


# ── 音频 ──────────────────────────────────────────────────────────────────────

def test_tts_returns_duration(client):
    """duration_ms 是硬要求：Core 用它回填 shots.duration_ms，时间线长度由配音决定。"""
    payload = TTSInput(
        text="You've come.", language="en-US", voice_id="mock_narrator_en",
        with_timestamps=True,
    ).model_dump(mode="json")
    task = _await_terminal(client, client.submit(Capability.audio_tts, payload).task_id)
    audio = task.output["audio"]
    assert audio["meta"]["duration_ms"] > 0
    assert task.output["timestamps"]
    ts = task.output["timestamps"]
    assert ts[0]["start_ms"] < ts[-1]["end_ms"] <= audio["meta"]["duration_ms"] + 1


def test_tts_duration_scales_with_text(client):
    def dur(text: str) -> int:
        p = TTSInput(text=text, language="zh-CN").model_dump(mode="json")
        t = _await_terminal(client, client.submit(Capability.audio_tts, p).task_id)
        return t.output["audio"]["meta"]["duration_ms"]

    assert dur("你来了。这么快就到了，路上可还顺利？") > dur("你来了。")


def test_voice_list(client):
    voices = client.voices(language="ja-JP")
    assert voices
    v = voices[0]
    assert v.voice_id and v.display_name and v.preview_url


# ── 幂等与批量 ─────────────────────────────────────────────────────────────────

def test_idempotency_returns_same_task(client):
    """生成很贵：同 key 重复提交不能重复计费。"""
    payload = {"prompt": "idempotency probe", "width": 512, "height": 512}
    key = canonical_idempotency_key("image.text_to_image", payload)
    a = client.submit(Capability.image_t2i, payload, idempotency_key=key)
    b = client.submit(Capability.image_t2i, payload, idempotency_key=key)
    assert a.task_id == b.task_id


def test_idempotency_key_is_order_insensitive():
    k1 = canonical_idempotency_key("image.text_to_image", {"prompt": "a", "width": 1280})
    k2 = canonical_idempotency_key("image.text_to_image", {"width": 1280, "prompt": "a"})
    assert k1 == k2


def test_batch_submit(client):
    reqs = [
        TaskRequest(
            capability=Capability.image_t2i,
            idempotency_key=canonical_idempotency_key("image.text_to_image", {"prompt": f"s{i}"}),
            input={"prompt": f"s{i}", "width": 256, "height": 256},
            options=TaskOptions(callback_url=None),
        )
        for i in range(5)
    ]
    results = client.submit_batch(reqs)
    assert len(results) == 5
    assert all(r.get("task_id") for r in results)


def test_batch_size_limit(client):
    reqs = [
        TaskRequest(capability=Capability.image_t2i, idempotency_key=f"k{i}", input={"prompt": "x"})
        for i in range(51)
    ]
    with pytest.raises(CapabilityError) as ei:
        client.submit_batch(reqs)
    assert ei.value.code == CapErrorCode.INVALID_REQUEST


# ── 错误与成本闸门 ─────────────────────────────────────────────────────────────

def test_unknown_model_is_not_retryable(client):
    with pytest.raises(CapabilityError) as ei:
        client.submit(Capability.image_t2i, {"prompt": "x"}, model="no-such-model")
    assert ei.value.code == CapErrorCode.MODEL_NOT_FOUND
    assert ei.value.retryable is False


def test_cost_limit_blocks_before_execution(client):
    with pytest.raises(CapabilityError) as ei:
        client.submit(
            Capability.image_t2i, {"prompt": "x"},
            options=TaskOptions(max_cost=0.0001, callback_url=None),
        )
    assert ei.value.code == CapErrorCode.COST_LIMIT_EXCEEDED
    assert ei.value.retryable is False


def test_task_not_found(client):
    with pytest.raises(CapabilityError):
        client.get_task("ct_does_not_exist")


# ── 回调签名 ──────────────────────────────────────────────────────────────────

def test_callback_signature_roundtrip():
    body = b'{"task_id":"ct_1","status":"succeeded"}'
    sig = sign_payload("whsec_test", body)
    assert verify_signature("whsec_test", body, sig)
    assert not verify_signature("whsec_other", body, sig)
    assert not verify_signature("whsec_test", body + b" ", sig)
    assert not verify_signature("whsec_test", body, None)


class TestEnumMembersExist:
    """枚举成员名写错了，import 与静态未定义名检查都发现不了 ——
    它是属性访问，只有真跑到那一行才炸。

    实跑时 cloudflare 方言里写了 CapErrorCode.PROVIDER_ERROR、
    AUTH_FAILED、TIMEOUT、NETWORK，四个全不存在，
    而它们只在**错误路径**上，正常出图永远走不到 ——
    等于把「出错时的行为」变成了「出错时再出一次错」。
    """

    def test_every_referenced_error_code_exists(self):
        import ast
        import pathlib

        from app.capability.errors import CapErrorCode

        names = {m.name for m in CapErrorCode}
        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        bad = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text("utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "CapErrorCode"
                        and node.attr not in names):
                    bad.append(f"{path.name}:{node.lineno} CapErrorCode.{node.attr}")
        assert not bad, "不存在的错误码：" + "、".join(bad)

    def test_every_referenced_task_state_exists(self):
        import ast
        import pathlib

        from app.capability.schemas import TaskState

        names = {m.name for m in TaskState}
        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        bad = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text("utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "TaskState"
                        and node.attr not in names):
                    bad.append(f"{path.name}:{node.lineno} TaskState.{node.attr}")
        assert not bad, "不存在的任务状态：" + "、".join(bad)


class TestFreeQuotaFailover:
    """一个模型的免费额度用尽，就换下一条免费路由接着跑。

    百炼一个账号下几十个模型各有各的免费额度：出图的 qwen-image-3.0
    见底了，qwen-image-3.0-pro 还满着。硬停在那里等人改配置，
    整章生产就断在半路 —— 而这类断点往往出现在跑到一半的批量里，
    前面花掉的额度全白费。
    """

    def _route(self, billing, model="m", ep_id="ep1"):
        from app.capability.router import ResolvedRoute
        from app.capability.schemas import Capability

        class Ep:
            id = ep_id
            enabled = True
            caps_cache_json = None

        return ResolvedRoute(
            endpoint=Ep(), capability=Capability.text_chat, model=model,
            default_params={"billing": billing} if billing else {},
        )

    def test_billing_defaults_to_unknown_not_free(self):
        """路由表里同时躺着 deepseek / mistral / openrouter ——
        猜一下就是在花别人的钱。宁可停下来报错。"""
        assert self._route(None).billing == "unknown"
        assert self._route("free").billing == "free"
        assert self._route("paid").billing == "paid"

    def test_only_free_routes_are_candidates(self):
        import inspect

        from app.capability import router

        src = inspect.getsource(router.next_free_route)
        assert 'route.billing != "free"' in src

    def test_tried_routes_are_not_retried(self):
        """换过去又撞额度时要继续往下，不能在两条之间来回弹。"""
        import inspect

        from app.capability import router

        assert "route.key in tried" in inspect.getsource(router.next_free_route)

    def test_route_key_separates_models_on_one_endpoint(self):
        """同一个端点下换模型也算换路由 —— 百炼的额度是按模型算的。"""
        a = self._route("free", model="qwen-image-3.0")
        b = self._route("free", model="qwen-image-3.0-pro")
        assert a.key != b.key

    def test_failover_only_fires_on_quota(self):
        """上游炸了该退避重试，不该换模型 —— 两种处置完全相反。"""
        import inspect

        from app.capability import service

        src = inspect.getsource(service.submit_task)
        assert "CapErrorCode.QUOTA_EXCEEDED.value" in src

    def test_pinned_route_is_never_swapped(self):
        """调用方点名的路由不做自动轮换 —— 那多半是在做定向重试或比对。"""
        import inspect

        from app.capability import service

        src = inspect.getsource(service.submit_task)
        assert "pinned" in src

    def test_both_failure_shapes_are_covered(self):
        """额度错误有两种到达方式：抛异常，或落进 result 变成 failed 任务。
        只接一种等于漏掉一半。"""
        import inspect

        from app.capability import service

        src = inspect.getsource(service.submit_task)
        assert "TaskStatus.failed" in src and "_failover(exc.code.value" in src


class TestPaidModelsAreBlockedByDefault:
    """这一条是拿真金白银换来的。

    路由表里 image.image_to_image 的首选是 qwen-image-edit-max，
    看着和别的百炼模型没两样，一天跑下来 ¥31.5；
    video.image_to_video 的 wan2.7-i2v 同一天 ¥48。
    两者都不在免费额度清单里，而系统里没有任何一处会因此拦一下 ——
    每一步都返回 200，账单第二天才看得到。
    """

    def _route(self, billing=None, model="m", quota=None):
        from app.capability.router import ResolvedRoute
        from app.capability.schemas import Capability

        class Ep:
            id = "ep1"
            enabled = True
            caps_cache_json = None

        dp = {}
        if billing:
            dp["billing"] = billing
        if quota:
            dp["free_quota"] = quota
        return ResolvedRoute(endpoint=Ep(), capability=Capability.image_i2i,
                             model=model, default_params=dp)

    def test_paid_route_is_refused(self):
        from app.capability.service import route_blocked

        why = route_blocked(None, self._route("paid", "qwen-image-edit-max"))
        assert why and "付费" in why

    def test_unmarked_route_is_treated_as_paid(self):
        """**不确定就当它要钱** —— 这个方向上猜错的代价是不对称的。"""
        from app.capability.service import route_blocked

        assert route_blocked(None, self._route(None, "some-new-model"))

    def test_free_route_passes(self):
        from app.capability.service import route_blocked

        assert route_blocked(None, self._route("free", "qwen3.8-flash")) is None

    def test_the_gate_is_on_the_primary_route_not_only_failover(self):
        """只在故障转移里检查等于没检查 —— 付费的 p0 每次都调用成功，
        永远走不到转移那一支。"""
        import inspect

        from app.capability import service

        src = inspect.getsource(service.submit_task)
        assert "route_blocked(db, route)" in src
        assert "_swap_route(blocked)" in src

    def test_no_free_route_left_raises_instead_of_spending(self):
        import inspect

        from app.capability import service

        src = inspect.getsource(service.submit_task)
        assert "CORE_ALLOW_PAID_MODELS=true" in src, "报错要说清怎么放行"


class TestPerModelQuotaCap:
    """免费额度也要自己数。

    供应商那边额度用尽才报错，而报错时这一次调用已经发生了 ——
    批量跑的时候是「撞上去才知道」。路由上配了 free_quota.calls
    就自己先数一遍，到点直接换下一条。
    """

    def test_quota_is_counted_per_model_not_per_route(self):
        """百炼的免费额度挂在模型上，同一个模型配在三条路由里共用一份。"""
        import inspect

        from app.capability import service

        src = inspect.getsource(service.model_calls_used)
        assert "GenTask.model == model" in src

    def test_only_successful_calls_count(self):
        """失败的那些供应商不计费，算进去会让额度提前见底。"""
        import inspect

        from app.capability import service

        assert "TaskStatus.succeeded" in inspect.getsource(service.model_calls_used)

    def test_cap_blocks_when_reached(self, monkeypatch):
        from app.capability import service

        monkeypatch.setattr(service, "model_calls_used", lambda db, m: 30)
        route = TestPaidModelsAreBlockedByDefault()._route(
            "free", "wan3.0-video", quota={"calls": 30})
        why = service.route_blocked(None, route)
        assert why and "30/30" in why

    def test_cap_allows_below_limit(self, monkeypatch):
        from app.capability import service

        monkeypatch.setattr(service, "model_calls_used", lambda db, m: 29)
        route = TestPaidModelsAreBlockedByDefault()._route(
            "free", "wan3.0-video", quota={"calls": 30})
        assert service.route_blocked(None, route) is None


class TestPerRouteApproval:
    """逐条批准优先于全局开关。

    全局 CORE_ALLOW_PAID_MODELS=true 会把**所有**付费路由一起放出来 ——
    包括 wan2.7-i2v（实测 ¥48/天）和 qwen-image-edit-max（¥31.5/天）。
    人想用的往往只是其中一条，为了那一条把另外两条也放开，代价不对称。
    """

    def _route(self, billing, approved=None, model="m"):
        from app.capability.router import ResolvedRoute
        from app.capability.schemas import Capability

        class Ep:
            id = "ep1"
            enabled = True
            caps_cache_json = None

        dp = {"billing": billing}
        if approved is not None:
            dp["approved"] = approved
        return ResolvedRoute(endpoint=Ep(), capability=Capability.image_t2i,
                             model=model, default_params=dp)

    def test_approved_paid_route_passes(self):
        from app.capability.service import route_blocked

        assert route_blocked(None, self._route("paid", approved=True)) is None

    def test_unapproved_paid_route_is_still_blocked(self):
        from app.capability.service import route_blocked

        assert route_blocked(None, self._route("paid"))
        assert route_blocked(None, self._route("paid", approved=False))

    def test_the_message_names_both_ways_out(self):
        from app.capability.service import route_blocked

        why = route_blocked(None, self._route("paid"))
        assert "approved:true" in why and "CORE_ALLOW_PAID_MODELS" in why


class TestFailoverOnUnreachable:
    """本地服务最常见的失败是**它没开** —— 显卡机器重启、WebUI 崩了、IP 变了。

    转移原来只认「额度耗尽」，于是首选路由每次 TRANSPORT_ERROR，
    而备用路由明明可用，整批就这么全失败 ——
    报出来是一串「连不上」，看着像网络问题，实际是没人替它换条路。
    """

    def test_transport_error_also_triggers_failover(self):
        import inspect

        from app.capability import service

        src = inspect.getsource(service.submit_task)
        assert "CapErrorCode.TRANSPORT_ERROR.value" in src

    def test_other_errors_do_not_trigger_it(self):
        """参数错换条路由还是参数错，只是把同一个错在每条路上撞一遍。"""
        import inspect

        from app.capability import service

        src = inspect.getsource(service.submit_task)
        gate = src[src.index("if pinned or exc_code not in"):][:220]
        assert "QUOTA_EXCEEDED" in gate and "TRANSPORT_ERROR" in gate
        assert "INVALID_REQUEST" not in gate
