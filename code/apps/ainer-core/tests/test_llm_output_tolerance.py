"""LLM 输出取值的容错。

**不能假设模型严格遵守 schema。** schema 写 string，
模型可能返回 ["紧张","悬疑"]、3、或 null ——
直接 `.strip()` 会以 AttributeError 把整批任务打挂，
而调用方看到的只是 500，完全不知道是模型多给了个数组。

这个洞是真炸过的：端到端第九轮在②停下，
mood 字段来了个 list。换模型时这类差异最集中 ——
同一份 schema，一个模型老实返回字符串，另一个顺手给了列表。
管线不该因此失败。
"""
from __future__ import annotations

import pytest

from app.pipelines.base import as_int, as_list, as_text


class TestAsText:
    @pytest.mark.parametrize("value,expect", [
        ("  紧张  ", "紧张"),
        ("", ""),
        (None, ""),
        (3, "3"),
        (3.5, "3.5"),
    ])
    def test_scalars(self, value, expect):
        assert as_text(value) == expect

    def test_list_is_joined_not_dropped(self):
        """模型给数组通常是因为它真有多个值，丢掉等于丢信息。"""
        assert as_text(["紧张", "悬疑"]) == "紧张，悬疑"

    def test_nested_list(self):
        assert as_text([["a", "b"], "c"]) == "a，b，c"

    def test_dict_takes_values(self):
        assert as_text({"a": "x", "b": "y"}) == "x，y"

    def test_none_entries_skipped(self):
        assert as_text(["a", None, "b"]) == "a，b"

    def test_empty_list_is_empty_string(self):
        assert as_text([]) == ""

    def test_limit_truncates(self):
        assert as_text("abcdefgh", limit=3) == "abc"

    def test_custom_separator(self):
        assert as_text(["a", "b"], sep="/") == "a/b"


class TestAsList:
    def test_string_becomes_single_item(self):
        """schema 写 array 而模型给了单个字符串 —— 反向也要兜住。"""
        assert as_list("单个") == ["单个"]

    def test_blank_string_yields_empty(self):
        assert as_list("   ") == []

    @pytest.mark.parametrize("value,expect", [
        (["a", "b"], ["a", "b"]),
        (None, []),
        ([], []),
        ({"k": "v"}, ["v"]),
        (5, ["5"]),
    ])
    def test_shapes(self, value, expect):
        assert as_list(value) == expect

    def test_drops_empty_entries(self):
        assert as_list(["a", "", None, "b"]) == ["a", "b"]

    def test_limit(self):
        assert as_list(["a", "b", "c"], limit=2) == ["a", "b"]


class TestAsInt:
    @pytest.mark.parametrize("value,expect", [
        (4, 4), ("4", 4), (4.7, 4), ("4.7", 4),
    ])
    def test_parses(self, value, expect):
        assert as_int(value, 0) == expect

    @pytest.mark.parametrize("value", [None, "九", "", [], {}])
    def test_falls_back_on_garbage(self, value):
        assert as_int(value, 3) == 3

    def test_clamps_to_range(self):
        """强度、张力这类字段有固定区间，越界值不该写进库。"""
        assert as_int(99, 3, lo=1, hi=5) == 5
        assert as_int(-2, 3, lo=1, hi=5) == 1


class TestNoRegression:
    def test_pipelines_do_not_strip_raw_llm_values(self):
        """管线里不该再出现 `(item.get(...) or "").strip()` 这种写法。

        它假设了模型一定返回字符串。取值一律走 as_text /as_list ——
        八十多处各写各的，总有一处会在换模型时炸。
        """
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent / "app"
        # 只查从 LLM 返回的 dict 里取值的那种：item.get(...) / entry.get(...)
        pat = re.compile(r'\b(?:item|entry|c|m|d)\.get\([^()]*\)\s*or\s*""\s*\)\s*\.strip\(\)')
        bad = []
        for p in root.rglob("*.py"):
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line):
                    bad.append(f"{p.name}:{i}")
        assert not bad, "这些地方仍在假设模型返回字符串：" + "、".join(bad)
