"""删除的正确性。

删除不可恢复，而这一层有三个容易出错的地方：

  没有外键的表不会级联 —— gen_tasks 与 assets 的 novel_id 不是外键
  按内容寻址的媒体文件可能被多本书共用 —— sha256 相同就是同一个文件
  删之前看不见影响面 ——「确定吗？」这三个字不构成信息
"""
from __future__ import annotations

import pytest


class TestOrphanCleanup:
    """gen_tasks 与 assets 的 novel_id **不是外键**。

    它们要跨表引用不同来源（章节、映射、镜头），加外键会把生命周期
    绑死在小说上，而任务记录有独立的审计价值。
    代价是删小说时不会自动走 —— 所以必须显式删。
    """

    def test_delete_removes_them_explicitly(self):
        import inspect

        from app.api.v2.library import delete_novel

        src = inspect.getsource(delete_novel)
        assert "delete(GenTask)" in src
        assert "delete(Asset)" in src

    def test_impact_counts_them(self):
        """影响面要包含它们 —— 不然人看到「产物 0」，
        以为没有产物，实际有一百多条留在库里。"""
        import inspect

        from app.api.v2.library import _impact

        src = inspect.getsource(_impact)
        assert '"gen_tasks"' in src and '"assets"' in src


class TestSharedMediaFiles:
    """按内容寻址是个陷阱：同一张图可能被多本书引用。

    媒体文件名是内容的 sha256 —— 两本书生成了同样的图，
    指向的是同一个文件。删一本书就删文件，另一本的图会凭空消失。
    """

    def test_checks_other_references_before_unlinking(self):
        import inspect

        from app.api.v2.library import delete_novel

        src = inspect.getsource(delete_novel)
        assert "still_used" in src
        # 必须在删行**之后**再查：删之前查，自己那几行也会算进去
        assert src.index("db.flush()") < src.index("still_used")

    def test_only_local_media_is_touched(self, tmp_path, monkeypatch):
        """URL 指向别处（中间层、对象存储）的一律不碰 ——
        那不是我们的文件，误删别人的存储不可逆。"""
        import app.capability.mediastore as ms
        from app.api.v2.library import _purge_media

        monkeypatch.setattr(ms, "media_root", lambda: tmp_path)
        (tmp_path / "abc.png").write_bytes(b"x")
        n = _purge_media([
            "http://localhost:8100/media/abc.png",
            "http://localhost:8199/files/other.png",     # 中间层的
            "https://cdn.example.com/assets/pic.png",     # 对象存储的
        ])
        assert n == 1
        assert not (tmp_path / "abc.png").exists()

    @pytest.mark.parametrize("name", [
        "../../etc/passwd", "a/b.png", ".hidden", "",
    ])
    def test_path_escape_is_refused(self, tmp_path, monkeypatch, name):
        """文件名来自数据库里的 URL —— 那是外部写进来的数据，
        不能直接当路径用。"""
        import app.capability.mediastore as ms
        from app.api.v2.library import _purge_media

        monkeypatch.setattr(ms, "media_root", lambda: tmp_path)
        assert _purge_media([f"http://x/media/{name}"]) == 0

    def test_missing_file_is_not_an_error(self, tmp_path, monkeypatch):
        """文件早被清理过是正常情况，不该让整次删除失败。"""
        import app.capability.mediastore as ms
        from app.api.v2.library import _purge_media

        monkeypatch.setattr(ms, "media_root", lambda: tmp_path)
        assert _purge_media(["http://x/media/gone.png"]) == 0


class TestBulkChapterDelete:
    def test_defaults_to_dry_run(self):
        """删几百章不可恢复。"""
        from app.api.v2.library import BulkDeleteIn

        assert BulkDeleteIn().dry_run is True

    def test_empty_filter_is_refused(self):
        """三个条件都空 = 删全部。**不接受** —— 那多半是前端漏传，
        而「整本删」有它自己的端点，走那条路时人知道自己在做什么。"""
        import inspect

        from app.api.v2.library import bulk_delete_chapters

        src = inspect.getsource(bulk_delete_chapters)
        assert "没有指定要删哪些章" in src

    def test_supports_both_ids_and_range(self):
        """勾选删是列表里的操作，区间删是「把第 800 章之后全删掉」——
        后者在长篇里更常用。"""
        from app.api.v2.library import BulkDeleteIn

        f = BulkDeleteIn.model_fields
        assert "chapter_ids" in f and "from_order" in f and "to_order" in f


class TestOrphanPurge:
    """级联只在删除那一刻生效，对历史遗留的孤儿无能为力。

    早先版本的删除、直接改库、中途失败的事务，都会留下孤儿。
    实测过一次：手动删掉的十几本书留下了 78 条产物。
    """

    def test_defaults_to_dry_run(self):
        """清理不可恢复，而孤儿本身不产生危害 ——
        不值得为了「顺手清一下」冒删错的风险。"""
        import inspect

        from app.api.v2.library import purge_orphans

        sig = inspect.signature(purge_orphans)
        assert sig.parameters["dry_run"].default.default is True

    def test_media_is_judged_by_url_not_by_row(self):
        """内容寻址下同一个文件可能有多条 asset 指着它 ——
        删掉一条不该动那个文件。判断「没人引用」要看 URL。"""
        import inspect

        from app.api.v2.library import purge_orphans

        src = inspect.getsource(purge_orphans)
        assert "surviving" in src and "referenced" in src
        assert "rsplit(\"/media/\", 1)" in src

    def test_reports_before_it_acts(self):
        """预演要说清会删多少、腾出多少文件。"""
        import inspect

        from app.api.v2.library import purge_orphans

        src = inspect.getsource(purge_orphans)
        for k in ("orphan_tasks", "orphan_assets", "unreferenced_files",
                  "sample_unreferenced"):
            assert k in src, k
