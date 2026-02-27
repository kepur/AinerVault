"""API+DB E2E for SKILL 15 policy persistence and audit traceability."""
from __future__ import annotations

import os
import sys
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel, Shot
from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun, WorkflowEvent
from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.services.base_skill import SkillContext
from ainern2d_shared.schemas.skills.skill_15 import Skill15Input

from app.services.skills.skill_15_creative_control import CreativeControlService
from app.services.skills.skill_22_persona_dataset_index import PersonaDatasetIndexService
from ainern2d_shared.schemas.skills.skill_22 import (
    DatasetItem,
    IndexItem,
    PersonaItem,
    Skill22Input,
)


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="requires DATABASE_URL for API+DB E2E",
)
def test_skill15_policy_stack_api_db_replay_traceability():
    suffix = uuid4().hex[:8]
    tenant_id = f"t_skill15_{suffix}"
    project_id = f"p_skill15_{suffix}"
    run_id = f"run_skill15_{suffix}"
    novel_id = f"novel_{suffix}"
    chapter_id = f"chapter_{suffix}"
    shot_id = f"shot_{suffix}"
    persona_ref = "director_A@2.0"

    db = SessionLocal()
    try:
        db.add(Novel(
            id=novel_id,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_novel_{suffix}",
            title=f"Skill15 Novel {suffix}",
            summary="test",
        ))
        db.commit()

        db.add(Chapter(
            id=chapter_id,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_chapter_{suffix}",
            novel_id=novel_id,
            chapter_no=1,
            language_code="zh",
            raw_text="chapter raw text",
        ))
        db.commit()

        db.add(Shot(
            id=shot_id,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_shot_{suffix}",
            chapter_id=chapter_id,
            shot_no=1,
            status=RunStatus.queued,
            prompt_json={},
        ))
        db.commit()

        db.add(RenderRun(
            id=run_id,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_run_{suffix}",
            chapter_id=chapter_id,
            status=RunStatus.running,
            stage=RenderStage.plan,
            progress=40,
        ))
        db.commit()

        ctx = SkillContext(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_skill15_{suffix}",
            schema_version="1.0",
        )
        s22 = PersonaDatasetIndexService(db)
        out22 = s22.execute(
            Skill22Input(
                datasets=[DatasetItem(dataset_id="DS_001", name="wuxia_rules")],
                indexes=[IndexItem(index_id="IDX_001", kb_version_id="KB_V1", dataset_ids=["DS_001"])],
                personas=[
                    PersonaItem(
                        persona_id="director_A",
                        persona_version="2.0",
                        dataset_ids=["DS_001"],
                        index_ids=["IDX_001"],
                        style_pack_ref="director_style@2.0",
                        policy_override_ref="policy_A@2.0",
                        critic_profile_ref="critic_A@2.0",
                        metadata={},
                    )
                ],
                preview_query="night duel in rain",
                preview_top_k=3,
            ),
            ctx,
        )
        assert out22.runtime_manifests

        svc = CreativeControlService(db)
        out = svc.execute(
            Skill15Input(
                active_persona_ref=persona_ref,
                persona_dataset_index_result=out22.model_dump(mode="json"),
            ),
            ctx,
        )

        assert out.status in ("policy_ready", "review_required")
        assert out.policy_stack_id
        assert out.policy_stack_name == f"run_policy_{run_id}"
        assert out.policy_event_id

        stack_row = db.get(CreativePolicyStack, out.policy_stack_id)
        assert stack_row is not None
        assert stack_row.name == out.policy_stack_name
        assert stack_row.stack_json["run_id"] == run_id
        assert stack_row.stack_json["active_persona_ref"] == persona_ref
        assert stack_row.stack_json["summary"]["hard_constraints"] >= 1

        built_event = db.execute(
            select(WorkflowEvent).where(
                WorkflowEvent.run_id == run_id,
                WorkflowEvent.event_type == "policy.stack.built",
                WorkflowEvent.deleted_at.is_(None),
            )
        ).scalars().first()
        assert built_event is not None
        assert built_event.payload_json["policy_stack_id"] == out.policy_stack_id
        assert built_event.payload_json["active_persona_ref"] == persona_ref

        from app.api.deps import get_db
        from app.api.v1.tasks import router as task_router

        def _override_get_db():
            local = SessionLocal()
            try:
                yield local
            finally:
                local.close()

        app = FastAPI()
        app.include_router(task_router)
        app.dependency_overrides[get_db] = _override_get_db
        try:
            with TestClient(app) as client:
                resp = client.get(f"/api/v1/runs/{run_id}/policy-stacks")
                assert resp.status_code == 200
                assert resp.headers["x-policy-stack-total"] == "1"
                assert int(resp.headers["x-policy-stack-query-ms"]) >= 0
                payload = resp.json()
                assert len(payload) == 1
                assert payload[0]["policy_stack_id"] == out.policy_stack_id
                assert payload[0]["run_id"] == run_id
                assert payload[0]["active_persona_ref"] == persona_ref
                assert payload[0]["audit_entries"] >= 1
        finally:
            app.dependency_overrides.clear()
    finally:
        db.rollback()
        db.execute(delete(WorkflowEvent).where(WorkflowEvent.run_id == run_id))
        db.execute(delete(CreativePolicyStack).where(
            CreativePolicyStack.tenant_id == tenant_id,
            CreativePolicyStack.project_id == project_id,
        ))
        db.execute(delete(RenderRun).where(RenderRun.id == run_id))
        db.execute(delete(Shot).where(Shot.id == shot_id))
        db.execute(delete(Chapter).where(Chapter.id == chapter_id))
        db.execute(delete(Novel).where(Novel.id == novel_id))
        db.commit()
        db.close()
