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
#: 拼音**专属**的声调符号：macron（ā ē ī ō ū ǖ）与 caron（ǎ ě ǐ ǒ ǔ ǚ）。
#: 西欧语言不用这两类，所以见到即可判定是拼音。
_PINYIN_ONLY_TONES = "āēīōūǖǎěǐǒǔǚǜǘ"
#: 与西欧语言**共用**的重音：á à é è í ì ó ò ú ù。
#: Cárdenas、Étienne、Gonçalo 里全是这些 —— 拿它们判拼音会把
#: 西语法语葡语的绝大多数人名判成音译，然后回落到兜底池。
_SHARED_ACCENTS = "áàéèíìóòúù"
_TONED_CHARS = _PINYIN_ONLY_TONES + _SHARED_ACCENTS

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
    """返回名字中疑似拼音的片段。空列表表示干净。

    只有**拼音专属**的声调符号才直接判定。共用重音（á é í ó ú）
    要走音节判断 —— 它们在西欧语言里是常态，
    见到就判拼音会把 Cárdenas、Étienne、Gonçalo 全判成音译。
    """
    if any(c in _PINYIN_ONLY_TONES for c in name):
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


#: 各书写系统的字符区间。判定「这个名字用的是不是目标语言的文字」——
#: 原来只认拉丁字母，于是俄语的 Фёдор、印地语的 अजय、阿拉伯语的 يوسف
#: 全被判成不合格，然后回落到兜底池。而兜底池只有 ja/en/ko，
#: 俄语会拿到一个英语名 —— 给俄语世界观配英文名比不配更糟，
#: 且下游全链路都会用它，没有任何一处会报错。
_SCRIPT_RANGES: dict[str, tuple[tuple[str, str], ...]] = {
    "latin": (("A", "Z"), ("a", "z"), ("À", "ÿ"), ("Ā", "ſ")),
    "cyrillic": (("Ѐ", "ӿ"),),
    "arabic": (("؀", "ۿ"), ("ݐ", "ݿ")),
    "devanagari": (("ऀ", "ॿ"),),
    "bengali": (("ঀ", "৿"),),
    "han": (("一", "鿿"),),
    "kana": (("぀", "ヿ"),),
    "hangul": (("가", "힣"), ("ᄀ", "ᇿ")),
}

#: 目标语言 → 期望的书写系统。多个表示都可接受。
_LANG_SCRIPTS: dict[str, tuple[str, ...]] = {
    "en": ("latin",), "es": ("latin",), "fr": ("latin",), "pt": ("latin",),
    "de": ("latin",), "it": ("latin",), "nl": ("latin",), "pl": ("latin",),
    "tr": ("latin",), "id": ("latin",), "vi": ("latin",),
    "ru": ("cyrillic",), "uk": ("cyrillic",), "bg": ("cyrillic",),
    "ar": ("arabic",), "fa": ("arabic",), "ur": ("arabic",),
    "hi": ("devanagari",), "mr": ("devanagari",), "ne": ("devanagari",),
    "bn": ("bengali",),
    "zh": ("han",), "ja": ("han", "kana"), "ko": ("hangul",),
}


def detect_scripts(value: str) -> set[str]:
    """这个字符串用到了哪些书写系统。"""
    found: set[str] = set()
    for ch in value:
        if not ch.strip() or ch in "'-·.":
            continue
        for name, ranges in _SCRIPT_RANGES.items():
            if any(lo <= ch <= hi for lo, hi in ranges):
                found.add(name)
                break
    return found


#: 明确要求音译的命名规范。这些圈层要的就是原名的转写 ——
#: 英语仙侠读者期待「Lin Zhao」，不是「Ethan Ashford」。
_TRANSLITERATION_PATTERNS = ("pinyin", "romaji", "hepburn", "wade", "translit")


def wants_transliteration(name_pattern: str | None) -> bool:
    """这个圈层的命名规范是不是「音译原名」。

    存真档的目标圈层写 name_pattern=pinyin，意思是**保留原名的读音**。
    此时拒绝拼音片段是**判反了** —— 实跑时校验器拒掉了 Lin Zhao、
    放行了 Ethan Ashford，于是一本仙侠里的主角叫 Ethan。
    """
    return any(k in (name_pattern or "").lower() for k in _TRANSLITERATION_PATTERNS)


def _min_tokens(name_pattern: str | None) -> int:
    """这个姓名格式至少要几段。

    俄语正式姓名是「名 + 父称 + 姓」三段（Фёдор Степанович Рукавишников）。
    按两段判会把完全正确的俄语全名判成不合格 —— 而不合格的下场是
    回落到兜底池，拿到一个别的语言的名字。
    """
    return 3 if (name_pattern or "").startswith("given_patronymic") else 2


def validate_localized_name(
    name: str, target_language: str, name_pattern: str | None = None,
    kind: str = "character",
) -> tuple[bool, str | None]:
    """校验一个候选名是否可用。返回 (是否合格, 不合格原因)。

    **段数要求只对人物生效。** 地点与组织有自己的命名规范：
    «Гостиный двор» 是完整的客栈名、Волчья балка 是完整的地名，
    它们不该被「必须是名+父称+姓」的规则拒掉 ——
    拒掉的下场是回落到人名兜底池，于是「镖局」变成了
    Николай Андреевич Лебедев，译文里「镖局的院子」
    成了「尼古拉·安德烈耶维奇·列别捷夫的院子」。
    """
    value = (name or "").strip()
    if not value:
        return False, "空名字"

    lang = target_language[:2].lower()

    if lang == "ko":
        # 谚文既不是汉字也不是假名，套 ja 的判据会把所有韩文名判成不合格，
        # 然后回落到兜底池 —— 而池子里正是这些被判不合格的名字，
        # 于是韩语这条线整个走不通。
        used = detect_scripts(value)
        if "hangul" in used:
            return True, None
        if "han" in used:
            return True, None          # 韩语人名可用汉字表记
        hits = contains_pinyin(value)
        if hits:
            return False, f"「{value}」含拼音片段 {hits}"
        return False, f"「{value}」不含谚文或汉字"

    if lang == "ja":
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

    # 其余语言：按该语言的书写系统判定
    expected = _LANG_SCRIPTS.get(lang, ("latin",))
    used = detect_scripts(value)
    if not used:
        return False, f"「{value}」不含任何可识别的文字"
    if not used & set(expected):
        return False, (
            f"「{value}」用的是 {'/'.join(sorted(used))} 文字，"
            f"目标语言 {lang} 需要 {'/'.join(expected)}"
        )
    if "han" in used and "han" not in expected:
        return False, f"「{value}」残留汉字"
    if "latin" in expected:
        # 音译圈层的判断**方向相反**：要的就是原名的转写。
        # 不分开的话，存真档会拒掉 Lin Zhao 而放行 Ethan Ashford
        if wants_transliteration(name_pattern):
            if not contains_pinyin(value) and not contains_han(value):
                return False, (
                    f"「{value}」不是原名的音译 —— 这个圈层要求保留原名读音"
                    f"（name_pattern={name_pattern}），"
                    f"给一个本地名字等于把角色换了个人"
                )
        else:
            hits = contains_pinyin(value)
            if hits:
                return False, f"「{value}」含拼音片段 {hits}"

    if kind == "character":
        need = _min_tokens(name_pattern)
        parts = [p for p in value.replace("　", " ").split() if p]
        if len(parts) < need:
            shape = "名 + 父称 + 姓" if need == 3 else "名 + 姓"
            return False, f"「{value}」应为「{shape}」的完整本地姓名"
    return True, None


def _has_kana(s: str) -> bool:
    return any("぀" <= c <= "ヿ" for c in s)


# ── 确定性兜底 ────────────────────────────────────────────────────────────────

class NoFallbackPool(RuntimeError):
    """该目标语言没有兜底姓名池。宁可报错，也不给一个别的语言的名字。"""

#: 兜底姓名池，**按性别分**。
#:
#: 原来是一个混着男女名的平表，取名只按哈希取模 —— 于是
#: 沈砚（男）拿到 Анна Петровна Волкова、老周（男）拿到 Мария Львовна Зайцева。
#: 数据上完全合法、校验也全过，只有读到正文的人会发现男主角叫了个女人名。
#: 目标语言的人名多带性别形态（俄语的父称与姓氏尾缀、西语葡语的词尾、
#: 阿拉伯语的 بن／بنت），配错一眼就能看出来。
#:
#: "any" 是给本身不显性别的名字留的（古典中文的「陆知微」「顾停云」这类），
#: 性别未知时也从它取。
_FALLBACK_POOLS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "ja": {
        "male": [("佐藤 健一", "さとう けんいち"), ("鈴木 隆", "すずき たかし"),
                 ("渡辺 誠", "わたなべ まこと"), ("山本 修", "やまもと おさむ")],
        "female": [("田中 静子", "たなか しずこ"), ("高橋 美代", "たかはし みよ"),
                   ("伊藤 房子", "いとう ふさこ"), ("中村 千代", "なかむら ちよ")],
    },
    "en": {
        "male": [("Edmund Ashcroft", ""), ("Roland Whitfield", ""),
                 ("Hugh Marlowe", ""), ("Walter Grimsby", "")],
        "female": [("Alice Thornbury", ""), ("Margery Colton", ""),
                   ("Constance Reed", ""), ("Eleanor Vance", "")],
    },
    "ko": {
        "male": [("김민준", ""), ("박지훈", "")],
        "female": [("이서연", ""), ("최수빈", "")],
    },
    # 中文作为**目标**语言的场景是真实存在的：日韩小说译成中文，
    # 或古典中文世界观之间互转。之前只把 zh 当源语言，漏了这一档 ——
    # 表现是命名回落时抛 NoFallbackPool，整批实体没有译名。
    "zh": {
        "male": [("沈砚舟", ""), ("裴无咎", ""), ("卫长陵", ""), ("周砚清", "")],
        "female": [("柳明栖", ""), ("苏怀瑾", "")],
        # 古典中文的名字多半不显性别，单列一档比硬塞进男女两边诚实
        "any": [("陆知微", ""), ("顾停云", "")],
    },
    "ru": {
        "male": [("Фёдор Ильич Соколов", ""), ("Николай Андреевич Лебедев", ""),
                 ("Павел Сергеевич Морозов", ""), ("Аркадий Львович Гущин", "")],
        "female": [("Анна Петровна Волкова", ""), ("Мария Львовна Зайцева", ""),
                   ("Дарья Ивановна Орлова", ""), ("Софья Кузьминична Белова", "")],
    },
    "es": {
        "male": [("Alonso Quijada", ""), ("Rodrigo Vela", ""), ("Gaspar Mendoza", "")],
        "female": [("Isabel Montoya", ""), ("Beatriz Cárdenas", ""), ("Elena Ferrer", "")],
    },
    "fr": {
        "male": [("Étienne Duval", ""), ("Henri Baudin", ""), ("Armand Delacroix", "")],
        "female": [("Camille Rousseau", ""), ("Sylvie Marchand", ""), ("Louise Bernard", "")],
    },
    "pt": {
        "male": [("Duarte Nogueira", ""), ("Gonçalo Braga", ""), ("Afonso Meireles", "")],
        "female": [("Inês Ribeiro", ""), ("Beatriz Soares", ""), ("Clara Antunes", "")],
    },
    "ar": {
        # بن = 之子，بنت = 之女 —— 阿拉伯语的父名结构本身就写着性别
        "male": [("يوسف بن إبراهيم", ""), ("عمر بن خالد", "")],
        "female": [("زينب بنت حسن", ""), ("فاطمة بنت سليمان", "")],
    },
    "hi": {
        "male": [("अजय शर्मा", ""), ("रघुनाथ सिंह", "")],
        "female": [("मीरा वर्मा", ""), ("कमला देवी", "")],
    },
    "bn": {
        "male": [("অরুণ ঘোষ", ""), ("বিমল সরকার", "")],
        "female": [("শ্যামা দত্ত", ""), ("রেণুকা বসু", "")],
    },
}

def deterministic_fallback_name(
    entity_id: str, transform_id: str, target_language: str,
    sex: str | None = None, *, avoid: set[str] | None = None,
) -> tuple[str, str]:
    """确定性兜底命名。

    v1 用 `hash()`，Python 字符串 hash 每进程随机 —— 同一实体重启后换个名字。
    改用 sha256：同一 (entity, transform, lang) 在任何进程、任何时刻结果恒定。

    **sex 决定从哪个池里取。** 不给的话从全部里取 ——
    那正是「沈砚拿到 Анна Петровна Волкова」的由来。

    avoid 里的名字跳过：兜底也会撞名，而撞名的两个角色在正文里
    是同一个人，比拿错性别更难发现。
    """
    lang = target_language[:2].lower()
    pools = _FALLBACK_POOLS.get(lang)
    if pools is None:
        # 不给别的语言的名字。回落到英语池会让俄语角色叫 Roland Whitfield，
        # 下游全链路都会用它，且没有任何一处会报错 —— 比没有名字糟得多。
        raise NoFallbackPool(
            f"目标语言 {lang} 没有兜底姓名池。请人工指定译名，"
            f"或在 _FALLBACK_POOLS 里补一组该语言的名字。"
        )
    pool = list(pools.get(sex or "", ()))
    pool += list(pools.get("any", ()))
    if not pool:
        # 性别给了但那一档是空的（或性别未知）：退回全部，
        # 有名字总比没名字好，但顺序仍然确定
        pool = [n for key in sorted(pools) for n in pools[key]]
    digest = hashlib.sha256(
        f"{entity_id}|{transform_id}|{target_language}".encode()
    ).digest()
    start = int.from_bytes(digest[:8], "big") % len(pool)
    taken = avoid or set()
    for off in range(len(pool)):
        cand = pool[(start + off) % len(pool)]
        if cand[0] not in taken:
            return cand
    # 池子被占满了：仍返回哈希位那个，让上层的撞名检查去报
    return pool[start]


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
