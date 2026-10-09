# Plan A 三方接口交接：v0.1

日期：2026-10-09。Owner：Codex。读者：Claude UI、Gemini QA。

R0/R1 第一批后端源码已写入；尚未重启服务或运行测试，不能等同已部署 API。具体路径、请求、范围与 Claude CR-01…CR-08 裁定见 [Codex 第一批交接](codex/handoff_batch1.md)。M2–M4 契约在对应批次前补齐。

最新用户修正与源码增量见 [自由画布第二批交接](codex/handoff_batch2_free_canvas.md)；三方按 [执行顺序](planA_execution_order.md) 推进。Gemini第一批模拟/关联测试报告已提交，本批变化尚未验证，不能沿用其QA_PASS宣布新建画布完成。

## 1. 不另建世界模型与执行器

复用 WorldEntity、AssetEpoch、Asset、StudioBoard、CanvasDoc、StudioNodeRun。production 层解析/编译真实对象，不把画布节点、译名或文件 URL当作实体身份。

保持现有端点可用；新增契约通过适配器统一返回。本文件不会宣布旧接口已实现它没有的字段。

## 2. 上下文与范围

ProductionContext 字段：

| 字段 | 约定 |
|---|---|
| `schema_version` | `ainer.production/v0.1` |
| `project_id` | 第一批为 `novel:<novel_id>`；无小说为 `board:<board_id>`，依托已持久化画布，不虚构独立项目表 |
| `novel_id / chapter_id / plan_id / script_doc_id` | 可空；有值时后端验证归属，不从标题猜 |
| `source_revision / transform_id / world_profile_id / production_language` | 固定生产源与表现世界；缺项显式列出 |
| `board_id / purpose` | 当前画布；purpose 为 `assets / directing / finishing / general`，区别于旧 kind 的 plan/scene/custom |
| `scope` | `chapter / scene / shots / custom`；包含对应 ID 列表；空白画布为 custom，不伪造章节 |
| `selection` | 当前资源、实例、事件、镜头、舞台、机位及时间；可空 |
| `return_to` | 画布/节点/面板/选择的返回定位；只能是应用内可解析定位 |

数据未完整时可保存草稿、引用可用素材；必须有源、实体或能力的操作报明确缺项，不统一禁用整个工作区。

独立空白不要求绑定小说/章/计划/世界。创建发送 `POST /studio/canvases {blank:true,source:"user"}`，title/purpose可省略，返回version1及真实空文档。不得携带plan_id或镜头/场次范围。创建后的首次保存使用返回version，不写死0。blank:false/旧请求保留原初始化语义。无源画布资源选择范围为同workspace；引用保留素材所属novel/世界/时期，不自动改变画布上下文。标准包/单格需明确binding中的世界和时期。已明确绑定小说/世界的画布仍执行一致性检查。

## 3. ResourceRef

```json
{
  "kind": "canonical_view",
  "id": "资源稳定标识",
  "revision": "固定版本标识",
  "binding": {
    "entity_id": "世界实体标识",
    "world_profile_id": "目标世界标识",
    "epoch_id": "时期标识",
    "view_key": "face_left",
    "instance_id": null
  },
  "mode": "reference"
}
```

`kind` 允许 entity、variant、canonical_pack、canonical_view、asset、event、stage、coverage、audio、run_output。`mode` 为 reference/snapshot/derived；reference也明确当前选定版本，新版本按策略更新，不用空版本掩盖依赖。

第一批实现 entity/variant/canonical_pack/canonical_view/asset/audio 的 reference 解析。其余种类、snapshot/derived、instance 覆盖明确返回未实现。首次发现资源允许省略 revision，解析后返回真实版本；新生产引用保存前必须有 revision。版本变化返回 unresolved/revision_conflict，不能静默改引用。canonical_pack/variant ID 为 epoch ID；canonical_view ID 为 `<epoch_id>:<标准view_key>`，revision 使用包查询返回的单格 revision。

Resolver 输出引用、显示名、资源状态、媒体（如有）、来源、缺项和实际可用视图。媒体 URL只是显示/传输地址，指纹依赖稳定资源版本。跨画布引用不用另一张画布 node ID作为资源 ID。

## 4. CanonicalAssetPack

包含：稳定 pack ID/version、EntityKind、entity_id、world_profile_id、epoch/variant、identity anchor、physical及来源、views、缺项、来源链与 adopted revision。

视图固定键：

- body_front、body_back、body_side。
- face_front、face_left、face_right、face_back。
- expr_joy、expr_anger、expr_sad、expr_laugh、expr_surprise、expr_fear、expr_think、expr_disgust、expr_doubt。

每格：view_key、asset_id、revision、media、可见侧/朝向/身体部位、来源参考、状态、锁定/采用信息。旧键由后端映射并记录；没有的格显式缺失，不补假 URL。标准拼版另存展示媒体，消费者仍引用独立单格。

本批状态：原生单格为 bound_unreviewed；旧 front→body_front、back→body_back 为 legacy_mapped；profile_left→body_side、bust→face_front 为 legacy_approximate。旧三分之四视图不伪装为正侧面，sheet 只作展示。旧 expr_sorrow/expr_happy 由后端映射为 expr_sad/expr_laugh。char-sheets 保留旧 key 兼容执行器，同时新增标准 view_key；UI 使用 view_key 绑定即可。旧照片的拍摄角度与身份质量仍需 QA，不因绑定就声明通过。

physical 字段区分实体默认、造型覆盖、实例覆盖与 text/inferred/default/user来源；用户改造型参数不无说明改全书实体。伤势等临时状态不写进永久参考包。

## 5. R0/R1 API 交接边界

| 操作 | 已有入口/新增设计 | 当前状态 |
|---|---|---|
| 创建/读取/保存画布 | `/api/v2/studio/canvases` 与 `/{board_id}`；PUT继续使用 base_version/doc，冲突409 | 已有源码；用途/统一上下文需扩展；本轮未运行验证 |
| Stage 素材卡 | `GET /api/v2/stage/cards?plan_id=...`；物理参数PATCH | 已有源码；当前依赖计划，不能称已支持空白画布 |
| 上下文 | `GET /api/v2/production/context?board_id=...` | 源码已实现；data 包含 context、board_version、readiness |
| 上下文保存 | `PATCH /api/v2/production/canvases/{board_id}/context` | 源码已实现；base_version/purpose/world_profile_id/return_to，沿用画布版本锁 |
| 解析引用 | `POST /api/v2/production/resources:resolve`，body `{context, refs}` | 源码已实现；顺序对齐，单项 unresolved 保留，整组上下文冲突409 |
| 素材包查询/绑定 | `GET/PATCH /api/v2/production/entities/{entity_id}/canonical-pack` | 源码已实现；GET指定 world_profile_id/epoch；PATCH见交接，验证独立单格并写入实际 AssetEpoch |
| 资产选择 | `GET /api/v2/production/resources?board_id=...&kind=entity|asset|audio` | 源码已实现；offset/limit、next_offset；包/单格从 canonical-pack 获得 |
| 准备缺项 | `POST /api/v2/production/prepare` | 仅复用/缺项规划已实现；jobs=[]、submission=not_implemented；submit=true 明确拒绝，尚无自动单格任务 |
| 使用位置 | `GET /api/v2/production/resources/{resource_id}/usages?board_id=...&revision=...` | 源码已实现；只查当前项目已保存节点 data.ref；coverage.complete=false，不冒充完整生成依赖索引 |

新响应采用 `{schema_version, data, issues}`；保留旧响应由客户端/后端适配。jobs返回真实 ID与状态，不同步等待长生成；不改现有端点为 incompatible envelope。

错误沿用可解析 HTTP状态：404缺失，409版本冲突，422契约/绑定缺项，能力不可用以明确错误码/问题返回。新错误 detail 至少包含 code/message/issues；旧字符串 detail保留适配。未就绪接口显示能力未就绪，不吞掉错误变成演示成功。

## 6. 时间与坐标

权威时间用整数 `*_ms`；传入渲染按明确 FPS转 frame_idx，时间区间 `[start_ms,end_ms)`，首帧0，最后一帧N-1。需保留 scene/edit/audio三种时间映射；不把渲染时长四舍五入误差当作剧情变化。

世界坐标米、Y向上、右手系；平面坐标 `[x,z]`；yaw角度单位度，遵守现有 SceneProtocol约定。身体左/右与屏幕左/右区分。前端、3D-BOX、Blender使用同一采样数据与转换。

## 7. 依赖与界面行为

只移动节点、改标题/分组不失效生成结果。改资源引用/版本则影响真实消费者；标记失效不自动运行。锁定 adopted 输出不被新参考或旧完成任务自动覆盖。

删除节点/画布与删除后端资源严格区分。引用不复制实体；资源派生保留父版本；缺失资源保存明确 orphan/missing状态，不新建同名角色顶替。

## 8. 变更记录与 ready 状态

- v0.1：2026-10-09，初始 R0/R1分工交接设计。没有部署或真实消费者验证声明。
- v0.1 源码增量：2026-10-09，第一批生产适配与标准包绑定；新增与已有路径详情见 Codex 交接。未进行测试、构建、服务重启、写库、生成或迁移。
- SOURCE_BATCH1：已写入共享工作区；不等同完整 R0/R1完成、部署或验证。
- SOURCE_BATCH2_FREE_CANVAS：自由画布修正已写源码；前端默认新建与实际UI验证待交付。分轮顺序与验收范围见执行顺序文档。
- BASE_READY：未发布。
- API_READY：未发布。Codex实现后记录具体端点、提交/契约版本和运行条件。
- UI_READY：未发布。Claude交付后记录同一契约版本及缺口。
- QA_PASS：未发布。Gemini对明确集成版本报告真实结果。

设计变更由Codex更新本文件；Claude/Gemini通过各自交接目录提出需求。下一批接口应在两方开始相关实现前列出，不根据本阶段空缺自行发明相互不兼容的路径。

## 第三批增量：单人接手自由画布与素材消费

2026-10-09，保持 schema `ainer.production/v0.1`，增加兼容字段与端点：

- `GET /production/entities/{id}/epochs?board_id=`：列真实已存世界/时期；board_id 可选，给了执行画布范围/世界检查。没有时期返回空列表，不调用生成。多时期必须由用户选择。
- `GET /production/resources`：增加可选 entity_kind；返回 `items[{ref,resource}]`、`next_offset`。素材 resource 增加 name（已有上传名称/元数据/ID回退）。客户端保持分页，独立画布不依赖 novelId。
- `POST /production/canvases/{board_id}/references`：`{base_version,ref,title?}`；引用已有的图片/视频/音频，行锁+画布版本检查+资源 revision/绑定检查。响应信封 data 包含 node_id、board_version、reused；仅写 source-backed ref，不写媒体副本，不提交生成。角色库从该入口加入任意目标画布。
- 生产引用保留 revision/mode/binding；消费者每次从真实源解析。版本冲突保留旧引用，显示原因；“采用素材最新版本”是显式操作，更新引用后不自动生成。复制这样的节点产生另一节点，仍引用相同源版本。
- `POST /studio/generate` 的 refs 每项可带 production_ref，target 增加 board_id；含生产引用时要求 board_id，服务端检查上下文、版本、源类型，使用真实 AssetURL/AssetID，忽略客户端缓存地址。源文件缺失阻止提交。旧请求仍可按原形状调用。
- 配方执行器支持生产引用和分组展开；source ref 的版本传递进入 recipe hash。选择一个下游运行时，其已失效的上游配方也会重新排队。服务端现取源与版本检查不依赖前端展示缓存。
- `POST /studio/char-sheets` 增加 binding `{entity_id,epoch_id,base_revision}`；先检查角色/时期、锁定与版本。后台生成完成后以行锁/版本检查写回标准包；新图先保留，绑定冲突不会覆盖更新过的造型，任务携带已生成 panels/sheet 与错误。未给 binding 的旧调用保持原生成方式。此入口仍是内存任务记录，重启恢复尚未实现，不等同 production/prepare 单格调度。
- canonical-pack 的 physical 与 stage/card 共用估算规则；仅 source=user 是用户标定，inferred/default 不能冒充真实测量。物理值参与包版本。
- 自由画布默认 blank:true/general，独立于当前分镜；初始保存使用创建响应版本。首页/切换器列全部画布；无节点显示编辑入口。音频节点支持上传/引用/播放/保存，不声称生成入口已支持音频驱动。

第三批状态：前端构建通过、后端语法解析通过；服务已重载记录在运行文件中。未运行功能测试、真实界面验收或媒体生成，本批不发布 QA_PASS。详细限制见第三批交接。

## 共享舞台增量契约

新增独立 ainer.shared-stage/v0.1，路径 /api/v2/production/stages；沿用 DirectorScene.protocol_json 作为执行源、notes_json 保存事件/覆盖与引用。StageContent + base_version 乐观版本/行锁；coverage 分开 clip_duration_ms 与 scene_start_ms/scene_end_ms，导出 sceneTimes。SceneStage 作为上游编译输入，from-narrative 经来源/尺寸/时间检查进入共享舞台。通用 kind=stage/coverage resolver 与生成适配仍待接通。完整路径、输入和消费清单见 [第四批交接](codex/handoff_batch4_shared_stage.md)。

## 9. 电影级分镜与视频生成硬性规范（Cinematic DP & Montage Hard Specifications）

日期：2026-10-09。依据用户硬性审查裁定（CR-10）：杜绝动作半截截断与同机位重复跌倒顿挫（Double-action Stutter）。

### 9.1 片段时长硬性上限（Max Segment Duration Limit）
- **单镜头片段最长为 5.0 秒，严禁超过 5.0 秒（`segment_duration_sec <= 5.0`）**。
- 无论通过快速成片（`quick_film`）、电影导演摄影指导（`cinematic_director`）还是底层 LTX-2.5 视频模型调用，超过 5.0s 的分镜必须在规划阶段强制截断/拆镜，禁止直接向视频模型提交 $> 5.0\text{s}$ 的单段生成（保障扩散模型潜空间稳定性并维护紧凑蒙太奇节奏）。

### 9.2 动作完整性与分切防重演规范（Cut-on-Action & Anti-Stutter Standard）
- **动作完整性**：主干技术动作（如高速刻雪、大回转、奔跑炫技）必须在单镜头内作为独立长帧完整呈现（上限 5.0s），禁止在动作未完成或失衡瞬间半途截断。
- **动作转折必须分切（Cut on Action / Perspective Jump）**：
  - 一旦发生动作性质的剧烈转折（如从高速滑行转为跌倒摔雪、从奔跑转为受击），**严禁使用同机位尾帧硬接（`continuation`）**，否则扩散模型将从上一镜尾部姿态重演跌倒，造成灾难性的“同机位重复跌倒两次”顿挫！
  - 必须采用**果断切镜头（Cut）**，并**剧烈改变景别与机位视角**（如从远景 WS 切入贴雪特写 CU，时长 1.5~2.5s），利用视点骤变打破视觉惯性，吸收微小动作不连续性。
- **恢复与收尾阶段（Recovery & Ending Shot）**：
  - 人物从冲击/摔倒姿态恢复（如雪地撑起、站立拍雪），必须通过中景/全景分切（MS/WS，时长 2.5~4.0s，$\le 5.0\text{s}$），配合镜头平缓后拉（Dolly pull-out）展现环境全景，完成视听语言的闭环。

### 9.3 经典蒙太奇三段式节奏模板（5s 炫技 + 2s 特写 + 3s 收尾）
| 镜头序号 | 景别 / 视点 | 时长限制 | 运镜规范 | 剪辑转场 | 动作与叙事职责 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Shot 1** | WS 远景 / 视平 | **$\le 5.0\text{s}$** | 手持跟镜 (handheld_tracking) | Cut 出发 | **完整技术长帧**：流畅大回转刻雪，动作饱满不提前跌倒 |
| **Shot 2** | CU 特写 / 低角度贴地 | **$\le 2.0\text{s}$** | 低机位平移追随 (low_angle_pan) | **Cut 分切（严禁尾帧直连）** | **动作转折爆点**：视角骤变，极速扑雪、雪浪爆发与情绪释放 |
| **Shot 3** | MS 中景 / 视平 | **$\le 3.0\text{s}$** | 匀速后拉 (dolly_pull_out) | **Cut 分切** | **情绪释怀收尾**：撑雪稳稳站立、拍打雪服，后拉展现全貌 |


## 第五批引用增量（2026-10-09）

stage/coverage ResourceRef 现在可解析并加入画布。coverage.id=`stage_id:coverage_id`，按首个冒号拆分；binding 不接受实例/造型覆盖。revision 为舞台 StageContent 加所选 coverage 的内容摘要，独立于 board_ids；资源返回真实舞台行版本、原子依赖与消费状态，不是媒体 URL。严格引用预演/导出分别为 `/api/v2/production/stages/reference-preview`、`reference-bake`，请求 `{board_id,ref}`。后者返回冻结版本的真实逐帧数据与来源包；视频未提交。旧生成入口遇到共享舞台控制返回 stage_control_not_supported，不允许静默丢弃。详见 codex/handoff_batch5_stage_canvas_refs.md；独立验收尚未执行，后台加载因现有任务暂缓。
