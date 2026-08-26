# AinerN2D_RunCenter_V3_Observable_DAG_MultiTrack_skill.md

> 目标：把当前「Run 运行中心」从“提交 JSON 的壳”升级为 **可观测的 AI 调度控制台**（类似 Airflow/LangSmith/Temporal Dashboard），并且支持**可扩展轨道/工种**（不止 TTS/BGM/SFX/Video 等固定几条），适配未来不断新增的模型与产物类型。  
> 本文定义：做什么 / 输入输出 / 状态变化 / 失败处理 / UI 信息架构 / 数据记录标准。

---

## 0. 总体原则（必须遵守）

1. **Run = 一次可追踪的 DAG 执行**  
   - Run 不是“一个按钮触发”或“一个队列任务”，必须包含多个 stage 与 node 的执行轨迹。
2. **所有 LLM/模型调用必须可观测**  
   - 每次调用记录：prompt、上下文、模型、输入输出摘要、token、耗时、重试、错误。
3. **轨道/工种必须可扩展（多轨并行）**  
   - 不假设固定轨道，任何新资产类型都可注册为 TrackType。
4. **幂等 + 可恢复**  
   - 任一 stage/node 失败后可重试；重试可视化；同输入多次执行可复用缓存产物。
5. **UI 必须一眼看懂**  
   - 跑了什么、跑到哪、还剩啥、花了多少、失败在哪、下一步是什么。

---

## 1. RunCenter V3 信息架构（UI）

### 1.1 顶部 Run Header（固定）
展示：
- Run ID（可复制）
- Project / Novel / Chapter / Scene Range（可跳转）
- Source Language / Target Language
- Culture Pack（auto / hybrid）
- Persona Ref / Director Profile
- Status（queued/running/success/failed/canceled/paused）
- Stage（当前阶段）
- Progress（总体百分比）
- Cost（tokens、模型费用估算、GPU 时间）
- Started/Updated/Finished 时间

交互：
- Pause / Resume / Cancel
- Retry Failed（run-level）
- Export Run Report（markdown/json）

### 1.2 中部 DAG 可视化（强制）
支持两种视图切换：
1) **Pipeline Timeline（线性阶段视图）**
2) **Graph DAG（节点拓扑视图）**

节点展示：
- node_name / node_type
- status
- model/provider
- token_used / time_used
- output_count
- error_flag

节点点击后：右侧打开 Node Details。

### 1.3 右侧 Node Details（强制）
Tab：
- **Inputs**：输入来源（chapter/script/world_model/translation/previous assets）
- **Prompt / Context**：prompt 摘要 + 展开全文
- **Model Call**：provider/model/params/seed/temperature
- **Outputs**：asset_id/uri/preview
- **Logs**：逐行日志、重试、异常栈
- **Cost**：token、latency、retry/backoff

### 1.4 底部 Multi-Track Asset Panel（建议）
按 Track 分组展示：
- Track Type（动态）
- Track Instances（例如 Dialogue/BGM/SFX/Narration/Subtitle/CameraPath）
- 每个 Track clip 列表（time range / source / status / locked）
- NLE 装配映射状态（assembled / partial / missing）

> 该面板是 Run 产物可视化，不替代 NLE 编辑器。

---

## 2. 多轨扩展：Track Registry（核心机制）

### 2.1 TrackType（可配置/可插拔）
字段：
- key（唯一）
- display_name
- asset_kind（audio/video/image/text/metadata）
- default_renderer
- requires_timeline（bool）
- supports_lock（bool）
- supports_regen（bool）
- depends_on（依赖 TrackType 或 Stage）

### 2.2 TrackInstance（同类型可多条）
字段：
- id
- run_id
- track_type_key
- label
- meta_json

### 2.3 Clip（轨道最小单元）
字段：
- id
- run_id
- track_instance_id
- start_ms / end_ms（可空）
- content_ref（text/span/shot_id/asset_id）
- status（planned/generated/failed/locked/replaced）
- locked_asset_id
- latest_asset_id
- regen_count / last_error

---

## 3. 执行模型：Run = Stage + Node DAG

### 3.1 Stage 标准命名
- ingest
- script_convert
- world_model_extract
- entity_mapping
- translation
- continuity_align
- shot_plan
- prompt_build
- asset_gen_*（按 Track 分支）
- composer
- export

### 3.2 Node（可并行，必须持久化）
字段：
- node_id, run_id
- stage_name
- node_name
- node_type（llm_call/model_call/io/transform/compose）
- status（queued/running/success/failed/skipped/canceled）
- attempt_count / max_attempts
- started_at / finished_at
- input_hash
- output_refs
- error_code / error_message

---

## 4. 可观测性：LLM/Model Call Logging 标准（强制）

### 4.1 RunEvent 事件类型
- llm.request
- llm.response
- model.request
- model.response
- retry
- error
- progress

payload 必备字段：
- provider/model
- params（temperature/seed/top_p 等）
- prompt（摘要 + 可选全文）
- context（rag/culture/persona 注入摘要）
- token_in/token_out（或估算）
- latency_ms
- http_status / error_stack

### 4.2 UI 展示规则
- 默认显示摘要（前 200 字 + hash）
- 支持展开全文、复制 prompt
- 支持“一键复跑该节点（同输入）”

---

## 5. 缓存与复用（省 token）

### 5.1 Cache Key
- chapter_id + stage_name + node_name
- input_hash（文本 + culture + persona + 参数 + mapping version）
- model/provider 版本

### 5.2 复用策略
- cache hit：节点状态显示 `success(cached)`
- UI 显示缓存来源 run_id
- 支持 `force_rerun`

---

## 6. V3 必须覆盖的问题修复

### 6.1 “重新抽离不可点击”
- 前端禁用态必须展示 tooltip 原因。
- 后端返回统一 `disabled_reason` 枚举：
  - provider_not_configured
  - chapter_not_selected
  - dependency_not_ready
  - run_in_progress

### 6.2 Translation 失败任务删除/批量删除
- 列表支持：单条删除、批量删除、仅失败过滤、一键清理失败。
- 若被下游 run 引用：阻止硬删或改 soft-delete 并提示。

### 6.3 翻译输入来自结构化剧本
翻译对象应来自 script blocks：
- scene_title/time/location/weather/mood
- narration
- dialogue（speaker）
- action
- 可选 sfx/bgm hint

支持策略：
- Strategy A：script_convert → translate → world_model_extract
- Strategy B：world_model_extract(源语言) → entity_mapping/localize → translate

Run/UI 可选择策略（默认可配置）。

### 6.4 “翻译后对白/场景没了”
- 保持 block 结构不变（title/narration/dialogue/action/meta）。
- 只翻译可翻译块，block_id 不变。
- 回填到同 scene/shot 的对应块。
- 块丢失时写 warning 并进入人工修复队列。

---

## 7. Run 与 Translation 衔接（转译后可直接跑素材）

### 7.1 推荐主流程
1) Chapter 选择
2) Script Convert
3) World Model Extract
4) Entity Mapping + Localization
5) Translation（带 mapping）
6) Shot Plan
7) Prompt Build（按 Track）
8) Asset Gen（多轨并行）
9) Composer（时间线装配）

### 7.2 Run 创建输入（版本选择）
Run 创建时必须允许选择：
- script_convert version
- world_model version
- entity_mapping version
- translation_project（或 target_language + packs）

避免每次重复调用上游。

---

## 8. API（I/O 约束）

### 8.1 POST /runs
Input:
- project_id, chapter_id
- source_language, target_language
- culture_pack_mode + selected_packs[]
- persona_ref
- requested_quality
- inputs: {script_version, world_model_version, mapping_version, translation_project_id}
- flags: {force_rerun, use_cache, dry_run}

Output:
- run_id
- dag_summary（节点列表 + 初始状态）

### 8.2 GET /runs/{run_id}
Output:
- run header
- stages summary
- dag nodes
- cost summary
- last_events

### 8.3 GET /runs/{run_id}/nodes/{node_id}
Output:
- inputs/outputs
- logs/events
- prompt/context（可脱敏）

### 8.4 Tracks
- GET /runs/{run_id}/tracks
- GET /runs/{run_id}/tracks/{track_instance_id}/clips

---

## 9. 失败处理

### 9.1 分级
- warning（不阻断）
- failed（阻断）
- degraded（继续执行但有质量风险）

### 9.2 自动重试
- 可配置最大重试次数 + 指数退避。
- 每次重试写 RunEvent 并在 UI 展示。

### 9.3 人工介入
- 节点状态 `needs_review`
- 允许 pause 在该节点
- UI 修改后 `Resume from node`

---

## 10. 验收标准

1. 任意 Run 展示完整 DAG 并实时更新。
2. 任一节点可查看模型调用摘要、token、耗时、错误。
3. 新增 TrackType 不改 UI 主框架即可显示。
4. cache hit 可视化且支持强制重跑。
5. 翻译输入来自结构化 blocks，翻译后结构不丢失。
6. 支持失败任务删除/批量删除。
7. 不可点击态返回并展示 disabled_reason。

---

## 11. 实施任务拆分（建议顺序）

1) 数据层：run_stages / run_nodes / run_events / track_registry / track_instances / clips
2) 后端：DAG 执行器 + 事件日志器 + gate/ensure + cache 复用
3) 前端：Run Header + Timeline/DAG + Node Details + Logs
4) Track 面板：按 TrackType 动态渲染
5) 翻译输入改造：script blocks 翻译 + block_id 对齐
6) 工程列表增强：失败任务删除/批量删除 + 依赖保护

---

## 12. 与当前仓库的落地映射（P1/P2/P3）

### P1（先把“可观测”补齐，低风险）
- 后端扩展现有 run 能力：
  - 复用 `tasks.py` 的 run 查询入口，新增 `run_nodes`/`run_events` 查询接口。
  - 在现有 `/runs/{run_id}/dag` 基础上补节点粒度与 attempt/cost。
- 前端升级 `StudioRunCenterPage.vue`：
  - 顶部 Run Header + 中部 DAG + 右侧 Node Details。

### P2（多轨模型）
- 新增 TrackRegistry + TrackInstance + Clip 表与 API。
- 复用现有 timeline/artifacts，聚合到 Run 多轨面板。

### P3（转译-Run 一键衔接）
- 新增从 Translation 工程创建 Run 的入口：
  - 自动继承 target_language/culture/persona/映射版本。
- Gate/Ensure：缺失补齐、stale 增量重跑、cache hit 可视化。

---

## 13. 一句话结论

> RunCenter V3 不是“另一个表单页”，而是 **以 DAG 为核心、以多轨为扩展单元、以事件日志为可观测基线** 的 AI 生产调度台。  
> 只有把 Translation 与 ScriptDoc/WorldModel/Plans 以“版本锁定”方式并入 Run，才能实现“转译后立即开跑素材生成”且可复现、可回溯、可扩展。
