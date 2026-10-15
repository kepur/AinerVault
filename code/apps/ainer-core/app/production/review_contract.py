"""审片问题记录 v0 纯函数合同（hub.P1.C2）。

依据 ``docs/v2/production_brain/review_standard_v0.md``（hub.P1.C1）。
只做纯 CPU 结构 + 语义校验，不接旧 Critic，不改 API/UI/DB。

边界（fail-closed）：
- 不导入 MLX/ORT/模型，不渲染，不读文件/媒体/数据库。外部记录只能通过
  ``fixtures`` 参数显式映射提供，缺映射即 ``unmapped_ref``。
- 结构由本模块 pydantic 模型与
  ``docs/v2/production_brain/review_record_v0.schema.json`` 共同约束；
  语义由 ``validate_*`` 纯函数执行，返回错误列表（空列表表示通过）。
- 必要证据缺失不得判通过；任一硬约束 ``fail`` 则总体必须 ``fail``，
  不得被主观意见/维度多数抵消；不计算任何分数，不自动晋升。
- 时间区间必须显式时钟单位（``sim_tick``/``video_frame``/``audio_sample``），
  左闭右开；跨时钟字段混用即 ``timeline_confusion``。
- 作者自评只能用于有界记录；``supports_promotion`` 为真时评审者必须非作者，
  且成对比较必须全盲 + 先查硬约束。

错误项形状：``{"code": str, "path": str, "message": str}``，
``path`` 为 JSON Pointer 风格（``""`` 表示根）。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROTOCOL = "hub.review/v0"
STANDARD_VERSION = "v0"
SIM_HZ = 120

DIMENSIONS = (
    "intent_genre",
    "era_world",
    "story_character",
    "cinema_edit",
    "art_identity",
    "sound_performance",
    "execution_experience",
)

HARD_CONSTRAINTS = (
    "execution_success",
    "identity",
    "locked_fields",
    "registered_gates",
    "license",
    "world_fact_separation",
)

SEVERITIES = ("blocker", "major", "minor", "note")
PREFERENCES = ("prefer_a", "prefer_b", "tie", "undecidable")
SCOPES = ("world", "performance", "presentation", "style")
CLOCKS = ("sim_tick", "video_frame", "audio_sample")
STATES = ("pass", "fail", "unverified")

# 顶层 forbiden：任何记录里出现这些键即视为捏造分数。
FORBIDDEN_SCORE_KEYS = {"score", "rating", "grade", "total_score"}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Binding(Contract):
    plan_id: str = Field(min_length=1)
    plan_revision: int = Field(ge=0)
    world_id: str = Field(min_length=1)
    world_version: int = Field(ge=1)
    scene_id: str = Field(min_length=1)
    scene_revision: int = Field(ge=0)
    take_id: str = Field(min_length=1)
    shot_id: str | None = Field(default=None, min_length=1)


class ClockInterval(Contract):
    clock: Literal["sim_tick", "video_frame", "audio_sample"]
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    sim_hz: Literal[120] | None = None
    fps: int | None = Field(default=None, ge=1, le=120)
    origin_tick: int | None = Field(default=None, ge=0)
    sample_rate: int | None = Field(default=None, ge=1)
    anchor_tick: int | None = Field(default=None, ge=0)


class EvidenceRef(Contract):
    ref: str = Field(min_length=1)
    digest: str | None = Field(default=None, min_length=1)
    locator: str | None = Field(default=None, min_length=1)
    summary: str = Field(min_length=1)


class Reviewer(Contract):
    kind: Literal["human", "model", "user"]
    id: str = Field(min_length=1)
    model_version: str | None = Field(default=None, min_length=1)
    is_author: bool
    evaluated_at: str | None = Field(default=None, min_length=1)


class InputIdentity(Contract):
    asset_ref: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class FixProposal(Contract):
    scope: Literal["world", "performance", "presentation", "style"]
    path: str = Field(min_length=1)
    minimal_range: str = Field(min_length=1)
    world_new_version_required: bool | None = None


class LockImpact(Contract):
    touches_lock: bool
    lock_paths: list[str] = Field(default_factory=list)


class Subject(Contract):
    kind: Literal["role", "entity", "shot", "take", "audio", "other"]
    id: str = Field(min_length=1)


class Issue(Contract):
    protocol: Literal["hub.review/v0"] = PROTOCOL
    record_kind: Literal["issue"] = "issue"
    issue_id: str = Field(min_length=1)
    standard_version: Literal["v0"] = STANDARD_VERSION
    binding: Binding
    subject: Subject
    clock: ClockInterval
    dimension: Literal["intent_genre", "era_world", "story_character", "cinema_edit",
                       "art_identity", "sound_performance", "execution_experience"]
    issue_type: str | None = Field(default=None, min_length=1)
    severity: Literal["blocker", "major", "minor", "note"]
    verdict: Literal["fail", "unverified"]
    hard_constraint: Literal["execution_success", "identity", "locked_fields",
                             "registered_gates", "license",
                             "world_fact_separation", "none"] = "none"
    evidence: list[EvidenceRef] = Field(default_factory=list)
    observed: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    fix: FixProposal
    lock_impact: LockImpact
    dependencies: list[str] = Field(default_factory=list)
    unverified_items: list[str] = Field(default_factory=list)
    reviewer: Reviewer
    inputs: list[InputIdentity] = Field(min_length=1)
    tech_refs: list[str] = Field(default_factory=list)
    followup_refs: list[str] = Field(default_factory=list)


class HardConstraintResult(Contract):
    name: Literal["execution_success", "identity", "locked_fields",
                  "registered_gates", "license", "world_fact_separation"]
    state: Literal["pass", "fail", "unverified"]
    note: str | None = Field(default=None, min_length=1)


class DimensionResult(Contract):
    dimension: Literal["intent_genre", "era_world", "story_character", "cinema_edit",
                       "art_identity", "sound_performance", "execution_experience"]
    status: Literal["pass", "fail", "unverified"]
    evidence_present: bool
    note: str | None = Field(default=None, min_length=1)


class Verdict(Contract):
    protocol: Literal["hub.review/v0"] = PROTOCOL
    record_kind: Literal["verdict"] = "verdict"
    verdict_id: str = Field(min_length=1)
    standard_version: Literal["v0"] = STANDARD_VERSION
    binding: Binding
    hard_constraints: list[HardConstraintResult] = Field(min_length=6, max_length=6)
    dimensions: list[DimensionResult] = Field(min_length=7, max_length=7)
    overall: Literal["pass", "fail", "unverified"]
    supports_promotion: bool = False
    reviewer: Reviewer
    inputs: list[InputIdentity] = Field(min_length=1)
    evaluated_at: str = Field(min_length=1)


class CandidateRef(Contract):
    take_id: str = Field(min_length=1)
    shot_id: str | None = Field(default=None, min_length=1)
    asset_ref: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class BlindSetup(Contract):
    author_hidden: bool
    technique_hidden: bool
    model_hidden: bool
    self_score_hidden: bool
    randomized_order: bool


class Baseline(Contract):
    event_id: str = Field(min_length=1)
    world_id: str = Field(min_length=1)
    world_version: int = Field(ge=1)
    role_ids: list[str] | None = Field(default=None, min_length=1)


class Comparison(Contract):
    protocol: Literal["hub.review/v0"] = PROTOCOL
    record_kind: Literal["comparison"] = "comparison"
    comparison_id: str = Field(min_length=1)
    standard_version: Literal["v0"] = STANDARD_VERSION
    baseline: Baseline
    candidate_a: CandidateRef
    candidate_b: CandidateRef
    preference: Literal["prefer_a", "prefer_b", "tie", "undecidable"]
    reason: str = Field(min_length=1)
    genre_target: str | None = Field(default=None, min_length=1)
    dimension: Any | None = None
    hard_constraints_checked: bool
    blind: BlindSetup
    supports_promotion: bool = False
    reviewer: Reviewer
    evaluated_at: str = Field(min_length=1)


class ChoiceCandidate(Contract):
    take_id: str = Field(min_length=1)
    asset_ref: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    diff: str | None = Field(default=None, min_length=1)


class Choice(Contract):
    protocol: Literal["hub.review/v0"] = PROTOCOL
    record_kind: Literal["choice"] = "choice"
    choice_id: str = Field(min_length=1)
    standard_version: Literal["v0"] = STANDARD_VERSION
    requirement_ref: str = Field(min_length=1)
    candidates: list[ChoiceCandidate] = Field(min_length=2)
    selected_take_id: str = Field(min_length=1)
    user_verbatim: str = Field(min_length=1)
    shown_order: list[str] = Field(min_length=2)
    cost: str | None = Field(default=None, min_length=1)
    chosen_at: str = Field(min_length=1)
    hard_constraints_preserved: Literal[True] = True
    grants_license_or_budget: Literal[False] = False
    reviewer: Reviewer


# Comparison.dimension 在 schema 里是七维枚举的可选项；pydantic 侧用 model_validator
# 太重，这里用 __init__ 之后由 validate_comparison 做枚举检查，保持纯函数可测。
_COMPARISON_DIMENSIONS = set(DIMENSIONS)


def err(code: str, path: str, message: str) -> dict:
    return {"code": code, "path": path, "message": message}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _structural_errors(model: type[Contract], data: Any, prefix: str = "") -> list[dict]:
    try:
        model.model_validate(data)
        return []
    except ValidationError as exc:
        out: list[dict] = []
        for e in exc.errors():
            loc = "/".join(str(p) for p in e.get("loc", ()))
            path = f"{prefix}/{loc}" if loc else (prefix or "")
            out.append(err("schema_violation", path, f"{e.get('msg', 'invalid')}: {e.get('type', '')}"))
        return out


def _forbidden_score_errors(data: Any, path: str) -> list[dict]:
    out: list[dict] = []
    if isinstance(data, dict):
        for key in data:
            if key in FORBIDDEN_SCORE_KEYS:
                out.append(err("fabricated_score", f"{path}/{key}",
                               f"禁止捏造分数 resident key '{key}'；v0 不设分数尺度"))
        for key, value in data.items():
            out.extend(_forbidden_score_errors(value, f"{path}/{key}"))
    elif isinstance(data, list):
        for i, value in enumerate(data):
            out.extend(_forbidden_score_errors(value, f"{path}/{i}"))
    return out


def validate_clock(clock: Any, path: str = "/clock") -> list[dict]:
    """校验时钟单位声明 + 半开区间。跨时钟字段混用即 timeline_confusion。"""
    errors = _structural_errors(ClockInterval, clock, path)
    if not isinstance(clock, dict):
        return errors or [err("invalid_interval", path, "clock 必须是对象")]
    unit = clock.get("clock")
    if unit not in CLOCKS:
        errors.append(err("invalid_interval", f"{path}/clock", f"clock 必须是 {CLOCKS} 之一"))
        return errors
    start, end = clock.get("start"), clock.get("end")
    if not (_is_int(start) and _is_int(end)) or not (isinstance(start, int) and start >= 0 and end > start):
        errors.append(err("invalid_interval", path, "区间必须左闭右开且满足 0<=start<end（整数 tick/frame/sample）"))
    if unit == "sim_tick":
        if clock.get("sim_hz") != SIM_HZ:
            errors.append(err("invalid_interval", f"{path}/sim_hz", "sim_tick 必须声明 sim_hz=120"))
        for foreign in ("fps", "origin_tick", "sample_rate", "anchor_tick"):
            if clock.get(foreign) is not None:
                errors.append(err("timeline_confusion", f"{path}/{foreign}",
                                   f"sim_tick 区间不得携带 {foreign}；疑似把视频帧/音频采样数混写成 tick"))
    elif unit == "video_frame":
        if not _is_int(clock.get("fps")) or not (1 <= clock["fps"] <= 120):
            errors.append(err("invalid_interval", f"{path}/fps", "video_frame 必须声明 fps（1..120）"))
        if not _is_int(clock.get("origin_tick")) or clock["origin_tick"] < 0:
            errors.append(err("invalid_interval", f"{path}/origin_tick", "video_frame 必须声明 origin_tick（frame 0 对应的 tick）"))
        for foreign in ("sim_hz", "sample_rate", "anchor_tick"):
            if clock.get(foreign) is not None:
                errors.append(err("timeline_confusion", f"{path}/{foreign}",
                                   f"video_frame 区间不得携带 {foreign}"))
    else:  # audio_sample
        if not _is_int(clock.get("sample_rate")) or clock["sample_rate"] < 1:
            errors.append(err("invalid_interval", f"{path}/sample_rate", "audio_sample 必须声明 sample_rate"))
        if not _is_int(clock.get("anchor_tick")) or clock["anchor_tick"] < 0:
            errors.append(err("invalid_interval", f"{path}/anchor_tick", "audio_sample 必须声明 anchor_tick"))
        for foreign in ("sim_hz", "fps", "origin_tick"):
            if clock.get(foreign) is not None:
                errors.append(err("timeline_confusion", f"{path}/{foreign}",
                                   f"audio_sample 区间不得携带 {foreign}"))
    return errors


def _fixture_entry(fixtures: Any, asset_ref: str) -> Any:
    if isinstance(fixtures, dict):
        return fixtures.get(asset_ref)
    return None


def validate_input_identity(inp: Any, fixtures: Any, path: str) -> list[dict]:
    """单个输入身份：必须经 fixtures 显式映射；版本不一致即 stale_media。"""
    errors = _structural_errors(InputIdentity, inp, path)
    if not isinstance(inp, dict):
        return errors
    ref = inp.get("asset_ref")
    entry = _fixture_entry(fixtures, ref) if isinstance(ref, str) else None
    if not isinstance(ref, str) or not ref:
        return errors
    if entry is None:
        errors.append(err("unmapped_ref", f"{path}/asset_ref",
                           f"外部记录 '{ref}' 没有显式 fixture 映射；不得读媒体/数据库"))
        return errors
    if not isinstance(entry, dict):
        errors.append(err("unmapped_ref", f"{path}/asset_ref", f"fixture 映射 '{ref}' 形状非法"))
        return errors
    current = entry.get("current_revision")
    if isinstance(current, str) and inp.get("revision") != current:
        errors.append(err("stale_media", f"{path}/revision",
                           f"输入版本 '{inp.get('revision')}' 不是当前版本 '{current}'；不得拿旧媒体当新结论"))
    want_sha = entry.get("sha256")
    got_sha = inp.get("sha256")
    if isinstance(want_sha, str) and isinstance(got_sha, str) and want_sha != got_sha:
        errors.append(err("stale_media", f"{path}/sha256", "输入字节身份与 fixture 登记不一致"))
    return errors


def validate_evidence_list(evidence: Any, fixtures: Any, path: str = "/evidence",
                           require_locator: bool = False) -> list[dict]:
    errors: list[dict] = []
    errors.extend(_forbidden_score_errors(evidence, path))
    if not isinstance(evidence, list):
        return errors + [err("missing_evidence", path, "evidence 必须是数组")]
    for i, item in enumerate(evidence):
        ipath = f"{path}/{i}"
        errors.extend(_structural_errors(EvidenceRef, item, ipath))
        if not isinstance(item, dict):
            continue
        ref, summary = item.get("ref"), item.get("summary")
        if not isinstance(ref, str) or not ref:
            errors.append(err("missing_evidence", f"{ipath}/ref", "证据必须给出 ref（路径/资产 ID）"))
        elif _fixture_entry(fixtures, ref) is None:
            errors.append(err("unmapped_ref", f"{ipath}/ref",
                               f"证据 '{ref}' 没有显式 fixture 映射；不得引用映射外记录"))
        if not isinstance(summary, str) or not summary.strip():
            errors.append(err("missing_evidence", f"{ipath}/summary", "证据必须给出摘要（实际观察定位），不附无来源总分"))
    if require_locator and evidence:
        if not any(isinstance(e, dict) and isinstance(e.get("locator"), str) and e["locator"].strip()
                   for e in evidence):
            errors.append(err("missing_evidence", path, "时间定位问题至少一条证据须带 locator（帧/时间定位）"))
    return errors


def _check_lock(fix: Any, lock: Any, path_fix: str = "/fix", path_lock: str = "/lock_impact") -> list[dict]:
    errors: list[dict] = []
    if not isinstance(lock, dict):
        return errors
    touches = lock.get("touches_lock")
    paths = lock.get("lock_paths")
    if touches is True:
        if not isinstance(paths, list) or not paths:
            errors.append(err("lock_violation", f"{path_lock}/lock_paths", "声明触碰锁定项必须列出 lock_paths"))
    elif touches is False:
        if isinstance(paths, list) and len(paths) > 0:
            errors.append(err("lock_violation", path_lock, "touches_lock=false 却列出 lock_paths，前后矛盾"))
        if isinstance(fix, dict) and isinstance(paths, list):
            pass  # paths 为空，无需前缀检查
        if isinstance(fix, dict):
            fix_path = fix.get("path")
            # 调用方传入已知锁定集合时做前缀检查；此处只做自洽（见 validate_issue 的 known_locks 参数）。
    else:
        errors.append(err("lock_violation", f"{path_lock}/touches_lock", "touches_lock 必须是布尔"))
    if isinstance(paths, list):
        for i, p in enumerate(paths):
            if not isinstance(p, str) or not p.startswith("/"):
                errors.append(err("lock_violation", f"{path_lock}/lock_paths/{i}", "lock path 必须以 / 开头"))
    return errors


def validate_issue(data: Any, fixtures: Any, known_locks: list[str] | None = None) -> list[dict]:
    """校验单条局部问题记录。known_locks 为当时用户锁定路径集合（可选）。"""
    errors: list[dict] = []
    errors.extend(_forbidden_score_errors(data, ""))
    errors.extend(_structural_errors(Issue, data, ""))
    if not isinstance(data, dict):
        return errors
    errors.extend(validate_clock(data.get("clock"), "/clock"))
    errors.extend(validate_evidence_list(data.get("evidence"), fixtures, "/evidence", require_locator=True))
    if isinstance(data.get("evidence"), list) and len(data["evidence"]) == 0:
        errors.append(err("missing_evidence", "/evidence", "问题记录 evidence 为空：缺证据不得判，只能记 unverified 且补证据"))
    inputs = data.get("inputs")
    if isinstance(inputs, list):
        for i, inp in enumerate(inputs):
            errors.extend(validate_input_identity(inp, fixtures, f"/inputs/{i}"))
    severity, verdict = data.get("severity"), data.get("verdict")
    hard = data.get("hard_constraint", "none")
    if severity == "blocker" and hard in (None, "none"):
        errors.append(err("blocker_without_constraint", "/hard_constraint",
                           "severity=blocker 必须指明哪条硬约束失败，不得只写严重不写约束"))
    fix = data.get("fix")
    if isinstance(fix, dict):
        if fix.get("scope") not in SCOPES:
            errors.append(err("invalid_scope", "/fix/scope", f"修改范围只能是 {SCOPES} 之一，并给最小范围"))
        if fix.get("scope") == "world" and fix.get("world_new_version_required") is not True:
            errors.append(err("invalid_scope", "/fix/world_new_version_required",
                               "改世界必须走统一信封与新版本（world_new_version_required=true），不直接修图伪造"))
        if not isinstance(fix.get("path"), str) or not fix["path"]:
            errors.append(err("invalid_scope", "/fix/path", "修改必须给出最小范围路径"))
    errors.extend(_check_lock(fix, data.get("lock_impact")))
    if isinstance(known_locks, list) and isinstance(fix, dict):
        fix_path = fix.get("path") if isinstance(fix.get("path"), str) else ""
        lock = data.get("lock_impact")
        touches = lock.get("touches_lock") if isinstance(lock, dict) else None
        for locked in known_locks:
            if fix_path == locked or fix_path.startswith(locked.rstrip("/") + "/"):
                if touches is not True:
                    errors.append(err("lock_violation", "/fix/path",
                                       f"修改路径 '{fix_path}' 命中用户锁定 '{locked}'，必须声明 touches_lock=true 并列出影响"))
    return errors


def validate_verdict(data: Any, fixtures: Any) -> list[dict]:
    """校验单候选评审结论。fail-closed：硬失败必总体 fail；缺证据必不能 pass。"""
    errors: list[dict] = []
    errors.extend(_forbidden_score_errors(data, ""))
    errors.extend(_structural_errors(Verdict, data, ""))
    if not isinstance(data, dict):
        return errors
    hard = data.get("hard_constraints")
    dims = data.get("dimensions")
    if isinstance(hard, list):
        names = [h.get("name") for h in hard if isinstance(h, dict)]
        if sorted(names) != sorted(HARD_CONSTRAINTS):
            errors.append(err("incomplete_assessment", "/hard_constraints",
                               f"六条硬约束必须恰好各出现一次：{HARD_CONSTRAINTS}"))
        states = {h.get("name"): h.get("state") for h in hard if isinstance(h, dict)}
    else:
        states = {}
    if isinstance(dims, list):
        dnames = [d.get("dimension") for d in dims if isinstance(d, dict)]
        if sorted(dnames) != sorted(DIMENSIONS):
            errors.append(err("incomplete_assessment", "/dimensions", f"七维必须恰好各出现一次：{DIMENSIONS}"))
        dimap = {d.get("dimension"): d for d in dims if isinstance(d, dict)}
    else:
        dimap = {}
    inputs = data.get("inputs")
    if isinstance(inputs, list):
        for i, inp in enumerate(inputs):
            errors.extend(validate_input_identity(inp, fixtures, f"/inputs/{i}"))
    # 缺证据即不能 pass：维度层
    for name, d in dimap.items():
        if isinstance(d, dict) and d.get("evidence_present") is False and d.get("status") == "pass":
            errors.append(err("missing_evidence", f"/dimensions/{name}",
                               f"维度 {name} 无证据却记 pass：静音/单帧/缺片段不得给通过"))
    overall = data.get("overall")
    any_fail = any(v == "fail" for v in states.values()) if isinstance(states, dict) else False
    any_unverified = any(v == "unverified" for v in states.values()) if isinstance(states, dict) else False
    if any_fail and overall != "fail":
        errors.append(err("blocker_overridden", "/overall",
                           "任一硬约束 fail 则总体必须 fail；不得被主观分数或维度多数抵消"))
    if not any_fail and any_unverified and overall == "pass":
        errors.append(err("missing_evidence", "/overall", "硬约束有 unverified 时总体不能 pass"))
    if overall == "pass" and isinstance(dimap, dict) and dimap:
        for name, d in dimap.items():
            if isinstance(d, dict) and (d.get("status") != "pass" or d.get("evidence_present") is not True):
                errors.append(err("missing_evidence", "/overall",
                                   f"总体 pass 要求七维全部 pass 且有证据；{name} 不满足，不得平均分抵消"))
                break
    reviewer = data.get("reviewer")
    if data.get("supports_promotion") is True:
        if not (isinstance(reviewer, dict) and reviewer.get("is_author") is False):
            errors.append(err("self_promotion", "/reviewer/is_author", "作者自评只用于有界搜索；晋升必须非作者评价"))
        if overall != "pass":
            errors.append(err("self_promotion", "/supports_promotion", "总体非 pass 不得声明晋升"))
    return errors


def validate_comparison(data: Any, fixtures: Any) -> list[dict]:
    """校验成对偏好（含平局/无法判断）。"""
    errors: list[dict] = []
    errors.extend(_forbidden_score_errors(data, ""))
    errors.extend(_structural_errors(Comparison, data, ""))
    if not isinstance(data, dict):
        return errors
    dim = data.get("dimension")
    if dim is not None and dim not in _COMPARISON_DIMENSIONS:
        errors.append(err("incomplete_assessment", "/dimension", f"dimension 只能是 {DIMENSIONS} 之一或省略"))
    ca, cb = data.get("candidate_a"), data.get("candidate_b")
    if isinstance(ca, dict) and isinstance(cb, dict):
        if ca.get("take_id") == cb.get("take_id"):
            errors.append(err("same_take", "/candidate_b/take_id", "成对比较必须是两个不同 take，不伪称相同 take"))
        for tag, cand in (("a", ca), ("b", cb)):
            ref = cand.get("asset_ref")
            entry = _fixture_entry(fixtures, ref) if isinstance(ref, str) else None
            if not isinstance(ref, str) or not ref:
                errors.append(err("missing_evidence", f"/candidate_{tag}/asset_ref", "候选必须给出媒体身份"))
            elif entry is None:
                errors.append(err("unmapped_ref", f"/candidate_{tag}/asset_ref",
                                   f"候选 '{ref}' 没有显式 fixture 映射"))
            elif isinstance(entry, dict) and isinstance(entry.get("current_revision"), str):
                if cand.get("revision") != entry["current_revision"]:
                    errors.append(err("stale_media", f"/candidate_{tag}/revision",
                                       f"候选版本 '{cand.get('revision')}' 不是当前版本 '{entry['current_revision']}'"))
    if not isinstance(data.get("reason"), str) or not data["reason"].strip():
        errors.append(err("missing_reason", "/reason", "成对偏好必须给出理由（含平局/无法判断的理由）"))
    if data.get("hard_constraints_checked") is not True:
        errors.append(err("hard_constraints_skipped", "/hard_constraints_checked",
                           "先查硬约束再分题材判断；未查硬约束的比较不得用"))
    blind = data.get("blind")
    if not isinstance(blind, dict):
        errors.append(err("missing_evidence", "/blind", "比较必须声明盲评设置"))
        blind = {}
    reviewer = data.get("reviewer")
    if data.get("supports_promotion") is True:
        if not (isinstance(reviewer, dict) and reviewer.get("is_author") is False):
            errors.append(err("self_promotion", "/reviewer/is_author", "作者自评不得作为晋升依据"))
        for key in ("author_hidden", "technique_hidden", "model_hidden", "self_score_hidden", "randomized_order"):
            if blind.get(key) is not True:
                errors.append(err("self_promotion", f"/blind/{key}", f"作为晋升依据的比较须全盲且随机顺序；{key} 未满足"))
        if data.get("hard_constraints_checked") is not True:
            errors.append(err("hard_constraints_skipped", "/hard_constraints_checked", "晋升比较必须先查硬约束"))
    return errors


def validate_choice(data: Any, fixtures: Any) -> list[dict]:
    """校验用户选择：最高品味依据，但不撤销硬约束、不授予许可/预算。"""
    errors: list[dict] = []
    errors.extend(_forbidden_score_errors(data, ""))
    errors.extend(_structural_errors(Choice, data, ""))
    if not isinstance(data, dict):
        return errors
    reviewer = data.get("reviewer")
    if not (isinstance(reviewer, dict) and reviewer.get("kind") == "user"):
        errors.append(err("wrong_reviewer", "/reviewer/kind", "用户选择必须由 kind=user 记录"))
    cands = data.get("candidates")
    take_ids: list[str] = []
    if isinstance(cands, list):
        for i, cand in enumerate(cands):
            if isinstance(cand, dict):
                if isinstance(cand.get("take_id"), str):
                    take_ids.append(cand["take_id"])
                ref = cand.get("asset_ref")
                entry = _fixture_entry(fixtures, ref) if isinstance(ref, str) else None
                if entry is None:
                    errors.append(err("unmapped_ref", f"/candidates/{i}/asset_ref",
                                       f"候选 '{ref}' 没有显式 fixture 映射"))
                elif isinstance(entry, dict) and isinstance(entry.get("current_revision"), str):
                    if cand.get("revision") != entry["current_revision"]:
                        errors.append(err("stale_media", f"/candidates/{i}/revision", "候选版本不是当前版本"))
    selected = data.get("selected_take_id")
    if isinstance(selected, str) and take_ids and selected not in take_ids:
        errors.append(err("unknown_selection", "/selected_take_id", "所选 take 不在候选名单中"))
    order = data.get("shown_order")
    if isinstance(order, list) and take_ids and sorted(order) != sorted(take_ids):
        errors.append(err("unknown_selection", "/shown_order", "shown_order 必须与候选 take 集合一致（含顺序记录）"))
    if not isinstance(data.get("user_verbatim"), str) or not data["user_verbatim"].strip():
        errors.append(err("missing_reason", "/user_verbatim", "用户选择必须绑定用户原话"))
    if data.get("hard_constraints_preserved") is not True:
        errors.append(err("blocker_overridden", "/hard_constraints_preserved", "用户偏好不会撤销硬约束"))
    if data.get("grants_license_or_budget") is not False:
        errors.append(err("blocker_overridden", "/grants_license_or_budget", "用户偏好不授予许可/训练预算"))
    return errors


def validate_record(data: Any, fixtures: Any, known_locks: list[str] | None = None) -> list[dict]:
    """按 record_kind 分发。kind 缺失/非法即 schema_violation。"""
    if not isinstance(data, dict):
        return [err("schema_violation", "", "记录必须是对象")]
    kind = data.get("record_kind")
    if kind == "issue":
        return validate_issue(data, fixtures, known_locks)
    if kind == "verdict":
        return validate_verdict(data, fixtures)
    if kind == "comparison":
        return validate_comparison(data, fixtures)
    if kind == "choice":
        return validate_choice(data, fixtures)
    return [err("schema_violation", "/record_kind", "record_kind 必须是 issue/verdict/comparison/choice 之一")]


def summarize_verdict(data: dict) -> dict:
    """只给计数，不给分数、不平均、不排名。"""
    hard = data.get("hard_constraints", [])
    dims = data.get("dimensions", [])
    return {
        "overall": data.get("overall"),
        "hard_fail": sum(1 for h in hard if isinstance(h, dict) and h.get("state") == "fail"),
        "hard_unverified": sum(1 for h in hard if isinstance(h, dict) and h.get("state") == "unverified"),
        "dim_fail": sum(1 for d in dims if isinstance(d, dict) and d.get("status") == "fail"),
        "dim_unverified": sum(1 for d in dims if isinstance(d, dict) and d.get("status") == "unverified"),
    }
