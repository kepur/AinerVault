# Event Contracts（Decision A）

## 1. 统一要求
- 所有事件必须使用 `EventEnvelope`。
- 所有事件必须包含：`tenant_id/project_id/trace_id/correlation_id/idempotency_key/schema_version`。

## 2. 核心事件流（闭环）

### 2.1 提交到编排
- 事件：`task.submitted`
- Producer：Gateway
- Consumer：Orchestrator
- Payload 关键字段：`task_id/chapter_id/requested_quality/language_context`

### 2.2 编排到规划
- 事件：`run.created`, `run.stage.changed`
- Producer：Orchestrator
- Consumer：Planner, Observer
- Payload 关键字段：`run_id/stage/progress`

### 2.3 规划到路由
- 事件：`plan.shot.generated`, `plan.prompt.generated`
- Producer：Planner
- Consumer：Model Router
- Payload 关键字段：`plan_id/shots/prompt_refs`

### 2.4 路由到执行
- 事件：`route.decision.made`, `job.created`
- Producer：Model Router/Orchestrator
- Consumer：Worker Hub
- Payload 关键字段：`job_id/worker_type/model_profile_id/fallback_chain`

### 2.5 执行到合成
- 事件：`job.succeeded`, `job.failed`（执行明细可附带 `worker.*.completed`）
- Producer：Worker Hub/Worker-*
- Consumer：Orchestrator, Composer, Observer
- Payload 关键字段：`job_id/status/artifacts/error_code/retryable`

### 2.6 合成到发布
- 事件：`compose.completed`, `artifact.published`
- Producer：Composer
- Consumer：Gateway/Studio/Observer
- Payload 关键字段：`run_id/final_artifact_uri/duration_ms`

## 3. 幂等与重试
- `idempotency_key` 必须在 producer 端生成。
- consumer 必须支持去重处理。
- 失败重试不允许改变业务语义。

## 4. 版本策略
- 事件版本由 `event_version` 标识。
- 新增字段优先可选；破坏变更必须升级主版本并灰度双发。

## 5. 事件权威生产者表（P0）

| 事件 | 权威 Producer | 说明 |
|---|---|---|
| `task.submitted` | Gateway | 用户提交入口唯一生产者 |
| `run.created` | Orchestrator | 仅编排器可创建 run |
| `run.stage.changed` | Orchestrator | 状态机推进唯一来源 |
| `route.decision.made` | Model Router | 路由决策唯一来源 |
| `job.created` | Orchestrator | 作业创建唯一来源 |
| `job.claimed` | Worker Hub | 认领状态由 worker-hub 统一上报 |
| `job.succeeded` | Worker Hub | 成功回写统一上报 |
| `job.failed` | Worker Hub | 失败回写统一上报 |
| `worker.video.completed` | worker-video | 执行器结果事件 |
| `worker.audio.completed` | worker-audio | 执行器结果事件 |
| `worker.llm.completed` | worker-llm | 执行器结果事件 |
| `worker.lipsync.completed` | worker-lipsync | 执行器结果事件 |
| `compose.completed` | Composer | 合成完成唯一来源 |
| `artifact.published` | Composer | 最终产物发布来源 |
| `error.recorded` | Observer | 错误归集事件统一来源 |

规则：同一事件类型禁止双 Producer。跨模块转发必须保持原 `producer` 并标记 `forwarded_by`。

## 6. 死信与重放策略（P1）
- 死信入口：消费失败超过 `max_retries` 的事件进入 DLQ。
- DLQ 记录必须包含：`event_id`, `event_type`, `producer`, `trace_id`, `error_code`, `first_failed_at`, `last_failed_at`。
- 重放策略：
	1. 人工确认可重放（避免业务副作用）。
	2. 按 `event_id` 幂等重放，不得重新生成新事件ID。
	3. 重放后记录 `replay_count` 与 `replayed_by`。
- 阻断策略：同一 `event_type` 的 DLQ 积压超过阈值时触发发布冻结。
