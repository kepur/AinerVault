from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

_DEFAULT_SECRET = "ainer_dev_auth_secret_change_me"
_DEFAULT_TTL_SECONDS = 60 * 60 * 24


@dataclass
class AuthClaims:
    user_id: str
    email: str
    role: str
    tenant_id: str
    project_id: str
    iat: int
    exp: int
    token_id: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "sub": self.user_id,
            "email": self.email,
            "role": self.role,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "iat": self.iat,
            "exp": self.exp,
            "jti": self.token_id,
        }


def _secret() -> str:
    return os.getenv("AINER_AUTH_SECRET", _DEFAULT_SECRET)


def _ttl_seconds() -> int:
    raw = os.getenv("AINER_AUTH_TOKEN_TTL_SECONDS", str(_DEFAULT_TTL_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_TTL_SECONDS
    return max(60, value)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("utf-8"))


def _sign(signing_input: str) -> str:
    digest = hmac.new(
        _secret().encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(digest)


def create_access_token(
    *,
    user_id: str,
    email: str,
    role: str,
    tenant_id: str,
    project_id: str,
) -> str:
    now = int(time.time())
    claims = AuthClaims(
        user_id=user_id,
        email=email,
        role=role,
        tenant_id=tenant_id,
        project_id=project_id,
        iat=now,
        exp=now + _ttl_seconds(),
        token_id=f"tok_{uuid4().hex}",
    )
    header = {"alg": "HS256", "typ": "JWT"}
    header_part = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = _b64url_encode(json.dumps(claims.model_dump(), separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}"
    signature = _sign(signing_input)
    return f"{signing_input}.{signature}"


def decode_access_token(token: str) -> AuthClaims:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("AUTH-VALIDATION-001: invalid token format")
    header_part, payload_part, signature_part = parts
    signing_input = f"{header_part}.{payload_part}"
    expected = _sign(signing_input)
    if not hmac.compare_digest(expected, signature_part):
        raise ValueError("AUTH-VALIDATION-001: invalid token signature")

    try:
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive parsing
        raise ValueError("AUTH-VALIDATION-001: invalid token payload") from exc

    now = int(time.time())
    exp = int(payload.get("exp", 0))
    if exp <= now:
        raise ValueError("AUTH-VALIDATION-001: token expired")

    return AuthClaims(
        user_id=str(payload.get("sub") or ""),
        email=str(payload.get("email") or ""),
        role=str(payload.get("role") or "viewer"),
        tenant_id=str(payload.get("tenant_id") or "default"),
        project_id=str(payload.get("project_id") or "default"),
        iat=int(payload.get("iat", now)),
        exp=exp,
        token_id=str(payload.get("jti") or ""),
    )


def extract_bearer_token(auth_header: str | None) -> str:
    if not auth_header:
        raise ValueError("AUTH-VALIDATION-001: missing authorization header")
    if not auth_header.startswith("Bearer "):
        raise ValueError("AUTH-VALIDATION-001: invalid authorization header")
    token = auth_header[len("Bearer ") :].strip()
    if not token:
        raise ValueError("AUTH-VALIDATION-001: empty bearer token")
    return token
