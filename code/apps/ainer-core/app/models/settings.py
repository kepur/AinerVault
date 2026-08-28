"""配置层：中间层端点与能力路由。

v1 的 model_providers / provider_adapters / model_profiles / route_decisions 四张表
加 3145 行 config_center.py，在这里被两张表取代 —— 因为适配逻辑全部下沉到中间层了。
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class QualityTier(str, enum.Enum):
    """质量档位。同一个能力，不同活儿该用不同强度的模型。

    分档的理由是成本与质量不成正比：分块、切镜这种活儿，
    强模型的产出与快模型没有可觉察差别，钱全烧在没人看得出的地方；
    而文化差异审查、名物定译这种活儿，快模型给的结论似是而非 ——
    读起来头头是道，错的地方要等读者笑不出来才发现。

    draft     快而便宜。批量、结构化、可机器校验的活儿。
    standard  默认档。大部分内容生成。
    premium   强模型。判断吃重、错了不易察觉的活儿。
    critical  最强档，可开多轮交叉验证。终审与不可逆决策。
    """

    draft = "draft"
    standard = "standard"
    premium = "premium"
    critical = "critical"


#: 每个 purpose 的默认档位。pipeline 不写死模型，只声明它要多强的判断力。
DEFAULT_TIER: dict[str, QualityTier] = {
    # 规则性强、错了立刻能发现
    "extract": QualityTier.standard,
    "lexicon": QualityTier.standard,
    "shot_plan": QualityTier.draft,
    "asset_variant": QualityTier.draft,
    "asset_ref": QualityTier.draft,
    "speakers": QualityTier.draft,
    # 判断吃重、错了藏得住
    "naming": QualityTier.premium,
    "devices": QualityTier.premium,
    "memes": QualityTier.premium,
    "translate": QualityTier.premium,
    "script": QualityTier.premium,
    # 终审：这一档的结论直接决定要不要返工
    "review": QualityTier.critical,
    "culture_review": QualityTier.critical,
    "backcheck": QualityTier.critical,
}


class CapabilityEndpoint(Base, StdMixin):
    __tablename__ = "capability_endpoints"
    __table_args__ = (UniqueConstraint("name", name="uq_capability_endpoints_name"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # {mode: bearer|header|none, token_enc, header_name}
    auth_json: Mapped[dict | None] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timeout_sec: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    # capability = 说本项目契约的中间层；openai = 直连 OpenAI 兼容的文本服务
    dialect: Mapped[str] = mapped_column(String(16), default="capability", nullable=False)
    health_json: Mapped[dict | None] = mapped_column(JSONB)
    # GET /capabilities 的缓存 —— 后台据此自动渲染参数表单
    caps_cache_json: Mapped[dict | None] = mapped_column(JSONB)
    caps_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contract_version: Mapped[str | None] = mapped_column(String(16))


class CapabilityRoute(Base, StdMixin):
    """能力 × 用途 → 端点 + 模型 + 默认参数。多条按 priority 依次 fallback。"""

    __tablename__ = "capability_routes"
    __table_args__ = (
        UniqueConstraint(
            "capability", "purpose", "tier", "priority",
            name="uq_capability_routes_cap_purpose_tier_prio",
        ),
        Index("ix_capability_routes_lookup", "capability", "purpose", "tier", "enabled"),
    )

    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    # first_frame | last_frame | scene_bg | entity_ref | dialogue | narration
    # | bgm | ambience | script | translate | extract | lexicon | "*"
    purpose: Mapped[str] = mapped_column(String(64), default="*", nullable=False)
    #: 质量档位。"*" 表示该路由不分档，任何档位都落到它 ——
    #: 只接了一个模型时不必被迫填四份路由。
    tier: Mapped[str] = mapped_column(String(16), default="*", nullable=False)
    endpoint_id: Mapped[str] = mapped_column(
        ForeignKey("capability_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str | None] = mapped_column(String(128))
    default_params: Mapped[dict | None] = mapped_column(JSONB)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PromptTemplate(Base, StdMixin):
    """系统提示词模板，可编辑可回滚。"""

    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_prompt_templates_key_ver"),)

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class User(Base, StdMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
