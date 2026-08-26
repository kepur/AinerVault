# AinerN2D — Agent 入口

> ## ⚠️ 2026-08-26 起：主线已切换到 v2
>
> **v2 设计基线在 `docs/v2/`，新工作一律以它为准。**
> 本文件以下内容描述的是 **v1（32 SKILL / 5 微服务 / DAG 编排）**，现已**冻结**：
> 代码保留可运行，但不再维护、不再扩展。仅作参考实现查阅。
>
> | 先读 | 内容 |
> |------|------|
> | [`docs/v2/00_OVERVIEW.md`](docs/v2/00_OVERVIEW.md) | 为什么重构、系统边界、主干模型、冻结清单 |
> | [`docs/v2/01_DATA_MODEL.md`](docs/v2/01_DATA_MODEL.md) | 20 张表（v1 为 57+）、版本化、旧表映射 |
> | [`docs/v2/02_CORE_API.md`](docs/v2/02_CORE_API.md) | Core 对外 API（~50 个路由，v1 为 145+） |
> | [`docs/v2/03_CAPABILITY_API_SPEC.md`](docs/v2/03_CAPABILITY_API_SPEC.md) | ★ 能力 API 标准（中间层契约） |
> | [`docs/v2/capability-api.openapi.yaml`](docs/v2/capability-api.openapi.yaml) | 上者的 OpenAPI 3.1，可直接生成 server stub |
> | [`docs/v2/04_ADMIN_UX.md`](docs/v2/04_ADMIN_UX.md) | 后台重设计：5 个区、一个工作台、6 条交互铁律 |
> | [`docs/v2/05_ROADMAP.md`](docs/v2/05_ROADMAP.md) | 落地顺序 P0/P1/P2、冻结做法、迁移脚本 |
> | [`docs/v2/06_WORLDVIEW_TRANSLATION.md`](docs/v2/06_WORLDVIEW_TRANSLATION.md) | ★ **世界观转译**：中国古代→日本昭和/欧洲中世纪，L1–L4 四层映射、防漂移三道闸 |
>
> v2 一句话：**AinerN2D 是一台「小说 → 多语言剧本 → 视频素材清单」的编译器。**
> 它不生成像素、不生成声波、不合成视频；它生成结构与指令，交给能力中间层执行。

---

# 附录：v1 存档（已冻结）


> 本文件是 AI Agent / 开发者的唯一启动入口。所有文档已按职责归类到子目录。

## 仓库目录结构

```
├── START_HERE_FOR_AGENTS.md   ← 你在这里
├── TASK_STATUS.md             ← 任务完成状态总览
├── code/                      ← 全部源码
│   ├── apps/
│   │   ├── ainern2d-studio-api/   后端主服务 (FastAPI, 145+ 路由)
│   │   ├── ainern2d-worker-hub/   任务分发 & 回调
│   │   ├── ainern2d-composer/     音视频合成
│   │   ├── ainern2-worker-runtime/ Worker 实现 (TTS/Video/LLM/Lipsync)
│   │   ├── ainern2d-studio-web/   前端 (Vue3 + TypeScript)
│   │   └── alembic/               数据库迁移
│   ├── shared/                    共享 ORM / DTO / 工具
│   ├── infra/                     Docker 基础设施配置
│   ├── scripts/                   开发/运维脚本
│   └── docker-compose.yml
├── docs/
│   ├── architecture/              00-14 微服务架构文档
│   ├── skills/                    SKILL_01-32 规格文档 + 进度
│   ├── integration/               集成指南 (README_*.md)
│   └── contracts/                 契约/事件/错误码
└── progress/                      交付进度 & Agent 接力
    ├── skill_delivery_status.yaml ← 进度权威 (机器可读)
    ├── SKILL_AGENT_PLAYBOOK.md    ← Agent 执行手册
    └── NEXT_AGENT_PROMPT.md       ← 下一个 Agent 接力 prompt
```

## 快速阅读顺序

| 优先级 | 文档 | 用途 |
|-------|------|------|
| **P0** | `progress/skill_delivery_status.yaml` | 32 个 SKILL 机器可读状态 |
| **P0** | `TASK_STATUS.md` | 完成/待办任务总览 |
| **P1** | `docs/architecture/00.架构.md` | 系统边界 & 术语 |
| **P1** | `docs/contracts/ainer_contracts.md` | API & 事件契约 |
| **P1** | `docs/contracts/ainer_event_types.md` | 事件类型定义 |
| **P1** | `docs/contracts/ainer_error_code.md` | 错误码定义 |
| **P2** | `docs/integration/README_01_30_MASTER_INTEGRATION.md` | 01-30 主链集成 |
| **P2** | `docs/integration/README_21_22_INTEGRATION_GUIDE.md` | 21/22 插入指南 |
| **P2** | `docs/integration/README_23_30_PRODUCT_GAP_PLAN.md` | 产品层差距计划 |
| **P3** | `docs/skills/SKILL_XX_*.md` | 实施前必读对应 SKILL 规格 |
| **P3** | `progress/SKILL_AGENT_PLAYBOOK.md` | Agent 执行手册 |

## 系统概览

**AinerN2D** = AI 小说转视频全自动生产系统

```
小说 → 场景(Scene) → 镜头(Shot) → 画面(Asset/Entity) + 声音(Audio)
```

### 核心 DAG 执行链

```
01(Ingestion) → 02(LangRouter) → 03(SceneShotPlan) → 04(EntityExtract)
  → 21(EntityRegistry) → 05(AudioPlan) → 06(AudioTimeline) → 07(Canonicalize)
  → 08(AssetMatch) → 14(Persona) → 15(CreativePolicy) → 19(ShotBudget)
  → 09(VisualPlan) → 10(PromptPlan) → 20(DSLCompile)
  → [渲染执行] → 16(Critic) → 18(Recovery) → 13(Feedback) → 17(A/B Test)
```

### 微服务映射

| 服务 | SKILL | 端口 |
|------|-------|------|
| **studio-api** | 01-05, 07-19, 21-30 | 8000 |
| **composer** | 06, 20 | 8020 |
| **worker-hub** | 分发调度 | 8010 |
| **worker-runtime** | TTS/Video/LLM/Lipsync | - |
| **studio-web** | 23/26/28/30/31 (UI) | 5173 |

## 核心约束

- 主运行对象：`run / job / stage / event / artifact`
- 仅 Orchestrator 可发布 `run.stage.changed`
- 写链路必带：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`
- 失败必带：`error_code / retryable / owner_module / trace_id`
- **禁止**：自定义 stage / 绕过 orchestrator 写终态 / 新增 `step.*` 主事件

## 代码框架

| 层 | 路径模式 |
|----|---------|
| **DTO** | `code/shared/ainern2d_shared/schemas/skills/skill_XX.py` |
| **Service** | `code/apps/ainern2d-studio-api/app/services/skills/skill_XX_*.py` |
| **Service (06/20)** | `code/apps/ainern2d-composer/app/services/skills/skill_XX_*.py` |
| **调度** | `SkillRegistry.dispatch(skill_id, input, ctx)` |
| **ORM** | `code/shared/ainern2d_shared/ainer_db_models/` |

所有 Service 继承 `BaseSkillService`：`run(input_dto, ctx)` → `execute(input_dto, ctx)`

## 开发环境

```bash
# 启动 (需要 Docker + 虚拟环境)
source .venv/bin/activate
cd code && bash scripts/dev-up.sh

# 数据库迁移
cd code/apps && python -m alembic upgrade head

# 前置门禁
python3 code/scripts/validate_preimplementation_readiness.py --strict
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost (nginx) / http://localhost:5173 |
| Studio API | http://localhost:8000/docs |
| Worker Hub | http://localhost:8010/docs |
| Composer | http://localhost:8020/docs |
| RabbitMQ | http://localhost:15672 |
| MinIO | http://localhost:9001 |

## 交付规范

1. 实现前读 `docs/skills/SKILL_XX_*.md` 规格
2. 重建顺序：DTO → Service → 调度注册 → DAG 接线 → 测试 → 进度回写
3. 实现后更新 `progress/skill_delivery_status.yaml`
4. 前置门禁必须 PASS：`validate_preimplementation_readiness.py --strict`
