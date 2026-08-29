"""成语与固定语的识别 —— 查表比让模型判更稳。

成语对翻译有两个硬性影响：

    cultural_load  成语几乎都是 high —— 它背后是典故，
                   直译过去目标读者只看到字面
    device_type    它是 idiom 类装置，重铸时该换目标文化的等价说法，
                   而不是把「破釜沉舟」译成「打破锅、沉掉船」

让模型判「这是不是成语」，四字短语和成语的界限它常常拿不准：
「推开客栈」不是成语，「破釜沉舟」是，而「雪夜奔波」介于两者之间。
判错的方向还不对称 —— 漏判一个成语，它就被当普通短语直译了。

所以内置一份高频成语表：**命中即确定**，不在表里的交给模型判。
表不求全（汉语成语三万条以上），只收文学与武侠语境里高频的那部分；
覆盖不到的仍有模型兜底，而命中的那些不会再出错。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HAN = re.compile(r"^[一-鿿]+$")

#: 高频成语。按语义域分组，便于后续按需扩充。
#: 收录标准：文学／武侠文本里常见，且**直译必失**（背后有典故或引申义）。
IDIOMS: frozenset[str] = frozenset("""
破釜沉舟 背水一战 四面楚歌 十面埋伏 声东击西 围魏救赵 釜底抽薪 暗度陈仓
兵不厌诈 出其不意 攻其不备 势如破竹 所向披靡 一鼓作气 溃不成军 丢盔弃甲
卧薪尝胆 忍辱负重 韬光养晦 深藏不露 锋芒毕露 崭露头角 后来居上 青出于蓝
塞翁失马 因祸得福 否极泰来 时来运转 命途多舛 生不逢时 怀才不遇 大器晚成
庄周梦蝶 黄粱一梦 南柯一梦 邯郸学步 刻舟求剑 守株待兔 缘木求鱼 掩耳盗铃
画蛇添足 杯弓蛇影 惊弓之鸟 草木皆兵 风声鹤唳 疑神疑鬼 杯水车薪 饮鸩止渴
唇亡齿寒 兔死狗烹 鸟尽弓藏 过河拆桥 恩将仇报 忘恩负义 落井下石 雪上加霜
雪中送炭 锦上添花 患难与共 同舟共济 肝胆相照 推心置腹 一见如故 相见恨晚
义薄云天 侠肝义胆 顶天立地 光明磊落 光风霁月 两袖清风 一尘不染 出淤泥而不染
不卑不亢 宠辱不惊 处变不惊 泰然自若 从容不迫 临危不惧 视死如归 慷慨赴义
指鹿为马 颠倒黑白 混淆是非 强词夺理 巧言令色 阳奉阴违 两面三刀 笑里藏刀
口蜜腹剑 心怀叵测 居心不良 别有用心 图谋不轨 狼子野心 包藏祸心 蛇蝎心肠
风声鹤唳 山雨欲来 剑拔弩张 一触即发 千钧一发 危在旦夕 命悬一线 九死一生
死里逃生 化险为夷 转危为安 绝处逢生 峰回路转 柳暗花明 豁然开朗 拨云见日
不动声色 不露痕迹 悄无声息 神不知鬼不觉 来去无踪 神出鬼没 行踪飘忽
装聋作哑 佯装不知 明知故问 心照不宣 心领神会 会心一笑 相视一笑 不言而喻
一言难尽 欲言又止 支吾其词 含糊其辞 王顾左右而言他 顾左右而言他
盛气凌人 咄咄逼人 得理不饶人 不依不饶 寸步不让 针锋相对 剑走偏锋
高深莫测 讳莫如深 讳言 三缄其口 守口如瓶 缄默不语 沉默寡言
一诺千金 言而有信 说一不二 一言九鼎 掷地有声 斩钉截铁 干净利落
拖泥带水 优柔寡断 举棋不定 犹豫不决 瞻前顾后 患得患失 畏首畏尾
心急如焚 忐忑不安 坐立不安 如坐针毡 芒刺在背 度日如年 望眼欲穿
喜出望外 大喜过望 欣喜若狂 手舞足蹈 眉飞色舞 兴高采烈 神采飞扬
垂头丧气 灰心丧气 心灰意冷 万念俱灰 心如死灰 悲痛欲绝 肝肠寸断
怒不可遏 勃然大怒 火冒三丈 咬牙切齿 义愤填膺 拍案而起 拂袖而去
目瞪口呆 瞠目结舌 哑口无言 面面相觑 不知所措 手足无措 张口结舌
风尘仆仆 跋山涉水 长途跋涉 餐风露宿 披星戴月 日夜兼程 马不停蹄
人困马乏 精疲力竭 筋疲力尽 力不从心 强弩之末 强撑 苦苦支撑
血雨腥风 腥风血雨 尸横遍野 血流成河 惨不忍睹 触目惊心 骇人听闻
不动如山 稳如泰山 岿然不动 纹丝不动 屹立不倒 坚如磐石
明察秋毫 洞若观火 一目了然 了如指掌 心知肚明 心中有数 胸有成竹
不speak
""".split()) - {"不speak"}

#: 固定俗语与歇后语式表达。不是成语但同样直译必失。
SET_PHRASES: frozenset[str] = frozenset("""
江湖险恶 人在江湖身不由己 无巧不成书 冤家路窄 不打不相识
行走江湖 落草为寇 劫富济贫 替天行道 快意恩仇 恩怨分明
明人不做暗事 冤有头债有主 一码归一码 井水不犯河水 各人自扫门前雪
识时务者为俊杰 好汉不吃眼前亏 留得青山在不怕没柴烧 三十六计走为上
""".split())


@dataclass(frozen=True)
class IdiomVerdict:
    kind: str            # "idiom" | "set_phrase" | "four_char"
    confidence: float
    reason: str

    @property
    def decisive(self) -> bool:
        """查表命中是确定的；四字格只是提示。"""
        return self.confidence >= 0.9


def classify(text: str) -> IdiomVerdict | None:
    """判断一段文字是不是成语／固定语。

    三档：
      表内成语    确定，cultural_load 直接给 high
      表内俗语    确定
      四字汉字格  仅提示 —— 「推开客栈」也是四字，靠结构分不出来，
                  所以不下结论，只标出来让模型多看一眼
    """
    t = (text or "").strip()
    if not t:
        return None
    if t in IDIOMS:
        return IdiomVerdict("idiom", 0.98,
                            f"「{t}」是成语，背后有典故 —— 直译只剩字面")
    if t in SET_PHRASES:
        return IdiomVerdict("set_phrase", 0.95, f"「{t}」是固定俗语，直译必失")
    if len(t) == 4 and _HAN.match(t):
        return IdiomVerdict("four_char", 0.4,
                            "四字汉字格，可能是成语 —— 但「推开客栈」也是四字，"
                            "结构分不出来，需要判断语义")
    return None


def find_in_text(text: str, limit: int = 20) -> list[tuple[str, str]]:
    """扫出文本里出现的成语与俗语。返回 (词, 类型)。

    给装置抽取当线索用：统计层先把确定的挑出来，
    模型只需要判它们的作用，不必再花力气去认。
    """
    if not text:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for bucket, kind in ((IDIOMS, "idiom"), (SET_PHRASES, "set_phrase")):
        for word in bucket:
            if word in text and word not in seen:
                seen.add(word)
                out.append((word, kind))
                if len(out) >= limit:
                    return out
    return out


def brief_for_prompt(hits: list[tuple[str, str]]) -> str:
    """把扫到的成语写进提示词。没扫到就不占位置。"""
    if not hits:
        return ""
    lines = [
        "【已识别的成语／固定语】这些直译必失 —— "
        "它们的 cultural_load 是 high，装置类型是 idiom，"
        "重铸时换目标文化的等价说法，不要逐字翻："
    ]
    lines += [f"  {w}（{k}）" for w, k in hits]
    return "\n".join(lines)
