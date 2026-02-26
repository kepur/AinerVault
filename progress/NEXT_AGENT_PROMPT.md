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

3) 本轮只做一个目标（二选一）：
A. 完成 SKILL_21 service 持久化写库（entity continuity 全链）
B. 完成 SKILL_22 service 持久化写库（persona dataset/index/lineage/manifest）

4) 执行边界：
- 允许修改：
  - code/shared/ainern2d_shared/schemas/skills/skill_21.py / skill_22.py
  - code/apps/ainern2d-studio-api/app/services/skills/skill_21_*.py / skill_22_*.py
  - 必要时：skill_registry.py / skill_dispatcher.py / tests/skills/test_skills_21_22.py
  - progress/skill_delivery_status.yaml（必须更新）
- 不允许大范围重构其他 skill。

5) 交付门禁：
- 通过目标相关 pytest
- 输出字段符合 ainer_contracts.md
- 错误码符合 ainer_error_code.md
- 更新 progress/skill_delivery_status.yaml 的 status/gate/next_action/evidence

6) 最终输出格式：
- 改动文件清单
- 输入->处理->输出链路说明
- 测试结果
- 未完成项与风险
```
