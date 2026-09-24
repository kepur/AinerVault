"""自动摆位 —— 多人镜的站位由人偶给，身份由分区给。

坏蛋镜 3（三人走廊）同一 seed 实测：
    叠参考图（两张脸）                    0/3 —— 三个位置全是错的人
    分区身份，底图 = 空景                  只画出 1 个人
    分区身份，底图 = 空景 + 灰人偶         3/3 —— 站位、发色、服装、动作全对
这里测的是人偶怎么摆：它错了，分区就在错的地方画对的人。
"""
from __future__ import annotations

import io

import pytest

from app.pipelines import blocking
from app.pipelines.blocking import Figure, auto_block, build_of, render_mask, render_preview


def _row(eid, pos, build=""):
    return {"entity_id": eid, "name": eid, "position": pos, "build_text": build}


class TestBuild:
    """高矮胖瘦从外观描述里读 —— 李爽「矮胖」画成和高个少年一样高，
    分区会把矮胖的身份塞进一个瘦高的人偶里。"""

    def test_stout_and_short_is_wider_and_lower(self):
        h, w = build_of("stout build with protruding belly, short stature")
        assert h < 1 and w > 1

    def test_tall_and_lanky_is_taller_and_narrower(self):
        h, w = build_of("tall and lanky male, long face")
        assert h > 1 and w < 1

    def test_no_keywords_means_average(self):
        assert build_of("round face, dark brown eyes") == (1.0, 1.0)


class TestAutoBlock:
    def test_slots_map_to_left_center_right(self):
        figs = auto_block([_row("a", "left"), _row("b", "center"), _row("c", "right")], "ws")
        xs = {f.entity_id: f.x for f in figs}
        assert xs["a"] < xs["b"] < xs["c"]

    def test_offscreen_people_are_not_drawn(self):
        figs = auto_block([_row("a", "center"), _row("b", "offscreen")], "ws")
        assert [f.entity_id for f in figs] == ["a"]

    def test_foreground_gets_a_free_spot_not_the_centre_line(self):
        """foreground 没有左右坐标 —— 放到空当里，而不是和站中间的人叠在一起。"""
        figs = auto_block([_row("a", "center"), _row("b", "foreground")], "ws")
        a, b = figs
        assert abs(a.x - b.x) > (a.width + b.width) / 2

    def test_width_accounts_for_the_frame_aspect(self):
        """肩宽按画面「宽」计、身高按「高」计 —— 漏乘宽高比，
        人偶在 800×480 上宽出 1.67 倍，三个人挤成三个方块。"""
        f = auto_block([_row("a", "center")], "fs", aspect=800 / 480)[0]
        ratio = (f.width * 800) / ((f.bottom - f.top) * 480)
        assert 0.2 < ratio < 0.35

    def test_same_depth_means_same_ground_line(self):
        """矮的人是头顶低，不是整个人往上飘。"""
        short, tall = auto_block(
            [_row("s", "left", "short stature"), _row("t", "right", "tall")], "ws")
        assert short.bottom == pytest.approx(tall.bottom)
        assert short.top > tall.top

    def test_at_most_three_figures(self):
        figs = auto_block([_row(str(i), "center") for i in range(5)], "ws")
        assert len(figs) == blocking.MAX_FIGURES

    def test_neighbours_do_not_overlap(self):
        figs = sorted(auto_block(
            [_row("a", "center_left"), _row("b", "center"), _row("c", "center_right")], "fs"),
            key=lambda f: f.x)
        for a, b in zip(figs, figs[1:]):
            assert b.x - a.x >= (a.width + b.width) / 2

    def test_figures_round_trip_through_storage(self):
        """站位要存进 params_json，以后 3D 台手摆的结果覆盖它。"""
        f = auto_block([_row("a", "center")], "ws")[0]
        assert Figure.of(f.as_dict()) == Figure.of(f.as_dict())
        assert set(f.as_dict()) >= {"entity_id", "x", "top", "bottom", "width"}


class TestRender:
    def _plate(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (800, 480), (200, 200, 200)).save(buf, format="PNG")
        return buf.getvalue()

    def test_preview_has_the_frame_size(self):
        from PIL import Image

        figs = auto_block([_row("a", "left"), _row("b", "right")], "ws")
        img = Image.open(io.BytesIO(render_preview(self._plate(), figs, 800, 480)))
        assert img.size == (800, 480)

    def test_mask_covers_its_figure_and_not_the_other_side(self):
        from PIL import Image

        left, right = auto_block([_row("a", "left"), _row("b", "right")], "ws")
        m = Image.open(io.BytesIO(render_mask(left, 800, 480))).convert("L")
        mid_y = int((left.top + left.bottom) / 2 * 480)
        assert m.getpixel((int(left.x * 800), mid_y)) > 200
        assert m.getpixel((int(right.x * 800), mid_y)) < 30


def test_regional_prompt_has_no_people_in_the_background():
    """全局条件管的正是人物区域之外 —— 在那里写「一个低着头的男孩」，
    模型就会在背景里再画一个。spike 里走廊尽头冒出的路人就是这么来的。"""
    import inspect

    from app.pipelines import frame_compose

    src = inspect.getsource(frame_compose._regional_payload)
    assert "no bystanders" in src
    assert "frame.prompt" not in src.split("scene = ")[1].split("payload")[0]
