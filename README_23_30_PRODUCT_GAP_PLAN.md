# README_23_30_PRODUCT_GAP_PLAN.md
# Studio 产品层（SKILL 23~30）缺口审计与优化规划

## 1. 审计结论（2026-02-27）
- 已完成：23~30 主干可用，支持登录守卫、章节管理、Task/Run 创建、Provider+Profile 配置、RAG/Culture 管理、素材库、时间线 patch、素材绑定一致性页面。
- 部分完成：任务运行中心、配置中心健康检查、权限体系、时间线工业级编辑体验。
- 未完成：强 RBAC/ACL 中间件细粒度校验、真实 provider 连通健康检查、Worker 状态看板、rerun-stage 操作面板、patch 版本树/回滚。

## 2. 后端 -> 前端落地差距（接口对账）
当前后端存在但前端未形成统一封装/页面能力的关键接口：
1. `/api/v1/runs/{run_id}`（Run 状态详情）
2. `/api/v1/runs/{run_id}/assets`（Run 维度产物）
3. `/api/v1/runs/{run_id}/policy-stacks`（策略回放）
4. `/api/v1/runs/{run_id}/prompt-plans`（Prompt 回放）
5. `/api/v1/runs/{run_id}/regenerate`（全 Run 重生成）
6. `/api/v1/shots/{shot_id}/regenerate`（单 Shot 重生成）
7. `/api/v1/tasks`（直接任务入口）
8. `/api/v1/projects` / `/api/v1/projects/{project_id}`（项目治理页面）
9. `/api/v1/novels/{novel_id}`（小说详情页能力）
10. `/api/v1/culture-packs/{culture_pack_id}/versions`（文化包版本列表）
11. `/api/v1/projects/{project_id}/entities/{entity_id}/continuity-profile`（一致性详情抽屉）

## 3. SKILL DoD 达成度评估
- SKILL_23：80%
  - 已达成：登录/登出、ACL、审计日志。
  - 缺口：缺少“项目级细粒度 ACL 强制中间件”，目前以角色门禁为主。
- SKILL_24：85%
  - 已达成：Project/Novel/Chapter CRUD、修订历史、01~03 预览、发起任务。
  - 缺口：章节发布态（draft/released）与审批流未落地。
- SKILL_25：75%
  - 已达成：Provider Token+Capability 配置、Profile CRUD、Stage/Feature 路由、Feature Matrix、Telegram 配置、Snapshot 冻结。
  - 缺口：密钥未接 Vault/KMS；健康检查非真实探测（未探 API 可用性/配额/速率）。
- SKILL_26：80%
  - 已达成：Collection/KB/Persona CRUD、绑定、Preview。
  - 缺口：Persona 发布/回滚工作流与审批日志。
- SKILL_27：80%
  - 已达成：Culture Pack CRUD + export。
  - 缺口：版本管理与规则校验器未在 UI 打通。
- SKILL_28：65%
  - 已达成：Chapter -> Task/Run、Snapshot。
  - 缺口：DAG 进度、Worker CPU/GPU/Queue 看板、rerun-stage、运行日志检索。
- SKILL_29：85%
  - 已达成：素材归档检索、anchor 回流、一致性绑定独立页面。
  - 缺口：资产血缘图与跨 run 复用推荐。
- SKILL_30：70%
  - 已达成：多轨展示、拖拽保存、PR patch + rerun-shot。
  - 缺口：patch 版本树、可视化回滚、真正 NLE 级多轨吸附/裁切/分组。

## 4. 优化规划（建议排期）
### Phase A（P0，1~2 周）：可运维可上线
1. 强 RBAC + Project ACL 中间件
- 所有写接口强制校验 `tenant_id/project_id` 与成员角色。
- 验收：越权请求 100% 403；审计记录含 actor+resource+action。

2. Provider Secret 安全化
- 将 `access_token` 从业务 JSON 迁移到 vault adapter（本地可先 env+加密层）。
- 验收：DB 不落明文密钥；UI 仅显示 masked token。

3. 运行中心可观测化
- Run DAG、stage 进度、失败原因、重试入口、run/shot regenerate。
- 验收：可在 `/studio/runs` 完成“失败定位 -> 重跑 -> 状态回看”。

### Phase B（P1，2~3 周）：配置中心产品化
1. Feature Routing 可视化
- 由 JSON 改成“功能卡片 + 可选 profile 下拉 + 能力约束校验”。
- 验收：不支持 embedding 的模型无法绑定 embedding 功能。

2. 实时健康检查
- 连通性、模型可用性、耗时、速率、余额（若 provider 支持）
- 验收：health 页有最近探测时间、状态、失败原因。

3. Culture/Persona 版本化 UI
- 列表、对比、发布、回滚。
- 验收：版本变更可追溯并可回滚。

### Phase C（P2，3~4 周）：编辑体验升级
1. 时间线 patch 版本树（PR 历史）
- patch diff、审阅、回滚、对比。
2. 多轨 NLE 增强
- 吸附、裁切、分组移动、批量替换素材。
3. 一致性面板增强
- continuity-profile 详情抽屉、角色/场景/道具冲突告警。

## 5. 建议新增功能（高价值）
1. 模型成本看板：按 provider/model/run 统计 token/cost/latency。
2. Prompt 回放中心：按 shot 看 prompt 演进与效果对照。
3. 项目模板化：快速创建“导演A+B文化包+路由策略”组合。
4. 运行 SLA 规则：超时/失败阈值告警到 Telegram/Webhook。
5. 素材质量评分：结合 SKILL_16 结果做素材优先级排序。

## 6. 下一轮执行建议（可直接派工）
- Task-01：`/studio/runs` 接入 run detail + run/shot regenerate + stage DAG。
- Task-02：配置中心增加“功能绑定下拉器”，替代 feature_routes JSON 手填。
- Task-03：接入 continuity-profile 详情抽屉并打通冲突提示。
- Task-04：补 `projects` 管理页（列表/详情/成员）并接 ACL。
