from __future__ import annotations

import hashlib
from typing import Any


def build_idempotency_key(*parts: Any) -> str:
	material = "|".join(str(part) for part in parts)
	digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
	return f"idem_{digest}"


def is_valid_idempotency_key(value: str) -> bool:
	return isinstance(value, str) and value.startswith("idem_") and len(value) >= 12

