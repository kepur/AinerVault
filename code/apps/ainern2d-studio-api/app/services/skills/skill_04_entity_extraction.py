"""SKILL 04: EntityExtractionService — 业务逻辑实现。
参考规格: SKILL_04_ENTITY_EXTRACTION_STRUCTURING.md
状态: SERVICE_READY
"""
from __future__ import annotations

import re
from collections import defaultdict
from uuid import uuid4

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_04 import (
    AliasGroup,
    AudioEventCandidate,
    EntitySceneShotLink,
    EntitySummary,
    RawEntity,
    Skill04Input,
    Skill04Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Entity signal patterns ─────────────────────────────────────────────────────
# Characters: names in 「」 / 『』 / dialogue attribution patterns
_CHAR_BRACKET_ZH = re.compile(r"[「『]([^」』]{1,20})[」』]")
_CHAR_ATTRIBUTION_ZH = re.compile(
    r"([^\s，。！？]{1,8})(?:说道|道[：:]|问道|答道|笑道|怒道|喝道|冷声道)"
)
_CHAR_PRONOUN_ZH = re.compile(r"(少侠|大侠|公子|姑娘|前辈|前辈|老者|少女|壮汉)")
_CHAR_ATTRIBUTION_EN = re.compile(
    r"([A-Z][a-z]{1,15})\s+(?:said|asked|replied|whispered|shouted)"
)

# Locations: scene-place indicators
_PLACE_ZH = re.compile(
    r"([\u4e00-\u9fff]{1,8}(?:客栈|大堂|山峰|城楼|院落|书房|密林|江边|湖畔|洞穴|庙宇|村庄|宫殿|亭台|桥上))"
)
_PLACE_EN = re.compile(
    r"\b([A-Z][a-z]+ (?:Inn|Hall|Mountain|Forest|River|Lake|Temple|Village|Palace|Bridge))\b"
)

# Props: weapons / objects
_PROP_ZH = re.compile(r"([\u4e00-\u9fff]{1,6}(?:剑|刀|枪|棍|拳|掌|令牌|玉佩|信物|暗器|毒针))")
_PROP_EN = re.compile(
    r"\b([A-Za-z]+ (?:sword|blade|dagger|staff|token|seal|amulet|poison))\b", re.I
)

# Costumes
_COSTUME_ZH = re.compile(r"([\u4e00-\u9fff]{1,6}(?:长袍|道袍|锦衣|铠甲|斗篷|头巾|发髻))")
_COSTUME_EN = re.compile(
    r"\b([A-Za-z]+ (?:robe|armor|cloak|gown|tunic|hood))\b", re.I
)

# Audio event candidates
_AUDIO_METAL_ZH = re.compile(r"金属|碰击|叮当|剑鸣|刀鸣|兵器交击")
_AUDIO_CROWD_ZH = re.compile(r"喧嚣|人声|嘈杂|叫嚷|议论纷纷")
_AUDIO_NATURE_ZH = re.compile(r"风声|雨声|雷声|鸟鸣|流水|波浪|松涛")
_AUDIO_EXPLOSION_ZH = re.compile(r"爆炸|轰鸣|巨响")

_AUDIO_PATTERNS_EN = re.compile(
    r"\b(?:clang|clash|crowd|shout|thunder|wind|rain|explosion|rumble|splashing)\b", re.I
)

_TYPE_DISPLAY: dict[str, str] = {
    "character": "characters",
    "scene_place": "scene_places",
    "prop": "props",
    "costume": "costumes",
    "audio_event_candidate": "audio_event_candidates",
}


class EntityExtractionService(BaseSkillService[Skill04Input, Skill04Output]):
    """SKILL 04 — Entity Extraction & Structuring.

    State machine:
      INIT → PRECHECKING → EXTRACTING_CANDIDATES → STRUCTURING_ENTITIES
           → MERGING_ALIASES → LINKING_TO_SCENES_SHOTS
           → READY_FOR_CANONICALIZATION | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_04"
    skill_name = "EntityExtractionService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Public entry ───────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill04Input, ctx: SkillContext) -> Skill04Output:
        warnings: list[str] = []
        review_items: list[str] = []
        lang = input_dto.primary_language or "zh-CN"

        # ── [E1] Precheck ─────────────────────────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")
        if not input_dto.segments:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError("REQ-VALIDATION-001: segments list is empty")

        # ── [E2] Candidate Extraction ─────────────────────────────────────────
        self._record_state(ctx, "PRECHECKING", "EXTRACTING_CANDIDATES")
        raw_candidates = self._extract_candidates(input_dto, lang)

        if not raw_candidates:
            warnings.append("no_entities_extracted: text may lack named entities")
            review_items.append("entity_extraction_empty")

        # ── [E3] Structuring & Typing ─────────────────────────────────────────
        self._record_state(ctx, "EXTRACTING_CANDIDATES", "STRUCTURING_ENTITIES")
        entities, audio_candidates = self._structure_entities(raw_candidates)

        # ── [E4] Alias & Duplicate Handling ───────────────────────────────────
        self._record_state(ctx, "STRUCTURING_ENTITIES", "MERGING_ALIASES")
        entities, alias_groups, dedup_count = self._merge_aliases(entities)
        if dedup_count:
            warnings.append(f"deduped_{dedup_count}_duplicate_entities")

        # ── [E5] Scene/Shot Linking ────────────────────────────────────────────
        self._record_state(ctx, "MERGING_ALIASES", "LINKING_TO_SCENES_SHOTS")
        links = self._link_to_scenes_shots(entities, input_dto)

        # ── Summary ───────────────────────────────────────────────────────────
        type_counts: dict[str, int] = defaultdict(int)
        for e in entities:
            type_counts[e.entity_type] += 1

        summary = EntitySummary(
            total_entities=len(entities),
            characters=type_counts["character"],
            scene_places=type_counts["scene_place"],
            props=type_counts["prop"],
            costumes=type_counts["costume"],
            audio_event_candidates=len(audio_candidates),
        )

        # ── Final status ──────────────────────────────────────────────────────
        needs_review = bool(review_items)
        status = "review_required" if needs_review else "ready_for_canonicalization"
        final_state = "REVIEW_REQUIRED" if needs_review else "READY_FOR_CANONICALIZATION"
        self._record_state(ctx, "LINKING_TO_SCENES_SHOTS", final_state)

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} status={status} "
            f"entities={len(entities)} aliases={len(alias_groups)} "
            f"audio_events={len(audio_candidates)}"
        )

        return Skill04Output(
            entity_summary=summary,
            entities=entities,
            entity_aliases=alias_groups,
            entity_scene_shot_links=links,
            audio_event_candidates=audio_candidates,
            warnings=warnings,
            review_required_items=review_items,
            status=status,
        )

    # ── [E2] Candidate Extraction ──────────────────────────────────────────────

    @staticmethod
    def _extract_candidates(
        input_dto: Skill04Input, lang: str
    ) -> list[dict]:
        """Extract raw surface-form candidates from segments + shot entity_hints."""
        is_zh = lang.startswith("zh")
        candidates: list[dict] = []

        def add(surface: str, etype: str, seg_id: str, confidence: float = 0.75) -> None:
            surface = surface.strip()
            if surface and len(surface) >= 2:
                candidates.append(
                    {"surface": surface, "type": etype, "seg_id": seg_id, "conf": confidence}
                )

        for seg in input_dto.segments:
            text = seg.get("text", "")
            seg_id = seg.get("segment_id", "")

            if is_zh:
                for m in _CHAR_BRACKET_ZH.finditer(text):
                    add(m.group(1), "character", seg_id, 0.85)
                for m in _CHAR_ATTRIBUTION_ZH.finditer(text):
                    add(m.group(1), "character", seg_id, 0.80)
                for m in _CHAR_PRONOUN_ZH.finditer(text):
                    add(m.group(1), "character", seg_id, 0.55)
                for m in _PLACE_ZH.finditer(text):
                    add(m.group(1), "scene_place", seg_id, 0.82)
                for m in _PROP_ZH.finditer(text):
                    add(m.group(1), "prop", seg_id, 0.78)
                for m in _COSTUME_ZH.finditer(text):
                    add(m.group(1), "costume", seg_id, 0.72)
            else:
                for m in _CHAR_ATTRIBUTION_EN.finditer(text):
                    add(m.group(1), "character", seg_id, 0.80)
                for m in _PLACE_EN.finditer(text):
                    add(m.group(1), "scene_place", seg_id, 0.82)
                for m in _PROP_EN.finditer(text):
                    add(m.group(1), "prop", seg_id, 0.75)
                for m in _COSTUME_EN.finditer(text):
                    add(m.group(1), "costume", seg_id, 0.70)

        # Supplement from shot entity_hints
        for shot in input_dto.shot_plan:
            for hint in shot.get("entity_hints", []):
                add(hint, "scene_place", shot.get("shot_id", ""), 0.60)

        return candidates

    # ── [E3] Structuring ──────────────────────────────────────────────────────

    @staticmethod
    def _structure_entities(
        candidates: list[dict],
    ) -> tuple[list[RawEntity], list[AudioEventCandidate]]:
        """Deduplicate surface forms per type and build RawEntity objects."""
        # Group by (surface, type)
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for c in candidates:
            grouped[(c["surface"], c["type"])].append(c)

        entities: list[RawEntity] = []
        audio_candidates: list[AudioEventCandidate] = []

        for (surface, etype), occurrences in grouped.items():
            if etype == "audio_event_candidate":
                audio_candidates.append(
                    AudioEventCandidate(
                        event_type=surface,
                        source_shot_id=occurrences[0].get("seg_id", ""),
                        confidence=max(c["conf"] for c in occurrences),
                    )
                )
                continue

            confidence = max(c["conf"] for c in occurrences)
            source_refs = [
                {"segment_id": c["seg_id"]}
                for c in occurrences
                if c["seg_id"]
            ][:5]

            entities.append(
                RawEntity(
                    entity_uid=f"E_{uuid4().hex[:8].upper()}",
                    surface_form=surface,
                    entity_type=etype,
                    attributes={"occurrence_count": len(occurrences)},
                    source_refs=source_refs,
                    confidence=round(confidence, 4),
                )
            )

        return entities, audio_candidates

    # ── [E4] Alias & Dedup ────────────────────────────────────────────────────

    @staticmethod
    def _merge_aliases(
        entities: list[RawEntity],
    ) -> tuple[list[RawEntity], list[AliasGroup], int]:
        """
        Merge entities with the same entity_type whose surface_forms are
        substrings of each other (likely aliases).
        """
        by_type: dict[str, list[RawEntity]] = defaultdict(list)
        for e in entities:
            by_type[e.entity_type].append(e)

        merged_ids: set[str] = set()
        kept: list[RawEntity] = []
        alias_groups: list[AliasGroup] = []
        dedup_count = 0

        for etype, group in by_type.items():
            for i, primary in enumerate(group):
                if primary.entity_uid in merged_ids:
                    continue
                cluster = [primary]
                for secondary in group[i + 1:]:
                    if secondary.entity_uid in merged_ids:
                        continue
                    # Substring match as alias signal
                    a, b = primary.surface_form, secondary.surface_form
                    if a in b or b in a:
                        cluster.append(secondary)
                        merged_ids.add(secondary.entity_uid)
                        dedup_count += 1

                kept.append(primary)
                if len(cluster) > 1:
                    alias_groups.append(
                        AliasGroup(
                            alias_group_id=f"AG_{uuid4().hex[:6].upper()}",
                            canonical_hint=primary.surface_form,
                            members=[e.surface_form for e in cluster],
                        )
                    )

        return kept, alias_groups, dedup_count

    # ── [E5] Scene/Shot Linking ────────────────────────────────────────────────

    @staticmethod
    def _link_to_scenes_shots(
        entities: list[RawEntity],
        input_dto: Skill04Input,
    ) -> list[EntitySceneShotLink]:
        """Link each entity to scenes/shots where its source segments appear."""
        # Build seg_id → scene_ids / shot_ids index from shot_plan
        seg_to_shots: dict[str, list[str]] = defaultdict(list)
        shot_to_scene: dict[str, str] = {}
        for shot in input_dto.shot_plan:
            shot_id = shot.get("shot_id", "")
            scene_id = shot.get("scene_id", "")
            shot_to_scene[shot_id] = scene_id
            for hint in shot.get("entity_hints", []):
                seg_to_shots[hint].append(shot_id)

        links: list[EntitySceneShotLink] = []
        for entity in entities:
            shot_ids: list[str] = []
            scene_ids: set[str] = set()

            for ref in entity.source_refs:
                seg_id = ref.get("segment_id", "")
                for sh_id in seg_to_shots.get(seg_id, []):
                    if sh_id not in shot_ids:
                        shot_ids.append(sh_id)
                    sc = shot_to_scene.get(sh_id, "")
                    if sc:
                        scene_ids.add(sc)

            # If no link found via shot plan, attach to first scene
            if not scene_ids and input_dto.scene_plan:
                first_scene = input_dto.scene_plan[0]
                if isinstance(first_scene, dict):
                    scene_ids.add(first_scene.get("scene_id", "SC01"))

            criticality = (
                "critical" if entity.confidence >= 0.85
                else "important" if entity.confidence >= 0.70
                else "normal"
            )

            links.append(
                EntitySceneShotLink(
                    entity_uid=entity.entity_uid,
                    scene_ids=sorted(scene_ids),
                    shot_ids=shot_ids,
                    first_appearance_shot_id=shot_ids[0] if shot_ids else "",
                    criticality=criticality,
                )
            )

        return links
