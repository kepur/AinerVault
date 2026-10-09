# Plan A Batch 2 综合测试、交互验证与视频质量验收报告

> **报告主体**：Gemini (Plan A 独立测试与质量验收代理)  
> **报告日期**：2026-10-09  
> **关联版本**：Commit `1e04b08` 及工作区最新修改  
> **验收原则**：只修改测试、测试工具和报告；严格区分「模拟测试」、「真实路径验证」与「质量通过」；**禁止仅因任务成功就宣布成片合格**。

---

## 1. 总体验收状态总览 (Executive Summary)

| 验收维度 | 涵盖范围 | 测试结果 | 关键指标 / 交付状态 |
|---|---|---|---|
| **构建与服务健康** | Studio 前端 (Vite/TS) + Core 后端 (FastAPI) | ✅ **PASS** | 前端构建耗时 339ms；Core 8100、Gateway 7999、Studio 5174 均健康运行 |
| **单元与契约测试** | 7 大测试套件 (Batch 1 契约、画布、舞台、分镜等) | ✅ **PASS** | **180/180 通过** (耗时 4.31s) |
| **回归基线维护** | `test_identity_anchor.py` 视角映射 | ✅ **PASS** | **88/88 通过**；已同步 Plan A 左右视角不隐式镜像契约 |
| **架构防御门禁** | `test_llm_output_tolerance.py` 静态防御 | ⚠️ **FAIL** | 发现 **DEFECT-LINT-01**：`canvas_exec.py:978` 与 `cards.py:119` 裸循环未套 `as_items` |
| **E2E 交互全流程** | 真实浏览器：点击新建、编辑、防抖保存、重新打开 | ⚠️ **PASSED WITH DEFECTS** | 4 步交互全部真实通过闭环；确证 **BUG-05** 与 **CR-09** |
| **视频物理生成** | 本地 Gateway 7999 (MLX LTX-2.5 22B Distilled) | 🟡 **TASK SUCCEEDED** | 生成 2.37s 对白视频与 9.04s 滑雪视频，带 48k 同步音频 |
| **电影镜头质感** | 白模站位、统一时间尾帧接力、运镜节奏、声画依据 | ❌ **NOT PASSED** | **2 项 FAILED，2 项 BLOCKED**：成片严重缺乏多镜头蒙太奇与站位控制 |

---

## 2. 自动化测试与契约验收 (Automated & Contract Suites)

### 2.1 Batch 2 核心套件 (180 项全绿)
运行脚本：`scripts/planA_qa/run_batch2_qa.py`（产物：`docs/studio/test_runs/batch2_latest.json`）
- `test_planA_contracts_batch1.py`: **14/14 通过**
  - 覆盖画布上下文、资源引用解析、标准包安全性、舞台卡片查询与 preferred 视角选择。
  - 覆盖新增的 `test_cr09_physical_consistency_canonical_pack_and_stage_cards` 契约回归。
- `test_canvas_api.py`: **18/18 通过**
- `test_stage_p0.py`: **12/12 通过**
- `test_char_sheet.py`: **15/15 通过**
- `test_blocking_api.py`: **19/19 通过**
- `test_cinematic_director.py`: **5/5 通过**
- `test_screenplay.py`: **97/97 通过**

### 2.2 契约同步与回归修复
- **文件**: `code/apps/ainer-core/tests/test_identity_anchor.py`
- **契约调整**: Plan A 明确要求“左右侧面、三视图立绘不隐式镜像，profile_right 映射到 profile_right”。旧测试断言 `profile_right == profile_left` 已过时。
- **验证结果**: 更新测试断言后，全套 88 项测试全部通过。

### 2.3 发现的架构防御缺陷 (DEFECT-LINT-01)
- **拦截用例**: `tests/test_llm_output_tolerance.py::TestAsItems::test_no_raw_get_loops_remain`
- **违规行**:
  1. `code/apps/ainer-core/app/pipelines/canvas_exec.py:978`: `for r in recipe.get("refs") or []:`
  2. `code/apps/ainer-core/app/stage/cards.py:119`: `for p in ref.get("sheet_panels") or []:`
- **风险**: 隐式假设了字典项，模型下游换型或异常时会报未捕获 TypeError。已立工单 `docs/studio/gemini/defect_lint01_tolerance.md`。

---

## 3. E2E 真实交互生命周期验证 (Click, Edit, Save, Reopen)

Gemini 编写了基于 Headless Chromium + Chrome DevTools Protocol (CDP) 的自动化交互评测脚本：`scripts/planA_qa/test_studio_e2e_lifecycle.py`。全程采集原生 DOM 事件并落盘截图证明链（`docs/studio/test_runs/screenshots/`）：

| 步骤 | 操作行为 | 实际表现 | 截图证据 | 判定 |
|---|---|---|---|---|
| **Step 1: 点击新建** | 点击 TopBar `+ 新建画布` $\to$ 切换空白画布 Tab $\to$ 输入标题并提交 | 画布创建成功，URL 携带 `?canvas=brd_...` | `01_create_blank_canvas_modal.png`<br>`02_blank_canvas_created.png` | **PASS** (伴生缺陷 BUG-05) |
| **Step 2: 放置与编辑** | 点击底栏 `+` $\to$ 放置「文本」节点 $\to$ 双击节点输入滑雪自由创作文本 $\to$ 失焦提交 | 文本节点成功挂载，DOM 渲染精确文字：「滑雪少女自由创作镜头：高山雪道急速俯冲，定格漫天飞雪特写」 | `03_node_added.png`<br>`04_node_edited.png` | **PASS** |
| **Step 3: 防抖自动保存** | 等待 1000ms 防抖 $\to$ 监听网络 PUT 请求与 TopBar 状态 | TopBar 徽标变为 `● 已保存`；数据库 `version` 递增至 3，节点内容持久化入库 | `05_canvas_saved.png` | **PASS** |
| **Step 4: 刷新重新打开** | 真实重新加载该 URL $\to$ 验证 DOM 重建 | 画布完全还原，节点 ID、标题与自定义文本 100% 保留，徽标为 `已保存` | `06_canvas_reopened.png` | **PASS** |

### 伴生发现的交互缺陷 (BUG-05)
用户反馈：“**新建画布 我说空白 用户自己随便自定义 我看功能实现还有问题**”。
- **实测确证**：
  1. 当创建时勾选默认的“关联到当前章节”时，`importer.ts` 的 `derivedGraph` 会自动在空白画布中央塞入一个「故事梗概」卡片，违背“完全空白”预期。
  2. 当用户取消勾选时，由于 `chapter_id=null`，TopBar 面包屑下拉菜单无法索引到该自由画布，刷新或切换后用户无法导航找回。
- **对应工单**：`docs/studio/gemini/defect_blank_canvas.md`（责任方：Claude）。

---

## 4. 视频测试与成片质量深度审计 (Video & Cinematic QA)

针对用户关切的问题：“**卡住了么？还是怎么样没有用本机ml-stable-diffusion 这个项目接口生成？但是我记得ltx2.5支持声音，而不是没有依据的生成**”以及“**完整的白模站位、统一时间与运镜改造尚未完成**”，Gemini 进行了端到端物理调用审计：

### 4.1 本地推理耗时与接口排查
- **当前推理后端**：网关运行在 `http://127.0.0.1:7999`，模型为 `ltx-2.5-22b-distilled`（本地 Apple Silicon MLX 架构）。
- **实测性能数据**：
  - 对白短镜头（2.37s，57 帧）：推理耗时 **186.7 秒 (~3.1 分钟)**。
  - 滑雪动作长镜头（9.04s，217 帧）：推理耗时 **683.3 秒 (~11.4 分钟)**（Stage 1 耗时 204s，Stage 2 耗时 425s）。
- **为什么用户感觉“卡住了”**：
  1. 9 秒视频单次推理耗时近 12 分钟，且前端任务轮询未展示 ComfyUI/MLX 的当前 Step 进度条（Progress 仅在日志里滚动）。
  2. 系统没有直接调用 `ml-stable-diffusion`（那是老版 CoreML SD 管道），而是统一接入了网关 7999 的本地 LTX-2.5 管道。

### 4.2 LTX 2.5 声音支持实测
- **技术现状**：LTX 2.5 本地模型**确实支持原生出声**（Gateway 返回带有 48kHz WAV 音轨）。
- **缺陷现状（“没有依据的生成”）**：
  - 对白镜头（a2v 模式）：由 TTS 真实驱动，声音有依据。
  - 滑雪动作镜头（generate 模式）：提示词仅写了 `Audio: natural ambient sound...`，模型生成的是一段通用风声底噪。它**没有依据剧本中精确的物理拟音**（如双板破雪声、雪杖击地声、倒地扑雪声、喘息大笑声）进行 Foley 拟音混合，因此听感脱节。

### 4.3 导演专业质量四项判定（为什么成片未通过）

| 质检维度 | 现状事实 | 质量判定 | 根因与改进需求 |
|---|---|---|---|
| **白模站位 (BLK-05)** | 3D-BOX 编辑器已支持摆放三维站位与机位，但 Blender worker 导出的 Depth/Pose/Canny 控制流尚未真正注入 LTX 2.5 生成管道。 | 🛑 **BLOCKED** | 需 Codex 打通 `director/renderers/ltx25.py` 的 Union Control，把白模骨架真正作为 IC-LoRA 条件送入。 |
| **统一时间与尾帧接力 (TIM-03)** | 当前滑雪测试强行用“一镜到底”把 3 张关键帧（0、72、144 帧）塞进单个 9 秒请求，导致剧烈变形；多镜头生成时镜头 $N$ 未继承镜头 $N-1$ 的 `last_frame`。 | ❌ **FAILED** | 严禁一镜到底插值多阶段剧烈动作！必须拆为多镜头序列，且将前一镜的尾帧作为后一镜的连续性底图/参考。 |
| **运镜与景别节奏 (CAM-04)** | 滑雪动作被拍成单一角度的平移缓推，缺乏电影蒙太奇（特写、全景、跟拍交替）。 | ❌ **FAILED** | 必须执行 `cinematic_director.py` 的多景别编排：WS（高山俯冲） $\to$ CU（跌倒飞雪微表情） $\to$ MLS（剪刀手站起）。 |
| **本地音频接地 (BUG-04)** | 滑雪动作仅使用模型自由脑补的环境声，没有基于声音规格的程序化拟音与角色人声。 | 🛑 **BLOCKED** | 需将 `procedural-foley-v1` 拟音轨与 LTX 2.5 混合合成，形成带依据的声景。 |

---

## 5. 待办移交与任务分工 (Actionable Handover)

### 5.1 移交给 Claude (前端 UI)
1. **修复 BUG-05 (空白画布自由化)**:
   - `NewCanvasModal.tsx`: 新建空白画布时取消强行默认勾选 `attachChapter`；当用户明确选择空白画布时，创建真正的空文档 `{schema: "ainer.board/v1", nodes: [], edges: []}`。
   - `importer.ts`: 当传入空画板或空白模板时，禁止通过 `derivedGraph` 自动塞入「故事梗概」节点。
   - `TopBar.tsx`: 支持展示并切换不隶属于特定章节的全局/自由创作画板。

### 5.2 移交给 Codex (后端与生成管线)
1. **修复 CR-09 (physical 契约一致性)**:
   - 见工单 `docs/studio/gemini/defect_cr09_physical.md`。
   - 统一收拢 `stage.py` 与 `service.py` 中的 `infer_physical` 调用，非人物实体不得出现人体尺寸，确保单一事实来源。
2. **修复 DEFECT-LINT-01 (架构防御门禁)**:
   - 见工单 `docs/studio/gemini/defect_lint01_tolerance.md`。
   - 在 `canvas_exec.py:978` 和 `cards.py:119` 中引入 `as_items()`，消除静态检查拦截。
3. **改造滑雪视频管线 (从单镜硬塞到多镜头蒙太奇与尾帧接力)**:
   - 抛弃单段 9 秒硬插值 3 张关键帧的做法。
   - 采用 3 个分镜头生成：第 1 镜（俯冲 WS） $\to$ 第 2 镜（跌倒特写 CU，使用第 1 镜尾帧色彩/光线锚） $\to$ 第 3 镜（站起大笑 MS）。
   - 将 `procedural-foley-v1` 的拟音音轨注入剪辑台，闭合声画依据。
4. **推进白模站位到 LTX 2.5 的 Union Control 真实接入**。
