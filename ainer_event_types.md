# AINER 事件类型（v1）

## 命名规范
- 格式：`domain.subject.action`（例：`run.stage.changed`）。
- 必须通过 `EventEnvelope` 发送（见 `ainer_contracts.md`）。
- 运行态主线仅使用：`run.*`、`job.*`。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded`。

## 1. 网关与鉴权（01/14）
- `auth.login.succeeded`
- `auth.login.failed`
- `project.created`
- `task.submitted`
- `task.cancel.requested`

## 2. 编排与状态机（02）
- `run.created`
- `run.stage.changed`
- `run.progress.updated`
- `run.succeeded`
- `run.failed`
- `run.canceled`
- `job.enqueued`
- `job.retry.scheduled`

## 3. 实体与知识（03/04）
- `entity.extraction.started`
- `entity.extraction.completed`
- `entity.canonicalized`
- `asset.candidate.generated`
- `asset.match.completed`

## 4. 规划链路（05/06）
- `plan.shot.generated`
- `plan.prompt.generated`
- `timeline.provisional.generated`
- `route.decision.made`
- `route.degraded`

## 5. 执行链路（07-11）
- `job.created`
- `job.claimed`
- `job.heartbeat`
- `job.succeeded`
- `job.failed`
- `worker.video.completed`
- `worker.audio.completed`
- `worker.llm.completed`
- `worker.lipsync.completed`

说明：`worker.*.completed` 为细粒度执行报告，状态机判定以 `job.succeeded/job.failed` 为准。

## 6. 合成与发布（12/14）
- `compose.started`
- `compose.completed`
- `compose.failed`
- `artifact.published`

## 7. 观测与治理（13）
- `audit.recorded`
- `error.recorded`
- `cost.updated`
- `slo.breached`
- `alert.triggered`

## 8. 与 SKILL 的对应（摘要）
- SKILL_01-02：`task.submitted` → `entity.extraction.*` / `route.decision.made`
- SKILL_03-04-07：`plan.shot.generated` / `entity.canonicalized`
- SKILL_05-06：`timeline.provisional.generated` / `job.succeeded`（audio 细节可见 `worker.audio.completed`）
- SKILL_08-09-10：`asset.match.completed` / `plan.prompt.generated` / `job.succeeded`（video 细节可见 `worker.video.completed`）

## 9. 兼容策略
- 事件新增仅允许新增类型或新增 payload 可选字段。
- 事件弃用需经历：`announce` → `dual-publish` → `remove` 三阶段。

## 10. RAG 进化事件（SKILL_11~13）
- `kb.item.created`
- `kb.item.updated`
- `kb.version.release.requested`
- `kb.version.released`
- `kb.version.rolled_back`
- `rag.chunking.started`
- `rag.embedding.completed`
- `rag.index.ready`
- `rag.eval.completed`
- `feedback.event.created`
- `proposal.created`
- `proposal.reviewed`
- `proposal.approved`
- `proposal.rejected`
- `kb.rollout.promoted`

## 11. 工业增强层事件（SKILL_14~22）
- `persona.resolved`
- `persona.version.published`
- `policy.stack.built`
- `shot.compute_budget.generated`
- `shot.dsl.compiled`
- `critic.evaluation.completed`
- `recovery.degradation.applied`
- `experiment.run.completed`
- `experiment.recommendation.generated`
- `entity.registry.resolved`
- `entity.continuity.locked`
- `preview.variant.generated`
- `preview.variant.approved`
- `voice.binding.updated`
- `persona.dataset.bound`
- `persona.index.bound`
- `persona.lineage.updated`
- `persona.runtime.manifested`

## 12. 废弃事件（兼容窗口）
- `step.enqueued`（deprecated -> `job.enqueued`）
- `step.retry.scheduled`（deprecated -> `job.retry.scheduled`）
