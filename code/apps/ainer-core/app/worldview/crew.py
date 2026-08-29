"""影视工种的产出规格 —— 把专业判据写成可执行的约束。

v1 的「影视团队」是权限绑定加一两句角色口吻：
「以导演视角输出镜头决策」。那是角色扮演思路 ——
给模型一个身份，指望它自己知道该怎么做。

实测下来这不成立。同一道灯光题：
    qwen3.8-27b   「低角度冷月光自窗棂斜入，窄束硬光只扫过腰刀与膝部轮廓」
    gpt-oss-20b   「柔和侧光」「神秘紧张」
后者对图像生成没有任何指导价值 —— 它没说光从哪来、有多硬、照到什么。
而没人告诉过它「柔和侧光」不算一个灯光方案。

所以每个工种的规格包含四件事：
    dimensions  必填维度。缺一项就不算完成，而不是「尽量填」
    criteria    合格判据。什么样的描述能拿去生成
    bad         典型的无效描述。**明确列出来**比说「要具体」有用得多
    lexicon     该工种的术语。给弱模型一份词汇表，它才写得出专业描述

规格与提示词共用同一份定义 —— 分开写会变成
「按一套标准生成、按另一套验收」。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CrewSpec:
    """一个工种的产出规格。"""

    role: str
    display_name: str
    #: 这个工种为什么存在 —— 写给模型看，让它知道自己在解决什么问题
    purpose: str
    dimensions: tuple[str, ...]
    criteria: tuple[str, ...]
    bad: tuple[str, ...]
    #: 术语表：{类别: {中文术语: English term}}。
    #:
    #: **双语不是为了好看，是三件事一次解决：**
    #:   给模型的词汇 —— 弱模型有了词表才写得出专业描述
    #:   验收白名单   —— 「中近景」这种精确回答不会因为太短被判缺失
    #:   英译对照     —— 出图那一份直接查表，不必让模型现翻。
    #:                   现翻会得到「medium close shot」「medium close-up」
    #:                   两种写法混用，而下游按字面匹配的工具会当成两个值
    lexicon: dict[str, dict[str, str]] = field(default_factory=dict)

    def terms(self) -> list[str]:
        """全部中文术语，用作验收白名单。"""
        return [t for group in self.lexicon.values() for t in group]

    def glossary(self) -> dict[str, str]:
        """中文 → English 的扁平对照表。"""
        return {k: v for group in self.lexicon.values() for k, v in group.items()}

    def brief(self, *, bilingual: bool = False) -> str:
        """组装成提示词片段。

        bilingual 时把术语表按「中文 = English」给出，并要求两份产出 ——
        中文那份给人审核，英文那份给图像／视频模型。
        **图像模型不认中文**：喂中文出来的是一整版汉字纹样，不是画面。
        """
        parts = [f"【{self.display_name}】{self.purpose}", "必填维度（缺一项即不合格）："]
        parts += [f"  · {d}" for d in self.dimensions]
        parts.append("合格判据：")
        parts += [f"  · {c}" for c in self.criteria]
        parts.append("以下写法一律不合格 —— 它们对生成没有指导价值：")
        parts += [f"  ✗ {b}" for b in self.bad]
        if self.lexicon:
            parts.append("可用术语（左中文，右英文；两边要一一对应）："
                         if bilingual else "可用术语：")
            for k, group in self.lexicon.items():
                if bilingual:
                    pairs = "、".join(f"{cn}={en}" for cn, en in group.items())
                else:
                    pairs = "、".join(group)
                parts.append(f"  {k}：{pairs}")
        if bilingual:
            parts.append(
                "\n**每个维度写两份**：\n"
                "  <维度key>      中文，给人审核\n"
                "  <维度key>_en   英文，**直接拼进出图提示词**\n"
                "\n为什么要两份：**图像模型不认中文** —— "
                "把中文描述喂给它，出来的是一整版汉字纹样，不是画面（实测过）。\n"
                "而中文那份是给人看的：审片的人要能一眼看懂并改。\n"
                "英文那份的写法：\n"
                "  · 术语一律用上表右侧的英文，不要自己另译 ——\n"
                "    「medium close shot」和「medium close-up」混用，\n"
                "    下游按字面匹配的工具会当成两个不同的值\n"
                "  · 写成逗号分隔的短语，不要写句子，不要写 The camera is…\n"
                "  · 不要出现人名 —— 图像模型读不出人名是谁，\n"
                "    用「the seated man」「the figure on the right」指代\n"
                "  · 两份内容必须一致，不是各写各的")
        return "\n".join(parts)


CINEMATOGRAPHY = CrewSpec(
    role="cinematography",
    display_name="摄影",
    purpose=(
        "决定观众从哪里看、看多少、怎么跟着看。"
        "分镜图能不能用，八成取决于这一层说得够不够死。"
    ),
    dimensions=(
        "景别：从大远景到大特写，明确到具体一级",
        "机位高度：低于视平线／平视／高于视平线／俯拍／仰拍",
        "机位方位：正面／四分之三侧／正侧／背侧／背面",
        "焦段与景深：广角带环境还是长焦压缩空间，前后景虚实到什么程度",
        "运镜：起幅与落幅各是什么，中间怎么走，速度快慢",
        "构图：主体在画面什么位置，占多大，前景有没有遮挡",
    ),
    criteria=(
        "运镜必须写清**起幅与落幅**，只写「推镜」等于没说 —— "
        "从哪推到哪、推多近，决定了首尾帧长什么样",
        "机位要能换算成一句提示词：「低机位仰拍，镜头贴近地面」而不是「有力的角度」",
        "景深要说明**谁清晰谁模糊**，这是引导注意力的主要手段",
        "静止镜头也要明说是静止的 —— 不写，视频模型会自己加运动",
    ),
    bad=(
        "「电影感的镜头」「有张力的构图」—— 形容感受不是描述画面",
        "「适当的景别」「合适的机位」—— 没有做出选择",
        "「镜头缓缓移动」—— 没说从哪到哪，落幅不确定",
        "「唯美的光影」—— 那是灯光的事，且同样没有信息",
    ),
    lexicon={
        "景别": {
            "大远景": "extreme wide shot", "远景": "wide shot",
            "全景": "full shot", "中全景": "medium full shot",
            "中景": "medium shot", "中近景": "medium close-up",
            "近景": "close shot", "特写": "close-up",
            "大特写": "extreme close-up",
        },
        "运镜": {
            "固定": "static locked-off camera", "推": "dolly in",
            "拉": "dolly out", "摇": "pan", "移": "tracking shot",
            "跟": "follow shot", "升": "crane up", "降": "crane down",
            "环绕": "orbit around subject", "手持晃动": "handheld shake",
            "变焦推拉": "zoom push-pull", "斯坦尼康": "steadicam glide",
        },
        "机位高度": {
            "低机位": "low camera position", "低于视平线": "below eye level",
            "平视": "eye level", "高机位": "high camera position",
            "高于视平线": "above eye level", "俯拍": "high angle looking down",
            "仰拍": "low angle looking up", "过肩": "over-the-shoulder",
            "主观视角": "point-of-view shot", "顶拍": "top-down overhead",
        },
        # 方位原来只写在维度描述里，没进术语表 —— 于是「正面」这种
        # 完全合格的回答因为太短被判成缺失。术语表同时是验收白名单，
        # 维度里列举的选项必须在这里也有一份
        "机位方位": {
            "正面": "frontal view", "四分之三侧": "three-quarter view",
            "正侧": "profile view", "背侧": "rear three-quarter view",
            "背面": "from behind", "过肩反打": "reverse over-the-shoulder",
        },
        "构图": {
            "居中": "centred composition", "三分线": "rule of thirds",
            "对称": "symmetrical composition", "框中框": "frame within a frame",
            "前景遮挡": "foreground occlusion", "留白": "negative space",
            "对角线": "diagonal composition", "引导线": "leading lines",
        },
        "焦段": {
            "超广角 14-24mm": "ultra-wide 14-24mm lens",
            "广角 24-35mm": "wide 24-35mm lens",
            "标准 50mm": "standard 50mm lens",
            "中长焦 85mm": "short telephoto 85mm lens",
            "长焦 135mm+": "telephoto 135mm lens",
            "微距": "macro lens",
        },
        "景深": {
            "浅景深": "shallow depth of field",
            "深景深": "deep focus", "前景虚化": "blurred foreground",
            "背景虚化": "bokeh background", "焦点转移": "rack focus",
        },
    },
)

LIGHTING = CrewSpec(
    role="lighting",
    display_name="灯光",
    purpose=(
        "决定画面的时间、天候与情绪。同一个场景同一个机位，"
        "换一套光就是另一场戏。"
    ),
    dimensions=(
        "主光：从哪个方位来、硬还是柔、强度",
        "补光：有没有、来自哪里、把暗部提到什么程度",
        "轮廓光／逆光：有没有、勾出什么",
        "画内光源：画面里能看见的灯、火、窗 —— 它们决定了光的合理性",
        "色温与色彩倾向：冷暖、有没有色偏",
        "反差：高反差硬调还是低反差平光",
    ),
    criteria=(
        "主光必须写**方位 + 光质**：「左前方 45 度硬光」而不是「侧光」",
        "夜戏要指明**光从哪来** —— 月光、火把、窗内漏出的灯，"
        "没有来源的夜戏会生成出「打了灯的黑夜」",
        "色温给数值或给具体参照（烛光 1800K／月光偏青 5600K），不要只写「暖」",
        "反差要说明**暗部还剩多少细节**，那决定了画面的调性",
    ),
    bad=(
        "「柔和侧光」—— 没说方位、没说强度、没说照到什么",
        "「氛围灯光」「神秘的光影」—— 形容词不是方案",
        "「自然光」—— 什么时辰、什么天候、从哪个窗进来",
        "「明暗对比强烈」—— 没说亮部在哪暗部在哪",
    ),
    lexicon={
        "光位": {
            "顺光": "frontal key light", "前侧光": "45-degree key light",
            "正侧光": "side light", "后侧光": "rear side light",
            "逆光": "backlight rim", "顶光": "top light",
            "底光": "underlight from below", "眼神光": "catchlight in the eyes",
            "伦勃朗光": "Rembrandt lighting",
        },
        "光质": {
            "硬光": "hard light with crisp shadows", "柔光": "soft diffused light",
            "散射": "scattered ambient light", "点状": "focused spot",
            "泛光": "broad flood light", "束光": "narrow beam",
        },
        "反差": {
            "高反差": "high contrast", "低反差": "low contrast",
            "硬调": "hard chiaroscuro", "软调": "soft gradation",
            "中间调": "mid-key balance", "低调": "low-key lighting",
            "高调": "high-key lighting",
        },
        "画内光源": {
            "烛火": "candle flame", "油灯": "oil lamp", "火把": "burning torch",
            "灯笼": "paper lantern", "月光": "moonlight", "窗光": "window light",
            "炉火": "hearth fire", "煤气灯": "gas lamp",
            "电灯": "electric bulb", "practical": "practical light in frame",
        },
        "色温": {
            "烛光 1800K": "1800K candlelight",
            "钨丝灯 2700K": "2700K tungsten",
            "日出 3200K": "3200K sunrise warmth",
            "日光 5600K": "5600K daylight",
            "阴天 6500K": "6500K overcast",
            "月光 7000K 偏青": "7000K cool moonlight",
        },
    },
)

PRODUCTION_DESIGN = CrewSpec(
    role="production_design",
    display_name="美术",
    purpose=(
        "决定画面里有什么东西、什么材质、什么颜色。"
        "世界观的可信度几乎全靠这一层承担。"
    ),
    dimensions=(
        "空间：场所类型、大小、结构特征",
        "陈设：画面里能看见的家具器物，按前中后景分别列",
        "材质：主要表面是什么 —— 木、石、砖、织物、金属",
        "色彩：主色调、点缀色、整体饱和度",
        "年代记号：能一眼看出时代的物件",
        "使用痕迹：新的还是旧的，有没有磨损、灰尘、修补",
    ),
    criteria=(
        "陈设要**具体到物**：「柜台上一把算盘、一摞账簿、半盏油灯」"
        "而不是「柜台上的物品」",
        "材质决定质感与打光反应，必须写 —— 「粗麻」和「细绸」在画面上完全不同",
        "年代记号是世界观落地的锚：写出那个年代**特有**的东西，"
        "而不是任何年代都有的桌椅",
        "使用痕迹是真实感的来源。全新的场景看着像样板间",
    ),
    bad=(
        "「古色古香的陈设」「充满年代感」—— 没有一件具体的东西",
        "「中式风格」—— 哪个朝代、哪个阶层、哪个地域",
        "「装饰精美」—— 装饰的是什么、什么纹样、什么材质",
    ),
    lexicon={
        "材质": {
            "原木": "raw timber", "漆木": "lacquered wood",
            "青砖": "grey fired brick", "夯土": "rammed earth",
            "石板": "stone slab", "粗麻": "coarse hemp cloth",
            "细绸": "fine silk", "皮革": "tanned leather",
            "生铁": "cast iron", "黄铜": "brass", "陶": "earthenware",
            "瓷": "porcelain", "毛毡": "felt", "藤编": "woven rattan",
        },
        "痕迹": {
            "崭新": "pristine and unused", "半旧": "moderately worn",
            "磨损": "worn and abraded", "斑驳": "mottled and patchy",
            "开裂": "cracked surface", "积尘": "dust-covered",
            "烟熏": "smoke-blackened", "修补过": "visibly repaired",
            "水渍": "water-stained", "锈蚀": "rusted",
        },
        "色调": {
            "暖调": "warm palette", "冷调": "cool palette",
            "中性": "neutral palette", "低饱和": "desaturated",
            "高饱和": "saturated", "单色": "monochromatic",
            "互补色": "complementary colour scheme",
            "土色系": "earth tones", "灰调": "muted greys",
        },
    },
)

SOUND = CrewSpec(
    role="sound",
    display_name="声音",
    purpose=(
        "决定观众听到什么。环境声撑起空间感，音效点强调动作，"
        "对白的音色与语气承载人物关系。"
    ),
    dimensions=(
        "环境底噪：这个空间持续存在的声音，以及它暗示的空间大小",
        "音效点：画面里哪些动作要出声，出在什么时间点",
        "对白：谁说、用什么音色、什么语气、什么语速",
        "画外声：画面外发生了什么声音 —— 它常常比画内更重要",
        "静默：有没有刻意的无声，无声之前和之后是什么",
        "配乐：要不要、什么情绪、从哪进哪出",
    ),
    criteria=(
        "环境底噪要写出**空间感**：「空旷院落，脚步有回声」"
        "而不是「安静的环境」",
        "音效点要绑定**具体动作与时刻**：「第 2 秒，油布被掀开的窸窣」",
        "对白必须绑定音色 —— 同一个角色全片是同一个音色，"
        "换了音色观众会当成换了人",
        "语气要写得能指导配音：「压着嗓子、气声、句尾往下沉」"
        "而不是「紧张地说」",
        "画外声要说明**方位与距离**，那决定了它在混音里的位置",
    ),
    bad=(
        "「紧张的音乐」「合适的音效」—— 没有可执行的信息",
        "「环境音」—— 什么环境、什么声音、多大",
        "「他紧张地说」—— 紧张在声音上表现为什么，配音演员没法照做",
    ),
    lexicon={
        "环境": {
            "室内混响": "indoor reverb", "空旷回声": "cavernous echo",
            "闷（软装吸声）": "damped, soft-furnished room",
            "风声": "wind", "雨声": "rain", "虫鸣": "insect chirping",
            "远处人声": "distant voices", "市集喧闹": "market bustle",
            "更漏": "night watch drum", "炉火噼啪": "crackling fire",
            "脚步回声": "footstep echo",
        },
        "语气": {
            "压低嗓子": "hushed, lowered voice", "气声": "breathy",
            "沙哑": "hoarse", "清亮": "clear and bright",
            "颤抖": "trembling", "平直": "flat and even",
            "上扬": "rising intonation", "尾音下沉": "falling sentence ending",
            "咬字用力": "hard articulation", "含混": "slurred",
        },
        "语速": {
            "极慢": "very slow", "缓": "slow", "常速": "normal pace",
            "快": "fast", "急促": "hurried", "断续": "halting",
        },
        "音效": {
            "点睛音": "accent hit", "拟音": "foley",
            "画外音": "off-screen sound", "混响尾巴": "reverb tail",
            "突然静默": "sudden silence",
        },
    },
)

EDITING = CrewSpec(
    role="editing",
    display_name="剪辑",
    purpose="决定这一镜多长、怎么进怎么出，以及它与前后镜的关系。",
    dimensions=(
        "时长：这一镜占多少秒，依据是什么",
        "入点：从哪个动作／状态开始",
        "出点：切在哪个动作／状态上",
        "转场：与下一镜之间是硬切、叠化、淡入淡出还是匹配剪辑",
        "节奏关系：比前一镜快还是慢，为什么",
    ),
    criteria=(
        "时长要有依据：对白镜看语音长度，动作镜看动作完成度，"
        "空镜看情绪需要停留多久",
        "出点要切在**动作中**而不是动作做完之后 —— "
        "切在完成之后，节奏会拖",
        "转场默认硬切。用叠化或淡出必须说明为什么（时间跳跃、情绪收束）",
    ),
    bad=(
        "「适当时长」「根据需要」—— 没有做出决定",
        "「流畅转场」—— 哪种转场",
    ),
    lexicon={
        "转场": {
            "硬切": "hard cut", "叠化": "cross dissolve", "淡入": "fade in",
            "淡出": "fade out", "白闪": "flash to white", "黑场": "cut to black",
            "匹配剪辑": "match cut", "跳切": "jump cut", "划变": "wipe",
            "声音先入": "J-cut, sound leads", "画面先入": "L-cut, image leads",
        },
        # 术语表同时是验收白名单 —— 维度里期待的那种回答
        # 必须在这里有一份，否则「切在动作中」这种合格答案会被判缺失
        "切点": {
            "切在动作中": "cut on action", "切在静止": "cut on stillness",
            "切在视线": "cut on eyeline", "切在声音": "cut on sound cue",
            "留白后切": "cut after a beat of held silence",
        },
        "节奏": {
            "比前镜快": "faster than the previous shot",
            "比前镜慢": "slower than the previous shot",
            "同速": "same tempo", "加速": "accelerating",
            "减速": "decelerating", "骤停": "abrupt stop",
        },
        "入点": {
            "动作起始": "starts at the beginning of the action",
            "静止起幅": "opens on a static hold",
            "入画": "subject enters frame",
            "已在进行中": "action already underway",
        },
    },
)


COSTUME_MAKEUP = CrewSpec(
    role="costume_makeup",
    display_name="服化",
    purpose=(
        "决定人物穿什么、脸上是什么状态。"
        "**它是观众判断身份与处境的最快通道** —— "
        "一件衣服的料子与磨损，比三句台词更快说清这个人是谁、过得怎么样。"
    ),
    dimensions=(
        "形制：衣服的款式与结构，属于哪个年代哪个阶层",
        "层次：从里到外几层，露出多少，怎么系怎么束",
        "材质与工艺：什么料子、什么织法、有没有刺绣或缝补",
        "磨损与污渍：新旧程度、磨在哪里、脏在哪里 —— 磨损的位置说明这个人做什么活",
        "妆容：肤色状态、有没有伤病痕迹、这一刻的汗与尘",
        "发式与毛发：怎么梳怎么束、须髯状态、这一刻乱不乱",
    ),
    criteria=(
        "**磨损要长在对的地方**。常年握刀的人磨在虎口与右肩，"
        "赶车的磨在膝盖与臀部，写字的磨在右袖口。"
        "磨在错的地方，观众说不出哪里不对，但会觉得假",
        "层次要说明**露出关系**：中衣露不露领、外袍系到哪一颗 —— "
        "这决定了画面上能看见几种颜色几种料子",
        "妆容要写**这一刻的状态**而不是长相：长相属于人物素材，"
        "这一层管的是他刚跑完还是刚睡醒",
        "阶层与年代必须落在具体物件上：料子的等级、纹样的规格、"
        "有没有配饰 —— 而不是「看上去很有身份」",
    ),
    bad=(
        "「古装」「传统服饰」—— 哪个年代、哪个阶层、什么形制",
        "「衣着朴素」—— 料子是什么、旧到什么程度、哪里破了",
        "「妆容自然」—— 这一层不写化妆技法，写人物此刻的脸是什么状态",
        "「一身华服」—— 华在哪：料子、纹样、配饰、层数",
    ),
    lexicon={
        "形制": {
            "圆领袍": "round-collar robe", "交领襦": "cross-collar tunic",
            "短打": "short work jacket and trousers",
            "直裰": "straight-cut scholar robe", "褙子": "long open vest",
            "劲装": "fitted martial outfit", "长衫": "long gown",
            "军服": "military uniform", "制服": "service uniform",
            "西装三件套": "three-piece suit", "工装": "workwear",
        },
        "层次": {
            "单层": "single layer", "中衣外袍": "inner robe under outer robe",
            "内衬外罩": "lining under overcoat",
            "束腰": "belted at the waist", "敞开": "worn open",
            "挽袖": "sleeves rolled up", "披挂": "draped over the shoulders",
        },
        "料子": {
            "粗麻": "coarse hemp", "细麻": "fine linen", "棉布": "cotton cloth",
            "绸": "silk", "缎": "satin", "锦": "brocade", "毛呢": "wool cloth",
            "皮": "leather", "毛皮": "fur", "葛布": "kudzu cloth",
        },
        "磨损部位": {
            "袖口磨白": "cuffs worn pale", "肘部起球": "pilled elbows",
            "领口发黑": "collar darkened with grime",
            "下摆磨须": "frayed hem", "膝部鼓包": "knees bagged out",
            "虎口老茧": "callused web of the hand",
            "右肩压痕": "pressure mark on the right shoulder",
        },
        "妆容状态": {
            "面色红润": "flushed complexion", "面色蜡黄": "sallow complexion",
            "风吹日晒": "weather-beaten skin", "满面尘灰": "dust-covered face",
            "汗湿鬓角": "sweat-damp temples", "唇色发白": "pale lips",
            "眼下青黑": "dark under-eyes", "淤青": "bruised",
            "新伤": "fresh wound", "旧疤": "old scar",
        },
        "发式": {
            "束发": "hair tied up", "披发": "hair loose",
            "发髻": "topknot", "马尾": "ponytail", "短发": "short hair",
            "凌乱": "dishevelled", "梳得服帖": "neatly combed",
            "花白": "greying", "光头": "shaven head",
        },
    },
)

COLOR_GRADING = CrewSpec(
    role="color_grading",
    display_name="调色",
    purpose=(
        "决定整段画面的色彩取向与影调。"
        "**它是唯一能跨镜统一观感的一层** —— 每一镜单独看都还行，"
        "调色不统一，连起来就像不同的片子剪在一起。"
    ),
    dimensions=(
        "整体取向：这一段的 look 是什么，一句话说清",
        "影调曲线：黑位提不提、高光滚不滚、中间调往哪压",
        "色彩偏移：阴影偏什么、高光偏什么 —— 这是 look 的主要来源",
        "饱和处理：整体饱和度，以及有没有哪个颜色单独提或压",
        "肤色处理：肤色往哪偏、要不要保护 —— 肤色错了观众第一眼就出戏",
        "颗粒与质感：胶片模拟、颗粒粗细、有没有光晕或色散",
    ),
    criteria=(
        "**必须与灯光的色温对得上**。灯光写了 2700K 钨丝灯，"
        "调色再往冷里压，画面会变成一种谁也没见过的颜色",
        "色彩偏移要写**方向与程度**：「阴影偏青，中度」"
        "而不是「冷色调处理」",
        "肤色是底线：无论 look 多重，肤色不能偏到发绿或发紫 —— "
        "观众对别的颜色宽容，对人脸不宽容",
        "同一场戏的调色必须一致。跨场可以变，**变要有理由**"
        "（时间推进、情绪转折、闪回）",
    ),
    bad=(
        "「电影感调色」「高级灰」—— 没有任何可执行的参数",
        "「冷色调」—— 冷在阴影还是高光，冷多少",
        "「提升氛围」—— 这不是调色的描述",
    ),
    lexicon={
        "取向": {
            "青橙": "teal and orange", "漂白旁路": "bleach bypass",
            "褪色": "faded film look", "高对比黑白": "high-contrast monochrome",
            "暖金": "warm golden", "冷蓝夜景": "cool blue night",
            "泛黄旧照": "yellowed vintage photo",
            "自然还原": "natural, minimal grade",
        },
        "影调": {
            "提黑位": "lifted blacks", "压黑位": "crushed blacks",
            "高光滚降": "rolled-off highlights", "高光硬切": "clipped highlights",
            "中间调压暗": "darkened midtones", "中间调提亮": "lifted midtones",
            "S 曲线": "S-curve contrast",
        },
        "色偏": {
            "阴影偏青": "cyan-shifted shadows", "阴影偏蓝": "blue-shifted shadows",
            "阴影偏绿": "green-shifted shadows", "高光偏黄": "yellow-shifted highlights",
            "高光偏橙": "orange-shifted highlights", "高光偏粉": "pink-shifted highlights",
            "整体偏暖": "overall warm shift", "整体偏冷": "overall cool shift",
        },
        "饱和": {
            "整体降饱和": "desaturated overall", "整体提饱和": "saturated overall",
            "肤色保护": "protected skin tones", "红色单独提": "boosted reds only",
            "绿色压暗": "muted greens", "选择性去色": "selective desaturation",
        },
        "质感": {
            "35mm 颗粒": "35mm film grain", "16mm 粗颗粒": "coarse 16mm grain",
            "无颗粒": "clean digital, no grain", "轻微光晕": "subtle halation",
            "色散": "chromatic aberration", "暗角": "vignette",
        },
    },
)

VFX = CrewSpec(
    role="vfx",
    display_name="视效",
    purpose=(
        "决定画面里哪些东西不是拍出来的，以及它们怎么与实拍接上。"
        "**接不上比没有更糟** —— 观众看不出是特效才算成功，"
        "看出来了，这一镜就白拍了。"
    ),
    dimensions=(
        "需求判定：这一镜要不要视效。**不要就明说不要** —— "
        "多数镜头不需要，而无中生有的特效是成本也是风险",
        "元素：具体加什么、去什么、换什么",
        "接合：与实拍怎么衔接 —— 边缘、遮挡关系、谁在谁前面",
        "光照匹配：元素的光从哪来，必须与灯光那一层写的一致",
        "运动匹配：元素要不要跟着相机动，运动模糊对不对得上",
        "时间性：什么时候出现、持续多久、怎么消失",
    ),
    criteria=(
        "**光照匹配是特效成败的第一位**。加一团火却不给周围的东西"
        "补上火光，观众立刻看出这团火是贴上去的",
        "遮挡关系必须写清谁在谁前面 —— 元素飘在人物前面还是后面，"
        "决定了它是在场景里还是浮在画面上",
        "运动模糊要与相机运动一致：相机在摇，静止的合成元素却是清晰的，"
        "那一眼就假",
        "**能实拍就实拍**。烛火、雨、尘埃这类东西，"
        "描述成实拍元素交给图像模型，比标成特效更可信",
    ),
    bad=(
        "「加一些特效」「炫酷的效果」—— 加什么、在哪、多久",
        "「魔法光效」—— 什么颜色、什么形态、光往哪照",
        "「后期处理」—— 那不是视效描述",
    ),
    lexicon={
        "类型": {
            "无": "no visual effects required",
            "合成元素": "composited element", "粒子": "particle simulation",
            "环境扩展": "set extension", "清除": "clean-up removal",
            "替换": "element replacement", "数字替身": "digital double",
            "流体": "fluid simulation", "破碎": "destruction simulation",
        },
        "元素": {
            "火": "fire", "烟": "smoke", "雾": "fog", "雨": "rain",
            "雪": "snow", "尘埃": "dust motes", "火星": "embers",
            "呼出的白气": "visible breath", "水花": "water splash",
            "光束": "light shaft", "血迹": "blood",
        },
        "接合": {
            "元素在前景": "element in foreground",
            "元素在背景": "element in background",
            "元素绕过主体": "element wraps behind the subject",
            "羽化边缘": "feathered edges", "景深匹配": "depth-of-field matched",
            "运动模糊匹配": "motion-blur matched",
            "接触阴影": "contact shadow grounding the element",
        },
        "光照": {
            "元素自发光": "element is self-illuminating",
            "受主光照亮": "lit by the key light",
            "在实拍上留光": "element casts light onto the plate",
            "无额外光": "no added illumination",
        },
    },
)

#: 全部工种。**顺序即生成顺序** —— 后面的工种能看到前面的产出。
#:
#: 排序不是随意的，是按依赖关系：
#:   摄影   先定机位与景别，别人才知道画面里有什么
#:   灯光   要知道机位才知道光从哪来会穿帮
#:   美术   要知道景别才知道该细化到什么程度
#:   服化   要知道景别 —— 大特写要写到毛孔，全景写到轮廓就够
#:   视效   要知道灯光才能匹配光照，那是特效成败的第一位
#:   调色   **必须排在灯光之后** —— 它是对灯光结果的再处理，
#:          灯光写了 2700K，调色再往冷压就得到一种谁也没见过的颜色
#:   声音   要知道剪辑定的时长才知道音效点落在第几秒
#:   剪辑   最后定时长与切点，它要看完前面所有人的产出
CREW: tuple[CrewSpec, ...] = (
    CINEMATOGRAPHY, LIGHTING, PRODUCTION_DESIGN, COSTUME_MAKEUP,
    VFX, COLOR_GRADING, EDITING, SOUND,
)
CREW_BY_ROLE: dict[str, CrewSpec] = {c.role: c for c in CREW}


def brief_for(role: str) -> str:
    spec = CREW_BY_ROLE.get(role)
    return spec.brief() if spec else ""


def all_roles() -> list[str]:
    return [c.role for c in CREW]
