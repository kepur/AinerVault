"""内置世界观档案 —— 合并自两条并行开发线。

axes 的六个轴不是装饰：region / era / genre / world_setting / social_context / tech_level
共同决定名物与视觉。同为日本，江户与昭和的「客栈」分别是「旅籠」与「旅館」——
era 轴错了，整本书的名物就全错，所以两者各自成档。
"""
from __future__ import annotations

from typing import Any

PROFILES: list[dict[str, Any]] = [
    {
        "code": "cn_tang_classical",
        "display_name": "中国 · 唐宋 · 古典",
        "role": "source",
        "axes": {
            "region": "CN",
            "era": "tang_song",
            "era_span": [
                1279,
                618
            ],
            "genre": "literary_historical",
            "world_setting": "historical",
            "social_context": "imperial_city",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "宽袍大袖",
                "宽袖襦裙",
                "斗拱飞檐",
                "木构建筑",
                "水墨的留白",
                "水墨质感",
                "灯笼照明",
                "青砖黛瓦"
            ],
            "visual_dont": [
                "塑料制品",
                "机动车",
                "现代霓虹",
                "玻璃幕墙",
                "电线电杆",
                "西式吧台",
                "西式酒吧吧台"
            ],
            "signage_rules": {
                "language": "汉字",
                "font_style": "楷书/隶书",
                "material": "木牌/绢布",
                "script": "汉字",
                "style": "楷书/隶书",
                "avoid": "现代字体"
            },
            "palette": [
                "#3A4A3F",
                "#7A2E28",
                "#8C6E4A",
                "#C8B89A",
                "月白",
                "朱红",
                "赭石",
                "黛青"
            ]
        },
        "language": {
            "code": "zh-CN",
            "register": "classical_literary",
            "name_pattern": "family_given",
            "name_script": "hanzi",
            "numerals": "hanzi",
            "date_style": "reign_year",
            "honorifics": {}
        },
        "description": None
    },
    {
        "code": "cn_wuxia",
        "display_name": "中国 · 武侠 · 江湖",
        "role": "source",
        "axes": {
            "region": "CN",
            "era": "ancient_fantasy",
            "genre": "wuxia",
            "world_setting": "historical_fantasy",
            "social_context": "jianghu",
            "tech_level": "pre_industrial",
            "era_span": [
                1368,
                1644
            ]
        },
        "visual": {
            "visual_do": [
                "刀剑",
                "刀剑兵器",
                "夜行衣",
                "客栈大堂",
                "客栈木梁",
                "屋顶轻功",
                "江湖装束",
                "灯笼",
                "竹林",
                "青石板路"
            ],
            "visual_dont": [
                "枪械",
                "火器",
                "现代服饰",
                "现代霓虹",
                "西式酒吧吧台",
                "西洋建筑"
            ],
            "signage_rules": {
                "language": "汉字",
                "font_style": "行书",
                "material": "木匾",
                "script": "汉字",
                "style": "行书/招幌"
            }
        },
        "language": {
            "code": "zh-CN",
            "register": "wuxia_vernacular",
            "name_pattern": "family_given",
            "name_script": "hanzi",
            "honorifics": {},
            "numerals": "hanzi"
        },
        "description": None
    },
    {
        "code": "en_modern",
        "display_name": "英语圈 · 现代都市",
        "role": "target",
        "axes": {
            "region": "US",
            "era": "contemporary",
            "era_span": [
                1990,
                2030
            ],
            "genre": "urban_drama",
            "world_setting": "realistic",
            "social_context": "metropolitan",
            "tech_level": "digital"
        },
        "visual": {
            "visual_do": [
                "asphalt streets",
                "casual wear",
                "contemporary streetwear",
                "glass and steel",
                "glass towers",
                "neon signage"
            ],
            "visual_dont": [
                "horse carriages",
                "oil lamps",
                "period costume"
            ],
            "signage_rules": {
                "language": "English",
                "font_style": "sans-serif",
                "script": "Latin",
                "style": "modern sans-serif"
            }
        },
        "language": {
            "code": "en-US",
            "register": "contemporary_neutral",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "arabic",
            "honorifics": {
                "娘子": "honey",
                "大人": "sir",
                "公子": "kid",
                "小姐": "miss",
                "老爷": "boss",
                "姑娘": "miss"
            },
            "forbidden_tokens": [
                "milord",
                "thee",
                "thou",
                "客栈"
            ],
            "date_style": "gregorian"
        },
        "description": None
    },
    {
        "code": "eu_medieval_high",
        "display_name": "欧洲 · 中世纪盛期 (1000–1300)",
        "role": "target",
        "axes": {
            "region": "EU",
            "era": "high_medieval",
            "era_span": [
                1000,
                1300
            ],
            "genre": "historical_drama",
            "world_setting": "historical",
            "social_context": "market_town",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "cobbled market square",
                "heraldic banners",
                "pointed and round arches",
                "rushlight and tallow candles",
                "stone and timber-framed buildings",
                "stone keeps and timber-framed houses",
                "thatched roofs",
                "torchlight and tallow candles",
                "woolen tunics and linen",
                "woolen tunics and linen shifts"
            ],
            "visual_dont": [
                "East Asian architecture",
                "chimneys in peasant homes",
                "gunpowder weapons",
                "plate armour",
                "plate glass",
                "potatoes or tomatoes",
                "printed books",
                "silk robes with wide sleeves"
            ],
            "signage_rules": {
                "language": "Latin or vernacular",
                "font_style": "uncial/blackletter",
                "material": "carved wood or painted board",
                "note": "多用图形招牌，识字率低",
                "script": "Latin",
                "style": "Gothic blackletter"
            },
            "costume_norms": {
                "color_palette": [
                    "madder red",
                    "woad blue",
                    "undyed wool",
                    "saffron"
                ],
                "fabric_types": [
                    "wool",
                    "linen",
                    "silk for nobility only"
                ],
                "social_class_indicators": "染色の鮮やかさと袖丈",
                "common": [
                    "tunic",
                    "surcoat",
                    "hose",
                    "wimple"
                ],
                "avoid": [
                    "hanfu",
                    "kimono"
                ]
            },
            "palette": [
                "#3B3227",
                "#6E5B43",
                "#A89070",
                "#6B2B26"
            ]
        },
        "language": {
            "code": "en-GB",
            "register": "archaic_formal",
            "name_pattern": "given_of_place",
            "name_script": "latin",
            "numerals": "roman",
            "date_style": "year_of_our_lord",
            "honorifics": {
                "娘子": "my lady",
                "夫人": "my lady",
                "公子": "young sir",
                "大人": "my lord",
                "小姐": "mistress",
                "老爷": "master",
                "少爷": "young master",
                "客官": "good sir",
                "师父": "master",
                "官人": "my lord",
                "在下": "this humble one",
                "姑娘": "maiden"
            },
            "forbidden_tokens": [
                "Mr.",
                "Ms.",
                "gun",
                "hotel",
                "okay",
                "pistol",
                "police",
                "yeah",
                "客栈",
                "衙门"
            ]
        },
        "description": None
    },
    {
        "code": "jp_edo",
        "display_name": "日本·江户 (1603–1868)",
        "role": "target",
        "axes": {
            "region": "JP",
            "era": "edo",
            "era_span": [
                1603,
                1868
            ],
            "genre": "jidaigeki",
            "world_setting": "historical",
            "social_context": "castle_town",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "町屋",
                "行灯",
                "提灯",
                "髷",
                "刀を差した武士",
                "旅籠の暖簾"
            ],
            "visual_dont": [
                "電線",
                "洋服",
                "路面電車",
                "ガラス窓"
            ],
            "signage_rules": {
                "language": "日本語（変体仮名）",
                "font_style": "勘亭流",
                "material": "木札・暖簾"
            }
        },
        "language": {
            "code": "ja-JP",
            "register": "archaic_formal",
            "name_pattern": "family_given",
            "name_script": "kanji+kana",
            "honorifics": {
                "娘子": "御内儀",
                "大人": "お殿様",
                "公子": "若様",
                "客官": "お客人",
                "小姐": "お嬢様"
            },
            "forbidden_tokens": [
                "旅館",
                "電車",
                "洋服",
                "inn",
                "hotel"
            ],
            "numerals": "kanji",
            "date_style": "era_year"
        },
        "description": None
    },
    {
        "code": "jp_showa",
        "display_name": "日本 · 昭和 (1926–1989)",
        "role": "target",
        "axes": {
            "region": "JP",
            "era": "showa",
            "era_span": [
                1926,
                1989
            ],
            "genre": "literary_drama",
            "world_setting": "historical",
            "social_context": "provincial_town",
            "tech_level": "early_industrial"
        },
        "visual": {
            "visual_do": [
                "ブリキ看板",
                "ホーロー看板",
                "土間と縁側",
                "木造二階建て",
                "木造家屋",
                "瓦屋根",
                "白熱灯と裸電球",
                "着物と割烹着",
                "着物と洋服の混在",
                "行灯・裸電球",
                "路面電車",
                "障子と畳"
            ],
            "visual_dont": [
                "LEDネオン",
                "LED照明",
                "ちょんまげ",
                "スマートフォン",
                "中華風の楼閣",
                "刀を差した武士",
                "江戸期の髷",
                "漢服",
                "現代のコンビニ",
                "現代の高層ビル"
            ],
            "signage_rules": {
                "language": "日本語（漢字・カタカナ主体）",
                "font_style": "角ゴシック/勘亭流",
                "material": "琺瑯看板・木札",
                "note": "右横書きは戦前、左横書きは戦後",
                "script": "漢字＋かな",
                "style": "レトロ書体・縦書き",
                "avoid": "簡体字・現代ゴシック"
            },
            "costume_norms": {
                "color_palette": [
                    "藍",
                    "鼠色",
                    "生成り",
                    "臙脂"
                ],
                "fabric_types": [
                    "木綿",
                    "銘仙",
                    "ウール"
                ],
                "social_class_indicators": "着物の質と洋装の割合",
                "common": [
                    "着物",
                    "袴",
                    "作務衣",
                    "国民服"
                ],
                "avoid": [
                    "漢服",
                    "唐装"
                ]
            },
            "palette": [
                "#2E2A26",
                "#7B6A55",
                "#8C3A2E",
                "#C4B49A",
                "セピア",
                "藍",
                "褪せた朱",
                "鼠色"
            ]
        },
        "language": {
            "code": "ja-JP",
            "register": "literary_formal",
            "name_pattern": "family_given",
            "name_script": "kanji+kana",
            "numerals": "kanji",
            "date_style": "era_year",
            "honorifics": {
                "娘子": "家内",
                "夫人": "奥様",
                "公子": "若様",
                "大人": "様",
                "先生": "先生",
                "小姐": "お嬢様",
                "老爷": "旦那様",
                "少爷": "若旦那",
                "姑娘": "お嬢さん",
                "客官": "お客さん",
                "师父": "師匠",
                "兄台": "兄さん",
                "官人": "旦那",
                "相公": "あなた",
                "在下": "私",
                "鄙人": "小生"
            },
            "forbidden_tokens": [
                "Mr.",
                "Mrs.",
                "hotel",
                "inn",
                "magistrate",
                "ござる",
                "ちょんまげ",
                "客栈",
                "拙者",
                "衙门",
                "铜钱"
            ]
        },
        "description": None
    }
]
