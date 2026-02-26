from __future__ import annotations

from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("observer.metrics_writer")

# Try to import prometheus_client; fall back to log-based recording.
try:
    from prometheus_client import Counter, Histogram, Gauge

    _JOB_RESULT_COUNTER = Counter(
        "ainer_job_result_total",
        "Count of completed jobs by type and status",
        ["job_type", "status"],
    )
    _LATENCY_HISTOGRAM = Histogram(
        "ainer_stage_latency_ms",
        "Latency of pipeline stages in milliseconds",
        ["stage"],
    )
    _QUEUE_DEPTH_GAUGE = Gauge(
        "ainer_queue_depth",
        "Current depth of message queues",
        ["topic"],
    )
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False


class MetricsWriter:
    """Emit operational metrics via Prometheus client or log-based fallback."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_latency(self, stage: str, duration_ms: float) -> None:
        """Record the latency for a pipeline *stage*."""
        if _PROM_AVAILABLE:
            _LATENCY_HISTOGRAM.labels(stage=stage).observe(duration_ms)
        else:
            logger.info(
                "metric_latency | stage={} duration_ms={}",
                stage, duration_ms,
            )

    def record_job_result(self, job_type: str, status: str) -> None:
        """Increment the job-result counter for *job_type* / *status*."""
        if _PROM_AVAILABLE:
            _JOB_RESULT_COUNTER.labels(job_type=job_type, status=status).inc()
        else:
            logger.info(
                "metric_job_result | job_type={} status={}",
                job_type, status,
            )

    def record_queue_depth(self, topic: str, depth: int) -> None:
        """Set the current queue depth for *topic*."""
        if _PROM_AVAILABLE:
            _QUEUE_DEPTH_GAUGE.labels(topic=topic).set(depth)
        else:
            logger.info(
                "metric_queue_depth | topic={} depth={}",
                topic, depth,
            )
