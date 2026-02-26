# Phase 2 RabbitMQ E2E 实流交接报告（2026-02-26）

## 1. 目标
验证 Phase 2 下一段要求：
- 使用本地真实 RabbitMQ broker。
- 完成 topic 链路实流：`task.submitted -> job.dispatch -> job.status -> compose.status`。
- 给出可复现证据与交接说明。

## 2. 环境与启动信息
- Workspace: `/Users/mac/AinerWorkFlow/AinerHub_IDEA`
- Python: `.venv/bin/python` (3.12)
- RabbitMQ: Docker 单容器 `rabbitmq:3-management`
  - 容器名：`ainer-rabbitmq`
  - AMQP: `localhost:5672`
  - 管理台: `http://localhost:15672`（默认 guest/guest）

### 2.1 Broker 启动命令
```bash
docker run -d --name ainer-rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
```

### 2.2 服务启动命令（本次实测）
```bash
PYTHONPATH=code/shared:code/apps/ainern2d-studio-api .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18080
PYTHONPATH=code/shared:code/apps/ainern2d-worker-hub .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18081
PYTHONPATH=code/shared:code/apps/ainern2d-composer .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18082
```

## 3. E2E 触发请求
```http
POST http://127.0.0.1:18080/api/v1/tasks
Content-Type: application/json

{
  "tenant_id": "t_001",
  "project_id": "p_001",
  "trace_id": "tr_e2e_001",
  "correlation_id": "cr_e2e_001",
  "idempotency_key": "idem_e2e_001",
  "chapter_id": "ch_001",
  "requested_quality": "standard",
  "language_context": "zh-CN",
  "payload": {"source": "e2e_test"}
}
```

返回：
```json
{"run_id":"run_aef22f3cfba344b7b09f310c0693732d","status":"queued","message":"accepted"}
```

## 4. 结果证据

### 4.1 运行态结果
`GET /api/v1/runs/run_aef22f3cfba344b7b09f310c0693732d` 返回：
```json
{
  "run_id": "run_aef22f3cfba344b7b09f310c0693732d",
  "status": "succeeded",
  "stage": "completed",
  "progress": 100.0,
  "latest_error": null,
  "final_artifact_uri": "s3://ainer-artifacts/run_aef22f3cfba344b7b09f310c0693732d/final.mp4",
  "schema_version": "1.0"
}
```

### 4.2 事件链证据
`GET /internal/observer/runs/{run_id}/trace` 解析结果（7 events）：
1. `task.submitted` (`gateway`)
2. `task.submitted` (`gateway`)
3. `job.created` (`orchestrator`)
4. `job.claimed` (`worker-hub`)
5. `job.succeeded` (`worker-hub`)
6. `compose.started` (`orchestrator`)
7. `compose.completed` (`composer`)

说明：链路关键 topic 全部命中，最终到达 `compose.status` 并回写 run 终态。

## 5. 交接结论
- **结论**：本地真实 RabbitMQ 下，Phase 2 指定 topic 链路已打通并完成一次成功实流。
- **可交接状态**：可交接给后续 AI/工程师继续补完集成测试与治理门禁。

## 6. 已知差异与后续建议
1. trace 中 `task.submitted` 出现重复（同步写入 + 消费再写入），建议后续按 `event_id` 去重。
2. 当前 E2E 以 in-memory store 为主，重启后状态不保留；后续应接入 DB 持久化。
3. 可补充自动化集成测试：
   - 提交 task 后断言 topic 顺序与终态；
   - 校验失败场景 `job.failed -> compose.failed` 的错误码覆盖。

## 7. 关联提交
- RabbitMQ 链路实现提交：`16ce328`
- 前置服务骨架提交：`d81c93f`
