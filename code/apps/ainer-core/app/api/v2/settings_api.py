"""设置：中间层端点 + 能力路由 + 聚合能力目录。

整个「配置中心」就这两张表 —— 适配逻辑全在中间层，Core 只需知道打哪个地址。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.client import CapabilityClient
from app.capability.errors import CapabilityError
from app.capability.schemas import Capability, CapabilityCatalog
from app.db import get_db
from app.ids import new_id
from app.models import CapabilityEndpoint, CapabilityRoute, utcnow

router = APIRouter(prefix="/api/v2/settings", tags=["settings"])


class EndpointIn(BaseModel):
    name: str
    base_url: str
    auth: dict = Field(default_factory=dict)
    enabled: bool = True
    timeout_sec: int = 60


class EndpointOut(BaseModel):
    id: str
    name: str
    base_url: str
    enabled: bool
    timeout_sec: int
    auth_mode: str
    health: dict | None = None
    contract_version: str | None = None
    capabilities_count: int = 0
    caps_fetched_at: str | None = None

    @classmethod
    def of(cls, e: CapabilityEndpoint) -> EndpointOut:
        caps = (e.caps_cache_json or {}).get("capabilities") or []
        return cls(
            id=e.id, name=e.name, base_url=e.base_url, enabled=e.enabled,
            timeout_sec=e.timeout_sec,
            auth_mode=str((e.auth_json or {}).get("mode") or "none"),
            health=e.health_json, contract_version=e.contract_version,
            capabilities_count=len(caps),
            caps_fetched_at=e.caps_fetched_at.isoformat() if e.caps_fetched_at else None,
        )


class RouteIn(BaseModel):
    capability: str
    purpose: str = "*"
    endpoint_id: str
    model: str | None = None
    default_params: dict = Field(default_factory=dict)
    priority: int = 0
    enabled: bool = True


# ── 端点 ──────────────────────────────────────────────────────────────────────

@router.get("/endpoints")
def list_endpoints(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(CapabilityEndpoint).order_by(CapabilityEndpoint.name)).scalars()
    return [EndpointOut.of(e).model_dump() for e in rows]


@router.post("/endpoints", status_code=201)
def create_endpoint(body: EndpointIn, db: Session = Depends(get_db)) -> dict:
    dup = db.execute(
        select(CapabilityEndpoint).where(CapabilityEndpoint.name == body.name)
    ).scalars().first()
    if dup:
        raise HTTPException(status_code=409, detail=f"端点名 {body.name} 已存在")
    ep = CapabilityEndpoint(
        id=new_id("ep"), name=body.name, base_url=body.base_url.rstrip("/"),
        auth_json=body.auth, enabled=body.enabled, timeout_sec=body.timeout_sec,
    )
    db.add(ep)
    db.flush()
    return EndpointOut.of(ep).model_dump()


@router.patch("/endpoints/{endpoint_id}")
def update_endpoint(endpoint_id: str, body: EndpointIn, db: Session = Depends(get_db)) -> dict:
    ep = db.get(CapabilityEndpoint, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    ep.name = body.name
    ep.base_url = body.base_url.rstrip("/")
    ep.auth_json = body.auth
    ep.enabled = body.enabled
    ep.timeout_sec = body.timeout_sec
    db.flush()
    return EndpointOut.of(ep).model_dump()


@router.delete("/endpoints/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: str, db: Session = Depends(get_db)) -> None:
    ep = db.get(CapabilityEndpoint, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    db.delete(ep)


@router.post("/endpoints/{endpoint_id}:test")
def test_endpoint(endpoint_id: str, db: Session = Depends(get_db)) -> dict:
    """真实请求 /health —— 不是模拟。v1 的 test-connection 是假的，这里是真的。"""
    ep = db.get(CapabilityEndpoint, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    with CapabilityClient(ep.base_url, auth=ep.auth_json or {}, timeout_sec=10) as c:
        try:
            h = c.health()
            result = {"ok": h.ok, "version": h.version, "upstreams": h.upstreams,
                      "checked_at": utcnow().isoformat()}
        except CapabilityError as exc:
            result = {"ok": False, "error": exc.to_json(), "checked_at": utcnow().isoformat()}
    ep.health_json = result
    if result.get("version"):
        ep.contract_version = result["version"]
    db.flush()
    return result


@router.post("/endpoints/{endpoint_id}:refresh-caps")
def refresh_caps(endpoint_id: str, db: Session = Depends(get_db)) -> dict:
    """拉取 Discovery 并缓存。后台的参数表单全部由此驱动。"""
    ep = db.get(CapabilityEndpoint, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    with CapabilityClient(ep.base_url, auth=ep.auth_json or {}, timeout_sec=20) as c:
        try:
            cat = c.capabilities()
        except CapabilityError as exc:
            raise HTTPException(status_code=502, detail=exc.to_json()) from exc

    ep.caps_cache_json = cat.model_dump(mode="json")
    ep.caps_fetched_at = utcnow()
    ep.contract_version = cat.capability_version
    db.flush()
    missing = cat.missing_required()
    return {
        "capability_version": cat.capability_version,
        "capabilities": [e.capability.value for e in cat.capabilities],
        "missing_required": [m.value for m in missing],
        "fetched_at": ep.caps_fetched_at.isoformat(),
    }


@router.get("/capabilities")
def aggregated_capabilities(db: Session = Depends(get_db)) -> dict:
    """聚合所有端点的能力目录。前端据 param_schema 自动渲染参数表单。"""
    endpoints = list(
        db.execute(
            select(CapabilityEndpoint).where(CapabilityEndpoint.enabled.is_(True))
        ).scalars()
    )
    merged: dict[str, list[dict]] = {}
    for ep in endpoints:
        raw = ep.caps_cache_json
        if not raw:
            continue
        cat = CapabilityCatalog.model_validate(raw)
        for entry in cat.capabilities:
            bucket = merged.setdefault(entry.capability.value, [])
            for m in entry.models:
                bucket.append({
                    **m.model_dump(mode="json"),
                    "endpoint_id": ep.id,
                    "endpoint_name": ep.name,
                })

    known = {c.value for c in Capability}
    return {
        "capabilities": [
            {"capability": cap, "models": models} for cap, models in sorted(merged.items())
        ],
        "unsupported": sorted(known - set(merged)),
    }


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.get("/routes")
def list_routes(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(CapabilityRoute).order_by(
            CapabilityRoute.capability, CapabilityRoute.purpose, CapabilityRoute.priority
        )
    ).scalars()
    return [
        {
            "id": r.id, "capability": r.capability, "purpose": r.purpose,
            "endpoint_id": r.endpoint_id, "model": r.model,
            "default_params": r.default_params or {}, "priority": r.priority,
            "enabled": r.enabled,
        }
        for r in rows
    ]


@router.put("/routes")
def replace_routes(body: list[RouteIn], db: Session = Depends(get_db)) -> dict:
    """整表提交，简单可靠。路由表很小，不值得做增量同步。"""
    valid_eps = {e.id for e in db.execute(select(CapabilityEndpoint)).scalars()}
    known_caps = {c.value for c in Capability}
    for r in body:
        if r.endpoint_id not in valid_eps:
            raise HTTPException(status_code=400, detail=f"未知端点 {r.endpoint_id}")
        if r.capability not in known_caps:
            raise HTTPException(status_code=400, detail=f"未知能力 {r.capability}")

    for old in db.execute(select(CapabilityRoute)).scalars().all():
        db.delete(old)
    db.flush()

    for r in body:
        db.add(CapabilityRoute(
            id=new_id("rt"), capability=r.capability, purpose=r.purpose,
            endpoint_id=r.endpoint_id, model=r.model,
            default_params=r.default_params, priority=r.priority, enabled=r.enabled,
        ))
    db.flush()
    return {"count": len(body)}
