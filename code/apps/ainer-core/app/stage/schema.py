"""舞台与镜头覆盖的数据契约（planA.md 第 4 节）。

素材卡 AssetCard：有限、标准化的素材（人 / 物 / 地点），带物理尺寸和可用参考格。
场景舞台 SceneStage：一场戏一个；布景 + 在场的人和物 + 动作时间线（beats）+ 推演出来的连续状态。
镜头覆盖 CoverageShot：每镜 = 机位 + 时间窗 [t0, t1] + 转场方式。

这里只做结构校验（字段、引用、时间顺序、动作在不在动作表里）；物理与连续性规则在 validate.py（P1）。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.stage.actions import ACTIONS, EFFECTS

CardKind = Literal["character", "prop", "location"]
Transition = Literal["cut", "match_action", "continuous", "time_jump"]
ShotSize = Literal["els", "ws", "fs", "ms", "mcu", "cu", "ecu"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Physical(_M):
    """物理尺寸。人：身高、体型、惯用手；物：尺寸（米，长宽高）。source 记来源，人改过的不再被推断覆盖。"""
    height_m: float | None = Field(None, ge=0.3, le=3.0)
    build: Literal["slim", "average", "athletic", "stout", "heavy", "lanky"] | None = None
    handedness: Literal["right", "left"] | None = None
    size_m: list[float] | None = None
    source: Literal["text", "inferred", "default", "user"] = "default"


class AssetCard(_M):
    id: str                                   # e:<实体 id> / p:<道具实体 id> / l:<地点实体 id>
    kind: CardKind
    entity_id: str | None = None
    name: str                                 # 原名（李爽）
    screen_name: str | None = None            # 译名（Brad Miller），来自翻译系统的世界观映射
    aliases: list[str] = Field(default_factory=list)
    epoch: str | None = None                  # 本章用哪一期的造型
    physical: Physical = Field(default_factory=Physical)
    #: 可用参考格：定妆照 16 格（body_front / face_left / expr_anger …）、旧参考集视角（front / bust …）、地点空镜
    views: dict[str, str] = Field(default_factory=dict)
    look_en: str = ""


class Effect(_M):
    kind: str
    on: str                                   # 演员 id 或道具 id
    where: str = ""                           # 部位 / 位置（mouth_corner_left、skis）
    from_t: float | None = None
    to_t: float | None = None

    @field_validator("kind")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in EFFECTS:
            raise ValueError(f"特效「{v}」不在特效表里：{', '.join(EFFECTS)}")
        return v


class BeatAction(_M):
    actor: str
    op: str
    #: 对象：演员 id / 道具 id / 地标 id，或平面坐标 [x, y]（米）
    target: str | list[float] | None = None
    speed: Literal["walk", "run", "ski", "drive"] | None = None
    hand: Literal["left", "right"] | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("op")
    @classmethod
    def _in_table(cls, v: str) -> str:
        if v not in ACTIONS:
            raise ValueError(f"动作「{v}」不在动作表里（app/stage/actions.py）")
        return v

    @model_validator(mode="after")
    def _needs_target(self) -> "BeatAction":
        if ACTIONS[self.op].needs == "target" and self.target is None:
            raise ValueError(f"「{ACTIONS[self.op].zh}」要写对象（target）")
        if isinstance(self.target, list) and len(self.target) != 2:
            raise ValueError("坐标 target 要 [x, y] 两个数（米）")
        return self


class Beat(_M):
    t: tuple[float, float]
    text: str = ""                            # 一句人话（剧本原意），给人看、给 LLM 对照
    line: str | None = None                   # 这一拍的台词（AudioSpec id），口型跟它走
    do: list[BeatAction] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)

    @field_validator("t")
    @classmethod
    def _span(cls, v: tuple[float, float]) -> tuple[float, float]:
        if not (0 <= v[0] < v[1]):
            raise ValueError(f"时间段 {list(v)} 要满足 0 ≤ 开始 < 结束")
        return v


class Landmark(_M):
    id: str
    pos: list[float]                          # [x, y] 或 [x, y, z]（米）
    label: str = ""


class StageSet(_M):
    location: str | None = None               # 地点素材卡 id
    preset: str | None = None                 # 白模预制场景（school_corridor / ski_slope …）
    size_m: list[float] | None = None         # 场地长宽高
    landmarks: list[Landmark] = Field(default_factory=list)
    light: dict[str, Any] = Field(default_factory=dict)


class StageCast(_M):
    actor: str                                # p1 / p2 …（舞台内的演员 id）
    card: str                                 # 素材卡 id
    start: list[float] | None = None          # 开场站位 [x, y]
    facing_deg: float | None = None


class StageProp(_M):
    id: str
    card: str | None = None
    holder: str | None = None                 # 拿在谁手里 / 放在哪个地标
    slot: str | None = None                   # pocket_right / hand_left / on_table …
    pos: list[float] | None = None


class SceneStage(_M):
    scene_id: str
    set: StageSet = Field(default_factory=StageSet)
    cast: list[StageCast] = Field(default_factory=list)
    props: list[StageProp] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
    #: 推演出来的连续状态（演员 id → 按时间的状态变化）；由校验器写，不由 LLM 写
    state: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    #: 主要对峙轴线（180° 规则）：{"a": 演员 id, "b": 演员 id}
    axis: dict[str, str] | None = None
    issues: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refs(self) -> "SceneStage":
        actors = [c.actor for c in self.cast]
        props = [p.id for p in self.props]
        marks = [m.id for m in self.set.landmarks]
        dup = {x for x in actors + props if (actors + props).count(x) > 1}
        if dup:
            raise ValueError(f"演员 / 道具 id 重复：{', '.join(sorted(dup))}")
        known = set(actors) | set(props) | set(marks)
        problems = []
        last = -1.0
        for i, b in enumerate(self.beats):
            if b.t[0] < last:
                problems.append(f"第 {i + 1} 拍开始于 {b.t[0]}s，早于上一拍的开始 {last}s（时间线要按先后排）")
            last = b.t[0]
            for a in b.do:
                if a.actor not in actors:
                    problems.append(f"第 {i + 1} 拍：没有演员「{a.actor}」")
                if isinstance(a.target, str) and a.target not in known:
                    problems.append(f"第 {i + 1} 拍：对象「{a.target}」不是演员、道具或地标")
            for e in b.effects:
                if e.on not in known:
                    problems.append(f"第 {i + 1} 拍特效：没有「{e.on}」")
        if self.axis and not set(self.axis.values()) <= set(actors):
            problems.append("轴线两端必须是演员")
        if problems:
            raise ValueError("；".join(problems))
        return self

    @property
    def duration(self) -> float:
        return max((b.t[1] for b in self.beats), default=0.0)


class CameraSpec(_M):
    #: 机位语义：落地时由 auto_frame 换成具体位置
    setup: Literal["wide_master", "over_shoulder", "single", "two_shot", "pov", "insert", "low_angle", "high_angle",
                   "tracking", "profile"] = "single"
    of: str | None = None                     # 过谁的肩 / 跟谁
    on: str | None = None                     # 对着谁
    lens_mm: float | None = Field(None, ge=12, le=200)
    height: Literal["low", "eye", "high", "overhead"] = "eye"
    move: Literal["static", "push_in", "pull_back", "pull_out", "pan", "track", "handheld"] = "static"


class CoverageShot(_M):
    shot_id: str
    order_no: int
    stage: str | None = None                  # scene_stages.id
    window: tuple[float, float]
    size: ShotSize = "ms"
    camera: CameraSpec = Field(default_factory=CameraSpec)
    transition_in: Transition = "cut"
    focus: str | None = None
    #: 首帧里看得见的演员：由 Blender 投影算出（不是 LLM 猜），关键帧和质检都按它来
    visible: list[str] = Field(default_factory=list)

    @field_validator("window")
    @classmethod
    def _span(cls, v: tuple[float, float]) -> tuple[float, float]:
        if not (0 <= v[0] < v[1]):
            raise ValueError(f"时间窗 {list(v)} 要满足 0 ≤ 开始 < 结束")
        if v[1] - v[0] > 20:
            raise ValueError("一镜最长 20 秒（LTX 2.5 上限）")
        return v
