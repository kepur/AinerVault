# Service API Contracts（可执行版）

## 1. 目标
- 给 AI agent 提供可直接编码的服务接口契约，避免跨服务字段/语义漂移。

## 2. 全局约束
- 所有写接口 MUST 接收：`tenant_id, project_id, trace_id, correlation_id, idempotency_key`。
- 所有错误响应 MUST 返回：`error_code, message, retryable, owner_module, trace_id`。
- 所有异步入口 MUST 返回 `202 + run_id|job_id`，不得阻塞等待 worker 完成。

## 3. Gateway（01）
### 3.1 POST /api/v1/tasks
- Request（最小）：
```json
{
  "tenant_id": "t_001",
  "project_id": "p_001",
  "trace_id": "tr_xxx",
  "correlation_id": "cr_xxx",
  "idempotency_key": "idem_xxx",
  "chapter_id": "ch_001",
  "requested_quality": "standard",
  "language_context": "zh-CN"
}
```
- Response：`202 {"run_id":"run_xxx","status":"queued"}`
- Side effects：发布 `task.submitted`。

### 3.2 GET /api/v1/runs/{run_id}
- Response：`run_status, stage, progress, latest_error, final_artifact_uri`。

## 4. Orchestrator（02）
### 4.1 POST /internal/orchestrator/events
- 输入：来自 worker-hub/composer 的事件回写。
- 行为：
  - 校验 Envelope 与幂等键；
  - 触发状态机迁移；
  - 写入 `workflow_events` 与 `run_stage_transitions`。

## 5. Worker Hub（07）
### 5.1 POST /internal/dispatch
- 输入：`job_id, worker_type, payload, timeout_ms, fallback_chain`。
- 输出：`202 {"job_id":"...","status":"enqueued"}`。
- 事件：`job.claimed`, `job.succeeded|job.failed`。

## 6. Composer（12）
### 6.1 POST /internal/compose
- 输入：`run_id, timeline_final, artifact_refs[]`。
- 输出：`compose_job_id`。
- 事件：`compose.started`, `compose.completed`, `artifact.published`。

## 7. Observer（13）
### 7.1 GET /internal/observer/runs/{run_id}/trace
- 输出：按时间排序的事件链（含 stage、producer、error_code）。

## 8. 禁止项
- FORBID：Gateway 直接修改 `render_runs/jobs` 终态。
- FORBID：Worker 直接发布 `run.*` 事件。
- FORBID：Composer 直接发布 `job.*` 事件。
