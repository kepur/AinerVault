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

from app.capability.errors import (
    MAX_ATTEMPTS, RETRY_BACKOFF_SEC, CapabilityError, CapErrorCode,
)
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
#: 被截断时自动抬高的输出预算上限。再高多数服务会直接拒请求。
_MAX_TOKENS_CEILING = 16384


# ── JSON 抽取 ────────────────────────────────────────────────────────────────

#: 推理模型把思考包在这类标签里。内容常含大括号，
#: 不剥掉会让括号扫描从思考里开始找。
_THINK = re.compile(
    r"<(think|thinking|reasoning|scratchpad)>.*?</\1>", re.S | re.I
)


def _balanced_spans(txt: str, limit: int = 40) -> list[tuple[int, int]]:
    """扫出所有括号平衡的 JSON 候选片段，长的优先。

    比 find/rfind 稳：那种切法假设整段里只有一对最外层括号，
    而推理模型常把思考写在 JSON 前后，思考里也有括号 ——
    从第一个 `{` 切到最后一个 `}` 就把两边的杂物一起圈进来了。

    **从每个开括号位置各扫一次**，而不是只认最外层：
    「思考：{不完整 …… 实际答案：{"a":1}」里那个未闭合的开括号
    会把后面真正的 JSON 一起吞掉，只有逐位置试才找得回来。
    字符串内的括号要跳过，否则 {"a": "}"} 会在错误的位置收尾。
    """
    spans: list[tuple[int, int]] = []
    for opener, closer in (("{", "}"), ("[", "]")):
        starts = [i for i, ch in enumerate(txt) if ch == opener][:limit]
        for start in starts:
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(txt)):
                ch = txt[i]
                if esc:
                    esc = False
                    continue
                if in_str:
                    if ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        spans.append((start, i + 1))
                        break
    # 长的优先：嵌套结构里最外层那个才是完整答案
    spans.sort(key=lambda sp: sp[0] - sp[1])
    return spans[:limit]


def _loads(content: str) -> Any:
    """从模型回复里抠出 JSON。

    即使开了 json_object 模式，模型仍可能裹 ``` 围栏、在前面加一句废话、
    或者（推理模型尤其如此）把整段思考写在 JSON 前后。
    """
    txt = _THINK.sub("", content or "")
    txt = _FENCE.sub("", txt).strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass
    for i, j in _balanced_spans(txt):
        try:
            return json.loads(txt[i:j])
        except json.JSONDecodeError:
            continue
    raise ValueError("回复中找不到可解析的 JSON")


def _schema_brief(schema: dict[str, Any]) -> str:
    return (
        "只输出一个 JSON 对象，不要围栏、不要解释、不要前后缀。\n"
        "必须严格符合下面的 JSON Schema：\n"
        + json.dumps(schema, ensure_ascii=False)
    )


class _Truncated(Exception):
    """输出撞上 max_tokens。内部信号，不外泄。"""

    def __init__(self, partial: str = "") -> None:
        self.partial = partial
        super().__init__("output truncated")


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
        """一次调用，带两种独立的重试。

        **传输重试**：连接被断、超时、上游 5xx、被限流。
        跑一本书是上百次调用，网络抖一下就让整步失败太脆 ——
        而失败的那一步可能已经烧了三分钟。
        错误码里早就标了 retryable，只是同步通道从没用上它：
        那套退避只接在异步任务的 attempt 机制上。

        **截断重试**：输出撞 max_tokens，抬高预算重来（见下）。

        两者次数分开算 —— 一次网络抖动不该消耗掉截断重试的机会，反之亦然。
        """
        last: CapabilityError | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                return self._call_once(messages, temperature=temperature,
                                       max_tokens=max_tokens, json_mode=json_mode)
            except CapabilityError as exc:
                if not exc.retryable or attempt == MAX_ATTEMPTS - 1:
                    raise
                last = exc
                delay = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
                log.warning("调用失败可重试（%s），%d 秒后第 %d 次重试：%s",
                            exc.code, delay, attempt + 2, str(exc)[:120])
                time.sleep(delay)
        assert last is not None
        raise last

    def _call_once(self, messages: list[dict[str, str]], *, temperature: float,
                   max_tokens: int, json_mode: bool) -> str:
        """一次调用。被 max_tokens 截断时自动抬高预算重来一次。

        契约要求返回可解析的 JSON，而被截断的 JSON 一定不可解析 ——
        所以这一层必须自己兜住，不能把「上游返回空内容」抛给 pipeline。
        结构化生成的输出常常是输入的好几倍（每项还要带候选和理由），
        调用方很难预先估准，估错的后果又是整个任务失败。
        """
        try:
            return self._once(messages, temperature=temperature,
                              max_tokens=max_tokens, json_mode=json_mode)
        except _Truncated as exc:
            bigger = min(max(max_tokens * 2, 8192), _MAX_TOKENS_CEILING)
            if bigger <= max_tokens:
                raise CapabilityError(
                    CapErrorCode.BAD_RESPONSE,
                    f"输出被截断，且预算已达上限 {max_tokens}。"
                    f"请减少单次请求的条目数（分批调用）。",
                ) from exc
            log.warning("输出被截断（max_tokens=%d），抬到 %d 重试", max_tokens, bigger)
            try:
                return self._once(messages, temperature=temperature,
                                  max_tokens=bigger, json_mode=json_mode)
            except _Truncated as exc2:
                # _Truncated 是内部信号。让它逃出这一层就会变成 500，
                # 调用方只看到「Internal Server Error」，
                # 完全不知道该做的是把单次请求拆小。
                raise CapabilityError(
                    CapErrorCode.BAD_RESPONSE,
                    f"输出两轮均被截断（已抬到 {bigger}）。"
                    f"这一次请求要生成的内容太多 —— 请减少单批条目数。",
                    # 不可重试：同样的请求重试三次还是同样地被截断，
                    # 只是白烧三倍 token。要解决得改调用方的批次大小。
                    retryable=False,
                ) from exc2

    def _once(self, messages: list[dict[str, str]], *, temperature: float,
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
        reason = choices[0].get("finish_reason")
        if reason == "length":
            # 有内容也算截断：JSON 缺右括号照样解析不了
            raise _Truncated(str(content or ""))
        if not content:
            raise CapabilityError(
                CapErrorCode.BAD_RESPONSE, f"上游返回空内容（finish_reason={reason}）"
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
            CapErrorCode.BAD_RESPONSE, f"两轮均未取得合法 JSON: {exc}",
            # **可重试**。这与截断不同：截断是确定性的（同样的请求
            # 必然同样被截断，要改的是批次大小），而「没输出合法 JSON」
            # 是随机的 —— 模型每次生成都不一样，换一次采样很可能就对了。
            # 标成不可重试的代价是整章这一步直接丢掉。
            retryable=True,
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
                retryable=False,
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
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps({"segments": payload},
                                               ensure_ascii=False)},
    ]
    content = call(messages, temperature=0.3, max_tokens=8192, json_mode=True)
    try:
        data = _loads(content)
    except ValueError:
        # 修复轮。text.chat 一直有这一轮，text.translate 没有 ——
        # 同一个问题只在一条路径上防住了，于是翻译遇到非 JSON 就整章失败，
        # 而后面的审查、回译、文化审查全部级联挂掉。
        # 温度压到 0：这一轮要的是听话，不是创造。
        log.warning("译文非 JSON，进入修复轮")
        fixed = call(
            messages + [
                {"role": "assistant", "content": content[:4000]},
                {"role": "user", "content": "上面的回复不是合法 JSON。"
                                            "只重新输出 JSON 本身，"
                                            "不要围栏、不要任何解释文字。"},
            ],
            temperature=0.0, max_tokens=8192, json_mode=True,
        )
        try:
            data = _loads(fixed)
        except ValueError as exc:
            raise CapabilityError(
                CapErrorCode.BAD_RESPONSE, f"两轮均未取得合法译文 JSON: {exc}",
                # 同上：非 JSON 是随机失败，重采样可能就好了
                retryable=True,
            ) from exc
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
