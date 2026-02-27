#!/usr/bin/env python3
"""Real-DB persistence validation for SKILL_21 and SKILL_22.

Prerequisites:
  - PostgreSQL is running
  - Alembic upgraded to head
  - DATABASE_URL is set (e.g. postgresql+psycopg2://ainer:ainer_dev_2024@localhost:5432/ainer_dev)

Usage:
  DATABASE_URL=... python3 code/scripts/validate_skill_21_22_persistence_realdb.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "apps" / "ainern2d-studio-api"))

from sqlalchemy import select, func

from ainern2d_shared.ainer_db_models.content_models import Chapter, Novel, Scene, Shot
from ainern2d_shared.ainer_db_models.enum_models import EntityType, RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.governance_models import PersonaPack, PersonaPackVersion
from ainern2d_shared.ainer_db_models.knowledge_models import Entity
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun
from ainern2d_shared.ainer_db_models.preview_models import (
    CharacterVoiceBinding,
    EntityContinuityProfile,
    EntityInstanceLink,
    EntityPreviewVariant,
    PersonaDatasetBinding,
    PersonaIndexBinding,
    PersonaLineageEdge,
    PersonaRuntimeManifest,
)
from ainern2d_shared.ainer_db_models.rag_models import KbVersion, RagCollection
from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.schemas.skills.skill_21 import (
    ExistingRegistryEntity,
    ExtractedEntity,
    ShotPlanRef,
    Skill21Input,
)
from ainern2d_shared.schemas.skills.skill_22 import (
    DatasetItem,
    IndexItem,
    PersonaItem,
    PersonaLineageOp,
    Skill22Input,
)
from ainern2d_shared.services.base_skill import SkillContext

from app.services.skills.skill_21_entity_registry_continuity import EntityRegistryContinuityService
from app.services.skills.skill_22_persona_dataset_index import PersonaDatasetIndexService


TENANT_ID = "t_e2e"
PROJECT_ID = "p_e2e"
RUN_SCOPE = os.getenv("E2E_RUN_SCOPE", uuid.uuid4().hex[:10].upper())
RUN_ID = f"RUN_E2E_21_22_{RUN_SCOPE}"
NOVEL_ID = "NOVEL_E2E_21_22"
CHAPTER_ID = "CH_E2E_21_22"
SCENE_ID = "SC_E2E_21_22"
SHOT_ID = "SH_E2E_21_22"
ENTITY_ID = "CHAR_E2E_21_22"

PACK_A = "PACK_E2E_A"
PACK_B = "PACK_E2E_B"
PPV_A = "PPV_E2E_A_1"
PPV_B = "PPV_E2E_B_1"
COLL_1 = "DS_E2E_001"
COLL_2 = "DS_E2E_002"
KB_1 = "KB_E2E_001"
KB_2 = "KB_E2E_002"


def _upsert_by_id(db, model, obj_id: str, **fields):
    row = db.get(model, obj_id)
    if row is None:
        row = model(id=obj_id, **fields)
        db.add(row)
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    db.flush()
    return row


def seed_baseline(db):
    _upsert_by_id(
        db,
        Novel,
        NOVEL_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        title="E2E Novel",
        summary="seed",
        default_language_code="zh",
    )
    _upsert_by_id(
        db,
        Chapter,
        CHAPTER_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        novel_id=NOVEL_ID,
        chapter_no=1,
        language_code="zh",
        title="E2E Chapter",
        raw_text="seed chapter",
    )
    _upsert_by_id(
        db,
        Scene,
        SCENE_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        novel_id=NOVEL_ID,
        label="E2E Scene",
        description="seed scene",
    )
    _upsert_by_id(
        db,
        Shot,
        SHOT_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        scene_id=SCENE_ID,
        shot_no=1,
        duration_ms=2500,
        status=RunStatus.queued,
    )
    _upsert_by_id(
        db,
        RenderRun,
        RUN_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        status=RunStatus.running,
        stage=RenderStage.entity,
        progress=10,
    )
    _upsert_by_id(
        db,
        Entity,
        ENTITY_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        novel_id=NOVEL_ID,
        type=EntityType.person,
        label="Li Mu",
        canonical_label="Li Mu",
        anchor_prompt="hero swordsman",
        traits_json={"costume": "dark robe"},
    )

    _upsert_by_id(
        db,
        RagCollection,
        COLL_1,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        novel_id=NOVEL_ID,
        name="E2E DS1",
        language_code="zh",
        description="dataset 1",
        tags_json=["e2e"],
    )
    _upsert_by_id(
        db,
        RagCollection,
        COLL_2,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        novel_id=NOVEL_ID,
        name="E2E DS2",
        language_code="zh",
        description="dataset 2",
        tags_json=["e2e"],
    )
    _upsert_by_id(
        db,
        KbVersion,
        KB_1,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        collection_id=COLL_1,
        version_name="v1",
        status="active",
    )
    _upsert_by_id(
        db,
        KbVersion,
        KB_2,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        collection_id=COLL_2,
        version_name="v1",
        status="active",
    )

    _upsert_by_id(
        db,
        PersonaPack,
        PACK_A,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        name="director_A",
        description="e2e pack A",
        tags_json=["e2e"],
    )
    _upsert_by_id(
        db,
        PersonaPack,
        PACK_B,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        name="director_B",
        description="e2e pack B",
        tags_json=["e2e"],
    )
    _upsert_by_id(
        db,
        PersonaPackVersion,
        PPV_A,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        persona_pack_id=PACK_A,
        version_name="1.0",
        style_json={"tone": "wuxia"},
        voice_json={"voice": "steady"},
        camera_json={"lens": "35mm"},
    )
    _upsert_by_id(
        db,
        PersonaPackVersion,
        PPV_B,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        persona_pack_id=PACK_B,
        version_name="1.0",
        style_json={"tone": "dark"},
        voice_json={"voice": "cold"},
        camera_json={"lens": "50mm"},
    )

    db.commit()


def run_skill_21(db):
    svc = EntityRegistryContinuityService(db)
    ctx = SkillContext(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        trace_id=f"trace_e2e_21_{RUN_SCOPE}",
        correlation_id=f"corr_e2e_21_{RUN_SCOPE}",
        idempotency_key=f"idem_e2e_21_{RUN_SCOPE}",
        schema_version="1.0",
    )
    inp = Skill21Input(
        extracted_entities=[
            ExtractedEntity(
                source_entity_uid="E1",
                entity_type="character",
                label="Li Mu",
                aliases=["李牧"],
                shot_ids=[SHOT_ID],
                scene_ids=[SCENE_ID],
            )
        ],
        existing_entity_registry=[
            ExistingRegistryEntity(
                entity_id=ENTITY_ID,
                entity_type="character",
                canonical_name="Li Mu",
                aliases=["李牧"],
            )
        ],
        shot_plan=[ShotPlanRef(shot_id=SHOT_ID, scene_id=SCENE_ID, entity_refs=["Li Mu"])],
        user_overrides={
            "preview_variant_seeds": [
                {
                    "source_entity_uid": "E1",
                    "shot_id": SHOT_ID,
                    "scene_id": SCENE_ID,
                    "view_angle": "front",
                    "generation_backend": "comfyui",
                    "status": "queued",
                }
            ],
            "voice_bindings": [
                {
                    "source_entity_uid": "E1",
                    "language_code": "zh-CN",
                    "voice_id": "voice_li_mu",
                    "tts_model": "tts-1",
                    "provider": "openai",
                    "locked": True,
                }
            ],
        },
    )
    out = svc.execute(inp, ctx)
    db.commit()
    return out


def run_skill_22(db):
    svc = PersonaDatasetIndexService(db)
    ctx = SkillContext(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        trace_id=f"trace_e2e_22_{RUN_SCOPE}",
        correlation_id=f"corr_e2e_22_{RUN_SCOPE}",
        idempotency_key=f"idem_e2e_22_{RUN_SCOPE}",
        schema_version="1.0",
    )
    inp = Skill22Input(
        datasets=[
            DatasetItem(dataset_id=COLL_1, name="dataset-1", role="primary"),
            DatasetItem(dataset_id=COLL_2, name="dataset-2", role="secondary"),
        ],
        indexes=[
            IndexItem(index_id="IDX_1", kb_version_id=KB_1, dataset_ids=[COLL_1], retrieval_policy={"priority": 90}),
            IndexItem(index_id="IDX_2", kb_version_id=KB_2, dataset_ids=[COLL_2], retrieval_policy={"priority": 110}),
        ],
        personas=[
            PersonaItem(
                persona_id="director_A",
                persona_version="1.0",
                dataset_ids=[COLL_1],
                index_ids=["IDX_1"],
                style_pack_ref="director_A@1.0",
                metadata={"persona_pack_version_id": PPV_A},
            ),
            PersonaItem(
                persona_id="director_B",
                persona_version="1.0",
                dataset_ids=[COLL_2],
                index_ids=["IDX_2"],
                style_pack_ref="director_B@1.0",
                metadata={"persona_pack_version_id": PPV_B},
            ),
        ],
        lineage_operations=[
            PersonaLineageOp(
                source_persona_ref="director_A@1.0",
                target_persona_ref="director_B@1.0",
                edge_type="branch",
                reason="e2e validation",
            )
        ],
        preview_query="night duel",
        preview_top_k=4,
    )
    out = svc.execute(inp, ctx)
    db.commit()
    return out


def count_rows(db):
    def c(model, *filters):
        stmt = select(func.count()).select_from(model)
        for flt in filters:
            stmt = stmt.where(flt)
        return int(db.execute(stmt).scalar() or 0)

    return {
        "entity_instance_links": c(EntityInstanceLink, EntityInstanceLink.run_id == RUN_ID, EntityInstanceLink.project_id == PROJECT_ID),
        "entity_continuity_profiles": c(EntityContinuityProfile, EntityContinuityProfile.project_id == PROJECT_ID, EntityContinuityProfile.entity_id == ENTITY_ID),
        "entity_preview_variants": c(EntityPreviewVariant, EntityPreviewVariant.run_id == RUN_ID, EntityPreviewVariant.project_id == PROJECT_ID, EntityPreviewVariant.entity_id == ENTITY_ID),
        "character_voice_bindings": c(CharacterVoiceBinding, CharacterVoiceBinding.project_id == PROJECT_ID, CharacterVoiceBinding.entity_id == ENTITY_ID),
        "persona_dataset_bindings": c(PersonaDatasetBinding, PersonaDatasetBinding.project_id == PROJECT_ID),
        "persona_index_bindings": c(PersonaIndexBinding, PersonaIndexBinding.project_id == PROJECT_ID),
        "persona_lineage_edges": c(PersonaLineageEdge, PersonaLineageEdge.project_id == PROJECT_ID),
        "persona_runtime_manifests": c(PersonaRuntimeManifest, PersonaRuntimeManifest.project_id == PROJECT_ID, PersonaRuntimeManifest.run_id == RUN_ID),
    }


def main() -> int:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL is required")
        return 2

    db = SessionLocal()
    try:
        seed_baseline(db)

        out21 = run_skill_21(db)
        out22 = run_skill_22(db)
        rows = count_rows(db)

        required_positive = [
            "entity_instance_links",
            "entity_continuity_profiles",
            "entity_preview_variants",
            "character_voice_bindings",
            "persona_dataset_bindings",
            "persona_index_bindings",
            "persona_lineage_edges",
            "persona_runtime_manifests",
        ]
        failed = [k for k in required_positive if rows.get(k, 0) <= 0]

        payload = {
            "database_url": db_url,
            "run_scope": RUN_SCOPE,
            "run_id": RUN_ID,
            "skill21_status": out21.status,
            "skill22_status": out22.status,
            "row_counts": rows,
            "failed_checks": failed,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))

        if failed:
            print(f"VALIDATION_RESULT: FAIL run_id={RUN_ID} failed_checks={','.join(failed)}")
            return 1
        print(
            "VALIDATION_RESULT: PASS "
            f"run_id={RUN_ID} skill21_status={out21.status} skill22_status={out22.status}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
