# AinerN2D 任务完成状态

> 基于 `progress/skill_delivery_status.yaml` 与代码实际分析，截至 2026-04-02

---

## 一、SKILL 完成状态总览

### ✅ 已完成 (DONE) — 30 个

| # | SKILL | 服务 | DTO | Service | 测试 |
|---|-------|------|-----|---------|------|
| 01 | Story Ingestion & Normalization | studio-api | ✅ | ✅ | ✅ |
| 02 | Language Context Router | studio-api | ✅ | ✅ | ✅ |
| 03 | Story Scene Shot Planner | studio-api | ✅ | ✅ | ✅ |
| 04 | Entity Extraction & Structuring | studio-api | ✅ | ✅ | ✅ |
| 05 | Audio Asset Planner | studio-api | ✅ | ✅ | ✅ |
| 06 | Audio Timeline Composer | composer | ✅ | ✅ | ✅ |
| 07 | Entity Canonicalization | studio-api | ✅ | ✅ | ✅ |
| 08 | Asset Matcher | studio-api | ✅ | ✅ | ✅ |
| 09 | Visual Render Planner | studio-api | ✅ | ✅ | ✅ |
| 10 | Prompt Planner | studio-api | ✅ | ✅ | ✅ |
| 11 | RAG KB Manager | studio-api | ✅ | ✅ | ✅ |
| 12 | RAG Pipeline Embedding | studio-api | ✅ | ✅ | ✅ |
| 13 | Feedback Evolution Loop | studio-api | ✅ | ✅ | ✅ |
| 14 | Persona Style Pack Manager | studio-api | ✅ | ✅ | ✅ |
| 15 | Creative Control Policy | studio-api | ✅ | ✅ | ✅ |
| 16 | Critic Evaluation Suite | studio-api | ✅ | ✅ | ✅ |
| 17 | Experiment A/B Test | studio-api | ✅ | ✅ | ✅ |
| 18 | Failure Recovery & Degradation | studio-api | ✅ | ✅ | ✅ |
| 19 | Compute-Aware Shot Budgeter | studio-api | ✅ | ✅ | ✅ |
| 20 | Shot DSL Compiler | composer | ✅ | ✅ | ✅ |
| 21 | Entity Registry & Continuity | studio-api | ✅ | ✅ | ✅ |
| 22 | Persona Dataset & Index | studio-api | ✅ | ✅ | ✅ |
| 23 | Studio Auth / User / Org | studio-api + web | ✅ | ✅ | ✅ |
| 24 | Project / Novel / Chapter | studio-api + web | ✅ | ✅ | ✅ |
| 25 | Config Center & Model Router | studio-api + web | ✅ | ✅ | ✅ |
| 26 | RAG KB Dataset Persona Console | studio-api + web | ✅ | ✅ | ✅ |
| 27 | World / Culture Pack Manager | studio-api + web | ✅ | ✅ | ✅ |
| 28 | Task / Run Orchestration UI | studio-api + web | ✅ | ✅ | ✅ |
| 29 | Asset Library by Project | studio-api + web | ✅ | ✅ | ✅ |
| 30 | Timeline Editor / NLE | studio-api + web | ✅ | ✅ | ✅ |

### ⚠️ 部分完成 (PARTIAL) — 2 个

| # | SKILL | 当前状态 | 缺失项 |
|---|-------|---------|--------|
| 31 | AI Story Expansion Assistant | 有 API + 前端按钮 | 模板扩写 OK，完整 AI 扩写策略/多模式(expand/complete/rewrite/polish)待完善 |
| 32 | ScriptDoc + WorldModel + Plans | 设计阶段 | Translate 线 / Produce 线分离、Plans 层统一重构未实施 |

---

## 二、基础设施状态

| 组件 | 状态 | 备注 |
|------|------|------|
| PostgreSQL (pgvector) | ✅ 运行中 | 57+ 表, ORM 完整 |
| RabbitMQ | ✅ 运行中 | Topic 编排就绪 |
| Redis | ✅ 运行中 | 缓存/会话 |
| MinIO (S3) | ✅ 运行中 | 素材存储 |
| Alembic 迁移 | ✅ | heads 已合并 |
| Docker Compose | ✅ | 9 容器全栈 |
| Nginx 反向代理 | ✅ | 前端 + API 路由 |

---

## 三、待完成任务清单 (TODO)

### P0 — 可运维可上线 (阻塞生产)

| # | 任务 | 关联 SKILL | 说明 |
|---|------|-----------|------|
| T01 | RabbitMQ 连接修复 | 全局 | studio-api 日志有 AMQPConnectionError，需检查容器内 DNS 或重连策略 |
| T02 | 真实 Provider 健康检查 | 25 | 当前 test-connection 是模拟，需真实请求 LLM API |
| T03 | RBAC ACL 决策可视化 | 23 | 缺 ACL 决策回放/可视化 UI |
| T04 | Run DAG 进度实时跟踪 | 28 | 缺 DAG 进度面板 (节点级 inputs/outputs/logs/cost) |
| T05 | Worker 看板 | 28 | 缺 Worker 实时状态/队列深度看板 |
| T06 | Rerun-stage 面板 | 28 | 阶段级重跑 UI 不完整 |

### P1 — 配置中心产品化

| # | 任务 | 关联 SKILL | 说明 |
|---|------|-----------|------|
| T07 | Feature Routing 可视化增强 | 25 | 功能→模型路由可视化绑定增强 |
| T08 | Provider Secret 安全化 | 25 | 密钥加密存储 (当前明文) |
| T09 | Culture/Persona 版本化 UI | 27/14 | 版本管理 & 回滚 UI |
| T10 | Persona 发布/回滚工作流 | 26 | 完整的审批发布流程 |
| T11 | SKILL_31 多模式 AI 扩写 | 31 | expand/complete/rewrite/polish 四种模式策略 |
| T12 | SKILL_32 Plans 层重构 | 32 | ScriptDoc/WorldModel/Plans 分离架构 |

### P2 — 编辑体验升级

| # | 任务 | 关联 SKILL | 说明 |
|---|------|-----------|------|
| T13 | 时间线 Patch 版本树 | 30 | 补丁历史树展示增强 |
| T14 | 多轨 NLE 增强 | 30 | 吸附/裁切/分组等工业级操作 |
| T15 | 一致性面板增强 | 21/29 | Entity 连续性跨 Run 可视化 |
| T16 | 素材血缘图可视化 | 29 | 资产血缘图 UI 渲染 |
| T17 | 跨 Run 素材复用建议 | 29 | 智能复用推荐面板 |

### P3 — 工业级质检

| # | 任务 | 关联 SKILL | 说明 |
|---|------|-----------|------|
| T18 | Critic 评估面板 | 16 | 8 维度评分可视化 |
| T19 | A/B Test 结果面板 | 17 | 实验结果/变体排名面板 |
| T20 | 自动恢复监控面板 | 18 | 失败恢复/降级策略运行态 |

---

## 四、SKILL 重叠说明 (非冲突，已明确分工)

| 看似重叠 | 实际分工 |
|----------|---------|
| SKILL_04 vs 21 | 04=抽取实体 → 21=固定 entity_id 注册表 |
| SKILL_11 vs 22 | 11=KB CRUD → 22=Dataset+Index+Persona 组装 |
| SKILL_14 vs 15 | 14=风格 DNA + RAG 覆盖 → 15=硬/软/探索约束堆叠 |
| SKILL_09 vs 19 | 09=复杂度→策略 → 19=算力预算分配 |
| SKILL_10 vs 20 | 10=生成 prompt 层 → 20=编译为后端特定格式 |
| SKILL_13 vs 16 | 16=生成后质检门 → 13=长期进化提案 |

---

## 五、SKILL_28 遗留 next_action

来自 `progress/skill_delivery_status.yaml`：
- **P1**: 补 `/runs/{run_id}/nodes/{node_id}` 详情接口 (inputs/outputs/logs/cost)
- **P1**: run-gate 返回 `disabled_reason` 细分枚举
- **P2**: 建立 TrackRegistry/TrackInstance/Clip 持久化与 `/runs/{run_id}/tracks` API
