"""Service-level E2E for SKILL 11/12/13 event contract and feedback loop closure."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.services.base_skill import SkillContext


def _assert_envelope_context(envelope, ctx: SkillContext) -> None:
    assert envelope.tenant_id == ctx.tenant_id
    assert envelope.project_id == ctx.project_id
    assert envelope.run_id == ctx.run_id
    assert envelope.trace_id == ctx.trace_id
    assert envelope.correlation_id == ctx.correlation_id
    assert envelope.schema_version == ctx.schema_version
    assert envelope.idempotency_key


def _rabbitmq_pop_json(
    amqp_url: str,
    queue_name: str,
    timeout_sec: float = 8.0,
    expected_event_type: str | None = None,
) -> dict | None:
    try:
        import pika
    except Exception:
        return None

    conn = pika.BlockingConnection(pika.URLParameters(amqp_url))
    ch = conn.channel()
    ch.queue_declare(queue=queue_name, durable=True)

    deadline = time.time() + timeout_sec
    payload: dict | None = None
    while time.time() < deadline:
        method, _props, body = ch.basic_get(queue=queue_name, auto_ack=False)
        if method is not None:
            candidate = json.loads(body.decode("utf-8"))
            ch.basic_ack(delivery_tag=method.delivery_tag)
            if expected_event_type is None or candidate.get("event_type") == expected_event_type:
                payload = candidate
                break
        time.sleep(0.1)

    conn.close()
    return payload


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.add.return_value = None
    db.commit.return_value = None
    db.flush.return_value = None
    return db


@pytest.fixture
def ctx():
    return SkillContext(
        tenant_id="t_e2e_11_13",
        project_id="p_e2e_11_13",
        run_id="run_e2e_11_13",
        trace_id="tr_e2e_11_13",
        correlation_id="co_e2e_11_13",
        idempotency_key="idem_e2e_11_13",
        schema_version="1.0",
    )


def test_e2e_11_12_event_contract_chain(mock_db, ctx):
    from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
    from app.services.skills.skill_12_rag_embedding import RagPipelineService
    from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input
    from ainern2d_shared.schemas.skills.skill_12 import KnowledgeItem, Skill12Input

    s11 = RagKBManagerService(mock_db)
    s12 = RagPipelineService(mock_db)

    kb_id = "kb_e2e_11_12"
    out11_create = s11.execute(
        Skill11Input(
            kb_id=kb_id,
            action="create",
            entries=[
                    KBEntry(
                        entry_id=f"e_{i}",
                        role="director",
                        title=f"Wuxia Rule {i}",
                        content_markdown=(
                            f"wuxia duel continuity rule {i}. "
                            "preserve identity continuity and keep action readability high. "
                        ) * 4,
                    entry_type="prompt_recipe",
                    status="active",
                    flat_tags=["wuxia", "continuity"],
                )
                for i in range(8)
            ],
        ),
        ctx,
    )

    out11_publish = s11.execute(
        Skill11Input(
            kb_id=kb_id,
            action="publish",
            chunking_policy_id="CHUNK_POLICY_V1",
        ),
        ctx,
    )

    assert out11_publish.kb_version_id
    assert "kb.version.release.requested" in out11_publish.events_emitted
    assert "kb.version.released" in out11_publish.events_emitted
    for envelope in out11_publish.event_envelopes:
        _assert_envelope_context(envelope, ctx)

    knowledge_items = [
        KnowledgeItem(
            item_id=e.entry_id,
            role=e.role,
            content=e.content_markdown,
            tags=e.flat_tags,
        )
        for e in out11_create.entries
    ]

    out12 = s12.execute(
        Skill12Input(
            kb_id=kb_id,
            kb_version_id=out11_publish.kb_version_id,
            knowledge_items=knowledge_items,
            preview_queries=["wuxia duel continuity"],
        ),
        ctx,
    )

    assert out12.status == "index_ready"
    assert out12.promote_gate_passed is True
    assert "rag.chunking.started" in out12.events_emitted
    assert "rag.embedding.completed" in out12.events_emitted
    assert "rag.index.ready" in out12.events_emitted
    assert "rag.eval.completed" in out12.events_emitted
    assert "kb.rollout.promoted" in out12.events_emitted
    for envelope in out12.event_envelopes:
        _assert_envelope_context(envelope, ctx)


def test_e2e_13_feedback_to_release_event_closure(mock_db, ctx):
    from app.services.skills.skill_13_feedback_loop import FeedbackLoopService
    from ainern2d_shared.schemas.skills.skill_13 import (
        RunContext,
        ShotResultContext,
        Skill13Input,
        UserFeedback,
        UserPreferences,
    )

    s13 = FeedbackLoopService(mock_db)

    out13 = s13.execute(
        Skill13Input(
            run_context=RunContext(run_id=ctx.run_id, kb_version_id="KB_V_BASELINE"),
            shot_result_context=ShotResultContext(shot_id="S1"),
            user_feedback=UserFeedback(
                rating=2,
                issues=["prompt_quality"],
                free_text="Prompt needs tighter shot intent and cleaner negative constraints.",
            ),
            user_preferences=UserPreferences(allow_shared_kb_write=True),
        ),
        ctx,
    )

    assert out13.action_taken == "proposal_created"
    assert out13.kb_evolution_triggered is True
    assert out13.new_kb_version_id

    expected_events = {
        "feedback.event.created",
        "proposal.created",
        "proposal.reviewed",
        "proposal.approved",
        "kb.version.released",
    }
    assert expected_events.issubset(set(out13.events_emitted))

    for envelope in out13.event_envelopes:
        _assert_envelope_context(envelope, ctx)

    created_payload = next(
        env.payload for env in out13.event_envelopes if env.event_type == "proposal.created"
    )
    released_payload = next(
        env.payload for env in out13.event_envelopes if env.event_type == "kb.version.released"
    )
    assert created_payload["proposal_id"] == out13.proposal.proposal_id
    assert released_payload["source_proposal_id"] == out13.proposal.proposal_id


def test_e2e_13_rejected_proposal_triggers_rollback_event(mock_db, ctx):
    from app.services.skills.skill_13_feedback_loop import FeedbackLoopService
    from ainern2d_shared.schemas.skills.skill_13 import (
        RegressionTestResult,
        RunContext,
        ShotResultContext,
        Skill13Input,
        UserFeedback,
    )

    s13 = FeedbackLoopService(mock_db)
    s13._run_regression_tests = lambda proposal: [  # type: ignore[method-assign]
        RegressionTestResult(
            test_id="rt_reject",
            proposal_id=proposal.proposal_id,
            historical_case_id="case_reject",
            previous_score=0.7,
            new_score=0.1,
            passed=False,
            detail="forced reject path",
        )
    ]

    out13 = s13.execute(
        Skill13Input(
            run_context=RunContext(run_id=ctx.run_id, kb_version_id="KB_V_PREV"),
            shot_result_context=ShotResultContext(shot_id="S2"),
            user_feedback=UserFeedback(
                rating=1,
                issues=["prompt_quality"],
                free_text="force reject for rollback linkage",
            ),
        ),
        ctx,
    )

    assert out13.status == "regression_failed"
    assert "proposal.rejected" in out13.events_emitted
    assert "kb.version.rolled_back" in out13.events_emitted
    rollback_payload = next(
        env.payload
        for env in out13.event_envelopes
        if env.event_type == "kb.version.rolled_back"
    )
    assert rollback_payload["rollback_target_kb_version_id"] == "KB_V_PREV"
    assert rollback_payload["source_proposal_id"] == out13.proposal.proposal_id


def test_e2e_13_to_11_rollback_closure_execution(mock_db, ctx):
    """
    Test the full rollback closure:
    1. SKILL 11 creates and publishes V1.
    2. SKILL 11 creates and publishes V2.
    3. SKILL 13 receives negative feedback and fails regression.
    4. SKILL 13 directly triggers SKILL 11 rollback executor.
    5. SKILL 11 active version is switched to rollback version.
    """
    from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
    from app.services.skills.skill_13_feedback_loop import FeedbackLoopService
    from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input as S11Input
    from ainern2d_shared.schemas.skills.skill_13 import (
        RegressionTestResult,
        RunContext,
        ShotResultContext,
        Skill13Input,
        UserFeedback,
    )

    s11 = RagKBManagerService(mock_db)
    s13 = FeedbackLoopService(mock_db)

    kb_id = "kb_e2e_rollback_closure"

    # 1. Setup SKILL 11 V1
    s11.execute(
        S11Input(
            kb_id=kb_id, action="create",
            entries=[KBEntry(entry_id="kb_item_1", title="Base Rule", content_markdown="V1 Content", status="active", entry_type="style_guide")]
        ), ctx
    )
    v1_out = s11.execute(S11Input(kb_id=kb_id, action="publish"), ctx)
    v1_id = v1_out.kb_version_id

    # 2. Setup SKILL 11 V2
    s11.execute(
        S11Input(
            kb_id=kb_id, action="create",
            entries=[KBEntry(entry_id="kb_item_2", title="New Rule", content_markdown="V2 Content", status="active", entry_type="style_guide")]
        ), ctx
    )
    v2_out = s11.execute(S11Input(kb_id=kb_id, action="publish"), ctx)
    v2_id = v2_out.kb_version_id

    assert v1_id != v2_id

    # 3. SKILL 13 receives feedback on V2, decides to rollback to V1
    s13._run_regression_tests = lambda proposal: [  # type: ignore[method-assign]
        RegressionTestResult(
            test_id="rt_reject_2",
            proposal_id=proposal.proposal_id,
            historical_case_id="case_reject_2",
            previous_score=0.9, new_score=0.2, passed=False, detail="forced failure"
        )
    ]

    out13 = s13.execute(
        Skill13Input(
            run_context=RunContext(run_id=ctx.run_id, kb_version_id=v1_id),
            shot_result_context=ShotResultContext(shot_id="S3"),
            user_feedback=UserFeedback(rating=1, issues=["art_style"], free_text="Revert this!"),
            kb_manager_config={
                "kb_id": kb_id,
                "enable_skill11_rollback": True,
            },
        ),
        ctx,
    )

    assert out13.status == "regression_failed"
    assert "kb.version.rolled_back" in out13.events_emitted
    rollback_payload = next(env.payload for env in out13.event_envelopes if env.event_type == "kb.version.rolled_back")

    assert rollback_payload["rollback_target_kb_version_id"] == v1_id
    assert rollback_payload["executor_triggered"] is True
    assert rollback_payload["executor_status"] == "ready"
    assert rollback_payload["rollback_result_kb_version_id"].startswith("KB_RB_")

    out11_export = s11.execute(S11Input(kb_id=kb_id, action="export"), ctx)
    assert out11_export.kb_version_id == rollback_payload["rollback_result_kb_version_id"]
    assert out11_export.version_history[-1].version_label == f"rollback_to_{v1_out.current_version.version_label}"


def test_e2e_13_rollback_event_consumed_by_skill_event_consumer(mock_db, ctx, monkeypatch):
    from app.api.v1 import orchestrator as orchestrator_api
    from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
    from app.services.skills.skill_13_feedback_loop import FeedbackLoopService
    from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input as S11Input
    from ainern2d_shared.schemas.skills.skill_13 import (
        RegressionTestResult,
        RunContext,
        ShotResultContext,
        Skill13Input,
        UserFeedback,
    )

    s11 = RagKBManagerService(mock_db)
    s13 = FeedbackLoopService(mock_db)
    kb_id = "kb_e2e_rollback_consumer"

    s11.execute(
        S11Input(
            kb_id=kb_id,
            action="create",
            entries=[
                KBEntry(
                    entry_id="k1",
                    title="base",
                    content_markdown="v1",
                    status="active",
                    entry_type="style_guide",
                )
            ],
        ),
        ctx,
    )
    v1_out = s11.execute(S11Input(kb_id=kb_id, action="publish"), ctx)

    s11.execute(
        S11Input(
            kb_id=kb_id,
            action="create",
            entries=[
                KBEntry(
                    entry_id="k2",
                    title="candidate",
                    content_markdown="v2",
                    status="active",
                    entry_type="style_guide",
                )
            ],
        ),
        ctx,
    )
    v2_out = s11.execute(S11Input(kb_id=kb_id, action="publish"), ctx)
    assert v1_out.kb_version_id != v2_out.kb_version_id

    s13._run_regression_tests = lambda proposal: [  # type: ignore[method-assign]
        RegressionTestResult(
            test_id="rt_consumer",
            proposal_id=proposal.proposal_id,
            historical_case_id="case_consumer",
            previous_score=0.8,
            new_score=0.1,
            passed=False,
            detail="force rollback event for consumer path",
        )
    ]

    out13 = s13.execute(
        Skill13Input(
            run_context=RunContext(run_id=ctx.run_id, kb_version_id=v1_out.kb_version_id),
            shot_result_context=ShotResultContext(shot_id="S4"),
            user_feedback=UserFeedback(
                rating=1,
                issues=["prompt_quality"],
                free_text="trigger bus consumer rollback",
            ),
            kb_manager_config={
                "kb_id": kb_id,
                # Do not direct-execute in SKILL 13; let consumer trigger SKILL 11.
                "enable_skill11_rollback": False,
            },
        ),
        ctx,
    )

    rollback_env = next(
        env for env in out13.event_envelopes if env.event_type == "kb.version.rolled_back"
    )
    assert rollback_env.payload["executor_status"] == "skipped"
    assert rollback_env.payload["kb_id"] == kb_id

    seen_event_ids: set[str] = set()

    def _persist_event(_db, event):
        seen_event_ids.add(event.event_id)

    mock_db.get.side_effect = lambda _model, event_id: object() if event_id in seen_event_ids else None
    monkeypatch.setattr(orchestrator_api, "get_db_session", lambda: mock_db)
    monkeypatch.setattr(orchestrator_api, "_persist_event", _persist_event)

    orchestrator_api.handle_skill_event(rollback_env.model_dump(mode="json"))
    out11_export = s11.execute(S11Input(kb_id=kb_id, action="export"), ctx)
    assert out11_export.kb_version_id != v2_out.kb_version_id
    assert out11_export.kb_version_id.startswith("KB_RB_")
    first_rollback_version = out11_export.kb_version_id
    first_version_count = len(out11_export.version_history)

    # Duplicate delivery with same event_id must be idempotent.
    orchestrator_api.handle_skill_event(rollback_env.model_dump(mode="json"))
    out11_export_again = s11.execute(S11Input(kb_id=kb_id, action="export"), ctx)
    assert out11_export_again.kb_version_id == first_rollback_version
    assert len(out11_export_again.version_history) == first_version_count


def test_e2e_13_registry_dispatch_publish_then_consumer_rollback(mock_db, ctx, monkeypatch):
    from app.api.v1 import orchestrator as orchestrator_api
    from app.services import skill_registry as skill_registry_module
    from app.services.skill_registry import SkillRegistry
    from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
    from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input as S11Input
    from ainern2d_shared.schemas.skills.skill_13 import (
        RegressionTestResult,
        RunContext,
        ShotResultContext,
        Skill13Input,
        UserFeedback,
    )

    s11 = RagKBManagerService(mock_db)
    kb_id = "kb_e2e_registry_publish_consume"
    s11.execute(
        S11Input(
            kb_id=kb_id,
            action="create",
            entries=[
                KBEntry(
                    entry_id="k1",
                    title="base",
                    content_markdown="v1",
                    status="active",
                    entry_type="style_guide",
                )
            ],
        ),
        ctx,
    )
    v1_out = s11.execute(S11Input(kb_id=kb_id, action="publish"), ctx)
    s11.execute(
        S11Input(
            kb_id=kb_id,
            action="create",
            entries=[
                KBEntry(
                    entry_id="k2",
                    title="candidate",
                    content_markdown="v2",
                    status="active",
                    entry_type="style_guide",
                )
            ],
        ),
        ctx,
    )
    s11.execute(S11Input(kb_id=kb_id, action="publish"), ctx)

    registry = SkillRegistry(mock_db)
    s13 = registry.get("skill_13")
    s13._run_regression_tests = lambda proposal: [  # type: ignore[method-assign]
        RegressionTestResult(
            test_id="rt_publish_consume",
            proposal_id=proposal.proposal_id,
            historical_case_id="case_publish_consume",
            previous_score=0.8,
            new_score=0.1,
            passed=False,
            detail="force rollback path",
        )
    ]

    published: list[tuple[str, dict]] = []
    seen_event_ids: set[str] = set()

    def _fake_publish(topic: str, payload: dict) -> None:
        published.append((topic, payload))

    def _persist_event(_db, event):
        seen_event_ids.add(event.event_id)

    mock_db.get.side_effect = lambda _model, event_id: object() if event_id in seen_event_ids else None
    monkeypatch.setattr(skill_registry_module, "publish", _fake_publish)
    monkeypatch.setattr(orchestrator_api, "get_db_session", lambda: mock_db)
    monkeypatch.setattr(orchestrator_api, "_persist_event", _persist_event)

    out13 = registry.dispatch(
        "skill_13",
        Skill13Input(
            run_context=RunContext(run_id=ctx.run_id, kb_version_id=v1_out.kb_version_id),
            shot_result_context=ShotResultContext(shot_id="S5"),
            user_feedback=UserFeedback(
                rating=1,
                issues=["prompt_quality"],
                free_text="trigger registry publish + consumer rollback",
            ),
            kb_manager_config={"kb_id": kb_id, "enable_skill11_rollback": False},
        ),
        ctx,
    )

    assert out13.status == "regression_failed"
    rollback_messages = [
        payload
        for topic, payload in published
        if topic == "skill.events" and payload.get("event_type") == "kb.version.rolled_back"
    ]
    assert len(rollback_messages) == 1

    orchestrator_api.handle_skill_event(rollback_messages[0])
    out11_export = s11.execute(S11Input(kb_id=kb_id, action="export"), ctx)
    assert out11_export.kb_version_id.startswith("KB_RB_")


def test_e2e_13_registry_dispatch_real_rabbitmq_publish_consume(mock_db, ctx, monkeypatch):
    """
    Real RabbitMQ transport validation:
    registry.dispatch(skill_13) publishes rollback event to queue,
    then consumer pops from queue and executes SKILL 11 rollback.
    """
    try:
        import pika
    except Exception:
        pytest.skip("pika not installed")

    from ainern2d_shared.config.setting import settings
    from app.api.v1 import orchestrator as orchestrator_api
    from app.services import skill_registry as skill_registry_module
    from app.services.skill_registry import SkillRegistry
    from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
    from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input as S11Input
    from ainern2d_shared.schemas.skills.skill_13 import (
        RegressionTestResult,
        RunContext,
        ShotResultContext,
        Skill13Input,
        UserFeedback,
    )

    # Connectivity probe; skip gracefully if RabbitMQ is not reachable.
    try:
        probe = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
        probe.close()
    except Exception as exc:
        pytest.skip(f"RabbitMQ unavailable: {exc}")

    topic = f"skill.events.e2e.{uuid.uuid4().hex}"
    # Clean queue to avoid stale messages from previous runs.
    conn = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
    ch = conn.channel()
    ch.queue_declare(queue=topic, durable=True)
    ch.queue_purge(queue=topic)
    conn.close()

    monkeypatch.setattr(
        skill_registry_module.SYSTEM_TOPICS, "SKILL_EVENTS", topic, raising=False
    )

    s11 = RagKBManagerService(mock_db)
    kb_id = "kb_e2e_real_rabbitmq_rollback"
    s11.execute(
        S11Input(
            kb_id=kb_id,
            action="create",
            entries=[
                KBEntry(
                    entry_id="k1",
                    title="base",
                    content_markdown="v1",
                    status="active",
                    entry_type="style_guide",
                )
            ],
        ),
        ctx,
    )
    v1_out = s11.execute(S11Input(kb_id=kb_id, action="publish"), ctx)
    s11.execute(
        S11Input(
            kb_id=kb_id,
            action="create",
            entries=[
                KBEntry(
                    entry_id="k2",
                    title="candidate",
                    content_markdown="v2",
                    status="active",
                    entry_type="style_guide",
                )
            ],
        ),
        ctx,
    )
    s11.execute(S11Input(kb_id=kb_id, action="publish"), ctx)

    registry = SkillRegistry(mock_db)
    s13 = registry.get("skill_13")
    s13._run_regression_tests = lambda proposal: [  # type: ignore[method-assign]
        RegressionTestResult(
            test_id="rt_real_rmq",
            proposal_id=proposal.proposal_id,
            historical_case_id="case_real_rmq",
            previous_score=0.8,
            new_score=0.1,
            passed=False,
            detail="force rollback event",
        )
    ]

    seen_event_ids: set[str] = set()

    def _persist_event(_db, event):
        seen_event_ids.add(event.event_id)

    mock_db.get.side_effect = lambda _model, event_id: object() if event_id in seen_event_ids else None
    monkeypatch.setattr(orchestrator_api, "get_db_session", lambda: mock_db)
    monkeypatch.setattr(orchestrator_api, "_persist_event", _persist_event)

    out13 = registry.dispatch(
        "skill_13",
        Skill13Input(
            run_context=RunContext(run_id=ctx.run_id, kb_version_id=v1_out.kb_version_id),
            shot_result_context=ShotResultContext(shot_id="S6"),
            user_feedback=UserFeedback(
                rating=1,
                issues=["prompt_quality"],
                free_text="real rabbitmq rollback",
            ),
            kb_manager_config={"kb_id": kb_id, "enable_skill11_rollback": False},
        ),
        ctx,
    )
    assert out13.status == "regression_failed"

    payload = _rabbitmq_pop_json(
        settings.rabbitmq_url,
        topic,
        expected_event_type="kb.version.rolled_back",
    )
    assert payload is not None
    assert payload["event_type"] == "kb.version.rolled_back"

    orchestrator_api.handle_skill_event(payload)
    out11_export = s11.execute(S11Input(kb_id=kb_id, action="export"), ctx)
    assert out11_export.kb_version_id.startswith("KB_RB_")
    first_rollback_version = out11_export.kb_version_id
    first_version_count = len(out11_export.version_history)

    # Duplicate delivery with the same event_id should be ignored by consumer.
    conn = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
    ch = conn.channel()
    ch.queue_declare(queue=topic, durable=True)
    ch.basic_publish(exchange="", routing_key=topic, body=json.dumps(payload).encode("utf-8"))
    conn.close()

    dup_payload = _rabbitmq_pop_json(
        settings.rabbitmq_url,
        topic,
        expected_event_type="kb.version.rolled_back",
    )
    assert dup_payload is not None
    assert dup_payload["event_id"] == payload["event_id"]
    orchestrator_api.handle_skill_event(dup_payload)

    out11_export_again = s11.execute(S11Input(kb_id=kb_id, action="export"), ctx)
    assert out11_export_again.kb_version_id == first_rollback_version
    assert len(out11_export_again.version_history) == first_version_count


def test_e2e_skill_event_duplicate_flush_conflict_skips_side_effect(mock_db, ctx, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from app.api.v1 import orchestrator as orchestrator_api

    payload = {
        "event_id": "evt_dup_flush_rollback_001",
        "event_type": "kb.version.rolled_back",
        "event_version": "1.0",
        "schema_version": "1.0",
        "producer": "test.skill.events",
        "occurred_at": "2026-02-27T00:00:00Z",
        "tenant_id": ctx.tenant_id,
        "project_id": ctx.project_id,
        "run_id": ctx.run_id,
        "trace_id": ctx.trace_id,
        "correlation_id": ctx.correlation_id,
        "idempotency_key": ctx.idempotency_key,
        "payload": {
            "kb_id": "kb_dup_flush_conflict",
            "rollback_target_kb_version_id": "KB_V_STABLE",
            "executor_triggered": False,
            "reason": "duplicate_flush_conflict",
        },
    }

    monkeypatch.setattr(orchestrator_api, "get_db_session", lambda: mock_db)
    mock_db.get.return_value = None
    mock_db.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate key"))

    orchestrator_api.handle_skill_event(payload)

    # Ensure we exit before rollback side-effect when uniqueness conflict happens.
    assert mock_db.rollback.called
    assert not mock_db.commit.called
