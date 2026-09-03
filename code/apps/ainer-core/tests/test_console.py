"""控制台的阶段模型。

后台原来是十七个能力页平铺，每个都要你先在别处选好上下文，
进去只说一句「先在书架选一个章节」。这里的每条测试对应
「换成对象下钻之后，界面上不能再骗人」的一个具体判据。
"""
from __future__ import annotations

from app.api.v2.console import _next_step, _stage


class TestStageState:
    def test_done_needs_a_denominator(self):
        assert _stage("k", "n", 3, 3, page="p")["state"] == "done"
        assert _stage("k", "n", 1, 3, page="p")["state"] == "partial"
        assert _stage("k", "n", 0, 3, page="p")["state"] == "todo"

    def test_zero_total_is_not_done(self):
        """0/0 不能算完成 —— 「一件都没有」和「全做完了」在界面上
        长得一样的话，人会以为这一步不用管。"""
        assert _stage("k", "n", 0, 0, page="p")["state"] == "todo"

    def test_blocked_beats_everything(self):
        """前置没做完时，这一步做了多少都不该显示成可以推进 ——
        「尾帧 0/30」旁边没有「首帧还没出」，人会去点尾帧然后发现点不动。"""
        st = _stage("k", "n", 5, 10, page="p", blocked_by="首帧还没出")
        assert st["state"] == "blocked"
        assert st["blocked_by"] == "首帧还没出"

    def test_exit_stage_is_not_a_todo(self):
        """交付与手动模式是**出口**，不是一件要做完的事。
        给它算完成度，界面上就成了一件永远差着的待办。"""
        st = _stage("handoff", "手动模式", 0, 0, page="handoff", countable=False)
        assert st["state"] == "open"
        assert st["countable"] is False


class TestNextStep:
    def test_picks_first_actionable(self):
        stages = [
            _stage("a", "甲", 1, 1, page="p1"),
            _stage("b", "乙", 0, 5, page="p2"),
            _stage("c", "丙", 0, 5, page="p3"),
        ]
        assert _next_step(stages)["key"] == "b"

    def test_skips_blocked(self):
        """指向一个点不动的地方，比不指还糟。"""
        stages = [
            _stage("a", "甲", 1, 1, page="p1"),
            _stage("b", "乙", 0, 5, page="p2", blocked_by="前面没做完"),
            _stage("c", "丙", 0, 5, page="p3"),
        ]
        assert _next_step(stages)["key"] == "c"

    def test_skips_exits(self):
        """出口永远「可开」，不该被当成下一步 ——
        否则一本什么都没做的书，下一步会是「去交付」。"""
        stages = [
            _stage("a", "甲", 1, 1, page="p1"),
            _stage("z", "出口", 0, 0, page="pz", countable=False),
        ]
        assert _next_step(stages) is None

    def test_partial_still_counts_as_next(self):
        """做了一半的那一步就是下一步 —— 不能跳过去做后面的。"""
        stages = [_stage("a", "甲", 3, 10, page="p1"),
                  _stage("b", "乙", 0, 10, page="p2")]
        nxt = _next_step(stages)
        assert nxt["key"] == "a" and nxt["done"] == 3 and nxt["total"] == 10

    def test_all_done_returns_none(self):
        assert _next_step([_stage("a", "甲", 1, 1, page="p")]) is None


class TestStageOrdering:
    """顺序不是排版偏好，是真实的依赖。"""

    def test_chapter_stages_follow_dependencies(self):
        import inspect

        from app.api.v2 import console

        src = inspect.getsource(console.chapter_stages)
        keys = ["script", "prose", "shots", "staging", "crew", "motion",
                "first_frame", "last_frame", "audio", "handoff"]
        pos = [src.index(f'"{k}"') for k in keys]
        assert pos == sorted(pos), "章节阶段的声明顺序必须与依赖顺序一致"

    def test_last_frame_blocked_by_first_frame(self):
        """没有首帧就派生不出尾帧。这条依赖写在代码里，不是靠人记住。"""
        import inspect

        from app.api.v2 import console

        src = inspect.getsource(console.chapter_stages)
        assert "no_first" in src
        assert 'blocked_by=no_plan or no_first' in src

    def test_novel_stages_are_book_wide(self):
        """整本共享的东西放在章节里做，会导致每章各定一套 ——
        第二十章的人就不是第一章那个人了。"""
        import inspect

        from app.api.v2 import console

        src = inspect.getsource(console.novel_stages)
        for key in ("chapters", "entities", "transform", "lexicon",
                    "epochs", "casting"):
            assert f'"{key}"' in src
