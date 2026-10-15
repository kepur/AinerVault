"""角色表演接口 v0 语义合同测试（hub.P1.D2）。

纯 CPU：不导入 MLX/ORT/模型，不渲染，不读媒体/数据库，不写生产库/RunStore，不碰关联项目。
D1 r3 的 schema/文档只读复用（逐字节 SHA 与 D1/D4 登记核对）；文件写入只用 pytest tmp_path。
标准例子直接取自 D1 schema 的 ``examples``，反例在内存里派生，不改作者 schema。
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
from fractions import Fraction
from pathlib import Path

import pytest

from app.production import performance_contract as pc

REPO = Path(__file__).resolve().parents[4]
SCHEMA_SRC = REPO / "docs" / "v2" / "production_brain" / "performance_interface_v0.schema.json"
DOC_SRC = REPO / "docs" / "v2" / "production_brain" / "performance_interface_v0.md"
D1_R3_IDENTITIES = REPO / "reports" / "production-brain" / "D1-r3" / "identities.json"
D4_ARTIFACT_IDENTITIES = REPO / "reports" / "production-brain" / "D1-independent-r3" / "artifact-identities.json"
R2_ARCHIVE_SCHEMA = REPO / "reports" / "production-brain" / "D1-r3" / "r2-performance_interface_v0.schema.json"
R2_ARCHIVE_DOC = REPO / "reports" / "production-brain" / "D1-r3" / "r2-performance_interface_v0.md"

#: D1 r3 作者登记（reports/production-brain/D1-r3/identities.json）。
D1_R3_SCHEMA_SHA = "34aba041558ecbc279ca84d2e846c76ee2334dd621433c086e9b150640b7d23c"
D1_R3_DOC_SHA = "73c3e88952e50f9e720ac2f80debe2915884a014f8498177e94de6c9ff039946"
#: D1 r2 原字节归档（D4 r3 报告登记的输入身份）。
R2_SCHEMA_SHA = "c8ce4696a960294de7731d7956a7c3e373eef4b2232e909354dc30230b8bbec5"
R2_DOC_SHA = "39d1743a69685408775971bbdb6633c2c6357e90aa781c1ac21a3f4678df15ff"

HEX_A = "a" * 64
HEX_B = "b" * 64
TAKES = ("suspense", "comedy", "dry")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_schema() -> dict:
    """只读加载 D1 r3 schema（不复制、不改写）。"""
    return json.loads(SCHEMA_SRC.read_text(encoding="utf-8"))


def examples(kind: str) -> list[dict]:
    return [item for item in load_schema()["examples"] if item.get("record_kind") == kind]


def example_request(take: str) -> dict:
    rid = f"fixture-request-{take}"
    return next(item for item in examples("request") if item["request_id"] == rid)


def example_response(take: str) -> dict:
    rid = f"fixture-request-{take}"
    return next(item for item in examples("response") if item["request_id"] == rid)


def artifact_sha(path: Path) -> str | None:
    """在 D4 artifact-identities.json 里查登记 SHA（结构不熟时返回 None）。"""
    if not D4_ARTIFACT_IDENTITIES.exists():
        return None
    try:
        entries = json.loads(D4_ARTIFACT_IDENTITIES.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and Path(str(entry.get("path", ""))) == path:
            return entry.get("sha256")
    return None


# --------------------------------------------------------------------------------------
# fixture：显式能力表 + 已注册控制器曲线（唯一入口是参数，不读盘）
# --------------------------------------------------------------------------------------


def fixture_capabilities(**overrides) -> dict:
    caps = {
        "controllers": {
            "fixture:ctl/head/turn": {
                "channel": "head_pose",
                "body_part": "head",
                "unit": "degree",
                "dim": 1,
                "value_range": [-90, 90],
                "executable": True,
            },
            "fixture:ctl/mouth/shape": {
                "channel": "mouth",
                "body_part": "face",
                "unit": "normalized",
                "dim": 1,
                "value_range": [0, 1],
                "executable": True,
            },
        },
        "aliases": {"head": ["head", "cranium"], "face": ["face", "head/face"]},
        "characters": ["fixture-heroine"],
        "intents": ["hesitant", "surprised", "deadpan"],
        "targets": ["fixture-elephant"],
    }
    caps.update(overrides)
    return caps


def fixture_request(**overrides) -> dict:
    request = {
        "protocol": pc.PROTOCOL,
        "record_kind": "request",
        "request_id": "fixture-request-d2",
        "binding": {
            "plan_id": "fixture-bag-elephant",
            "plan_revision": 0,
            "beat_id": "fixture-reveal",
            "event_id": "fixture-transform",
            "world_id": "fixture-world",
            "world_version": 1,
            "scene_id": "fixture-scene",
            "scene_revision": 0,
            "take_id": "fixture-d2",
            "actor_id": "fixture-heroine",
            "character_ref": "fixture:char/heroine",
            "sim_hz": 120,
            "render_fps": 24,
        },
        "intent": "hesitant",
        "intensity": 0.65,
        "target_ref": "fixture-elephant",
        "start_tick": 0,
        "duration_ticks": 600,
        "locks": [],
        "audio_ref": None,
    }
    request.update(overrides)
    return request


def fixture_curve(**overrides) -> dict:
    """已注册 head_pose 曲线：twos@24fps = 10 tick 网格，阶段 0/60/180/420/600。"""
    curve = {
        "channel": "head_pose",
        "body_part": "head",
        "controller_ref": "fixture:ctl/head/turn",
        "mapping_status": "registered",
        "execution_status": "candidate",
        "unit": "degree",
        "phases": {
            "start_tick": 0,
            "anticipation_end_tick": 60,
            "arrival_end_tick": 180,
            "hold_end_tick": 420,
            "end_tick": 600,
        },
        "timing": "twos",
        "interpolation": "linear",
        "owner": {"kind": "director", "id": "fixture-director", "authorization_ref": "fixture-only-not-authorization"},
        "keyframes": [
            {"tick": 0, "value": 0},
            {"tick": 60, "value": 30},
            {"tick": 180, "value": 30},
            {"tick": 420, "value": 0},
            {"tick": 600, "value": 0},
        ],
    }
    curve.update(overrides)
    return curve


def fixture_response(request: dict, curves: list[dict] | None = None, **overrides) -> dict:
    response = {
        "protocol": pc.PROTOCOL,
        "record_kind": "response",
        "response_id": "fixture-response-d2",
        "request_id": request["request_id"],
        "binding": copy.deepcopy(request["binding"]),
        "curves": [] if curves is None else curves,
        "unsupported": [{"path": "/curves", "reason": "fixture: not executed"}],
    }
    response.update(overrides)
    return response


def with_mouth_audio(request: dict, *, sample_rate: int = 48000, status: str = "aligned") -> dict:
    request = copy.deepcopy(request)
    audio = {
        "asset_ref": "fixture:audio/no-real-media",
        "sha256": HEX_A,
        "sample_rate": sample_rate,
        "anchor_tick": 0,
        "offset_samples": -2400,
        "alignment": {"status": status},
    }
    if status == "aligned":
        audio["alignment"].update({"ref": "fixture:alignment/no-real-media", "sha256": HEX_B})
    request["audio_ref"] = audio
    return request


def codes(result: pc.ValidationResult) -> list[str]:
    return result.error_codes()


def paths_with_code(result: pc.ValidationResult, code: str) -> list[str]:
    return [item["path"] for item in result.errors if item["code"] == code]


# --------------------------------------------------------------------------------------
# D1 r3 身份：schema/文档未被本任务改写
# --------------------------------------------------------------------------------------


def test_d1_schema_and_doc_bytes_match_upstream_registry(tmp_path):
    registry = {entry["path"]: entry["sha256"] for entry in json.loads(D1_R3_IDENTITIES.read_text(encoding="utf-8"))}
    assert sha256_of(SCHEMA_SRC) == D1_R3_SCHEMA_SHA == registry[str(SCHEMA_SRC)]
    assert sha256_of(DOC_SRC) == D1_R3_DOC_SHA == registry[str(DOC_SRC)]
    (tmp_path / "d1-identities-check.json").write_text(
        json.dumps({"schema": sha256_of(SCHEMA_SRC), "doc": sha256_of(DOC_SRC)}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_d1_r2_archives_unchanged(tmp_path):
    assert sha256_of(R2_ARCHIVE_SCHEMA) == R2_SCHEMA_SHA
    assert sha256_of(R2_ARCHIVE_DOC) == R2_DOC_SHA
    assert artifact_sha(R2_ARCHIVE_SCHEMA) in (None, R2_SCHEMA_SHA)
    assert artifact_sha(R2_ARCHIVE_DOC) in (None, R2_DOC_SHA)
    (tmp_path / "r2-archive-check.json").write_text(
        json.dumps({"schema": sha256_of(R2_ARCHIVE_SCHEMA), "doc": sha256_of(R2_ARCHIVE_DOC)}),
        encoding="utf-8",
    )


def test_module_constants_match_d1_schema_enums(tmp_path):
    schema_copy = tmp_path / "performance_interface_v0.schema.json"
    schema_copy.write_bytes(SCHEMA_SRC.read_bytes())
    drift = pc.schema_contract_drift(json.loads(schema_copy.read_text(encoding="utf-8")))
    assert drift == []
    assert len(pc.ERROR_CODES) == 10
    assert pc.SIM_HZ == 120


def test_d1_schema_examples_cover_three_takes_and_error_record():
    assert {item["request_id"] for item in examples("request")} == {
        "fixture-request-suspense",
        "fixture-request-comedy",
        "fixture-request-dry",
        "fixture-audio-clock",
    }
    assert {item["request_id"] for item in examples("response")} == {
        "fixture-request-suspense",
        "fixture-request-comedy",
        "fixture-request-dry",
    }
    assert {item["request_id"] for item in examples("error")} == {"fixture-audio-clock"}


# --------------------------------------------------------------------------------------
# 三版本例子：语义通过，但全部仍是候选 / 未支持
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("take", TAKES)
def test_three_request_examples_pass_semantics(take):
    result = pc.validate_request(example_request(take))
    assert result.ok, result.errors
    assert result.executable is False


@pytest.mark.parametrize("take", TAKES)
def test_three_response_examples_pass_semantics_and_stay_unsupported(take, tmp_path):
    request = example_request(take)
    response = example_response(take)
    result = pc.validate_response(response, request, executed_tick_ranges=[])
    assert result.ok, result.errors
    assert result.proposed_curves == 1
    assert result.executable_curves == 0
    assert result.executable is False
    assert all(curve["mapping_status"] == "pending_D5" for curve in response["curves"])
    assert all(curve["execution_status"] == "unsupported" for curve in response["curves"])
    assert all(curve["controller_ref"].startswith(pc.PENDING_PREFIX) for curve in response["curves"])
    assert any(item["reason"] for item in result.unsupported)
    (tmp_path / f"take-{take}.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("take", TAKES)
def test_three_examples_never_claim_execution(take):
    request = example_request(take)
    result = pc.validate_exchange(
        request, example_response(take), capabilities=None, executed_tick_ranges=[]
    )
    assert result.ok, (result.request.errors, result.reply.errors)
    assert result.reply.executable is False
    assert all("pending" in curve["controller_ref"] for curve in example_response(take)["curves"])


def test_audio_clock_request_requires_missing_audio_alignment():
    request = next(item for item in examples("request") if item["request_id"] == "fixture-audio-clock")
    result = pc.validate_request(request)
    assert result.ok is False
    assert codes(result) == ["missing_audio_alignment"]
    assert paths_with_code(result, "missing_audio_alignment") == ["/audio_ref/alignment"]


def test_audio_clock_error_record_validates_and_binds_request():
    request = next(item for item in examples("request") if item["request_id"] == "fixture-audio-clock")
    error_record = examples("error")[0]
    result = pc.validate_error_record(error_record, request)
    assert result.ok, result.errors
    mismatched = copy.deepcopy(error_record)
    mismatched["request_id"] = "fixture-request-other"
    assert codes(pc.validate_error_record(mismatched, request)) == ["stale_revision"]


def test_three_examples_do_not_smuggle_execution_through_unsupported_list():
    for take in TAKES:
        response = example_response(take)
        result = pc.validate_response(response, example_request(take), executed_tick_ranges=[])
        assert result.executable is False
        assert all(curve["mapping_status"] == "pending_D5" for curve in response["curves"])


# --------------------------------------------------------------------------------------
# 120Hz ↔ 输出 fps 换算与节奏网格
# --------------------------------------------------------------------------------------


def test_ticks_per_frame_is_exact_rational():
    assert pc.ticks_per_frame(24) == Fraction(5)
    assert pc.ticks_per_frame(30) == Fraction(4)
    assert pc.ticks_per_frame(120) == Fraction(1)
    assert pc.ticks_per_frame(25) == Fraction(24, 5)  # 不取整


def test_frame_period_ticks_ones_twos_threes():
    assert pc.frame_period_ticks("ones", 24) == Fraction(5)
    assert pc.frame_period_ticks("twos", 24) == Fraction(10)
    assert pc.frame_period_ticks("threes", 24) == Fraction(15)
    assert pc.frame_period_ticks("twos", 30) == Fraction(8)


def test_frame_grid_rejects_tick_stepping_instead_of_frames():
    assert pc.on_frame_period_grid(10, "twos", 24) is True
    assert pc.on_frame_period_grid(2, "twos", 24) is False  # 「一拍二」不是每 2 tick
    assert pc.on_frame_period_grid(5, "ones", 24) is True
    assert pc.on_frame_period_grid(15, "threes", 24) is True
    # 120 不能被 fps 整除时网格稀疏：25fps ones = 24 tick，不取整
    assert pc.on_frame_period_grid(5, "ones", 25) is False
    assert pc.on_frame_period_grid(24, "ones", 25) is True


def test_tick_to_frame_exactness():
    assert pc.tick_to_frame(120, 24) == Fraction(24)
    assert pc.tick_to_frame(5, 24) == Fraction(1)
    assert pc.tick_to_frame(1, 25) == Fraction(25, 120)
    assert pc.tick_to_frame(130, 24, origin_tick=10) == Fraction(24)


def test_pose_curve_tick_stepping_rejected():
    request = fixture_request()
    curve = fixture_curve(
        keyframes=[
            {"tick": 0, "value": 0},
            {"tick": 2, "value": 30},
            {"tick": 600, "value": 0},
        ],
        phases={
            "start_tick": 0,
            "anticipation_end_tick": 2,
            "arrival_end_tick": 4,
            "hold_end_tick": 598,
            "end_tick": 600,
        },
    )
    result = pc.validate_response(fixture_response(request, [curve]), request, capabilities=fixture_capabilities())
    assert codes(result) == ["invalid_time_curve"]
    assert "10 tick" in result.errors[0]["message"]


def test_sparse_frame_grid_for_25fps_pose_curve():
    request = fixture_request()
    request["binding"]["render_fps"] = 25
    curve = fixture_curve(
        timing="ones",
        keyframes=[{"tick": 0, "value": 0}, {"tick": 5, "value": 30}, {"tick": 600, "value": 0}],
        phases={
            "start_tick": 0,
            "anticipation_end_tick": 5,
            "arrival_end_tick": 6,
            "hold_end_tick": 595,
            "end_tick": 600,
        },
    )
    result = pc.validate_response(fixture_response(request, [curve]), request, capabilities=fixture_capabilities())
    assert codes(result) == ["invalid_time_curve"]

    on_grid = fixture_curve(
        timing="ones",
        keyframes=[{"tick": 0, "value": 0}, {"tick": 24, "value": 30}, {"tick": 600, "value": 0}],
        phases={
            "start_tick": 0,
            "anticipation_end_tick": 24,
            "arrival_end_tick": 48,
            "hold_end_tick": 576,
            "end_tick": 600,
        },
    )
    ok = pc.validate_response(
        fixture_response(request, [on_grid]), request, capabilities=fixture_capabilities(), executed_tick_ranges=[]
    )
    assert ok.ok, ok.errors
    assert ok.executable is True


def test_non_pose_curve_off_grid_is_note_not_error():
    request = fixture_request()
    curve = fixture_curve(channel="facial_unit", body_part="face", unit="degree")
    curve["keyframes"] = [{"tick": 0, "value": 0}, {"tick": 7, "value": 10}, {"tick": 600, "value": 0}]
    result = pc.validate_response(fixture_response(request, [curve]), request, capabilities=fixture_capabilities())
    assert result.ok, result.errors
    assert any("非姿态轨" in note for note in result.notes)


def test_pose_phase_boundaries_off_frame_grid_recorded():
    request = fixture_request()
    curve = fixture_curve(
        keyframes=[{"tick": 0, "value": 0}, {"tick": 63, "value": 30}, {"tick": 600, "value": 0}],
        phases={
            "start_tick": 0,
            "anticipation_end_tick": 63,
            "arrival_end_tick": 183,
            "hold_end_tick": 423,
            "end_tick": 600,
        },
    )
    result = pc.validate_response(fixture_response(request, [curve]), request, capabilities=fixture_capabilities())
    assert codes(result) == ["invalid_time_curve"]  # 63 不在 twos@24fps 的 10 tick 网格上
    assert any("整帧" in note or "未验证" in note for note in result.notes)


# --------------------------------------------------------------------------------------
# 音频时钟与口型
# --------------------------------------------------------------------------------------


def test_audio_clock_formula_exact():
    audio = {"sample_rate": 48000, "anchor_tick": 0, "offset_samples": -2400}
    assert pc.sample_of_tick(0, audio) == Fraction(-2400)
    assert pc.sample_of_tick(6, audio) == Fraction(0)
    assert pc.sample_of_tick(12, audio) == Fraction(2400)
    assert pc.sample_of_tick(1, audio) == Fraction(400 - 2400)
    shifted = {"sample_rate": 48000, "anchor_tick": 6, "offset_samples": 0}
    assert pc.sample_of_tick(6, shifted) == Fraction(0)


def test_audio_clock_is_independent_of_render_fps_and_timing():
    """音频/口型不跟着渲染降频：换算只吃 sample_rate/anchor/offset。"""
    audio = {"sample_rate": 44100, "anchor_tick": 0, "offset_samples": 0}
    assert pc.sample_of_tick(120, audio) == Fraction(44100)
    assert pc.on_audio_sample_grid(2, 44100) is True
    assert pc.on_audio_sample_grid(1, 44100) is False
    assert pc.on_audio_sample_grid(1, 48000) is True


def test_mouth_curve_without_audio_rejected():
    request = fixture_request()
    mouth = fixture_curve(
        channel="mouth",
        body_part="face",
        controller_ref="pending:D5/face/mouth",
        mapping_status="pending_D5",
        execution_status="unsupported",
        unsupported_reason="D5 controller registry not available",
        unit="normalized",
        timing="ones",
        keyframes=[{"tick": 0, "value": 0}, {"tick": 5, "value": 0.5}, {"tick": 600, "value": 0}],
        phases={
            "start_tick": 0,
            "anticipation_end_tick": 5,
            "arrival_end_tick": 10,
            "hold_end_tick": 590,
            "end_tick": 600,
        },
    )
    result = pc.validate_response(fixture_response(request, [mouth]), request, executed_tick_ranges=[])
    assert "missing_audio_alignment" in codes(result)
    assert result.executable is False


def test_mouth_curve_with_pending_alignment_rejected():
    request = with_mouth_audio(fixture_request(), status="pending")
    mouth = fixture_curve(channel="mouth", body_part="face", unit="normalized", timing="ones")
    mouth["controller_ref"] = "fixture:ctl/mouth/shape"
    mouth["keyframes"] = [{"tick": 0, "value": 0}, {"tick": 5, "value": 0.5}, {"tick": 600, "value": 0}]
    mouth["phases"] = {
        "start_tick": 0,
        "anticipation_end_tick": 5,
        "arrival_end_tick": 10,
        "hold_end_tick": 590,
        "end_tick": 600,
    }
    assert pc.validate_request(request).ok is False
    result = pc.validate_response(
        fixture_response(request, [mouth]), request, capabilities=fixture_capabilities(), executed_tick_ranges=[]
    )
    assert "missing_audio_alignment" in codes(result)


def test_mouth_curve_with_aligned_audio_and_registered_controller_ok():
    request = with_mouth_audio(fixture_request())
    mouth = fixture_curve(channel="mouth", body_part="face", unit="normalized", controller_ref="fixture:ctl/mouth/shape")
    mouth["keyframes"] = [{"tick": 0, "value": 0}, {"tick": 5, "value": 0.5}, {"tick": 600, "value": 0}]
    mouth["phases"] = {
        "start_tick": 0,
        "anticipation_end_tick": 5,
        "arrival_end_tick": 10,
        "hold_end_tick": 590,
        "end_tick": 600,
    }
    result = pc.validate_response(
        fixture_response(request, [mouth]), request, capabilities=fixture_capabilities(), executed_tick_ranges=[]
    )
    assert result.ok, result.errors
    assert result.executable is True


def test_mouth_keyframe_off_audio_sample_grid_rejected():
    request = with_mouth_audio(fixture_request(), sample_rate=44100)
    mouth = fixture_curve(channel="mouth", body_part="face", unit="normalized", controller_ref="fixture:ctl/mouth/shape")
    mouth["keyframes"] = [{"tick": 0, "value": 0}, {"tick": 5, "value": 0.5}, {"tick": 600, "value": 0}]
    mouth["phases"] = {
        "start_tick": 0,
        "anticipation_end_tick": 5,
        "arrival_end_tick": 10,
        "hold_end_tick": 590,
        "end_tick": 600,
    }
    result = pc.validate_response(
        fixture_response(request, [mouth]), request, capabilities=fixture_capabilities(), executed_tick_ranges=[]
    )
    assert codes(result) == ["invalid_time_curve"]
    assert "整数 sample" in result.errors[0]["message"]


# --------------------------------------------------------------------------------------
# 阶段顺序 / 任务边界 / keyframe 覆盖
# --------------------------------------------------------------------------------------


def test_inverted_phase_order_rejected():
    curve = fixture_curve()
    curve["phases"]["arrival_end_tick"] = 30  # 到位早于预备结束
    result = pc.validate_response(
        fixture_response(fixture_request(), [curve]), fixture_request(), capabilities=fixture_capabilities()
    )
    assert codes(result) == ["invalid_time_curve"]
    assert "严格递增" in result.errors[0]["message"]


def test_degenerate_phase_stage_rejected():
    curve = fixture_curve()
    curve["phases"]["hold_end_tick"] = curve["phases"]["arrival_end_tick"]  # 缺停留
    result = pc.validate_response(
        fixture_response(fixture_request(), [curve]), fixture_request(), capabilities=fixture_capabilities()
    )
    assert codes(result) == ["invalid_time_curve"]


def test_negative_or_shifted_duration_rejected():
    request = fixture_request()
    request["duration_ticks"] = -600
    assert codes(pc.validate_request(request)) == ["invalid_time_curve"]
    request = fixture_request()
    request["start_tick"] = -1
    assert codes(pc.validate_request(request)) == ["invalid_time_curve"]
    request = fixture_request()
    request["duration_ticks"] = 0
    assert codes(pc.validate_request(request)) == ["invalid_time_curve"]


def test_phases_outside_request_window_rejected():
    request = fixture_request()
    request["duration_ticks"] = 400  # 任务区间 [0,400)，曲线跑到 600
    curve = fixture_curve()
    result = pc.validate_response(fixture_response(request, [curve]), request)
    assert "invalid_time_curve" in codes(result)
    assert any("越出请求任务区间" in item["message"] for item in result.errors)


def test_duplicate_keyframe_ticks_rejected():
    curve = fixture_curve()
    curve["keyframes"] = [
        {"tick": 0, "value": 0},
        {"tick": 180, "value": 30},
        {"tick": 180, "value": 20},
        {"tick": 600, "value": 0},
    ]
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert "invalid_time_curve" in codes(result)


def test_keyframes_must_cover_track_interval():
    curve = fixture_curve()
    curve["keyframes"] = [{"tick": 10, "value": 0}, {"tick": 600, "value": 0}]
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert "invalid_time_curve" in codes(result)
    assert any("覆盖完整轨区间" in item["message"] for item in result.errors)


def test_keyframe_out_of_order_rejected():
    curve = fixture_curve()
    curve["keyframes"] = [{"tick": 0, "value": 0}, {"tick": 300, "value": 30}, {"tick": 200, "value": 0}, {"tick": 600, "value": 0}]
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert "invalid_time_curve" in codes(result)


def test_single_keyframe_rejected_structurally():
    curve = fixture_curve()
    curve["keyframes"] = [{"tick": 0, "value": 0}]
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert result.ok is False
    assert result.errors[0]["path"] == "/curves/0/keyframes"


# --------------------------------------------------------------------------------------
# 值：有限、范围、单位、维度
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_rejected(bad):
    curve = fixture_curve()
    curve["keyframes"][1]["value"] = bad
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert codes(result) == ["out_of_range"]
    assert result.errors[0]["path"] == "/curves/0/keyframes/1/value"


@pytest.mark.parametrize("bad", [400.0, -400.0, 90.5])
def test_out_of_unit_range_rejected(bad):
    curve = fixture_curve()  # degree；能力表 value_range=[-90,90]
    curve["keyframes"][1]["value"] = bad
    result = pc.validate_response(
        fixture_response(fixture_request(), [curve]), fixture_request(), capabilities=fixture_capabilities()
    )
    assert set(codes(result)) == {"out_of_range"}


def test_unit_fallback_range_without_registry():
    """无能力表时按单位兜底值域校验，并额外报未注册控制器。"""
    curve = fixture_curve(unit="normalized")
    curve["keyframes"][1]["value"] = 1.5
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert "out_of_range" in codes(result)
    assert "unknown_controller" in codes(result)


def test_registered_value_range_and_unit_used():
    curve = fixture_curve()
    curve["keyframes"][1]["value"] = 91  # 能力表 value_range=[-90,90]
    result = pc.validate_response(
        fixture_response(fixture_request(), [curve]), fixture_request(), capabilities=fixture_capabilities()
    )
    assert codes(result) == ["out_of_range"]

    curve = fixture_curve(unit="normalized")  # 与已登记 degree 不符
    result = pc.validate_response(
        fixture_response(fixture_request(), [curve]), fixture_request(), capabilities=fixture_capabilities()
    )
    assert "out_of_range" in codes(result)
    assert any("unit" in item["message"] for item in result.errors)


def test_vector_dimension_mismatch_rejected():
    curve = fixture_curve()
    curve["keyframes"] = [
        {"tick": 0, "value": [0, 0]},
        {"tick": 600, "value": [1, 2]},
    ]
    result = pc.validate_response(
        fixture_response(fixture_request(), [curve]), fixture_request(), capabilities=fixture_capabilities()
    )
    assert "out_of_range" in codes(result)  # 已登记 dim=1

    curve = fixture_curve()
    curve["keyframes"] = [{"tick": 0, "value": [0, 0]}, {"tick": 600, "value": 1}]
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert "out_of_range" in codes(result)
    assert any("维度不一致" in item["message"] for item in result.errors)


def test_bool_is_not_a_number():
    curve = fixture_curve()
    curve["keyframes"][1]["value"] = True
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert result.ok is False
    assert result.errors[0]["path"] == "/curves/0/keyframes/1/value"


# --------------------------------------------------------------------------------------
# 控制器注册 / pending:D5 / 可执行性
# --------------------------------------------------------------------------------------


def test_registered_controller_without_capability_table_rejected():
    curve = fixture_curve()
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert codes(result) == ["unknown_controller"]


def test_unknown_controller_rejected():
    curve = fixture_curve(controller_ref="fixture:ctl/unknown/thing")
    result = pc.validate_response(
        fixture_response(fixture_request(), [curve]), fixture_request(), capabilities=fixture_capabilities()
    )
    assert codes(result) == ["unknown_controller"]


def test_pending_d5_curve_stays_unsupported_with_registry():
    curve = fixture_curve(
        controller_ref="pending:D5/face/hesitant",
        mapping_status="pending_D5",
        execution_status="unsupported",
        unsupported_reason="D5 controller registry not available",
    )
    result = pc.validate_response(
        fixture_response(fixture_request(), [curve]),
        fixture_request(),
        capabilities=fixture_capabilities(),
        executed_tick_ranges=[],
    )
    assert result.ok, result.errors
    assert result.executable is False
    assert any(item["path"] == "/curves/0" for item in result.unsupported)
    assert any("D5" in item["reason"] for item in result.unsupported)


def test_pending_d5_claimed_executable_rejected():
    curve = fixture_curve(
        controller_ref="pending:D5/face/hesitant",
        mapping_status="pending_D5",
        execution_status="candidate",
        unsupported_reason=None,
    )
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert "unsupported_action" in codes(result)


def test_capability_table_cannot_mark_pending_controller_executable():
    caps = fixture_capabilities()
    caps["controllers"]["pending:D5/face/hesitant"] = {"unit": "normalized", "executable": True}
    curve = fixture_curve(
        controller_ref="pending:D5/face/hesitant",
        mapping_status="pending_D5",
        execution_status="unsupported",
        unsupported_reason="D5 controller registry not available",
    )
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request(), capabilities=caps)
    assert "unsupported_action" in codes(result)
    assert result.executable is False


def test_registered_but_not_executable_cannot_claim_candidate():
    caps = fixture_capabilities()
    caps["controllers"]["fixture:ctl/head/turn"]["executable"] = False
    curve = fixture_curve()
    result = pc.validate_response(
        fixture_response(fixture_request(), [curve]),
        fixture_request(),
        capabilities=caps,
        executed_tick_ranges=[],
    )
    assert codes(result) == ["unsupported_action"]
    assert result.executable is False


def test_registered_pending_name_mismatch_rejected():
    curve = fixture_curve(controller_ref="pending:D5/x")
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    assert "unknown_controller" in codes(result)


def test_fully_registered_fixture_curve_is_executable():
    """正例：只有全部由显式 fixture 能力表登记、且已执行区间显式声明时才可执行。"""
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    result = pc.validate_response(
        response, request, capabilities=fixture_capabilities(), executed_tick_ranges=[]
    )
    assert result.ok, result.errors
    assert result.proposed_curves == 1
    assert result.executable_curves == 1
    assert result.executable is True


def test_execution_blocked_without_executed_tick_ranges():
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    result = pc.validate_response(response, request, capabilities=fixture_capabilities(), executed_tick_ranges=None)
    assert result.ok, result.errors
    assert result.executable is False
    assert any("changed_past" in item["reason"] for item in result.unsupported)


def test_execution_blocked_without_request_binding():
    response = fixture_response(fixture_request(), [fixture_curve()])
    result = pc.validate_response(response, None, capabilities=fixture_capabilities(), executed_tick_ranges=[])
    assert result.ok, result.errors
    assert result.executable is False
    assert any("绑定未验证" in item["reason"] for item in result.unsupported)


def test_unregistered_body_part_alias_blocks_execution():
    caps = fixture_capabilities(aliases={})
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    result = pc.validate_response(response, request, capabilities=caps, executed_tick_ranges=[])
    assert result.ok, result.errors
    assert result.executable is False
    assert any("别名未登记" in item["reason"] for item in result.unsupported)


# --------------------------------------------------------------------------------------
# 控制者与别名部位重叠
# --------------------------------------------------------------------------------------


def _two_curves(first: dict, second: dict) -> tuple[dict, dict]:
    request = fixture_request()
    return request, fixture_response(request, [first, second])


def test_same_body_part_double_write_conflict():
    first = fixture_curve()
    second = fixture_curve(owner={"kind": "runtime", "id": "fixture-runtime", "authorization_ref": "fixture-ref"})
    request, response = _two_curves(first, second)
    result = pc.validate_response(response, request, capabilities=fixture_capabilities(), executed_tick_ranges=[])
    assert codes(result) == ["control_conflict"]
    assert result.errors[0]["path"] == "/curves/1"
    assert result.executable is False


def test_alias_body_part_overlap_conflict():
    first = fixture_curve(body_part="head")
    second = fixture_curve(body_part="cranium", channel="gaze", unit="degree")
    request, response = _two_curves(first, second)
    result = pc.validate_response(response, request, capabilities=fixture_capabilities(), executed_tick_ranges=[])
    assert codes(result) == ["control_conflict"]
    assert "cranium" in result.errors[0]["message"] or "head" in result.errors[0]["message"]


def test_different_body_parts_same_interval_ok():
    caps = fixture_capabilities()
    caps["aliases"]["hand"] = ["hand"]
    caps["controllers"]["fixture:ctl/hand/raise"] = {
        "channel": "gesture",
        "body_part": "hand",
        "unit": "normalized",
        "dim": 1,
        "value_range": [0, 1],
        "executable": True,
    }
    first = fixture_curve()
    second = fixture_curve(
        channel="gesture",
        body_part="hand",
        unit="normalized",
        controller_ref="fixture:ctl/hand/raise",
        keyframes=[{"tick": 0, "value": 0}, {"tick": 600, "value": 0.5}],
    )
    request, response = _two_curves(first, second)
    result = pc.validate_response(response, request, capabilities=caps, executed_tick_ranges=[])
    assert result.ok, result.errors
    assert result.executable is True


def test_non_overlapping_same_part_ok():
    caps = fixture_capabilities()
    first = fixture_curve()
    second = fixture_curve(
        phases={
            "start_tick": 600,
            "anticipation_end_tick": 660,
            "arrival_end_tick": 720,
            "hold_end_tick": 900,
            "end_tick": 960,
        },
        keyframes=[{"tick": 600, "value": 0}, {"tick": 660, "value": 10}, {"tick": 960, "value": 0}],
    )
    request = fixture_request(duration_ticks=960)
    response = fixture_response(request, [first, second])
    result = pc.validate_response(response, request, capabilities=caps, executed_tick_ranges=[])
    assert result.ok, result.errors
    assert result.executable_curves == 2


def test_blend_without_registered_rule_conflict():
    first = fixture_curve()
    second = fixture_curve(
        owner={"kind": "blend", "id": "fixture-blend", "authorization_ref": "fixture-ref"},
        keyframes=[{"tick": 0, "value": 0}, {"tick": 600, "value": 5}],
    )
    request, response = _two_curves(first, second)
    result = pc.validate_response(response, request, capabilities=fixture_capabilities(), executed_tick_ranges=[])
    assert codes(result) == ["control_conflict"]


def test_blend_with_registered_rule_allowed():
    caps = fixture_capabilities(blend_rules={"fixture-blend": {"inputs": ["fixture:ctl/head/turn"], "rule": "weighted_sum"}})
    first = fixture_curve()
    second = fixture_curve(
        owner={"kind": "blend", "id": "fixture-blend", "authorization_ref": "fixture-ref"},
        keyframes=[{"tick": 0, "value": 0}, {"tick": 600, "value": 5}],
    )
    request, response = _two_curves(first, second)
    result = pc.validate_response(response, request, capabilities=caps, executed_tick_ranges=[])
    assert result.ok, result.errors
    assert any("blend" in note for note in result.notes)


# --------------------------------------------------------------------------------------
# 锁定项
# --------------------------------------------------------------------------------------


def test_lock_conflict_direct():
    request = fixture_request(locks=[{"path": "/world/actor/head", "by": "fixture-user", "reason": "user-lock"}])
    result = pc.validate_response(
        fixture_response(request, [fixture_curve()]), request, capabilities=fixture_capabilities()
    )
    assert codes(result) == ["lock_conflict"]


def test_lock_conflict_survives_alias_rename():
    """反例：换个部位名字想绕开锁定，别名展开后仍命中。"""
    request = fixture_request(locks=[{"path": "/world/actor/head", "by": "fixture-user", "reason": "user-lock"}])
    renamed = fixture_curve(body_part="cranium")
    result = pc.validate_response(
        fixture_response(request, [renamed]), request, capabilities=fixture_capabilities()
    )
    assert codes(result) == ["lock_conflict"]


def test_lock_holder_user_may_write_its_own_lock():
    """锁持有者（用户手调）本人可以写锁定部位；这就是「用户手调最高约束」。"""
    request = fixture_request(locks=[{"path": "/world/actor/head", "by": "fixture-user", "reason": "user-lock"}])
    user_curve = fixture_curve(owner={"kind": "user", "id": "fixture-user", "authorization_ref": "fixture-user-edit"})
    result = pc.validate_response(
        fixture_response(request, [user_curve]),
        request,
        capabilities=fixture_capabilities(),
        executed_tick_ranges=[],
    )
    assert result.ok, result.errors
    assert result.executable is True


def test_director_authorization_cannot_bypass_user_lock():
    request = fixture_request(locks=[{"path": "/world/actor/head", "by": "fixture-user", "reason": "user-lock"}])
    result = pc.validate_response(
        fixture_response(request, [fixture_curve()]), request, capabilities=fixture_capabilities()
    )
    assert codes(result) == ["lock_conflict"]


def test_identity_lock_blocks_every_writer():
    request = fixture_request(locks=[{"path": "/character/identity", "by": "fixture-user", "reason": "identity"}])
    result = pc.validate_response(
        fixture_response(request, [fixture_curve()]), request, capabilities=fixture_capabilities()
    )
    assert codes(result) == ["lock_conflict"]


def test_position_lock_does_not_block_face_pose():
    request = example_request("suspense")
    result = pc.validate_response(example_response("suspense"), request, executed_tick_ranges=[])
    assert result.ok, result.errors


@pytest.mark.parametrize("bad_pointer", ["world/actor", "/bad~2escape", "/bad~", "world", 5])
def test_invalid_lock_pointer_rejected(bad_pointer):
    request = fixture_request(locks=[{"path": bad_pointer, "by": "fixture-user", "reason": "user-lock"}])
    result = pc.validate_request(request)
    assert "lock_conflict" in codes(result)


def test_duplicate_lock_path_rejected():
    lock = {"path": "/world/actor/head", "by": "fixture-user", "reason": "user-lock"}
    result = pc.validate_request(fixture_request(locks=[lock, dict(lock)]))
    assert "lock_conflict" in codes(result)


# --------------------------------------------------------------------------------------
# 旧版本 / 绑定一致性 / 时钟偷换
# --------------------------------------------------------------------------------------


def test_stale_plan_revision_rejected():
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    response["binding"]["plan_revision"] = 0
    request["binding"]["plan_revision"] = 3
    result = pc.validate_response(response, request, capabilities=fixture_capabilities())
    assert codes(result) == ["stale_revision"]
    assert result.errors[0]["path"] == "/binding/plan_revision"


def test_world_version_mismatch_rejected():
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    response["binding"]["world_version"] = 1
    request["binding"]["world_version"] = 2
    result = pc.validate_response(response, request, capabilities=fixture_capabilities())
    assert codes(result) == ["stale_revision"]


def test_actor_mismatch_unknown_actor():
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    response["binding"]["actor_id"] = "fixture-other"
    result = pc.validate_response(response, request, capabilities=fixture_capabilities())
    assert codes(result) == ["unknown_actor"]


def test_character_not_in_capability_table_unknown_actor():
    request = fixture_request()
    request["binding"]["character_ref"] = "fixture:char/unknown"
    result = pc.validate_request(request, capabilities=fixture_capabilities())
    assert codes(result) == ["unknown_actor"]


def test_take_id_mismatch_stale_revision():
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    response["binding"]["take_id"] = "fixture-other-take"
    result = pc.validate_response(response, request, capabilities=fixture_capabilities())
    assert codes(result) == ["stale_revision"]


@pytest.mark.parametrize("fps", [120, 30, 25])
def test_render_fps_mismatch_is_time_curve_error(fps):
    """反例：24fps 请求被 120fps（或其它帧率）响应冒充。"""
    request = fixture_request()
    request["binding"]["render_fps"] = 24
    response = fixture_response(request, [fixture_curve()])
    response["binding"]["render_fps"] = fps
    result = pc.validate_response(response, request, capabilities=fixture_capabilities())
    assert "invalid_time_curve" in codes(result)


def test_response_sim_hz_must_be_120():
    """24Hz 冒充 120Hz：既违反 sim_hz 常量，也与请求时钟不一致，两处都必须报。"""
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    response["binding"]["sim_hz"] = 24
    result = pc.validate_response(response, request, capabilities=fixture_capabilities())
    assert set(codes(result)) == {"invalid_time_curve"}
    assert set(paths_with_code(result, "invalid_time_curve")) == {"/binding/sim_hz"}
    assert any("必须是 120" in item["message"] for item in result.errors)
    assert any("不一致" in item["message"] for item in result.errors)


def test_request_sim_hz_must_be_120():
    request = fixture_request()
    request["binding"]["sim_hz"] = 24
    result = pc.validate_request(request)
    assert codes(result) == ["invalid_time_curve"]


def test_response_request_id_mismatch():
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()], request_id="fixture-request-other")
    result = pc.validate_response(response, request, capabilities=fixture_capabilities())
    assert codes(result) == ["stale_revision"]


# --------------------------------------------------------------------------------------
# error 记录
# --------------------------------------------------------------------------------------


def test_error_record_accepts_all_ten_codes():
    record = {
        "protocol": pc.PROTOCOL,
        "record_kind": "error",
        "request_id": "fixture-request-d2",
        "errors": [pc.err(code, "/curves/0", f"fixture {code}") for code in pc.ERROR_CODES],
    }
    assert pc.validate_error_record(record).ok is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rec: rec.update({"errors": []}),
        lambda rec: rec["errors"][0].update({"code": "made_up_code"}),
        lambda rec: rec["errors"][0].pop("message"),
        lambda rec: rec["errors"][0].update({"path": "/bad~2escape"}),
        lambda rec: rec.update({"curves": []}),
        lambda rec: rec.pop("request_id"),
    ],
)
def test_error_record_shape_rejections(mutate):
    record = {
        "protocol": pc.PROTOCOL,
        "record_kind": "error",
        "request_id": "fixture-request-d2",
        "errors": [pc.err("missing_audio_alignment", "/audio_ref/alignment", "fixture")],
    }
    mutate(record)
    result = pc.validate_error_record(record)
    assert result.ok is False


def test_error_result_serializes_to_d1_shape():
    curve = fixture_curve(controller_ref="fixture:ctl/unknown")
    result = pc.validate_response(fixture_response(fixture_request(), [curve]), fixture_request())
    record = result.as_error_record("fixture-request-d2")
    assert record["record_kind"] == "error"
    assert record["protocol"] == pc.PROTOCOL
    assert pc.validate_error_record(record, fixture_request()).ok is True


# --------------------------------------------------------------------------------------
# changed_past / 已执行区间
# --------------------------------------------------------------------------------------


def test_changed_past_overlap_rejected():
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    result = pc.validate_response(
        response, request, capabilities=fixture_capabilities(), executed_tick_ranges=[(300, 700)]
    )
    assert codes(result) == ["changed_past"]
    assert result.executable is False


def test_disjoint_executed_ranges_ok():
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    result = pc.validate_response(
        response, request, capabilities=fixture_capabilities(), executed_tick_ranges=[(600, 700)]
    )
    assert result.ok, result.errors


# --------------------------------------------------------------------------------------
# 纯函数 / 无 IO / 确定性
# --------------------------------------------------------------------------------------


def test_module_has_no_io_or_model_imports():
    source = inspect.getsource(pc)
    forbidden = (
        "import mlx",
        "import onnxruntime",
        "import torch",
        "import sqlalchemy",
        "import requests",
        "import urllib",
        "import subprocess",
        "import socket",
        "open(",
        "os.environ",
        "Path(",
        "run_store",
        "RunStore",
    )
    for token in forbidden:
        assert token not in source, f"performance_contract.py 不得出现 {token!r}"


def test_validators_do_not_mutate_inputs():
    request = example_request("comedy")
    response = example_response("comedy")
    request_before = copy.deepcopy(request)
    response_before = copy.deepcopy(response)
    pc.validate_exchange(request, response, capabilities=fixture_capabilities(), executed_tick_ranges=[])
    assert request == request_before
    assert response == response_before


def test_validators_write_no_files_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pc.validate_exchange(
        example_request("dry"), example_response("dry"), capabilities=fixture_capabilities(), executed_tick_ranges=[]
    )
    assert list(tmp_path.iterdir()) == []


def test_results_are_deterministic():
    request = example_request("suspense")
    response = example_response("suspense")
    first = pc.validate_response(response, request, executed_tick_ranges=[]).to_dict()
    second = pc.validate_response(response, request, executed_tick_ranges=[]).to_dict()
    assert first == second


def test_unknown_record_kind_fails_closed():
    result = pc.validate_record({"record_kind": "curve"})
    assert result.ok is False
    assert result.error_codes() == ["unsupported_action"]


def test_structural_defects_map_to_d1_codes():
    request = fixture_request()
    request["binding"]["plan_revision"] = -1
    assert "stale_revision" in codes(pc.validate_request(request))
    request = fixture_request()
    request["locks"] = [{"path": "/x", "by": "u"}]
    assert "lock_conflict" in codes(pc.validate_request(request))
    request = fixture_request()
    request["audio_ref"] = {"asset_ref": "x", "sha256": "zz", "sample_rate": 48000, "anchor_tick": 0, "offset_samples": 0}
    assert "missing_audio_alignment" in codes(pc.validate_request(request))
    request = fixture_request()
    request["intensity"] = 2
    assert "out_of_range" in codes(pc.validate_request(request))


def test_pointer_helpers_follow_r3_grammar():
    assert pc.pointer_tokens("") == []
    assert pc.pointer_tokens("/a/b") == ["a", "b"]
    assert pc.pointer_tokens("/a~1b/c~0d") == ["a/b", "c~d"]
    assert pc.pointer_tokens("/bad~2escape") is None
    assert pc.pointer_tokens("/bad~") is None
    assert pc.pointer_tokens("nope") is None
    assert pc.pointer_tokens("/~01") == ["~1"]
    assert pc.pointer_join("a/b", "c~d") == "/a~1b/c~0d"
    assert pc.escape_pointer_token("~") == "~0"


def test_execution_requires_positive_evidence_not_structure_alone():
    """结构通过 ≠ 可执行：能力表、别名、绑定、已执行区间缺一即不放行。"""
    request = fixture_request()
    response = fixture_response(request, [fixture_curve()])
    no_alias = fixture_capabilities(aliases={})
    no_binding = pc.validate_response(response, None, capabilities=fixture_capabilities(), executed_tick_ranges=[])
    no_ranges = pc.validate_response(response, request, capabilities=fixture_capabilities(), executed_tick_ranges=None)
    no_alias_result = pc.validate_response(response, request, capabilities=no_alias, executed_tick_ranges=[])
    assert all(item.ok for item in (no_binding, no_ranges, no_alias_result))
    assert not any(item.executable for item in (no_binding, no_ranges, no_alias_result))
    assert pc.validate_response(
        response, request, capabilities=fixture_capabilities(), executed_tick_ranges=[]
    ).executable is True
