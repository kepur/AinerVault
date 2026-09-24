"""自动摆位 —— 3D 导演台的 v0。

从表演单推出每个人在画面里的人偶站位，渲染「空景 + 灰人偶」预览与每人的区域 mask。
多人镜的首帧据此走分区身份：底图管站位，每人的区域管身份。

**为什么需要人偶。** 2026-09-24 坏蛋镜 3（三人走廊）同一 seed 实测：
    叠参考图（两张脸）                    0/3 —— 三个位置全是错的人
    分区身份，底图 = 空景                  只画出 1 个人
    分区身份，底图 = 空景 + 灰人偶         3/3 —— 站位、发色、服装全对
分区条件会给「已经站好位的人形」换上身份，但不会自己去摆位：每人一次前向，
模型想把人画哪就画哪，mask 截出来的只是那一块。人偶就是站位本身。

这里的几何是规则推出来的，不是模型猜的：站位槽 → 横向位置，
foreground／background → 景深层，景别 → 人偶大小，体型关键词 → 高矮胖瘦。
以后 3D 台手摆的结果会覆盖这里的默认值 —— 所以产出是可存储的纯数据。
"""
from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

#: 站位槽 → 身体中线的横向位置（0 = 左边缘，1 = 右边缘）
POSITION_X = {
    "far_left": 0.12, "left": 0.24, "center_left": 0.38, "center": 0.50,
    "center_right": 0.62, "right": 0.76, "far_right": 0.88,
}
#: 不在画面里，或者没有左右坐标、要另外安排横向位置的站位
DEPTH_ONLY = frozenset({"foreground", "background"})
OFF_FRAME = frozenset({"offscreen", "off_screen"})

#: 景深层 → 人偶的 (头顶, 脚底)，以画面高度为 1
_DEPTH = {"foreground": (0.10, 1.02), "mid": (0.16, 1.00), "background": (0.32, 0.82)}

#: 景别 → 人偶放大倍数（以头顶为锚点往下放）。中景只到腰，腿在画外
_SIZE_SCALE = {"els": 0.7, "ws": 0.95, "fs": 1.0, "mls": 1.35, "ms": 1.7}

#: 允许走分区身份的景别。特写只有一个人，走原来的主体路径
REGIONAL_SIZES = frozenset(_SIZE_SCALE)

#: 分区一次最多几个人（与本机工作台 limits.max_regions 一致）
MAX_FIGURES = 3

#: 体型关键词 → (身高系数, 宽度系数)。先匹配先生效
_BUILD = (
    (re.compile(r"\b(stout|stocky|chubby|plump|heavy[- ]?set|protruding belly)\b", re.I), (0.88, 1.30)),
    (re.compile(r"\bshort stature\b|\bshort\b", re.I), (0.86, 1.05)),
    (re.compile(r"\b(tall|lanky)\b", re.I), (1.08, 0.88)),
    (re.compile(r"\b(skinny|slender|thin|slim|scrawny)\b", re.I), (1.0, 0.80)),
)


@dataclass
class Figure:
    """一个人偶在画面里的位置。全部按画面比例，与分辨率无关。"""

    entity_id: str
    name: str
    x: float        # 身体中线
    top: float      # 头顶
    bottom: float   # 脚底（中景可以 > 1，表示腿在画外）
    width: float    # 肩宽

    def as_dict(self) -> dict[str, Any]:
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}

    @classmethod
    def of(cls, d: dict[str, Any]) -> "Figure":
        return cls(**{k: d[k] for k in ("entity_id", "name", "x", "top", "bottom", "width")})


def build_of(text: str | None) -> tuple[float, float]:
    """从外观描述里读体型。读不出来就是标准身材。"""
    hi, wi = 1.0, 1.0
    seen: set[int] = set()
    for i, (pattern, (h, w)) in enumerate(_BUILD):
        if i not in seen and pattern.search(text or ""):
            seen.add(i)
            hi *= h
            wi *= w
    return hi, wi


def auto_block(
    performers: Iterable[dict[str, Any]], shot_size: str, *, aspect: float = 800 / 480,
) -> list[Figure]:
    """从表演单摆人偶。

    performers：按主次排好的在场角色，每项
    `{entity_id, name, position, build_text}`。不在画面里的（offscreen）应已排除。
    """
    scale = _SIZE_SCALE.get((shot_size or "").lower(), 1.0)
    rows = [p for p in performers if str(p.get("position")) not in OFF_FRAME][:MAX_FIGURES]

    figures: list[Figure] = []
    for p in rows:
        pos = str(p.get("position") or "center")
        layer = pos if pos in DEPTH_ONLY else "mid"
        layer_top, layer_bottom = _DEPTH[layer]
        hi, wi = build_of(p.get("build_text"))
        # 先按景别缩放整个景深层：以这一层的标准头顶为锚往下放大，
        # 中景的地面线落到画外（腿出画）。**锚点是层的，不是人的** ——
        # 按各自头顶缩放的话，高矮两人的脚底会错开，像一个站在台阶上
        nominal = (layer_bottom - layer_top) * scale
        ground = layer_top + nominal
        # 再在共同的地面线上按身高往上量：矮的人是头顶低，不是整个人往上飘
        height = nominal * hi
        top = ground - height
        bottom = ground
        # 肩宽约为身高的 0.27。身高按画面「高」计、肩宽按画面「宽」计，
        # 要除以宽高比 —— 漏了这一步，人偶在 800×480 上宽出 1.67 倍，
        # 三个人挤成三个方块，区域 mask 大面积重叠
        width = height * 0.27 * wi / aspect
        x = POSITION_X.get(pos, None)
        figures.append(Figure(
            entity_id=str(p["entity_id"]), name=str(p.get("name") or ""),
            x=x if x is not None else float("nan"),
            top=max(0.0, top), bottom=bottom, width=width,
        ))

    _place_depth_only(figures)
    _separate(figures)
    return figures


def _place_depth_only(figures: list[Figure]) -> None:
    """foreground／background 没有左右坐标：放到离已占位置最远的空当。"""
    taken = [f.x for f in figures if f.x == f.x]      # 非 NaN
    for f in figures:
        if f.x == f.x:
            continue
        candidates = [0.24, 0.38, 0.5, 0.62, 0.76]
        best = max(candidates, key=lambda c: (min((abs(c - t) for t in taken), default=1.0),
                                              -abs(c - 0.5)))
        f.x = best
        taken.append(best)


def _separate(figures: list[Figure], gap: float = 0.02) -> None:
    """相邻两人不能叠在一起 —— 叠了分区 mask 就分不清谁是谁。"""
    order = sorted(figures, key=lambda f: f.x)
    for _ in range(4):
        moved = False
        for a, b in zip(order, order[1:]):
            need = (a.width + b.width) / 2 + gap
            if b.x - a.x < need:
                push = (need - (b.x - a.x)) / 2
                a.x -= push
                b.x += push
                moved = True
        for f in order:
            f.x = min(max(f.x, f.width / 2 + 0.01), 1 - f.width / 2 - 0.01)
        if not moved:
            break


# ── 渲染 ─────────────────────────────────────────────────────

_SHADE = (122, 122, 126)


def render_preview(plate: bytes, figures: list[Figure], width: int, height: int):
    """空景 + 灰人偶。返回 PNG 字节。

    人偶故意画得粗糙：头、躯干、两条腿。它只负责告诉模型「这里站着一个人、
    这么高、这么宽」，长相和衣服由分区里的那张脸决定。画得越像具体的人，
    越会和参考脸打架。
    """
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.open(io.BytesIO(plate)).convert("RGB").resize((width, height))
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # 远的先画，近的压在上面
    for f in sorted(figures, key=lambda f: f.bottom):
        _mannequin(d, f, width, height)
    layer = layer.filter(ImageFilter.GaussianBlur(1.2))
    img.paste(layer, (0, 0), layer)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mannequin(d, f: Figure, width: int, height: int) -> None:
    cx = f.x * width
    top, bottom = f.top * height, f.bottom * height
    h = bottom - top
    w = f.width * width
    shade = _SHADE + (255,)
    hr = h * 0.075
    d.ellipse([cx - hr, top, cx + hr, top + 2 * hr], fill=shade)
    t0 = top + 2 * hr + h * 0.01
    t1 = top + h * 0.52
    d.rounded_rectangle([cx - w / 2, t0, cx + w / 2, t1], radius=w * 0.25, fill=shade)
    lw = w * 0.42
    d.rounded_rectangle([cx - w / 2 + 2, t1 - 4, cx - 2, bottom], radius=lw * 0.3, fill=shade)
    d.rounded_rectangle([cx + 2, t1 - 4, cx + w / 2 - 2, bottom], radius=lw * 0.3, fill=shade)


def render_mask(f: Figure, width: int, height: int, *, pad: float = 0.35,
                feather: int = 18) -> bytes:
    """这个人的区域：人偶外框加一圈余量，边缘羽化。

    余量给手臂和姿态留空间 —— 框卡得太死，模型只能画一个立正的人；
    羽化让相邻区域平滑过渡，不出硬边。
    """
    from PIL import Image, ImageDraw, ImageFilter

    m = Image.new("L", (width, height), 0)
    half = f.width * (0.5 + pad)
    x0, x1 = (f.x - half) * width, (f.x + half) * width
    y0 = max(0.0, f.top - 0.04) * height
    y1 = min(1.0, f.bottom) * height
    ImageDraw.Draw(m).rectangle([x0, y0, x1, y1], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(feather))
    buf = io.BytesIO()
    m.save(buf, format="PNG")
    return buf.getvalue()
