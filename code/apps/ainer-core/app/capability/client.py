"""Capability API 客户端。

契约见 docs/v2/03_CAPABILITY_API_SPEC.md。本模块是 Core 与外部世界的唯一出口 ——
任何厂商名都不应出现在此文件之外。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.capability.dialects import (
    DIALECT_CLOUDFLARE, DIALECT_OPENAI, SYNC_ONLY_DIALECTS, cloudflare_health,
    cloudflare_invoke, openai_catalog, openai_health, openai_invoke,
)
from app.capability.errors import CapabilityError, CapErrorCode
from app.capability.router import ResolvedRoute
from app.capability.schemas import (
    CONTRACT_VERSION, Capability, CapabilityCatalog, HealthResult, Task,
    TaskAccepted, TaskOptions, TaskRequest, TaskState, Voice,
)
from app.config import settings

log = logging.getLogger(__name__)


def canonical_idempotency_key(
    capability: str, payload: dict[str, Any], *,
    endpoint_id: str | None = None, model: str | None = None,
) -> str:
    """幂等键 = sha256(capability + 端点 + 模型 + 规范化 input)。

    同 key 重复提交必须返回同一 task_id、不重复计费 —— 生成很贵，
    重试/重复点击/任务重放都不能烧两次钱。

    端点与模型必须进 key：不进的话，把路由从 mock 切到真模型、
    或把 flash 换成 pro，同一段提示词会直接命中旧任务、秒回上一家的答案。
    换模型的当下是最不该拿到缓存的时刻，而这种命中不报错、只是结果不对。
    """
    blob = json.dumps(
        {"capability": capability, "endpoint": endpoint_id, "model": model,
         "input": payload},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sign_payload(secret: str, raw_body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, raw_body: bytes, header_value: str | None) -> bool:
    """回调签名校验，常数时间比较。"""
    if not header_value:
        return False
    return hmac.compare_digest(sign_payload(secret, raw_body), header_value.strip())


class CapabilityClient:
    """一个端点一个客户端实例。同步实现 —— pipeline 是普通函数，不需要 async 传染。"""

    def __init__(
        self,
        base_url: str,
        *,
        auth: dict[str, Any] | None = None,
        timeout_sec: int = 60,
        dialect: str = "capability",
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth or {}
        self.timeout_sec = timeout_sec
        self.dialect = dialect or "capability"
        self._client = client
        self._owns_client = client is None

    # ── 生命周期 ──────────────────────────────────────────────
    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_sec)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> CapabilityClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @classmethod
    def from_route(cls, route: ResolvedRoute, **kw: Any) -> CapabilityClient:
        ep = route.endpoint
        return cls(
            ep.base_url, auth=ep.auth_json or {}, timeout_sec=ep.timeout_sec,
            dialect=ep.dialect or "capability", **kw,
        )

    # ── 传输 ─────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.dialect not in SYNC_ONLY_DIALECTS:
            h["X-Capability-Version"] = CONTRACT_VERSION
        mode = str(self.auth.get("mode") or "none").lower()
        token = self.auth.get("token")
        if mode == "bearer" and token:
            h["Authorization"] = f"Bearer {token}"
        elif mode == "header" and token:
            h[str(self.auth.get("header_name") or "X-API-Key")] = str(token)
        return h

    def _request(
        self, method: str, path: str, *, json_body: dict | None = None,
        params: dict | None = None, timeout: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = self.client.request(
                method, url, json=json_body, params=params,
                headers=self._headers(), timeout=timeout or self.timeout_sec,
            )
        except httpx.TimeoutException as exc:
            raise CapabilityError(
                CapErrorCode.UPSTREAM_TIMEOUT, f"{method} {path} 超时: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise CapabilityError(
                CapErrorCode.TRANSPORT_ERROR, f"{method} {path} 传输失败: {exc}"
            ) from exc

        if resp.status_code >= 400:
            body: dict | None = None
            try:
                body = resp.json()
            except Exception:
                pass
            raise CapabilityError.from_response(resp.status_code, body, resp.text[:400])

        if not resp.content:
            return {}
        try:
            data = resp.json()
        except Exception as exc:
            raise CapabilityError(
                CapErrorCode.BAD_RESPONSE, f"{path} 返回非 JSON: {resp.text[:200]}"
            ) from exc
        if not isinstance(data, dict):
            raise CapabilityError(CapErrorCode.BAD_RESPONSE, f"{path} 返回非对象")
        return data

    # ── Discovery ─────────────────────────────────────────────
    def health(self) -> HealthResult:
        if self.dialect == DIALECT_CLOUDFLARE:
            return cloudflare_health(
                self.client, self.base_url, self._headers(), self.timeout_sec)
        if self.dialect == DIALECT_OPENAI:
            return openai_health(self.client, self.base_url, self._headers(), 10)
        return HealthResult.model_validate(self._request("GET", "/health", timeout=10))

    def capabilities(self) -> CapabilityCatalog:
        if self.dialect == DIALECT_OPENAI:
            return openai_catalog(self.client, self.base_url, self._headers(), 20)
        return CapabilityCatalog.model_validate(self._request("GET", "/capabilities", timeout=20))

    def voices(self, *, language: str | None = None, gender: str | None = None) -> list[Voice]:
        params = {k: v for k, v in {"language": language, "gender": gender}.items() if v}
        data = self._request("GET", "/voices", params=params, timeout=20)
        return [Voice.model_validate(v) for v in data.get("voices", [])]

    # ── 任务 ─────────────────────────────────────────────────
    def _build_request(
        self, capability: Capability | str, payload: dict[str, Any], *,
        model: str | None = None, options: TaskOptions | None = None,
        idempotency_key: str | None = None,
    ) -> TaskRequest:
        cap = Capability(capability) if isinstance(capability, str) else capability
        opts = options or TaskOptions()
        if opts.callback_url is None:
            opts = opts.model_copy(
                update={
                    "callback_url": f"{settings.public_base_url}/api/v2/gen-tasks/callback",
                    "callback_secret": settings.callback_secret,
                }
            )
        return TaskRequest(
            capability=cap,
            idempotency_key=idempotency_key or canonical_idempotency_key(cap.value, payload),
            model=model,
            input=payload,
            options=opts,
        )

    def submit(
        self, capability: Capability | str, payload: dict[str, Any], *,
        model: str | None = None, options: TaskOptions | None = None,
        idempotency_key: str | None = None,
    ) -> TaskAccepted:
        """异步提交。同 idempotency_key 重复提交返回同一 task_id。"""
        if self.dialect in SYNC_ONLY_DIALECTS:
            raise CapabilityError(
                CapErrorCode.INVALID_REQUEST,
                f"{self.dialect} 方言没有任务队列，请走 invoke()（submit_task 会"
                f"对同步方言自动改走同步分支）。",
            )
        req = self._build_request(
            capability, payload, model=model, options=options, idempotency_key=idempotency_key
        )
        data = self._request("POST", "/tasks", json_body=req.model_dump(mode="json"))
        return TaskAccepted.model_validate(data)

    def submit_batch(self, requests: list[TaskRequest]) -> list[dict[str, Any]]:
        """批量提交。一章分镜可能一次 40–200 个任务，逐个 HTTP 太慢。"""
        if not requests:
            return []
        if len(requests) > 50:
            raise CapabilityError(CapErrorCode.INVALID_REQUEST, "单批最多 50 个任务")
        data = self._request(
            "POST", "/tasks:batch",
            json_body={"tasks": [r.model_dump(mode="json") for r in requests]},
        )
        return list(data.get("results") or [])

    def invoke(
        self, capability: Capability | str, payload: dict[str, Any], *,
        model: str | None = None, options: TaskOptions | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        """同步快捷通道。

        走中间层时只有 text.* 能用 —— 图像视频耗时长，占着连接不放
        会拖垮批量生成。但**直连供应商的同步方言不受这条限制**：
        它们根本没有任务队列，一次 HTTP 就是全部（Workers AI 出一张图
        几秒钟），此时禁止同步等于禁止使用。
        """
        cap = Capability(capability) if isinstance(capability, str) else capability
        if not cap.value.startswith("text.") and self.dialect not in SYNC_ONLY_DIALECTS:
            raise CapabilityError(
                CapErrorCode.INVALID_REQUEST, f"{cap.value} 不可走同步通道，请用 submit()"
            )
        req = self._build_request(
            cap, payload, model=model, options=options, idempotency_key=idempotency_key
        )
        if self.dialect == DIALECT_CLOUDFLARE:
            return cloudflare_invoke(
                self.client, self.base_url, self._headers(),
                capability=cap, payload=req.input, model=model,
                timeout=min(req.options.timeout_ms / 1000, self.timeout_sec),
                task_id=req.idempotency_key,
            )
        if self.dialect == DIALECT_OPENAI:
            return openai_invoke(
                self.client, self.base_url, self._headers(),
                capability=cap, payload=req.input, model=model,
                timeout=min(req.options.timeout_ms / 1000, self.timeout_sec),
                task_id=req.idempotency_key,
            )
        data = self._request(
            "POST", "/invoke", json_body=req.model_dump(mode="json"),
            timeout=min(req.options.timeout_ms / 1000, 60),
        )
        task = Task.model_validate(data)
        if task.status == TaskState.failed and task.error:
            raise CapabilityError(
                task.error.code, task.error.message,
                retryable=task.error.retryable, provider_raw=task.error.provider_raw,
            )
        return task

    def get_task(self, task_id: str) -> Task:
        return Task.model_validate(self._request("GET", f"/tasks/{task_id}", timeout=20))

    def cancel(self, task_id: str) -> Task:
        return Task.model_validate(self._request("POST", f"/tasks/{task_id}:cancel", timeout=20))
