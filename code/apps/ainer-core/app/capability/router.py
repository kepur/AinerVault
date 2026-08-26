"""能力路由：capability × purpose → 端点 + 模型 + 默认参数。

多条路由按 priority 升序依次 fallback。整个「配置中心」就是这一张表加一张端点表 ——
因为适配逻辑全部下沉到中间层了。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.errors import CapabilityError, CapErrorCode
from app.capability.schemas import Capability, CapabilityCatalog
from app.models import CapabilityEndpoint, CapabilityRoute


@dataclass(slots=True)
class ResolvedRoute:
    endpoint: CapabilityEndpoint
    capability: Capability
    model: str | None
    default_params: dict[str, Any] = field(default_factory=dict)
    priority: int = 0

    @property
    def catalog(self) -> CapabilityCatalog | None:
        raw = self.endpoint.caps_cache_json
        return CapabilityCatalog.model_validate(raw) if raw else None

    def estimated_ms(self) -> int | None:
        cat = self.catalog
        if not cat:
            return None
        entry = cat.get(self.capability)
        if not entry:
            return None
        for m in entry.models:
            if self.model and m.id == self.model:
                return m.estimated_ms
        d = entry.default_model()
        return d.estimated_ms if d else None

    def unit_cost(self) -> float | None:
        """单次调用预估成本，用于成本闸门。"""
        cat = self.catalog
        if not cat:
            return None
        entry = cat.get(self.capability)
        if not entry:
            return None
        target = None
        for m in entry.models:
            if self.model and m.id == self.model:
                target = m
                break
        target = target or entry.default_model()
        return target.pricing.cost if target and target.pricing else None


def resolve_routes(
    db: Session, capability: Capability | str, purpose: str = "*"
) -> list[ResolvedRoute]:
    """返回按 priority 升序的候选路由。先找专用 purpose，再回落到 "*"。"""
    cap = Capability(capability) if isinstance(capability, str) else capability

    def _query(p: str) -> list[CapabilityRoute]:
        return list(
            db.execute(
                select(CapabilityRoute)
                .where(
                    CapabilityRoute.capability == cap.value,
                    CapabilityRoute.purpose == p,
                    CapabilityRoute.enabled.is_(True),
                )
                .order_by(CapabilityRoute.priority.asc())
            ).scalars()
        )

    rows = _query(purpose)
    if not rows and purpose != "*":
        rows = _query("*")

    out: list[ResolvedRoute] = []
    for r in rows:
        ep = db.get(CapabilityEndpoint, r.endpoint_id)
        if ep is None or not ep.enabled:
            continue
        out.append(
            ResolvedRoute(
                endpoint=ep,
                capability=cap,
                model=r.model,
                default_params=dict(r.default_params or {}),
                priority=r.priority,
            )
        )
    return out


def resolve_one(db: Session, capability: Capability | str, purpose: str = "*") -> ResolvedRoute:
    routes = resolve_routes(db, capability, purpose)
    if not routes:
        cap = capability.value if isinstance(capability, Capability) else capability
        raise CapabilityError(
            CapErrorCode.NO_ROUTE,
            f"未配置能力路由：{cap} (purpose={purpose})。请在 设置 › 能力路由 中添加。",
        )
    return routes[0]
