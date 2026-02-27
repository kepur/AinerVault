from __future__ import annotations

from datetime import datetime, timezone
import json
from time import perf_counter
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.exc import PendingRollbackError, SQLAlchemyError
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from app.api.deps import publish

_TG_CIRCUIT_LOCK = threading.Lock()
_TG_CIRCUIT_STATE: dict[str, dict[str, float | int]] = {}
_TG_CIRCUIT_FAILURE_THRESHOLD = 3
_TG_CIRCUIT_OPEN_SECONDS = 60
_TG_DEFAULT_MAX_RETRY_ATTEMPTS = 3


def _load_telegram_settings(db: Session, *, tenant_id: str, project_id: str) -> dict:
    try:
        row = db.execute(
            select(CreativePolicyStack).where(
                CreativePolicyStack.tenant_id == tenant_id,
                CreativePolicyStack.project_id == project_id,
                CreativePolicyStack.name == "telegram_notify_default",
                CreativePolicyStack.deleted_at.is_(None),
            )
        ).scalars().first()
    except PendingRollbackError:
        return {}
    except SQLAlchemyError:
        return {}
    if row is None:
        return {}
    return dict(row.stack_json or {})


def _event_subscribed(settings: dict, event_type: str) -> bool:
    raw_events = settings.get("notify_events") or []
    events = {str(item).strip() for item in raw_events if str(item).strip()}
    if not events:
        return True
    return event_type in events or "*" in events


def _build_message(
    *,
    event_type: str,
    summary: str,
    run_id: str | None,
    job_id: str | None,
    trace_id: str | None,
    correlation_id: str | None,
    extra: dict | None,
) -> str:
    lines = [
        f"[Ainer Studio] {summary}",
        f"event={event_type}",
    ]
    if run_id:
        lines.append(f"run_id={run_id}")
    if job_id:
        lines.append(f"job_id={job_id}")
    if trace_id:
        lines.append(f"trace_id={trace_id}")
    if correlation_id:
        lines.append(f"correlation_id={correlation_id}")
    if extra:
        lines.append(f"extra={json.dumps(extra, ensure_ascii=False)}")
    lines.append(f"time={datetime.now(timezone.utc).isoformat()}")
    return "\n".join(lines)


def _tg_circuit_key(tenant_id: str, project_id: str) -> str:
    return f"{tenant_id}:{project_id}"


def _tg_circuit_open(key: str) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    with _TG_CIRCUIT_LOCK:
        state = _TG_CIRCUIT_STATE.get(key) or {}
        opened_until = float(state.get("opened_until", 0))
        return opened_until > now


def _tg_record_success(key: str) -> None:
    with _TG_CIRCUIT_LOCK:
        _TG_CIRCUIT_STATE[key] = {"failures": 0, "opened_until": 0}


def _tg_record_failure(key: str) -> None:
    now = datetime.now(timezone.utc).timestamp()
    with _TG_CIRCUIT_LOCK:
        state = _TG_CIRCUIT_STATE.get(key) or {"failures": 0, "opened_until": 0}
        failures = int(state.get("failures", 0)) + 1
        opened_until = float(state.get("opened_until", 0))
        if failures >= _TG_CIRCUIT_FAILURE_THRESHOLD:
            opened_until = now + _TG_CIRCUIT_OPEN_SECONDS
        _TG_CIRCUIT_STATE[key] = {"failures": failures, "opened_until": opened_until}


def _enqueue_telegram_retry(
    *,
    tenant_id: str,
    project_id: str,
    event_type: str,
    summary: str,
    run_id: str | None,
    job_id: str | None,
    trace_id: str | None,
    correlation_id: str | None,
    extra: dict | None,
    retry_attempt: int,
    max_retry_attempts: int,
    retry_reason: str,
    delay_ms: int,
) -> None:
    publish(
        SYSTEM_TOPICS.ALERT_EVENTS,
        {
            "event_type": "telegram.notify.retry",
            "tenant_id": tenant_id,
            "project_id": project_id,
            "source_event_type": event_type,
            "summary": summary,
            "run_id": run_id,
            "job_id": job_id,
            "trace_id": trace_id,
            "correlation_id": correlation_id,
            "extra": extra or {},
            "retry_attempt": retry_attempt,
            "max_retry_attempts": max_retry_attempts,
            "retry_reason": retry_reason,
            "delay_ms": delay_ms,
        },
    )


def notify_telegram_event(
    *,
    db: Session,
    tenant_id: str,
    project_id: str,
    event_type: str,
    summary: str,
    run_id: str | None = None,
    job_id: str | None = None,
    trace_id: str | None = None,
    correlation_id: str | None = None,
    extra: dict | None = None,
    timeout_ms: int = 3000,
    queue_on_failure: bool = True,
    retry_attempt: int = 0,
    max_retry_attempts: int = _TG_DEFAULT_MAX_RETRY_ATTEMPTS,
) -> dict:
    settings = _load_telegram_settings(db, tenant_id=tenant_id, project_id=project_id)
    if not settings:
        return {"delivered": False, "reason": "telegram_settings_not_found"}
    if not bool(settings.get("enabled", False)):
        return {"delivered": False, "reason": "telegram_disabled"}
    if not _event_subscribed(settings, event_type):
        return {"delivered": False, "reason": "event_not_subscribed"}

    bot_token = str(settings.get("bot_token") or "").strip()
    chat_id = str(settings.get("chat_id") or "").strip()
    thread_id = str(settings.get("thread_id") or "").strip()
    parse_mode = str(settings.get("parse_mode") or "Markdown").strip()
    if not bot_token:
        return {"delivered": False, "reason": "missing_bot_token"}
    if not chat_id:
        return {"delivered": False, "reason": "missing_chat_id"}
    circuit_key = _tg_circuit_key(tenant_id, project_id)
    if _tg_circuit_open(circuit_key):
        if queue_on_failure and retry_attempt < max_retry_attempts:
            _enqueue_telegram_retry(
                tenant_id=tenant_id,
                project_id=project_id,
                event_type=event_type,
                summary=summary,
                run_id=run_id,
                job_id=job_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                extra=extra,
                retry_attempt=retry_attempt + 1,
                max_retry_attempts=max_retry_attempts,
                retry_reason="circuit_open",
                delay_ms=2000,
            )
        return {"delivered": False, "reason": "circuit_open"}

    message = _build_message(
        event_type=event_type,
        summary=summary,
        run_id=run_id,
        job_id=job_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        extra=extra,
    )
    req_payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if thread_id:
        req_payload["message_thread_id"] = thread_id

    request = Request(
        url=f"https://api.telegram.org/bot{bot_token}/sendMessage",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        data=json.dumps(req_payload).encode("utf-8"),
    )
    started = perf_counter()
    timeout_seconds = max(0.5, min(20.0, timeout_ms / 1000.0))

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            latency_ms = int((perf_counter() - started) * 1000)
            status_code = int(getattr(response, "status", 0) or 0)
            parsed = {}
            try:
                parsed = json.loads(response.read().decode("utf-8") or "{}")
            except Exception:
                parsed = {}
            telegram_ok = bool(parsed.get("ok", 200 <= status_code < 300))
            if (200 <= status_code < 300) and telegram_ok:
                _tg_record_success(circuit_key)
            else:
                _tg_record_failure(circuit_key)
                if queue_on_failure and retry_attempt < max_retry_attempts:
                    _enqueue_telegram_retry(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        event_type=event_type,
                        summary=summary,
                        run_id=run_id,
                        job_id=job_id,
                        trace_id=trace_id,
                        correlation_id=correlation_id,
                        extra=extra,
                        retry_attempt=retry_attempt + 1,
                        max_retry_attempts=max_retry_attempts,
                        retry_reason="telegram_not_ok",
                        delay_ms=1000 * (2 ** retry_attempt),
                    )
            return {
                "delivered": (200 <= status_code < 300) and telegram_ok,
                "status_code": status_code,
                "latency_ms": latency_ms,
                "telegram_ok": telegram_ok,
            }
    except HTTPError as exc:
        _tg_record_failure(circuit_key)
        if queue_on_failure and retry_attempt < max_retry_attempts and exc.code >= 500:
            _enqueue_telegram_retry(
                tenant_id=tenant_id,
                project_id=project_id,
                event_type=event_type,
                summary=summary,
                run_id=run_id,
                job_id=job_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                extra=extra,
                retry_attempt=retry_attempt + 1,
                max_retry_attempts=max_retry_attempts,
                retry_reason=f"http_error:{exc.code}",
                delay_ms=1000 * (2 ** retry_attempt),
            )
        return {
            "delivered": False,
            "status_code": exc.code,
            "reason": f"http_error:{exc.code}",
        }
    except URLError as exc:
        _tg_record_failure(circuit_key)
        if queue_on_failure and retry_attempt < max_retry_attempts:
            _enqueue_telegram_retry(
                tenant_id=tenant_id,
                project_id=project_id,
                event_type=event_type,
                summary=summary,
                run_id=run_id,
                job_id=job_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                extra=extra,
                retry_attempt=retry_attempt + 1,
                max_retry_attempts=max_retry_attempts,
                retry_reason=f"network_error:{exc.reason}",
                delay_ms=1000 * (2 ** retry_attempt),
            )
        return {
            "delivered": False,
            "status_code": None,
            "reason": f"network_error:{exc.reason}",
        }
    except Exception as exc:  # pragma: no cover
        _tg_record_failure(circuit_key)
        if queue_on_failure and retry_attempt < max_retry_attempts:
            _enqueue_telegram_retry(
                tenant_id=tenant_id,
                project_id=project_id,
                event_type=event_type,
                summary=summary,
                run_id=run_id,
                job_id=job_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                extra=extra,
                retry_attempt=retry_attempt + 1,
                max_retry_attempts=max_retry_attempts,
                retry_reason=f"notify_error:{str(exc)}",
                delay_ms=1000 * (2 ** retry_attempt),
            )
        return {
            "delivered": False,
            "status_code": None,
            "reason": f"notify_error:{str(exc)}",
        }
