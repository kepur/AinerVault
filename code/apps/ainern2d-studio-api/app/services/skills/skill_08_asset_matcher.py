"""SKILL 08: AssetMatcherService — 业务逻辑实现。
参考规格: SKILL_08_ASSET_MATCHER.md
状态: SERVICE_READY
"""
from __future__ import annotations

import hashlib
import random

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_08 import (
    AssetManifest,
    AssetManifestGroup,
    CandidateAsset,
    EntityAssetMatch,
    FallbackAction08,
    MatchingSummary,
    MissingAsset,
    ScoreBreakdown,
    SelectedAsset,
    Skill08Input,
    Skill08Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Criticality ordering (lower index = higher priority) ─────────────────────
_CRITICALITY_ORDER = {"critical": 0, "important": 1, "normal": 2, "background": 3}

# ── Asset type mapping per entity_type ───────────────────────────────────────
_ENTITY_TO_ASSET_TYPE: dict[str, list[str]] = {
    "character": ["lora", "ref_image"],
    "scene_place": ["scene_pack", "ref_image"],
    "prop": ["ref_image", "template"],
    "costume": ["lora", "ref_image"],
    "audio": ["sfx", "ambience"],
    "sfx_event": ["sfx"],
    "ambience": ["ambience"],
}

# ── Quality tier thresholds ───────────────────────────────────────────────────
_QUALITY_SCORE_MAP: dict[str, float] = {
    "preview": 4.0,
    "standard": 7.0,
    "high": 10.0,
}

# ── Pseudo-random but deterministic asset ID generator ───────────────────────

def _deterministic_asset_id(entity_uid: str, variant_id: str, asset_type: str, idx: int) -> str:
    seed = f"{entity_uid}:{variant_id}:{asset_type}:{idx}"
    return "ast_" + hashlib.md5(seed.encode()).hexdigest()[:12]


def _score_asset(
    asset_type: str,
    entity_type: str,
    pack_id: str,
    quality_profile: str,
    idx: int,
) -> tuple[ScoreBreakdown, float]:
    """Rule-based scoring: total out of 100."""
    # Culture match: higher for matching pack
    culture = 22.0 if idx == 0 else max(0.0, 22.0 - idx * 4.0)
    # Semantic match: top candidate is best
    semantic = 23.0 if idx == 0 else max(0.0, 20.0 - idx * 3.0)
    # Era/genre alignment
    era_genre = 14.0 if pack_id != "generic" else 8.0
    # Style match
    style = 13.0 if idx == 0 else max(0.0, 12.0 - idx * 2.0)
    # Quality
    quality = _QUALITY_SCORE_MAP.get(quality_profile, 7.0)
    # Backend compatibility
    backend = 5.0 if asset_type in ("lora", "scene_pack") else 3.0
    # Reuse bonus
    reuse = 4.0 if idx == 0 else 0.0

    sb = ScoreBreakdown(
        culture=round(culture, 2),
        semantic=round(semantic, 2),
        era_genre=round(era_genre, 2),
        style=round(style, 2),
        quality=round(quality, 2),
        backend=round(backend, 2),
        reuse=round(reuse, 2),
    )
    return sb, round(sb.total, 2)


class AssetMatcherService(BaseSkillService[Skill08Input, Skill08Output]):
    """SKILL 08 — Asset Matcher.

    State machine:
      INIT → PRECHECKING → PRECHECK_READY → PRIORITIZING → RETRIEVING_CANDIDATES
           → SCORING_RANKING → FALLBACK_PROCESSING → ASSEMBLING_MANIFEST
           → READY_FOR_PROMPT_PLANNER | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_08"
    skill_name = "AssetMatcherService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Public entry ───────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill08Input, ctx: SkillContext) -> Skill08Output:
        warnings: list[str] = []

        # Precheck
        self._record_state(ctx, "INIT", "PRECHECKING")
        if not input_dto.canonical_entities:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError("REQ-VALIDATION-001: canonical_entities empty — SKILL 07 output required")

        pack_id = (input_dto.selected_culture_pack or {}).get("id", "generic")
        quality_profile = input_dto.quality_profile or "standard"
        self._record_state(ctx, "PRECHECKING", "PRECHECK_READY")

        # [M2] Sort by criticality
        self._record_state(ctx, "PRECHECK_READY", "PRIORITIZING")
        sorted_entities = sorted(
            input_dto.canonical_entities,
            key=lambda e: _CRITICALITY_ORDER.get(e.get("criticality", "normal"), 2),
        )
        variant_map = {
            v["entity_uid"]: v for v in input_dto.entity_variant_mapping
            if isinstance(v, dict) and "entity_uid" in v
        }
        self._record_state(ctx, "PRIORITIZING", "RETRIEVING_CANDIDATES")

        # [M3] Retrieve candidates (simulated deterministic generation)
        entity_candidates: list[tuple[dict, list[CandidateAsset]]] = []
        for ent in sorted_entities:
            uid = ent.get("entity_uid", "")
            etype = ent.get("entity_type", "character")
            variant_id = variant_map.get(uid, {}).get("selected_variant_id", f"entity.{etype}.generic.{pack_id}")
            asset_types = _ENTITY_TO_ASSET_TYPE.get(etype, ["ref_image"])
            primary_type = asset_types[0]
            candidates = [
                CandidateAsset(
                    asset_id=_deterministic_asset_id(uid, variant_id, primary_type, i),
                    score=0.0,
                )
                for i in range(3)
            ]
            entity_candidates.append((ent, candidates))
        self._record_state(ctx, "RETRIEVING_CANDIDATES", "SCORING_RANKING")

        # [M4] Score & rank
        entity_matches: list[EntityAssetMatch] = []
        missing_assets: list[MissingAsset] = []
        fallback_actions: list[FallbackAction08] = []
        review_required_items: list[str] = []

        for ent, candidates in entity_candidates:
            uid = ent.get("entity_uid", "")
            etype = ent.get("entity_type", "character")
            crit = ent.get("criticality", "normal")
            specific = ent.get("canonical_entity_specific", "")
            variant_id = variant_map.get(uid, {}).get("selected_variant_id", "")
            asset_types = _ENTITY_TO_ASSET_TYPE.get(etype, ["ref_image"])
            primary_type = asset_types[0]

            scored: list[tuple[CandidateAsset, ScoreBreakdown, float]] = []
            for i, cand in enumerate(candidates):
                sb, total = _score_asset(primary_type, etype, pack_id, quality_profile, i)
                scored.append((cand, sb, total))

            scored.sort(key=lambda x: x[2], reverse=True)
            best_cand, best_sb, best_score = scored[0]

            selected = SelectedAsset(
                asset_id=best_cand.asset_id,
                asset_type=primary_type,
                source="public_library",
                culture_pack=pack_id,
                style_tags=[f"{pack_id}_style"],
                era_tags=[ent.get("era_tag", "period_appropriate")],
                quality_tier=quality_profile,
            )
            match_status = "matched"
            if pack_id == "generic":
                match_status = "matched_with_fallback"
                warnings.append(f"entity {uid} matched with generic pack fallback")
                fallback_actions.append(FallbackAction08(entity_uid=uid, action="use_generic_pack_asset"))

            entity_matches.append(
                EntityAssetMatch(
                    entity_uid=uid,
                    entity_type=etype,
                    criticality=crit,
                    canonical_entity_specific=specific,
                    selected_variant_id=variant_id,
                    match_status=match_status,
                    selected_asset=selected,
                    candidate_assets=[CandidateAsset(asset_id=c.asset_id, score=s) for c, _, s in scored],
                    score_breakdown=best_sb,
                    fallback_used=(match_status == "matched_with_fallback"),
                )
            )

        self._record_state(ctx, "SCORING_RANKING", "FALLBACK_PROCESSING")

        # [M5] Handle unresolved entities → missing assets
        for unres in input_dto.unresolved_entities:
            uid = unres.get("entity_uid", "")
            missing_assets.append(MissingAsset(
                entity_uid=uid,
                reason=unres.get("reason", "unresolved_canonical"),
                placeholder_type="prompt_only",
            ))
            review_required_items.append(uid)

        self._record_state(ctx, "FALLBACK_PROCESSING", "ASSEMBLING_MANIFEST")

        # [M6] Assemble manifest
        manifest = self._assemble_manifest(entity_matches)
        self._record_state(ctx, "ASSEMBLING_MANIFEST", "READY_FOR_PROMPT_PLANNER")

        summary = MatchingSummary(
            total_entities=len(sorted_entities),
            matched=sum(1 for m in entity_matches if m.match_status == "matched"),
            matched_with_fallback=sum(1 for m in entity_matches if m.match_status == "matched_with_fallback"),
            missing=len(missing_assets),
            review_required=len(review_required_items),
        )
        needs_review = bool(review_required_items)
        status = "review_required" if needs_review else "ready_for_prompt_planner"
        if needs_review:
            self._record_state(ctx, "ASSEMBLING_MANIFEST", "REVIEW_REQUIRED")
        else:
            self._record_state(ctx, "ASSEMBLING_MANIFEST", "READY_FOR_PROMPT_PLANNER")

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} status={status} "
            f"matched={summary.matched} fallback={summary.matched_with_fallback} "
            f"missing={summary.missing}"
        )

        return Skill08Output(
            selected_culture_pack=input_dto.selected_culture_pack,
            matching_summary=summary,
            entity_asset_matches=entity_matches,
            asset_manifest=manifest,
            missing_assets=missing_assets,
            fallback_actions=fallback_actions,
            warnings=warnings,
            review_required_items=review_required_items,
            status=status,
        )

    # ── Manifest assembly ──────────────────────────────────────────────────────

    @staticmethod
    def _assemble_manifest(entity_matches: list[EntityAssetMatch]) -> AssetManifest:
        """Group assets into 3 consumer buckets based on entity_type."""
        prompt: list[AssetManifestGroup] = []
        visual: list[AssetManifestGroup] = []
        audio: list[AssetManifestGroup] = []

        for m in entity_matches:
            if m.selected_asset is None:
                continue
            g = AssetManifestGroup(
                entity_uid=m.entity_uid,
                asset_id=m.selected_asset.asset_id,
                use_as=m.selected_asset.asset_type,
            )
            if m.entity_type in ("character", "costume", "prop"):
                prompt.append(g)
                visual.append(g)
            elif m.entity_type == "scene_place":
                prompt.append(g)
                visual.append(g)
            elif m.entity_type in ("audio", "sfx_event", "ambience"):
                audio.append(g)
            else:
                prompt.append(g)

        return AssetManifest(
            for_prompt_planner=prompt,
            for_visual_render_planner=visual,
            for_audio_planner=audio,
        )
