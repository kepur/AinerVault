# Claude 第一批交接报告

日期：2026-10-09。提交方：Claude（制作界面）。接收方：Codex（集成）、Gemini（测试）。

交接格式按 `planA_agents.md` §6。

---

## 1. 基线与本方提交

| 项 | 实际情况 |
|---|---|
| BASE_READY | **未发布**（`planA_contracts.md` §8 仍写「未发布」） |
| API_READY | **未发布**；`/api/v2/production/*` 全族在源码中不存在 |
| 工作目录 | 共享目录 `/Users/mac/AinerWorkFlow/AinerHub_IDEA`，未创建独立 worktree |
| 本方代码提交 | **无**。本批不含任何 `code/` 下的改动 |
| git 操作 | 未执行任何 add / commit / branch / stash |

**为什么本批没有代码**：用户指令为「共同基线未准备好时，先做设计和接口需求，不在共享目录抢改代码」；`planA_agents.md` §3 同样要求「发出 BASE_READY 后才正式实现」，并在共享目录情形下要求「先只做各自可独立的准备」。当前工作区有 103 处未提交改动且分属多方，此时在 `src/` 落代码会与基线整理冲突。

---

## 2. 改动路径

仅 Claude 写区内的新建文件，全部为文档：

| 文件 | 内容 |
|---|---|
| `docs/studio/claude/README.md` | 本目录索引与状态 |
| `docs/studio/claude/batch1_design.md` | 第一批 UI 设计（含实测基线） |
| `docs/studio/claude/batch1_requests.md` | 8 条结构化接口变更请求 |
| `docs/studio/claude/handoff_batch1.md` | 本文件 |

未修改：任何后端文件、任何前端源码、`admin.html`、迁移、网关、权威契约、他方文档。

---

## 3. 完成项

对照 `planA_agents.md` §4「Claude 第一批」：

| 要求 | 状态 | 位置 |
|---|---|---|
| A/B/C/D 导航与同一上下文 | 设计完成 | design §2.1 |
| B/C 画布用途与创建流程 | 设计完成 | design §2.2 |
| 资产抽屉引用实体/时期/单格 | 设计完成 | design §2.3 |
| 从角色库加入导演画布 | 设计完成 | design §2.3 |
| 缺视角补建并返回原槽位 | 设计完成，依赖 CR-04 | design §2.3 |
| 定妆照 3+4+9 展示、单格状态与历史 | 设计完成 | design §2.4 |
| 绑定/引用/快照/派生区分 | 设计完成 | design §2.3 表 |
| 未就绪能力显示真实缺项 | 规则确定 | design §2.4、§4 |
| 开发 fixture 标记演示 | 规则确定 | design §4 |
| 不重写后台模型，契约缺失写变更请求 | 遵守 | requests 8 条 |
| 后台流程重组 | 设计完成 | design §2.6 |

**完成的是设计，不是实现。** 按 `planA.md` §14 的口径，本批处于「设计」阶段，未进入「代码存在 / 集成完成 / 独立验证通过」。

---

## 4. 未完成项与缺口

1. 全部 UI 编码（design §3 的 7 项）——待 BASE_READY 与 CR-01…CR-06 裁定。
2. D 成片时间线、3D 导演台多轨、失效与影响范围 UI：属 M2–M4，本批不设计。
3. 道具/地点标准包的 UI：真实数据为 0 条（CR-08），本批只定空状态规则。

---

## 5. 接口 / 契约版本

- 依据：`planA_contracts.md` **v0.1**。
- 本批不引入新契约版本，所有诉求以变更请求提出，等待 Codex 登记。
- UI_READY：**未发布**。

---

## 6. 迁移 / 配置需求

Claude 本批无迁移、无配置、无依赖变更，未改前端锁文件。

需 Codex 处理的后端事项（来自变更请求，均不由 Claude 执行）：

- CR-02 的 `purpose` 存量回填。
- CR-05 的 `char_sheet.py` 表情键修正（或改契约）。
- CR-06 的旧键→新键映射落库与标注。

---

## 7. 启动方式

本批无可启动产物。查验本文所引事实的方式见 design §7。

---

## 8. 实际验证情况与限制

**做过的**：只读查验——端点清单（grep + curl）、`stage/cards` 必填项（curl 422）、production 族不存在（grep 全库）、实体与视角键统计（只读 SQLAlchemy，结束 rollback）、画布统计、前端 `tsc --noEmit` 零报错。

**没做的**：未写库、未提交任何生成任务、未重启服务、未跑测试、未产生媒体、未使用付费端点、未占用 GPU。

**限制**：

1. 本批无代码，Gemini 无可测实现；建议 Gemini 本批只建立验收矩阵并记录基线（与 `planA_agents.md` §4「Gemini 第一批」第一条一致）。
2. 实测只在本机当前数据库；若 Codex 整理基线时变更数据，design §1.2 的数字需重测。
3. `planA.md` §16 提到的样例 ID（`brd_01M4DQ6R8VZA9TATV5BQ949YS7` 等）本批已间接确认画布 ID 真实存在于 `GET /studio/canvases` 返回中；滑雪素材 ID 未查验。

---

## 9. 给 Codex 的请求

1. 裁定 `batch1_requests.md` 的 CR-01…CR-06，并登记契约版本。
2. 发布 BASE_READY，说明基线快照与 Claude 的起始提交。
3. 确认 CR-04 的过渡方案（整包生成代替单格补建，按钮如实标注）是否可接受。

## 10. 给 Gemini 的提示

1. 本批无实现，不要按「功能应可用」记失败，应记「未实现」。
2. design §2.4 的真实形态是 **16 格大面积缺失**；若在真实库看到满格，说明接了演示数据，应记为缺陷。
3. design §7 列出了本方所有事实的查验命令，可用于独立复核本文数字。
