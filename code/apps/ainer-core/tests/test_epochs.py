"""素材时期演化的测试。

小说是沿时间展开的：少年林凡与中年林凡不是同一套衣着兵器，
而老家的院子二十年后还是那个院子。

三件事各有各的失败方式，都不会报错、只会让成片不对：
    区间选错  这一章用了错误时期的形态
    拼接顺序  invariant 放后面，脸会跟着衣服漂
    不复用    「探访故乡」与二十章前是两个不同的院子
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models import INVARIANT_FIELDS, VARIANT_FIELDS, EpochKind
from app.pipelines.epochs import compose_epoch_prompt


def _epoch(inv=None, var=None):
    return SimpleNamespace(invariant_json=inv or {}, variant_json=var or {})


class TestComposePrompt:
    def test_invariant_comes_first(self):
        """**顺序固定：invariant 在前。**

        图像模型对前面的词更敏感。把同一性锚点放前面、衣着道具放后面，
        换了衣服脸还是那张脸；反过来放，生成的结果会更像
        「一个穿着某某衣服的人」而不是「某某人穿了衣服」。
        """
        out = compose_epoch_prompt(
            _epoch(
                inv={"face_shape": "方脸", "scars": "左颊旧疤"},
                var={"garments": "青布长衫", "carried": "腰刀"},
            ),
            "character",
        )
        assert out.index("方脸") < out.index("青布长衫")
        assert out.index("左颊旧疤") < out.index("腰刀")

    def test_field_order_follows_declaration(self):
        """字段顺序跟着声明走，不跟着字典插入顺序 ——
        否则同一份数据两次生成的提示词可能不同，图就不稳。
        """
        inv = {"scars": "疤", "face_shape": "方脸"}      # 故意倒序
        out = compose_epoch_prompt(_epoch(inv=inv), "character")
        assert out.index("方脸") < out.index("疤")

    def test_extra_fields_are_kept(self):
        """结构化字段之外自由填的也要带上，不能因为不在表里就丢。"""
        out = compose_epoch_prompt(
            _epoch(inv={"face_shape": "方脸"}, var={"自定义": "披蓑衣"}),
            "character",
        )
        assert "披蓑衣" in out

    def test_empty_yields_empty(self):
        assert compose_epoch_prompt(_epoch(), "character") == ""

    def test_blank_values_skipped(self):
        out = compose_epoch_prompt(
            _epoch(inv={"face_shape": "方脸", "eye_color": ""}), "character")
        assert out == "方脸"

    @pytest.mark.parametrize("kind", ["character", "location", "prop", "costume"])
    def test_every_kind_has_both_field_sets(self, kind):
        """每类实体都要分清哪些不变、哪些可变 ——
        缺一半的话，那类素材要么全书不变、要么每镜都在漂。
        """
        assert INVARIANT_FIELDS.get(kind), f"{kind} 缺少不变字段"
        assert VARIANT_FIELDS.get(kind), f"{kind} 缺少可变字段"

    def test_face_fields_are_invariant_not_variant(self):
        """脸必须在 invariant 里。它是同一性的锚 ——
        放进 variant 就意味着每期重新描述一次，三期下来是三个人。
        """
        inv = set(INVARIANT_FIELDS["character"])
        var = set(VARIANT_FIELDS["character"])
        for f in ("face_shape", "features", "eye_color", "scars"):
            assert f in inv and f not in var

    def test_garments_are_variant_not_invariant(self):
        """衣着兵器必须可变 —— 那正是分期要表达的东西。"""
        inv = set(INVARIANT_FIELDS["character"])
        var = set(VARIANT_FIELDS["character"])
        for f in ("garments", "carried", "hair", "age_look"):
            assert f in var and f not in inv

    def test_location_structure_is_invariant(self):
        """「探访故乡」靠的就是结构不变，季节天候可以变。"""
        assert "structure" in INVARIANT_FIELDS["location"]
        assert "season" in VARIANT_FIELDS["location"]
        assert "structure" not in VARIANT_FIELDS["location"]


class TestEpochKinds:
    def test_covers_the_real_causes_of_change(self):
        """时期不是按章节机械切的，是由事件触发的。"""
        kinds = {k.value for k in EpochKind}
        for expected in ("age", "gear", "injury", "status", "season", "ruin"):
            assert expected in kinds


class TestFieldLength:
    """时期记录是档案，提示词不是。

    实跑时一个三人镜拼出 2483 字，而「随身携带一根铁质镖旗杆
    （可作短棍使用）」在画面里根本看不见 —— 它唯一的作用是把
    「谁在做什么」挤出模型的注意力。
    """

    def test_long_field_is_cut_at_a_clause_boundary(self):
        from app.pipelines.epochs import _short
        out = _short("腰刀一把，刀鞘为黑色牛皮，刀柄包铜，未出鞘时仅露刀把")
        assert len(out) <= 26
        assert not out.endswith("，")
        assert out.startswith("腰刀一把")

    def test_short_field_is_untouched(self):
        from app.pipelines.epochs import _short
        assert _short("黑鞘铜柄腰刀") == "黑鞘铜柄腰刀"

    def test_no_boundary_falls_back_to_a_hard_cut(self):
        """半个短语比没有更糟，但没有句读时也只能硬切。"""
        from app.pipelines.epochs import _short
        out = _short("あ" * 60)
        assert len(out) == 26


class TestPromptIsNotFedBackIn:
    """合成结果不能被当成下一次的镜头内容。

    实跑时一个三人镜拼到 4034 字，同一批人物描述重复四遍，
    每遍还是不同批次抽取的旧值 —— 画面里那三个人各有四套衣服。
    起因是 compose 读 frame.prompt 当「镜头内容」，又把产出写回 frame.prompt。
    """

    def test_compose_reads_content_not_prompt(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "pipelines" / "frame_compose.py").read_text("utf-8")
        head = src[:src.index("def bind_and_compose")]
        assert "positive.append(frame.prompt" not in head
        assert '.get("content")' in head


class TestRecoverContent:
    def test_uncomposed_prompt_is_kept_whole(self):
        from app.pipelines.frame_compose import _recover_content
        text = "沈砚推开门，腰刀在手，门外三人回头"
        assert _recover_content(text) == text

    def test_nested_prompt_yields_the_last_segment(self):
        """合成时新内容拼在前面，所以原句在最后一段。"""
        from app.pipelines.frame_compose import _recover_content
        nested = "壮实，肩宽背厚, medium shot, 壮实，肩宽背厚, medium shot, 沈砚推开门"
        assert _recover_content(nested) == "沈砚推开门"


class TestFrameSyncAfterRegenerate:
    def test_sync_keys_off_the_current_task_not_presence_of_an_asset(self):
        """判「有图就跳过」的话，regenerate 之后挂着的还是旧图 ——
        重出一版花了钱，看到的却是上一版。"""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "pipelines" / "frame_compose.py").read_text("utf-8")
        body = src[src.index("def sync_frame_assets"):]
        assert "if frame.asset_id or not frame.gen_task_id" not in body
        assert "asset_id != frame.asset_id" in body
