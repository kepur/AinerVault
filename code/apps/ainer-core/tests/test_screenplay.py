"""小说 → 剧本：把一段话拆成台词与动作。

**这是整条影片线的关键一步，而它原来不存在。**
块级分类只回答「这一段是不是对白段」，回答不了「哪几个字是说出口的」。
于是配音把整段都念了 —— 包括「老周把碗放在栏杆上」。
听起来就是有旁白，而数据上这一条明明标着 dialogue。
"""
from __future__ import annotations

import pytest

from app.pipelines import screenplay as sp


class TestQuoteSplit:
    def test_speech_and_action_interleaved(self):
        """小说里台词和叙述是混在一起的，一段可能有两句台词夹一个动作。"""
        s = sp.split_speech("「镖师不跑。」老周把碗放在栏杆上。「要跑，第一趟就跑了。」")
        assert s.speech == ["镖师不跑。", "要跑，第一趟就跑了。"]
        assert "老周把碗放在栏杆上" in s.action
        assert not s.uncertain

    def test_russian_guillemets(self):
        s = sp.split_speech(
            "«Охранник не убегает». Старый Чжоу поставил чашку. «Если бы бежал».")
        assert len(s.speech) == 2
        assert "поставил чашку" in s.action

    def test_english_double_quotes(self):
        s = sp.split_speech('"The box will not open," he said, setting down the crowbar.')
        assert s.speech and "box will not open" in s.speech[0]
        assert "crowbar" in s.action

    def test_pure_narration_has_no_speech(self):
        """整段没有引号 —— 这不是「拆不动」，它拆得很干净：没人说话。"""
        s = sp.split_speech("沈砚没点灯。他把腰刀横在膝上，坐在门后听。")
        assert s.speech == []
        assert s.action.startswith("沈砚没点灯")
        assert not s.uncertain

    def test_unclosed_quote_does_not_swallow_the_rest(self):
        """有左引号无右引号时不能猜到段尾 ——
        那会把后面的动作描写整段算成台词，配音就把它念出来。"""
        s = sp.split_speech("「他说了什么 然后老周转身走了。")
        assert "老周转身走了" not in " ".join(s.speech)

    def test_empty(self):
        assert sp.split_speech("").speech == []
        assert sp.split_speech(None).action == ""


class TestDashSplit:
    def test_attribution_marks_the_boundary(self):
        """破折号体里，归属小句是唯一可靠的边界信号。"""
        s = sp.split_speech("— Не здорово, — отозвался Шень Янь. — Ты здесь третий день.")
        assert s.speech == ["Не здорово"]
        assert "отозвался" in s.action

    def test_leading_dash_is_skipped_before_searching(self):
        """不跳过行首那个破折号的话，正则会咬住它，
        head 变成空串、台词整句丢掉，而报出来的理由指向完全错误的地方。"""
        s = sp.split_speech("— Это я, — сказал он.")
        assert s.speech == ["Это я"]

    def test_no_attribution_is_reported_not_guessed(self):
        """拆不动就说拆不动 —— 猜一个然后让配音念错更糟。"""
        s = sp.split_speech("— Просто иду мимо.")
        assert s.speech == []
        assert "归属小句" in s.uncertain

    def test_trailing_dash_content_is_flagged(self):
        """归属之后还有破折号：可能是第二句台词，也可能是「不是」的意思。
        分不开，说出来。"""
        s = sp.split_speech("— Это я, — сказал он. — А он — нет.")
        assert s.uncertain


class TestShotDuration:
    """首尾帧之间超过五秒就会审美疲劳 —— 走路、海浪、粒子，
    五秒之内是一个动作，五秒之后是同一个动作重复。
    这不是审美偏好，是 i2v 的能力边界。"""

    def test_static_capped_at_five(self):
        ms, why = sp.clamp_shot_ms(9800, action=False)
        assert ms == sp.STATIC_MAX_MS
        assert "疲劳" in why

    def test_action_capped_shorter(self):
        ms, _ = sp.clamp_shot_ms(4200, action=True)
        assert ms == sp.ACTION_MAX_MS
        assert sp.ACTION_MAX_MS < sp.STATIC_MAX_MS

    def test_too_short_is_lifted(self):
        ms, why = sp.clamp_shot_ms(400, action=False)
        assert ms == sp.MIN_MS and "看清" in why

    def test_in_range_untouched(self):
        assert sp.clamp_shot_ms(3800, action=False) == (3800, "")

    def test_action_words_both_languages(self):
        """分镜的描述可能是中文也可能是英文。"""
        assert sp.is_action_beat("裴无咎挥刀砍下")
        assert sp.is_action_beat("he leaps across the gap")
        assert not sp.is_action_beat("沈砚坐在门后听")


class TestJunkGuard:
    """解析成功不等于内容干净。"""

    def test_model_invented_placeholder(self):
        """我们给它 {{CHAR:xxx}}，它还回来 ⟦E1⟧ ——
        restore_placeholders 只认 {{}}，还原不了，垃圾直接进成品。"""
        assert "⟦E1⟧" in sp.translation_junk("— Это я. ⟦E1⟧ сказал.")

    def test_json_skeleton_fragment(self):
        """JSON 解出来了、字段也在，只是值里混进了骨架本身。
        逐条看译文时眼睛会自动跳过句尾那串括号。"""
        assert sp.translation_junk("Он шагнул вперёд. }]}]}]}")

    def test_unrestored_own_placeholder(self):
        assert sp.translation_junk("Он сказал {{CHAR:abc123}} тихо.")

    def test_clean_text_passes(self):
        assert sp.translation_junk("Он поставил чашку на перила.") == []


class TestQuoteLossInTranslation:
    """中译英之后「不巧。」变成了裸的 Not so fortunate. —— 引号没了。

    拆不出台词的后果是这条对白**一句配音都没有**，
    比混进旁白更糟：观众只会觉得这个角色突然哑了。
    """

    def test_dialogue_without_quotes_becomes_speech(self):
        s = sp.split_speech("Not so fortunate.", is_dialogue=True, source="「不巧。」")
        assert s.speech == ["Not so fortunate."]
        assert s.uncertain

    def test_lost_quotes_are_named_as_a_translation_defect(self):
        """原文有引号而译文没有 —— 那是译文的问题，不是「这段没人说话」。"""
        s = sp.split_speech("Not so fortunate.", is_dialogue=True, source="「不巧。」")
        assert "译文丢了引号" in s.uncertain

    def test_source_without_quotes_reads_differently(self):
        s = sp.split_speech("He said nothing.", is_dialogue=True,
                            source="他什么也没说。")
        assert s.speech and "译文丢了引号" not in s.uncertain

    def test_narration_block_is_unaffected(self):
        """非对白块没有引号就是真的没人说话，不该被当成台词。"""
        s = sp.split_speech("沈砚没点灯。他把腰刀横在膝上。")
        assert s.speech == [] and not s.uncertain

    def test_has_quotes_helper(self):
        assert sp.has_quotes("「不巧。」")
        assert sp.has_quotes('"Not so fortunate."')
        assert not sp.has_quotes("Not so fortunate.")


class TestVisibleChange:
    """首尾帧之间必须有看得见的变化。

    实跑里分镜给的是：
        镜 3  油布掀开声响结束，沈砚依然静坐
        镜 4  门外传来低骂声，沈砚依然静止
        镜 8  裴无咎收起笑容，铁钎直立地面   ← 这一句被七个镜头共用
    「声响结束」在画面上什么都不变，「依然静坐」是明说不动。
    首尾帧于是几乎相同，i2v 插不出任何东西 —— 那就是幻灯片。
    30 镜里有 24 镜是这样。
    """

    def test_physical_action_passes(self):
        for t in ("他向前走两步，推开药匣子", "沈砚推门而出，站起身来",
                  "he steps forward and opens the chest"):
            ok, _ = sp.is_visible_change(t)
            assert ok, t

    def test_sound_only_is_rejected(self):
        ok, why = sp.is_visible_change("门外脚步声由远及近")
        assert not ok and "声音" in why

    def test_explicit_no_change_is_rejected_first(self):
        """判据顺序有讲究：「油布掀开声响结束，沈砚依然静坐」里
        「掀开」是可见动词，但整句的意思是「什么都没变」——
        先看动词会判成通过。"""
        ok, why = sp.is_visible_change("油布掀开声响结束，沈砚依然静坐")
        assert not ok and "没有变化" in why

    def test_expression_change_is_rejected(self):
        """表情微变在五秒的镜头里看不出来。"""
        ok, _ = sp.is_visible_change("裴无咎收起笑容，铁钎直立地面")
        assert not ok

    def test_empty_is_rejected_with_its_own_reason(self):
        ok, why = sp.is_visible_change("")
        assert not ok and "没有写" in why

    def test_duplicates_are_found(self):
        """几镜共用同一句，意味着那几镜的尾帧长得一样，
        剪在一起像同一个画面播了几遍 ——
        重复本身就是「这几镜其实没分开」的证据。"""
        dups = sp.duplicate_changes([(8, "A"), (10, "A"), (12, "A"), (9, "B")])
        assert dups == [{"text": "A", "shots": [8, 10, 12]}]

    def test_blank_instructions_are_not_counted_as_duplicates(self):
        assert sp.duplicate_changes([(1, ""), (2, None), (3, "  ")]) == []

    def test_camera_motion_accepts_handheld_lips_and_pan(self):
        assert sp.is_camera_motion("镜头轻微手持，捕捉对白口型")[0]
        assert sp.is_camera_motion("slow pan right with natural blinking")[0]
        assert not sp.is_camera_motion("脚步声由远及近")[0]


class TestHeldShotDuration:
    """静态镜的时长上限。

    STATIC_MAX_MS 的 8 秒是给**对话镜**的 —— 画面定着但声音在走，
    注意力在台词上。空镜定场、情绪停顿没有这层声音，
    8 秒纯定格观众会以为播放器卡了。
    """

    def test_held_shot_is_capped_shorter_than_dialogue(self):
        assert sp.HELD_MAX_MS < sp.STATIC_MAX_MS
        capped, why = sp.clamp_shot_ms(8000, action=False, held=True)
        assert capped == sp.HELD_MAX_MS
        assert "定格" in why

    def test_held_overrides_the_action_keyword_guess(self):
        """分镜明示「这一镜不动」时，关键词猜测不该翻盘。

        词表是兜底，模型的标注是判断 —— 一句「他拔刀出鞘的余音未散」
        命中「拔刀」会被猜成动作镜，可画面上什么都没动。
        """
        capped, _ = sp.clamp_shot_ms(8000, action=True, held=True)
        assert capped == sp.HELD_MAX_MS

    def test_normal_shots_keep_their_old_caps(self):
        """held 是新增的一档，不能顺手改掉原来两档的行为。"""
        assert sp.clamp_shot_ms(9000, action=False)[0] == sp.STATIC_MAX_MS
        assert sp.clamp_shot_ms(9000, action=True)[0] == sp.ACTION_MAX_MS


class TestShotPlanPrompt:
    def test_prompt_demands_a_physical_action(self):
        """原来的提示词写的是「变化要小而明确」，模型照做了，
        于是写出「依然静坐」—— 那不是模型不听话，
        是没人告诉过它「变化必须看得见」。"""
        import inspect

        from app.pipelines import shot_plan

        src = inspect.getsource(shot_plan)
        assert "必须是一个看得见的物理动作" in src
        assert "脚步声由远及近" in src      # 反例要写进去
        assert "每一镜的变化说明必须互不相同" in src

    def test_prompt_offers_hold_instead_of_faking_motion(self):
        """「写不出动作就标 hold」必须和「动作必须看得见」同时存在。

        只留后者，模型就被逼着给对话镜、情绪停顿编一个假动作 ——
        「他收起笑容」五秒内看不出来，首尾帧生成出来几乎一样，
        视频模型插不出东西，白烧八十秒，成片里还是一张静止画面。
        只留前者，模型会拿 hold 当偷懒出口，成片变幻灯片。
        两句话是一对，缺一不可，所以一起守。
        """
        import inspect

        from app.pipelines import shot_plan

        src = inspect.getsource(shot_plan)
        assert '"animate"' in src and '"camera"' in src and '"hold"' in src
        assert "主体与摄影机都不动才标 hold" in src
        assert "四成以内" in src              # 比例上限，防幻灯片
        assert "拿不准时优先 animate" in src    # 边界情况往安全一侧倒

    def test_shot_schema_requires_motion(self):
        """motion 必须是 required —— 选填的话模型会整批不填，
        全部退回 animate，等于这个改动没发生过。"""
        from app.pipelines.shot_plan import SHOT_SCHEMA

        item = SHOT_SCHEMA["properties"]["shots"]["items"]
        assert "motion" in item["required"]
        assert item["properties"]["motion"]["enum"] == ["animate", "camera", "hold"]


class TestScriptAsides:
    """剧本正文里不该有模型的思考过程。

    实跑：「Tyler转头看向身旁的Chubbs（即Brad Lee的同伙，此处原文指代混乱，
    根据上下文Brad Lee是说话者……」—— 起因是绰号没在人物表里说明，
    模型把 Chubbs 当成了另一个人，然后把这份困惑写进了场记。

    这段话不会停在剧本里：制作单会读走它、写进出图提示词，
    最后变成画面上一段没人要的东西。而 JSON 解析、字段校验、
    场次统计全都正常，报表上一片绿。
    """

    @pytest.mark.parametrize("text", [
        "Tyler转头看向Chubbs（即Brad Lee的同伙，此处原文指代混乱）",
        "两人对视。根据上下文，这里应是同一个人。",
        "他推开门（译者注：原文为窗）",
    ])
    def test_asides_are_caught(self, text):
        from app.pipelines.screenplay import script_asides

        assert script_asides(text)

    @pytest.mark.parametrize("text", [
        "Tyler 猛地抬手，一巴掌扇在 Thomas Chen 脸上。",
        "Thomas Chen 低着头，双手死死攥住校服口袋。",
        "走廊尽头的窗透进光，尘埃在光柱里浮着。",
        # 拉丁标记必须按整词找 —— 裸子串把 "sic" 匹进了 "sick"，
        # 一句完全正常的台词被报成模型旁注。实跑撞到过：
        # "Tommy, what's wrong? Are you sick?"
        "Tommy, what's wrong? Are you sick?",
        "the music stopped",
        "a basic mistake",
    ])
    def test_normal_lines_pass(self, text):
        """场记本来就会写括号和状语，台词里也会出现 sick/music。
        这一栏非空是要人去看的，喊狼喊多了就没人看了。"""
        from app.pipelines.screenplay import script_asides

        assert not script_asides(text)

    @pytest.mark.parametrize("text,mark", [
        ("原文如此 [sic]", "sic"),
        ("TN: 原文为窗", "TN"),
    ])
    def test_real_latin_markers_still_caught(self, text, mark):
        from app.pipelines.screenplay import script_asides

        assert mark in script_asides(text)

    def test_build_reports_them(self):
        import inspect

        from app.pipelines import script_build

        src = inspect.getsource(script_build.build_script)
        assert "sp.script_asides" in src
        assert '"asides"' in src


class TestCastBrief:
    """同一个人的几种叫法要一起喂给剧本模型。

    译文里李爽既叫 Brad Lee 也叫 Chubbs（绰号按语域译的），
    不给人物表，剧本模型就当成两个角色 —— 往后说话人分不清、
    配音分不到嗓子、分镜不知道镜头该给谁。
    """

    def test_cast_is_injected_into_the_prompt(self):
        import inspect

        from app.pipelines import script_build

        assert "cast_brief(db, chapter, transform)" in inspect.getsource(
            script_build.build_script)

    def test_no_transform_means_no_cast_list(self):
        """原语言剧本没有译名可列，硬凑一份只会是噪声。"""
        from app.pipelines.script_build import cast_brief

        assert cast_brief(None, None, None) == ""

    def test_stale_full_name_is_not_listed_as_an_alias(self):
        """抽取会给本名也登记一条 formal_full 称呼，字面与 display_name 一样。

        它与人名映射是同一件事的两份副本，而改译名时只改了映射那份。
        于是人物表里出现「Thomas Chen 又叫 Thomas Ashford」——
        一个正文里根本不存在的名字，模型收到只会更糊涂。
        """
        import inspect

        from app.pipelines import script_build

        src = inspect.getsource(script_build.cast_brief)
        assert "a.source_surface == ent.display_name" in src
        assert "_is_common_address" in src, "「that whelp」不是这个人的另一个名字"


class TestActionBeats:
    """一个 action 块只写一个节拍 —— 一个节拍＝一个 3–5 秒的镜头。

    实跑里模型给出的块长这样：
      「清晨5:30，闹钟响起。Thomas Chen起床复习功课，吃完早餐后向母亲要了
        十美元。步行五分钟到达学校。」
    四个节拍、两个地点、半小时。分镜看到的是**一个块**，于是只出一个镜，
    首尾帧之间跨了半小时 —— 出图模型只能自己编中间发生了什么，
    首帧还在卧室，尾帧已经在校门口，人物衣着光线全会漂。
    """

    def test_the_real_case_is_split(self):
        got = sp.split_action(
            "清晨5:30，闹钟响起。Thomas Chen起床复习功课，"
            "吃完早餐后向母亲要了十美元。步行五分钟到达学校。")
        assert len(got) >= 3
        assert any("闹钟" in b for b in got)
        assert any("学校" in b for b in got), "地点转移必须单独成拍"

    def test_a_single_picture_is_not_split(self):
        """长描写不算多节拍 —— 切开会把一个镜头拆成三个静止帧。"""
        one = "走廊尽头的窗透进光，尘埃在光柱里浮着，地板反着冷白的反光。"
        assert sp.split_action(one) == [one]
        assert sp.action_is_overloaded(one)[0] is False

    def test_only_true_fragments_merge_back(self):
        """只并没有主体的拟声残片。

        **拆细是可逆的，塞粗是不可逆的** —— 分镜那一步可以把相邻的块
        并进同一个镜头，却几乎不会把一个块拆成两个。所以宁可多切一刀
        让分镜去合。「他愣住。」是一个合法的反应镜头，不该被并掉；
        「啪。」没有主体，才是残片。
        """
        assert len(sp.split_action("Tyler抬手扇了他一巴掌。啪。")) == 1
        assert len(sp.split_action("Tyler抬手扇了他一巴掌。他愣住。")) == 2

    def test_a_real_short_beat_survives(self):
        """**6 而不是 12。** 第一版阈值 12，把「步行五分钟到达学校。」
        （10 字）当碎片并了回去 —— 而那是一次地点转移。"""
        got = sp.split_action(
            "他吃完早餐，向母亲要了十美元。步行五分钟到达学校。")
        assert len(got) == 2

    def test_empty_and_single_are_safe(self):
        assert sp.split_action("") == []
        assert sp.split_action("他推门进去。") == ["他推门进去。"]

    def test_only_action_blocks_are_split(self):
        """对白拆两半就成了两个人在说；narration 本来就不进画面。"""
        from app.pipelines.script_build import _one_beat_blocks

        raw = [
            {"type": "dialogue", "text": "Hey, kid. Hand it over. Now."},
            {"type": "narration", "text": "那是九十年代。天很冷。风很大。"},
            {"type": "action", "text": "他推开门。走进走廊。灯光刺眼。"},
        ]
        out = _one_beat_blocks(raw)
        assert sum(1 for b in out if b["type"] == "dialogue") == 1
        assert sum(1 for b in out if b["type"] == "narration") == 1
        assert sum(1 for b in out if b["type"] == "action") >= 2

    def test_split_blocks_keep_their_other_fields(self):
        from app.pipelines.script_build import _one_beat_blocks

        out = _one_beat_blocks([
            {"type": "action", "text": "他推开门。走进走廊。灯光刺眼。",
             "speaker": None, "beat": "b1"}])
        assert all(b.get("beat") == "b1" for b in out)

    def test_the_prompt_says_it_too(self):
        """规则层是保证，提示词是让模型一次做对。"""
        from app.pipelines.script_build import SYSTEM_PROMPT

        assert "一个 action 块只写一个节拍" in SYSTEM_PROMPT
        assert "固定机位" in SYSTEM_PROMPT


class TestDurationTiers:
    """上限按内容分档，不是一刀切。

    用户原话：「谈话可以拉长到 5-8s 一个镜头，只是人物嘴唇动，
    没有大幅度运镜，所以不需要分镜很多；但是一旦出现快速打斗场面
    可能 1-2s 就要一个分镜」。

    一刀切 5 秒的后果两头都错：对话镜被切成两半（同一张脸接同一张脸，
    反而更像卡带），打斗镜又切得不够（一次出击、一次格挡、一次踉跄
    压进一镜，首尾帧只记得住头尾那两个，中间那个直接消失）。
    """

    def test_talking_gets_more_room_than_fighting(self):
        assert sp.STATIC_MAX_MS > sp.ACTION_MAX_MS

    def test_the_numbers_match_what_was_asked(self):
        assert sp.STATIC_MAX_MS == 8000, "对话 5–8 秒"
        assert sp.ACTION_MAX_MS == 2000, "打斗 1–2 秒"

    def test_a_long_conversation_is_not_over_cut(self):
        from app.pipelines.shot_plan import _coverage_slices

        got = _coverage_slices(15000, cap=sp.STATIC_MAX_MS)
        assert len(got) == 2 and all(5000 <= x <= 8000 for x in got)

    def test_a_fight_is_cut_fine(self):
        from app.pipelines.shot_plan import _coverage_slices

        got = _coverage_slices(5000, cap=sp.ACTION_MAX_MS)
        assert len(got) >= 3 and all(x <= sp.ACTION_MAX_MS for x in got)

    def test_shot_plan_picks_the_tier_by_content(self):
        import inspect

        from app.pipelines import shot_plan

        src = inspect.getsource(shot_plan.build_shot_plan)
        assert "sp.is_action_beat(" in src
        assert "sp.HELD_MAX_MS if held" in src
        assert "sp.ACTION_MAX_MS if action and not camera_only" in src
        assert "sp.STATIC_MAX_MS" in src
