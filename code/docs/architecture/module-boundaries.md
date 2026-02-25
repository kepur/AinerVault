# Module Boundaries（Decision A）

## 1. 数据所有权

### 1.1 共享模型（平台主数据）
- 内容主线：Novel/Chapter/Scene/Shot/Dialogue/AudioTimelineItem。
- 执行主线：ExecutionRequest/RenderRun/Job/Artifact。
- 知识主线：Entity/Relationship/Event/EntityState/RAG。

### 1.2 服务私有表（运行细节）
- Orchestrator：DAG 运行快照、补偿记录、调度窗口。
- Model Router：路由评分、节点健康缓存、策略命中。
- Worker Hub/Worker-*：claim 历史、执行日志、本地缓存。
- Composer：合成批次、中间片段清单、导出审计。
- Observer：聚合指标宽表、告警规则、成本账本。

## 2. 共享字段标准（必须一致）
- `tenant_id`
- `project_id`
- `trace_id`
- `correlation_id`
- `idempotency_key`
- `error_code`
- `version`
- `created_at`
- `updated_at`
- `deleted_at`

## 3. 模块职责边界
- Gateway：只做入口、鉴权、聚合，不做复杂编排。
- Orchestrator：状态机与流程推进，不做具体算法生成。
- Planner：计划产物生成，不直接执行重任务。
- Router：只做路由决策，不直接承载业务状态机。
- Worker Hub：分发与回写，不做产品逻辑决策。
- Worker-*：专注执行，结果通过 WorkerResult 回传。
- Composer：只负责合成链路与导出产物。
- Observer：只做观测聚合，不反向改业务状态。

## 4. 与 SKILL 的映射要求
- 每个 SKILL 至少映射一个共享对象（plan/entity/artifact/event）和一个服务私有处理节点。
- 无共享对象落库的 SKILL 不允许上线。
