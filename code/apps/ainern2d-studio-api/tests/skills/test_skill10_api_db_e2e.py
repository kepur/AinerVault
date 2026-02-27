"""API+DB E2E for SKILL 10 prompt plan replay consistency."""
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

from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel, PromptPlan, Shot
from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun
from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.services.base_skill import SkillContext
from app.services.skills.skill_10_prompt_planner import PromptPlannerService
from ainern2d_shared.schemas.skills.skill_10 import Skill10Input


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="requires DATABASE_URL for API+DB E2E",
)
def test_skill10_prompt_plan_api_db_replay_consistency(monkeypatch):
    suffix = uuid4().hex[:8]
    tenant_id = f"t_skill10_{suffix}"
    project_id = f"p_skill10_{suffix}"
    run_id = f"run_skill10_{suffix}"
    novel_id = f"novel_{suffix}"
    chapter_id = f"chapter_{suffix}"
    shot_id = f"shot_{suffix}"
    persona_ref = "director_A@2.0"
    entity_id = "CHAR_0001"

    db = SessionLocal()
    try:
        db.add(Novel(
            id=novel_id,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_novel_{suffix}",
            title=f"Skill10 Novel {suffix}",
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
            progress=50,
        ))
        db.commit()

        ctx = SkillContext(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_skill10_{suffix}",
            schema_version="1.0",
        )

        svc = PromptPlannerService(db)
        inp = Skill10Input(
            entity_canonicalization_result={
                "selected_culture_pack": {"id": "cn_wuxia"},
                "culture_constraints": {"visual_do": [], "visual_dont": []},
                "entity_variant_mapping": [
                    {
                        "entity_uid": entity_id,
                        "entity_type": "character",
                        "surface_form": "Li Mu",
                        "visual_traits": ["dark robe"],
                    }
                ],
                "status": "ready_for_asset_match",
            },
            asset_match_result={
                "entity_asset_matches": [{"entity_uid": entity_id}],
                "status": "ready_for_prompt_planner",
            },
            visual_render_plan={
                "status": "ready_for_render_execution",
                "shot_render_plans": [
                    {"shot_id": shot_id, "scene_id": "SC1", "motion_level": "LOW"}
                ],
            },
            shot_plan={
                "shots": [
                    {
                        "shot_id": shot_id,
                        "scene_id": "SC1",
                        "shot_type": "medium",
                        "goal": "inn standoff",
                        "entities": [entity_id],
                    }
                ]
            },
            continuity_exports={
                "prompt_consistency_anchors": [
                    {
                        "entity_id": entity_id,
                        "continuity_status": "active",
                        "consistency_tokens": ["scar on left brow"],
                    }
                ],
                "asset_matcher_anchors": [
                    {"entity_id": entity_id, "anchor_prompt": "same hero face and costume"}
                ],
            },
            persona_dataset_index_result={
                "runtime_manifests": [
                    {
                        "persona_ref": persona_ref,
                        "style_pack_ref": "director_style@2.0",
                        "policy_override_ref": "policy_v2",
                        "critic_profile_ref": "critic_v2",
                    }
                ]
            },
            active_persona_ref=persona_ref,
        )

        out1 = svc.execute(inp, ctx)
        assert out1.global_prompt_constraints.persona_runtime_ref == persona_ref
        assert entity_id in out1.global_prompt_constraints.continuity_anchor_ids

        persisted1 = db.execute(
            select(PromptPlan).where(PromptPlan.run_id == run_id)
        ).scalars().all()
        assert len(persisted1) == 1
        persisted_prompt_text = persisted1[0].prompt_text
        persisted_plan_id = persisted1[0].id

        ctx_replay = SkillContext(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_skill10_replay_{suffix}",
            schema_version="1.0",
        )
        out2 = svc.execute(inp, ctx_replay)
        assert out2.status in ("ready_for_prompt_execution", "review_required")
        persisted2 = db.execute(
            select(PromptPlan).where(PromptPlan.run_id == run_id)
        ).scalars().all()
        assert len(persisted2) == 1
        assert persisted2[0].id == persisted_plan_id
        assert persisted2[0].prompt_text == persisted_prompt_text

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
                resp1 = client.get(f"/api/v1/runs/{run_id}/prompt-plans")
                assert resp1.status_code == 200
                assert resp1.headers["x-prompt-plan-total"] == "1"
                payload1 = resp1.json()
                assert len(payload1) == 1
                assert payload1[0]["run_id"] == run_id
                assert payload1[0]["shot_id"] == shot_id
                assert payload1[0]["prompt_text"] == persisted_prompt_text
                assert entity_id in payload1[0]["model_hint_json"]["consistency_anchors"]

                resp2 = client.get(f"/api/v1/runs/{run_id}/prompt-plans")
                assert resp2.status_code == 200
                assert resp2.json() == payload1
        finally:
            app.dependency_overrides.clear()
    finally:
        db.rollback()
        from ainern2d_shared.ainer_db_models.pipeline_models import WorkflowEvent
        db.execute(delete(WorkflowEvent).where(WorkflowEvent.run_id == run_id))
        db.execute(delete(PromptPlan).where(PromptPlan.run_id == run_id))
        db.execute(delete(RenderRun).where(RenderRun.id == run_id))
        db.execute(delete(Shot).where(Shot.id == shot_id))
        db.execute(delete(Chapter).where(Chapter.id == chapter_id))
        db.execute(delete(Novel).where(Novel.id == novel_id))
        db.commit()
        db.close()


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="requires DATABASE_URL for API+DB E2E",
)
def test_skill10_multishot_replay_consistency_with_microshot_input():
    suffix = uuid4().hex[:8]
    tenant_id = f"t_skill10_m_{suffix}"
    project_id = f"p_skill10_m_{suffix}"
    run_id = f"run_skill10_m_{suffix}"
    novel_id = f"novel_m_{suffix}"
    chapter_id = f"chapter_m_{suffix}"
    shot_id_1 = f"shot_m1_{suffix}"
    shot_id_2 = f"shot_m2_{suffix}"

    db = SessionLocal()
    try:
        db.add(Novel(
            id=novel_id,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_novel_m_{suffix}",
            title=f"Skill10 MultiShot Novel {suffix}",
            summary="test",
        ))
        db.commit()
        db.add(Chapter(
            id=chapter_id,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_chapter_m_{suffix}",
            novel_id=novel_id,
            chapter_no=1,
            language_code="zh",
            raw_text="chapter raw text",
        ))
        db.commit()
        db.add(Shot(
            id=shot_id_1,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_shot_m1_{suffix}",
            chapter_id=chapter_id,
            shot_no=1,
            status=RunStatus.queued,
            prompt_json={},
        ))
        db.add(Shot(
            id=shot_id_2,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_shot_m2_{suffix}",
            chapter_id=chapter_id,
            shot_no=2,
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
            idempotency_key=f"idem_run_m_{suffix}",
            chapter_id=chapter_id,
            status=RunStatus.running,
            stage=RenderStage.plan,
            progress=60,
        ))
        db.commit()

        svc = PromptPlannerService(db)
        inp = Skill10Input(
            entity_canonicalization_result={
                "selected_culture_pack": {"id": "cn_wuxia"},
                "culture_constraints": {"visual_do": [], "visual_dont": []},
                "entity_variant_mapping": [
                    {
                        "entity_uid": "CHAR_0001",
                        "entity_type": "character",
                        "surface_form": "Li Mu",
                        "visual_traits": ["dark robe"],
                    }
                ],
                "status": "ready_for_asset_match",
            },
            asset_match_result={
                "entity_asset_matches": [{"entity_uid": "CHAR_0001"}],
                "status": "ready_for_prompt_planner",
            },
            visual_render_plan={
                "status": "ready_for_render_execution",
                "shot_render_plans": [
                    {"shot_id": shot_id_1, "scene_id": "SC1", "motion_level": "LOW"},
                    {"shot_id": shot_id_2, "scene_id": "SC1", "motion_level": "HIGH"},
                ],
                "microshot_render_plans": [
                    {
                        "microshot_id": f"ms_{suffix}",
                        "parent_shot_id": shot_id_2,
                        "motion_description": "fast sword clash",
                    }
                ],
            },
            shot_plan={
                "shots": [
                    {"shot_id": shot_id_1, "scene_id": "SC1", "goal": "setup", "entities": ["CHAR_0001"]},
                    {"shot_id": shot_id_2, "scene_id": "SC1", "goal": "duel", "entities": ["CHAR_0001"]},
                ]
            },
        )
        out1 = svc.execute(
            inp,
            SkillContext(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"co_{suffix}",
                idempotency_key=f"idem_skill10_m_{suffix}",
                schema_version="1.0",
            ),
        )
        assert out1.prompt_plan_summary.total_shots == 2
        assert out1.prompt_plan_summary.total_microshots == 1

        persisted1 = db.execute(
            select(PromptPlan).where(PromptPlan.run_id == run_id).order_by(PromptPlan.shot_id.asc())
        ).scalars().all()
        assert len(persisted1) == 2
        first_snapshot = [(r.id, r.shot_id, r.prompt_text) for r in persisted1]

        out2 = svc.execute(
            inp,
            SkillContext(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                trace_id=f"tr_{suffix}",
                correlation_id=f"co_{suffix}",
                idempotency_key=f"idem_skill10_m_replay_{suffix}",
                schema_version="1.0",
            ),
        )
        assert out2.prompt_plan_summary.total_shots == 2
        persisted2 = db.execute(
            select(PromptPlan).where(PromptPlan.run_id == run_id).order_by(PromptPlan.shot_id.asc())
        ).scalars().all()
        assert len(persisted2) == 2
        second_snapshot = [(r.id, r.shot_id, r.prompt_text) for r in persisted2]
        assert second_snapshot == first_snapshot

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
                full = client.get(f"/api/v1/runs/{run_id}/prompt-plans")
                assert full.status_code == 200
                assert full.headers["x-prompt-plan-total"] == "2"
                full_payload = full.json()
                assert len(full_payload) == 2

                page = client.get(f"/api/v1/runs/{run_id}/prompt-plans?limit=1&offset=1")
                assert page.status_code == 200
                assert page.headers["x-prompt-plan-total"] == "2"
                page_payload = page.json()
                assert len(page_payload) == 1
                assert page_payload[0]["shot_id"] == full_payload[1]["shot_id"]
        finally:
            app.dependency_overrides.clear()
    finally:
        db.rollback()
        from ainern2d_shared.ainer_db_models.pipeline_models import WorkflowEvent
        db.execute(delete(WorkflowEvent).where(WorkflowEvent.run_id == run_id))
        db.execute(delete(PromptPlan).where(PromptPlan.run_id == run_id))
        db.execute(delete(RenderRun).where(RenderRun.id == run_id))
        db.execute(delete(Shot).where(Shot.id.in_([shot_id_1, shot_id_2])))
        db.execute(delete(Chapter).where(Chapter.id == chapter_id))
        db.execute(delete(Novel).where(Novel.id == novel_id))
        db.commit()
        db.close()
