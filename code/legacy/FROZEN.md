# v1 冻结说明

> 2026-08-27 起，v1 整体冻结。**代码一行未删，可运行、可查阅、可按需解冻。**

## 冻结范围

`code/apps/` 下的五个 v1 应用：

| 目录 | 说明 |
|------|------|
| `ainern2d-studio-api/` | 145+ 路由、SkillRegistry、32 个 SKILL service |
| `ainern2d-worker-hub/` | 任务分发与回调 |
| `ainern2d-composer/` | 音视频合成（SKILL 06/20） |
| `ainern2-worker-runtime/` | TTS / Video / LLM / Lipsync worker |
| `ainern2d-studio-web/` | 42 个页面的前端 |

数据库中的 `public` schema（96 张表）同样原样保留。v2 的表全部在 `core` schema，两者物理隔离。

## 怎么启动 v1

```bash
docker compose --profile legacy up -d
```

`docker-compose.yml` 里这五个服务已标 `profiles: ["legacy"]` —— 默认 `docker compose up` 不会启动它们，但加 profile 随时可拉起。基础设施（postgres / redis / minio / rabbitmq）仍是默认启动，v1 与 v2 共用。

## 为什么不在 v1 上改，而是另起 ainer-core

v1 的代码依赖三样东西，混在一起会把它们带进 v2：

1. `SkillRegistry.dispatch` + `BaseSkillService` —— 为「32 个可插拔技能」设计的通用 DAG 框架。v2 只有一条固定的线性管线，用普通 Python 函数表达即可（见 `app/pipelines/`）。
2. RabbitMQ 的 `run.stage.changed` 事件契约与 orchestrator 写终态的约束。
3. `tenant_id` / `project_id` 双层作用域中间件。v2 砍掉多租户，只留 `workspace_id` 作扩展位。

物理隔离是最便宜的解耦。v1 保持为一份可运行的参考实现。

## 将来要解冻某个能力，该怎么接

**不要**把它重新接回 DAG。正确做法是走 v2 的数据边界：

| 想解冻的能力 | 接法 |
|-------------|------|
| NLE / 时间线编辑（SKILL 30） | 消费 v2 的 `POST /chapters/{id}/export` 的 `manifest` 格式，作为独立工具 |
| 音视频合成（SKILL 06/20） | 实现为 Capability Gateway 的一个能力，或消费 manifest 的外部服务 |
| Critic 评估（SKILL 16） | 读 `core.assets` + `core.gen_tasks`，写回一张自己的评分表 |
| A/B Test（SKILL 17） | 在 `core.capability_routes` 上做流量分配，不需要新框架 |
| Persona / RAG Console（22/26） | v2 已把 RAG 用于世界观 KB（见 `docs/v2/06`），先看那条线够不够 |

## 已从 v1 继承到 v2 的资产

这些是 v1 里质量最高的部分，v2 直接继承而非重写：

- **占位符防漂移机制**（`translation.py` 的 `_build_placeholder_maps`）：别名一起替换、按长度倒序、LLM 变异容错、锁定语言缺译名硬失败。v2 在此基础上修了 `hash()` 兜底漂移 bug。
- **术语表 + 候选审核 + 一致性告警** 三张表的模型设计。
- **文化绑定的两层抽象**（SKILL_07）：Canonical Entity → Cultural Variant。v2 把它从画面线扩展到了正文线。
- **实体 × 文化包 视觉变体**（`EntityPromptVariant` 的 UNIQUE 约束思路）→ v2 的 `entity_world_visual`。
