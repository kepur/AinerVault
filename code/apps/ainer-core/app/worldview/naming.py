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

# 目标语言里合法、但形似拼音的常见词 —— 避免误伤。
# 英文虚词与拼音姓氏大量撞车：he=何/贺, she=佘, you=尤, an=安, long=龙…
_ALLOW = {
    # 英文高频虚词与代词
    "he", "she", "it", "you", "we", "they", "him", "her", "his", "hers",
    "the", "a", "an", "and", "or", "but", "if", "so", "as", "at", "by",
    "for", "from", "in", "into", "of", "on", "to", "up", "out", "off",
    "was", "were", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "shall", "should", "can", "could", "may",
    "might", "must", "not", "no", "yes", "all", "any", "some", "who",
    "what", "when", "where", "why", "how", "then", "than", "there", "here",
    "this", "that", "these", "those", "one", "two", "ten", "men", "sun",
    "son", "run", "ran", "sit", "set", "see", "saw", "say", "said", "hand",
    "wind", "mind", "find", "kind", "band", "land", "sand", "send", "bend",
    "dan", "don", "din", "den", "din", "bin", "ban", "bun", "gun", "fun",
    "pin", "pen", "pan", "pun", "tin", "ton", "tan", "tone", "lane", "line",
    "mine", "nine", "wine", "dine", "fine", "pine", "vine", "shine",
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
    # 白名单优先于姓氏表：he/she/you/an 这些英文虚词与拼音姓氏（何/佘/尤/安）
    # 大量撞车，先判姓氏会把整篇英文都标成音译。
    if t in _ALLOW:
        return False
    if t in _SURNAMES:
        return True
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


# ── 中文姓名解析（family_key 推断的基础）─────────────────────────────────────

#: 单姓。覆盖《百家姓》高频段 + 现代常见姓。
_CN_SURNAMES_1 = set(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾萧田董袁潘"
    "于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江"
    "尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤翁柳鲍樊霍虞万支柯昝"
    "管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑裴陆荣翁荀"
    "羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋"
    "仲伊宫宁仇栾暴甘钭厉戎祖符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸"
    "籍赖卓蔺屠蒙池乔阴鬱胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍卻璩桑桂濮牛"
)
#: 复姓
_CN_SURNAMES_2 = {
    "欧阳", "太史", "端木", "上官", "司马", "东方", "独孤", "南宫", "万俟", "闻人",
    "夏侯", "诸葛", "尉迟", "公羊", "赫连", "澹台", "皇甫", "宗政", "濮阳", "公冶",
    "太叔", "申屠", "公孙", "慕容", "仲孙", "钟离", "长孙", "宇文", "司徒", "鲜于",
    "司空", "闾丘", "子车", "亓官", "司寇", "巫马", "公西", "颛孙", "壤驷", "公良",
    "漆雕", "乐正", "宰父", "谷梁", "拓跋", "夹谷", "轩辕", "令狐", "段干", "百里",
    "呼延", "东郭", "南门", "羊舌", "微生", "公户", "公玉", "公仪", "梁丘", "公仲",
    "西门", "东门", "左丘", "第五", "南荣",
}
#: 常见称谓后缀 —— 「李掌柜」「王大人」这类里，姓后面跟的是身份不是名
_TITLE_SUFFIXES = (
    "掌柜", "大人", "先生", "夫人", "公子", "小姐", "姑娘", "老板", "师父", "大夫",
    "郎中", "员外", "老爷", "少爷", "婆婆", "大娘", "大爷", "叔", "伯", "哥", "姐",
)


def cn_surname(name: str) -> str:
    """取中文姓名的姓。识别不出返回空串。"""
    n = (name or "").strip()
    if len(n) < 2 or not contains_han(n):
        return ""
    if n[:2] in _CN_SURNAMES_2:
        return n[:2]
    if n[0] in _CN_SURNAMES_1:
        return n[0]
    return ""


def infer_family_key(name: str) -> str | None:
    """由中文姓名推断家族标识。

    同 family_key 的实体在同一 transform 下必须共享姓氏映射 ——
    李清照与其父李格非同属 li_family，映射到昭和日本时姓氏统一，
    不会一个綾小路一个佐藤。这是 v1 没有的一层。
    """
    surname = cn_surname(name)
    if not surname:
        return None
    # 「李掌柜」这类是称谓不是姓名，不参与家族分组
    rest = name.strip()[len(surname):]
    if rest and rest in _TITLE_SUFFIXES:
        return None
    return f"{surname}_family"


def is_person_like(name: str) -> bool:
    """粗判是否像人名 —— 用于实体抽取后的兜底过滤。"""
    n = (name or "").strip()
    if not (2 <= len(n) <= 6) or not contains_han(n):
        return False
    return bool(cn_surname(n))
