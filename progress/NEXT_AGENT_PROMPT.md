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

2.1) 开发前强制校验（MUST）：
- 先运行：
  python3 code/scripts/validate_skill_framework.py --strict --report progress/MODEL_CONFIRMATION_REPORT.md
- 若出现 FAIL，先修复 FAIL 再编码。
- 每次提交前再运行一次同命令，确保无新增漂移。

3) 本轮只做一个目标（二选一）：
A. 做 E2E：`04 -> 21 -> 07 -> 08 -> 10 -> 20`，验证 continuity anchors 在 prompt/DSL 中可追溯
B. 做 E2E：`11/12/14 -> 22 -> 15/17`，验证 runtime manifest 对策略与实验配置生效

4) 执行边界：
- 允许修改：
  - 目标 SKILL 对应的 DTO/Service/Test 文件与必要 API
  - 必要时：skill_registry.py / skill_dispatcher.py / orchestrator_dag.py
  - progress/skill_delivery_status.yaml（必须更新）
- 不允许大范围重构其他 skill。

5) 交付门禁：
- 通过目标相关 pytest
- 输出字段符合 ainer_contracts.md
- 错误码符合 ainer_error_code.md
- `validate_skill_framework.py --strict` 通过
- 更新 progress/skill_delivery_status.yaml 的 status/gate/next_action/evidence

6) 最终输出格式：
- 改动文件清单
- 输入->处理->输出链路说明
- 测试结果
- 未完成项与风险
```
