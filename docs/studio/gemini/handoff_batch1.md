# Gemini 第一批交接报告 (Batch 1 QA Handoff)

**日期**：2026-10-09  
**提交方**：Gemini (独立测试与质量审计)  
**接收方**：Codex (后端与集成负责人)、Claude (制作界面负责人)  
**契约基准**：`ainer.production/v0.1`  
**报告规范**：依据 `docs/studio/planA_agents.md` §6  

---

## 1. 基线与本方提交

| 审查项 | 当前状态 | 详细说明 |
|---|---|---|
| **BASE_READY** | **已确认就绪** | 后端 R0/R1 源码已具备，全部 8 个端点通过自动化测试 |
| **API_READY (Batch 1)** | **建议发布** | Codex 交付的 R0/R1 接口通过 Gemini 独立自动化测试验证 |
| **UI_READY (Batch 1)** | **未发布** | Claude 第一批仅交付设计文档，前端代码尚未写入 |
| **QA_PASS (Batch 1 契约层)** | **正式发布** | 契约、路由、别名、并发锁、上下文、残缺检测全部通过 |
| **QA_PASS (成片质量层)** | **未通过 (FAILED)** | 滑雪视频存在单镜头过长、缺少分镜机位、无尾帧接力、无声音等问题 |
| **本方代码修改边界** | **严格遵守** | **仅修改测试、测试工具与报告，0 修改业务实现** |
| **数据库隔离性** | **100% 隔离** | 使用 `IsolatedMockSession`，**零写入生产 PostgreSQL 数据库** |
| **GPU 与算力消耗** | **0 消耗** | 未向生产模型或本地 GPU 派发重型生成任务 |

---

## 2. 本方改动与新增路径清单

本方所有工作严格限制在 `planA_agents.md` 规定的 Gemini 写区内：

| 类型 | 文件路径 | 用途说明 |
|---|---|---|
| **规范文档** | `docs/studio/gemini/acceptance_matrix.md` | 全阶段验收矩阵 (R0~R5，三层梯队，详细判定标准) |
| **规范文档** | `docs/studio/gemini/min_test_data.md` | 最小测试数据规范说明书 (3角色、2道具、2地点、分镜时间线) |
| **审计报告** | `docs/studio/gemini/baseline_audit_batch1.md` | 第一批基线独立审计报告 (Codex/Claude 复核与缺陷分析) |
| **交接报告** | `docs/studio/gemini/handoff_batch1.md` | 本交接文件 |
| **测试夹具** | `scripts/planA_qa/min_test_fixtures.py` | 纯内存隔离测试夹具与模拟 Session 生成器 |
| **测试套件** | `code/apps/ainer-core/tests/test_planA_contracts_batch1.py` | 涵盖 R0/R1 8 大路由、12 个深度场景的自动化测试套件 |
| **执行脚本** | `scripts/planA_qa/run_batch1_qa.py` | 一键自动化 QA 验证执行器，输出测试摘要 JSON |
| **测试记录** | `docs/studio/test_runs/batch1_latest.json` | 自动化测试执行记录与结果归档 |
| **测试修正** | `code/apps/ainer-core/tests/test_stage_p0.py` | 同步测试断言至当前契约 (`source='inferred'`) |
| **测试修正** | `code/apps/ainer-core/tests/test_char_sheet.py` | 消除后台线程并发竞态条件，保证测试确定性 |

---

## 3. 完成项 (对照 planA_agents.md §4 Gemini 第一批)

1. **阅读并对齐所有契约与规则**：深入通读 `planA.md`、`planA_agents.md`、`planA_contracts.md`、`docs/studio/codex/handoff_batch1.md` 与 `docs/studio/claude/handoff_batch1.md`。
2. **准备验收矩阵 (Acceptance Matrix)**：输出 `docs/studio/gemini/acceptance_matrix.md`，覆盖接口、画布、角色、站位、运镜、时间、依赖失效与媒体质量，建立 `[模拟测试]`、`[真实路径]` 与 `[质量通过]` 三层标准。
3. **准备最小测试数据 (Minimum Test Dataset)**：输出 `min_test_fixtures.py` 与 `min_test_data.md`，提供 3 个角色、2 个道具、2 个地点、完整 NarrativeIR 序列与 4 种画布。
4. **对 Codex 交付的 R0/R1 后端实施独立验证**：
   - 验证生产路由 100% 注册，OpenAPI 规范有效。
   - 验证上下文获取与乐观锁并发控制 (409)。
   - 验证资源解析严格等长对齐与逐项隔离。
   - 验证 16 格定妆照规范、CR-05 表情别名与 CR-06 遗留映射。
   - 验证增量绑定、行锁保护与素材防冒充 (422)。
   - 验证 CR-01 无计划素材卡拉取。
   - 验证缺项规划与 usages 扫描范围显式声明。
5. **对既有单元测试完成回归**：修复存量测试与契约之间的历史差异，全套 89 个关联测试实现 **100% 通过**。
6. **对用户反馈问题 (#1 ~ #8) 完成质量审计**：确立「任务成功 $\neq$ 成片合格」红线，剖析 3D 白模不可用与滑雪视频单镜头过长的技术根因。

---

## 4. 未完成项与缺口

1. **Claude UI 前端交互未跑通**：由于 Claude 第一批未提交 `src/` 代码，画布前端联动、资产抽屉、16格定妆照展示目前处于**未实现**状态，无法进行端到端浏览器录屏与 UI 截图验收。
2. **3D 导演台编辑器打不开 (用户反馈 #1, #2)**：属于 Claude 前端视图代码缺口，等待修复。
3. **多镜头分镜与尾帧接力 (用户反馈 #4, #5)**：需要 Codex 在 R3 阶段落地无限分镜接力与本地 MLX 管线调度。
4. **LTX 2.5 音频管线集成 (用户反馈 #7)**：尚未接入。

---

## 5. 接口与契约版本

- **当前生效**：`ainer.production/v0.1`。
- **状态裁定**：所有 8 条 CR 请求已完成后端落地或权威适配，无需升级 v0.2，Claude 可完全基于当前契约进行 UI 编码。

---

## 6. 验证与复现执行方式

任何团队成员均可在根目录下执行以下命令重现 Gemini 的所有验证结果：

```bash
# 执行自动化 QA 套件 (用时约 2.6 秒，纯内存运行，无副作用)
.venv/bin/python scripts/planA_qa/run_batch1_qa.py

# 单独执行 Plan A 契约测试
.venv/bin/pytest code/apps/ainer-core/tests/test_planA_contracts_batch1.py -v
```

---

## 7. 给 Codex 的工作请求与建议

1. **建议发布 API_READY (Batch 1)**：后端代码经过全量契约测试，逻辑健全，无阻碍性 Bug，可正式向 Claude 宣布 API_READY。
2. **着手 R3 影视生成管线重构 (响应用户反馈 #3, #4, #5, #7)**：
   - **镜头拆解**：针对滑雪场景，禁止 15s 单镜头生成；在分镜计划中默认拆解为 2-3 个覆盖镜头（例如：远景下滑 $\to$ 面部特写 $\to$ 冲出旗门跟踪镜）。
   - **尾帧接力机制**：第二镜头必须基于第一镜头的尾帧或高相似度定妆照作为条件输入，实现无限分镜连续性。
   - **本地 MLX / LTX 2.5 集成**：排查并打通本地 `ml-stable-diffusion` 与 LTX 2.5 音视频一体化生成。

---

## 8. 给 Claude 的工作请求与建议

1. **开始第一批 UI 编码**：Codex 后端已完备，8 项 CR 已裁定，请依据 `batch1_design.md` 在 `code/apps/ainer-studio/src/` 中开展编码。
2. **优先修复 3D 白模编辑打不开的问题 (用户反馈 #1, #2)**：
   - 检查 `http://localhost:5174/studio?view=box` 的加载逻辑，兼容最新 `SceneStage` 数据结构。
   - 保证白模能够加载并响应姿态与相机控制。
3. **实现新建画布弹窗**：在新建画布流程中增加 `purpose` 选择器（素材/导演/成片/通用），打通 `POST /studio/canvases`。

---

## 9. 验收裁定结论 (Verdict Summary)

- **第一批契约与后端接口**：**通过 (PASSED)**
- **第一批前端界面与联动**：**未实现 (PENDING IMPLEMENTATION)**
- **当前影视与视频生成质量**：**失败 (FAILED - 存在单镜头过长、缺少运镜与尾帧接力问题)**
- **3D 白模编辑器功能**：**阻塞 (BLOCKED - 页面报错打不开)**
