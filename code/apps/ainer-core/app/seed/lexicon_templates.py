"""内置名物词表模板 —— 合并自两条并行开发线。

三个原则：
1. canonical_key 是上位语义，跨世界观稳定，可跨小说复用
2. forbidden_targets 记「绝不能这么译」—— 闸二反向校验的依据
3. 时代必须对：昭和(1926–1989)是现代日本，客栈是「旅館」不是「旅籠」；
   「旅籠」属于江户。era 轴错了，整本书的名物就全错。

译法分歧已逐条裁决，理由写在各条 rationale 里，可复核。
"""
from __future__ import annotations

from typing import Any

TEMPLATES: list[dict[str, Any]] = [
    {
        "pair_code": "cn_ancient__jp_showa",
        "display_name": "中国古代 → 日本昭和",
        "source_profile_code": "cn_tang_classical",
        "target_profile_code": "jp_showa",
        "description": "把古典中国的名物、职官、称谓映射到昭和日本的物质生活层。注意昭和是近现代：客栈对应旅館而非江户的旅籠。",
        "entries": [
            {
                "canonical_key": "currency.gold_ingot",
                "category": "currency",
                "source_term": "金锭",
                "source_aliases": [],
                "target_term": "金塊",
                "target_reading": "きんかい",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "currency.copper_coin",
                "category": "currency",
                "source_term": "铜钱",
                "source_aliases": [
                    "制钱",
                    "文钱",
                    "铜板"
                ],
                "target_term": "銭",
                "target_reading": "せん",
                "forbidden_targets": [
                    "copper coin",
                    "penny",
                    "文",
                    "铜钱"
                ],
                "rationale": "昭和货币单位为円/銭；「文」是江户及以前"
            },
            {
                "canonical_key": "currency.silver",
                "category": "currency",
                "source_term": "银两",
                "source_aliases": [
                    "两银子",
                    "纹银",
                    "银子"
                ],
                "target_term": "円",
                "target_reading": "えん",
                "forbidden_targets": [
                    "silver",
                    "silver tael",
                    "tael",
                    "両",
                    "银两"
                ],
                "rationale": "昭和已行円制；「両」属江户"
            },
            {
                "canonical_key": "custom.bow_salute",
                "category": "custom",
                "source_term": "作揖",
                "source_aliases": [],
                "target_term": "お辞儀",
                "target_reading": "おじぎ",
                "forbidden_targets": [
                    "cup one's hands",
                    "作揖"
                ],
                "rationale": None
            },
            {
                "canonical_key": "custom.matchmaker",
                "category": "custom",
                "source_term": "媒人",
                "source_aliases": [
                    "媒婆"
                ],
                "target_term": "仲人",
                "target_reading": "なこうど",
                "forbidden_targets": [
                    "matchmaker"
                ],
                "rationale": None
            },
            {
                "canonical_key": "abstract.filial_piety",
                "category": "custom",
                "source_term": "孝道",
                "source_aliases": [
                    "孝顺"
                ],
                "target_term": "親孝行",
                "target_reading": "おやこうこう",
                "forbidden_targets": [
                    "filial piety"
                ],
                "rationale": None
            },
            {
                "canonical_key": "abstract.jianghu",
                "category": "custom",
                "source_term": "江湖",
                "source_aliases": [],
                "target_term": "渡世",
                "target_reading": "とせい",
                "forbidden_targets": [
                    "jianghu",
                    "rivers and lakes",
                    "underworld"
                ],
                "rationale": "江湖指脱离官府的流动社会；日语「渡世」最近，直译会完全失义"
            },
            {
                "canonical_key": "custom.kowtow",
                "category": "custom",
                "source_term": "磕头",
                "source_aliases": [],
                "target_term": "土下座",
                "target_reading": "どげざ",
                "forbidden_targets": [
                    "kowtow",
                    "磕头"
                ],
                "rationale": None
            },
            {
                "canonical_key": "abstract.face_honor",
                "category": "custom",
                "source_term": "面子",
                "source_aliases": [
                    "脸面"
                ],
                "target_term": "面目",
                "target_reading": "めんぼく",
                "forbidden_targets": [
                    "face"
                ],
                "rationale": None
            },
            {
                "canonical_key": "food.steamed_bun",
                "category": "food",
                "source_term": "包子",
                "source_aliases": [],
                "target_term": "饅頭",
                "target_reading": "まんじゅう",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "food.rice",
                "category": "food",
                "source_term": "米饭",
                "source_aliases": [],
                "target_term": "ご飯",
                "target_reading": "ごはん",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "food.congee",
                "category": "food",
                "source_term": "粥",
                "source_aliases": [
                    "稀饭"
                ],
                "target_term": "お粥",
                "target_reading": "おかゆ",
                "forbidden_targets": [
                    "porridge"
                ],
                "rationale": None
            },
            {
                "canonical_key": "food.pastry",
                "category": "food",
                "source_term": "糕点",
                "source_aliases": [
                    "点心"
                ],
                "target_term": "和菓子",
                "target_reading": "わがし",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "food.tea",
                "category": "food",
                "source_term": "茶",
                "source_aliases": [
                    "香茗"
                ],
                "target_term": "お茶",
                "target_reading": "おちゃ",
                "forbidden_targets": [
                    "tea"
                ],
                "rationale": None
            },
            {
                "canonical_key": "food.wine",
                "category": "food",
                "source_term": "酒",
                "source_aliases": [],
                "target_term": "酒",
                "target_reading": "さけ",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "food.wine_vessel",
                "category": "food",
                "source_term": "酒壶",
                "source_aliases": [],
                "target_term": "徳利",
                "target_reading": "とっくり",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "food.noodles",
                "category": "food",
                "source_term": "面条",
                "source_aliases": [
                    "面"
                ],
                "target_term": "蕎麦",
                "target_reading": "そば",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "food.steamed_bun",
                "category": "food",
                "source_term": "馒头",
                "source_aliases": [
                    "蒸饼"
                ],
                "target_term": "饅頭",
                "target_reading": "まんじゅう",
                "forbidden_targets": [
                    "bun"
                ],
                "rationale": "注意日语「饅頭」是甜点心，若原文指主食应改用「蒸しパン」并加注"
            },
            {
                "canonical_key": "food.rice_wine",
                "category": "food",
                "source_term": "黄酒",
                "source_aliases": [
                    "米酒",
                    "酒"
                ],
                "target_term": "日本酒",
                "target_reading": "にほんしゅ",
                "forbidden_targets": [
                    "wine",
                    "rice wine"
                ],
                "rationale": None
            },
            {
                "canonical_key": "garment.hairpin",
                "category": "garment",
                "source_term": "发簪",
                "source_aliases": [
                    "簪子"
                ],
                "target_term": "簪",
                "target_reading": "かんざし",
                "forbidden_targets": [
                    "hairpin"
                ],
                "rationale": None
            },
            {
                "canonical_key": "garment.cloak",
                "category": "garment",
                "source_term": "斗篷",
                "source_aliases": [],
                "target_term": "外套",
                "target_reading": "がいとう",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.pendant",
                "category": "garment",
                "source_term": "玉佩",
                "source_aliases": [],
                "target_term": "根付",
                "target_reading": "ねつけ",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.shoes",
                "category": "garment",
                "source_term": "绣鞋",
                "source_aliases": [
                    "布鞋"
                ],
                "target_term": "草履",
                "target_reading": "ぞうり",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.skirt",
                "category": "garment",
                "source_term": "罗裙",
                "source_aliases": [
                    "裙子"
                ],
                "target_term": "袴",
                "target_reading": "はかま",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.sash",
                "category": "garment",
                "source_term": "腰带",
                "source_aliases": [],
                "target_term": "帯",
                "target_reading": "おび",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.straw_cloak",
                "category": "garment",
                "source_term": "蓑衣",
                "source_aliases": [],
                "target_term": "蓑",
                "target_reading": "みの",
                "forbidden_targets": [
                    "raincoat"
                ],
                "rationale": None
            },
            {
                "canonical_key": "garment.long_robe",
                "category": "garment",
                "source_term": "长衫",
                "source_aliases": [
                    "长袍"
                ],
                "target_term": "着物",
                "target_reading": "きもの",
                "forbidden_targets": [
                    "robe",
                    "长衫",
                    "汉服"
                ],
                "rationale": None
            },
            {
                "canonical_key": "garment.robe",
                "category": "garment",
                "source_term": "长袍",
                "source_aliases": [
                    "袍子",
                    "长衫"
                ],
                "target_term": "着物",
                "target_reading": "きもの",
                "forbidden_targets": [
                    "kimono",
                    "robe"
                ],
                "rationale": None
            },
            {
                "canonical_key": "garment.jacket",
                "category": "garment",
                "source_term": "马褂",
                "source_aliases": [
                    "外褂"
                ],
                "target_term": "羽織",
                "target_reading": "はおり",
                "forbidden_targets": [
                    "jacket"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.young_sir",
                "category": "honorific",
                "source_term": "公子",
                "source_aliases": [],
                "target_term": "若様",
                "target_reading": "わかさま",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "honorific.humble_self",
                "category": "honorific",
                "source_term": "在下",
                "source_aliases": [
                    "鄙人",
                    "小人"
                ],
                "target_term": "私",
                "target_reading": "わたくし",
                "forbidden_targets": [
                    "this humble one",
                    "在下"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.madam",
                "category": "honorific",
                "source_term": "夫人",
                "source_aliases": [],
                "target_term": "奥様",
                "target_reading": "おくさま",
                "forbidden_targets": [
                    "madam",
                    "夫人"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.maiden",
                "category": "honorific",
                "source_term": "姑娘",
                "source_aliases": [],
                "target_term": "お嬢さん",
                "target_reading": "おじょうさん",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "honorific.wife",
                "category": "honorific",
                "source_term": "娘子",
                "source_aliases": [
                    "浑家"
                ],
                "target_term": "家内",
                "target_reading": "かない",
                "forbidden_targets": [
                    "wife",
                    "娘子"
                ],
                "rationale": "对外称自己妻子。当面称呼应改用「お前」或名字"
            },
            {
                "canonical_key": "honorific.husband",
                "category": "honorific",
                "source_term": "官人",
                "source_aliases": [
                    "相公"
                ],
                "target_term": "旦那",
                "target_reading": "だんな",
                "forbidden_targets": [
                    "husband",
                    "官人"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.young_lady",
                "category": "honorific",
                "source_term": "小姐",
                "source_aliases": [],
                "target_term": "お嬢様",
                "target_reading": "おじょうさま",
                "forbidden_targets": [
                    "miss",
                    "小姐"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.young_master",
                "category": "honorific",
                "source_term": "少爷",
                "source_aliases": [],
                "target_term": "若旦那",
                "target_reading": "わかだんな",
                "forbidden_targets": [
                    "young master",
                    "少爷"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.shopkeeper",
                "category": "honorific",
                "source_term": "掌柜",
                "source_aliases": [
                    "东家",
                    "店家"
                ],
                "target_term": "主人",
                "target_reading": "しゅじん",
                "forbidden_targets": [
                    "innkeeper",
                    "shopkeeper",
                    "掌柜",
                    "番頭"
                ],
                "rationale": "番頭是雇员领班，掌柜多为业主，昭和用主人/店主"
            },
            {
                "canonical_key": "honorific.master_male",
                "category": "honorific",
                "source_term": "老爷",
                "source_aliases": [],
                "target_term": "旦那様",
                "target_reading": "だんなさま",
                "forbidden_targets": [
                    "master",
                    "老爷"
                ],
                "rationale": None
            },
            {
                "canonical_key": "measure.chi",
                "category": "measure",
                "source_term": "尺",
                "source_aliases": [],
                "target_term": "尺",
                "target_reading": "しゃく",
                "forbidden_targets": [],
                "rationale": "日语「尺」约 30.3cm，与中文尺 33cm 接近，可直接沿用"
            },
            {
                "canonical_key": "measure.jin",
                "category": "measure",
                "source_term": "斤",
                "source_aliases": [],
                "target_term": "貫",
                "target_reading": "かん",
                "forbidden_targets": [
                    "斤"
                ],
                "rationale": "昭和法定尺贯法沿用至 1959 年；日语「斤」仅用于面包计量"
            },
            {
                "canonical_key": "measure.shichen",
                "category": "measure",
                "source_term": "时辰",
                "source_aliases": [],
                "target_term": "刻",
                "target_reading": "とき",
                "forbidden_targets": [
                    "hour",
                    "时辰"
                ],
                "rationale": "昭和口语可按语境改用「時間」"
            },
            {
                "canonical_key": "measure.li",
                "category": "measure",
                "source_term": "里",
                "source_aliases": [],
                "target_term": "キロ",
                "target_reading": "り",
                "forbidden_targets": [
                    "里"
                ],
                "rationale": "日语「里」约 3.93km，中文「里」约 0.5km，相差近八倍。直接沿用会让读者对距离的感知错八倍，必须换算为公制"
            },
            {
                "canonical_key": "office.courtroom",
                "category": "office",
                "source_term": "公堂",
                "source_aliases": [
                    "大堂"
                ],
                "target_term": "法廷",
                "target_reading": "ほうてい",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "office.magistrate",
                "category": "office",
                "source_term": "县令",
                "source_aliases": [
                    "县太爷",
                    "知县"
                ],
                "target_term": "町長",
                "target_reading": "ちょうちょう",
                "forbidden_targets": [
                    "bailiff",
                    "magistrate",
                    "代官",
                    "县令"
                ],
                "rationale": "町村制下的地方首长。若原文强调司法权，可用「署長」"
            },
            {
                "canonical_key": "office.jail",
                "category": "office",
                "source_term": "大牢",
                "source_aliases": [
                    "监牢",
                    "牢房"
                ],
                "target_term": "留置場",
                "target_reading": "りゅうちじょう",
                "forbidden_targets": [
                    "jail",
                    "大牢"
                ],
                "rationale": None
            },
            {
                "canonical_key": "office.seal",
                "category": "office",
                "source_term": "官印",
                "source_aliases": [
                    "官防"
                ],
                "target_term": "印鑑",
                "target_reading": "いんかん",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "office.clerk",
                "category": "office",
                "source_term": "师爷",
                "source_aliases": [
                    "幕僚",
                    "文书"
                ],
                "target_term": "書記",
                "target_reading": "しょき",
                "forbidden_targets": [
                    "scribe"
                ],
                "rationale": None
            },
            {
                "canonical_key": "office.constable",
                "category": "office",
                "source_term": "捕快",
                "source_aliases": [
                    "差役",
                    "衙役"
                ],
                "target_term": "巡査",
                "target_reading": "じゅんさ",
                "forbidden_targets": [
                    "constable",
                    "同心",
                    "岡っ引き",
                    "捕快"
                ],
                "rationale": "昭和为近代警察制；同心岡っ引き属江户"
            },
            {
                "canonical_key": "office.complaint",
                "category": "office",
                "source_term": "状纸",
                "source_aliases": [
                    "诉状"
                ],
                "target_term": "訴状",
                "target_reading": "そじょう",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "office.prefect",
                "category": "office",
                "source_term": "知府",
                "source_aliases": [
                    "太守"
                ],
                "target_term": "県知事",
                "target_reading": "けんちじ",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "office.government_office",
                "category": "office",
                "source_term": "衙门",
                "source_aliases": [
                    "县衙",
                    "官府",
                    "官衙"
                ],
                "target_term": "役所",
                "target_reading": "やくしょ",
                "forbidden_targets": [
                    "magistrate",
                    "magistrate's office",
                    "yamen",
                    "奉行所",
                    "衙门"
                ],
                "rationale": "昭和的地方行政机关。涉及缉捕的场景可用「警察署」"
            },
            {
                "canonical_key": "office.village_head",
                "category": "office",
                "source_term": "里正",
                "source_aliases": [
                    "保长"
                ],
                "target_term": "村長",
                "target_reading": "そんちょう",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "place.school",
                "category": "place",
                "source_term": "书院",
                "source_aliases": [
                    "学堂",
                    "私塾"
                ],
                "target_term": "塾",
                "target_reading": "じゅく",
                "forbidden_targets": [
                    "academy",
                    "书院",
                    "寺子屋"
                ],
                "rationale": "书院是私学，昭和对应「塾」；「学校」指近代公立学制，语感不符"
            },
            {
                "canonical_key": "place.side_room",
                "category": "place",
                "source_term": "厢房",
                "source_aliases": [
                    "偏房"
                ],
                "target_term": "離れ",
                "target_reading": "はなれ",
                "forbidden_targets": [
                    "side room"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.courtyard",
                "category": "place",
                "source_term": "后院",
                "source_aliases": [
                    "内院",
                    "庭院"
                ],
                "target_term": "中庭",
                "target_reading": "なかにわ",
                "forbidden_targets": [
                    "courtyard"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.city_gate",
                "category": "place",
                "source_term": "城门",
                "source_aliases": [
                    "关门"
                ],
                "target_term": "門",
                "target_reading": "もん",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "place.residence",
                "category": "place",
                "source_term": "宅院",
                "source_aliases": [
                    "大宅",
                    "宅第",
                    "府上",
                    "府邸"
                ],
                "target_term": "屋敷",
                "target_reading": "やしき",
                "forbidden_targets": [
                    "mansion",
                    "宅院"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.lodging_venue",
                "category": "place",
                "source_term": "客栈",
                "source_aliases": [
                    "客舍",
                    "旅店",
                    "逆旅"
                ],
                "target_term": "旅館",
                "target_reading": "りょかん",
                "forbidden_targets": [
                    "hotel",
                    "inn",
                    "客栈",
                    "旅籠"
                ],
                "rationale": "昭和期的和式住宿设施。江户期的「旅籠」属于更早的时代层，不可混用"
            },
            {
                "canonical_key": "place.temple",
                "category": "place",
                "source_term": "寺庙",
                "source_aliases": [
                    "庙宇",
                    "佛寺"
                ],
                "target_term": "寺",
                "target_reading": "てら",
                "forbidden_targets": [
                    "temple"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.temple",
                "category": "place",
                "source_term": "庙宇",
                "source_aliases": [
                    "寺庙",
                    "庙",
                    "佛寺"
                ],
                "target_term": "神社",
                "target_reading": "じんじゃ",
                "forbidden_targets": [
                    "temple",
                    "庙宇"
                ],
                "rationale": "佛寺场景可改用「寺（てら）」，按原文宗教属性择一"
            },
            {
                "canonical_key": "place.pawnshop",
                "category": "place",
                "source_term": "当铺",
                "source_aliases": [
                    "典当行"
                ],
                "target_term": "質屋",
                "target_reading": "しちや",
                "forbidden_targets": [
                    "pawnshop"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.wharf",
                "category": "place",
                "source_term": "码头",
                "source_aliases": [
                    "渡口",
                    "埠头"
                ],
                "target_term": "波止場",
                "target_reading": "はとば",
                "forbidden_targets": [
                    "wharf",
                    "码头"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.teahouse",
                "category": "place",
                "source_term": "茶馆",
                "source_aliases": [
                    "茶坊",
                    "茶楼",
                    "茶肆"
                ],
                "target_term": "喫茶店",
                "target_reading": "きっさてん",
                "forbidden_targets": [
                    "cafe",
                    "teahouse",
                    "茶屋",
                    "茶馆"
                ],
                "rationale": "昭和的市井闲谈场所是喫茶店；茶屋偏江户"
            },
            {
                "canonical_key": "place.pharmacy",
                "category": "place",
                "source_term": "药铺",
                "source_aliases": [
                    "药堂",
                    "医馆"
                ],
                "target_term": "薬局",
                "target_reading": "やっきょく",
                "forbidden_targets": [
                    "薬種問屋",
                    "apothecary"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.shopping_street",
                "category": "place",
                "source_term": "街市",
                "source_aliases": [
                    "闹市"
                ],
                "target_term": "商店街",
                "target_reading": "しょうてんがい",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "place.dining_venue",
                "category": "place",
                "source_term": "酒楼",
                "source_aliases": [
                    "酒家",
                    "酒肆",
                    "饭庄"
                ],
                "target_term": "料亭",
                "target_reading": "りょうてい",
                "forbidden_targets": [
                    "bar",
                    "pub",
                    "restaurant",
                    "居酒屋",
                    "酒楼"
                ],
                "rationale": "酒楼兼具宴饮与身份场合，昭和对应料亭；居酒屋过于平民"
            },
            {
                "canonical_key": "place.market",
                "category": "place",
                "source_term": "集市",
                "source_aliases": [
                    "墟市",
                    "市集"
                ],
                "target_term": "市場",
                "target_reading": "いちば",
                "forbidden_targets": [
                    "market",
                    "集市"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.brothel",
                "category": "place",
                "source_term": "青楼",
                "source_aliases": [
                    "妓院",
                    "花楼"
                ],
                "target_term": "遊郭",
                "target_reading": "ゆうかく",
                "forbidden_targets": [
                    "brothel"
                ],
                "rationale": None
            },
            {
                "canonical_key": "prop.letter",
                "category": "prop",
                "source_term": "书信",
                "source_aliases": [
                    "家书",
                    "信笺"
                ],
                "target_term": "手紙",
                "target_reading": "てがみ",
                "forbidden_targets": [
                    "letter"
                ],
                "rationale": None
            },
            {
                "canonical_key": "prop.umbrella",
                "category": "prop",
                "source_term": "伞",
                "source_aliases": [],
                "target_term": "傘",
                "target_reading": "かさ",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "prop.seal",
                "category": "prop",
                "source_term": "印章",
                "source_aliases": [
                    "图章",
                    "私印"
                ],
                "target_term": "印鑑",
                "target_reading": "いんかん",
                "forbidden_targets": [
                    "seal",
                    "stamp"
                ],
                "rationale": None
            },
            {
                "canonical_key": "prop.folding_fan",
                "category": "prop",
                "source_term": "折扇",
                "source_aliases": [
                    "纸扇"
                ],
                "target_term": "扇子",
                "target_reading": "せんす",
                "forbidden_targets": [
                    "fan"
                ],
                "rationale": None
            },
            {
                "canonical_key": "prop.lantern",
                "category": "prop",
                "source_term": "灯笼",
                "source_aliases": [
                    "纸灯"
                ],
                "target_term": "提灯",
                "target_reading": "ちょうちん",
                "forbidden_targets": [
                    "lantern",
                    "灯笼"
                ],
                "rationale": None
            },
            {
                "canonical_key": "ritual.incense",
                "category": "ritual",
                "source_term": "上香",
                "source_aliases": [],
                "target_term": "焼香",
                "target_reading": "しょうこう",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "ritual.midautumn",
                "category": "ritual",
                "source_term": "中秋",
                "source_aliases": [],
                "target_term": "月見",
                "target_reading": "つきみ",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "custom.kowtow",
                "category": "ritual",
                "source_term": "叩首",
                "source_aliases": [
                    "磕头",
                    "跪拜"
                ],
                "target_term": "土下座",
                "target_reading": "どげざ",
                "forbidden_targets": [
                    "kowtow",
                    "bow"
                ],
                "rationale": None
            },
            {
                "canonical_key": "ritual.wedding",
                "category": "ritual",
                "source_term": "拜堂",
                "source_aliases": [
                    "成亲"
                ],
                "target_term": "祝言",
                "target_reading": "しゅうげん",
                "forbidden_targets": [
                    "wedding ceremony"
                ],
                "rationale": None
            },
            {
                "canonical_key": "ritual.newyear",
                "category": "ritual",
                "source_term": "春节",
                "source_aliases": [
                    "过年"
                ],
                "target_term": "正月",
                "target_reading": "しょうがつ",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "role.landlord",
                "category": "title",
                "source_term": "地主",
                "source_aliases": [
                    "乡绅"
                ],
                "target_term": "地主",
                "target_reading": "じぬし",
                "forbidden_targets": [
                    "landlord"
                ],
                "rationale": None
            },
            {
                "canonical_key": "role.waiter",
                "category": "title",
                "source_term": "小二",
                "source_aliases": [
                    "店小二",
                    "伙计"
                ],
                "target_term": "店員",
                "target_reading": "てんいん",
                "forbidden_targets": [
                    "丁稚",
                    "女中",
                    "waiter"
                ],
                "rationale": None
            },
            {
                "canonical_key": "role.physician",
                "category": "title",
                "source_term": "郎中",
                "source_aliases": [
                    "大夫",
                    "医师"
                ],
                "target_term": "医者",
                "target_reading": "いしゃ",
                "forbidden_targets": [
                    "doctor"
                ],
                "rationale": None
            },
            {
                "canonical_key": "role.escort",
                "category": "title",
                "source_term": "镖师",
                "source_aliases": [
                    "镖头"
                ],
                "target_term": "護衛",
                "target_reading": "ごえい",
                "forbidden_targets": [
                    "bodyguard",
                    "用心棒"
                ],
                "rationale": None
            },
            {
                "canonical_key": "vehicle.boat",
                "category": "vehicle",
                "source_term": "船",
                "source_aliases": [],
                "target_term": "船",
                "target_reading": "ふね",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "vehicle.palanquin",
                "category": "vehicle",
                "source_term": "轿子",
                "source_aliases": [
                    "软轿"
                ],
                "target_term": "駕籠",
                "target_reading": "かご",
                "forbidden_targets": [
                    "palanquin",
                    "轿子"
                ],
                "rationale": "昭和已罕见，若出现应作为旧时代残留，保留駕籠并加注"
            },
            {
                "canonical_key": "vehicle.carriage",
                "category": "vehicle",
                "source_term": "马车",
                "source_aliases": [
                    "车马"
                ],
                "target_term": "人力車",
                "target_reading": "じんりきしゃ",
                "forbidden_targets": [
                    "carriage",
                    "駕籠",
                    "马车"
                ],
                "rationale": "昭和初期的市井交通。若为货运场景可用「荷車（にぐるま）」"
            },
            {
                "canonical_key": "weapon.sword",
                "category": "weapon",
                "source_term": "剑",
                "source_aliases": [],
                "target_term": "刀",
                "target_reading": "かたな",
                "forbidden_targets": [
                    "sword",
                    "剑"
                ],
                "rationale": "日本刀形制。直刃场景可用「直刀（ちょくとう）」"
            },
            {
                "canonical_key": "weapon.bow",
                "category": "weapon",
                "source_term": "弓箭",
                "source_aliases": [],
                "target_term": "弓矢",
                "target_reading": "ゆみや",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "weapon.saber",
                "category": "weapon",
                "source_term": "腰刀",
                "source_aliases": [
                    "朴刀"
                ],
                "target_term": "短刀",
                "target_reading": "たんとう",
                "forbidden_targets": [
                    "saber"
                ],
                "rationale": None
            },
            {
                "canonical_key": "weapon.long_blade",
                "category": "weapon",
                "source_term": "长刀",
                "source_aliases": [],
                "target_term": "太刀",
                "target_reading": "たち",
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "weapon.straight_sword",
                "category": "weapon",
                "source_term": "长剑",
                "source_aliases": [
                    "宝剑",
                    "剑"
                ],
                "target_term": "刀",
                "target_reading": "かたな",
                "forbidden_targets": [
                    "sword",
                    "katana"
                ],
                "rationale": "写作时用汉字「刀」，避免罗马字 katana 破坏语言纯度"
            }
        ]
    },
    {
        "pair_code": "cn_ancient__eu_medieval",
        "display_name": "中国古代 → 欧洲中世纪盛期",
        "source_profile_code": "cn_tang_classical",
        "target_profile_code": "eu_medieval_high",
        "description": "映射到 1000–1300 年的欧洲。无对应物的（茶、米饭）回退到上位语义，而不是直译成时代外的词。",
        "entries": [
            {
                "canonical_key": "currency.gold_ingot",
                "category": "currency",
                "source_term": "金锭",
                "source_aliases": [],
                "target_term": "gold florin",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "currency.copper_coin",
                "category": "currency",
                "source_term": "铜钱",
                "source_aliases": [
                    "制钱",
                    "文钱",
                    "铜板"
                ],
                "target_term": "penny",
                "target_reading": None,
                "forbidden_targets": [
                    "cent",
                    "copper coin",
                    "dollar",
                    "yuan",
                    "铜钱"
                ],
                "rationale": None
            },
            {
                "canonical_key": "currency.silver",
                "category": "currency",
                "source_term": "银两",
                "source_aliases": [
                    "纹银",
                    "银子"
                ],
                "target_term": "silver mark",
                "target_reading": None,
                "forbidden_targets": [
                    "coin",
                    "dollar",
                    "silver tael",
                    "tael",
                    "银两"
                ],
                "rationale": None
            },
            {
                "canonical_key": "custom.bow_salute",
                "category": "custom",
                "source_term": "作揖",
                "source_aliases": [],
                "target_term": "bow",
                "target_reading": None,
                "forbidden_targets": [
                    "cup one's hands"
                ],
                "rationale": None
            },
            {
                "canonical_key": "custom.matchmaker",
                "category": "custom",
                "source_term": "媒人",
                "source_aliases": [
                    "媒婆"
                ],
                "target_term": "marriage broker",
                "target_reading": None,
                "forbidden_targets": [
                    "matchmaker"
                ],
                "rationale": None
            },
            {
                "canonical_key": "abstract.filial_piety",
                "category": "custom",
                "source_term": "孝道",
                "source_aliases": [
                    "孝顺"
                ],
                "target_term": "duty to one's father",
                "target_reading": None,
                "forbidden_targets": [
                    "filial piety"
                ],
                "rationale": None
            },
            {
                "canonical_key": "abstract.jianghu",
                "category": "custom",
                "source_term": "江湖",
                "source_aliases": [],
                "target_term": "the road",
                "target_reading": None,
                "forbidden_targets": [
                    "jianghu",
                    "rivers and lakes",
                    "underworld"
                ],
                "rationale": "以 the road / men of the road 表达游走于王法之外的流动世界"
            },
            {
                "canonical_key": "custom.kowtow",
                "category": "custom",
                "source_term": "磕头",
                "source_aliases": [],
                "target_term": "kneel",
                "target_reading": None,
                "forbidden_targets": [
                    "kowtow",
                    "磕头"
                ],
                "rationale": None
            },
            {
                "canonical_key": "abstract.face_honor",
                "category": "custom",
                "source_term": "面子",
                "source_aliases": [
                    "脸面"
                ],
                "target_term": "honour",
                "target_reading": None,
                "forbidden_targets": [
                    "face"
                ],
                "rationale": None
            },
            {
                "canonical_key": "food.rice",
                "category": "food",
                "source_term": "米饭",
                "source_aliases": [],
                "target_term": "pottage",
                "target_reading": None,
                "forbidden_targets": [
                    "rice"
                ],
                "rationale": "中世纪欧洲主食是麦粥与面包，直译 rice 会破坏时代感"
            },
            {
                "canonical_key": "food.congee",
                "category": "food",
                "source_term": "粥",
                "source_aliases": [
                    "稀饭"
                ],
                "target_term": "pottage",
                "target_reading": None,
                "forbidden_targets": [
                    "porridge",
                    "congee"
                ],
                "rationale": None
            },
            {
                "canonical_key": "food.pastry",
                "category": "food",
                "source_term": "糕点",
                "source_aliases": [
                    "点心"
                ],
                "target_term": "honey cake",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "food.tea",
                "category": "food",
                "source_term": "茶",
                "source_aliases": [
                    "香茗"
                ],
                "target_term": "herbal infusion",
                "target_reading": None,
                "forbidden_targets": [
                    "coffee",
                    "tea"
                ],
                "rationale": "茶未传入欧洲；draught 带药水意味，infusion 更中性"
            },
            {
                "canonical_key": "food.wine",
                "category": "food",
                "source_term": "酒",
                "source_aliases": [],
                "target_term": "ale",
                "target_reading": None,
                "forbidden_targets": [
                    "liquor"
                ],
                "rationale": "平民场合用 ale，贵族场合用 wine"
            },
            {
                "canonical_key": "food.noodles",
                "category": "food",
                "source_term": "面条",
                "source_aliases": [
                    "面"
                ],
                "target_term": "bread",
                "target_reading": None,
                "forbidden_targets": [
                    "noodles"
                ],
                "rationale": None
            },
            {
                "canonical_key": "food.steamed_bun",
                "category": "food",
                "source_term": "馒头",
                "source_aliases": [
                    "蒸饼"
                ],
                "target_term": "maslin loaf",
                "target_reading": None,
                "forbidden_targets": [
                    "bun",
                    "bread roll"
                ],
                "rationale": "中世纪平民主食为混麦粗面包，非蒸制"
            },
            {
                "canonical_key": "food.rice_wine",
                "category": "food",
                "source_term": "黄酒",
                "source_aliases": [
                    "米酒",
                    "酒"
                ],
                "target_term": "ale",
                "target_reading": None,
                "forbidden_targets": [
                    "rice wine",
                    "beer",
                    "sake"
                ],
                "rationale": None
            },
            {
                "canonical_key": "garment.hairpin",
                "category": "garment",
                "source_term": "发簪",
                "source_aliases": [
                    "簪子"
                ],
                "target_term": "hairpin",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.cloak",
                "category": "garment",
                "source_term": "斗篷",
                "source_aliases": [],
                "target_term": "mantle",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.shoes",
                "category": "garment",
                "source_term": "绣鞋",
                "source_aliases": [
                    "布鞋"
                ],
                "target_term": "leather shoes",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.skirt",
                "category": "garment",
                "source_term": "罗裙",
                "source_aliases": [
                    "裙子"
                ],
                "target_term": "kirtle",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.sash",
                "category": "garment",
                "source_term": "腰带",
                "source_aliases": [],
                "target_term": "girdle",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.straw_cloak",
                "category": "garment",
                "source_term": "蓑衣",
                "source_aliases": [],
                "target_term": "oiled cloak",
                "target_reading": None,
                "forbidden_targets": [
                    "raincoat"
                ],
                "rationale": None
            },
            {
                "canonical_key": "garment.long_robe",
                "category": "garment",
                "source_term": "长衫",
                "source_aliases": [
                    "长袍"
                ],
                "target_term": "tunic",
                "target_reading": None,
                "forbidden_targets": [
                    "robe",
                    "长衫"
                ],
                "rationale": None
            },
            {
                "canonical_key": "garment.robe",
                "category": "garment",
                "source_term": "长袍",
                "source_aliases": [
                    "袍子",
                    "长衫"
                ],
                "target_term": "tunic",
                "target_reading": None,
                "forbidden_targets": [
                    "kimono",
                    "robe",
                    "dress"
                ],
                "rationale": None
            },
            {
                "canonical_key": "garment.jacket",
                "category": "garment",
                "source_term": "马褂",
                "source_aliases": [
                    "外褂"
                ],
                "target_term": "surcoat",
                "target_reading": None,
                "forbidden_targets": [
                    "coat",
                    "jacket"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.young_sir",
                "category": "honorific",
                "source_term": "公子",
                "source_aliases": [],
                "target_term": "young sir",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "honorific.humble_self",
                "category": "honorific",
                "source_term": "在下",
                "source_aliases": [
                    "鄙人",
                    "小人"
                ],
                "target_term": "this humble one",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "honorific.madam",
                "category": "honorific",
                "source_term": "夫人",
                "source_aliases": [],
                "target_term": "my lady",
                "target_reading": None,
                "forbidden_targets": [
                    "Mrs.",
                    "夫人"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.maiden",
                "category": "honorific",
                "source_term": "姑娘",
                "source_aliases": [],
                "target_term": "maiden",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "honorific.wife",
                "category": "honorific",
                "source_term": "娘子",
                "source_aliases": [
                    "浑家"
                ],
                "target_term": "my wife",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "honorific.husband",
                "category": "honorific",
                "source_term": "官人",
                "source_aliases": [
                    "相公"
                ],
                "target_term": "my lord",
                "target_reading": None,
                "forbidden_targets": [
                    "husband",
                    "官人"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.young_lady",
                "category": "honorific",
                "source_term": "小姐",
                "source_aliases": [],
                "target_term": "mistress",
                "target_reading": None,
                "forbidden_targets": [
                    "Miss",
                    "小姐"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.young_master",
                "category": "honorific",
                "source_term": "少爷",
                "source_aliases": [],
                "target_term": "young master",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "honorific.shopkeeper",
                "category": "honorific",
                "source_term": "掌柜",
                "source_aliases": [
                    "店家"
                ],
                "target_term": "innkeeper",
                "target_reading": None,
                "forbidden_targets": [
                    "boss",
                    "manager"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.master_male",
                "category": "honorific",
                "source_term": "老爷",
                "source_aliases": [],
                "target_term": "master",
                "target_reading": None,
                "forbidden_targets": [
                    "Mr.",
                    "老爷"
                ],
                "rationale": None
            },
            {
                "canonical_key": "measure.chi",
                "category": "measure",
                "source_term": "尺",
                "source_aliases": [],
                "target_term": "foot",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "measure.jin",
                "category": "measure",
                "source_term": "斤",
                "source_aliases": [],
                "target_term": "pound",
                "target_reading": None,
                "forbidden_targets": [
                    "jin",
                    "kilo"
                ],
                "rationale": None
            },
            {
                "canonical_key": "measure.shichen",
                "category": "measure",
                "source_term": "时辰",
                "source_aliases": [],
                "target_term": "hour",
                "target_reading": None,
                "forbidden_targets": [
                    "时辰"
                ],
                "rationale": "可用教会时辰 matins / vespers 增强时代感"
            },
            {
                "canonical_key": "measure.li",
                "category": "measure",
                "source_term": "里",
                "source_aliases": [],
                "target_term": "league",
                "target_reading": None,
                "forbidden_targets": [
                    "kilometre",
                    "li",
                    "mile",
                    "里"
                ],
                "rationale": None
            },
            {
                "canonical_key": "office.courtroom",
                "category": "office",
                "source_term": "公堂",
                "source_aliases": [
                    "大堂"
                ],
                "target_term": "manor court",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "office.magistrate",
                "category": "office",
                "source_term": "县令",
                "source_aliases": [
                    "县太爷",
                    "知县"
                ],
                "target_term": "bailiff",
                "target_reading": None,
                "forbidden_targets": [
                    "governor",
                    "magistrate",
                    "mayor",
                    "县令"
                ],
                "rationale": "领主治下的地方司法与行政代理人"
            },
            {
                "canonical_key": "office.jail",
                "category": "office",
                "source_term": "大牢",
                "source_aliases": [
                    "监牢",
                    "牢房"
                ],
                "target_term": "dungeon",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "office.seal",
                "category": "office",
                "source_term": "官印",
                "source_aliases": [
                    "官防"
                ],
                "target_term": "seal",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "office.clerk",
                "category": "office",
                "source_term": "师爷",
                "source_aliases": [
                    "幕僚"
                ],
                "target_term": "clerk",
                "target_reading": None,
                "forbidden_targets": [
                    "secretary"
                ],
                "rationale": None
            },
            {
                "canonical_key": "office.constable",
                "category": "office",
                "source_term": "捕快",
                "source_aliases": [
                    "差役",
                    "衙役"
                ],
                "target_term": "sergeant",
                "target_reading": None,
                "forbidden_targets": [
                    "constable",
                    "officer",
                    "police"
                ],
                "rationale": "constable 在中世纪指王室要职（Constable of England），用于差役会大幅拔高身份"
            },
            {
                "canonical_key": "office.prefect",
                "category": "office",
                "source_term": "知府",
                "source_aliases": [
                    "太守"
                ],
                "target_term": "sheriff",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": "郡级王权代表"
            },
            {
                "canonical_key": "office.government_office",
                "category": "office",
                "source_term": "衙门",
                "source_aliases": [
                    "县衙",
                    "官府",
                    "官衙"
                ],
                "target_term": "bailiff's court",
                "target_reading": None,
                "forbidden_targets": [
                    "city hall",
                    "police station",
                    "yamen",
                    "衙门"
                ],
                "rationale": None
            },
            {
                "canonical_key": "office.village_head",
                "category": "office",
                "source_term": "里正",
                "source_aliases": [
                    "保长"
                ],
                "target_term": "reeve",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": "庄园中由村民推举的管事"
            },
            {
                "canonical_key": "place.school",
                "category": "place",
                "source_term": "书院",
                "source_aliases": [
                    "学堂",
                    "私塾"
                ],
                "target_term": "abbey school",
                "target_reading": None,
                "forbidden_targets": [
                    "academy",
                    "university"
                ],
                "rationale": "盛期主流教育在修道院与座堂学校"
            },
            {
                "canonical_key": "place.courtyard",
                "category": "place",
                "source_term": "后院",
                "source_aliases": [
                    "内院"
                ],
                "target_term": "inner yard",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "place.city_gate",
                "category": "place",
                "source_term": "城门",
                "source_aliases": [],
                "target_term": "town gate",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "place.residence",
                "category": "place",
                "source_term": "宅院",
                "source_aliases": [
                    "宅第",
                    "府邸"
                ],
                "target_term": "manor house",
                "target_reading": None,
                "forbidden_targets": [
                    "manor",
                    "mansion",
                    "villa"
                ],
                "rationale": "manor 指含土地的庄园，manor house 才是宅子本身"
            },
            {
                "canonical_key": "place.lodging_venue",
                "category": "place",
                "source_term": "客栈",
                "source_aliases": [
                    "客舍",
                    "旅店"
                ],
                "target_term": "inn",
                "target_reading": None,
                "forbidden_targets": [
                    "hotel",
                    "motel",
                    "tavern",
                    "客栈"
                ],
                "rationale": "tavern 主营售酒，inn 才提供住宿；「客栈」是投宿处"
            },
            {
                "canonical_key": "place.temple",
                "category": "place",
                "source_term": "寺庙",
                "source_aliases": [
                    "佛寺"
                ],
                "target_term": "abbey",
                "target_reading": None,
                "forbidden_targets": [
                    "temple",
                    "pagoda"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.temple",
                "category": "place",
                "source_term": "庙宇",
                "source_aliases": [
                    "寺庙",
                    "庙"
                ],
                "target_term": "church",
                "target_reading": None,
                "forbidden_targets": [
                    "temple"
                ],
                "rationale": "大型场景可用 abbey / cathedral"
            },
            {
                "canonical_key": "place.wharf",
                "category": "place",
                "source_term": "码头",
                "source_aliases": [
                    "渡口",
                    "埠头"
                ],
                "target_term": "wharf",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "place.teahouse",
                "category": "place",
                "source_term": "茶馆",
                "source_aliases": [
                    "茶楼",
                    "茶肆"
                ],
                "target_term": "alehouse",
                "target_reading": None,
                "forbidden_targets": [
                    "cafe",
                    "café",
                    "coffeehouse",
                    "teahouse"
                ],
                "rationale": "茶与咖啡在中世纪欧洲尚未传入，须转为功能等价的 alehouse"
            },
            {
                "canonical_key": "place.pharmacy",
                "category": "place",
                "source_term": "药铺",
                "source_aliases": [
                    "医馆"
                ],
                "target_term": "apothecary",
                "target_reading": None,
                "forbidden_targets": [
                    "pharmacy",
                    "drugstore"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.dining_venue",
                "category": "place",
                "source_term": "酒楼",
                "source_aliases": [
                    "酒家",
                    "酒肆"
                ],
                "target_term": "alehouse",
                "target_reading": None,
                "forbidden_targets": [
                    "bar",
                    "pub",
                    "restaurant"
                ],
                "rationale": "pub 是近代词；中世纪售麦酒处为 alehouse"
            },
            {
                "canonical_key": "place.market",
                "category": "place",
                "source_term": "集市",
                "source_aliases": [
                    "市集"
                ],
                "target_term": "market square",
                "target_reading": None,
                "forbidden_targets": [
                    "mall"
                ],
                "rationale": None
            },
            {
                "canonical_key": "prop.letter",
                "category": "prop",
                "source_term": "书信",
                "source_aliases": [
                    "家书"
                ],
                "target_term": "letter",
                "target_reading": None,
                "forbidden_targets": [
                    "email",
                    "message"
                ],
                "rationale": None
            },
            {
                "canonical_key": "prop.seal",
                "category": "prop",
                "source_term": "印章",
                "source_aliases": [
                    "私印"
                ],
                "target_term": "signet",
                "target_reading": None,
                "forbidden_targets": [
                    "stamp",
                    "chop"
                ],
                "rationale": None
            },
            {
                "canonical_key": "prop.lantern",
                "category": "prop",
                "source_term": "灯笼",
                "source_aliases": [
                    "纸灯"
                ],
                "target_term": "horn lantern",
                "target_reading": None,
                "forbidden_targets": [
                    "flashlight",
                    "lamp",
                    "lantern"
                ],
                "rationale": "纸在欧洲稀缺，中世纪提灯多以兽角薄片透光"
            },
            {
                "canonical_key": "ritual.incense",
                "category": "ritual",
                "source_term": "上香",
                "source_aliases": [],
                "target_term": "light a candle",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": "以点烛替代焚香，符合基督教礼仪"
            },
            {
                "canonical_key": "custom.kowtow",
                "category": "ritual",
                "source_term": "叩首",
                "source_aliases": [
                    "磕头",
                    "跪拜"
                ],
                "target_term": "kneel and bow the head",
                "target_reading": None,
                "forbidden_targets": [
                    "kowtow",
                    "salute"
                ],
                "rationale": None
            },
            {
                "canonical_key": "ritual.wedding",
                "category": "ritual",
                "source_term": "拜堂",
                "source_aliases": [
                    "成亲"
                ],
                "target_term": "wedding at the church door",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "role.landlord",
                "category": "title",
                "source_term": "地主",
                "source_aliases": [
                    "乡绅"
                ],
                "target_term": "lord of the manor",
                "target_reading": None,
                "forbidden_targets": [
                    "landlord"
                ],
                "rationale": None
            },
            {
                "canonical_key": "role.waiter",
                "category": "title",
                "source_term": "小二",
                "source_aliases": [
                    "店小二",
                    "伙计"
                ],
                "target_term": "pot-boy",
                "target_reading": None,
                "forbidden_targets": [
                    "waiter",
                    "server"
                ],
                "rationale": None
            },
            {
                "canonical_key": "role.physician",
                "category": "title",
                "source_term": "郎中",
                "source_aliases": [
                    "大夫"
                ],
                "target_term": "leech",
                "target_reading": None,
                "forbidden_targets": [
                    "doctor",
                    "physician"
                ],
                "rationale": "leech 是中世纪对医者的常用称呼，比 doctor 更贴时代"
            },
            {
                "canonical_key": "role.escort",
                "category": "title",
                "source_term": "镖师",
                "source_aliases": [
                    "镖头"
                ],
                "target_term": "man-at-arms",
                "target_reading": None,
                "forbidden_targets": [
                    "bodyguard",
                    "escort"
                ],
                "rationale": None
            },
            {
                "canonical_key": "vehicle.boat",
                "category": "vehicle",
                "source_term": "船",
                "source_aliases": [],
                "target_term": "barge",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "vehicle.palanquin",
                "category": "vehicle",
                "source_term": "轿子",
                "source_aliases": [
                    "软轿"
                ],
                "target_term": "litter",
                "target_reading": None,
                "forbidden_targets": [
                    "palanquin",
                    "sedan chair"
                ],
                "rationale": None
            },
            {
                "canonical_key": "vehicle.carriage",
                "category": "vehicle",
                "source_term": "马车",
                "source_aliases": [
                    "车马"
                ],
                "target_term": "cart",
                "target_reading": None,
                "forbidden_targets": [
                    "car",
                    "carriage",
                    "coach",
                    "马车"
                ],
                "rationale": "带弹簧的 carriage/coach 是近代产物；盛期多为 cart 或 wagon"
            },
            {
                "canonical_key": "weapon.sword",
                "category": "weapon",
                "source_term": "剑",
                "source_aliases": [],
                "target_term": "longsword",
                "target_reading": None,
                "forbidden_targets": [
                    "jian",
                    "剑"
                ],
                "rationale": None
            },
            {
                "canonical_key": "weapon.bow",
                "category": "weapon",
                "source_term": "弓箭",
                "source_aliases": [],
                "target_term": "longbow",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "weapon.saber",
                "category": "weapon",
                "source_term": "腰刀",
                "source_aliases": [
                    "朴刀"
                ],
                "target_term": "falchion",
                "target_reading": None,
                "forbidden_targets": [
                    "saber",
                    "dao"
                ],
                "rationale": None
            },
            {
                "canonical_key": "weapon.long_blade",
                "category": "weapon",
                "source_term": "长刀",
                "source_aliases": [],
                "target_term": "falchion",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "weapon.straight_sword",
                "category": "weapon",
                "source_term": "长剑",
                "source_aliases": [
                    "宝剑",
                    "剑"
                ],
                "target_term": "longsword",
                "target_reading": None,
                "forbidden_targets": [
                    "katana",
                    "jian",
                    "blade"
                ],
                "rationale": None
            }
        ]
    },
    {
        "pair_code": "cn_wuxia__en_modern",
        "display_name": "中式武侠 → 英语现代都市",
        "source_profile_code": "cn_wuxia",
        "target_profile_code": "en_modern",
        "description": "江湖概念的现代都市改编。直译（jianghu / inner power）会丢失语义，一律转为功能等价的现代表达。",
        "entries": [
            {
                "canonical_key": "currency.silver",
                "category": "currency",
                "source_term": "银两",
                "source_aliases": [
                    "纹银",
                    "银子"
                ],
                "target_term": "cash",
                "target_reading": None,
                "forbidden_targets": [
                    "silver mark",
                    "silver tael",
                    "tael",
                    "银两"
                ],
                "rationale": None
            },
            {
                "canonical_key": "technique.inner_power",
                "category": "custom",
                "source_term": "内功",
                "source_aliases": [],
                "target_term": "conditioning",
                "target_reading": None,
                "forbidden_targets": [
                    "inner power",
                    "neigong",
                    "内功"
                ],
                "rationale": None
            },
            {
                "canonical_key": "technique.manual",
                "category": "custom",
                "source_term": "秘籍",
                "source_aliases": [
                    "武功秘籍"
                ],
                "target_term": "playbook",
                "target_reading": None,
                "forbidden_targets": [
                    "secret manual",
                    "秘籍"
                ],
                "rationale": None
            },
            {
                "canonical_key": "technique.lightness",
                "category": "custom",
                "source_term": "轻功",
                "source_aliases": [],
                "target_term": "parkour",
                "target_reading": None,
                "forbidden_targets": [
                    "lightness skill",
                    "qinggong"
                ],
                "rationale": None
            },
            {
                "canonical_key": "abstract.face_honor",
                "category": "custom",
                "source_term": "面子",
                "source_aliases": [
                    "脸面"
                ],
                "target_term": "respect",
                "target_reading": None,
                "forbidden_targets": [
                    "face",
                    "honour"
                ],
                "rationale": None
            },
            {
                "canonical_key": "faction.martial_alliance",
                "category": "faction",
                "source_term": "武林盟",
                "source_aliases": [],
                "target_term": "the syndicate",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "faction.jianghu",
                "category": "faction",
                "source_term": "江湖",
                "source_aliases": [],
                "target_term": "the streets",
                "target_reading": None,
                "forbidden_targets": [
                    "jianghu",
                    "rivers and lakes",
                    "the road",
                    "江湖"
                ],
                "rationale": "现代都市改编下 the streets 比 the life 更贴"
            },
            {
                "canonical_key": "faction.sect",
                "category": "faction",
                "source_term": "门派",
                "source_aliases": [
                    "帮派",
                    "宗门"
                ],
                "target_term": "crew",
                "target_reading": None,
                "forbidden_targets": [
                    "sect",
                    "门派"
                ],
                "rationale": "现代都市语境下的组织称谓"
            },
            {
                "canonical_key": "food.wine",
                "category": "food",
                "source_term": "酒",
                "source_aliases": [],
                "target_term": "whiskey",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "garment.long_robe",
                "category": "garment",
                "source_term": "长衫",
                "source_aliases": [],
                "target_term": "long coat",
                "target_reading": None,
                "forbidden_targets": [
                    "robe",
                    "长衫"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.humble_self",
                "category": "honorific",
                "source_term": "在下",
                "source_aliases": [
                    "鄙人"
                ],
                "target_term": "I",
                "target_reading": None,
                "forbidden_targets": [
                    "this humble one",
                    "在下"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.hero",
                "category": "honorific",
                "source_term": "大侠",
                "source_aliases": [
                    "少侠"
                ],
                "target_term": "legend",
                "target_reading": None,
                "forbidden_targets": [
                    "great hero",
                    "大侠"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.senior_brother",
                "category": "honorific",
                "source_term": "师兄",
                "source_aliases": [],
                "target_term": "senior",
                "target_reading": None,
                "forbidden_targets": [
                    "senior brother"
                ],
                "rationale": None
            },
            {
                "canonical_key": "honorific.master_male",
                "category": "honorific",
                "source_term": "师父",
                "source_aliases": [
                    "师傅"
                ],
                "target_term": "boss",
                "target_reading": None,
                "forbidden_targets": [
                    "master",
                    "sifu"
                ],
                "rationale": None
            },
            {
                "canonical_key": "office.constable",
                "category": "office",
                "source_term": "捕快",
                "source_aliases": [
                    "差役",
                    "衙役"
                ],
                "target_term": "detective",
                "target_reading": None,
                "forbidden_targets": [
                    "bailiff",
                    "constable"
                ],
                "rationale": None
            },
            {
                "canonical_key": "office.government_office",
                "category": "office",
                "source_term": "衙门",
                "source_aliases": [
                    "官府"
                ],
                "target_term": "precinct",
                "target_reading": None,
                "forbidden_targets": [
                    "magistrate",
                    "yamen"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.lodging_venue",
                "category": "place",
                "source_term": "客栈",
                "source_aliases": [
                    "旅店"
                ],
                "target_term": "motel",
                "target_reading": None,
                "forbidden_targets": [
                    "inn",
                    "tavern",
                    "客栈"
                ],
                "rationale": None
            },
            {
                "canonical_key": "place.teahouse",
                "category": "place",
                "source_term": "茶馆",
                "source_aliases": [
                    "茶肆"
                ],
                "target_term": "diner",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "place.dining_venue",
                "category": "place",
                "source_term": "酒楼",
                "source_aliases": [
                    "酒家",
                    "酒肆"
                ],
                "target_term": "bar and grill",
                "target_reading": None,
                "forbidden_targets": [
                    "alehouse",
                    "tavern"
                ],
                "rationale": "酒楼兼营饮食，非纯酒吧"
            },
            {
                "canonical_key": "org.escort_agency",
                "category": "place",
                "source_term": "镖局",
                "source_aliases": [],
                "target_term": "private security firm",
                "target_reading": None,
                "forbidden_targets": [
                    "escort agency"
                ],
                "rationale": "escort agency 在当代英语有性服务含义，必须避开"
            },
            {
                "canonical_key": "custom.kowtow",
                "category": "ritual",
                "source_term": "叩首",
                "source_aliases": [
                    "磕头"
                ],
                "target_term": "grovel",
                "target_reading": None,
                "forbidden_targets": [
                    "kowtow"
                ],
                "rationale": None
            },
            {
                "canonical_key": "role.escort",
                "category": "title",
                "source_term": "镖师",
                "source_aliases": [
                    "镖头"
                ],
                "target_term": "security contractor",
                "target_reading": None,
                "forbidden_targets": [
                    "man-at-arms"
                ],
                "rationale": None
            },
            {
                "canonical_key": "vehicle.horse",
                "category": "vehicle",
                "source_term": "马",
                "source_aliases": [],
                "target_term": "bike",
                "target_reading": None,
                "forbidden_targets": [
                    "horse",
                    "马"
                ],
                "rationale": "都市化改编下的个人交通工具"
            },
            {
                "canonical_key": "vehicle.horse_carriage",
                "category": "vehicle",
                "source_term": "马车",
                "source_aliases": [],
                "target_term": "car",
                "target_reading": None,
                "forbidden_targets": [
                    "carriage",
                    "cart"
                ],
                "rationale": None
            },
            {
                "canonical_key": "weapon.saber",
                "category": "weapon",
                "source_term": "刀",
                "source_aliases": [],
                "target_term": "knife",
                "target_reading": None,
                "forbidden_targets": [],
                "rationale": None
            },
            {
                "canonical_key": "weapon.sword",
                "category": "weapon",
                "source_term": "剑",
                "source_aliases": [],
                "target_term": "blade",
                "target_reading": None,
                "forbidden_targets": [
                    "jian",
                    "剑"
                ],
                "rationale": None
            },
            {
                "canonical_key": "weapon.hidden",
                "category": "weapon",
                "source_term": "暗器",
                "source_aliases": [],
                "target_term": "throwing knife",
                "target_reading": None,
                "forbidden_targets": [
                    "hidden weapon"
                ],
                "rationale": None
            },
            {
                "canonical_key": "weapon.straight_sword",
                "category": "weapon",
                "source_term": "长剑",
                "source_aliases": [
                    "剑"
                ],
                "target_term": "blade",
                "target_reading": None,
                "forbidden_targets": [
                    "longsword",
                    "katana"
                ],
                "rationale": None
            }
        ]
    }
]
