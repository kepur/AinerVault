# Claude 工作目录（制作界面）

Plan A 三方协作中 Claude 一路的设计、交接与接口变更请求。职责范围见 `../planA_agents.md` §2「Claude 写入区」。

## 文件

| 文件 | 用途 | 读者 |
|---|---|---|
| `batch1_design.md` | 第一批 UI 设计：A/B/C/D 导航与上下文、B/C 自建画布、资产引用、16 格定妆照、后台重组 | Codex、Gemini |
| `batch1_requests.md` | 第一批接口变更请求 CR-01…CR-08 | Codex |
| `handoff_batch1.md` | 第一批交接报告 | Codex、Gemini |

## 当前状态（2026-10-09）

| 标记 | 状态 |
|---|---|
| SOURCE_BATCH1 | Codex 02:27 已写入后端源码（未运行验证） |
| BASE_READY | 未发布（Codex） |
| API_READY | 未发布；`/api/v2/production/*` 源码已存在且可导入，但**运行中的服务未加载**（core 当前已停） |
| UI_READY | **未发布**。第一批交付的是设计，无代码 |

CR-01…CR-08 **已全部裁定并有源码**，裁定见 `../codex/handoff_batch1.md` §3，Claude 的独立复核见 `batch1_design.md` §8。

剩余阻塞：BASE_READY 未发布；后端源码未运行验证；`project_id` 级无小说入口未实现。

本批只支持 `mode=reference`：快照、派生、历史回退在 UI 上隐藏并注明「能力待接」（CR-03 裁定）。

## 约定

- 权威契约是 `../planA_contracts.md`，由 Codex 维护。Claude 不在本目录自行定义契约，只提变更请求。
- 本目录所有「现状」陈述都附查验方式（见 `batch1_design.md` §7），可被独立复核。
- 区分四种状态：设计 / 代码存在 / 集成完成 / 独立验证通过。本目录出现「完成」时必须指明是哪一种。
