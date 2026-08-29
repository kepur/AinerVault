"""中文名物的构词规则 —— 类别判定不该靠模型猜。

中文名物的后缀承载类别信息，规律性极强：

    刀剑枪戟斧钺鞭锏  → weapon      腰刀、长剑、判官笔
    衣袍衫裙靴帽冠巾  → garment     蓑衣、直裰、乌纱帽
    楼馆店栈庄铺坊院  → place       客栈、镖局、酒楼
    门墙瓦梁柱阶檐窗  → architecture 柜台、门槛、飞檐
    车轿船舟马鞍辔    → vehicle     镖车、马车、乌篷船
    令尹丞尉史卿守牧  → office      县令、府尹、都尉

度量与货币更强 —— 它们是**数词 + 量词**的固定结构：
    三千里、半盏茶、一炷香、小半个时辰   → measure
    五两银子、几吊铜钱、一锭元宝         → currency

让模型判这些，换个模型就可能把「腰刀」判成 other，
而 category 决定了它在提示词里怎么呈现、在审计时怎么比对。

规则判不出的才交给模型。规则只管中文源 ——
别的语言各有各的构词法，硬套会把 doublet 判成 other。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import LexiconCategory as C

#: 后缀 → 类别。按后缀长度倒序匹配，长的优先
#: （「银子」比「子」准，「时辰」比「辰」准）。
_SUFFIX: dict[str, C] = {}


def _add(cat: C, *suffixes: str) -> None:
    for s in suffixes:
        _SUFFIX[s] = cat


_add(C.weapon, "刀", "剑", "枪", "戟", "斧", "钺", "钩", "叉", "鞭", "锏",
     "锤", "棍", "棒", "矛", "弓", "弩", "箭", "镖", "刺", "匕首", "长枪")
_add(C.garment, "衣", "袍", "衫", "裙", "裤", "靴", "鞋", "帽", "冠", "巾",
     "带", "裘", "氅", "袄", "褂", "蓑衣", "直裰", "襦")
_add(C.place, "楼", "馆", "店", "栈", "庄", "铺", "坊", "院", "府", "衙",
     "寺", "庙", "观", "塔", "亭", "台", "堂", "阁", "轩", "斋",
     "局", "行", "号", "客栈", "驿站", "镖局")
_add(C.architecture, "门", "墙", "瓦", "梁", "柱", "阶", "檐", "窗", "榻",
     "炕", "灶", "井", "廊", "槛", "柜台", "屋顶")
_add(C.vehicle, "车", "轿", "船", "舟", "筏", "鞍", "辔", "镫", "马车", "驿马")
_add(C.office, "令", "尹", "丞", "尉", "史", "卿", "守", "牧", "监", "使",
     "总管", "捕头", "捕快", "衙役", "差役")
_add(C.food, "酒", "茶", "饭", "菜", "饼", "面", "粥", "汤", "糕", "点心", "干粮")
_add(C.currency, "银", "钱", "元宝", "银子", "银两", "铜钱", "纹银", "碎银",
     "通宝", "银票", "会票")
_add(C.honorific, "公子", "少爷", "娘子", "相公", "官人", "大人", "老爷",
     "夫人", "太太", "姑娘", "客官")

#: 数量 + 量词 = 度量。这是结构而非词表，覆盖面比枚举广得多。
_NUMERAL = "零一二三四五六七八九十百千万两半几数多整小０-９0-9"
_MEASURE_UNIT = (
    "里", "丈", "尺", "寸", "分", "斤", "两", "钱", "石", "斗", "升",
    "亩", "顷", "匹", "端", "刻", "时辰", "盏茶", "炷香", "更", "旬",
    "日", "月", "年", "步", "跬",
)
_MEASURE_RE = re.compile(
    rf"^[{_NUMERAL}个]+\s*(?:{'|'.join(sorted(_MEASURE_UNIT, key=len, reverse=True))})"
)
#: 数量 + 货币单位
_CURRENCY_UNIT = ("两银子", "两银", "吊钱", "贯钱", "文钱", "锭银", "锭金")
_CURRENCY_RE = re.compile(
    rf"^[{_NUMERAL}个]+\s*(?:{'|'.join(sorted(_CURRENCY_UNIT, key=len, reverse=True))})"
)

_HAN = re.compile(r"[一-鿿]")


@dataclass(frozen=True)
class CatVerdict:
    category: C
    confidence: float
    reason: str

    @property
    def decisive(self) -> bool:
        """够硬到可以推翻模型。

        结构性判据（数量+量词）比后缀更可靠 —— 后缀会撞车
        （「银」既能是 currency 也能是材质），结构不会。
        """
        return self.confidence >= 0.9


def classify(term: str) -> CatVerdict | None:
    """按构词法判名物类别。判不出返回 None，交给模型。"""
    t = (term or "").strip()
    if not t or not _HAN.search(t):
        return None

    # ── 结构：数量 + 货币单位 ──（先于度量，因为「两银子」也含量词「两」）
    if _CURRENCY_RE.match(t):
        return CatVerdict(C.currency, 0.95, "数量 + 货币单位，是钱不是长度")

    # ── 结构：数量 + 量词 ──
    if _MEASURE_RE.match(t):
        return CatVerdict(C.measure, 0.95,
                          "数量 + 量词，是度量而非实物 —— "
                          "「半盏茶」说的是时间，不是一杯茶")

    # ── 后缀：长的优先 ──
    for suffix in sorted(_SUFFIX, key=len, reverse=True):
        if t.endswith(suffix) and len(t) >= len(suffix):
            # 只有**单字后缀且整词就是那一个字**时才降级 ——
            # 「刀」孤零零一个字可能是泛指，而「蓑衣」「客栈」「铜钱」
            # 整词等于后缀恰恰说明它就是那个完整的词，该给高置信。
            bare_single = len(t) == 1 and len(suffix) == 1
            conf = 0.75 if bare_single else 0.9
            return CatVerdict(_SUFFIX[suffix], conf,
                              f"以「{suffix}」结尾，属 {_SUFFIX[suffix].value}")
    return None


def brief_for_prompt() -> str:
    """判据摘要，写进挖掘提示词让模型先对齐。

    与规则共用一套定义 —— 两边各写各的，模型按一套判、系统按另一套复核，
    冲突时谁也说不清该信谁。
    """
    return (
        "【中文名物的构词判据】category 按这些规律定：\n"
        "  刀剑枪戟斧钺鞭锏 结尾 → weapon　　衣袍衫裙靴帽冠巾 结尾 → garment\n"
        "  楼馆店栈庄铺坊院 结尾 → place　　　门墙瓦梁柱阶檐窗 结尾 → architecture\n"
        "  车轿船舟鞍辔 结尾 → vehicle　　　　令尹丞尉史卿守牧 结尾 → office\n"
        "  数量 + 量词（三千里／半盏茶／一炷香／小半个时辰）→ measure\n"
        "    注意这类**说的是度量不是实物**：「半盏茶」指一段时间，不是一杯茶，\n"
        "    译成目标语言的时间说法，不要译成喝茶\n"
        "  数量 + 货币单位（五两银子／几吊铜钱）→ currency"
    )
