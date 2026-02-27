import axios from 'axios'

const API_BASE_URL = '/api/v1'

export interface Chapter {
  id: string
  tenant_id: string
  project_id: string
  novel_id: string
  chapter_no: number
  language_code: string
  title?: string
  markdown_text: string
}

export interface AIExpandRequest {
  tenant_id: string
  project_id: string
  instruction: string
  style_hint: string
  target_language?: string
  max_tokens?: number
}

export interface AIExpandResponse {
  chapter_id: string
  original_length: number
  expanded_length: number
  expanded_markdown: string
  appended_excerpt: string
  provider_used: string
  model_name: string
  mode: string
  prompt_tokens_estimate: number
  completion_tokens_estimate: number
}

export interface ChapterUpdateRequest {
  title?: string
  language_code?: string
  markdown_text: string
  revision_note?: string
}

/**
 * 获取章节详情
 */
export async function getChapter(novelId: string, chapterId: string): Promise<Chapter> {
  const response = await axios.get(
    `${API_BASE_URL}/novels/${novelId}/chapters/${chapterId}`
  )
  return response.data
}

/**
 * 更新章节内容
 */
export async function updateChapter(
  novelId: string,
  chapterId: string,
  data: ChapterUpdateRequest
): Promise<Chapter> {
  const response = await axios.put(
    `${API_BASE_URL}/novels/${novelId}/chapters/${chapterId}`,
    data
  )
  return response.data
}

/**
 * AI智能扩展章节剧情
 * 一键生成扩展建议
 */
export async function aiExpandChapter(
  chapterId: string,
  data: AIExpandRequest
): Promise<AIExpandResponse> {
  const response = await axios.post(
    `${API_BASE_URL}/chapters/${chapterId}/ai-expand`,
    data,
    {
      headers: {
        'Content-Type': 'application/json',
      },
    }
  )
  return response.data
}

/**
 * 获取章节发布状态
 */
export async function getChapterPublishStatus(chapterId: string): Promise<any> {
  const response = await axios.get(
    `${API_BASE_URL}/chapters/${chapterId}/publish-status`
  )
  return response.data
}

/**
 * 提交章节发布审批
 */
export async function submitChapterForApproval(
  chapterId: string,
  data: {
    tenant_id: string
    project_id: string
    action: 'submit' | 'approve' | 'reject'
    rejection_reason?: string
  }
): Promise<any> {
  const response = await axios.post(
    `${API_BASE_URL}/chapters/${chapterId}/publish-approval`,
    data
  )
  return response.data
}

/**
 * 获取章节版本对比
 */
export async function getChapterDiff(
  chapterId: string,
  fromVersion?: string,
  toVersion?: string
): Promise<any> {
  const response = await axios.get(
    `${API_BASE_URL}/chapters/${chapterId}/diff`,
    {
      params: {
        from_version: fromVersion || 'latest',
        to_version: toVersion || 'current',
      },
    }
  )
  return response.data
}

/**
 * 获取章节修订历史
 */
export async function getChapterRevisions(chapterId: string): Promise<any[]> {
  const response = await axios.get(
    `${API_BASE_URL}/chapters/${chapterId}/revisions`
  )
  return response.data
}

export default {
  getChapter,
  updateChapter,
  aiExpandChapter,
  getChapterPublishStatus,
  submitChapterForApproval,
  getChapterDiff,
  getChapterRevisions,
}
