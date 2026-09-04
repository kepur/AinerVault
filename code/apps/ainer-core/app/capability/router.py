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
    def billing(self) -> str:
        """这条路由花不花钱：free / paid / unknown。

        存在 default_params.billing 里，不新开一列 —— 它本来就是
        「这条路由的配置」，而且免迁移，运维改一行 JSON 就能标。

        **默认是 unknown，不是 free。** 额度耗尽自动换下一条时只认
        明确标了 free 的：路由表里同时躺着 deepseek / mistral /
        openrouter，猜一下就是在花别人的钱。宁可停下来报错。
        """
        raw = str(self.default_params.get("billing") or "").strip().lower()
        return raw if raw in {"free", "paid"} else "unknown"

    @property
    def key(self) -> str:
        """同一条路由的稳定标识，用来记「这条已经试过了」。"""
        return f"{self.endpoint.id}:{self.model or ''}"

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


def next_free_route(
    db: Session, capability: Capability | str, purpose: str = "*",
    tier: str | None = None, *, tried: "frozenset[str]" = frozenset(),
) -> ResolvedRoute | None:
    """还没试过的、**明确标了免费**的下一条路由。没有就返回 None。

    用途只有一个：某个模型的免费额度用尽时接着往下跑。
    百炼一个账号下几十个模型各有各的免费额度 —— 出图额度见底了，
    换 qwen-image-3.0-pro 还能接着出；硬停在那里等人来改配置，
    整章生产就断在半路。

    只认 billing=free。路由表里同时配着付费端点，
    自动掉过去就是在悄悄花钱 —— 那比停下来糟糕得多。
    """
    for route in resolve_routes(db, capability, purpose, tier):
        if route.key in tried or route.billing != "free":
            continue
        return route
    return None
