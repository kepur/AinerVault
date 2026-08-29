"""音色的维度、术语与规则 —— 让「同一个角色同一个嗓子」可判定。

## 为什么不直接存 TTS 的 voice_id

存了就锁死在一家引擎上。换 TTS（云 API 换成本地 qwen3-tts，或者反过来）
时，voice_id 全部失效，整本书要重新配一遍音 ——
而「重新配一遍」意味着所有角色的嗓子都变了，读者会当成换了一套演员。

所以权威是**声学描述**，voice_id 只是某个引擎上的一次落地。
描述稳定，换引擎时重新落地即可，角色之间的相对关系不变：
沙哑低沉的还是沙哑低沉的，清亮的还是清亮的。

## 不变量与变量 —— 与素材时期同一套办法

    identity   声线本体：声部、音区、音质、共鸣、口音
    epoch      这一时期：年龄感、语速、力度、状态

**拆开是为了让嗓子保持同一个人。** 合起来存的话，少年林凡与中年林凡
各写一遍音色描述，两次描述必然漂移，配出来就是两个演员。
拆开之后 identity 逐字复用，只有 epoch 那几项随时期变 ——
这正是「同一个音色的不同年龄版本」的可执行含义。

变声期是唯一允许 voice_type 变的情形（童声 → 成年），
受伤允许 texture 变沙哑。除此之外 identity 漂移就是配错了人。

## 撞声

模型给五个角色配音，会给出五个「低沉浑厚的男中音」——
每一个单看都合格，放进同一场戏观众分不清谁在说话。
这类错误和翻轴一样，单条看不出来，比对才露馅，
而它同样是**可判定的**：声部、音区、音质都是有限取值，能两两比。

判定范围限定在**同场说过话的角色之间**。全书两两互斥是做不到的 ——
四十个角色不可能有四十种能听辨的嗓子，也没必要：
第三章的店小二和第二十章的船夫永远不会同框，撞了也没人察觉。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# ── 术语表 ────────────────────────────────────────────────────────────────────
# 有序量表用于算「差几档」，无序量表只判相同与否。
# 这份表同时是**生成时给模型的词汇**和**验收时的白名单** —— 一物两用，
# 与工种规格同一套做法：分开写会变成按一套标准生成、按另一套验收。

#: 声部。跨类几乎一定能听辨，是最强的区分维度。
#:
#: **只回答「哪一类嗓子」，不掺别的。** 这里曾经有一项「苍老中性」，
#: 实跑时老周（一个男人）被配成它，落到 TTS 就是 gender=neutral ——
#: 按语音库选声的引擎可能给他一把女声。
#: 苍老该由年龄感（老年）、音质（干涩／沙哑）、共鸣（喉音）表达，
#: 那三项本来就在表里，且不会污染选声。
VOICE_TYPES: tuple[str, ...] = ("童声", "少年音", "女声", "男声")

#: 音区。有序 —— 差一档还可能混，差两档基本不会。
PITCH: tuple[str, ...] = ("低沉", "偏低", "中位", "偏高", "明亮高")

#: 音质。声部之后最主要的身份载体。
TEXTURE: tuple[str, ...] = (
    "清亮", "圆润", "浑厚", "沙哑", "气声", "干涩", "金属感", "绵软", "粗粝",
)

#: 共鸣位置。次要维度，但同声部同音区时靠它拉开。
RESONANCE: tuple[str, ...] = ("胸腔", "口腔", "鼻腔", "头声", "喉音")

#: 年龄感。有序，随时期推进。
AGE_FEEL: tuple[str, ...] = ("童年", "少年", "青年", "壮年", "中年", "老年")

#: 语速基线。有序。
TEMPO: tuple[str, ...] = ("迟缓", "偏慢", "中等", "偏快", "急促")

#: 力度。有序。
ENERGY: tuple[str, ...] = ("虚弱", "收敛", "沉稳", "充沛", "张扬")

#: 状态。无序，多为一时的。
CONDITION: tuple[str, ...] = ("健康", "带伤", "久病", "醉酒", "疲惫", "惊惶")

#: 声线本体 —— 跨时期必须逐字一致
IDENTITY_FIELDS: tuple[str, ...] = (
    "voice_type", "pitch", "texture", "resonance", "accent",
)
#: 这一时期特有 —— 时期之间该变的就是这些
EPOCH_FIELDS: tuple[str, ...] = ("age_feel", "tempo", "energy", "condition")

#: 每个字段的取值表。accent 没有固定表 —— 它由目标圈层决定，
#: 「外省口音」在帝俄晚期和在维多利亚英国不是同一个东西。
VOCAB: dict[str, tuple[str, ...]] = {
    "voice_type": VOICE_TYPES,
    "pitch": PITCH,
    "texture": TEXTURE,
    "resonance": RESONANCE,
    "age_feel": AGE_FEEL,
    "tempo": TEMPO,
    "energy": ENERGY,
    "condition": CONDITION,
}
#: 有序量表 —— 可以算档位差
ORDERED: dict[str, tuple[str, ...]] = {
    "pitch": PITCH, "age_feel": AGE_FEEL, "tempo": TEMPO, "energy": ENERGY,
}

_FIELD_CN = {
    "voice_type": "声部", "pitch": "音区", "texture": "音质",
    "resonance": "共鸣", "accent": "口音", "age_feel": "年龄感",
    "tempo": "语速", "energy": "力度", "condition": "状态",
}


def field_label(name: str) -> str:
    return _FIELD_CN.get(name, name)


@dataclass
class VoiceSpec:
    """一个角色在某一时期的音色。timbre_json 的结构化视图。"""

    voice_type: str = ""
    pitch: str = ""
    texture: str = ""
    resonance: str = ""
    accent: str = ""
    age_feel: str = ""
    tempo: str = ""
    energy: str = ""
    condition: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "VoiceSpec":
        data = data or {}
        return cls(**{
            f: str(data.get(f) or "").strip()
            for f in IDENTITY_FIELDS + EPOCH_FIELDS
        })

    def as_dict(self) -> dict[str, str]:
        return {f: getattr(self, f) for f in IDENTITY_FIELDS + EPOCH_FIELDS}

    def identity(self) -> tuple[str, ...]:
        return tuple(getattr(self, f) for f in IDENTITY_FIELDS)

    def missing(self) -> list[str]:
        """哪些必填维度是空的。accent 与 condition 允许空 ——
        没有口音特征和状态正常都是有效答案，写「无」反而是噪声。"""
        optional = {"accent", "condition"}
        return [
            f for f in IDENTITY_FIELDS + EPOCH_FIELDS
            if f not in optional and not getattr(self, f)
        ]

    def off_vocab(self) -> list[str]:
        """哪些取值不在术语表里。"""
        bad = []
        for f, terms in VOCAB.items():
            v = getattr(self, f)
            if v and v not in terms:
                bad.append(f"{field_label(f)}={v}")
        return bad

    def describe(self) -> str:
        """人读的一句话。"""
        parts = [p for p in (
            self.age_feel, self.voice_type, self.pitch, self.texture,
        ) if p]
        s = "".join(parts)
        tail = [p for p in (self.resonance and f"{self.resonance}共鸣",
                            self.accent, self.tempo and f"语速{self.tempo}",
                            self.energy) if p]
        if self.condition and self.condition != "健康":
            tail.append(self.condition)
        return s + ("（" + "、".join(tail) + "）" if tail else "")


def _step(field_name: str, a: str, b: str) -> int | None:
    """有序量表上差几档。任一取值不在表里则返回 None。"""
    scale = ORDERED.get(field_name)
    if not scale or a not in scale or b not in scale:
        return None
    return abs(scale.index(a) - scale.index(b))


#: 各维度对「能不能听辨」的贡献。声部换了立刻能分，共鸣只是锦上添花。
_WEIGHT = {
    "voice_type": 3, "texture": 2, "pitch": 2, "age_feel": 2,
    "resonance": 1, "accent": 1, "tempo": 1,
}
#: 同场说过话的角色之间，至少要有这么多分的差别
SAME_SCENE_MIN = 3
#: 全书范围内（不同场次）的下限。放松是因为不同场的两个配角不会被比较
BOOK_MIN = 2


def distinctness(a: VoiceSpec, b: VoiceSpec) -> tuple[int, list[str]]:
    """两个音色差多少，以及差在哪。

    返回 (分数, 差异说明)。分数越高越容易听辨。
    **同时返回差异说明**，因为「撞了」本身没有可操作性 ——
    要改的人得知道是哪一项撞了才知道该动哪一项。

    有序维度按档位给分：音区差一档还可能混，差两档基本不会，
    所以差一档只算一半的分。
    """
    score = 0
    diffs: list[str] = []
    for f, w in _WEIGHT.items():
        va, vb = getattr(a, f), getattr(b, f)
        if not va or not vb or va == vb:
            continue
        steps = _step(f, va, vb)
        gain = w if steps is None or steps >= 2 else max(1, w // 2)
        score += gain
        diffs.append(f"{field_label(f)} {va}／{vb}")
    return score, diffs


@dataclass
class Collision:
    """两个角色的音色太像。"""

    left: str
    right: str
    score: int
    threshold: int
    scope: str          # same_scene | book
    where: str = ""     # 撞在哪一场
    diffs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "left": self.left, "right": self.right, "score": self.score,
            "threshold": self.threshold, "scope": self.scope,
            "where": self.where, "diffs": self.diffs,
            "detail": (
                f"{self.left} 与 {self.right} 音色接近（{self.score}/{self.threshold}）"
                + (f"，同场：{self.where}" if self.where else "")
                + ("；仅差 " + "，".join(self.diffs) if self.diffs else "；各维度完全相同")
            ),
        }


def check_collisions(
    voices: dict[str, VoiceSpec],
    *,
    labels: dict[str, str] | None = None,
    co_occurrence: Iterable[tuple[str, Iterable[str]]] = (),
) -> list[Collision]:
    """找出听不出区别的角色对。

    co_occurrence 是「场次 → 该场说过话的角色」。同场的用严格阈值，
    其余用宽阈值 —— 见模块说明：全书两两互斥既做不到也没必要。

    同一对角色只报一次，同场优先 —— 同一个问题报两遍，
    改的人会以为有两处要改。
    """
    labels = labels or {}
    name = lambda k: labels.get(k, k)  # noqa: E731

    strict: dict[tuple[str, str], str] = {}
    for where, members in co_occurrence:
        ms = sorted({m for m in members if m in voices})
        for i, a in enumerate(ms):
            for b in ms[i + 1:]:
                strict.setdefault((a, b), where)

    out: list[Collision] = []
    keys = sorted(voices)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            pair = (a, b)
            same_scene = pair in strict
            floor = SAME_SCENE_MIN if same_scene else BOOK_MIN
            score, diffs = distinctness(voices[a], voices[b])
            if score >= floor:
                continue
            out.append(Collision(
                left=name(a), right=name(b), score=score, threshold=floor,
                scope="same_scene" if same_scene else "book",
                where=strict.get(pair, ""), diffs=diffs,
            ))
    out.sort(key=lambda c: (c.score, c.scope != "same_scene"))
    return out


#: 允许 identity 变动的时期类型，以及允许变的字段。
#: 其余情形下 identity 变了就是配错了人，不是「演化」。
#:
#: 音区跟着年龄走是生理事实：男孩变声后降下去，老年又浮上来一点。
#: 所以它虽然算 identity（同一时刻比两个角色时，音区是主要的区分维度），
#: 却必须允许 age 类时期改它 —— 否则「少年林凡」到「中年林凡」
#: 会被判成两个人，而那恰恰是配得对的情况。
#: 反过来，gear／status 这类时期改音区就是漂了：换了把刀嗓子不会变。
_DRIFT_ALLOWED: dict[str, tuple[str, ...]] = {
    # 变声期：童声 → 成年，以及随之而来的音区下沉
    "age": ("voice_type", "pitch"),
    # 伤病改嗓：断喉、久咳、烟熏
    "injury": ("texture", "resonance", "pitch"),
}


def check_identity_drift(
    epochs: list[tuple[str, str, VoiceSpec]],
) -> list[dict[str, Any]]:
    """同一角色跨时期，声线本体有没有跑掉。

    epochs 是按时间排好的 [(时期 key, 时期类型, 音色)]。
    逐对相邻比较而不是都跟基准比 —— 变声之后就该以变声后的为准，
    拿中年的嗓子跟童声比会一直报警。
    """
    issues: list[dict[str, Any]] = []
    for (pk, _pkind, prev), (ck, ckind, cur) in zip(epochs, epochs[1:]):
        allowed = _DRIFT_ALLOWED.get(ckind, ())
        for f in IDENTITY_FIELDS:
            pv, cv = getattr(prev, f), getattr(cur, f)
            if not pv or not cv or pv == cv or f in allowed:
                continue
            issues.append({
                "type": "identity_drift",
                "from_epoch": pk, "to_epoch": ck, "field": f,
                "detail": (
                    f"{pk} → {ck}：{field_label(f)}从「{pv}」变成「{cv}」，"
                    f"而这一期是「{ckind}」，不该改声线本体"
                ),
            })
    return issues


# ── 时期推导 ──────────────────────────────────────────────────────────────────
# 年龄推进对嗓子的影响是规律的，不必每次问模型：
# 少年到壮年音区下沉、力度上升，老年音区回升但力度下降、语速变慢。
# 规律的部分用规则推，模型只负责它真正判断不了的（这个角色伤在哪、伤成什么样）。

def _shift(scale: tuple[str, ...], value: str, delta: int) -> str:
    if value not in scale:
        return value
    return scale[max(0, min(len(scale) - 1, scale.index(value) + delta))]


#: 年龄感 → (音区偏移, 语速偏移, 力度偏移)，相对青年
_AGE_SHIFT: dict[str, tuple[int, int, int]] = {
    "童年": (2, 1, -1),
    "少年": (1, 1, 0),
    "青年": (0, 0, 0),
    "壮年": (0, 0, 1),
    "中年": (-1, 0, 0),
    "老年": (-1, -1, -1),
}


def derive_epoch_voice(
    base: VoiceSpec, *, age_feel: str = "", kind: str = "age",
    condition: str = "",
) -> VoiceSpec:
    """从基准音色推出某一时期的音色。

    identity 五项**逐字复用**，只动 epoch 四项 ——
    这就是「同一个嗓子的不同年龄版本」在代码里的样子。

    童年一档特殊：声部同时改成童声，因为变声前后确实是两种声部，
    而这正是 _DRIFT_ALLOWED 允许 age 改 voice_type 的原因。
    """
    out = VoiceSpec(**{f: getattr(base, f) for f in IDENTITY_FIELDS})
    out.age_feel = age_feel or base.age_feel
    out.condition = condition or "健康"

    b_age = base.age_feel if base.age_feel in _AGE_SHIFT else "青年"
    bp, bt, be = _AGE_SHIFT[b_age]
    tp, tt, te = _AGE_SHIFT.get(out.age_feel, (bp, bt, be))
    out.pitch = _shift(PITCH, base.pitch, tp - bp)
    out.tempo = _shift(TEMPO, base.tempo or "中等", tt - bt)
    out.energy = _shift(ENERGY, base.energy or "沉稳", te - be)

    if out.age_feel == "童年" and base.voice_type in ("男声", "女声"):
        out.voice_type = "童声"
    if kind == "injury":
        out.texture = "沙哑" if base.texture != "沙哑" else "气声"
        out.energy = _shift(ENERGY, out.energy, -1)
        out.condition = condition or "带伤"
    return out


# ── 与 TTS 引擎的接口 ─────────────────────────────────────────────────────────

#: 中性描述 → 各引擎通用的参数区间。
#: 具体引擎（qwen3-tts / 云 API）在中间层把这些映到自家的取值，
#: 核心永远不认某一家的 voice_id —— 与能力契约同一条原则。
_PITCH_HZ = {"低沉": -0.35, "偏低": -0.18, "中位": 0.0, "偏高": 0.18, "明亮高": 0.35}
_TEMPO_RATE = {"迟缓": 0.82, "偏慢": 0.91, "中等": 1.0, "偏快": 1.09, "急促": 1.2}
_ENERGY_GAIN = {"虚弱": -0.3, "收敛": -0.15, "沉稳": 0.0, "充沛": 0.15, "张扬": 0.3}
#: 声部 → 引擎的选声类别。**每一项都必须映得出确定的类别** ——
#: 映到 neutral 等于把选声权交回给引擎，而引擎不知道这个角色是男是女
_GENDER = {"童声": "child", "少年音": "male", "女声": "female", "男声": "male"}
_AGE_YEARS = {"童年": 9, "少年": 16, "青年": 25, "壮年": 33, "中年": 45, "老年": 65}


def to_tts_params(spec: VoiceSpec, *, voice_ref: str | None = None) -> dict[str, Any]:
    """把中性描述落成一次 TTS 调用的参数。

    pitch/rate/gain 是**相对偏移**而不是绝对值 —— 绝对值绑定采样率与
    引擎默认音高，换引擎就全错；相对偏移在哪家引擎上都表示同一件事：
    比这个音色的基准低三成、快一成。

    style_prompt 给支持自然语言描述的引擎（qwen3-tts 这类）直接用；
    不支持的引擎忽略它，靠 voice_ref 与数值参数也能配出接近的声音。
    """
    params: dict[str, Any] = {
        "gender": _GENDER.get(spec.voice_type, "neutral"),
        "age_hint": _AGE_YEARS.get(spec.age_feel, 30),
        "pitch_shift": _PITCH_HZ.get(spec.pitch, 0.0),
        "rate": _TEMPO_RATE.get(spec.tempo, 1.0),
        "gain": _ENERGY_GAIN.get(spec.energy, 0.0),
        "style_prompt": spec.describe(),
    }
    if voice_ref:
        params["voice_id"] = voice_ref
    return params


def vocab_brief() -> str:
    """给模型的术语表。取值必须从表里选 —— 表同时是验收白名单。"""
    lines = ["每一项都必须从下列取值中选一个，不要自造词，不要写成一句话："]
    for f in IDENTITY_FIELDS + EPOCH_FIELDS:
        terms = VOCAB.get(f)
        if terms:
            lines.append(f"  {field_label(f)}（{f}）：{'、'.join(terms)}")
        else:
            lines.append(
                f"  {field_label(f)}（{f}）：按目标圈层里真实存在的口音层写，"
                f"如「首都腔」「外省口音」「乡音」「教会腔」；没有明显口音就留空"
            )
    return "\n".join(lines)
