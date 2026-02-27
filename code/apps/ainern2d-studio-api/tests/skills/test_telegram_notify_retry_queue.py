from __future__ import annotations

import os
import sys
from urllib.error import URLError
from uuid import uuid4

import pytest
from sqlalchemy import delete

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from app.services import telegram_notify


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="requires DATABASE_URL for telegram queue retry test",
)
def test_notify_telegram_event_enqueues_retry_on_network_failure(monkeypatch):
    suffix = uuid4().hex[:8]
    tenant_id = f"t_tg_{suffix}"
    project_id = f"p_tg_{suffix}"
    db = SessionLocal()
    try:
        db.add(
            CreativePolicyStack(
                id=f"policy_{suffix}",
                tenant_id=tenant_id,
                project_id=project_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"co_{suffix}",
                idempotency_key=f"idem_{suffix}",
                name="telegram_notify_default",
                status="active",
                stack_json={
                    "enabled": True,
                    "bot_token": "fake-token",
                    "chat_id": "123456",
                    "notify_events": ["task.submitted"],
                },
            )
        )
        db.commit()

        published: list[tuple[str, dict]] = []

        def _fake_publish(topic: str, payload: dict) -> None:
            published.append((topic, payload))

        monkeypatch.setattr(telegram_notify, "publish", _fake_publish)

        def _raise_network(*_args, **_kwargs):
            raise URLError("simulated-network-down")

        monkeypatch.setattr(telegram_notify, "urlopen", _raise_network)
        out = telegram_notify.notify_telegram_event(
            db=db,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type="task.submitted",
            summary="test",
            run_id="run_test",
        )
        assert out["delivered"] is False
        assert out["reason"].startswith("network_error")
        assert published
        topic, payload = published[0]
        assert topic == SYSTEM_TOPICS.ALERT_EVENTS
        assert payload["event_type"] == "telegram.notify.retry"
        assert payload["retry_attempt"] == 1
    finally:
        db.rollback()
        db.execute(
            delete(CreativePolicyStack).where(
                CreativePolicyStack.tenant_id == tenant_id,
                CreativePolicyStack.project_id == project_id,
            )
        )
        db.commit()
        db.close()
