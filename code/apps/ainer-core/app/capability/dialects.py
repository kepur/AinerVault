"""端点方言：Core 与「不说 Capability 契约的服务」之间的翻译层。

中间层还没搭起来之前，Core 需要能直接打 OpenAI 兼容的文本服务，
否则整条翻译链只能对着 mock 空转 —— 管线形态验得再全，也证明不了内容质量。

方言只有两种：
    capability  说 docs/v2/03_CAPABILITY_API_SPEC.md 那套契约，异步、全能力
    openai      说 /chat/completions，同步、仅文本

厂商名依然不出现在这里 —— "openai" 是协议名不是厂商名，
具体是谁（DeepSeek / vLLM / 任意兼容服务）只写在 capability_endpoints 那一行里。

**契约保证由谁兑现**：规范 §4.1 要求 json_schema 输出可解析、§4.2 要求逐段对齐，
并把「内部重试/修复」的责任放在中间层。走 openai 方言时没有中间层，
所以这两件事必须在本模块里做完 —— 少做一层，上游 pipeline 就要被迫写兜底解析，
那正是 v1 到处都是 try/except json.loads 的由来。
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from app.capability.errors import CapabilityError, CapErrorCode
from app.capability.schemas import (
    CONTRACT_VERSION, Capability, CapabilityCatalog, CapabilityEntry,
    HealthResult, ModelDescriptor, Task, TaskState, Usage,
)

log = logging.getLogger(__name__)

DIALECT_CAPABILITY = "capability"
DIALECT_OPENAI = "openai"
DIALECTS = (DIALECT_CAPABILITY, DIALECT_OPENAI)

#: openai 方言能承接的能力。图像/音频不在此列 —— 走这条方言的服务只有文本。
OPENAI_CAPABILITIES = (Capability.text_chat, Capability.text_translate)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)
#: 分段翻译一次最多要求的段数，超了模型必丢段
_TRANSLATE_BATCH = 40


# ── JSON 抽取 ────────────────────────────────────────────────────────────────

def _loads(content: str) -> Any:
    """从模型回复里抠出 JSON。

    即使开了 json_object 模式，模型仍可能裹 ``` 围栏或在前面加一句废话，
    所以围栏剥离和首尾括号定位都得留着。
    """
    txt = _FENCE.sub("", content or "").strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = txt.find(opener), txt.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(txt[i : j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("回复中找不到可解析的 JSON")


def _schema_brief(schema: dict[str, Any]) -> str:
    return (
        "只输出一个 JSON 对象，不要围栏、不要解释、不要前后缀。\n"
        "必须严格符合下面的 JSON Schema：\n"
        + json.dumps(schema, ensure_ascii=False)
    )


class _Caller:
    """把一次 /chat/completions 调用连同重试封起来。"""

    def __init__(self, transport: httpx.Client, base_url: str, headers: dict[str, str],
                 model: str | None, timeout: float) -> None:
        self.transport = transport
        self.url = f"{base_url.rstrip('/')}/chat/completions"
        self.headers = headers
        self.model = model
        self.timeout = timeout
        self.tokens = {"input": 0, "output": 0, "total": 0}
        self.calls = 0

    def __call__(self, messages: list[dict[str, str]], *, temperature: float,
                 max_tokens: int, json_mode: bool) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            # 兼容层统一用 json_object：json_schema 各家支持度参差，
            # 硬发过去会被整个请求拒掉，而 schema 本身已经写进 system 了。
            body["response_format"] = {"type": "json_object"}
        try:
            resp = self.transport.post(
                self.url, json=body, headers=self.headers, timeout=self.timeout
            )
        except httpx.TimeoutException as exc:
            raise CapabilityError(CapErrorCode.UPSTREAM_TIMEOUT, f"上游超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise CapabilityError(CapErrorCode.TRANSPORT_ERROR, f"传输失败: {exc}") from exc

        if resp.status_code >= 400:
            raise _map_openai_error(resp)

        try:
            data = resp.json()
        except Exception as exc:
            raise CapabilityError(
                CapErrorCode.BAD_RESPONSE, f"上游返回非 JSON: {resp.text[:200]}"
            ) from exc

        usage = data.get("usage") or {}
        self.tokens["input"] += int(usage.get("prompt_tokens") or 0)
        self.tokens["output"] += int(usage.get("completion_tokens") or 0)
        self.tokens["total"] += int(usage.get("total_tokens") or 0)
        self.calls += 1

        choices = data.get("choices") or []
        if not choices:
            raise CapabilityError(CapErrorCode.BAD_RESPONSE, "上游未返回 choices")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if not content:
            reason = choices[0].get("finish_reason")
            raise CapabilityError(
                CapErrorCode.BAD_RESPONSE,
                f"上游返回空内容（finish_reason={reason}）"
                + ("，多半是 max_tokens 太小被截断" if reason == "length" else ""),
            )
        return str(content)

    def usage(self, started: float) -> Usage:
        return Usage(
            tokens=dict(self.tokens),
            duration_ms=int((time.time() - started) * 1000),
            units={"calls": float(self.calls)},
        )


def _map_openai_error(resp: httpx.Response) -> CapabilityError:
    """HTTP 状态 → 契约错误码。分清可重试与不可重试，重试逻辑才有意义。"""
    try:
        body = resp.json()
    except Exception:
        body = {}
    err = body.get("error") if isinstance(body, dict) else None
    message = (err or {}).get("message") if isinstance(err, dict) else None
    message = str(message or resp.text[:300] or f"HTTP {resp.status_code}")
    code = {
        400: CapErrorCode.INVALID_REQUEST,
        401: CapErrorCode.UNAUTHORIZED,
        403: CapErrorCode.UNAUTHORIZED,
        404: CapErrorCode.MODEL_NOT_FOUND,
        402: CapErrorCode.QUOTA_EXCEEDED,
        422: CapErrorCode.INVALID_REQUEST,
        429: CapErrorCode.RATE_LIMITED,
    }.get(resp.status_code)
    if code is None:
        code = (
            CapErrorCode.UPSTREAM_ERROR if resp.status_code >= 500
            else CapErrorCode.INVALID_REQUEST
        )
    return CapabilityError(code, message, provider_raw=body or None)


# ── 能力实现 ─────────────────────────────────────────────────────────────────

def _run_chat(call: _Caller, payload: dict[str, Any]) -> dict[str, Any]:
    """text.chat。带 json_schema 时兑现「输出可解析」这条契约保证。"""
    messages = [dict(m) for m in payload.get("messages") or []]
    if not messages:
        raise CapabilityError(CapErrorCode.INVALID_REQUEST, "messages 为空")
    temperature = float(payload.get("temperature", 0.7))
    max_tokens = int(payload.get("max_tokens", 8192))
    rf = payload.get("response_format") or {}
    schema = rf.get("schema") if rf.get("type") == "json_schema" else None
    want_json = bool(schema) or rf.get("type") == "json_object"

    if schema:
        brief = _schema_brief(schema)
        if messages[0].get("role") == "system":
            messages[0]["content"] = f"{messages[0]['content']}\n\n{brief}"
        else:
            messages.insert(0, {"role": "system", "content": brief})

    content = call(messages, temperature=temperature, max_tokens=max_tokens,
                   json_mode=want_json)
    if not want_json:
        return {"text": content}

    try:
        return {"json": _loads(content), "text": content}
    except ValueError:
        pass
    # 修复轮：把坏输出原样回喂。温度压到 0 —— 这一轮要的是听话，不是创造。
    log.warning("json 解析失败，进入修复轮")
    fixed = call(
        messages + [
            {"role": "assistant", "content": content[:4000]},
            {"role": "user", "content": "上面的回复不是合法 JSON。只重新输出 JSON 本身，"
                                        "不要围栏、不要任何解释文字。"},
        ],
        temperature=0.0, max_tokens=max_tokens, json_mode=True,
    )
    try:
        return {"json": _loads(fixed), "text": fixed}
    except ValueError as exc:
        raise CapabilityError(
            CapErrorCode.BAD_RESPONSE, f"两轮均未取得合法 JSON: {exc}"
        ) from exc


_TRANSLATE_RULES = (
    "你是翻译引擎。规则：\n"
    "1. 逐段翻译，输入几段就输出几段，一段都不能少、不能合并、不能拆分。\n"
    "2. 原样保留每段的 id。\n"
    "3. 形如 ⟦E1⟧ 的占位符必须原样保留，不得翻译、不得改写、不得增删。\n"
    "4. 只输出 JSON：{\"segments\":[{\"id\":\"...\",\"text\":\"译文\"}]}"
)


def _run_translate(call: _Caller, payload: dict[str, Any]) -> dict[str, Any]:
    """text.translate。兑现「逐段对齐」这条契约保证：分批 + 缺段补译。"""
    segments = list(payload.get("segments") or [])
    if not segments:
        return {"segments": []}

    head = [_TRANSLATE_RULES, f"源语言：{payload.get('source_language')}　"
                              f"目标语言：{payload.get('target_language')}"]
    if payload.get("style_prompt"):
        head.append(str(payload["style_prompt"]))
    glossary = payload.get("glossary") or []
    if glossary:
        head.append("术语对照（必须严格使用右侧译法）：\n" + "\n".join(
            f"  {g.get('source')} → {g.get('target')}"
            + (f"（{g['note']}）" if g.get("note") else "")
            for g in glossary
        ))
    system = "\n\n".join(head)

    out: dict[str, str] = {}
    for i in range(0, len(segments), _TRANSLATE_BATCH):
        batch = segments[i : i + _TRANSLATE_BATCH]
        _translate_batch(call, system, batch, out)

    missing = [s for s in segments if str(s.get("id")) not in out]
    if missing:
        # 一次补译机会。仍缺就报错 —— 静默丢段比报错危险得多。
        log.warning("翻译缺 %d 段，补译", len(missing))
        _translate_batch(call, system, missing, out)
        still = [str(s.get("id")) for s in segments if str(s.get("id")) not in out]
        if still:
            raise CapabilityError(
                CapErrorCode.BAD_RESPONSE,
                f"上游两轮后仍缺 {len(still)} 段译文（契约 §4.2 要求 id 一一对应）："
                + "、".join(still[:5]),
            )
    return {"segments": [{"id": str(s.get("id")), "text": out[str(s.get("id"))]}
                         for s in segments]}


def _translate_batch(call: _Caller, system: str, batch: list[dict],
                     out: dict[str, str]) -> None:
    payload = [
        {"id": str(s.get("id")), "text": str(s.get("text") or ""),
         **({"speaker": s["speaker"]} if s.get("speaker") else {})}
        for s in batch
    ]
    try:
        content = call(
            [{"role": "system", "content": system},
             {"role": "user", "content": json.dumps({"segments": payload},
                                                    ensure_ascii=False)}],
            temperature=0.3, max_tokens=8192, json_mode=True,
        )
        data = _loads(content)
    except ValueError as exc:
        raise CapabilityError(CapErrorCode.BAD_RESPONSE, f"译文非 JSON: {exc}") from exc
    for item in (data.get("segments") if isinstance(data, dict) else data) or []:
        if not isinstance(item, dict):
            continue
        sid, text = str(item.get("id") or ""), item.get("text")
        if sid and text is not None and sid not in out:
            out[sid] = str(text)


_RUNNERS = {
    Capability.text_chat: _run_chat,
    Capability.text_translate: _run_translate,
}


# ── 对外入口 ─────────────────────────────────────────────────────────────────

def openai_invoke(
    transport: httpx.Client, base_url: str, headers: dict[str, str], *,
    capability: Capability, payload: dict[str, Any], model: str | None,
    timeout: float, task_id: str,
) -> Task:
    runner = _RUNNERS.get(capability)
    if runner is None:
        raise CapabilityError(
            CapErrorCode.CAPABILITY_UNSUPPORTED,
            f"{capability.value} 不能走 openai 方言 —— 该方言只有文本能力。"
            f"图像/音频请指向说 Capability 契约的中间层端点。",
        )
    started = time.time()
    call = _Caller(transport, base_url, headers, model, timeout)
    output = runner(call, payload)
    return Task(
        task_id=task_id, status=TaskState.succeeded, capability=capability,
        output=output, usage=call.usage(started), model=model, provider="openai-compatible",
    )


def openai_health(transport: httpx.Client, base_url: str, headers: dict[str, str],
                  timeout: float) -> HealthResult:
    """OpenAI 兼容服务没有 /health，用 /models 代替 —— 它同时验了鉴权。"""
    try:
        resp = transport.get(f"{base_url.rstrip('/')}/models",
                             headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise CapabilityError(CapErrorCode.TRANSPORT_ERROR, f"传输失败: {exc}") from exc
    if resp.status_code >= 400:
        raise _map_openai_error(resp)
    try:
        models = [str(m.get("id")) for m in (resp.json().get("data") or [])]
    except Exception:
        models = []
    return HealthResult(
        ok=True, version=f"openai-dialect/{CONTRACT_VERSION}",
        upstreams=[{"name": "openai-compatible", "ok": True, "models": models}],
    )


def openai_catalog(transport: httpx.Client, base_url: str, headers: dict[str, str],
                   timeout: float) -> CapabilityCatalog:
    """从 /models 合成能力目录，让后台的模型下拉框照常有东西选。"""
    health = openai_health(transport, base_url, headers, timeout)
    ids = (health.upstreams[0].get("models") if health.upstreams else []) or []
    descriptors = [
        ModelDescriptor(id=m, display_name=m, default=(i == 0), estimated_ms=8000)
        for i, m in enumerate(ids)
    ]
    return CapabilityCatalog(
        capability_version=CONTRACT_VERSION,
        capabilities=[CapabilityEntry(capability=c, models=list(descriptors))
                      for c in OPENAI_CAPABILITIES],
    )
