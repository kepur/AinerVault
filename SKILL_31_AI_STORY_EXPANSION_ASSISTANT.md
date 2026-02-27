# 31_AI_STORY_EXPANSION_ASSISTANT.md
# AI Story Expansion Assistant（AI辅助编剧助手 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义 Studio 章节编辑器内的"AI辅助编剧"功能：
- 章节编辑器右上角快速选择LLM模型
- 一键调用LLM智能补全/扩展剧情
- 实时预览补全结果
- 支持多种扩展风格（扩写/补全/改写/润色）
- 可配置提示词模板和创意参数

---

## 1. Workflow Goal（目标）
1) 用户在编辑章节时，右上角显示模型选择器
2) 用户选择扩展模式（扩写/补全/改写/润色）
3) 用户点击"AI助手"按钮，触发异步扩展任务
4) 实时返回扩展建议，用户可预览、接受或修改
5) 支持多轮对话优化，直到满意为止

---

## 2. Integration Points（接入点）
- 25：选择模型档案与Provider
- 24：章节编辑上下文与元数据
- 01：故事规范化（扩展后内容入库）
- 28：可选：扩展后发起生成任务

---

## 3. Definition of Done
- [ ] 章节编辑器集成模型选择器
- [ ] 支持多种扩展模式（扩写/补全/改写/润色）
- [ ] 异步扩展API返回job_id和进度
- [ ] 支持实时预览和接受/拒绝

---

## 4. 对话补充需求索引（接力必读）
- 本 Skill 补充：AI 辅助编剧是创作流的关键入口，必须支持"一键AI补全"。
- 章节编辑器：左侧Markdown编辑区，右侧实时预览，右上角模型选择和AI助手入口。

---

## 5. API 规范

### 5.1 扩展模式定义
```
- expand: 扩写（增加详细描写和对话）
- complete: 补全（填补不完整的情节）
- rewrite: 改写（改变语气或风格）
- polish: 润色（改进文笔和措辞）
```

### 5.2 请求格式
```json
POST /chapters/{chapter_id}/ai-expand
{
  "tenant_id": "string",
  "project_id": "string",
  "model_profile_id": "string",
  "expand_mode": "expand|complete|rewrite|polish",
  "source_text": "string (要扩展的文本段落)",
  "context_before": "string (前文上下文，可选)",
  "context_after": "string (后文上下文，可选)",
  "style_guidance": "string (风格指引，可选)",
  "temperature": 0.7,
  "max_tokens": 1000
}
```

### 5.3 响应格式
```json
{
  "chapter_id": "string",
  "job_id": "string",
  "status": "initiated|processing|completed|failed",
  "original_text": "string",
  "expanded_text": "string (完成时返回)",
  "metadata": {
    "expand_mode": "string",
    "model_used": "string",
    "tokens_used": number,
    "cost_estimate": number
  }
}
```

---

## 6. 前端交互设计

### 6.1 章节编辑器布局
```
┌─────────────────────────────────────────────────────┐
│  < 返回  | 章节标题  [v] 删除                    │
├─────────────────────────────────────────────────────┤
│  [模型选择▼] [扩写▼] [AI助手💡] [发布]  [保存] │
├───────────────────┬─────────────────────────────────┤
│  Markdown编辑     │  实时预览                       │
│  (左侧)           │  (右侧)                         │
│                   │                                 │
│ # 标题            │ # 标题                          │
│ 内容写在这里      │ 内容展示在这里                  │
│                   │                                 │
│ xxx在哪里干什    │ xxx在哪里干什么事，他...       │
│ 么事              │                                 │
│                   │  [展开/折叠AI建议]             │
│                   │                                 │
└───────────────────┴─────────────────────────────────┘
```

### 6.2 交互流程
1. 用户在编辑区选中需要扩展的文本
2. 点击"AI助手"按钮
3. 弹出对话框：选择扩展模式、确认模型
4. 点击"生成"，显示加载状态
5. AI建议出现在右侧预览区，用户可：
   - 接受：替换原文本
   - 修改：进一步调整AI建议
   - 再试：重新生成
   - 拒绝：丢弃建议

---

## 7. 提示词模板

### 7.1 扩写模板
```
你是一位专业的小说编剧助手。
当前故事背景：{context}
用户的原始描写："{original_text}"
前文上下文：{context_before}
后文上下文：{context_after}

请扩写这段内容，添加更多细节描写、角色对话和场景描述，
使故事更生动有趣。保持原有风格和主题。

输出只返回扩写后的文本，不要包含任何解释。
```

### 7.2 补全模板
```
你是一位专业的小说编剧助手。
用户在编写故事时，有些情节不完整或有逻辑断裂。
原始文本："user_text"
前文上下文：{context_before}
后文上下文：{context_after}

请补全这段文本，填补情节空白，确保逻辑连贯和叙事完整。

输出只返回补全后的文本，不要包含任何解释。
```

---

## 8. 技术要点

### 8.1 流式传输（可选增强）
支持流式返回扩展内容，提升用户体验：
```
GET /chapters/{chapter_id}/ai-expand/{job_id}/stream
```

### 8.2 多轮优化
支持基于反馈的迭代优化：
```
POST /chapters/{chapter_id}/ai-expand/{job_id}/refine
{
  "feedback": "string",
  "adjustment": "make it more concise|add more emotion|change tone"
}
```

### 8.3 成本控制
- 每个扩展请求计费（基于token使用）
- 支持估算成本（dry-run模式）
- 用户可设置最大花费限制

---

## 9. 产品特性

### 9.1 智能预设
- 短篇补全 (max_tokens: 200)
- 中篇扩写 (max_tokens: 500)
- 长篇创作 (max_tokens: 1000)
- 自定义配置

### 9.2 风格指引预设
- 武侠风格：详写武器、武功、江湖人物
- 恐怖风格：营造气氛、细节渲染
- 浪漫风格：人物情感、细腻描写
- 科幻风格：设定解释、技术细节

### 9.3 批量操作
支持对多个段落批量扩展（提升创作效率）

---

## 10. 后续增强（P2/P3）
- [ ] 支持自定义提示词模板编辑
- [ ] 支持多模型对比（同时调用多个模型，展示对比结果）
- [ ] AI创意评分（评估扩展内容的创意度和质量）
- [ ] 故事连贯性检查（检测前后文逻辑一致性）
- [ ] 实时协作（多人编辑时的AI建议同步）
