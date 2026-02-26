# FOUNDATION_FRAMEWORK（基础落地框架）

## 1. 目标
- 用统一框架让多 AI Agent 按同一边界实现 SKILL_01~22。
- 先做模型确认，再做编码，实现可接力、不跑偏。

## 2. 强制流程（每一轮都一样）
1. `模型确认`：先执行 `python3 code/scripts/validate_skill_framework.py --strict --report progress/MODEL_CONFIRMATION_REPORT.md`
2. `锁定范围`：本轮只选 1 个 SKILL（或 1 个闭环目标）
3. `按顺序实现`：DTO -> Service -> 调度映射 -> DAG/依赖 -> 测试
4. `验证`：跑目标 pytest + 再跑一次 `validate_skill_framework.py --strict`
5. `进度回写`：更新 `progress/skill_delivery_status.yaml`

## 3. 不跑偏边界
- 规格权威：根目录 `SKILL_01...SKILL_22`。
- 接入权威：`README_21_22_INTEGRATION_GUIDE.md`。
- 进度权威：`progress/skill_delivery_status.yaml`。
- 严禁跨 SKILL 大范围重构；如必须跨文件，只能为“接口对齐”最小变更。

## 4. 文件边界模板
- DTO：`code/shared/ainern2d_shared/schemas/skills/skill_XX.py`
- Service：
  - `01~05,07~19,21~22` -> `code/apps/ainern2d-studio-api/app/services/skills/skill_XX_*.py`
  - `06,20` -> `code/apps/ainern2d-composer/app/services/skills/skill_XX_*.py`
- 调度：`skill_registry.py` / `skill_dispatcher.py` / `dag_engine.py`
- 进度：`progress/skill_delivery_status.yaml`

## 5. 当前基础框架结论（2026-02-27）
- 结构层已对齐：SKILL_01~22 的 spec/DTO/service/调度/DAG 锚点齐全。
- DB 结构层已补齐：21/22 新表 + jobtype 枚举迁移已存在。
- 待闭环：
  - 在可用 PostgreSQL 执行 `alembic upgrade head`
  - SKILL_21/22 service 持久化写库

## 6. 接力交付最小模板
- 改动文件：
- 输入 -> 处理 -> 输出：
- 测试命令与结果：
- `validate_skill_framework.py --strict` 结果：
- 回写的 progress 条目：
- 剩余风险：
