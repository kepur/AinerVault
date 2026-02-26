from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class QueueMessage:
	event_type: str
	payload: dict[str, Any]
	trace_id: str
	correlation_id: str
	idempotency_key: str

