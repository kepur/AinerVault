"""站位读写 —— 3D 导演台写回来的那份数据。"""
from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.api.v2 import blocking as api


def test_figures_outside_the_frame_are_rejected():
    with pytest.raises(ValidationError):
        api.FigureIn(entity_id="a", x=1.4, top=0.1, bottom=0.9, width=0.1)


def test_a_zero_width_figure_is_rejected():
    with pytest.raises(ValidationError):
        api.FigureIn(entity_id="a", x=0.5, top=0.1, bottom=0.9, width=0)


def test_medium_shots_may_put_the_feet_below_the_frame():
    """中景的腿在画外 —— 脚底 > 1 是合法的。"""
    api.FigureIn(entity_id="a", x=0.5, top=0.05, bottom=1.7, width=0.2)


def test_hand_placed_blocking_survives_rebinding():
    """3D 台手摆过的站位（source=stage）不能被重新绑定时的自动摆位盖掉。"""
    from app.pipelines import frame_compose

    src = inspect.getsource(frame_compose.bind_and_compose)
    assert '.get("source") != "stage"' in src


def test_moving_people_invalidates_the_old_frame():
    src = inspect.getsource(api.put_blocking)
    assert '"needs_regeneration"' in src


def test_new_people_cannot_be_added_from_the_stage():
    """每人的区域要带他自己的脸和外观 —— 凭空加一个人，
    那块区域只有人偶和空描述，模型会在那里画一个陌生人。"""
    src = inspect.getsource(api.put_blocking)
    assert "UNKNOWN_FIGURE" in src


def test_routes_are_registered():
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v2/shots/{shot_id}/blocking" in paths
