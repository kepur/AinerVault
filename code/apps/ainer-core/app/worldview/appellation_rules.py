"""中文称呼的形态学规则 —— 用构词法判 name_type，而不是赌模型的判断力。

**为什么要有这一层。** 让 LLM 判「老周是专名还是名号」，
换个模型就可能换个答案：minimax 判成 epithet，那会走意译译出 Old Zhou；
下一个模型可能判对，再下一个又判错。管线的正确率不该随模型漂移。

而中文称呼的构词是**有规律且可枚举**的：

    老周 / 小林 / 阿强      亲近前缀 + 姓          → proper
    张老 / 李公             姓 + 敬称后缀          → proper
    姓沈的                  「姓」+ 姓 + 「的」    → proper（轻蔑）
    掌柜 / 镖头 / 县令      职务词                 → role
    灰衣汉子 / 独臂老人     特征 + 人称量词        → epithet
    那个人 / 几个汉子       指示／数量 + 泛称      → generic

规则给不出结论时才交给模型，且把判据一并喂过去（见 entities.py 的提示词）。
两边都判时以**高置信规则**为准 —— 规则错了能改一行代码，
模型错了只能重跑并祈祷。

这一层只管中文源。别的源语言各有各的构词法，
判不出来就返回 None，让模型接手。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import EntityKind, NameType
from app.worldview.naming import _CN_SURNAMES_1, _CN_SURNAMES_2

#: 亲近前缀。「老周」的周换成李就成了老李 —— 它指的是特定那个人，
#: 所以是 proper 而非 epithet。判成 epithet 会让它走意译，
#: 译出 Old Zhou 这种东西。
_INTIMATE_PREFIX = ("老", "小", "阿", "大")

#: 姓后敬称。张老、李公、王翁
_RESPECT_SUFFIX = ("老", "公", "翁", "叟", "君", "生")

#: 职务与身份。可枚举，且名物词表里通常也有。
#: 收得比实际用到的宽 —— 漏判一个职务的代价是它去造了个人名，
#: 而多判一个的代价只是走词表转译，后者轻得多。
_ROLE_WORDS = frozenset("""
掌柜 镖头 总镖头 镖师 趟子手 伙计 小二 店家 老板 东家 账房 跑堂
师父 师娘 师兄 师弟 师姐 师妹 徒弟 弟子 门主 帮主 舵主 堂主 教头
县令 知府 知县 巡抚 总督 太守 县丞 主簿 捕头 捕快 差役 衙役 官差
将军 校尉 都尉 参将 副将 千总 把总 兵卒 军士 亲兵 侍卫 护卫
郎中 大夫 先生 秀才 举人 进士 状元 书生 老丈 老者 婆子 丫鬟 家丁
车夫 船夫 樵夫 渔夫 农夫 猎户 铁匠 木匠 裁缝 厨子 更夫 门房
方丈 住持 道长 和尚 尼姑 道士 神父 牧师
公子 小姐 少爷 夫人 太太 老爷 姑娘 娘子 相公 官人
""".split())

#: 人称量词。出现在末尾且前面是描述性成分时，整体是 epithet
_PERSON_NOUN = ("汉子", "老人", "男子", "女子", "书生", "少年", "少女",
                "老者", "妇人", "孩子", "和尚", "道人", "客人", "人影")

#: 通称 —— 指一**类**人而不是某一个人。
#:
#: 与 _ROLE_WORDS 的区别在于能不能落到唯一的人身上：
#: 「掌柜」在一家客栈里就是那一个，「学生」在一间教室里有五十个。
#: 所以职务可以走名物词表转译并保持一致，通称不行。
#:
#: 为什么必须硬判：这些词一旦成了某个角色的别名，
#: 占位符那一闸会把全文每一个「学生」都换成主角的名字。
#: 坏蛋第一章实跑的后果 ——
#:   「把一个身材瘦弱的学生逼在墙角」→ 直接点名 Thomas Ashford，
#:   而原文到第七句才借旁人之口交代他叫什么，悬念在替换那一步就没了；
#:   「这小子是我班里学习尖子」→ "This that whelp is a straight-A
#:   student"，因为「小子」被锁成固定短语，前面的「这」没了着落。
#:
#: 收得**窄**：只收落不到具体人身上的通称。
#: 「胖子」「高个」这类在一场戏里指认得出唯一那个人的绰号不收 ——
#: 那是 epithet，是称呼系统本来就要处理的东西。
_COMMON_ADDRESS = frozenset("""
学生 学生们 同学 同学们 老师 女生 男生 女孩 男孩 孩子 孩子们
小子 家伙 少年 少女 男人 女人 男的 女的 人们 大家 众人 大伙
老头 老太 青年 中年人 年轻人 路人 旁人 别人 有人 对方
""".split())

#: 指示与不定量词。带这些的是泛指，不该建实体
_GENERIC_LEAD = ("那个", "这个", "某个", "有个", "一个", "几个", "两个",
                 "三个", "众", "诸", "各", "另一")

_HAN = re.compile(r"[一-鿿]")
#: 描述性成分：颜色、材质、身体特征。用于识别 epithet
_DESCRIPTIVE = frozenset(
    "黑白红黄蓝绿青灰紫褐金银铜铁木石布绸绢麻皮革"
    "独断残瞎聋哑跛驼胖瘦高矮老少美丑长短大小"
)


@dataclass(frozen=True)
class Verdict:
    """一次规则判定。confidence 决定它能不能覆盖模型的判断。"""

    name_type: NameType
    confidence: float
    reason: str

    @property
    def decisive(self) -> bool:
        """够不够硬到可以直接推翻模型。

        0.9 这条线是按「误判代价」定的：过线的规则都是构词法上
        几乎没有反例的（姓氏表命中、职务词表命中）。
        没过线的只作为提示，不覆盖模型。
        """
        return self.confidence >= 0.9


def _is_surname(ch: str) -> bool:
    return ch in _CN_SURNAMES_1


def classify(name: str, kind: EntityKind) -> Verdict | None:
    """按构词法判 name_type。判不出返回 None，交给模型。

    只处理中文。非中文名字直接返回 None —— 别的语言各有各的构词法，
    硬套中文规则会把 Sir Thomas 判成职务。
    """
    n = (name or "").strip()
    if not n or not _HAN.search(n):
        return None

    # ── 通称：指一类人，落不到具体某个人身上 ──
    if n in _COMMON_ADDRESS:
        return Verdict(NameType.generic, 0.96,
                       f"「{n}」指的是一类人，不是特定的谁")

    # ── 泛指：指示词或不定量词开头 ──
    for lead in _GENERIC_LEAD:
        if n.startswith(lead):
            return Verdict(NameType.generic, 0.95,
                           f"以指示／不定量词「{lead}」开头，指的不是特定的谁")

    # ── 职务：整词命中 ──
    if n in _ROLE_WORDS:
        return Verdict(NameType.role, 0.95, f"「{n}」是职务／身份称谓")
    # 「总镖头」这类前缀职务：去掉修饰仍是职务词
    for prefix in ("总", "副", "大", "老", "小"):
        if n.startswith(prefix) and n[len(prefix):] in _ROLE_WORDS:
            return Verdict(NameType.role, 0.92,
                           f"「{n[len(prefix):]}」是职务，「{prefix}」是修饰")

    if kind is not EntityKind.character:
        # 以下规则都是人名构词，非人物不适用
        return None

    # ── 亲近前缀 + 姓：老周、小林 ──
    if len(n) == 2 and n[0] in _INTIMATE_PREFIX and _is_surname(n[1]):
        return Verdict(
            NameType.proper, 0.95,
            f"「{n[0]}」+ 姓「{n[1]}」是亲近称呼，指特定的那个人 —— "
            f"换个姓就是另一个人，所以是专名不是名号",
        )

    # ── 「阿X」：X 通常是**名**而不是姓（阿强、阿珍），所以不查姓氏表。
    #    「阿」几乎只用于人的亲近称呼，误判风险低；
    #    但置信度给低一档 —— 万一是「阿房宫」这类地名的一截。
    if len(n) == 2 and n[0] == "阿":
        return Verdict(NameType.proper, 0.9,
                       "「阿」+ 单字是亲近称呼，后面那字通常是名而非姓")

    # ── 姓 + 敬称：张老、李公 ──
    if len(n) == 2 and _is_surname(n[0]) and n[1] in _RESPECT_SUFFIX:
        return Verdict(NameType.proper, 0.92, f"姓「{n[0]}」+ 敬称「{n[1]}」")

    # ── 姓X的：轻蔑称呼，仍指特定的人 ──
    if len(n) >= 3 and n.startswith("姓") and n.endswith("的") and _is_surname(n[1]):
        return Verdict(NameType.proper, 0.93, f"「姓{n[1]}的」指特定的人，语气轻蔑")

    # ── 描述性 + 人称量词：灰衣汉子、独臂老人 ──
    for noun in _PERSON_NOUN:
        if n.endswith(noun) and len(n) > len(noun):
            head = n[: -len(noun)]
            if any(c in _DESCRIPTIVE for c in head):
                return Verdict(
                    NameType.epithet, 0.9,
                    f"「{head}」是外形特征 + 「{noun}」—— 靠特征指认，换个人仍成立",
                )
            return Verdict(NameType.epithet, 0.75,
                           f"以人称量词「{noun}」结尾，多半是描述性称号")

    # ── 完整姓名：姓 + 1~2 字名 ──
    if 2 <= len(n) <= 4:
        if n[:2] in _CN_SURNAMES_2 and len(n) >= 3:
            return Verdict(NameType.proper, 0.93, f"复姓「{n[:2]}」+ 名")
        if _is_surname(n[0]) and len(n) >= 2:
            return Verdict(NameType.proper, 0.88, f"姓「{n[0]}」+ 名")

    return None


def brief_for_prompt() -> str:
    """把规则摘成提示词里的判据，让模型先对齐再判。

    规则与提示词共用同一份定义 —— 两边各写各的，
    模型会按一套标准判、系统按另一套复核，冲突时谁也说不清该信谁。
    """
    return (
        "【中文称呼的构词判据】按这些规律判 name_type：\n"
        "  老周／小林／阿强   亲近前缀 + 姓 → proper。换个姓就是另一个人，\n"
        "                     所以是专名。判成 epithet 会译出 Old Zhou 这种东西\n"
        "  张老／李公         姓 + 敬称后缀 → proper\n"
        "  姓沈的             指特定的人，语气轻蔑 → proper\n"
        "  掌柜／镖头／县令   职务词 → role（总镖头、副将这类前缀职务同样是 role）\n"
        "  灰衣汉子／独臂老人 特征 + 人称量词 → epithet，靠特征指认，换个人仍成立\n"
        "  那个人／几个汉子   指示或不定量词开头 → generic，不要建实体"
    )
