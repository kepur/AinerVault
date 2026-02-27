# SKILL_23_30_PRODUCT_REQUIREMENTS_MASTER.md
# Studio 产品层（23~30）对话需求总规（可接力）

## 0. 目的
- 本文是 23~30 的“对话需求收敛稿”，供多 Agent 接力时做统一验收。
- 若与单个 `SKILL_2X_*.md` 冲突，以该 Skill 规格为准；本文作为补充验收基线。

## 1. 全局产品要求
- 后台必须是 Naive UI 管理界面，具备一级/二级栏目分层，避免把所有功能堆在一个页面。
- 未登录不得操作后台；登录守卫 + Bearer 鉴权 + 基础 RBAC 必须生效。
- API 失败返回统一结构化错误对象（保留 `error_code/retryable/owner_module/trace_id` 契约）。
- 所有核心页面支持列表/过滤/增删改查，布局以“配置页 / 工作台页 / 执行页”分离。

## 2. 编排与通知（本轮新增硬要求）
- `bootstrap-defaults` 必须使用真实 LangGraph（StateGraph）编排，而非普通 for 循环。
- Bootstrap 需支持：
  - `model_profile_id` 可选
  - `role_ids` 多选
  - `enrich_rounds`
  - `session_id` + WS 实时进度
- Telegram 通知必须不仅用于测试按钮，还需覆盖跨模块关键调用（至少）：
  - `task.submitted`
  - `bootstrap.started / bootstrap.completed / bootstrap.failed`
  - `role.skill.run.completed / role.skill.run.failed`
- 通知必须受 `notify_events` 过滤，避免全量噪声推送。

## 3. 按 Skill 补充验收
### SKILL_23（Auth）
- 登录页支持语言选择。
- 默认测试账号可直接登录验证。
- 后续待补：project 维度细粒度 ACL 中间件（P1）。

### SKILL_24（Novel/Chapter）
- 小说与章节必须拆页：
  - 小说列表页：默认只显示小说，不显示章节。
  - 章节工作区：选中小说后展示章节列表。
- 章节编辑器为全屏工作区：左 Markdown 编辑，右实时预览。
- 必须有“一键 AI 扩写剧情”入口并可回写编辑区。

### SKILL_25（Config/Model Router）
- Provider 配置需覆盖：公网/本地、token、能力标签（embedding/multimodal/tts 等）。
- `Model Profile` 与 `Feature Route Map` 必须独立页面，不与 Provider CRUD 混堆。
- 初始化入口必须支持“选模型 + 选角色 + enrich rounds”并写库。
- 支持 provider 联通测试按钮，能显示 connected/latency/status。

### SKILL_26（RAG/Persona）
- 角色可挂载知识包并支持增量导入任务（txt/pdf/excel 文本抽取链路可继续迭代）。
- 角色工作台可直接调用知识导入、查看变化报告。

### SKILL_27（Culture）
- 文化包保持独立管理页，支持列表筛选与版本导出。

### SKILL_28（Task/Run）
- Chapter -> Task/Run 闭环必须保留。
- Run Snapshot 冻结需包含 provider/router/language/telegram 等配置快照。
- 通知入口与配置中心打通（TG/Webhook 先做 TG）。

### SKILL_29（Asset）
- 素材库与素材绑定一致性必须是独立页面。
- 人物/场景/道具绑定可查看、过滤、锁定、重生成入口保留。

### SKILL_30（Timeline）
- PR 式 patch 页面独立展示，不可与其它模块拥挤堆叠。
- 当前以 patch 驱动为主；多轨拖拽编辑器属于后续增强项（P1/P2）。

## 4. 四大配置模型（必须配置化）
### 4.1 ModelProfile（模型档案）
- 目标：不是“选模型”，而是可复用推理配置包。
- 必含字段：
  - `provider`
  - `model_name`
  - `capability_tags`（`long_context/json_schema/vision/tool_call/fast/cheap/embedding/multimodal`）
  - `default_params`（`temperature/top_p/max_tokens`）
  - `cost_rate_limit`
  - `guardrails`
  - `routing_policy`（fallback profile）

### 4.2 RoleProfile（角色档案）
- 角色 = 默认技能套餐 + 默认知识域 + 默认模型。
- 必含字段：
  - `role_id`
  - `prompt_style`
  - `default_skills`
  - `default_knowledge_scopes`
  - `default_model_profile`
  - `permissions`

### 4.3 SkillRegistry（技能注册）
- 每个技能用统一 schema 注册，避免前端硬编码入口。
- 建议最小字段：
  - `skill_id`
  - `input_schema`
  - `output_schema`
  - `required_knowledge_scopes`
  - `default_model_profile`
  - `tools_required`
  - `ui_renderer`
  - `init_template`

### 4.4 FeatureRouteMap（功能路由映射）
- 目标：新增技能时只加映射，不改一堆页面路由逻辑。
- 必含字段：
  - `route_id/path/component`
  - `feature_id`
  - `allowed_roles`
  - `ui_mode`
  - `depends_on`

## 5. 两条后台生产线（接力必做）
### 5.1 Skill 初始化流水线（Bootstrapping）
- 选模型档案 + 角色集合 + enrich rounds。
- LLM 模板生成基础知识和角色默认配置。
- 入库 Role/Skill/Route/Language/StageRouting。
- 通过 LangGraph StateGraph 编排，支持 WS 进度事件流。

### 5.2 知识导入增量流水线（RAG Evolution）
- 导入 txt/pdf/excel 等文本内容。
- 解析 -> 抽取术语/规则 -> 去重 -> chunk -> embedding/upsert。
- 生成 knowledge change report，并标记影响角色/技能。

## 6. Role Studio 工作台形态
- 任务面板：小说/章节/任务树。
- 技能面板：角色可执行技能（参数+模型+知识域）。
- 知识面板：挂载 pack、导入入口、命中引用。
- 运行日志面板：输入输出、成本、失败重试、引用片段。

## 7. IA 与页面拆分（避免拥挤）
- 顶层栏目建议：
  - Studio（Run/Timeline/Regenerate）
  - Roles（RoleProfile/SkillRegistry/RouteMap）
  - Knowledge（KB/Import/Index/Eval）
  - Models（Provider/ModelProfile/Router）
  - Ops（Queue/Worker/Artifacts/Logs）
- 强制拆页要求：
  - Novel 列表页与 Chapter 工作区分离。
  - Provider/Profile/Route 分离为独立页面。
  - Timeline patch/PR diff 独立页面。
  - Asset 绑定一致性独立页面。

## 8. 通知与可观测补充
- Telegram 必须具备：
  - 配置保存 + 测试发送
  - `notify_events` 白名单过滤
  - 跨模块调用通知（任务、bootstrap、role skill、章节AI扩写、RAG导入、timeline patch/job）
- Bootstrap 需保留 `session_id` WS 实时日志，便于初始化过程审计。

## 9. P0 / P1 规划（接力建议）
### P0（先完成）
- LangGraph bootstrap + WS 进度 + TG 跨模块通知。
- 小说/章节拆页 + 后台信息架构分层。
- Model Profile / Feature Route 独立页。
- 初始化入口支持“选模型 + 选角色 + enrich rounds”。

### P1（下一轮）
- 强 RBAC（project 细粒度 ACL）中间件。
- Provider 配额/限流/余额指标。
- 时间线 patch 版本树 + 回滚对比（拖拽多轨后续）。
- Persona 发布/回滚评审流。
