"""能力契约错误码。与 docs/v2/03_CAPABILITY_API_SPEC.md §6 一一对应。"""
from __future__ import annotations

from enum import Enum


class CapErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    COST_LIMIT_EXCEEDED = "COST_LIMIT_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    CONTENT_POLICY_BLOCKED = "CONTENT_POLICY_BLOCKED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    TASK_FAILED = "TASK_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # 客户端侧
    NO_ROUTE = "NO_ROUTE"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    BAD_RESPONSE = "BAD_RESPONSE"


#: 默认可重试性。中间层返回的 error.retryable 优先于此表。
DEFAULT_RETRYABLE: dict[CapErrorCode, bool] = {
    CapErrorCode.INVALID_REQUEST: False,
    CapErrorCode.CAPABILITY_UNSUPPORTED: False,
    CapErrorCode.MODEL_NOT_FOUND: False,
    CapErrorCode.UNAUTHORIZED: False,
    CapErrorCode.QUOTA_EXCEEDED: False,
    CapErrorCode.COST_LIMIT_EXCEEDED: False,
    CapErrorCode.RATE_LIMITED: True,
    CapErrorCode.CONTENT_POLICY_BLOCKED: False,
    CapErrorCode.UPSTREAM_ERROR: True,
    CapErrorCode.UPSTREAM_TIMEOUT: True,
    CapErrorCode.TASK_FAILED: False,
    CapErrorCode.INTERNAL_ERROR: True,
    CapErrorCode.NO_ROUTE: False,
    CapErrorCode.TRANSPORT_ERROR: True,
    CapErrorCode.BAD_RESPONSE: True,
}

#: HTTP 状态码 → 错误码。用于中间层未返回结构化 code 时的兜底推断。
HTTP_TO_CODE: dict[int, CapErrorCode] = {
    400: CapErrorCode.INVALID_REQUEST,
    401: CapErrorCode.UNAUTHORIZED,
    402: CapErrorCode.QUOTA_EXCEEDED,
    403: CapErrorCode.UNAUTHORIZED,
    404: CapErrorCode.MODEL_NOT_FOUND,
    422: CapErrorCode.CONTENT_POLICY_BLOCKED,
    429: CapErrorCode.RATE_LIMITED,
    500: CapErrorCode.INTERNAL_ERROR,
    502: CapErrorCode.UPSTREAM_ERROR,
    503: CapErrorCode.UPSTREAM_ERROR,
    504: CapErrorCode.UPSTREAM_TIMEOUT,
}

#: 指数退避（秒）。retryable=True 时按此序列重试，最多 3 次。
RETRY_BACKOFF_SEC: tuple[int, ...] = (2, 8, 30)
MAX_ATTEMPTS = 3


class CapabilityError(Exception):
    """能力调用失败。retryable 决定调用方是否重试。"""

    def __init__(
        self,
        code: CapErrorCode | str,
        message: str,
        *,
        retryable: bool | None = None,
        provider_raw: dict | None = None,
        http_status: int | None = None,
    ) -> None:
        self.code = CapErrorCode(code) if isinstance(code, str) else code
        self.message = message
        self.retryable = (
            retryable if retryable is not None else DEFAULT_RETRYABLE.get(self.code, False)
        )
        self.provider_raw = provider_raw
        self.http_status = http_status
        super().__init__(f"[{self.code.value}] {message}")

    def to_json(self) -> dict:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "provider_raw": self.provider_raw,
        }

    @classmethod
    def from_response(cls, status: int, body: dict | None, fallback: str = "") -> CapabilityError:
        body = body or {}
        raw_code = body.get("code")
        try:
            code = CapErrorCode(raw_code) if raw_code else HTTP_TO_CODE.get(
                status, CapErrorCode.UPSTREAM_ERROR
            )
        except ValueError:
            code = HTTP_TO_CODE.get(status, CapErrorCode.UPSTREAM_ERROR)
        return cls(
            code,
            body.get("message") or fallback or f"HTTP {status}",
            retryable=body.get("retryable"),
            provider_raw=body.get("provider_raw"),
            http_status=status,
        )
