"""静态检查：函数体里有没有引用未定义的名字。

补的是回归里的一个洞。原有的「导入检查」只验证模块能加载 ——
而 `NameError: name 'texts' is not defined` 藏在函数体内，
只有真正执行到那一行才会炸。

这个洞是被一次真实事故逼出来的：把 survey 的挖掘逻辑拆成 _mine_batch
时漏传了 texts 参数，模块照常导入、测试全绿，
直到端到端跑到第⑤步才以 500 暴露 —— 而那一步要等二十分钟。

**必须按作用域分析。** 第一版把所有函数的参数都当成模块级名字，
于是 texts 作为另一个函数的局部变量被算作「已定义」，
检查通过 —— 一个抓不到目标 bug 的检查比没有更糟，它给虚假的安全感。
所以下面这套逐层维护可见名字集合，并有一条测试专门验证它能抓到原始事故。
"""
from __future__ import annotations

import ast
import builtins
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
_BUILTINS = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "__spec__"}


def _bound_here(node: ast.AST) -> set[str]:
    """在这一层作用域里绑定的名字（不下钻到嵌套函数与类）。"""
    names: set[str] = set()

    def walk(n: ast.AST, top: bool = False) -> None:
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(child.name)      # 名字可见，但体内不下钻
                continue
            if isinstance(child, (ast.Lambda,)):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for a in child.names:
                    names.add((a.asname or a.name).split(".")[0])
            elif isinstance(child, ast.ExceptHandler) and child.name:
                names.add(child.name)
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                names.update(child.names)
            walk(child)

    walk(node, top=True)
    return names


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> set[str]:
    a = fn.args
    out = {p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)}
    if a.vararg:
        out.add(a.vararg.arg)
    if a.kwarg:
        out.add(a.kwarg.arg)
    return out


def _loads_in_scope(node: ast.AST) -> list[ast.Name]:
    """本层作用域里 Load 的名字（不下钻到嵌套函数）。

    comprehension 的 target 在自己的作用域里绑定，一并收进来 ——
    不收会把 `[x for x in xs]` 里的 x 误报成未定义。
    """
    out: list[ast.Name] = []
    local: set[str] = set()

    def walk(n: ast.AST) -> None:
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp,
                                  ast.GeneratorExp)):
                for gen in child.generators:
                    for t in ast.walk(gen.target):
                        if isinstance(t, ast.Name):
                            local.add(t.id)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                out.append(child)
            walk(child)

    walk(node)
    return [n for n in out if n.id not in local]


def _check(tree: ast.Module, path: pathlib.Path) -> list[str]:
    module_names = _bound_here(tree) | _BUILTINS
    problems: list[str] = []

    def visit(node: ast.AST, visible: set[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = visible | _params(child) | _bound_here(child) | {child.name}
                for name in _loads_in_scope(child):
                    if name.id not in inner:
                        problems.append(
                            f"{path.name}:{name.lineno} {child.name}() "
                            f"引用未定义的 `{name.id}`"
                        )
                visit(child, inner)
            elif isinstance(child, ast.ClassDef):
                visit(child, visible | _bound_here(child))
            else:
                visit(child, visible)

    visit(tree, module_names)
    return problems


def _module_files() -> list[pathlib.Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in str(p))


@pytest.mark.parametrize(
    "path", _module_files(), ids=lambda p: str(p.relative_to(APP)))
def test_no_undefined_names(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems = _check(tree, path)
    assert not problems, "\n".join(problems)


def test_check_catches_the_original_accident():
    """验证这套检查确实能抓到逼出它的那个事故。

    没有这条，上面那些 pass 说明不了任何事 ——
    第一版的实现全绿，却对真 bug 视而不见。
    """
    src = '''
def caller(db, texts):
    for batch in texts:
        helper(db, batch)

def helper(db, batch):
    return _ctx(texts, batch)
'''
    tree = ast.parse(src)
    problems = _check(tree, pathlib.Path("fake.py"))
    assert any("texts" in p and "helper" in p for p in problems), problems


def test_no_false_positive_on_comprehension_targets():
    """`[x for x in xs]` 里的 x 不该被报成未定义。

    误报比漏报更伤：一旦开始加 noqa，整条检查很快就被绕过去了。
    """
    src = '''
def f(items):
    return [x.name for x in items if x], {k: v for k, v in items}
'''
    assert not _check(ast.parse(src), pathlib.Path("fake.py"))


def test_no_false_positive_on_closures():
    src = '''
def outer(cfg):
    def inner(x):
        return cfg[x]
    return inner
'''
    assert not _check(ast.parse(src), pathlib.Path("fake.py"))


class TestLibraryScale:
    """书架必须按几千章设计，不是按几十章。

    一部长篇八百到三千章。全量返回既撑爆响应，状态四联那四个 JOIN
    也会在几千个 id 上跑 —— 而人一次只看得了几十行。
    """

    def test_list_chapters_is_paginated(self):
        import inspect

        from app.api.v2.library import list_chapters

        sig = inspect.signature(list_chapters)
        for p in ("offset", "limit", "q"):
            assert p in sig.parameters, f"章节列表缺 {p}"

    def test_state_is_computed_for_the_page_only(self):
        """状态四联用的是本页的 id，不是全书的 ——
        翻页的代价与页大小成正比，而不是与书长成正比。"""
        import inspect

        from app.api.v2.library import list_chapters

        src = inspect.getsource(list_chapters)
        assert "ids = [c.id for c in rows]" in src
        assert ".offset(offset).limit(limit)" in src

    def test_import_preview_is_truncated(self):
        """没人会看三千行分章表，而三千条带摘要的响应有好几 MB。"""
        from app.api.v2.library import _PREVIEW_N, _preview

        class _C:
            def __init__(self, i):
                self.order_no, self.title = i, f"第{i}章"
                self.word_count, self.detected_by = 100, "heading"
                self.content = "正文" * 80

        out = _preview([_C(i) for i in range(1, 801)])
        assert len(out) == _PREVIEW_N + 1        # 首尾 + 一行省略说明
        elided = [c for c in out if c["detected_by"] == "elided"]
        assert len(elided) == 1 and "省略" in elided[0]["title"]

    def test_short_books_are_not_truncated(self):
        from app.api.v2.library import _preview

        class _C:
            def __init__(self, i):
                self.order_no, self.title = i, f"第{i}章"
                self.word_count, self.detected_by = 100, "heading"
                self.content = "正文"

        out = _preview([_C(i) for i in range(1, 6)])
        assert len(out) == 5
        assert not any(c["detected_by"] == "elided" for c in out)

    def test_preview_keeps_both_ends(self):
        """分章最容易错的是开头与结尾：前言被当成第一章，
        或尾声没被切出来。中间那些长得都一样。"""
        from app.api.v2.library import _preview

        class _C:
            def __init__(self, i, t):
                self.order_no, self.title = i, t
                self.word_count, self.detected_by = 100, "heading"
                self.content = ""

        rows = [_C(1, "楔子")] + [_C(i, f"第{i}章") for i in range(2, 801)] \
            + [_C(801, "尾声")]
        out = _preview(rows)
        assert out[0]["title"] == "楔子"
        assert out[-1]["title"] == "尾声"

    def test_bulk_insert_not_row_by_row(self):
        """逐个 db.add 会为每一行建 ORM 实例并跟踪 —— 三千章下来
        光身份映射就占满内存，而插完就不再碰它们了。"""
        import inspect

        from app.api.v2.library import import_chapters

        src = inspect.getsource(import_chapters)
        assert "db.execute(insert(Chapter)" in src
        assert "delete(Chapter)" in src, "整本替换要一条 DELETE，不是逐行删"

    def test_upload_has_a_size_ceiling(self):
        """不设限的话，几百 MB 的文件会被整个读进内存
        再切成几万个对象。"""
        from app.api.v2.library import _MAX_UPLOAD

        assert 5 * 1024 * 1024 <= _MAX_UPLOAD <= 50 * 1024 * 1024

    def test_encoding_fallbacks_cover_cjk(self):
        """gb18030 要排在 gbk 之前 —— 它是超集。"""
        from app.api.v2.library import _ENCODINGS

        assert "utf-8" in _ENCODINGS and "gb18030" in _ENCODINGS
        assert "big5" in _ENCODINGS

    def test_progress_is_one_aggregate_not_per_chapter(self):
        """几千章的书，逐章翻页去数「还有多少没译」不现实 ——
        而那恰恰是接手一本长篇时第一个要知道的数字。"""
        import inspect

        from app.api.v2.library import novel_progress

        src = inspect.getsource(novel_progress)
        assert "func.count" in src and "group_by" in src
        assert "for c in rows" not in src, "进度不该逐章循环"
