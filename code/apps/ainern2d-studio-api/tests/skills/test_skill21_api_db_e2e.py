"""API+DB E2E for Preview API to SKILL 21 Continuity Lock chain."""
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

from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel, Shot, PromptPlan
from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus, EntityType
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun, Job, WorkflowEvent
from ainern2d_shared.ainer_db_models.knowledge_models import Entity
from ainern2d_shared.ainer_db_models.preview_models import (
    EntityPreviewVariant,
    EntityContinuityProfile,
    EntityInstanceLink,
)
from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.services.base_skill import SkillContext

from app.services.skills.skill_21_entity_registry_continuity import EntityRegistryContinuityService
from ainern2d_shared.schemas.skills.skill_21 import Skill21Input, ExtractedEntity, ExistingRegistryEntity, ShotPlanRef
from app.services.skills.skill_08_asset_matcher import AssetMatcherService
from ainern2d_shared.schemas.skills.skill_08 import Skill08Input
from app.services.skills.skill_10_prompt_planner import PromptPlannerService
from ainern2d_shared.schemas.skills.skill_10 import Skill10Input

from app.api.deps import get_db
from app.api.v1.preview import router as preview_router


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="requires DATABASE_URL for API+DB E2E",
)
def test_preview_api_continuity_lock_e2e():
    suffix = uuid4().hex[:8]
    tenant_id = f"t_skill21_{suffix}"
    project_id = f"p_skill21_{suffix}"
    run_id = f"run_skill21_{suffix}"
    novel_id = f"novel_{suffix}"
    chapter_id = f"chapter_{suffix}"
    shot_id = f"shot_{suffix}"
    scene_id = f"scene_{suffix}"
    entity_id = f"E_{suffix}"
    variant_id = f"epv_{suffix}"

    db = SessionLocal()
    try:
        db.add(Novel(
            id=novel_id, tenant_id=tenant_id, project_id=project_id, 
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}", 
            idempotency_key=f"idem_novel_{suffix}", title="test", summary="test"
        ))
        db.commit()
        db.add(Chapter(
            id=chapter_id, tenant_id=tenant_id, project_id=project_id, 
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}", 
            idempotency_key=f"idem_chapter_{suffix}",
            novel_id=novel_id, chapter_no=1, language_code="zh", raw_text="text"
        ))
        db.commit()
        db.add(Shot(
            id=shot_id, tenant_id=tenant_id, project_id=project_id, 
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}", 
            idempotency_key=f"idem_shot_{suffix}",
            chapter_id=chapter_id, shot_no=1, status=RunStatus.queued, prompt_json={}
        ))
        db.commit()
        db.add(RenderRun(
            id=run_id, tenant_id=tenant_id, project_id=project_id, 
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}", 
            idempotency_key=f"idem_run_{suffix}",
            chapter_id=chapter_id, status=RunStatus.running, stage=RenderStage.plan, progress=50
        ))
        db.commit()
        
        # We need an entity to act as target for preview
        db.add(Entity(
            id=entity_id, tenant_id=tenant_id, project_id=project_id, 
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}", 
            idempotency_key=f"idem_ent_{suffix}", novel_id=novel_id,
            type=EntityType.person, label="Li Mu", traits_json={"traits": ["sword"]}
        ))
        db.commit()
        
        # Also create a preview variant to approve
        db.add(EntityPreviewVariant(
            id=variant_id,
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_var_{suffix}",
            run_id=run_id,
            entity_id=entity_id,
            view_angle="front",
            generation_backend="comfyui",
            status="generated",
            prompt_text="Li Mu, sword, front view",
            artifact_id=None
        ))
        db.commit()

        def _override_get_db():
            local = SessionLocal()
            try:
                yield local
            finally:
                local.close()

        app = FastAPI()
        app.include_router(preview_router)
        app.dependency_overrides[get_db] = _override_get_db

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/preview/variants/{variant_id}/review",
                json={"decision": "approve", "note": "looks good"}
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "approved"
            profile_id = resp.json()["continuity_profile_id"]
            assert profile_id is not None

        # Verify continuity profile correctly updated in DB
        profile = db.execute(
            select(EntityContinuityProfile).where(EntityContinuityProfile.id == profile_id)
        ).scalars().first()
        assert profile is not None
        assert profile.locked_preview_variant_id == variant_id
        assert profile.continuity_status == "locked"

        # Initialize Skill Context
        ctx = SkillContext(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            trace_id=f"tr_{suffix}",
            correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_skill21_{suffix}",
            schema_version="1.0",
        )

        # Execute SKILL_21
        s21 = EntityRegistryContinuityService(db)
        out21 = s21.execute(Skill21Input(
            extracted_entities=[ExtractedEntity(
                source_entity_uid=entity_id, entity_type="character", 
                label="Li Mu", aliases=[], shot_ids=[shot_id], scene_ids=[scene_id]
            )],
            existing_entity_registry=[ExistingRegistryEntity(
                entity_id=entity_id, entity_type="character", 
                canonical_name="Li Mu", aliases=[]
            )],
            shot_plan=[ShotPlanRef(
                shot_id=shot_id, scene_id=scene_id, entity_refs=[entity_id]
            )],
            user_overrides={}
        ), ctx)
        
        assert out21.status == "continuity_ready"
        assert len(out21.continuity_exports.prompt_consistency_anchors) > 0
        anchor = out21.continuity_exports.prompt_consistency_anchors[0]
        anchor_dict = anchor.model_dump() if hasattr(anchor, "model_dump") else anchor
        assert anchor_dict["entity_id"] == entity_id
        assert anchor_dict["continuity_status"] == "locked"

        # Execute SKILL_08 using SKILL_21 exports
        ctx.idempotency_key = f"idem_skill08_{suffix}"
        s08 = AssetMatcherService(db)
        out08 = s08.execute(Skill08Input(
            canonical_entities=[{"entity_uid": entity_id, "entity_type": "character", "surface_form": "Li Mu"}],
            entity_variant_mapping=[{"entity_uid": entity_id, "entity_type": "character", "surface_form": "Li Mu"}],
            selected_culture_pack={"id": "cn_wuxia"},
            culture_constraints={"visual_do": [], "visual_dont": []},
            conflicts=[],
            unresolved_entities=[],
            quality_profile="standard",
            backend_capability=["comfyui"],
            continuity_exports=out21.continuity_exports.model_dump(mode="json"),
        ), ctx)
        assert out08.status == "ready_for_prompt_planner"

        # Execute SKILL_10 using SKILL_08 and SKILL_21 exports
        ctx.idempotency_key = f"idem_skill10_{suffix}"
        s10 = PromptPlannerService(db)
        out10 = s10.execute(Skill10Input(
            entity_canonicalization_result={
                "selected_culture_pack": {"id": "cn_wuxia"},
                "culture_constraints": {"visual_do": [], "visual_dont": []},
                "entity_variant_mapping": [
                    {"entity_uid": entity_id, "entity_type": "character", "surface_form": "Li Mu"}
                ],
                "status": "ready_for_asset_match",
            },
            asset_match_result=out08.model_dump(mode="json"),
            visual_render_plan={
                "shot_render_plans": [{"shot_id": shot_id, "scene_id": scene_id, "motion_level": "LOW"}],
                "status": "ready_for_render_execution",
            },
            shot_plan={"shots": [{"shot_id": shot_id, "scene_id": scene_id, "entities": [entity_id]}]},
            continuity_exports=out21.continuity_exports.model_dump(mode="json"),
            entity_registry_continuity_result=out21.model_dump(mode="json"),
        ), ctx)
        
        assert out10.status == "ready_for_prompt_execution"
        assert entity_id in out10.global_prompt_constraints.continuity_anchor_ids
        
    finally:
        db.rollback()
        db.execute(delete(WorkflowEvent).where(WorkflowEvent.run_id == run_id))
        db.execute(delete(PromptPlan).where(PromptPlan.run_id == run_id))
        db.execute(delete(EntityPreviewVariant).where(EntityPreviewVariant.run_id == run_id))
        db.execute(delete(EntityContinuityProfile).where(EntityContinuityProfile.entity_id == entity_id))
        db.execute(delete(EntityInstanceLink).where(EntityInstanceLink.entity_id == entity_id))
        db.execute(delete(Entity).where(Entity.id == entity_id))
        db.execute(delete(RenderRun).where(RenderRun.id == run_id))
        db.execute(delete(Shot).where(Shot.id == shot_id))
        db.execute(delete(Chapter).where(Chapter.id == chapter_id))
        db.execute(delete(Novel).where(Novel.id == novel_id))
        db.commit()
        db.close()
