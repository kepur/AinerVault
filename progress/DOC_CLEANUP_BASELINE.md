# 文档清理基线（先治理，再删除）

## 1. 结论
- 不建议直接清空 `code/docs`。
- 正确做法：保留权威文档，过时文档先归档，再做引用清理后删除。

## 2. 必须保留（MUST KEEP）
- 根目录权威：
  - `00.架构.md`
  - `START_HERE_FOR_AGENTS.md`
  - `README_21_22_INTEGRATION_GUIDE.md`
  - `SKILL_01_*.md` ... `SKILL_22_*.md`
  - `ainer_contracts.md`
  - `ainer_event_types.md`
  - `ainer_error_code.md`
- `code/docs/architecture`（契约与边界类）
  - `service-api-contracts.md`
  - `stage-enum-authority.md`
  - `queue-topics-and-retry-policy.md`
  - `agent-data-model-guideline.md`
  - `ideal-db-model-blueprint.md`
- `code/docs/runbooks`（落地执行类）
  - `implementation-status-ledger.md`
  - `e2e-handoff-test-matrix.md`
  - `ci-gate-execution-spec.md`
  - `agent-implementation-playbook.md`

## 3. 可归档后再删（REVIEW FIRST）
- 阶段性审计报告、一次性 handoff 报告、过期迁移计划草稿。
- 原则：先移动到 `code/docs/_archive/`，跑一次全仓引用扫描，确认无引用再删除。

## 4. 物理删除流程（推荐）
1. 标记候选文件到 `code/docs/_archive/index.md`。
2. 执行全仓引用扫描：`rg -n "<文件名或关键词>"`.
3. 若无引用，执行物理删除；若有引用，先改引用后再删。
4. 删除后再跑一次扫描，确保无悬挂引用。

## 5. 当前建议
- 先不删 `code/docs` 主干文档。
- 优先把“接力入口”收敛到 `progress/` + `START_HERE_FOR_AGENTS.md`，再逐批归档历史文档。
