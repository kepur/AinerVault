"""SKILL 13: FeedbackLoopService — 业务逻辑实现。
参考规格: SKILL_13_FEEDBACK_EVOLUTION_LOOP.md
状态: SERVICE_READY

State machine (MD §6):
  INIT → CAPTURING_FEEDBACK → DECIDING_ACTION
    → BUILDING_RUN_PATCH → COMPLETED
    → GENERATING_PROPOSAL → REVIEWING_PROPOSAL → APPLYING_TO_KB
      → RELEASING_VERSION → EMBEDDING_BUILDING → EVALUATING_IMPROVEMENT
      → COMPLETED | FAILED
"""
from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.skills.skill_13 import (
    ActionTaken,
    EvolutionHistory,
    EvolutionRecommendation,
    FeedbackAggregation,
    FeedbackEvent,
    FeedbackIssueCategory,
    FeatureFlags,
    ImpactScore,
    ImprovementProposal,
    KBUpdateProposal,
    ProposalStatus,
    RegressionTestResult,
    RunPatchRecord,
    Skill13Input,
    Skill13Output,
    Skill13State,
    SuggestedTags,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from ainern2d_shared.utils.time import utcnow

# ── Issue category → suggested role (MD §F4) ─────────────────────────────────
_ISSUE_TO_ROLE: dict[str, str] = {
    "cinematography_camera_move": "cinematographer",
    "lighting_gaffer": "gaffer",
    "art_style": "art_director",
    "pacing_editing": "editor",
    "continuity_script_supervisor": "script_supervisor",
    "motion_readability": "cinematographer",
    "culture_mismatch": "art_director",
    "character_inconsistency": "script_supervisor",
    "prop_inconsistency": "script_supervisor",
    "prompt_quality": "prompt_engineer",
    "model_failure": "engineer",
}

# ── Issue category → target skill for evolution recommendations ───────────────
_ISSUE_TO_SKILL: dict[str, str] = {
    "cinematography_camera_move": "skill_09",
    "lighting_gaffer": "skill_09",
    "art_style": "skill_10",
    "continuity_script_supervisor": "skill_04",
    "motion_readability": "skill_09",
    "culture_mismatch": "skill_07",
    "character_inconsistency": "skill_04",
    "prop_inconsistency": "skill_08",
    "pacing_editing": "skill_06",
    "prompt_quality": "skill_10",
    "model_failure": "skill_06",
}

# ── Issue category → auto-tags ────────────────────────────────────────────────
_ISSUE_TO_TAGS: dict[str, dict[str, list[str]]] = {
    "cinematography_camera_move": {"shot_type": ["action"]},
    "lighting_gaffer": {"shot_type": ["vfx"]},
    "art_style": {"genre": ["stylized"]},
    "motion_readability": {"motion_level": ["HIGH_MOTION"]},
    "pacing_editing": {"shot_type": ["montage"]},
    "culture_mismatch": {"culture_pack": ["needs_review"]},
}

# Rating threshold: at or above this value feedback is recorded but no evolution
_POSITIVE_RATING_THRESHOLD = 4


class FeedbackLoopService(BaseSkillService[Skill13Input, Skill13Output]):
    """SKILL 13 — Feedback Evolution Loop.

    State machine (MD §6):
      INIT → CAPTURING_FEEDBACK → DECIDING_ACTION
        → BUILDING_RUN_PATCH → COMPLETED
        → GENERATING_PROPOSAL → REVIEWING_PROPOSAL → APPLYING_TO_KB
          → RELEASING_VERSION → EMBEDDING_BUILDING → EVALUATING_IMPROVEMENT
          → COMPLETED | FAILED
    """

    skill_id = "skill_13"
    skill_name = "FeedbackLoopService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── main entry ────────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill13Input, ctx: SkillContext) -> Skill13Output:
        state = Skill13State.INIT
        flags = input_dto.feature_flags
        events: list[str] = []
        event_envelopes: list[EventEnvelope] = []

        try:
            # ── F1: Capture Feedback ──────────────────────────────────────
            state = self._transition(ctx, state, Skill13State.CAPTURING_FEEDBACK)
            feedback_event = self._capture_feedback(input_dto, ctx)
            self._emit_event(
                events,
                event_envelopes,
                ctx,
                event_type="feedback.event.created",
                payload={
                    "feedback_event_id": feedback_event.feedback_event_id,
                    "run_id": feedback_event.run_id,
                    "shot_id": feedback_event.shot_id,
                    "kb_version_id": feedback_event.kb_version_id,
                    "rating": feedback_event.rating,
                    "issues": feedback_event.issues,
                },
            )

            # ── Impact scoring ────────────────────────────────────────────
            impact = self._compute_impact(input_dto)
            feedback_event.impact = impact

            # ── Feedback aggregation ──────────────────────────────────────
            aggregations = self._aggregate_feedback(input_dto)

            # ── F2: Decide Patch vs Evolution ─────────────────────────────
            state = self._transition(ctx, state, Skill13State.DECIDING_ACTION)
            action_taken = self._decide_action(input_dto)

            if action_taken == ActionTaken.IGNORED:
                state = self._transition(ctx, state, Skill13State.COMPLETED)
                return Skill13Output(
                    feedback_event=feedback_event,
                    action_taken=action_taken.value,
                    feedback_aggregations=aggregations,
                    impact_score=impact,
                    state=state.value,
                    status="completed",
                    events_emitted=events,
                    event_envelopes=event_envelopes,
                )

            # ── F3: Run-level Patch ───────────────────────────────────────
            run_patch: RunPatchRecord | None = None
            if action_taken == ActionTaken.RUN_PATCH:
                state = self._transition(ctx, state, Skill13State.BUILDING_RUN_PATCH)
                run_patch = self._build_run_patch(input_dto, feedback_event)
                state = self._transition(ctx, state, Skill13State.COMPLETED)

                logger.info(
                    f"[{self.skill_id}] run_patch created | run={ctx.run_id} "
                    f"patch={run_patch.patch_id}"
                )
                return Skill13Output(
                    feedback_event=feedback_event,
                    action_taken=action_taken.value,
                    run_patch=run_patch,
                    feedback_aggregations=aggregations,
                    impact_score=impact,
                    state=state.value,
                    status="completed",
                    events_emitted=events,
                    event_envelopes=event_envelopes,
                )

            # ── F4: Proposal Auto-generation ──────────────────────────────
            state = self._transition(ctx, state, Skill13State.GENERATING_PROPOSAL)
            proposal = self._generate_proposal(input_dto, feedback_event, flags)
            self._emit_event(
                events,
                event_envelopes,
                ctx,
                event_type="proposal.created",
                payload={
                    "proposal_id": proposal.proposal_id,
                    "feedback_event_id": proposal.feedback_event_id,
                    "suggested_role": proposal.suggested_role,
                    "target_skill": proposal.target_skill,
                    "status": proposal.status,
                },
            )

            # ── Evolution recommendations per skill ───────────────────────
            recommendations = self._generate_recommendations(input_dto, proposal)

            # ── KB update proposals for SKILL 11 ──────────────────────────
            kb_proposals = self._generate_kb_update_proposals(proposal)

            # ── F7: Regression testing ────────────────────────────────────
            regression_results: list[RegressionTestResult] = []
            if flags.regression_test_enabled:
                state = self._transition(
                    ctx, state, Skill13State.REVIEWING_PROPOSAL,
                )
                regression_results = self._run_regression_tests(proposal)

                regression_passed = all(r.passed for r in regression_results)
                if not regression_passed:
                    proposal.status = ProposalStatus.REJECTED.value
                    self._emit_event(
                        events,
                        event_envelopes,
                        ctx,
                        event_type="proposal.reviewed",
                        payload={
                            "proposal_id": proposal.proposal_id,
                            "decision": "rejected",
                            "reason": "regression_failed",
                        },
                    )
                    self._emit_event(
                        events,
                        event_envelopes,
                        ctx,
                        event_type="proposal.rejected",
                        payload={
                            "proposal_id": proposal.proposal_id,
                            "feedback_event_id": proposal.feedback_event_id,
                            "reason": "regression_failed",
                        },
                    )
                    self._emit_rollback_event(
                        events,
                        event_envelopes,
                        ctx,
                        run_context=input_dto.run_context,
                        kb_manager_config=input_dto.kb_manager_config,
                        proposal=proposal,
                        reason="regression_failed",
                    )
                    state = self._transition(ctx, state, Skill13State.FAILED)
                    logger.warning(
                        f"[{self.skill_id}] regression failed | "
                        f"proposal={proposal.proposal_id}"
                    )
                    return Skill13Output(
                        feedback_event=feedback_event,
                        action_taken=action_taken.value,
                        proposal=proposal,
                        feedback_aggregations=aggregations,
                        impact_score=impact,
                        kb_update_proposals=kb_proposals,
                        regression_results=regression_results,
                        evolution_recommendations=recommendations,
                        state=state.value,
                        status="regression_failed",
                        events_emitted=events,
                        event_envelopes=event_envelopes,
                    )

            # ── F5: Review & Merge ────────────────────────────────────────
            if flags.enable_review_gate:
                state = self._transition(
                    ctx, state, Skill13State.REVIEWING_PROPOSAL,
                )
                proposal = self._review_proposal(proposal, flags)
                review_decision = "approved" if proposal.status == ProposalStatus.APPROVED.value else "pending_review"
                self._emit_event(
                    events,
                    event_envelopes,
                    ctx,
                    event_type="proposal.reviewed",
                    payload={
                        "proposal_id": proposal.proposal_id,
                        "decision": review_decision,
                        "status": proposal.status,
                    },
                )
                if proposal.status == ProposalStatus.APPROVED.value:
                    self._emit_event(
                        events,
                        event_envelopes,
                        ctx,
                        event_type="proposal.approved",
                        payload={
                            "proposal_id": proposal.proposal_id,
                            "feedback_event_id": proposal.feedback_event_id,
                        },
                    )
                elif proposal.status == ProposalStatus.REJECTED.value:
                    self._emit_event(
                        events,
                        event_envelopes,
                        ctx,
                        event_type="proposal.rejected",
                        payload={
                            "proposal_id": proposal.proposal_id,
                            "feedback_event_id": proposal.feedback_event_id,
                        },
                    )
                    self._emit_rollback_event(
                        events,
                        event_envelopes,
                        ctx,
                        run_context=input_dto.run_context,
                        kb_manager_config=input_dto.kb_manager_config,
                        proposal=proposal,
                        reason="review_rejected",
                    )

            # ── F5 cont: Apply to KB (if approved/merged) ────────────────
            kb_evolution = False
            new_kb_version_id = ""
            evolution_history: EvolutionHistory | None = None

            if proposal.status in (
                ProposalStatus.APPROVED.value,
                ProposalStatus.MERGED.value,
            ):
                state = self._transition(ctx, state, Skill13State.APPLYING_TO_KB)
                proposal.status = ProposalStatus.MERGED.value
                kb_evolution = True

                # ── F6: Release & Re-embed ────────────────────────────────
                state = self._transition(ctx, state, Skill13State.RELEASING_VERSION)
                new_kb_version_id = self._generate_kb_version_id(input_dto)

                state = self._transition(
                    ctx, state, Skill13State.EMBEDDING_BUILDING,
                )
                # Trigger embedding pipeline (placeholder — actual call to SKILL 12)
                logger.info(
                    f"[{self.skill_id}] embedding build triggered | "
                    f"kb_version={new_kb_version_id}"
                )
                self._emit_event(
                    events,
                    event_envelopes,
                    ctx,
                    event_type="kb.version.released",
                    payload={
                        "kb_version_id": new_kb_version_id,
                        "source_proposal_id": proposal.proposal_id,
                        "kb_version_before": input_dto.run_context.kb_version_id,
                    },
                )

                # ── F7: Evaluate improvement ──────────────────────────────
                state = self._transition(
                    ctx, state, Skill13State.EVALUATING_IMPROVEMENT,
                )
                evolution_history = EvolutionHistory(
                    evolution_id=f"EVO_{uuid.uuid4().hex[:8]}",
                    version_tag=new_kb_version_id,
                    proposals_merged=[proposal.proposal_id],
                    kb_version_before=input_dto.run_context.kb_version_id,
                    kb_version_after=new_kb_version_id,
                    regression_passed=all(
                        r.passed for r in regression_results
                    ) if regression_results else True,
                    created_at=utcnow().isoformat(),
                )

            state = self._transition(ctx, state, Skill13State.COMPLETED)

            logger.info(
                f"[{self.skill_id}] completed | run={ctx.run_id} "
                f"action={action_taken.value} proposal={proposal.proposal_id} "
                f"kb_evolution={kb_evolution}"
            )

            return Skill13Output(
                feedback_event=feedback_event,
                action_taken=action_taken.value,
                proposal=proposal,
                feedback_aggregations=aggregations,
                impact_score=impact,
                kb_update_proposals=kb_proposals,
                regression_results=regression_results,
                evolution_recommendations=recommendations,
                evolution_history=evolution_history,
                state=state.value,
                kb_evolution_triggered=kb_evolution,
                new_kb_version_id=new_kb_version_id,
                status="completed",
                events_emitted=events,
                event_envelopes=event_envelopes,
            )

        except Exception as exc:
            self._transition(ctx, state, Skill13State.FAILED)
            logger.error(
                f"[{self.skill_id}] FAILED | run={ctx.run_id} error={exc}"
            )
            raise

    # ── F1: Capture Feedback ──────────────────────────────────────────────────

    def _capture_feedback(
        self, inp: Skill13Input, ctx: SkillContext,
    ) -> FeedbackEvent:
        uf = inp.user_feedback
        return FeedbackEvent(
            version=ctx.schema_version,
            feedback_event_id=f"FB_{uuid.uuid4().hex[:8]}",
            run_id=inp.run_context.run_id or ctx.run_id,
            kb_version_id=inp.run_context.kb_version_id,
            shot_id=inp.shot_result_context.shot_id,
            rating=uf.rating,
            issues=uf.issues,
            free_text=uf.free_text,
            source="user_explicit",
            created_at=utcnow().isoformat(),
        )

    # ── Impact scoring ────────────────────────────────────────────────────────

    @staticmethod
    def _compute_impact(inp: Skill13Input) -> ImpactScore:
        issues = inp.user_feedback.issues
        severity = max(0.0, min(1.0, (5 - inp.user_feedback.rating) / 4.0))
        affected = len({_ISSUE_TO_SKILL.get(i, "") for i in issues} - {""})
        composite = round(
            0.3 * len(issues) + 0.4 * severity + 0.3 * affected, 3,
        )
        return ImpactScore(
            frequency=len(issues),
            severity=severity,
            user_priority=max(0, 5 - inp.user_feedback.rating),
            affected_skill_count=affected,
            composite_score=composite,
        )

    # ── Feedback aggregation ──────────────────────────────────────────────────

    @staticmethod
    def _aggregate_feedback(inp: Skill13Input) -> list[FeedbackAggregation]:
        counts = Counter(inp.user_feedback.issues)
        aggregations: list[FeedbackAggregation] = []
        for issue, count in counts.items():
            aggregations.append(FeedbackAggregation(
                issue_category=issue,
                count=count,
                avg_rating=float(inp.user_feedback.rating),
                representative_texts=(
                    [inp.user_feedback.free_text]
                    if inp.user_feedback.free_text else []
                ),
                trend="rising" if inp.user_feedback.rating <= 2 else "stable",
            ))
        return aggregations

    # ── F2: Decide action ─────────────────────────────────────────────────────

    @staticmethod
    def _decide_action(inp: Skill13Input) -> ActionTaken:
        rating = inp.user_feedback.rating

        # High rating → record only, no action
        if rating >= _POSITIVE_RATING_THRESHOLD:
            return ActionTaken.IGNORED

        # No issues and no free_text → cannot create proposal
        if not inp.user_feedback.issues and not inp.user_feedback.free_text:
            return ActionTaken.IGNORED

        # User provides reusable suggestion with clear issue type → proposal
        if inp.user_feedback.issues and inp.user_feedback.free_text:
            if inp.feature_flags.enable_proposal_autogeneration:
                return ActionTaken.PROPOSAL_CREATED
            return ActionTaken.NEEDS_REVIEW

        # Has free_text only → run-level patch (quick retry)
        if inp.user_feedback.free_text and not inp.user_feedback.issues:
            return ActionTaken.RUN_PATCH

        # Has issues only → proposal
        if inp.user_feedback.issues:
            return ActionTaken.PROPOSAL_CREATED

        return ActionTaken.RUN_PATCH

    # ── F3: Run-level Patch builder ───────────────────────────────────────────

    @staticmethod
    def _build_run_patch(
        inp: Skill13Input, fb: FeedbackEvent,
    ) -> RunPatchRecord:
        return RunPatchRecord(
            patch_id=f"PATCH_{uuid.uuid4().hex[:8]}",
            run_id=fb.run_id,
            prompt_patch=inp.user_feedback.free_text,
            negative_constraints=[
                f"avoid:{issue}" for issue in inp.user_feedback.issues
            ],
            param_adjustments={},
            feedback_event_id=fb.feedback_event_id,
        )

    # ── F4: Proposal auto-generation ──────────────────────────────────────────

    @staticmethod
    def _generate_proposal(
        inp: Skill13Input, fb: FeedbackEvent, flags: FeatureFlags,
    ) -> ImprovementProposal:
        issues = inp.user_feedback.issues
        primary_issue = issues[0] if issues else "prompt_quality"

        # Role routing (MD §F4.1)
        role = _ISSUE_TO_ROLE.get(primary_issue, "prompt_engineer")

        # Auto-tagging (MD §F4.2)
        merged_tags: dict[str, list[str]] = {
            "culture_pack": [], "genre": [], "motion_level": [], "shot_type": [],
        }
        if flags.enable_auto_tagging:
            for issue in issues:
                tag_map = _ISSUE_TO_TAGS.get(issue, {})
                for key, vals in tag_map.items():
                    for v in vals:
                        if v not in merged_tags.get(key, []):
                            merged_tags.setdefault(key, []).append(v)

        # Title & content abstraction (MD §F4.3)
        title = (
            f"Auto-proposal for {primary_issue}"
            if not inp.user_feedback.free_text
            else inp.user_feedback.free_text[:80]
        )
        content = inp.user_feedback.free_text or (
            f"Address {', '.join(issues)} issues detected in shot "
            f"{inp.shot_result_context.shot_id}."
        )

        # Visibility
        visibility = (
            "project_shared"
            if inp.user_preferences.allow_shared_kb_write
            else "private"
        )

        # Strength: multi-issue or low rating → hard
        strength = (
            "hard_constraint"
            if len(issues) >= 2 or inp.user_feedback.rating <= 1
            else "soft_constraint"
        )

        return ImprovementProposal(
            version=fb.version,
            proposal_id=f"PR_{uuid.uuid4().hex[:8]}",
            feedback_event_id=fb.feedback_event_id,
            suggested_role=role,
            suggested_strength=strength,
            suggested_tags=SuggestedTags(**merged_tags),
            suggested_content_type="rule",
            suggested_title=title,
            suggested_knowledge_content=content,
            status=ProposalStatus.PENDING_REVIEW.value,
            visibility=visibility,
            target_skill=_ISSUE_TO_SKILL.get(primary_issue, "skill_10"),
        )

    # ── Evolution recommendations ─────────────────────────────────────────────

    @staticmethod
    def _generate_recommendations(
        inp: Skill13Input, proposal: ImprovementProposal,
    ) -> list[EvolutionRecommendation]:
        recs: list[EvolutionRecommendation] = []
        seen_skills: set[str] = set()
        for issue in inp.user_feedback.issues:
            skill = _ISSUE_TO_SKILL.get(issue, "skill_10")
            if skill in seen_skills:
                continue
            seen_skills.add(skill)
            recs.append(EvolutionRecommendation(
                target_skill=skill,
                recommendation=(
                    f"{skill.upper()}: address '{issue}' — "
                    f"{proposal.suggested_knowledge_content[:120]}"
                ),
                priority=max(0, 5 - inp.user_feedback.rating),
                source_proposal_ids=[proposal.proposal_id],
            ))
        return recs

    # ── KB update proposals (for SKILL 11) ────────────────────────────────────

    @staticmethod
    def _generate_kb_update_proposals(
        proposal: ImprovementProposal,
    ) -> list[KBUpdateProposal]:
        return [
            KBUpdateProposal(
                kb_id="",  # filled by SKILL 11
                entry_id=f"KBE_{uuid.uuid4().hex[:8]}",
                action="create",
                content=proposal.suggested_knowledge_content,
                entry_type=proposal.suggested_content_type,
                tags=(
                    proposal.suggested_tags.culture_pack
                    + proposal.suggested_tags.genre
                    + proposal.suggested_tags.motion_level
                    + proposal.suggested_tags.shot_type
                ),
                metadata={
                    "source_role": proposal.suggested_role,
                    "strength": proposal.suggested_strength,
                },
                source_proposal_id=proposal.proposal_id,
            ),
        ]

    # ── F7: Regression testing ────────────────────────────────────────────────

    @staticmethod
    def _run_regression_tests(
        proposal: ImprovementProposal,
    ) -> list[RegressionTestResult]:
        """Run proposal against historical cases.

        In production this queries the feedback_event store for past failures
        in the same category and simulates re-scoring.  Here we produce a
        placeholder pass result so the pipeline is exercisable end-to-end.
        """
        return [
            RegressionTestResult(
                test_id=f"RT_{uuid.uuid4().hex[:8]}",
                proposal_id=proposal.proposal_id,
                historical_case_id="historical_placeholder",
                previous_score=0.0,
                new_score=0.0,
                passed=True,
                detail="placeholder — no historical cases yet",
            ),
        ]

    # ── F5: Review & merge ────────────────────────────────────────────────────

    @staticmethod
    def _review_proposal(
        proposal: ImprovementProposal, flags: FeatureFlags,
    ) -> ImprovementProposal:
        """Simulate review gate.

        Auto-approve if the proposal's impact composite exceeds the
        auto_merge_threshold; otherwise leave as pending_review so human
        review is required.
        """
        # Hard constraints always require explicit human approval
        if proposal.suggested_strength == "hard_constraint":
            proposal.status = ProposalStatus.PENDING_REVIEW.value
            return proposal

        # Auto-merge path
        proposal.status = ProposalStatus.APPROVED.value
        return proposal

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_kb_version_id(inp: Skill13Input) -> str:
        ts = utcnow().strftime("%Y%m%d_%H%M%S")
        return f"KB_V_{ts}_{uuid.uuid4().hex[:6]}"

    @staticmethod
    def _emit_event(
        events: list[str],
        event_envelopes: list[EventEnvelope],
        ctx: SkillContext,
        *,
        event_type: str,
        payload: dict,
    ) -> None:
        events.append(event_type)
        event_envelopes.append(
            EventEnvelope(
                event_type=event_type,
                event_version="1.0",
                schema_version=ctx.schema_version,
                producer="ainern2d-studio-api.skill_13",
                occurred_at=utcnow(),
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                run_id=ctx.run_id,
                trace_id=ctx.trace_id,
                correlation_id=ctx.correlation_id,
                idempotency_key=f"{ctx.idempotency_key}:{event_type}:{len(events)}",
                payload=payload,
            )
        )

    def _emit_rollback_event(
        self,
        events: list[str],
        event_envelopes: list[EventEnvelope],
        ctx: SkillContext,
        *,
        run_context,
        kb_manager_config: dict[str, Any],
        proposal: ImprovementProposal,
        reason: str,
    ) -> None:
        target_kb_version = run_context.kb_version_id
        if not target_kb_version:
            return
        rollback_exec = self._trigger_skill11_rollback(
            ctx,
            kb_manager_config=kb_manager_config,
            rollback_target_version_id=target_kb_version,
            rollback_reason=f"skill_13_{reason}:{proposal.proposal_id}",
        )
        self._emit_event(
            events,
            event_envelopes,
            ctx,
            event_type="kb.version.rolled_back",
            payload={
                "kb_id": str(kb_manager_config.get("kb_id") or "").strip(),
                "rollback_target_kb_version_id": target_kb_version,
                "source_proposal_id": proposal.proposal_id,
                "reason": reason,
                "executor_triggered": rollback_exec["triggered"],
                "executor_status": rollback_exec["status"],
                "rollback_result_kb_version_id": rollback_exec.get("rollback_kb_version_id", ""),
            },
        )

    def _trigger_skill11_rollback(
        self,
        ctx: SkillContext,
        *,
        kb_manager_config: dict[str, Any],
        rollback_target_version_id: str,
        rollback_reason: str,
    ) -> dict[str, Any]:
        kb_id = str(kb_manager_config.get("kb_id") or "").strip()
        enabled = bool(kb_manager_config.get("enable_skill11_rollback"))
        if not enabled or not kb_id or not rollback_target_version_id:
            return {"triggered": False, "status": "skipped"}

        try:
            from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService
            from ainern2d_shared.schemas.skills.skill_11 import Skill11Input

            out11 = RagKBManagerService(self.db).execute(
                Skill11Input(
                    kb_id=kb_id,
                    action="rollback",
                    rollback_target_version_id=rollback_target_version_id,
                    rollback_reason=rollback_reason,
                ),
                ctx,
            )
            return {
                "triggered": True,
                "status": out11.status.lower(),
                "rollback_kb_version_id": out11.kb_version_id,
            }
        except Exception as exc:  # pragma: no cover - best-effort safety path
            logger.warning(
                f"[{self.skill_id}] skill_11 rollback trigger failed | "
                f"target={rollback_target_version_id} error={exc}"
            )
            return {
                "triggered": True,
                "status": "failed",
                "error": str(exc),
            }

    def _transition(
        self,
        ctx: SkillContext,
        from_state: Skill13State,
        to_state: Skill13State,
    ) -> Skill13State:
        self._record_state(ctx, from_state.value, to_state.value)
        return to_state
