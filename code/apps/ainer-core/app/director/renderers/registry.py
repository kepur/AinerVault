"""渲染器注册表：名字 → 适配器。加新模型（Wan / Hunyuan / Seedance）就在这里多登记一个。"""
from __future__ import annotations

from app.director.renderers.base import BaseRendererAdapter, RendererError
from app.director.renderers.ltx097 import LTX097Adapter
from app.director.renderers.ltx25 import LTX25Adapter

RENDERERS: dict[str, BaseRendererAdapter] = {
    "ltx_097": LTX097Adapter(),
    "ltx_25": LTX25Adapter(),
}


def get(name: str) -> BaseRendererAdapter:
    r = RENDERERS.get(name)
    if r is None:
        raise RendererError(f"没有渲染器「{name}」。可用：{', '.join(RENDERERS)}")
    return r
