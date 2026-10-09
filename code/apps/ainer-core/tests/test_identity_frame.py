"""3D 导演出片的身份首帧：人物色块轮廓 → 分区身份的矩形区域。"""
from __future__ import annotations

from PIL import Image, ImageDraw

from app.director import identity_frame as F


def _mask(tmp_path, name, box, size=(200, 100)):
    im = Image.new("L", size, 0)
    ImageDraw.Draw(im).rectangle(box, fill=255)
    p = tmp_path / f"{name}.png"
    im.save(p)
    return p


def test_regions_pad_the_silhouette_and_split_overlaps_at_the_midline(tmp_path):
    """外扩留出头发、手；两个人外扩后重叠时从两人中心的中线切开，不互相压（压了会串脸）。"""
    masks = {"p1": _mask(tmp_path, "p1", (40, 20, 79, 99)), "p2": _mask(tmp_path, "p2", (84, 20, 123, 99))}
    boxes = F._boxes(masks, 200, 100)
    a, b = boxes["p1"], boxes["p2"]
    assert a[0] < 40 and b[2] > 123                  # 外扩了
    assert a[2] == b[0]                               # 中线切开，不重叠
    assert 79 <= a[2] <= 84


def test_people_not_in_frame_get_no_region(tmp_path):
    masks = {"p1": _mask(tmp_path, "p1", (0, 0, 0, 0)), "p2": _mask(tmp_path, "p2", (84, 20, 123, 99))}
    Image.new("L", (200, 100), 0).save(masks["p1"])   # 全黑：被挡住或在画面外
    assert set(F._boxes(masks, 200, 100)) == {"p2"}


# ── 做不出身份首帧时：不悄悄退回纯文字出人 ────────────────────

import json
from types import SimpleNamespace

import pytest


class _DB:
    def __init__(self, names=None):
        self.names = names or {}

    def get(self, _model, key):
        return SimpleNamespace(display_name=self.names[key]) if key in self.names else None

    def commit(self):
        pass

    def rollback(self):
        pass


def _previs(tmp_path, monkeypatch):
    monkeypatch.setattr(F.config, "job_dir", lambda _jid: tmp_path)
    Image.new("RGB", (200, 100), (128, 128, 128)).save(tmp_path / "first_frame.png")
    (tmp_path / "masks").mkdir()
    _mask(tmp_path / "masks", "p1", (40, 20, 79, 99))
    (tmp_path / "visibility.json").write_text(json.dumps(
        {"actors": {"p1": {"mask": "masks/p1.png", "coverage": [0.05]}}}), encoding="utf-8")
    return SimpleNamespace(id="djob_x", input_json={"render_plan": {"output_resolution": [200, 100]}})


def test_nobody_in_the_shot_means_nothing_to_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(F.config, "job_dir", lambda _jid: tmp_path)
    assert F.render(_DB(), SimpleNamespace(id="djob_x", input_json={}), {"cast": []}) is None


def test_missing_previs_masks_is_an_error_not_a_silent_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(F.config, "job_dir", lambda _jid: tmp_path)
    with pytest.raises(F.IdentityFrameError, match="色块"):
        F.render(_DB(), SimpleNamespace(id="djob_x", input_json={}), {"cast": ["ent_a"], "actors": ["p1"]})


def test_a_person_on_screen_without_a_face_reference_is_named(tmp_path, monkeypatch):
    """有人在画面里却没有正脸参考：出来的会是随便一张脸（实看到过卡通大头），报出是谁缺参考。"""
    job = _previs(tmp_path, monkeypatch)
    monkeypatch.setattr(F, "_face_ref", lambda *a, **k: None)
    with pytest.raises(F.IdentityFrameError, match="谢文东"):
        F.render(_DB({"ent_a": "谢文东"}), job, {"cast": ["ent_a"], "actors": ["p1"], "looks": ["a boy"]})


# ── 首帧画成动作的起势 ────────────────────────────────────

def test_staging_reads_the_opening_action_and_names_the_target_by_screen_position():
    """镜 1 实跑：两人冲中间的人挥拳；首帧要画成出拳的起势，不是外貌描述里的插兜。"""
    proto = {"actors": [{"id": "p1"}, {"id": "p2"}, {"id": "p3", "pose": "stand"}],
             "timeline": [{"time": 0.0, "op": "actor.play_action", "actor": "p2", "action": "right_punch",
                           "target_actor": "p1"},
                          {"time": 0.0, "op": "actor.play_action", "actor": "p3", "action": "left_punch",
                           "target_actor": "p1"},
                          {"time": 0.4, "op": "actor.play_action", "actor": "p1", "action": "hit_react_back"}]}
    boxes = {"p2": (38, 0, 377, 576), "p1": (377, 170, 650, 553), "p3": (650, 6, 1011, 576)}
    s = F.staging(proto, boxes)
    assert "right fist" in s["p2"] and "the person in the middle" in s["p2"]
    assert "left fist" in s["p3"]
    assert "p1" not in s                           # 0.4 秒才挨打：开场那一刻没有动作，也没写初始姿势


def test_staging_falls_back_to_the_initial_pose():
    proto = {"actors": [{"id": "p1", "pose": "sit"}], "timeline": []}
    assert F.staging(proto, {"p1": (0, 0, 10, 10)}) == {"p1": "sitting"}


def test_habitual_poses_are_dropped_from_the_look_but_features_stay():
    look = ("round face with short chin, dyed multi-colored messy hair, oversized graphic t-shirt, "
            "arrogant posture, hands in pockets or gesturing aggressively, fearful expression")
    out = F.without_habits(look)
    assert "pockets" not in out and "posture" not in out
    assert out.startswith("round face with short chin") and "graphic t-shirt" in out and "fearful expression" in out


# ── 演员 ↔ 角色库角色：按 character_ref 绑定，不靠 p1/p2 的顺序 ──────────────

def test_bind_cast_pins_entity_ids_on_actors():
    from app.director.from_shot import _bound, bind_cast

    class _Db:
        def get(self, _model, eid):
            return type("E", (), {"display_name": {"e1": "谢文东", "e2": "李爽"}[eid]})()

    proto = {"actors": [{"id": "p2", "type": "human"}, {"id": "p1", "type": "human"}, {"id": "car", "type": "vehicle"}]}
    bind_cast(_Db(), proto, ["e1", "e2"])
    by_id = {a["id"]: a for a in proto["actors"]}
    assert by_id["p1"]["character_ref"] == "e:e1" and by_id["p1"]["name"] == "谢文东"
    assert by_id["p2"]["character_ref"] == "e:e2"
    assert "character_ref" not in by_id["car"]
    assert dict(_bound(proto)) == {"e1": "p1", "e2": "p2"}


def test_bound_actors_follows_character_ref_not_order(tmp_path):
    import json

    from app.director.identity_frame import bound_actors

    f = tmp_path / "scene_protocol.json"
    f.write_text(json.dumps({"actors": [{"id": "a", "character_ref": "e:e2"}, {"id": "b", "character_ref": "e:e1"}]}))
    assert bound_actors(f, ["e1", "e2"]) == [("a", "e2"), ("b", "e1")]
    # 有人没绑定 → 不冒充，交回按顺序的旧路径
    f.write_text(json.dumps({"actors": [{"id": "a", "character_ref": "e:e2"}, {"id": "b"}]}))
    assert bound_actors(f, ["e1", "e2"]) == []


def test_closeup_drops_lower_body_description():
    look = "tall lanky male, messy multi-colored hair, denim jacket, olive cargo pants, worn white sneakers"
    out = F.upper_body_only(look)
    assert "denim jacket" in out and "hair" in out
    assert "pants" not in out and "sneakers" not in out


def test_facing_from_yaw_and_camera():
    """镜 5：两人面对面，相机在斜前方 → 侧脸/四分之三，不是正脸；背对相机的人 → away。"""
    # 相机在 +Z 方向 5 米，看原点
    resolved = {"camera": {"frames": [0, 1.5, 5, 0, 1.5, 0, 40, 0]}}
    proto = {"actors": [
        {"id": "a", "spawn": {"position": [-0.8, 0, 0], "rotation": [0, 90, 0]}},    # 面朝 +X（朝 b）
        {"id": "b", "spawn": {"position": [0.8, 0, 0], "rotation": [0, -90, 0]}},    # 面朝 -X（朝 a）
        {"id": "c", "spawn": {"position": [0, 0, 0], "rotation": [0, 0, 0]}},        # 面朝 +Z（朝相机）
        {"id": "d", "spawn": {"position": [0, 0, 0], "rotation": [0, 180, 0]}},      # 背对相机
    ]}
    f = F.facing(resolved, proto)
    assert f["a"][0] == "profile" and "screen-right" in f["a"][1]
    assert f["b"][0] == "profile" and "screen-left" in f["b"][1]
    assert f["c"][0] == "to_camera"
    assert f["d"][0] == "away"
