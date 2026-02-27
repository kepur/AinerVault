"""Service-level handoff E2E for SKILL 04 continuity fields -> SKILL 21 consumption."""
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
        tenant_id="t_e2e_04_21",
        project_id="p_e2e_04_21",
        run_id="run_e2e_04_21",
        trace_id="tr_e2e_04_21",
        correlation_id="co_e2e_04_21",
        idempotency_key="idem_e2e_04_21",
        schema_version="1.0",
    )


def test_e2e_04_continuity_handoff_consumed_by_21(mock_db, ctx):
    from app.services.skills.skill_04_entity_extraction import EntityExtractionService
    from app.services.skills.skill_21_entity_registry_continuity import (
        EntityRegistryContinuityService,
    )
    from ainern2d_shared.schemas.skills.skill_04 import Skill04Input
    from ainern2d_shared.schemas.skills.skill_21 import ExistingRegistryEntity, Skill21Input

    s04 = EntityExtractionService(mock_db)
    s21 = EntityRegistryContinuityService(mock_db)

    out04 = s04.execute(
        Skill04Input(
            segments=[
                {
                    "segment_id": "SEG_A",
                    "text": "李牧说道：客栈后院有刺客，快取长剑。",
                },
                {
                    "segment_id": "SEG_B",
                    "text": "王掌柜答道：大堂灯笼已灭，风雨声越来越近。",
                },
            ],
            primary_language="zh-CN",
            scene_plan=[{"scene_id": "SC01"}],
            shot_plan=[
                {
                    "shot_id": "S01",
                    "scene_id": "SC01",
                    "entity_hints": ["李牧", "客栈后院", "长剑"],
                },
                {
                    "shot_id": "S02",
                    "scene_id": "SC01",
                    "entity_hints": ["王掌柜", "大堂", "灯笼"],
                },
            ],
            culture_hint="cn_wuxia",
        ),
        ctx,
    )

    assert out04.continuity_handoff.extracted_entities
    assert out04.continuity_handoff.shot_plan_refs

    first = out04.continuity_handoff.extracted_entities[0]
    out21 = s21.execute(
        Skill21Input(
            extracted_entities=[
                item.model_dump(mode="json")
                for item in out04.continuity_handoff.extracted_entities
            ],
            shot_plan=[
                item.model_dump(mode="json")
                for item in out04.continuity_handoff.shot_plan_refs
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
