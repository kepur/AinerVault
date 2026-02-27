"""Service-level dependency E2E for SKILL 03 -> 04 -> 21 -> 07 chain."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.services.base_skill import SkillContext


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
        tenant_id="t_e2e_03_21_07",
        project_id="p_e2e_03_21_07",
        run_id="run_e2e_03_21_07",
        trace_id="tr_e2e_03_21_07",
        correlation_id="co_e2e_03_21_07",
        idempotency_key="idem_e2e_03_21_07",
        schema_version="1.0",
    )


def test_e2e_03_to_04_21_07_dependency_chain(mock_db, ctx):
    from app.services.skills.skill_03_scene_shot_plan import SceneShotPlanService
    from app.services.skills.skill_04_entity_extraction import EntityExtractionService
    from app.services.skills.skill_07_canonicalization import CanonicalizationService
    from app.services.skills.skill_21_entity_registry_continuity import (
        EntityRegistryContinuityService,
    )
    from ainern2d_shared.schemas.skills.skill_03 import Skill03Input
    from ainern2d_shared.schemas.skills.skill_04 import Skill04Input
    from ainern2d_shared.schemas.skills.skill_07 import Skill07Input
    from ainern2d_shared.schemas.skills.skill_21 import (
        ExistingRegistryEntity,
        ExtractedEntity,
        ShotPlanRef,
        Skill21Input,
    )

    s03 = SceneShotPlanService(mock_db)
    s04 = EntityExtractionService(mock_db)
    s21 = EntityRegistryContinuityService(mock_db)
    s07 = CanonicalizationService(mock_db)

    base_segments = [
        {
            "segment_id": "SEG_001",
            "chapter_id": "ch_001",
            "text": "客栈大堂里风声骤紧，李牧说道：今夜黑衣人必来。",
        },
        {
            "segment_id": "SEG_002",
            "chapter_id": "ch_001",
            "text": "王掌柜低声道：后院已有持刀刺客潜伏，灯笼在雨里摇晃。",
        },
    ]

    out03 = s03.execute(
        Skill03Input(
            segments=base_segments,
            language_route={"source_primary_language": "zh-CN"},
            culture_hint="cn_wuxia",
            feature_flags={"enable_audio_event_pre_hints": True},
        ),
        ctx,
    )

    assert out03.status in ("ready_for_parallel_execution", "review_required")
    assert out03.scene_plan
    assert out03.shot_plan

    out04 = s04.execute(
        Skill04Input(
            segments=base_segments,
            primary_language="zh-CN",
            scene_plan=[s.model_dump(mode="json") for s in out03.scene_plan],
            shot_plan=[s.model_dump(mode="json") for s in out03.shot_plan],
            culture_hint="cn_wuxia",
        ),
        ctx,
    )

    assert out04.status in ("ready_for_canonicalization", "review_required")
    assert out04.entities

    extracted_entities: list[ExtractedEntity] = []
    for ent in out04.entities[:4]:
        extracted_entities.append(
            ExtractedEntity(
                source_entity_uid=ent.entity_uid,
                entity_type=ent.entity_type,
                label=ent.surface_form,
                aliases=[ent.surface_form],
                shot_ids=[sp.shot_id for sp in out03.shot_plan[:1]],
                scene_ids=[sc.scene_id for sc in out03.scene_plan[:1]],
            )
        )

    assert extracted_entities
    first = extracted_entities[0]
    out21 = s21.execute(
        Skill21Input(
            extracted_entities=extracted_entities,
            shot_plan=[
                ShotPlanRef(
                    shot_id=sp.shot_id,
                    scene_id=sp.scene_id,
                    entity_refs=list(sp.entity_hints),
                )
                for sp in out03.shot_plan
            ],
            existing_entity_registry=[
                ExistingRegistryEntity(
                    entity_id="ENT_LI_MU",
                    entity_type=first.entity_type,
                    canonical_name=first.label,
                    aliases=first.aliases,
                )
            ],
        ),
        ctx,
    )

    assert out21.status in ("continuity_ready", "review_required")
    assert out21.resolved_entities
    assert out21.continuity_exports.prompt_consistency_anchors

    resolved_ids = {r.source_entity_uid: r.matched_entity_id for r in out21.resolved_entities}
    shots_for_07 = []
    for sp in out03.shot_plan:
        refs = list(sp.entity_hints)
        for source_uid, matched_id in resolved_ids.items():
            if source_uid in refs and matched_id not in refs:
                refs.append(matched_id)
        shots_for_07.append(
            {"shot_id": sp.shot_id, "scene_id": sp.scene_id, "entity_refs": refs}
        )

    out07 = s07.execute(
        Skill07Input(
            entities=[e.model_dump(mode="json") for e in out04.entities],
            entity_aliases=[a.model_dump(mode="json") for a in out04.entity_aliases],
            shots=shots_for_07,
            scenes=[s.model_dump(mode="json") for s in out03.scene_plan],
            entity_registry_continuity_result=out21.model_dump(mode="json"),
            culture_candidates=[
                {
                    "culture_pack_id": "cn_wuxia",
                    "confidence": 0.95,
                    "reason_tags": ["genre_wuxia", "historical_style"],
                }
            ],
            genre="wuxia",
            story_world_setting="ancient jianghu",
            target_language="zh-CN",
        ),
        ctx,
    )

    assert out07.status in ("ready_for_asset_match", "review_required")
    assert out07.selected_culture_pack.id == "cn_wuxia"
    assert out07.entity_variant_mapping
    variant_by_uid = {v.entity_uid: v for v in out07.entity_variant_mapping}
    for source_uid, matched_id in resolved_ids.items():
        if source_uid in variant_by_uid:
            assert variant_by_uid[source_uid].entity_id == matched_id
