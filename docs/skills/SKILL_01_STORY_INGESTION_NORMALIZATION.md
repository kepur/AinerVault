# 01_STORY_INGESTION_NORMALIZATION.md
# Story Ingestion & Normalization（故事输入与规范化 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 用于接收小说/文案/网页抓取内容/脚本草稿等原始输入，完成统一清洗、结构化切分、语言识别、编码与格式规范化，
输出可供后续模块（02/03/07等）稳定消费的标准化内容对象。

> 本模块是内容入口层，不负责实体抽取、文化绑定、素材匹配或渲染执行。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
将多来源原始文本统一转换为：
- 标准化文档对象（Document）
- 章节/段落/句子层级结构
- 语言与编码识别结果
- 元信息（来源、作者、时间、抓取上下文）
- 清洗日志（清洗了什么、丢弃了什么）
- 风险与警告（缺失标题、乱码、混合语言过重等）

输出供下游：
- `02_LANGUAGE_CONTEXT_ROUTER.md`
- `03_STORY_SCENE_SHOT_PLANNER.md`
- `07_ENTITY_CANONICALIZATION_CULTURAL_BINDING.md`（间接）

---

## 2. Scope（范围）
### 包含
- 输入来源适配（手动粘贴、上传文本、网页抓取结果、OCR结果）
- 编码/换行/空白/特殊字符规范化
- 标题/章节/段落切分
- 语言识别与混合语言检测
- 基础质量检查（过短、重复、乱码）
- 标准化输出契约（normalized_story.json）

### 不包含
- 深层语义总结
- 实体抽取与标签化
- 分镜规划
- 翻译生成（可只做语言检测和路由建议）
- 文化风格判断（由后续模块处理）

---

## 3. Inputs（输入）
### 3.1 必需输入
- `raw_input`
  - 文本内容 / 抓取结果 / 上游收集内容
- `input_source_type`
  - `manual_text` / `web_scrape` / `file_upload` / `ocr_text` / `api_payload`

### 3.2 可选输入
- `source_metadata`
  - URL、标题、作者、发布时间、站点名等
- `user_context`
  - 用户指定语言、题材、目标输出语言
- `ingestion_options`
  - 是否保留HTML标签（默认否）
  - 是否保留注释/脚注
  - 是否严格模式（遇错即停）
- `project_id` / `task_id`
- `feature_flags`
  - `enable_sentence_split`
  - `enable_mixed_language_detection`
  - `enable_quality_report`

---

## 4. Outputs（输出）
### 4.1 主输出文件
- `normalized_story.json`

### 4.2 必需字段
1. `status`
2. `document_meta`
3. `language_detection`
4. `structure`
5. `normalized_text`
6. `segments[]`
7. `quality_report`
8. `warnings[]`
9. `ingestion_log[]`

---

## 5. Branching Logic（分支流程与判断）

### [I1] Source Precheck（来源预检查）
#### Trigger
收到原始输入
#### Actions
1. 检查是否为空/极短
2. 检查来源类型是否合法
3. 若是抓取内容，尝试提取主体文本（剔除导航/广告样板）
4. 记录来源元信息
#### Output
- `precheck_status`
- `blocking_issues[]`

---

### [I2] Text Normalization（文本规范化）
#### Trigger
预检查通过
#### Actions
1. 编码统一为 UTF-8（逻辑层）
2. 统一换行符（CRLF -> LF）
3. 去除异常控制字符/零宽字符（按策略）
4. 规范化空白和段落间距
5. 可选：去除 HTML 标签、Markdown 噪声
#### Output
- `normalized_text`
- `ingestion_log[]`

---

### [I3] Structure Parsing（结构解析）
#### Trigger
文本已规范化
#### Actions
1. 识别标题（若存在）
2. 识别章节边界（Chapter/第X章/Scene等）
3. 识别段落与句子（可选）
4. 生成层级结构索引
#### Output
- `structure`
- `segments[]`

---

### [I4] Language Detection & Mixed-Language Check（语言识别）
#### Trigger
结构解析完成
#### Actions
1. 检测主语言（zh/en/ko/...）
2. 检测混合语言比例
3. 检测是否存在异常混杂（例如乱码、OCR碎片）
4. 输出语言路由建议（供 02 使用）
#### Output
- `language_detection`
- `warnings[]`

---

### [I5] Quality Report（质量报告）
#### Trigger
完成文本与结构处理
#### Actions
1. 检查重复段落/空段落
2. 检查文本长度是否满足后续规划需求
3. 检查章节是否过长（便于后续切分）
4. 输出质量分与建议
#### Output
- `quality_report`

---

## 6. Concurrency & Dependency（并发与依赖）
### 串行依赖（推荐）
1. Source Precheck
2. Text Normalization
3. Structure Parsing
4. Language Detection
5. Quality Report

### 可并行（可选）
- 在结构解析后，可并行做：
  - 语言检测
  - 重复段落检查
  - 长度统计

---

## 7. State Machine（状态机）
States:
- INIT
- PRECHECKING
- NORMALIZING
- PARSING_STRUCTURE
- DETECTING_LANGUAGE
- QUALITY_CHECKING
- READY_FOR_ROUTING
- REVIEW_REQUIRED
- FAILED

---

## 8. Output Contract（输出契约）
```json
{
  "version": "1.0",
  "status": "ready_for_routing",
  "document_meta": {
    "doc_id": "DOC_001",
    "source_type": "manual_text",
    "title": "示例标题",
    "project_id": "optional"
  },
  "language_detection": {
    "primary_language": "zh",
    "mixed_languages": [{"lang": "en", "ratio": 0.08}],
    "confidence": 0.94,
    "route_hint": "zh_primary_with_minor_en"
  },
  "structure": {
    "has_title": true,
    "chapter_count": 3,
    "paragraph_count": 46,
    "sentence_split_enabled": true
  },
  "normalized_text": "....",
  "segments": [],
  "quality_report": {
    "length_chars": 12540,
    "empty_paragraphs": 0,
    "duplicate_paragraphs": 1,
    "quality_score": 82
  },
  "warnings": [],
  "ingestion_log": []
}
```

---

## 9. Definition of Done（完成标准）
- [ ] 原始输入已完成规范化
- [ ] 已生成结构层级（至少段落级）
- [ ] 已完成语言识别与路由提示
- [ ] 已输出质量报告与警告
- [ ] 状态明确为 `READY_FOR_ROUTING` / `REVIEW_REQUIRED` / `FAILED`
