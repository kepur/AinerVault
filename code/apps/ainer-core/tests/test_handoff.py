"""手动模式 —— 轨道化时间轴、提示词成型、三种导出。

导出的三种文件各有各的硬约束，全都是「格式对了但用不了」那一类：
SRT 里多一行说明，播放器把它当第一句台词；
CSV 里留一个换行，一格提示词被拆成好几行、行号与镜号就对不上。
"""
from __future__ import annotations

import pytest

from app.pipelines import handoff as hf


class TestTimecode:
    def test_format(self):
        assert hf.timecode(0) == "00:00:00,000"
        assert hf.timecode(93_456) == "00:01:33,456"
        assert hf.timecode(3_600_000) == "01:00:00,000"

    def test_sep_switches_for_srt_vs_nle(self):
        """SRT 用逗号，给剪辑软件看的用点。播放器认死了逗号那一种。"""
        assert hf.timecode(1500, sep=",") == "00:00:01,500"
        assert hf.timecode(1500, sep=".") == "00:00:01.500"

    def test_negative_clamped(self):
        assert hf.timecode(-5) == "00:00:00,000"


class TestSpeechEstimate:
    def test_cjk_and_latin_use_different_rates(self):
        """中文按字、西文按词。混用一种速率会让整章时间码整体漂移。"""
        cn = hf.estimate_speech_ms("林昭抬起头，没有说话。")
        en = hf.estimate_speech_ms("Lin Zhao raised his head and said nothing.")
        assert cn > 0 and en > 0
        # 同样长度的字符串，中文更快念完 —— 一个汉字承载的信息多于一个字母
        assert cn < en

    def test_empty_is_zero_not_minimum(self):
        """空文本给 0，不给下限 —— 「没有台词」和「有一句很短的台词」
        在时间轴上不是一回事。"""
        assert hf.estimate_speech_ms("") == 0
        assert hf.estimate_speech_ms("   ") == 0

    def test_short_line_has_floor(self):
        assert hf.estimate_speech_ms("走。") >= hf._MIN_LINE_MS


class TestImageFormatting:
    def test_midjourney_drops_sentence_like_negatives(self):
        """MJ 的 --no 只吃名词短语。塞整句进去不但无效，
        还可能被当成要画的内容。"""
        out = hf.format_image(
            "a man behind a door", "blurry, watermark, "
            "a very long sentence describing what must not appear",
            target="midjourney", aspect="16:9")
        assert "--ar 16:9" in out
        assert "--no blurry, watermark" in out
        assert "a very long sentence" not in out

    def test_sd_keeps_full_negative(self):
        out = hf.format_image("a man", "blurry, extra fingers",
                              target="sd", aspect="16:9")
        assert out.startswith("Positive:")
        assert "Negative:\nblurry, extra fingers" in out

    def test_generic_carries_aspect(self):
        out = hf.format_image("a man", "", target="generic", aspect="21:9")
        assert "【画幅】21:9" in out

    def test_empty_prompt_yields_empty(self):
        """没有提示词就是空字符串 —— 不要拼一个只有画幅的壳子出来，
        那会让「待手搓」的格子看上去像已经写好了。"""
        assert hf.format_image("", "blurry", target="generic", aspect="16:9") == ""


class TestVideoFormatting:
    def test_missing_frames_say_so(self):
        """首尾帧地址是手搓时要上传的文件。缺了要写明缺，
        不能留空 —— 空白处人会以为不需要。"""
        out = hf.format_video("slow push in", first_url=None,
                              last_url=None, duration_ms=4000)
        assert "未生成" in out
        assert "4.0s" in out

    def test_missing_motion_is_not_disguised_as_static(self):
        """缺运动要由缺口面板阻断，不能用一句 static 冒充生产提示词。"""
        out = hf.format_video("", first_url="u", last_url=None, duration_ms=2000)
        assert out == ""


class TestSpeechFormatting:
    def test_carries_speaker_voice_and_instruct(self):
        out = hf.format_speech("你来晚了。", speaker="沈砚", voice="Aiden",
                               instruct="低沉沙哑，语速偏慢", language="zh-CN")
        assert out.startswith("你来晚了。")
        assert "沈砚" in out and "Aiden" in out
        assert "【表演指示】低沉沙哑，语速偏慢" in out

    def test_no_meta_line_when_nothing_known(self):
        out = hf.format_speech("走。", speaker=None, voice=None,
                               instruct=None, language=None)
        assert out == "走。"


class TestExports:
    """导出的三种文件各有各的硬约束。"""

    def _fake(self):
        return {
            "chapter": {"title": "第3章"},
            "aspect_ratio": "16:9", "target": "generic",
            "total_duration_ms": 5000, "shots": 2,
            "notes": "note",
            "gaps": [{"track": "dialogue", "shot": 1, "why": "没绑音色",
                      "fix": "去配音表"}],
            "resources": {"anchors": [{"url": "http://x/a.png", "role": "character",
                                       "shots": [1, 2]}]},
            "tracks": [
                {"id": "dialogue", "name": "对白", "hint": "h", "ready": 1, "manual": 0,
                 "clips": [{"key": "dialogue:1:0", "track": "dialogue", "shot": 1,
                            "start_ms": 0, "duration_ms": 2000, "tc": "00:00:00.000",
                            "label": "开场", "asset_url": "http://x/a.wav",
                            "status": "ready", "speaker": "沈砚",
                            "copy": "你来晚了。\n【说话人 沈砚】",
                            "detail": {}, "refs": []}]},
                {"id": "frame_first", "name": "首帧", "hint": "h", "ready": 0, "manual": 1,
                 "clips": [{"key": "frame_first:1:0", "track": "frame_first", "shot": 1,
                            "start_ms": 0, "duration_ms": 2000, "tc": "00:00:00.000",
                            "label": "门缝", "asset_url": None, "status": "manual",
                            "copy": "a narrow door gap", "detail": {},
                            "refs": [{"role": "character", "url": "http://x/a.png"}]}]},
            ],
        }

    def test_srt_has_no_preamble(self):
        """SRT 里任何非字幕内容都会被播放器当成第一句台词显示出来。"""
        srt = hf.to_srt(self._fake())
        assert srt.startswith("1\n00:00:00,000 --> ")
        assert "手搓" not in srt

    def test_srt_only_speech_tracks(self):
        srt = hf.to_srt(self._fake())
        assert "narrow door gap" not in srt

    def test_srt_uses_comma_separator(self):
        assert "-->" in hf.to_srt(self._fake())
        assert "00:00:00,000" in hf.to_srt(self._fake())

    def test_csv_flattens_newlines(self):
        """提示词里的换行必须压平 —— 否则一格提示词会被表格软件
        拆成好几行，行号和镜号就对不上了。"""
        csv_text = hf.to_csv(self._fake())
        body = [ln for ln in csv_text.splitlines() if ln and not ln.startswith("轨道")]
        assert len(body) == 2
        assert "⏎" in csv_text

    def test_csv_marks_manual_rows(self):
        csv_text = hf.to_csv(self._fake())
        assert "待手搓" in csv_text and "已生成" in csv_text

    def test_markdown_leads_with_gaps(self):
        """缺口要排在提示词前面。排在后面等于没写 ——
        人看到第一块可复制的文本就开始干活了。"""
        md = hf.to_markdown(self._fake())
        assert md.index("开工前要补的缺口") < md.index("a narrow door gap")

    def test_markdown_fences_prompts(self):
        md = hf.to_markdown(self._fake())
        assert "```\na narrow door gap\n```" in md


class TestBilingualCopy:
    """每格两份提示词。

    **中文那份不是英文的译文**，而是同一批数据的中文侧 ——
    shot.description、表演的中文表情动作、八工种的中文单，本来就都存着。
    它有两个真实用途：给人审核（英文提示词看不出这一镜在拍什么），
    以及直接喂认中文的国产模型。
    """

    def test_image_cn_puts_subject_before_crew(self):
        """和英文那份同一个道理：工种细节排在主体之前，
        出来的是一张打光样片而不是这一镜。"""
        out = hf.compose_image_cn(
            "沈砚在门后警惕等待，腰刀横在膝上。",
            [{"角色": "沈砚", "表情": "双目微眯", "动作": "坐在门后", "手持": ["腰刀"]}],
            {"lighting": "左前方45度硬光", "cinematography": "中近景，倾斜高角度"},
            aspect="16:9")
        assert out.index("沈砚在门后") < out.index("摄影：")
        assert out.index("摄影：") < out.index("灯光：")
        assert "【画幅】16:9" in out

    def test_image_cn_folds_props_list(self):
        out = hf.compose_image_cn("", [{"角色": "沈砚", "手持": ["腰刀", "油布"]}],
                                  {}, aspect=None)
        assert "腰刀、油布" in out

    def test_image_cn_keeps_chinese_negatives(self):
        """文化包的 visual_dont 本来就是中文。它在英文提示词里有害
        （模型不认，还可能被当成要画的内容），在中文那份里恰恰是对的。"""
        out = hf.compose_image_cn("门缝", [], {}, aspect=None,
                                  negative="美式元素、现代都市")
        assert "【不要】美式元素、现代都市" in out

    def test_video_cn_does_not_hide_missing_motion(self):
        """中文侧也不能用机位固定掩盖缺失的物理运动设计。"""
        out = hf.compose_video_cn({}, first_url=None, last_url=None,
                                  duration_ms=3000)
        assert out == ""

    def test_video_cn_orders_by_shooting_sequence(self):
        out = hf.compose_video_cn(
            {"节奏": "先慢后快", "起幅": "人静坐", "相机": "机位固定",
             "落幅": "人抬头", "主体": "头部侧转"},
            first_url="a", last_url="b", duration_ms=2000)
        order = [out.index(k) for k in ("起幅", "落幅", "相机", "主体", "节奏")]
        assert order == sorted(order)

    def test_speech_cn_does_not_translate_the_line_back(self):
        """台词是目标语言的成品，翻回中文就不是要念的那句了。
        中文侧给的是「谁在说、什么嗓子、怎么演」，加原文以便对照。"""
        out = hf.compose_speech_cn(
            "Не вовремя.", speaker="沈砚", voice="Aiden",
            instruct="低沉浑厚", habits="句式中长", language="ru-RU",
            source_text="不巧。")
        assert out.startswith("Не вовремя.")
        assert "【原文对照】不巧。" in out
        assert "【表演指示】低沉浑厚" in out
        assert "【语言习惯】句式中长" in out

    def test_speech_cn_omits_redundant_source(self):
        """原文与译文相同时不重复列一遍 —— 那只会让人以为漏译了。"""
        out = hf.compose_speech_cn("不巧。", speaker=None, voice=None,
                                   instruct=None, habits=None,
                                   language=None, source_text="不巧。")
        assert "原文对照" not in out

    def test_csv_carries_both_columns(self):
        rows = TestExports()._fake()
        rows["tracks"][0]["clips"][0]["copy_cn"] = "中文那份"
        text = hf.to_csv(rows)
        header = text.splitlines()[0]
        assert "提示词（英文·给模型）" in header
        assert "提示词（中文·给人／国产模型）" in header
        assert "中文那份" in text

    def test_markdown_labels_which_is_which(self):
        """两块代码围栏挨在一起时，没有标签人分不清该粘哪一块。"""
        rows = TestExports()._fake()
        rows["tracks"][1]["clips"][0]["copy_cn"] = "门缝里透进微光"
        md = hf.to_markdown(rows)
        assert "**英文 · 给模型**" in md
        assert "门缝里透进微光" in md
        assert md.index("a narrow door gap") < md.index("门缝里透进微光")


class TestLastFrameDerivation:
    def test_prefers_english_deltas_over_chinese_instruction(self):
        """ShotMotion.deltas_en_json 的注释写着「i2i 读的是这一条」，
        但这里从前读的是中文的 derive_instruction —— 它被直接接在英文提示词
        后面送进图像模型。设计了但没接线。"""
        from app.pipelines.frame_compose import _derive_en

        class F:
            derive_instruction = "门外脚步声由远及近，轻重分明"

        text, why = _derive_en(F(), ["head tilts 15 degrees", "fingers touch hilt"])
        assert text == "head tilts 15 degrees, fingers touch hilt"
        assert not why

    def test_chinese_instruction_never_reaches_the_model(self):
        """没有英文时不回落到中文 —— 宁可给一句中性的英文。
        但要报出来，否则「尾帧和首帧几乎一样」会被当成模型不给力。"""
        from app.pipelines.frame_compose import _derive_en

        class F:
            derive_instruction = "门外脚步声由远及近"

        text, why = _derive_en(F(), None)
        assert "门外" not in text
        assert text == "slight natural progression of the moment"
        assert "只有中文" in why

    def test_english_instruction_passes_through(self):
        from app.pipelines.frame_compose import _derive_en

        class F:
            derive_instruction = "eyes widen, hand tightens on hilt"

        text, why = _derive_en(F(), None)
        assert text == "eyes widen, hand tightens on hilt"
        assert not why

    def test_missing_instruction_is_reported(self):
        from app.pipelines.frame_compose import _derive_en

        class F:
            derive_instruction = None

        text, why = _derive_en(F(), None)
        assert text == "slight natural progression of the moment"
        assert why

    def test_last_frame_carries_explicit_aspect(self):
        """首帧一旦是从方形身份锚编辑出来的，尾帧跟随底图就会继承那个方形。"""
        import inspect

        from app.pipelines import frame_compose

        src = inspect.getsource(frame_compose.generate_last_frames)
        assert '"width": width_last' in src
        assert "_size_for(" in src
