"""创作画布（ainer-studio ?view=flow）的后端：画布文档、搬画布、按计划取剧本、白模信息、上传。

不连库：纯函数直接测，接口用假库真跑一遍（同 test_blocking_api）。
"""
from __future__ import annotations

import copy
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.api.v2 import canvas as api
from app.models import ScriptDoc, ShotPlan, StudioBoard


def _doc(nodes=(), edges=(), **kw):
    return {"schema": "ainer.board/v1", "viewport": {"x": 0, "y": 0, "zoom": 1},
            "nodes": list(nodes), "edges": list(edges), **kw}


def _node(nid, kind, ref_id=None, typ="video", **data):
    return {"id": nid, "type": typ, "position": {"x": 10, "y": 20},
            "data": {"ref": {"kind": kind, "id": ref_id or nid}, "title": nid, **data}}


def _media_node(url, nid="n1"):
    return _node(nid, "free", typ="image", media={"url": url, "mime": "image/png"})


# ── 路由 ────────────────────────────────────────────────────────────────

_ROUTES = {
    ("GET", "/api/v2/studio/plans/{plan_id}/canvas"),
    ("PUT", "/api/v2/studio/plans/{plan_id}/canvas"),
    ("POST", "/api/v2/studio/plans/{plan_id}/canvas:adopt"),
    ("GET", "/api/v2/studio/plans/{plan_id}/script"),
    ("GET", "/api/v2/studio/box/{project_id}/doc"),
    ("POST", "/api/v2/studio/uploads"),
}


def test_canvas_router_has_every_route():
    have = {(m, r.path) for r in api.router.routes for m in getattr(r, "methods", ())}
    assert _ROUTES <= have


def test_app_registers_canvas_and_canvas_gen():
    """main.py 同时挂 canvas 与 canvas_gen（后者由 be-generate 写；还没写完时跳过）。"""
    pytest.importorskip("app.api.v2.canvas_gen")
    from app.main import app

    have = {(m, getattr(r, "path", "")) for r in app.routes for m in getattr(r, "methods", None) or ()}
    assert _ROUTES <= have
    assert any(p == "/api/v2/studio/generate" for _m, p in have)


# ── 文档校验 ────────────────────────────────────────────────────────────

def test_a_plain_doc_passes():
    doc = _doc([_node("shot:a", "shot", "a"), _media_node("/media/ab12.png")],
               [{"id": "e1", "source": "n1", "target": "shot:a", "data": {"kind": "ref"}}],
               hidden=["scene:x"])
    out = api.validate_doc(doc)
    assert [n["id"] for n in out["nodes"]] == ["shot:a", "n1"]
    assert out["hidden"] == ["scene:x"] and len(out["edges"]) == 1


def test_wrong_schema_is_rejected():
    with pytest.raises(api.CanvasDocError):
        api.validate_doc({**_doc(), "schema": "xyflow"})
    with pytest.raises(api.CanvasDocError):
        api.validate_doc({"nodes": [], "edges": []})


@pytest.mark.parametrize("url", [
    # 网关临时地址：几小时后就是死链（铁律 2）
    "https://gw.example.com/tmp/out.png?X-Amz-Signature=abc",
    # 写死主机的 /media：换部署地址就坏，前端该先过 media()
    "http://localhost:8100/media/ab12.png",
    "/media/../app/config.py",
    "/media/.env",
    "/media/sub/dir.png",
    "blob:http://localhost:5173/1234",
    "data:text/html;base64,PHNjcmlwdD4=",
    "",
])
def test_foreign_media_urls_are_rejected(url):
    with pytest.raises(api.CanvasDocError):
        api.validate_doc(_doc([_media_node(url)]))


@pytest.mark.parametrize("url", [
    "/media/0f3a9c.png", "/media/0f3a9c.webm", "/media/0f3a9c.jpg?v=2",
    "data:image/svg+xml;utf8,<svg/>", "data:image/png;base64,iVBORw0KGgo=",
])
def test_same_origin_and_small_data_urls_pass(url):
    api.validate_doc(_doc([_media_node(url)]))


def test_an_oversized_data_url_is_rejected():
    big = "data:image/png;base64," + "A" * (512 * 1024)
    with pytest.raises(api.CanvasDocError, match="512KB"):
        api.validate_doc(_doc([_media_node(big)]))


def test_live_nodes_keep_only_view_state():
    """派生节点的内容每次现取：board/cast 的字段混进文档就成了第二份数据源（铁律 1）。"""
    shot = _node("shot:a", "shot", "a", camera="cam1", pinned=True, live=False, role="shot",
                 orphan=True, description="镜头描述", media={"url": "/media/x.png"}, video_url="/media/v.mp4")
    free = _node("n1", "free", typ="text", text="自己写的", orphan=True)
    out = api.validate_doc(_doc([shot, free]))
    assert set(out["nodes"][0]["data"]) == {"ref", "title", "role", "camera", "pinned", "live"}
    assert out["nodes"][1]["data"] == {"ref": {"kind": "free", "id": "n1"}, "title": "n1", "text": "自己写的"}
    assert "orphan" in shot["data"], "不改入参"


def test_director_outputs_keep_their_media():
    """导演产物没有现取接口，前端靠 data.media 显示 —— 剥掉就再也显示不出来。"""
    n = _node("dout:j1:depth", "director_output", "sc1", job="j1", output="depth",
              media={"url": "/media/d.mp4", "mime": "video/mp4"})
    n["data"]["ref"] = {"kind": "director_output", "id": "sc1", "job": "j1", "output": "depth"}
    out = api.validate_doc(_doc([n]))
    assert out["nodes"][0]["data"]["media"]["url"] == "/media/d.mp4"


def test_derived_edges_are_not_stored():
    edges = [{"id": "d1", "source": "scene:s", "target": "shot:a", "data": {"kind": "flow", "derived": True}},
             {"id": "u1", "source": "n1", "target": "shot:a", "data": {"kind": "ref"}}]
    out = api.validate_doc(_doc([_node("shot:a", "shot", "a"), _media_node("/media/a.png")], edges))
    assert [e["id"] for e in out["edges"]] == ["u1"]


def test_limits_and_garbage_are_rejected():
    with pytest.raises(api.CanvasDocError, match="上限"):
        api.validate_doc(_doc([_node(f"n{i}", "free") for i in range(api.MAX_NODES + 1)]))
    with pytest.raises(api.CanvasDocError, match="重复"):
        api.validate_doc(_doc([_node("n1", "free"), _node("n1", "free")]))
    nan = _node("n1", "free")
    nan["position"] = {"x": float("nan"), "y": 0}
    with pytest.raises(api.CanvasDocError):
        api.validate_doc(_doc([nan]))
    huge = _node("n1", "free", typ="text", text="字" * (2 * 1024 * 1024))
    with pytest.raises(api.CanvasDocError, match="MB"):
        api.validate_doc(_doc([huge]))


def test_version_conflict():
    assert not api.version_conflict(None, 0)   # 没有画布，首存
    assert api.version_conflict(None, 2)
    assert not api.version_conflict(3, 3)
    assert api.version_conflict(3, 2)


# ── 读写接口：假库真跑 ──────────────────────────────────────────────────

class _Rows:
    def __init__(self, row):
        self.row = row

    def scalars(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return []


class _DB:
    def __init__(self, *plans, boards=None, docs=None):
        self.plans = {p.id: p for p in plans}
        self.boards: dict[str, StudioBoard] = dict(boards or {})
        self.docs = docs or {}
        self.commits = 0
        self.sql: list[str] = []

    def get(self, model, key):
        if model is ShotPlan:
            return self.plans.get(key)
        if model is ScriptDoc:
            return self.docs.get(key)
        return None

    def execute(self, stmt):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        self.sql.append(sql)
        if "studio_boards" in sql:
            return _Rows(next((b for pid, b in self.boards.items() if f"'{pid}'" in sql), None))
        return _Rows(None)

    def add(self, row):
        if isinstance(row, StudioBoard):
            self.boards[row.shot_plan_id] = row

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _plan(pid="sp1"):
    return SimpleNamespace(id=pid, script_doc_id="doc_" + pid)


def _put(db, base, doc, plan="sp1"):
    return api.put_canvas(plan, api.CanvasIn(base_version=base, doc=doc), db=db)


def test_a_plan_without_a_canvas_reads_as_version_zero():
    db = _DB(_plan())
    assert api.get_canvas("sp1", db=db) == {"version": 0, "doc": None, "updated_at": None}
    with pytest.raises(HTTPException) as err:
        api.get_canvas("nope", db=db)
    assert err.value.status_code == 404


def test_save_bumps_the_version_and_commits_before_answering():
    """get_db 的 commit 在响应之后才跑：前端拿到新版本号立刻再存，读到旧版本就是平白一个 409。"""
    db = _DB(_plan())
    out = _put(db, 0, _doc([_node("shot:a", "shot", "a")]))
    assert out["version"] == 1 and db.commits == 1
    assert db.boards["sp1"].id.startswith("brd_")
    assert out["doc"]["nodes"][0]["id"] == "shot:a"
    assert "FOR UPDATE" in db.sql[-1], "读版本要锁行，两个标签页同时存时后到的才会读到新版本"
    assert _put(db, 1, _doc())["version"] == 2
    assert api.get_canvas("sp1", db=db)["version"] == 2


def test_a_stale_save_gets_409_with_the_current_version():
    db = _DB(_plan())
    _put(db, 0, _doc())
    with pytest.raises(HTTPException) as err:
        _put(db, 0, _doc())
    assert err.value.status_code == 409
    assert err.value.detail["code"] == "CANVAS_VERSION_CONFLICT"
    assert err.value.detail["version"] == 1
    assert db.boards["sp1"].version == 1


def test_a_bad_doc_gets_422_and_nothing_is_written():
    db = _DB(_plan())
    with pytest.raises(HTTPException) as err:
        _put(db, 0, _doc([_media_node("https://gw.example.com/tmp/a.png")]))
    assert err.value.status_code == 422 and err.value.detail["code"] == "CANVAS_INVALID"
    assert "sp1" not in db.boards and db.commits == 0


# ── 换计划搬画布 ────────────────────────────────────────────────────────

def test_shots_map_by_scene_and_place_in_scene():
    """order_no 是整份计划连续编号：第一场多切一镜，后面每场全错一位。按「第几场第几镜」对。"""
    old = [("o1", 1, 1), ("o2", 1, 2), ("o3", 2, 3), ("o4", 2, 4), ("o5", None, 5)]
    new = [("n1", 1, 1), ("n2", 1, 2), ("n2b", 1, 3), ("n3", 2, 4), ("n4", 2, 5), ("n5", None, 6)]
    assert api.build_shot_map(old, new) == {"o1": "n1", "o2": "n2", "o3": "n3", "o4": "n4", "o5": "n5"}
    # 新计划这一场镜头少了：多出来的旧镜头映射不上
    assert api.build_shot_map([("a", 1, 1), ("b", 1, 2)], [("x", 1, 1)]) == {"a": "x"}


def test_scenes_map_by_order():
    assert api.build_scene_map([("s1", 1), ("s2", 2), ("s3", 3)], [("t1", 1), ("t2", 2)]) == {"s1": "t1", "s2": "t2"}


def _old_canvas():
    nodes = [
        _node("scene:s1", "scene", "s1", typ="text", title="场景 1"),
        _node("shot:o1", "shot", "o1", title="镜头 3"),
        _node("shot:o2", "shot", "o2", title="滑雪那一镜"),
        _node("shot:gone", "shot", "gone", title="镜头 9"),
        _node("entity:e1:front", "entity_view", "e1", typ="image", title="定妆照 · 林晓"),
        _node("note1", "free", typ="text", text="笔记"),
        _node("story:ch1", "story", "ch1", typ="text"),
    ]
    nodes[4]["data"]["ref"]["view"] = "front"
    edges = [
        {"id": "e:entity:e1:front->shot:o1", "source": "entity:e1:front", "target": "shot:o1",
         "data": {"kind": "identity"}},
        {"id": "e:note1->shot:gone", "source": "note1", "target": "shot:gone", "data": {"kind": "ref"}},
    ]
    return _doc(nodes, edges, hidden=["shot:o2", "shot:gone", "scene:s9"])


def test_remap_moves_refs_edges_and_hidden_and_counts_the_losses():
    old = _old_canvas()
    before = copy.deepcopy(old)
    r = api.remap_doc(old, {"o1": "n1", "o2": "n2"}, {"s1": "t1"}, numbers={"n1": 4, "n2": 5, "t1": 1})
    assert old == before, "不改入参"
    ids = [n["id"] for n in r.doc["nodes"]]
    assert ids == ["scene:t1", "shot:n1", "shot:n2", "entity:e1:front", "note1", "story:ch1"]
    by_id = {n["id"]: n for n in r.doc["nodes"]}
    assert by_id["shot:n1"]["data"]["ref"] == {"kind": "shot", "id": "n1"}
    assert by_id["shot:n1"]["position"] == {"x": 10, "y": 20}
    assert by_id["shot:n1"]["data"]["title"] == "镜头 4", "自动标题的序号跟着新镜头走"
    assert by_id["shot:n2"]["data"]["title"] == "滑雪那一镜", "人改过的标题不碰"
    assert (r.mapped, r.dropped, r.dropped_edges) == (3, 1, 1)
    assert r.doc["edges"] == [{"id": "e:entity:e1:front->shot:n1", "source": "entity:e1:front",
                               "target": "shot:n1", "data": {"kind": "identity"}}]
    assert r.doc["hidden"] == ["shot:n2"]
    api.validate_doc(r.doc)


def test_remap_follows_the_chapter_only_when_asked():
    r = api.remap_doc(_old_canvas(), {}, {}, story_map={"ch1": "ch2"})
    assert "story:ch2" in [n["id"] for n in r.doc["nodes"]]
    r = api.remap_doc(_old_canvas(), {}, {})
    assert "story:ch1" in [n["id"] for n in r.doc["nodes"]]


def test_adopt_refuses_to_overwrite_without_force(monkeypatch):
    rows = {"sp_old": [("o1", 1, 1), ("o2", 1, 2)], "sp_new": [("n1", 1, 1), ("n2", 1, 2)]}
    monkeypatch.setattr(api, "_shot_rows", lambda db, plan: rows[plan.id])
    monkeypatch.setattr(api, "_scene_rows", lambda db, plan: [("s1", 1)] if plan.id == "sp_old" else [("t1", 1)])
    src = StudioBoard(id="brd_old", shot_plan_id="sp_old", version=7, doc_json=_old_canvas())
    db = _DB(_plan("sp_old"), _plan("sp_new"), boards={"sp_old": src})

    out = api.adopt_canvas("sp_new", api.AdoptIn(from_plan_id="sp_old"), db=db)
    assert out["version"] == 1 and db.commits == 1
    assert (out["mapped"], out["dropped"]) == (3, 1)
    assert {"shot:n1", "shot:n2", "scene:t1"} <= {n["id"] for n in out["doc"]["nodes"]}
    assert src.version == 7, "来源画布不动"

    with pytest.raises(HTTPException) as err:
        api.adopt_canvas("sp_new", api.AdoptIn(from_plan_id="sp_old"), db=db)
    assert err.value.status_code == 409 and err.value.detail["code"] == "CANVAS_EXISTS"
    out = api.adopt_canvas("sp_new", api.AdoptIn(from_plan_id="sp_old", force=True), db=db)
    assert out["version"] == 2

    with pytest.raises(HTTPException) as err:
        api.adopt_canvas("sp_old", api.AdoptIn(from_plan_id="sp_new2"), db=db)
    assert err.value.status_code == 404


# ── 剧本、白模、上传 ────────────────────────────────────────────────────

def test_script_is_the_plans_own_version_through_doc_payload(monkeypatch):
    """按 plan.script_doc_id 取（不是激活剧本），复用 script._doc_payload。"""
    from app.api.v2 import script as script_api

    seen = []

    def fake_payload(db, doc):
        seen.append(doc.id)
        return {"id": doc.id, "version": 3, "chapter_id": "ch1", "scenes": [{
            "id": "s1", "order_no": 1, "title": "滑雪场", "time_of_day": "日", "location_text": "雪坡",
            "weather": "晴", "summary": "林晓冲下坡", "bg_asset_id": None,
            "blocks": [{"id": "b1", "seq_no": 1, "type": "dialogue", "text": "再快一点！",
                        "speaker": "林晓", "translatable": True}],
        }]}

    monkeypatch.setattr(script_api, "_doc_payload", fake_payload)
    db = _DB(_plan(), docs={"doc_sp1": SimpleNamespace(id="doc_sp1")})
    out = api.plan_script("sp1", db=db)
    assert seen == ["doc_sp1"]
    assert out["scenes"] == [{"id": "s1", "order_no": 1, "title": "滑雪场", "time_of_day": "日",
                              "location_text": "雪坡", "summary": "林晓冲下坡",
                              "blocks": [{"id": "b1", "type": "dialogue", "text": "再快一点！", "speaker": "林晓"}]}]


def test_box_info_names_the_cameras_and_can_leave_the_doc_out():
    doc = {"duration": 6.0, "cameras": [{"id": "cam_follow", "name": "跟拍"}, {"id": "cam_wide", "name": "远景"}]}
    p = SimpleNamespace(id="sc1", title="雪坡", thumb_url="http://localhost:8100/media/t.png", updated_at=None,
                        compiled_json=doc, diagnostics_json={"ok": True, "summary": {"objects": 12}})
    out = api.box_info(p, "run_1")
    assert out["cameras"] == [{"id": "cam_follow", "name": "跟拍"}, {"id": "cam_wide", "name": "远景"}]
    assert out["duration"] == 6.0 and out["objects"] == 12 and out["active_run"] == "run_1"
    assert out["doc"] is doc and out["ok"] is True
    assert api.box_info(p, None, include_doc=False)["doc"] is None
    # 编译失败（没有 doc）时退到诊断摘要
    broken = SimpleNamespace(**{**vars(p), "compiled_json": None,
                                "diagnostics_json": {"ok": False, "summary": {
                                    "duration": 4, "cameras": [{"id": "c1", "name": "主"}]}}})
    out = api.box_info(broken, None)
    assert out["cameras"] == [{"id": "c1", "name": "主"}] and out["duration"] == 4 and out["doc"] is None


def test_upload_kinds():
    assert api.upload_kind("image/png") is not None
    assert api.upload_kind("video/webm") is not None
    assert api.upload_kind("audio/mpeg") is not None
    assert api.upload_kind("image/svg+xml") is None
    assert api.upload_kind("text/html") is None
    assert api.same_origin("http://localhost:8100/media/ab.png") == "/media/ab.png"


def _file(raw: bytes, name: str, mime: str) -> UploadFile:
    return UploadFile(io.BytesIO(raw), filename=name, headers=Headers({"content-type": mime}))


def test_upload_stores_an_asset_and_answers_with_a_same_origin_url(monkeypatch):
    stored = []

    def fake_store(raw, *, mime):
        stored.append(mime)
        return {"url": "http://localhost:8100/media/abc.png", "sha256": "abc", "mime": mime, "bytes": len(raw)}

    monkeypatch.setattr(api, "store_bytes", fake_store)
    added = []
    db = _DB()
    db.add = added.append  # type: ignore[method-assign]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    out = api.upload(_file(png, "a.png", "image/png"), novel_id=None, db=db)
    assert out["url"] == "/media/abc.png" and out["mime"] == "image/png"
    assert added[0].source.value == "uploaded" and db.commits == 1

    with pytest.raises(HTTPException) as err:
        api.upload(_file(b"<svg onload=alert(1)>", "x.svg", "image/svg+xml"), novel_id=None, db=db)
    assert err.value.status_code == 422
    assert stored == ["image/png"], "不收的文件不该落盘"


def test_the_routes_work_over_http():
    """路径里的冒号（canvas:adopt）、409/422 的错误体、multipart 上传，走一遍真的 HTTP 层。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.db import get_db

    db = _DB(_plan("sp1"), _plan("sp2"))
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    url = "/api/v2/studio/plans/sp1/canvas"
    assert c.put(url, json={"base_version": 0, "doc": _doc()}).json()["version"] == 1
    r = c.put(url, json={"base_version": 0, "doc": _doc()})
    # 前端 api.ts 的 call() 从 detail.message 取提示、按 409 进「有冲突」
    assert r.status_code == 409 and r.json()["detail"]["version"] == 1
    assert c.put(url, json={"base_version": -1, "doc": _doc()}).status_code == 422
    r = c.post("/api/v2/studio/plans/sp2/canvas:adopt", json={"from_plan_id": "sp1"})
    assert r.status_code == 200 and r.json()["version"] == 1
    r = c.post("/api/v2/studio/uploads", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 422
