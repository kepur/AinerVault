# 创作画布（纳逗式节点画布 + 3D 白模）

Ainer Studio 的第二个视图：`/studio/?view=flow`。

- **一章多张画布**：第一次打开某份分镜时，后端按场次自动分好；镜头多的场次再按镜数均分成几张（`1. 走廊抢劫（1/2）`）。另有一张「整章总览」，也可以自建空白画布、把选中的镜头单独建一张。
- 剧本场次、镜头、定妆照（本章出场角色）、3D 白模，都按场次泳道自动摆出来；可以自由加文本、上传图、生成节点、连线。
- **一键出片**：整张画布（或选中的几镜）从定妆照、场景图出分镜图（关键帧），再交给 LTX 2.5 出带声视频，挂回镜头；分镜画布和章节合成用的是同一个视频。

原始实现规格：`creative_canvas_spec_v1.md`。下面写的是**落地后的现状**，和规格不同的地方以这里为准。

## 怎么打开

| 场景 | 地址 |
|---|---|
| 开发 | `npm run dev`（5174；`/api`、`/media`、`/admin`、`/health`、`/docs` 都转给 8100 的 core），打开 `http://localhost:5174/studio/?view=flow` |
| 演示（不要后端） | `?view=flow&demo=1`。内置《滑雪少女的穿越》，多张画布、一键出片都按时间模拟；存档在浏览器 localStorage |
| 正式 | `npm run build` 后由 core 在 `/studio` 提供（后台的「Studio …↗」入口落在这里） |

后端迁移：`e2b6d4a9c3f1_studio_boards`（`alembic upgrade head`），新建 `core.studio_boards`（画布）和 `core.studio_runs`（一键出片）。

## 出片流程（一键出片 / 出分镜图）

借鉴纳逗：**定妆照 + 场景图 → 分镜图（关键帧）→ 视频模型钉住这张图出片**。白模是可选的，只在要精确控制站位和运镜时用。

| 选项 | 取值 | 说明 |
|---|---|---|
| 方案 `method` | `keyframe`（默认）/ `director` | keyframe：FLUX 按定妆照和场景图画关键帧，再出片。director：LLM 搭 3D 白模 → Blender 预演 → 身份首帧 → LTX |
| 引擎 `engine` | `local`（默认）/ `cloud` | local：FLUX.2-klein-4b-edit 800×480 + LTX-2.5 22B distilled Q8。cloud：qwen-image-edit-max + wan2.7-i2v（要花钱） |
| 档位 `profile` | `fast`（默认）/ `hd` | fast = 768×448，本机最快的一档 |
| 声音 `audio` | `auto`（默认）/ `generate` / `none` | auto：有对白先配音再驱动口型（a2v），没对白让 LTX 自带环境声 |
| 出到 `stop_after` | `frame` / `video`（默认） | frame：只出分镜图，在画布上审过再出视频（顶栏「一键出片」里默认选这个） |
| `reuse_frames` | 默认 true | 已经画过的分镜图不重画，直接出视频 |
| `shot_ids` | 可选 | 只跑这几镜（多选工具条「出分镜图（N 镜）」、右键菜单用它） |

单镜入口：选中镜头 → Dock 或右键 →「出分镜图 / 分镜图出片」（默认），备选「3D 导演出片 / 按白模重出 / 文字预览 / 文字出片」。

关键帧提示词的规则（`app/pipelines/keyframe.py`）：

- 人放最前、按参考图顺序对应；多人镜头写死人数、不许重复（klein 会把同一个人画两遍）；
- 特写（ECU/CU）只给焦点人物一张头肩照；其余镜头焦点人物在前，最多 3 人；
- 运镜句子不进关键帧（关键帧是一张静态图）；视频提示词里特写镜头的环绕、大幅推拉会被压成慢推（`tame_camera`）；
- 有场景图时用它当底图，保持场景可识别。

## 给其他系统调（旅拍、相册、小说都走这一套）

| 接口 | 作用 |
|---|---|
| `GET /api/v2/studio/chapters/{id}/canvases?plan_id=` | 这一章的画布列表（第一次调用时自动按场次分） |
| `POST /api/v2/studio/plans/{id}/canvases:split` | 重新按场次分 |
| `POST /api/v2/studio/canvases` | 新建画布（`kind=custom`，`scope.shot_ids` 指定镜头） |
| `GET/PUT/PATCH/DELETE /api/v2/studio/canvases/{id}` | 读写画布文档（`version` 乐观锁，409 冲突） |
| `GET /api/v2/studio/shots/{id}/canvas` | 某一镜所在的场次画布 |
| `POST /api/v2/studio/canvases/{id}:run` | 一键出片（body 见上表），返回 run |
| `GET /api/v2/studio/runs/{id}`、`POST …:cancel` | 进度（每镜 `step` audio/frame/video/director/done）、取消（穿透到网关） |
| `POST /api/v2/characters/e:{实体id}:references` | 小说角色一键重出定妆照（本机：正面全身 → 其余角度 → 设定图） |
| `GET /api/v2/characters?scope=book&novel_id=` | 这本书的角色卡（没有定妆照的也列出，标 `missing`） |
| `GET /api/v2/scene3d/projects?plan_id=` | 这份分镜里导演出片搭的白模（每项带 `shot_id`、`shot_order`） |

分镜画布的 `GET /api/v2/studio/plans/{id}/board` 每镜多了 `canvas_id`（所在场次画布）和 `canvas_run`（一键出片正跑到这一镜）；有 `canvas_run` 时分镜画布每 6 秒刷新。

## 视图之间的上下文（`src/ctx.ts`）

所有视图共用一套地址栏参数，顶部 Nav 切换时原样带过去，各视图挂载时现读：

| 参数 | 含义 |
|---|---|
| `view` | canvas 分镜画布 / flow 创作画布 / box 3D-BOX / characters 角色库 / styles 风格广场 |
| `novel` `chapter` `plan` | 书、章、分镜计划 |
| `canvas` | 当前创作画布 |
| `shot` | 当前镜头（旧链接的 `focus` 兼容读取，读到后改写成 `shot`） |
| `box` `from` | 白模项目；3D-BOX 编辑器「←」回哪个视图 |
| `char` | 角色卡（`e:<实体id>` 或 preset id） |

- 换书清章、计划、画布、镜头；换章清计划、画布、镜头；换计划清画布、镜头（不然风格广场会把预设套到上一章的计划上）。
- 两个画布选中镜头都会写 `shot`；带着 `shot` 进创作画布，若当前 `canvas` 不含这一镜，会落到它所在的场次画布并选中它；进分镜画布会选中并飞到这一镜。
- 3D-BOX：带着 `plan` 进来默认只列本章白模（「本章 / 全部」切换），卡片上「镜 N ↩」回创作画布；从画布跳进编辑器，「← 创作画布」回原处。
- 角色库：带着 `novel` 默认进「本书」；`char` 直接打开角色详情。
- 后台：左栏有五个「Studio …↗」直达入口；分镜全景每镜有「分镜画布定位 ↗」「进创作画布 ↗」。Studio 的「后台 ↗」按视图落到分镜全景 / 章节工作台 / 世界模型。

## 画布上的编辑

- **删除**：Delete / ⌫ / ⌘⌫，工具条和右键都有。剧本、镜头、定妆照、白模这类派生节点只是「从画布拿掉」，后端还在；底栏「已拿掉 N」能逐个或全部放回，⌘K 搜索也能搜到并放回。可以撤销。
- **清理空节点**：误加的空生成节点（点了「生成」却没发过提示词）底栏一键清掉。
- **右键菜单**：节点（和工具条同一套动作）、多选（出分镜图、钉住、删除）、连线（派生连线不能删，会写原因）、空白处（添加、搜索、整理、全选、放回、清理）。
- **⌘A** 全选。
- 标题和卡片等宽，放不下省略、悬停看全名；角色的默认时期（baseline）不再挂角标；音色角标是 ♪。
- 定妆照「更多 → 重出定妆照」：画坏了（多出手、背景不是灰底）就重出，出完重画分镜图才换上。

## 文件

前端 `code/apps/ainer-studio/src/canvas/`：

| 文件 | 作用 |
|---|---|
| `model.ts` `contract.ts` `api.ts` | 数据契约、store 形状、全部后端调用（演示模式整体接管 `cv.*`） |
| `store.tsx` | 画布列表 / 载入链、受控图、保存、唯一轮询器、一键出片跟踪、拿掉 / 放回、快捷键 |
| `importer.ts` | 派生节点全集与自动布局（按画布的 `scope` 过滤） |
| `actions.ts` | 每种节点的动作（工具条、右键、Dock 共用）；镜头出片方式 `shotMethods` |
| `chrome/*` | 顶栏（画布切换、一键出片、合成章节）、节点工具条、右键菜单、底栏、Dock、搜索、新增菜单、资产抽屉 |
| `nodes/*` `edges/*` `three/*` | 四种节点、连线、白模实时视口 |
| `demo.ts` | 演示数据和模拟后端 |

画布外：`src/ctx.ts`（地址栏约定）、`Root.tsx`、`Nav.tsx`、`App.tsx`、`components/Canvas.tsx`、`components/Inspector.tsx`、`box/BoxHome.tsx`、`box/BoxEditor.tsx`、`library/Characters.tsx`。

后端 `code/apps/ainer-core/`：

| 文件 | 作用 |
|---|---|
| `app/api/v2/canvas.py` | 画布 CRUD、按场次分、镜头所在画布、兼容旧的 `plans/{id}/canvas` |
| `app/api/v2/canvas_run.py` + `app/pipelines/canvas_run.py` | 一键出片：后台线程按镜推进（audio → frame → video / director），core 重启后接着跑 |
| `app/pipelines/keyframe.py` | 关键帧方案：选人、提示词、提交 FLUX / 视频 |
| `app/pipelines/char_refs.py` | 一键重出定妆照（后台串三步） |
| `app/api/v2/canvas_gen.py` + `app/capability/generic.py` | 自由生成节点 |
| `app/models/studio_board.py`、迁移 `e2b6d4a9c3f1` | `studio_boards`、`studio_runs` |

## 铁律（审查按这个打回）

1. **画布只存布局**：派生节点只存引用和视图状态（标题、钉住、机位、实时），内容每次现取。
2. **文档里只许 `/media/…` 同源地址或 `data:`**：后端 PUT 会拒掉网关临时地址。
3. **做不到的能力按钮灰掉并写原因**，不假装能用（选段创作、声音分离、超清等）。右键菜单里「更多」下灰掉的不列。
4. 定妆照在画布上只读；改外观去角色库造型室，画坏了用「重出定妆照」。
5. 所有长任务登记进 `store.tasks`，由唯一轮询器推进。节点不许自己 `setInterval`。
6. **主画布首包不带 three**：`BoxPreview`、`BoxEditor`、`Stage`、`box/CameraView` 都要动态 import；`box/director` 只能 `import type`。
7. 跨视图链接一律走 `ctx.ts` 的 `hrefFor` / `navigate`，不手拼地址。

## 实测记录

- 2026-10-08 镜 6、7（一键出片，keyframe + LTX）：关键帧约 90 秒（含 ComfyUI 载模型）；镜 6 a2v 3.7 秒（推理 207 秒）。问题：镜 6 特写画成两人正脸、环绕运镜让视频崩掉；镜 7 血从眼睛流出。已修：特写只给焦点人物、关键帧去掉运镜句、视频提示词压运镜。
- 2026-10-08 第 1 场前半 14 镜只出分镜图（`stop_after=frame`）：每镜 85–135 秒。镜 3 很好；镜 1 三人画成四人（被霸凌者重复），根因之一是李爽的定妆照本身画坏了（四只手）。已加人数约束，李爽定妆照要重出。

## 待办

- 尾帧：关键帧方案目前只画首帧。
- 视频提示词的运镜让 LLM 再审一遍（现在是规则压制）。
- 相册 / 旅拍的预设演员：用户自己的照片做人物卡，走同一条「定妆照 → 分镜图 → 出片」。
- 18 句对白还没有绑定音色。
- 章节合成按画布范围、异步出。
- 「用白模出片」只支持该镜导演链自己的白模。
- 3D-BOX 老项目的 `shot_plan_id` 等列是空的（列表靠镜头反查，不影响使用）；要回填数据库需要确认。

## 2026-10-09 自由画布接手增量

默认新建进入空白页，不带当前 plan，不要求小说/图片/AI 规划。顶部“我的画布”列出独立与章节画布；切换前先保存，保存失败保留当前内容。独立画布从 production/resources 分页引用真实工作区素材。角色标准单格带实体、世界、时期和版本，重开/生成从源解析；角色库也能直接选择目标画布并加入单格。音频可上传、播放、保存，音频驱动生成仍未接。

本批源码、接口、角色整包回写、运行加载记录和验收边界见 `codex/handoff_batch3_solo.md`。已构建并加载服务，未由 Codex 运行功能或媒体测试。旧 entity_view 的配方消费仍有适配缺口，完整共享舞台/时钟/运镜改造不在本批完成状态内。

## 2026-10-09 共享舞台增量

创作画布顶栏“共享舞台”可从空白手工创建实例、机位、动作和覆盖；多个镜头与画布复用同一场景协议。来源角色的世界/时期引用、统一站位采样、首中尾预演与逐帧数据导出均有真实接口。外部白模改动需明确采用，避免双源覆盖。Gemini 的剧情舞台编译已衔接持久化入口，旧 state-at 物理站位也取同一运行时。功能和媒体验收仍交 Gemini；持物/特效状态、通用节点 DAG、最终视频与完整物理控制不属已通过范围。见 codex/handoff_batch4_shared_stage.md。


## 2026-10-09 第五批：舞台/镜头画布引用

共享舞台已增加舞台/镜头引用节点、上游标准角色视图/道具连线、同源机位与时间的首中尾预演和严格版本控制包导出。素材/舞台过期需明确修复和采用；未支持的共享控制不会被媒体生成器静默忽略。前端构建和后台静态导入通过，独立验收仍交 Gemini。预检时后台有一个生成任务，未重启，新增后台接口待任务结束加载；最终视频控制消费未完成。见 [第五批交接](codex/handoff_batch5_stage_canvas_refs.md)。
