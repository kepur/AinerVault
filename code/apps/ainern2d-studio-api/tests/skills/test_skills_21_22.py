"""Unit tests for SKILL 21–22 execute() logic."""
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
        tenant_id="t1",
        project_id="p1",
        run_id="run_21_22",
        trace_id="tr_21_22",
        correlation_id="co_21_22",
        idempotency_key="idem_21_22",
        schema_version="1.0",
    )


class TestSkill21:
    def _make_service(self, db):
        from app.services.skills.skill_21_entity_registry_continuity import EntityRegistryContinuityService

        return EntityRegistryContinuityService(db)

    def test_link_existing_entity_continuity_ready(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_21 import (
            ExistingRegistryEntity,
            ExtractedEntity,
            ShotPlanRef,
            Skill21Input,
        )

        svc = self._make_service(mock_db)
        inp = Skill21Input(
            extracted_entities=[
                ExtractedEntity(
                    source_entity_uid="E1",
                    entity_type="character",
                    label="Li Mu",
                    aliases=["李牧"],
                    shot_ids=["S1"],
                    scene_ids=["SC1"],
                )
            ],
            existing_entity_registry=[
                ExistingRegistryEntity(
                    entity_id="CHAR_0001",
                    entity_type="character",
                    canonical_name="Li Mu",
                    aliases=["李牧"],
                )
            ],
            shot_plan=[ShotPlanRef(shot_id="S1", scene_id="SC1", entity_refs=["Li Mu"])],
        )
        out = svc.execute(inp, ctx)
        assert out.status == "continuity_ready"
        assert out.registry_actions.linked_existing == 1
        assert out.registry_actions.created_new == 0
        assert out.review_required_items == []

    def test_create_new_entity_marks_review_required(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_21 import (
            ExtractedEntity,
            ShotPlanRef,
            Skill21Input,
        )

        svc = self._make_service(mock_db)
        inp = Skill21Input(
            extracted_entities=[
                ExtractedEntity(
                    source_entity_uid="E9",
                    entity_type="prop",
                    label="Ancient Sword",
                    shot_ids=["S2"],
                    scene_ids=["SC2"],
                )
            ],
            shot_plan=[ShotPlanRef(shot_id="S2", scene_id="SC2", entity_refs=["Ancient Sword"])],
        )
        out = svc.execute(inp, ctx)
        assert out.status == "review_required"
        assert out.registry_actions.created_new == 1
        assert len(out.review_required_items) >= 1


class TestSkill22:
    def _make_service(self, db):
        from app.services.skills.skill_22_persona_dataset_index import PersonaDatasetIndexService

        return PersonaDatasetIndexService(db)

    def test_persona_manifest_ready(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_22 import (
            DatasetItem,
            IndexItem,
            PersonaItem,
            Skill22Input,
        )

        svc = self._make_service(mock_db)
        inp = Skill22Input(
            datasets=[DatasetItem(dataset_id="DS_001", name="wu_xia_rules")],
            indexes=[IndexItem(index_id="IDX_001", kb_version_id="KB_V1", dataset_ids=["DS_001"])],
            personas=[
                PersonaItem(
                    persona_id="director_A",
                    persona_version="1.0",
                    dataset_ids=["DS_001"],
                    index_ids=["IDX_001"],
                    style_pack_ref="director_xiaoli@1.2.0",
                )
            ],
            preview_query="night duel on rain street",
            preview_top_k=3,
        )
        out = svc.execute(inp, ctx)
        assert out.status == "persona_index_ready"
        assert len(out.runtime_manifests) == 1
        assert out.runtime_manifests[0].persona_ref == "director_A@1.0"

    def test_missing_persona_style_goes_review_required(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_22 import (
            DatasetItem,
            IndexItem,
            PersonaItem,
            Skill22Input,
        )

        svc = self._make_service(mock_db)
        inp = Skill22Input(
            datasets=[DatasetItem(dataset_id="DS_001", name="rules")],
            indexes=[IndexItem(index_id="IDX_001", kb_version_id="KB_V1", dataset_ids=["DS_001"])],
            personas=[
                PersonaItem(
                    persona_id="director_B",
                    persona_version="1.0",
                    dataset_ids=["DS_001"],
                    index_ids=["IDX_001"],
                    style_pack_ref="",
                )
            ],
        )
        out = svc.execute(inp, ctx)
        assert out.status == "review_required"
        assert any("persona_style_missing" in item for item in out.review_required_items)

    def test_empty_personas_raise(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_22 import Skill22Input

        svc = self._make_service(mock_db)
        with pytest.raises(ValueError, match="REQ-VALIDATION-022"):
            svc.execute(Skill22Input(personas=[]), ctx)
