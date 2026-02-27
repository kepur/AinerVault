"""SKILL 08: AssetMatcherService — Full implementation.

Per SKILL_08_ASSET_MATCHER.md spec with:
- 7-component scoring engine (culture/semantic/era_genre/style/quality/backend/reuse)
- 6-level fallback cascade (variant_exact → parent → era_similar → generic → placeholder → review)
- Hard filter enforcement (culture/era/genre/backend constraints)
- Conflict detection (ASSET_CULTURE_CONFLICT, ASSET_ERA_CONFLICT, etc.)
- Quality threshold enforcement per criticality level
- User preferences & project asset pack priority
- Feature flags (auto_placeholder, generic_fallback_policy, cross_culture_substitution)

State machine:
  INIT → PRECHECKING → PRECHECK_READY → PRIORITIZING → RETRIEVING_CANDIDATES
       → SCORING_RANKING → FALLBACK_PROCESSING → ASSEMBLING_MANIFEST
       → READY_FOR_PROMPT_PLANNER | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

import hashlib
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_08 import (
    AssetConflict,
    AssetManifest,
    AssetManifestGroup,
    CandidateAsset,
    ConflictType,
    CultureConstraints,
    EntityAssetMatch,
    FallbackAction08,
    FallbackLevel,
    FeatureFlags,
    MatchingSummary,
    MatchState,
    MissingAsset,
    QUALITY_THRESHOLDS,
    ReviewRequiredItem,
    SCORE_WEIGHTS,
    ScoreBreakdown,
    SelectedAsset,
    Skill08Input,
    Skill08Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Constants ─────────────────────────────────────────────────────────────────

_CRITICALITY_ORDER = {"critical": 0, "important": 1, "normal": 2, "background": 3}

_ENTITY_TO_ASSET_TYPES: dict[str, list[str]] = {
    "character": ["lora", "ref_image"],
    "scene": ["scene_pack", "ref_image"],
    "scene_place": ["scene_pack", "ref_image"],
    "prop": ["ref_image", "template"],
    "costume": ["lora", "ref_image"],
    "vehicle": ["ref_image", "template"],
    "fx": ["ref_image", "template"],
    "visual_effect": ["ref_image", "template"],
    "sfx_event": ["sfx"],
    "ambience_event": ["ambience"],
    "audio": ["sfx", "ambience"],
    "ambience": ["ambience"],
}

_QUALITY_TIER_RANK: dict[str, int] = {"preview": 1, "standard": 2, "high": 3}

_USE_AS_MAP: dict[str, str] = {
    "character": "character_reference",
    "scene": "scene_anchor",
    "scene_place": "scene_anchor",
    "prop": "prop_reference",
    "costume": "costume_reference",
    "vehicle": "vehicle_reference",
    "fx": "fx_reference",
    "visual_effect": "fx_reference",
    "sfx_event": "sfx_asset",
    "ambience_event": "ambience_asset",
    "audio": "audio_asset",
    "ambience": "ambience_asset",
}

_STYLE_FAMILIES: dict[str, list[str]] = {
    "realistic": ["cinematic", "photorealistic", "realistic"],
    "anime": ["anime", "cartoon", "2d", "cel_shaded"],
    "guochao": ["guochao", "chinese_ink", "traditional_chinese"],
    "cyber": ["cyberpunk", "neon", "sci_fi", "futuristic"],
    "cinematic": ["cinematic", "realistic", "film_grain"],
}


# ── Deterministic asset ID ────────────────────────────────────────────────────

def _make_asset_id(entity_uid: str, culture: str, asset_type: str, suffix: str) -> str:
    """Deterministic but meaningful asset ID based on entity+culture+type."""
    base = f"{asset_type}_{culture}_{entity_uid}_{suffix}"
    short_hash = hashlib.sha256(base.encode()).hexdigest()[:8]
    return f"{asset_type}_{culture}_{short_hash}"


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _tag_overlap(a: list[str], b: list[str]) -> float:
    """Jaccard-like overlap between two tag sets, 0.0 to 1.0."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    sa = {t.lower() for t in a}
    sb = {t.lower() for t in b}
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def _culture_score(candidate_culture: str, target_culture: str, cc: CultureConstraints) -> float:
    """Score culture fit (0-25)."""
    mx = SCORE_WEIGHTS["culture"]
    if candidate_culture == target_culture:
        return mx
    if candidate_culture in cc.forbidden_culture_packs:
        return 0.0
    # Partial match (same root culture, e.g. cn_wuxia vs cn_historical)
    cand_root = candidate_culture.split("_")[0] if candidate_culture else ""
    target_root = target_culture.split("_")[0] if target_culture else ""
    if cand_root and cand_root == target_root:
        return round(mx * 0.7, 2)
    if candidate_culture in ("generic", ""):
        return round(mx * 0.3, 2)
    return round(mx * 0.15, 2)


def _semantic_score(entity_tags: list[str], candidate_tags: list[str]) -> float:
    """Score semantic similarity via tag overlap (0-25)."""
    return round(SCORE_WEIGHTS["semantic"] * _tag_overlap(entity_tags, candidate_tags), 2)


def _era_genre_score(
    candidate_era: list[str],
    candidate_genre: list[str],
    target_era: str,
    target_genre: str,
    cc: CultureConstraints,
) -> float:
    """Score era/genre match (0-15)."""
    mx = SCORE_WEIGHTS["era_genre"]

    # Era scoring
    era_s = 0.5  # neutral when no target
    if target_era:
        lower_eras = [e.lower() for e in candidate_era]
        if target_era.lower() in lower_eras:
            era_s = 1.0
        elif any(e.startswith(target_era.split("_")[0]) for e in lower_eras if e):
            era_s = 0.6
        elif candidate_era:
            era_s = 0.2
    if cc.era_blacklist and any(
        e.lower() in [b.lower() for b in cc.era_blacklist] for e in candidate_era
    ):
        era_s = 0.0

    # Genre scoring
    genre_s = 0.5
    if target_genre:
        lower_genres = [g.lower() for g in candidate_genre]
        if target_genre.lower() in lower_genres:
            genre_s = 1.0
        elif candidate_genre:
            genre_s = 0.3
    if cc.genre_blacklist and any(
        g.lower() in [b.lower() for b in cc.genre_blacklist] for g in candidate_genre
    ):
        genre_s = 0.0

    return round(mx * (era_s * 0.5 + genre_s * 0.5), 2)


def _style_score(candidate_styles: list[str], target_style: str) -> float:
    """Score style coherence (0-15)."""
    mx = SCORE_WEIGHTS["style"]
    if not target_style:
        return round(mx * 0.5, 2)
    lower_styles = [s.lower() for s in candidate_styles]
    if target_style.lower() in lower_styles:
        return mx
    family = _STYLE_FAMILIES.get(target_style.lower(), [])
    if any(s in family for s in lower_styles):
        return round(mx * 0.7, 2)
    return round(mx * 0.2, 2)


def _quality_score(candidate_tier: str, target_profile: str) -> float:
    """Score quality tier match (0-10)."""
    mx = SCORE_WEIGHTS["quality"]
    cand = _QUALITY_TIER_RANK.get(candidate_tier, 2)
    target = _QUALITY_TIER_RANK.get(target_profile, 2)
    if cand >= target:
        return mx
    if cand == target - 1:
        return round(mx * 0.6, 2)
    return round(mx * 0.2, 2)


def _backend_score(candidate_backends: list[str], required_backends: list[str]) -> float:
    """Score backend compatibility (0-5)."""
    mx = SCORE_WEIGHTS["backend"]
    if not required_backends:
        return mx
    if not candidate_backends:
        return round(mx * 0.3, 2)
    matched = sum(1 for b in required_backends if b in candidate_backends)
    return round(mx * (matched / len(required_backends)), 2)


def _reuse_score(asset_id: str, project_asset_ids: set[str], is_project_pack: bool) -> float:
    """Score reuse bonus (0-5)."""
    mx = SCORE_WEIGHTS["reuse"]
    if is_project_pack:
        return mx
    if asset_id in project_asset_ids:
        return round(mx * 0.8, 2)
    return 0.0


# ── Service ───────────────────────────────────────────────────────────────────

class AssetMatcherService(BaseSkillService[Skill08Input, Skill08Output]):
    """SKILL 08 — Asset Matcher.

    Full implementation with 7-component scoring, 6-level fallback cascade,
    hard filter enforcement, conflict detection, and quality thresholds.
    """

    skill_id = "skill_08"
    skill_name = "AssetMatcherService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Public entry ──────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill08Input, ctx: SkillContext) -> Skill08Output:
        warnings: list[str] = []
        all_conflicts: list[AssetConflict] = []

        # Parse structured config from raw dicts
        ff = self._parse_feature_flags(input_dto.feature_flags)
        cc = self._parse_culture_constraints(input_dto.culture_constraints)
        pack_id = (input_dto.selected_culture_pack or {}).get("id", "generic")
        target_era = (input_dto.selected_culture_pack or {}).get("era", "")
        target_genre = (input_dto.selected_culture_pack or {}).get("genre", "")
        quality_profile = input_dto.quality_profile or "standard"
        style_mode = input_dto.style_mode or ""
        project_asset_ids = self._extract_project_asset_ids(input_dto.project_asset_pack)
        continuity_ctx = self._resolve_continuity_context(input_dto)

        # ── [M1] Precheck ────────────────────────────────────────────────────
        self._record_state(ctx, MatchState.INIT.value, MatchState.PRECHECKING.value)

        blocking = self._precheck(input_dto, cc)
        if blocking:
            self._record_state(ctx, MatchState.PRECHECKING.value, MatchState.FAILED.value)
            raise ValueError(f"REQ-VALIDATION-001: {'; '.join(blocking)}")

        self._record_state(ctx, MatchState.PRECHECKING.value, MatchState.PRECHECK_READY.value)

        # ── [M2] Entity Prioritization ───────────────────────────────────────
        self._record_state(ctx, MatchState.PRECHECK_READY.value, MatchState.PRIORITIZING.value)

        sorted_entities = sorted(
            input_dto.canonical_entities,
            key=lambda e: _CRITICALITY_ORDER.get(e.get("criticality", "normal"), 2),
        )
        variant_map: dict[str, dict[str, Any]] = {
            v["entity_uid"]: v
            for v in input_dto.entity_variant_mapping
            if isinstance(v, dict) and "entity_uid" in v
        }

        self._record_state(ctx, MatchState.PRIORITIZING.value, MatchState.RETRIEVING_CANDIDATES.value)

        # ── [M3] Candidate Retrieval ─────────────────────────────────────────
        entity_candidates: list[tuple[dict[str, Any], list[CandidateAsset]]] = []
        for ent in sorted_entities:
            variant_info = variant_map.get(ent.get("entity_uid", ""), {})
            candidates = self._retrieve_candidates(
                entity=ent,
                variant_info=variant_info,
                pack_id=pack_id,
                target_era=target_era,
                target_genre=target_genre,
                style_mode=style_mode,
                quality_profile=quality_profile,
                backend_capability=input_dto.backend_capability,
                cc=cc,
                ff=ff,
                project_asset_pack=input_dto.project_asset_pack,
                asset_library_index=input_dto.asset_library_index,
            )
            entity_candidates.append((ent, candidates))

        self._record_state(
            ctx, MatchState.RETRIEVING_CANDIDATES.value, MatchState.SCORING_RANKING.value,
        )

        # ── [M4] Scoring & Ranking ───────────────────────────────────────────
        entity_matches: list[EntityAssetMatch] = []
        missing_assets: list[MissingAsset] = []
        fallback_actions: list[FallbackAction08] = []
        review_items: list[ReviewRequiredItem] = []

        for ent, candidates in entity_candidates:
            uid = ent.get("entity_uid", "")
            etype = ent.get("entity_type", "character")
            crit = ent.get("criticality", "normal")
            specific = ent.get("canonical_entity_specific", "")
            variant_info = variant_map.get(uid, {})
            variant_id = variant_info.get("selected_variant_id", "")
            entity_tags = ent.get("visual_tags", []) or ent.get("tags", []) or []
            continuity_ref = self._match_continuity_ref(uid, variant_info, continuity_ctx)
            continuity_prompt_anchor = continuity_ctx["asset_anchor_map"].get(continuity_ref, {})
            continuity_consistency_anchor = continuity_ctx["prompt_anchor_map"].get(continuity_ref, {})
            continuity_critic_rule = continuity_ctx["critic_rule_map"].get(continuity_ref, {})
            identity_lock = bool(continuity_critic_rule.get("identity_lock", False))

            if continuity_consistency_anchor:
                entity_tags = list(entity_tags) + list(
                    continuity_consistency_anchor.get("consistency_tokens", [])
                )
            if continuity_prompt_anchor.get("anchor_prompt"):
                entity_tags.append(str(continuity_prompt_anchor["anchor_prompt"]))
            entity_tags = list(dict.fromkeys([t for t in entity_tags if t]))

            if continuity_ctx["has_data"] and not continuity_ref and crit in ("critical", "important"):
                warnings.append(f"continuity_anchor_missing:{uid}")

            # Score each candidate
            scored = self._score_candidates(
                candidates=candidates,
                entity_tags=entity_tags,
                pack_id=pack_id,
                target_era=target_era,
                target_genre=target_genre,
                style_mode=style_mode,
                quality_profile=quality_profile,
                backend_capability=input_dto.backend_capability,
                cc=cc,
                project_asset_ids=project_asset_ids,
            )
            scored = self._apply_continuity_boost(
                scored=scored,
                continuity_ref=continuity_ref,
                continuity_prompt_anchor=continuity_prompt_anchor,
                identity_lock=identity_lock,
            )

            # Apply user preferences
            scored = self._apply_user_preferences(scored, input_dto.user_preferences, etype)

            # Apply render-profile weight adjustments
            scored = self._apply_render_profile_adjustments(
                scored, input_dto.global_render_profile, crit,
            )

            threshold = QUALITY_THRESHOLDS.get(crit, 60.0)
            best = scored[0] if scored and scored[0].score >= threshold else None

            # Detect conflicts
            ent_conflicts = self._detect_conflicts(
                entity=ent, candidate=best, pack_id=pack_id,
                target_era=target_era, style_mode=style_mode,
                backend_capability=input_dto.backend_capability,
                identity_lock=identity_lock,
            )
            all_conflicts.extend(ent_conflicts)

            if best:
                match_status = "matched"
                fallback_level = ""
                fb_used = False

                if best.fallback_level != FallbackLevel.VARIANT_EXACT.value:
                    match_status = "matched_with_fallback"
                    fallback_level = best.fallback_level
                    fb_used = True
                    fallback_actions.append(FallbackAction08(
                        entity_uid=uid,
                        action=f"fallback_to_{fallback_level}",
                        fallback_level=fallback_level,
                        from_variant=variant_id,
                        to_variant=best.culture_pack,
                    ))

                # High-severity conflict on critical/important entity → review
                high_conflicts = [c for c in ent_conflicts if c.severity == "high"]
                if high_conflicts and crit in ("critical", "important"):
                    match_status = "review_required"
                    review_items.append(ReviewRequiredItem(
                        entity_uid=uid,
                        entity_type=etype,
                        criticality=crit,
                        reason=f"high_severity_conflict: {high_conflicts[0].conflict_type}",
                        suggested_action="manual_asset_review",
                    ))

                selected_asset = SelectedAsset(
                    asset_id=best.asset_id,
                    asset_type=best.asset_type,
                    source=best.source,
                    path_or_ref=best.path_or_ref or f"asset://{best.asset_id}",
                    culture_pack=best.culture_pack,
                    style_tags=best.style_tags,
                    era_tags=best.era_tags,
                    backend_compatibility=best.backend_compatibility,
                    quality_tier=best.quality_tier,
                )

                entity_matches.append(EntityAssetMatch(
                    entity_uid=uid,
                    entity_type=etype,
                    criticality=crit,
                    canonical_entity_specific=specific,
                    selected_variant_id=variant_id,
                    match_status=match_status,
                    selected_asset=selected_asset,
                    candidate_assets=scored[:5],
                    score_breakdown=best.score_breakdown,
                    fallback_used=fb_used,
                    fallback_level=fallback_level,
                    warnings=[c.description for c in ent_conflicts if c.severity != "high"],
                    conflicts=ent_conflicts,
                ))
            else:
                # No acceptable candidate
                result = self._handle_missing_entity(
                    entity=ent, variant_id=variant_id, crit=crit,
                    ff=ff, scored_candidates=scored,
                )
                entity_matches.append(result["match"])
                if result.get("missing"):
                    missing_assets.append(result["missing"])
                if result.get("fallback"):
                    fallback_actions.append(result["fallback"])
                if result.get("review"):
                    review_items.append(result["review"])

        self._record_state(
            ctx, MatchState.SCORING_RANKING.value, MatchState.FALLBACK_PROCESSING.value,
        )

        # ── [M5] Handle unresolved entities from upstream ────────────────────
        for unres in input_dto.unresolved_entities:
            uid = unres.get("entity_uid", "")
            missing_assets.append(MissingAsset(
                entity_uid=uid,
                reason=unres.get("reason", "unresolved_canonical"),
                placeholder_type="manual_asset_required",
            ))
            review_items.append(ReviewRequiredItem(
                entity_uid=uid,
                entity_type=unres.get("entity_type", ""),
                criticality=unres.get("criticality", "normal"),
                reason="unresolved_from_upstream",
                suggested_action="resolve_entity_first",
            ))

        for c in all_conflicts:
            if c.severity in ("medium", "high"):
                warnings.append(f"[{c.conflict_type}] {c.entity_uid}: {c.description}")

        self._record_state(
            ctx, MatchState.FALLBACK_PROCESSING.value, MatchState.ASSEMBLING_MANIFEST.value,
        )

        # ── [M6] Assemble manifest ───────────────────────────────────────────
        manifest = self._assemble_manifest(entity_matches)

        has_review = bool(review_items)
        status = "review_required" if has_review else "ready_for_prompt_planner"
        final_state = (
            MatchState.REVIEW_REQUIRED.value if has_review
            else MatchState.READY_FOR_PROMPT_PLANNER.value
        )
        self._record_state(ctx, MatchState.ASSEMBLING_MANIFEST.value, final_state)

        summary = MatchingSummary(
            total_entities=len(sorted_entities) + len(input_dto.unresolved_entities),
            matched=sum(1 for m in entity_matches if m.match_status == "matched"),
            matched_with_fallback=sum(
                1 for m in entity_matches if m.match_status == "matched_with_fallback"
            ),
            missing=len(missing_assets),
            review_required=len(review_items),
        )

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} status={status} "
            f"matched={summary.matched} fallback={summary.matched_with_fallback} "
            f"missing={summary.missing} review={summary.review_required}"
        )

        return Skill08Output(
            version="1.0",
            status=status,
            selected_culture_pack=input_dto.selected_culture_pack,
            matching_summary=summary,
            entity_asset_matches=entity_matches,
            asset_manifest=manifest,
            missing_assets=missing_assets,
            fallback_actions=fallback_actions,
            warnings=warnings,
            review_required_items=review_items,
        )

    # ── [M1] Precheck ────────────────────────────────────────────────────────

    @staticmethod
    def _precheck(inp: Skill08Input, cc: CultureConstraints) -> list[str]:
        """Validate preconditions. Returns list of blocking issues."""
        issues: list[str] = []
        if not inp.canonical_entities:
            issues.append("canonical_entities empty — SKILL 07 output required")
        for conflict in inp.conflicts:
            if conflict.get("severity") == "high" and conflict.get("blocking", False):
                issues.append(
                    f"upstream_blocking_conflict: {conflict.get('conflict_type', 'unknown')}"
                )
        return issues

    # ── Config parsing helpers ────────────────────────────────────────────────

    @staticmethod
    def _parse_feature_flags(raw: dict[str, Any]) -> FeatureFlags:
        if not raw:
            return FeatureFlags()
        return FeatureFlags(
            auto_placeholder=raw.get("auto_placeholder", True),
            generic_fallback_policy=raw.get("generic_fallback_policy", "allowed"),
            cross_culture_substitution=raw.get("cross_culture_substitution", False),
        )

    @staticmethod
    def _parse_culture_constraints(raw: dict[str, Any]) -> CultureConstraints:
        if not raw:
            return CultureConstraints()
        return CultureConstraints(
            required_culture_packs=raw.get("required_culture_packs", []),
            forbidden_culture_packs=raw.get("forbidden_culture_packs", []),
            era_whitelist=raw.get("era_whitelist", []),
            era_blacklist=raw.get("era_blacklist", []),
            genre_whitelist=raw.get("genre_whitelist", []),
            genre_blacklist=raw.get("genre_blacklist", []),
        )

    @staticmethod
    def _extract_project_asset_ids(project_pack: dict[str, Any]) -> set[str]:
        if not project_pack:
            return set()
        assets = project_pack.get("assets", [])
        return {a.get("asset_id", "") for a in assets if isinstance(a, dict)}

    @staticmethod
    def _resolve_continuity_context(input_dto: Skill08Input) -> dict[str, Any]:
        continuity_exports = input_dto.continuity_exports or {}
        continuity_result = input_dto.entity_registry_continuity_result or {}
        if not continuity_exports and isinstance(continuity_result, dict):
            continuity_exports = dict(continuity_result.get("continuity_exports", {}))

        prompt_anchor_map: dict[str, dict[str, Any]] = {}
        asset_anchor_map: dict[str, dict[str, Any]] = {}
        critic_rule_map: dict[str, dict[str, Any]] = {}
        for item in continuity_exports.get("prompt_consistency_anchors", []):
            if isinstance(item, dict) and item.get("entity_id"):
                prompt_anchor_map[str(item["entity_id"])] = item
        for item in continuity_exports.get("asset_matcher_anchors", []):
            if isinstance(item, dict) and item.get("entity_id"):
                asset_anchor_map[str(item["entity_id"])] = item
        for item in continuity_exports.get("critic_rules_baseline", []):
            if isinstance(item, dict) and item.get("entity_id"):
                critic_rule_map[str(item["entity_id"])] = item

        return {
            "prompt_anchor_map": prompt_anchor_map,
            "asset_anchor_map": asset_anchor_map,
            "critic_rule_map": critic_rule_map,
            "has_data": bool(prompt_anchor_map or asset_anchor_map or critic_rule_map),
        }

    @staticmethod
    def _match_continuity_ref(
        entity_uid: str,
        variant_info: dict[str, Any],
        continuity_ctx: dict[str, Any],
    ) -> str:
        if not continuity_ctx["has_data"]:
            return ""
        candidates = [
            entity_uid,
            str(variant_info.get("entity_id") or ""),
            str(variant_info.get("canonical_entity_id") or ""),
            str(variant_info.get("matched_entity_id") or ""),
            str(variant_info.get("source_entity_uid") or ""),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            if (
                candidate in continuity_ctx["asset_anchor_map"]
                or candidate in continuity_ctx["prompt_anchor_map"]
                or candidate in continuity_ctx["critic_rule_map"]
            ):
                return candidate
        return ""

    # ── [M3] Candidate Retrieval (6-level fallback cascade) ───────────────────

    def _retrieve_candidates(
        self,
        entity: dict[str, Any],
        variant_info: dict[str, Any],
        pack_id: str,
        target_era: str,
        target_genre: str,
        style_mode: str,
        quality_profile: str,
        backend_capability: list[str],
        cc: CultureConstraints,
        ff: FeatureFlags,
        project_asset_pack: dict[str, Any],
        asset_library_index: dict[str, Any],
    ) -> list[CandidateAsset]:
        """Generate candidates through the 6-level fallback cascade with hard filters."""
        uid = str(entity.get("entity_uid", ""))
        etype = str(entity.get("entity_type", "character"))
        specific = str(entity.get("canonical_entity_specific", ""))
        root = str(entity.get("canonical_entity_root", ""))
        crit = str(entity.get("criticality", "normal"))
        variant_id = str(variant_info.get("selected_variant_id", ""))
        entity_tags = entity.get("visual_tags", []) or entity.get("tags", []) or []
        asset_types = _ENTITY_TO_ASSET_TYPES.get(etype, ["ref_image"])
        primary_type = asset_types[0]
        index_assets = self._extract_index_assets(asset_library_index)

        all_cands: list[CandidateAsset] = []
        seen_asset_ids: set[str] = set()

        def _append_if_valid(candidate: CandidateAsset, target_culture: str) -> None:
            if not candidate.asset_id or candidate.asset_id in seen_asset_ids:
                return
            if self._passes_hard_filters(candidate, target_culture, cc, backend_capability):
                all_cands.append(candidate)
                seen_asset_ids.add(candidate.asset_id)

        # Level 0: Project asset pack (highest priority)
        if project_asset_pack:
            for pa in project_asset_pack.get("assets", []):
                if not isinstance(pa, dict):
                    continue
                if pa.get("entity_type", "") == etype or pa.get("entity_uid") == uid:
                    cand = self._asset_dict_to_candidate(
                        pa,
                        FallbackLevel.VARIANT_EXACT.value,
                        primary_type,
                        source="project_pack",
                    )
                    _append_if_valid(cand, pack_id)

        # Level 1: asset_library_index variant_exact
        if variant_id and index_assets:
            for asset in index_assets:
                if not self._index_asset_matches_entity(asset, uid, etype, variant_info):
                    continue
                asset_variant = str(
                    asset.get("selected_variant_id") or asset.get("variant_id") or ""
                ).strip()
                if asset_variant != variant_id:
                    continue
                cand = self._asset_dict_to_candidate(
                    asset,
                    FallbackLevel.VARIANT_EXACT.value,
                    primary_type,
                    source="asset_library_index",
                )
                _append_if_valid(cand, pack_id)

        # Level 1: variant_exact — exact variant from culture pack
        if variant_id:
            for c in self._generate_variant_candidates(
                uid, variant_id, pack_id, entity_tags, primary_type,
                target_era, target_genre, style_mode, quality_profile,
                FallbackLevel.VARIANT_EXACT.value, count=3,
            ):
                _append_if_valid(c, pack_id)

        # Level 2: asset_library_index canonical specific
        if len(all_cands) < 2 and specific and index_assets:
            for asset in index_assets:
                if not self._index_asset_matches_entity(asset, uid, etype, variant_info):
                    continue
                asset_specific = str(
                    asset.get("canonical_entity_specific")
                    or asset.get("canonical_entity_id")
                    or ""
                ).strip()
                if not asset_specific:
                    continue
                if asset_specific != specific and not asset_specific.startswith(f"{specific}."):
                    continue
                cand = self._asset_dict_to_candidate(
                    asset,
                    FallbackLevel.VARIANT_PARENT.value,
                    primary_type,
                    source="asset_library_index",
                )
                _append_if_valid(cand, pack_id)

        # Level 2: variant_same_pack_parent (synthetic fallback)
        if len(all_cands) < 2 and specific:
            parent = ".".join(specific.split(".")[:-1]) if "." in specific else specific
            for c in self._generate_variant_candidates(
                uid, f"{parent}.{pack_id}", pack_id, entity_tags, primary_type,
                target_era, target_genre, style_mode, quality_profile,
                FallbackLevel.VARIANT_PARENT.value, count=2,
            ):
                _append_if_valid(c, pack_id)

        # Level 3: asset_library_index canonical root / era-genre similar
        if len(all_cands) < 2 and index_assets:
            for asset in index_assets:
                if not self._index_asset_matches_entity(asset, uid, etype, variant_info):
                    continue
                asset_root = str(asset.get("canonical_entity_root") or "").strip()
                if root and asset_root != root:
                    continue
                cand = self._asset_dict_to_candidate(
                    asset,
                    FallbackLevel.ERA_SIMILAR.value,
                    primary_type,
                    source="asset_library_index",
                )
                _append_if_valid(cand, pack_id)

        # Level 3: variant_similar_era_genre (synthetic fallback)
        if len(all_cands) < 2:
            pack_root = pack_id.split("_")[0] if pack_id else "generic"
            similar_pack = f"{pack_root}_historical"
            trimmed_tags = entity_tags[: max(1, len(entity_tags) // 2)]
            tier = "standard" if quality_profile == "high" else quality_profile
            for c in self._generate_variant_candidates(
                uid, f"entity.{etype}.era_similar.{similar_pack}", similar_pack,
                trimmed_tags, primary_type, target_era, target_genre, style_mode,
                tier, FallbackLevel.ERA_SIMILAR.value, count=2,
            ):
                _append_if_valid(c, pack_id)

        # Level 4: generic_culturally_safe
        if len(all_cands) < 1 and ff.generic_fallback_policy != "disabled":
            if crit != "critical" or ff.generic_fallback_policy == "allowed":
                for c in self._generate_generic_candidates(uid, etype, entity_tags, primary_type):
                    _append_if_valid(c, "generic")

        # Level 5: placeholder_to_generate
        if len(all_cands) < 1 and ff.auto_placeholder:
            all_cands.append(self._generate_placeholder(uid, etype, primary_type))

        return all_cands

    # ── Candidate generators ──────────────────────────────────────────────────

    @staticmethod
    def _generate_variant_candidates(
        uid: str, variant_id: str, pack_id: str, entity_tags: list[str],
        primary_type: str, era: str, genre: str, style_mode: str,
        quality_profile: str, level: str, count: int = 3,
    ) -> list[CandidateAsset]:
        """Generate deterministic candidates for a variant with meaningful traits."""
        candidates: list[CandidateAsset] = []
        for i in range(count):
            asset_id = _make_asset_id(uid, pack_id, primary_type, f"v{i}")
            style_tags = [style_mode] if style_mode else ["realistic"]
            era_tags = [era] if era else ["period_appropriate"]
            genre_tags = [genre] if genre else []
            # Lower-ranked candidates get degraded quality
            tier = quality_profile
            if i == 1 and quality_profile == "high":
                tier = "standard"
            elif i >= 2:
                tier = "preview" if quality_profile != "preview" else quality_profile
            # Reduce tag overlap for lower candidates
            vtags = list(entity_tags)
            if i > 0:
                vtags = vtags[: max(1, len(vtags) - i)]
            compat = (
                ["comfyui", "sdxl", "prompt_only"]
                if primary_type in ("lora", "scene_pack")
                else ["prompt_only", "prompt_ref"]
            )
            candidates.append(CandidateAsset(
                asset_id=asset_id,
                asset_type=primary_type,
                source="public_library",
                path_or_ref=f"asset://{asset_id}",
                culture_pack=pack_id,
                style_tags=style_tags,
                era_tags=era_tags,
                genre_tags=genre_tags,
                visual_tags=vtags,
                backend_compatibility=compat,
                quality_tier=tier,
                fallback_level=level,
            ))
        return candidates

    @staticmethod
    def _generate_generic_candidates(
        uid: str, etype: str, entity_tags: list[str], primary_type: str,
    ) -> list[CandidateAsset]:
        """Generate generic culturally-safe candidates."""
        asset_id = _make_asset_id(uid, "generic", primary_type, "g0")
        return [CandidateAsset(
            asset_id=asset_id,
            asset_type=primary_type,
            source="public_library",
            path_or_ref=f"asset://{asset_id}",
            culture_pack="generic",
            style_tags=["neutral"],
            era_tags=["universal"],
            genre_tags=[],
            visual_tags=entity_tags[:2] if entity_tags else [],
            backend_compatibility=["prompt_only"],
            quality_tier="standard",
            fallback_level=FallbackLevel.GENERIC.value,
        )]

    @staticmethod
    def _generate_placeholder(uid: str, etype: str, primary_type: str) -> CandidateAsset:
        """Generate a placeholder candidate."""
        asset_id = f"placeholder_{etype}_{uid}".replace(".", "_")
        return CandidateAsset(
            asset_id=asset_id,
            asset_type="placeholder",
            source="generated_placeholder",
            culture_pack="",
            backend_compatibility=["prompt_only"],
            quality_tier="preview",
            fallback_level=FallbackLevel.PLACEHOLDER.value,
        )

    @staticmethod
    def _extract_index_assets(asset_library_index: dict[str, Any]) -> list[dict[str, Any]]:
        if not asset_library_index:
            return []
        raw_assets: Any = asset_library_index
        if isinstance(asset_library_index, dict):
            raw_assets = []
            for key in ("assets", "items", "entries", "index"):
                if isinstance(asset_library_index.get(key), list):
                    raw_assets = asset_library_index.get(key, [])
                    break
        if not isinstance(raw_assets, list):
            return []
        return [item for item in raw_assets if isinstance(item, dict)]

    @staticmethod
    def _index_asset_matches_entity(
        asset: dict[str, Any],
        entity_uid: str,
        entity_type: str,
        variant_info: dict[str, Any],
    ) -> bool:
        refs = {
            entity_uid,
            str(variant_info.get("entity_id") or ""),
            str(variant_info.get("canonical_entity_id") or ""),
            str(variant_info.get("matched_entity_id") or ""),
            str(variant_info.get("source_entity_uid") or ""),
        }
        refs.discard("")

        asset_uid = str(asset.get("entity_uid") or asset.get("source_entity_uid") or "")
        asset_entity_id = str(asset.get("entity_id") or asset.get("canonical_entity_id") or "")
        if asset_uid and asset_uid in refs:
            return True
        if asset_entity_id and asset_entity_id in refs:
            return True

        asset_type = str(asset.get("entity_type") or "")
        if asset_type and asset_type == entity_type:
            if any(asset.get(key) for key in (
                "selected_variant_id",
                "variant_id",
                "canonical_entity_specific",
                "canonical_entity_root",
            )):
                return True

        return False

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value if str(v)]
        if isinstance(value, str):
            return [value] if value else []
        return []

    @staticmethod
    def _asset_dict_to_candidate(
        asset: dict[str, Any],
        fallback_level: str,
        default_type: str,
        source: str = "project_pack",
    ) -> CandidateAsset:
        """Convert a raw asset dict to CandidateAsset."""
        asset_id = str(asset.get("asset_id") or asset.get("id") or "").strip()
        asset_ref = str(
            asset.get("path_or_ref")
            or asset.get("asset_ref")
            or asset.get("uri")
            or asset.get("path")
            or ""
        ).strip()
        return CandidateAsset(
            asset_id=asset_id,
            asset_type=str(asset.get("asset_type") or asset.get("type") or default_type),
            source=source,
            path_or_ref=asset_ref,
            culture_pack=str(asset.get("culture_pack") or asset.get("culture") or ""),
            style_tags=AssetMatcherService._as_list(
                asset.get("style_tags") or asset.get("styles")
            ),
            era_tags=AssetMatcherService._as_list(
                asset.get("era_tags") or asset.get("era")
            ),
            genre_tags=AssetMatcherService._as_list(
                asset.get("genre_tags") or asset.get("genres")
            ),
            visual_tags=AssetMatcherService._as_list(
                asset.get("visual_tags") or asset.get("tags")
            ),
            backend_compatibility=AssetMatcherService._as_list(
                asset.get("backend_compatibility")
                or asset.get("supported_backends")
            ) or ["prompt_only"],
            quality_tier=str(asset.get("quality_tier") or asset.get("quality") or "standard"),
            fallback_level=fallback_level,
        )

    # ── Hard Filters ──────────────────────────────────────────────────────────

    @staticmethod
    def _passes_hard_filters(
        candidate: CandidateAsset,
        target_culture: str,
        cc: CultureConstraints,
        backend_capability: list[str],
    ) -> bool:
        """Apply hard filters per §8.1: culture, era, genre, backend constraints."""
        if candidate.culture_pack in cc.forbidden_culture_packs:
            return False
        if cc.required_culture_packs:
            if (
                candidate.culture_pack not in cc.required_culture_packs
                and candidate.culture_pack != target_culture
                and candidate.culture_pack not in ("generic", "")
            ):
                return False
        if cc.era_blacklist and any(
            e.lower() in [b.lower() for b in cc.era_blacklist] for e in candidate.era_tags
        ):
            return False
        if cc.genre_blacklist and any(
            g.lower() in [b.lower() for b in cc.genre_blacklist] for g in candidate.genre_tags
        ):
            return False
        # Backend: at least one overlap (prompt_only always acceptable)
        if backend_capability and candidate.backend_compatibility:
            if not (
                set(candidate.backend_compatibility)
                & (set(backend_capability) | {"prompt_only"})
            ):
                return False
        return True

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_candidates(
        self,
        candidates: list[CandidateAsset],
        entity_tags: list[str],
        pack_id: str,
        target_era: str,
        target_genre: str,
        style_mode: str,
        quality_profile: str,
        backend_capability: list[str],
        cc: CultureConstraints,
        project_asset_ids: set[str],
    ) -> list[CandidateAsset]:
        """Score all candidates and return sorted descending by total score."""
        scored: list[CandidateAsset] = []
        for cand in candidates:
            sb = ScoreBreakdown(
                culture=_culture_score(cand.culture_pack, pack_id, cc),
                semantic=_semantic_score(entity_tags, cand.visual_tags),
                era_genre=_era_genre_score(
                    cand.era_tags, cand.genre_tags, target_era, target_genre, cc,
                ),
                style=_style_score(cand.style_tags, style_mode),
                quality=_quality_score(cand.quality_tier, quality_profile),
                backend=_backend_score(cand.backend_compatibility, backend_capability),
                reuse=_reuse_score(
                    cand.asset_id, project_asset_ids,
                    is_project_pack=(cand.source == "project_pack"),
                ),
            )
            scored.append(cand.model_copy(update={
                "score": sb.total,
                "score_breakdown": sb,
            }))
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored

    @staticmethod
    def _apply_continuity_boost(
        scored: list[CandidateAsset],
        continuity_ref: str,
        continuity_prompt_anchor: dict[str, Any],
        identity_lock: bool,
    ) -> list[CandidateAsset]:
        if not scored or not continuity_ref:
            return scored

        boosted: list[CandidateAsset] = []
        anchor_text = str(continuity_prompt_anchor.get("anchor_prompt") or "").lower()
        for cand in scored:
            extra_semantic = 0.0
            extra_reuse = 0.0
            if anchor_text and any(anchor_text in str(t).lower() for t in cand.visual_tags):
                extra_semantic = 1.5
            if identity_lock and cand.source == "project_pack":
                extra_reuse = 2.0
            if extra_semantic or extra_reuse:
                new_sb = cand.score_breakdown.model_copy(
                    update={
                        "semantic": round(
                            min(SCORE_WEIGHTS["semantic"], cand.score_breakdown.semantic + extra_semantic),
                            2,
                        ),
                        "reuse": round(
                            min(SCORE_WEIGHTS["reuse"], cand.score_breakdown.reuse + extra_reuse),
                            2,
                        ),
                    }
                )
                cand = cand.model_copy(update={"score": new_sb.total, "score_breakdown": new_sb})
            boosted.append(cand)

        boosted.sort(key=lambda c: c.score, reverse=True)
        return boosted

    # ── User Preferences ──────────────────────────────────────────────────────

    @staticmethod
    def _apply_user_preferences(
        scored: list[CandidateAsset],
        user_prefs: dict[str, Any],
        entity_type: str,
    ) -> list[CandidateAsset]:
        """Boost candidates matching user preferences, then re-sort."""
        if not user_prefs or not scored:
            return scored

        preferred_sources = user_prefs.get("preferred_sources", [])
        preferred_styles = user_prefs.get("preferred_styles", [])
        preferred_quality = user_prefs.get("preferred_quality", "")
        boost = float(user_prefs.get("preference_boost", 5.0))

        result: list[CandidateAsset] = []
        for cand in scored:
            extra = 0.0
            if preferred_sources and cand.source in preferred_sources:
                extra += boost * 0.4
            if preferred_styles:
                if set(s.lower() for s in preferred_styles) & set(s.lower() for s in cand.style_tags):
                    extra += boost * 0.4
            if preferred_quality and cand.quality_tier == preferred_quality:
                extra += boost * 0.2
            if extra > 0:
                new_reuse = min(cand.score_breakdown.reuse + extra, SCORE_WEIGHTS["reuse"])
                new_sb = cand.score_breakdown.model_copy(update={"reuse": round(new_reuse, 2)})
                cand = cand.model_copy(update={
                    "score": new_sb.total,
                    "score_breakdown": new_sb,
                })
            result.append(cand)

        result.sort(key=lambda c: c.score, reverse=True)
        return result

    # ── Render Profile Adjustments (§16.2, §16.3) ────────────────────────────

    @staticmethod
    def _apply_render_profile_adjustments(
        scored: list[CandidateAsset],
        render_profile: str,
        criticality: str,
    ) -> list[CandidateAsset]:
        """Adjust weights based on global_render_profile."""
        if render_profile == "LOW_LOAD":
            # Boost reuse weight for background entities to reduce generation
            if criticality in ("normal", "background"):
                result: list[CandidateAsset] = []
                for c in scored:
                    bonus = min(c.score_breakdown.reuse + 2.0, SCORE_WEIGHTS["reuse"])
                    sb = c.score_breakdown.model_copy(update={"reuse": round(bonus, 2)})
                    result.append(c.model_copy(update={
                        "score": sb.total,
                        "score_breakdown": sb,
                    }))
                result.sort(key=lambda x: x.score, reverse=True)
                return result
        elif render_profile == "HIGH_LOAD":
            # Boost quality weight for critical entities
            if criticality in ("critical", "important"):
                result = []
                for c in scored:
                    bonus = min(c.score_breakdown.quality + 2.0, SCORE_WEIGHTS["quality"])
                    sb = c.score_breakdown.model_copy(update={"quality": round(bonus, 2)})
                    result.append(c.model_copy(update={
                        "score": sb.total,
                        "score_breakdown": sb,
                    }))
                result.sort(key=lambda x: x.score, reverse=True)
                return result
        return scored

    # ── Conflict Detection (§10) ──────────────────────────────────────────────

    @staticmethod
    def _detect_conflicts(
        entity: dict[str, Any],
        candidate: CandidateAsset | None,
        pack_id: str,
        target_era: str,
        style_mode: str,
        backend_capability: list[str],
        identity_lock: bool = False,
    ) -> list[AssetConflict]:
        """Detect conflicts between selected candidate and entity requirements."""
        if candidate is None:
            return []

        uid = entity.get("entity_uid", "")
        etype = entity.get("entity_type", "")
        crit = entity.get("criticality", "normal")
        conflicts: list[AssetConflict] = []

        severity_for_crit = (
            "high" if crit == "critical"
            else ("medium" if crit == "important" else "low")
        )

        # Culture conflict
        if candidate.culture_pack and candidate.culture_pack != pack_id:
            cand_root = candidate.culture_pack.split("_")[0]
            target_root = pack_id.split("_")[0] if pack_id else ""
            if cand_root != target_root:
                conflicts.append(AssetConflict(
                    conflict_type=ConflictType.ASSET_CULTURE_CONFLICT.value,
                    entity_uid=uid,
                    severity=severity_for_crit,
                    description=(
                        f"candidate culture '{candidate.culture_pack}' "
                        f"differs from target '{pack_id}'"
                    ),
                    asset_id=candidate.asset_id,
                ))

        # Era conflict
        if target_era and candidate.era_tags:
            lower_eras = [e.lower() for e in candidate.era_tags]
            if target_era.lower() not in lower_eras:
                has_related = any(
                    e.startswith(target_era.split("_")[0]) for e in lower_eras if e
                )
                if not has_related:
                    conflicts.append(AssetConflict(
                        conflict_type=ConflictType.ASSET_ERA_CONFLICT.value,
                        entity_uid=uid,
                        severity="medium" if crit in ("critical", "important") else "low",
                        description=(
                            f"candidate era {candidate.era_tags} "
                            f"does not match target '{target_era}'"
                        ),
                        asset_id=candidate.asset_id,
                    ))

        # Style conflict
        if style_mode and candidate.style_tags:
            if style_mode.lower() not in [s.lower() for s in candidate.style_tags]:
                conflicts.append(AssetConflict(
                    conflict_type=ConflictType.ASSET_STYLE_CONFLICT.value,
                    entity_uid=uid,
                    severity="low",
                    description=(
                        f"candidate styles {candidate.style_tags} "
                        f"do not include '{style_mode}'"
                    ),
                    asset_id=candidate.asset_id,
                ))

        # Backend incompatibility
        if backend_capability and candidate.backend_compatibility:
            if not (set(candidate.backend_compatibility) & set(backend_capability)):
                conflicts.append(AssetConflict(
                    conflict_type=ConflictType.ASSET_BACKEND_INCOMPATIBLE.value,
                    entity_uid=uid,
                    severity="high",
                    description=(
                        f"no backend overlap: candidate={candidate.backend_compatibility} "
                        f"required={backend_capability}"
                    ),
                    asset_id=candidate.asset_id,
                ))

        # Quality below threshold for critical entities
        cand_rank = _QUALITY_TIER_RANK.get(candidate.quality_tier, 2)
        if crit == "critical" and cand_rank < 2:
            conflicts.append(AssetConflict(
                conflict_type=ConflictType.ASSET_QUALITY_BELOW_THRESHOLD.value,
                entity_uid=uid,
                severity="medium",
                description=(
                    f"quality_tier '{candidate.quality_tier}' "
                    f"below expected for critical entity"
                ),
                asset_id=candidate.asset_id,
            ))

        # Character consistency risk
        if etype == "character" and candidate.source != "project_pack":
            severity = "high" if identity_lock else "low"
            description = (
                "identity lock enabled but character asset not from project_pack"
                if identity_lock
                else "character not from project_pack; cross-shot consistency may vary"
            )
            conflicts.append(AssetConflict(
                conflict_type=ConflictType.CHARACTER_CONSISTENCY_RISK.value,
                entity_uid=uid,
                severity=severity,
                description=description,
                asset_id=candidate.asset_id,
            ))

        return conflicts

    # ── Handle Missing Entity (§11) ───────────────────────────────────────────

    @staticmethod
    def _handle_missing_entity(
        entity: dict[str, Any],
        variant_id: str,
        crit: str,
        ff: FeatureFlags,
        scored_candidates: list[CandidateAsset],
    ) -> dict[str, Any]:
        """Handle entity with no acceptable candidate above threshold."""
        uid = entity.get("entity_uid", "")
        etype = entity.get("entity_type", "")
        specific = entity.get("canonical_entity_specific", "")
        result: dict[str, Any] = {}

        best = scored_candidates[0] if scored_candidates else None

        if crit == "critical":
            # Critical: must go to review, no generic fallback
            result["match"] = EntityAssetMatch(
                entity_uid=uid,
                entity_type=etype,
                criticality=crit,
                canonical_entity_specific=specific,
                selected_variant_id=variant_id,
                match_status="review_required",
                candidate_assets=scored_candidates[:3],
                score_breakdown=best.score_breakdown if best else ScoreBreakdown(),
                fallback_level=FallbackLevel.REVIEW.value,
                warnings=["no_candidate_above_threshold_for_critical_entity"],
            )
            result["review"] = ReviewRequiredItem(
                entity_uid=uid,
                entity_type=etype,
                criticality=crit,
                reason="no_acceptable_candidate",
                suggested_action="manual_asset_curation",
            )
            result["missing"] = MissingAsset(
                entity_uid=uid,
                reason="no_candidate_above_critical_threshold",
                placeholder_type="reference_needed",
            )
        elif ff.auto_placeholder:
            placeholder_id = f"placeholder_{etype}_{uid}".replace(".", "_")
            result["match"] = EntityAssetMatch(
                entity_uid=uid,
                entity_type=etype,
                criticality=crit,
                canonical_entity_specific=specific,
                selected_variant_id=variant_id,
                match_status="missing",
                selected_asset=SelectedAsset(
                    asset_id=placeholder_id,
                    asset_type="placeholder",
                    source="generated_placeholder",
                    quality_tier="preview",
                ),
                candidate_assets=scored_candidates[:3],
                score_breakdown=ScoreBreakdown(),
                fallback_used=True,
                fallback_level=FallbackLevel.PLACEHOLDER.value,
                warnings=["auto_placeholder_generated"],
            )
            result["missing"] = MissingAsset(
                entity_uid=uid,
                reason="no_candidate_above_threshold",
                placeholder_type="prompt_only",
            )
            result["fallback"] = FallbackAction08(
                entity_uid=uid,
                action="auto_placeholder_generated",
                fallback_level=FallbackLevel.PLACEHOLDER.value,
            )
        else:
            result["match"] = EntityAssetMatch(
                entity_uid=uid,
                entity_type=etype,
                criticality=crit,
                canonical_entity_specific=specific,
                selected_variant_id=variant_id,
                match_status="missing",
                candidate_assets=scored_candidates[:3],
                score_breakdown=ScoreBreakdown(),
                warnings=["no_acceptable_candidate_and_placeholder_disabled"],
            )
            result["missing"] = MissingAsset(
                entity_uid=uid,
                reason="no_candidate_and_placeholder_disabled",
                placeholder_type="manual_asset_required",
            )

        return result

    # ── [M6] Manifest Assembly ────────────────────────────────────────────────

    @staticmethod
    def _assemble_manifest(entity_matches: list[EntityAssetMatch]) -> AssetManifest:
        """Group assets into consumer buckets per §14.4."""
        prompt: list[AssetManifestGroup] = []
        visual: list[AssetManifestGroup] = []
        audio: list[AssetManifestGroup] = []
        consistency: list[AssetManifestGroup] = []

        for m in entity_matches:
            if m.selected_asset is None:
                continue
            use_as = _USE_AS_MAP.get(m.entity_type, m.selected_asset.asset_type)
            g = AssetManifestGroup(
                entity_uid=m.entity_uid,
                asset_id=m.selected_asset.asset_id,
                use_as=use_as,
            )
            if m.entity_type in ("sfx_event", "ambience_event", "audio", "ambience"):
                audio.append(g)
            else:
                prompt.append(g)
                visual.append(g)
            if m.entity_type in ("character", "costume"):
                consistency.append(g)

        return AssetManifest(
            for_prompt_planner=prompt,
            for_visual_render_planner=visual,
            for_audio_planner=audio,
            for_consistency_checker=consistency,
        )
