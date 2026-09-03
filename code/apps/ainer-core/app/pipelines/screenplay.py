"""小说 → 剧本：把一段话拆成「台词」与「动作」。

**这是整条影片线的关键一步，而它原来不存在。**

小说的一个自然段里，台词和叙述是混在一起的：

    「镖师不跑。」老周把碗放在栏杆上。「要跑，第一趟就跑了。」
     ~~~~~~~~~~ 台词        ~~~~~~~~~~~~~~~~~~~~ 动作      ~~~~~~~~~~~~~~~~~~~~ 台词

块级分类只回答「这一段是不是对白段」，回答不了「哪几个字是说出口的」。
于是配音把整段都念了 —— 包括「老周把碗放在栏杆上」。听起来就是有旁白，
而数据上这一条明明标着 dialogue。

有声书里这样是对的（一个人念完整段）。**影片里是错的**：

    台词  → 配音，且要与口型对上
    动作  → 不发声，它是画面：首尾帧之间变的就是这件事
    叙述  → 同样不发声，它是场景描述

所以同一段文本在两种投影里要拆成不同的东西。这个拆分是**规则能做的**
（引号是形式化的），不该交给模型 —— 交给模型就得为每一段付一次钱，
而且它会时不时把动作也算进台词。

## 拆不动的要报出来

俄语、法语用破折号引出对话，而破折号也用作插入语：

    — Это я, — сказал он. — А он — нет.
      ~~~~~~~ 台词  ~~~~~~~~~ 归属      ~~~~~~~ 台词  ~~~ 这个破折号是「不是」的意思

规则拆不干净。**报出来让人看一眼，比猜一个然后让配音念错强。**
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: 成对引号。每一对都要**成对**匹配 —— 只找左引号会把
#: 「他说：『别去。』」这类嵌套拆错
_PAIRS: tuple[tuple[str, str], ...] = (
    ("「", "」"),   # 「」中日
    ("『", "』"),   # 『』
    ("“", "”"),   # “” 中英
    ("«", "»"),   # «» 俄法西
    ("„", "“"),   # „“ 德
    ("‘", "’"),   # ‘’
    ('"', '"'),
)

#: 破折号引出的对话。俄语与法语用它，而破折号又兼作插入语，
#: 所以命中它只说明「这一段可能是破折号体」，不足以直接切
_DASH_LEAD = re.compile(r"(?m)^\s*[—–-]\s+")

#: 归属小句：「他说」「她低声道」。**位置固定在台词之后**，
#: 这是破折号体里唯一可靠的边界信号
_ATTRIB = re.compile(
    r"[—–-]\s*[^—–]{0,40}?"
    r"(сказал\w*|ответил\w*|проговорил\w*|отозвал\w*|добавил\w*|"
    r"said|replied|asked|added|murmured|"
    r"说|道|答|问|喙咕|低声)",
    re.I)


@dataclass
class Split:
    """一段话拆开之后。"""

    speech: list[str] = field(default_factory=list)
    action: str = ""
    #: 拆不干净时说明为什么。**空字符串表示拆得干净** ——
    #: 不要用 None，None 会被 `if uncertain` 判成假，
    #: 而「拆不动」恰恰是最需要被看见的那种情况
    uncertain: str = ""

    @property
    def speech_text(self) -> str:
        return " ".join(s.strip() for s in self.speech if s.strip())

    def as_dict(self) -> dict[str, Any]:
        return {"speech": self.speech, "action": self.action,
                "uncertain": self.uncertain}


def split_speech(text: str) -> Split:
    """把一段话拆成台词与动作。

    优先找成对引号 —— 那是无歧义的。找不到才看破折号体，
    而破折号体只在能定位到归属小句时才拆，否则整段算动作并报出来。
    """
    raw = (text or "").strip()
    if not raw:
        return Split()

    quoted = _by_quotes(raw)
    if quoted is not None:
        return quoted

    if _DASH_LEAD.search(raw):
        return _by_dash(raw)

    # 没有任何引号：整段是叙述/动作，没有台词。
    # **这不是「拆不动」** —— 它拆得很干净，答案就是「没人说话」
    return Split(speech=[], action=raw)


def _by_quotes(raw: str) -> Split | None:
    spans: list[tuple[int, int, str]] = []
    for lq, rq in _PAIRS:
        start = 0
        while True:
            i = raw.find(lq, start)
            if i < 0:
                break
            j = raw.find(rq, i + len(lq))
            if j < 0:
                # 有左无右：引号没闭合。**不猜到段尾** ——
                # 那会把后面的动作描写整段算成台词
                start = i + len(lq)
                continue
            spans.append((i, j + len(rq), raw[i + len(lq):j]))
            start = j + len(rq)
    if not spans:
        return None

    spans.sort()
    merged: list[tuple[int, int, str]] = []
    for sp in spans:
        if merged and sp[0] < merged[-1][1]:
            continue          # 嵌套引号：外层已经收了
        merged.append(sp)

    speech = [s for *_, s in merged if s.strip()]
    action = _strip_join(
        [raw[:merged[0][0]]]
        + [raw[merged[k][1]:merged[k + 1][0]] for k in range(len(merged) - 1)]
        + [raw[merged[-1][1]:]])
    return Split(speech=speech, action=action)


def _by_dash(raw: str) -> Split:
    """破折号体。只在能定位归属小句时才切。"""
    # **从引导破折号之后开始找归属小句。**
    # 不跳过的话，正则会咬住行首那个破折号 ——
    # 「— Это я, — сказал он」里 head 变成空串，台词整句丢掉，
    # 而报出来的理由是「破折号之后没有内容」，指向完全错误的地方。
    lead = _DASH_LEAD.match(raw)
    off = lead.end() if lead else 0
    m = _ATTRIB.search(raw, off)
    if m is None:
        return Split(
            speech=[], action=raw,
            uncertain="破折号体但找不到「他说」这类归属小句，"
                      "无法确定哪一段是说出口的话；整段先按动作处理")
    head = raw[off:m.start()]
    speech = head.strip(" —–-,.;")
    tail = raw[m.start():]
    if not speech:
        return Split(speech=[], action=raw,
                     uncertain="破折号在最前但其后没有内容")
    return Split(
        speech=[speech], action=tail.strip(),
        # 后半段可能还有第二句台词（「— А он — нет.」），
        # 而那个破折号也可能是「不是」的意思 —— 分不开，说出来
        uncertain=("这一段是破折号体，归属小句之后还有内容；"
                   "若其中还有台词，需要人看一眼"
                   if _DASH_LEAD.search(tail) or "—" in tail else ""))


def _strip_join(parts: list[str]) -> str:
    out = " ".join(p.strip() for p in parts if p and p.strip())
    return re.sub(r"\s{2,}", " ", out).strip(" ,.;。，")


# ── 时长规则 ──────────────────────────────────────────────────────────────────
#
# 用户的话：**首尾帧之间超过五秒就会审美疲劳** ——
# 走路、海浪、粒子，五秒之内是一个动作，五秒之后是同一个动作重复。
# 动态场景更短：一次出击、一次爆炸，三秒就该切。
#
# 这不是审美偏好，是 i2v 模型的能力边界：它在首尾帧之间做插值，
# 时间越长插得越假，最后变成慢动作糊影。

#: 静态场景（对话、静观、环境）
STATIC_MAX_MS = 5000
#: 动态场景（打斗、追逐、爆炸）
ACTION_MAX_MS = 3000
#: 低于这个数观众来不及看清
MIN_MS = 1200

#: 判定「动态」的词。中英文都收 —— 分镜的描述可能是任一种语言
_ACTION_WORDS = (
    "打斗", "挥刀", "出招", "抛", "撞", "摔",
    "踢", "拳", "爆", "奔", "追", "跑", "跃", "扭打",
    "拔刀", "刺", "砍", "剥", "撞击", "飞溅",
    "fight", "strike", "punch", "kick", "leap", "chase", "run", "explos",
    "slash", "stab", "crash", "burst", "shatter", "collide", "throw",
)


def is_action_beat(*texts: str | None) -> bool:
    """这一镜是不是动态场景。"""
    blob = " ".join(t.lower() for t in texts if t)
    return any(w in blob for w in _ACTION_WORDS)


def clamp_shot_ms(ms: int, *, action: bool) -> tuple[int, str]:
    """把镜头长度收进可用区间，返回（新长度, 原因）。

    **超上限要切，不是警告。** 一个九秒的静止镜头在成片里就是九秒不动，
    而它在数据里看着完全正常 —— 只有播到那里的人会难受。
    """
    cap = ACTION_MAX_MS if action else STATIC_MAX_MS
    if ms > cap:
        return cap, (f"{'动态' if action else '静态'}场景上限 {cap/1000:.0f}s，"
                     f"原 {ms/1000:.1f}s 会让同一个动作重复到疲劳")
    if ms < MIN_MS:
        return MIN_MS, f"低于 {MIN_MS/1000:.1f}s 观众来不及看清"
    return ms, ""


# ── 占位符残留 ────────────────────────────────────────────────────────────────

#: 还原之后仍然像占位符的东西。**模型会发明自己的简写**：
#: 我们给它 `{{CHAR:xxx}}`，它还回来 `⟦E1⟧` ——
#: restore_placeholders 只认 `{{}}`，还原不了，垃圾 token 直接进成品。
_LEFTOVER = re.compile(
    r"\{\{[^}]{0,40}\}\}"          # 我们自己的没被还原
    r"|[⟦⟧〖〗][^⟦⟧〖〗]{0,20}"
    r"[⟦⟧〖〗]"  # ⟦E1⟧ 这类模型自造的
    r"|<[A-Z]{1,6}\d{0,3}>"        # <E1> <CHAR1>
    r"|\[\[[^\]]{0,30}\]\]"        # [[E1]]
)


def leftover_placeholders(text: str) -> list[str]:
    """译文里残留的占位符。空列表 = 干净。

    要在**每一条译文落库前**查一次。查不查的差别是：
    「配音念出一串 ⟦E1⟧」和「这条译文没通过，回去重译」。
    """
    return sorted({m.group(0) for m in _LEFTOVER.finditer(text or "")})


#: 结构性垃圾：模型把 JSON 骨架的碎片留在了正文里。
#: 实跑撞到的是 `Павел Сергеевич Морозов шагнул вперёд. }]}]}]}` ——
#: 一串括号跟在一句正常的译文后面，解析器认为这一条成功了。
_JUNK = re.compile(
    r"[}\]]{2,}"                    # }]}]}]} 这类闭合括号串
    r"|\{\s*\"[a-z_]{2,20}\"\s*:"      # {"translated_text": 之类的键
    r"|^\s*[\[{]\s*$"                 # 独占一行的括号
    , re.M)


def translation_junk(text: str) -> list[str]:
    """译文里不该有的东西：占位符残留 + 结构碎片。

    **要在每一条译文落库前查。** 查与不查的差别是
    「配音把 }]}]}]} 念出来」和「这一条没通过，回去重译」。

    解析成功不等于内容干净：JSON 解出来了、字段也在，
    只是字段的值里混进了骨架本身。这类错误逐条看译文时最容易漏 ——
    眼睛会自动跳过句尾那串括号。
    """
    out = leftover_placeholders(text)
    out += sorted({m.group(0).strip() for m in _JUNK.finditer(text or "")
                   if m.group(0).strip()})
    return sorted(set(out))
