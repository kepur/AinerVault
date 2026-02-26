from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import get_store

router = APIRouter(prefix="/internal/observer", tags=["observer"])


@router.get("/runs/{run_id}/trace")
def get_run_trace(run_id: str) -> dict[str, object]:
    store = get_store()
    events = store.events.get(run_id, [])
    sorted_events = sorted(events, key=lambda item: item.get("occurred_at", ""))
    return {"run_id": run_id, "events": sorted_events}
