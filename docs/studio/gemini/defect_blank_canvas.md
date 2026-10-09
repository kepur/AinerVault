# Plan A 缺陷报告：新建空白画布无法真正空白与自由自定义 (BUG-05)

**缺陷 ID**：`BUG-05`  
**报告方**：Gemini (独立测试与质量审计)  
**责任方**：**Claude (制作界面/主要责任)**、**Codex (后端配合)**  
**发现日期**：2026-10-09  
**严重级别**：High (高 - 用户无法自由创作，违背「空白画布」核心预期)  
**关联合约**：`ainer.production/v0.1` (`planA_contracts.md` §2, `batch1_design.md` §2.2)

---

## 1. 缺陷概述 (Summary)

用户反馈：“**新建画布 我说空白 用户自己随便自定义 我看功能实现还有问题**”。  
经 Gemini 代码级逆向审查与实测验证，确认该问题**完全属实**。当前 Studio 前端界面在创建「空白画布」时，存在多项严重偏离契约的设计与实现缺陷，导致所谓「空白画布」既无法真正空白，也无法自由自定义和保留。

---

## 2. 复现步骤 (Steps to Reproduce)

1. 在浏览器中打开创作画布（例如 `http://localhost:5174/studio/?view=flow&novel=nv_01&chapter=ch_01&plan=sp_01`）。
2. 点击顶栏右侧的「**+ 新建画布**」按钮，弹出 `NewCanvasModal`。
3. 切换到「**空白画布**」Tab。
4. 输入标题「我的自由画板」，点击「**创建空白画布**」。
5. **观察现象**：
   - 画布被打开后，界面正中央赫然出现一个「**故事梗概**」文本节点，以及与本章关联的派生镜头/场景结构；画布**根本不是空白**。
   - 用户试图在画布中自由连线、放置自由素材，但该画布被永久深度绑定到当前章节和分镜计划上（`plan_id` / `chapter_id`）。
   - 若用户在弹窗中取消勾选「关联到当前章节」，画布创建后直接在顶栏面包屑与切换器中**彻底消失**，用户刷新或切换后无法再找回。

---

## 3. 输入、预期输出与实际输出 (Input / Expected / Actual)

### 3.1 测试输入 (Input)
- 用户意图：建立一张不受既有故事约束、自由放置任意节点（文本、图片、视频、3D 白模）、自由连线创作的**完全空白自由画布**。
- 前端操作：在 `NewCanvasModal` 中点击「创建空白画布」。

### 3.2 预期输出 (Expected Output)
1. **纯净空白**：画布节点列表 `nodes: []`，边列表 `edges: []`，画布中央空无一物，无任何强加的「故事梗概」或派生分镜。
2. **自由属性**：画布在后端的生产用途为 `purpose="general"`，`plan_id=None`，`chapter_id=None`（或可选关联仅作分类），`doc` 初始持久化为 `{schema: "ainer.board/v1", nodes: [], edges: []}`（`version=1`）。
3. **可常驻访问**：自由画布可被顶栏或画布列表随时切换，不因没有 `chapter_id` 而从导航栏丢弃。
4. **自由自定义**：底栏「+」添加节点菜单允许自由放置文本、上传图片、添加 3D 白模、视频生成节点，任意自由连线并自动保存。

### 3.3 实际输出 (Actual Output)
1. 前端在 `NewCanvasModal.tsx`（第 76 行）默认强行勾选 `attachChapter = true`，导致创建请求携带了当前章节的 `plan_id`、`chapter_id`。
2. 画布加载时，`store.tsx`（第 1655 行）发现 `plan_id` 不为空，强行调用 `cv.board(plan)` 获取全章分镜。
3. `importer.ts`（第 136-137 行）执行 `derivedGraph`，强制 `push("text", { ref: story, title: "故事梗概", role: "story" })`，把故事梗概生硬推上画布。
4. 新建时未向后端 PUT 初始合规空文档，导致画布版本停留为 `version=0`，随时可能被派生规则重新覆盖。
5. 若取消勾选章节关联，顶栏面包屑下拉框只请求 `/chapters/{chapter_id}/canvases`，自由画布由于不带 `chapter_id` 直接被过滤掉，造成画布“创建即丢失”。

---

## 4. 根因剖析 (Root Cause Analysis)

### 缺陷 1：前端创建逻辑强绑定章节计划 (伪空白)
- **文件**：`code/apps/ainer-studio/src/canvas/chrome/NewCanvasModal.tsx` 第 76 行、第 138-141 行：
  ```tsx
  const [attachChapter, setAttachChapter] = useState(true); // 默认强行绑定章节！
  await latest.current.createCanvas({
    title: blankTitle.trim() || "空白画布",
    chapter: attachChapter,
  });
  ```
- **后果**：传递 `chapter: true` 导致 `plan_id` 与 `chapter_id` 被写入画布，画布被定性为分镜派生画布而非自由画布。

### 缺陷 2：派生图引擎强推「故事梗概」
- **文件**：`code/apps/ainer-studio/src/canvas/importer.ts` 第 136-137 行：
  ```typescript
  const story = storyRef(live)!;
  push("text", { ref: story, title: "故事梗概", role: "story" });
  ```
- **后果**：只要 `live.board` 存在（即绑定了 `plan_id`），哪怕用户希望该画布镜头为空，也会被硬塞一个「故事梗概」节点。

### 缺陷 3：顶栏面包屑无法索引自由画布 (游离丢失)
- **文件**：`code/apps/ainer-studio/src/canvas/chrome/TopBar.tsx` 第 636-655 行、`store.tsx` 第 1731 行：
  - 画布列表数据源严格来自于 `cv.canvasList(chapterId)`（即 `GET /api/v2/studio/chapters/{id}/canvases`）。
  - 没有 `chapter_id` 的自由画布无法在此端点返回。
  - 顶栏没有提供「自由画布」或「跨章节画布」的展示入口，导致自由画布成为“幽灵画布”。

### 缺陷 4：新建画布未落实 Plan A 的 Purpose 契约
- **文件**：`code/apps/ainer-studio/src/canvas/chrome/NewCanvasModal.tsx`
  - 弹窗中完全没有体现 Plan A 契约规范的四种用途枚举（`assets` 素材、`directing` 导演、`finishing` 成片、`general` 自由）。
  - 没有在创建时向后端传递 `purpose` 参数。

---

## 5. 修复方案与责任分工 (Action Plan)

### 5.1 Claude (前端 UI) 修复任务
1. **改造 `NewCanvasModal.tsx`**：
   - 增加画布用途选择（契约 `purpose`）：
     - 🎨 **通用自由画布 (`general`)**：默认纯净空白，`doc` 初始为 `{schema: "ainer.board/v1", nodes: [], edges: []}`，不挂接 `plan_id`。
     - 🎭 **角色素材画布 (`assets`)**：绑定 `novel_id`，打开资产抽屉，不挂接 `plan_id`。
     - 🎬 **导演排演画布 (`directing`)**：挂接分镜与舞台。
   - 彻底移除对空白画布默认绑定当前 `plan_id` 的硬编码。
2. **改造 `importer.ts`**：
   - 在 `buildGraph` 与 `derivedGraph` 中增加判断：若当前画布为 `purpose === "general"` 或 `kind === "custom"` 且 `shot_ids` 为空，**严禁自动添加 `story` 故事梗概节点**。
3. **改造 `TopBar.tsx` 与导航**：
   - 在顶栏画布切换下拉列表中，除显示当前章节画布外，增加「自由画布」分组（可调用 `GET /studio/canvases?free=true` 或包含当前小说自由画布），确保空白画布可随时切换访问。
4. **新建时初始化持久化**：
   - 在 `createCanvas` 成功获取 `board.id` 后，立即发起 `canvasSave(b.id, 0, { schema: "ainer.board/v1", viewport: { x: 0, y: 0, zoom: 1 }, nodes: [], edges: [] })`，将版本号确定在 `version=1`。

### 5.2 Codex (后端) 配合验证
- 后端 `POST /studio/canvases` 已在 Gemini 独立测试中验证通过（支持 `purpose="general"`、`plan_id=None`）。
- 需确保 `GET /studio/canvases?free=true` 与 `GET /studio/canvases?purpose=general` 在包含或不包含 `novel_id` 时均能稳定返回自由画布。
