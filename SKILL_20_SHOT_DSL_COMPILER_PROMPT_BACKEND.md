# 20_SHOT_DSL_COMPILER_PROMPT_BACKEND.md
# Shot DSL Compiler & Prompt Backend Adapter（镜头DSL编译与多后端Prompt适配 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义从“结构化镜头语义（Shot DSL）”到“具体模型后端 Prompt/参数”的编译层：
- Shot DSL（中间导演语法）
- Prompt 编译（按模型后端）
- 参数映射（fps/时长/seed/negative prompt等）
- 多后端适配（Wan / Hunyuan / ComfyUI workflow）

这是把自然语言规划与具体模型执行解耦的关键层。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
实现：
1. 统一 Shot DSL 表达镜头意图与约束
2. 将 DSL 编译为不同后端的 prompt + 参数
3. 支持 persona / RAG / policy 注入
4. 输出可追溯的编译产物（compiler trace）
5. 为失败恢复与A/B提供稳定对照面

---

## 2. Inputs（输入）
### 2.1 必需输入
- `shot_dsl[]`（来自 09/10 输出或新增 DSL 生成模块）
- `creative_control_stack.json`（15）
- `shot_compute_budget_plan.json`（19）
- `resolved_persona_profile.json`（14，可选）
- `kb_version` / RAG snippets（11/12/10）

### 2.2 可选输入
- backend capability registry
- compiler templates（per backend）
- negative prompt policies
- feature_flags:
  - enable_backend_specific_compiler
  - enable_compiler_trace
  - enable_multi_candidate_compile

---

## 3. Outputs（输出）
- `compiled_prompt_bundle.json`
- `compiler_trace_report.json`

### 3.1 每个 shot 编译产物（建议）
- backend_target
- positive_prompt
- negative_prompt
- parameters（fps/resolution/duration/seed/...）
- constraints_applied
- persona_influences
- rag_sources_used（引用ID）
- compile_warnings

---

## 4. Shot DSL（建议结构）
建议 DSL 关注“意图”而非模型细节：
- shot_intent
- shot_type
- camera（framing / angle / movement）
- subject_action
- timing_anchor（音频事件对齐）
- visual_constraints（空间轴/接触可读性/文化约束）
- style_targets（情绪、材质、光感）
- fallback_class（失败时可降级类别）

---

## 5. Branching Logic（分支流程与判断）

### [SD1] Validate DSL（校验 DSL）
#### Actions
1. 校验 DSL 字段完整性
2. 校验 timing anchor 是否存在于 `audio_event_manifest`
3. 校验与 hard constraints 不冲突
#### Output
- validated shot dsl

---

### [SD2] Enrich with Context（上下文增强）
#### Actions
1. 注入 persona style bias（14）
2. 注入 creative control constraints（15）
3. 注入 RAG snippets（10/11/12）
4. 注入 compute budget params（19）
#### Output
- enriched dsl context

---

### [SD3] Compile to Backend Prompt（编译到后端）
#### Actions
1. 根据 backend_target 选择 compiler template
2. 生成 positive / negative prompt
3. 映射参数（fps、duration、resolution、seed等）
4. 输出 compile trace（记录规则命中）
#### Output
- compiled prompt artifact

---

### [SD4] Multi-Candidate Compile（多候选编译，可选）
#### Trigger
探索层允许候选（15）
#### Actions
1. 生成多个 prompt 变体（控制变动字段）
2. 标记 candidate_id 与差异点
3. 输出给执行器或 17 做实验
#### Output
- multi-candidate compiled bundle

---

### [SD5] Export Traceability（追溯导出）
#### Actions
1. 记录使用的 persona/kb/policy/compiler template 版本
2. 记录注入的 rag chunk ids（引用）
3. 记录被裁剪/被忽略的约束
#### Output
- `compiler_trace_report.json`

---

## 6. Output Contract（示例）
```json
{
  "version": "1.0",
  "status": "compiled_ready",
  "shots": [
    {
      "shot_id": "S27",
      "backend_target": "wan_i2v",
      "candidate_id": "C1",
      "positive_prompt": "....",
      "negative_prompt": "....",
      "parameters": {
        "fps": 24,
        "duration_ms": 700,
        "resolution": "720p",
        "seed": 123456
      },
      "constraints_applied": ["hard:culture_signage_zh", "hard:timing_anchor_AE_102", "soft:persona_cut_density_high"],
      "persona_influences": ["director_xiaoli@1.2.0"],
      "rag_sources_used": ["CH_0012", "CH_0091"],
      "compile_warnings": []
    }
  ]
}
```

---

## 7. State Machine（状态机）
States:
- INIT
- VALIDATING_DSL
- ENRICHING_CONTEXT
- COMPILING
- BUILDING_CANDIDATES
- EXPORTING_TRACE
- COMPILED_READY
- FAILED

---

## 8. Definition of Done（完成标准）
- [ ] DSL 可校验并与时间锚点/硬约束对齐
- [ ] 支持 persona/RAG/policy/compute 注入
- [ ] 支持多后端 Prompt 编译
- [ ] 输出 compiler trace，保证可追溯
