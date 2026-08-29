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
