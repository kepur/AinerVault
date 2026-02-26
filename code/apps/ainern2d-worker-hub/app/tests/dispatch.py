"""worker-hub dispatch 单元测试"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType, RenderStage
from ainern2d_shared.ainer_db_models.pipeline_models import Job


def _make_job(**overrides) -> Job:
    defaults = dict(
        id="job_test_001",
        tenant_id="t1",
        project_id="p1",
        run_id="run_001",
        job_type=JobType.render_video,
        stage=RenderStage.execute,
        status=JobStatus.queued,
        priority=0,
        payload_json={"worker_type": "worker-video"},
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestRoutingTable:
    def test_resolve_video(self):
        from app.dispatcher.routing_table import RoutingTable
        rt = RoutingTable()
        assert rt.resolve(JobType.render_video) == "worker-video"

    def test_resolve_audio(self):
        from app.dispatcher.routing_table import RoutingTable
        rt = RoutingTable()
        assert rt.resolve(JobType.synth_audio) == "worker-audio"

    def test_resolve_llm(self):
        from app.dispatcher.routing_table import RoutingTable
        rt = RoutingTable()
        assert rt.resolve(JobType.extract_entities) == "worker-llm"


class TestNodeRegistry:
    def test_register_and_get(self):
        from app.dispatcher.node_registry import NodeRegistry
        nr = NodeRegistry()
        nr.register("node-1", "worker-video", capacity=3, gpu_tier="A100")
        available = nr.get_available("worker-video")
        assert len(available) == 1
        assert available[0]["node_id"] == "node-1"

    def test_deregister(self):
        from app.dispatcher.node_registry import NodeRegistry
        nr = NodeRegistry()
        nr.register("node-1", "worker-video", capacity=3)
        nr.deregister("node-1")
        assert nr.get_available("worker-video") == []
