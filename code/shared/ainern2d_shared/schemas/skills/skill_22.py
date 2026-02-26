"""SKILL 22: Persona Dataset & Index Manager — Input/Output DTOs.

Spec: SKILL_22_PERSONA_DATASET_INDEX_MANAGER.md
"""
from __future__ import annotations

from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


class Skill22FeatureFlags(BaseSchema):
    enable_persona_lineage: bool = True
    enable_dataset_branching: bool = True
    enable_preview_retrieval: bool = True
    enable_multi_index_persona: bool = True


class DatasetItem(BaseSchema):
    dataset_id: str
    name: str = ""
    role: str = "primary"
    tags: list[str] = []
    metadata: dict[str, Any] = {}


class IndexItem(BaseSchema):
    index_id: str
    kb_version_id: str = ""
    dataset_ids: list[str] = []
    retrieval_policy: dict[str, Any] = {}


class PersonaItem(BaseSchema):
    persona_id: str
    persona_version: str = "1.0"
    dataset_ids: list[str] = []
    index_ids: list[str] = []
    style_pack_ref: str = ""
    policy_override_ref: str = ""
    critic_profile_ref: str = ""
    metadata: dict[str, Any] = {}


class PersonaLineageOp(BaseSchema):
    source_persona_ref: str
    target_persona_ref: str
    edge_type: str = "upgrade"
    reason: str = ""


class LineageEdge(BaseSchema):
    from_ref: str
    to_ref: str
    edge_type: str = "upgrade"
    reason: str = ""


class LineageGraph(BaseSchema):
    nodes: list[str] = []
    edges: list[LineageEdge] = []


class PreviewRetrievalHit(BaseSchema):
    persona_ref: str
    dataset_id: str = ""
    index_id: str = ""
    score: float = 0.0
    reason: str = ""


class PreviewRetrievalPlan(BaseSchema):
    query: str = ""
    top_k: int = 5
    hits: list[PreviewRetrievalHit] = []
    effective_style_refs: list[str] = []
    effective_policy_refs: list[str] = []


class PersonaRuntimeManifestOut(BaseSchema):
    persona_ref: str
    resolved_dataset_ids: list[str] = []
    resolved_index_ids: list[str] = []
    style_pack_ref: str = ""
    policy_override_ref: str = ""
    critic_profile_ref: str = ""
    runtime_manifest: dict[str, Any] = {}


class Skill22Input(BaseSchema):
    """SKILL 22 input DTO."""

    datasets: list[DatasetItem] = []
    indexes: list[IndexItem] = []
    personas: list[PersonaItem] = []
    lineage_operations: list[PersonaLineageOp] = []
    preview_query: str = ""
    preview_top_k: int = 5
    rag_kb_manager_result: dict[str, Any] = {}
    rag_embedding_result: dict[str, Any] = {}
    persona_style_result: dict[str, Any] = {}
    existing_lineage_graph: LineageGraph = LineageGraph()
    feature_flags: Skill22FeatureFlags = Skill22FeatureFlags()


class Skill22Output(BaseSchema):
    """SKILL 22 output DTO."""

    version: str = "1.0"
    status: str = "persona_index_ready"
    datasets: list[DatasetItem] = []
    indexes: list[IndexItem] = []
    personas: list[PersonaItem] = []
    runtime_manifests: list[PersonaRuntimeManifestOut] = []
    lineage_graph: LineageGraph = LineageGraph()
    preview_retrieval_plan: PreviewRetrievalPlan = PreviewRetrievalPlan()
    warnings: list[str] = []
    review_required_items: list[str] = []
