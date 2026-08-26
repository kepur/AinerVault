# 22_PERSONA_DATASET_INDEX_MANAGER.md
# Persona Dataset & Index Manager（导演A/B/C 数据集与索引管理 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 用于解决：
- 数据集 A 形成导演 A
- 后续添加特别数据集形成导演 B
- 导演 A 可升级到 A v2 / v3
- 也可新建独立的导演 C

该模块不是单纯“一个 embedding 集”，而是管理：
- Dataset
- KB Index / Embedding Index
- Persona（导演/摄影/灯光等人格）
- Persona 与 Dataset / Index / Style DNA / Policy 的映射

---

## 1. Workflow Goal（目标）
实现一套可管理、可升级、可回滚的 Persona 构建体系：
1. Dataset 管理（原始知识集）
2. Index 构建（切片 + embedding 后形成索引）
3. Persona 组装（绑定 dataset/index/style_dna/policy）
4. Persona 版本管理（A v1 -> A v2）
5. Persona 分支管理（导演A / B / C）
6. Preview：预览某 Persona 会调用哪些知识与参数

---

## 2. Concepts（核心概念）

### 2.1 Dataset
原始知识来源集合：
- 手工规则
- 案例文档
- 镜头分析
- 导演风格笔记
- 灯光/美术/运镜知识库

### 2.2 Knowledge Index
由某批 Dataset 构建而来的 embedding 索引：
- `index_id`
- `kb_version_id`
- `dataset_ids[]`

### 2.3 Persona Profile
真正用于运行时调用的对象，不等于 dataset：
- 绑定哪些 dataset/index
- 使用什么 style DNA
- 使用什么 policy override
- 使用什么 critic threshold

### 2.4 Persona Lineage（人格谱系）
用于追踪：
- A v1 -> A v2
- A 分叉成 B
- C 独立创建

---

## 3. Inputs（输入）

### 3.1 前端输入（用户操作）
- 新建 Dataset
- 上传/编辑内容
- 选择加入哪个 index build
- 创建 Persona
- 给 Persona 绑定：
  - datasets
  - index version
  - style dna
  - policy override
- 发布 Persona version

### 3.2 系统输入
- `11_RAG_KB_MANAGER`
- `12_RAG_PIPELINE_EMBEDDING`
- `14_PERSONA_STYLE_PACK_MANAGER`
- feature_flags:
  - enable_persona_lineage
  - enable_dataset_branching
  - enable_preview_retrieval
  - enable_multi_index_persona

---

## 4. Outputs（输出）
### 4.1 主输出文件
- `persona_dataset_index_manifest.json`

### 4.2 输出内容必须包含
1. `datasets[]`
2. `indexes[]`
3. `personas[]`
4. `lineage_graph`
5. `preview_retrieval_plan`
6. `warnings[]`

---

## 5. Branching Logic（分支流程与判断）

### [PD1] Dataset Management（数据集管理）
#### Actions
1. 新建/编辑 Dataset
2. 打 role/tags
3. 标记是否进入下次 index build
#### Output
- dataset saved

---

### [PD2] Index Build Selection（索引构建选择）
#### Actions
1. 选择多个 dataset 构建 index
2. 生成 index build request（调用 12）
3. 记录 index 与 dataset 的关联关系
#### Output
- index build request / result

---

### [PD3] Persona Assembly（人格组装）
#### Actions
1. 选择 persona 名称与 base role
2. 绑定 dataset_ids / index_ids
3. 绑定 style pack（14）
4. 绑定 policy / critic profiles
5. 生成 runtime persona manifest
#### Output
- persona draft

---

### [PD4] Persona Upgrade / Branching（升级与分支）
#### Trigger
用户对现有人格做升级或分叉
#### Actions
1. `upgrade`：A v1 -> A v2（保持 lineage）
2. `branch`：A -> B（继承一部分，再加入新数据集）
3. `new`：全新导演 C
4. 记录 lineage graph
#### Output
- updated lineage

---

### [PD5] Preview Retrieval（预览调用效果）
#### Trigger
用户想看导演A/B/C 会召回什么
#### Actions
1. 输入 query / shot desc
2. 根据 persona 的 index + style pack + policy 做 preview retrieval
3. 显示：
   - top chunks
   - 来自哪些 dataset
   - 哪些 style/policy 生效
#### Output
- retrieval preview

---

## 6. Output Contract（示例）
```json
{
  "version": "1.0",
  "status": "persona_index_ready",
  "datasets": [
    {"dataset_id": "DS_001", "name": "武侠动作运镜规则集"},
    {"dataset_id": "DS_002", "name": "导演A私有笔记"}
  ],
  "indexes": [
    {"index_id": "IDX_010", "kb_version_id": "KB_V1_20260226_001"}
  ],
  "personas": [
    {
      "persona_id": "director_A",
      "persona_version": "2.0",
      "dataset_ids": ["DS_001", "DS_002"],
      "index_ids": ["IDX_010"],
      "style_pack_ref": "director_xiaoli@1.2.0"
    }
  ],
  "lineage_graph": {
    "nodes": ["director_A@1.0", "director_A@2.0", "director_B@1.0"],
    "edges": [
      {"from": "director_A@1.0", "to": "director_A@2.0", "type": "upgrade"},
      {"from": "director_A@1.0", "to": "director_B@1.0", "type": "branch"}
    ]
  },
  "preview_retrieval_plan": {},
  "warnings": []
}
```

---

## 7. Integration Points（接入点）
- 上游：
  - `11_RAG_KB_MANAGER`
  - `12_RAG_PIPELINE_EMBEDDING`
  - `14_PERSONA_STYLE_PACK_MANAGER`
- 下游：
  - `10_PROMPT_PLANNER`
  - `15_CREATIVE_CONTROL_POLICY`
  - `17_EXPERIMENT_AB_TEST_ORCHESTRATOR`

---

## 8. Definition of Done（完成标准）
- [ ] 支持 Dataset / Index / Persona 三层对象管理
- [ ] 支持 Persona 升级、分支、全新创建
- [ ] 支持 preview 某 Persona 的知识召回效果
- [ ] 支持被 10/15/17 直接消费
