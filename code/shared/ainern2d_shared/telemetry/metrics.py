from __future__ import annotations

try:
	from prometheus_client import Counter
except Exception:
	Counter = None


if Counter is not None:
	REQUEST_COUNTER = Counter(
		"ainer_requests_total",
		"Total number of handled requests",
		["service", "route", "status"],
	)
else:
	REQUEST_COUNTER = None


def record_request(service: str, route: str, status: str) -> None:
	if REQUEST_COUNTER is None:
		return
	REQUEST_COUNTER.labels(service=service, route=route, status=status).inc()

