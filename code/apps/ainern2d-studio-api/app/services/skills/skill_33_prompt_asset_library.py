"""SKILL 33: Prompt Asset Library & Character Growth Continuity — Service.

State machine:
  INIT → PRECHECKING → CORE_BUILDING → STAGE_RESOLVING → ASSET_ASSEMBLING
       → SHOT_BINDING → SNAPSHOT_SEED_EXPORTING
       → READY_FOR_ASSET_MATCH_AND_PROMPT_PLANNER | REVIEW_REQUIRED | FAILED

Four-layer model:
  1. Character Core  — from EntityContinuityProfile.anchors/rules
  2. Character Stage — from CharacterStageProfile by chapter range
  3. Shot Override   — from ShotAssetBinding.state_override_json
  4. Prompt Snapshot — immutable layered snapshot
"""
from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Chapter, Scene, Shot
from ainern2d_shared.ainer_db_models.knowledge_models import Entity
from ainern2d_shared.ainer_db_models.preview_models import EntityContinuityProfile
from ainern2d_shared.ainer_db_models.prompt_asset_models import (
    CharacterStageProfile,
    PromptSnapshot,
    SemanticAsset,
    ShotAssetBinding,
)
from ainern2d_shared.schemas.skills.skill_33 import (
    CharacterCoreProfile,
    CharacterStageOut,
    ConsistencyRule,
    PromptSnapshotSeed,
    ReviewRequiredItem33,
    SemanticAssetOut,
    ShotAssetBindingOut,
    Skill33Input,
    Skill33Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


def _consistency_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


class PromptAssetLibraryService(BaseSkillService[Skill33Input, Skill33Output]):
    """SKILL 33 — build prompt asset context from four-layer model."""

    skill_id = "skill_33"
    skill_name = "PromptAssetLibraryService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, inp: Skill33Input, ctx: SkillContext) -> Skill33Output:
        warnings: list[str] = []
        review_items: list[ReviewRequiredItem33] = []
        core_profiles: list[CharacterCoreProfile] = []
        stage_profiles: list[CharacterStageOut] = []
        semantic_assets: list[SemanticAssetOut] = []
        bindings_out: list[ShotAssetBindingOut] = []
        snapshot_seeds: list[PromptSnapshotSeed] = []
        consistency_rules: list[ConsistencyRule] = []

        # ── PRECHECKING ───────────────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")

        entities = self._load_entities(inp)
        if not entities:
            warnings.append("no_entities_found")
            return Skill33Output(
                status="FAILED",
                warnings=warnings,
                review_required_items=review_items,
            )

        chapters = self._load_chapters(inp)
        shots = self._load_shots(inp, chapters)

        # ── CORE_BUILDING ─────────────────────────────────────────
        if inp.feature_flags.enable_core_building:
            self._record_state(ctx, "PRECHECKING", "CORE_BUILDING")
            core_profiles, core_rules = self._build_character_cores(inp, entities)
            consistency_rules.extend(core_rules)

        # ── STAGE_RESOLVING ───────────────────────────────────────
        if inp.feature_flags.enable_stage_resolving:
            self._record_state(ctx, "CORE_BUILDING", "STAGE_RESOLVING")
            stage_profiles = self._resolve_stages(inp, entities, chapters)

        # ── ASSET_ASSEMBLING ──────────────────────────────────────
        if inp.feature_flags.enable_asset_assembling:
            self._record_state(ctx, "STAGE_RESOLVING", "ASSET_ASSEMBLING")
            semantic_assets = self._assemble_assets(inp)

        # ── SHOT_BINDING ──────────────────────────────────────────
        if inp.feature_flags.enable_shot_binding:
            self._record_state(ctx, "ASSET_ASSEMBLING", "SHOT_BINDING")
            bindings_out = self._build_shot_bindings(inp, shots, entities, stage_profiles)

        # ── SNAPSHOT_SEED_EXPORTING ───────────────────────────────
        if inp.feature_flags.enable_snapshot_export:
            self._record_state(ctx, "SHOT_BINDING", "SNAPSHOT_SEED_EXPORTING")
            snapshot_seeds = self._export_snapshot_seeds(
                inp, core_profiles, stage_profiles, bindings_out, semantic_assets,
            )

        # ── CONSISTENCY CHECK ─────────────────────────────────────
        if inp.feature_flags.enable_consistency_check:
            violations = self._check_consistency(
                core_profiles, stage_profiles, bindings_out, semantic_assets,
            )
            review_items.extend(violations)

        # ── Final status ──────────────────────────────────────────
        if review_items:
            status = "REVIEW_REQUIRED"
        else:
            status = "READY_FOR_ASSET_MATCH_AND_PROMPT_PLANNER"

        self._record_state(ctx, "SNAPSHOT_SEED_EXPORTING", status)

        return Skill33Output(
            status=status,
            character_core_profiles=core_profiles,
            character_stage_profiles=stage_profiles,
            semantic_assets=semantic_assets,
            shot_asset_bindings=bindings_out,
            prompt_snapshot_seeds=snapshot_seeds,
            consistency_rules=consistency_rules,
            warnings=warnings,
            review_required_items=review_items,
        )

    # ── Load helpers ──────────────────────────────────────────────

    def _load_entities(self, inp: Skill33Input) -> list[Entity]:
        stmt = (
            select(Entity)
            .where(
                Entity.tenant_id == inp.tenant_id,
                Entity.project_id == inp.project_id,
                Entity.novel_id == inp.novel_id,
                Entity.deleted_at.is_(None),
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def _load_chapters(self, inp: Skill33Input) -> list[Chapter]:
        stmt = (
            select(Chapter)
            .where(
                Chapter.tenant_id == inp.tenant_id,
                Chapter.project_id == inp.project_id,
                Chapter.novel_id == inp.novel_id,
                Chapter.deleted_at.is_(None),
            )
            .order_by(Chapter.chapter_no)
        )
        if inp.chapter_ids:
            stmt = stmt.where(Chapter.id.in_(inp.chapter_ids))
        return list(self.db.execute(stmt).scalars().all())

    def _load_shots(self, inp: Skill33Input, chapters: list[Chapter]) -> list[Shot]:
        if not chapters:
            return []
        chapter_ids = [c.id for c in chapters]
        stmt = (
            select(Shot)
            .where(
                Shot.tenant_id == inp.tenant_id,
                Shot.project_id == inp.project_id,
                Shot.chapter_id.in_(chapter_ids),
                Shot.deleted_at.is_(None),
            )
            .order_by(Shot.shot_no)
        )
        return list(self.db.execute(stmt).scalars().all())

    # ── CORE_BUILDING ─────────────────────────────────────────────

    def _build_character_cores(
        self, inp: Skill33Input, entities: list[Entity],
    ) -> tuple[list[CharacterCoreProfile], list[ConsistencyRule]]:
        cores: list[CharacterCoreProfile] = []
        rules: list[ConsistencyRule] = []

        for entity in entities:
            # Load continuity profile if exists
            profile = self.db.execute(
                select(EntityContinuityProfile).where(
                    EntityContinuityProfile.tenant_id == inp.tenant_id,
                    EntityContinuityProfile.project_id == inp.project_id,
                    EntityContinuityProfile.entity_id == entity.id,
                )
            ).scalars().first()

            anchors = {}
            rules_json: dict = {}
            if profile:
                anchors = profile.anchors_json or {}
                rules_json = profile.rules_json or {}

            # Supplement from Entity.traits_json
            traits = entity.traits_json or {}
            base_appearance = anchors.get("appearance", traits.get("appearance", {}))
            base_temperament = anchors.get("temperament", traits.get("temperament", {}))

            forbidden = rules_json.get("forbidden", [])
            must_not = rules_json.get("must_not", [])

            core = CharacterCoreProfile(
                entity_id=entity.id,
                entity_label=entity.label,
                entity_type=entity.type.value if entity.type else "character",
                anchors=anchors,
                rules=rules_json,
                base_appearance=base_appearance if isinstance(base_appearance, dict) else {"description": str(base_appearance)},
                base_temperament=base_temperament if isinstance(base_temperament, dict) else {"description": str(base_temperament)},
                forbidden=forbidden if isinstance(forbidden, list) else [],
                must_not=must_not if isinstance(must_not, list) else [],
            )
            cores.append(core)

            # Generate consistency rules from core forbidden/must_not
            for f in core.forbidden:
                rules.append(ConsistencyRule(
                    entity_id=entity.id,
                    rule_type="forbidden",
                    description=f,
                    source="core",
                ))
            for m in core.must_not:
                rules.append(ConsistencyRule(
                    entity_id=entity.id,
                    rule_type="must_not",
                    description=m,
                    source="core",
                ))

        return cores, rules

    # ── STAGE_RESOLVING ───────────────────────────────────────────

    def _resolve_stages(
        self, inp: Skill33Input, entities: list[Entity], chapters: list[Chapter],
    ) -> list[CharacterStageOut]:
        results: list[CharacterStageOut] = []
        entity_ids = [e.id for e in entities]

        stmt = (
            select(CharacterStageProfile)
            .where(
                CharacterStageProfile.tenant_id == inp.tenant_id,
                CharacterStageProfile.project_id == inp.project_id,
                CharacterStageProfile.entity_id.in_(entity_ids),
                CharacterStageProfile.deleted_at.is_(None),
            )
            .order_by(CharacterStageProfile.chapter_start)
        )
        stages = list(self.db.execute(stmt).scalars().all())

        # If chapters specified, filter stages by chapter range overlap
        if chapters:
            chapter_nos = {c.chapter_no for c in chapters}
            min_ch = min(chapter_nos)
            max_ch = max(chapter_nos)
        else:
            min_ch, max_ch = 1, 9999

        for s in stages:
            s_end = s.chapter_end or 9999
            if s.chapter_start <= max_ch and s_end >= min_ch:
                results.append(CharacterStageOut(
                    stage_id=s.id,
                    entity_id=s.entity_id,
                    stage_name=s.stage_name,
                    chapter_start=s.chapter_start,
                    chapter_end=s.chapter_end,
                    appearance_override=s.appearance_override_json or {},
                    temperament_override=s.temperament_override_json or {},
                    default_costume_asset_id=s.default_costume_asset_id,
                    default_prop_asset_ids=s.default_prop_asset_ids_json or [],
                    emotional_baseline=s.emotional_baseline_json or {},
                    status_tags=s.status_tags_json or [],
                ))

        return results

    # ── ASSET_ASSEMBLING ──────────────────────────────────────────

    def _assemble_assets(self, inp: Skill33Input) -> list[SemanticAssetOut]:
        stmt = (
            select(SemanticAsset)
            .where(
                SemanticAsset.tenant_id == inp.tenant_id,
                SemanticAsset.project_id == inp.project_id,
                SemanticAsset.novel_id == inp.novel_id,
                SemanticAsset.is_active.is_(True),
                SemanticAsset.deleted_at.is_(None),
            )
        )
        assets = list(self.db.execute(stmt).scalars().all())
        return [
            SemanticAssetOut(
                asset_id=a.id,
                novel_id=a.novel_id,
                entity_id=a.entity_id,
                asset_type=a.asset_type,
                canonical_name=a.canonical_name,
                aliases=a.aliases_json or [],
                tags=a.tags_json or [],
                status=a.status,
                structured=a.structured_json or {},
                prompt=a.prompt_json or {},
                negative_prompt=a.negative_prompt_json or {},
                is_active=a.is_active,
            )
            for a in assets
        ]

    # ── SHOT_BINDING ──────────────────────────────────────────────

    def _build_shot_bindings(
        self,
        inp: Skill33Input,
        shots: list[Shot],
        entities: list[Entity],
        stage_profiles: list[CharacterStageOut],
    ) -> list[ShotAssetBindingOut]:
        if not shots:
            return []

        shot_ids = [s.id for s in shots]
        stmt = (
            select(ShotAssetBinding)
            .where(
                ShotAssetBinding.tenant_id == inp.tenant_id,
                ShotAssetBinding.project_id == inp.project_id,
                ShotAssetBinding.shot_id.in_(shot_ids),
                ShotAssetBinding.deleted_at.is_(None),
            )
        )
        existing = list(self.db.execute(stmt).scalars().all())
        return [
            ShotAssetBindingOut(
                binding_id=b.id,
                chapter_id=b.chapter_id,
                shot_id=b.shot_id,
                entity_id=b.entity_id,
                binding_role=b.binding_role,
                stage_profile_id=b.stage_profile_id,
                selected_asset_ids=b.selected_asset_ids_json or [],
                state_override=b.state_override_json or {},
                prompt_snapshot_id=b.prompt_snapshot_id,
            )
            for b in existing
        ]

    # ── SNAPSHOT_SEED_EXPORTING ───────────────────────────────────

    def _export_snapshot_seeds(
        self,
        inp: Skill33Input,
        cores: list[CharacterCoreProfile],
        stages: list[CharacterStageOut],
        bindings: list[ShotAssetBindingOut],
        assets: list[SemanticAssetOut],
    ) -> list[PromptSnapshotSeed]:
        seeds: list[PromptSnapshotSeed] = []
        core_map = {c.entity_id: c for c in cores}
        stage_map: dict[str, list[CharacterStageOut]] = {}
        for s in stages:
            stage_map.setdefault(s.entity_id, []).append(s)
        asset_map = {a.asset_id: a for a in assets}

        for binding in bindings:
            entity_id = binding.entity_id or ""
            core = core_map.get(entity_id)
            core_layer = {}
            if core:
                core_layer = {
                    "appearance": core.base_appearance,
                    "temperament": core.base_temperament,
                    "anchors": core.anchors,
                }

            # Pick best stage
            stage_layer = {}
            if binding.stage_profile_id:
                for st in stages:
                    if st.stage_id == binding.stage_profile_id:
                        stage_layer = {
                            "stage_name": st.stage_name,
                            "appearance_override": st.appearance_override,
                            "temperament_override": st.temperament_override,
                        }
                        break

            override_layer = binding.state_override

            # Gather asset prompt fragments
            asset_layers = []
            for aid in binding.selected_asset_ids:
                asset = asset_map.get(aid)
                if asset:
                    asset_layers.append({
                        "asset_type": asset.asset_type,
                        "name": asset.canonical_name,
                        "prompt": asset.prompt,
                        "negative_prompt": asset.negative_prompt,
                    })

            # Merge prompt text
            parts = []
            if core and core.base_appearance:
                desc = core.base_appearance.get("description", "")
                if desc:
                    parts.append(str(desc))
            for al in asset_layers:
                p = al.get("prompt", {})
                if isinstance(p, dict):
                    txt = p.get("text", p.get("description", ""))
                    if txt:
                        parts.append(str(txt))
                elif isinstance(p, str) and p:
                    parts.append(p)
            if override_layer:
                override_desc = override_layer.get("description", "")
                if override_desc:
                    parts.append(str(override_desc))
            merged_text = ", ".join(parts) if parts else ""

            neg_parts = []
            if core:
                for f in core.forbidden:
                    neg_parts.append(f)
            for al in asset_layers:
                np_ = al.get("negative_prompt", {})
                if isinstance(np_, dict):
                    txt = np_.get("text", "")
                    if txt:
                        neg_parts.append(str(txt))
                elif isinstance(np_, str) and np_:
                    neg_parts.append(np_)
            merged_neg = ", ".join(neg_parts) if neg_parts else ""

            c_hash = _consistency_hash(
                entity_id, binding.shot_id, merged_text, merged_neg,
            )

            seeds.append(PromptSnapshotSeed(
                shot_id=binding.shot_id,
                entity_id=binding.entity_id,
                source_type="auto",
                core_layer=core_layer,
                stage_layer=stage_layer,
                override_layer=override_layer,
                asset_layers=asset_layers,
                merged_prompt_text=merged_text,
                merged_negative_prompt_text=merged_neg,
                consistency_hash=c_hash,
            ))

        return seeds

    # ── CONSISTENCY CHECK ─────────────────────────────────────────

    def _check_consistency(
        self,
        cores: list[CharacterCoreProfile],
        stages: list[CharacterStageOut],
        bindings: list[ShotAssetBindingOut],
        assets: list[SemanticAssetOut],
    ) -> list[ReviewRequiredItem33]:
        violations: list[ReviewRequiredItem33] = []
        core_map = {c.entity_id: c for c in cores}
        asset_map = {a.asset_id: a for a in assets}

        for binding in bindings:
            entity_id = binding.entity_id or ""
            core = core_map.get(entity_id)
            if not core:
                continue

            # Check forbidden items in selected assets
            for aid in binding.selected_asset_ids:
                asset = asset_map.get(aid)
                if not asset:
                    continue
                asset_tags = [t.lower() for t in asset.tags]
                asset_name = asset.canonical_name.lower()
                for forbidden in core.forbidden:
                    forbidden_lower = forbidden.lower()
                    if forbidden_lower in asset_name or forbidden_lower in asset_tags:
                        violations.append(ReviewRequiredItem33(
                            item_type="forbidden_hit",
                            entity_id=entity_id,
                            shot_id=binding.shot_id,
                            description=f"Asset '{asset.canonical_name}' matches forbidden rule: '{forbidden}'",
                            severity="error",
                        ))

            # Check must_not in override
            override = binding.state_override
            if override and core.must_not:
                override_str = str(override).lower()
                for must_not in core.must_not:
                    if must_not.lower() in override_str:
                        violations.append(ReviewRequiredItem33(
                            item_type="must_not_violation",
                            entity_id=entity_id,
                            shot_id=binding.shot_id,
                            description=f"Override contains must_not item: '{must_not}'",
                            severity="error",
                        ))

        return violations
