"""Service-level E2E for SKILL 01 -> SKILL 02 handoff closure."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from ainern2d_shared.services.base_skill import SkillContext


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.add.return_value = None
    db.commit.return_value = None
    db.flush.return_value = None
    return db


@pytest.fixture
def ctx():
    return SkillContext(
        tenant_id="t_e2e_01_02",
        project_id="p_e2e_01_02",
        run_id="run_e2e_01_02",
        trace_id="tr_e2e_01_02",
        correlation_id="co_e2e_01_02",
        idempotency_key="idem_e2e_01_02",
        schema_version="1.0",
    )


def test_e2e_01_to_02_handoff_contract_chain(mock_db, ctx):
    from app.services.skills.skill_01_story_ingestion import StoryIngestionService
    from app.services.skills.skill_02_language_context import LanguageContextService
    from ainern2d_shared.schemas.skills.skill_01 import IngestionOptions, Skill01Input
    from ainern2d_shared.schemas.skills.skill_02 import Skill02Input

    s01 = StoryIngestionService(mock_db)
    s02 = LanguageContextService(mock_db)

    raw_story = (
        "第一章 江湖初见\n\n"
        "少年李牧背着旧剑走入风雪中的客栈，火盆旁坐着沉默旅人，掌柜低声提醒今夜不太平。"
        "他看见墙上残破的悬赏告示，心里想起失散多年的师兄，决定在天亮前查明线索。\n\n"
        "第二章 夜雨追踪\n\n"
        "夜雨敲打瓦檐，李牧沿着湿滑长街追寻黑衣人的脚印，转角处传来急促马蹄声与呼救声。"
        "他避开巡夜兵丁翻入后院，发现一封写着旧门派暗号的密信，局势骤然紧张。"
    )

    out01 = s01.execute(
        Skill01Input(
            raw_text=raw_story,
            input_source_type="manual_text",
            ingestion_options=IngestionOptions(enable_sentence_split=True),
        ),
        ctx,
    )

    assert out01.status in ("ready_for_routing", "review_required")
    assert out01.document_meta.project_id == ctx.project_id
    assert out01.tenant_id == ctx.tenant_id
    assert out01.project_id == ctx.project_id
    assert out01.trace_id == ctx.trace_id
    assert out01.correlation_id == ctx.correlation_id
    assert out01.idempotency_key == ctx.idempotency_key
    assert out01.schema_version == ctx.schema_version
    assert out01.version == ctx.schema_version
    assert out01.language_detection.primary_language.startswith("zh")
    assert out01.structure.paragraph_count >= 2
    assert out01.ingestion_log

    out02 = s02.execute(
        Skill02Input(
            primary_language=out01.language_detection.primary_language,
            secondary_languages=out01.language_detection.secondary_languages,
            normalized_text=out01.normalized_text,
            quality_status=out01.status,
            target_output_language="zh-CN",
            genre="wuxia",
            story_world_setting="historical jianghu",
        ),
        ctx,
    )

    assert out02.status in ("ready_for_planning", "review_required")
    assert out02.language_route.source_primary_language == out01.language_detection.primary_language
    assert out02.language_route.target_output_language == "zh-CN"
    assert out02.translation_plan.mode in ("none", "bilingual", "full")
    assert out02.culture_candidates
