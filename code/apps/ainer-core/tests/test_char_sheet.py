"""标准定妆照：16 格规格与参考图一致、提示词、依赖分批、拼版、下游挑格、编排（不连库不连网关）、接口。"""
from __future__ import annotations

import threading

import pytest
from PIL import Image, ImageDraw

from app.pipelines import char_sheet as cs

BASE = "http://localhost:8100"


def _figure(w: int = 512, h: int = 768, cx: int = 256, color=(180, 60, 60)) -> Image.Image:
    """浅灰底上一个色块小人（头是浅肤色：和浅灰底亮度差很小，专门测特写不切头）。"""
    im = Image.new("RGB", (w, h), (205, 207, 210))
    d = ImageDraw.Draw(im)
    d.ellipse([cx - 40, 60, cx + 40, 150], fill=(230, 190, 160))
    d.rectangle([cx - 70, 150, cx + 70, 470], fill=color)
    d.rectangle([cx - 60, 470, cx + 60, 720], fill=(50, 50, 70))
    return im


@pytest.fixture(autouse=True)
def _clean():
    cs._JOBS.clear()
    cs._font.cache_clear()
    yield
    cs._JOBS.clear()
    cs._font.cache_clear()


# ── 规格 ────────────────────────────────────────────────────────────────────

def test_spec_matches_the_reference_sheet():
    assert [s.title for s in cs.SECTIONS] == ["角色全景前后侧三视图", "角色面部多视角特写", "九宫格表情特写"]
    assert len(cs.PANEL_KEYS_STANDARD) == 16 and len(set(cs.PANEL_KEYS_STANDARD)) == 16
    assert set(cs.LABELS) == set(cs.PANEL_KEYS_STANDARD) == set(cs.SOURCES)
    labels = [[cs.LABELS[k] for k in s.keys] for s in cs.SECTIONS]
    assert labels == [["前视图", "后视图", "侧视图"],
                      ["正面特写", "左侧特写", "右侧特写", "后脑特写"],
                      ["喜", "怒", "哀", "乐", "惊", "恐", "思", "厌", "疑"]], "九宫格按 喜怒哀 / 乐惊恐 / 思厌疑 排"
    assert [s.cols for s in cs.SECTIONS] == [3, 2, 3]
    assert set(cs.PANEL_KEYS_QUICK) == {"body_front", "body_side", "body_back", "face_front"}
    assert cs.panel_keys("quick") == cs.PANEL_KEYS_QUICK and cs.panel_keys("bogus") == cs.PANEL_KEYS_STANDARD


def test_prompts_are_english_same_person_and_never_say_character_sheet():
    for key in cs.PANEL_KEYS_STANDARD:
        p = cs.panel_prompt(key, look="red ski suit, short black hair")
        assert p.isascii(), f"{key} 的提示词要全英文"
        assert "same person" in p
        low = p.lower()
        assert "character sheet" not in low and "turnaround" not in low, "这类词会让 klein 滑向动漫"
        assert "no text" in low
    assert "red ski suit" in cs.panel_prompt("body_front", "red ski suit")
    assert "Keep the same outfit" in cs.panel_prompt("body_front", ""), "没给造型就沿用照片里的穿着"
    assert "facing left" in cs.panel_prompt("body_side")
    assert "back to the camera" in cs.panel_prompt("body_back")
    assert "hand resting on the chin" in cs.panel_prompt("expr_think")
    with pytest.raises(KeyError):
        cs.panel_prompt("nope")


def test_layers_follow_the_dependencies():
    std = cs.plan_layers(cs.PANEL_KEYS_STANDARD)
    assert std[0] == ["body_front"]
    assert std[1] == ["body_back", "body_side", "face_front"], "后、侧从前视图改；正脸以照片为底、前视图当参考"
    assert len(std[2]) == 12 and "face_front" not in std[2]
    assert cs.plan_layers(cs.PANEL_KEYS_QUICK) == [["body_front"], ["body_back", "body_side", "face_front"]]
    with pytest.raises(ValueError):
        cs.plan_layers(["face_left"]), "依赖不在要出的格里不能悄悄出一张没底图的"


def test_seeds_are_fixed_and_distinct_per_panel():
    seeds = [cs.panel_seed(100, k) for k in cs.PANEL_KEYS_STANDARD]
    assert seeds == list(range(100, 116))
    assert cs.panel_seed(100, "face_front") == cs.panel_seed(100, "face_front")


def test_edit_payload_marks_extra_refs_as_identity_and_pins_the_size():
    p = cs._edit_payload("Do it.", f"{BASE}/media/a.png", [f"{BASE}/media/b.png", f"{BASE}/media/a.png", ""], 7)
    assert p["image"] == {"url": f"{BASE}/media/a.png"}
    assert (p["width"], p["height"]) == (512, 768) and p["style"] == "photoreal"
    assert p["params"] == {"seed": 7, "style": "photoreal", "ref_megapixels": 0.4}
    assert [r["ref"]["url"] for r in p["reference_images"]] == [f"{BASE}/media/b.png"], "和底图相同的、空的不送"
    assert all(r["identity"] is True for r in p["reference_images"]), "网关只收 identity=true 的附加参考"


def test_long_ref_ids_are_hashed_to_fit_the_column():
    assert cs._short_ref_id("brd_1:node") == "brd_1:node"
    long = cs._short_ref_id("brd_01HZZZZZZZZZZZZZZZZZZZZZZZ:idea:sheet")
    assert long.startswith("h:") and len(long) == 32
    assert long == cs._short_ref_id("brd_01HZZZZZZZZZZZZZZZZZZZZZZZ:idea:sheet")


# ── 拼版 ────────────────────────────────────────────────────────────────────

def test_compose_standard_and_quick_sheets():
    panels = {k: _figure(cx=200 + 20 * i) for i, k in enumerate(cs.PANEL_KEYS_STANDARD)}
    std = cs.compose_sheet(panels, "唐小山", "standard")
    assert std.mode == "RGB"
    assert 2200 <= std.width <= 2600 and 900 <= std.height <= 1400, std.size
    assert std.getpixel((5, 5)) == cs.BG
    quick = cs.compose_sheet({k: panels[k] for k in cs.PANEL_KEYS_QUICK}, "", "quick")
    assert quick.height == std.height, "快速版和标准版等高，只是更窄"
    assert 1200 <= quick.width < std.width


def test_compose_marks_missing_panels_and_works_without_system_fonts(monkeypatch):
    monkeypatch.setattr(cs, "_FONT_FILES", ("/nonexistent/font.ttc",))
    monkeypatch.setattr(cs, "_FONT_GLOBS", ())
    cs._font.cache_clear()
    img = cs.compose_sheet({"body_front": _figure()}, "名字", "standard")
    assert img.width > 2000
    empty = cs.compose_sheet({}, "", "quick")
    assert empty.size[0] > 1000


def test_fit_centres_on_the_subject_and_keeps_the_head():
    off = _figure(cx=130)                                   # 人站在左边
    tile = cs._fit(off, (230, 500), head=False)
    mid = tile.getpixel((115, 250))
    assert mid != (205, 207, 210), "裁出来的中间应该是人，不是背景"
    face = cs._fit(off, (300, 350), head=True)
    top_band = [face.getpixel((x, y)) for y in range(0, 60, 4) for x in range(0, 300, 6)]
    assert any(p == (230, 190, 160) for p in top_band), "特写从头顶上方开始，不切头"
    assert face.getpixel((150, 0)) == (205, 207, 210), "头顶上留一点背景"
    plain = Image.new("RGB", (512, 768), (205, 207, 210))
    assert cs._fit(plain, (200, 200), head=True).size == (200, 200), "找不到人就居中裁"


# ── 下游挑格 ────────────────────────────────────────────────────────────────

def test_identity_panels_picks_what_downstream_needs():
    panels = [{"key": k, "label": cs.LABELS[k], "url": f"/media/{k}.png"} for k in cs.PANEL_KEYS_STANDARD]
    assert [p["key"] for p in cs.identity_panels(panels, "character")] == ["body_front", "face_front", "body_side"]
    assert [p["key"] for p in cs.identity_panels(panels, "base")] == ["body_front"]
    # 执行器存在 run.extra 里的形状：{label: key, media}
    extra = [{"label": "face_front", "media": {"url": "/media/f.png"}},
             {"label": "body_back", "media": {"url": "/media/b.png"}}]
    assert [p["label"] for p in cs.identity_panels(extra, "character")] == ["face_front"], "有哪个给哪个"
    assert cs.identity_panels(extra, "base")[0]["media"]["url"] == "/media/f.png", "没有前视图就退到正脸"
    assert cs.identity_panels([{"label": "侧视图", "url": "/media/s.png"}], "character")[0]["url"] == "/media/s.png"
    assert cs.identity_panels([], "character") == [] and cs.identity_panels(None, "base") == []
    assert cs.identity_panels([{"label": "junk"}, "bad"], "base") == []  # type: ignore[list-item]


# ── 媒体地址 ────────────────────────────────────────────────────────────────

def test_media_urls(monkeypatch, tmp_path):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "media_dir", str(tmp_path))
    monkeypatch.setattr(s, "public_base_url", "http://core:8100/")
    (tmp_path / "p.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    assert cs.same_origin("http://localhost:8100/media/x.png") == "/media/x.png"
    assert cs.same_origin("/media/x.png") == "/media/x.png"
    assert cs.media_name("/media/../etc") is None and cs.media_name("https://x.com/a.png") is None
    assert cs.resolve_person("/media/p.png") == "http://core:8100/media/p.png", "网关要绝对地址"
    assert cs.resolve_person("http://localhost:8100/media/p.png") == "http://core:8100/media/p.png"
    with pytest.raises(cs.SheetError):
        cs.resolve_person("https://example.com/p.png")
    with pytest.raises(cs.SheetError):
        cs.resolve_person("/media/missing.png")
    with pytest.raises(cs.SheetError):
        cs.resolve_person("")
    import base64
    import io

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, format="PNG")
    got = cs.resolve_person("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
    assert got.startswith("http://core:8100/media/") and (tmp_path / got.rsplit("/", 1)[1]).is_file()


# ── 编排（假网关） ──────────────────────────────────────────────────────────

class _Fake:
    """替掉提交 / 等待 / 取图 / 存图：只看编排对不对。"""

    def __init__(self, monkeypatch, fail: dict[str, str] | None = None):
        self.payloads: list[tuple[str, dict]] = []
        self.by_tid: dict[str, str] = {}
        self.stored: list[dict] = []
        self.fail = fail or {}
        monkeypatch.setattr(cs, "resolve_person", lambda url: f"{BASE}/media/person.png")
        monkeypatch.setattr(cs, "_route", lambda db: object())
        monkeypatch.setattr(cs, "_submit", self.submit)
        monkeypatch.setattr(cs, "_await", self.wait)
        monkeypatch.setattr(cs, "_asset_of", self.asset_of)
        monkeypatch.setattr(cs, "_load_image", lambda url: _figure())
        monkeypatch.setattr(cs, "_store_sheet", self.store)

    def key_of(self, payload: dict) -> str:
        return next(k for k in cs.PANEL_KEYS_STANDARD if cs.panel_prompt(k, "look") == payload["prompt"]
                    or cs.panel_prompt(k, "") == payload["prompt"])

    def submit(self, db, route, payload, *, ref_kind, ref_id, force):
        tid = f"gt_{len(self.payloads)}"
        key = self.key_of(payload)
        self.payloads.append((key, payload))
        self.by_tid[tid] = key
        return tid

    def wait(self, db, tids, *, on_done, cancelled):
        for tid in tids:
            on_done(tid, tid)
        return []

    def asset_of(self, db, task):
        key = self.by_tid[task]
        if key in self.fail:
            raise cs.SheetError(self.fail[key])
        return f"as_{key}", f"{BASE}/media/{key}.png"

    def store(self, db, img, meta):
        self.stored.append({"size": img.size, **meta})
        return "as_sheet", f"{BASE}/media/sheet.png"


def test_generate_sheet_runs_layer_by_layer(monkeypatch):
    fake = _Fake(monkeypatch)
    progress: list[tuple[int, str]] = []
    res = cs.generate_sheet(None, person_url="/media/p.png", name="唐小山", look="look", seed=500,
                            on_progress=lambda p, s: progress.append((p, s)))
    order = [k for k, _ in fake.payloads]
    assert order[0] == "body_front" and set(order[1:4]) == {"body_back", "body_side", "face_front"}
    assert len(order) == 16
    pay = dict(fake.payloads)
    assert pay["body_front"]["image"]["url"] == f"{BASE}/media/person.png"
    assert pay["body_back"]["image"]["url"] == f"{BASE}/media/body_front.png"
    assert pay["face_front"]["image"]["url"] == f"{BASE}/media/person.png", "脸以人物照片为底图"
    assert [r["ref"]["url"] for r in pay["face_front"]["reference_images"]] == [f"{BASE}/media/body_front.png"]
    assert pay["expr_doubt"]["image"]["url"] == f"{BASE}/media/face_front.png"
    assert pay["expr_doubt"]["params"]["seed"] == 515

    assert res["sheet"] == {"asset_id": "as_sheet", "url": "/media/sheet.png"}, "给出去的一律同源"
    assert [p["key"] for p in res["panels"]] == cs.PANEL_KEYS_STANDARD
    assert all(p["url"].startswith("/media/") and p["label"] == cs.LABELS[p["key"]] for p in res["panels"])
    assert res["missing"] == [] and res["seed"] == 500
    assert fake.stored[0]["preset"] == "standard" and len(fake.stored[0]["panels"]) == 16

    pcts = [p for p, _ in progress]
    assert pcts == sorted(pcts) and pcts[-1] == 100 and progress[0] == (0, "三视图 0/3")
    assert ("三视图 3/3" in [s for _, s in progress]) and ("表情 9/9" in [s for _, s in progress])


def test_quick_preset_only_submits_four(monkeypatch):
    fake = _Fake(monkeypatch)
    res = cs.generate_sheet(None, person_url="/media/p.png", preset="quick")
    assert sorted(k for k, _ in fake.payloads) == sorted(cs.PANEL_KEYS_QUICK)
    assert res["preset"] == "quick" and len(res["panels"]) == 4 and res["seed"] == cs.DEFAULT_SEED


def test_failed_face_skips_its_dependents_but_still_composes(monkeypatch):
    fake = _Fake(monkeypatch, fail={"face_front": "网关报错"})
    res = cs.generate_sheet(None, person_url="/media/p.png")
    assert len(fake.payloads) == 4, "正脸没出成，从它改的 12 格不交"
    miss = {m["key"]: m["error"] for m in res["missing"]}
    assert miss["face_front"] == "网关报错"
    assert miss["expr_joy"] == "上游「正面特写」没出成" and len(miss) == 13
    assert res["sheet"]["url"] == "/media/sheet.png" and len(res["panels"]) == 3


def test_failed_front_view_fails_the_sheet(monkeypatch):
    _Fake(monkeypatch, fail={"body_front": "超时"})
    with pytest.raises(cs.SheetError, match="前视图没出成"):
        cs.generate_sheet(None, person_url="/media/p.png")


def test_cancel_stops_before_submitting(monkeypatch):
    fake = _Fake(monkeypatch)
    with pytest.raises(cs.SheetCancelled):
        cs.generate_sheet(None, person_url="/media/p.png", cancelled=lambda: True)
    assert fake.payloads == []


# ── 后台任务与接口 ──────────────────────────────────────────────────────────

class _FakeDb:
    def rollback(self):
        pass

    def close(self):
        pass


def _join(jid: str) -> None:
    for t in threading.enumerate():
        if t.name == f"char-sheet-{jid}":
            t.join(3)


def test_job_runs_in_the_background(monkeypatch):
    import app.db

    monkeypatch.setattr(app.db, "SessionLocal", _FakeDb)

    started = threading.Event()

    def fake_generate(db, **kw):
        kw["on_progress"](50, "面部特写 2/4")
        started.wait(2)
        return {"sheet": {"asset_id": "as_s", "url": "/media/s.png"}, "panels": [{"key": "body_front"}], "missing": []}

    monkeypatch.setattr(cs, "generate_sheet", fake_generate)
    st = cs.start({"person_url": f"{BASE}/media/p.png", "preset": "quick"})
    assert st["state"] == "running" and st["id"].startswith("csheet_")
    started.set()
    _join(st["id"])
    done = cs.job(st["id"])
    assert done["state"] == "done" and done["progress"] == 100 and done["sheet"]["url"] == "/media/s.png"


def test_job_failure_lands_in_state(monkeypatch):
    import app.db

    monkeypatch.setattr(app.db, "SessionLocal", _FakeDb)

    def boom(db, **kw):
        raise cs.SheetError("flux2-klein-4b-edit 不能用")

    monkeypatch.setattr(cs, "generate_sheet", boom)
    st = cs.start({"person_url": f"{BASE}/media/p.png"})
    _join(st["id"])
    assert cs.job(st["id"])["state"] == "failed" and "不能用" in cs.job(st["id"])["error"]
    assert cs.job("nope") is None


def test_router_routes():
    from app.api.v2.char_sheet import router

    got = {(r.path, m) for r in router.routes for m in getattr(r, "methods", ())}
    assert ("/api/v2/studio/char-sheets", "POST") in got
    assert ("/api/v2/studio/char-sheets/{job_id}", "GET") in got


def test_router_rejects_bad_person_up_front():
    from fastapi import HTTPException

    from app.api.v2.char_sheet import CharSheetIn, MediaIn, _person_url

    with pytest.raises(HTTPException) as e:
        _person_url(None, MediaIn(url="https://example.com/p.png"))  # type: ignore[arg-type]
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        _person_url(None, MediaIn())  # type: ignore[arg-type]
    with pytest.raises(Exception):
        CharSheetIn(person=MediaIn(url="/media/p.png"), preset="huge")
