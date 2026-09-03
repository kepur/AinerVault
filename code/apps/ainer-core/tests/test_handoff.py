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

    def test_static_default_when_no_motion(self):
        """静止也要明写，否则视频模型会自己加运动。"""
        out = hf.format_video("", first_url="u", last_url=None, duration_ms=2000)
        assert "static locked-off shot" in out


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
