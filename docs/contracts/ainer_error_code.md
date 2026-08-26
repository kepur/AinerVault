# AINER 错误码规范（v1）

## 1. 规则
- 格式：`{DOMAIN}-{CATEGORY}-{NNN}`。
- 示例：`AUTH-VALIDATION-001`。
- 每个错误必须标注：`retryable`、`http_status`、`owner_module`。

## 2. 分类
- `AUTH`：登录、权限、租户隔离。
- `REQ`：请求校验、参数、幂等冲突。
- `ORCH`：编排状态机、DAG、超时。
- `PLAN`：规划失败（分镜、提示词、时间线）。
- `ROUTE`：模型路由和降级失败。
- `WORKER`：执行失败（视频/音频/LLM/lipsync）。
- `COMPOSE`：合成失败。
- `ASSET`：素材检索或产物写入失败。
- `RAG`：检索、向量、embedding 模型失败。
- `OBS`：观测链路异常。
- `SYS`：系统级不可用（依赖中断/资源不足）。

## 3. 建议错误码集（首批）
- `AUTH-VALIDATION-001`：登录参数非法。
- `AUTH-FORBIDDEN-002`：无项目权限。
- `REQ-IDEMPOTENCY-001`：幂等键冲突。
- `ORCH-STATE-001`：状态迁移非法。
- `ORCH-TIMEOUT-002`：步骤超时。
- `PLAN-GENERATE-001`：分镜生成失败。
- `ROUTE-NO_TARGET-001`：无可用路由目标。
- `WORKER-CLAIM-001`：任务认领失败。
- `WORKER-EXEC-002`：执行器运行失败。
- `COMPOSE-FFMPEG-001`：合成命令失败。
- `ASSET-UPLOAD-001`：产物上传失败。
- `RAG-EMBEDDING-001`：向量生成失败。
- `OBS-TRACE-001`：追踪写入失败。
- `SYS-DEPENDENCY-001`：依赖服务不可用。

## 4. 错误对象
```json
{
	"error_code": "WORKER-EXEC-002",
	"message": "video worker execution failed",
	"retryable": true,
	"owner_module": "ainern2d-worker-video",
	"trace_id": "tr_...",
	"correlation_id": "cr_...",
	"details": {}
}
```

## 5. 决策A执行要求
- 共享模型与服务私有表都必须落地 `error_code` 字段。
- 所有 `job.failed` / `run.failed` 事件必须带错误对象。
- `worker.*.completed` 若表示失败语义，必须同步产生 `job.failed`。
- `error.recorded` 必须可追溯到 `run_id + job_id + trace_id`。
