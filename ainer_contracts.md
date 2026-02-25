# AINER 通信契约（v1）

## 1. 目标与范围
- 用一套跨服务 DTO 保证 01-14 模块解耦协作。
- 约束：共享字段标准先落地，服务私有表可扩展但不得破坏契约。

## 1.1 统一术语（权威）
- `run`：一次端到端业务运行实例（由 orchestrator 创建与推进）。
- `job`：run 内可调度的原子执行单元（由 orchestrator 创建，worker-hub 回写状态）。
- `stage`：run 的阶段状态（如 ingest/plan/route/execute/compose/observe）。
- `event`：跨模块传递的事实消息，统一使用 `EventEnvelope`。
- `artifact`：可回溯产物元数据对象（视频/音频/中间件导出文件）。
- `step`：仅允许表示“内部算法步骤或降级动作序号”，不得作为主运行对象命名。

## 2. 统一 Envelope

### 2.1 EventEnvelope
```json
{
	"event_id": "evt_...",
	"event_type": "run.stage.changed",
	"event_version": "1.0",
	"occurred_at": "2026-02-26T12:00:00Z",
	"producer": "ainern2d-orchestrator",
	"tenant_id": "t_...",
	"project_id": "p_...",
	"run_id": "run_...",
	"job_id": "job_...",
	"trace_id": "tr_...",
	"correlation_id": "cr_...",
	"idempotency_key": "idem_...",
	"payload": {}
}
```

### 2.2 公共字段（所有契约都应包含）
- `tenant_id`：租户隔离主键。
- `project_id`：项目隔离主键（可映射 novel/project）。
- `trace_id`：跨模块追踪。
- `correlation_id`：同一业务请求关联键。
- `idempotency_key`：去重键。
- `schema_version`：对象结构版本。

## 3. 核心 DTO

### 3.1 TaskSpec（网关/编排入口）
- 用途：描述一次生成请求。
- 必填：`task_id`, `tenant_id`, `project_id`, `chapter_id`, `requested_quality`, `language_context`, `input_uri`。
- 可选：`budget_profile`, `deadline_ms`, `priority`, `user_overrides`。

### 3.2 DispatchDecision（模型路由）
- 必填：`task_id`, `route_id`, `worker_type`, `model_profile_id`, `fallback_chain`, `timeout_ms`。
- 建议：`cost_estimate`, `gpu_tier`, `degrade_policy`。

### 3.3 EntityPack（实体核心）
- 必填：`chapter_id`, `entities[]`, `relationships[]`, `events[]`, `extraction_version`。
- `entities[]` 建议字段：`entity_id`, `type`, `label`, `canonical_label`, `aliases[]`, `culture_tags[]`。

### 3.4 AssetCandidate（素材知识）
- 必填：`asset_id`, `asset_type`, `score`, `source`, `license_scope`, `uri`。
- 可选：`embedding_model`, `match_reason`, `safety_flags[]`。

### 3.5 ShotPlan（分镜规划）
- 必填：`plan_id`, `chapter_id`, `shots[]`, `plan_version`。
- `shots[]` 建议字段：`shot_id`, `shot_no`, `duration_ms`, `camera`, `scene_id`, `entities[]`, `prompt_refs[]`。

### 3.6 TimelinePlan（音频/视觉时序）
- 必填：`timeline_id`, `chapter_id`, `segments[]`, `timeline_version`。
- `segments[]` 建议字段：`segment_id`, `start_ms`, `end_ms`, `track`, `artifact_refs[]`。

### 3.7 ArtifactMeta（产物元数据）
- 必填：`artifact_id`, `artifact_type`, `uri`, `checksum`, `size_bytes`, `created_at`。
- 可选：`shot_id`, `run_id`, `codec`, `duration_ms`, `width`, `height`, `frame_rate`。

### 3.8 WorkerResult（执行结果）
- 必填：`job_id`, `status`, `attempt`, `started_at`, `finished_at`, `artifacts[]`。
- 失败时必填：`error_code`, `error_message`, `retryable`。

## 4. 版本与兼容
- 契约采用语义版本：`major.minor`。
- 规则：
	- `minor` 仅新增可选字段。
	- `major` 允许删除/改语义，必须提供迁移窗口。
- 所有事件与 DTO 必须携带 `schema_version`。

## 5. 决策A执行要求
- 先落共享字段标准，再做服务私有表映射。
- 服务私有表允许冗余，但以下字段命名必须一致：
	- `tenant_id`, `project_id`, `trace_id`, `correlation_id`, `idempotency_key`, `error_code`, `created_at`, `updated_at`, `deleted_at`, `version`。

## 5.1 事件层级约束（必须）
- 运行态主线事件采用：`run.*` + `job.*`。
- `worker.*.completed` 属于执行器明细事件，可保留但不得替代 `job.succeeded/job.failed`。
- 阶段推进统一通过 `run.stage.changed` 表达，不新增 `step.*` 运行态事件。

## 6. 契约强制级别（P0）

### 6.1 字段级别矩阵

| 字段 | 级别 | 说明 |
|---|---|---|
| `tenant_id` | MUST | 多租户隔离必需 |
| `project_id` | MUST | 项目隔离必需 |
| `trace_id` | MUST | 链路追踪必需 |
| `correlation_id` | MUST | 业务关联必需 |
| `idempotency_key` | MUST | 幂等去重必需 |
| `schema_version` | MUST | 契约版本必需 |
| `event_version` | MUST（事件） | 事件版本必需 |
| `error_code` | MUST（失败时） | 失败归因必需 |
| `retryable` | MUST（失败时） | 重试策略必需 |
| `occurred_at` | MUST（事件） | 事件时间必需 |
| `producer` | MUST（事件） | 权威来源必需 |

### 6.2 SHOULD 字段
- `kb_version_id`：涉及 RAG 注入时建议必须。
- `recipe_id`：涉及多角色检索配方时建议必须。
- `budget_profile`：涉及成本控制时建议携带。

### 6.3 OPTIONAL 字段
- `user_overrides`
- `degrade_policy`
- `quality_notes`

## 7. 契约门禁规则（CI）
- 每次 PR 必须执行契约校验：
	1. MUST 字段完整性校验（缺失即失败）。
	2. `schema_version/event_version` 变更一致性校验。
	3. 失败事件必须包含 `error_code + retryable`。
	4. 运行态事件必须使用 `run.*` / `job.*`，禁止新增 `step.*`。
	5. 新事件类型必须在 `ainer_event_types.md` 注册。
- 发布门禁：任一 Blocker 契约用例失败，禁止发布。
