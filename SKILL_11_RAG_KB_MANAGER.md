# 11_RAG_KB_MANAGER.md
# RAG Knowledge Base Manager（智能体RAG知识库管理｜前端CMS Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义 AinerN2D 的“专业角色知识库（Role Packs）”管理系统能力：
- 前端管理（录入/编辑/检索预览/版本发布）
- 数据入库与权限
- 版本化与可追溯性
- 质量控制（审核、弃用、回滚）

该模块输出的是“知识库可用状态 + 版本 + 索引元数据”，供：
- `12_RAG_PIPELINE_EMBEDDING.md`（切片/向量化/索引）
- `10_PROMPT_PLANNER.md`（检索调用）
- `13_FEEDBACK_EVOLUTION_LOOP.md`（反馈进化写回）

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
让用户在前端像“CMS”一样管理知识资产：
- 可以添加/编辑/组织不同专业角色（导演/运镜/灯光/美术/场控等）的知识
- 支持结构化字段 + 文档内容（Markdown/PDF/网页粘贴）
- 支持标签化（culture_pack/genre/era/style_mode/shot_type/motion_level等）
- 支持强弱约束（hard/soft）
- 支持版本发布（KB Version）与回滚
- 支持检索预览（输入镜头描述 → 查看会召回哪些知识片段）

---

## 2. Concepts（核心概念）

### 2.1 Role Pack（角色知识包）
代表一个“专业人员视角”的知识集合，例如：
- director / editor / cinematographer / gaffer / art_director / script_supervisor / sound_designer / colorist

### 2.2 Knowledge Item（知识条目）
知识库中的最小管理单元：一条规则/清单/模板/案例/反例。

### 2.3 Knowledge Version（知识库版本）
把一批知识条目的“发布状态”固化，保证生成可追溯：
- 生成 Run 记录必须引用 kb_version_id

### 2.4 Status（状态）
- draft：草稿
- active：启用
- deprecated：弃用（仍可追溯）
- archived：归档（默认不检索）

---

## 3. Inputs（输入）

### 3.1 前端输入（用户操作）
- 新建/编辑 Knowledge Item
- 上传文档（PDF/DOC/MD/URL）
- 选择 Role / Tags / Strength
- 发布版本 / 回滚版本
- 检索预览请求（Query + Filters）

### 3.2 可选系统输入
- 项目默认 culture pack、默认 tags
- 用户权限（个人库/团队库/公共库）
- feature_flags：
  - enable_role_packs
  - enable_versioning
  - enable_review_workflow
  - enable_preview_search

---

## 4. Outputs（输出）

### 4.1 管理输出（API/UI）
- Knowledge Item 列表与详情
- Role Pack 概览（条目数、最近更新、embedding状态）
- KB Version 列表（发布历史、差异摘要）
- 检索预览结果（召回片段 + 分数 + 来源）

### 4.2 结构化输出（供下游）
- `kb_release_manifest.json`
  - 本次发布的版本信息、包含的条目范围、hash、embedding目标

---

## 5. UI Pages（前端页面建议｜最少集）
1) **Role Packs**
- 列出所有角色：导演/运镜/灯光/美术/场控…
- 显示：active条目数、draft条目数、当前发布版本、embedding状态

2) **Knowledge Items**
- 筛选：role/tags/status/strength
- 支持批量操作：启用/弃用/打标签/加入发布候选

3) **Item Editor**
- 左侧结构化字段（role/tags/strength/适用范围）
- 右侧内容编辑（Markdown）
- 上传附件/引用来源
- “生成切片预览”（可选）

4) **Preview Search**
- 输入：镜头描述/Prompt草稿
- 选择：role recipe + filters（culture_pack/genre/motion_level）
- 输出：召回片段列表、分数、来源条目、版本、可一键打开编辑

5) **Version & Release**
- 当前版本
- 发布候选清单
- 差异摘要（新增/修改/弃用）
- 一键发布、回滚

---

## 6. Data Contract（数据契约｜建议字段）

### 6.1 Knowledge Item（示例）
```json
{
  "knowledge_item_id": "KI_0001",
  "role": "cinematographer",
  "title": "高动作段微镜头切分规则",
  "content_type": "rule",
  "content_markdown": "...",
  "tags": {
    "culture_pack": ["cn_wuxia"],
    "genre": ["wuxia"],
    "motion_level": ["HIGH_MOTION"],
    "shot_type": ["action"]
  },
  "strength": "hard_constraint",
  "status": "active",
  "version": "1.0",
  "visibility": "project_shared",
  "source": {"type": "user_note", "ref": "manual"},
  "created_at": "2026-02-26T00:00:00+08:00",
  "updated_at": "2026-02-26T00:00:00+08:00"
}
```

### 6.2 KB Release Manifest（示例）
```json
{
  "kb_version_id": "KB_V1_20260226_001",
  "release_notes": "新增运镜与灯光规则若干，弃用旧版武侠客栈灯光条目",
  "included_items": ["KI_0001", "KI_0002"],
  "deprecated_items": ["KI_0009"],
  "target_embedding_model": "your_embedding_model_name",
  "chunking_policy_id": "CHUNK_POLICY_V1",
  "hash": "sha256:....",
  "created_at": "2026-02-26T00:00:00+08:00"
}
```

---

## 7. Branching Logic（分支流程与判断）

### [K1] Create / Edit Item（创建/编辑条目）
#### Trigger
用户保存条目
#### Actions
1. 校验 role/tags/strength/status
2. 保存 content 与元数据
3. 标记该条目 `embedding_status = stale`
4. 若启用审核流程：进入 pending_review
#### Output
- item 保存结果
- embedding 需要更新的提示

---

### [K2] Review Workflow（可选：审核）
#### Trigger
条目状态从 draft -> active 或 proposal -> active
#### Actions
1. 审核内容是否可复用（不是一次性补丁）
2. 检查是否与现有规则冲突
3. 通过：active；拒绝：draft/rejected；需要修改：needs_edit
#### Output
- review decision

---

### [K3] Publish Version（发布版本）
#### Trigger
用户点击发布
#### Actions
1. 生成 kb_version_id
2. 冻结本次发布的条目集合（included + deprecated）
3. 输出 `kb_release_manifest.json`
4. 触发 12 的 embedding pipeline
#### Output
- 发布成功 + 版本号
- embedding 任务队列

---

### [K4] Rollback Version（回滚版本）
#### Trigger
用户选择历史版本回滚
#### Actions
1. 切换 active version 指针
2. 标记新旧版本差异
3. 记录回滚原因与操作者
#### Output
- 当前版本已切换

---

### [K5] Preview Search（检索预览）
#### Trigger
用户输入 query + filters
#### Actions
1. 使用当前 kb_version 的索引检索
2. 返回 top-k chunks
3. 展示来源 item、role、tags、strength
4. 若存在 hard_constraint 冲突，提示冲突来源
#### Output
- preview results

---

## 8. State Machine（状态机）
States:
- INIT
- EDITING_ITEMS
- REVIEWING_ITEMS
- READY_TO_RELEASE
- RELEASING_VERSION
- EMBEDDING_IN_PROGRESS
- ACTIVE_VERSION_READY
- ROLLBACKING
- FAILED

---

## 9. Security & Permissions（权限建议）
- visibility: personal / project_shared / org_public
- 个人库默认不影响全局生成，除非用户选择“应用到项目”
- 发布版本需要更高权限（project admin）
- 记录操作审计（谁在何时改了什么）

---

## 10. Definition of Done（完成标准）
- [ ] 用户可新增/编辑/弃用条目
- [ ] 支持 role/tags/strength/status 管理
- [ ] 支持发布版本并生成 release manifest
- [ ] 支持检索预览与来源追溯
- [ ] 每次生成 run 可记录 kb_version_id

---

## 11. 工业闭环补充（P0）

### 11.1 必须输出字段
- `kb_version_id`
- `release_manifest_hash`
- `active_recipe_set_id`
- `approval_ticket_id`

### 11.2 关键事件
- `kb.item.created`
- `kb.item.updated`
- `kb.version.release.requested`
- `kb.version.released`
- `kb.version.rolled_back`

### 11.3 门禁规则
- 未通过审核的条目不得进入 `active`。
- `hard_constraint` 条目必须双人审核。
- 发布后必须触发 12 的 `rag.chunking.started`。

### 11.4 与 10 的衔接
- 发布后向 `10_PROMPT_PLANNER` 暴露：`kb_version_id + recipe_set`。
- Prompt 生成记录必须回写 `kb_version_id`，用于可追溯与回滚。
