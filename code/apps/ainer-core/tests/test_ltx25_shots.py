"""分镜走 LTX-2.5：一镜提示词怎么拼、对白驱动轨怎么排。"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from app.pipelines import ltx25_shots as L


def _sfx(text):
    return SimpleNamespace(text=text)


def test_prompt_order_framing_action_audio_and_nobody_speaks_without_dialogue():
    p = L.shot_prompt(SimpleNamespace(prompt="wide shot of a school corridor"),
                      SimpleNamespace(motion_prompt_en="Slow dolly in. The boy flinches."),
                      [_sfx("at 0.2s: dull thud of a back hitting the lockers. Long foley note for the mixer")], [])
    visual, action, audio = p.split("\n\n")
    assert visual.startswith("wide shot") and action.startswith("Slow dolly in")
    # 音效说明只留第一句；没对白要写死「没人说话」，不然模型会自己编台词
    assert "dull thud of a back hitting the lockers" in audio and "foley note" not in audio
    assert audio.endswith("No one speaks: no dialogue, no voices.")


def test_prompt_with_dialogue_names_the_speaker_and_drops_chinese_cues():
    p = L.shot_prompt(None, SimpleNamespace(motion_prompt_en="Handheld."),
                      [_sfx("青地面上的摩擦声。"), _sfx("heavy breathing nearby")], ["a stout boy with rainbow hair"])
    assert "青" not in p and "heavy breathing nearby" in p
    assert "a stout boy with rainbow hair speaks" in p


def test_prompt_stays_within_budget_and_keeps_the_audio_line():
    """首帧提示词只取开头（主体、景别）；运动单太长时截动作后半段，声音那行保住。"""
    p = L.shot_prompt(SimpleNamespace(prompt="v, " * 3000), SimpleNamespace(motion_prompt_en="m" * 5000), [], [])
    framing, action, audio = p.split("\n\n")
    assert len(p) <= L.PROMPT_BUDGET and audio.endswith("no voices.")
    assert len(framing) <= L.FRAMING_CHARS and action.startswith("m" * 400)


def test_scene_header_and_cast_come_first_and_speaker_is_referenced_by_number():
    """同一场戏每镜都写同一段场景头和人物外貌 —— 实跑里第 2 镜的首帧提示词写着「正午城市室外」，
    没有场景头就真出成了室外；说话的人用编号指代，不把外貌再抄一遍。"""
    p = L.shot_prompt(SimpleNamespace(prompt="close-up of the leader"), SimpleNamespace(motion_prompt_en="Slow pan."),
                      [], ["character (2)"], scene="school corridor, day, bright interior lighting",
                      characters=["stout boy, rainbow hair", "tall lanky boy, denim jacket"])
    header = p.split("\n\n")[0]
    assert header.startswith("Setting (the same location and lighting for every shot of this scene): school corridor")
    assert "(1) stout boy, rainbow hair; (2) tall lanky boy, denim jacket" in header
    assert p.endswith("character (2) speaks; lips move in sync with the dialogue.")


@pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0, reason="需要 ffmpeg")
def test_drive_track_is_lead_plus_lines_plus_tail(tmp_path, monkeypatch):
    """驱动轨＝前留白＋逐句顺排＋后留白，和 build_timeline 排台词的位置一致。"""
    from app.capability import mediastore
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "media_dir", str(tmp_path))
    for name, secs in (("a.wav", 1.0), ("b.wav", 0.5)):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}",
                        "-ar", "24000", str(tmp_path / name)], check=True)
    assets = {"a1": SimpleNamespace(url="http://localhost:8100/media/a.wav"),
              "a2": SimpleNamespace(url="http://localhost:8100/media/b.wav")}
    shot = SimpleNamespace(order_no=2, camera_json={"dialogue_lead_ms": 300, "dialogue_tail_ms": 100})
    url, ms = L.drive_track(shot, [SimpleNamespace(asset_id="a1"), SimpleNamespace(asset_id="a2")], assets)
    assert url.endswith(".wav") and abs(ms - 1900) <= 30
    assert (mediastore.media_root() / url.rsplit("/media/", 1)[-1]).exists()


def test_style_line_leads_the_prompt_and_follows_the_plan_preset():
    """没有画风锚时，配音驱动的镜头被画成了皮克斯式卡通 —— 写实锚要放在最前面。"""
    plan = SimpleNamespace(config_json={})
    p = L.shot_prompt(None, SimpleNamespace(motion_prompt_en="Slow pan."), [], [], style=L.style_line(plan),
                      scene="school corridor")
    assert p.startswith("Live-action film footage, photorealistic") and "not cartoon" in p.split("\n\n")[0]
    anime = SimpleNamespace(config_json={"style_preset": {"render": "anime"}})
    assert L.style_line(anime).startswith("Japanese anime style")
