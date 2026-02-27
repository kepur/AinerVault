# START HERE FOR AGENTS

## 0. 目标
- 这是协作 AI/开发者的唯一启动入口。
- 目标：按统一边界与门禁实现，不跑偏，不越权。

## 1. 强制阅读顺序（MUST）
1) `00.架构.md`（目录结构总纲与系统边界起点）
2) `progress/README.md`（接力进度入口）
3) `progress/skill_delivery_status.yaml`（22 技能机器可读状态）
4) `progress/SKILL_AGENT_PLAYBOOK.md`（Agent 专用执行手册）
5) `SKILL_IMPLEMENTATION_PROGRESS.md`（历史明细）
6) `code/docs/runbooks/implementation-status-ledger.md`
7) `ainer_contracts.md`
8) `ainer_event_types.md`
9) `ainer_error_code.md`
10) `code/docs/architecture/stage-enum-authority.md`
11) `code/docs/architecture/service-api-contracts.md`
12) `code/docs/architecture/queue-topics-and-retry-policy.md`
13) `code/docs/runbooks/agent-implementation-playbook.md`
14) `code/docs/runbooks/ci-gate-execution-spec.md`
15) `code/docs/runbooks/e2e-handoff-test-matrix.md`
16) `code/docs/architecture/agent-data-model-guideline.md` (Agent数据模型直接落地必读基线)
17) `code/docs/runbooks/agent-direct-implementation-readiness.md`（直落地可行性与补齐清单）
18) `code/docs/architecture/agent-coding-framework-guideline.md` (Agent编码框架与代码生成模板指南)
19) `README_21_22_INTEGRATION_GUIDE.md`（01~22 主链接入权威）
20) **实施前必须读取目标 SKILL 对应根目录规格**：`SKILL_XX_*.md`

## 2. 核心约束（必须遵守）
- 主运行对象：`run/job/stage/event/artifact`。
- 主状态事件：`job.succeeded/job.failed`；`worker.*.completed` 仅执行明细。
- 仅 Orchestrator 可发布 `run.stage.changed`。
- 所有写链路必须带：`tenant_id/project_id/trace_id/correlation_id/idempotency_key/schema_version`。
- 失败必须带：`error_code/retryable/owner_module/trace_id`。

## 3. 禁止项（FORBID）
- 禁止自定义与 stage 权威冲突的新 stage。
- 禁止绕过 orchestrator 直接写 run 终态。
- 禁止新增 `step.*` 作为运行态主事件。
- 禁止未过 CI/E2E Blocker 门禁直接合并。
- 禁止在无替代实现的情况下直接删除 `code/shared/.../schemas/skills/skill_*.py` 与 `code/apps/*/services/skills/skill_*.py`。

## 4. 实施顺序（固定）
1) 模型与迁移
2) 编排状态机
3) 执行链路（worker-hub/worker）
4) 合成发布（composer）
5) 观测治理（observer）
6) 增强层（14~22）

## 4.6 当前权威主链（SKILL_01 ~ SKILL_22）
- **第一权威**：根目录 `SKILL_01_STORY_INGESTION_NORMALIZATION.md` 到 `SKILL_22_PERSONA_DATASET_INDEX_MANAGER.md`（22 个 SKILL 规格文件）。
- **第二权威（接入说明）**：`README_21_22_INTEGRATION_GUIDE.md`（只用于说明 21/22 如何插入既有链路）。
- `21` 插入位：`04 -> 21 -> 07`。
- `22` 插入位：`11 + 12 + 14 -> 22 -> 10/15/17`。
- 若其它文档仍是旧口径（如只覆盖到 `SKILL_20`），按“历史说明”处理，不得覆盖本链路。
- 若 `README_21_22_INTEGRATION_GUIDE.md` 与任一 `SKILL_XX_*.md` 冲突，以对应 `SKILL_XX_*.md` 为准。

## 4.7 模块责任（00~14 架构文档）
- `00.架构.md`：全局边界、主术语、系统主流程
- `01.ainer-gateway.md`：入口/API 网关责任
- `02.ainer-orchestrator.md`：run/job/stage 编排与状态推进
- `03.ainer-entity-core.md`：实体核心能力
- `04.ainer-asset-knowledge.md`：素材/知识检索层
- `05.ainer-planner.md`：规划链路（shot/prompt/timeline）
- `06.ainer-model-router.md`：模型路由与降级决策
- `07.ainer-worker-hub.md`：任务分发与回调聚合
- `08.ainer-worker-video.md`：视频执行器
- `09.ainer-worker-audio.md`：音频执行器
- `10.ainer-worker-llm.md`：LLM 执行器
- `11.ainer-worker-lipsync.md`：口型执行器
- `12.ainer-composer.md`：合成与出片
- `13.ainer-observer.md`：观测与审计
- `14.ainer-studio-web.md`：前端工作台责任

## 4.8 SKILL 实现框架（AI 接力必读）
- 规格权威在根目录：每个 SKILL 实施前先读对应 `SKILL_XX_*.md`
- Service 文件边界：
  - `SKILL_01~05,07~19`：`code/apps/ainern2d-studio-api/app/services/skills/skill_XX_*.py`
  - `SKILL_06,20`：`code/apps/ainern2d-composer/app/services/skills/skill_XX_*.py`
  - `SKILL_21,22`：`code/apps/ainern2d-studio-api/app/services/skills/skill_21_*.py` / `skill_22_*.py`（已落地骨架+调度+DAG+服务级 E2E）
- DTO 文件边界：`code/shared/ainern2d_shared/schemas/skills/skill_XX.py`（`01~22` 已有）
- 所有 Service 继承 `BaseSkillService`
  - 对外统一调用入口：`run(input_dto, ctx)`
  - 子类实现核心逻辑：`execute(input_dto, ctx)`
- 调度路径：
  - studio-api：`SkillRegistry.dispatch(skill_id, input, ctx)`
  - composer（06/20）：`ComposerSkillDispatcher.execute_job(job)`
- **实现某个 SKILL 后必须更新 `progress/skill_delivery_status.yaml` 对应条目（权威）**
- `SKILL_IMPLEMENTATION_PROGRESS.md` 仅保留历史明细
- SKILL DAG 依赖关系见 `README_21_22_INTEGRATION_GUIDE.md` 与 `progress/skill_delivery_status.yaml`

## 4.9 SKILL 文件重建策略（替换式，不是删除式）
- 源头权威：`SKILL_XX_*.md` + `README_21_22_INTEGRATION_GUIDE.md` + `ainer_contracts.md` + `ainer_event_types.md` + `ainer_error_code.md`。
- 重建顺序固定：`DTO -> Service -> 调度注册 -> DAG接线 -> 测试 -> 进度回写`。
- 允许“替换重写”单个 skill 文件；不允许“全量删除后再慢慢补”。
- 删除条件：仅当该 skill 的替代 DTO/Service/调度/测试已就位，且 `progress/skill_delivery_status.yaml` 已更新为可接力状态。

## 5. 验收门禁
- 统一前置门禁：`python3 code/scripts/validate_preimplementation_readiness.py --strict`
- 若需要真实库门禁：`DATABASE_URL=postgresql+psycopg2://ainer:ainer_dev_2024@localhost:5432/ainer_dev python3 code/scripts/validate_preimplementation_readiness.py --strict`
- 报告产物：`progress/PREIMPLEMENTATION_READINESS_REPORT.md`
- `alembic upgrade -> downgrade -> upgrade` 必须通过。
- E2E Blocker 用例必须 100% 通过。
- 术语扫描必须一致（run/job/stage/event/artifact）。

## 6. 交付输出
- 更新 `implementation-status-ledger.md` 状态。
- 更新 `progress/skill_delivery_status.yaml` 对应 skill 条目（status/gate/next_action）。
- 附验证证据（迁移日志、E2E结果、关键事件链）。

## 7. 历史文档策略（避免冲突）
- 历史审计/旧接入说明文档已物理删除，不再作为实现输入。
- 旧文档若出现 `skill.xx.completed` 事件命名，以 `ainer_event_types.md` 和 `ainer_contracts.md` 为准。
- 新增/删除文档后，必须执行一次全仓引用扫描，确保无悬挂引用。
- 进度权威以 `progress/skill_delivery_status.yaml` 为准，`SKILL_IMPLEMENTATION_PROGRESS.md` 作为历史明细参考。
