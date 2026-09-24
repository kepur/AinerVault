"""画布（ainer-studio）用的聚合接口与前端入口。"""
from __future__ import annotations

import inspect


def test_routes_are_registered():
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    for p in ("/api/v2/studio/chapters/{chapter_id}/plans",
              "/api/v2/studio/plans/{plan_id}/board",
              "/api/v2/studio/plans/{plan_id}/cast",
              "/studio", "/studio/{path:path}"):
        assert p in paths, p


def test_board_can_show_any_plan_not_just_the_latest():
    """/storyboard 只认「激活剧本的最新版本计划」—— 坏蛋第一章因此永远显示那份
    2 镜试片，215 镜的正式分镜在审稿页上根本打不开。画布要能指定看哪一份。"""
    from app.api.v2 import studio

    sig = inspect.signature(studio.plan_board)
    assert "plan_id" in sig.parameters


def test_the_studio_route_cannot_escape_its_folder():
    """/studio/{path} 直接读盘 —— 必须挡住 ../ 之类的路径，只许读构建目录里的文件。"""
    from app import main

    src = inspect.getsource(main.studio_page)
    assert "_STUDIO.resolve() in target.parents" in src


def test_cast_uses_the_epoch_actually_used_for_frames():
    """资产面板上的人必须是出图时真正用的那一期参考集（同一个人不同时期衣着不同）。"""
    from app.api.v2 import studio

    assert "resolve_epoch" in inspect.getsource(studio.plan_cast)
