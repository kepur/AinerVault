"""In-memory worker node registry (thread-safe)."""

from __future__ import annotations

import threading
import time
from typing import Any

from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)

_HEARTBEAT_TIMEOUT_S = 60  # nodes silent longer than this are considered dead


class NodeRegistry:
    """Tracks registered worker nodes and their availability."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(
        self,
        node_id: str,
        worker_type: str,
        capacity: int,
        gpu_tier: str | None = None,
    ) -> None:
        with self._lock:
            self._nodes[node_id] = {
                "node_id": node_id,
                "worker_type": worker_type,
                "capacity": capacity,
                "current_load": 0,
                "gpu_tier": gpu_tier,
                "last_seen": time.time(),
            }
        logger.info("registered node %s (type=%s)", node_id, worker_type)

    def deregister(self, node_id: str) -> None:
        with self._lock:
            self._nodes.pop(node_id, None)
        logger.info("deregistered node %s", node_id)

    # ------------------------------------------------------------------
    # Heartbeat / load
    # ------------------------------------------------------------------
    def heartbeat(self, node_id: str) -> None:
        """Update the last_seen timestamp for a node."""
        with self._lock:
            node = self._nodes.get(node_id)
            if node is not None:
                node["last_seen"] = time.time()

    def update_load(self, node_id: str, current_load: int) -> None:
        with self._lock:
            node = self._nodes.get(node_id)
            if node is not None:
                node["current_load"] = current_load

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def get_available(self, worker_type: str) -> list[dict]:
        """Return nodes with spare capacity whose heartbeat is recent."""
        now = time.time()
        with self._lock:
            return [
                dict(n)
                for n in self._nodes.values()
                if n["worker_type"] == worker_type
                and n["capacity"] > n["current_load"]
                and (now - n["last_seen"]) <= _HEARTBEAT_TIMEOUT_S
            ]