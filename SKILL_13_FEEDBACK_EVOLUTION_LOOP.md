# 13_FEEDBACK_EVOLUTION_LOOP.md
# Feedback → Proposal → Review → Release（反馈进化闭环 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义 “生成不满意 → 用户补充建议 → 自动抽象成可复用知识 → 进入审核 → 发布新版本 → RAG进化” 的闭环机制。

该模块连接：
- 运行结果（run / shot / prompt plan）
- 用户反馈（rating + issues + free text）
- 进化提案（proposal）
- 知识库管理（11）
- embedding pipeline（12）

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
实现两条路径：
1) **短期修补（Run-level Patch）**：仅影响当前任务/本次重试，不入库
2) **长期进化（KB Evolution）**：抽象为可复用规则/模板，进入知识库版本迭代

输出：
- feedback_event 记录
- improvement_proposal（可编辑草稿）
- 审核与合并记录
- 触发 kb release + embedding build
- 可追溯“某次生成使用了哪版知识库”

---

## 2. Inputs（输入）

### 2.1 必需输入
- `run_context`
  - run_id, task_id, kb_version_id, model info
- `shot_result_context`
  - shot_id/microshot_id, prompts used, assets used, render plan used
- `user_feedback`
  - rating (1-5)
  - issues[]（运镜/灯光/美术/动作/一致性/文化等）
  - free_text（用户补充建议）

### 2.2 可选输入
- `auto_diagnostics`
  - 系统检测到的失败原因（例如 motion mismatch, culture mismatch）
- `feature_flags`
  - enable_proposal_autogeneration
  - enable_role_auto_routing
  - enable_review_gate
  - enable_auto_tagging
- `user_preferences`
  - 是否允许把个人偏好写入项目共享库
- `kb_manager_config`（11）
- `embedding_pipeline_config`（12）

---

## 3. Outputs（输出）
### 3.1 主输出
- `feedback_event.json`
- `improvement_proposal.json`（可选：若进入长期进化）

### 3.2 必需字段
- feedback_event：run_id/shot_id/rating/issues/free_text
- proposal：suggested_role/tags/content/strength/status
- action_taken：run_patch / proposal_created / ignored / needs_review

---

## 4. Feedback Taxonomy（反馈分类体系｜建议）
issues 统一枚举（可扩展）：
- cinematography_camera_move（运镜/摄影）
- lighting_gaffer（灯光）
- art_style（美术风格）
- continuity_script_supervisor（连续性/场控）
- motion_readability（动作可读性）
- culture_mismatch（文化错位）
- character_inconsistency（角色不一致）
- prop_inconsistency（道具不一致）
- pacing_editing（剪辑节奏）
- prompt_quality（提示词质量）
- model_failure（模型失败）

---

## 5. Branching Logic（分支流程与判断）

### [F1] Capture Feedback（记录反馈）
#### Trigger
用户提交评分/原因/建议
#### Actions
1. 写入 feedback_event
2. 关联 run_id、kb_version_id、shot_id、prompts/assets/render plan
3. 若 rating >= 阈值：可只记录不触发进化
#### Output
- feedback_event.json

---

### [F2] Decide Patch vs Evolution（短期修补 vs 长期进化）
#### Decision Rules（建议）
- 若用户只想“马上重试”：走 Run-level Patch
- 若用户提供可复用建议 + 明确问题类型：进入 Proposal
- 若是单次偏好（个人审美）：默认 private proposal
- 若是系统性问题（多次出现/高频问题）：进入 project_shared proposal

#### Output
- action_taken

---

### [F3] Run-level Patch Builder（短期修补生成）
#### Trigger
action_taken = run_patch
#### Actions
1. 将用户 free_text 转为本次重试的 prompt patch（追加层/负面约束/参数调整）
2. 写入 run_patch_record（仅绑定 run_id）
3. 不改动知识库
#### Output
- run_patch_record

---

### [F4] Proposal Auto-generation（长期进化提案生成）
#### Trigger
action_taken = proposal_created 且 enable_proposal_autogeneration
#### Actions
1. 自动选择 role（或给候选列表）
   - 运镜问题 → cinematographer
   - 灯光问题 → gaffer
   - 美术问题 → art_director
   - 节奏问题 → editor
   - 连续性问题 → script_supervisor
2. 自动打 tags（culture_pack/genre/motion_level/shot_type）
3. 将 free_text + run_context 抽象为可复用 Knowledge Item 草稿：
   - title（短）
   - rule/checklist/template/anti_pattern
   - strength（hard/soft）
   - content（尽量通用）
4. 输出 proposal，状态 pending_review
#### Output
- improvement_proposal.json

---

### [F5] Review & Merge（审核与合并）
#### Trigger
proposal pending_review
#### Actions
1. 审核可复用性（是否只是一次性补丁）
2. 检查与现有 hard rules 冲突
3. 合并/编辑/拒绝
4. 通过则写入 KB（11）并标记 embedding stale
#### Output
- proposal_status 更新
- kb item 写入结果

---

### [F6] Release & Re-embed（发布与向量化）
#### Trigger
累计到一批 approved proposals 或用户手动发布
#### Actions
1. 生成 kb_release_manifest（11）
2. 触发 embedding pipeline（12）
3. 发布新 kb_version
4. 将新版本与旧 run 记录关联（供对比评测）
#### Output
- 新 kb_version_id
- index_build_report

---

### [F7] Regression Evaluation（回归评测，建议）
#### Trigger
新版本 index_ready
#### Actions
1. 选取历史失败样例（来自 feedback_event）
2. 重跑检索/提示词（可选）或小规模生成（可选）
3. 对比满意度/召回/冲突率
4. 若变差：建议回滚
#### Output
- evolution_report

---

## 6. State Machine（状态机）
States:
- INIT
- CAPTURING_FEEDBACK
- DECIDING_ACTION
- BUILDING_RUN_PATCH
- GENERATING_PROPOSAL
- REVIEWING_PROPOSAL
- APPLYING_TO_KB
- RELEASING_VERSION
- EMBEDDING_BUILDING
- EVALUATING_IMPROVEMENT
- COMPLETED
- FAILED

---

## 7. Output Contract（输出契约）

### 7.1 feedback_event.json（示例）
```json
{
  "version": "1.0",
  "feedback_event_id": "FB_0001",
  "run_id": "RUN_123",
  "kb_version_id": "KB_V1_20260226_001",
  "shot_id": "S27",
  "rating": 2,
  "issues": ["motion_readability", "cinematography_camera_move"],
  "free_text": "打斗段镜头切太慢，击打点需要更密微镜头，并提高动作可读性。",
  "created_at": "2026-02-26T00:00:00+08:00"
}
```

### 7.2 improvement_proposal.json（示例）
```json
{
  "version": "1.0",
  "proposal_id": "PR_0001",
  "feedback_event_id": "FB_0001",
  "suggested_role": "cinematographer",
  "suggested_strength": "hard_constraint",
  "suggested_tags": {
    "culture_pack": ["cn_wuxia"],
    "genre": ["wuxia"],
    "motion_level": ["HIGH_MOTION"],
    "shot_type": ["action"]
  },
  "suggested_content_type": "rule",
  "suggested_title": "高动作段优先微镜头拆分与击打点对齐",
  "suggested_knowledge_content": "当音频峰值/金属碰撞密集时，将动作镜头拆分为0.3~1.0s微镜头，优先对齐击打点，减少冗长环境描述，突出关键姿态与空间关系。",
  "status": "pending_review",
  "visibility": "project_shared"
}
```

---

## 8. Guardrails（防污染护栏）
- 反馈不直接写入 active 知识库，必须经过 proposal & review
- 支持 private vs shared 两种写入路径
- 强约束（hard_constraint）需要更严格审核
- 记录每次上线版本的差异与回滚点
- 对 deprecated 规则仍可检索用于解释，但默认不注入生成

---

## 9. Definition of Done（完成标准）
- [ ] 能记录 feedback_event 并关联 run/shot/kb_version
- [ ] 能区分 run_patch 与 proposal_evolution
- [ ] 能自动生成 proposal 草稿（可编辑）
- [ ] 能审核/合并到 KB，并触发发布与 embedding
- [ ] 能对新版本做基础回归评测并给出建议

---

## 10. 强制分流规则（P0）
- `Run-level Patch`：只作用当前 run，不进入知识库。
- `KB Evolution Proposal`：仅在可复用规则成立时进入评审。
- 禁止反馈直接写入 active 知识库。

## 11. 关键事件（P0/P1）
- `feedback.event.created`
- `proposal.created`
- `proposal.reviewed`
- `proposal.approved`
- `proposal.rejected`
- `kb.version.released`
- `kb.version.rolled_back`

## 12. 进化质量门禁（P1）
- 提案合并后必须触发 12 的评测。
- 未通过评测不得推广为 active 版本。
- 版本推广后若失败率升高，触发自动回滚建议。
