"""API+DB E2E for SKILL 22 Persona Lineage, Downstream Consumption, and Rollback."""
from __future__ import annotations

import os
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel, Shot, PromptPlan
from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun, WorkflowEvent
from ainern2d_shared.ainer_db_models.rag_models import RagCollection
from ainern2d_shared.ainer_db_models.preview_models import (
    PersonaRuntimeManifest,
    PersonaDatasetBinding,
    PersonaLineageEdge,
)
from ainern2d_shared.ainer_db_models.governance_models import PersonaPack, PersonaPackVersion
from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.services.base_skill import SkillContext

from app.services.skills.skill_22_persona_dataset_index import PersonaDatasetIndexService
from ainern2d_shared.schemas.skills.skill_22 import Skill22Input, PersonaItem, DatasetItem

from app.services.skills.skill_10_prompt_planner import PromptPlannerService
from ainern2d_shared.schemas.skills.skill_10 import Skill10Input

from app.services.skills.skill_15_creative_control import CreativeControlService
from ainern2d_shared.schemas.skills.skill_15 import Skill15Input

from app.services.skills.skill_17_experiment import ExperimentService
from ainern2d_shared.schemas.skills.skill_17 import Skill17Input


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="requires DATABASE_URL for API+DB E2E",
)
def test_persona_lineage_rollback_e2e():
    suffix = uuid4().hex[:8]
    tenant_id = f"t_skill22_{suffix}"
    project_id = f"p_skill22_{suffix}"
    run_id = f"run_skill22_{suffix}"
    novel_id = f"novel_{suffix}"
    chapter_id = f"chapter_{suffix}"
    shot_id = f"shot_{suffix}"
    scene_id = f"scene_{suffix}"

    dataset1_id = f"ds1_{suffix}"
    dataset2_id = f"ds2_{suffix}"
    pack_v1_id = f"pack_v1_{suffix}"
    pack_v2_id = f"pack_v2_{suffix}"
    persona_pack_id = f"persona_pack_{suffix}"

    db = SessionLocal()
    try:
        # 1. Setup minimal DB context
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
        
        # 2. Setup Persona Packs and Datasets
        # Instead of dynamically creating these, we'll pretend upstream created them or Skill22 will resolve them if missing.
        db.add(RagCollection(
            id=dataset1_id, tenant_id=tenant_id, project_id=project_id, 
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_ds1_{suffix}", 
            name=f"Base Dataset {suffix}"
        ))
        db.add(RagCollection(
            id=dataset2_id, tenant_id=tenant_id, project_id=project_id, 
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_ds2_{suffix}", 
            name=f"Upgraded Dataset {suffix}"
        ))
        # Setup a PersonaPack explicitly before tying versions to it
        db.add(PersonaPack(
            id=persona_pack_id, tenant_id=tenant_id, project_id=project_id,
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_pack_{suffix}", name=f"director_A_{suffix}"
        ))
        db.add(PersonaPackVersion(
            id=pack_v1_id, tenant_id=tenant_id, project_id=project_id,
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_pack1_{suffix}", persona_pack_id=persona_pack_id, version_name="1.0", style_json={}
        ))
        db.add(PersonaPackVersion(
            id=pack_v2_id, tenant_id=tenant_id, project_id=project_id,
            trace_id=f"tr_{suffix}", correlation_id=f"co_{suffix}",
            idempotency_key=f"idem_pack2_{suffix}", persona_pack_id=persona_pack_id, version_name="2.0", style_json={}
        ))
        db.commit()

        # Contexts
        ctx_v1 = SkillContext(
            tenant_id=tenant_id, project_id=project_id, run_id=run_id,
            trace_id=f"tr_v1_{suffix}", correlation_id=f"co_v1_{suffix}",
            idempotency_key=f"idem_skill22_v1_{suffix}", schema_version="1.0",
        )
        ctx_v2 = SkillContext(
            tenant_id=tenant_id, project_id=project_id, run_id=run_id,
            trace_id=f"tr_v2_{suffix}", correlation_id=f"co_v2_{suffix}",
            idempotency_key=f"idem_skill22_v2_{suffix}", schema_version="1.0",
        )

        s22 = PersonaDatasetIndexService(db)

        # -------------------------------------------------------------------------------------------------
        # STEP 1: Execute SKILL_22 for Version 1.0
        # -------------------------------------------------------------------------------------------------
        out22_v1 = s22.execute(Skill22Input(
            personas=[PersonaItem(
                persona_id="director_A", persona_version="1.0",
                dataset_ids=[dataset1_id], style_pack_ref="style_v1", policy_override_ref="policy_v1",
                metadata={"persona_pack_version_id": pack_v1_id}
            )],
            datasets=[DatasetItem(dataset_id=dataset1_id, name="V1 Data")]
        ), ctx_v1)

        assert out22_v1.status in ("persona_index_ready", "review_required")
        assert len(out22_v1.runtime_manifests) == 1
        assert out22_v1.runtime_manifests[0].style_pack_ref == "style_v1"

        # Check downstream V1 consumption
        s10 = PromptPlannerService(db)
        out10_v1 = s10.execute(Skill10Input(
            active_persona_ref="director_A@1.0",
            persona_dataset_index_result=out22_v1.model_dump(mode="json"),
            visual_render_plan={"status": "ready_for_render_execution", "shot_render_plans": [{"shot_id": shot_id, "scene_id": scene_id, "motion_level": "LOW"}]},
            shot_plan={"shots": [{"shot_id": shot_id, "scene_id": scene_id, "entities": []}]},
            entity_canonicalization_result={"status": "ready"},
            asset_match_result={"status": "ready"}
        ), ctx_v1)
        assert out10_v1.status == "ready_for_prompt_execution"
        assert out10_v1.global_prompt_constraints.persona_runtime_ref == "director_A@1.0"
        # Since style_v1 is active, we expect prompt planner to potentially extract persona rules, though currently it just verifies it parses.

        s15 = CreativeControlService(db)
        out15_v1 = s15.execute(Skill15Input(
            active_persona_ref="director_A@1.0",
            persona_dataset_index_result=out22_v1.model_dump(mode="json")
        ), ctx_v1)
        assert getattr(out15_v1, "status", None) in ["policy_ready", "review_required"]
        assert any(a.action == "injected_persona_profile_from_skill22" and a.decision == "director_A@1.0" for a in out15_v1.audit_trail)
        policy_refs_v1 = [
            c.value
            for c in (out15_v1.hard_constraints + out15_v1.soft_constraints + out15_v1.guidelines)
            if c.parameter == "persona_policy_override_ref"
        ]
        assert "policy_v1" in policy_refs_v1

        # Note: Skill 17 consumption test skipped as it requires complex benchmark_cases setup to pass validations

        # -------------------------------------------------------------------------------------------------
        # STEP 2: Execute SKILL_22 for Version 2.0 (Upgrade)
        # -------------------------------------------------------------------------------------------------
        out22_v2 = s22.execute(Skill22Input(
            personas=[PersonaItem(
                persona_id="director_A", persona_version="2.0",
                dataset_ids=[dataset1_id, dataset2_id], style_pack_ref="style_v2", policy_override_ref="policy_v2",
                metadata={"persona_pack_version_id": pack_v2_id}
            )],
            datasets=[DatasetItem(dataset_id=dataset1_id, name="V1 Data"), DatasetItem(dataset_id=dataset2_id, name="V2 Data")],
            lineage_operations=[{
                "source_persona_ref": "director_A@1.0",
                "target_persona_ref": "director_A@2.0",
                "edge_type": "upgrade",
                "reason": "Test upgrade"
            }]
        ), ctx_v2)

        assert out22_v2.status in ("persona_index_ready", "review_required")
        assert any(e.edge_type == "upgrade" for e in out22_v2.lineage_graph.edges)

        # Check downstream V2 consumption
        ctx_v2_10 = SkillContext(
            tenant_id=tenant_id, project_id=project_id, run_id=run_id,
            trace_id=f"tr_v2_10_{suffix}", correlation_id=f"co_v2_10_{suffix}",
            idempotency_key=f"idem_skill10_v2_{suffix}", schema_version="1.0",
        )
        out10_v2 = s10.execute(Skill10Input(
            active_persona_ref="director_A@2.0",
            persona_dataset_index_result=out22_v2.model_dump(mode="json"),
            visual_render_plan={"status": "ready_for_render_execution", "shot_render_plans": [{"shot_id": shot_id, "scene_id": scene_id, "motion_level": "LOW"}]},
            shot_plan={"shots": [{"shot_id": shot_id, "scene_id": scene_id, "entities": []}]},
            entity_canonicalization_result={"status": "ready"},
            asset_match_result={"status": "ready"}
        ), ctx_v2_10)
        assert out10_v2.global_prompt_constraints.persona_runtime_ref == "director_A@2.0"

        out15_v2 = s15.execute(Skill15Input(
            active_persona_ref="director_A@2.0",
            persona_dataset_index_result=out22_v2.model_dump(mode="json")
        ), ctx_v2)
        policy_refs_v2 = [
            c.value
            for c in (out15_v2.hard_constraints + out15_v2.soft_constraints + out15_v2.guidelines)
            if c.parameter == "persona_policy_override_ref"
        ]
        assert "policy_v2" in policy_refs_v2

        # -------------------------------------------------------------------------------------------------
        # STEP 3: Verification of Lineage Rollback (consuming V1 despite V2 existing)
        # -------------------------------------------------------------------------------------------------
        ctx_rollback = SkillContext(
            tenant_id=tenant_id, project_id=project_id, run_id=run_id,
            trace_id=f"tr_rollback_{suffix}", correlation_id=f"co_rollback_{suffix}",
            idempotency_key=f"idem_skill10_rollback_{suffix}", schema_version="1.0",
        )
        out10_rb = s10.execute(Skill10Input(
            active_persona_ref="director_A@1.0",
            # Pass BOTH manifests to simulate full run history, system should pick the active_persona_ref targeted
            persona_dataset_index_result={
                "runtime_manifests": out22_v1.model_dump(mode="json")["runtime_manifests"] + out22_v2.model_dump(mode="json")["runtime_manifests"]
            },
            visual_render_plan={"status": "ready_for_render_execution", "shot_render_plans": [{"shot_id": shot_id, "scene_id": scene_id, "motion_level": "LOW"}]},
            shot_plan={"shots": [{"shot_id": shot_id, "scene_id": scene_id, "entities": []}]},
            entity_canonicalization_result={"status": "ready"},
            asset_match_result={"status": "ready"}
        ), ctx_rollback)
        assert out10_rb.global_prompt_constraints.persona_runtime_ref == "director_A@1.0"

        out15_rb = s15.execute(Skill15Input(
            active_persona_ref="director_A@1.0",
            persona_dataset_index_result={
                "runtime_manifests": out22_v1.model_dump(mode="json")["runtime_manifests"] + out22_v2.model_dump(mode="json")["runtime_manifests"]
            },
        ), ctx_rollback)
        # Verify it successfully rolled back to V1 persona profile injection
        assert any(a.action == "injected_persona_profile_from_skill22" and a.decision == "director_A@1.0" for a in out15_rb.audit_trail)
        policy_refs_rb = [
            c.value
            for c in (out15_rb.hard_constraints + out15_rb.soft_constraints + out15_rb.guidelines)
            if c.parameter == "persona_policy_override_ref"
        ]
        assert "policy_v1" in policy_refs_rb

    finally:
        db.rollback()
        db.execute(delete(WorkflowEvent).where(WorkflowEvent.run_id == run_id))
        db.execute(delete(PromptPlan).where(PromptPlan.run_id == run_id))
        db.execute(delete(PersonaRuntimeManifest).where(PersonaRuntimeManifest.run_id == run_id))
        db.execute(delete(PersonaDatasetBinding).where(PersonaDatasetBinding.tenant_id == tenant_id))
        db.execute(delete(PersonaLineageEdge).where(PersonaLineageEdge.tenant_id == tenant_id))
        db.execute(delete(PersonaPackVersion).where(PersonaPackVersion.tenant_id == tenant_id))
        db.execute(delete(RagCollection).where(RagCollection.tenant_id == tenant_id))
        db.execute(delete(RenderRun).where(RenderRun.id == run_id))
        db.execute(delete(Shot).where(Shot.id == shot_id))
        db.execute(delete(Chapter).where(Chapter.id == chapter_id))
        db.execute(delete(Novel).where(Novel.id == novel_id))
        db.commit()
        db.close()
