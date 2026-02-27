# Next Agent Prompt（可直接复制）

```text
你是本仓库的继续实现 Agent。严格按下面流程执行，不要跨范围改动：

1) 先读取（按顺序）：
- START_HERE_FOR_AGENTS.md
- progress/README.md
- progress/skill_delivery_status.yaml
- README_21_22_INTEGRATION_GUIDE.md
- SKILL_01_STORY_INGESTION_NORMALIZATION.md ... SKILL_22_PERSONA_DATASET_INDEX_MANAGER.md
- ainer_contracts.md / ainer_event_types.md / ainer_error_code.md

2) 当前基线（必须继承）：
- SKILL_21/22 的 DTO + Service + Registry/Dispatcher + DAG 已接线
- 数据库增量迁移已新增：code/apps/alembic/versions/0f2b6c9b0c7f_align_skill_21_22_schema.py
- 迁移覆盖 jobtype 枚举补值 + 21/22 所需 8 张表
- 已有真实库验证脚本：code/scripts/validate_skill_21_22_persistence_realdb.py（已通过）
- SKILL_10 已接入：
  - SKILL_21 `continuity_exports`
  - SKILL_22 `runtime_manifests`（支持 `active_persona_ref`）
- SKILL_08 / SKILL_16 已接入 SKILL_21 continuity exports
- SKILL_15 / SKILL_17 已接入 SKILL_22 runtime manifests
- 新增服务级 E2E 用例：
  - code/apps/ainern2d-studio-api/tests/skills/test_e2e_handoff_21_22.py
  - 覆盖 E2E-021 / E2E-022 的服务链路消费验证
- SKILL_24 已新增：
  - `/api/v1/chapters/{chapter_id}/assist-expand`（优先 Provider LLM，失败回退模板扩写）
  - 前端章节工作区重构（小说先选中、章节后显示、Markdown 左编右预览、AI 扩写按钮）
- SKILL_25 已新增：
  - `/api/v1/config/telegram-settings/test`（后台测试发送）
  - `/api/v1/config/bootstrap-defaults`（LangGraph StateGraph 编排：模型/角色可选 + enrich rounds）
  - bootstrap graph 已改为 TypedDict StateGraph，修复跨节点状态丢失（`roles_upserted/skills_upserted/routes_upserted` 正常累积）
  - `/api/v1/config/ws/bootstrap/{session_id}`（bootstrap 实时进度 WS）
  - Telegram 通知已接入 `task.submitted` / `bootstrap.*` / `role.skill.run.*` / `plan.prompt.generated` / `rag.embedding.completed` / `job.created`（受 notify_events 过滤）
  - Provider / Model-Routing / Role-Config / Role-Workbench 已拆分为独立页面
- SKILL_26 / SKILL_30 已补：
  - `/api/v1/rag/import-jobs` 完成后发送 `rag.embedding.completed`
  - `/api/v1/runs/{run_id}/timeline/patch` 入队后发送 `job.created`
- SKILL_24 已补：
  - `/api/v1/chapters/{chapter_id}/assist-expand` 结束后发送 `plan.prompt.generated`
- 23~30 对话需求总规文档：
  - `SKILL_23_30_PRODUCT_REQUIREMENTS_MASTER.md`（接力必读）

2.1) 开发前强制校验（MUST）：
- 先运行统一开工门禁：
  python3 code/scripts/validate_preimplementation_readiness.py --strict
- 报告必须刷新到：
  progress/PREIMPLEMENTATION_READINESS_REPORT.md
- 先运行：
  python3 code/scripts/validate_skill_framework.py --strict --report progress/MODEL_CONFIRMATION_REPORT.md
- 若出现 FAIL，先修复 FAIL 再编码。
- 每次提交前再运行一次同命令，确保无新增漂移。

3) 本轮只做一个目标（任选一项）：
A. 做 SKILL_24：章节发布审批 + PR diff 可视化
B. 做 SKILL_25：provider 配额/限流/余额指标接入
C. 做 SKILL_25：run_skill 异步队列模式 + 成本计量
D. 做 SKILL_26：二进制 txt/pdf/xlsx 解析 + 导入异步队列

4) 执行边界：
- 允许修改：
  - 目标 SKILL 对应的 DTO/Service/Test 文件与必要 API/DAO
  - 必要时：skill_registry.py / skill_dispatcher.py / orchestrator_dag.py
  - progress/skill_delivery_status.yaml（必须更新）
- 不允许大范围重构其他 skill。

5) 交付门禁：
- 通过目标相关 pytest
- 输出字段符合 ainer_contracts.md
- 错误码符合 ainer_error_code.md
- `validate_skill_framework.py --strict` 通过
- `validate_preimplementation_readiness.py --strict` 通过
- 更新 progress/skill_delivery_status.yaml 的 status/gate/next_action/evidence

6) 最终输出格式：
- 改动文件清单
- 输入->处理->输出链路说明
- 测试结果
- 未完成项与风险
```
