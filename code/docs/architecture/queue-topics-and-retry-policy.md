# Queue Topics and Retry Policy

## 1. Topic 权威映射

| Topic | Producer | Consumer | 事件类型 | 说明 |
|---|---|---|---|---|
| `task.submitted` | gateway | orchestrator | `task.submitted` | 任务入口 |
| `job.dispatch` | orchestrator | worker-hub | `job.created` | 下发执行作业 |
| `job.status` | worker-hub | orchestrator/observer | `job.claimed/job.succeeded/job.failed` | 执行状态主线 |
| `worker.detail` | worker-* | observer | `worker.*.completed` | 执行细节 |
| `compose.dispatch` | orchestrator | composer | `compose.started` | 合成入口 |
| `compose.status` | composer | gateway/observer | `compose.completed/compose.failed/artifact.published` | 合成发布 |
| `alert.events` | observer | ops/sre | `alert.triggered` | 告警链路 |

## 2. 重试策略
- `job.created` 消费失败：指数退避（1s, 5s, 30s, 2m），上限 5 次。
- `job.failed` 为可重试时：由 orchestrator 重新发布 `job.retry.scheduled`。
- 超过 `max_attempts`：入 DLQ，触发 `error.recorded`。

## 3. DLQ 策略
- DLQ key：`event_id`（幂等重放必须复用原 event_id）。
- 必带字段：`event_id,event_type,producer,trace_id,error_code,first_failed_at,last_failed_at,replay_count`。
- 重放规则：人工审批后执行，禁止自动无限重放。

## 4. 禁止项
- FORBID：绕过 topic 直连调用跨服务核心流程。
- FORBID：worker-detail topic 替代 job-status topic。
