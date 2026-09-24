"""后台轮询 —— 回调丢了的任务靠它收尾。

回调是首选通知方式，但会丢：上游重试耗尽、网络抖动、**本服务重启**。
契约里说轮询兜底「应由定时任务每分钟调一次」，而这个定时任务从来没有人建 ——
`POST /gen-tasks:poll-due` 只在页面上的几个按钮里被短暂地连点几下。

于是 core 一重启，正在出的图和视频就再也收不到结果：任务停在 running，
规格停在「生成中」，而工作台看起来一切正常，只是永远不动。
实跑这一周每次重启服务后都得手动轮询才能把结果挂回来。

这里做成进程内的一个循环：随 app 启动、随 app 关闭，每隔
`settings.poll_loop_sec` 秒跑一遍到期任务。设成 0 就关掉。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def poll_due_once(db: Session, *, limit: int = 50) -> dict[str, Any]:
    """把到期未终结的任务各查一次。端点和后台循环共用这一段。"""
    from app.capability.service import due_for_poll, poll_task
    from app.models import TaskStatus

    terminal = {TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled}
    tasks = due_for_poll(db, limit=limit)
    settled = 0
    for t in tasks:
        before = t.status
        poll_task(db, t)
        if t.status != before and t.status in terminal:
            settled += 1
    return {"checked": len(tasks), "settled": settled}


def _tick() -> dict[str, Any]:
    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            out = poll_due_once(db)
            db.commit()
        except Exception:
            db.rollback()
            raise
    if out["settled"]:
        log.info("后台轮询：查了 %d 个到期任务，%d 个已收尾",
                 out["checked"], out["settled"])
    return out


async def run_forever(interval_sec: float) -> None:
    """先睡再查 —— 启动那一刻不抢数据库，测试里起停 app 也不会真去轮询。

    DB 与上游 HTTP 都是同步调用，放到线程里跑，不堵事件循环。
    单次出错只记日志不退出：一次上游抖动不该让兜底从此停摆。
    """
    while True:
        await asyncio.sleep(interval_sec)
        try:
            await asyncio.to_thread(_tick)
        except Exception:  # noqa: BLE001
            log.exception("后台轮询这一轮失败，下一轮照常")
