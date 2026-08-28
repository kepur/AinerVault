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
    tier: str = "*"

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
    db: Session, capability: Capability | str, purpose: str = "*",
    tier: str | None = None,
) -> list[ResolvedRoute]:
    """返回按 priority 升序的候选路由。

    四步回落，从最具体到最通用：
        (purpose, tier) → (purpose, "*") → ("*", tier) → ("*", "*")

    purpose 优先于 tier 是有意的：「这是翻译活」比「这活要用强模型」
    更能决定该走哪个端点 —— 有人给翻译单接了一个专门调过的模型，
    那它比任何档位规则都更该被用上。

    tier 为 None 时按 DEFAULT_TIER 取该 purpose 的默认档 ——
    调用方声明用途即可，不必每处都想一遍该用多强的模型。
    """
    from app.models import DEFAULT_TIER

    cap = Capability(capability) if isinstance(capability, str) else capability
    if tier is None:
        t = DEFAULT_TIER.get(purpose)
        tier = t.value if t else "*"

    def _query(p: str, ti: str) -> list[CapabilityRoute]:
        return list(
            db.execute(
                select(CapabilityRoute)
                .where(
                    CapabilityRoute.capability == cap.value,
                    CapabilityRoute.purpose == p,
                    CapabilityRoute.tier == ti,
                    CapabilityRoute.enabled.is_(True),
                )
                .order_by(CapabilityRoute.priority.asc())
            ).scalars()
        )

    rows: list[CapabilityRoute] = []
    for p, ti in ((purpose, tier), (purpose, "*"), ("*", tier), ("*", "*")):
        rows = _query(p, ti)
        if rows:
            break

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
                tier=r.tier,
            )
        )
    return out


def resolve_one(
    db: Session, capability: Capability | str, purpose: str = "*",
    tier: str | None = None,
) -> ResolvedRoute:
    routes = resolve_routes(db, capability, purpose, tier)
    if not routes:
        cap = capability.value if isinstance(capability, Capability) else capability
        raise CapabilityError(
            CapErrorCode.NO_ROUTE,
            f"未配置能力路由：{cap} (purpose={purpose}, tier={tier})。"
            f"请在 设置 › 能力路由 中添加 —— 加一条 purpose=* / tier=* 的兜底路由"
            f"即可覆盖全部调用。",
        )
    return routes[0]
