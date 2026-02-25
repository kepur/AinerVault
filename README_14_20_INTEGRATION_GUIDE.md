# README_14_20_INTEGRATION_GUIDE.md
# AinerN2D 14~20 工业级增强层接入说明（接入 01~13）

本说明定义：`14~20` 如何插入现有 `01~13` Skill 流程。它们是增强层，不替代主链。

---

## 一、当前主链（已有）
- `01~03`：内容入口 → 路由 → 场景/镜头规划
- `04~06`：实体抽取 → 音频规划 → 音频时间线回填
- `07~10`：文化绑定 → 素材匹配 → 视觉渲染规划 → Prompt Planner
- `11~13`：RAG知识库管理 → 向量化管线 → 反馈进化闭环

---

## 二、14~20 的定位（增强层）
1. 风格人格层：`14`
2. 控制治理层：`15`, `18`, `19`
3. 质量评测/实验层：`16`, `17`
4. 编译适配层：`20`

---

## 三、推荐接入位置（核心）

### A) Persona 风格人格层（14）
- 接入点：`10_PROMPT_PLANNER` 之前（强烈建议）
- 可选：在 `09_VISUAL_RENDER_PLANNER` 之前影响镜头切分偏好
- MVP：先注入 `persona_id` / `style_dna` / `rag_recipe_override`

### B) 创作控制策略栈（15）
- 依赖：`06`（音频时序） + `07`（文化约束） + `14`（人格）
- 输出给：`19`、`09`、`10`、`18`
- 推荐顺序：`06 + 07 + 14 -> 15 -> 19 -> 09 -> 10/20`

### C) 镜头级算力预算器（19）
- 接入点：`09` 前（推荐）或作为 `09` 子步骤
- 依赖：`03 shot_plan` + `06 audio_event_manifest` + `15 control stack`
- 作用：shot 级动态 fps/分辨率/重试预算

### D) Shot DSL 编译层（20）
- 接入点：`10` 之后、执行器之前（推荐）
- 结构：`10` 输出 DSL seed/intent，`20` 编译为后端特定 prompt/参数

### E) Critic 评测套件（16）
- 接入点：渲染后
- 输出到：`18`（自动修复/降级） + `13`（长期进化） + `17`（实验评分）

### F) 失败恢复与降级（18）
- 接入点：异常时触发，重点挂在 `09/10/20` 执行与 `16` 之后
- 工业状态：`success` / `success_with_degradation` / `partial_review_required` / `failed_blocking`

### G) 实验与 A/B 编排（17）
- 接入点：后台优化层，不属于单次主链
- 变量来源：`14`、`11/12`、`15`、`19`、`20`

---

## 四、升级后主链（工业版）
1. `01` Story Ingestion
2. `02` Language Context Router
3. `03` Story→Scene→Shot Planner
4. `04` Entity Extraction
5. `05` Audio Asset Planner
6. `06` Audio Timeline Composer
7. `07` Entity Canonicalization + Cultural Binding
8. `08` Asset Matcher
9. `14` Persona Style Pack Resolve
10. `15` Creative Control Policy Build
11. `19` Compute-Aware Shot Budgeter
12. `09` Visual Render Planner
13. `10` Prompt Planner
14. `20` Shot DSL Compiler / Backend Adapter
15. 执行渲染（workers）
16. `16` Critic Evaluation Suite
17. `18` Failure Recovery & Degradation（按需）
18. `13` Feedback Evolution Loop
19. `17` A/B Experiment Orchestrator（离线/后台）

---

## 五、最小接入方案（增量）

### Phase A（收益优先）
- `14` Persona（先接 10）
- `15` Control Policy（先做 hard/soft 分层）
- `19` Shot Budgeter（先做 fps/优先级）
- `16` Critic（先做 2~3 个 critic）

### Phase B（稳定性）
- `18` Failure Recovery（失败矩阵 + 降级状态）
- `20` Shot DSL Compiler（后端解耦）

### Phase C（优化飞轮）
- `17` A/B 编排（连接 16 打分）
- 与 `13` 反馈进化联动

---

## 六、版本追溯（必须）
每次 run 至少记录：
- `kb_version_id`（11/12）
- `persona_version`（14）
- `creative_policy_version`（15）
- `compute_budget_policy_version`（19）
- `compiler_template_version`（20）
- `prompt_recipe_version`（10）
- `critic_suite_version`（16）

---

## 七、一句话总结
`14~20` 为现有 `01~13` 增加了：
- 可控风格（14）
- 系统治理（15/18/19）
- 可评测进化（16/17）
- 可移植执行（20）

从“强生成流水线”升级为“工业级 AI 导演工厂”。

---

## 八、落地不跑偏（强制）
实现前必须按以下文档执行：
- `code/docs/runbooks/implementation-status-ledger.md`
- `code/docs/architecture/stage-enum-authority.md`
- `code/docs/architecture/service-api-contracts.md`
- `code/docs/architecture/queue-topics-and-retry-policy.md`
- `code/docs/runbooks/ci-gate-execution-spec.md`

禁止项：
- 禁止自定义与 stage 权威冲突的新 stage。
- 禁止用 `worker.*.completed` 替代 `job.succeeded/job.failed`。
- 禁止绕过 Orchestrator 直接写 run 终态。
