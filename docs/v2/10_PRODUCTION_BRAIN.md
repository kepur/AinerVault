# 10 · 制作脑在 AinerHub 的落位与改造路线

- 状态：设计草案 v0 · 2026-10-15 · 起草：Claude（Relay 任务 hub.P1.A1）· 待 Codex 平级审议
- **第 3 节已由用户决定（D-012，同日）：选甲**——一个逻辑世界系统，按状态类型统一权威，代码不搬。正式记录见 AWZ `RESEARCH_LOG.md` D-012 和 `docs/adr/ADR-0011-three-systems.md` 修订一；统一变更协议任务是 awz.P3.E3。
- 依据：用户决定 D-011（`~/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0011-three-systems.md`）——顶层三个系统：制作脑（影视创作与控制）、世界系统（AnimeWorld）、世界脑（AinerZero）；制作脑代码归 AinerHub。总目标见 `~/AinerWorkFlow/AnimeWorldZero/docs/NORTH_STAR.md`。
- 本次只读代码和文档，新增了本文件这一个文件，没有改任何已有文件，没有重启服务，没有运行测试或生成。下文的“已有”指源码和文档里有，**不等于已独立验收**。

## 0. 结论

1. **AinerHub 已经有制作脑的大半骨架**：
   - 剧本编译（ScriptDoc、ShotPlan）；
   - 世界观转译；
   - Director（LLM 规划、JSON Patch 改稿）；
   - 舞台与镜头覆盖（SceneStage、CoverageShot）；
   - 动漫路线原型；
   - 逐镜质检闸门。

   缺的是：NarrativeIR（剧情语义层，Plan A 评审已提出）、技法库、审片标准、沉浸与交互叙事、专项小模型。
2. **AinerHub 还长出了半个世界系统**：`app/worldmodel` 的持久世界库（World DB）已经能做：
   - 区域、地标、通路、实例、事实与版本；
   - 增量的提议、应用、拒绝；
   - 一场一演、每镜一个 take；
   - Blender 无头世界检查和多机位渲染。

   AWZ 有世界系统的另一半：确定性内核、事件、ACIS 身份、风格包、门禁、考场，加上刚起草的世界指令协议（awz.P3.E1）。
3. **不处理的话会出现三份重复**：
   - **两套世界真值**：AinerHub World DB 与舞台，对 AWZ 的世界源与时间线；
   - **两套变更协议**：AinerHub `WorldDelta`，对 AWZ `WorldCommand`；
   - **两条 Blender 通道**：AinerHub `director/blender_worker` 与 `worldmodel/blender_run`，对 AWZ 计划中的 P3-A1/A3。
4. **建议**：逻辑上只有一个世界系统、一套变更协议、一条渲染通道；代码先不搬。权威怎样划分见第 3 节，**需要用户拍板**，因为它会修订 D-011 第 2 项“世界系统负责控制编译与校验”在代码位置上的含义。

## 1. 制作脑 11 个技能组对应 AinerHub 的现有组件

| 技能组（模块树编号） | 现状 | AinerHub 现有组件（路径相对 `code/apps/ainer-core/app/`） | 缺口 |
|---|---|---|---|
| 4.1 创作要求与剧本理解 | 已有 | `pipelines/screenplay.py`（ScriptDoc：场景、Block、说话人）；小说、章节、翻译九张表；`worldview/`（世界观转译 L1–L4） | `screenplay.py` 有第六批回归未修，60 项测试失败，归 Codex 写区（见 TASK_STATUS） |
| 4.2 编剧与叙事 | 部分 | ScriptDoc 结构 | **NarrativeIR 没有**：谁、做什么、为什么、改变什么、观众必须看到什么（`planA.review.md` 第 2 节 A、R0） |
| 4.3 导演与场面调度 | 部分 | `director/planner.py`（自然语言转场景，修改指令转 JSON Patch）；`stage/`（SceneStage 节拍、`state_at`）；`worldmodel/llm_build.py`（章节转世界增量与表演草稿，只提议） | 导演意图（为什么看谁）没有结构化 |
| 4.4 摄影与剪辑 | 部分 | `stage/schema.py` CoverageShot；`worldmodel` 的 take（机位、时间窗）；`worldmodel/staging.py`（按已审首帧拟合相机）；director 运镜操作 | 剪辑语法还没拆成 `edit_type`、`continuity_mode`、`pixel_reuse_allowed`（`planA.review` 第 2 节 B 已提出） |
| 4.5 美术、装造与道具 | 部分 | WorldEntity 的视觉提示与参考图；`stage/cards.py` 素材卡；世界观 L4 视觉变体；`scripts/anime_npr_poc.py`、`anime_repaint_poc.py`（路线 A/B） | 美术规范、色板与装造的版本化；路线 A/B 都还没达到参考水平（`var/world_greybox/anime_routes/README.md` 自评） |
| 4.6 表演与声音指导 | 部分 | `worldmodel/motion.py`（Mixamo 骨架动作库）；`worldmodel/dialogue_route.py`（配音驱动对白、Rhubarb 口型）；音色档案 | 表演意图与情绪曲线没有结构化 |
| 4.7 沉浸、交互叙事与导播 | 没有 | — | 全部 |
| 4.8 审片与监工 | 部分 | `worldmodel/qa.py`（逐镜质检闸门，数值化的代理指标）；`worldmodel/ab_metrics.py`（CCIP、CLIP、对白 A/B） | 审美与叙事的审片标准（hub.P1.C1）；v1 的 Critic 套件被冻结 |
| 4.9 知识库与技法库 | 部分 | 世界观知识库（RAG，名物转译的证据链，已撤销冻结）；`presets/`、`prompts.py` | 技法库没有（hub.P1.B1） |
| 4.10 制作计划契约与控制编译 | 部分（多套并存） | `ainer.scene/v1`（`director/protocol.py`）加 `director/patch.py`；SceneStage 编译为 SceneProtocol（`stage/compile.py`）；`world_take.json`（`worldmodel/compile.py`） | 格式过多，NarrativeIR 尚未建立，见第 4 节 |
| 4.11 专项小模型 | 没有 | 只有 A/B 指标 | 全部 |

和制作脑方向相冲突的两条 v2 冻结（`docs/v2/00_OVERVIEW.md` §2.4）：
- **Critic 评估套件**和**反馈进化环**被冻结（“质检交给人眼”）。制作脑要持续学习，需要审片记录和反馈闭环，但不必解冻旧代码：可以用 hub.P1.C1 审片标准加上制作记录，重新做一个轻量版本。
- **修改历史版本树**被冻结。世界指令协议（只追加的 revision 链）可以替代，不需要恢复旧 NLE。

是否在 v2 框架里重新开放这两项，由 AinerHub 负责人和用户决定。

## 2. 世界系统的职责现在分在两个仓库

| 职责 | AinerHub | AWZ |
|---|---|---|
| 持久世界与版本：区域、地标、通路、实例、事实、版本、增量 | **已有**：World DB（`worldmodel/service.py`，表前缀 `world_`）。版本单调递增；`base_version` 不等就标冲突；事实带 `evidence_span`，来源分原文明示、推断、用户 | 世界指令协议草案（awz.P3.E1，未实现）；`.aworld`（P3-E2）未开始 |
| 时间与状态求值 | `stage/compile.py` 的 `state_at(stage, t)`；表演轨（关键帧加动作片段） | 内核 120Hz 闭式求值、计数随机数、状态日志与哈希（R1 已验收） |
| 碰撞、可达、导航 | `worldmodel/geometry.py`（AABB、可达性）；Blender 侧 `world_check`（碰撞、可达、视锥、朝向），带确定性修正 | `kernel/collision.py`（只校验预编轨迹） |
| 动作与骨骼 | `worldmodel/motion.py`（Mixamo 命名） | 解析行走 |
| 身份 | WorldEntity 加 `director/identity_frame.py` | ACIS 身份包 v1 加 Gate ID（限范围验收） |
| 风格 | 预设和路线 A/B 原型 | 风格包 v1 加 Gate S（限范围验收） |
| Blender 渲染 | `director/blender_worker`（首帧、遮罩、可见性采样）；`worldmodel/blender_run.py`（world_multicam：clay、depth、pose） | 计划：P3-A1 渲染契约、P3-A3 Blender 最小切片 |
| 世界脑考场 | — | Bridge、episode、课程（T10，D-009 挂起） |

两边都把“生成的画面不回写成世界事实”定为规则（`world_greybox_pipeline.md` §2、ADR-0003），方向一致，只是实现分在两处。

## 3. 需要用户决定：世界系统怎样合成一个

**选项甲（推荐）：一个逻辑世界系统，按状态类型划分唯一权威，代码先不搬。**

| 状态类型 | 唯一权威 | 另一边的角色 |
|---|---|---|
| 持久世界（区域、地标、通路、实例、事实、版本） | AinerHub World DB（最成熟；作为 `.aworld` 的存储实现候选） | AWZ 从指定版本的快照导出世界源再编译，不自存一份 |
| 运行与确定性求值（时间、事件、规则、交互运行、快照重算） | AWZ 内核 | AinerHub 的 `state_at` 和表演求值逐步改为调用 AWZ 编译结果，或用黄金日志做一致性测试 |
| 身份与风格 | AWZ 的 ACIS 身份包和风格包 | AinerHub WorldEntity 用 ID 引用，不另存一套锁定参数 |
| 变更协议 | 一个信封：AWZ 世界指令协议并入 AinerHub WorldDelta 的操作族（第 3.1 节） | 两边各自实现同一份 schema |
| Blender 渲染 | 一条通道：以 AinerHub 现有 worker 为起点，抽象出 RenderBackend 契约（P3-A1） | AWZ 的 P3-A3 改为复用，而不是重写 |

**选项乙**：整个世界系统归 AinerHub，AWZ 退为内核库、身份与风格门禁、世界脑考场。

**选项丙**：整个世界系统归 AWZ，AinerHub 的 World DB 迁过去，AinerHub 只留制作脑。

推荐甲：两边已有的成熟部分都保留在原地，只统一权威和协议，搬动代码的风险最小。代价是跨仓库协作，契约必须先冻结。

### 3.1 变更协议怎样合一（若选甲）

- AinerHub `WorldDelta` 的字段是：`base_version`、`ops[]`、`status`（proposed / applied / rejected / conflict）、`chapter_id`、`evidence`。AWZ 草案的字段是：`expected_revision`、带 `test` 前置的 JSON Patch、`class`、预览令牌、逆补丁。
- 合并后的结构：
  - **信封共用**：版本号、操作者、来源与证据、状态、预览与提交、撤销与回滚；
  - **操作分两族**：持久世界操作沿用 AinerHub 的 `add_region`、`move_instance` 等；场景和表演用 JSON Patch。
  - “提议”就是预览，“应用”就是提交。
- AWZ 草案里“四类修改各自只能改自己的派生摘要”这条可测试规则保留；持久世界操作一律归 `world` 类。

## 4. 契约谱系：制作计划和现有格式的关系

建议只有一条谱系，不新造平行格式：

```text
ScriptDoc（剧本） ─► NarrativeIR（叙事：事件、因果、观众须见）
                       ─► SceneStage / ScenePerformance（表演：一场一演）
                           ─► CoverageShot / Take（镜头：机位、时间窗、转场三字段）
                               ─► ainer.scene/v1 · world_take.json（执行：交给世界系统和渲染）
```

- **制作计划（awz.P3.J1）是包在这条谱系外面的信封**：加上创作要求、美术计划、体验计划、技法引用、锁定字段，以及执行反馈的链接。它引用上面各层，不复制它们。
- J1 应以这条谱系为输入；NarrativeIR 本身按 `planA.review` R0 在 AinerHub 实现。

## 5. 改造路线（只排顺序，不排工期）

1. **R0 用户决定第 3 节**（甲、乙或丙）。决定之前，AWZ 的 P3-I1、I2、E2 和 P3-A1、A3 不宜开工，免得造出第三份实现。
2. **R1 统一变更协议**：选甲时，合并 E1 和 WorldDelta 的 schema，两边各写一致性测试。
3. **R2 统一渲染通道**：P3-A1 渲染契约以 AinerHub 现有 worker 为参照，P3-A3 改为复用。
4. **R3 叙事层与制作计划**：NarrativeIR（AinerHub）加制作计划信封（J1）。
5. **R4 技法库与审片标准接入质检**：hub.P1.B1、B1 的复核 B2、C1。
6. **R5 用统一链路做验证**：先拍小房间，再加书包变形，然后同一段出悬疑版和喜剧版。

始终不碰：
- v1 冻结代码；
- Codex 写区（`pipelines/screenplay.py` 的回归归 Codex）；
- 下面列出的他人未提交改动。

## 6. 名称冲突

D-011 规定“世界模型”只指 AinerZero，“世界系统”指 AnimeWorld。AinerHub 里有三处同名或近名：

- `docs/v2/00_OVERVIEW.md` 主干图中的 `WorldModel`（人物、地点、道具、风格设定）：建议在文档里称“世界设定库”；
- `app/worldmodel/`（World DB）：建议在文档里称“持久世界库”，它属于世界系统的存储层；
- `world_profiles`（世界观转译）：称“世界观转译档案”。

代码里的包名和表名暂不改，改名由负责人决定。

## 7. 本次没有改动的文件

当前分支 `feat/world-greybox-pipeline` 上有他人的未提交改动，本次一个都没有碰：

- `code/apps/ainer-core/scripts/anime_repaint_poc.py`
- `code/apps/ainer-studio/src/`：`box/BoxHome.tsx`、`canvas/Flow.tsx`、`canvas/chrome.css`、`canvas/chrome/` 下 7 个文件、`canvas/comic.ts`、`canvas/nodes.css`、`canvas/nodes/ImageNode.tsx`、`canvas/nodes/index.ts`、`canvas/store.tsx`、`library/Characters.tsx`、`styles.css`、`workbench/ShotRoute.tsx`、`workbench/shotRouting.ts`
- `code/apps/ainer-studio/tests/shot-routing.test.mjs`
- `docs/transcreation/drama_transcreation_pipeline.md`
- `var/world_greybox/anime_routes/README.md`、`STATE.md`
- 未跟踪：`scripts/anime_timing_variants.sh`、`canvas/nodes/GroupNode.tsx`、`production/useLocalNames.ts`、`docs/studio/claude/ux_pass_2026-10-13.md`、`docs/studio/twenty_shot_preview.md`
