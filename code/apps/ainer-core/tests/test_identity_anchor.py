"""身份锚 —— 把「同一个人」从文字变成事实。

拿同一句描述生成三次是三张脸，所以跨期同一性的落点是一张共用的参考图。
这里测的是那张图的提示词怎么拼 —— 它错一个词，六个角色的脸就全跑偏。
"""
from __future__ import annotations

import pytest

from app.pipelines.identity import (
    ANCHOR_FRAMING, ANCHOR_NEGATIVE, compose_anchor_prompt, era_phrase,
)


class _Profile:
    def __init__(self, axes):
        self.axes_json = axes


class _Epoch:
    def __init__(self, inv, var=None):
        self.invariant_json = inv
        self.variant_json = var or {}


class TestEraPhrase:
    """「帝俄晚期」在提示词里必须写成年代 + 地域 ——
    图像模型不认中文，也不认 ru_imperial 这种内部代码。

    但**国籍不是人种**。原来拼的是 "early 21st century American man"，
    而人物不变项里明明写着 monolid eyes、East Asian；模型把 American
    读成白人，坏蛋的主角出成一个白人少年，而他的译名是 Thomas Chen。
    这一步是所有下游画面的底图，错在这里全片跟着错。
    改成写「故事发生在哪」，长相交给不变项自己说。
    """

    @pytest.mark.parametrize("axes,expect", [
        ({"region": "RU", "era_span": [1855, 1917]},
         "set in a Russian city, late 19th century"),
        ({"region": "GB", "era_span": [1837, 1901]},
         "set in a British city, late 19th century"),
        ({"region": "JP", "era_span": [1926, 1989]},
         "set in a Japanese city, mid 20th century"),
        ({"region": "US", "era_span": [1920, 1929]},
         "set in an American city, early 20th century"),
    ])
    def test_reads_axes(self, axes, expect):
        assert era_phrase(_Profile(axes)) == expect

    @pytest.mark.parametrize("axes", [
        {"region": "RU", "era_span": [1855, 1917]},
        {"region": "US", "era_span": [1990, 2030]},
    ])
    def test_era_phrase_is_the_setting_not_the_person(self, axes):
        """这一句只说故事发生在哪。人长什么样由 demonym() 单独给 ——
        两件事合成一句写过 "early 21st century American man"，
        结果地域被当成人种、年代被当成形容词，两头都不准。"""
        got = era_phrase(_Profile(axes))
        assert " man" not in got and " woman" not in got
        assert "set in" in got


class TestDemonym:
    """人物外貌属于目标世界观 —— 和货币场所一样要映射。

    不写的话模型照着原文的中文外貌描述画，坏蛋出来是一屋子中国脸，
    而故事发生在美国、名字叫 Thomas。
    """

    @pytest.mark.parametrize("region,expect", [
        ("US", "American"), ("RU", "Russian"), ("JP", "Japanese"),
    ])
    def test_reads_the_region(self, region, expect):
        from app.pipelines.identity import demonym

        assert demonym(_Profile({"region": region})) == expect

    def test_unknown_region_gives_nothing(self):
        """猜错族裔比不写更糟 —— 不写模型按其余线索推。"""
        from app.pipelines.identity import demonym

        assert demonym(_Profile({"region": "ZZ"})) == ""

    @pytest.mark.parametrize("text,region,hit", [
        ("East Asian male, monolid eyes", "US", True),
        ("East Asian male, monolid eyes", "JP", False),   # 译到日本就是对的
        ("square face, thick brows", "US", False),
    ])
    def test_unmapped_appearance_is_reported(self, text, region, hit):
        from app.pipelines.identity import foreign_appearance_terms

        got = foreign_appearance_terms(text, _Profile({"region": region}))
        assert bool(got) is hit

    def test_missing_pieces_degrade_gracefully(self):
        assert era_phrase(_Profile({"region": "RU"})) == "set in a Russian city"
        assert era_phrase(_Profile({"era_span": [1855, 1917]})) \
            == "late 19th century"
        assert era_phrase(_Profile({})) == ""

    def test_unknown_region_is_dropped_not_guessed(self):
        """猜错族裔比不写更糟 —— 不写模型按其余线索推，写错它就照着错的画。"""
        assert era_phrase(_Profile({"region": "ZZ", "era_span": [1900, 1910]})) \
            == "early 20th century"


class TestAnchorPrompt:
    def test_sex_and_era_lead_the_prompt(self):
        """实跑时沈砚（男，帝俄晚期）的锚图出来是张现代女性的脸 ——
        英文不变项里没有性别词，SD 就自己挑了一个。"""
        p = compose_anchor_prompt(
            _Epoch({"sex": "male", "_en": "square face, thick brows"}),
            _Profile({"region": "RU", "era_span": [1855, 1917]}),
        )
        assert p.startswith("Russian man, ")
        assert "square face, thick brows" in p
        # 年代地域另起一段说「故事发生在哪」，不与族裔挤在一起
        assert "set in a Russian city, late 19th century" in p
        assert p.endswith(ANCHOR_FRAMING)

    def test_no_english_means_no_prompt(self):
        """中文喂给 SDXL 出来的是汉字纹样，不是脸 —— 宁可不生成。"""
        assert compose_anchor_prompt(_Epoch({"face_shape": "国字脸"})) == ""

    def test_variant_is_never_included(self):
        """锚会被后续每一期引用。带上第一期的衣着兵器，
        那身衣服会渗进中年的每一张图。"""
        p = compose_anchor_prompt(
            _Epoch({"sex": "male", "_en": "square face"},
                   {"_en": "dark grey escort coat, sabre at the hip"}))
        assert "sabre" not in p and "coat" not in p

    def test_framing_forbids_costume_and_scene(self):
        for word in ("no costume detail", "no props", "plain mid-grey"):
            assert word in ANCHOR_FRAMING
        for word in ("full body", "costume", "weapon", "scenery"):
            assert word in ANCHOR_NEGATIVE

    def test_profile_is_optional(self):
        p = compose_anchor_prompt(_Epoch({"sex": "female", "_en": "round face"}))
        assert p.startswith("woman, round face")


class TestAgeFallback:
    """没有年龄的头肩像，模型一律画成三十岁上下 ——
    于是六十岁的老周和二十岁的裴无咎看着同龄。

    实跑时模型漏填了 age_en（一次调用要两种语言，它会放弃一种），
    但 visual_en 的第一段基本都是年龄，因为提示词就是那么要求的。
    """

    @pytest.mark.parametrize("item,expect", [
        ({"age_en": "late twenties", "visual_en": "x"}, "late twenties"),
        ({"visual_en": "mid-40s, short dark hair"}, "mid-40s"),
        ({"visual_en": "early sixties, grey beard"}, "early sixties"),
        ({"visual_en": "a boy of about twelve, ragged tunic"},
         "a boy of about twelve"),
    ])
    def test_reads_or_recovers(self, item, expect):
        from app.pipelines.entity_epochs import _age_en
        assert _age_en(item) == expect

    def test_non_age_head_is_not_mistaken(self):
        """首段不是年龄时不能硬当年龄用 —— 「短发」当成年龄会毁掉整张脸。"""
        from app.pipelines.entity_epochs import _age_en
        assert _age_en({"visual_en": "short dark hair, grey coat"}) == ""

    def test_age_leads_the_anchor_prompt(self):
        from app.pipelines.entity_epochs import AGE_EN_KEY
        p = compose_anchor_prompt(
            _Epoch({"sex": "male", "_en": "square face"},
                   {AGE_EN_KEY: "early sixties"}),
            _Profile({"region": "RU", "era_span": [1855, 1917]}))
        assert p.startswith("early sixties, Russian man, square face")
        assert "set in a Russian city" in p


def test_sex_noun_is_dropped_when_the_age_phrase_already_has_it():
    """年龄短语常常自带 man／woman，再补一个就成了
    「man in his late fifties, … Russian man」—— 读起来像没校对过。"""
    from app.pipelines.entity_epochs import AGE_EN_KEY
    p = compose_anchor_prompt(
        _Epoch({"sex": "male", "_en": "square face"},
               {AGE_EN_KEY: "man in his late fifties"}),
        _Profile({"region": "RU", "era_span": [1855, 1917]}))
    # 年龄短语自带 man，就不再补一个 —— 但族裔仍要写
    assert p.startswith("man in his late fifties, Russian, square face, ")
    assert "Russian man" not in p
    assert "set in a Russian city" in p


def test_sex_noun_survives_when_the_age_phrase_lacks_it():
    from app.pipelines.entity_epochs import AGE_EN_KEY
    p = compose_anchor_prompt(
        _Epoch({"sex": "male", "_en": "square face"},
               {AGE_EN_KEY: "elderly, deeply lined"}),
        _Profile({"region": "RU", "era_span": [1855, 1917]}))
    assert p.startswith("elderly, deeply lined, Russian man, ")


class TestBustReference:
    """特写要头肩像。三张全身参考在特写里等于没有参考 ——
    脸只占参考图的百分之几，模型只能自己把五官放大重画，
    于是全片最该认得出人的那几个镜头恰恰最不像。"""

    @pytest.mark.parametrize("size", ["cu", "ecu"])
    def test_close_shots_take_the_bust(self, size):
        from app.pipelines.identity import preferred_reference_view

        assert preferred_reference_view("to_camera", size) == "bust"
        assert preferred_reference_view("profile_right", size) == "bust"

    @pytest.mark.parametrize("size", ["ms", "fs", "ws", "els", "", None])
    def test_wider_shots_still_go_by_facing(self, size):
        from app.pipelines.identity import preferred_reference_view

        assert preferred_reference_view("to_camera", size) == "front"
        assert preferred_reference_view("profile_right", size) == "profile_left"

    def test_bust_falls_back_to_front_not_to_a_profile(self):
        """没有头肩像时宁可用正面 —— 侧身全身那张连脸都不完整。"""
        from app.models import AssetEpoch
        from app.pipelines.identity import character_reference_asset_id

        epoch = AssetEpoch(reference_set_json={"views": {
            "front": {"asset_id": "a_front"},
            "profile_left": {"asset_id": "a_profile"},
        }})
        assert character_reference_asset_id(epoch, "profile_left", "cu") == "a_front"

    def test_bust_wins_when_present(self):
        from app.models import AssetEpoch
        from app.pipelines.identity import character_reference_asset_id

        epoch = AssetEpoch(reference_set_json={"views": {
            "front": {"asset_id": "a_front"},
            "bust": {"asset_id": "a_bust"},
        }})
        assert character_reference_asset_id(epoch, "to_camera", "cu") == "a_bust"
        assert character_reference_asset_id(epoch, "to_camera", "ms") == "a_front"

    def test_bust_prompt_reframes_rather_than_crops(self):
        """裁一刀出来的脸只有几十个像素，放大回去还是糊的。"""
        from app.models import AssetEpoch
        from app.pipelines.identity import compose_character_reference_prompt

        got = compose_character_reference_prompt(AssetEpoch(), None, "bust")
        assert "head-and-shoulders" in got
        assert "filling the frame" in got
        assert "skin texture" in got

    def test_frame_compose_passes_the_shot_size_down(self):
        """选参考图的函数拿得到景别，但没人传的话它永远走朝向那一支。"""
        import inspect

        from app.pipelines import frame_compose

        src = inspect.getsource(frame_compose.compose_frame_prompt)
        assert "shot_size" in src.split("_entity_look(")[1][:220]


class TestAnchorsAttachThemselves:
    """出完就挂上，不要求人再跑一次 sync。

    「generate 提交、sync 挂回」这套两段式是为异步供应商准备的，
    而同步方言（百炼出图是同步的）在 submit_task 返回时图就已经在库里。
    漏跑一次 sync 的代价：七张锚图全都有，每一期的
    identity_ref_asset_id 仍然是空 —— 下一步「扩成正面全身参考」
    七个人全部报「先生成身份锚」，而锚明明就在那儿。
    """

    def test_generate_calls_sync(self):
        import inspect

        from app.pipelines import identity

        src = inspect.getsource(identity.generate_anchors)
        assert "sync_anchors(db, novel_id, profile)" in src

    def test_sync_only_runs_when_something_was_submitted(self):
        """一次都没提交时不必空跑，也不该在结果里报一份假的同步数。"""
        import inspect

        from app.pipelines import identity

        src = inspect.getsource(identity.generate_anchors)
        assert "if result.submitted:" in src

    def test_result_reports_what_got_attached(self):
        from app.pipelines.identity import AnchorResult

        assert "synced" in AnchorResult().as_dict()


class TestStaleReferences:
    """锚换了，从旧锚派生的参考图就作废。

    每张视角图都记着 source_asset_id（从哪张图派生的），
    但从来没有人读过它。坏蛋实测：正面参考 12:06 从旧锚派生，
    12:14 锚被重出（旧锚把亚裔主角画成了白人），于是每一期的
    identity_ref_asset_id 指向新脸，views.front 里还是那张白人全身像。
    再往下所有引用这个人的镜头都会拿到两张脸，
    而这一步只报「skipped: 7」，看着像一切正常。
    """

    def test_front_is_redone_when_the_anchor_changed(self):
        import inspect

        from app.pipelines import identity

        src = inspect.getsource(identity.generate_character_references)
        assert "stale_front" in src
        assert 'front_item.get("source_asset_id") != epoch.identity_ref_asset_id' in src

    def test_derived_views_follow_the_front(self):
        """派生视角的上游是正面图，同一条判据。"""
        import inspect

        from app.pipelines import identity

        src = inspect.getsource(identity.generate_character_references)
        assert "stale_view" in src
        assert 'current.get("source_asset_id") != front_id' in src

    def test_stale_is_reported_not_silent(self):
        """悄悄重出等于悄悄多花一次额度；要说清是上游换了。"""
        from app.pipelines.identity import CharacterReferenceResult

        assert "stale" in CharacterReferenceResult().as_dict()

    def test_no_anchor_means_no_staleness_claim(self):
        """还没有锚的时候不能把已有参考图判成过期 —— 那是另一回事。"""
        import inspect

        from app.pipelines import identity

        src = inspect.getsource(identity.generate_character_references)
        assert "front_id and epoch.identity_ref_asset_id" in src


class TestRefKindsAreDerivedNotCopied:
    """回挂时判「这是不是人物参考图」的那份清单，必须从视角表派生。

    原来是手写的三个字符串，与 identity.REFERENCE_REF_KINDS 是同一份
    清单的第二个副本。加第四个视角（头肩近景）时只改了那一份 ——
    于是 bust 的任务提交成功、图也出来了，回挂时判不出它是人物参考，
    asset_id 一直是空。而参考集里那一格写着 status: succeeded，
    从状态上看完全正常，只有真去取图时才发现是空的。
    """

    def test_every_view_can_be_attached_back(self):
        from app.capability.service import _character_ref_kinds
        from app.pipelines.identity import (
            CHARACTER_REFERENCE_VIEWS, REFERENCE_REF_KINDS,
        )

        kinds = _character_ref_kinds()
        for view in CHARACTER_REFERENCE_VIEWS:
            assert REFERENCE_REF_KINDS[view] in kinds, f"{view} 回挂不了"

    def test_no_second_hardcoded_copy(self):
        import inspect

        from app.capability import service

        src = inspect.getsource(service)
        assert '"character_ref_front"' not in src, "清单只应有一份，在 identity 里"

    def test_every_view_has_a_ref_kind_and_a_chinese_name(self):
        """加视角时三张表要一起加，缺一张就是一处静默的空。"""
        from app.pipelines.identity import (
            CHARACTER_REFERENCE_VIEWS, REFERENCE_REF_KINDS, REFERENCE_VIEW_CN,
        )

        for view in CHARACTER_REFERENCE_VIEWS:
            assert view in REFERENCE_REF_KINDS
            assert view in REFERENCE_VIEW_CN


class TestReferenceSheet:
    """四张视角分开存，分镜只会选中其中一张。

    一个人物只占一个参考位 —— 正面那张里的服饰、侧脸那张里的轮廓，
    到了实际出图时都不在场，于是同一个人在镜与镜之间漂：
    这一镜外套长一点，下一镜下巴尖一点，每张单看都合理。
    拼成一张，模型在同一个参考位上就能同时看到这几样。
    """

    def test_sheet_is_not_a_generated_view(self):
        """拼图是本地拼的，不能混进「要向模型要几张图」那张表。"""
        from app.pipelines.identity import CHARACTER_REFERENCE_VIEWS, SHEET_VIEW

        assert SHEET_VIEW not in CHARACTER_REFERENCE_VIEWS

    def test_sheet_wins_for_normal_shots(self):
        from app.models import AssetEpoch
        from app.pipelines.identity import SHEET_VIEW, character_reference_asset_id

        epoch = AssetEpoch(reference_set_json={"views": {
            "front": {"asset_id": "a_front"},
            SHEET_VIEW: {"asset_id": "a_sheet"},
        }})
        assert character_reference_asset_id(epoch, "to_camera", "ms") == "a_sheet"
        assert character_reference_asset_id(epoch, "to_camera", "ws") == "a_sheet"

    def test_close_shots_still_take_the_bust(self):
        """特写要的是脸的分辨率，拼图上的脸反而更小。"""
        from app.models import AssetEpoch
        from app.pipelines.identity import SHEET_VIEW, character_reference_asset_id

        epoch = AssetEpoch(reference_set_json={"views": {
            "bust": {"asset_id": "a_bust"},
            SHEET_VIEW: {"asset_id": "a_sheet"},
        }})
        assert character_reference_asset_id(epoch, "to_camera", "cu") == "a_bust"

    def test_sheet_falls_back_when_absent(self):
        from app.models import AssetEpoch
        from app.pipelines.identity import character_reference_asset_id

        epoch = AssetEpoch(reference_set_json={"views": {
            "front": {"asset_id": "a_front"}}})
        assert character_reference_asset_id(epoch, "to_camera", "ms") == "a_front"

    def test_labels_are_english(self):
        """这张图会作为参考图送给出图模型 —— 中文标注在它眼里是汉字纹样。"""
        from app.pipelines.identity import SHEET_LABELS

        for text in SHEET_LABELS.values():
            assert text.isascii()

    def test_frames_block_the_sheet_layout(self):
        """不挡的话模型会连版式一起抄，出来一张分格设定图而不是一个镜头。"""
        import inspect

        from app.pipelines import frame_compose

        src = inspect.getsource(frame_compose.compose_frame_prompt)
        for term in ("character sheet", "split screen", "collage"):
            assert term in src


class TestSkinToneIsAlsoUnmapped:
    """肤色词比族裔词更隐蔽 —— 它不写族裔，出来的仍是一张东亚面孔。

    坏蛋实测：用户指着父母说「很中国脸」。查不变项，族裔词一个没有，
    是「natural yellowish skin tone」在起作用，而只找族裔词的检查
    一个都抓不到。
    """

    @pytest.mark.parametrize("text", [
        "middle-aged woman, natural yellowish skin tone, round face",
        "square jaw, yellow skin, thick brows",
    ])
    def test_skin_tone_counts_as_unmapped(self, text):
        from app.pipelines.identity import foreign_appearance_terms

        assert foreign_appearance_terms(text, _Profile({"region": "US"}))

    def test_ordinary_skin_words_are_not_flagged(self):
        """「pale」「weathered tan」是普通的肤质描写，不该误伤。"""
        from app.pipelines.identity import foreign_appearance_terms

        for text in ("pale bloodless skin", "weathered tan skin, freckles"):
            assert not foreign_appearance_terms(text, _Profile({"region": "US"}))

    def test_the_mining_prompt_says_not_to_write_them(self):
        """规则层能查出来，提示词也要让模型一次做对。"""
        from app.pipelines.entity_epochs import _system

        prompt = _system(cap_chapters=3, total=20)
        assert "yellowish skin" in prompt
        assert "不要写族裔词" in prompt
