# 第六批交接清单：剧本设定器、世界观跨文化深度转译与 480p 极速引擎

## 1. 本批次核心解决的问题

1. **本地模型速度为王（480p / 768×448 极速默认）**
   - 彻底修复画幅警告（`⚠️ 该模型最大 1024x576，按此出`），默认切换为 **480p (768×448)**；
   - 严格满足 LTX-2.5 模型 64 倍数空间维度要求（$768 = 64 \times 12, 448 = 64 \times 7$），单帧 Token 面积降至 344,064，出片时间缩短至 ~1.5 分钟以内。

2. **文本节点全流程 AI 编剧与导演分镜整合**
   - 改变过去画布文本节点仅能单调「搭白模/复制文字」的局限；
   - 浮动工具栏与底部 Dock 接入 **✨ 剧本设定器** 与 **🎬 导演拆分镜**；
   - 集成系统既有大模型与导演大师 Skill（`SKILL_34` 摄影机调度/景别运镜/反抽搐切镜规范）。

3. **世界观念翻译与国际化双模式（保留剧情出海 vs 深度世界观圈层转译）**
   - **模式一（国内原生）**：快节奏爆款短剧、反转打脸、爽点前置；
   - **模式二（东方文化忠实出海）**：保留仙侠/武侠原生世界观与中国文化底色，加入海外易懂的术语注解与英文本土化表达；
   - **模式三（世界观文化圈层全景深度转译）**：
     - 将中式修仙/宫斗/赘婿等核心设定**全景转移映射**到海外文化语境（如欧洲中世纪大修道院骑士圣物、英国摄政时代贵族联姻、现代欧美隐形黑帮财阀）；
     - 术语全量替换（青云宗 ➔ Order of St. Aurelius、龙珠 ➔ Wyrm-Heart Relic、退婚 ➔ Trial by Ordeal）；
     - 角色命名与身份重塑（林凡 ➔ Julian Thorne、皇帝 ➔ King Lothair IV）；
     - 视觉 Prompt 强制剔除汉服与中式亭台楼阁，替换为哥特石砌教堂、板甲骑士与西方中世纪写实光影。

4. **精细化 5 维交互配置器**
   - 时代背景（多选 ≤ 2 项）
   - 角色设定（多选 ≤ 5 项）
   - 核心看点（多选 ≤ 3 项）
   - 画风（单选图文卡片 + 搜索检索）
   - 剧本结构与集数（1~100 集交互滑块 + 结构单选）

---

## 2. 核心架构与修改文件清单

### 2.1 后端引擎 (`code/apps/ainer-core`)

- **`app/pipelines/screenplay.py`** (新建)
  - 核心函数 `expand_screenplay(req: ScreenplayExpandIn)`；
  - 接入 `WorldProfile` 与 `WorldLexiconTemplate` 语义词典；
  - 拥有 `DOMESTIC_SYSTEM`、`FAITHFUL_EXPORT_SYSTEM`、`WORLD_ADAPTATION_SYSTEM` 三套严谨 System Prompt；
  - 配备完整的本地离线结构化兜底引擎（LLM 掉线时亦可保证结构化输出）。
- **`app/api/v2/quick_film.py`**
  - 新增 Pydantic 模型 `ScreenplayExpandIn` 与 `ScreenplayExpandOut`；
  - 暴露端点 `POST /api/v2/studio/screenplay-expand`。
- **`app/capability/generic.py`**
  - `GenerateIn.resolution` 默认值调整为 `"480p"`。

### 2.2 前端画布与外壳 (`code/apps/ainer-studio`)

- **`src/canvas/chrome/Dock.tsx`**
  - 缓存键升级为 `v2`，`DEFAULT_OPTS.resolution` 调整为 `"480p"`；
  - 当选中文本节点时，Dock 顶部自动呈现 **✨ 剧本设定器** 与 **Top 8 预设标签快捷行**（`#玄幻逆袭`、`#职场成长`、`#末世基建`、`#女频甜宠` 等）；
  - 点击任意标签直接打开设定器并预填对应 5 维数值。
- **`src/canvas/chrome/ScreenplayConfigModal.tsx`** (新建 & 深度重构)
  - **完全对齐参考设计原型**：
    - 采用 **1060px 宽屏暗黑玻璃拟态容器**，整体字号全面放大（标题 20px、预设与维度 14~15px、灵感 15px）；
    - **左侧「爆款预设 Top 8」**：Top 3 配备全景氛围 Banner 图标，4~8 号配备高质感圆形序号标牌与外发光；
    - **居中「双球流光概念视效」**：左侧 5 大主题材 + 右侧 5 大子题材双级联动，中心呈现双球透镜与流光连接桥，具有镜面高光与状态徽章；
    - **底部「6 大功能维度卡片」**：`目标受众`、`角色设定`、`时代背景`、`核心看点`、`画风`、`剧本结构` 6 卡横排，配备专属 SVG 图标与高亮数值；
    - **大字号 Popover 弹窗选择器**：44px 高、14px 大字号按钮，3 列网格排布，配有实时集数滑块与画风搜索过滤；
    - **世界观念翻译出海模式栏**：支持国内原生短剧、东方文化出海与全景世界观深度转译，目标映射世界下拉快速切换；
    - **左下角「展示爆款预设」开关**：iOS 风格切换按钮，支持一键展开/折叠左侧预设栏；
    - **生成成果展示与双向注入**：支持一键「注入画布卡片」与「🎬 注入并拆分镜」（自动调用系统导演 Skill 拆出镜头网络）。
- **`src/canvas/actions.ts`**
  - 在 `textActions` 中注入 `✨ 剧本设定器` 和 `🎬 导演拆分镜`；
  - 修复 `errText` 引用并与分镜动作关联。
- **`src/canvas/contract.ts` & `src/canvas/model.ts`**
  - 定义 `ScreenplayExpandIn`、`ScreenplayResult` 类型；
  - `OverlaySpec` 增加 `{ kind: "screenplay_config"; nodeId?: string; presetId?: string }`。
- **`src/canvas/chrome.css`**
  - 完善 `.cv-screenplay-modal`、`.cv-dock-script-bar`、`.cv-dock-script-chip` 等所有视觉样式。

---

## 3. 验证情况

1. **后端接口测试**：
   - 国内原生模式：`POST /api/v2/studio/screenplay-expand` 成功生成 35 集分幕与对白样现。
   - 跨文化深度转译模式（目标：`eu_medieval_high`）：成功将东方修仙核心冲突转译为中世纪修道院与圣物传奇，全量概念映射及角色身份替换无缝闭环。
2. **前端编译检查**：
   - `npm run build` 执行成功，0 TypeScript 报错，0 Lint 警告。
3. **服务状态**：
   - Vite 客户端：`http://localhost:5174` (正常)
   - Core API：`http://localhost:8100` (正常，带 `--reload`)
   - AI Studio 服务：`http://localhost:7999` (正常)
