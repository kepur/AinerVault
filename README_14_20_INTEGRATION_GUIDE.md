# README_14_20_INTEGRATION_GUIDE.md
# AinerN2D 14~20 工业级增强层接入说明（接入 01~13）

本说明告诉你：`14~20` 应该如何插入你现有 `01~13` Skill 流程，不是替代，而是增强。

---

## 一、你当前主链（已有）
- `01~03`：内容入口 → 路由 → 场景/镜头规划
- `04~06`：实体抽取 → 音频规划 → 音频时间线回填
- `07~10`：文化绑定 → 素材匹配 → 视觉渲染规划 → Prompt Planner
- `11~13`：RAG知识库管理 → 向量化管线 → 反馈进化闭环

---

## 二、14~20 属于“工业级增强层”，不是基础主链
你可以把它理解成四个横切层：

1. **风格人格层**：`14`
2. **控制治理层**：`15`, `18`, `19`
3. **质量评测/实验层**：`16`, `17`
4. **编译适配层**：`20`

---

## 三、推荐接入位置（最关键）

### A. Persona 风格人格层（14）
#### 接入点
- 在 `10_PROMPT_PLANNER` 之前加载（强烈建议）
- 也可在 `09_VISUAL_RENDER_PLANNER` 之前用于影响镜头负载与切分偏好

#### 作用
- 给 `10` 注入 `Style DNA + RAG Recipe Override`
- 给 `15` 注入 persona soft constraints
- 给 `17` 提供实验变量（人格A/B）

#### 最小接入方式（MVP）
- 先只在 `10_PROMPT_PLANNER` 使用：
  - `persona_id`
  - `style_dna`
  - `rag_recipe_override`

---

### B. 创作控制策略栈（15）
#### 接入点
- 依赖 `06`（音频最终时间线）和 `07`（文化约束）
- 输出给 `09`、`10`、`19`、`18`

#### 作用
- 把所有约束分层：
  - hard（时长/文化/预算）
  - soft（persona风格）
  - exploration（允许多候选）
- 防止系统越做越散

#### 推荐顺序
`06 + 07 + 14 -> 15 -> (19 -> 09 -> 10/20)`

---

### C. 镜头级算力预算器（19）
#### 接入点
- 放在 `09_VISUAL_RENDER_PLANNER` 前（推荐）
- 或作为 `09` 的子步骤（如果你先不拆模块）

#### 依赖
- `03 shot_plan`
- `06 audio_event_manifest`
- `15 creative_control_stack`

#### 输出给
- `09`（渲染规划）
- `18`（失败恢复降级策略）

#### 作用
- 将你目前“全局低/中/高档位”升级为每个 shot 的动态 fps / 分辨率 / 重试预算

---

### D. Shot DSL 编译层（20）
#### 接入点（最推荐）
- 放在 `10_PROMPT_PLANNER` 之后、执行器之前
- 或直接让 `10` 输出 Shot DSL，`20` 负责编译到各后端 prompt

#### 推荐结构
- `10`：输出更抽象的 Prompt/Shot Intent / DSL seed
- `20`：编译为 Wan/Hunyuan/ComfyUI 的具体 prompt + 参数

#### 好处
- 切换模型后端更稳
- A/B测试更干净（17）
- 故障定位更清晰（DSL问题 vs 编译问题 vs 模型问题）

---

### E. Critic 评测套件（16）
#### 接入点
- 放在生成结果之后（渲染后）
- 作为交付前质检关卡

#### 输出流向
- `18`：自动修复/降级/局部重试
- `13`：系统性问题写入反馈进化
- `17`：实验评分指标

#### 决策位置
你可以做一个“质量门（Quality Gate）”：
- pass -> 交付
- retry_partial -> 18
- manual_review -> 人工队列

---

### F. 失败恢复与降级策略（18）
#### 接入点
- 运行时异常时触发（任何阶段都可）
- 最关键是挂在 `09/10/20` 执行器与 `16` Critic 后

#### 输出
- 工业级状态：
  - success
  - success_with_degradation
  - partial_review_required
  - failed_blocking

#### 作用
- 防止“一处失败整片卡死”

---

### G. 实验与A/B编排（17）
#### 接入点
- 不属于单次主链运行，而是“系统优化后台”
- 可调用整条链的子集（通常从 `09/10/20` 到渲染再到 `16`）

#### 实验变量来源
- `14 Persona`
- `11/12 KB & RAG`
- `15 Policy`
- `19 Compute budget`
- `20 Compiler template`

#### 输出
- 推荐默认 persona/policy/recipe
- 按题材/动作强度的最佳配置

---

## 四、推荐的“升级后主链”（工业版）
建议你未来主链（逻辑顺序）如下：

1. `01` Story Ingestion
2. `02` Language Context Router
3. `03` Story→Scene→Shot Planner
4. `04` Entity Extraction
5. `05` Audio Asset Planner
6. `06` Audio Timeline Composer
7. `07` Entity Canonicalization + Cultural Binding
8. `08` Asset Matcher
9. `14` Persona Style Pack Resolve（新增）
10. `15` Creative Control Policy Build（新增）
11. `19` Compute-Aware Shot Budgeter（新增）
12. `09` Visual Render Planner（利用 15/19）
13. `10` Prompt Planner（利用 14/15 + RAG）
14. `20` Shot DSL Compiler / Backend Adapter（新增）
15. 执行渲染（执行器）
16. `16` Critic Evaluation Suite（新增）
17. `18` Failure Recovery & Degradation（新增，按需触发）
18. `13` Feedback Evolution Loop（长期进化）
19. `17` A/B Experiment Orchestrator（离线/后台优化）

---

## 五、最小接入方案（你现在就能做）
如果你不想一下子做太复杂，建议按这个顺序增量接入：

### Phase A（马上收益最大）
- `14` Persona（先只接 10）
- `15` Control Policy（先只做 hard/soft 分层）
- `19` Shot Budgeter（先只做 fps与优先级）
- `16` Critic（先做 2~3 个 critic）

### Phase B（工业稳定性）
- `18` Failure Recovery（做失败矩阵 + 降级状态）
- `20` Shot DSL Compiler（解耦后端）

### Phase C（系统优化飞轮）
- `17` A/B 实验编排（连接 16 打分）
- 与 `13` 反馈进化联动

---

## 六、版本追溯建议（非常重要）
从现在开始，run 记录建议至少携带这些版本号：
- `kb_version_id`（11/12）
- `persona_version`（14）
- `creative_policy_version`（15）
- `compute_budget_policy_version`（19）
- `compiler_template_version`（20）
- `prompt_recipe_version`（10）
- `critic_suite_version`（16）

这样你才能真正做工业级优化与回滚。

---

## 七、一句话总结
`14~20` 不是在你现有系统上“再堆功能”，而是在给你的 AinerN2D 增加：
- **可控风格（14）**
- **系统治理（15/18/19）**
- **可评测进化（16/17）**
- **可移植执行（20）**

这四层一加，你的系统就从“强大的生成流水线”升级成“工业级 AI 导演工厂”。
