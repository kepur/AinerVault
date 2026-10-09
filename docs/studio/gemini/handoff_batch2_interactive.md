# Plan A Gemini 独立验证交付报告 (Batch 2: 交互与生命周期实测)

**版本**：v1.1 (Batch 2 真实路径端到端交互验证)  
**验证负责人**：Gemini (独立验证与 QA Agent)  
**被测服务**：
- 前端：Ainer Studio (`http://localhost:5174/studio/?view=flow`)
- 后端：AinerN2D Core FastAPI (`http://localhost:8100/api/v2/studio`)
**测试引擎**：Chrome DevTools Protocol (CDP) + Headless Chromium + Python 3.12  
**核心验证目标**：针对用户指令“**下一轮要验证实际点击、编辑、保存和重新打开**”，开展真实浏览器环境下的完整端到端交互闭环验证。

---

## 1. 验证结论总览

| 交互生命周期阶段 | 预期行为 | 实测结果 | 判定 | 证据截图 |
|---|---|---|---|---|
| **1. 实际点击 (Click)** | 点击顶栏「+ 新建画布」，切换到「空白画布」Tab，输入标题并提交 | 弹窗正常弹出，Tab 与输入框正常响应，调用 `POST /api/v2/studio/canvases` 成功返回新画布 ID | **通过** | `01_create_blank_canvas_modal.png` |
| **1.1 空白状态核验** | 新建空白画布初始应为 0 节点的纯净自由工作区 | 画布中央**自动强行注入了「故事梗概」卡片**（1 个节点），并非真正空白 | **失败 (BUG-05)** | `02_blank_canvas_created.png` |
| **2. 实际新增 (Add)** | 点击底栏「+」菜单，选择「文本」添加节点 | 节点成功挂载到 React Flow 画布，初始状态为未命名自由文本卡片 | **通过** | `03_node_added.png` |
| **2.1 就地编辑 (Edit)** | 双击文本卡片进入编辑模式，键入自定义分镜描述并失焦保存 | `TextEditor` 激活，键入分镜文字，失焦后 DOM 实时呈现编辑文字，Dock 联动自由生成模式 | **通过** | `04_node_edited.png` |
| **3. 实际保存 (Save)** | 1000ms 防抖后自动触发 `PUT /studio/canvases/{id}`，顶栏显示「已保存」 | 顶栏角标成功转为绿点「已保存」，后端数据库 version 从 1 升至 2，`doc.nodes` 包含持久化文本 | **通过** | `05_canvas_saved.png` |
| **4. 重新打开 (Reopen)** | 浏览器硬刷新/直接访问该画布专属 URL，还原全部改动 | 页面完整重载，React Flow 重新渲染，所编辑的文本节点 100% 还原，文字完全一致 | **通过** | `06_canvas_reopened.png` |

**总体判定**：`PASSED_WITH_DEFECTS (全生命周期打通通过，伴随 BUG-05 缺陷确认)`

---

## 2. 端到端执行详情与证据链

测试脚本路径：`scripts/planA_qa/test_studio_e2e_lifecycle.py`  
测试报告数据：`docs/studio/test_runs/e2e_interactive_latest.json`  
新建测试画布 ID：`brd_01M4F0N86DRMD3VZ728PKDV3CN`  
画布标题：`E2E自由创作板_滑雪特写`  

### Step 1: 点击新建画布弹窗
1. 访问创作画布页面 `http://localhost:5174/studio/?view=flow`；
2. 自动化定位并点击顶栏 `.cv-topbar` 中的 `+ 新建画布` 按钮；
3. 弹出 `<NewCanvasModal>`，点击切换到「空白画布」Tab；
4. 输入标题 `E2E自由创作板_滑雪特写`；
5. 点击「创建空白画布」按钮。
- **证据截图**：`docs/studio/test_runs/screenshots/01_create_blank_canvas_modal.png`

---

### Step 2: 初始画布状态检查与 BUG-05 现场确认
1. 页面跳转进入新画布 `brd_01M4F0N86DRMD3VZ728PKDV3CN`；
2. 检查 React Flow 画布内初始节点列表：
   ```json
   [
     {
       "id": "story:ch_01M1METGFD9RXHWWV8FR65Z57K",
       "title": "故事梗概",
       "text": "少年热血 第一章 欺负\n辍学少年Tyler和Brad Miller在走廊拦截并殴打学生Thomas Ashford..."
     }
   ]
   ```
3. **现场实测确认**：即使在新建时明确选择了「空白画布」，画布初次加载时仍被强行塞入了属于当前章节的「故事梗概」节点，**完全无法获得用户自定义的纯净空白画布**。
- **证据截图**：`docs/studio/test_runs/screenshots/02_blank_canvas_created.png`

---

### Step 3: 实际新增文本节点与就地编辑
1. 点击底栏居中圆型大号加号按钮 (`button.cv-bb-plus`)，展开新增菜单；
2. 点击「文本」项，React Flow 画布成功新增节点 `n_mv081pmpdltl3`；
3. 模拟用户双击该节点卡片 `.cv-card`，激活就地编辑框 `<textarea class="cv-text__edit">`；
4. 输入自定义分镜文本：
   > `滑雪少女自由创作镜头：高山雪道急速俯冲，定格漫天飞雪特写`
5. 触发失焦（`blur`）完成提交；
6. 检查 DOM：`.cv-text__plain` 节点成功呈现上述全部字样，底部 Dock 自动联动进入自由生成（LTX-2.5）设置面板。
- **证据截图**：
  - 新增节点：`docs/studio/test_runs/screenshots/03_node_added.png`
  - 编辑完成：`docs/studio/test_runs/screenshots/04_node_edited.png`

---

### Step 4: 实际防抖自动保存与数据库校验
1. 编辑完成后等待 1000ms（触发 `store.tsx` 内 `SAVE_DEBOUNCE` 防抖）；
2. 顶栏右侧保存状态角标由 `保存中…` 成功转变为 `● 已保存`（类名包含 `t-ok`）；
3. 直接通过 HTTP 请求后端接口 `GET /api/v2/studio/canvases/brd_01M4F0N86DRMD3VZ728PKDV3CN`，核验 PostgreSQL 数据库中的真实文档：
   ```json
   {
     "id": "brd_01M4F0N86DRMD3VZ728PKDV3CN",
     "title": "E2E自由创作板_滑雪特写",
     "version": 2,
     "doc": {
       "schema": "ainer.board/v1",
       "nodes": [
         {
           "id": "story:ch_01M1METGFD9RXHWWV8FR65Z57K",
           "type": "text",
           "data": { "ref": { "kind": "story", "id": "..." }, "role": "story", "title": "故事梗概" }
         },
         {
           "id": "n_mv081pmpdltl3",
           "type": "text",
           "data": {
             "ref": { "kind": "free", "id": "n_mv081pmpdltl3" },
             "role": "note",
             "title": "文本",
             "text": "滑雪少女自由创作镜头：高山雪道急速俯冲，定格漫天飞雪特写"
           }
         }
       ]
     }
   }
   ```
4. **校验结论**：
   - 乐观锁版本由 1 递增至 2；
   - 用户编辑的内容完整写入 `doc.nodes[1].data.text`，未发生字段丢失或格式破坏。
- **证据截图**：`docs/studio/test_runs/screenshots/05_canvas_saved.png`

---

### Step 5: 重新打开与持久化完整性复验
1. 模拟用户关闭标签页后重新打开：浏览器直接导航到该画布链接：
   `http://localhost:5174/studio/?view=flow&canvas=brd_01M4F0N86DRMD3VZ728PKDV3CN`
2. 等待 React Flow 画布挂载与接口数据拉取（4.0 秒）；
3. 审查重载后的 DOM：
   - 包含节点数：2
   - 目标节点 `n_mv081pmpdltl3` 完好无损存在；
   - 节点内正文 `.cv-text__plain`：`"滑雪少女自由创作镜头：高山雪道急速俯冲，定格漫天飞雪特写"`；
   - 顶栏状态指示为 `● 已保存`。
- **证据截图**：`docs/studio/test_runs/screenshots/06_canvas_reopened.png`

---

## 3. 伴随缺陷分析与修复指引 (BUG-05)

### 缺陷现象
用户反馈：*“新建画布 我说空白 用户自己随便自定义 我看功能实现还有问题”*。  
本轮实测证实：
1. **自动注入故事卡片**：勾选“关联到当前章节”（默认勾选）创建时，系统会自动在画布中塞入当前章节的「故事梗概」节点，破坏了“纯净空白”的初衷；
2. **脱离章节即丢失导航入口**：若不勾选“关联到当前章节”，画布在后端保存为 `chapter_id=null`，但在顶栏的面包屑中根本没有该画布的列表入口，直接打开其 URL 甚至会被强制重定向回默认章节的第一张分镜画布！

### 修复指引 (交接给 Claude / 前端与 Codex / 后端)
1. **`NewCanvasModal.tsx` & `store.tsx` (Claude)**：
   - 当用户提交「空白画布」时，向 `createCanvas` 显式传递初始空文档：
     ```ts
     doc: {
       schema: DOC_SCHEMA,
       viewport: { x: 0, y: 0, zoom: 1 },
       nodes: [],
       edges: [],
       hidden: []
     }
     ```
   - 在 `importer.ts` 的 `buildGraph` 中增加判断：若传入的 `saved` 具有显式空 `nodes: []`（且标记为自建自由画布），不执行 `derivedGraph` 的剧本梗概卡片注入。
2. **顶栏导航与自建画布管理 (Claude / Codex)**：
   - 在顶栏画布下拉框（Crumb）中，除显示当前章节的场次画布外，增加「我的自由创作画布」独立分类，支持无章节限制的纯自由画布漫游与切换。

---

## 4. 交付清单与文件索引

1. **测试运行脚本**：`scripts/planA_qa/test_studio_e2e_lifecycle.py`
2. **结构化测试结果**：`docs/studio/test_runs/e2e_interactive_latest.json`
3. **关键步骤证据截图**：
   - `docs/studio/test_runs/screenshots/01_create_blank_canvas_modal.png` (新建弹窗)
   - `docs/studio/test_runs/screenshots/02_blank_canvas_created.png` (新建后带故事梗概缺陷)
   - `docs/studio/test_runs/screenshots/03_node_added.png` (新增文本节点)
   - `docs/studio/test_runs/screenshots/04_node_edited.png` (就地编辑完成)
   - `docs/studio/test_runs/screenshots/05_canvas_saved.png` (防抖保存与顶栏已保存角标)
   - `docs/studio/test_runs/screenshots/06_canvas_reopened.png` (重新打开后节点完整还原)
4. **全阶段验收矩阵**：`docs/studio/gemini/acceptance_matrix.md` (已更新至 Batch 2)
