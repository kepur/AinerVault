"""角色表演接口 v0 纯 CPU 语义合同（hub.P1.D2）。

依据（只读，不修改作者合同）：

- ``docs/v2/production_brain/performance_interface_v0.md``（D1 r3）
- ``docs/v2/production_brain/performance_interface_v0.schema.json``（D1 r3）

本模块只做 ``request`` / ``response`` / ``error`` 三类记录的**纯函数**语义校验与候选曲线检查：
不生成曲线、不执行、不渲染、不接角色包、不写任何文件/数据库/运行账本、不做网络、
不导入 MLX/ORT/模型。所有外部事实（控制器注册表、部位别名、已登记角色/意图/目标、
blend 规则、已执行区间）一律由调用方以显式 fixture 参数传入；缺表即 fail-closed，不猜。

结构层（pydantic，``extra="forbid"``、``strict=True``、``allow_inf_nan=False``）只复刻
D1 schema 的形状；语义层负责 D1 文档「D2 语义校验器必须 fail-closed」一节的全部条目。
结构层报错同样映射到 D1 十码，规则见 :func:`structural_error_code`。

与 D1 十码的判定映射（D2 判断，未改作者合同）：

======================= =========================================================
code                     本模块触发条件
======================= =========================================================
unknown_actor            binding 的 actor_id/character_ref 与 request 不一致，或
                         不在显式传入的能力表 characters 中
stale_revision           plan_revision/world_version/scene_revision 与 request 不一致；
                         其余 binding 身份字段不一致；错误记录 request_id 不匹配
invalid_time_curve       sim_hz != 120；阶段边界未严格递增或有空段；阶段越出请求区间；
                         keyframe tick 乱序/重复/未覆盖轨区间；时长<=0 或起点<0；
                         request/response 的 render_fps 不一致（偷换时钟）；
                         姿态轨 keyframe 步长不在 ones/twos/threes 的视频帧网格上
                         （按声明 render_fps 换算，不是每 N 个 tick）；
                         口型轨 keyframe 步长落在非整数音频 sample 上
unknown_controller       controller_ref 未在显式能力表中登记；缺能力表；
                         pending_D5 轨的 controller_ref 不以 ``pending:D5/`` 开头；
                         已注册轨使用 ``pending:`` 名
out_of_range             数值非有限（NaN/±Inf）；数值超出单位/已登记值域；
                         向量维度不一致或与已登记维度不符；unit 与已登记控制器不符
missing_audio_alignment  无音频或 alignment.status != aligned 时出现 mouth 轨；
                         audio_ref/对齐产物身份不可解析
lock_conflict            locks[].path 不是合法 JSON Pointer 或重复；曲线（含别名展开与
                         控制器路径 token）命中锁定路径且写者不是锁持有者
control_conflict         同一 actor 同一生效部位（含别名展开）区间重叠且有多名写者；
                         blend 未登记合成规则/显式输入
unsupported_action       pending_D5 轨被标为可执行；真实 D5 未完时能力表把占位登记为
                         可执行；已注册控制器未登记为 executable 却声明 candidate；
                         意图/目标未登记；记录形状违反 v0 合同（兜底码）
changed_past             曲线区间与显式传入的已执行/已播出 tick 区间重叠
======================= =========================================================

D1 合同里没有优先级字段与混合权重字段（``owner`` 仅 kind/id/authorization_ref，
``additionalProperties=false``），因此 v0 一律按「同优先级重叠即冲突」处理；
需要优先级或显式混合权重时须先由 D1 修订 schema，本模块不放行任何隐式最后写入者胜出。

可执行性口径（v0）：``ValidationResult.executable`` 只有在下列全部成立时才为真——
绑定可核对、已执行区间显式传入、每条曲线控制器由显式能力表登记为 executable、
部位别名已登记、无冲突/锁/越界/时钟问题。真实 D5 未完成时 ``pending:D5`` 轨恒为
unsupported，因此真实数据的 executable 必为 False。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Annotated, Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# --------------------------------------------------------------------------------------
# 常量（与 D1 schema 的枚举一致，由 :func:`schema_contract_drift` 逐项核对）
# --------------------------------------------------------------------------------------

PROTOCOL = "hub.performance/v0"
SIM_HZ = 120
PENDING_PREFIX = "pending:D5/"

RECORD_KINDS = ("request", "response", "error")
CHANNELS = (
    "gaze",
    "facial_unit",
    "mouth",
    "head_pose",
    "body_pose",
    "gesture",
    "secondary_motion",
)
#: ones/twos/threes 只约束姿态呈现；音频/口型和世界运行不跟着降频（D1 文档）。
POSE_CHANNELS = ("head_pose", "body_pose", "gesture", "secondary_motion")
UNITS = ("normalized", "degree", "meter")
TIMINGS = ("ones", "twos", "threes")
TIMING_FRAMES = {"ones": 1, "twos": 2, "threes": 3}
INTERPOLATIONS = ("step", "linear", "cubic")
MAPPING_STATUSES = ("pending_D5", "registered")
EXECUTION_STATUSES = ("unsupported", "candidate")
OWNER_KINDS = ("user", "director", "runtime", "worldbrain", "blend")
ALIGNMENT_STATUSES = ("aligned", "pending", "failed")
ERROR_CODES = (
    "unknown_actor",
    "stale_revision",
    "invalid_time_curve",
    "unknown_controller",
    "out_of_range",
    "missing_audio_alignment",
    "lock_conflict",
    "control_conflict",
    "unsupported_action",
    "changed_past",
)

#: 能力表未登记值时按单位的保守兜底值域；登记值域优先。
DEFAULT_UNIT_RANGES: dict[str, tuple[float, float]] = {
    "normalized": (0.0, 1.0),
    "degree": (-360.0, 360.0),
    "meter": (-1000.0, 1000.0),
}

BINDING_ACTOR_FIELDS = ("actor_id", "character_ref")
BINDING_REVISION_FIELDS = ("plan_revision", "world_version", "scene_revision")
BINDING_CLOCK_FIELDS = ("sim_hz", "render_fps")
BINDING_IDENTITY_FIELDS = ("plan_id", "beat_id", "event_id", "world_id", "scene_id", "take_id")

_HEX64 = re.compile(r"^[a-f0-9]{64}$")
#: D1 r3 收紧后的 JSON Pointer 语法（空串为根）。
_POINTER_TOKEN = re.compile(r"^(?:[^~/]|~[01])*$")
#: pydantic 联合类型报错会带分支标签，构造 Pointer 时要去掉。
_UNION_BRANCH_LABELS = frozenset({"float", "list[float]", "AudioRefModel", "null", "none"})
#: 锁 token 里表示「角色/身份」的词：命中即视为身份锁定（除锁持有者外全部拒绝）。
_LOCK_IDENTITY_TOKENS = frozenset({"character", "character_ref", "identity", "actor_id"})


def err(code: str, path: str, message: str) -> dict[str, str]:
    """构造 D1 形状的错误项 ``{code, path, message}``。"""
    if code not in ERROR_CODES:
        raise ValueError(f"code 不在 D1 十码内: {code!r}")
    return {"code": code, "path": path, "message": message}


# --------------------------------------------------------------------------------------
# JSON Pointer（D1 r3）
# --------------------------------------------------------------------------------------


def pointer_tokens(pointer: Any) -> list[str] | None:
    """解析 JSON Pointer；非法返回 ``None``；空串表示根，返回 ``[]``。

    语法为 D1 r3 的 ``^(?:/(?:[^~/]|~[01])*)*$``：只允许 ``~0``/``~1`` 转义。
    """
    if not isinstance(pointer, str):
        return None
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        return None
    tokens = pointer.split("/")[1:]
    if any(_POINTER_TOKEN.match(token) is None for token in tokens):
        return None
    return [token.replace("~1", "/").replace("~0", "~") for token in tokens]


def escape_pointer_token(token: str) -> str:
    """RFC 6901 转义：``~`` → ``~0``，``/`` → ``~1``。"""
    return token.replace("~", "~0").replace("/", "~1")


def pointer_join(*tokens: Any) -> str:
    """按 RFC 6901 拼 JSON Pointer（无 token 时为空根）。"""
    return "".join(f"/{escape_pointer_token(str(t))}" for t in tokens)


def structural_error_code(path: str, error_type: str = "") -> str:
    """把结构层缺陷映射到 D1 十码（fail-closed：任何缺陷都报错，不静默放行）。"""
    tokens = pointer_tokens(path) or []
    tail = tokens[-1] if tokens else ""
    if error_type == "finite_number":
        if tail in ("tick", "start_tick", "duration_ticks", "render_fps", "sim_hz") or "phases" in tokens:
            return "invalid_time_curve"
        return "out_of_range"
    if len(tokens) >= 2 and tokens[0] == "binding":
        field = tokens[1]
        if field in BINDING_ACTOR_FIELDS:
            return "unknown_actor"
        if field in BINDING_REVISION_FIELDS:
            return "stale_revision"
        if field in BINDING_CLOCK_FIELDS:
            return "invalid_time_curve"
        return "stale_revision"
    if tokens and tokens[0] == "audio_ref":
        return "missing_audio_alignment"
    if tokens and tokens[0] == "locks":
        return "lock_conflict"
    if "phases" in tokens or tail in ("start_tick", "duration_ticks", "tick"):
        return "invalid_time_curve"
    if tail in ("value", "unit", "intensity"):
        return "out_of_range"
    if tail in ("controller_ref", "mapping_status"):
        return "unknown_controller"
    return "unsupported_action"


# --------------------------------------------------------------------------------------
# 时间/音频换算（精确有理数，不静默取整、不改速）
# --------------------------------------------------------------------------------------


def ticks_per_frame(render_fps: int) -> Fraction:
    """一个输出视频帧等于多少 tick（120Hz 时间锚点）。"""
    return Fraction(SIM_HZ, render_fps)


def frame_period_ticks(timing: str, render_fps: int) -> Fraction:
    """ones/twos/threes 的姿态保持周期（tick），按声明的输出 fps 换算。"""
    return Fraction(TIMING_FRAMES[timing] * SIM_HZ, render_fps)


def tick_to_frame(tick: int, render_fps: int, origin_tick: int = 0) -> Fraction:
    """tick → 视频帧号（精确有理数，不四舍五入）。"""
    return Fraction((tick - origin_tick) * render_fps, SIM_HZ)


def on_frame_period_grid(delta_ticks: int, timing: str, render_fps: int) -> bool:
    """``delta_ticks`` 是否正好是 ones/twos/threes 的整数个视频帧。

    例：24fps 下 twos = 10 tick；把「一拍二」写成每 2 tick 更新即不在此网格上。
    120 不能被 fps 整除时网格稀疏（25fps ones = 24 tick），这是精确算式的必然结果，
    不取整、不改速。
    """
    return (delta_ticks * render_fps) % (TIMING_FRAMES[timing] * SIM_HZ) == 0


def sample_of_tick(tick: int, audio_ref: Mapping[str, Any]) -> Fraction:
    """D1 音频时钟：``sample(tick)=offset_samples+(tick-anchor_tick)*sample_rate/120``。

    保留有理数；与 render_fps/timing 无关（不得为让表情峰值好看静默伸缩音频）。
    """
    return Fraction(int(audio_ref["offset_samples"])) + Fraction(
        (int(tick) - int(audio_ref["anchor_tick"])) * int(audio_ref["sample_rate"]), SIM_HZ
    )


def on_audio_sample_grid(delta_ticks: int, sample_rate: int) -> bool:
    """``delta_ticks`` 是否对应整数个音频 sample（口型 keyframe 必须落在音频时钟上）。"""
    return (delta_ticks * sample_rate) % SIM_HZ == 0


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# --------------------------------------------------------------------------------------
# 结构层（严格复刻 D1 schema；语义另判）
# --------------------------------------------------------------------------------------


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class BindingModel(_Contract):
    plan_id: str = Field(min_length=1)
    plan_revision: int = Field(ge=0)
    beat_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    world_id: str = Field(min_length=1)
    world_version: int = Field(ge=1)
    scene_id: str = Field(min_length=1)
    scene_revision: int = Field(ge=0)
    take_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    character_ref: str = Field(min_length=1)
    # sim_hz 只在语义层判 == 120，好给出 invalid_time_curve 而不是结构错误。
    sim_hz: int
    render_fps: int = Field(ge=1, le=120)


class LockModel(_Contract):
    path: str = Field(min_length=1)
    by: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class AlignmentModel(_Contract):
    status: Literal["aligned", "pending", "failed"]
    ref: str | None = Field(default=None, min_length=1)
    sha256: str | None = Field(default=None, min_length=1)


class AudioRefModel(_Contract):
    asset_ref: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    sample_rate: int = Field(ge=1)
    anchor_tick: int = Field(ge=0)
    offset_samples: int
    alignment: AlignmentModel


class RequestModel(_Contract):
    protocol: Literal["hub.performance/v0"]
    record_kind: Literal["request"]
    request_id: str = Field(min_length=1)
    binding: BindingModel
    intent: str = Field(min_length=1)
    intensity: float
    target_ref: str = Field(min_length=1)
    start_tick: int = Field(ge=0)
    duration_ticks: int = Field(ge=1)
    locks: list[LockModel]
    audio_ref: AudioRefModel | None


class PhasesModel(_Contract):
    start_tick: int = Field(ge=0)
    anticipation_end_tick: int = Field(ge=0)
    arrival_end_tick: int = Field(ge=0)
    hold_end_tick: int = Field(ge=0)
    end_tick: int = Field(ge=0)


class OwnerModel(_Contract):
    kind: Literal["user", "director", "runtime", "worldbrain", "blend"]
    id: str = Field(min_length=1)
    authorization_ref: str = Field(min_length=1)


class KeyframeModel(_Contract):
    tick: int = Field(ge=0)
    value: float | Annotated[list[float], Field(min_length=1)]


class CurveModel(_Contract):
    channel: Literal[
        "gaze",
        "facial_unit",
        "mouth",
        "head_pose",
        "body_pose",
        "gesture",
        "secondary_motion",
    ]
    body_part: str = Field(min_length=1)
    controller_ref: str = Field(min_length=1)
    mapping_status: Literal["pending_D5", "registered"]
    execution_status: Literal["unsupported", "candidate"]
    unsupported_reason: str | None = Field(default=None, min_length=1)
    unit: Literal["normalized", "degree", "meter"]
    target_ref: str | None = Field(default=None, min_length=1)
    phases: PhasesModel
    timing: Literal["ones", "twos", "threes"]
    interpolation: Literal["step", "linear", "cubic"]
    owner: OwnerModel
    keyframes: list[KeyframeModel] = Field(min_length=2)


class UnsupportedItemModel(_Contract):
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ResponseModel(_Contract):
    protocol: Literal["hub.performance/v0"]
    record_kind: Literal["response"]
    response_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    binding: BindingModel
    curves: list[CurveModel]
    unsupported: list[UnsupportedItemModel]


class ErrorItemModel(_Contract):
    code: Literal[
        "unknown_actor",
        "stale_revision",
        "invalid_time_curve",
        "unknown_controller",
        "out_of_range",
        "missing_audio_alignment",
        "lock_conflict",
        "control_conflict",
        "unsupported_action",
        "changed_past",
    ]
    path: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ErrorRecordModel(_Contract):
    protocol: Literal["hub.performance/v0"]
    record_kind: Literal["error"]
    request_id: str = Field(min_length=1)
    errors: list[ErrorItemModel] = Field(min_length=1)


# --------------------------------------------------------------------------------------
# 结果对象
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """一次校验的结果：硬错误 + 明确不支持项 + 未验证备注。"""

    record_kind: str
    errors: tuple[dict[str, str], ...] = ()
    unsupported: tuple[dict[str, str], ...] = ()
    notes: tuple[str, ...] = ()
    proposed_curves: int = 0
    executable_curves: int = 0

    @property
    def ok(self) -> bool:
        """无硬错误即结构/语义合同成立；**不等于**可执行或已实现。"""
        return not self.errors

    @property
    def executable(self) -> bool:
        """是否存在可当作已执行/可执行的曲线（v0 真实 D5 未完时恒为 False）。"""
        return self.ok and self.proposed_curves > 0 and self.executable_curves == self.proposed_curves

    def error_codes(self) -> list[str]:
        return [item["code"] for item in self.errors]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_kind": self.record_kind,
            "ok": self.ok,
            "executable": self.executable,
            "proposed_curves": self.proposed_curves,
            "executable_curves": self.executable_curves,
            "errors": [dict(item) for item in self.errors],
            "unsupported": [dict(item) for item in self.unsupported],
            "notes": list(self.notes),
        }

    def as_error_record(self, request_id: str) -> dict[str, Any]:
        """把本结果的硬错误序列化成 D1 ``record_kind=error`` 记录（纯函数，不写状态）。"""
        if not self.errors:
            raise ValueError("没有硬错误，不构成 record_kind=error 记录")
        return {
            "protocol": PROTOCOL,
            "record_kind": "error",
            "request_id": request_id,
            "errors": [dict(item) for item in self.errors],
        }


@dataclass(frozen=True)
class ExchangeResult:
    """request 与 reply（response 或 error 记录）成对校验的结果。"""

    request: ValidationResult
    reply: ValidationResult

    @property
    def ok(self) -> bool:
        return self.request.ok and self.reply.ok

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "request": self.request.to_dict(), "reply": self.reply.to_dict()}


# --------------------------------------------------------------------------------------
# 能力表（只接受显式传入的 fixture；绝不从磁盘/网络读）
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Capabilities:
    raw: Mapping[str, Any] | None

    @property
    def provided(self) -> bool:
        return isinstance(self.raw, Mapping)

    def section(self, key: str) -> Any:
        if not self.provided:
            return None
        return self.raw.get(key)  # type: ignore[union-attr]

    def controllers(self) -> Mapping[str, Any]:
        value = self.section("controllers")
        return value if isinstance(value, Mapping) else {}

    def aliases(self) -> Mapping[str, Sequence[str]]:
        value = self.section("aliases")
        return value if isinstance(value, Mapping) else {}

    def blend_rules(self) -> Mapping[str, Any]:
        value = self.section("blend_rules")
        return value if isinstance(value, Mapping) else {}


def _norm(token: Any) -> str:
    return str(token).strip().lower()


def _split_controller_tokens(controller_ref: str) -> set[str]:
    """把 controller_ref 按 ``/`` 与 ``:`` 切开，用于锁命中判定（换名字也要能命中）。"""
    text = _norm(controller_ref)
    if text.startswith(_norm(PENDING_PREFIX)):
        text = text[len(_norm(PENDING_PREFIX)) :]
    tokens: set[str] = set()
    for chunk in text.replace(":", "/").split("/"):
        if chunk:
            tokens.add(chunk)
    return tokens


def _expand_body_part(body_part: str, aliases: Mapping[str, Sequence[str]]) -> tuple[frozenset[str], bool]:
    """别名展开：返回（部位 token 集合，是否在别名表中登记过）。"""
    part = _norm(body_part)
    tokens = {part}
    registered = False
    for canonical, members in aliases.items():
        group = {_norm(canonical)}
        if isinstance(members, (list, tuple, set, frozenset)):
            group |= {_norm(m) for m in members}
        if part in group:
            registered = True
            tokens |= group
    return frozenset(tokens), registered


def _curve_identity_tokens(curve: CurveModel, aliases: Mapping[str, Sequence[str]]) -> frozenset[str]:
    parts, _ = _expand_body_part(curve.body_part, aliases)
    return frozenset(
        {_norm(curve.channel), _norm(curve.body_part), *parts, *_split_controller_tokens(curve.controller_ref)}
    )


def _intervals_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _is_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


# --------------------------------------------------------------------------------------
# request 校验
# --------------------------------------------------------------------------------------


def validate_request(
    request: Any,
    *,
    capabilities: Mapping[str, Any] | None = None,
) -> ValidationResult:
    """校验 ``record_kind=request``：结构 + 时间/音频/锁/能力表语义。"""
    caps = _Capabilities(capabilities)
    errors: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []
    notes: list[str] = []
    record = _structure(errors, RequestModel, request, "/")
    if record is None:
        return _result("request", errors, unsupported, notes)

    binding = record.binding
    if binding.sim_hz != SIM_HZ:
        errors.append(
            err(
                "invalid_time_curve",
                "/binding/sim_hz",
                f"sim_hz 必须是 {SIM_HZ}（120Hz 时间锚点），实际 {binding.sim_hz!r}；"
                "低采样率冒充 120Hz 会静默改变曲线含义",
            )
        )
    if not _is_finite_number(record.intensity) or not 0.0 <= float(record.intensity) <= 1.0:
        errors.append(
            err("out_of_range", "/intensity", f"intensity 必须是 [0,1] 内有限数，实际 {record.intensity!r}")
        )
    if not _is_int(record.start_tick) or record.start_tick < 0:
        errors.append(err("invalid_time_curve", "/start_tick", f"start_tick 必须 >=0 整数，实际 {record.start_tick!r}"))
    if not _is_int(record.duration_ticks) or record.duration_ticks <= 0:
        errors.append(
            err("invalid_time_curve", "/duration_ticks", f"duration_ticks 必须为正整数，实际 {record.duration_ticks!r}")
        )
    # 时长/起点合法时给出换算锚点：帧 = tick * fps / 120（有理数，不取整）。
    if _is_int(record.start_tick) and _is_int(record.duration_ticks) and record.duration_ticks > 0:
        notes.append(
            f"tick 区间左闭右开 [{record.start_tick},{record.start_tick + record.duration_ticks})；"
            f"{binding.render_fps}fps 下一帧 = {ticks_per_frame(binding.render_fps)} tick；"
            f"{record.start_tick} tick = 帧 {tick_to_frame(record.start_tick, binding.render_fps)}"
        )

    characters = caps.section("characters")
    if _is_string_sequence(characters):
        for field, value in (("actor_id", binding.actor_id), ("character_ref", binding.character_ref)):
            if value not in characters:
                errors.append(
                    err("unknown_actor", f"/binding/{field}", f"{field}={value!r} 不在显式能力表 characters 中")
                )
    elif caps.provided:
        unsupported.append({"path": "/binding/actor_id", "reason": "能力表未登记 characters；演员/角色身份未验证"})

    intents = caps.section("intents")
    if _is_string_sequence(intents):
        if record.intent not in intents:
            errors.append(err("unsupported_action", "/intent", f"intent={record.intent!r} 未在登记意图表中"))
    else:
        unsupported.append({"path": "/intent", "reason": "意图映射未实现：字符串出现不代表已实现映射"})

    _check_locks(record.locks, errors)
    _check_audio_ref(record, errors, unsupported, notes)
    if record.audio_ref is None:
        unsupported.append({"path": "/curves/mouth", "reason": "audio_ref=null：没有实际音频，mouth unsupported"})
    return _result("request", errors, unsupported, notes)


def _check_locks(locks: Sequence[LockModel], errors: list[dict[str, str]]) -> None:
    seen: set[str] = set()
    for index, lock in enumerate(locks):
        path = f"/locks/{index}"
        if pointer_tokens(lock.path) is None:
            errors.append(
                err("lock_conflict", f"{path}/path", f"lock path 不是合法 JSON Pointer（D1 r3 语法）：{lock.path!r}")
            )
            continue
        if lock.path in seen:
            errors.append(err("lock_conflict", f"{path}/path", f"重复锁定的 path：{lock.path!r}"))
        seen.add(lock.path)


def _check_audio_ref(
    record: RequestModel,
    errors: list[dict[str, str]],
    unsupported: list[dict[str, str]],
    notes: list[str],
) -> None:
    audio = record.audio_ref
    if audio is None:
        return
    if not _HEX64.match(audio.sha256):
        errors.append(
            err("missing_audio_alignment", "/audio_ref/sha256", "audio_ref.sha256 必须是 64 位小写十六进制原字节摘要")
        )
    if audio.alignment.status != "aligned":
        errors.append(
            err(
                "missing_audio_alignment",
                "/audio_ref/alignment",
                f"alignment.status={audio.alignment.status!r}：无对齐产物时 mouth 必须 unsupported，"
                "不得用填充字段假称完成",
            )
        )
        unsupported.append({"path": "/audio_ref/alignment", "reason": f"alignment={audio.alignment.status}"})
        return
    if not audio.alignment.ref or not audio.alignment.sha256:
        errors.append(
            err("missing_audio_alignment", "/audio_ref/alignment", "aligned 必须同时给出真实对齐产物 ref 与 sha256")
        )
        return
    if not _HEX64.match(audio.alignment.sha256):
        errors.append(
            err("missing_audio_alignment", "/audio_ref/alignment/sha256", "对齐产物 sha256 必须是 64 位小写十六进制")
        )
    notes.append(
        "音频时钟 sample(tick)=offset_samples+(tick-anchor_tick)*sample_rate/120；"
        f"sample_rate={audio.sample_rate}，anchor_tick={audio.anchor_tick}，offset_samples={audio.offset_samples}；"
        f"sample(0)={sample_of_tick(0, {'offset_samples': audio.offset_samples, 'anchor_tick': audio.anchor_tick, 'sample_rate': audio.sample_rate})}"
    )


# --------------------------------------------------------------------------------------
# response 校验
# --------------------------------------------------------------------------------------


def validate_response(
    response: Any,
    request: Any = None,
    *,
    capabilities: Mapping[str, Any] | None = None,
    executed_tick_ranges: Iterable[Sequence[int]] | None = None,
) -> ValidationResult:
    """校验 ``record_kind=response``：结构 + 候选曲线语义。

    ``executed_tick_ranges`` 是显式传入的已执行/已播出 tick 区间（左闭右开，``[]`` 表示
    「本 take 尚无已执行区间」）；``None`` 表示没有该信息，此时记录未验证、不放行执行。
    """
    caps = _Capabilities(capabilities)
    errors: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []
    notes: list[str] = []
    record = _structure(errors, ResponseModel, response, "/")
    if record is None:
        return _result("response", errors, unsupported, notes)

    request_model = _structure(errors, RequestModel, request, "/request") if request is not None else None
    if request is not None and request_model is None:
        notes.append("request 本身结构不成立，绑定一致性无法核对")

    fps = record.binding.render_fps
    window = _request_window(request_model)
    bound = request_model is not None
    if not bound:
        unsupported.append({"path": "/request_id", "reason": "未提供可解析的 request：请求/响应绑定未验证"})
    else:
        _check_request_response_binding(record, request_model, errors, notes)

    if record.binding.sim_hz != SIM_HZ:
        errors.append(
            err(
                "invalid_time_curve",
                "/binding/sim_hz",
                f"response.binding.sim_hz 必须是 {SIM_HZ}，实际 {record.binding.sim_hz!r}",
            )
        )

    executed = None if executed_tick_ranges is None else _normalize_ranges(executed_tick_ranges)
    if executed is None:
        unsupported.append({"path": "/curves", "reason": "未提供已执行区间：changed_past 未验证"})

    aliases = caps.aliases()
    audio_ref = request_model.audio_ref if request_model is not None else None
    audio_aligned = bool(
        audio_ref is not None
        and audio_ref.alignment.status == "aligned"
        and audio_ref.alignment.ref
        and audio_ref.alignment.sha256
        and _HEX64.match(audio_ref.alignment.sha256)
    )
    bad: set[int] = set()
    executable: set[int] = set()

    for index, curve in enumerate(record.curves):
        base = f"/curves/{index}"
        before = len(errors)
        can_execute = _check_curve(
            curve,
            base,
            render_fps=fps,
            window=window,
            caps=caps,
            aliases=aliases,
            audio_ref=audio_ref,
            audio_aligned=audio_aligned,
            errors=errors,
            unsupported=unsupported,
            notes=notes,
        )
        if len(errors) != before:
            bad.add(index)
        elif can_execute:
            executable.add(index)
        if curve.mapping_status == "pending_D5":
            unsupported.append(
                {
                    "path": base,
                    "reason": curve.unsupported_reason
                    or "mapping_status=pending_D5：D5 控制器注册表未就绪，占位不可执行",
                }
            )
        if curve.channel == "mouth" and not audio_aligned:
            unsupported.append({"path": base, "reason": "无 aligned 音频产物：mouth unsupported"})

    _check_ownership(record.curves, aliases, caps, errors, notes, bad)
    _check_curve_locks(record.curves, aliases, request_model, errors, bad)
    if executed is not None:
        _check_changed_past(record.curves, executed, errors, bad)

    if not bound or executed is None:
        executable = set()  # 未验证即不放行执行（fail-closed）
    if not record.unsupported and (unsupported or not executable):
        notes.append("response.unsupported 为空，但存在 unsupported/未执行曲线；记录未声明不支持项（不改变判定）")

    return _result(
        "response",
        errors,
        unsupported,
        notes,
        proposed=len(record.curves),
        executable=len(executable - bad),
    )


def _check_request_response_binding(
    response: ResponseModel,
    request: RequestModel,
    errors: list[dict[str, str]],
    notes: list[str],
) -> None:
    if response.request_id != request.request_id:
        errors.append(
            err(
                "stale_revision",
                "/request_id",
                f"response.request_id={response.request_id!r} 与 request.request_id={request.request_id!r} 不一致",
            )
        )
    for field in BINDING_ACTOR_FIELDS:
        if getattr(response.binding, field) != getattr(request.binding, field):
            errors.append(
                err(
                    "unknown_actor",
                    f"/binding/{field}",
                    f"response.binding.{field}={getattr(response.binding, field)!r} 与请求 "
                    f"{getattr(request.binding, field)!r} 不一致",
                )
            )
    for field in BINDING_REVISION_FIELDS:
        if getattr(response.binding, field) != getattr(request.binding, field):
            errors.append(
                err(
                    "stale_revision",
                    f"/binding/{field}",
                    f"response.binding.{field}={getattr(response.binding, field)!r} 与请求 "
                    f"{getattr(request.binding, field)!r} 不一致（旧版本不得改写新绑定）",
                )
            )
    for field in BINDING_CLOCK_FIELDS:
        if getattr(response.binding, field) != getattr(request.binding, field):
            errors.append(
                err(
                    "invalid_time_curve",
                    f"/binding/{field}",
                    f"response.binding.{field}={getattr(response.binding, field)!r} 与请求 "
                    f"{getattr(request.binding, field)!r} 不一致（时钟基准不得偷换）",
                )
            )
    for field in BINDING_IDENTITY_FIELDS:
        if getattr(response.binding, field) != getattr(request.binding, field):
            errors.append(
                err(
                    "stale_revision",
                    f"/binding/{field}",
                    f"response.binding.{field}={getattr(response.binding, field)!r} 与请求 "
                    f"{getattr(request.binding, field)!r} 不一致（响应必须绑定同一请求身份）",
                )
            )
    if request.locks:
        notes.append(f"请求含 {len(request.locks)} 条锁定项；曲线写者须为锁持有者或让出该范围")


def _check_curve(
    curve: CurveModel,
    base: str,
    *,
    render_fps: int,
    window: tuple[int, int] | None,
    caps: _Capabilities,
    aliases: Mapping[str, Sequence[str]],
    audio_ref: AudioRefModel | None,
    audio_aligned: bool,
    errors: list[dict[str, str]],
    unsupported: list[dict[str, str]],
    notes: list[str],
) -> bool:
    """单条曲线的语义检查；返回「其余条件都满足时是否可作为可执行候选」。"""
    can_execute = True
    phases = curve.phases
    bounds = (
        phases.start_tick,
        phases.anticipation_end_tick,
        phases.arrival_end_tick,
        phases.hold_end_tick,
        phases.end_tick,
    )
    labels = ("start", "anticipation_end", "arrival_end", "hold_end", "end")
    for left, right in zip(range(4), range(1, 5)):
        if bounds[left] >= bounds[right]:
            errors.append(
                err(
                    "invalid_time_curve",
                    f"{base}/phases/{labels[right]}_tick",
                    f"预备→到位→停留→回落必须严格递增（每段非空）：{labels[left]}={bounds[left]} "
                    f">= {labels[right]}={bounds[right]}；只有 hold/release 而缺到位的隐式曲线不接受",
                )
            )
    if window is not None:
        win_start, win_end = window
        if phases.start_tick < win_start or phases.end_tick > win_end:
            errors.append(
                err(
                    "invalid_time_curve",
                    f"{base}/phases",
                    f"阶段区间 [{phases.start_tick},{phases.end_tick}) 越出请求任务区间 [{win_start},{win_end})",
                )
            )

    ticks = [kf.tick for kf in curve.keyframes]
    start, end = phases.start_tick, phases.end_tick
    if any(b <= a for a, b in zip(ticks, ticks[1:])):
        errors.append(err("invalid_time_curve", f"{base}/keyframes", f"keyframe tick 必须严格递增且不重复：{ticks}"))
    if ticks[0] != start or ticks[-1] != end:
        errors.append(
            err(
                "invalid_time_curve",
                f"{base}/keyframes",
                f"keyframe 必须覆盖完整轨区间 [{start},{end}]（末端边界值允许落在 end_tick），"
                f"实际首尾 {ticks[0]}/{ticks[-1]}",
            )
        )
    deltas = [b - a for a, b in zip(ticks, ticks[1:])]

    if curve.channel in POSE_CHANNELS:
        for delta in deltas:
            if delta <= 0:
                continue
            if not on_frame_period_grid(delta, curve.timing, render_fps):
                errors.append(
                    err(
                        "invalid_time_curve",
                        f"{base}/keyframes",
                        f"{curve.timing} 在 {render_fps}fps 下应按 {frame_period_ticks(curve.timing, render_fps)} tick"
                        f"（{TIMING_FRAMES[curve.timing]} 个视频帧）保持，实际步长 {delta} tick；"
                        f"不能把一拍二硬写成每 {TIMING_FRAMES[curve.timing]} tick",
                    )
                )
                break
        for boundary in bounds[1:4]:
            if (boundary - start) * render_fps % SIM_HZ:
                notes.append(
                    f"{base}: 阶段边界 {boundary} 不在 {render_fps}fps 的整帧上（节奏只约束姿态呈现，按未验证记录）"
                )
                break
    elif deltas and any(delta > 0 and not on_frame_period_grid(delta, curve.timing, render_fps) for delta in deltas):
        notes.append(
            f"{base}: 非姿态轨 {curve.channel} 的 keyframe 步长不在 {curve.timing} 的视频帧网格上；"
            "节奏只约束姿态呈现，按未验证记录"
        )

    if curve.channel == "mouth":
        if not audio_aligned or audio_ref is None:
            errors.append(
                err(
                    "missing_audio_alignment",
                    f"{base}/channel",
                    "mouth 轨必须有可信音频与 aligned 产物；无音频/未对齐/对齐失败时不得写成功口型",
                )
            )
        else:
            for delta in deltas:
                if delta <= 0:
                    continue
                if not on_audio_sample_grid(delta, audio_ref.sample_rate):
                    errors.append(
                        err(
                            "invalid_time_curve",
                            f"{base}/keyframes",
                            f"口型 keyframe 步长 {delta} tick 在 {audio_ref.sample_rate}Hz 下不是整数 sample；"
                            "口型以锁定音频为基准，不得改速或降频",
                        )
                    )
                    break

    _check_curve_values(curve, base, caps, errors, notes)
    if not _check_curve_controller(curve, base, caps, errors, notes):
        can_execute = False

    _, registered = _expand_body_part(curve.body_part, aliases)
    if not registered:
        unsupported.append(
            {"path": f"{base}/body_part", "reason": f"部位别名未登记（{curve.body_part!r}）：控制权与锁定范围未验证"}
        )
        can_execute = False

    targets = caps.section("targets")
    if _is_string_sequence(targets) and curve.target_ref and curve.target_ref not in targets:
        errors.append(
            err("unsupported_action", f"{base}/target_ref", f"target_ref={curve.target_ref!r} 不在登记目标表中")
        )
    return can_execute


def _check_curve_values(
    curve: CurveModel,
    base: str,
    caps: _Capabilities,
    errors: list[dict[str, str]],
    notes: list[str],
) -> None:
    entry = caps.controllers().get(curve.controller_ref)
    registered_unit: Any = None
    registered_range: tuple[float, float] | None = None
    registered_dim: int | None = None
    if isinstance(entry, Mapping):
        registered_unit = entry.get("unit")
        rng = entry.get("value_range")
        if _is_string_sequence(rng) and len(rng) == 2:
            registered_range = (float(rng[0]), float(rng[1]))
        dim = entry.get("dim")
        if _is_int(dim):
            registered_dim = dim
    if registered_unit is not None and registered_unit != curve.unit:
        errors.append(
            err(
                "out_of_range",
                f"{base}/unit",
                f"unit={curve.unit!r} 与已登记控制器 {curve.controller_ref!r} 的 unit={registered_unit!r} 不符",
            )
        )
    low, high = registered_range or DEFAULT_UNIT_RANGES[curve.unit]
    dims: set[int] = set()
    for kf_index, keyframe in enumerate(curve.keyframes):
        vector = isinstance(keyframe.value, list)
        values = keyframe.value if vector else [keyframe.value]
        dims.add(len(values))
        for element_index, element in enumerate(values):
            pointer = f"{base}/keyframes/{kf_index}/value" + (pointer_join(element_index) if vector else "")
            if not _is_finite_number(element):
                errors.append(err("out_of_range", pointer, f"数值必须有限，实际 {element!r}"))
                continue
            if float(element) < low or float(element) > high:
                errors.append(
                    err(
                        "out_of_range",
                        pointer,
                        f"值 {element!r} 超出单位 {curve.unit!r} 的允许范围 [{low},{high}]"
                        + ("（显式能力表登记值域）" if registered_range else "（单位兜底范围；控制器未登记值域）"),
                    )
                )
    if len(dims) > 1:
        errors.append(err("out_of_range", f"{base}/keyframes", f"向量维度不一致：{sorted(dims)}（标量与向量不得混用）"))
    elif registered_dim is not None and dims and next(iter(dims)) != registered_dim:
        errors.append(
            err(
                "out_of_range",
                f"{base}/keyframes",
                f"向量维度 {next(iter(dims))} 与已登记控制器维度 {registered_dim} 不符",
            )
        )


def _check_curve_controller(
    curve: CurveModel,
    base: str,
    caps: _Capabilities,
    errors: list[dict[str, str]],
    notes: list[str],
) -> bool:
    """控制器/映射/执行状态语义；返回该曲线是否可作为可执行候选。"""
    entry = caps.controllers().get(curve.controller_ref)
    if curve.mapping_status == "pending_D5":
        if not curve.controller_ref.startswith(PENDING_PREFIX):
            errors.append(
                err(
                    "unknown_controller",
                    f"{base}/controller_ref",
                    f"mapping_status=pending_D5 的 controller_ref 必须以 {PENDING_PREFIX!r} 开头，"
                    f"实际 {curve.controller_ref!r}",
                )
            )
        if curve.execution_status != "unsupported":
            errors.append(
                err(
                    "unsupported_action",
                    f"{base}/execution_status",
                    "pending_D5 轨永不 executable：占位曲线不得回填为已执行/可执行",
                )
            )
        if not curve.unsupported_reason:
            errors.append(
                err("unsupported_action", f"{base}/unsupported_reason", "unsupported 轨必须给出 unsupported_reason")
            )
        if isinstance(entry, Mapping) and entry.get("executable") is True:
            errors.append(
                err(
                    "unsupported_action",
                    f"{base}/controller_ref",
                    "真实 D5 未完成：能力表不得把 pending:D5 占位登记为 executable",
                )
            )
        return False
    if curve.controller_ref.startswith("pending:"):
        errors.append(
            err(
                "unknown_controller",
                f"{base}/controller_ref",
                f"mapping_status=registered 却使用占位名 {curve.controller_ref!r}",
            )
        )
        return False
    if not caps.provided:
        errors.append(
            err(
                "unknown_controller",
                f"{base}/controller_ref",
                f"未显式传入控制器能力表，无法确认 {curve.controller_ref!r} 已注册（fail-closed）",
            )
        )
        return False
    if not isinstance(entry, Mapping):
        errors.append(
            err(
                "unknown_controller",
                f"{base}/controller_ref",
                f"controller_ref={curve.controller_ref!r} 不在显式能力表 controllers 中",
            )
        )
        return False
    if curve.execution_status == "unsupported":
        if not curve.unsupported_reason:
            errors.append(
                err("unsupported_action", f"{base}/unsupported_reason", "unsupported 轨必须给出 unsupported_reason")
            )
        return False
    if entry.get("executable") is not True:
        errors.append(
            err(
                "unsupported_action",
                f"{base}/execution_status",
                f"控制器 {curve.controller_ref!r} 已注册但未登记为 executable：不得声明 candidate",
            )
        )
        return False
    notes.append(f"{base}: 控制器 {curve.controller_ref!r} 由显式 fixture 能力表登记为 executable（非真实 D5）")
    return True


def _normalize_ranges(ranges: Iterable[Sequence[int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for item in ranges or ():
        if _is_string_sequence(item) and len(item) == 2:
            start, end = item
            if _is_int(start) and _is_int(end) and end > start:
                out.append((start, end))
    return out


def _request_window(request: RequestModel | None) -> tuple[int, int] | None:
    if request is None:
        return None
    return (request.start_tick, request.start_tick + request.duration_ticks)


def _check_ownership(
    curves: Sequence[CurveModel],
    aliases: Mapping[str, Sequence[str]],
    caps: _Capabilities,
    errors: list[dict[str, str]],
    notes: list[str],
    bad: set[int],
) -> None:
    """同一 actor 的生效部位（含别名展开）区间重叠即冲突；blend 必须显式登记规则与输入。"""
    rules = caps.blend_rules()
    for i in range(len(curves)):
        for j in range(i + 1, len(curves)):
            left, right = curves[i], curves[j]
            interval_left = (left.phases.start_tick, left.phases.end_tick)
            interval_right = (right.phases.start_tick, right.phases.end_tick)
            if not _intervals_overlap(interval_left, interval_right):
                continue
            parts_left, _ = _expand_body_part(left.body_part, aliases)
            parts_right, _ = _expand_body_part(right.body_part, aliases)
            shared = sorted(parts_left & parts_right)
            if not shared:
                continue
            if _blend_covers(left, right, rules) or _blend_covers(right, left, rules):
                notes.append(f"/curves/{i} 与 /curves/{j} 的重叠由已登记 blend 规则覆盖：{shared}")
                continue
            errors.append(
                err(
                    "control_conflict",
                    f"/curves/{j}",
                    f"同一 actor 的生效部位 {shared} 在 "
                    f"[{max(interval_left[0], interval_right[0])},{min(interval_left[1], interval_right[1])}) "
                    f"重叠：/curves/{i}（owner={left.owner.kind}:{left.owner.id}）与 "
                    f"/curves/{j}（owner={right.owner.kind}:{right.owner.id}）同优先级；"
                    "v0 不接受多写者或最后写入者胜出",
                )
            )
            bad.update({i, j})


def _blend_covers(writer: CurveModel, other: CurveModel, rules: Mapping[str, Any]) -> bool:
    """``writer`` 是否为已登记 blend 控制者且把 ``other`` 列为显式输入。"""
    if writer.owner.kind != "blend":
        return False
    rule = rules.get(writer.owner.id)
    if not isinstance(rule, Mapping):
        return False
    if not str(rule.get("rule", "")).strip():
        return False
    inputs = rule.get("inputs")
    if not _is_string_sequence(inputs):
        return False
    return other.controller_ref in inputs


def _check_curve_locks(
    curves: Sequence[CurveModel],
    aliases: Mapping[str, Sequence[str]],
    request: RequestModel | None,
    errors: list[dict[str, str]],
    bad: set[int],
) -> None:
    if request is None or not request.locks:
        return
    for index, curve in enumerate(curves):
        identity = _curve_identity_tokens(curve, aliases)
        for lock_index, lock in enumerate(request.locks):
            tokens = pointer_tokens(lock.path)
            if tokens is None:
                continue
            if not _lock_covers(tokens, index, identity):
                continue
            if curve.owner.kind == "user" and curve.owner.id == lock.by:
                continue
            errors.append(
                err(
                    "lock_conflict",
                    f"/curves/{index}",
                    f"曲线写者 owner={curve.owner.kind}:{curve.owner.id} 命中锁定项 /locks/{lock_index}"
                    f"（path={lock.path!r}，锁持有者={lock.by!r}）：锁定项最高约束，"
                    "改部位/控制器名字不改变生效身份",
                )
            )
            bad.add(index)


def _lock_covers(lock_tokens: Sequence[str], index: int, identity: frozenset[str]) -> bool:
    normalized = {_norm(token) for token in lock_tokens}
    if len(lock_tokens) >= 2 and _norm(lock_tokens[0]) == "curves":
        try:
            if int(lock_tokens[1]) == index:
                return True
        except ValueError:
            pass
    if normalized & _LOCK_IDENTITY_TOKENS:
        return True
    return bool(normalized & identity)


def _check_changed_past(
    curves: Sequence[CurveModel],
    executed: Sequence[tuple[int, int]],
    errors: list[dict[str, str]],
    bad: set[int],
) -> None:
    for index, curve in enumerate(curves):
        interval = (curve.phases.start_tick, curve.phases.end_tick)
        for start, end in executed:
            if _intervals_overlap(interval, (start, end)):
                errors.append(
                    err(
                        "changed_past",
                        f"/curves/{index}",
                        f"曲线区间 [{interval[0]},{interval[1]}) 与已执行/已播出区间 [{start},{end}) 重叠："
                        "不得更改已经执行/播出的区间",
                    )
                )
                bad.add(index)


# --------------------------------------------------------------------------------------
# error 记录校验
# --------------------------------------------------------------------------------------


def validate_error_record(error_record: Any, request: Any = None) -> ValidationResult:
    """校验 ``record_kind=error``：非空 errors、十码、r3 Pointer、不夹带成功曲线。"""
    errors: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []
    notes: list[str] = []
    record = _structure(errors, ErrorRecordModel, error_record, "/")
    if record is None:
        return _result("error", errors, unsupported, notes)

    request_model = _structure(errors, RequestModel, request, "/request") if request is not None else None
    if request_model is not None and record.request_id != request_model.request_id:
        errors.append(
            err(
                "stale_revision",
                "/request_id",
                f"error.request_id={record.request_id!r} 与 request.request_id={request_model.request_id!r} 不一致："
                "消费者必须校验与原请求关联",
            )
        )
    for index, item in enumerate(record.errors):
        if pointer_tokens(item.path) is None:
            errors.append(
                err("lock_conflict", f"/errors/{index}/path", f"错误 path 不是合法 JSON Pointer（D1 r3）：{item.path!r}")
            )
    notes.append("error 记录不写任何世界或表演状态；原提案保留，零静默修正")
    return _result("error", errors, unsupported, notes)


# --------------------------------------------------------------------------------------
# 顶层分发
# --------------------------------------------------------------------------------------


def validate_record(
    record: Any,
    request: Any = None,
    *,
    capabilities: Mapping[str, Any] | None = None,
    executed_tick_ranges: Iterable[Sequence[int]] | None = None,
) -> ValidationResult:
    """按 ``record_kind`` 分发；未知/缺失 record_kind 即 fail-closed。"""
    kind = record.get("record_kind") if isinstance(record, Mapping) else None
    if kind == "request":
        return validate_request(record, capabilities=capabilities)
    if kind == "response":
        return validate_response(
            record, request, capabilities=capabilities, executed_tick_ranges=executed_tick_ranges
        )
    if kind == "error":
        return validate_error_record(record, request)
    return _result(
        "unknown",
        [err("unsupported_action", "/record_kind", f"record_kind 必须是 {RECORD_KINDS} 之一，实际 {kind!r}")],
        [],
        [],
    )


def validate_exchange(
    request: Any,
    reply: Any,
    *,
    capabilities: Mapping[str, Any] | None = None,
    executed_tick_ranges: Iterable[Sequence[int]] | None = None,
) -> ExchangeResult:
    """成对校验：request +（response 或 error 记录）。"""
    return ExchangeResult(
        request=validate_request(request, capabilities=capabilities),
        reply=validate_record(
            reply,
            request,
            capabilities=capabilities,
            executed_tick_ranges=executed_tick_ranges,
        ),
    )


# --------------------------------------------------------------------------------------
# D1 schema 一致性（只接受已解析的 schema 对象，不读盘）
# --------------------------------------------------------------------------------------


def _schema_branch(schema: Mapping[str, Any], record_kind: str) -> Mapping[str, Any] | None:
    for branch in schema.get("oneOf", []):
        if isinstance(branch, Mapping) and branch.get("properties", {}).get("record_kind", {}).get("const") == record_kind:
            return branch
    return None


def _properties(node: Any) -> Mapping[str, Any]:
    if isinstance(node, Mapping) and isinstance(node.get("properties"), Mapping):
        return node["properties"]
    return {}


def _items_properties(node: Any) -> Mapping[str, Any]:
    """取数组 schema 的 items 对象属性。"""
    if isinstance(node, Mapping):
        return _properties(node.get("items"))
    return {}


def _alignment_status_enum(request_branch: Mapping[str, Any]) -> Any:
    audio = _properties(request_branch).get("audio_ref", {})
    for branch in audio.get("oneOf", []) if isinstance(audio, Mapping) else []:
        if isinstance(branch, Mapping) and branch.get("type") == "object":
            return _properties(_properties(branch).get("alignment")).get("status", {}).get("enum")
    return None


def schema_contract_drift(schema: Mapping[str, Any]) -> list[str]:
    """对比 D1 schema 枚举与本模块常量；返回漂移描述（空列表表示一致）。

    只吃已解析的 schema 对象，不做 IO；用于证明本模块复用而非改写 D1 合同。
    """
    drift: list[str] = []

    def compare(label: str, expected: Any, actual: Any) -> None:
        if expected != actual:
            drift.append(f"{label}: schema={actual!r} module={expected!r}")

    request_branch = _schema_branch(schema, "request")
    response_branch = _schema_branch(schema, "response")
    error_branch = _schema_branch(schema, "error")
    if request_branch is None or response_branch is None or error_branch is None:
        return ["schema 缺少 request/response/error 三个 oneOf 分支"]

    request_props = _properties(request_branch)
    compare("protocol", PROTOCOL, request_props.get("protocol", {}).get("const"))
    compare("sim_hz", SIM_HZ, _properties(request_props.get("binding")).get("sim_hz", {}).get("const"))
    compare("render_fps.maximum", 120, _properties(request_props.get("binding")).get("render_fps", {}).get("maximum"))
    compare(
        "record_kinds",
        list(RECORD_KINDS),
        [branch.get("properties", {}).get("record_kind", {}).get("const") for branch in schema.get("oneOf", [])],
    )

    curve_props = _items_properties(_properties(response_branch).get("curves"))
    compare("channels", list(CHANNELS), curve_props.get("channel", {}).get("enum"))
    compare("units", list(UNITS), curve_props.get("unit", {}).get("enum"))
    compare("timings", list(TIMINGS), curve_props.get("timing", {}).get("enum"))
    compare("interpolations", list(INTERPOLATIONS), curve_props.get("interpolation", {}).get("enum"))
    compare("mapping_statuses", list(MAPPING_STATUSES), curve_props.get("mapping_status", {}).get("enum"))
    compare("execution_statuses", list(EXECUTION_STATUSES), curve_props.get("execution_status", {}).get("enum"))
    compare("owner_kinds", list(OWNER_KINDS), _properties(curve_props.get("owner")).get("kind", {}).get("enum"))
    compare(
        "error_codes",
        list(ERROR_CODES),
        _items_properties(_properties(error_branch).get("errors")).get("code", {}).get("enum"),
    )
    compare("alignment_statuses", list(ALIGNMENT_STATUSES), _alignment_status_enum(request_branch))
    return drift


# --------------------------------------------------------------------------------------
# 内部工具
# --------------------------------------------------------------------------------------


def _structure(
    errors: list[dict[str, str]],
    model: type[BaseModel],
    data: Any,
    prefix: str,
) -> Any:
    """结构校验；失败时把 pydantic 错误映射成 D1 形状并返回 ``None``。"""
    if not isinstance(data, Mapping):
        errors.append(err("unsupported_action", prefix, f"记录必须是对象，实际 {type(data).__name__}"))
        return None
    try:
        return model.model_validate(dict(data))
    except ValidationError as exc:
        seen: set[tuple[str, str]] = set()
        for item in exc.errors():
            loc = tuple(part for part in item.get("loc", ()) if part not in _UNION_BRANCH_LABELS)
            suffix = pointer_join(*loc)
            path = suffix if prefix == "/" else prefix + suffix
            if not path:
                path = prefix
            code = structural_error_code(path, str(item.get("type", "")))
            if (code, path) in seen:
                continue
            seen.add((code, path))
            errors.append(err(code, path, f"结构层：{item.get('msg', '结构不成立')}"))
        return None


def _result(
    record_kind: str,
    errors: list[dict[str, str]],
    unsupported: list[dict[str, str]],
    notes: list[str],
    proposed: int = 0,
    executable: int = 0,
) -> ValidationResult:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in errors:
        key = (item["code"], item["path"], item["message"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    unique_unsupported: list[dict[str, str]] = []
    seen_unsupported: set[tuple[str, str]] = set()
    for item in unsupported:
        key = (item["path"], item["reason"])
        if key not in seen_unsupported:
            seen_unsupported.add(key)
            unique_unsupported.append(item)
    return ValidationResult(
        record_kind=record_kind,
        errors=tuple(deduped),
        unsupported=tuple(unique_unsupported),
        notes=tuple(dict.fromkeys(notes)),
        proposed_curves=proposed,
        executable_curves=executable,
    )
