# 26_RAG_KB_DATASET_PERSONA_CONSOLE.md
# RAG / KB / Dataset / Persona Console（RAG控制台 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 是 Studio 的 RAG 控制台 UI 层，聚合：
- 11 知识库管理（条目CMS）
- 12 向量化管线（chunk/embedding/index）
- 14 人格风格包（Style DNA）
- 22 导演A/B/C 数据集-索引-人格谱系

---

## 1. Workflow Goal（目标）
- Dataset 管理与导入
- KB 条目管理与审核
- 一键构建/重建索引
- Persona 组装（A/B/C）
- Persona 预览（query -> top chunks）
- Persona 版本发布与回滚

---

## 2. Integration Points（接入点）
- 11/12/14/22：全量对接
- 10：运行时选择 persona（28 传入）
- 17：实验选择变量（persona/version）

---

## 3. Definition of Done
- [ ] 用户可创建/升级/分支 Persona（导演A/B/C）
- [ ] 可预览召回与来源追溯
- [ ] 可触发索引构建并查看报告

---

## 4. 对话补充需求索引（接力必读）
- 23~30 对话收敛需求见：`SKILL_23_30_PRODUCT_REQUIREMENTS_MASTER.md`
- 本 Skill 重点补充：角色工作台需直连知识包初始化与增量导入任务，并展示变化报告。
