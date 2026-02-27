"""
SKILL Registry — Orchestrator 通过此注册表按 skill_id 调度对应的 Service。

用法:
    registry = SkillRegistry(db)
    result = registry.dispatch("skill_01", input_dto, ctx)
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from app.api.deps import publish

from .skills.skill_01_story_ingestion import StoryIngestionService
from .skills.skill_02_language_context import LanguageContextService
from .skills.skill_03_scene_shot_plan import SceneShotPlanService
from .skills.skill_04_entity_extraction import EntityExtractionService
from .skills.skill_05_audio_asset_plan import AudioAssetPlanService
from .skills.skill_07_canonicalization import CanonicalizationService
from .skills.skill_08_asset_matcher import AssetMatcherService
from .skills.skill_09_visual_render_plan import VisualRenderPlanService
from .skills.skill_10_prompt_planner import PromptPlannerService
from .skills.skill_11_rag_kb_manager import RagKBManagerService
from .skills.skill_12_rag_embedding import RagEmbeddingService
from .skills.skill_13_feedback_loop import FeedbackLoopService
from .skills.skill_14_persona_style import PersonaStyleService
from .skills.skill_15_creative_control import CreativeControlService
from .skills.skill_16_critic_evaluation import CriticEvaluationService
from .skills.skill_17_experiment import ExperimentService
from .skills.skill_18_failure_recovery import FailureRecoveryService
from .skills.skill_19_compute_budget import ComputeBudgetService
from .skills.skill_21_entity_registry_continuity import EntityRegistryContinuityService
from .skills.skill_22_persona_dataset_index import PersonaDatasetIndexService

# skill_id → Service class 映射
_SKILL_MAP: dict[str, type[BaseSkillService]] = {
    "skill_01": StoryIngestionService,
    "skill_02": LanguageContextService,
    "skill_03": SceneShotPlanService,
    "skill_04": EntityExtractionService,
    "skill_05": AudioAssetPlanService,
    # skill_06 在 composer 服务中
    "skill_07": CanonicalizationService,
    "skill_08": AssetMatcherService,
    "skill_09": VisualRenderPlanService,
    "skill_10": PromptPlannerService,
    "skill_11": RagKBManagerService,
    "skill_12": RagEmbeddingService,
    "skill_13": FeedbackLoopService,
    "skill_14": PersonaStyleService,
    "skill_15": CreativeControlService,
    "skill_16": CriticEvaluationService,
    "skill_17": ExperimentService,
    "skill_18": FailureRecoveryService,
    "skill_19": ComputeBudgetService,
    # skill_20 在 composer 服务中
    "skill_21": EntityRegistryContinuityService,
    "skill_22": PersonaDatasetIndexService,
}
_SKILL_EVENT_PUBLISH_SET = frozenset({"skill_11", "skill_12", "skill_13"})


class SkillRegistry:
    """SKILL 注册表 — 负责 skill_id → Service 实例化和调度。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._instances: dict[str, BaseSkillService] = {}

    def get(self, skill_id: str) -> BaseSkillService:
        """获取 SKILL Service 实例（单例缓存）。"""
        if skill_id not in _SKILL_MAP:
            raise ValueError(
                f"Unknown skill_id: {skill_id}. "
                f"Available: {sorted(_SKILL_MAP.keys())}"
            )
        if skill_id not in self._instances:
            self._instances[skill_id] = _SKILL_MAP[skill_id](self.db)
        return self._instances[skill_id]

    def dispatch(self, skill_id: str, input_dto: Any, ctx: SkillContext) -> Any:
        """调度执行指定 SKILL。"""
        service = self.get(skill_id)
        logger.info(f"[SkillRegistry] Dispatching {skill_id} for run={ctx.run_id}")
        result = service.run(input_dto, ctx)
        self._publish_skill_events(skill_id, result)
        return result

    @staticmethod
    def _extract_event_payloads(result: Any) -> list[dict[str, Any]]:
        envelopes = getattr(result, "event_envelopes", None)
        if not envelopes:
            return []

        payloads: list[dict[str, Any]] = []
        for envelope in envelopes:
            if hasattr(envelope, "model_dump"):
                payloads.append(envelope.model_dump(mode="json"))
            elif isinstance(envelope, dict):
                payloads.append(envelope)
        return payloads

    def _publish_skill_events(self, skill_id: str, result: Any) -> None:
        if skill_id not in _SKILL_EVENT_PUBLISH_SET:
            return

        events = self._extract_event_payloads(result)
        if not events:
            return

        for event_payload in events:
            publish(SYSTEM_TOPICS.SKILL_EVENTS, event_payload)

    @staticmethod
    def list_skills() -> list[str]:
        """列出所有已注册的 skill_id。"""
        return sorted(_SKILL_MAP.keys())

    @staticmethod
    def is_registered(skill_id: str) -> bool:
        return skill_id in _SKILL_MAP
