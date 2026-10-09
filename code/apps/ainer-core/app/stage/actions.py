"""动作表：舞台时间线（SceneStage.beats[].do）只能用这里的动作。

为什么要一张固定的表：LLM 自由写「他扇了一耳光」时，没人知道扇耳光要先走到 0.8 米以内、挨打的人会往后仰、
嘴角可能出血 —— 图像模型和视频模型更不知道。把动作做成表，每个动作写死：
- 谁参与（只有自己，还是有一个对象）；
- 物理前提：接触类动作双方距离上限；移动类动作速度上限；
- 后果：做完以后身体处于什么状态（站 / 坐 / 躺 / 蹲），对方会怎样（受击后仰）；
- 落到 3D 白模上用哪个动作或姿势（ainer-studio/src/scene/rig.ts 的 MOTIONS / POSE_DEFS；还没有的标 None，P3 补）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: 速度上限（米/秒）。超了说明时间排得太紧：延长这一拍，或者把 walk 改成 run
SPEED_LIMIT = {"walk": 1.5, "run": 6.0, "ski": 15.0, "drive": 30.0}
#: 接触类动作双方身体中心的最大距离（米）：一臂长 + 半个身位
CONTACT_M = 0.8

Posture = Literal["standing", "sitting", "lying", "crouching", "kneeling"]


@dataclass(frozen=True)
class ActionDef:
    zh: str
    #: self = 只有自己；target = 要有一个对象（人或道具或地点）
    needs: Literal["self", "target"] = "self"
    #: 接触类：执行时和对象的距离上限（米）；None = 不要求接触
    contact_m: float | None = None
    #: 会移动位置：按 speed 校验速度
    moves: bool = False
    default_s: float = 1.0
    #: 做完以后自己的姿态（None = 不变）
    posture_after: Posture | None = None
    #: 对象（人）受到的后果：做完以后对象的姿态 / 状态
    target_posture_after: Posture | None = None
    target_reacts: str | None = None
    #: 3D 白模：rig.ts 里的 MOTIONS id（动作）或 POSE_DEFS id（静态姿势）；None = 白模里还没有，P3 补
    rig_motion: str | None = None
    rig_pose: str | None = None
    #: 这个动作允许引出的特效（见 EFFECTS）
    effects: tuple[str, ...] = field(default_factory=tuple)


ACTIONS: dict[str, ActionDef] = {
    # ── 移动 ──
    "walk_to": ActionDef("走到", needs="target", moves=True, default_s=2.0, rig_motion="walk_forward"),
    "run_to": ActionDef("跑到", needs="target", moves=True, default_s=1.5, rig_motion="run_forward"),
    "back_against": ActionDef("退到…边（背靠）", needs="target", moves=True, default_s=1.0, rig_pose="stand"),
    "turn_to": ActionDef("转向", needs="target", default_s=0.5, rig_motion="turn_to"),
    "ski_downhill": ActionDef("滑雪下坡", moves=True, default_s=3.0, rig_pose="crouch", effects=("snow_spray",)),
    # ── 姿态 ──
    "stand": ActionDef("站着", default_s=1.0, posture_after="standing", rig_pose="stand"),
    "sit": ActionDef("坐下", default_s=1.0, posture_after="sitting", rig_pose="sit"),
    "crouch": ActionDef("蹲下", default_s=0.8, posture_after="crouching", rig_pose="crouch"),
    "kneel": ActionDef("跪下", default_s=0.8, posture_after="kneeling", rig_pose="kneel"),
    "fall": ActionDef("摔倒", default_s=1.2, posture_after="lying", rig_motion="fall_backward", effects=("snow_spray", "dust")),
    "stand_up": ActionDef("起身", default_s=1.4, posture_after="standing", rig_motion="stand_up"),
    # ── 交流 ──
    "talk": ActionDef("说话", needs="target", default_s=2.0, rig_motion="idle"),
    "look_at": ActionDef("看向", needs="target", default_s=0.5),
    "look_back": ActionDef("回头看", default_s=1.6, rig_motion="look_back"),
    "point_at": ActionDef("指着", needs="target", default_s=1.0, rig_pose="point"),
    "wave": ActionDef("挥手", default_s=1.0, rig_pose="wave"),
    "peace_sign": ActionDef("比耶", default_s=1.0),
    "laugh": ActionDef("笑", default_s=1.0),
    "cry": ActionDef("哭", default_s=1.5, effects=("tears",)),
    # ── 接触 ──
    "slap": ActionDef("扇耳光", needs="target", contact_m=CONTACT_M, default_s=0.6, target_reacts="head snaps to the side",
                      effects=("blood_trickle", "red_mark")),
    "punch": ActionDef("打一拳", needs="target", contact_m=CONTACT_M, default_s=0.6, target_reacts="hit_react_back",
                       effects=("blood_trickle",)),
    "push": ActionDef("推", needs="target", contact_m=CONTACT_M, default_s=0.6, target_reacts="stumbles back"),
    "shove_into": ActionDef("推撞到…上", needs="target", contact_m=CONTACT_M, default_s=0.8, target_reacts="slams into it"),
    "grab": ActionDef("抓住（衣领 / 手臂）", needs="target", contact_m=CONTACT_M, default_s=0.6),
    "kick": ActionDef("踢", needs="target", contact_m=1.1, default_s=0.8, rig_motion="front_kick", target_reacts="hit_react_back"),
    "block": ActionDef("格挡", default_s=0.8, rig_motion="block_high"),
    "hug": ActionDef("拥抱", needs="target", contact_m=0.5, default_s=2.0),
    # ── 道具 ──
    "pick_up": ActionDef("拿起", needs="target", contact_m=CONTACT_M, default_s=1.0),
    "hand_over": ActionDef("递给", needs="target", contact_m=CONTACT_M, default_s=1.0),
    "search_pockets": ActionDef("搜身", needs="target", contact_m=0.6, default_s=2.0),
    "protect_pocket": ActionDef("护住口袋", default_s=1.0),
    "phone": ActionDef("打电话 / 看手机", default_s=2.0, rig_pose="phone"),
}

#: 特效：从哪儿来、怎么持续。effects[].kind 只能用这些
EFFECTS: dict[str, dict[str, str]] = {
    "blood_trickle": {"zh": "细细一道血", "persist": "until_cleaned",
                      "prompt": "a thin trickle of blood at the {where}, only there"},
    "red_mark": {"zh": "脸上红印", "persist": "scene", "prompt": "a reddish hand mark on the {where}"},
    "tears": {"zh": "眼泪", "persist": "beat", "prompt": "eyes wet with tears, tears on the cheeks"},
    "snow_spray": {"zh": "雪雾", "persist": "beat", "prompt": "a spray of powder snow kicked up from the skis"},
    "dust": {"zh": "扬尘", "persist": "beat", "prompt": "a small puff of dust from the ground"},
    "wet": {"zh": "湿身", "persist": "scene", "prompt": "clothes and hair soaking wet"},
}


def check_speed(distance_m: float, seconds: float, mode: str = "walk") -> str | None:
    """位移太快：返回人话；合理返回 None。"""
    if seconds <= 0:
        return "时长必须大于 0"
    v = distance_m / seconds
    limit = SPEED_LIMIT.get(mode, SPEED_LIMIT["walk"])
    if v > limit:
        return f"{seconds:.1f} 秒走 {distance_m:.1f} 米（{v:.1f} 米/秒）超过{mode}的上限 {limit} 米/秒"
    return None


def check_contact(op: str, distance_m: float) -> str | None:
    """接触类动作双方离太远：返回人话。"""
    a = ACTIONS.get(op)
    if a is None or a.contact_m is None:
        return None
    if distance_m > a.contact_m:
        return f"「{a.zh}」时双方相距 {distance_m:.1f} 米，超过 {a.contact_m} 米：先走近"
    return None
