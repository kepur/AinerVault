"""文化圈层包 —— 语言只是外壳，圈层才是内容。

一门语言背后从来不是一个文化。同为 en-GB，摄政英国与维多利亚英国的
名物、称谓、视觉全然不同：前者是马车与舞会，后者是蒸汽与煤烟；
Miss 在前者指未婚小姐、在后者还多一层雇佣关系。同为 pt，
葡萄牙半岛的 Dom 与巴西的 Coronel 分属两套权力结构。

所以档案按**圈层**建，不按语言建。language.code 只是 BCP-47 标签，
用来选 TTS 音色与前端筛选；决定译文长什么样的是 axes 六轴。
同一 language.code 下可以有任意多个圈层档案，靠 world_transform 区分 ——
这也是 translation_blocks 按 transform_id 而非语言码存的原因。

覆盖全球前十大语言：en / zh / hi / es / fr / ar / bn / pt / ru / ja。
每个语言至少一个圈层，历史跨度大的语言给多个。
"""
from __future__ import annotations

from typing import Any

CULTURE_PACKS: list[dict[str, Any]] = [
    {
        "code": "cn_modern_net",
        "display_name": "中文 · 当代网络 (2010–2030)",
        "role": "source",
        "axes": {
            "region": "CN", "era": "contemporary", "era_span": [2010, 2030],
            "genre": "web_fiction", "world_setting": "modern",
            "social_context": "urban_online", "tech_level": "digital"
        },
        "visual": {
            "visual_do": ["写字楼格子间", "外卖与共享单车", "手机屏幕", "地铁早高峰",
                          "奶茶店", "出租屋", "直播补光灯", "城中村"],
            "visual_dont": ["古装", "马车", "中世纪建筑", "西部荒原"],
            "signage_rules": {"language": "汉字", "script": "简体汉字",
                              "style": "黑体/圆体", "material": "亚克力灯箱",
                              "avoid": "毛笔书法"},
            "palette": ["#F5F5F5", "#2B2B2B", "#4A90D9", "#FF6B6B", "屏幕蓝", "水泥灰"]
        },
        "language": {
            "code": "zh-CN", "register": "internet_vernacular",
            "name_pattern": "family_given", "name_script": "hanzi",
            "numerals": "arabic", "date_style": "calendar_year",
            "honorifics": {"peer": "哥/姐", "online": "老铁/家人们"}
        },
        "description": "网文的主战场。网络梗密度极高，且半数活不过三年 —— 时效性判断在这里最吃重。"
    },
    {
        "code": "en_gb_regency",
        "display_name": "英语 · 摄政英国 (1811–1820)",
        "role": "target",
        "axes": {
            "region": "GB",
            "era": "regency",
            "era_span": [
                1811,
                1820
            ],
            "genre": "social_romance",
            "world_setting": "historical",
            "social_context": "landed_gentry",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "马车与驿站",
                "乡绅庄园",
                "舞会长厅",
                "烛台与壁炉",
                "高腰束胸长裙",
                "燕尾服与领巾",
                "羽毛笔与蜡封信",
                "修剪的英式园林"
            ],
            "visual_dont": [
                "电灯",
                "汽车",
                "牛仔裤",
                "工厂烟囱",
                "枪战",
                "美式口语"
            ],
            "signage_rules": {
                "language": "English",
                "script": "latin",
                "style": "衬线雕刻体",
                "material": "漆木招牌/黄铜",
                "avoid": "无衬线现代字体"
            },
            "palette": [
                "#3E4A3C",
                "#8B6F4E",
                "#C9B79C",
                "#6B2737",
                "奶油白",
                "深酒红",
                "苔绿"
            ]
        },
        "language": {
            "code": "en-GB",
            "register": "regency_polite",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "male": "Mr.",
                "female_married": "Mrs.",
                "female_single": "Miss",
                "noble": "Lord/Lady",
                "knight": "Sir"
            }
        },
        "description": "简·奥斯汀的世界。阶层、体面、婚姻即经济。称谓错一层就是失礼，社交距离全靠称呼维持。"
    },
    {
        "code": "en_gb_victorian",
        "display_name": "英语 · 维多利亚英国 (1837–1901)",
        "role": "target",
        "axes": {
            "region": "GB",
            "era": "victorian",
            "era_span": [
                1837,
                1901
            ],
            "genre": "social_realism",
            "world_setting": "historical",
            "social_context": "industrial_city",
            "tech_level": "early_industrial"
        },
        "visual": {
            "visual_do": [
                "煤气路灯",
                "蒸汽火车",
                "浓雾与煤烟",
                "礼帽与手杖",
                "束胸裙撑",
                "红砖排屋",
                "工厂烟囱",
                "马车与鹅卵石街"
            ],
            "visual_dont": [
                "电灯泡普及",
                "汽车",
                "塑料",
                "现代广告牌",
                "牛仔风格"
            ],
            "signage_rules": {
                "language": "English",
                "script": "latin",
                "style": "维多利亚花体/粗衬线",
                "material": "搪瓷/漆木",
                "avoid": "极简无衬线"
            },
            "palette": [
                "#2B2B2B",
                "#5C4033",
                "#8B0000",
                "#3F4A56",
                "煤黑",
                "雾灰",
                "深绛"
            ]
        },
        "language": {
            "code": "en-GB",
            "register": "victorian_formal",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "male": "Mr.",
                "female_married": "Mrs.",
                "female_single": "Miss",
                "servant_address": "Sir/Madam",
                "noble": "Lord/Lady"
            }
        },
        "description": "狄更斯与勃朗特的世界。工业、阶级鸿沟、道德压抑。体面是外壳，煤灰是底色。"
    },
    {
        "code": "en_us_frontier",
        "display_name": "英语 · 美国西部拓荒 (1865–1895)",
        "role": "target",
        "axes": {
            "region": "US",
            "era": "old_west",
            "era_span": [
                1865,
                1895
            ],
            "genre": "western",
            "world_setting": "historical",
            "social_context": "frontier_town",
            "tech_level": "early_industrial"
        },
        "visual": {
            "visual_do": [
                "木板门面小镇",
                "旋转门酒馆",
                "左轮与温彻斯特",
                "马鞍与栓马桩",
                "宽檐帽与皮靴",
                "尘土与荒原",
                "驿马车",
                "铁路终点站"
            ],
            "visual_dont": [
                "中世纪城堡",
                "汽车",
                "摩天楼",
                "英式庄园礼仪",
                "东亚建筑"
            ],
            "signage_rules": {
                "language": "English",
                "script": "latin",
                "style": "西部粗木刻体",
                "material": "手绘木板",
                "avoid": "花体/现代字体"
            },
            "palette": [
                "#8B5A2B",
                "#C19A6B",
                "#4A3728",
                "#9B2226",
                "沙黄",
                "旧木棕",
                "锈红"
            ]
        },
        "language": {
            "code": "en-US",
            "register": "frontier_vernacular",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "male": "Mister",
                "sheriff": "Sheriff",
                "informal": "stranger/partner"
            }
        },
        "description": "无政府边疆。称谓短促直接，法律是枪和治安官。摄政英国那套礼仪在这里是笑话。"
    },
    {
        "code": "en_us_prohibition",
        "display_name": "英语 · 美国禁酒令时期 (1920–1933)",
        "role": "target",
        "axes": {
            "region": "US",
            "era": "prohibition",
            "era_span": [
                1920,
                1933
            ],
            "genre": "crime_noir",
            "world_setting": "historical",
            "social_context": "metropolis",
            "tech_level": "industrial"
        },
        "visual": {
            "visual_do": [
                "地下酒吧",
                "爵士乐队",
                "flapper 短发直筒裙",
                "三件套西装与礼帽",
                "老式轿车",
                "霓虹初现",
                "钢架高楼",
                "汤普森冲锋枪"
            ],
            "visual_dont": [
                "中世纪",
                "马车为主的街道",
                "现代智能设备",
                "东方建筑"
            ],
            "signage_rules": {
                "language": "English",
                "script": "latin",
                "style": "Art Deco 几何体",
                "material": "霓虹管/镀铬",
                "avoid": "衬线古典体"
            },
            "palette": [
                "#1C1C1C",
                "#B8860B",
                "#8B0000",
                "#2F4F4F",
                "香槟金",
                "午夜蓝",
                "血红"
            ]
        },
        "language": {
            "code": "en-US",
            "register": "jazz_age_slang",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "male": "Mister",
                "informal": "pal/buddy",
                "boss": "Boss"
            }
        },
        "description": "爵士时代。黑帮、私酒、财富与堕落。俚语密度极高，是这一圈层的标志。"
    },
    {
        "code": "cn_republic",
        "display_name": "中文 · 民国 (1912–1949)",
        "role": "target",
        "axes": {
            "region": "CN",
            "era": "republic_era",
            "era_span": [
                1912,
                1949
            ],
            "genre": "period_drama",
            "world_setting": "historical",
            "social_context": "treaty_port",
            "tech_level": "early_industrial"
        },
        "visual": {
            "visual_do": [
                "长衫与旗袍",
                "石库门里弄",
                "黄包车",
                "有轨电车",
                "月份牌与霓虹",
                "留声机",
                "西式洋行",
                "煤球炉"
            ],
            "visual_dont": [
                "现代高楼玻璃幕墙",
                "智能手机",
                "中世纪欧洲元素",
                "汉唐宽袍"
            ],
            "signage_rules": {
                "language": "汉字",
                "script": "繁体汉字",
                "style": "美术字/魏碑",
                "material": "搪瓷招牌/霓虹",
                "avoid": "简体现代字体"
            },
            "palette": [
                "#3C3C3C",
                "#8C6E4A",
                "#A23B33",
                "#D9C9A8",
                "月白",
                "旧墨",
                "胭脂"
            ]
        },
        "language": {
            "code": "zh-CN",
            "register": "republic_vernacular",
            "name_pattern": "family_given",
            "name_script": "hanzi",
            "numerals": "hanzi",
            "date_style": "republic_year",
            "honorifics": {
                "male": "先生",
                "female": "女士/小姐",
                "elder": "老先生",
                "military": "长官"
            }
        },
        "description": "新旧交替。长衫与西装同街，文言与白话同页。称谓正处在剧变中，这本身就是戏。"
    },
    {
        "code": "jp_sengoku",
        "display_name": "日语 · 战国 (1467–1600)",
        "role": "target",
        "axes": {
            "region": "JP",
            "era": "sengoku",
            "era_span": [
                1467,
                1600
            ],
            "genre": "samurai_war",
            "world_setting": "historical",
            "social_context": "warring_states",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "具足甲胄",
                "山城天守",
                "阵羽织",
                "太刀与长枪",
                "火绳枪",
                "旗指物",
                "囲炉裏",
                "障子与畳"
            ],
            "visual_dont": [
                "江户町人文化",
                "现代建筑",
                "西洋礼服",
                "中式斗拱"
            ],
            "signage_rules": {
                "language": "日本語",
                "script": "kanji",
                "style": "隷書/勘亭流",
                "material": "木札/布幟",
                "avoid": "現代ゴシック"
            },
            "palette": [
                "#2F3A2E",
                "#6B4423",
                "#8C1F1F",
                "#C8B89A",
                "墨",
                "朱",
                "黄土"
            ]
        },
        "language": {
            "code": "ja-JP",
            "register": "archaic_martial",
            "name_pattern": "family_given",
            "name_script": "kanji_kana",
            "numerals": "kanji",
            "date_style": "era_name",
            "honorifics": {
                "lord": "殿",
                "retainer": "様",
                "peer": "殿",
                "humble": "拙者"
            }
        },
        "description": "乱世。称谓即身份，用错等于挑衅。敬语层级比江户更硬。"
    },
    {
        "code": "jp_heisei",
        "display_name": "日语 · 平成现代 (1989–2019)",
        "role": "target",
        "axes": {
            "region": "JP",
            "era": "heisei",
            "era_span": [
                1989,
                2019
            ],
            "genre": "contemporary_drama",
            "world_setting": "modern",
            "social_context": "urban",
            "tech_level": "digital"
        },
        "visual": {
            "visual_do": [
                "便利店",
                "电车与站前商店街",
                "公寓阳台",
                "制服",
                "自动贩卖机",
                "霓虹招牌",
                "咖啡连锁",
                "手机"
            ],
            "visual_dont": [
                "和服日常化",
                "武士刀",
                "茅草屋顶",
                "中世纪欧洲"
            ],
            "signage_rules": {
                "language": "日本語",
                "script": "mixed",
                "style": "ゴシック体",
                "material": "アクリル/LED",
                "avoid": "毛筆体"
            },
            "palette": [
                "#E8E8E8",
                "#4A6FA5",
                "#2B2B2B",
                "#D64545",
                "白",
                "群青",
                "蛍光"
            ]
        },
        "language": {
            "code": "ja-JP",
            "register": "modern_polite",
            "name_pattern": "family_given",
            "name_script": "kanji_kana",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "peer": "さん",
                "junior": "くん/ちゃん",
                "senior": "先輩",
                "teacher": "先生"
            }
        },
        "description": "现代日本。敬语仍在，但载体从身份变成距离与场合。"
    },
    {
        "code": "es_golden_age",
        "display_name": "西班牙语 · 黄金世纪西班牙 (1550–1650)",
        "role": "target",
        "axes": {
            "region": "ES",
            "era": "siglo_de_oro",
            "era_span": [
                1550,
                1650
            ],
            "genre": "picaresque",
            "world_setting": "historical",
            "social_context": "imperial_court",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "拉夫领与斗篷",
                "细剑 rapier",
                "石砌广场",
                "修道院回廊",
                "烛光与油画",
                "驴车与石板路",
                "客栈 posada",
                "宗教游行"
            ],
            "visual_dont": [
                "工业机械",
                "美洲原住民装饰为主体",
                "现代服饰",
                "东亚建筑"
            ],
            "signage_rules": {
                "language": "Español",
                "script": "latin",
                "style": "巴洛克雕刻体",
                "material": "石刻/锻铁",
                "avoid": "现代无衬线"
            },
            "palette": [
                "#2E2A26",
                "#7B3F00",
                "#8B1A1A",
                "#D4AF6A",
                "赭",
                "深红",
                "金"
            ]
        },
        "language": {
            "code": "es-ES",
            "register": "castilian_classical",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "roman",
            "date_style": "calendar_year",
            "honorifics": {
                "male": "Don",
                "female": "Doña",
                "noble": "Señoría",
                "cleric": "Padre"
            }
        },
        "description": "堂吉诃德的世界。荣誉、宗教、没落贵族。Don 这个称谓本身就是全部社会结构。"
    },
    {
        "code": "es_mx_revolution",
        "display_name": "西班牙语 · 墨西哥革命 (1910–1920)",
        "role": "target",
        "axes": {
            "region": "MX",
            "era": "mexican_revolution",
            "era_span": [
                1910,
                1920
            ],
            "genre": "historical_drama",
            "world_setting": "historical",
            "social_context": "rural_revolt",
            "tech_level": "early_industrial"
        },
        "visual": {
            "visual_do": [
                "宽檐草帽 sombrero",
                "子弹带 bandolera",
                "干旱高原",
                "土坯村落",
                "蒸汽火车",
                "骑兵与卡宾枪",
                "龙舌兰田",
                "教堂钟楼"
            ],
            "visual_dont": [
                "欧洲宫廷",
                "现代都市",
                "东亚元素",
                "西班牙半岛口音标记"
            ],
            "signage_rules": {
                "language": "Español",
                "script": "latin",
                "style": "手绘广告体",
                "material": "刷漆灰泥墙",
                "avoid": "巴洛克花体"
            },
            "palette": [
                "#C1440E",
                "#E8C547",
                "#4B5320",
                "#8B5A2B",
                "土红",
                "麦黄",
                "仙人掌绿"
            ]
        },
        "language": {
            "code": "es-MX",
            "register": "mexican_vernacular",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "male": "Señor",
                "informal": "compadre",
                "leader": "General"
            }
        },
        "description": "革命年代。西班牙半岛那套 Don/Doña 在这里带殖民色彩，语域完全不同。"
    },
    {
        "code": "fr_revolution",
        "display_name": "法语 · 大革命 (1789–1799)",
        "role": "target",
        "axes": {
            "region": "FR",
            "era": "french_revolution",
            "era_span": [
                1789,
                1799
            ],
            "genre": "political_drama",
            "world_setting": "historical",
            "social_context": "revolutionary_paris",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "三色帽徽",
                "断头台",
                "国民自卫军制服",
                "沙龙与咖啡馆",
                "石板街垒",
                "烛台会议厅",
                "马车",
                "小册子与传单"
            ],
            "visual_dont": [
                "工业烟囱",
                "汽车",
                "现代服饰",
                "东方建筑"
            ],
            "signage_rules": {
                "language": "Français",
                "script": "latin",
                "style": "共和体大写",
                "material": "石刻/纸告示",
                "avoid": "王室花体"
            },
            "palette": [
                "#0055A4",
                "#FFFFFF",
                "#EF4135",
                "#4A4A4A",
                "三色",
                "石灰白",
                "血红"
            ]
        },
        "language": {
            "code": "fr-FR",
            "register": "revolutionary_rhetoric",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "arabic",
            "date_style": "republican_calendar",
            "honorifics": {
                "formal": "Citoyen/Citoyenne",
                "old_regime": "Monsieur/Madame"
            }
        },
        "description": "称谓本身就是政治。Monsieur 换成 Citoyen 是一场革命，用错会掉脑袋。"
    },
    {
        "code": "fr_belle_epoque",
        "display_name": "法语 · 美好年代 (1871–1914)",
        "role": "target",
        "axes": {
            "region": "FR",
            "era": "belle_epoque",
            "era_span": [
                1871,
                1914
            ],
            "genre": "social_romance",
            "world_setting": "historical",
            "social_context": "metropolis",
            "tech_level": "early_industrial"
        },
        "visual": {
            "visual_do": [
                "奥斯曼式公寓",
                "煤气路灯转电灯",
                "咖啡馆露台",
                "新艺术曲线",
                "礼帽与手杖",
                "束腰长裙",
                "地铁初建",
                "红磨坊"
            ],
            "visual_dont": [
                "中世纪",
                "美式西部",
                "现代玻璃幕墙"
            ],
            "signage_rules": {
                "language": "Français",
                "script": "latin",
                "style": "Art Nouveau 曲线体",
                "material": "锻铁/彩玻",
                "avoid": "粗黑现代体"
            },
            "palette": [
                "#2F4F4F",
                "#C9A227",
                "#8B3A62",
                "#E8DCC4",
                "香槟",
                "孔雀绿",
                "玫瑰灰"
            ]
        },
        "language": {
            "code": "fr-FR",
            "register": "parisian_refined",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "male": "Monsieur",
                "female_married": "Madame",
                "female_single": "Mademoiselle"
            }
        },
        "description": "普鲁斯特的巴黎。优雅、颓废、阶层微妙。称谓的细微差别承载全部社交信息。"
    },
    {
        "code": "ar_abbasid",
        "display_name": "阿拉伯语 · 阿拔斯巴格达 (750–1258)",
        "role": "target",
        "axes": {
            "region": "IQ",
            "era": "abbasid_golden",
            "era_span": [
                750,
                1258
            ],
            "genre": "adventure_fantasy",
            "world_setting": "historical",
            "social_context": "caliphate_city",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "穹顶与尖拱",
                "几何镶嵌",
                "香料市集 souq",
                "长袍与头巾",
                "骆驼商队",
                "庭院水池",
                "手抄本与星盘",
                "灯盏"
            ],
            "visual_dont": [
                "十字架为主体",
                "工业机械",
                "东亚建筑",
                "现代服饰"
            ],
            "signage_rules": {
                "language": "العربية",
                "script": "arabic",
                "style": "库法体/纳斯赫体",
                "material": "彩釉瓷砖/木雕",
                "avoid": "拉丁字母招牌"
            },
            "palette": [
                "#0F5257",
                "#C9A227",
                "#7B2D26",
                "#E8DCC4",
                "松石绿",
                "金",
                "赭"
            ]
        },
        "language": {
            "code": "ar-SA",
            "register": "classical_arabic",
            "name_pattern": "given_patronymic",
            "name_script": "arabic_script",
            "numerals": "arabic_indic",
            "date_style": "hijri",
            "honorifics": {
                "respect": "سيدي",
                "scholar": "شيخ",
                "ruler": "أمير المؤمنين"
            }
        },
        "description": "一千零一夜的世界。名字是父子链（ibn/bint），不是姓氏 —— 命名结构与西方根本不同。"
    },
    {
        "code": "ru_imperial",
        "display_name": "俄语 · 帝俄晚期 (1855–1917)",
        "role": "target",
        "axes": {
            "region": "RU",
            "era": "late_imperial",
            "era_span": [
                1855,
                1917
            ],
            "genre": "social_realism",
            "world_setting": "historical",
            "social_context": "imperial_city",
            "tech_level": "early_industrial"
        },
        "visual": {
            "visual_do": [
                "圣彼得堡运河",
                "洋葱顶教堂",
                "军官制服与肩章",
                "毛皮大衣",
                "雪橇",
                "庄园与农奴村",
                "萨莫瓦壶",
                "烛光舞会"
            ],
            "visual_dont": [
                "美式元素",
                "现代都市",
                "东亚建筑",
                "工业流水线"
            ],
            "signage_rules": {
                "language": "Русский",
                "script": "cyrillic",
                "style": "帝俄衬线体",
                "material": "漆木/黄铜",
                "avoid": "苏联构成主义"
            },
            "palette": [
                "#2C3E50",
                "#7B241C",
                "#D4AC0D",
                "#EAECEE",
                "帝俄绿",
                "深红",
                "雪白"
            ]
        },
        "language": {
            "code": "ru-RU",
            "register": "imperial_formal",
            "name_pattern": "given_patronymic_family",
            "name_script": "cyrillic",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "formal": "имя + отчество",
                "noble": "Ваше сиятельство",
                "officer": "Ваше благородие"
            }
        },
        "description": "托尔斯泰的世界。正式称呼是「名 + 父称」，只用名是极亲密 —— 这层关系西方语言里没有对应。"
    },
    {
        "code": "ru_soviet",
        "display_name": "俄语 · 苏联 (1922–1991)",
        "role": "target",
        "axes": {
            "region": "RU",
            "era": "soviet",
            "era_span": [
                1922,
                1991
            ],
            "genre": "political_drama",
            "world_setting": "historical",
            "social_context": "socialist_city",
            "tech_level": "industrial"
        },
        "visual": {
            "visual_do": [
                "赫鲁晓夫楼",
                "构成主义海报",
                "红旗与标语",
                "工厂与拖拉机",
                "军大衣",
                "地铁宫殿",
                "排队与配给",
                "伏尔加轿车"
            ],
            "visual_dont": [
                "帝俄贵族舞会",
                "西方消费广告",
                "宗教仪式为主体"
            ],
            "signage_rules": {
                "language": "Русский",
                "script": "cyrillic",
                "style": "构成主义粗体",
                "material": "搪瓷/铁牌",
                "avoid": "帝俄花体"
            },
            "palette": [
                "#B22222",
                "#4A4A4A",
                "#D9CBA3",
                "#2F4F4F",
                "苏联红",
                "工业灰",
                "麦黄"
            ]
        },
        "language": {
            "code": "ru-RU",
            "register": "soviet_official",
            "name_pattern": "given_patronymic_family",
            "name_script": "cyrillic",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "formal": "товарищ",
                "workplace": "имя + отчество"
            }
        },
        "description": "товарищ（同志）取代了全部旧称谓。称谓的更替本身就是这个圈层的核心。"
    },
    {
        "code": "pt_discoveries",
        "display_name": "葡萄牙语 · 大航海 (1450–1600)",
        "role": "target",
        "axes": {
            "region": "PT",
            "era": "age_of_discovery",
            "era_span": [
                1450,
                1600
            ],
            "genre": "maritime_adventure",
            "world_setting": "historical",
            "social_context": "port_city",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "卡拉维尔帆船",
                "曼努埃尔式石雕",
                "航海图与星盘",
                "香料与瓷器",
                "石砌港口",
                "修士与商人",
                "缆绳与木桶",
                "灯塔"
            ],
            "visual_dont": [
                "工业时代",
                "内陆草原为主",
                "东亚建筑为主体",
                "现代服饰"
            ],
            "signage_rules": {
                "language": "Português",
                "script": "latin",
                "style": "曼努埃尔式雕刻",
                "material": "石刻/彩瓷 azulejo",
                "avoid": "现代无衬线"
            },
            "palette": [
                "#1B4D3E",
                "#C9A227",
                "#8B4513",
                "#E8DCC4",
                "海蓝",
                "金",
                "赤陶"
            ]
        },
        "language": {
            "code": "pt-PT",
            "register": "classical_portuguese",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "roman",
            "date_style": "calendar_year",
            "honorifics": {
                "male": "Dom",
                "female": "Dona",
                "captain": "Capitão"
            }
        },
        "description": "航海帝国。海是主场，陆地是补给。"
    },
    {
        "code": "pt_br_coffee",
        "display_name": "葡萄牙语 · 巴西咖啡时代 (1850–1930)",
        "role": "target",
        "axes": {
            "region": "BR",
            "era": "coffee_republic",
            "era_span": [
                1850,
                1930
            ],
            "genre": "social_drama",
            "world_setting": "historical",
            "social_context": "plantation_and_port",
            "tech_level": "early_industrial"
        },
        "visual": {
            "visual_do": [
                "咖啡庄园 fazenda",
                "殖民地风格宅邸",
                "热带植被",
                "港口与货栈",
                "亚麻西装与草帽",
                "有轨电车",
                "教堂广场",
                "蒸汽火车"
            ],
            "visual_dont": [
                "欧洲寒冷气候",
                "葡萄牙半岛石砌为主",
                "现代高楼"
            ],
            "signage_rules": {
                "language": "Português",
                "script": "latin",
                "style": "手绘商号体",
                "material": "刷漆木/灰泥",
                "avoid": "哥特体"
            },
            "palette": [
                "#3E5C3A",
                "#A0522D",
                "#E8C547",
                "#F5F0E1",
                "咖啡棕",
                "热带绿",
                "米白"
            ]
        },
        "language": {
            "code": "pt-BR",
            "register": "brazilian_vernacular",
            "name_pattern": "given_family",
            "name_script": "latin",
            "numerals": "arabic",
            "date_style": "calendar_year",
            "honorifics": {
                "male": "Senhor",
                "female": "Senhora",
                "landowner": "Coronel"
            }
        },
        "description": "热带、奴隶制余绪、咖啡财富。与葡萄牙半岛同语不同世界，Coronel 是巴西独有的权力称谓。"
    },
    {
        "code": "hi_mughal",
        "display_name": "印地语 · 莫卧儿 (1526–1857)",
        "role": "target",
        "axes": {
            "region": "IN",
            "era": "mughal",
            "era_span": [
                1526,
                1857
            ],
            "genre": "court_epic",
            "world_setting": "historical",
            "social_context": "imperial_court",
            "tech_level": "pre_industrial"
        },
        "visual": {
            "visual_do": [
                "红砂岩宫殿",
                "洋葱穹顶",
                "细密画风格",
                "宝石与织金",
                "象轿",
                "庭园水渠 charbagh",
                "纱丽与长袍 jama",
                "弯刀 talwar"
            ],
            "visual_dont": [
                "欧洲哥特建筑",
                "工业机械",
                "现代服饰",
                "东亚屋顶"
            ],
            "signage_rules": {
                "language": "हिन्दी",
                "script": "devanagari",
                "style": "纳斯塔利克/天城体",
                "material": "石刻/织物",
                "avoid": "拉丁招牌"
            },
            "palette": [
                "#8B1A1A",
                "#C9A227",
                "#0F5257",
                "#E8DCC4",
                "朱砂",
                "金",
                "孔雀蓝"
            ]
        },
        "language": {
            "code": "hi-IN",
            "register": "courtly_hindustani",
            "name_pattern": "given_title",
            "name_script": "devanagari",
            "numerals": "devanagari",
            "date_style": "hijri",
            "honorifics": {
                "emperor": "जहाँपनाह",
                "noble": "साहब",
                "respect": "जी"
            }
        },
        "description": "宫廷史诗。जी（ji）后缀是敬意的最小单位，去掉就是失礼。"
    },
    {
        "code": "bn_renaissance",
        "display_name": "孟加拉语 · 孟加拉文艺复兴 (1800–1930)",
        "role": "target",
        "axes": {
            "region": "IN",
            "era": "bengal_renaissance",
            "era_span": [
                1800,
                1930
            ],
            "genre": "literary_drama",
            "world_setting": "historical",
            "social_context": "colonial_city",
            "tech_level": "early_industrial"
        },
        "visual": {
            "visual_do": [
                "殖民地柱廊建筑",
                "恒河与渡船",
                "多蒂与纱丽",
                "煤气灯与马车",
                "印刷所与书房",
                "季风雨季",
                "黄麻仓库",
                "庭院式宅邸 thakur bari"
            ],
            "visual_dont": [
                "欧洲雪景",
                "工业流水线为主体",
                "东亚建筑",
                "现代摩天楼"
            ],
            "signage_rules": {
                "language": "বাংলা",
                "script": "bengali",
                "style": "孟加拉字体",
                "material": "漆木/搪瓷",
                "avoid": "纯拉丁招牌"
            },
            "palette": [
                "#8B4513",
                "#1B4D3E",
                "#D4AF37",
                "#F5F0E1",
                "赭红",
                "季风灰",
                "姜黄"
            ]
        },
        "language": {
            "code": "bn-IN",
            "register": "literary_bengali",
            "name_pattern": "given_family",
            "name_script": "bengali",
            "numerals": "bengali",
            "date_style": "calendar_year",
            "honorifics": {
                "respect": "বাবু",
                "elder_male": "দাদা",
                "elder_female": "দিদি"
            }
        },
        "description": "泰戈尔的世界。殖民与本土思想的交汇，语言处在文言与口语的分层中。"
    }
]
