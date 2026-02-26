# SKILL Agent Playbook（专供 AI 接力）

## 1. 是否需要“转译给 Agent 的 playbook”
- 需要。
- 原因：根目录需求文档是“业务目标层”，Agent 落地还需要“执行顺序 + 文件边界 + 门禁清单 + 输出模板”。
- 本文件就是该转译层，配合 `progress/skill_delivery_status.yaml` 使用。

## 2. Agent 启动阅读顺序（固定）
1. `START_HERE_FOR_AGENTS.md`
2. `progress/README.md`
3. `progress/skill_delivery_status.yaml`
4. `README_21_22_INTEGRATION_GUIDE.md`
5. `ainer_contracts.md`
6. `ainer_event_types.md`
7. `ainer_error_code.md`
8. `code/docs/runbooks/implementation-status-ledger.md`
9. `code/docs/runbooks/e2e-handoff-test-matrix.md`

## 3. 接力执行协议（每次只做一个 skill）
1. 在 `skill_delivery_status.yaml` 里锁定一个 `gate != PASS` 的 SKILL。
2. 仅修改该 SKILL 允许的文件边界：
   - DTO: `code/shared/ainern2d_shared/schemas/skills/skill_XX.py`
   - Service: `code/apps/*/app/services/skills/skill_XX_*.py`
   - 调度: `skill_registry.py` 或 `skill_dispatcher.py`
   - 必要时补测试：`code/apps/*/tests/skills/test_skills_XX*.py`
3. 严格按链路接线，不改非目标 skill 行为。
4. 提交前执行最小门禁：
   - 单测/集成测至少覆盖新增分支
   - 事件字段符合 `ainer_contracts.md`
   - 错误码域符合 `ainer_error_code.md`
5. 更新 `skill_delivery_status.yaml` 当前 skill 的 `status/gate/next_action`。

## 4. 交付模板（Agent 输出必须包含）
- 改动文件列表（精确到路径）
- 本次实现了哪些链路（输入 -> 处理 -> 输出）
- 未完成项（阻塞原因）
- 回滚风险点

## 5. 建议给其他 AI 的调用提示词（可直接复制）
```text
你是本仓库的实现 Agent。先按以下顺序读取：
1) START_HERE_FOR_AGENTS.md
2) progress/skill_delivery_status.yaml
3) README_21_22_INTEGRATION_GUIDE.md
4) ainer_contracts.md / ainer_event_types.md / ainer_error_code.md
5) code/docs/runbooks/e2e-handoff-test-matrix.md

然后只实现我指定的一个 SKILL（不要跨 skill 扩散）：
- 先报告该 SKILL 当前 status/gate 与阻塞项；
- 按 DTO -> Service -> 调度注册 -> 测试 的顺序修改；
- 产出必须满足 run/job/stage/event/artifact 主术语；
- 失败分支必须返回规范 error_code；
- 完成后更新 progress/skill_delivery_status.yaml 对应条目；
- 最后给出：改动文件、测试结果、剩余风险。
```
