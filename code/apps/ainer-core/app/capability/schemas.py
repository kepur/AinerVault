"""能力契约的 pydantic 模型。

严格对应 docs/v2/capability-api.openapi.yaml。Core 侧只用这些类型与中间层交互，
任何厂商细节都不出现在这里。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1.0"


class Capability(str, Enum):
    text_chat = "text.chat"
    text_translate = "text.translate"
    image_t2i = "image.text_to_image"
    image_i2i = "image.image_to_image"
    image_edit = "image.edit"
    image_upscale = "image.upscale"
    audio_tts = "audio.tts"
    audio_voice_list = "audio.voice_list"
    audio_music = "audio.music"
    audio_sfx = "audio.sfx"
    video_i2v = "video.image_to_video"


#: 主线必需能力。未声明的能力在后台自动置灰。
REQUIRED_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.text_chat,
        Capability.text_translate,
        Capability.image_t2i,
        Capability.image_i2i,
        Capability.audio_tts,
        Capability.audio_voice_list,
    }
)


class TaskState(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATES: frozenset[TaskState] = frozenset(
    {TaskState.succeeded, TaskState.failed, TaskState.cancelled}
)


class RefRole(str, Enum):
    """参考图语义。中间层负责映射到各厂商的具体机制；不支持的应忽略并 warn。"""

    character = "character"      # IP-Adapter FaceID / subject reference
    style = "style"              # style reference / LoRA
    composition = "composition"  # ControlNet pose / depth
    scene = "scene"              # 低强度 i2i / scene reference


class CameraMove(str, Enum):
    static = "static"
    push_in = "push_in"
    pull_out = "pull_out"
    pan_left = "pan_left"
    pan_right = "pan_right"
    tilt_up = "tilt_up"
    tilt_down = "tilt_down"
    orbit_left = "orbit_left"
    orbit_right = "orbit_right"
    handheld = "handheld"


# ── 媒体引用 ──────────────────────────────────────────────────────────────────

class AssetRefIn(BaseModel):
    """输入媒体引用，url / asset_id / b64 三选一。"""

    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    asset_id: str | None = None
    b64: str | None = None
    mime: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> AssetRefIn:
        if not (self.url or self.asset_id or self.b64):
            raise ValueError("AssetRefIn 需要 url / asset_id / b64 之一")
        if self.b64 and not self.mime:
            raise ValueError("b64 输入必须带 mime")
        return self


class AssetOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str
    mime: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ReferenceImage(BaseModel):
    ref: AssetRefIn
    role: RefRole
    weight: float = 0.8
    tag: str | None = None


# ── 请求信封 ──────────────────────────────────────────────────────────────────

class TaskOptions(BaseModel):
    priority: Literal["low", "normal", "high"] = "normal"
    timeout_ms: int = 300_000
    callback_url: str | None = None
    callback_secret: str | None = None
    max_cost: float | None = None
    trace_id: str | None = None


class TaskRequest(BaseModel):
    capability: Capability
    idempotency_key: str
    model: str | None = None
    input: dict[str, Any]
    options: TaskOptions = Field(default_factory=TaskOptions)


class Usage(BaseModel):
    model_config = ConfigDict(extra="allow")

    cost: float | None = None
    currency: str = "USD"
    duration_ms: int | None = None
    tokens: dict[str, int] | None = None
    units: dict[str, float] = Field(default_factory=dict)


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    retryable: bool | None = None
    provider_raw: dict[str, Any] | None = None


class TaskAccepted(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: str
    status: TaskState = TaskState.queued
    capability: Capability | None = None
    estimated_ms: int | None = None
    accepted_at: str | None = None


class Task(BaseModel):
    """任务终态/中间态。回调 body 与 GET /tasks/{id} 返回同一结构。"""

    model_config = ConfigDict(extra="allow")

    task_id: str
    status: TaskState
    capability: Capability | None = None
    progress: float | None = None
    output: dict[str, Any] | None = None
    usage: Usage | None = None
    provider: str | None = None
    model: str | None = None
    error: ErrorBody | None = None
    submitted_at: str | None = None
    finished_at: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    @property
    def warnings(self) -> list[str]:
        return list((self.output or {}).get("warnings") or [])


# ── Discovery ─────────────────────────────────────────────────────────────────

class Pricing(BaseModel):
    model_config = ConfigDict(extra="allow")

    unit: str | None = None
    cost: float | None = None
    currency: str = "USD"


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    id: str
    display_name: str
    default: bool = False
    async_only: bool = False
    estimated_ms: int | None = None
    pricing: Pricing | None = None
    limits: dict[str, Any] = Field(default_factory=dict)
    #: JSON Schema —— 后台据此自动渲染参数表单，加模型无需改前端
    param_schema: dict[str, Any] = Field(default_factory=dict)


class CapabilityEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    capability: Capability
    models: list[ModelDescriptor] = Field(default_factory=list)

    def default_model(self) -> ModelDescriptor | None:
        for m in self.models:
            if m.default:
                return m
        return self.models[0] if self.models else None


class CapabilityCatalog(BaseModel):
    model_config = ConfigDict(extra="allow")

    capability_version: str = CONTRACT_VERSION
    capabilities: list[CapabilityEntry] = Field(default_factory=list)

    def get(self, cap: Capability | str) -> CapabilityEntry | None:
        cap = Capability(cap) if isinstance(cap, str) else cap
        for entry in self.capabilities:
            if entry.capability == cap:
                return entry
        return None

    def supports(self, cap: Capability | str) -> bool:
        entry = self.get(cap)
        return bool(entry and entry.models)

    def missing_required(self) -> list[Capability]:
        return sorted(
            (c for c in REQUIRED_CAPABILITIES if not self.supports(c)), key=lambda c: c.value
        )


class Voice(BaseModel):
    model_config = ConfigDict(extra="allow")

    voice_id: str
    display_name: str
    languages: list[str] = Field(default_factory=list)
    gender: str | None = None
    age: str | None = None
    tags: list[str] = Field(default_factory=list)
    preview_url: str | None = None
    supports: dict[str, bool] = Field(default_factory=dict)


class HealthResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = False
    version: str | None = None
    upstreams: list[dict[str, Any]] = Field(default_factory=list)


# ── 各能力 input 构造器 ────────────────────────────────────────────────────────
# 只做类型与默认值约束，不含任何厂商逻辑。

class ChatInput(BaseModel):
    messages: list[dict[str, str]]
    temperature: float = 0.7
    max_tokens: int = 8192
    response_format: dict[str, Any] | None = None
    stream: bool = False


class TranslateSegment(BaseModel):
    id: str
    text: str
    kind: str | None = None
    speaker: str | None = None


class GlossaryEntry(BaseModel):
    source: str
    target: str
    note: str | None = None


class TranslateInput(BaseModel):
    source_language: str
    target_language: str
    segments: list[TranslateSegment]
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    style_prompt: str | None = None
    context_before: str | None = None
    context_after: str | None = None


class T2IInput(BaseModel):
    prompt: str
    negative_prompt: str | None = None
    width: int = 1280
    height: int = 720
    n: int = 1
    reference_images: list[ReferenceImage] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class I2IInput(BaseModel):
    """尾帧（后针）主用。

    strength 语义统一为「改动幅度」：0 保持原图，1 完全重绘。尾帧推荐 0.25–0.45。
    厂商语义相反的由中间层做 1-x 转换 —— 这是最容易出错的一处。
    """

    image: AssetRefIn
    prompt: str
    negative_prompt: str | None = None
    strength: float = 0.35
    reference_images: list[ReferenceImage] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class TTSInput(BaseModel):
    text: str
    language: str
    voice_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    reference_audio: AssetRefIn | None = None
    output_format: Literal["wav", "mp3", "ogg"] = "wav"
    sample_rate: int = 44100
    with_timestamps: bool = True


class MusicInput(BaseModel):
    prompt: str
    duration_ms: int
    loopable: bool = False
    instrumental: bool = True


class I2VInput(BaseModel):
    first_frame: AssetRefIn
    last_frame: AssetRefIn | None = None
    prompt: str | None = None
    duration_ms: int = 4000
    fps: int = 24
    width: int | None = None
    height: int | None = None
    camera: dict[str, Any] | None = None
    params: dict[str, Any] = Field(default_factory=dict)
