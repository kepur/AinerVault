# Claude 第一批 UI 设计：A/B/C/D 导航、B/C 自建画布、资产引用、16 格定妆照

日期：2026-10-09。Owner：Claude。契约依据：`docs/studio/planA_contracts.md` v0.1。主方案：`planA.md` v2 第 2、3、5、11 节。

本文是 **设计**，不是已实现代码。写作时 BASE_READY 与 API_READY 均未发布，因此本批不在 `code/apps/ainer-studio/src/` 落代码；实现待基线冻结且本文第 6 节的阻塞项有结论后开始。

所有「现状」均为 2026-10-09 在本机实际查验的结果，不是推测。查验方式见第 7 节。

---

## 1. 现状基线（实测）

### 1.1 真实可用的后端接口

core 在 8100 运行（`/health` 返回 `ainer-core 2.0.0`）。本批 UI 可以绑定的真实端点：

| 端点 | 实测结果 | 本批用途 |
|---|---|---|
| `GET /api/v2/studio/canvases?limit=&free=` | 返回真实画布列表（含 scope、plan_id、chapter_id、novel_id） | B/C 画布首页 |
| `GET/POST/PUT/PATCH/DELETE /api/v2/studio/canvases[/{id}]` | 存在；PUT 用 base_version + doc，409 冲突 | 画布创建与读写 |
| `GET /api/v2/stage/cards?plan_id=…` | **强制要求 `plan_id`**（不给返回 422 missing） | B 资产卡；自由画布不可用，见 6.1 |
| `PATCH /api/v2/stage/cards/{card_id}/physical` | 存在 | 物理尺寸编辑 |
| `GET /api/v2/characters?scope=book&novel_id=` | 存在，返回本书角色 | 角色库 |
| `POST /api/v2/studio/char-sheets` / `GET …/{job_id}` | 存在（源码级） | 16 格定妆照生成 |
| `GET /api/v2/studio/plans/{plan_id}/cast` | 存在，返回 views 映射 | 资产抽屉角色页 |
| `POST /api/v2/studio/canvases/{id}:execute` / `/node-runs` / `:stop` | 存在 | 节点运行状态 |

`/api/v2/production/*` 全族（context、resources:resolve、canonical-pack、resources、prepare、usages）在源码中**一个都不存在**（`grep` 全库无匹配）。契约 v0.1 §5 标注「待实现」，与实测一致。

### 1.2 真实数据

| 事实 | 实测值 | 对 UI 的影响 |
|---|---|---|
| 世界实体 | character 7、location 1、**prop 0** | 道具卡没有真实数据可绑；道具 UI 本批只出空状态，不做假卡 |
| 现有视角键 | `front`、`bust`、`back`、`profile_left`、`three_quarter_left`、`sheet` | **全是旧键** |
| 16 格标准键 | `body_*`/`face_*`/`expr_*` 在库中出现 **0 次**；`sheet_panels` 字段 0 条 | 16 格展示在真实数据上**必然全缺**，见 2.4 |
| 画布 | kind：scene 11、custom 2、plan 1；无章节无计划的自由画布 2 张 | 自由画布是真实存在的入口，不是假设 |
| `purpose` | 存在，但是 `scope_json["purpose"]` 里的自由字符串（≤32 字符），无枚举校验 | 不能作为 B/C 分流的可信依据，见 6.2 |

### 1.3 现有前端

- `src/Nav.tsx`：5 个平级视图 `canvas / flow / box / characters / styles`。
- `src/ctx.ts`：9 个地址栏键 `view, novel, chapter, plan, canvas, shot, box, char, from`，已实现换上级级联清下级。
- `src/canvas/`：节点画布齐全；第三轮另一 agent 已加 `chrome/NewCanvasModal.tsx`、`idea/`、`model.ts` 的 `Recipe`/`CanvasCard`/`NodeRun` 契约。
- `src/canvas/chrome/AssetsDrawer.tsx`：角色/媒体/白模三页，角色页用的是旧视角键常量。
- `src/library/Characters.tsx`：本书/我的/官方三档，`?char=` 深链已通。
- `app/static/admin.html`：侧栏分组 `g-home / g-src / g-world / g-trans / g-media / g-sys`。

前端 `npx tsc --noEmit` 当前零报错，这是本批实现的起点，不能在交付时退化。

---

## 2. 设计

### 2.1 A/B/C/D 导航与同一上下文

四个阶段取代当前 5 个平级视图。现有视图**不删除**，降为阶段内的面板，深链保留。

| 阶段 | 面板（现有 → 归属） | 新增 |
|---|---|---|
| A 故事与世界 | admin 的书架、世界模型、人物时期、译本、剧本转换 | 「一句话开始」最小生产容器入口 |
| B 素材与场景 | 角色库 `characters`、风格广场 `styles`、资产抽屉 | 资产中心总览；**B 自建素材画布** |
| C 导演与分镜 | 分镜画布 `canvas`、创作画布 `flow`、3D-BOX `box` | **C 自建导演画布**；镜头表 |
| D 成片与剪辑 | 现有合成章节、film 入口 | 成片时间线（本批只占位，不实现） |

**上下文的关键设计决定：地址栏是定位器，不是上下文本身。**

契约 §2 的 ProductionContext 有 15 个字段（含 scope、selection、return_to 等结构化对象），塞不进 URL，也不该由前端拼装——前端拼装等于前端第二次定义事实来源，违反契约 §1。

因此分成两层：

- **地址栏（前端拥有）**：`stage`（a/b/c/d）、`project`、`novel`、`chapter`、`plan`、`canvas`、`shot`、`box`、`char`、`from`。即现有 `ctx.ts` 的 9 键加 `stage` 与 `project`。只放可寻址的稳定 ID，不放版本、不放 selection。
- **解析后的上下文（后端拥有）**：`GET /api/v2/production/context?board_id=…&…` 返回完整 ProductionContext + readiness + issues。前端把它当只读事实，渲染顶栏（项目、生产世界、源版本、范围、画布、保存状态）与缺项提示。

`ctx.ts` 现有的级联清空规则保留并扩展：换 `project` 清 novel 及以下；换 `novel` 清 chapter 及以下。换阶段 **不清** 任何 ID——A→B→C 的意义就是带着同一上下文走，这是契约 §3「一键必须到达真实消费者」的前提。

`return_to` 不进地址栏：它是「画布/节点/面板/选择」的复合定位，由前端维护一个会话内返回栈，跳转时随请求带给后端用于 prepare 的 `return_slot`，回来时本地出栈。URL 只保留 `from=<stage>` 供整页刷新后的降级返回。

**阶段未就绪时不禁用整个工作区**（契约 §2 末句）：缺源内容时 A 仍可建最小容器，B 仍可建自建画布；只有确实需要某个源/实体/能力的按钮显示具体缺项。

### 2.2 B/C 自建画布的用途与创建流程

画布底层沿用 `StudioBoard` + `CanvasDoc`，不新建存储（方案 §11.1）。新增的只是 `purpose` 的语义与入口。

| purpose | 阶段 | 默认内容 | 典型来源 |
|---|---|---|---|
| `assets` | B | 空 / 角色定妆照模板 / 道具多视图模板 / 场景空间模板 / 素材组合 | B「新建素材画布」 |
| `directing` | C | 空 / 单镜 / 若干镜 / 一场 / 正反打 / 动作接续 | C「新建导演画布」、从 B「用于导演画布」 |
| `finishing` | D | 成片时间线 | D（本批不实现） |
| `general` | 任意 | 空白自由实验 | 现有 2 张自由画布迁入此值 |

创建流程（B 与 C 同构，仅模板集合与落点阶段不同）：

```
选模板 → 选范围（可空：自由画布）→ 命名 → POST /canvases{purpose, title, scope?}
      → 有模板则 PUT 初始 doc（base_version=0）→ 进入画布并写地址栏 canvas=<id>
```

模板只给结构与默认规则，**实体、事件、版本必须重新绑定**（方案 §11.1）。模板不预置任何具体 entity_id。

画布首页（B 与 C 各一个，数据源同为 `GET /studio/canvases`，按 purpose 过滤）：卡片显示封面、标题、用途标签、所属小说章节、节点数、更新时间。**删除画布只移除工作视图**，弹窗必须写明「不会删除角色、标准素材或已采用成片」（契约 §7）。

### 2.3 资产抽屉：引用真实实体 / 时期 / 单格

现有 `AssetsDrawer.tsx` 的角色页用旧视角键常量铺三张图。改造方向：

**页签**：人物 / 道具 / 地点 / 媒体 / 白模。道具与地点在真实数据为 0 条时显示「这本书还没有道具实体」的真实空状态，**不填演示卡**。

**每个角色一行，展开是 16 格**（见 2.4）。点单格 = 以 `ResourceRef` 放到画布：

```json
{"kind": "canonical_view", "id": "<resource_id>", "revision": "<rev>",
 "binding": {"entity_id": "...", "world_profile_id": "...", "epoch_id": "...", "view_key": "face_left"},
 "mode": "reference"}
```

画布节点存的是这个 ref，不是文件 URL（契约 §3：媒体 URL 只是显示地址）。现有画布节点的 `entity_view` ref 形状是 `{kind, id, view}`，缺 `revision` 与 `world_profile_id`——这是必须升级的点，见 6.3。

**三种操作在 UI 上分开，不合并成一个「添加」按钮**（契约 §7、方案 §3）：

| 操作 | 按钮 | 行为 | 版本语义 |
|---|---|---|---|
| 引用 | 拖拽 / 单击 | 放入 ref，`mode=reference` | 跟随该资源当前选定版本；出新版本显示「有更新」 |
| 快照 | 右键「固定当前版本」 | `mode=snapshot` | 锁在此 revision，不自动替换 |
| 派生 | 右键「另存为新素材」 | `mode=derived`，保留父版本 | 新资源，记录变更范围 |

**从角色库加入导演画布**：角色库详情页的「用于导演画布」→ 选现有 C 画布或新建 → 插入 ref + 建立人物实例 → 保留生产世界 → 跳转并选中新节点。不经过「下载再上传」。

**缺视角补建并返回原槽位**：槽位空时显示「补建」而不是灰掉。点击后记录 `return_slot = {board_id, node_id, slot}`，提交补建任务，完成后产物直接落回该槽位并高亮。目标接口是 `POST /production/prepare`；在它就绪前的过渡方案见 6.4。

### 2.4 16 格定妆照展示

按参考图 03 与方案 §5.1 的三分区布局，**三个分区并排**，不是一个 16 宫格：

```
┌─ 全身三视图 ─┐ ┌─ 头部四视图 ─┐ ┌──── 九宫格表情 ────┐
│ 前   后   侧 │ │ 正面   左侧  │ │ 喜   怒   哀        │
│              │ │ 右侧   后脑  │ │ 乐   惊   恐        │
│              │ │              │ │ 思   厌   疑        │
└──────────────┘ └──────────────┘ └────────────────────┘
```

固定键严格按契约 §4（注意与 `planA.md` §5.1 的差异，见 6.5）：
`body_front/body_back/body_side`、`face_front/face_left/face_right/face_back`、`expr_joy/expr_anger/expr_sad/expr_laugh/expr_surprise/expr_fear/expr_think/expr_disgust/expr_doubt`。

**每格的状态**：状态词汇以后端 `app/production/canonical.py` 实际产出为准，不自造：

| 后端 status | 格子表现 | 可做的操作 |
|---|---|---|
| （键不存在） | 虚线框 + 键名 + 「补建」 | 补建（整包，见 6.4） |
| `legacy_mapped` | 实图 + 角标「旧键 front→body_front」 | 引用、重画 |
| `legacy_approximate` | 实图 + **橙色**角标「近似映射 bust→face_front」 | 引用、重画（提示建议重画） |
| `bound_unreviewed` | 实图 + 角标「未审核」 | 引用、重画 |

`legacy_approximate` 必须和 `legacy_mapped` 视觉上区分开：前者是「拿头肩近景当正脸特写」这类将就，用户需要知道它不是真的那一格。

**本批不提供快照、派生、历史回退**（CR-03 裁定：后端只支持 `mode=reference`，无历史对象存储）。这三个入口**隐藏或禁用并注明「能力待接」**，不做成看起来能用的按钮。2.3 的三种操作表里只有「引用」在本批可用。

资源出新版本时后端返回 `revision_conflict`，UI 保留旧引用并提示用户选择是否采用新版本，不自动替换。

**拼版（`sheet`）是展示与导出资源，不是消费源**（契约 §4 末句、方案 §5.2）。UI 必须：拼版单独一栏并标注「展示用」；把拼版拖进镜头时弹出确认「拼版含多个人形与文字，通常应改用单格」，默认推荐单格。

**真实数据下的必然形态（2026-10-09 实测，用后端 `canonical_views()` 跑过全部时期）**：

| 角色 | 就绪格数 | 构成 |
|---|---|---|
| 谢文东、李爽、高个少年、徐娜、班主任、谢文东的父亲、谢文东的母亲 | **4/16** | `legacy_mapped` 2（body_front、body_back）+ `legacy_approximate` 2（body_side、face_front） |
| 班主任、徐娜的另一时期 | **1/16** | `legacy_mapped` 1 |

即：首次打开任何角色，正确画面是 **4 格有图（其中 2 格是近似映射）+ 12 格缺失 + 整包补建入口**，9 格表情全部为空。这不是 bug，是真实缺项。

验收口径：**看到 4/16 且两格带橙色「近似映射」角标 = 通过**；看到满格 = 接了演示数据，判缺陷。

### 2.5 角色库与资产中心的关系

角色库是资产中心的人物视图，**不是第二个身份源**（方案 §2 B 节）。现有 `Characters.tsx` 的「本书/我的/官方」保留，但：

- 「本书」项下每张卡显示 16 格就绪度（如「3/16」）与缺项数，点进去就是 2.4 的三分区。
- 详情页的操作区分「改这一期的造型」与「改全书实体」——契约 §4：用户改造型参数不得无说明改全书实体。
- 物理尺寸（身高/体型/惯用手）显示来源徽章 `text / inferred / default / user`；用户改过显示 `user` 且不再被推断覆盖。现有 `PATCH /stage/cards/{id}/physical` 已实现此语义。

### 2.6 admin.html 流程重组

侧栏从 6 个分组（`g-home/g-src/g-world/g-trans/g-media/g-sys`）改为 **A/B/C/D + 制作设置**。原页面全部保留为阶段内的详细面板，**URL 与数据不变**（方案 §2 页面结构）。

| 新分组 | 收纳的现有页面 |
|---|---|
| A 故事与世界 | console、library、world、model、culture、epochs、prompts、fidelity、reader、prose、review、script |
| B 素材与场景 | 角色库↗、风格广场↗、prompts（素材提示词台账） |
| C 导演与分镜 | storyboard、staging、crew、分镜画布↗、创作画布↗、3D-BOX↗ |
| D 成片与剪辑 | casting、audio、handoff |
| 制作设置 | tasks、settings、技能与模型配置 |

跳 Studio 的入口（已实现的 `App.openStudio(view, shot)`）改为带 `stage` 参数。本批只重排分组与补 `stage`，**不动页面内部逻辑、不改后端模型**。

---

## 3. 本批交付边界

交付（基线就绪后实现）：

1. `ctx.ts` 增加 `stage`、`project`；阶段切换不清 ID；返回栈。
2. `Nav.tsx` → A/B/C/D 四阶段 + 阶段内面板切换。
3. B/C 画布首页与新建流程（按 purpose 过滤与创建）。
4. `AssetsDrawer.tsx` 改造：人物/道具/地点/媒体/白模；单格引用；引用/快照/派生分开；缺项补建与返回槽位。
5. 16 格三分区组件 `CanonicalSheet`（角色库详情与资产抽屉共用）。
6. `Characters.tsx` 接 16 格就绪度与来源徽章。
7. `admin.html` 侧栏按 A/B/C/D 重排 + `stage` 参数。

不在本批：D 成片时间线、3D 导演台多轨（M2）、失效原因与影响范围 UI（M3）、剪辑与导出（M4）。

---

## 4. 演示数据规则

契约要求「开发 fixture 必须标记演示，仅供隔离 UI 开发，不能作为真实路径验收」。

现有 `?demo=1` 演示模式保留且必须满足：

- 演示模式下顶栏常驻「演示数据」角标（现已实现 `cv-demo-pill`）。
- 演示数据**不得**进入 16 格就绪度统计、不得用于任何交付截图。
- 本批所有验收截图必须来自真实库，并在交接中注明画布/实体 ID。

---

## 5. 与第三轮已有代码的关系

第三轮另一 agent 已落地 `NewCanvasModal.tsx`、`idea/buildIdeaGraph.ts`、`canvas_exec` 与 `char_sheet`。本批**不重写**这些文件，只做：

- `NewCanvasModal` 增加 purpose 选择与 B/C 模板集合（在其现有结构上扩展）。
- `char_sheet` 的 16 格产物接进 2.4 的展示组件（只消费，不改后端）。
- `model.ts` 的 `Recipe`/`CanvasCard` 契约沿用，新增字段走第 6 节变更请求。

---

## 6. 阻塞项与变更请求索引

请求原文见 `batch1_requests.md`，裁定见 `docs/studio/codex/handoff_batch1.md` §3。**8 条已全部裁定并有源码**（2026-10-09 02:27 Codex 写入，未运行验证）。

| 编号 | 裁定结果 | 对设计的影响 |
|---|---|---|
| CR-01 | `?board_id=` / `?novel_id=` 已写；三者只能选一；`project_id` 未实现 | 2.2 可做；无小说的独立项目容器仍不可用 |
| CR-02 | purpose 枚举化 + 重复值并集过滤已写；存量不回填，按 kind 推导默认值 | 2.2 可做 |
| CR-03 | 只支持 `mode=reference`；**snapshot / derived / 历史未实现** | **2.3、2.4 改为只做「引用」，另三项隐藏并注明待接** |
| CR-04 | 接受「整包生成」过渡方案；`prepare` **只做规划、不提交任务** | 2.3 补建按钮须写明是规划或整包，不能假装单格补建已完成 |
| CR-05 | 以契约 `expr_sad/expr_laugh` 为准；后端做权威别名适配 | 2.4 **UI 不建别名表**，直接用标准键 |
| CR-06 | 映射表已落地，区分 `legacy_mapped` / `legacy_approximate`；三分之四不冒充正侧面 | 2.4 状态表已按真实词汇改写 |
| CR-07 | `context` 源码已写；自由画布也需真实 `board_id` | 2.1 顶栏可接；读 `data.context`，不由 UI 推断 |
| CR-08 | 不造道具数据，空即空 | 2.3 道具页签保持真实空状态 |

**剩余真实阻塞**：只有 BASE_READY 未发布，以及这批源码**尚未运行验证**（见第 8 节）。CR 层面已无阻塞，UI 编码可在基线冻结后开始。

---

## 7. 本文事实的查验方式

| 事实 | 查验方式 |
|---|---|
| 端点存在性 | `grep "@router\.(get\|post\|…)" app/api/v2/*.py`；`curl http://127.0.0.1:8100/...` |
| `stage/cards` 必填 plan_id | `curl /api/v2/stage/cards` → 422 `plan_id Field required` |
| production 族不存在 | `grep -rn "api/v2/production" ainer-core/app ainer-studio/src` → 无匹配 |
| 实体与视角键统计 | 只读 SQLAlchemy 查询 `WorldEntity`、`AssetEpoch.reference_set_json`，结束 rollback |
| 画布与自由画布数 | 只读查询 `StudioBoard` |
| 前端类型状态 | `npx tsc --noEmit -p tsconfig.json` |

本轮只读查询，未写库、未提交生成任务、未重启服务。

---

## 8. Codex SOURCE_BATCH1 后的复核（2026-10-09 02:4x，Claude 独立查验）

Codex 于 02:27 写入第一批后端源码并裁定 CR-01…CR-08。本节是 Claude 的独立复核，只做静态与只读检查，未启动服务、未写库。

### 8.1 核实通过

| 项 | 方法 | 结果 |
|---|---|---|
| production 路由存在 | `grep @router` + `import app.main` 数路由 | 源码 8 条，注册成功 |
| char-sheets 已注册 | 同上 | 已注册（Codex 称此前未注册，核实属实） |
| CR-05 别名适配 | 读 `char_sheet.py:567`、`production/canonical.py:2` | `expr_sorrow→expr_sad`、`expr_happy→expr_laugh` 已在后端完成，UI 无需别名表 |
| CR-02 purpose 枚举 | 读 `canvas.py:707,753` | `Literal["assets","directing","finishing","general"]`，查询支持重复值 |
| CR-01 无 plan 素材卡 | 读 `stage.py:41-59` | `plan_id/novel_id/board_id` 三选一，缺失返回 `code: scope_required` |
| CR-06 旧键映射 | 读 `production/canonical.py:9-14` | 与 Claude 建议一致；`three_quarter_left` 未被映射（正确） |
| 16 格真实就绪度 | 只读调用 `canonical_views()` 跑全部时期 | 见 2.4 表：多数角色 4/16 |

### 8.2 必须注意的状态差

**运行中的 core 没有这些路由。** 复核时 8100 端口已无进程（此前本会话查验时在运行）。Codex 明确未重启服务，所以：

- 源码里有 = 接口可用，**不成立**；
- Claude 的 UI 实现在联调前，必须由集成方按 `planA_agents.md` §7 协调一次重启；
- Gemini 的接口测试同理，不能对着停掉的服务判失败。

### 8.3 Claude 据此调整的设计

1. 2.3、2.4：快照 / 派生 / 历史回退**改为隐藏并注明「能力待接」**（CR-03）。本批只做「引用」。
2. 2.4：状态词汇改用后端真实值 `legacy_mapped / legacy_approximate / bound_unreviewed`，并要求近似映射用橙色角标区分。
3. 2.4：缺项形态由估计值改为实测值（4/16，9 格表情全空）。
4. 2.3：补建按钮文案必须区分「整包生成」与「仅规划」——`prepare` 当前不提交任务。

### 8.4 仍未解决

- BASE_READY 未发布，Claude 仍不在 `src/` 落代码。
- 这批后端源码未运行验证；接口实际行为未知。
- `project_id` 级（无小说）入口未实现，B 的独立项目容器仍不可用。
