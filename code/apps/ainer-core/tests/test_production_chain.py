"""从已锁定译本到最终成品的连接契约。

这些测试专门防「字段已经存了，但真正生产的函数没有读它」。
"""
from __future__ import annotations

import pytest

import inspect
from pathlib import Path


def test_prose_and_screenplay_have_independent_active_versions():
    from app.pipelines import script_build

    src = inspect.getsource(script_build.activate_doc)
    assert "ScriptDoc.doc_mode == doc.doc_mode" in src


def test_target_screenplay_reads_only_locked_translation():
    from app.pipelines import script_build

    src = inspect.getsource(script_build._production_text)
    assert "TranslationBlock.locked" not in src  # lock is checked on the loaded row
    assert "translations[b.id].locked" in src
    assert '"production_source": "locked_translation"' in src
    assert "if transform is None" in src
    assert "translated_text or block.source_text" not in src


def test_target_names_are_rebound_to_stable_entities_across_production_steps():
    from app.pipelines import performance, script_build, shot_plan, speakers

    assert "load_entity_surfaces" in inspect.getsource(script_build.build_script)
    assert "speaker_entity_id" in inspect.getsource(script_build.build_script)
    assert "entity_index.catalog()" in inspect.getsource(shot_plan.build_shot_plan)
    assert "transform_id=plan.transform_id" in inspect.getsource(
        performance.extract_performance)
    assert "transform_id=transform_id" in inspect.getsource(speakers.resolve_speakers)


def test_shot_plan_refuses_a_screenplay_from_another_world_projection():
    from app.pipelines import shot_plan

    src = inspect.getsource(shot_plan.build_shot_plan)
    assert "script_transform != transform.id" in src
    assert "当前剧本不是从这个已锁定译本生成" in src


def test_frame_prompt_consumes_crew_motion_and_invalidates_stale_composition():
    from app.pipelines import frame_compose

    compose = inspect.getsource(frame_compose.compose_frame_prompt)
    generate = inspect.getsource(frame_compose.generate_first_frames)
    assert "crew_prompts" in compose and "motion.start_frame_en" in compose
    assert "production_revision" in generate
    assert "请先重新「绑定素材并拼 prompt」" in generate


def test_chapter_outputs_are_persisted_and_visible():
    from app.pipelines import audiobook, cut

    assert '"purpose": "audiobook_final"' in inspect.getsource(audiobook.render_audiobook)
    assert '"purpose": "final_cut"' in inspect.getsource(cut.render)
    html = (Path(__file__).resolve().parent.parent / "app" / "static" / "admin.html").read_text()
    assert "逐章录入（章节标题 + 正文）" in html
    assert "🎧 有声小说 · 连续试听" in html
    assert "🎬 电影剪辑台 · 试看成片" in html


def test_audiobook_timeline_tolerates_stale_missing_asset_links():
    """存量 AudioSpec 可能指向已清理的 Asset；章节页应显示缺失，不应 500。"""
    from app.pipelines import audiobook

    src = inspect.getsource(audiobook.build_timeline)
    assert "if asset is not None else" in src


def test_film_audio_never_generates_narration():
    from app.pipelines import audio_compose, delivery, handoff

    compile_src = inspect.getsource(audio_compose.compile_audio)
    generate_src = inspect.getsource(audio_compose.generate_audio)
    assert "if not is_dialogue" in compile_src
    assert "电影小说不是有声书" in compile_src
    assert "AudioSpec.kind != AudioKind.narration" in generate_src
    assert all(track[0] != "narration" for track in handoff.TRACKS)
    assert "AudioKind.dialogue, AudioKind.narration" not in inspect.getsource(
        delivery.build_manifest)


def test_sync_dialect_result_is_not_overwritten_by_generating():
    """提交后不能无条件把规格写回「生成中」。

    同步方言在 submit_task **内部**就完成了回挂：那一刻规格已经是
    ready、asset_id 也有值。提交方返回后再写一次 generating，就把刚
    挂上的结果盖掉了。

    盖掉之后没有任何一条路能修回来 —— 任务已是终态，回调不会再送，
    poll_task 见终态直接返回，而 regenerate=False 的提交只挑 pending。
    于是规格永远停在「生成中」，尽管 wav 就在库里、任务也写着成功，
    界面上每一步都显示成功。实测一次整章跑完卡住 125 条。
    """
    from app.pipelines import audio_compose

    src = inspect.getsource(audio_compose.generate_audio)
    marker = "spec.status = SpecStatus.generating"
    assert marker in src
    before = src.split(marker)[0]
    guard = before.rstrip().rsplit("\n", 1)[-1].strip()
    assert guard == "if spec.asset_id is None:", (
        f"「生成中」写在了 {guard!r} 下面 —— 它必须被"
        "「确实还没有产物」这一条挡住，否则同步方言的结果会被盖掉")


class TestScreenplayProjectionGuard:
    """有了锁定译本就不能再照原文出剧本。

    不传 transform 时静默回落到 chapter.content，产出是一份中文剧本：
    场景写着「J市第二中学教学楼一层走廊」，时间写「日」。它看起来完全
    正常 —— 有场次、有对白、有时长，每一步都成功 —— 而整条影片线从这里
    起就走在原文世界里：出图提示词是中文（图像模型不认），人名没过映射，
    名物没过词表，要到成片才看得出来。

    实跑撞到的正是这个：接口字段叫 transform_id，调用方传了 language=en-US，
    多余字段被静默忽略，于是拿到一份中文剧本。
    """

    def test_guard_exists_and_names_the_transform(self):
        import inspect

        from app.pipelines import script_build

        src = inspect.getsource(script_build._production_text)
        assert "_active_transform_with_locked_prose" in src
        assert "transform_id=" in src, "报错要给出该传哪个映射"

    def test_only_locked_translations_block(self):
        """建了映射还没开始翻的时候照原文出剧本是合理的 ——
        那时根本没有译本可用。拦在那里只会变成一个挡路的误报。"""
        import inspect

        from app.pipelines import script_build

        src = inspect.getsource(script_build._active_transform_with_locked_prose)
        assert "TranslationBlock.locked.is_(True)" in src

    def test_escape_hatch_is_real(self):
        """报错里许诺的 allow_source 必须真的存在，否则那句话是空头支票。"""
        import inspect

        from app.api.v2.script import GenerateIn
        from app.pipelines import script_build

        assert "allow_source" in GenerateIn.model_fields
        assert "allow_source" in inspect.signature(
            script_build.build_script).parameters
        assert "allow_source" in inspect.getsource(script_build._production_text)


class TestShotPlanBatching:
    """分镜要在场内分批，否则一场三十多个镜头一次吐不完。

    每个镜头要吐 description + first_frame + last_frame + 可见差异
    + 出场人物 + 素材键，四五百 token 起步。截断重试把预算抬到 8192
    之后仍然两轮都截断，报出来是「输出太多」——
    根因是这一层从来没在场内分过批。

    上游把场记按节拍拆细之后这个坑才浮出来：块从 91 变成 113，
    镜头数跟着涨，一次性生成再也装不下。拆细是对的
    （首尾帧之间跨半小时会漂），代价是这里必须分批。
    """

    def _blocks(self, n):
        return [f"b{i}" for i in range(n)]

    def test_small_scene_is_one_call(self):
        from app.pipelines.shot_plan import _chunk_scene

        assert len(_chunk_scene(self._blocks(6), 5)) == 1

    def test_large_scene_is_split(self):
        from app.pipelines.shot_plan import _SHOTS_PER_CALL, _chunk_scene

        parts = _chunk_scene(self._blocks(33), 34)
        assert len(parts) > 1
        assert all(c <= _SHOTS_PER_CALL for _b, c in parts)

    def test_no_block_is_lost(self):
        """丢块就是丢剧情 —— 而它不会报错，只会让那几句话没有画面。"""
        from app.pipelines.shot_plan import _chunk_scene

        for n, count in ((33, 34), (7, 25), (100, 41), (1, 9)):
            parts = _chunk_scene(self._blocks(n), count)
            assert sum(len(b) for b, _c in parts) == n, (n, count)

    def test_shot_budget_is_preserved(self):
        from app.pipelines.shot_plan import _chunk_scene

        for n, count in ((33, 34), (50, 27), (12, 11)):
            parts = _chunk_scene(self._blocks(n), count)
            assert sum(c for _b, c in parts) == count, (n, count)

    def test_never_more_batches_than_blocks(self):
        """块比镜头少时不能切出空批 —— 空批会让模型凭空造镜头。"""
        from app.pipelines.shot_plan import _chunk_scene

        parts = _chunk_scene(self._blocks(3), 30)
        assert len(parts) <= 3
        assert all(b for b, _c in parts)

    def test_generation_uses_the_chunker(self):
        import inspect

        from app.pipelines import shot_plan

        src = inspect.getsource(shot_plan.build_shot_plan)
        assert "_chunk_scene(scene_blocks, count)" in src


class TestSpeakerMustBeOnScreen:
    """对白镜头的出场人物里必须有说话人。

    entity_names 是模型的判断，而这一镜覆盖的对白块上写着 speaker_tag ——
    那是上一步定下来的事实，不是判断。坏蛋实跑里镜 2 的台词是
    Tyler Kao 说的（speaker_tag 写得清清楚楚），模型却把出场人物填成了
    Brad Lee，于是首帧提示词描述的是另一个人 —— 画面里张嘴的那张脸是错的，
    而台词、配音、时间轴全都对。这种错只有把画面和台词摆在一起才看得出来。
    """

    def test_rule_exists_and_prefers_the_fact(self):
        import inspect

        from app.pipelines import shot_plan

        src = inspect.getsource(shot_plan.build_shot_plan)
        assert "b.speaker_entity_id" in src
        assert "BlockType.dialogue" in src

    def test_correction_is_reported_not_silent(self):
        """悄悄补上等于把一处模型错误藏起来 ——
        这个数字等于「有几镜的画面里张嘴的是另一张脸」。"""
        from app.pipelines.shot_plan import ShotPlanResult

        assert "speaker_added" in ShotPlanResult().as_dict()

    def test_only_dialogue_blocks_pull_a_speaker_in(self):
        """场记块没有说话人 —— 拿它的 speaker_tag 去补会把空值塞进出场人物。"""
        import inspect

        from app.pipelines import shot_plan

        src = inspect.getsource(shot_plan.build_shot_plan)
        gate = src[src.index("for b in shot_blocks:"):][:400]
        assert "is not BlockType.dialogue" in gate and "continue" in gate


class TestCoverageSplit:
    """一镜超过五秒就切机位。

    一个画面停五秒以上观众会觉得卡住；首尾帧插值本身也撑不住更长 ——
    超过五秒开始变慢动作糊影。坏蛋第一章实测 143 镜里 27 个超过 10 秒，
    最长 37 秒。

    **切的是机位，不是内容。** 一句十五秒的台词没法缩短，能做的是换角度
    覆盖它：说话人正面、听者反应、手部特写。这是剪辑里 coverage 的本意。
    """

    @pytest.mark.parametrize("dur", [1200, 3000, 4999, 5000])
    def test_short_shots_are_left_alone(self, dur):
        from app.pipelines.shot_plan import _coverage_slices

        assert _coverage_slices(dur) == [dur]

    @pytest.mark.parametrize("dur", [7300, 13700, 37380, 60000])
    def test_long_shots_all_land_in_range(self, dur):
        from app.pipelines.shot_plan import _SHOT_MAX_MS, _coverage_slices

        got = _coverage_slices(dur)
        assert len(got) > 1
        assert all(x <= _SHOT_MAX_MS for x in got), got

    def test_total_duration_is_preserved(self):
        """切机位不该改变这一段占的时间 —— 时间轴要对得上配音。"""
        from app.pipelines.shot_plan import _coverage_slices

        for dur in (7300, 13700, 37380):
            assert sum(_coverage_slices(dur)) == dur

    def test_slices_are_even(self):
        """「切满五秒再留个零头」会留下一秒的尾巴，剪在一起像卡了一下。"""
        from app.pipelines.shot_plan import _coverage_slices

        got = _coverage_slices(37380)
        assert max(got) - min(got) <= 1

    def test_the_split_is_reported(self):
        """剪的人要知道哪几个镜头本来是一条，
        才不会当成连续动作去接。"""
        from app.pipelines.shot_plan import ShotPlanResult

        assert "split_for_length" in ShotPlanResult().as_dict()

    def test_build_uses_the_splitter(self):
        import inspect

        from app.pipelines import shot_plan

        src = inspect.getsource(shot_plan.build_shot_plan)
        assert "_coverage_slices(\n" in src or "_coverage_slices(" in src
        assert "for slice_idx, dur in enumerate(slices)" in src


class TestSwearWordsAreNotRelatives:
    """骂人的虚词被当成了亲属称谓。

    中文的「妈的」「你妈」「草你妈」里那个「妈」是语气，不指任何人。
    逐字译过去就凭空多出一个母亲 —— 而这一步不会报错，句子读着也通顺。

    坏蛋实跑的样子：校园走廊抢劫那场，三句台词全变成了对「Mom」说话：
        「草你妈的，别和我罗嗦」 → "Fuck you, Mom. Stop rambling"
        「妈的，给你脸你不要脸」 → "Mom, we gave you a chance..."
    整章 21 句剧本块中招。更麻烦的是这一章后面真有主角的妈妈，
    下游再也分不出哪个 Mom 是人：选角把她排进出场名单、配音照念、
    口型照对，最后成片里一群高中生在走廊里喊妈。
    """

    @pytest.mark.parametrize("line", [
        "草你妈的，别和我罗嗦，快点",
        "妈的，给你脸你不要脸",
        "去你妈的，你有钱吗",
        "他妈的真烦",
        "行，操你妈的，你给我等着",
    ])
    def test_swearing_is_detected(self, line):
        from app.pipelines.audit import _SWEAR_MOTHER

        assert _SWEAR_MOTHER.search(line)

    @pytest.mark.parametrize("line", [
        "家里只有他的妈妈在",
        "谢妈妈说：快点吃饭吧，一会都凉了",
        "为了不引起妈妈的怀疑，谢文东拿起饭碗",
        "妈妈是下岗工人",
        "向妈妈要了十元钱上学去了",
    ])
    def test_a_real_mother_is_left_alone(self, line):
        """**叠词「妈妈」永远是称谓。**

        「为了不引起妈妈的怀疑」里含着「妈的」三个字 —— 不排掉叠词，
        这句正经叙述会被报成骂人。同一章里两种用法都有，所以这条不能
        靠「这本书脏话多」之类的整体判断来糊弄。
        """
        from app.pipelines.audit import _SWEAR_MOTHER

        assert not _SWEAR_MOTHER.search(line)

    def test_only_flagged_when_the_translation_actually_says_mom(self):
        """原文骂人、译文也骂人 —— 那是对的，不该报。"""
        from app.pipelines.audit import _MOTHER_WORD, _SWEAR_MOTHER

        source, good = "草你妈的，别和我罗嗦", "Fuck off, stop rambling"
        assert _SWEAR_MOTHER.search(source)
        assert not _MOTHER_WORD.search(good)

    def test_the_rule_is_in_the_translation_prompt_too(self):
        """规则层是兜底，提示词里也要说 —— 拦下来不如一开始就别译错。"""
        from app.pipelines import translate

        assert "Mom" in translate._PROFANITY_RULE
        for kind in ("dialogue", "narration", "inner_monolog"):
            assert "语气助词" in translate._KIND_RULES[kind]


class TestRejectedRequestsAreNotResubmittedForever:
    """供应商说了不可重试，就别再投第二次。

    挑活的判据是「有没有产物」，而被明确拒绝的规格永远不会有产物 ——
    于是每调用一次 :generate 都把同一批重新投一遍，永远投不完。

    坏蛋实跑的样子：本地 foley 只做固定语义（脚步、衣料、撞击、纸张、
    风雨雷、环境床），「汽车喇叭」「喉咙紧绷」这类直接回 INVALID_REQUEST
    且 retryable=false。三十轮下来每一轮都报「提交 3 条」，成功数一直
    停在 5，而没有任何一步说过投不出去 —— 报表上看着一直在干活。

    只挡 retryable=false：超时、掉线、服务重启那些都该再试。
    """

    def test_a_flat_refusal_is_skipped_with_a_reason(self):
        from app.pipelines.audio_compose import _unsupported_reason

        spec, task = _spec(), _task(
            "failed", {"code": "INVALID_REQUEST", "retryable": False,
                       "message": "audio.sfx 暂不支持这个音效语义"})
        why = _unsupported_reason(_Sess(task), spec, regenerate=False)
        assert why and "暂不支持" in why

    def test_a_retryable_failure_is_tried_again(self):
        from app.pipelines.audio_compose import _unsupported_reason

        task = _task("failed", {"code": "TIMEOUT", "retryable": True,
                                "message": "上游超时"})
        assert _unsupported_reason(_Sess(task), _spec(), regenerate=False) is None

    def test_a_failure_with_no_retryable_flag_is_tried_again(self):
        """没表态就当可以重试 —— 宁可多试一次，不要漏掉能做的。"""
        from app.pipelines.audio_compose import _unsupported_reason

        task = _task("failed", {"code": "UPSTREAM_ERROR", "message": "崩了"})
        assert _unsupported_reason(_Sess(task), _spec(), regenerate=False) is None

    def test_an_explicit_regenerate_overrides_the_refusal(self):
        """重出是人明确要求的，不挡 —— 也许换了供应商。"""
        from app.pipelines.audio_compose import _unsupported_reason

        task = _task("failed", {"retryable": False, "message": "做不了"})
        assert _unsupported_reason(_Sess(task), _spec(), regenerate=True) is None


class _Sess:
    def __init__(self, task):
        self._task = task

    def get(self, _model, _id):
        return self._task


def _spec():
    from app.models import AudioKind

    return type("S", (), {"gen_task_id": "gt_x", "kind": AudioKind.sfx,
                          "text": "car horn in the distance"})()


def _task(status, err):
    from app.models import TaskStatus

    return type("T", (), {"status": TaskStatus(status), "error_json": err})()


class TestRuleLayerOverridesWhatTheModelWontFix:
    """模型改不掉的禁用词，按词条表直接改掉。

    **试过三次都不行。** 提示词里写了「骂人的虚词不是称谓」，词条表
    登记了「草你妈的 → Fuck you，禁用 Mom」，strict 还带着违规反馈重译
    了一次 —— 五个块里仍有四个把「妈」译成 Mom，其中一版把
    「Fuck you, Mom」改成了「Shit, Mom」：换了脏话，留着妈。

    到这一步该由规则接手。词条表已经写明正确译法，改法是确定的，
    不必再赌模型这一次听不听。
    """

    def _fix(self, text, expected):
        from app.worldview.validator import Violation, repair_forbidden

        return repair_forbidden(text, [Violation(
            kind="forbidden_token", severity="high",
            detected="Mom", expected=expected)])

    def test_a_spare_vocative_is_deleted(self):
        """正确译法已经在句子里 —— 那个 Mom 是多出来的一声称呼。"""
        out, fixes = self._fix('"Fuck you, Mom! Stop rambling."', "Fuck you")
        assert out == '"Fuck you! Stop rambling."'
        assert fixes

    def test_an_em_dash_vocative_too(self):
        out, _ = self._fix('"Fine. Fuck you, Mom—just wait!"', "Fuck you")
        assert out == '"Fine. Fuck you—just wait!"'

    def test_the_swear_itself_is_replaced_when_there_is_no_other(self):
        """「Mom's」就是「妈的」被逐字搬过来了 —— 整段换成词条译法。"""
        out, _ = self._fix('"Mom\'s, you don\'t know when to quit."', "Damn it")
        assert out.startswith('"Damn it, you don')
        assert "Mom" not in out

    def test_a_real_mother_is_never_touched(self):
        """真在跟母亲说话的句子命不中词条，走不到这里 ——
        即便走到了，没有违规就什么都不改。"""
        from app.worldview.validator import repair_forbidden

        line = '"Mom, dinner is ready," she called from the kitchen.'
        out, fixes = repair_forbidden(line, [])
        assert out == line and not fixes

    def test_medium_violations_are_left_to_the_model(self):
        """只覆写 high 的禁用词。漏译那类要人看，不该被规则悄悄抹平。"""
        from app.worldview.validator import Violation, repair_forbidden

        line = '"Fuck you, Mom!"'
        out, fixes = repair_forbidden(line, [Violation(
            kind="lexicon_miss", severity="medium",
            detected="Mom", expected="Fuck you")])
        assert out == line and not fixes

    def test_the_pipeline_rechecks_after_repairing(self):
        """规则改完要复检 —— 改坏了得看得见，不能就地宣布干净。"""
        import inspect

        from app.pipelines import translate

        src = inspect.getsource(translate.translate_chapter)
        after = src.split("repair_forbidden")[1]
        assert "check_translation" in after.split("record_violations")[0]


def test_the_budget_is_spent_on_work_that_can_actually_be_done():
    """先筛掉不该投的，再按 limit 截断 —— 顺序不是风格问题。

    先截断的话，预算会被开头那几条「投不出去」的吃光：实跑里前三条
    恰好都是本地 foley 做不了的音效，于是每次调用都是 submitted=0 /
    skipped=3，后面二十五条可做的永远排不上队，而接口一直回 200。

    这也是活锁的真实代价 —— 不只是白跑，是把能做的饿死了：三十轮下来
    成功数停在 5/33，而其中二十条本来就在 foley 的词表里。
    """
    import inspect

    from app.pipelines import audio_compose

    src = inspect.getsource(audio_compose.generate_audio)
    assert src.index("_unsupported_reason") < src.index("eligible[:limit]"), (
        "limit 截断必须排在资格筛选之后，否则预算会被跳过的规格吃光")
