"""SKILL 22: Persona Dataset & Index Manager — service skeleton.

Spec: SKILL_22_PERSONA_DATASET_INDEX_MANAGER.md
Status: SERVICE_READY (skeleton)
"""
from __future__ import annotations

from uuid import uuid4

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_22 import (
    DatasetItem,
    IndexItem,
    LineageEdge,
    LineageGraph,
    PersonaItem,
    PersonaRuntimeManifestOut,
    PreviewRetrievalHit,
    PreviewRetrievalPlan,
    Skill22Input,
    Skill22Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext


class PersonaDatasetIndexService(BaseSkillService[Skill22Input, Skill22Output]):
    """SKILL 22 — assemble dataset/index/persona lineage runtime manifests."""

    skill_id = "skill_22"
    skill_name = "PersonaDatasetIndexService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill22Input, ctx: SkillContext) -> Skill22Output:
        warnings: list[str] = []
        review_required_items: list[str] = []

        self._record_state(ctx, "INIT", "PRECHECKING")
        if not input_dto.personas:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError("REQ-VALIDATION-022: personas is empty")

        self._record_state(ctx, "PRECHECKING", "DATASET_MANAGEMENT")
        dataset_map = self._resolve_datasets(input_dto)
        if not dataset_map:
            warnings.append("datasets_empty: no dataset provided or derived")
            review_required_items.append("datasets_empty")

        self._record_state(ctx, "DATASET_MANAGEMENT", "INDEX_BINDING")
        index_map = self._resolve_indexes(input_dto, dataset_map)
        if not index_map:
            warnings.append("indexes_empty: no index provided or derived")
            review_required_items.append("indexes_empty")

        self._record_state(ctx, "INDEX_BINDING", "PERSONA_ASSEMBLY")
        personas, runtime_manifests = self._assemble_personas(
            input_dto=input_dto,
            dataset_map=dataset_map,
            index_map=index_map,
            warnings=warnings,
            review_required_items=review_required_items,
        )

        self._record_state(ctx, "PERSONA_ASSEMBLY", "LINEAGE_UPDATE")
        lineage_graph = self._build_lineage_graph(input_dto, personas)

        self._record_state(ctx, "LINEAGE_UPDATE", "PREVIEW_PLANNING")
        preview_plan = self._build_preview_plan(
            input_dto=input_dto,
            personas=personas,
            dataset_map=dataset_map,
            index_map=index_map,
        )

        status = "review_required" if review_required_items else "persona_index_ready"
        terminal_state = "REVIEW_REQUIRED" if review_required_items else "READY_FOR_PROMPT_POLICY_CONSUMPTION"
        self._record_state(ctx, "PREVIEW_PLANNING", terminal_state)
        logger.info(
            f"[{self.skill_id}] run={ctx.run_id} "
            f"datasets={len(dataset_map)} indexes={len(index_map)} "
            f"personas={len(personas)} status={status}"
        )

        return Skill22Output(
            status=status,
            datasets=list(dataset_map.values()),
            indexes=list(index_map.values()),
            personas=personas,
            runtime_manifests=runtime_manifests,
            lineage_graph=lineage_graph,
            preview_retrieval_plan=preview_plan,
            warnings=warnings,
            review_required_items=sorted(set(review_required_items)),
        )

    @staticmethod
    def _resolve_datasets(input_dto: Skill22Input) -> dict[str, DatasetItem]:
        dataset_map: dict[str, DatasetItem] = {d.dataset_id: d for d in input_dto.datasets}

        # Derive fallback datasets from upstream KB manager output if present.
        kb_result = input_dto.rag_kb_manager_result or {}
        for idx, entry in enumerate(kb_result.get("collections", []), start=1):
            dataset_id = str(entry.get("dataset_id") or entry.get("collection_id") or f"DS_AUTO_{idx:03d}")
            if dataset_id in dataset_map:
                continue
            dataset_map[dataset_id] = DatasetItem(
                dataset_id=dataset_id,
                name=str(entry.get("name") or entry.get("collection_name") or dataset_id),
                role="derived",
                tags=list(entry.get("tags") or ["auto"]),
                metadata={"source": "skill_11"},
            )
        return dataset_map

    @staticmethod
    def _resolve_indexes(input_dto: Skill22Input, dataset_map: dict[str, DatasetItem]) -> dict[str, IndexItem]:
        index_map: dict[str, IndexItem] = {i.index_id: i for i in input_dto.indexes}

        # Derive fallback indexes from embedding result if present.
        emb_result = input_dto.rag_embedding_result or {}
        for idx, entry in enumerate(emb_result.get("indexes", []), start=1):
            index_id = str(entry.get("index_id") or entry.get("id") or f"IDX_AUTO_{idx:03d}")
            if index_id in index_map:
                continue
            dataset_ids = [d for d in entry.get("dataset_ids", []) if d in dataset_map]
            index_map[index_id] = IndexItem(
                index_id=index_id,
                kb_version_id=str(entry.get("kb_version_id") or ""),
                dataset_ids=dataset_ids,
                retrieval_policy=dict(entry.get("retrieval_policy") or {}),
            )
        return index_map

    @staticmethod
    def _assemble_personas(
        input_dto: Skill22Input,
        dataset_map: dict[str, DatasetItem],
        index_map: dict[str, IndexItem],
        warnings: list[str],
        review_required_items: list[str],
    ) -> tuple[list[PersonaItem], list[PersonaRuntimeManifestOut]]:
        personas_out: list[PersonaItem] = []
        manifests_out: list[PersonaRuntimeManifestOut] = []

        default_style = str((input_dto.persona_style_result or {}).get("style_pack_ref") or "")

        for persona in input_dto.personas:
            resolved_dataset_ids = [d for d in persona.dataset_ids if d in dataset_map]
            resolved_index_ids = [i for i in persona.index_ids if i in index_map]

            if persona.dataset_ids and len(resolved_dataset_ids) != len(persona.dataset_ids):
                warnings.append(f"persona_dataset_missing:{persona.persona_id}")
                review_required_items.append(f"persona_dataset_missing:{persona.persona_id}")
            if persona.index_ids and len(resolved_index_ids) != len(persona.index_ids):
                warnings.append(f"persona_index_missing:{persona.persona_id}")
                review_required_items.append(f"persona_index_missing:{persona.persona_id}")

            if not resolved_dataset_ids and dataset_map:
                resolved_dataset_ids = [next(iter(dataset_map.keys()))]
                warnings.append(f"persona_dataset_defaulted:{persona.persona_id}")
            if not resolved_index_ids and index_map:
                resolved_index_ids = [next(iter(index_map.keys()))]
                warnings.append(f"persona_index_defaulted:{persona.persona_id}")

            # Keep output persona aligned to resolved refs for downstream consumption.
            effective_style_ref = persona.style_pack_ref or default_style
            if not effective_style_ref:
                review_required_items.append(f"persona_style_missing:{persona.persona_id}")

            persona_out = PersonaItem(
                persona_id=persona.persona_id,
                persona_version=persona.persona_version,
                dataset_ids=resolved_dataset_ids,
                index_ids=resolved_index_ids,
                style_pack_ref=effective_style_ref,
                policy_override_ref=persona.policy_override_ref,
                critic_profile_ref=persona.critic_profile_ref,
                metadata=persona.metadata,
            )
            personas_out.append(persona_out)

            persona_ref = f"{persona_out.persona_id}@{persona_out.persona_version}"
            manifests_out.append(
                PersonaRuntimeManifestOut(
                    persona_ref=persona_ref,
                    resolved_dataset_ids=resolved_dataset_ids,
                    resolved_index_ids=resolved_index_ids,
                    style_pack_ref=effective_style_ref,
                    policy_override_ref=persona_out.policy_override_ref,
                    critic_profile_ref=persona_out.critic_profile_ref,
                    runtime_manifest={
                        "manifest_id": f"PRM_{uuid4().hex[:10].upper()}",
                        "persona_ref": persona_ref,
                        "dataset_ids": resolved_dataset_ids,
                        "index_ids": resolved_index_ids,
                        "style_pack_ref": effective_style_ref,
                        "policy_override_ref": persona_out.policy_override_ref,
                        "critic_profile_ref": persona_out.critic_profile_ref,
                    },
                )
            )

        return personas_out, manifests_out

    @staticmethod
    def _build_lineage_graph(input_dto: Skill22Input, personas: list[PersonaItem]) -> LineageGraph:
        nodes = set(input_dto.existing_lineage_graph.nodes)
        edges: list[LineageEdge] = list(input_dto.existing_lineage_graph.edges)

        for persona in personas:
            nodes.add(f"{persona.persona_id}@{persona.persona_version}")

        if input_dto.feature_flags.enable_persona_lineage:
            for op in input_dto.lineage_operations:
                edges.append(
                    LineageEdge(
                        from_ref=op.source_persona_ref,
                        to_ref=op.target_persona_ref,
                        edge_type=op.edge_type,
                        reason=op.reason,
                    )
                )
                nodes.add(op.source_persona_ref)
                nodes.add(op.target_persona_ref)

        # Deduplicate edges.
        seen_edges: set[tuple[str, str, str]] = set()
        deduped_edges: list[LineageEdge] = []
        for edge in edges:
            key = (edge.from_ref, edge.to_ref, edge.edge_type)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            deduped_edges.append(edge)

        return LineageGraph(nodes=sorted(nodes), edges=deduped_edges)

    @staticmethod
    def _build_preview_plan(
        input_dto: Skill22Input,
        personas: list[PersonaItem],
        dataset_map: dict[str, DatasetItem],
        index_map: dict[str, IndexItem],
    ) -> PreviewRetrievalPlan:
        if not input_dto.feature_flags.enable_preview_retrieval:
            return PreviewRetrievalPlan(
                query=input_dto.preview_query,
                top_k=max(1, input_dto.preview_top_k),
                hits=[],
                effective_style_refs=[p.style_pack_ref for p in personas if p.style_pack_ref],
                effective_policy_refs=[p.policy_override_ref for p in personas if p.policy_override_ref],
            )

        top_k = max(1, input_dto.preview_top_k)
        hits: list[PreviewRetrievalHit] = []
        for persona in personas:
            persona_ref = f"{persona.persona_id}@{persona.persona_version}"
            for dataset_id in persona.dataset_ids[:top_k]:
                index_id = persona.index_ids[0] if persona.index_ids else ""
                if dataset_id not in dataset_map:
                    continue
                if index_id and index_id not in index_map:
                    index_id = ""
                score = 0.9 if input_dto.preview_query else 0.7
                hits.append(
                    PreviewRetrievalHit(
                        persona_ref=persona_ref,
                        dataset_id=dataset_id,
                        index_id=index_id,
                        score=score,
                        reason="preview_match_by_persona_binding",
                    )
                )

        return PreviewRetrievalPlan(
            query=input_dto.preview_query,
            top_k=top_k,
            hits=hits[:top_k],
            effective_style_refs=[p.style_pack_ref for p in personas if p.style_pack_ref],
            effective_policy_refs=[p.policy_override_ref for p in personas if p.policy_override_ref],
        )
