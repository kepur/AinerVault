"""从已锁定译本到最终成品的连接契约。

这些测试专门防「字段已经存了，但真正生产的函数没有读它」。
"""
from __future__ import annotations

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
