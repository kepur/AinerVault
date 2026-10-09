"""电影导演模块与纳逗Pro结构化提示词矩阵测试。"""
from __future__ import annotations

import json
import pytest

from app.pipelines import cinematic_director as cd
from app.pipelines import director_review as dr


def test_shot_scales_and_camera_moves_completeness():
    for scale in ("ecu", "cu", "mcu", "ms", "fs", "ws", "ews"):
        assert scale in cd.SHOT_SCALES
        assert cd.SHOT_SCALES[scale]["lens"]
        assert cd.SHOT_SCALES[scale]["framing"]

    for move_key, move_info in cd.CAMERA_MOVES.items():
        assert "name_cn" in move_info
        assert "desc_en" in move_info
        # 确保没有危险的破坏潜空间运镜
        assert "orbit" not in move_info["desc_en"].lower()
        assert "spin" not in move_info["desc_en"].lower()


def test_nadou_structured_prompt_formatting():
    shot = cd.CinematicShot(
        shot_index=1,
        size="cu",
        angle="low_angle",
        camera_move="handheld_tracking",
        transition_type="cut",
        first_frame_desc="女孩倒在雪地上，仰头看着天空，白色头盔，黑色滑雪镜架在头盔前。",
        action_physics="胸口微微起伏，吐出白雾，在雪地里释怀大笑。",
        audio_cues="呼啸风声与雪地微声，女孩轻快的笑声",
        duration_sec=3.5,
        visual_style="自然电影级质感，高对比雪地光影，手持摄影质感。",
        scene_setting="阳光刺眼的高山雪坡，皑皑白雪覆盖的滑雪道。",
        character_ref="参考 [滑雪服定妆照] [多角度定妆照] 中的女孩，粉色滑雪服。",
        prompt_blocks={"运镜": "手持微晃动态跟镜"},
    )
    formatted = cd.format_nadou_prompt_blocks(shot)
    assert "【视觉风格】自然电影级质感" in formatted
    assert "【场景设定】阳光刺眼的高山雪坡" in formatted
    assert "【角色参考】参考 [滑雪服定妆照]" in formatted
    assert "【画面构图】女孩倒在雪地上" in formatted
    assert "【运镜】手持微晃动态跟镜" in formatted
    assert "【动作物理】胸口微微起伏" in formatted
    assert "【音频拟音】呼啸风声与雪地微声" in formatted


def test_ltx_motion_prompt_builds_continuation_and_single_camera():
    shot = cd.CinematicShot(
        shot_index=2,
        size="ms",
        angle="eye_level",
        camera_move="slow_push_in",
        transition_type="continuation",
        first_frame_desc="Skier falling into snow.",
        action_physics="Skis cross unexpectedly, momentum pitches body forward into deep powder snow spray.",
        audio_cues="snow impact thud and wind rushing",
        duration_sec=4.0,
    )
    prompt = cd.build_ltx_motion_prompt(shot, is_continuation=True)
    assert "The action continues seamlessly from the initial frame" in prompt
    assert "Skis cross unexpectedly" in prompt
    assert "Camera movement: Camera slowly and smoothly pushes in" in prompt
    assert "Cinematic live-action film footage" in prompt
    assert "Audio: snow impact thud and wind rushing" in prompt


def test_dp_first_frame_prompt_removes_ambiguity():
    shot = cd.CinematicShot(
        shot_index=1,
        size="ecu",
        angle="low_angle",
        first_frame_desc="Extreme closeup of ski goggles reflecting the snow peaks.",
    )
    prompt = cd.build_first_frame_prompt(shot, "Snowy alpine slopes", "Female skier in orange gear")
    assert "extreme close-up" in prompt.lower()
    assert "low angle from near the snow surface" in prompt
    assert "85mm macro lens" in prompt
    assert "sharp focus" in prompt


def test_plan_cinematic_film_orchestration(monkeypatch):
    mock_llm_response = json.dumps({
        "title": "滑雪少女的穿越",
        "style": "自然电影级质感，高对比雪地光影，手持摄影质感",
        "scene": "A steep alpine ski slope under bright winter sunlight",
        "character": "Young woman in bright orange ski suit with helmet and goggles",
        "audio_ambient": "Cold wind rushing and snow crunching under boots",
        "shots": [
            {
                "shot_index": 1,
                "size": "ms",
                "angle": "eye_level",
                "camera_move": "handheld_tracking",
                "transition": "cut",
                "first_frame": "The woman stands atop the slope, looking down, holding ski poles.",
                "action_physics": "She pushes off smoothly, carving down the slope with fine snow spray.",
                "audio": "Ski edges carving snow",
                "seconds": 3.5,
            },
            {
                "shot_index": 2,
                "size": "fs",
                "angle": "low_angle",
                "camera_move": "low_angle_pan",
                "transition": "continuation",
                "first_frame": "Gliding at speed down the slope.",
                "action_physics": "Her skis cross, body pitches forward, tumbling into soft powder snow.",
                "audio": "Impact thud and snow erupting",
                "seconds": 4.0,
            },
            {
                "shot_index": 3,
                "size": "cu",
                "angle": "eye_level",
                "camera_move": "slow_push_in",
                "transition": "cut",
                "first_frame": "Lying on the snow looking up, snow on goggles and jacket.",
                "action_physics": "She brushes snow off her gloves, breathing a cloud of white frost, laughing.",
                "audio": "Soft laughing breath in cold air",
                "seconds": 3.0,
            },
        ],
    })
    monkeypatch.setattr(dr, "_chat", lambda *a, **k: (mock_llm_response, "qwen3.6"))
    result = cd.plan_cinematic_film(None, "滑雪女孩摔倒又笑着爬起来", shots_count=3)
    assert result["title"] == "滑雪少女的穿越"
    assert len(result["shots"]) == 3
    assert result["shots"][0].transition_type == "cut"
    assert result["shots"][1].transition_type == "continuation"
    assert result["shots"][2].transition_type == "cut"
    assert "continues seamlessly" in result["shots"][1].motion_prompt_en


def test_max_shot_duration_hard_limit_and_clamping():
    assert cd.MAX_SHOT_DURATION_SEC == 5.0

    # 超出 5.0 秒必须被自动限幅至 5.0 秒
    oversized_shot = cd.CinematicShot(shot_index=1, duration_sec=8.0)
    assert oversized_shot.duration_sec == 5.0

    normal_shot = cd.CinematicShot(shot_index=2, duration_sec=4.5)
    assert normal_shot.duration_sec == 4.5

    undersized_shot = cd.CinematicShot(shot_index=3, duration_sec=0.2)
    assert undersized_shot.duration_sec == cd.MIN_SHOT_DURATION_SEC


def test_validate_montage_sequence_rules():
    # 场景 1：错误配置——前一镜正在跌倒，后一镜用 continuation 尾帧硬接导致跌倒动作重演
    bad_shots = [
        cd.CinematicShot(
            shot_index=1,
            size="ws",
            transition_type="cut",
            duration_sec=3.0,
            action_physics="The woman leans forward, skis cross and she starts falling sideways.",
        ),
        cd.CinematicShot(
            shot_index=2,
            size="cu",
            transition_type="continuation",  # 错误：上一镜未闭环动作强行 continuation
            duration_sec=3.0,
            action_physics="She tumbles softly into the deep powder snow.",
        ),
    ]
    errors = cd.validate_montage_sequence(bad_shots)
    assert len(errors) == 1
    assert "违反剪辑规范" in errors[0]
    assert "不得使用尾帧延续 (continuation) 重复摔倒" in errors[0]

    # 场景 2：标准规范配置——5s 炫技长帧 + 2s 贴雪特写 Cut + 3s 中景站立 Cut
    standard_shots = [
        cd.CinematicShot(
            shot_index=1,
            size="ws",
            transition_type="cut",
            duration_sec=5.0,  # 5s 炫技长镜头
            action_physics="The female skier accelerates powerfully, carving smooth deep turns with dynamic snow spray.",
        ),
        cd.CinematicShot(
            shot_index=2,
            size="cu",
            transition_type="cut",  # 规范：果断切镜头 (Cut)，景别骤变至贴雪特写
            duration_sec=2.0,  # 2s 特写爆点
            action_physics="A dramatic cut to ground-level close-up. Skis catch in deep powder, tumbling into the snow bank.",
        ),
        cd.CinematicShot(
            shot_index=3,
            size="ms",
            transition_type="cut",  # 规范：中景分切收尾
            duration_sec=3.0,  # 3s 收尾
            action_physics="From kneeling on the snow, she pushes herself upward and stands completely tall, brushing off snow.",
        ),
    ]
    clean_errors = cd.validate_montage_sequence(standard_shots)
    assert len(clean_errors) == 0

