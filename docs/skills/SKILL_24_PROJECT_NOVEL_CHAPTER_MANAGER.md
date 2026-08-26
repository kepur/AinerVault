# 24_PROJECT_NOVEL_CHAPTER_MANAGER.md
# Project / Novel / Chapter Manager（项目+小说+篇章管理 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义 Studio 侧“内容管理与创作入口”：
- 项目管理（Project）
- 小说管理（Novel）
- 篇章管理（Chapter）
- MD 编辑器（手写/修改）
- LLM 扩写/改写/翻译（调用 01~03）
- 基于篇章 + 目标语言/文化包/Persona 触发任务派发（调用 28）

---

## 1. Workflow Goal（目标）
1) 用户可创建项目并上传/粘贴小说内容
2) 可拆分为章节/篇章并编辑
3) 可选择“LLM扩写/补全/翻译”
4) 章级版本管理（draft/released）
5) 一键从某章节发起“生成任务”（到 28）

---

## 2. Inputs（输入）
- project meta（名称、题材、默认语言）
- novel content（原文、元信息）
- chapter content（markdown）
- target language / locale / culture pack（可选）
- persona selection（可选）
- user overrides（写作方向、风格）

---

## 3. Outputs（输出）
- Project / Novel / Chapter records
- Chapter revisions（历史版本）
- 标准化输入对象（供 01）
- 生成任务请求（供 28）

---

## 4. Key Features（关键功能）
- Chapter 编辑（MD）
- 一键：调用 01 规范化、02 路由、03 规划（预览）
- 一键：生成 Embedding（若该 chapter 要入 KB，可联动 11/12）
- 章节选择目标语言 + culture pack + persona（供 28）

---

## 5. Integration Points（接入点）
- 01：story ingestion（将 chapter 作为 raw_input）
- 02：language route（目标语言/locale/culture candidates）
- 03：scene/shot plan 预览
- 28：创建 Task/Run 进行全链路执行（01~22）

---

## 6. Definition of Done
- [ ] 支持 Project/Novel/Chapter CRUD
- [ ] 支持 Markdown 编辑与版本历史
- [ ] 支持调用 01~03 做预览规划
- [ ] 支持从 Chapter 发起任务到 28

---

## 7. 对话补充需求索引（接力必读）
- 23~30 对话收敛需求见：`SKILL_23_30_PRODUCT_REQUIREMENTS_MASTER.md`
- 本 Skill 重点补充：小说页与章节工作区拆页；章节编辑区左编右预览；AI 扩写入口。
