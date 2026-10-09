"""创作画布的自由生成：选能力、夹参数、摆 payload、只给本库地址、路由形状。

数据库不在跑：这里只测纯函数和 HTTP 形状，库相关的部分用假对象顶上。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.capability import generic
from app.capability.generic import I2I, I2V, T2I, GenerateIn, RefIn


def ref(role: str, kind: str = "image", url: str = "http://localhost:8100/media/a.png",
        tag: str | None = None) -> RefIn:
    return RefIn(node_id=f"n_{role}", url=url, kind=kind, role=role, tag=tag)  # type: ignore[arg-type]


#: 本机网关 /capabilities 的真实形状（sizes 是 "WxH" 字符串，LTX-2.5 带 ready 与 supports）
GATEWAY_CAPS = {
    "capability_version": "1.0",
    "capabilities": [
        {"capability": "image.text_to_image", "models": [{
            "id": "flux2-klein-4b", "display_name": "FLUX.2-klein 4B", "default": True,
            "estimated_ms": 19500, "pricing": {"unit": "image", "cost": 0.0, "currency": "USD"},
            "limits": {"max_prompt_chars": 2000, "sizes": ["800x480", "512x768", "1536x768", "1280x720"],
                       "max_ref_images": 0}}]},
        {"capability": "image.image_to_image", "models": [{
            "id": "flux2-klein-4b-edit", "display_name": "FLUX.2-klein 编辑", "default": True,
            "limits": {"sizes": ["800x480", "512x768", "1536x768"], "max_ref_images": 4}}]},
        {"capability": "video.image_to_video", "models": [
            {"id": "ltxv-2b-distilled", "display_name": "LTX-Video 2B", "default": True,
             "limits": {"sizes": ["800x480"], "max_duration_ms": 6000}, "control_types": ["v2v"]},
            {"id": "ltx-2.5-22b-distilled", "display_name": "LTX-2.5", "default": False, "ready": False,
             "estimated_ms": 360000, "pricing": {"cost": 0.0},
             "limits": {"sizes": ["576x320", "704x384", "832x448", "1024x576",
                                  "320x576", "384x704", "448x832", "576x1024"],
                        "size_multiple": 64, "max_duration_ms": 20000},
             "supports": {"text_to_video": True}, "control_types": []},
        ]},
        # 枚举里没有的能力：解析模型列表时不能因为它 500
        {"capability": "video.lip_sync", "models": [{"id": "latentsync", "display_name": "x"}]},
    ],
}
GATEWAY = SimpleNamespace(id="ep_gw", name="本机网关", base_url="http://127.0.0.1:7999/cap/v1",
                          caps_cache_json=GATEWAY_CAPS)


def info(model: str) -> generic.ModelInfo:
    caps = ("image.text_to_image", "image.image_to_image", "video.image_to_video")
    return next(i for i in generic.catalog_models(GATEWAY, caps) if i.model == model)


# ── 选能力 ──────────────────────────────────────────────────────────────────

def test_image_goes_text_to_image_unless_a_base_image_is_given():
    assert generic.pick_capability("image", []) == T2I
    assert generic.pick_capability("image", [ref("character"), ref("style")]) == T2I
    assert generic.pick_capability("image", [ref("base")]) == I2I
    # 生成面板的角色下拉里没有「底图」，对图片来说「首帧」就是从这张出发
    assert generic.pick_capability("image", [ref("first_frame")]) == I2I
    # 视频当不了底图
    assert generic.pick_capability("image", [ref("base", kind="video")]) == T2I


def test_video_is_always_image_to_video_because_the_enum_has_no_text_to_video():
    from app.capability.schemas import Capability

    assert "video.text_to_video" not in {c.value for c in Capability}
    assert generic.pick_capability("video", []) == I2V
    assert generic.pick_capability("video", [ref("first_frame")]) == I2V


# ── 夹参数 ──────────────────────────────────────────────────────────────────

LTX25_SIZES = ["576x320", "704x384", "832x448", "1024x576", "320x576", "384x704", "448x832", "576x1024"]
FLUX_SIZES = ["800x480", "512x768", "1536x768", "1280x720"]


def test_720p_on_ltx25_is_clamped_to_its_largest_16_9_and_says_so():
    w, h, warns = generic.clamp_size("16:9", "720p", LTX25_SIZES, 64)
    assert (w, h) == (1024, 576)
    assert any("最大 1024×576" in x for x in warns)


def test_480p_picks_by_area_not_just_aspect():
    """只看画幅的话 480p 也会被拉到 1024×576，慢一倍。"""
    w, h, warns = generic.clamp_size("16:9", "480p", LTX25_SIZES, 64)
    assert (w, h) == (832, 448)
    assert warns


def test_portrait_stays_portrait():
    assert generic.clamp_size("9:16", "720p", LTX25_SIZES, 64)[:2] == (576, 1024)


def test_exact_size_has_no_warning():
    assert generic.clamp_size("16:9", "720p", FLUX_SIZES, None) == (1280, 720, [])


def test_missing_aspect_falls_back_to_the_closest_and_says_which():
    w, h, warns = generic.clamp_size("1:1", "720p", FLUX_SIZES, None)
    assert (w, h) == (512, 768)
    assert any("没有 1:1" in x for x in warns)


def test_without_sizes_the_short_side_is_aligned_to_the_multiple():
    assert generic.clamp_size("16:9", "720p", None, 64)[:2] == (1280, 704)
    assert generic.clamp_size("9:16", "480p", None, None)[:2] == (480, 856)


def test_bad_aspect_and_resolution_fall_back_with_a_warning():
    w, h, warns = generic.clamp_size("wide", "hd", None, None)
    assert (w, h) == (1280, 720)
    assert len(warns) == 2


def test_parse_sizes_accepts_every_shape_the_dialects_use():
    assert generic.parse_sizes(["1024x576", "1024*1024", [512, 768], {"width": 800, "height": 480},
                                "junk", None, [0, 5], "1024x576"]) == \
        [(1024, 576), (1024, 1024), (512, 768), (800, 480)]


def test_duration_is_clamped_to_the_model_limit():
    assert generic.clamp_duration(15000, 6000) == (6000, ["该模型最长 6s，按 6s 出"])
    assert generic.clamp_duration(None, 20000) == (generic.DEFAULT_VIDEO_MS, [])
    ms, warns = generic.clamp_duration(200, None)
    assert ms == generic.MIN_VIDEO_MS and warns


def test_count_is_clamped():
    assert generic.clamp_count(2) == (2, [])
    assert generic.clamp_count(0) == (1, [])
    n, warns = generic.clamp_count(9)
    assert n == generic.MAX_COUNT and warns


# ── 参考取舍 ─────────────────────────────────────────────────────────────────

def test_flux_text_to_image_takes_no_reference_and_says_so():
    refs, warns = generic.fit_refs(T2I, [ref("character"), ref("style")], info("flux2-klein-4b"))
    assert refs == []
    assert any("不吃参考图" in w for w in warns)


def test_image_to_image_keeps_one_base_and_counts_it_against_the_limit():
    many = [ref("first_frame")] + [ref("character", tag=f"人{i}") for i in range(5)]
    refs, warns = generic.fit_refs(I2I, many, info("flux2-klein-4b-edit"))
    assert [r.role for r in refs] == ["base", "character", "character", "character"]
    assert any("最多收 3 张" in w for w in warns)


def test_identity_refs_survive_the_cut_before_style_refs():
    refs, _ = generic.fit_refs(I2I, [ref("base"), ref("style", tag="风格"), ref("character", tag="脸")],
                               generic.ModelInfo("e", "e", "m", "m", I2I, max_ref_images=2))
    assert [r.tag for r in refs[1:]] == ["脸"]


def test_video_slots_first_frame_and_identity_sheet():
    refs, _ = generic.fit_refs(I2V, [ref("character", tag="林晓"), ref("character", tag="男人"),
                                     ref("first_frame", tag="雪坡")], info("ltx-2.5-22b-distilled"))
    roles = {r.role: r.tag for r in refs}
    assert roles == {"first_frame": "雪坡", "reference_sheet": "林晓"}


def test_control_video_is_dropped_when_the_model_cannot_run_it():
    clay = ref("control_video", kind="video", url="http://localhost:8100/media/c.mp4", tag="白模")
    refs, warns = generic.fit_refs(I2V, [clay], info("ltx-2.5-22b-distilled"))
    assert refs == [] and any("控制视频" in w for w in warns)
    refs, _ = generic.fit_refs(I2V, [clay], info("ltxv-2b-distilled"))
    assert [(r.role, r.tag) for r in refs] == [("control_video", "v2v")]


def test_control_and_identity_sheet_are_not_sent_together():
    clay = ref("control_video", kind="video", url="http://localhost:8100/media/c.mp4")
    refs, warns = generic.fit_refs(I2V, [clay, ref("character")], info("ltxv-2b-distilled"))
    assert [r.role for r in refs] == ["control_video"]
    assert any("不能同一次用" in w for w in warns)


def test_audio_and_wrong_kind_refs_are_skipped_with_a_reason():
    refs, warns = generic.fit_refs(T2I, [ref("reference", kind="audio"), ref("reference", kind="video")])
    assert refs == [] and len(warns) == 2


# ── payload ─────────────────────────────────────────────────────────────────

def body(media: str = "image", refs: list[RefIn] | None = None, **kw: Any) -> GenerateIn:
    return GenerateIn(media=media, prompt="a girl skiing", refs=refs or [], **kw)  # type: ignore[arg-type]


def test_text_to_image_payload_shape():
    p = generic.build_payload(T2I, body(refs=[ref("character", tag="林晓")], negative_prompt="blurry"),
                              1280, 720, None, 7)
    assert p["width"] == 1280 and p["height"] == 720 and p["n"] == 1
    assert p["params"] == {"seed": 7} and p["negative_prompt"] == "blurry"
    item = p["reference_images"][0]
    assert item["ref"] == {"url": "http://localhost:8100/media/a.png"}
    assert item["role"] == "character" and item["identity"] is True and item["tag"] == "林晓"


def test_image_to_image_payload_puts_the_base_in_image():
    p = generic.build_payload(I2I, body(refs=[ref("base"), ref("style")]), 800, 480, None, 1)
    assert p["image"] == {"url": "http://localhost:8100/media/a.png"}
    assert [r["role"] for r in p["reference_images"]] == ["style"]
    assert "identity" not in p["reference_images"][0]


def test_image_to_video_payload_shape():
    refs = [ref("first_frame"), ref("last_frame"), ref("reference_sheet"),
            ref("control_video", kind="video", url="http://localhost:8100/media/c.mp4", tag="depth")]
    p = generic.build_payload(I2V, body("video", refs), 1024, 576, 8000, 3)
    assert p["first_frame"] == p["last_frame"] == p["reference_sheet"] == {"url": "http://localhost:8100/media/a.png"}
    assert p["control"] == {"type": "depth", "video": {"url": "http://localhost:8100/media/c.mp4"}}
    assert p["duration_ms"] == 8000 and p["fps"] == generic.FPS and "reference_images" not in p


def test_data_url_refs_become_b64_and_core_asset_ids_never_reach_the_gateway():
    """网关把 asset_id 当它自己输出目录里的文件名 —— Core 的资产 id 送过去只会报不存在。"""
    r = RefIn(node_id="n", url="data:image/svg+xml;base64,PHN2Zy8+", asset_id="as_X", kind="image", role="base")
    p = generic.build_payload(I2I, body(refs=[r]), 800, 480, None, 1)
    assert p["image"] == {"b64": "PHN2Zy8+", "mime": "image/svg+xml"}
    assert "as_X" not in repr(p)


def test_seed_plus_i_keeps_the_idempotency_keys_apart():
    """幂等键是 input 的哈希：count=2 用同一个 seed 会被合成一条任务。"""
    from app.capability.client import canonical_idempotency_key

    b = body()
    keys = {canonical_idempotency_key(T2I, generic.build_payload(T2I, b, 800, 480, None, 100 + i),
                                      endpoint_id="ep", model="m") for i in range(4)}
    assert len(keys) == 4


# ── 本库地址 ─────────────────────────────────────────────────────────────────

def test_media_name_only_accepts_plain_media_paths():
    assert generic.media_name("/media/abc.png") == "abc.png"
    assert generic.media_name("http://localhost:8100/media/abc.mp4") == "abc.mp4"
    for bad in ("http://127.0.0.1:7999/api/image?f=x.png",   # 网关暂存目录，会被清
                "/media/../secret", "/media/a/b.png", "/media/.hidden", "/media/x.png?f=1",
                "data:image/png;base64,AAA", "", None, "/api/v2/director/jobs/j/files/a.mp4"):
        assert generic.media_name(bad) is None, bad


def test_local_media_url_requires_the_file_to_be_in_our_store(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "media_dir", str(tmp_path))
    (tmp_path / "abc.png").write_bytes(b"x")
    assert generic.local_media_url("http://localhost:8100/media/abc.png") == "/media/abc.png"
    assert generic.local_media_url("http://other-host:9/media/abc.png") == "/media/abc.png"
    assert generic.local_media_url("/media/missing.png") is None
    assert generic.local_media_url("http://127.0.0.1:7999/api/image?f=abc.png") is None


def test_refs_are_rewritten_to_absolute_urls_and_foreign_ones_dropped(tmp_path, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "media_dir", str(tmp_path))
    monkeypatch.setattr(s, "public_base_url", "http://core:8100/")
    (tmp_path / "abc.png").write_bytes(b"x")
    db = SimpleNamespace(get=lambda *_: None)
    out, warns = generic.resolve_refs(db, [
        RefIn(node_id="a", url="/media/abc.png"),
        RefIn(node_id="b", url="https://example.com/x.png", tag="外链"),
        RefIn(node_id="c", url="data:image/png;base64,AAA"),
    ])
    assert [r.url for r in out] == ["http://core:8100/media/abc.png", "data:image/png;base64,AAA"]
    assert len(warns) == 1 and "外链" in warns[0]


def test_canvas_node_ids_fit_the_ref_id_column():
    assert generic.canvas_ref_id("n_abc") == "n_abc"
    long_id = "entity:ent_01JABCDEFGHJKMNPQRSTVWXYZ0:three_quarter_left"
    rid = generic.canvas_ref_id(long_id)
    assert rid is not None and len(rid) <= 32 and rid == generic.canvas_ref_id(long_id)
    assert generic.canvas_ref_id(None) is None


def test_attach_to_ref_ignores_the_canvas_node_kind():
    """规格要求确认：_attach_to_ref 对不认识的 ref_kind 什么都不做，也不碰数据库。"""
    from app.capability.service import _attach_to_ref

    touched: list[str] = []

    class Db:
        def __getattr__(self, name: str) -> Any:
            touched.append(name)
            raise AssertionError(name)

    task = SimpleNamespace(id="gt_x", ref_kind="canvas_node", ref_id="n_1", result_json={})
    _attach_to_ref(Db(), task, [SimpleNamespace(id="as_1")])  # type: ignore[arg-type]
    assert touched == []


# ── 模型目录 ─────────────────────────────────────────────────────────────────

def test_catalog_parses_gateway_limits_and_skips_unknown_capabilities():
    infos = generic.catalog_models(GATEWAY, generic.CAPS_BY_MEDIA["video"])
    assert [i.model for i in infos] == ["ltxv-2b-distilled", "ltx-2.5-22b-distilled"]
    two, ltx = infos
    assert two.is_default and two.local and two.control_types == ["v2v"]
    assert ltx.ready is False and ltx.supports["text_to_video"] is True
    assert ltx.sizes[3] == (1024, 576) and ltx.size_multiple == 64 and ltx.max_duration_ms == 20000
    assert generic.catalog_models(SimpleNamespace(id="e", caps_cache_json=None), ("image.text_to_image",)) == []


def test_model_option_has_the_frontend_shape_and_never_calls_unknown_price_free():
    opt = generic.to_option(info("flux2-klein-4b"), "image", billing="free", blocked=None, routed=True)
    assert set(opt) == {"endpoint_id", "model", "label", "capability", "media", "ready", "local",
                        "cost", "estimated_ms", "limits", "supports"}
    assert set(opt["limits"]) == {"sizes", "max_duration_ms", "max_ref_images", "max_count"}
    assert opt["limits"]["sizes"][0] == [800, 480] and opt["cost"] == 0.0 and opt["ready"] is True

    paid = generic.ModelInfo("ep_ds", "百炼", "wan2.7-i2v", "万相 2.7", I2V)
    opt = generic.to_option(paid, "video", billing="unknown", blocked="wan2.7-i2v 标为未标注…", routed=True)
    assert opt["cost"] is None and opt["ready"] is False and "付费·未批准" in opt["label"]


def test_picked_model_borrows_billing_but_not_approval_from_other_purposes():
    """approved 是「这个用途批准花钱」，不能借给画布；billing 是模型本身的属性，可以借。"""
    ep = SimpleNamespace(id="ep_gw")
    other = SimpleNamespace(capability=I2V, endpoint_id="ep_gw", model="ltx-2.5-22b-distilled",
                            purpose="shot_video_ltx25", tier="*", priority=0,
                            default_params={"billing": "paid", "approved": True, "audio": {"mode": "x"}})
    route, routed = generic.route_for(info("ltx-2.5-22b-distilled"), ep, [other])  # type: ignore[arg-type]
    assert routed and route.default_params == {"billing": "paid"}

    own = SimpleNamespace(capability=I2V, endpoint_id="ep_gw", model=None, purpose="*", tier="*",
                          priority=1, default_params={"billing": "free"})
    route, routed = generic.route_for(info("ltxv-2b-distilled"), ep, [own])  # type: ignore[arg-type]
    assert routed and route.billing == "free" and route.model == "ltxv-2b-distilled"

    route, routed = generic.route_for(info("ltxv-2b-distilled"), ep, [])  # type: ignore[arg-type]
    assert not routed and route.billing == "unknown"


def test_request_body_matches_the_frontend_generate_body():
    b = GenerateIn.model_validate({
        "media": "video", "endpoint_id": None, "model": "ltx-2.5-22b-distilled",
        "prompt": "参考「林晓」滑下雪坡", "negative_prompt": None,
        "refs": [{"node_id": "entity:e1:front", "url": "/media/a.png", "asset_id": None,
                  "kind": "image", "role": "character", "tag": "林晓"}],
        "aspect_ratio": "16:9", "resolution": "720p", "duration_ms": 15000, "count": 2, "seed": None,
        "target": {"plan_id": "sp_1", "node_id": "shot:sh_1"}, "confirm_cost": True,
    })
    assert b.refs[0].role == "character" and b.target and b.target.node_id == "shot:sh_1"


# ── 路由 ────────────────────────────────────────────────────────────────────

def test_router_paths():
    from app.api.v2 import canvas_gen

    routes = {(getattr(r, "path", ""), m) for r in canvas_gen.router.routes for m in getattr(r, "methods", ())}
    for want in (("/api/v2/studio/models", "GET"), ("/api/v2/studio/generate", "POST"),
                 ("/api/v2/studio/generate/{task_id}", "GET")):
        assert want in routes, want


def test_routes_are_registered_on_the_app():
    try:
        from app.main import app
    except ImportError as exc:          # be-canvas 的 canvas.py 没写完时 main 起不来，不是这里的问题
        pytest.skip(f"app.main 还导入不了：{exc}")
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v2/studio/generate" in paths and "/api/v2/studio/models" in paths


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v2 import canvas_gen
    from app.db import get_db

    class FakeDb:
        def commit(self) -> None:
            pass

    def fake_db():
        yield FakeDb()

    app = FastAPI()
    app.include_router(canvas_gen.router)
    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


def test_models_route_shape(client, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(generic, "list_models", lambda db, media: seen.append(media) or [{"model": "m"}])
    assert client.get("/api/v2/studio/models?media=video").json() == {"models": [{"model": "m"}]}
    assert seen == ["video"]
    assert client.get("/api/v2/studio/models?media=audio").status_code == 422


def test_cost_gate_is_a_409_with_the_estimate(client, monkeypatch):
    def gate(db, body):
        raise generic.GenerateError(409, "COST_CONFIRM_REQUIRED", "预估要花钱", estimated_cost=2.5, count=2)

    monkeypatch.setattr(generic, "submit", gate)
    r = client.post("/api/v2/studio/generate", json={"media": "image", "prompt": "x", "refs": [],
                                                    "aspect_ratio": "16:9", "resolution": "720p", "count": 2})
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "COST_CONFIRM_REQUIRED", "message": "预估要花钱",
                                  "estimated_cost": 2.5, "count": 2}


def test_generate_route_passes_confirm_cost_through(client, monkeypatch):
    got: list[GenerateIn] = []
    result = {"tasks": [{"id": "gt_1", "status": "queued"}], "warnings": [], "estimated_cost": 0.0,
              "requires_confirm": False,
              "resolved": {"endpoint_id": "ep", "model": "m", "width": 800, "height": 480, "duration_ms": None}}
    monkeypatch.setattr(generic, "submit", lambda db, body: got.append(body) or result)
    r = client.post("/api/v2/studio/generate", json={"media": "image", "prompt": "x", "refs": [],
                                                    "aspect_ratio": "16:9", "resolution": "720p",
                                                    "count": 1, "confirm_cost": True})
    assert r.status_code == 200 and r.json() == result and got[0].confirm_cost is True


def test_task_state_route_404s_unknown_tasks(client, monkeypatch):
    monkeypatch.setattr(generic, "task_state", lambda db, tid: None)
    assert client.get("/api/v2/studio/generate/gt_nope").status_code == 404
    state = {"id": "gt_1", "status": "succeeded", "progress": 1.0, "error": None,
             "assets": [{"asset_id": "as_1", "url": "/media/a.png", "kind": "image", "mime": "image/png"}]}
    monkeypatch.setattr(generic, "task_state", lambda db, tid: state)
    assert client.get("/api/v2/studio/generate/gt_1").json() == state
