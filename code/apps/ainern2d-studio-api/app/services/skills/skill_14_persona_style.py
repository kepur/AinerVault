"""SKILL 14: PersonaStyleService — 业务逻辑实现。
参考规格: SKILL_14_PERSONA_STYLE_PACK_MANAGER.md
状态: SERVICE_READY

State machine:
  INIT → LOADING_CHAIN → RESOLVING_INHERITANCE → VALIDATING_STYLE
       → BUILDING_MANIFEST → EXPORTING → READY | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_14 import (
    ConflictItem,
    ConsistencyIssue,
    CulturePackRef,
    EntityStyleEntry,
    ExportResult,
    InheritanceNode,
    PersonaPack,
    PersonaVersion,
    PolicyOverride,
    RAGRecipeOverride,
    Skill14FeatureFlags,
    Skill14Input,
    Skill14Output,
    StyleDNA,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from ainern2d_shared.utils.time import utcnow

_VALID_ACTIONS = frozenset({
    "create", "read", "update", "delete", "list", "clone", "compare",
    "publish", "resolve", "validate", "export", "import_culture",
})

_VALID_BASE_ROLES = frozenset({"director", "cinematographer", "editor"})

_SHADING_METHODS = frozenset({"flat", "cel", "gradient", "realistic"})

_INHERITANCE_LAYERS = ("base", "culture", "genre", "project", "user_override")

_STYLE_DNA_FLOAT_FIELDS = (
    "cut_density", "motion_aggressiveness", "dialogue_patience",
    "atmospheric_hold_preference", "impact_alignment_priority",
    "symmetry_preference",
)

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


# ══════════════════════════════════════════════════════════════════════════════
# In-memory pack store (placeholder for real DB persistence)
# ══════════════════════════════════════════════════════════════════════════════
_PACK_STORE: dict[str, PersonaPack] = {}


class PersonaStyleService(BaseSkillService[Skill14Input, Skill14Output]):
    """SKILL 14 — Persona & Style Pack Manager.

    Supports full CRUD, inheritance-chain resolution, conflict detection,
    style-consistency validation, multi-format export, culture-pack import,
    version management with rollback, and clone/compare operations.
    """

    skill_id = "skill_14"
    skill_name = "PersonaStyleService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── public entry ──────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill14Input, ctx: SkillContext) -> Skill14Output:
        self._record_state(ctx, "INIT", "LOADING_CHAIN")

        action = (input_dto.action or "create").strip().lower()
        if action not in _VALID_ACTIONS:
            self._record_state(ctx, "LOADING_CHAIN", "FAILED")
            raise ValueError(
                f"REQ-VALIDATION-001: unsupported persona action '{action}'"
            )

        flags = input_dto.feature_flags or Skill14FeatureFlags()

        try:
            handler = getattr(self, f"_action_{action}")
        except AttributeError:
            self._record_state(ctx, "LOADING_CHAIN", "FAILED")
            raise ValueError(f"REQ-VALIDATION-002: no handler for '{action}'")

        try:
            result: Skill14Output = handler(input_dto, ctx, flags)
        except Exception:
            self._record_state(ctx, "BUILDING_MANIFEST", "FAILED")
            raise

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"action={action} pack={result.persona_pack_id} "
            f"state={result.state}"
        )
        return result

    # ══════════════════════════════════════════════════════════════════════════
    # CRUD actions
    # ══════════════════════════════════════════════════════════════════════════

    def _action_create(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        pack = dto.persona_pack or PersonaPack()
        pack.persona_pack_id = pack.persona_pack_id or f"pp_{uuid.uuid4().hex[:8]}"
        self._validate_pack_fields(pack)
        pack.status = "draft"
        pack.current_version = pack.current_version or "0.1.0"
        pack.versions = [
            PersonaVersion(
                version=pack.current_version,
                changelog="initial creation",
                snapshot=pack.model_dump(),
            )
        ]
        _PACK_STORE[pack.persona_pack_id] = pack
        self._record_state(ctx, "LOADING_CHAIN", "READY")
        return Skill14Output(
            persona_pack_id=pack.persona_pack_id,
            current_version=pack.current_version,
            status=pack.status,
            state="READY",
            **self._build_binding_refs(pack),
            persona_pack_manifest=pack,
        )

    def _action_read(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        pack = self._get_pack_or_error(dto.target_pack_id)
        self._record_state(ctx, "LOADING_CHAIN", "READY")
        return Skill14Output(
            persona_pack_id=pack.persona_pack_id,
            current_version=pack.current_version,
            status=pack.status,
            state="READY",
            **self._build_binding_refs(pack),
            persona_pack_manifest=pack,
        )

    def _action_update(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        pid = dto.persona_pack.persona_pack_id or dto.target_pack_id
        if dto.rollback_to_version:
            return self._action_update_with_rollback(pid, dto.rollback_to_version, ctx)

        existing = self._get_pack_or_error(pid)
        incoming = dto.persona_pack
        self._validate_pack_fields(incoming)

        # Merge mutable fields
        existing.display_name = incoming.display_name or existing.display_name
        existing.base_role = incoming.base_role or existing.base_role
        existing.inherits_from = incoming.inherits_from or existing.inherits_from
        existing.style_dna = incoming.style_dna or existing.style_dna
        existing.persona_manifest = incoming.persona_manifest or existing.persona_manifest
        existing.rag_recipe_override = incoming.rag_recipe_override or existing.rag_recipe_override
        existing.policy_override = incoming.policy_override or existing.policy_override
        existing.critic_threshold_override = incoming.critic_threshold_override or existing.critic_threshold_override
        existing.tags = incoming.tags or existing.tags
        existing.status = "stale_eval"

        new_ver = self._bump_version(existing.current_version)
        existing.current_version = new_ver
        existing.versions.append(
            PersonaVersion(
                version=new_ver,
                changelog="update",
                parent_version=existing.versions[-1].version if existing.versions else "",
                snapshot=existing.model_dump(),
            )
        )
        _PACK_STORE[pid] = existing
        self._record_state(ctx, "LOADING_CHAIN", "READY")
        return Skill14Output(
            persona_pack_id=pid,
            current_version=new_ver,
            status=existing.status,
            state="READY",
            **self._build_binding_refs(existing),
            persona_pack_manifest=existing,
        )

    def _action_delete(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        pid = dto.target_pack_id
        self._get_pack_or_error(pid)
        _PACK_STORE.pop(pid, None)
        self._record_state(ctx, "LOADING_CHAIN", "READY")
        return Skill14Output(
            persona_pack_id=pid, status="deleted", state="READY",
        )

    def _action_list(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        """Return first pack as manifest + warnings listing all ids."""
        ids = list(_PACK_STORE.keys())
        first = _PACK_STORE[ids[0]] if ids else None
        self._record_state(ctx, "LOADING_CHAIN", "READY")
        return Skill14Output(
            persona_pack_id=first.persona_pack_id if first else "",
            status="listed",
            state="READY",
            **self._build_binding_refs(first or PersonaPack()),
            persona_pack_manifest=first,
            warnings=[f"available_packs: {ids}"],
        )

    def _action_clone(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        source = self._get_pack_or_error(dto.target_pack_id)
        cloned = source.model_copy(deep=True)
        cloned.persona_pack_id = f"pp_{uuid.uuid4().hex[:8]}"
        cloned.display_name = f"{source.display_name}_clone"
        cloned.status = "draft"
        cloned.current_version = "0.1.0"
        cloned.versions = [
            PersonaVersion(
                version="0.1.0",
                changelog=f"cloned from {source.persona_pack_id}",
                snapshot=cloned.model_dump(),
            )
        ]
        _PACK_STORE[cloned.persona_pack_id] = cloned
        self._record_state(ctx, "LOADING_CHAIN", "READY")
        return Skill14Output(
            persona_pack_id=cloned.persona_pack_id,
            current_version=cloned.current_version,
            status=cloned.status,
            state="READY",
            **self._build_binding_refs(cloned),
            persona_pack_manifest=cloned,
        )

    def _action_compare(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        pack_a = self._get_pack_or_error(dto.target_pack_id)
        pack_b = self._get_pack_or_error(dto.compare_pack_id)
        diff = self._compute_diff(pack_a.model_dump(), pack_b.model_dump())
        self._record_state(ctx, "LOADING_CHAIN", "READY")
        return Skill14Output(
            persona_pack_id=pack_a.persona_pack_id,
            current_version=pack_a.current_version,
            status="compared",
            state="READY",
            **self._build_binding_refs(pack_a),
            diff=diff,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Publish / Resolve / Validate / Export / Import
    # ══════════════════════════════════════════════════════════════════════════

    def _action_publish(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        pid = dto.persona_pack.persona_pack_id or dto.target_pack_id
        pack = self._get_pack_or_error(pid)

        self._record_state(ctx, "LOADING_CHAIN", "BUILDING_MANIFEST")

        if flags.strict_version_control:
            if not _SEMVER_RE.match(pack.current_version):
                raise ValueError(
                    f"PLAN-GENERATE-001: invalid semver '{pack.current_version}'"
                )

        pack.status = "active"
        new_ver = self._bump_version(pack.current_version, bump="minor")
        pack.current_version = new_ver
        pack.versions.append(
            PersonaVersion(
                version=new_ver,
                changelog="published",
                parent_version=pack.versions[-1].version if pack.versions else "",
                snapshot=pack.model_dump(),
            )
        )
        _PACK_STORE[pid] = pack

        self._record_state(ctx, "BUILDING_MANIFEST", "READY")
        return Skill14Output(
            persona_pack_id=pid,
            current_version=new_ver,
            status="active",
            state="READY",
            **self._build_binding_refs(pack),
            persona_pack_manifest=pack,
        )

    def _action_resolve(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        """Resolve inheritance chain → effective style DNA + overrides."""
        self._record_state(ctx, "LOADING_CHAIN", "RESOLVING_INHERITANCE")

        pack = dto.persona_pack or PersonaPack()
        chain = dto.inheritance_chain or self._auto_load_chain(
            pack.inherits_from, flags.max_chain_depth,
        )

        if len(chain) > flags.max_chain_depth:
            raise ValueError(
                f"PLAN-GENERATE-002: inheritance depth {len(chain)} "
                f"exceeds max_chain_depth={flags.max_chain_depth}"
            )

        resolved_dna, resolved_rag, resolved_policy, conflicts, chain_nodes = (
            self._resolve_chain(chain, pack, flags)
        )

        self._record_state(ctx, "RESOLVING_INHERITANCE", "VALIDATING_STYLE")

        state = "READY"
        if conflicts and not flags.auto_resolve_conflicts:
            state = "REVIEW_REQUIRED"

        self._record_state(ctx, "VALIDATING_STYLE", state)

        resolved_from = [n.pack_id for n in chain_nodes] + [pack.persona_pack_id]

        return Skill14Output(
            persona_pack_id=pack.persona_pack_id,
            current_version=pack.current_version,
            status=pack.status,
            state=state,
            **self._build_binding_refs(pack),
            resolved_style_dna=resolved_dna,
            resolved_rag_override=resolved_rag,
            resolved_policy_override=resolved_policy,
            resolved_from=resolved_from,
            inheritance_chain_used=chain_nodes,
            conflicts=conflicts,
            conflict_auto_resolved=flags.auto_resolve_conflicts and len(conflicts) > 0,
        )

    def _action_validate(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        """Validate style consistency across project entities."""
        self._record_state(ctx, "LOADING_CHAIN", "VALIDATING_STYLE")

        pack = dto.persona_pack or PersonaPack()
        issues = self._check_style_consistency(
            pack, dto.entity_styles or [],
        )

        state = "READY" if not issues else "REVIEW_REQUIRED"
        self._record_state(ctx, "VALIDATING_STYLE", state)

        return Skill14Output(
            persona_pack_id=pack.persona_pack_id,
            current_version=pack.current_version,
            status=pack.status,
            state=state,
            **self._build_binding_refs(pack),
            consistency_issues=issues,
            warnings=[f"{len(issues)} consistency issue(s) found"] if issues else [],
        )

    def _action_export(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        """Export style pack in requested format."""
        self._record_state(ctx, "LOADING_CHAIN", "EXPORTING")

        pack = dto.persona_pack or PersonaPack()
        fmt = (dto.export_request.format if dto.export_request else "json").lower()
        export = self._export_pack(pack, fmt)

        self._record_state(ctx, "EXPORTING", "READY")

        return Skill14Output(
            persona_pack_id=pack.persona_pack_id,
            current_version=pack.current_version,
            status=pack.status,
            state="READY",
            **self._build_binding_refs(pack),
            export_result=export,
        )

    def _action_import_culture(
        self, dto: Skill14Input, ctx: SkillContext, flags: Skill14FeatureFlags,
    ) -> Skill14Output:
        """Import visual rules from a SKILL 07 culture pack into style DNA."""
        self._record_state(ctx, "LOADING_CHAIN", "RESOLVING_INHERITANCE")

        pack = dto.persona_pack or PersonaPack()
        culture = dto.culture_pack_ref or CulturePackRef()
        warnings: list[str] = []

        pack = self._apply_culture_pack(pack, culture, warnings)

        self._record_state(ctx, "RESOLVING_INHERITANCE", "READY")

        return Skill14Output(
            persona_pack_id=pack.persona_pack_id,
            current_version=pack.current_version,
            status=pack.status,
            state="READY",
            **self._build_binding_refs(pack),
            persona_pack_manifest=pack,
            warnings=warnings,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Rollback support (invoked via update with rollback_to_version)
    # ══════════════════════════════════════════════════════════════════════════

    def _action_update_with_rollback(
        self, pid: str, target_ver: str, ctx: SkillContext,
    ) -> Skill14Output:
        pack = self._get_pack_or_error(pid)
        for v in pack.versions:
            if v.version == target_ver and v.snapshot:
                restored = PersonaPack.model_validate(v.snapshot)
                restored.current_version = self._bump_version(pack.current_version)
                restored.status = "draft"
                restored.versions = pack.versions + [
                    PersonaVersion(
                        version=restored.current_version,
                        changelog=f"rollback to {target_ver}",
                        parent_version=pack.current_version,
                        snapshot=restored.model_dump(),
                    )
                ]
                _PACK_STORE[pid] = restored
                self._record_state(ctx, "LOADING_CHAIN", "READY")
                return Skill14Output(
                    persona_pack_id=pid,
                    current_version=restored.current_version,
                    status=restored.status,
                    state="READY",
                    **self._build_binding_refs(restored),
                    persona_pack_manifest=restored,
                    warnings=[f"rolled back to {target_ver}"],
                )
        raise ValueError(
            f"PLAN-GENERATE-003: version '{target_ver}' not found for pack '{pid}'"
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ══════════════════════════════════════════════════════════════════════════

    # ── Validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_pack_fields(pack: PersonaPack) -> None:
        if pack.base_role and pack.base_role not in _VALID_BASE_ROLES:
            raise ValueError(
                f"REQ-VALIDATION-003: invalid base_role '{pack.base_role}'"
            )
        dna = pack.style_dna
        for field in _STYLE_DNA_FLOAT_FIELDS:
            val = getattr(dna, field, None)
            if val is not None and not (0.0 <= val <= 1.0):
                raise ValueError(
                    f"REQ-VALIDATION-004: style_dna.{field}={val} out of [0,1]"
                )
        if dna.shading_method and dna.shading_method not in _SHADING_METHODS:
            raise ValueError(
                f"REQ-VALIDATION-005: invalid shading_method '{dna.shading_method}'"
            )

    # ── Store lookup ──────────────────────────────────────────────────────────

    @staticmethod
    def _get_pack_or_error(pid: str) -> PersonaPack:
        if not pid or pid not in _PACK_STORE:
            raise ValueError(
                f"ASSET-UPLOAD-001: persona pack '{pid}' not found"
            )
        return _PACK_STORE[pid]

    # ── Version helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _bump_version(current: str, bump: str = "patch") -> str:
        parts = current.split(".")
        if len(parts) != 3:
            parts = ["0", "1", "0"]
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        if bump == "major":
            major += 1; minor = 0; patch = 0
        elif bump == "minor":
            minor += 1; patch = 0
        else:
            patch += 1
        return f"{major}.{minor}.{patch}"

    @staticmethod
    def _build_binding_refs(pack: PersonaPack) -> dict[str, str]:
        """Build canonical refs consumed by SKILL 22 persona binding."""
        pack_id = str(pack.persona_pack_id or "").strip()
        version = str(pack.current_version or "").strip()
        persona_pack_version_ref = f"{pack_id}@{version}" if pack_id and version else ""
        style_pack_ref = persona_pack_version_ref

        policy_override_ref = str(
            (pack.policy_override.extra or {}).get("policy_override_ref") or ""
        ).strip()
        if not policy_override_ref and persona_pack_version_ref:
            has_policy_override = (
                pack.policy_override.prefer_microshots_in_high_motion
                or pack.policy_override.max_dialogue_hold_ms_in_action != 1200
                or bool(pack.policy_override.extra)
            )
            if has_policy_override:
                policy_override_ref = f"{persona_pack_version_ref}:policy"

        critic_profile_ref = str(
            (pack.critic_threshold_override.extra or {}).get("critic_profile_ref") or ""
        ).strip()
        if not critic_profile_ref and persona_pack_version_ref:
            has_critic_override = (
                pack.critic_threshold_override.motion_readability_min != 0.7
                or bool(pack.critic_threshold_override.extra)
            )
            if has_critic_override:
                critic_profile_ref = f"{persona_pack_version_ref}:critic"

        return {
            "style_pack_ref": style_pack_ref,
            "policy_override_ref": policy_override_ref,
            "critic_profile_ref": critic_profile_ref,
            "persona_pack_version_ref": persona_pack_version_ref,
        }

    # ── Inheritance resolution ────────────────────────────────────────────────

    def _auto_load_chain(
        self, parent_ids: list[str], max_depth: int,
    ) -> list[PersonaPack]:
        """Walk parent_ids and recursively load from store."""
        chain: list[PersonaPack] = []
        visited: set[str] = set()

        def _walk(ids: list[str], depth: int) -> None:
            if depth > max_depth:
                return
            for pid in ids:
                if pid in visited:
                    continue
                visited.add(pid)
                parent = _PACK_STORE.get(pid)
                if parent is None:
                    logger.warning(f"[{self.skill_id}] parent pack '{pid}' not in store")
                    continue
                _walk(parent.inherits_from, depth + 1)
                chain.append(parent)

        _walk(parent_ids, 1)
        return chain

    @staticmethod
    def _resolve_chain(
        chain: list[PersonaPack],
        leaf: PersonaPack,
        flags: Skill14FeatureFlags,
    ) -> tuple[
        StyleDNA,
        RAGRecipeOverride,
        PolicyOverride,
        list[ConflictItem],
        list[InheritanceNode],
    ]:
        """Merge chain (base→leaf). Child values override parent values.

        Returns (resolved_dna, resolved_rag, resolved_policy, conflicts, nodes).
        """
        conflicts: list[ConflictItem] = []
        nodes: list[InheritanceNode] = []

        merged_dna = StyleDNA()
        merged_rag = RAGRecipeOverride()
        merged_policy = PolicyOverride()

        all_packs = list(chain) + [leaf]

        for idx, pack in enumerate(all_packs):
            layer = _INHERITANCE_LAYERS[min(idx, len(_INHERITANCE_LAYERS) - 1)]
            nodes.append(InheritanceNode(
                pack_id=pack.persona_pack_id,
                layer=layer,
                version=pack.current_version,
            ))

            parent_dna_dict = merged_dna.model_dump()
            child_dna_dict = pack.style_dna.model_dump()

            # Detect conflicts before overwrite
            if flags.enable_inheritance and idx > 0:
                for key, child_val in child_dna_dict.items():
                    parent_val = parent_dna_dict.get(key)
                    if child_val != parent_val and parent_val is not None:
                        # Only flag as conflict when both explicitly differ
                        # from defaults on "important" fields
                        if key in ("shading_method",) and isinstance(child_val, str):
                            if child_val != parent_val:
                                conflicts.append(ConflictItem(
                                    field_path=f"style_dna.{key}",
                                    parent_value=parent_val,
                                    child_value=child_val,
                                    severity="warn",
                                    description=(
                                        f"Parent specifies '{parent_val}' but "
                                        f"child overrides to '{child_val}'"
                                    ),
                                ))

            # Merge: child overrides parent
            if flags.enable_inheritance:
                for key, child_val in child_dna_dict.items():
                    default_val = StyleDNA.model_fields[key].default
                    if child_val != default_val:
                        setattr(merged_dna, key, child_val)

                # Merge RAG override
                rag_dict = pack.rag_recipe_override.model_dump()
                for k, v in rag_dict.items():
                    default_v = RAGRecipeOverride.model_fields[k].default
                    if v != default_v:
                        setattr(merged_rag, k, v)

                # Merge policy override
                pol_dict = pack.policy_override.model_dump()
                for k, v in pol_dict.items():
                    default_v = PolicyOverride.model_fields[k].default
                    if v != default_v:
                        setattr(merged_policy, k, v)
            else:
                # No inheritance — leaf wins outright
                merged_dna = leaf.style_dna
                merged_rag = leaf.rag_recipe_override
                merged_policy = leaf.policy_override
                break

        return merged_dna, merged_rag, merged_policy, conflicts, nodes

    # ── Style consistency validation ──────────────────────────────────────────

    @staticmethod
    def _check_style_consistency(
        pack: PersonaPack,
        entities: list[EntityStyleEntry],
    ) -> list[ConsistencyIssue]:
        issues: list[ConsistencyIssue] = []
        expected_shading = pack.style_dna.shading_method
        expected_weight = pack.style_dna.line_style.weight

        for ent in entities:
            if ent.shading_method and ent.shading_method != expected_shading:
                issues.append(ConsistencyIssue(
                    entity_uid=ent.entity_uid,
                    field="shading_method",
                    expected=expected_shading,
                    actual=ent.shading_method,
                    severity="warn",
                ))
            if ent.line_weight > 0 and abs(ent.line_weight - expected_weight) > 0.5:
                issues.append(ConsistencyIssue(
                    entity_uid=ent.entity_uid,
                    field="line_weight",
                    expected=str(expected_weight),
                    actual=str(ent.line_weight),
                    severity="warn",
                ))
        return issues

    # ── Export ────────────────────────────────────────────────────────────────

    @staticmethod
    def _export_pack(pack: PersonaPack, fmt: str) -> ExportResult:
        dna = pack.style_dna
        manifest = pack.model_dump()

        if fmt == "json":
            return ExportResult(format="json", payload=manifest)

        if fmt == "prompt_fragment":
            fragment = (
                f"style: {dna.shading_method} shading, "
                f"line weight {dna.line_style.weight}, "
                f"palette primary={dna.color_palette.primary} "
                f"accent={dna.color_palette.accent}, "
                f"proportion head/body={dna.proportion_rules.head_body_ratio}, "
                f"motion squash_stretch={dna.motion_style.squash_stretch_factor}"
            )
            return ExportResult(
                format="prompt_fragment",
                prompt_fragment=fragment,
                payload={"prompt_fragment": fragment},
            )

        if fmt == "comfyui":
            payload = {
                "shading": dna.shading_method,
                "line_weight": dna.line_style.weight,
                "color_primary": dna.color_palette.primary,
                "color_accent": dna.color_palette.accent,
                "grain": dna.texture_profile.grain,
                "noise": dna.texture_profile.noise,
                "smoothness": dna.texture_profile.smoothness,
                "head_body_ratio": dna.proportion_rules.head_body_ratio,
                "squash_stretch": dna.motion_style.squash_stretch_factor,
            }
            return ExportResult(format="comfyui", payload=payload)

        if fmt == "lora_recipe":
            payload = {
                "base_model": "sd_xl",
                "trigger_words": [
                    dna.shading_method,
                    dna.line_style.texture,
                    f"palette_{dna.color_palette.primary}",
                ],
                "training_hints": {
                    "shading": dna.shading_method,
                    "line_texture": dna.line_style.texture,
                    "proportion_style": dna.proportion_rules.limb_style,
                },
                "recommended_weight": 0.75,
            }
            return ExportResult(format="lora_recipe", payload=payload)

        return ExportResult(
            format=fmt,
            payload={"error": f"unsupported format '{fmt}'"},
        )

    # ── Culture pack integration ──────────────────────────────────────────────

    @staticmethod
    def _apply_culture_pack(
        pack: PersonaPack,
        culture: CulturePackRef,
        warnings: list[str],
    ) -> PersonaPack:
        """Merge SKILL 07 culture-pack visual rules into style DNA."""
        if not culture.culture_pack_id:
            warnings.append("no culture_pack_id supplied; skipping import")
            return pack

        # Map constraint rules into DNA fields
        rules = culture.constraint_rules or {}

        if "shading_method" in rules:
            val = rules["shading_method"]
            if val in _SHADING_METHODS:
                pack.style_dna.shading_method = val
            else:
                warnings.append(f"culture shading_method '{val}' unknown; ignored")

        if "color_palette" in rules and isinstance(rules["color_palette"], dict):
            cp = rules["color_palette"]
            if "primary" in cp:
                pack.style_dna.color_palette.primary = cp["primary"]
            if "accent" in cp:
                pack.style_dna.color_palette.accent = cp["accent"]

        if "line_weight" in rules:
            try:
                pack.style_dna.line_style.weight = float(rules["line_weight"])
            except (TypeError, ValueError):
                warnings.append("culture line_weight not numeric; ignored")

        # Store visual traits as tags
        if culture.visual_traits:
            pack.tags = list(set(pack.tags + culture.visual_traits))

        warnings.append(
            f"imported culture pack '{culture.culture_pack_id}' "
            f"(locale={culture.locale}, era={culture.era})"
        )
        return pack

    # ── Diff utility ──────────────────────────────────────────────────────────

    @staticmethod
    def _compute_diff(
        a: dict[str, Any], b: dict[str, Any], prefix: str = "",
    ) -> dict[str, Any]:
        diff: dict[str, Any] = {}
        all_keys = set(a.keys()) | set(b.keys())
        for key in sorted(all_keys):
            path = f"{prefix}.{key}" if prefix else key
            va, vb = a.get(key), b.get(key)
            if isinstance(va, dict) and isinstance(vb, dict):
                sub = PersonaStyleService._compute_diff(va, vb, path)
                if sub:
                    diff.update(sub)
            elif va != vb:
                diff[path] = {"pack_a": va, "pack_b": vb}
        return diff
