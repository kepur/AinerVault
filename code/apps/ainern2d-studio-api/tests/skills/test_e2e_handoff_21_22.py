"""E2E handoff tests for SKILL 21/22 enhanced chains.

Targets:
- E2E-021: 04 -> 21 -> 07 -> 08 -> 10 -> 20 (continuity preview chain)
- E2E-022: 11/12/14 -> 22 -> 10/15/17 (persona dataset/index runtime chain)
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.services.base_skill import SkillContext


def _load_composer_skill20_service():
    """Load composer SKILL 20 service without clashing with studio `app` package."""
    root = Path(__file__).resolve().parents[3]
    service_file = root / "ainern2d-composer" / "app" / "services" / "skills" / "skill_20_dsl_compiler.py"
    spec = importlib.util.spec_from_file_location("composer_skill20_module", service_file)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load composer skill_20 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DslCompilerService


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
        tenant_id="t_e2e",
        project_id="p_e2e",
        run_id="run_e2e_21_22",
        trace_id="tr_e2e_21_22",
        correlation_id="co_e2e_21_22",
        idempotency_key="idem_e2e_21_22",
        schema_version="1.0",
    )


def test_e2e_021_continuity_chain_reaches_dsl_compile(mock_db, ctx):
    from app.services.skills.skill_04_entity_extraction import EntityExtractionService
    from app.services.skills.skill_07_canonicalization import CanonicalizationService
    from app.services.skills.skill_08_asset_matcher import AssetMatcherService
    from app.services.skills.skill_10_prompt_planner import PromptPlannerService
    from app.services.skills.skill_21_entity_registry_continuity import (
        EntityRegistryContinuityService,
    )
    from ainern2d_shared.schemas.skills.skill_04 import Skill04Input
    from ainern2d_shared.schemas.skills.skill_07 import Skill07Input
    from ainern2d_shared.schemas.skills.skill_08 import Skill08Input
    from ainern2d_shared.schemas.skills.skill_10 import Skill10Input
    from ainern2d_shared.schemas.skills.skill_20 import Skill20FeatureFlags, Skill20Input
    from ainern2d_shared.schemas.skills.skill_21 import (
        ExistingRegistryEntity,
        ExtractedEntity,
        ShotPlanRef,
        Skill21Input,
    )

    s04 = EntityExtractionService(mock_db)
    s21 = EntityRegistryContinuityService(mock_db)
    s07 = CanonicalizationService(mock_db)
    s08 = AssetMatcherService(mock_db)
    s10 = PromptPlannerService(mock_db)
    s20 = _load_composer_skill20_service()(mock_db)

    out04 = s04.execute(
        Skill04Input(
            segments=[
                {
                    "segment_id": "SEG_001",
                    "text": "「李牧」说道：客栈大堂里只听见长剑出鞘。",
                }
            ],
            primary_language="zh-CN",
            scene_plan=[{"scene_id": "SC1", "title": "客栈大堂"}],
            shot_plan=[
                {
                    "shot_id": "S1",
                    "scene_id": "SC1",
                    "entity_hints": ["李牧", "客栈大堂", "长剑"],
                    "criticality": "critical",
                }
            ],
            culture_hint="cn_wuxia",
        ),
        ctx,
    )
    assert out04.entities

    character = next((e for e in out04.entities if e.entity_type == "character"), None)
    assert character is not None

    out21 = s21.execute(
        Skill21Input(
            extracted_entities=[
                ExtractedEntity(
                    source_entity_uid=character.entity_uid,
                    entity_type="character",
                    label=character.surface_form,
                    aliases=[character.surface_form],
                    shot_ids=["S1"],
                    scene_ids=["SC1"],
                )
            ],
            existing_entity_registry=[
                ExistingRegistryEntity(
                    entity_id=character.entity_uid,
                    entity_type="character",
                    canonical_name=character.surface_form,
                    aliases=[character.surface_form],
                )
            ],
            shot_plan=[
                ShotPlanRef(
                    shot_id="S1",
                    scene_id="SC1",
                    entity_refs=[character.surface_form, character.entity_uid],
                )
            ],
            user_overrides={
                "preview_variant_seeds": [
                    {
                        "source_entity_uid": character.entity_uid,
                        "shot_id": "S1",
                        "scene_id": "SC1",
                        "view_angle": "front",
                        "generation_backend": "comfyui",
                        "status": "approved",
                    }
                ],
                "voice_bindings": [
                    {
                        "source_entity_uid": character.entity_uid,
                        "language_code": "zh-CN",
                        "voice_id": "voice_li_mu",
                    }
                ],
            },
        ),
        ctx,
    )
    assert out21.continuity_exports.prompt_consistency_anchors

    out07 = s07.execute(
        Skill07Input(
            entities=[e.model_dump(mode="json") for e in out04.entities],
            entity_aliases=[a.model_dump(mode="json") for a in out04.entity_aliases],
            shots=[{"shot_id": "S1", "scene_id": "SC1"}],
            scenes=[{"scene_id": "SC1"}],
            culture_candidates=[
                {
                    "culture_pack_id": "cn_wuxia",
                    "confidence": 0.95,
                    "reason_tags": ["genre_wuxia"],
                }
            ],
            genre="wuxia",
            story_world_setting="ancient China",
            target_language="zh-CN",
        ),
        ctx,
    )

    out08 = s08.execute(
        Skill08Input(
            canonical_entities=[e.model_dump(mode="json") for e in out07.canonical_entities],
            entity_variant_mapping=[
                m.model_dump(mode="json") for m in out07.entity_variant_mapping
            ],
            selected_culture_pack=out07.selected_culture_pack.model_dump(mode="json"),
            culture_constraints=out07.culture_constraints.model_dump(mode="json"),
            conflicts=[c.model_dump(mode="json") for c in out07.conflicts],
            unresolved_entities=[
                u.model_dump(mode="json") for u in out07.unresolved_entities
            ],
            quality_profile="standard",
            backend_capability=["comfyui", "sdxl", "prompt_only"],
            continuity_exports=out21.continuity_exports.model_dump(mode="json"),
        ),
        ctx,
    )

    out10 = s10.execute(
        Skill10Input(
            entity_canonicalization_result=out07.model_dump(mode="json"),
            asset_match_result=out08.model_dump(mode="json"),
            visual_render_plan={
                "status": "ready_for_render_execution",
                "shot_render_plans": [
                    {
                        "shot_id": "S1",
                        "scene_id": "SC1",
                        "motion_level": "MEDIUM",
                        "criticality": "critical",
                    }
                ],
            },
            shot_plan={
                "shots": [
                    {
                        "shot_id": "S1",
                        "scene_id": "SC1",
                        "shot_type": "medium",
                        "goal": "inn standoff",
                        "entities": [character.entity_uid],
                    }
                ]
            },
            continuity_exports=out21.continuity_exports.model_dump(mode="json"),
            entity_registry_continuity_result=out21.model_dump(mode="json"),
        ),
        ctx,
    )

    assert character.entity_uid in out10.global_prompt_constraints.continuity_anchor_ids
    assert out10.shot_prompt_plans
    assert out10.shot_prompt_plans[0].derived_from.continuity_anchor_refs

    primary_variant = out10.model_variants[0]
    out20 = s20.execute(
        Skill20Input(
            shot_prompt_plans=[
                {
                    "shot_id": "S1",
                    "scene_id": "SC1",
                    "shot_type": "medium",
                    "shot_intent": "continuity-locked duel setup",
                    "subject_action": "standoff",
                    "entity_refs": [character.entity_uid],
                    "positive_prompt": primary_variant.positive_prompt,
                    "negative_prompt": primary_variant.negative_prompt,
                    "model_backend": "comfyui",
                }
            ],
            kb_version="KB_V1_E2E021",
            feature_flags=Skill20FeatureFlags(enable_multi_candidate_compile=False),
        ),
        ctx,
    )

    assert out20.status in ("compiled_ready", "review_required")
    assert out20.manifest.total_shots == 1
    assert out20.compiled_shots
    assert character.surface_form in out20.compiled_shots[0].positive_prompt


def test_e2e_022_persona_runtime_manifest_consumed_by_10_15_17(mock_db, ctx):
    from app.services.skills.skill_10_prompt_planner import PromptPlannerService
    from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
    from app.services.skills.skill_12_rag_embedding import RagPipelineService
    from app.services.skills.skill_14_persona_style import PersonaStyleService
    from app.services.skills.skill_15_creative_control import CreativeControlService
    from app.services.skills.skill_17_experiment import ExperimentService
    from app.services.skills.skill_22_persona_dataset_index import PersonaDatasetIndexService
    from ainern2d_shared.schemas.skills.skill_10 import Skill10Input
    from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input
    from ainern2d_shared.schemas.skills.skill_12 import KnowledgeItem, Skill12Input
    from ainern2d_shared.schemas.skills.skill_14 import PersonaPack, Skill14Input
    from ainern2d_shared.schemas.skills.skill_15 import Skill15Input
    from ainern2d_shared.schemas.skills.skill_17 import Skill17Input, VariantConfig
    from ainern2d_shared.schemas.skills.skill_22 import (
        DatasetItem,
        IndexItem,
        PersonaItem,
        Skill22Input,
    )

    s11 = RagKBManagerService(mock_db)
    s12 = RagPipelineService(mock_db)
    s14 = PersonaStyleService(mock_db)
    s22 = PersonaDatasetIndexService(mock_db)
    s10 = PromptPlannerService(mock_db)
    s15 = CreativeControlService(mock_db)
    s17 = ExperimentService(mock_db)

    kb_id = "kb_e2e_022"
    s11.execute(
        Skill11Input(
            kb_id=kb_id,
            action="create",
            entries=[
                KBEntry(
                    entry_id="KB_ITEM_001",
                    role="director",
                    title="Wuxia Prompt Rule",
                    content_markdown="Keep wuxia tone and character consistency.",
                    entry_type="prompt_recipe",
                    status="active",
                    flat_tags=["wuxia", "continuity"],
                )
            ],
        ),
        ctx,
    )
    out11_publish = s11.execute(Skill11Input(kb_id=kb_id, action="publish"), ctx)
    kb_version = out11_publish.kb_version_id or "KB_V1_E2E022"

    out12 = s12.execute(
        Skill12Input(
            kb_id=kb_id,
            kb_version_id=kb_version,
            knowledge_items=[
                KnowledgeItem(
                    item_id="KB_ITEM_001",
                    role="director",
                    content="Wuxia direction rules for duel scenes and shot consistency.",
                    tags=["wuxia", "director"],
                )
            ],
        ),
        ctx,
    )
    index_id = out12.index_metadata.index_id or "IDX_E2E_022"

    out14_create = s14.execute(
        Skill14Input(
            action="create",
            persona_pack=PersonaPack(
                persona_pack_id="director_pack_e2e022",
                display_name="Director E2E 022",
                base_role="director",
            ),
        ),
        ctx,
    )
    out14_publish = s14.execute(
        Skill14Input(
            action="publish",
            persona_pack=PersonaPack(persona_pack_id=out14_create.persona_pack_id),
        ),
        ctx,
    )
    style_pack_ref = f"{out14_create.persona_pack_id}@{out14_publish.current_version}"

    out22 = s22.execute(
        Skill22Input(
            datasets=[DatasetItem(dataset_id="DS_E2E_001", name="wuxia_rules")],
            indexes=[
                IndexItem(
                    index_id=index_id,
                    kb_version_id=kb_version,
                    dataset_ids=["DS_E2E_001"],
                    retrieval_policy={"priority": 90},
                )
            ],
            personas=[
                PersonaItem(
                    persona_id="director_A",
                    persona_version="2.0",
                    dataset_ids=["DS_E2E_001"],
                    index_ids=[index_id],
                    style_pack_ref=style_pack_ref,
                    policy_override_ref="policy_A_v2",
                    critic_profile_ref="critic_A_v2",
                    metadata={"persona_pack_version_id": "director_A@2.0"},
                )
            ],
            preview_query="night duel in rain",
            preview_top_k=3,
        ),
        ctx,
    )

    assert out22.runtime_manifests
    active_persona_ref = out22.runtime_manifests[0].persona_ref
    runtime_payload = out22.model_dump(mode="json")

    out10 = s10.execute(
        Skill10Input(
            entity_canonicalization_result={
                "selected_culture_pack": {"id": "cn_wuxia"},
                "culture_constraints": {"visual_do": [], "visual_dont": []},
                "entity_variant_mapping": [
                    {"entity_uid": "CHAR_0001", "entity_type": "character", "surface_form": "Li Mu"}
                ],
                "status": "ready_for_asset_match",
            },
            asset_match_result={
                "entity_asset_matches": [
                    {"entity_uid": "CHAR_0001", "lora_refs": [], "embedding_refs": []}
                ],
                "status": "ready_for_prompt_planner",
            },
            visual_render_plan={
                "shot_render_plans": [{"shot_id": "S1", "scene_id": "SC1", "motion_level": "LOW"}],
                "status": "ready_for_render_execution",
            },
            shot_plan={"shots": [{"shot_id": "S1", "scene_id": "SC1", "entities": ["CHAR_0001"]}]},
            persona_dataset_index_result=runtime_payload,
            active_persona_ref=active_persona_ref,
        ),
        ctx,
    )
    assert out10.global_prompt_constraints.persona_runtime_ref == active_persona_ref

    out15 = s15.execute(
        Skill15Input(
            persona_dataset_index_result=runtime_payload,
            active_persona_ref=active_persona_ref,
        ),
        ctx,
    )
    assert any(
        entry.action == "injected_persona_profile_from_skill22"
        and entry.decision == active_persona_ref
        for entry in out15.audit_trail
    )

    out17 = s17.execute(
        Skill17Input(
            control_variant=VariantConfig(variant_id="var_A"),
            test_variants=[VariantConfig(variant_id="var_B")],
            persona_dataset_index_result=runtime_payload,
            active_persona_ref=active_persona_ref,
        ),
        ctx,
    )
    assert all(v.persona_version == active_persona_ref for v in out17.variants)
    assert out17.status in ("concluded", "analyzing")
