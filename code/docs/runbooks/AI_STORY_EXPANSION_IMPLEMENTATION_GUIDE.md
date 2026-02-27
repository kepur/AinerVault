# AI Story Expansion Assistant 实现指南

**文档日期**: 2026-02-28
**SKILL**: SKILL_31 AI Story Expansion Assistant
**状态**: 完成实现

---

## 目录
1. [功能概述](#功能概述)
2. [系统架构](#系统架构)
3. [后端实现](#后端实现)
4. [前端实现](#前端实现)
5. [API文档](#api文档)
6. [使用指南](#使用指南)
7. [配置说明](#配置说明)
8. [故障排查](#故障排查)

---

## 功能概述

### 核心功能
AI Story Expansion Assistant 提供了一键AI智能扩展剧情的功能，用户可以在章节编辑器中：

1. **快速选择模型** - 右上角下拉菜单选择LLM模型（GPT-4, Claude等）
2. **选择扩展模式** - 扩写/补全/改写/润色
3. **一键生成建议** - 点击"AI助手"按钮自动补全
4. **实时预览** - 右侧面板实时展示建议内容
5. **灵活接受** - 接受/修改/拒绝AI建议

### 应用场景
- **快速扩写**: 作者写了框架情节，AI自动丰富细节
- **情节补全**: AI识别不完整的地方，自动填充逻辑
- **文风改写**: AI改变语气或调整表现方式
- **文笔润色**: AI改进措辞和节奏

---

## 系统架构

### 组件图
```
┌─────────────────────────────────────────────────────┐
│          StudioChapterEditorPage.vue                │
│          (Vue3 编辑器组件)                           │
├─────────────────────────────────────────────────────┤
│  [模型选择] [扩展模式] [AI助手]  [保存] [发布]    │
├──────────────────┬──────────────────────────────────┤
│ Markdown编辑区   │  实时预览 + AI建议面板          │
│ (左侧)           │  (右侧)                         │
└──────────────────┴──────────────────────────────────┘
         │                      │
         └──────────┬───────────┘
                    │
              章节API客户端
              (chapter.ts)
                    │
         ┌──────────┴───────────┐
         │                      │
    POST /chapters/{id}    POST /chapters/{id}/ai-expand
    (保存章节)              (AI扩展)
         │                      │
         └──────────┬───────────┘
                    │
         ┌──────────▼───────────┐
         │   FastAPI后端        │
         │  (novels.py)         │
         ├──────────────────────┤
         │ - updateChapter()    │
         │ - aiExpandChapter()  │
         │ - getChapter()       │
         └──────────┬───────────┘
                    │
         ┌──────────▼───────────┐
         │   LLM服务调用        │
         │  (OpenAI/Claude等)   │
         └──────────────────────┘
```

### 数据流
```
用户编辑
   ↓
选中文本
   ↓
点击AI助手
   ↓
填写参数(模式、风格、指令等)
   ↓
点击"生成"
   ↓
后端调用_build_expansion_prompt()构建提示词
   ↓
后端调用_simulate_llm_expansion()或真实LLM API
   ↓
返回扩展内容
   ↓
前端展示在AI建议面板
   ↓
用户选择接受/修改/拒绝
```

---

## 后端实现

### 1. API 端点实现

**文件**: `code/apps/ainern2d-studio-api/app/api/v1/novels.py`

#### 端点定义
```python
@router.post("/chapters/{chapter_id}/ai-expand",
             response_model=ChapterAssistExpandResponse,
             status_code=202)
def ai_expand_chapter_content(
    chapter_id: str,
    body: ChapterAssistExpandRequest,
    db: Session = Depends(get_db),
) -> ChapterAssistExpandResponse:
```

#### 请求模型
```python
class ChapterAssistExpandRequest(BaseModel):
    tenant_id: str                      # 租户ID
    project_id: str                     # 项目ID
    instruction: str                    # 扩展指令
    style_hint: str                     # 风格指引
    target_language: str | None = None  # 目标语言
    max_tokens: int = 900               # 最大token数
```

#### 响应模型
```python
class ChapterAssistExpandResponse(BaseModel):
    chapter_id: str                     # 章节ID
    original_length: int                # 原始文本长度
    expanded_length: int                # 扩展后长度
    expanded_markdown: str              # 扩展内容
    appended_excerpt: str               # 新增部分摘录
    provider_used: str                  # 使用的提供商
    model_name: str                     # 模型名称
    mode: str                           # 扩展模式
    prompt_tokens_estimate: int         # 估计的提示词token数
    completion_tokens_estimate: int     # 估计的补全token数
```

### 2. 核心函数

#### `_build_expansion_prompt()`
构建AI扩展提示词

```python
def _build_expansion_prompt(
    original_text: str,
    instruction: str,
    style_hint: str,
    target_language: str = "zh",
) -> str:
    """构建AI扩展提示词"""
    return f"""你是一位专业的网络小说编剧助手。
当前任务：{instruction}
原始文本：
```
{original_text}
```
写作风格指引：{style_hint}
要求：
1. 保持原有故事主线和人物设定
2. 增加细节描写、心理活动、对话等元素
3. 提升情节节奏和阅读体验
4. 保持一致的叙事风格
5. 只输出扩展后的完整文本，不要包含任何解释或标记
输出语言：{target_language}
"""
```

#### `_simulate_llm_expansion()`
模拟LLM调用（实际部署时应替换为真实API）

```python
def _simulate_llm_expansion(
    original_text: str,
    prompt: str,
    max_tokens: int = 900
) -> str:
    """模拟LLM调用返回扩展文本"""
    # 实际实现应调用OpenAI、Claude等真实LLM API
    # 当前为演示实现
```

### 3. 事件追踪
```python
# 创建WorkflowEvent记录
event = WorkflowEvent(
    event_type="chapter.ai_expansion",
    payload_json={
        "chapter_id": chapter_id,
        "instruction": body.instruction,
        "model": model_name,
        "original_length": len(original_text),
        "expanded_length": len(expanded_text),
        ...
    },
)

# Telegram通知
notify_telegram_event(
    event_type="chapter.ai_expansion",
    summary=f"AI扩展章节 {chapter.title}",
)
```

---

## 前端实现

### 1. Vue3 章节编辑器组件

**文件**: `code/apps/ainern2d-studio-web/src/pages/StudioChapterEditorPage.vue`

#### 组件结构
```vue
<template>
  <div class="chapter-editor-container">
    <!-- 顶部工具栏 -->
    <div class="editor-header">
      <!-- 模型选择 + 扩展模式 + AI助手按钮 -->
    </div>

    <!-- 编辑区：左编辑右预览 -->
    <div class="editor-content">
      <!-- 左侧：Markdown编辑器 -->
      <div class="editor-pane">
        <textarea class="markdown-editor"></textarea>
      </div>

      <!-- 右侧：实时预览 + AI建议 -->
      <div class="preview-pane">
        <div class="preview-content"></div>
        <div class="ai-suggestion-panel"></div>
      </div>
    </div>

    <!-- AI助手对话框 -->
    <div class="modal-overlay" v-if="showAIDialog">
      <div class="modal-content">
        <!-- 扩展模式、风格、指令、token配置 -->
      </div>
    </div>
  </div>
</template>
```

#### 关键方法

**`openAIAssistantDialog()`** - 打开AI助手对话框
```typescript
const openAIAssistantDialog = () => {
  if (!selectedText.value) {
    alert('请先在编辑区选中要扩展的文本')
    return
  }
  showAIDialog.value = true
}
```

**`generateAIExpansion()`** - 生成AI扩展建议
```typescript
const generateAIExpansion = async () => {
  isGenerating.value = true
  try {
    const response = await fetch(
      `/api/v1/chapters/${route.params.chapterId}/ai-expand`,
      {
        method: 'POST',
        body: JSON.stringify({
          tenant_id: 'default-tenant',
          project_id: 'default-project',
          instruction: customInstruction.value || getDefaultInstruction(expandMode.value),
          style_hint: styleGuidance.value,
          max_tokens: maxTokens.value,
        }),
      }
    )
    const data = await response.json()
    aiSuggestion.value = data.expanded_markdown
  } finally {
    isGenerating.value = false
  }
}
```

**`acceptAISuggestion()`** - 接受AI建议
```typescript
const acceptAISuggestion = () => {
  if (aiSuggestion.value) {
    const textarea = document.querySelector('.markdown-editor')
    const start = textarea.selectionStart
    const before = markdownText.value.substring(0, start)
    const after = markdownText.value.substring(textarea.selectionEnd)
    markdownText.value = before + aiSuggestion.value + after
    aiSuggestion.value = null
  }
}
```

### 2. TypeScript API 客户端

**文件**: `code/apps/ainern2d-studio-web/src/api/chapter.ts`

```typescript
export async function aiExpandChapter(
  chapterId: string,
  data: AIExpandRequest
): Promise<AIExpandResponse> {
  const response = await axios.post(
    `${API_BASE_URL}/chapters/${chapterId}/ai-expand`,
    data
  )
  return response.data
}
```

---

## API文档

### POST /chapters/{chapter_id}/ai-expand

**功能**: 一键AI智能扩展章节剧情

**请求**:
```json
POST /api/v1/chapters/ch_12345/ai-expand

{
  "tenant_id": "tenant_1",
  "project_id": "proj_1",
  "instruction": "扩写这段剧情，增强冲突和情绪转折",
  "style_hint": "影视化叙事，保留可分镜细节",
  "target_language": "zh",
  "max_tokens": 900
}
```

**响应** (202 Accepted):
```json
{
  "chapter_id": "ch_12345",
  "original_length": 500,
  "expanded_length": 1200,
  "expanded_markdown": "扩展后的完整文本...",
  "appended_excerpt": "新增部分摘录...",
  "provider_used": "openai",
  "model_name": "gpt-4",
  "mode": "expand",
  "prompt_tokens_estimate": 250,
  "completion_tokens_estimate": 300
}
```

**状态码**:
- `202 Accepted` - 扩展请求已接受，正在处理
- `400 Bad Request` - 请求参数错误
- `403 Forbidden` - 权限不足
- `404 Not Found` - 章节不存在

**速率限制**:
- 每个用户每分钟最多 10 次请求
- 每个用户每小时最多 100 次请求
- 每个用户每日最多 1000 次请求

---

## 使用指南

### 用户操作步骤

#### 1. 打开章节编辑器
- 在小说列表中选择小说
- 选择要编辑的章节
- 点击"编辑"进入编辑器

#### 2. 准备文本
- 在左侧Markdown编辑区编写或粘贴故事内容
- 实时预览显示在右侧

#### 3. 选中要扩展的文本
- 在编辑区鼠标选中需要扩展的文本段落
- 可以选中任意长度的文本（建议 50-500 字）

#### 4. 打开AI助手
- 在右上角选择LLM模型（GPT-4 推荐）
- 选择扩展模式：
  - **扩写**: 增加场景描写、对话和细节
  - **补全**: 填补不完整的情节
  - **改写**: 改变语气或风格
  - **润色**: 改进文笔和措辞
- 点击"💡 AI助手"按钮

#### 5. 配置AI参数
在弹出的对话框中：
- **扩展模式**: 选择或确认模式
- **风格指引** (可选): 例如"武侠风格"、"细腻深情"等
- **自定义指令** (可选): 更具体的要求
- **输出长度**: 使用滑块调整 token 数量（200-2500）
- 点击"生成建议"

#### 6. 预览和选择
- 等待AI生成建议（通常 5-30 秒）
- 在右侧预览面板查看扩展建议
- 点击"接受"使用建议、"修改"细化、或"拒绝"放弃

#### 7. 保存章节
- 点击右上角"保存"保存编辑
- 点击"发布"提交审批

### 最佳实践

1. **选择合适的文本长度** - 建议 50-300 字的段落
2. **明确的风格指引** - 给AI更多上下文信息
3. **迭代优化** - 不满意可以再次调用AI
4. **保留原意** - AI的建议应该与原文保持一致
5. **人工审核** - 总是检查AI建议是否合适

---

## 配置说明

### 环境变量配置

在 `.env` 文件中配置：

```env
# LLM API 配置
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.openai.com/v1

# 或 Claude
ANTHROPIC_API_KEY=sk-ant-xxx

# 或其他 LLM 提供商
LLM_PROVIDER=openai  # openai|anthropic|custom
LLM_MODEL=gpt-4

# 成本配置
AI_EXPANSION_COST_PER_1K_TOKENS=0.03
AI_EXPANSION_MAX_DAILY_COST=100.0

# 限流配置
AI_EXPANSION_RATE_LIMIT_PER_MINUTE=10
AI_EXPANSION_RATE_LIMIT_PER_HOUR=100
AI_EXPANSION_RATE_LIMIT_PER_DAY=1000
```

### 模型配置

在后端配置默认模型：

```python
# 从数据库查询
provider = db.query(ModelProvider).filter(
    ModelProvider.is_default == True
).first()

# 或硬编码配置
DEFAULT_MODEL = {
    'name': 'gpt-4',
    'provider': 'openai',
    'temperature': 0.7,
    'max_tokens': 2500,
}
```

---

## 故障排查

### 问题 1: "请先选中要扩展的文本"

**原因**: 用户没有在编辑区选中文本

**解决**:
1. 在左侧编辑区用鼠标选中需要扩展的文本
2. 确保至少选中 1 个字符
3. 再次点击"AI助手"按钮

### 问题 2: "AI生成失败"

**原因**: API 调用失败或超时

**排查步骤**:
1. 检查网络连接
2. 确认 API Key 配置正确
3. 查看浏览器控制台的错误信息
4. 检查后端日志：`docker logs studio-api`

**常见原因**:
- `401 Unauthorized` - API Key 不正确
- `429 Too Many Requests` - 超过频率限制
- `503 Service Unavailable` - LLM 服务不可用
- 超时 - 请求耗时过长

### 问题 3: 生成的文本质量不好

**解决方案**:
1. **优化提示词**:
   - 提供更详细的风格指引
   - 给出具体的例子
   - 明确说明不要做什么

2. **调整参数**:
   - 增加 max_tokens (更长的输出)
   - 降低温度值 (更一致的输出)
   - 选择更强大的模型 (GPT-4 vs GPT-3.5)

3. **分段扩展**:
   - 把长文本分成多段
   - 分别扩展每段
   - 手动合并结果

### 问题 4: 扩展内容与原文不一致

**排查**:
1. 检查 context_before 和 context_after 是否正确
2. 确保 style_hint 清晰明确
3. 查看生成的提示词是否包含足够的上下文
4. 尝试修改指令，给AI更多约束

### 问题 5: 性能问题 - 编辑器卡顿

**解决**:
1. **减小编辑文本大小** - 分割成多个章节
2. **关闭实时预览** - 只在需要时刷新
3. **使用轻量级编辑器** - CodeMirror 而不是 Monaco
4. **浏览器优化** - 清理缓存，更新浏览器

---

## 性能指标

### 期望的响应时间
- API 调用: 200-500 ms
- LLM 生成: 5-30 秒 (取决于长度和模型)
- 前端渲染: < 100 ms

### 成本估算
假设 GPT-4 定价（每 1M tokens $30）:
- 短文本扩展（200 tokens）: ~$0.01
- 中文本扩展（500 tokens）: ~$0.02
- 长文本扩展（1000 tokens）: ~$0.03

---

## 后续增强计划

### Phase 2 (P1)
- [ ] 支持流式传输（实时显示生成过程）
- [ ] 多轮对话优化（基于反馈的迭代）
- [ ] 模型对比（同时调用多个模型）
- [ ] 缓存优化（避免重复调用）

### Phase 3 (P2)
- [ ] AI创意评分（自动评估内容质量）
- [ ] 故事连贯性检查（检测逻辑一致性）
- [ ] 角色性格验证（确保人物一致）
- [ ] 批量扩展（一次处理多个段落）

### Phase 4 (P3)
- [ ] 自定义提示词模板编辑
- [ ] 风格库（预定义的写作风格）
- [ ] 写作建议（主动识别改进机会）
- [ ] 实时协作（多人编辑时的AI同步）

---

## 支持与反馈

### 获取帮助
- 文档: [SKILL_31_AI_STORY_EXPANSION_ASSISTANT.md](../SKILL_31_AI_STORY_EXPANSION_ASSISTANT.md)
- 代码: `code/apps/ainern2d-studio-api/app/api/v1/novels.py`
- 前端: `code/apps/ainern2d-studio-web/src/pages/StudioChapterEditorPage.vue`

### 反馈与建议
- 提交 Issue: GitHub Issues
- 讨论功能: Discussions
- 报告 Bug: Bug Report Template

---

**文档版本**: 1.0
**最后更新**: 2026-02-28
**维护者**: AI Studio Team
