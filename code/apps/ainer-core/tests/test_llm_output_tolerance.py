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


# ── 两条路径都要有修复轮 ──────────────────────────────────────────────────────

class TestRepairRoundParity:
    def test_both_paths_have_a_repair_round(self):
        """text.chat 与 text.translate 都得有非 JSON 的修复轮。

        端到端第十轮：ch1 翻译时模型回了非 JSON，整章失败，
        后面的违规审查、回译、文化审查全部级联挂掉 —— 一个根因四处失败。
        而 text.chat 早就有修复轮，只是 text.translate 没有：
        **同一个问题只在一条路径上防住了**。
        """
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "capability" / "dialects.py").read_text(encoding="utf-8")
        chat = src[src.index("def _run_chat"):src.index("_TRANSLATE_RULES")]
        trans = src[src.index("def _translate_batch"):]
        for name, body in (("_run_chat", chat), ("_translate_batch", trans)):
            assert "修复轮" in body, f"{name} 缺少非 JSON 的修复轮"
            assert "temperature=0.0" in body, f"{name} 的修复轮该把温度压到 0"


# ── 从模型回复里抠 JSON ───────────────────────────────────────────────────────

from app.capability.dialects import _balanced_spans, _loads


class TestJsonExtraction:
    """推理模型常把整段思考写在 JSON 前后，思考里也有括号。

    原来的 find("{") → rfind("}") 假设整段里只有一对最外层括号，
    遇到这种就把两边的杂物一起圈进来 —— 端到端第十一轮
    ⑥命名两轮都没抠出 JSON，就是这么failed的。
    """

    @pytest.mark.parametrize("raw,expect", [
        ('{"a":1}', {"a": 1}),
        ('```json\n{"a":1}\n```', {"a": 1}),
        ('让我分析一下。\n{"a":1}\n以上。', {"a": 1}),
        ('[{"a":1}]', [{"a": 1}]),
    ])
    def test_basic_shapes(self, raw, expect):
        assert _loads(raw) == expect

    def test_strips_reasoning_tags(self):
        """<think> 里的内容常含大括号，不剥掉会从思考里开始找。"""
        assert _loads("<think>先看 {这里} 再看</think>{\"a\":1}") == {"a": 1}

    def test_unclosed_bracket_in_reasoning(self):
        """未闭合的开括号会把后面真正的 JSON 一起吞掉。

        只有从**每个**开括号位置各扫一次才找得回来 ——
        只认最外层的写法在这里必然失败。
        """
        assert _loads("思考：{不完整\n实际答案：{\"a\":1}") == {"a": 1}

    def test_braces_inside_strings(self):
        """字符串里的括号不算数，否则会在错误的位置收尾。"""
        assert _loads('{"a":"}"}') == {"a": "}"}

    def test_trailing_braces_after_json(self):
        assert _loads('{"a":1} 补充说明 {备注}') == {"a": 1}

    def test_picks_the_longest_candidate(self):
        """嵌套结构里最外层那个才是完整答案。"""
        got = _loads('分析：{想法} 结果：{"groups":[{"x":1}]} 完毕')
        assert got == {"groups": [{"x": 1}]}

    def test_raises_when_no_json(self):
        with pytest.raises(ValueError):
            _loads("没有任何 JSON")

    def test_spans_are_longest_first(self):
        spans = _balanced_spans('{"a":{"b":1}}')
        assert spans and spans[0] == (0, 13)


class TestRetryability:
    """两种失败要分开对待。

    截断是**确定性**的：同样的请求必然同样被截断，
    重试三次只是白烧三倍 token —— 要改的是调用方的批次大小。

    非 JSON 是**随机**的：模型每次生成都不一样，换一次采样很可能就对了。
    标成不可重试的代价是整章这一步直接丢掉 ——
    端到端第十三轮④梗抽取就是这么丢的。
    """

    @staticmethod
    def _source() -> str:
        import pathlib

        return (pathlib.Path(__file__).resolve().parent.parent
                / "app" / "capability" / "dialects.py").read_text(encoding="utf-8")

    def test_truncation_is_not_retryable(self):
        src = self._source()
        i = src.index("输出两轮均被截断")
        assert "retryable=False" in src[i:i + 400], "截断该标为不可重试"

    @pytest.mark.parametrize("marker", ["两轮均未取得合法 JSON",
                                        "两轮均未取得合法译文 JSON"])
    def test_bad_json_is_retryable(self, marker):
        src = self._source()
        i = src.index(marker)
        assert "retryable=True" in src[i:i + 400], f"{marker} 是随机失败，该允许重试"


class TestTopLevelShape:
    """schema 顶层是 object，模型有时只给数组。

    尤其在 schema 只有一个数组字段时（{"terms": [...]}
    它直接返回 [...]）。所有管线都写 data.get(...)，
    拿到 list 会以 AttributeError 变成 500，
    而调用方完全不知道是形状不对 —— 端到端第十二轮就是这么挂的。
    """

    @staticmethod
    def _fields(schema):
        return [
            k for k, v in (schema.get("properties") or {}).items()
            if isinstance(v, dict) and v.get("type") == "array"
        ]

    def test_single_array_field_is_unambiguous(self):
        schema = {"type": "object", "properties": {"terms": {"type": "array"}}}
        assert self._fields(schema) == ["terms"]

    def test_multiple_array_fields_are_ambiguous(self):
        """有多个数组字段时不能猜 —— 猜错等于把数据放进错误的槽。"""
        schema = {"type": "object", "properties": {
            "entities": {"type": "array"}, "beats": {"type": "array"},
        }}
        assert len(self._fields(schema)) == 2

    def test_no_array_field(self):
        schema = {"type": "object", "properties": {"verdict": {"type": "string"}}}
        assert self._fields(schema) == []
