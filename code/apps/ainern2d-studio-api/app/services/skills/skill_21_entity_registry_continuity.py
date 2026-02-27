"""SKILL 21: Entity Registry & Continuity Manager — service skeleton.

Spec: SKILL_21_ENTITY_REGISTRY_CONTINUITY_MANAGER.md
Status: SERVICE_READY (skeleton)
"""
from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Scene, Shot
from ainern2d_shared.ainer_db_models.knowledge_models import Entity
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun
from ainern2d_shared.ainer_db_models.preview_models import (
    CharacterVoiceBinding,
    EntityContinuityProfile,
    EntityInstanceLink,
    EntityPreviewVariant,
)
from ainern2d_shared.schemas.skills.skill_21 import (
    ContinuityExports,
    ContinuityProfileOut,
    CreatedEntity,
    EntityInstanceLinkOut,
    ExistingRegistryEntity,
    ExtractedEntity,
    LinkConflict,
    RegistryActions,
    ResolvedEntity,
    Skill21Input,
    Skill21Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext


class EntityRegistryContinuityService(BaseSkillService[Skill21Input, Skill21Output]):
    """SKILL 21 — resolve entity identity and continuity anchors."""

    skill_id = "skill_21"
    skill_name = "EntityRegistryContinuityService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill21Input, ctx: SkillContext) -> Skill21Output:
        warnings: list[str] = []
        review_required_items: list[str] = []
        link_conflicts: list[LinkConflict] = []
        created_entities: list[CreatedEntity] = []
        resolved_entities: list[ResolvedEntity] = []
        instance_links: list[EntityInstanceLinkOut] = []
        continuity_profiles: list[ContinuityProfileOut] = []

        self._record_state(ctx, "INIT", "PRECHECKING")
        extracted_entities = self._collect_extracted_entities(input_dto)
        if not extracted_entities:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError("REQ-VALIDATION-021: extracted_entities is empty")
        if not input_dto.shot_plan:
            warnings.append("shot_plan_empty: instance tracking will be best-effort")

        self._record_state(ctx, "PRECHECKING", "ENTITY_LINKING")
        registry_index = self._build_registry_index(input_dto.existing_entity_registry)
        source_map = {e.source_entity_uid: e for e in extracted_entities}

        for entity in extracted_entities:
            matched = self._match_existing_entity(
                entity=entity,
                registry=input_dto.existing_entity_registry,
                registry_index=registry_index,
            )
            if len(matched) > 1:
                link_conflicts.append(
                    LinkConflict(
                        source_entity_uid=entity.source_entity_uid,
                        reason="multiple_registry_candidates",
                        candidates=[m.entity_id for m in matched],
                        confidence=0.6,
                    )
                )
                review_required_items.append(
                    f"link_conflict:{entity.source_entity_uid}:multiple_candidates"
                )

            if matched:
                selected = matched[0]
                confidence = 0.92 if len(matched) == 1 else 0.68
                resolved_entities.append(
                    ResolvedEntity(
                        source_entity_uid=entity.source_entity_uid,
                        linked_to_existing=True,
                        matched_entity_id=selected.entity_id,
                        confidence=confidence,
                        entity_type=entity.entity_type,
                        world_model_id=entity.world_model_id,
                    )
                )
                if confidence < 0.75:
                    review_required_items.append(
                        f"low_confidence_link:{entity.source_entity_uid}:{confidence:.2f}"
                    )
            else:
                new_entity_id = self._generate_entity_id(entity.entity_type, entity.label)
                created_entities.append(
                    CreatedEntity(
                        source_entity_uid=entity.source_entity_uid,
                        new_entity_id=new_entity_id,
                        entity_type=entity.entity_type,
                        canonical_name=entity.label,
                    )
                )
                resolved_entities.append(
                    ResolvedEntity(
                        source_entity_uid=entity.source_entity_uid,
                        linked_to_existing=False,
                        matched_entity_id=new_entity_id,
                        confidence=0.55,
                        entity_type=entity.entity_type,
                        world_model_id=entity.world_model_id,
                    )
                )
                review_required_items.append(
                    f"new_entity_created:{entity.source_entity_uid}:{new_entity_id}"
                )

        self._record_state(ctx, "ENTITY_LINKING", "INSTANCE_TRACKING")
        if input_dto.feature_flags.enable_instance_tracking:
            for resolved in resolved_entities:
                source_entity = source_map.get(resolved.source_entity_uid)
                if source_entity is None:
                    continue
                shot_ids = source_entity.shot_ids or self._infer_shot_ids(source_entity, input_dto)
                scene_ids = source_entity.scene_ids
                if not shot_ids:
                    warnings.append(
                        f"instance_tracking_missing_shot:{source_entity.source_entity_uid}"
                    )
                    review_required_items.append(
                        f"instance_tracking_missing_shot:{source_entity.source_entity_uid}"
                    )
                    continue
                for idx, shot_id in enumerate(shot_ids, start=1):
                    scene_id = (
                        scene_ids[idx - 1]
                        if idx - 1 < len(scene_ids)
                        else self._infer_scene_id_from_shot(shot_id, input_dto)
                    )
                    instance_links.append(
                        EntityInstanceLinkOut(
                            instance_id=f"SHOT_{shot_id}_{resolved.matched_entity_id}_INST_{idx:02d}",
                            entity_id=resolved.matched_entity_id,
                            shot_id=shot_id,
                            scene_id=scene_id,
                            source_entity_uid=resolved.source_entity_uid,
                        )
                    )

        self._record_state(ctx, "INSTANCE_TRACKING", "CONTINUITY_PROFILE_UPDATE")
        if input_dto.feature_flags.enable_continuity_rules:
            for resolved in resolved_entities:
                source_entity = source_map.get(resolved.source_entity_uid)
                if source_entity is None:
                    continue
                anchors = {
                    "entity_label": source_entity.label,
                    "aliases": source_entity.aliases,
                    "entity_type": source_entity.entity_type,
                    "traits": source_entity.traits,
                }
                if input_dto.feature_flags.enable_world_model_link and source_entity.world_model_id:
                    anchors["world_model_id"] = source_entity.world_model_id
                existing_profile = self._find_continuity_profile(ctx, resolved.matched_entity_id)
                if existing_profile and existing_profile.continuity_status == "locked":
                    continuity_status = "locked"
                else:
                    continuity_status = (
                        "needs_review"
                        if resolved.confidence < 0.75 or not source_entity.label
                        else "active"
                    )
                if continuity_status == "needs_review":
                    review_required_items.append(
                        f"continuity_review:{resolved.source_entity_uid}"
                    )
                continuity_profiles.append(
                    ContinuityProfileOut(
                        entity_id=resolved.matched_entity_id,
                        continuity_status=continuity_status,
                        anchors=anchors,
                        rules={
                            "identity_lock": True,
                            "allow_alias_expansion": True,
                            "allow_minor_style_variation": True,
                        },
                        allowed_variations=["costume_detail", "background_prop_density"],
                    )
                )

        continuity_exports = self._build_continuity_exports(
            resolved_entities=resolved_entities,
            continuity_profiles=continuity_profiles,
        )
        persisted = self._persist_outputs(
            input_dto=input_dto,
            ctx=ctx,
            resolved_entities=resolved_entities,
            entity_instance_links=instance_links,
            continuity_profiles=continuity_profiles,
            warnings=warnings,
            review_required_items=review_required_items,
        )

        status = (
            "review_required"
            if review_required_items
            else "continuity_ready"
        )
        terminal_state = (
            "REVIEW_REQUIRED"
            if review_required_items
            else "READY_FOR_CANONICALIZATION"
        )
        self._record_state(ctx, "CONTINUITY_PROFILE_UPDATE", terminal_state)
        logger.info(
            f"[{self.skill_id}] run={ctx.run_id} "
            f"resolved={len(resolved_entities)} created={len(created_entities)} "
            f"instances={len(instance_links)} status={status} "
            f"persisted(inst={persisted['instance_links']},cp={persisted['continuity_profiles']},"
            f"pv={persisted['preview_variants']},voice={persisted['voice_bindings']})"
        )

        return Skill21Output(
            status=status,
            registry_actions=RegistryActions(
                linked_existing=sum(1 for r in resolved_entities if r.linked_to_existing),
                created_new=len(created_entities),
                review_needed=len(review_required_items),
            ),
            resolved_entities=resolved_entities,
            created_entities=created_entities,
            entity_instance_links=instance_links,
            continuity_profiles=continuity_profiles,
            continuity_exports=continuity_exports,
            link_conflicts=link_conflicts,
            warnings=warnings,
            review_required_items=sorted(set(review_required_items)),
        )

    def _persist_outputs(
        self,
        input_dto: Skill21Input,
        ctx: SkillContext,
        resolved_entities: list[ResolvedEntity],
        entity_instance_links: list[EntityInstanceLinkOut],
        continuity_profiles: list[ContinuityProfileOut],
        warnings: list[str],
        review_required_items: list[str],
    ) -> dict[str, int]:
        persisted = {
            "instance_links": 0,
            "continuity_profiles": 0,
            "preview_variants": 0,
            "voice_bindings": 0,
        }
        source_to_entity = {r.source_entity_uid: r.matched_entity_id for r in resolved_entities}
        run_exists = self._id_exists(RenderRun, ctx.run_id)

        if not run_exists:
            warnings.append(f"persistence_skip_run_not_found:{ctx.run_id}")
            review_required_items.append(f"run_not_found:{ctx.run_id}")

        try:
            # 1) continuity profile upsert
            for profile in continuity_profiles:
                entity_id = profile.entity_id
                if not self._id_exists(Entity, entity_id):
                    warnings.append(f"continuity_profile_skip_entity_missing:{entity_id}")
                    review_required_items.append(f"entity_missing:{entity_id}")
                    continue

                existing = self._find_continuity_profile(ctx, entity_id)
                if existing:
                    if existing.continuity_status != "locked":
                        existing.continuity_status = profile.continuity_status
                    existing.anchors_json = dict(profile.anchors)
                    existing.rules_json = dict(profile.rules)
                    existing.meta_json = {
                        "allowed_variations": list(profile.allowed_variations),
                        "updated_by": self.skill_id,
                    }
                else:
                    self.db.add(
                        EntityContinuityProfile(
                            id=f"ECP_{uuid4().hex[:16].upper()}",
                            tenant_id=ctx.tenant_id,
                            project_id=ctx.project_id,
                            trace_id=ctx.trace_id,
                            correlation_id=ctx.correlation_id,
                            idempotency_key=f"{ctx.idempotency_key}:ecp:{entity_id}",
                            entity_id=entity_id,
                            continuity_status=profile.continuity_status,
                            anchors_json=dict(profile.anchors),
                            rules_json=dict(profile.rules),
                            meta_json={"allowed_variations": list(profile.allowed_variations)},
                        )
                    )
                persisted["continuity_profiles"] += 1

            # 2) entity instance links upsert
            if run_exists:
                for link in entity_instance_links:
                    entity_id = link.entity_id
                    if not self._id_exists(Entity, entity_id):
                        warnings.append(f"instance_link_skip_entity_missing:{entity_id}")
                        review_required_items.append(f"entity_missing:{entity_id}")
                        continue

                    shot_id = link.shot_id or None
                    if shot_id and not self._id_exists(Shot, shot_id):
                        warnings.append(f"instance_link_shot_missing:{shot_id}")
                        shot_id = None
                    scene_id = link.scene_id or None
                    if scene_id and not self._id_exists(Scene, scene_id):
                        warnings.append(f"instance_link_scene_missing:{scene_id}")
                        scene_id = None

                    instance_key = link.instance_id or f"INST_{uuid4().hex[:10].upper()}"
                    existing = self._find_instance_link(
                        ctx=ctx,
                        run_id=ctx.run_id,
                        entity_id=entity_id,
                        shot_id=shot_id,
                        instance_key=instance_key,
                    )
                    if existing:
                        existing.scene_id = scene_id
                        existing.meta_json = {"source_entity_uid": link.source_entity_uid}
                        existing.source_skill = self.skill_id
                    else:
                        self.db.add(
                            EntityInstanceLink(
                                id=f"EIL_{uuid4().hex[:16].upper()}",
                                tenant_id=ctx.tenant_id,
                                project_id=ctx.project_id,
                                trace_id=ctx.trace_id,
                                correlation_id=ctx.correlation_id,
                                idempotency_key=f"{ctx.idempotency_key}:eil:{instance_key}",
                                entity_id=entity_id,
                                run_id=ctx.run_id,
                                shot_id=shot_id,
                                scene_id=scene_id,
                                instance_key=instance_key,
                                source_skill=self.skill_id,
                                confidence=1.0,
                                meta_json={"source_entity_uid": link.source_entity_uid},
                            )
                        )
                    persisted["instance_links"] += 1

            # 3) optional preview variant seeds from user_overrides
            preview_seeds = input_dto.user_overrides.get("preview_variant_seeds", [])
            if isinstance(preview_seeds, list) and run_exists:
                for seed in preview_seeds:
                    if not isinstance(seed, dict):
                        continue
                    entity_ref = str(seed.get("entity_id") or seed.get("source_entity_uid") or "")
                    entity_id = source_to_entity.get(entity_ref, entity_ref)
                    if not entity_id or not self._id_exists(Entity, entity_id):
                        warnings.append(f"preview_seed_skip_entity_missing:{entity_ref}")
                        continue

                    shot_id = str(seed.get("shot_id") or "") or None
                    if shot_id and not self._id_exists(Shot, shot_id):
                        warnings.append(f"preview_seed_shot_missing:{shot_id}")
                        shot_id = None
                    scene_id = str(seed.get("scene_id") or "") or None
                    if scene_id and not self._id_exists(Scene, scene_id):
                        warnings.append(f"preview_seed_scene_missing:{scene_id}")
                        scene_id = None

                    self.db.add(
                        EntityPreviewVariant(
                            id=f"EPV_{uuid4().hex[:16].upper()}",
                            tenant_id=ctx.tenant_id,
                            project_id=ctx.project_id,
                            trace_id=ctx.trace_id,
                            correlation_id=ctx.correlation_id,
                            idempotency_key=f"{ctx.idempotency_key}:epv:{entity_id}:{uuid4().hex[:8]}",
                            run_id=ctx.run_id,
                            entity_id=entity_id,
                            shot_id=shot_id,
                            scene_id=scene_id,
                            view_angle=str(seed.get("view_angle") or "front"),
                            generation_backend=str(seed.get("generation_backend") or "comfyui"),
                            status=str(seed.get("status") or "queued"),
                            prompt_text=seed.get("prompt_text"),
                            negative_prompt_text=seed.get("negative_prompt_text"),
                            regenerate_from_variant_id=seed.get("regenerate_from_variant_id"),
                            review_note=seed.get("review_note"),
                            meta_json={"source": "skill_21.preview_variant_seed"},
                        )
                    )
                    persisted["preview_variants"] += 1

            # 4) optional character voice binding from user_overrides
            voice_bindings = input_dto.user_overrides.get("voice_bindings", [])
            if isinstance(voice_bindings, list):
                for binding in voice_bindings:
                    if not isinstance(binding, dict):
                        continue
                    entity_ref = str(binding.get("entity_id") or binding.get("source_entity_uid") or "")
                    entity_id = source_to_entity.get(entity_ref, entity_ref)
                    if not entity_id or not self._id_exists(Entity, entity_id):
                        warnings.append(f"voice_binding_skip_entity_missing:{entity_ref}")
                        continue

                    voice_id = str(binding.get("voice_id") or "")
                    if not voice_id:
                        warnings.append(f"voice_binding_skip_voice_id_missing:{entity_id}")
                        continue

                    language_code = str(binding.get("language_code") or "zh-CN")
                    existing = self._find_voice_binding(ctx, entity_id, language_code)
                    if existing:
                        existing.voice_id = voice_id
                        existing.tts_model = str(binding.get("tts_model") or "tts-1")
                        existing.provider = str(binding.get("provider") or "openai")
                        existing.locked = bool(binding.get("locked", True))
                        existing.notes = binding.get("notes")
                        existing.meta_json = {"source": "skill_21.voice_binding_update"}
                    else:
                        self.db.add(
                            CharacterVoiceBinding(
                                id=f"CVB_{uuid4().hex[:16].upper()}",
                                tenant_id=ctx.tenant_id,
                                project_id=ctx.project_id,
                                trace_id=ctx.trace_id,
                                correlation_id=ctx.correlation_id,
                                idempotency_key=f"{ctx.idempotency_key}:cvb:{entity_id}:{language_code}",
                                entity_id=entity_id,
                                language_code=language_code,
                                voice_id=voice_id,
                                tts_model=str(binding.get("tts_model") or "tts-1"),
                                provider=str(binding.get("provider") or "openai"),
                                locked=bool(binding.get("locked", True)),
                                notes=binding.get("notes"),
                                meta_json={"source": "skill_21.voice_binding_create"},
                            )
                        )
                    persisted["voice_bindings"] += 1

            self.db.flush()
            return persisted
        except Exception as exc:
            self.db.rollback()
            warnings.append(f"persistence_failed:{type(exc).__name__}")
            review_required_items.append("persistence_failed")
            logger.warning(f"[{self.skill_id}] persistence failed: {exc}")
            return {k: 0 for k in persisted}

    def _find_continuity_profile(self, ctx: SkillContext, entity_id: str) -> EntityContinuityProfile | None:
        return self._first_model(
            select(EntityContinuityProfile).where(
                EntityContinuityProfile.tenant_id == ctx.tenant_id,
                EntityContinuityProfile.project_id == ctx.project_id,
                EntityContinuityProfile.entity_id == entity_id,
                EntityContinuityProfile.deleted_at.is_(None),
            ),
            EntityContinuityProfile,
        )

    def _find_instance_link(
        self,
        ctx: SkillContext,
        run_id: str,
        entity_id: str,
        shot_id: str | None,
        instance_key: str,
    ) -> EntityInstanceLink | None:
        return self._first_model(
            select(EntityInstanceLink).where(
                EntityInstanceLink.tenant_id == ctx.tenant_id,
                EntityInstanceLink.project_id == ctx.project_id,
                EntityInstanceLink.run_id == run_id,
                EntityInstanceLink.entity_id == entity_id,
                EntityInstanceLink.shot_id == shot_id,
                EntityInstanceLink.instance_key == instance_key,
                EntityInstanceLink.deleted_at.is_(None),
            ),
            EntityInstanceLink,
        )

    def _find_voice_binding(
        self,
        ctx: SkillContext,
        entity_id: str,
        language_code: str,
    ) -> CharacterVoiceBinding | None:
        return self._first_model(
            select(CharacterVoiceBinding).where(
                CharacterVoiceBinding.tenant_id == ctx.tenant_id,
                CharacterVoiceBinding.project_id == ctx.project_id,
                CharacterVoiceBinding.entity_id == entity_id,
                CharacterVoiceBinding.language_code == language_code,
                CharacterVoiceBinding.deleted_at.is_(None),
            ),
            CharacterVoiceBinding,
        )

    def _first_model(self, query: Any, model_cls: type) -> Any | None:
        try:
            row = self.db.execute(query).scalars().first()
            return row if isinstance(row, model_cls) else None
        except Exception:
            return None

    def _id_exists(self, model_cls: type, item_id: str | None) -> bool:
        if not item_id:
            return False
        try:
            row = self.db.execute(
                select(model_cls.id).where(model_cls.id == item_id)
            ).first()
            return bool(row)
        except Exception:
            return False

    @staticmethod
    def _collect_extracted_entities(input_dto: Skill21Input) -> list[ExtractedEntity]:
        if input_dto.extracted_entities:
            return input_dto.extracted_entities

        result = input_dto.entity_extraction_result or {}
        entities: list[ExtractedEntity] = []
        raw_groups = {
            "character": result.get("characters", []),
            "scene": result.get("locations", []),
            "prop": result.get("props", []),
        }
        for entity_type, group in raw_groups.items():
            for idx, item in enumerate(group, start=1):
                source_uid = str(item.get("source_entity_uid") or item.get("entity_uid") or f"{entity_type}_{idx:03d}")
                entities.append(
                    ExtractedEntity(
                        source_entity_uid=source_uid,
                        entity_type=entity_type,
                        label=str(item.get("label") or item.get("name") or source_uid),
                        aliases=list(item.get("aliases") or []),
                        world_model_id=str(item.get("world_model_id") or ""),
                        traits=dict(item.get("traits") or {}),
                        shot_ids=list(item.get("shot_ids") or []),
                        scene_ids=list(item.get("scene_ids") or []),
                    )
                )
        return entities

    @staticmethod
    def _build_registry_index(registry: list[ExistingRegistryEntity]) -> dict[str, list[ExistingRegistryEntity]]:
        index: dict[str, list[ExistingRegistryEntity]] = {}
        for item in registry:
            keys = {item.canonical_name, *item.aliases}
            for key in keys:
                nk = EntityRegistryContinuityService._norm_key(key)
                if not nk:
                    continue
                index.setdefault(nk, []).append(item)
            if item.world_model_id:
                index.setdefault(f"world:{item.world_model_id.strip().lower()}", []).append(item)
        return index

    @classmethod
    def _match_existing_entity(
        cls,
        entity: ExtractedEntity,
        registry: list[ExistingRegistryEntity],
        registry_index: dict[str, list[ExistingRegistryEntity]],
    ) -> list[ExistingRegistryEntity]:
        matched: list[ExistingRegistryEntity] = []
        if entity.world_model_id:
            matched.extend(registry_index.get(f"world:{entity.world_model_id.strip().lower()}", []))
        keys = {entity.label, *entity.aliases}
        for key in keys:
            matched.extend(registry_index.get(cls._norm_key(key), []))

        # Deduplicate preserving order.
        seen: set[str] = set()
        deduped: list[ExistingRegistryEntity] = []
        for item in matched:
            if item.entity_id in seen:
                continue
            seen.add(item.entity_id)
            deduped.append(item)

        # Lightweight type preference: same entity_type first.
        if deduped:
            same_type = [d for d in deduped if d.entity_type == entity.entity_type]
            if same_type:
                return same_type + [d for d in deduped if d.entity_id not in {x.entity_id for x in same_type}]
        return deduped

    @staticmethod
    def _infer_shot_ids(entity: ExtractedEntity, input_dto: Skill21Input) -> list[str]:
        inferred: list[str] = []
        keys = {entity.source_entity_uid, entity.label, *entity.aliases}
        normalized_keys = {EntityRegistryContinuityService._norm_key(k) for k in keys if k}
        for shot in input_dto.shot_plan:
            refs = {EntityRegistryContinuityService._norm_key(r) for r in shot.entity_refs}
            if normalized_keys & refs:
                inferred.append(shot.shot_id)
        return inferred

    @staticmethod
    def _infer_scene_id_from_shot(shot_id: str, input_dto: Skill21Input) -> str:
        for shot in input_dto.shot_plan:
            if shot.shot_id == shot_id:
                return shot.scene_id
        return ""

    @staticmethod
    def _build_continuity_exports(
        resolved_entities: list[ResolvedEntity],
        continuity_profiles: list[ContinuityProfileOut],
    ) -> ContinuityExports:
        profile_map = {p.entity_id: p for p in continuity_profiles}
        asset_anchors: list[dict] = []
        prompt_anchors: list[dict] = []
        critic_rules: list[dict] = []

        for resolved in resolved_entities:
            profile = profile_map.get(resolved.matched_entity_id)
            anchors = profile.anchors if profile else {}
            rules = profile.rules if profile else {}
            asset_anchors.append(
                {
                    "entity_id": resolved.matched_entity_id,
                    "entity_type": resolved.entity_type,
                    "anchor_prompt": anchors.get("entity_label", ""),
                }
            )
            prompt_anchors.append(
                {
                    "entity_id": resolved.matched_entity_id,
                    "continuity_status": profile.continuity_status if profile else "unknown",
                    "consistency_tokens": [anchors.get("entity_label", ""), *anchors.get("aliases", [])],
                }
            )
            critic_rules.append(
                {
                    "entity_id": resolved.matched_entity_id,
                    "identity_lock": bool(rules.get("identity_lock", False)),
                    "allow_minor_style_variation": bool(rules.get("allow_minor_style_variation", False)),
                }
            )
        return ContinuityExports(
            asset_matcher_anchors=asset_anchors,
            prompt_consistency_anchors=prompt_anchors,
            critic_rules_baseline=critic_rules,
        )

    @staticmethod
    def _norm_key(text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        return normalized

    @staticmethod
    def _generate_entity_id(entity_type: str, label: str) -> str:
        type_prefix = {
            "character": "CHAR",
            "scene": "SCENE",
            "prop": "PROP",
        }.get((entity_type or "").lower(), "ENTITY")
        slug = re.sub(r"[^a-z0-9]+", "_", (label or "").strip().lower()).strip("_")
        slug = slug[:18] if slug else "unnamed"
        return f"{type_prefix}_{slug}_{uuid4().hex[:8].upper()}"
