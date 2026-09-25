"""站位读写 —— 3D 导演台写回来的那份数据。"""
from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.api.v2 import blocking as api


def test_figures_outside_the_frame_are_rejected():
    with pytest.raises(ValidationError):
        api.FigureIn(entity_id="a", x=1.4, top=0.1, bottom=0.9, width=0.1)


def test_a_zero_width_figure_is_rejected():
    with pytest.raises(ValidationError):
        api.FigureIn(entity_id="a", x=0.5, top=0.1, bottom=0.9, width=0)


def test_medium_shots_may_put_the_feet_below_the_frame():
    """中景的腿在画外 —— 脚底 > 1 是合法的。"""
    api.FigureIn(entity_id="a", x=0.5, top=0.05, bottom=1.7, width=0.2)


def test_hand_placed_blocking_survives_rebinding():
    """3D 台手摆过的站位（source=stage）不能被重新绑定时的自动摆位盖掉。"""
    from app.pipelines import frame_compose

    src = inspect.getsource(frame_compose.bind_and_compose)
    assert '.get("source") != "stage"' in src


def test_moving_people_invalidates_the_old_frame():
    src = inspect.getsource(api.put_blocking)
    assert '"needs_regeneration"' in src


def test_new_people_cannot_be_added_from_the_stage():
    """每人的区域要带他自己的脸和外观 —— 凭空加一个人，
    那块区域只有人偶和空描述，模型会在那里画一个陌生人。"""
    src = inspect.getsource(api.put_blocking)
    assert "UNKNOWN_FIGURE" in src


def test_routes_are_registered():
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v2/shots/{shot_id}/blocking" in paths


# ── 导演台写回：真跑一遍接口（假库，只有一镜两帧）─────────────

from types import SimpleNamespace


class _Rows:
    def __init__(self, row):
        self.row = row

    def scalars(self):
        return self

    def first(self):
        return self.row


class _FakeDB:
    def __init__(self, shot, first, last):
        self.shot, self.first, self.last = shot, first, last

    def get(self, model, key):
        return self.shot if key == self.shot.id else None

    def execute(self, stmt):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        return _Rows(self.last if "'last'" in sql else self.first)

    def flush(self):
        pass

    def commit(self):
        self.committed = True


def _auto_figures():
    return [
        {"entity_id": "a", "name": "甲", "x": 0.3, "top": 0.1, "bottom": 0.9, "width": 0.15,
         "prompt": "black jacket", "face_url": "http://x/a.png"},
        {"entity_id": "b", "name": "乙", "x": 0.7, "top": 0.1, "bottom": 0.9, "width": 0.15,
         "prompt": "white shirt", "face_url": "http://x/b.png"},
    ]


def _world():
    shot = SimpleNamespace(id="s1", camera_json={"lens": "35mm"}, video_asset_id="vid1")
    first = SimpleNamespace(asset_id="img1", params_json={"regional": {
        "source": "auto", "plate_url": "http://x/plate.png", "figures": _auto_figures()}})
    last = SimpleNamespace(asset_id="img2", params_json={})
    return shot, first, last, _FakeDB(shot, first, last)


def _put(db, figures, **kw):
    body = api.BlockingIn(figures=[api.FigureIn(**{k: f[k] for k in (
        "entity_id", "x", "top", "bottom", "width")}) for f in figures], **kw)
    return api.put_blocking("s1", body, db=db)


_RIG = {"move": "orbit_left", "video_move": "orbit_left", "shot_size": "ms",
        "description_en": "Camera orbits 60 degrees to the left around the subject."}


def test_an_actor_moved_out_of_frame_can_be_moved_back():
    """起幅里可以少人，但他仍在这场戏里 —— 从前按当前 figures 认人，
    摆出画一次，下次保存带上他就被当成「计划外的人」拒掉。"""
    _shot, _first, _last, db = _world()
    _put(db, _auto_figures()[:1])
    out = _put(db, _auto_figures())
    assert [f["entity_id"] for f in out["figures"]] == ["a", "b"]
    assert [f["entity_id"] for f in api.get_blocking("s1", db=db)["cast"]] == ["a", "b"]


def test_saving_without_changes_invalidates_nothing():
    """打开导演台、什么都没动、点了保存 —— 首帧、尾帧、视频都不该变旧。"""
    shot, first, last, db = _world()
    _put(db, _auto_figures())
    assert not first.params_json.get("needs_regeneration")
    assert not last.params_json.get("needs_regeneration")
    assert shot.video_asset_id == "vid1"


def test_moving_someone_invalidates_the_frames_and_the_video():
    """尾帧是在首帧上编辑出来的，视频吃首尾帧 —— 首帧重出，它们都是旧的。"""
    shot, first, last, db = _world()
    moved = _auto_figures()
    moved[0]["x"] = 0.2
    _put(db, moved)
    assert first.params_json["needs_regeneration"] is True
    assert last.params_json["needs_regeneration"] is True
    assert shot.video_asset_id is None


def test_a_new_camera_move_redoes_last_frame_and_video_but_not_the_first():
    """落幅跟着相机走，起幅没动 —— 首帧不必重出。"""
    shot, first, last, db = _world()
    _put(db, _auto_figures(), camera=_RIG, stage3d={"version": 1})
    assert shot.camera_json == {"lens": "35mm", "rig": _RIG}
    assert not first.params_json.get("needs_regeneration")
    assert last.params_json["needs_regeneration"] is True
    assert shot.video_asset_id is None
    back = api.get_blocking("s1", db=db)
    assert back["camera"] == _RIG and back["stage3d"] == {"version": 1}


def test_reset_puts_the_auto_blocking_back_right_away():
    """从前只把标签改成 auto，看到的仍是手摆的站位，要等下次绑定才回去。"""
    shot, first, _last, db = _world()
    moved = _auto_figures()
    moved[1]["x"] = 0.9
    _put(db, moved, camera=_RIG, stage3d={"version": 1})
    out = api.reset_blocking("s1", db=db)
    plan = first.params_json["regional"]
    assert out["source"] == "auto" and plan["source"] == "auto"
    assert [f["x"] for f in plan["figures"]] == [0.3, 0.7]
    assert "auto_figures" not in plan and "stage3d" not in first.params_json
    assert shot.camera_json == {"lens": "35mm"}


def test_rebinding_keeps_the_geometry_but_refreshes_identity():
    """手摆的是站位；脸、外观、动作跟设定和表演单走。表演单删掉的人从画面里拿掉。"""
    from app.pipelines.frame_compose import stage_plan_refreshed

    kept = {"source": "stage", "figures": [
        {**_auto_figures()[0], "x": 0.12, "prompt": "old look"},
        {**_auto_figures()[1], "x": 0.88}]}
    fresh = _auto_figures()[:1]
    fresh[0]["prompt"] = "new look"
    out = stage_plan_refreshed(kept, {"source": "auto", "plate_url": "p", "figures": fresh})
    assert out["source"] == "stage"
    assert [(f["entity_id"], f["x"], f["prompt"]) for f in out["figures"]] == [("a", 0.12, "new look")]
    assert out["auto_figures"] == fresh


def test_the_stage_framing_sets_the_shot_size_in_the_prompt():
    """人偶按台上的相机投影；提示词还写分镜的 close-up，两路条件就打架。"""
    from app.pipelines.frame_compose import framed_size

    shot = SimpleNamespace(shot_size="cu", camera_json={"rig": _RIG})
    assert framed_size({"regional": {"source": "stage"}}, shot) == "ms"
    assert framed_size({"regional": {"source": "auto"}}, shot) == "cu"


def test_the_camera_move_reaches_the_video_request():
    from app.pipelines.cut import apply_rig

    out = apply_rig({"prompt": "he raises the knife"}, _RIG)
    assert out["camera"] == {"move": "orbit_left"}
    assert out["prompt"].startswith("Camera orbits 60 degrees")
    assert out["prompt"].endswith("he raises the knife")
    # 贝塞尔、摇臂这些工作台不认的词：没有结构化参数，只靠描述
    custom = apply_rig({"prompt": "p"}, {"move": "custom", "video_move": None,
                                         "description_en": "Camera moves along a curved path."})
    assert "camera" not in custom and custom["prompt"].startswith("Camera moves along")
    # 静止镜只给结构化的 static，不写一句「不动」去抢动作描述的位置
    still = apply_rig({"prompt": "p"}, {"move": "static", "video_move": "static",
                                        "description_en": "Static locked-off camera."})
    assert still == {"prompt": "p", "camera": {"move": "static"}}
    assert apply_rig({"prompt": "p"}, None) == {"prompt": "p"}


def test_the_last_frame_is_told_how_the_camera_moved():
    from app.pipelines.frame_compose import camera_change

    assert camera_change(_RIG).startswith("Camera change: Camera orbits")
    assert camera_change({"move": "static", "description_en": "Static."}) == ""
    assert camera_change({"move": "handheld", "description_en": "Handheld."}) == ""
    assert camera_change(None) == ""


def test_single_person_shots_still_take_a_camera_move():
    """运镜不只属于多人镜：单人、特写的首帧不按站位出，但运镜照样交给视频和尾帧。"""
    from fastapi import HTTPException

    shot, first, last, db = _world()
    first.params_json = {}          # 没有分区计划
    with pytest.raises(HTTPException) as err:
        _put(db, [])
    assert err.value.status_code == 409
    out = _put(db, [], camera=_RIG, stage3d={"version": 1})
    assert out["regional"] is False and out["source"] is None
    assert shot.camera_json["rig"] == _RIG
    assert "regional" not in first.params_json and first.params_json["stage3d"] == {"version": 1}
    assert last.params_json["needs_regeneration"] is True and shot.video_asset_id is None


def test_the_save_is_committed_before_the_response():
    """get_db 的 commit 在响应发出之后才跑。导演台保存一返回就发出图请求，
    出图读到旧站位、再整段覆盖回去，手摆的站位就没了。"""
    _shot, _first, _last, db = _world()
    _put(db, _auto_figures(), camera=_RIG)
    assert getattr(db, "committed", False)
    db.committed = False
    api.reset_blocking("s1", db=db)
    assert db.committed
