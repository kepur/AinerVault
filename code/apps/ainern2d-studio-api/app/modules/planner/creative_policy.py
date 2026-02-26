from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.schemas.timeline import ShotPlan


class CreativePolicyEvaluator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def evaluate(
        self,
        run_id: str,
        shot_plan: ShotPlan,
        policy_stack_id: str | None = None,
    ) -> dict:
        if policy_stack_id is None:
            return {"passed": True, "violations": [], "warnings": []}

        stack = self.db.get(CreativePolicyStack, policy_stack_id)
        if stack is None:
            return {"passed": True, "violations": [], "warnings": []}

        rules: list[dict] = (stack.stack_json or {}).get("rules", [])
        violations: list[str] = []
        warnings: list[str] = []

        for item in shot_plan.shots:
            for rule in rules:
                rule_type = rule.get("type", "warn")
                keywords = rule.get("blocked_keywords", [])
                prompt_lower = item.prompt.lower()
                for kw in keywords:
                    if kw.lower() in prompt_lower:
                        msg = (
                            f"Shot {item.shot_id}: keyword '{kw}' violates "
                            f"rule '{rule.get('name', 'unnamed')}'"
                        )
                        if rule_type == "block":
                            violations.append(msg)
                        else:
                            warnings.append(msg)

                max_dur = rule.get("max_duration_ms")
                if max_dur and item.duration_ms > max_dur:
                    msg = (
                        f"Shot {item.shot_id}: duration {item.duration_ms}ms "
                        f"exceeds max {max_dur}ms"
                    )
                    if rule_type == "block":
                        violations.append(msg)
                    else:
                        warnings.append(msg)

        return {
            "passed": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
        }

    def get_active_policy(
        self, tenant_id: str, project_id: str
    ) -> CreativePolicyStack | None:
        stmt = (
            select(CreativePolicyStack)
            .filter_by(
                tenant_id=tenant_id,
                project_id=project_id,
                status="active",
                deleted_at=None,
            )
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()
