"""L1 人名：确定性兜底 + 拼音检测 + 家族姓氏一致性。

修 v1 两个缺陷：
1. `_fallback_localized_name` 用 `hash(entity_id) % len(pool)`。Python 字符串 hash 每进程
   随机（PYTHONHASHSEED），同一实体在不同进程会兜底到不同名字 —— 漂移恰好发生在
   最不该发生的兜底路径上。此处改用 sha256，跨进程恒定。
2. `FORBIDDEN_PINYIN_PARTS` 只有约 30 个硬编码词，Zheng/Feng/Shen/Tang 等一律漏网。
   此处改为「姓氏全表 + 汉语特征音节 + 英文白名单」三层规则。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

# ── 百家姓罗马化（含常见复姓与港台/威妥玛拼法）────────────────────────────────
_SURNAMES = {
    # 单姓 · 高频
    "li", "wang", "zhang", "liu", "chen", "yang", "huang", "zhao", "wu", "zhou",
    "xu", "sun", "ma", "zhu", "hu", "guo", "he", "gao", "lin", "luo", "zheng",
    "liang", "xie", "song", "tang", "deng", "han", "feng", "cao", "peng", "zeng",
    "xiao", "tian", "dong", "yuan", "pan", "cai", "jiang", "yu", "du", "ye",
    "cheng", "wei", "su", "lu", "ding", "ren", "shen", "yao", "lu", "jiang",
    "cui", "zhong", "tan", "lu", "wang", "shi", "yan", "xiong", "jin", "lu",
    "hao", "kong", "bai", "cui", "kang", "mao", "qiu", "qin", "jiang", "shi",
    "gu", "hou", "shao", "meng", "long", "wan", "duan", "lei", "qian", "tang",
    "yin", "li", "yi", "chang", "wu", "qiao", "he", "lai", "gong", "wen",
    "pang", "fan", "lan", "shi", "ou", "ni", "xiang", "mo", "zhuang", "xin",
    "guan", "zhuo", "ji", "fu", "gan", "geng", "bo", "cong", "hua", "kan",
    # 复姓
    "ouyang", "shangguan", "sima", "zhuge", "situ", "dongfang", "duanmu",
    "gongsun", "huangfu", "murong", "nangong", "shangqiu", "taishi", "ximen",
    "xiahou", "yuchi", "zhongli", "linghu",
    # 威妥玛 / 粤语常见拼法
    "lee", "wong", "chan", "cheung", "leung", "ng", "chow", "lam", "tsang",
    "chiang", "hsu", "hsieh", "kuo", "tsai", "chao", "hsiung", "kao",
}

# 汉语拼音特征音节（几乎不出现在英文/日文罗马字中）
_PINYIN_INITIALS = ("zh", "ch", "sh", "q", "x", "c", "z", "r")
_PINYIN_FINALS = (
    "uo", "uang", "iang", "iong", "iu", "ian", "üe", "ue", "ui", "un",
    "ong", "eng", "ao", "ou", "ai", "ei", "ie", "ia", "uai", "van", "ang",
)
# 声调数字 / 带调字母
_TONE_RE = re.compile(r"[1-5]$")
_TONED_CHARS = "āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ"

# 目标语言里合法、但形似拼音的常见词 —— 避免误伤
_ALLOW = {
    "man", "men", "can", "cane", "ban", "bane", "dan", "dane", "fan", "fane",
    "pan", "pane", "tan", "wang", "hang", "sang", "long", "song", "gong",
    "king", "sing", "ring", "wing", "ding", "bing", "ping", "ting", "mine",
    "shine", "shan", "shane", "chen", "chan", "chin", "shin", "sean", "shaun",
    "lian", "ian", "sian", "an", "on", "in", "en", "un",
}

_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_KATAKANA_RE = re.compile(r"^[゠-ヿ・　-〿\s]+$")
_HAN_RE = re.compile(r"[一-鿿]")


def _strip_tones(text: str) -> str:
    out = unicodedata.normalize("NFD", text)
    return "".join(c for c in out if not unicodedata.combining(c))


def looks_like_pinyin(token: str) -> bool:
    """单个拉丁词是否像汉语拼音。"""
    t = _strip_tones(token.strip().lower().replace("'", "").replace("-", ""))
    t = _TONE_RE.sub("", t)
    if not t or not t.isalpha():
        return False
    if t in _SURNAMES:
        return True
    if t in _ALLOW:
        return False
    has_initial = t.startswith(_PINYIN_INITIALS)
    has_final = any(t.endswith(f) for f in _PINYIN_FINALS)
    # zh/x/q/c/z 起头 + 拼音韵尾，两个条件同时成立才判定，压低假阳性
    return has_initial and has_final


def contains_pinyin(name: str) -> list[str]:
    """返回名字中疑似拼音的片段。空列表表示干净。"""
    if any(c in _TONED_CHARS for c in name):
        return [name]
    return [tok for tok in _LATIN_TOKEN_RE.findall(name) if looks_like_pinyin(tok)]


def contains_han(name: str) -> bool:
    return bool(_HAN_RE.search(name))


def looks_like_katakana_transliteration(name: str) -> bool:
    """日语目标下的片假名音译，如 リ・セイショウ —— 是音译不是文化等效命名。"""
    s = name.strip()
    if not s or not _KATAKANA_RE.match(s):
        return False
    return "・" in s or "･" in s or len(s.replace(" ", "")) >= 4


def validate_localized_name(name: str, target_language: str) -> tuple[bool, str | None]:
    """校验一个候选名是否可用。返回 (是否合格, 不合格原因)。"""
    value = (name or "").strip()
    if not value:
        return False, "空名字"

    lang = target_language[:2].lower()

    if lang in {"ja", "ko"}:
        if contains_han(value) or _KATAKANA_RE.match(value) or _has_kana(value):
            if looks_like_katakana_transliteration(value):
                return False, f"「{value}」是片假名音译，不是文化等效命名"
            return True, None
        hits = contains_pinyin(value)
        if hits:
            return False, f"「{value}」含拼音片段 {hits}"
        return False, f"「{value}」不含目标语言文字"

    if lang == "zh":
        return (True, None) if contains_han(value) else (False, f"「{value}」不含汉字")

    # 拉丁语系目标
    hits = contains_pinyin(value)
    if hits:
        return False, f"「{value}」含拼音片段 {hits}"
    if contains_han(value):
        return False, f"「{value}」残留汉字"
    if len(_LATIN_TOKEN_RE.findall(value)) < 2:
        return False, f"「{value}」应为「名 + 姓」的完整本地姓名"
    return True, None


def _has_kana(s: str) -> bool:
    return any("぀" <= c <= "ヿ" for c in s)


# ── 确定性兜底 ────────────────────────────────────────────────────────────────

_FALLBACK_POOLS: dict[str, list[tuple[str, str]]] = {
    "ja": [
        ("佐藤 健一", "さとう けんいち"), ("田中 静子", "たなか しずこ"),
        ("鈴木 隆", "すずき たかし"), ("高橋 美代", "たかはし みよ"),
        ("渡辺 誠", "わたなべ まこと"), ("伊藤 房子", "いとう ふさこ"),
        ("山本 修", "やまもと おさむ"), ("中村 千代", "なかむら ちよ"),
    ],
    "en": [
        ("Edmund Ashcroft", ""), ("Alice Thornbury", ""), ("Roland Whitfield", ""),
        ("Margery Colton", ""), ("Hugh Marlowe", ""), ("Constance Reed", ""),
        ("Walter Grimsby", ""), ("Eleanor Vance", ""),
    ],
    "ko": [
        ("김민준", ""), ("이서연", ""), ("박지훈", ""), ("최수빈", ""),
    ],
}


def deterministic_fallback_name(
    entity_id: str, transform_id: str, target_language: str
) -> tuple[str, str]:
    """确定性兜底命名。

    v1 用 `hash()`，Python 字符串 hash 每进程随机 —— 同一实体重启后换个名字。
    改用 sha256：同一 (entity, transform, lang) 在任何进程、任何时刻结果恒定。
    """
    lang = target_language[:2].lower()
    pool = _FALLBACK_POOLS.get(lang, _FALLBACK_POOLS["en"])
    digest = hashlib.sha256(
        f"{entity_id}|{transform_id}|{target_language}".encode()
    ).digest()
    idx = int.from_bytes(digest[:8], "big") % len(pool)
    return pool[idx]


# ── 家族姓氏一致性 ─────────────────────────────────────────────────────────────

def split_surname(name: str, name_pattern: str) -> tuple[str, str]:
    """按目标世界观的姓名格式拆出 (姓, 名)。"""
    parts = name.strip().replace("　", " ").split()
    if len(parts) < 2:
        return "", name.strip()
    if name_pattern == "given_family":
        return parts[-1], " ".join(parts[:-1])
    # family_given（中日韩）与 given_of_place 都以首段为姓/家名
    return parts[0], " ".join(parts[1:])


def check_family_consistency(
    names: list[tuple[str, str, str]], name_pattern: str
) -> list[dict]:
    """检查同一家族的姓氏是否一致。

    names: [(entity_id, family_key, target_name), ...]
    返回冲突列表 —— 李清照与其父李格非若被映射成两个姓，在这里被抓住。
    """
    by_family: dict[str, list[tuple[str, str, str]]] = {}
    for entity_id, family_key, target_name in names:
        if family_key:
            by_family.setdefault(family_key, []).append(
                (entity_id, split_surname(target_name, name_pattern)[0], target_name)
            )

    conflicts: list[dict] = []
    for family_key, members in by_family.items():
        surnames = {s for _, s, _ in members if s}
        if len(surnames) > 1:
            majority = max(surnames, key=lambda s: sum(1 for _, x, _ in members if x == s))
            for entity_id, surname, full in members:
                if surname and surname != majority:
                    conflicts.append({
                        "entity_id": entity_id,
                        "family_key": family_key,
                        "detected": full,
                        "detected_surname": surname,
                        "expected_surname": majority,
                        "all_surnames": sorted(surnames),
                    })
    return conflicts
