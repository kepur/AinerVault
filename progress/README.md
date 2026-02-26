# Progress Workspace（Agent 接力总入口）

## 1. 目的
- 为多 AI Agent 并行/接力开发提供单一进度入口。
- 让 Agent 先读状态，再编码，避免重复劳动和边界漂移。

## 2. 文件说明
- `progress/skill_delivery_status.yaml`
  - 22 个 SKILL 的机器可读状态矩阵（文档/DTO/Service/调度绑定/下一步）。
- `progress/SKILL_AGENT_PLAYBOOK.md`
  - Agent 专用落地手册（阅读顺序、执行门禁、交付模板、提示词模板）。
- `progress/NEXT_AGENT_PROMPT.md`
  - 可直接复制给其他 Agent 的接力提示词（含当前基线与边界）。
- `progress/DOC_CLEANUP_BASELINE.md`
  - 文档保留与清理基线（哪些必须保留，哪些可归档/候选删除）。

## 3. 更新规则（必须）
- 任意 SKILL 状态变化时，先更新 `skill_delivery_status.yaml`，再更新业务代码。
- 合并前必须补“证据路径”（代码文件、测试文件、运行日志/报告）。
- 若 `START_HERE_FOR_AGENTS.md` 阅读顺序变化，需同步更新本目录文档。

## 4. 当前结论（快照）
- `SKILL_01~20`：代码文件与调度入口基本存在，但统一门禁状态仍为 `REVIEW_REQUIRED`。
- `SKILL_21~22`：DTO/Service/调度/DAG 已落地，当前处于 `INTEGRATION_READY`，待 E2E。
- 数据库：已新增 21/22 对齐迁移 `0f2b6c9b0c7f_align_skill_21_22_schema.py`，待在可用 PostgreSQL 环境执行 `alembic upgrade head`。
