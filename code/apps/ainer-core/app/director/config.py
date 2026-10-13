"""Director Core 配置：configs/director/*.yaml ＋ 环境变量覆盖（DIRECTOR_*）。

功能开关（feature_flags.yaml）决定哪些后端真跑：V1 是 Blender ＋ LTX 0.9.7 开，UE ＋ LTX 2.5 关。
关着的后端代码照样在（协议映射、参数校验、payload、mock），调用时抛 FeatureDisabled。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

#: ainer-core 根目录（相对路径都相对它，与 media_dir 的 var/media 同一个基准）
CORE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = CORE_ROOT / "configs" / "director"
FLAGS = ("blender_enabled", "ue_enabled", "ltx097_enabled", "ltx25_enabled", "world_greybox_enabled")


class FeatureDisabled(RuntimeError):
    """后端在当前版本没开（开关在 configs/director/feature_flags.yaml）。"""


@lru_cache
def load(name: str) -> dict[str, Any]:
    p = CONFIG_DIR / f"{name}.yaml"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def reload() -> None:
    load.cache_clear()


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def features() -> dict[str, bool]:
    base = load("feature_flags")
    out = {}
    for k in FLAGS:
        env = os.environ.get(f"DIRECTOR_{k.upper()}")
        out[k] = _truthy(env) if env is not None else bool(base.get(k, False))
    return out


def enabled(flag: str) -> bool:
    return features().get(flag, False)


def require(flag: str, what: str) -> None:
    if not enabled(flag):
        raise FeatureDisabled(f"{what}在当前版本未启用（configs/director/feature_flags.yaml 的 {flag}=false）")


def storage_dir() -> Path:
    p = Path(load("director").get("storage_dir") or "var/director")
    if not p.is_absolute():
        p = CORE_ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def job_dir(job_id: str) -> Path:
    d = storage_dir() / "jobs" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d
