"""ULID —— 26 字符 Crockford Base32，字典序即时间序，无第三方依赖。"""
from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: 无 I L O U


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        out.append(_ALPHABET[rem])
    return "".join(reversed(out))


def ulid() -> str:
    """48 bit 毫秒时间戳 + 80 bit 随机。"""
    ts = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    return _encode(ts, 10) + _encode(rand, 16)


def new_id(prefix: str = "") -> str:
    """带业务前缀的 id，便于日志里一眼认出类型。prefix 不进排序位。"""
    return f"{prefix}_{ulid()}" if prefix else ulid()
