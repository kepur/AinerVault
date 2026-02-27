"""Service-level E2E for SKILL 11/12/13 event contract and feedback loop closure."""
from __future__ import annotations

import os
import sys
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
    3. SKILL 13 receives negative feedback on V2, fails regression, and emits rollback event.
    4. We catch the rollback event and feed it into SKILL 11.
    5. SKILL 11 executes rollback to V1.
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
            run_context=RunContext(run_id=ctx.run_id, kb_version_id=v1_id), # We simulate that V1 was the stable prior version
            shot_result_context=ShotResultContext(shot_id="S3"),
            user_feedback=UserFeedback(rating=1, issues=["art_style"], free_text="Revert this!"),
        ),
        ctx,
    )

    assert out13.status == "regression_failed"
    assert "kb.version.rolled_back" in out13.events_emitted
    rollback_payload = next(env.payload for env in out13.event_envelopes if env.event_type == "kb.version.rolled_back")
    
    target_vid_from_event = rollback_payload["rollback_target_kb_version_id"]
    reason_from_event = rollback_payload["reason"]
    
    assert target_vid_from_event == v1_id

    # 4. Dispatch the rollback event payload to SKILL 11
    # In a real message broker, the consumer would map the event to this input DTO.
    out11_rollback = s11.execute(
        S11Input(
            kb_id=kb_id,
            action="rollback",
            rollback_target_version_id=target_vid_from_event,
            rollback_reason=reason_from_event,
        ),
        ctx,
    )

    # 5. Verify SKILL 11 performed the rollback successfully
    assert out11_rollback.status == "READY"
    assert out11_rollback.current_version.version_label == f"rollback_to_{v1_out.current_version.version_label}"
    assert out11_rollback.current_version.release_notes == reason_from_event
    assert "kb.version.rolled_back" in out11_rollback.events_emitted

