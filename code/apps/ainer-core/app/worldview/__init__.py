"""世界观转译：中国古代 → 日本昭和 / 欧洲中世纪。

四层映射：
  L1 人名   naming.py + entity_world_names（含 family_key 家族姓氏一致性）
  L2 称谓   world_profiles.language_json.honorifics
  L3 名物   matcher.py + mining.py + survey.py + world_lexicon
  L4 视觉   entity_world_visual

两阶段审核：
  起飞前  preflight.py  —— 审几百条词表，管全书几十万字
  落地后  validator.py  —— 三道闸自动扫，人工只看违规
"""
from app.worldview.matcher import Hit, LexiconMatcher, scan_forbidden
from app.worldview.mining import mine_candidates
from app.worldview.injector import compose_system_prompt
from app.worldview.validator import Violation, build_retry_feedback, check_translation

__all__ = [
    "LexiconMatcher", "Hit", "scan_forbidden", "mine_candidates",
    "compose_system_prompt", "check_translation", "build_retry_feedback", "Violation",
]
