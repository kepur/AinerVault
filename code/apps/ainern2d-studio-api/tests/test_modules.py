"""Unit tests for studio-api modules: model_router, entity core, asset-knowledge."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = MagicMock()
    db.add.return_value = None
    db.flush.return_value = None
    db.commit.return_value = None
    return db


def _make_profile(
    id: str = "prof_1",
    purpose: str = "worker-llm",
    provider_id: str = "prov_1",
    params_json: dict | None = None,
):
    from ainern2d_shared.ainer_db_models.provider_models import ModelProfile
    p = MagicMock(spec=ModelProfile)
    p.id = id
    p.purpose = purpose
    p.provider_id = provider_id
    p.params_json = params_json or {}
    return p


def _make_provider(id: str = "prov_1", endpoint: str = "http://localhost:8000"):
    from ainern2d_shared.ainer_db_models.provider_models import ModelProvider
    prov = MagicMock(spec=ModelProvider)
    prov.id = id
    prov.endpoint = endpoint
    return prov


def _make_task_spec(budget_profile: str = "balanced", cost: float = 0.0):
    from ainern2d_shared.schemas.task import TaskSpec
    ts = MagicMock(spec=TaskSpec)
    ts.task_id = "task_001"
    ts.budget_profile = budget_profile
    ts.deadline_ms = 30_000
    ts.user_overrides = {}
    return ts


# ===========================================================================
# model_router / router.py – _rank() scoring
# ===========================================================================

class TestModelRouterRank:
    def test_premium_prefers_high_quality(self):
        from app.modules.model_router.router import ModelRouter

        cheap = _make_profile("cheap", params_json={"quality_score": 3.0, "cost_per_1k_tokens": 0.001, "latency_ms": 500})
        premium = _make_profile("premium", params_json={"quality_score": 9.0, "cost_per_1k_tokens": 0.05, "latency_ms": 2000})

        task = _make_task_spec(budget_profile="premium")
        ranked = ModelRouter._rank([cheap, premium], task)
        assert ranked[0].id == "premium", "premium budget should prefer high quality"

    def test_economy_prefers_low_cost(self):
        from app.modules.model_router.router import ModelRouter

        cheap = _make_profile("cheap", params_json={"quality_score": 3.0, "cost_per_1k_tokens": 0.001, "latency_ms": 500})
        expensive = _make_profile("expensive", params_json={"quality_score": 9.0, "cost_per_1k_tokens": 0.09, "latency_ms": 2000})

        task = _make_task_spec(budget_profile="economy")
        ranked = ModelRouter._rank([expensive, cheap], task)
        assert ranked[0].id == "cheap", "economy budget should prefer cheap"

    def test_balanced_mix(self):
        from app.modules.model_router.router import ModelRouter

        a = _make_profile("a", params_json={"quality_score": 7.0, "cost_per_1k_tokens": 0.01, "latency_ms": 1000})
        b = _make_profile("b", params_json={"quality_score": 5.0, "cost_per_1k_tokens": 0.001, "latency_ms": 500})

        task = _make_task_spec(budget_profile="balanced")
        ranked = ModelRouter._rank([a, b], task)
        # Both should appear in output
        assert len(ranked) == 2

    def test_empty_profiles_returns_empty(self):
        from app.modules.model_router.router import ModelRouter
        assert ModelRouter._rank([], _make_task_spec()) == []

    def test_missing_params_json_defaults_gracefully(self):
        from app.modules.model_router.router import ModelRouter
        prof = _make_profile("x", params_json=None)
        ranked = ModelRouter._rank([prof], _make_task_spec())
        assert ranked[0].id == "x"


# ===========================================================================
# model_router / provider_registry.py
# ===========================================================================

class TestProviderRegistry:
    def test_list_profiles_filters_by_purpose(self):
        from app.modules.model_router.provider_registry import ProviderRegistry

        db = _mock_db()
        llm = _make_profile("p1", purpose="worker-llm")
        vid = _make_profile("p2", purpose="worker-video")
        db.query.return_value.filter.return_value.all.return_value = [llm]

        reg = ProviderRegistry(db)
        result = reg.list_profiles("worker-llm")
        assert result == [llm]

    def test_get_endpoint_returns_none_for_unknown_profile(self):
        from app.modules.model_router.provider_registry import ProviderRegistry
        db = _mock_db()
        db.get.return_value = None
        reg = ProviderRegistry(db)
        assert reg.get_endpoint("nonexistent") is None

    def test_check_health_returns_false_for_missing_provider(self):
        from app.modules.model_router.provider_registry import ProviderRegistry
        db = _mock_db()
        db.get.return_value = None
        reg = ProviderRegistry(db)
        assert reg.check_health("bad_profile") is False

    def test_check_health_probes_endpoint(self):
        from app.modules.model_router.provider_registry import ProviderRegistry

        db = _mock_db()
        profile = _make_profile("p1", provider_id="prov1")
        provider = _make_provider("prov1", endpoint="http://example.com")
        db.get.side_effect = lambda model, id: profile if id == "p1" else provider

        reg = ProviderRegistry(db)
        with patch("app.modules.model_router.provider_registry.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client_cls.return_value.__enter__.return_value.head.return_value = mock_resp
            assert reg.check_health("p1") is True


# ===========================================================================
# model_router / dispath_decision.py – audit()
# ===========================================================================

class TestDispatchDecisionAuditor:
    def _make_decision(self, cost: float = 0.01, worker_type: str = "worker-llm"):
        from ainern2d_shared.schemas.task import DispatchDecision
        d = MagicMock(spec=DispatchDecision)
        d.task_id = "task_x"
        d.cost_estimate = cost
        d.worker_type = worker_type
        d.model_profile_id = "prof_1"
        d.route_id = "rt_abc"
        d.fallback_chain = []
        return d

    def _make_stack(self, name: str, stack_json: dict):
        from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
        s = MagicMock(spec=CreativePolicyStack)
        s.name = name
        s.status = "active"
        s.stack_json = stack_json
        return s

    def test_passes_when_no_active_stacks(self):
        from app.modules.model_router.dispath_decision import DispatchDecisionAuditor
        from ainern2d_shared.ainer_db_models.enum_models import GateDecision

        db = _mock_db()
        db.query.return_value.filter.return_value.all.return_value = []
        auditor = DispatchDecisionAuditor(db)
        result = auditor.audit(self._make_decision())
        assert result.gate_decision == GateDecision.pass_

    def test_rejects_when_cost_ceiling_exceeded(self):
        from app.modules.model_router.dispath_decision import DispatchDecisionAuditor
        from ainern2d_shared.ainer_db_models.enum_models import GateDecision

        db = _mock_db()
        stack = self._make_stack("budget_policy", {"cost_ceiling": 0.005})
        db.query.return_value.filter.return_value.all.return_value = [stack]

        auditor = DispatchDecisionAuditor(db)
        result = auditor.audit(self._make_decision(cost=0.01))
        assert result.gate_decision == GateDecision.fail

    def test_rejects_banned_provider(self):
        from app.modules.model_router.dispath_decision import DispatchDecisionAuditor
        from ainern2d_shared.ainer_db_models.enum_models import GateDecision

        db = _mock_db()
        stack = self._make_stack("content_policy", {"banned_providers": ["worker-llm"]})
        db.query.return_value.filter.return_value.all.return_value = [stack]

        auditor = DispatchDecisionAuditor(db)
        result = auditor.audit(self._make_decision(worker_type="worker-llm"))
        assert result.gate_decision == GateDecision.fail

    def test_passes_within_ceiling(self):
        from app.modules.model_router.dispath_decision import DispatchDecisionAuditor
        from ainern2d_shared.ainer_db_models.enum_models import GateDecision

        db = _mock_db()
        stack = self._make_stack("budget_policy", {"cost_ceiling": 1.0})
        db.query.return_value.filter.return_value.all.return_value = [stack]

        auditor = DispatchDecisionAuditor(db)
        result = auditor.audit(self._make_decision(cost=0.01))
        assert result.gate_decision == GateDecision.pass_


# ===========================================================================
# entiry_core / continuity.py – conflict detection
# ===========================================================================

class TestContinuityChecker:
    def _make_entity_pack(self, entity_id: str, attributes: dict):
        from ainern2d_shared.schemas.entity import EntityPack, EntityItem
        item = MagicMock(spec=EntityItem)
        item.entity_id = entity_id
        item.attributes = attributes
        pack = MagicMock(spec=EntityPack)
        pack.entities = [item]
        return pack

    def test_first_appearance_consistent(self):
        from app.modules.entiry_core.continuity import ContinuityChecker

        db = _mock_db()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        checker = ContinuityChecker(db)
        pack = self._make_entity_pack("ent_1", {"hair": "black"})
        report = checker.check("run1", pack)
        assert report["ent_1"]["consistent"] is True
        assert report["ent_1"]["detail"] == "first_appearance"

    def test_no_conflict_same_values(self):
        from app.modules.entiry_core.continuity import ContinuityChecker
        from ainern2d_shared.ainer_db_models.knowledge_models import EntityState

        db = _mock_db()
        prev = MagicMock(spec=EntityState)
        prev.state_json = {"hair": "black", "eyes": "blue"}
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = prev

        checker = ContinuityChecker(db)
        pack = self._make_entity_pack("ent_1", {"hair": "black", "eyes": "blue"})
        report = checker.check("run1", pack)
        assert report["ent_1"]["consistent"] is True

    def test_detects_attribute_conflict(self):
        from app.modules.entiry_core.continuity import ContinuityChecker
        from ainern2d_shared.ainer_db_models.knowledge_models import EntityState

        db = _mock_db()
        prev = MagicMock(spec=EntityState)
        prev.state_json = {"hair": "black"}
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = prev

        checker = ContinuityChecker(db)
        pack = self._make_entity_pack("ent_1", {"hair": "white"})  # changed!
        report = checker.check("run1", pack)
        assert report["ent_1"]["consistent"] is False
        assert "hair" in report["ent_1"]["detail"]

    def test_new_keys_do_not_conflict(self):
        from app.modules.entiry_core.continuity import ContinuityChecker
        from ainern2d_shared.ainer_db_models.knowledge_models import EntityState

        db = _mock_db()
        prev = MagicMock(spec=EntityState)
        prev.state_json = {"hair": "black"}
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = prev

        checker = ContinuityChecker(db)
        # Adding new key "age" should not conflict
        pack = self._make_entity_pack("ent_1", {"hair": "black", "age": "17"})
        report = checker.check("run1", pack)
        assert report["ent_1"]["consistent"] is True


# ===========================================================================
# asset-knowledge / embedding.py – hash fallback
# (directory name has a hyphen so we use importlib to load it)
# ===========================================================================

def _import_embedding_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "asset_knowledge_embedding",
        os.path.join(os.path.dirname(__file__), "../app/modules/asset-knowledge/embedding.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestEmbeddingGenerator:
    def test_hash_vector_is_deterministic(self):
        mod = _import_embedding_module()
        v1 = mod._hash_vector("hello world")
        v2 = mod._hash_vector("hello world")
        assert v1 == v2
        assert len(v1) == 1536

    def test_hash_vector_differs_for_different_text(self):
        mod = _import_embedding_module()
        assert mod._hash_vector("foo") != mod._hash_vector("bar")

    def test_embed_uses_hash_fallback_when_no_api_key(self):
        mod = _import_embedding_module()
        from ainern2d_shared.ainer_db_models.rag_models import RagDocument

        db = _mock_db()
        doc = MagicMock(spec=RagDocument)
        doc.tenant_id = "t1"
        doc.project_id = "p1"
        doc.content_text = "Sample story text for embedding"
        db.get.return_value = doc

        gen = mod.EmbeddingGenerator(db, api_key="")  # no key → hash fallback
        emb = gen.embed("doc_001")
        assert emb.embedding_dim == 1536
        assert len(emb.embedding) == 1536

    def test_embed_raises_for_missing_doc(self):
        mod = _import_embedding_module()
        db = _mock_db()
        db.get.return_value = None
        gen = mod.EmbeddingGenerator(db, api_key="")
        with pytest.raises(LookupError):
            gen.embed("nonexistent_doc")
