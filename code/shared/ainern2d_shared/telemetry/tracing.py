from __future__ import annotations

from contextlib import contextmanager

try:
	from opentelemetry import trace
except Exception:
	trace = None


@contextmanager
def start_span(span_name: str):
	if trace is None:
		yield None
		return

	tracer = trace.get_tracer("ainern2d")
	with tracer.start_as_current_span(span_name) as span:
		yield span

