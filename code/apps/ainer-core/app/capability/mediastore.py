"""产物落盘 —— 同步方言返回的是字节，而契约里流转的是 URL。

走中间层时，产物由中间层存好、回一个 URL。直连供应商没有这一层：
Cloudflare Workers AI 把图片以 base64 塞在响应里，一次就完事。
于是 Core 必须自己把字节变成一个能被后台、被 i2i 的参考图、
被下游交付清单引用的 URL。

## 按内容寻址

文件名是内容的 sha256。同一张图重复生成不会占两份，
而**更要紧的是幂等**：同一个任务重跑（幂等键命中、回调重放）
不会造出第二个 URL，于是 assets 表里也不会多出一条指向同一张图的记录。

## 这不是对象存储

本地目录只服务开发与单机部署。接了真实对象存储之后，
换掉 `store_bytes` 的实现即可 —— 调用方拿到的始终只是一个 URL。
"""
from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path

from app.config import get_settings

log = logging.getLogger(__name__)

#: 扩展名按 mime 定。写错扩展名，浏览器与下游工具都会拒认
_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif",
    "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "video/mp4": ".mp4",
}

#: 字节头 → 真实类型。**不信供应商声明的 content-type。**
#: Cloudflare 的 SDXL 回的头写着 image/png，字节却是 JPEG ——
#: 照着头存就得到一个叫 .png 的 JPEG，而按扩展名分发的下游工具会拒收。
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"OggS", "audio/ogg"),
)


def sniff(raw: bytes, declared: str) -> str:
    """按字节头认类型，认不出才回落到声明的。"""
    for sig, mime in _MAGIC:
        if raw.startswith(sig):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        return "audio/wav"
    if raw[4:12] in (b"ftypisom", b"ftypmp42", b"ftypM4V ", b"ftypM4A "):
        # MP4 是容器，仅看 ftyp 分不出是视频还是 M4A。上游明确声明
        # audio/mp4 时保留音频类型，否则浏览器会把有声书当成黑画面视频。
        return "audio/mp4" if declared.startswith("audio/") else "video/mp4"
    return declared


def media_root() -> Path:
    root = Path(get_settings().media_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_bytes(raw: bytes, *, mime: str) -> dict[str, object]:
    """把字节存下来，返回一条可直接放进 output.images 的产物描述。"""
    mime = sniff(raw, mime)
    digest = hashlib.sha256(raw).hexdigest()
    name = digest + _EXT.get(mime, ".bin")
    path = media_root() / name
    if not path.exists():
        path.write_bytes(raw)
    base = get_settings().public_base_url.rstrip("/")
    return {
        "url": f"{base}/media/{name}",
        "sha256": digest,
        "mime": mime,
        "bytes": len(raw),
    }


def store_b64(data: str, *, mime: str) -> dict[str, object]:
    """base64 字符串版。容忍 data: URI 前缀 ——
    有的供应商回裸 base64，有的回完整 data URI，两种都要能收。"""
    payload = data.split(",", 1)[1] if data.startswith("data:") else data
    return store_bytes(base64.b64decode(payload), mime=mime)
