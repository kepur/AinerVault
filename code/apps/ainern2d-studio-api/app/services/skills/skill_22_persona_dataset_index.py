"""SKILL 22: Persona Dataset & Index Manager — service skeleton.

Spec: SKILL_22_PERSONA_DATASET_INDEX_MANAGER.md
Status: SERVICE_READY (skeleton)
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.governance_models import PersonaPackVersion
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun
from ainern2d_shared.ainer_db_models.preview_models import (
    PersonaDatasetBinding,
    PersonaIndexBinding,
    PersonaLineageEdge,
    PersonaRuntimeManifest,
)
from ainern2d_shared.ainer_db_models.rag_models import KbVersion, RagCollection
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
        persisted = self._persist_outputs(
            ctx=ctx,
            input_dto=input_dto,
            personas=personas,
            runtime_manifests=runtime_manifests,
            lineage_graph=lineage_graph,
            dataset_map=dataset_map,
            index_map=index_map,
            preview_plan=preview_plan,
            warnings=warnings,
            review_required_items=review_required_items,
        )

        status = "review_required" if review_required_items else "persona_index_ready"
        terminal_state = "REVIEW_REQUIRED" if review_required_items else "READY_FOR_PROMPT_POLICY_CONSUMPTION"
        self._record_state(ctx, "PREVIEW_PLANNING", terminal_state)
        logger.info(
            f"[{self.skill_id}] run={ctx.run_id} "
            f"datasets={len(dataset_map)} indexes={len(index_map)} "
            f"personas={len(personas)} status={status} "
            f"persisted(ds={persisted['dataset_bindings']},idx={persisted['index_bindings']},"
            f"lineage={persisted['lineage_edges']},manifest={persisted['runtime_manifests']})"
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

    def _persist_outputs(
        self,
        ctx: SkillContext,
        input_dto: Skill22Input,
        personas: list[PersonaItem],
        runtime_manifests: list[PersonaRuntimeManifestOut],
        lineage_graph: LineageGraph,
        dataset_map: dict[str, DatasetItem],
        index_map: dict[str, IndexItem],
        preview_plan: PreviewRetrievalPlan,
        warnings: list[str],
        review_required_items: list[str],
    ) -> dict[str, int]:
        persisted = {
            "dataset_bindings": 0,
            "index_bindings": 0,
            "lineage_edges": 0,
            "runtime_manifests": 0,
        }

        try:
            run_exists = self._id_exists(RenderRun, ctx.run_id)
            if not run_exists:
                warnings.append(f"runtime_manifest_skip_run_not_found:{ctx.run_id}")
                review_required_items.append(f"run_not_found:{ctx.run_id}")

            persona_ref_to_version_id: dict[str, str] = {}
            for persona in personas:
                persona_ref = f"{persona.persona_id}@{persona.persona_version}"
                persona_version_id = self._resolve_persona_pack_version_id(persona)
                if not persona_version_id:
                    warnings.append(f"persona_version_missing:{persona_ref}")
                    review_required_items.append(f"persona_version_missing:{persona_ref}")
                    continue
                persona_ref_to_version_id[persona_ref] = persona_version_id

                for dataset_id in persona.dataset_ids:
                    if not self._id_exists(RagCollection, dataset_id):
                        warnings.append(f"dataset_binding_skip_collection_missing:{dataset_id}")
                        review_required_items.append(f"collection_missing:{dataset_id}")
                        continue

                    dataset = dataset_map.get(dataset_id)
                    binding_role = dataset.role if dataset else "primary"
                    weight = 1.0
                    if dataset:
                        try:
                            weight = float((dataset.metadata or {}).get("weight", 1.0))
                        except Exception:
                            weight = 1.0

                    existing_ds = self._find_dataset_binding(
                        ctx=ctx,
                        persona_pack_version_id=persona_version_id,
                        collection_id=dataset_id,
                    )
                    if existing_ds:
                        existing_ds.binding_role = binding_role
                        existing_ds.weight = weight
                        existing_ds.meta_json = {"source": self.skill_id}
                    else:
                        self.db.add(
                            PersonaDatasetBinding(
                                id=f"PDSB_{uuid4().hex[:16].upper()}",
                                tenant_id=ctx.tenant_id,
                                project_id=ctx.project_id,
                                trace_id=ctx.trace_id,
                                correlation_id=ctx.correlation_id,
                                idempotency_key=f"{ctx.idempotency_key}:pdsb:{persona_version_id}:{dataset_id}",
                                persona_pack_version_id=persona_version_id,
                                collection_id=dataset_id,
                                binding_role=binding_role,
                                weight=weight,
                                meta_json={"source": self.skill_id},
                            )
                        )
                    persisted["dataset_bindings"] += 1

                for index_id in persona.index_ids:
                    kb_version_id = self._resolve_kb_version_id(index_id, index_map)
                    if not kb_version_id:
                        warnings.append(f"index_binding_skip_kb_missing:{index_id}")
                        review_required_items.append(f"kb_version_missing:{index_id}")
                        continue

                    index_item = index_map.get(index_id)
                    priority = 100
                    if index_item:
                        try:
                            priority = int((index_item.retrieval_policy or {}).get("priority", 100))
                        except Exception:
                            priority = 100

                    existing_idx = self._find_index_binding(
                        ctx=ctx,
                        persona_pack_version_id=persona_version_id,
                        kb_version_id=kb_version_id,
                    )
                    if existing_idx:
                        existing_idx.priority = priority
                        existing_idx.retrieval_policy_json = dict(index_item.retrieval_policy) if index_item else {}
                    else:
                        self.db.add(
                            PersonaIndexBinding(
                                id=f"PIB_{uuid4().hex[:16].upper()}",
                                tenant_id=ctx.tenant_id,
                                project_id=ctx.project_id,
                                trace_id=ctx.trace_id,
                                correlation_id=ctx.correlation_id,
                                idempotency_key=f"{ctx.idempotency_key}:pib:{persona_version_id}:{kb_version_id}",
                                persona_pack_version_id=persona_version_id,
                                kb_version_id=kb_version_id,
                                priority=priority,
                                retrieval_policy_json=dict(index_item.retrieval_policy) if index_item else {},
                            )
                        )
                    persisted["index_bindings"] += 1

            # lineage edges
            for edge in lineage_graph.edges:
                source_id = persona_ref_to_version_id.get(edge.from_ref)
                target_id = persona_ref_to_version_id.get(edge.to_ref)
                if not source_id and self._id_exists(PersonaPackVersion, edge.from_ref):
                    source_id = edge.from_ref
                if not target_id and self._id_exists(PersonaPackVersion, edge.to_ref):
                    target_id = edge.to_ref
                if not source_id or not target_id:
                    warnings.append(f"lineage_skip_unresolved_ref:{edge.from_ref}->{edge.to_ref}")
                    continue

                existing_edge = self._find_lineage_edge(
                    ctx=ctx,
                    source_persona_pack_version_id=source_id,
                    target_persona_pack_version_id=target_id,
                    edge_type=edge.edge_type,
                )
                if existing_edge:
                    existing_edge.reason = edge.reason
                    existing_edge.meta_json = {"source": self.skill_id}
                else:
                    self.db.add(
                        PersonaLineageEdge(
                            id=f"PLE_{uuid4().hex[:16].upper()}",
                            tenant_id=ctx.tenant_id,
                            project_id=ctx.project_id,
                            trace_id=ctx.trace_id,
                            correlation_id=ctx.correlation_id,
                            idempotency_key=f"{ctx.idempotency_key}:ple:{source_id}:{target_id}:{edge.edge_type}",
                            source_persona_pack_version_id=source_id,
                            target_persona_pack_version_id=target_id,
                            edge_type=edge.edge_type,
                            reason=edge.reason,
                            meta_json={"source": self.skill_id},
                        )
                    )
                persisted["lineage_edges"] += 1

            # runtime manifests (per run + persona)
            if run_exists:
                hit_map: dict[str, list[dict[str, Any]]] = {}
                for hit in preview_plan.hits:
                    hit_map.setdefault(hit.persona_ref, []).append(hit.model_dump(mode="json"))

                for manifest in runtime_manifests:
                    persona_version_id = persona_ref_to_version_id.get(manifest.persona_ref)
                    if not persona_version_id and self._id_exists(PersonaPackVersion, manifest.persona_ref):
                        persona_version_id = manifest.persona_ref

                    existing_manifest = None
                    if persona_version_id:
                        existing_manifest = self._find_runtime_manifest(
                            ctx=ctx,
                            run_id=ctx.run_id,
                            persona_pack_version_id=persona_version_id,
                        )

                    if existing_manifest:
                        existing_manifest.resolved_dataset_ids_json = list(manifest.resolved_dataset_ids)
                        existing_manifest.resolved_index_ids_json = list(manifest.resolved_index_ids)
                        existing_manifest.runtime_manifest_json = dict(manifest.runtime_manifest)
                        existing_manifest.preview_query = input_dto.preview_query
                        existing_manifest.preview_topk = max(1, input_dto.preview_top_k)
                        existing_manifest.preview_result_json = {
                            "hits": hit_map.get(manifest.persona_ref, []),
                        }
                    else:
                        self.db.add(
                            PersonaRuntimeManifest(
                                id=f"PRM_{uuid4().hex[:16].upper()}",
                                tenant_id=ctx.tenant_id,
                                project_id=ctx.project_id,
                                trace_id=ctx.trace_id,
                                correlation_id=ctx.correlation_id,
                                idempotency_key=f"{ctx.idempotency_key}:prm:{manifest.persona_ref}",
                                run_id=ctx.run_id,
                                persona_pack_version_id=persona_version_id,
                                resolved_dataset_ids_json=list(manifest.resolved_dataset_ids),
                                resolved_index_ids_json=list(manifest.resolved_index_ids),
                                runtime_manifest_json=dict(manifest.runtime_manifest),
                                preview_query=input_dto.preview_query,
                                preview_topk=max(1, input_dto.preview_top_k),
                                preview_result_json={"hits": hit_map.get(manifest.persona_ref, [])},
                            )
                        )
                    persisted["runtime_manifests"] += 1

            self.db.flush()
            return persisted
        except Exception as exc:
            self.db.rollback()
            warnings.append(f"persistence_failed:{type(exc).__name__}")
            review_required_items.append("persistence_failed")
            logger.warning(f"[{self.skill_id}] persistence failed: {exc}")
            return {k: 0 for k in persisted}

    def _resolve_persona_pack_version_id(self, persona: PersonaItem) -> str:
        meta = persona.metadata or {}
        candidates = [
            str(meta.get("persona_pack_version_id") or ""),
            str(meta.get("persona_pack_version_ref") or ""),
            persona.persona_id,
        ]
        for cid in candidates:
            if cid and self._id_exists(PersonaPackVersion, cid):
                return cid
        return ""

    def _resolve_kb_version_id(self, index_id: str, index_map: dict[str, IndexItem]) -> str:
        index_item = index_map.get(index_id)
        candidates = [
            str(index_item.kb_version_id if index_item else ""),
            index_id,
        ]
        for cid in candidates:
            if cid and self._id_exists(KbVersion, cid):
                return cid
        return ""

    def _find_dataset_binding(
        self,
        ctx: SkillContext,
        persona_pack_version_id: str,
        collection_id: str,
    ) -> PersonaDatasetBinding | None:
        return self._first_model(
            select(PersonaDatasetBinding).where(
                PersonaDatasetBinding.tenant_id == ctx.tenant_id,
                PersonaDatasetBinding.project_id == ctx.project_id,
                PersonaDatasetBinding.persona_pack_version_id == persona_pack_version_id,
                PersonaDatasetBinding.collection_id == collection_id,
                PersonaDatasetBinding.deleted_at.is_(None),
            ),
            PersonaDatasetBinding,
        )

    def _find_index_binding(
        self,
        ctx: SkillContext,
        persona_pack_version_id: str,
        kb_version_id: str,
    ) -> PersonaIndexBinding | None:
        return self._first_model(
            select(PersonaIndexBinding).where(
                PersonaIndexBinding.tenant_id == ctx.tenant_id,
                PersonaIndexBinding.project_id == ctx.project_id,
                PersonaIndexBinding.persona_pack_version_id == persona_pack_version_id,
                PersonaIndexBinding.kb_version_id == kb_version_id,
                PersonaIndexBinding.deleted_at.is_(None),
            ),
            PersonaIndexBinding,
        )

    def _find_lineage_edge(
        self,
        ctx: SkillContext,
        source_persona_pack_version_id: str,
        target_persona_pack_version_id: str,
        edge_type: str,
    ) -> PersonaLineageEdge | None:
        return self._first_model(
            select(PersonaLineageEdge).where(
                PersonaLineageEdge.tenant_id == ctx.tenant_id,
                PersonaLineageEdge.project_id == ctx.project_id,
                PersonaLineageEdge.source_persona_pack_version_id == source_persona_pack_version_id,
                PersonaLineageEdge.target_persona_pack_version_id == target_persona_pack_version_id,
                PersonaLineageEdge.edge_type == edge_type,
                PersonaLineageEdge.deleted_at.is_(None),
            ),
            PersonaLineageEdge,
        )

    def _find_runtime_manifest(
        self,
        ctx: SkillContext,
        run_id: str,
        persona_pack_version_id: str,
    ) -> PersonaRuntimeManifest | None:
        return self._first_model(
            select(PersonaRuntimeManifest).where(
                PersonaRuntimeManifest.tenant_id == ctx.tenant_id,
                PersonaRuntimeManifest.project_id == ctx.project_id,
                PersonaRuntimeManifest.run_id == run_id,
                PersonaRuntimeManifest.persona_pack_version_id == persona_pack_version_id,
                PersonaRuntimeManifest.deleted_at.is_(None),
            ),
            PersonaRuntimeManifest,
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
        style_result = input_dto.persona_style_result or {}
        default_style = str(style_result.get("style_pack_ref") or "")
        default_policy = str(style_result.get("policy_override_ref") or "")
        default_critic = str(style_result.get("critic_profile_ref") or "")
        default_pack_version_ref = str(style_result.get("persona_pack_version_ref") or "")

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
            effective_policy_ref = persona.policy_override_ref or default_policy
            effective_critic_ref = persona.critic_profile_ref or default_critic
            persona_meta = dict(persona.metadata or {})
            if (
                default_pack_version_ref
                and not persona_meta.get("persona_pack_version_ref")
                and not persona_meta.get("persona_pack_version_id")
            ):
                persona_meta["persona_pack_version_ref"] = default_pack_version_ref

            if not effective_style_ref:
                review_required_items.append(f"persona_style_missing:{persona.persona_id}")

            persona_out = PersonaItem(
                persona_id=persona.persona_id,
                persona_version=persona.persona_version,
                dataset_ids=resolved_dataset_ids,
                index_ids=resolved_index_ids,
                style_pack_ref=effective_style_ref,
                policy_override_ref=effective_policy_ref,
                critic_profile_ref=effective_critic_ref,
                metadata=persona_meta,
            )
            personas_out.append(persona_out)

            persona_ref = f"{persona_out.persona_id}@{persona_out.persona_version}"
            manifests_out.append(
                PersonaRuntimeManifestOut(
                    persona_ref=persona_ref,
                    resolved_dataset_ids=resolved_dataset_ids,
                    resolved_index_ids=resolved_index_ids,
                    style_pack_ref=effective_style_ref,
                    policy_override_ref=effective_policy_ref,
                    critic_profile_ref=effective_critic_ref,
                    runtime_manifest={
                        "manifest_id": f"PRM_{uuid4().hex[:10].upper()}",
                        "persona_ref": persona_ref,
                        "dataset_ids": resolved_dataset_ids,
                        "index_ids": resolved_index_ids,
                        "style_pack_ref": effective_style_ref,
                        "policy_override_ref": effective_policy_ref,
                        "critic_profile_ref": effective_critic_ref,
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
