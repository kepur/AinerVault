"""后台轮询 —— 回调丢了的任务靠它收尾。

契约说轮询兜底「应由定时任务每分钟调一次」，而这个定时任务从来没人建：
core 一重启，正在出的图和视频就再也收不到结果，规格停在「生成中」。
"""
from __future__ import annotations

import inspect

from app.workers import poller


class _Task:
    def __init__(self, status):
        self.status = status


def test_counts_only_tasks_that_actually_settled(monkeypatch):
    """查了几个、收尾了几个要分开报 —— 查了没结果不算收尾。"""
    from app.capability import service
    from app.models import TaskStatus

    tasks = [_Task(TaskStatus.running), _Task(TaskStatus.running),
             _Task(TaskStatus.running)]
    outcome = iter([TaskStatus.succeeded, TaskStatus.running, TaskStatus.failed])

    def fake_poll(_db, t):
        t.status = next(outcome)
        return t

    monkeypatch.setattr(service, "due_for_poll", lambda _db, limit: tasks)
    monkeypatch.setattr(service, "poll_task", fake_poll)
    assert poller.poll_due_once(object()) == {"checked": 3, "settled": 2}


def test_the_endpoint_and_the_loop_share_one_implementation():
    """两份实现迟早会漂 —— 端点只转调。"""
    from app.api.v2 import gen_tasks

    assert "poll_due_once" in inspect.getsource(gen_tasks.poll_due)


def test_the_loop_is_started_and_stopped_with_the_app():
    """随 app 起、随 app 停；设成 0 就关。"""
    from app import main

    src = inspect.getsource(main.lifespan)
    assert "run_forever" in src
    assert "poll_loop_sec > 0" in src
    assert "cancel()" in src


def test_the_loop_sleeps_before_its_first_tick():
    """先睡再查：启动那一刻不抢数据库，测试里起停 app 也不会真去轮询。"""
    src = inspect.getsource(poller.run_forever)
    assert src.index("asyncio.sleep") < src.index("to_thread")
