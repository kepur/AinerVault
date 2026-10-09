"""Plan A · P0：素材卡的物理尺寸推断、动作表、舞台与镜头覆盖的契约校验。"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.stage.actions import ACTIONS, CONTACT_M, EFFECTS, check_contact, check_speed
from app.stage.cards import infer_physical
from app.stage.schema import CoverageShot, SceneStage

RIG = Path(__file__).resolve().parents[2] / "ainer-studio" / "src" / "scene" / "rig.ts"


@pytest.mark.parametrize("text, height, build, source", [
    ("round face with short chin, stout build with protruding belly, short stature, teenage boy in his mid teens", 1.62, "stout", "inferred"),
    ("tall and lanky male, long face, teenage boy in his late teens", 1.80, "lanky", "inferred"),
    ("narrow face, thin eyebrows, extremely skinny build with visible ribs, teenage boy", 1.70, "slim", "inferred"),
    ("a young woman in her twenties", 1.63, "average", "default"),
    ("瘦高的少年", 1.80, "lanky", "inferred"),
    ("矮胖的中年男人", 1.67, "stout", "inferred"),
])
def test_physical_is_inferred_from_the_description(text, height, build, source):
    p = infer_physical(text)
    assert (p.height_m, p.build, p.source) == (height, build, source)


def test_face_words_are_not_body_shape():
    p = infer_physical("an adult man with short hair, thin lips and a short chin")
    assert p.height_m == 1.75 and p.build == "average" and p.source == "default", "短发、薄嘴唇说的不是身材"


def test_action_table_is_physically_consistent():
    for name, a in ACTIONS.items():
        if a.contact_m is not None:
            assert a.needs == "target", f"{name}：接触类动作必须有对象"
        assert a.default_s > 0
        for e in a.effects:
            assert e in EFFECTS, f"{name} 引出未知特效 {e}"
    assert check_contact("slap", CONTACT_M + 0.5) and check_contact("slap", 0.5) is None
    assert check_contact("talk", 5.0) is None, "说话不要求接触"
    assert check_speed(10, 2, "walk") and check_speed(10, 2, "run") is None
    assert check_speed(30, 3, "ski") is None and check_speed(1, 0) == "时长必须大于 0"


def test_rig_names_exist_in_the_white_model_library():
    src = RIG.read_text(encoding="utf-8")
    motions = set(re.findall(r"^  ([a-z_]+): \{", src[src.index("export const MOTIONS"):], re.M))
    poses = set(re.findall(r"^  ([a-z_]+): \{", src[src.index("export const POSE_DEFS"):src.index("export const MOTIONS")], re.M))
    for name, a in ACTIONS.items():
        if a.rig_motion:
            assert a.rig_motion in motions, f"{name} → MOTIONS 里没有 {a.rig_motion}"
        if a.rig_pose:
            assert a.rig_pose in poses, f"{name} → POSE_DEFS 里没有 {a.rig_pose}"


def _stage(**over):
    base = {
        "scene_id": "sc1",
        "set": {"landmarks": [{"id": "lockers_left", "pos": [-1.5, 0]}]},
        "cast": [{"actor": "p1", "card": "e:victim"}, {"actor": "p2", "card": "e:tyler"}],
        "props": [{"id": "money", "holder": "p1", "slot": "pocket_right"}],
        "beats": [
            {"t": [0, 2], "text": "逼到储物柜前", "do": [{"actor": "p2", "op": "walk_to", "target": [-1.1, 1.0]},
                                                    {"actor": "p1", "op": "back_against", "target": "lockers_left"}]},
            {"t": [2, 3], "text": "扇耳光", "do": [{"actor": "p2", "op": "slap", "target": "p1", "hand": "right"}],
             "effects": [{"kind": "blood_trickle", "on": "p1", "where": "mouth_corner_left", "from_t": 2.6}]},
        ],
        "axis": {"a": "p2", "b": "p1"},
    }
    base.update(over)
    return base


def test_a_valid_stage_parses():
    s = SceneStage(**_stage())
    assert s.duration == 3 and s.beats[1].do[0].op == "slap"


@pytest.mark.parametrize("patch, msg", [
    ({"beats": [{"t": [0, 1], "do": [{"actor": "p1", "op": "fly_away"}]}]}, "不在动作表"),
    ({"beats": [{"t": [0, 1], "do": [{"actor": "p2", "op": "slap"}]}]}, "要写对象"),
    ({"beats": [{"t": [0, 1], "do": [{"actor": "p9", "op": "stand"}]}]}, "没有演员「p9」"),
    ({"beats": [{"t": [0, 1], "do": [{"actor": "p1", "op": "walk_to", "target": "door"}]}]}, "不是演员、道具或地标"),
    ({"beats": [{"t": [2, 3]}, {"t": [0, 1]}]}, "要按先后排"),
    ({"beats": [{"t": [1, 1]}]}, "开始 < 结束"),
    ({"beats": [{"t": [0, 1], "effects": [{"kind": "explosion", "on": "p1"}]}]}, "不在特效表"),
    ({"axis": {"a": "p2", "b": "money"}}, "轴线两端必须是演员"),
    ({"props": [{"id": "p1"}]}, "id 重复"),
])
def test_bad_stages_are_rejected_with_a_reason(patch, msg):
    with pytest.raises(ValidationError) as e:
        SceneStage(**_stage(**patch))
    assert msg in str(e.value)


def test_coverage_window_is_bounded():
    assert CoverageShot(shot_id="sh1", order_no=1, window=(5.0, 6.6), size="ms").window == (5.0, 6.6)
    with pytest.raises(ValidationError):
        CoverageShot(shot_id="sh1", order_no=1, window=(0, 25))
    with pytest.raises(ValidationError):
        CoverageShot(shot_id="sh1", order_no=1, window=(3, 2))
