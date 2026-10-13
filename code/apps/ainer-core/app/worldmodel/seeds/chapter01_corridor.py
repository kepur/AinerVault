"""第一章 · 学校走廊（剧本场次 sc_01M1PKEFAEBQV5GMSDSGZKNE58）：世界、整场一次表演、20 镜 take。

数据来源（出处）：
- 剧情文本：AiComicStudio 第一章 20 镜预览 plan.json 中各剧本段落（block id 记在 evidence 里）。
- 起始站位：已人工审核的开场首帧 as_01M4S2FP85Z7MFGPDXRCNJ20KB（标准卡布局，floor_plane horizon_y=0.4）
  的人物框，经针孔相机反投影到地面（staging.calibrate_actors），不是凭空摆位。
- 镜长与帧率：沿用 Codex 20 镜成片的镜长（run.json duration_s）与动态漫画路由帧率（对白 8、动作 8、踢 12）。
"""
from __future__ import annotations

import math

from app.worldmodel import staging

NOVEL_ID = "nv_01M1MER58J7H3B06F0BQF0TNTE"
CHAPTER_ID = "ch_01M1METGFD9RXHWWV8FR65Z57K"
SCENE_KEY = "sc_01M1PKEFAEBQV5GMSDSGZKNE58"
REGION_KEY = "school/corridor_locker_hall"
TITLE = "Chapter 1 world (Thomas Ashford)"

#: 已审核开场首帧（800×480）里的人物框与地平线
FRAME_W, FRAME_H = 800, 480
OPENING_HORIZON = 0.40
OPENING_CAM_H, OPENING_LENS = 1.15, 35.0
OPENING_PLACEMENTS = {"thomas": [185, 58, 77, 408], "brad": [272, 112, 105, 349],
                      "tyler": [396, 26, 105, 444], "kyle": [526, 80, 69, 333]}

ACTORS = {
    "thomas": {"entity_id": "we_01M1NJRP0ZK44AZK0P2JND9VK7", "name": "Thomas Ashford", "height_m": 1.70, "build": "slim",
               "color": [0.20, 0.45, 0.95]},
    "brad": {"entity_id": "we_01M1NJRP0ZZ48NWVXQ6BGJNSNX", "name": "Brad Miller", "height_m": 1.62, "build": "stout",
             "color": [0.20, 0.85, 0.35]},
    "tyler": {"entity_id": "we_01M1NJRP0ZZD8JCNDN5DWZE8EQ", "name": "Tyler Stone", "height_m": 1.80, "build": "lanky",
              "color": [0.95, 0.25, 0.20]},
    "kyle": {"entity_id": "da_0dcf55f15e2ff78fa13f603f", "name": "Kyle Reed", "height_m": 1.75, "build": "average",
             "color": [0.95, 0.80, 0.20]},
}

# ------------------------------------------------------------------ 世界（相机原点在走廊里，看 +X；+Y 是储物柜墙）
LOCKER_FACE_Y = 1.07
WINDOW_FACE_Y = -1.27


def world_ops() -> list[dict]:
    ev = "bk_01M1PKEFAJVD2D2D3G18JRXQMB：90年代风格的学校走廊，两名染发的辍学少年将瘦弱的Thomas Ashford逼至墙角。"
    return [
        {"op": "add_region", "key": "school", "kind": "building", "name": "Thomas 的中学",
         "bounds_aabb": {"min": [-6, -8, 0], "max": [40, 8, 4]}, "status": "provisional", "aliases": ["学校", "school"]},
        {"op": "add_region", "key": REGION_KEY, "parent_key": "school", "kind": "corridor", "name": "教学楼储物柜走廊",
         "bounds_aabb": {"min": [-2.0, WINDOW_FACE_Y - 0.3, 0], "max": [22.0, LOCKER_FACE_Y + 0.5, 3.0]}, "lod": "L1",
         "status": "confirmed", "aliases": ["走廊", "corridor", "hallway", "墙角"],
         "description": "90 年代风格学校走廊：左侧蓝色储物柜与木门，右侧大窗，地面浅色瓷砖，尽头为出口。"},
        {"op": "add_asset", "key": "floor_tile", "kind": "floor", "dims_m": [24.0, 2.9, 0.02]},
        {"op": "add_asset", "key": "locker_bank", "kind": "structure", "dims_m": [6.0, 0.5, 1.95]},
        {"op": "add_asset", "key": "wall_plain", "kind": "structure", "dims_m": [24.0, 0.2, 3.0]},
        {"op": "add_asset", "key": "window_wall", "kind": "structure", "dims_m": [24.0, 0.25, 0.9],
         "meta": {"windows_above_m": 0.9}},
        {"op": "add_asset", "key": "end_wall", "kind": "structure", "dims_m": [0.2, 2.6, 3.0]},
        {"op": "add_asset", "key": "door_wood", "kind": "prop", "dims_m": [0.9, 0.08, 2.05]},
        {"op": "add_asset", "key": "school_bag", "kind": "prop", "dims_m": [0.32, 0.18, 0.4]},
        *[{"op": "add_asset", "key": f"char_{k}", "kind": "character", "name": a["name"], "rig": "mixamo",
           "entity_id": a["entity_id"], "dims_m": [0.5, 0.35, a["height_m"]], "meta": {"build": a["build"]}}
          for k, a in ACTORS.items()],
        {"op": "add_instance", "region_key": REGION_KEY, "key": "floor", "asset_key": "floor_tile", "collision": False,
         "xform": {"pos": [10.0, (LOCKER_FACE_Y + WINDOW_FACE_Y) / 2, -0.02]}},
        {"op": "add_instance", "region_key": REGION_KEY, "key": "lockers_a", "asset_key": "locker_bank",
         "xform": {"pos": [3.0, LOCKER_FACE_Y + 0.25, 0]}},
        {"op": "add_instance", "region_key": REGION_KEY, "key": "lockers_b", "asset_key": "locker_bank",
         "xform": {"pos": [11.5, LOCKER_FACE_Y + 0.25, 0]}},
        {"op": "add_instance", "region_key": REGION_KEY, "key": "left_wall", "asset_key": "wall_plain",
         "xform": {"pos": [10.0, LOCKER_FACE_Y + 0.6, 0]}},
        {"op": "add_instance", "region_key": REGION_KEY, "key": "window_wall", "asset_key": "window_wall",
         "xform": {"pos": [10.0, WINDOW_FACE_Y - 0.125, 0]}},
        {"op": "add_instance", "region_key": REGION_KEY, "key": "classroom_door", "asset_key": "door_wood",
         "collision": False, "xform": {"pos": [6.6, LOCKER_FACE_Y + 0.04, 0]}},
        {"op": "add_instance", "region_key": REGION_KEY, "key": "far_end_wall", "asset_key": "end_wall",
         "xform": {"pos": [21.5, (LOCKER_FACE_Y + WINDOW_FACE_Y) / 2, 0]}},
        {"op": "add_instance", "region_key": REGION_KEY, "key": "thomas_bag", "asset_key": "school_bag",
         "collision": False, "xform": {"pos": [3.9, 0.85, 0]}},
        {"op": "add_landmark", "region_key": REGION_KEY, "key": "locker_corner", "kind": "wall",
         "pos": [3.3, LOCKER_FACE_Y - 0.25, 0], "facing_deg": -90, "description": "Thomas 被逼到的储物柜墙边"},
        {"op": "add_landmark", "region_key": REGION_KEY, "key": "bag_spot", "kind": "spot", "pos": [3.9, 0.85, 0]},
        {"op": "add_landmark", "region_key": REGION_KEY, "key": "corridor_exit", "kind": "door", "pos": [20.5, 0.0, 0],
         "facing_deg": 90, "description": "走廊尽头，通往教学楼出口"},
        {"op": "add_fact", "subject_kind": "region", "subject_key": REGION_KEY, "predicate": "era_style",
         "value": "1990s school", "source": "explicit", "evidence_span": ev, "confidence": 0.95},
        {"op": "add_fact", "subject_kind": "landmark", "subject_key": "locker_corner", "predicate": "event",
         "value": "Thomas cornered against the wall", "source": "explicit", "evidence_span": ev, "confidence": 0.9},
        {"op": "add_fact", "subject_kind": "region", "subject_key": REGION_KEY, "predicate": "layout",
         "value": "lockers on the left wall, windows on the right, corridor recedes from camera",
         "source": "user", "evidence_span": "已审核首帧 as_01M4S2FP85Z7MFGPDXRCNJ20KB 的背景与 floor_plane", "confidence": 0.9},
        {"op": "add_fact", "subject_kind": "landmark", "subject_key": "corridor_exit", "predicate": "leads_to",
         "value": "school building exit", "source": "explicit",
         "evidence_span": "bk 19：Thomas Ashford在空荡的走廊站了很久，弯腰捡起地上的书包，走出教学楼。", "confidence": 0.85},
        {"op": "lock_region", "key": REGION_KEY},
    ]


# ------------------------------------------------------------------ 镜头表（沿用 Codex 20 镜的镜长与路由帧率）
#  kind: action / speech / inner；size: wide / medium / close；move: 运镜（每镜都有）；mood：紧张度
SHOTS = [
    {"n": 1, "kind": "action", "size": "wide", "dur": 3125, "fps": 8, "focus": ["thomas", "brad", "tyler", "kyle"],
     "move": {"type": "push_in", "amount": 0.7}, "mood": "menace",
     "text": "90年代风格的学校走廊，两名染发的辍学少年将瘦弱的Thomas Ashford逼至墙角。", "frame": "as_01M4S2FP85Z7MFGPDXRCNJ20KB"},
    {"n": 2, "kind": "speech", "size": "close", "dur": 3708, "fps": 8, "focus": ["tyler"], "move": {"type": "push_in", "amount": 0.25},
     "mood": "menace", "text": "Hey, kid, hand over all your money!"},
    {"n": 3, "kind": "action", "size": "wide", "dur": 2833, "fps": 8, "focus": ["thomas", "brad", "tyler", "kyle"],
     "move": {"type": "pan_left", "amount": 6}, "mood": "fear", "text": "Thomas Ashford低着头，身体紧贴墙壁，双手护住口袋。"},
    {"n": 4, "kind": "speech", "size": "close", "dur": 3032, "fps": 8, "focus": ["thomas"], "move": {"type": "push_in", "amount": 0.2},
     "mood": "fear", "text": "I don't have any money."},
    {"n": 5, "kind": "action", "size": "medium", "dur": 3125, "fps": 8, "focus": ["thomas", "tyler"],
     "move": {"type": "push_in", "amount": 0.35}, "mood": "violence", "text": "Tyler猛地抬手，一记耳光扇在Thomas Ashford脸上。"},
    {"n": 6, "kind": "speech", "size": "close", "dur": 4016, "fps": 8, "focus": ["tyler"], "move": {"type": "push_in", "amount": 0.25},
     "mood": "anger", "text": "Fuck you. Stop rambling and hurry up!"},
    {"n": 7, "kind": "action", "size": "close", "dur": 2417, "fps": 8, "focus": ["thomas"], "move": {"type": "push_in", "amount": 0.2},
     "mood": "pain", "text": "Thomas Ashford嘴角渗出血迹，泪水在眼眶中打转，他死死咬住嘴唇不让自己哭出声。"},
    {"n": 8, "kind": "speech", "size": "close", "dur": 7412, "fps": 8, "focus": ["brad"], "move": {"type": "push_in", "amount": 0.25},
     "mood": "mockery", "text": "Forget it, don't break him. This kid is a straight-A student in my class, haha!"},
    {"n": 9, "kind": "action", "size": "medium", "dur": 3125, "fps": 8, "focus": ["brad", "tyler"],
     "move": {"type": "truck_right", "amount": 0.3}, "mood": "contempt",
     "text": "Tyler轻蔑地打量着Thomas Ashford，随后转头看向身旁的Brad Miller。"},
    {"n": 10, "kind": "speech", "size": "close", "dur": 6750, "fps": 8, "focus": ["tyler"], "move": {"type": "push_in", "amount": 0.25},
     "mood": "contempt", "text": "Shit, look at you, such a wimp. What good does being smart do?"},
    {"n": 11, "kind": "speech", "size": "close", "dur": 6583, "fps": 8, "focus": ["tyler"], "move": {"type": "push_in", "amount": 0.25},
     "mood": "menace", "text": "Chubbs, go check his pockets. I don't believe he has no money!"},
    {"n": 12, "kind": "action", "size": "medium", "dur": 3125, "fps": 8, "focus": ["thomas", "brad"],
     "move": {"type": "push_in", "amount": 0.35}, "mood": "violence", "text": "Brad Miller（Chubbs）哼了一声，走近Thomas Ashford，伸手去抓他的衣领。"},
    {"n": 13, "kind": "speech", "size": "close", "dur": 3717, "fps": 8, "focus": ["brad"], "move": {"type": "push_in", "amount": 0.25},
     "mood": "menace", "text": "Thomas Ashford, let go of your hands."},
    {"n": 14, "kind": "action", "size": "wide", "dur": 3417, "fps": 12, "focus": ["thomas", "brad"],
     "move": {"type": "push_in", "amount": 0.3}, "mood": "violence",
     "text": "Thomas Ashford无视指令，双手紧紧捂住口袋。Brad Miller咒骂一声，抬脚狠狠踹向Thomas Ashford的腹部。"},
    {"n": 15, "kind": "speech", "size": "close", "dur": 5084, "fps": 8, "focus": ["brad"], "move": {"type": "push_in", "amount": 0.25},
     "mood": "anger", "text": "Shit, are you treating me like I'm full of crap?"},
    {"n": 16, "kind": "action", "size": "medium", "dur": 4125, "fps": 8, "focus": ["thomas", "brad"],
     "move": {"type": "crane_down", "amount": 0.3}, "mood": "despair",
     "text": "Thomas Ashford背部撞墙滑落。Brad Miller掰开他的手，从口袋里掏出一张皱巴巴的五美元钞票。"},
    {"n": 17, "kind": "speech", "size": "close", "dur": 6021, "fps": 8, "focus": ["brad"], "move": {"type": "push_in", "amount": 0.25},
     "mood": "mockery", "text": "Damn it, we gave you a chance and you didn't take it."},
    {"n": 18, "kind": "action", "size": "wide", "dur": 4125, "fps": 8, "focus": ["thomas", "brad", "tyler", "kyle"],
     "move": {"type": "pull_out", "amount": 0.8}, "mood": "despair",
     "text": "Tyler和Brad Miller大笑着转身离开，留下Thomas Ashford在墙角，面部扭曲，浑身颤抖。"},
    {"n": 19, "kind": "action", "size": "wide", "dur": 3125, "fps": 8, "focus": ["thomas"],
     "move": {"type": "pan_right", "amount": 8}, "mood": "loneliness",
     "text": "Thomas Ashford在空荡的走廊站了很久，弯腰捡起地上的书包，走出教学楼。"},
    {"n": 20, "kind": "inner", "size": "close", "dur": 9375, "fps": 8, "focus": ["thomas"], "move": {"type": "push_in", "amount": 0.3},
     "mood": "despair", "text": "Why? Why do they always bully me? Why don't they bully anyone else? Why is it me?"},
]


def timeline() -> list[dict]:
    t = 0
    out = []
    for s in SHOTS:
        out.append({**s, "start_ms": t, "end_ms": t + s["dur"]})
        t += s["dur"]
    return out


def opening_camera() -> dict:
    return staging.camera_from_horizon(OPENING_HORIZON, OPENING_CAM_H, OPENING_LENS, FRAME_W, FRAME_H)


def start_positions() -> dict[str, list[float]]:
    return staging.calibrate_actors(opening_camera(), OPENING_PLACEMENTS, FRAME_W, FRAME_H)


def _yaw_to(a, b) -> float:
    """面朝 b 的偏航（正面 = -Y 方向在 yaw=0；yaw 绕 Z 逆时针）。"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return round(math.degrees(math.atan2(dx, -dy)), 1)


def tracks() -> dict:
    """整场一次表演：位置关键帧 + 动作片段（骨架姿态）。时间为场景时钟（ms）。"""
    T = {s["n"]: s for s in timeline()}
    P = start_positions()
    th, br, ty, ky = P["thomas"], P["brad"], P["tyler"], P["kyle"]
    # 起始：Thomas 在储物柜前，三人从走廊深处半步逼近（开场首帧即 t=0 的站位）
    th_wall = [th[0], min(th[1] + 0.1, LOCKER_FACE_Y - 0.24), 0.0]
    br_in = [br[0] + 0.35, br[1] - 0.05, 0.0]   # 侧身让出 Tyler 的位置
    ty_in = [ty[0] - 0.15, ty[1] + 0.12, 0.0]
    ky_in = [ky[0] - 0.35, ky[1] + 0.1, 0.0]
    e1 = T[1]["end_ms"]
    slap_pos = [th_wall[0] - 0.15, th_wall[1] - 0.95, 0.0]
    yaw_th = _yaw_to(th, ty)
    k = lambda t, p, yaw: {"t_ms": int(t), "pos": [round(p[0], 3), round(p[1], 3), 0.0], "yaw_deg": yaw}  # noqa: E731

    thomas = {"keys": [k(0, th, yaw_th), k(e1 - 400, th_wall, yaw_th), k(T[16]["start_ms"], th_wall, yaw_th),
                       k(T[19]["start_ms"] + 300, th_wall, yaw_th),
                       k(T[19]["start_ms"] + 1500, [3.9, 0.7, 0], 90.0),
                       k(T[19]["end_ms"], [5.6, 0.45, 0], 90.0),
                       k(T[20]["end_ms"], [10.0, 0.3, 0], 90.0)],
              "clips": [{"clip": "back_away", "start_ms": 0, "end_ms": e1},
                        {"clip": "talk", "start_ms": T[2]["start_ms"], "end_ms": T[2]["end_ms"], "intensity": 0.2},
                        {"clip": "cower", "start_ms": T[3]["start_ms"], "end_ms": T[5]["start_ms"] + 900},
                        {"clip": "recoil", "start_ms": T[5]["start_ms"] + 1100, "end_ms": T[5]["end_ms"], "target": "tyler"},
                        {"clip": "hold_face", "start_ms": T[6]["start_ms"], "end_ms": T[12]["start_ms"]},
                        {"clip": "cower", "start_ms": T[12]["start_ms"], "end_ms": T[14]["start_ms"] + 1500},
                        {"clip": "double_over", "start_ms": T[14]["start_ms"] + 1500, "end_ms": T[16]["start_ms"]},
                        {"clip": "slump", "start_ms": T[16]["start_ms"], "end_ms": T[17]["start_ms"] + 2500},
                        {"clip": "stand_up", "start_ms": T[17]["start_ms"] + 2500, "end_ms": T[18]["start_ms"]},
                        {"clip": "tremble", "start_ms": T[18]["start_ms"], "end_ms": T[19]["start_ms"] + 300},
                        {"clip": "pick_up", "start_ms": T[19]["start_ms"] + 300, "end_ms": T[19]["start_ms"] + 1500,
                         "landmark": "bag_spot"},
                        {"clip": "walk", "start_ms": T[19]["start_ms"] + 1500, "end_ms": T[20]["end_ms"]}]}
    tyler = {"keys": [k(0, ty, _yaw_to(ty, th)), k(e1, ty_in, _yaw_to(ty_in, th)),
                      # 耳光：草稿站位略在够不着的地方，交给 world_check 修正（真实验证修正回路）
                      k(T[5]["start_ms"] + 200, slap_pos, _yaw_to(slap_pos, th_wall)),
                      k(T[6]["end_ms"], slap_pos, _yaw_to(slap_pos, th_wall)),
                      k(T[7]["end_ms"], ty_in, _yaw_to(ty_in, th)),
                      k(T[9]["start_ms"] + 1200, ty_in, _yaw_to(ty_in, th)),
                      k(T[9]["start_ms"] + 1800, ty_in, _yaw_to(ty_in, br_in)),
                      k(T[11]["end_ms"], ty_in, _yaw_to(ty_in, br_in)),
                      k(T[12]["start_ms"], ty_in, _yaw_to(ty_in, th)),
                      k(T[18]["start_ms"] + 700, ty_in, 90.0),
                      k(T[18]["end_ms"], [ty_in[0] + 3.2, ty_in[1] - 0.2, 0], 90.0),
                      k(T[20]["end_ms"], [18.0, -0.5, 0], 90.0)],
             "clips": [{"clip": "walk", "start_ms": 0, "end_ms": e1},
                       {"clip": "demand", "start_ms": T[2]["start_ms"], "end_ms": T[2]["end_ms"]},
                       {"clip": "slap", "start_ms": T[5]["start_ms"] + 500, "end_ms": T[5]["start_ms"] + 1400, "target": "thomas"},
                       {"clip": "talk", "start_ms": T[6]["start_ms"], "end_ms": T[6]["end_ms"], "intensity": 0.9},
                       {"clip": "look_down", "start_ms": T[9]["start_ms"], "end_ms": T[9]["start_ms"] + 1200},
                       {"clip": "turn_head", "start_ms": T[9]["start_ms"] + 1200, "end_ms": T[9]["end_ms"]},
                       {"clip": "talk", "start_ms": T[10]["start_ms"], "end_ms": T[11]["end_ms"], "intensity": 0.7},
                       {"clip": "laugh", "start_ms": T[18]["start_ms"], "end_ms": T[18]["start_ms"] + 700},
                       {"clip": "walk", "start_ms": T[18]["start_ms"] + 700, "end_ms": T[20]["end_ms"]}]}
    brad = {"keys": [k(0, br, _yaw_to(br, th)), k(e1, br_in, _yaw_to(br_in, th)),
                     k(T[9]["start_ms"] + 1500, br_in, _yaw_to(br_in, ty_in)),
                     k(T[12]["start_ms"], br_in, _yaw_to(br_in, th)),
                     k(T[12]["start_ms"] + 1300, [th_wall[0] + 0.62, th_wall[1] - 0.2, 0], _yaw_to(br_in, th)),
                     k(T[14]["start_ms"] + 600, [th_wall[0] + 0.9, th_wall[1] - 0.35, 0], _yaw_to(br_in, th)),
                     k(T[16]["start_ms"] + 600, [th_wall[0] + 0.55, th_wall[1] - 0.2, 0], _yaw_to(br_in, th)),
                     k(T[17]["end_ms"] - 1500, br_in, _yaw_to(br_in, th)),
                     k(T[18]["start_ms"] + 700, br_in, 90.0),
                     k(T[18]["end_ms"], [br_in[0] + 2.8, br_in[1] - 0.6, 0], 90.0),
                     k(T[20]["end_ms"], [17.0, 0.2, 0], 90.0)],
            "clips": [{"clip": "walk", "start_ms": 0, "end_ms": e1},
                      {"clip": "laugh", "start_ms": T[8]["start_ms"], "end_ms": T[8]["end_ms"]},
                      {"clip": "walk", "start_ms": T[12]["start_ms"], "end_ms": T[12]["start_ms"] + 1300},
                      {"clip": "grab", "start_ms": T[12]["start_ms"] + 1400, "end_ms": T[12]["end_ms"], "target": "thomas"},
                      {"clip": "talk", "start_ms": T[13]["start_ms"], "end_ms": T[13]["end_ms"], "intensity": 0.8},
                      {"clip": "kick", "start_ms": T[14]["start_ms"] + 1300, "end_ms": T[14]["start_ms"] + 2300, "target": "thomas"},
                      {"clip": "talk", "start_ms": T[15]["start_ms"], "end_ms": T[15]["end_ms"], "intensity": 0.9},
                      {"clip": "take_money", "start_ms": T[16]["start_ms"] + 1500, "end_ms": T[16]["end_ms"], "target": "thomas"},
                      {"clip": "talk", "start_ms": T[17]["start_ms"], "end_ms": T[17]["end_ms"], "intensity": 0.6},
                      {"clip": "laugh", "start_ms": T[18]["start_ms"], "end_ms": T[18]["start_ms"] + 700},
                      {"clip": "walk", "start_ms": T[18]["start_ms"] + 700, "end_ms": T[20]["end_ms"]}]}
    kyle = {"keys": [k(0, ky, _yaw_to(ky, th)), k(e1, ky_in, _yaw_to(ky_in, th)),
                     k(T[18]["start_ms"] + 500, ky_in, 90.0),
                     k(T[18]["end_ms"], [ky_in[0] + 3.0, ky_in[1], 0], 90.0),
                     k(T[20]["end_ms"], [19.0, -0.8, 0], 90.0)],
            "clips": [{"clip": "walk", "start_ms": 0, "end_ms": e1},
                      {"clip": "idle_arms_crossed", "start_ms": e1, "end_ms": T[18]["start_ms"]},
                      {"clip": "walk", "start_ms": T[18]["start_ms"] + 500, "end_ms": T[20]["end_ms"]}]}
    out = {"thomas": thomas, "tyler": tyler, "brad": brad, "kyle": kyle}
    for name, tr in out.items():
        tr.update(entity_id=ACTORS[name]["entity_id"], asset_key=f"char_{name}")
    return out


def total_ms() -> int:
    return timeline()[-1]["end_ms"]


def designed_camera(shot: dict, positions: dict[str, list[float]]) -> dict:
    """设计机位（没有首帧框可拟合时使用）：wide = 开场相机；medium = 两人中点前 2.4m；close = 焦点人物脸前 1.1m。"""
    if shot["size"] == "wide":
        return opening_camera()
    pts = [positions[a] for a in shot["focus"]]
    cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    if shot["size"] == "medium":
        return {"pos": [cx - 2.4, cy - 0.5, 1.3], "target": [cx, cy, 1.1], "lens_mm": 35.0}
    a = shot["focus"][0]
    h = ACTORS[a]["height_m"] * 0.93
    p = positions[a]
    # 从走廊中线一侧看向面部
    dx, dy = -0.8, (-0.75 if p[1] > 0 else 0.75)
    return {"pos": [p[0] + dx, p[1] + dy, h], "target": [p[0], p[1], h - 0.02], "lens_mm": 50.0}


ROUTES = {"action": "ltx25_layout", "speech": "dialogue_a2v", "inner": "dialogue_a2v"}

# ------------------------------------------------------------------ 第二个区域：放学后的傍晚街道（镜 19 的已审核首帧在这里）
STREET_KEY = "town/evening_street"
STREET_SCENE_KEY = SCENE_KEY + "#street"
STREET_SHOTS = {19}
STREET_HORIZON, STREET_CAM_H = 0.53, 0.93
STREET_PLACEMENTS = {"thomas": [307, 76, 74, 390]}


def street_ops() -> list[dict]:
    ev = "bk 19 已审核首帧 as_01M4S1R2HTKEBQPHE3WKBWDTHS：傍晚住宅街道，路灯在左，木板房在右"
    return [
        {"op": "add_region", "key": STREET_KEY, "kind": "street", "name": "学校外的傍晚街道",
         "bounds_aabb": {"min": [-4, -12, 0], "max": [60, 8, 8]}, "lod": "L0", "status": "provisional",
         "aliases": ["街道", "street", "放学路上"]},
        {"op": "add_portal", "from_key": REGION_KEY, "to_key": STREET_KEY},
        {"op": "add_asset", "key": "road", "kind": "floor", "dims_m": [64, 20, 0.02]},
        {"op": "add_asset", "key": "house", "kind": "building", "dims_m": [7.0, 6.0, 6.5]},
        {"op": "add_asset", "key": "lamp_post", "kind": "prop", "dims_m": [0.2, 0.2, 4.5]},
        {"op": "add_asset", "key": "curb", "kind": "structure", "dims_m": [64, 0.3, 0.15]},
        {"op": "add_instance", "region_key": STREET_KEY, "key": "road", "asset_key": "road", "collision": False,
         "xform": {"pos": [28, -2, -0.02]}},
        *[{"op": "add_instance", "region_key": STREET_KEY, "key": f"house_{i}", "asset_key": "house",
           "xform": {"pos": [6 + i * 9.0, -8.5, 0]}} for i in range(5)],
        *[{"op": "add_instance", "region_key": STREET_KEY, "key": f"lamp_{i}", "asset_key": "lamp_post",
           "xform": {"pos": [3 + i * 12.0, 3.2, 0]}} for i in range(4)],
        {"op": "add_instance", "region_key": STREET_KEY, "key": "curb_right", "asset_key": "curb", "collision": False,
         "xform": {"pos": [28, -3.0, 0]}},
        {"op": "add_fact", "subject_kind": "region", "subject_key": STREET_KEY, "predicate": "time_of_day",
         "value": "evening", "source": "user", "evidence_span": ev, "confidence": 0.8},
        {"op": "add_fact", "subject_kind": "region", "subject_key": STREET_KEY, "predicate": "reached_from",
         "value": REGION_KEY, "source": "explicit",
         "evidence_span": "bk 19：……弯腰捡起地上的书包，走出教学楼。", "confidence": 0.8},
    ]


def street_camera() -> dict:
    return staging.camera_from_horizon(STREET_HORIZON, STREET_CAM_H, OPENING_LENS, FRAME_W, FRAME_H)


def street_tracks() -> dict:
    p = staging.calibrate_actors(street_camera(), STREET_PLACEMENTS, FRAME_W, FRAME_H)["thomas"]
    end = [p[0] + 0.9, p[1] - 1.1, 0.0]
    yaw = _yaw_to(p, end)
    return {"thomas": {"entity_id": ACTORS["thomas"]["entity_id"], "asset_key": "char_thomas",
                       "keys": [{"t_ms": 0, "pos": p, "yaw_deg": yaw}, {"t_ms": 3125, "pos": end, "yaw_deg": yaw}],
                       "clips": [{"clip": "walk", "start_ms": 0, "end_ms": 3125},
                                 {"clip": "look_down", "start_ms": 0, "end_ms": 3125}]}}


def build(db, *, max_rounds: int = 3, cameras: dict[int, dict] | None = None) -> dict:
    """建（或复用）第一章世界 → 应用章节 delta → 整场一次表演（带 world_check 有界修正）→ 20 个 take。幂等。"""
    from sqlalchemy import select

    from app.models import SpatialWorld, WorldTake
    from app.worldmodel import compile as wc
    from app.worldmodel import service as ws

    w = db.scalar(select(SpatialWorld).where(SpatialWorld.novel_id == NOVEL_ID, SpatialWorld.title == TITLE))
    if w is None:
        w = ws.create_world(db, title=TITLE, novel_id=NOVEL_ID)
        d = ws.propose_delta(db, w.id, world_ops(), chapter_id=CHAPTER_ID, note="chapter 1: locker corridor")
        ws.apply_delta(db, d.id)
    if not ws.search_regions(db, w.id, "evening_street"):
        d = ws.propose_delta(db, w.id, street_ops(), chapter_id=CHAPTER_ID, note="chapter 1: street after school")
        ws.apply_delta(db, d.id)
    from app.worldmodel import geometry as geo

    def staged(scene_key, region_key, duration, trk, mood):
        perf = ws.performance_for_scene(db, scene_key)
        if perf is not None and perf.world_id == w.id:
            return perf
        snap = ws.snapshot(db, w.id, region_keys=[region_key])
        draft = {"region_key": region_key, "duration_ms": duration, "tracks": trk, "rev": 1}
        fixed, rounds = wc.bounded_stage(snap, draft, max_rounds)
        perf = ws.create_performance(db, w.id, scene_key=scene_key, region_key=region_key, duration_ms=duration,
                                     tracks=fixed["tracks"], fps=24, mood=mood)
        perf.rev = fixed["rev"]
        perf.check_report = {"rounds": rounds, "ok": rounds[-1]["ok"], "max_rounds": max_rounds}
        db.flush()
        return perf

    perf = staged(SCENE_KEY, REGION_KEY, total_ms(), tracks(), {str(s["n"]): s["mood"] for s in SHOTS})
    street = staged(STREET_SCENE_KEY, STREET_KEY, 3125, street_tracks(), {"19": "loneliness"})
    have = {t.shot_key for p in (perf, street)
            for t in db.scalars(select(WorldTake).where(WorldTake.performance_id == p.id))}
    for s in timeline():
        key = f"chapter01/shot{s['n']:02d}"
        if key in have:
            continue
        p = street if s["n"] in STREET_SHOTS else perf
        start = 0 if p is street else s["start_ms"]
        end = start + s["dur"]
        pos = {a: geo.lerp_track(tr["keys"], start)[0] for a, tr in p.tracks.items()}
        cam = (cameras or {}).get(s["n"]) or (street_camera() if p is street else designed_camera(s, pos))
        ws.add_take(db, p, shot_key=key, start_ms=start, end_ms=end,
                    camera={**cam, "move": s["move"], "size": s["size"]}, order_no=s["n"], route=ROUTES[s["kind"]],
                    fps=s["fps"], focus=s["focus"], mood=s["mood"])
    db.flush()
    return {"world_id": w.id, "performance_id": perf.id, "street_performance_id": street.id,
            "version": w.current_version}


# ------------------------------------------------------------------ 通用流水线配置（app/worldmodel/pipeline.py 不含任何章节硬编码）
CODEX_RUN_DIR = "AiComicStudio/var/chapter-01/preview-twenty-v3"
ACTOR_DESC = {"thomas": "the thin black-haired Thomas in a navy sweater vest", "brad": "the stocky green-haired Brad",
              "tyler": "the tall red-haired Tyler in black", "kyle": "the blond Kyle in a navy track jacket"}
ACTOR_HUE = {"tyler": "red", "brad": "green", "kyle": "blond"}   # qa.HUES 里的标志色 → 身份闸门按白模可见面积缩放
ACTION_EN = {
    1: "In a 1990s school corridor, three delinquent boys corner the thin black-haired Thomas against the lockers. "
       "The bullies lean in and shift their weight menacingly; Thomas shrinks back.",
    3: "Thomas lowers his head, presses his back against the lockers and covers his trouser pockets with both hands. "
       "The bullies loom over him.",
    5: "The tall red-haired Tyler suddenly raises his hand and slaps Thomas across the face once; Thomas's head snaps "
       "aside and he recoils. Non-graphic.",
    7: "Close-up of Thomas: a thin trickle of blood at the corner of his mouth, tears welling in his eyes, he bites "
       "his lip to keep from crying. His mouth stays closed.",
}


def pipeline_config(db, workflow_root: str) -> dict:
    """第一章 → 通用 world-greybox 运行配置。workflow_root = /Users/.../AinerWorkFlow。"""
    from app.worldmodel import service as ws
    r = build(db)
    run_dir = f"{workflow_root}/{CODEX_RUN_DIR}"
    shots = []
    for s in SHOTS:
        shots.append({"n": s["n"], "kind": s["kind"], "dur": s["dur"], "fps": s["fps"], "focus": s["focus"],
                      "move": s["move"], "mood": s["mood"], "text": s["text"],
                      "layout": s["kind"] == "action" and s["n"] != 7,
                      **({"action_en": ACTION_EN[s["n"]]} if s["n"] in ACTION_EN else {}),
                      "ambience": ("quiet evening street ambience, slow footsteps, distant traffic" if s["n"] in STREET_SHOTS
                                   else "school corridor room tone, distant hallway chatter, shoe scuffs, clothing rustle; "
                                        "no speech, no music")})
    return {
        "world_id": r["world_id"], "performances": [r["performance_id"], r["street_performance_id"]],
        "build": {"type": "seed", "module": "app.worldmodel.seeds.chapter01_corridor"},
        "frames": {"type": "comic_run", "path": f"{run_dir}/run.json"},
        "voices": {"dir": run_dir, "pattern": "voice-{n:02d}.wav"},
        "frame_w": FRAME_W, "frame_h": FRAME_H,
        "face_safe_source": {   # 原管线面部安全版（对白 native8 + 嘴型、动作 native8/12）；没有这个文件时回退旧的 comic_run 成片
            "video": "/Users/mac/AinerWorkFlow/AiComicStudio/var/chapter-01/preview-twenty-v3/twenty-shots-dialogue8.mp4",
            "order": "/Users/mac/AinerWorkFlow/AiComicStudio/var/chapter-01/preview-twenty-v3/shot-order.json",
            "preview_dir": "/Users/mac/AinerWorkFlow/AiComicStudio/var/chapter-01/preview-twenty-v3",
            "store_db": "/Users/mac/AinerWorkFlow/AiComicStudio/var/productions.sqlite3"},   # 只读
        "dialogue_greybox": True, "dialogue_ab_shots": [2, 8, 13, 15],
        "ab_python": "/Users/mac/AinerWorkFlow/AiComicStudio/vendor/av-venv/bin/python",
        "greybox_kinds": ["action"],
        "actors": {k: {**v, "desc": ACTOR_DESC.get(k, k), **({"hue": ACTOR_HUE[k]} if k in ACTOR_HUE else {})}
                   for k, v in ACTORS.items()},
        "shots": shots,
        "music": [{"name": "tension", "from_shot": 1, "bpm": 92, "key": "D minor",
                   "prompt": "tense dark cinematic underscore, low strings pulse, muted percussion, menacing, school "
                             "bullying scene, instrumental"},
                  {"name": "despair", "from_shot": 17, "bpm": 66, "key": "A minor",
                   "prompt": "slow sad piano and soft strings, lonely, despair, quiet evening, instrumental"}],
        "key_prefix": "world-greybox-ch01-v3", "output_name": "chapter01_world_greybox.mp4",
        "version": ws.get_world(db, r["world_id"]).current_version,
    }
