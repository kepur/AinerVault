"""Unit tests for SKILL 05–08 execute() logic."""
from __future__ import annotations

import sys
import os
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
        tenant_id="t1", project_id="p1", run_id="run05",
        trace_id="tr5", correlation_id="co5",
        idempotency_key="idem05", schema_version="1.0",
    )


# ── SKILL 05: AudioAssetPlanService ──────────────────────────────────────────

class TestSkill05:
    def _make_service(self, db):
        from app.services.skills.skill_05_audio_asset_plan import AudioAssetPlanService
        return AudioAssetPlanService(db)

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_05 import Skill05Input
        svc = self._make_service(mock_db)
        scene_plan = [{"scene_id": "sc_001", "scene_type": "outdoor", "location": "mountain_top",
                        "emotion": "tense", "genre": "wuxia"}]
        shot_plan = [{"shot_id": "sh_001", "scene_id": "sc_001",
                      "tts_backfill_required": True,
                      "speaker_id": "char_001", "duration_seconds": 3.0}]
        inp = Skill05Input(scene_plan=scene_plan, shot_plan=shot_plan, language_code="zh-CN")
        out = svc.execute(inp, ctx)
        assert out.status == "ready_for_audio_execution"
        assert len(out.tts_plan) >= 1
        assert len(out.bgm_plan) >= 1

    def test_execute_empty_shots_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_05 import Skill05Input
        svc = self._make_service(mock_db)
        inp = Skill05Input(scene_plan=[], shot_plan=[], language_code="zh-CN")
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)

    def test_audio_task_dag_not_none(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_05 import Skill05Input
        svc = self._make_service(mock_db)
        scene_plan = [{"scene_id": "sc_001", "scene_type": "indoor", "emotion": "calm",
                        "genre": "drama"}]
        shot_plan = [{"shot_id": "sh_001", "scene_id": "sc_001",
                      "action_cues": ["sword clang"], "duration_seconds": 2.0}]
        inp = Skill05Input(scene_plan=scene_plan, shot_plan=shot_plan, language_code="en-US")
        out = svc.execute(inp, ctx)
        assert out.audio_task_dag is not None

    def test_review_required_triggered_by_backend_capability_conflicts(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_05 import (
            BackendAudioCapability,
            Skill05Input,
        )
        svc = self._make_service(mock_db)
        scene_plan = [
            {
                "scene_id": "sc_001",
                "scene_type": "action",
                "emotion_tone": "tense",
            }
        ]
        shot_plan = [
            {
                "shot_id": "sh_001",
                "scene_id": "sc_001",
                "tts_backfill_required": True,
                "characters_present": ["hero"],
                "audio_hints": ["metal_hit_sfx"],
                "dialogue_text": "动手！",
            }
        ]
        inp = Skill05Input(
            scene_plan=scene_plan,
            shot_plan=shot_plan,
            language_code="zh-CN",
            voice_cast_profile={"hero": "voice_hero"},
            backend_audio_capability=BackendAudioCapability(
                supported_tts_speakers=["voice_safe"],
                supported_bgm_moods=["neutral_background"],
                supported_sfx_event_types=["crowd"],
            ),
        )
        out = svc.execute(inp, ctx)
        assert out.status == "review_required"
        assert len(out.review_required_items) >= 1
        assert any(
            item.startswith("backend_capability_unsupported_")
            for item in out.review_required_items
        )


# ── SKILL 07: CanonicalizationService ────────────────────────────────────────

class TestSkill07:
    def _make_service(self, db):
        from app.services.skills.skill_07_canonicalization import CanonicalizationService
        return CanonicalizationService(db)

    def _entities(self):
        return [
            {"entity_uid": "ent_001", "entity_type": "character",
             "surface_form": "李明", "attributes": {}, "scene_scope": ["sc_001"]},
            {"entity_uid": "ent_002", "entity_type": "scene_place",
             "surface_form": "客栈大堂", "attributes": {}, "scene_scope": ["sc_001"]},
        ]

    def test_execute_basic_wuxia(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_07 import Skill07Input
        svc = self._make_service(mock_db)
        inp = Skill07Input(
            entities=self._entities(),
            scenes=[{"scene_id": "sc_001"}],
            target_language="zh-CN",
            genre="wuxia",
            story_world_setting="ancient China",
            culture_candidates=[{"culture_pack_id": "cn_wuxia", "confidence": 0.9,
                                   "reason_tags": ["genre_wuxia"]}],
        )
        out = svc.execute(inp, ctx)
        assert out.status in ("ready_for_asset_match", "review_required")
        assert out.selected_culture_pack.id == "cn_wuxia"
        assert len(out.canonical_entities) == 2
        assert len(out.entity_variant_mapping) >= 1

    def test_user_override_pack(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_07 import Skill07Input
        svc = self._make_service(mock_db)
        inp = Skill07Input(
            entities=self._entities(),
            scenes=[{"scene_id": "sc_001"}],
            target_language="zh-CN",
            user_override={"culture_pack": "jp_anime"},
        )
        out = svc.execute(inp, ctx)
        assert out.selected_culture_pack.id == "jp_anime"

    def test_empty_entities_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_07 import Skill07Input
        svc = self._make_service(mock_db)
        inp = Skill07Input(entities=[], scenes=[], target_language="zh-CN")
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)

    def test_canonical_namespace_format(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_07 import Skill07Input
        svc = self._make_service(mock_db)
        inp = Skill07Input(
            entities=[{"entity_uid": "ent_003", "entity_type": "prop",
                        "surface_form": "长剑", "attributes": {}, "scene_scope": ["sc_001"]}],
            scenes=[{"scene_id": "sc_001"}],
            target_language="zh-CN",
            culture_candidates=[{"culture_pack_id": "cn_wuxia", "confidence": 0.85}],
        )
        out = svc.execute(inp, ctx)
        assert out.canonical_entities[0].canonical_entity_specific.startswith("prop.")

    def test_consumes_skill21_resolved_entity_id_mapping(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_07 import Skill07Input
        svc = self._make_service(mock_db)
        inp = Skill07Input(
            entities=self._entities(),
            scenes=[{"scene_id": "sc_001"}],
            target_language="zh-CN",
            culture_candidates=[{"culture_pack_id": "cn_wuxia", "confidence": 0.9}],
            entity_registry_continuity_result={
                "resolved_entities": [
                    {
                        "source_entity_uid": "ent_001",
                        "matched_entity_id": "CHAR_0001_FIXED",
                    }
                ]
            },
        )
        out = svc.execute(inp, ctx)
        mapped = next(e for e in out.canonical_entities if e.entity_uid == "ent_001")
        assert mapped.entity_id == "CHAR_0001_FIXED"
        vm = next(v for v in out.entity_variant_mapping if v.entity_uid == "ent_001")
        assert vm.entity_id == "CHAR_0001_FIXED"
        assert vm.matched_entity_id == "CHAR_0001_FIXED"


# ── SKILL 08: AssetMatcherService ────────────────────────────────────────────

class TestSkill08:
    def _make_service(self, db):
        from app.services.skills.skill_08_asset_matcher import AssetMatcherService
        return AssetMatcherService(db)

    def _canonical_entities(self):
        return [
            {"entity_uid": "ent_001", "entity_type": "character", "criticality": "critical",
             "canonical_entity_specific": "character.human", "scene_scope": ["sc_001"]},
            {"entity_uid": "ent_002", "entity_type": "scene_place", "criticality": "important",
             "canonical_entity_specific": "place.social_lodging_venue.inn",
             "scene_scope": ["sc_001"]},
        ]

    def test_execute_basic(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_08 import Skill08Input
        svc = self._make_service(mock_db)
        inp = Skill08Input(
            canonical_entities=self._canonical_entities(),
            entity_variant_mapping=[
                {"entity_uid": "ent_001", "selected_variant_id": "character.human.cn_wuxia"},
                {"entity_uid": "ent_002", "selected_variant_id": "place.social_lodging_venue.inn.cn_wuxia"},
            ],
            selected_culture_pack={"id": "cn_wuxia"},
            quality_profile="standard",
        )
        out = svc.execute(inp, ctx)
        assert out.status in ("ready_for_prompt_planner", "review_required")
        assert out.matching_summary.total_entities == 2
        assert len(out.entity_asset_matches) == 2

    def test_asset_manifest_has_groups(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_08 import Skill08Input
        svc = self._make_service(mock_db)
        inp = Skill08Input(
            canonical_entities=self._canonical_entities(),
            entity_variant_mapping=[],
            selected_culture_pack={"id": "cn_wuxia"},
        )
        out = svc.execute(inp, ctx)
        assert out.asset_manifest is not None
        total = (len(out.asset_manifest.for_prompt_planner) +
                 len(out.asset_manifest.for_visual_render_planner) +
                 len(out.asset_manifest.for_audio_planner))
        assert total >= 1

    def test_asset_library_index_variant_exact_is_preferred(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_08 import Skill08Input
        svc = self._make_service(mock_db)
        inp = Skill08Input(
            canonical_entities=[
                {
                    "entity_uid": "ent_idx_1",
                    "entity_type": "character",
                    "criticality": "critical",
                    "canonical_entity_specific": "character.human",
                    "visual_tags": ["hero_face", "black_robe"],
                }
            ],
            entity_variant_mapping=[
                {
                    "entity_uid": "ent_idx_1",
                    "selected_variant_id": "character.human.cn_wuxia",
                }
            ],
            selected_culture_pack={"id": "cn_wuxia"},
            style_mode="realistic",
            backend_capability=["comfyui"],
            asset_library_index={
                "assets": [
                    {
                        "asset_id": "idx_exact_001",
                        "entity_uid": "ent_idx_1",
                        "entity_type": "character",
                        "selected_variant_id": "character.human.cn_wuxia",
                        "asset_type": "lora",
                        "culture_pack": "cn_wuxia",
                        "style_tags": ["realistic"],
                        "visual_tags": ["hero_face", "black_robe"],
                        "backend_compatibility": ["comfyui"],
                        "quality_tier": "high",
                        "path_or_ref": "asset://idx_exact_001",
                    },
                    {
                        "asset_id": "idx_wrong_001",
                        "entity_uid": "ent_idx_1",
                        "entity_type": "character",
                        "selected_variant_id": "character.human.cn_wuxia",
                        "asset_type": "lora",
                        "culture_pack": "en_western_fantasy",
                        "style_tags": ["realistic"],
                        "visual_tags": ["hero_face"],
                        "backend_compatibility": ["comfyui"],
                        "quality_tier": "high",
                    },
                ]
            },
        )
        out = svc.execute(inp, ctx)
        assert out.entity_asset_matches
        selected = out.entity_asset_matches[0].selected_asset
        assert selected is not None
        assert selected.asset_id == "idx_exact_001"
        assert selected.source == "asset_library_index"

    def test_asset_library_index_canonical_specific_fallback(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_08 import Skill08Input
        svc = self._make_service(mock_db)
        inp = Skill08Input(
            canonical_entities=[
                {
                    "entity_uid": "ent_idx_2",
                    "entity_type": "scene_place",
                    "criticality": "important",
                    "canonical_entity_root": "place.social_lodging_venue",
                    "canonical_entity_specific": "place.social_lodging_venue.inn",
                    "visual_tags": ["wood_architecture", "lantern_lighting"],
                }
            ],
            entity_variant_mapping=[{"entity_uid": "ent_idx_2"}],
            selected_culture_pack={"id": "cn_wuxia"},
            style_mode="realistic",
            backend_capability=["comfyui"],
            asset_library_index={
                "assets": [
                    {
                        "asset_id": "idx_specific_001",
                        "entity_uid": "ent_idx_2",
                        "entity_type": "scene_place",
                        "canonical_entity_specific": "place.social_lodging_venue.inn",
                        "asset_type": "scene_pack",
                        "culture_pack": "cn_wuxia",
                        "style_tags": ["realistic"],
                        "visual_tags": ["wood_architecture", "lantern_lighting"],
                        "backend_compatibility": ["comfyui"],
                        "quality_tier": "high",
                    }
                ]
            },
        )
        out = svc.execute(inp, ctx)
        assert out.entity_asset_matches
        match = out.entity_asset_matches[0]
        assert match.match_status == "matched_with_fallback"
        assert match.selected_asset is not None
        assert match.selected_asset.asset_id == "idx_specific_001"
        assert match.fallback_level == "variant_same_pack_parent"

    def test_empty_entities_raises(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_08 import Skill08Input
        svc = self._make_service(mock_db)
        inp = Skill08Input(canonical_entities=[], entity_variant_mapping=[],
                           selected_culture_pack={})
        with pytest.raises(ValueError, match="REQ-VALIDATION"):
            svc.execute(inp, ctx)

    def test_criticality_ordering(self, mock_db, ctx):
        """Critical entities appear before background in entity_asset_matches."""
        from ainern2d_shared.schemas.skills.skill_08 import Skill08Input
        entities = [
            {"entity_uid": "e_bg", "entity_type": "character", "criticality": "background",
             "canonical_entity_specific": "character.human"},
            {"entity_uid": "e_crit", "entity_type": "character", "criticality": "critical",
             "canonical_entity_specific": "character.human"},
        ]
        svc = self._make_service(mock_db)
        inp = Skill08Input(canonical_entities=entities, entity_variant_mapping=[],
                           selected_culture_pack={"id": "cn_wuxia"})
        out = svc.execute(inp, ctx)
        assert out.entity_asset_matches[0].entity_uid == "e_crit"

    def test_continuity_identity_lock_is_consumed(self, mock_db, ctx):
        from ainern2d_shared.schemas.skills.skill_08 import Skill08Input
        svc = self._make_service(mock_db)
        inp = Skill08Input(
            canonical_entities=[
                {
                    "entity_uid": "CHAR_0001",
                    "entity_type": "character",
                    "criticality": "critical",
                    "canonical_entity_specific": "character.human",
                    "visual_tags": ["hero_face", "black robe", "same hero face and costume"],
                }
            ],
            entity_variant_mapping=[
                {
                    "entity_uid": "CHAR_0001",
                    "selected_variant_id": "character.human.cn_wuxia",
                    "entity_id": "CHAR_0001",
                }
            ],
            selected_culture_pack={"id": "cn_wuxia"},
            backend_capability=["comfyui", "sdxl", "prompt_only"],
            continuity_exports={
                "asset_matcher_anchors": [
                    {
                        "entity_id": "CHAR_0001",
                        "anchor_prompt": "same hero face and costume",
                    }
                ],
                "prompt_consistency_anchors": [
                    {
                        "entity_id": "CHAR_0001",
                        "continuity_status": "active",
                        "consistency_tokens": ["hero_face", "black robe"],
                    }
                ],
                "critic_rules_baseline": [
                    {"entity_id": "CHAR_0001", "identity_lock": True}
                ],
            },
        )
        out = svc.execute(inp, ctx)
        assert out.status == "review_required"
        assert any(
            "high_severity_conflict" in item.reason
            for item in out.review_required_items
        )
