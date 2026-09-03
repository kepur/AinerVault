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
    HealthResult, ModelDescriptor, Task, TaskState, Usage, Voice,
)

log = logging.getLogger(__name__)

DIALECT_CAPABILITY = "capability"
DIALECT_OPENAI = "openai"
DIALECT_CLOUDFLARE = "cloudflare"
DIALECT_DASHSCOPE = "dashscope"
DIALECTS = (DIALECT_CAPABILITY, DIALECT_OPENAI, DIALECT_CLOUDFLARE,
            DIALECT_DASHSCOPE)

#: openai 方言能承接的能力。图像/音频不在此列 —— 走这条方言的服务只有文本。
OPENAI_CAPABILITIES = (Capability.text_chat, Capability.text_translate)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)
#: 分段翻译一次最多要求的段数，超了模型必丢段
_TRANSLATE_BATCH = 40
#: 被截断时自动抬高的输出预算上限。再高多数服务会直接拒请求。
_MAX_TOKENS_CEILING = 16384
#: 单次重试最长等待。provider 偶尔会报出几十分钟的重置时间，
#: 那种情况该失败并让人换个模型，而不是把任务挂在那里。
_MAX_RETRY_WAIT = 75.0


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
                # provider 说了等多久就听它的 —— 固定退避在
                # 按分钟重置配额的服务上永远等不够
                told = getattr(exc, "retry_after", None)
                delay = (
                    min(float(told) + 0.5, _MAX_RETRY_WAIT) if told
                    else RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
                )
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


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """从响应里读出「该等多久」。

    固定退避 (2, 8, 30) 在限流严格的 provider 上必然失败 ——
    Groq 的 token 配额按分钟重置，等 2 秒再打还是 429，
    三次退避加起来 40 秒也不够，于是整步失败。
    而它明确告诉了该等多久，只是没人读。

    三处依次尝试：标准 Retry-After 头、provider 自定义的
    x-ratelimit-reset-* 头、错误消息里的「try again in 1m2.28s」。
    """
    for key in ("retry-after", "x-ratelimit-reset-tokens",
                "x-ratelimit-reset-requests"):
        raw = resp.headers.get(key)
        if not raw:
            continue
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m)?\s*$", str(raw))
        if m:
            n = float(m.group(1))
            unit = m.group(2) or "s"
            return n / 1000 if unit == "ms" else n * 60 if unit == "m" else n
    try:
        msg = str((resp.json().get("error") or {}).get("message") or "")
    except Exception:
        msg = resp.text[:300]
    # 「Please try again in 1m2.28s」/「try again in 4.5s」
    m = re.search(r"try again in\s+(?:(\d+)m)?([\d.]+)s", msg, re.I)
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    return None


def _map_openai_error(resp: httpx.Response) -> CapabilityError:
    """HTTP 状态 → 契约错误码。分清可重试与不可重试，重试逻辑才有意义。"""
    try:
        body = resp.json()
    except Exception:
        body = {}
    err = body.get("error") if isinstance(body, dict) else None
    message = (err or {}).get("message") if isinstance(err, dict) else None
    message = str(message or resp.text[:300] or f"HTTP {resp.status_code}")
    # 「单次请求超过每分钟配额」被有些 provider 报成 400 而不是 429
    # （Groq 就是）。当成普通 INVALID_REQUEST 的话，
    # 错误消息里只有一串组织 id 和限额数字，调用方看不出该做什么 ——
    # 而该做的是把这一批拆小，不是重试。
    if resp.status_code == 400 and re.search(
        r"request too large|too many tokens|context length|maximum context",
        message, re.I,
    ):
        return CapabilityError(
            CapErrorCode.INVALID_REQUEST,
            f"单次请求超出该模型的配额或上下文上限，**需要减小批次**"
            f"（不是重试能解决的）。上游原文：{message[:200]}",
            retryable=False, provider_raw=body or None,
        )

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
    err = CapabilityError(code, message, provider_raw=body or None)
    # 把「该等多久」挂在异常上，让重试层用它代替固定退避
    err.retry_after = _retry_after_seconds(resp)
    return err


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


# ══════════════════════════════════════════════════════════════════════════════
# cloudflare 方言 —— Workers AI 直连
# ══════════════════════════════════════════════════════════════════════════════
#
# 与 openai 方言同一个理由：能力中间层还没上线，而图像这条线不接真模型
# 就永远只能对着占位图验证管线。Workers AI 有免费额度、
# 一次同步 HTTP 就出图，是这个阶段成本最低的真实来源。
#
# 它与契约有两处对不上，都得在这一层抹平：
#
#   **没有任务队列。** 契约里图像走 submit → 回调/轮询 → 取产物；
#   Workers AI 是一次请求一张图。所以这里直接返回终态 Task，
#   由 submit_task 走同步分支。
#
#   **回的是字节不是 URL。** flux 系列把 JPEG 以 base64 塞在 result.image，
#   SD 系列直接回二进制 PNG。两种都要落盘换成 URL ——
#   契约下游（参考图、i2i、交付清单）认的只有 URL。

#: 同步方言：没有任务队列，submit 也得当场跑完
SYNC_ONLY_DIALECTS = (DIALECT_OPENAI, DIALECT_CLOUDFLARE, DIALECT_DASHSCOPE)

#: **每个模型只吃自己 schema 里的字段，多传一个就整个请求 400。**
#: flux-1-schnell 只认 prompt 与 steps —— 传 width/height/seed/negative_prompt
#: 都会被拒（"Additional or unevaluated properties not allowed"），
#: 而那三样恰恰是画幅、可复现、去干扰的全部手段。
#: 所以这里按模型列出可传字段，不在表里的一律不传。
#: 不这么做的话，换个模型整批出图会全军覆没，且错误信息指向的是
#: 「多传了字段」而不是「这个模型不支持画幅」，很难看懂。
_CF_PARAMS: tuple[tuple[str, frozenset[str]], ...] = (
    ("flux-1-schnell", frozenset({"prompt", "steps"})),
    # SD 系列（含 lightning / dreamshaper / leonardo）吃全套
    ("", frozenset({"prompt", "negative_prompt", "width", "height", "seed",
                    "num_steps", "guidance"})),
)

#: 产出形态：flux 与 leonardo 回 {"result":{"image":"<base64>"}}，
#: SD 系列回裸 PNG。按 content-type 判，模型名只作兜底
_CF_B64_MODELS = ("flux", "leonardo")

#: 步数上限。各家不同，传大了同样是 400
_CF_MAX_STEPS = {"flux-1-schnell": 8}
_CF_DEFAULT_MAX_STEPS = 20


def _cf_allowed(model: str) -> frozenset[str]:
    for key, allowed in _CF_PARAMS:
        if not key or key in model:
            return allowed
    return _CF_PARAMS[-1][1]


def _cf_error(resp: httpx.Response) -> CapabilityError:
    """Workers AI 的错误也裹在 {success:false, errors:[...]} 里。"""
    code, retryable = CapErrorCode.UPSTREAM_ERROR, resp.status_code >= 500
    detail = resp.text[:400]
    try:
        body = resp.json()
        errs = body.get("errors") or []
        if errs:
            detail = "; ".join(
                f"{e.get('code')}: {e.get('message')}" for e in errs if isinstance(e, dict)
            ) or detail
    except Exception:  # noqa: BLE001
        pass
    if resp.status_code in (401, 403):
        code = CapErrorCode.UNAUTHORIZED
    elif resp.status_code == 404:
        # 模型名写错与账号没开通 AI 都回 404，分不开，所以把两种可能都说出来
        code = CapErrorCode.INVALID_REQUEST
        detail += "（模型名写错，或该账号还没开通 Workers AI）"
    elif resp.status_code == 429:
        code, retryable = CapErrorCode.RATE_LIMITED, True
    elif 400 <= resp.status_code < 500:
        code = CapErrorCode.INVALID_REQUEST
    return CapabilityError(code, f"Cloudflare {resp.status_code}: {detail}",
                           retryable=retryable)


def _cf_image_payload(payload: dict[str, Any], model: str) -> dict[str, Any]:
    """契约的图像入参 → Workers AI 的入参，按模型裁掉不支持的字段。"""
    allowed = _cf_allowed(model)
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    cap = next((v for k, v in _CF_MAX_STEPS.items() if k in model),
               _CF_DEFAULT_MAX_STEPS)
    raw: dict[str, Any] = {
        "prompt": str(payload.get("prompt") or "").strip(),
        "negative_prompt": str(payload.get("negative_prompt") or "").strip(),
        "width": payload.get("width"),
        "height": payload.get("height"),
        "seed": params.get("seed"),
        "guidance": params.get("guidance"),
    }
    steps = params.get("steps")
    steps = max(1, min(int(steps), cap)) if isinstance(steps, int) else min(8, cap)
    raw["steps"] = raw["num_steps"] = steps

    out: dict[str, Any] = {}
    for key, val in raw.items():
        if key not in allowed or val in (None, "", 0):
            continue
        out[key] = val
    if not out.get("prompt"):
        raise CapabilityError(CapErrorCode.INVALID_REQUEST, "图像生成缺少 prompt")
    return out


def cloudflare_invoke(
    transport: httpx.Client, base_url: str, headers: dict[str, str], *,
    capability: Capability, payload: dict[str, Any], model: str | None,
    timeout: float, task_id: str,
) -> Task:
    """跑一次 Workers AI，产物落盘后按契约的 Task 形态返回。"""
    from app.capability.mediastore import store_b64, store_bytes

    if capability not in (Capability.image_t2i, Capability.image_i2i):
        raise CapabilityError(
            CapErrorCode.INVALID_REQUEST,
            f"cloudflare 方言目前只接图像生成，{capability.value} 请走中间层端点。",
        )
    if not model:
        raise CapabilityError(
            CapErrorCode.INVALID_REQUEST,
            "cloudflare 方言必须在路由上指定模型，例如 "
            "@cf/black-forest-labs/flux-1-schnell",
        )

    url = f"{base_url.rstrip('/')}/run/{model.lstrip('/')}"
    body = _cf_image_payload(payload, model)
    try:
        resp = transport.post(url, json=body, headers=headers, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise CapabilityError(CapErrorCode.UPSTREAM_TIMEOUT, f"Cloudflare 超时：{exc}",
                              retryable=True) from exc
    except httpx.HTTPError as exc:
        raise CapabilityError(CapErrorCode.TRANSPORT_ERROR, f"Cloudflare 连接失败：{exc}",
                              retryable=True) from exc
    if resp.status_code >= 400:
        raise _cf_error(resp)

    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
    if ctype == "application/json" or (
            not ctype.startswith("image/")
            and any(k in model for k in _CF_B64_MODELS)):
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise CapabilityError(
                CapErrorCode.UPSTREAM_ERROR,
                f"Cloudflare 回了非 JSON 内容（content-type={ctype}）",
            ) from exc
        img = ((data.get("result") or {}) if isinstance(data, dict) else {}).get("image")
        if not img:
            raise CapabilityError(
                CapErrorCode.UPSTREAM_ERROR,
                f"Cloudflare 响应里没有图片：{str(data)[:200]}")
        media = store_b64(str(img), mime="image/jpeg")
    else:
        media = store_bytes(resp.content, mime=ctype or "image/png")

    media["meta"] = {
        k: body[k] for k in ("width", "height", "seed", "num_steps", "steps")
        if k in body
    }

    warnings: list[str] = []
    # **参考图用不上，但不能默默丢掉。** Workers AI 没有 IP-Adapter，
    # 也没有面部参考通道 —— 传了也不会被读。
    # 静默忽略的后果是：脸参考图明明生成好了、挂到每一期了、
    # 交付清单里也有，出来的脸却每张都不一样，而没有任何地方说过为什么。
    if payload.get("reference_images"):
        warnings.append(
            f"Cloudflare Workers AI 不支持参考图（{model} 无面部/风格参考通道），"
            f"本次的 {len(payload['reference_images'])} 张参考图未被使用 —— "
            f"跨期同一性这一轮只由文字描述保证"
        )
    dropped = sorted(set(_cf_allowed("")) - _cf_allowed(model)
                     & {k for k in ("width", "height", "seed", "negative_prompt")
                        if payload.get(k) or (payload.get("params") or {}).get(k)})
    if dropped:
        warnings.append(
            f"{model} 不接受 {'、'.join(dropped)}，已略去 —— "
            f"换成 stable-diffusion-xl-lightning 可用这些"
        )

    return Task(
        task_id=task_id, status=TaskState.succeeded,
        capability=capability.value, model=model, provider="cloudflare",
        output={"images": [media]},
        # 免费额度内成本记 0，但产出张数要记 —— 用量统计靠它
        usage={"cost": 0.0, "units": {"images": 1.0}},
        warnings=warnings or None,
    )


def cloudflare_health(transport: httpx.Client, base_url: str,
                      headers: dict[str, str], timeout: float) -> HealthResult:
    """Workers AI 没有健康检查端点，用模型列表代替。"""
    try:
        resp = transport.get(f"{base_url.rstrip('/')}/models/search",
                             headers=headers, timeout=timeout, params={"per_page": 1})
        ok = resp.status_code < 400
    except httpx.HTTPError:
        ok = False
    return HealthResult(ok=ok, version=f"cloudflare-dialect/{CONTRACT_VERSION}",
                        contract_version=CONTRACT_VERSION)


# ══ dashscope 方言 ══════════════════════════════════════════════════════════
#
# 阿里云百炼。它和前面两种方言最大的差别不在参数形状，而在**产物形态**：
#
#   Cloudflare  直接回字节 —— 存下来就完了
#   DashScope   回一个带 Expires 签名的 OSS 临时 URL —— **必须当场下载**
#
# 那个 URL 十几分钟就失效。把它当成 asset.url 存进库，是「当时点开能看、
# 第二天全成死链」这类问题里最难查的一种：库里有行、有 URL、状态是 ready，
# 只有图不见了。所以本方言的每条产出路径末尾都必须落盘，没有例外。
#
# 第二个差别是能力覆盖面：这是目前唯一一个图像、语音、视频都能打的直连方言。
# 图像与语音同步，视频异步（提交拿 task_id 再轮询）——
# 但对上游而言三者都走 invoke()，视频的异步是本模块内部的事。

#: 同步端点。图像（含参考图编辑）与语音都在这里，靠 model 区分。
_DS_MM = "/api/v1/services/aigc/multimodal-generation/generation"
#: 视频合成是独立的异步端点
_DS_VIDEO = "/api/v1/services/aigc/video-generation/video-synthesis"
_DS_TASKS = "/api/v1/tasks"

#: 视频轮询节奏。首轮等久一点没意义 —— 排队时间远大于这个粒度
_DS_POLL_SEC = 5.0

#: 画幅只接受 "宽*高"（星号，不是小写 x）
_DS_SIZE_SEP = "*"

#: 语音：契约给的是 voice_id，这里原样透传。
#: 没给就用一个中性音色兜底 —— 但会带 warning，
#: 因为「配音表明明配了音色，出来的却全是同一个人」查起来很费劲。
_DS_FALLBACK_VOICE = "Cherry"


def _ds_is_tts(model: str) -> bool:
    return "-tts" in model


def _ds_is_video(model: str) -> bool:
    return "-i2v" in model or "-t2v" in model or "video" in model


def _ds_error(resp: httpx.Response) -> CapabilityError:
    """百炼的错误裹在 {code, message, request_id} 里，HTTP 码常常是 400 一把抓。"""
    code, retryable = CapErrorCode.UPSTREAM_ERROR, resp.status_code >= 500
    detail = resp.text[:400]
    ds_code = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            ds_code = str(body.get("code") or "")
            detail = str(body.get("message") or detail)
    except Exception:  # noqa: BLE001
        pass
    # **额度判断必须排在 401/403 之前。** 额度用尽回的也是 403，
    # 而「UNAUTHORIZED」会把人送去查 API key —— key 是好的，
    # 白查一圈才发现是额度。实跑撞到的真实码是
    # `AllocationQuota.FreeTierOnly`，不是我原先猜的
    # Arrearage / InsufficientQuota / FreeQuotaExhausted：
    # **供应商的错误码只能观察，不能猜。**
    # **限流要排在额度之前判。** 限流码里也带 Quota
    #（`Throttling.RateQuota`），按子串先撞额度那一支的话，
    # 一次本该退避重试的限流会被判成不可重试的额度耗尽 ——
    # 整批生成会在一次瞬时限流上永久停住。
    if resp.status_code == 429 or "Throttling" in ds_code:
        code, retryable = CapErrorCode.RATE_LIMITED, True
    elif "Quota" in ds_code or "Arrearage" in ds_code:
        # 不可重试：重试只会把同一个错再撞一遍。
        # 处置方式和别的错完全不同 —— 去充值或换模型，不是改参数
        code = CapErrorCode.UPSTREAM_ERROR
        detail += "（该模型的额度已用尽，需开通付费或把这条路由换到别的模型）"
    elif resp.status_code in (401, 403) or ds_code in ("InvalidApiKey", "Unauthorized"):
        code = CapErrorCode.UNAUTHORIZED
    elif 400 <= resp.status_code < 500:
        code = CapErrorCode.INVALID_REQUEST
    return CapabilityError(
        code, f"DashScope {resp.status_code} {ds_code}: {detail}".strip(),
        retryable=retryable)


def _ds_fetch(transport: httpx.Client, url: str, *, mime: str,
              timeout: float) -> dict[str, object]:
    """把签名 URL 的内容取回来落盘。**方言里最不能省的一步。**"""
    from app.capability.mediastore import store_bytes

    try:
        resp = transport.get(url, timeout=timeout)
    except httpx.HTTPError as exc:
        raise CapabilityError(
            CapErrorCode.TRANSPORT_ERROR,
            f"DashScope 产物下载失败（签名 URL 有效期很短，失败即不可恢复）：{exc}",
            retryable=True) from exc
    if resp.status_code >= 400:
        raise CapabilityError(
            CapErrorCode.UPSTREAM_ERROR,
            f"DashScope 产物 URL 返回 {resp.status_code} —— 多半是签名已过期")
    return store_bytes(resp.content, mime=mime)


def _ds_data_url(transport: httpx.Client, ref: Any, timeout: float) -> str | None:
    """AssetRefIn → data URL。

    百炼的编辑模型**接受 base64 data URL**，不要求参考图有公网地址 ——
    这一条是身份锚能不能跨期保持同一张脸的关键：
    本地生成的锚图不必先传到某个对象存储上去。
    """
    import base64
    from pathlib import Path

    from app.capability.mediastore import media_root

    if not isinstance(ref, dict):
        return None
    b64 = ref.get("b64")
    mime = str(ref.get("mime") or "image/png")
    if b64:
        return f"data:{mime};base64,{b64}"
    url = str(ref.get("url") or "")
    if not url:
        return None
    # 本地产物直接读文件，不绕一圈 HTTP —— 容器里 public_base_url 未必自指
    if "/media/" in url:
        path = Path(media_root()) / url.rsplit("/media/", 1)[-1].split("?")[0]
        if path.exists():
            raw = path.read_bytes()
            from app.capability.mediastore import sniff
            return f"data:{sniff(raw, mime)};base64,{base64.b64encode(raw).decode()}"
    if url.startswith(("http://", "https://")):
        try:
            resp = transport.get(url, timeout=timeout)
            if resp.status_code < 400:
                from app.capability.mediastore import sniff
                got = sniff(resp.content, mime)
                return f"data:{got};base64,{base64.b64encode(resp.content).decode()}"
        except httpx.HTTPError:
            return None
    return None


def _ds_image_body(transport: httpx.Client, payload: dict[str, Any], model: str,
                   *, capability: Capability, timeout: float,
                   warnings: list[str]) -> dict[str, Any]:
    """契约的图像入参 → 百炼的 multimodal 形状。"""
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise CapabilityError(CapErrorCode.INVALID_REQUEST, "图像生成缺少 prompt")

    content: list[dict[str, Any]] = []
    # 底图（i2i 的原图）排在参考图之前 —— 编辑模型按出现顺序理解「改哪张」
    if capability in (Capability.image_i2i, Capability.image_edit):
        base = _ds_data_url(transport, payload.get("image"), timeout)
        if not base:
            raise CapabilityError(
                CapErrorCode.INVALID_REQUEST,
                f"{capability.value} 需要底图，但 image 取不到内容")
        content.append({"image": base})

    from app.pipelines.base import as_items

    used = 0
    for item in as_items(payload, "reference_images"):
        data_url = _ds_data_url(transport, item.get("ref"), timeout)
        if data_url is None:
            warnings.append(f"参考图 {item.get('tag') or item.get('role')} 取不到内容，已跳过")
            continue
        content.append({"image": data_url})
        used += 1
    if used and "-edit" not in model:
        # 非编辑模型收下参考图也不会读。说清楚比默默丢掉重要 ——
        # 「脸参考图明明挂上了，出来的脸每张都不一样」是最难查的一类
        warnings.append(
            f"{model} 不是编辑模型，{used} 张参考图不会被读取；"
            f"跨期同一性请改用 qwen-image-edit-max / qwen-image-edit-plus")
        content = [c for c in content if "image" not in c] or []
        if capability in (Capability.image_i2i, Capability.image_edit):
            raise CapabilityError(
                CapErrorCode.INVALID_REQUEST,
                f"{capability.value} 需要编辑模型，{model} 不接受底图")

    content.append({"text": prompt})

    params: dict[str, Any] = {"n": int(payload.get("n") or 1), "watermark": False}
    neg = str(payload.get("negative_prompt") or "").strip()
    if neg:
        params["negative_prompt"] = neg
    w, h = payload.get("width"), payload.get("height")
    # **编辑模型也要传画幅。** 不传的话输出跟随底图尺寸，
    # 而身份锚是方形头肩像 —— 于是 16:9 的交付里混进一批 1:1 的镜头，
    # 要到剪辑台上才发现。
    if w and h:
        params["size"] = f"{int(w)}{_DS_SIZE_SEP}{int(h)}"
    extra = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    for key in ("seed", "prompt_extend"):
        if extra.get(key) is not None:
            params[key] = extra[key]
    return {"model": model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": params}


def _ds_tts_body(payload: dict[str, Any], model: str,
                 warnings: list[str]) -> dict[str, Any]:
    """契约的 TTS 入参 → 百炼形状。

    **instruct 是这条方言最有价值的一处。** 配音表算出来的是
    音质／语速／力度／状态这些维度，此前要为每个引擎写一层数值映射；
    instruct 版直接吃一句自然语言，维度可以原样说出来。
    """
    text = str(payload.get("text") or "").strip()
    if not text:
        raise CapabilityError(CapErrorCode.INVALID_REQUEST, "TTS 缺少 text")
    voice = payload.get("voice_id")
    if not voice:
        voice = _DS_FALLBACK_VOICE
        warnings.append(
            f"未指定音色，回落到 {_DS_FALLBACK_VOICE} —— "
            f"整章都用同一个兜底音色时，听起来像「配音没生效」而不像「缺配置」")
    body_in: dict[str, Any] = {"text": text, "voice": str(voice)}

    extra = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    # 配音表算出来的中性描述存在 style_prompt 里（voice.to_tts_params）。
    # 认这个键，是为了让「配音表 → 引擎」这一段不需要额外映射层：
    # 音质／语速／力度／状态本来就是一句话能说清的事。
    instruct = str(extra.get("instruct") or extra.get("style_prompt") or "").strip()
    if instruct:
        if "instruct" in model:
            body_in["instruct"] = instruct
        else:
            warnings.append(
                f"{model} 不接受表演指示，「{instruct[:24]}」未生效；"
                f"换 qwen3-tts-instruct-flash 可用")
    params: dict[str, Any] = {}
    lang = str(payload.get("language") or "")
    if lang:
        params["language_type"] = _DS_LANG.get(lang.split("-")[0].lower(), "Auto")
    return {"model": model, "input": body_in, "parameters": params}


#: 百炼要的是语种名不是 BCP-47
_DS_LANG = {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean",
            "fr": "French", "de": "German", "es": "Spanish", "it": "Italian",
            "ru": "Russian", "pt": "Portuguese", "ar": "Arabic", "id": "Indonesian"}


def _ds_video_body(transport: httpx.Client, payload: dict[str, Any], model: str,
                   timeout: float) -> dict[str, Any]:
    first = _ds_data_url(transport, payload.get("first_frame"), timeout)
    if not first:
        raise CapabilityError(
            CapErrorCode.INVALID_REQUEST,
            "图生视频需要首帧，但 first_frame 取不到内容")
    # media 的元素是**带角色的对象**：{"type": "first_frame"|"last_frame", "url": ...}。
    # 这一处踩了两层：
    #   传地址字符串 → "No such property: type for class: java.lang.String"
    #   传 {"type":"image","image":...} → 提交时回 200 PENDING，
    #     执行时才 FAILED，错误里才说出合法的 type 取值
    # **提交成功不代表形状对** —— 这个端点是异步校验的，
    # 所以接它的时候必须轮到终态再判断，不能看 200 就当通过。
    body_in: dict[str, Any] = {"media": [{"type": "first_frame", "url": first}]}
    last = _ds_data_url(transport, payload.get("last_frame"), timeout)
    if last:
        body_in["media"].append({"type": "last_frame", "url": last})
    prompt = str(payload.get("prompt") or "").strip()
    if prompt:
        body_in["prompt"] = prompt
    params: dict[str, Any] = {}
    dur = payload.get("duration_ms")
    if dur:
        params["duration"] = max(1, round(int(dur) / 1000))
    return {"model": model, "input": body_in, "parameters": params}



def retrying(fn: Any, *, what: str) -> Any:
    """把一次可重试的调用包成带退避的调用。

    **退避原来只接在文本调用上。** `_Caller.run` 里那套（读 provider 的
    Retry-After、按 2/8/30 退避）是给 chat 用的，图像／语音／视频这条路
    一次都没经过它 —— 错误码里明明标了 retryable，却没有任何地方读它。

    结果是：整批出图撞上一次瞬时限流就整批失败。而批量场景恰恰是最容易
    撞限流的地方（29 张图连着发），也是失败代价最高的地方
    （前面已经生成的都还没落库）。

    what 只用于日志 —— 出错时要看得出是哪一类调用在退避，
    「调用失败可重试」这一行如果不说是什么调用，等于没说。
    """
    last: CapabilityError | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return fn()
        except CapabilityError as exc:
            if not exc.retryable or attempt == MAX_ATTEMPTS - 1:
                raise
            last = exc
            told = getattr(exc, "retry_after", None)
            delay = (
                min(float(told) + 0.5, _MAX_RETRY_WAIT) if told
                else RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
            )
            log.warning("%s 失败可重试（%s），%d 秒后第 %d 次：%s",
                        what, exc.code, delay, attempt + 2, str(exc)[:120])
            time.sleep(delay)
    assert last is not None
    raise last

def _ds_post(transport: httpx.Client, base_url: str, headers: dict[str, str],
             path: str, body: dict[str, Any], *, timeout: float,
             extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
    hdrs = {**headers, "Content-Type": "application/json", **(extra_headers or {})}

    def once() -> dict[str, Any]:
        try:
            resp = transport.post(f"{base_url.rstrip('/')}{path}", json=body,
                                  headers=hdrs, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise CapabilityError(CapErrorCode.UPSTREAM_TIMEOUT,
                                  f"DashScope 超时：{exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise CapabilityError(CapErrorCode.TRANSPORT_ERROR,
                                  f"DashScope 连接失败：{exc}", retryable=True) from exc
        if resp.status_code >= 400:
            err = _ds_error(resp)
            after = _retry_after_seconds(resp)
            if after is not None:
                err.retry_after = after
            raise err
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise CapabilityError(CapErrorCode.BAD_RESPONSE,
                                  "DashScope 返回非 JSON") from exc

    return retrying(once, what=f"DashScope {path.rsplit('/', 1)[-1]}")


def _ds_await_video(transport: httpx.Client, base_url: str, headers: dict[str, str],
                    task_ref: str, *, timeout: float) -> str:
    """轮询到出片，返回视频 URL。

    上游看到的是一次同步调用 —— 百炼的 task_id 不是我们的 task_id，
    也没有回调通道，暴露出去只会多一套对不上的状态机。
    代价是超时后那次生成就找不回来了，所以超时信息里必须带上
    供应商的 task_id：那是人工去控制台捞回来的唯一线索。
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            resp = transport.get(f"{base_url.rstrip('/')}{_DS_TASKS}/{task_ref}",
                                 headers=headers, timeout=30)
        except httpx.HTTPError as exc:
            raise CapabilityError(CapErrorCode.TRANSPORT_ERROR,
                                  f"DashScope 轮询失败：{exc}", retryable=True) from exc
        if resp.status_code >= 400:
            raise _ds_error(resp)
        out = (resp.json() or {}).get("output") or {}
        state = str(out.get("task_status") or "").upper()
        if state == "SUCCEEDED":
            url = out.get("video_url") or ((out.get("results") or [{}])[0] or {}).get("url")
            if not url:
                raise CapabilityError(CapErrorCode.BAD_RESPONSE,
                                      f"DashScope 视频任务成功但没有 URL：{str(out)[:200]}")
            return str(url)
        if state in ("FAILED", "CANCELED", "UNKNOWN"):
            # 入参形状错也走到这里 —— 提交那一步回的是 200 PENDING。
            # 所以这条错误必须把供应商原话带全：它是唯一说出
            # 「合法取值是什么」的地方，截断了就只剩「任务失败」。
            detail = str(out.get("message") or out.get("code") or "")
            code = (CapErrorCode.INVALID_REQUEST
                    if str(out.get("code") or "").startswith("Invalid")
                    else CapErrorCode.UPSTREAM_ERROR)
            raise CapabilityError(
                code, f"DashScope 视频任务 {state}（task_id={task_ref}）：{detail}")
        if time.monotonic() >= deadline:
            raise CapabilityError(
                CapErrorCode.UPSTREAM_TIMEOUT,
                f"DashScope 视频任务在 {timeout:.0f}s 内没出片，"
                f"供应商 task_id={task_ref}（生成仍在继续，可到控制台取回）",
                retryable=False)
        time.sleep(min(_DS_POLL_SEC, max(0.5, deadline - time.monotonic())))


def dashscope_invoke(
    transport: httpx.Client, base_url: str, headers: dict[str, str], *,
    capability: Capability, payload: dict[str, Any], model: str | None,
    timeout: float, task_id: str,
) -> Task:
    """跑一次百炼，产物落盘后按契约的 Task 形态返回。"""
    if not model:
        raise CapabilityError(
            CapErrorCode.INVALID_REQUEST,
            "dashscope 方言必须在路由上指定模型，例如 qwen-image-3.0")
    warnings: list[str] = []

    if capability in (Capability.image_t2i, Capability.image_i2i,
                      Capability.image_edit):
        body = _ds_image_body(transport, payload, model, capability=capability,
                              timeout=timeout, warnings=warnings)
        data = _ds_post(transport, base_url, headers, _DS_MM, body, timeout=timeout)
        urls = _ds_images(data)
        if not urls:
            raise CapabilityError(CapErrorCode.UPSTREAM_ERROR,
                                  f"DashScope 响应里没有图片：{str(data)[:200]}")
        images = [_ds_fetch(transport, u, mime="image/png", timeout=timeout)
                  for u in urls]
        usage = data.get("usage") or {}
        for img in images:
            img["meta"] = {k: usage[k] for k in ("output_width", "output_height")
                           if k in usage}
        return Task(task_id=task_id, status=TaskState.succeeded,
                    capability=capability.value, model=model, provider="dashscope",
                    output={"images": images},
                    usage=Usage(cost=0.0, units={"images": float(len(images))}),
                    warnings=warnings or None)

    if capability == Capability.audio_tts:
        body = _ds_tts_body(payload, model, warnings)
        data = _ds_post(transport, base_url, headers, _DS_MM, body, timeout=timeout)
        audio = ((data.get("output") or {}).get("audio") or {})
        url = audio.get("url")
        if not url:
            raise CapabilityError(CapErrorCode.UPSTREAM_ERROR,
                                  f"DashScope 响应里没有音频：{str(data)[:200]}")
        media = _ds_fetch(transport, str(url), mime="audio/wav", timeout=timeout)
        # **时长权威是 TTS 的真实时长**（交付清单靠它对齐字幕与镜头长度）。
        # 百炼不回时长，只能从 wav 头算 —— 算不出就不填，绝不估。
        dur = _wav_duration_ms(media)
        if dur is not None:
            # **写进 meta，不是顶层。** 产物落库时只有 item["meta"] 会进
            # Asset.meta_json，而回挂音频时长读的正是那一处 ——
            # 写在顶层的话，音频生成得好好的、asset 也挂上了，
            # 唯独 duration_ms 永远是 None，镜头长度回填全程静默跳过。
            media.setdefault("meta", {})["duration_ms"] = dur
        else:
            warnings.append("未能从音频读出时长，交付清单的时间码会缺这一段")
        chars = float((data.get("usage") or {}).get("characters") or 0)
        return Task(task_id=task_id, status=TaskState.succeeded,
                    capability=capability.value, model=model, provider="dashscope",
                    output={"audio": media},
                    usage=Usage(cost=0.0, units={"characters": chars}),
                    warnings=warnings or None)

    if capability == Capability.video_i2v:
        body = _ds_video_body(transport, payload, model, timeout)
        data = _ds_post(transport, base_url, headers, _DS_VIDEO, body,
                        timeout=min(timeout, 60),
                        extra_headers={"X-DashScope-Async": "enable"})
        ref = ((data.get("output") or {}).get("task_id"))
        if not ref:
            raise CapabilityError(CapErrorCode.BAD_RESPONSE,
                                  f"DashScope 未回 task_id：{str(data)[:200]}")
        url = _ds_await_video(transport, base_url, headers, str(ref), timeout=timeout)
        media = _ds_fetch(transport, url, mime="video/mp4", timeout=max(timeout, 120))
        return Task(task_id=task_id, status=TaskState.succeeded,
                    capability=capability.value, model=model, provider="dashscope",
                    output={"video": media},
                    usage=Usage(cost=0.0, units={"videos": 1.0}),
                    warnings=warnings or None)

    raise CapabilityError(
        CapErrorCode.INVALID_REQUEST,
        f"dashscope 方言不接 {capability.value}，请走中间层端点。")


def _ds_images(data: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for choice in ((data.get("output") or {}).get("choices") or []):
        for part in ((choice.get("message") or {}).get("content") or []):
            if isinstance(part, dict) and part.get("image"):
                out.append(str(part["image"]))
    return out


def _wav_duration_ms(media: dict[str, object]) -> int | None:
    """从落盘的 wav 头读真实时长。读不出返回 None —— 宁可缺也不要估。"""
    import struct
    from pathlib import Path

    from app.capability.mediastore import media_root

    url = str(media.get("url") or "")
    if "/media/" not in url:
        return None
    path = Path(media_root()) / url.rsplit("/media/", 1)[-1]
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return None
    pos, rate, bits, ch, frames = 12, 0, 0, 0, 0
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        if cid == b"fmt " and pos + 8 + 16 <= len(raw):
            ch, rate = struct.unpack("<HI", raw[pos + 10:pos + 16])
            bits = struct.unpack("<H", raw[pos + 22:pos + 24])[0]
        elif cid == b"data":
            frames = size
            break
        pos += 8 + size + (size & 1)
    if not (rate and bits and ch and frames):
        return None
    return int(frames / (rate * ch * bits / 8) * 1000)


def dashscope_health(transport: httpx.Client, base_url: str,
                     headers: dict[str, str], timeout: float) -> HealthResult:
    """百炼没有健康检查端点，用兼容模式的模型列表代替。"""
    try:
        resp = transport.get(f"{base_url.rstrip('/')}/compatible-mode/v1/models",
                             headers=headers, timeout=timeout)
        ok = resp.status_code < 400
    except httpx.HTTPError:
        ok = False
    return HealthResult(ok=ok, version=f"dashscope-dialect/{CONTRACT_VERSION}",
                        contract_version=CONTRACT_VERSION)


#: 能力 → 该走哪些模型。**手写而不是从 /models 拉**：
#: 百炼的模型列表两百多个，绝大多数是文本模型，混在图像下拉框里没法选；
#: 而且列表里看不出「哪个能吃参考图」—— 那恰恰是选型时唯一要紧的信息。
_DS_CATALOG: tuple[tuple[Capability, tuple[tuple[str, str], ...]], ...] = (
    (Capability.image_t2i, (
        # 默认放 2.0 Pro 而不是 3.0：**免费额度差一个数量级**
        #（3.0 是 10 张，2.0 Pro 是 100 张），而出一整本的素材参考图
        # 动辄几十张，用 3.0 会在半路撞 AllocationQuota.FreeTierOnly。
        # 质量更高的留在下面，要用的人自己选。
        ("qwen-image-2.0-pro-2026-06-22", "通义万相 2.0 Pro · 文生图（额度充裕）"),
        ("qwen-image-max", "通义万相 Max · 文生图"),
        ("qwen-image-3.0", "通义万相 3.0 · 文生图（免费额度很少）"),
        ("qwen-image-3.0-pro", "通义万相 3.0 Pro · 文生图（免费额度很少）"),
        ("z-image-turbo", "Z-Image Turbo · 快速出图"),
    )),
    (Capability.image_i2i, (
        ("qwen-image-edit-max", "通义图像编辑 Max · 吃参考图，跨期保脸靠它"),
        ("qwen-image-edit-plus", "通义图像编辑 Plus"),
    )),
    (Capability.image_edit, (
        ("qwen-image-edit-max", "通义图像编辑 Max"),
        ("qwen-image-edit-plus", "通义图像编辑 Plus"),
    )),
    (Capability.audio_tts, (
        ("qwen3-tts-instruct-flash", "Qwen3 TTS Instruct · 可用自然语言下表演指示"),
        ("qwen3-tts-flash", "Qwen3 TTS Flash · 命名音色"),
    )),
    (Capability.video_i2v, (
        ("wan2.7-i2v", "万相 2.7 · 图生视频"),
    )),
)


def dashscope_catalog(transport: httpx.Client, base_url: str,
                      headers: dict[str, str], timeout: float) -> CapabilityCatalog:
    """百炼没有能力发现端点，目录是手写的。"""
    entries = []
    for cap, models in _DS_CATALOG:
        entries.append(CapabilityEntry(
            capability=cap,
            models=[ModelDescriptor(id=mid, display_name=name, default=(i == 0),
                                    estimated_ms=12000 if cap != Capability.video_i2v
                                    else 120000)
                    for i, (mid, name) in enumerate(models)],
        ))
    return CapabilityCatalog(capability_version=CONTRACT_VERSION,
                             capabilities=entries)


#: 可用音色。**性别是按厂商命名推断的提示，不是实测结果** ——
#: 名字看起来像女名的标 female，如此而已。真要确认得听。
#: 所以配音表里这一栏必须可人工改：机器给初值，人听过之后覆写。
#: 年龄不列 —— 编一个「中年」出来，会让人以为系统真的知道。
_DS_VOICES: tuple[tuple[str, str], ...] = (
    ("Cherry", "female"), ("Jennifer", "female"), ("Katerina", "female"),
    ("Jada", "female"), ("Sunny", "female"), ("Kiki", "female"),
    ("Serena", "female"), ("Chelsie", "female"),
    ("Ethan", "male"), ("Ryan", "male"), ("Elias", "male"), ("Dylan", "male"),
    ("Marcus", "male"), ("Roy", "male"), ("Peter", "male"), ("Rocky", "male"),
    ("Eric", "male"), ("Aiden", "male"), ("Nofish", "male"), ("Li", "male"),
)


def dashscope_voices(*, language: str | None = None,
                     gender: str | None = None) -> list[Voice]:
    """音色清单。百炼没有列举接口，这份表是手写的。"""
    want = (gender or "").lower()
    return [
        Voice(voice_id=vid, display_name=vid, gender=g,
              languages=["zh", "en", "ja", "ko", "fr", "de", "es", "it", "ru", "pt"],
              tags=["dashscope", "qwen3-tts"])
        for vid, g in _DS_VOICES
        if not want or want == g
    ]
