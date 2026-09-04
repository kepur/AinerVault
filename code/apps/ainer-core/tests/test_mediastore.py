"""产物落盘。

同步方言返回的是字节，而契约里流转的是 URL —— 这一层负责转换。
"""
from __future__ import annotations

from app.capability.mediastore import _EXT, sniff


class TestSniff:
    """**不信供应商声明的 content-type。**

    Cloudflare 的 SDXL 回的头写着 image/png，字节却是 JPEG ——
    照着头存就得到一个叫 .png 的 JPEG，而按扩展名分发的下游工具会拒收。
    """

    def test_jpeg_bytes_beat_a_png_header(self):
        assert sniff(b"\xff\xd8\xff\xe0rest", "image/png") == "image/jpeg"

    def test_png_bytes_are_recognised(self):
        assert sniff(b"\x89PNG\r\n\x1a\nrest", "image/jpeg") == "image/png"

    def test_webp_needs_both_riff_and_webp(self):
        assert sniff(b"RIFF\x00\x00\x00\x00WEBPxx", "application/octet-stream") \
            == "image/webp"
        assert sniff(b"RIFF\x00\x00\x00\x00WAVEfmt", "x") == "audio/wav"

    def test_unknown_falls_back_to_the_declared_type(self):
        """认不出时用声明的 —— 猜错类型比不猜更糟。"""
        assert sniff(b"\x00\x01\x02\x03nothing", "audio/mpeg") == "audio/mpeg"

    def test_every_sniffable_type_has_an_extension(self):
        for mime in ("image/jpeg", "image/png", "image/webp", "image/gif",
                     "audio/mpeg", "audio/wav", "audio/ogg", "audio/mp4",
                     "video/mp4"):
            assert mime in _EXT, mime

    def test_m4a_container_stays_audio(self):
        raw = b"\x00\x00\x00\x18ftypM4A " + b"rest"
        assert sniff(raw, "audio/mp4") == "audio/mp4"
        assert sniff(raw, "video/mp4") == "video/mp4"


def test_same_bytes_give_the_same_url(tmp_path, monkeypatch):
    """按内容寻址：同一个任务重跑不会造出第二个 URL，
    于是 assets 表里也不会多出一条指向同一张图的记录。"""
    import app.capability.mediastore as ms

    monkeypatch.setattr(ms, "media_root", lambda: tmp_path)
    a = ms.store_bytes(b"\x89PNG\r\n\x1a\nabc", mime="image/png")
    b = ms.store_bytes(b"\x89PNG\r\n\x1a\nabc", mime="image/png")
    assert a["url"] == b["url"]
    assert a["url"].endswith(".png")
    assert len(list(tmp_path.iterdir())) == 1


def test_extension_follows_the_sniffed_type(tmp_path, monkeypatch):
    """声明 png、字节是 jpeg → 存成 .jpg。"""
    import app.capability.mediastore as ms

    monkeypatch.setattr(ms, "media_root", lambda: tmp_path)
    out = ms.store_bytes(b"\xff\xd8\xff\xe0jpegdata", mime="image/png")
    assert out["url"].endswith(".jpg") and out["mime"] == "image/jpeg"
