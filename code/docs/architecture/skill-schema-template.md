# Skill Schema Template（机器可读约束）

## 1. 必填章节（MUST）
1) `Workflow Goal`
2) `术语对齐声明（固定模板）`
3) `输入（Input Contract）`
4) `输出（Output Contract）`
5) `状态机/阶段映射（run.stage）`
6) `失败与回滚策略`
7) `事件映射`
8) `DoD/验收门禁`

## 2. 字段规范
- 输入必须声明：`tenant_id, project_id, trace_id, correlation_id, idempotency_key`。
- 输出必须声明：主状态事件（`job.succeeded/job.failed`）与明细事件。

## 3. 禁止项
- 不得定义与 `stage-enum-authority.md` 冲突的 stage。
- 不得将 `worker.*.completed` 当作主状态完成判定。

## 4. 示例骨架
```markdown
## 1. Workflow Goal
## 术语对齐声明（固定模板）
## 2. 输入（Input Contract）
## 3. 输出（Output Contract）
## 4. 状态机/阶段映射
## 5. 失败与回滚策略
## 6. 事件映射
## 7. DoD/验收门禁
```
