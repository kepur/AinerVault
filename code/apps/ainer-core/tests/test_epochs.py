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


class TestCjkGuard:
    """图像模型不认中文。

    实跑时把中文外貌描述喂给 SDXL，出来的是一整版汉字纹样，一张脸都没有。
    同一段英文出来的是一张正经的 19 世纪肖像。
    """

    def test_chinese_segments_are_reported(self):
        from app.pipelines.frame_compose import cjk_segments
        out = cjk_segments("medium shot, 站在门口，手握刀柄, 35mm lens, 面无表情")
        assert out == ["站在门口，手握刀柄", "面无表情"]

    def test_english_only_prompt_is_clean(self):
        from app.pipelines.frame_compose import cjk_segments
        assert cjk_segments("medium shot, 35mm lens, plain grey background") == []

    def test_segments_are_reported_not_stripped(self):
        """删掉等于悄悄丢信息：「站在门口，手握刀柄」删了，
        画面里的人就不再握刀了，而没有任何地方说过为什么。"""
        from app.pipelines.frame_compose import cjk_segments
        text = "a, 握刀柄, b"
        assert "握刀柄" in cjk_segments(text)
        assert text == "a, 握刀柄, b"   # 原串不动

    def test_kana_and_hangul_count_too(self):
        from app.pipelines.frame_compose import cjk_segments
        assert cjk_segments("ひらがな, 한글, latin") == ["ひらがな", "한글"]


class TestGazeIsGeometric:
    """人名对图像模型毫无意义。

    「looking at 裴无咎」它读不出是谁，更读不出该往哪看 ——
    而那段中文还会被当成图案画进画面。
    「gaze directed at the figure on the right」才是它能执行的指令。
    """

    def test_no_name_reaches_the_prompt(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "pipelines" / "frame_compose.py").read_text("utf-8")
        assert 'f"looking at {p.gaze_target}"' not in src
        assert "gaze directed at the figure" in src
        assert "gaze directed off-screen" in src


class TestNoDuplicatedAge:
    """年龄本来就是 visual_en 的第一段，别再往前拼一次。

    拼了就成了「…178cm tall, man in his mid-twenties, hair…」，
    而 AGE_EN_KEY 存在只为锚图 —— 那里没有 visual_en 可取。
    """

    def test_visual_prompt_does_not_prepend_the_age_key(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "pipelines" / "entity_epochs.py").read_text("utf-8")
        body = src[src.index("row.visual_prompt") - 600:]
        assert "d.variant.get(AGE_EN_KEY)" not in body


class TestAssetKeysAreStrings:
    """asset_keys 是字符串列表，不是对象列表。

    用 as_items 取会把它们全滤掉 —— 于是 missing_assets 永远是空的，
    「缺素材」这道检查从来没真跑过，而它是分镜编译前最后一道闸。
    实跑时日志里每镜刷一条「asset_keys 里有 2 个元素不是对象，已丢弃」，
    而返回值一直是漂亮的 missing_assets: []。
    """

    def test_compose_uses_as_list_for_asset_keys(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "app" / "pipelines" / "frame_compose.py").read_text("utf-8")
        assert 'as_items(params, "asset_keys")' not in src
        assert 'as_list(params.get("asset_keys"))' in src

    def test_as_list_keeps_plain_strings(self):
        from app.pipelines.base import as_list
        assert as_list(["costume.robe", "prop.sabre"]) == \
            ["costume.robe", "prop.sabre"]
