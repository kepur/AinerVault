"""Ainer Scene Protocol v1：引擎无关的场景交换格式。

LLM、3D-BOX、Blender、UE、视频模型之间只认它 —— 谁都不直接写 bpy / Unreal Python：
  - LLM 输出这份 JSON（或写 3D-BOX 场景脚本，脚本在沙箱里跑出来也会导出成这份 JSON）
  - 前端拖拽改动 → JSON Patch（RFC 6902）打到这份 JSON 上
  - Blender / UE 适配器把它（和烘焙出的逐帧数据）翻译成各自引擎的操作

约定：Y 向上、米、右手系；物体 yaw 0 面向 +Z；角度一律是度，欧拉 XYZ 次序。
动作名（actor.play_action）与运镜名（camera.move）来自 3D-BOX 运行时的目录，两边同一份。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROTOCOL = "ainer.scene/v1"

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── 目录（动作库、运镜库、预制件、体型）：以 3D-BOX 运行时为准 ─────────────

_FALLBACK_MOTIONS = ["idle", "walk_forward", "run_forward", "turn_left", "turn_right", "turn_to", "look_back",
                     "right_punch", "left_punch", "front_kick", "dodge_left", "dodge_right", "block_high",
                     "hit_react_back", "hit_react_left", "fall_backward", "stand_up"]


@lru_cache
def catalog_ids() -> dict[str, list[str]]:
    """动作、运镜、预制件、体型、姿势的合法名字。拿不到 node 目录时退回内置清单（动作）并放行其余。"""
    try:
        from app.scene3d.runner import catalog
        cat = catalog()
        return {
            "motions": [m["id"] for m in cat.get("motions", [])] or _FALLBACK_MOTIONS,
            "camera_presets": [p["id"] for p in cat.get("cameraPresets", [])],
            "prefabs": [p["name"] for p in cat.get("prefabs", [])],
            "bodies": [b["name"] for b in cat.get("bodies", [])],
            "poses": [p["name"] for p in cat.get("poses", [])],
        }
    except Exception:           # noqa: BLE001 —— 没有 node 也能校验结构
        return {"motions": _FALLBACK_MOTIONS, "camera_presets": [], "prefabs": [], "bodies": [], "poses": []}


# ── 场景各部分 ────────────────────────────────────────────

class Meta(_M):
    title: str = "untitled"
    fps: int = Field(24, ge=1, le=60)
    duration_sec: float = Field(6.0, gt=0, le=180)
    unit: Literal["meter"] = "meter"
    aspect: float = Field(16 / 9, gt=0.2, le=5)
    coordinate_system: dict[str, str] = Field(default_factory=lambda: {"up": "+Y", "forward": "+Z", "handedness": "right"})
    #: 从哪来：{"kind": "3dbox", "project_id": …} / {"kind": "llm", "prompt": …} / {"kind": "api"}
    source: dict[str, Any] | None = None


class Light(_M):
    id: str | None = None
    kind: Literal["sun", "point", "spot", "ambient"]
    color: str = "#ffffff"
    intensity: float = 1.0
    position: Vec3 | None = None
    direction: Vec3 | None = None
    range: float | None = None


class Environment(_M):
    preset: str | None = None                     # alley_night / street_day / blank_stage …（给人看、给 UE 选关卡）
    weather: Literal["clear", "rain", "fog", "snow", "overcast"] = "clear"
    time_of_day: Literal["day", "dawn", "dusk", "night"] = "day"
    sky: Literal["day", "dawn", "dusk", "night", "overcast", "studio"] = "day"
    ground: Literal["grid", "asphalt", "grass", "sand", "snow", "water", "stone", "floor", "dirt"] = "grid"
    ground_size: float = Field(120, gt=1, le=4000)
    fog: float = Field(0, ge=0, le=1)
    lights: list[Light] = Field(default_factory=list)


class Transform(_M):
    position: Vec3 = (0.0, 0.0, 0.0)
    rotation: Vec3 = (0.0, 0.0, 0.0)             # 度，XYZ；多数物体只用 y（朝向）
    scale: Vec3 = (1.0, 1.0, 1.0)


class Asset(_M):
    id: str
    type: Literal["procedural_prefab", "mannequin", "character_ref", "image", "model"]
    ref: str                                      # prefab 名 / 体型 / 角色库 id / 文件
    url: str | None = None
    tags: list[str] = Field(default_factory=list)


class Actor(_M):
    id: str
    name: str | None = None
    type: Literal["human", "vehicle", "animal"] = "human"
    #: 人：mannequin/<体型>（male/female/teen/child/muscular/…）；车、动物：prefab/<名字>
    model_ref: str = "mannequin/male"
    #: 角色库里的角色（e:<实体 id> 或官方预设 id）：成片阶段拿它的立绘当身份参考
    character_ref: str | None = None
    spawn: Transform = Field(default_factory=Transform)
    rig: str = "ainer_mannequin_v1"
    appearance: dict[str, Any] = Field(default_factory=dict)   # {style_tag, color, look}
    pose: str | None = None                                    # 初始姿势（stand/fight/sit/…）
    params: dict[str, Any] = Field(default_factory=dict)       # 车、动物的预制件参数
    parent: str | None = None


class Prop(_M):
    id: str
    name: str | None = None
    prefab: str | None = None                     # 预制件（building/car/tree/…）
    primitive: Literal["box", "sphere", "cylinder", "cone", "plane", "torus", "capsule", "prism"] | None = None
    size: Vec3 | None = None                      # 基本体尺寸（米）
    params: dict[str, Any] = Field(default_factory=dict)
    spawn: Transform = Field(default_factory=Transform)
    color: str | None = None
    parent: str | None = None
    #: 道路／河流：地面上的带子
    strip: dict[str, Any] | None = None
    hidden: bool = False


class CameraKey(_M):
    """机位关键帧。位置三选一：position（世界）/ follow+offset（跟随目标）/ orbit+angle+radius+height（绕目标）。"""
    t: float = Field(ge=0)
    position: Vec3 | None = None
    follow: str | None = None
    offset: Vec3 | None = None
    orbit: str | None = None
    angle: float | None = None
    radius: float | None = None
    height: float | None = None
    look_at: Vec3 | str | dict[str, Any] | None = None
    lens_mm: float | None = Field(None, ge=8, le=300)
    roll: float | None = None


class Camera(_M):
    id: str
    name: str | None = None
    type: Literal["cinematic", "follow", "static", "handheld"] = "cinematic"
    lens_mm: float = Field(35, ge=8, le=300)
    sensor: Literal["full_frame"] = "full_frame"   # 36×24mm，水平适配
    transform: Transform | None = None              # 起幅位置（导出时按 t=0 算好）
    keys: list[CameraKey] = Field(default_factory=list)
    shake: float = Field(0, ge=0, le=1)
    presets: list[str] = Field(default_factory=list)


# ── 时间线指令 ────────────────────────────────────────────

class _Op(_M):
    time: float = Field(0, ge=0)


class MoveTo(_Op):
    op: Literal["actor.move_to", "prop.move_to"]
    actor: str | None = None
    prop: str | None = None
    target_position: Vec3
    duration: float | None = Field(None, gt=0)
    speed: float | None = Field(None, gt=0)
    gait: Literal["walk", "run", "drive", "fly", "swim"] | None = None


class MoveAlong(_Op):
    op: Literal["actor.move_along", "prop.move_along"]
    actor: str | None = None
    prop: str | None = None
    path: list[Vec3] = Field(min_length=2)
    duration: float | None = Field(None, gt=0)
    speed: float | None = Field(None, gt=0)
    gait: Literal["walk", "run", "drive", "fly", "swim"] | None = None


class MoveKeys(_Op):
    op: Literal["actor.move", "prop.move"]
    actor: str | None = None
    prop: str | None = None
    keys: list[dict[str, Any]] = Field(min_length=1)       # [{t, at, rot}]
    gait: Literal["walk", "run", "drive", "fly", "swim"] | None = None


class PlayAction(_Op):
    op: Literal["actor.play_action"]
    actor: str
    action: str
    duration: float | None = Field(None, gt=0)
    target_actor: str | None = None
    target_bone: str | None = None                    # V1 只用来记录（打哪儿），动作库按整体面向目标

    @field_validator("action")
    @classmethod
    def _known(cls, v: str) -> str:
        ids = catalog_ids()["motions"]
        if ids and v not in ids:
            raise ValueError(f"动作库里没有「{v}」。可用：{', '.join(ids)}")
        return v


class SetPose(_Op):
    op: Literal["actor.set_pose"]
    actor: str
    pose: str


class LookAt(_Op):
    op: Literal["actor.look_at"]
    actor: str
    target_actor: str
    duration: float | None = Field(None, gt=0)


class CameraFollow(_Op):
    op: Literal["camera.follow"]
    camera: str
    target_actor: str
    style: Literal["back", "front", "side", "top", "first", "side_follow"] = "back"
    duration: float | None = Field(None, gt=0)
    distance: float | None = Field(None, gt=0)
    height: float | None = None
    side: Literal[-1, 1] = 1


class CameraMove(_Op):
    op: Literal["camera.move"]
    camera: str
    preset: str
    target: str | Vec3 | None = None
    duration: float = Field(4, gt=0)
    side: Literal[-1, 1] | None = None
    angle: float | None = None

    @field_validator("preset")
    @classmethod
    def _known(cls, v: str) -> str:
        ids = catalog_ids()["camera_presets"]
        if ids and v not in ids:
            raise ValueError(f"运镜库里没有「{v}」")
        return v


class CameraKeysOp(_Op):
    op: Literal["camera.keys"]
    camera: str
    keys: list[CameraKey] = Field(min_length=1)


class CameraFrame(_Op):
    op: Literal["camera.frame"]
    camera: str
    target: str
    size: Literal["els", "ws", "fs", "mls", "ms", "mcu", "cu", "ecu"] = "ms"
    angle: float | None = None


class CameraCut(_Op):
    op: Literal["camera.cut"]
    camera: str


TimelineOp = Annotated[Union[MoveTo, MoveAlong, MoveKeys, PlayAction, SetPose, LookAt,
                             CameraFollow, CameraMove, CameraKeysOp, CameraFrame, CameraCut],
                       Field(discriminator="op")]


class RenderPlan(_M):
    preview: bool = True
    passes: list[Literal["preview", "clay", "depth", "pose", "canny"]] = Field(
        default_factory=lambda: ["preview", "clay", "depth", "pose", "canny"])
    output_resolution: tuple[int, int] = (1024, 576)
    fps: int = 24
    #: "cut" = 按剪辑表（camera.cut）逐帧切主机位；或某台机位的 id
    camera: str = "cut"
    export_camera_json: bool = True
    export_motion_json: bool = True
    final_renderer: Literal["ltx_097", "ltx_25"] = "ltx_097"
    control_type: Literal["v2v", "depth", "pose", "canny"] = "v2v"

    @field_validator("output_resolution")
    @classmethod
    def _mult32(cls, v: tuple[int, int]) -> tuple[int, int]:
        w, h = v
        if not (256 <= w <= 2048 and 256 <= h <= 2048):
            raise ValueError("分辨率要在 256–2048 之间")
        return (w // 32 * 32, h // 32 * 32)


class SceneProtocol(_M):
    protocol: Literal["ainer.scene/v1"] = PROTOCOL
    scene_id: str
    meta: Meta = Field(default_factory=Meta)
    environment: Environment = Field(default_factory=Environment)
    assets: list[Asset] = Field(default_factory=list)
    actors: list[Actor] = Field(default_factory=list)
    props: list[Prop] = Field(default_factory=list)
    cameras: list[Camera] = Field(default_factory=list)
    timeline: list[TimelineOp] = Field(default_factory=list)
    render_plan: RenderPlan = Field(default_factory=RenderPlan)

    @model_validator(mode="after")
    def _references(self) -> "SceneProtocol":
        """时间线引用的人、物、机位都得存在；id 不能重复。"""
        actors = {a.id for a in self.actors}
        props = {p.id for p in self.props}
        cams = {c.id for c in self.cameras}
        ids = [a.id for a in self.actors] + [p.id for p in self.props]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"id 重复：{', '.join(sorted(dup))}")
        things = actors | props
        problems = []
        for i, op in enumerate(self.timeline):
            name = op.op
            for field, pool, what in (("actor", actors, "人物"), ("prop", props, "物体"), ("camera", cams, "机位"),
                                      ("target_actor", things, "目标")):
                v = getattr(op, field, None)
                if v is not None and v not in pool:
                    problems.append(f"timeline[{i}] {name}：没有这个{what}「{v}」")
            if name.startswith(("actor.move", "prop.move")) and not (getattr(op, "actor", None) or getattr(op, "prop", None)):
                problems.append(f"timeline[{i}] {name}：要写 actor 或 prop")
            if op.time > self.meta.duration_sec + 1e-6:
                problems.append(f"timeline[{i}] {name}：time={op.time} 超出片长 {self.meta.duration_sec}s")
        for c in self.cameras:
            for k in c.keys:
                for ref in (k.follow, k.orbit):
                    if ref is not None and ref not in things:
                        problems.append(f"机位 {c.id}：跟随/环绕的「{ref}」不存在")
        if self.render_plan.camera != "cut" and self.render_plan.camera not in cams:
            problems.append(f"render_plan.camera：没有机位「{self.render_plan.camera}」")
        if problems:
            raise ValueError("；".join(problems[:12]))
        return self


def json_schema() -> dict[str, Any]:
    s = SceneProtocol.model_json_schema()
    s["$id"] = "https://ainer.local/schemas/ainer.scene.v1.json"
    s["title"] = "Ainer Scene Protocol v1"
    return s
