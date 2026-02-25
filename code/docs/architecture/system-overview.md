# System Overview（Decision A）

## 目标
- 面向新项目构建工业级多模态生成平台。
- 采用“共享模型 + 服务私有表并行”策略，先统一共享字段标准。

## 端到端闭环
1. 用户登录与鉴权（Gateway/Studio）。
2. 项目与内容输入（Novel/Chapter）。
3. 实体抽取与规范化（Entity Core）。
4. 分镜/提示词/时间线规划（Planner + Model Router）。
5. Worker 执行（Video/Audio/LLM/LipSync）。
6. 合成导出（Composer）。
7. 观测回流（Observer）。
8. 人工修订与重生成（Studio）。

## 核心原则
- 标准优先：`tenant_id/project_id/trace_id/idempotency_key/error_code/version` 必须统一。
- 契约驱动：服务通过 EventEnvelope + DTO 交互，不共享内部实现。
- 版本兼容：新增字段优先可选，破坏变更用 major 版本。

## 关键文档
- 根级契约：`ainer_contracts.md`
- 事件字典：`ainer_event_types.md`
- 错误码：`ainer_error_code.md`
- 模块边界：`module-boundaries.md`
- 事件契约映射：`event-contracts.md`
