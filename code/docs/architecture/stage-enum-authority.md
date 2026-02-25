# Stage Enum Authority（唯一权威）

## 1. 目的
- 提供全系统唯一 `run.stage` 枚举与迁移规则，杜绝不同服务各自定义 stage。

## 2. 权威枚举（MUST）
`ingest -> entity -> knowledge -> plan -> route -> execute -> audio -> video -> lipsync -> compose -> observe`

## 3. 迁移规则
- 仅 `orchestrator` 可发布 `run.stage.changed`。
- 仅允许前向迁移；回退必须通过 `run_patch_records + compensation_records` 记录。
- 非法迁移（如 `ingest -> compose`）必须拒绝并返回 `ORCH-STATE-001`。

## 4. 阶段门禁（摘要）
- `ingest -> entity`：输入校验通过，execution_request 已创建。
- `entity -> knowledge`：EntityPack 完整并有 canonicalization 结果。
- `knowledge -> plan`：候选资产可用率达到阈值。
- `plan -> route`：PromptPlan/TimelineSegment 生成完成。
- `route -> execute`：RouteDecision 可用且 fallback_chain 非空。
- `execute -> compose`：关键 job 全部 `job.succeeded` 或标记降级可继续。
- `compose -> observe`：`artifact.published` 成功。

## 5. 代码映射
- 枚举实现：`code/shared/ainern2d_shared/ainer_db_models/enum_models.py::RenderStage`
- 状态落库：`render_runs.stage`, `run_stage_transitions`。
