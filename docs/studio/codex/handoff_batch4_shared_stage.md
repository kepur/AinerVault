# 第四批交接：共享舞台、时间与 Gemini 编译层集成

日期：2026-10-09。最新分工：Gemini 接手 CR-09、DEFECT-LINT-01 与滑雪管线；Codex 继续共享舞台、站位、机位、时间联动与最终集成。本批不运行功能/视频测试，不提交 GPU 作业，不修改 Gemini 的物理推断、容错和滑雪文件。

## 本批交付

- 画布顶栏新增“共享舞台”，真实接口支持空白创建、手工人物/物体/机位/运动轨/镜头编辑、角色库世界与时期绑定、版本保存、首中尾预演、任意时刻状态和逐帧数据导出。空白创建不预建演员、故事或相机，不调用 LLM。
- 几何/动作唯一来源为已有 DirectorScene.protocol_json；notes_json.production_stage 保存素材引用、初始状态、事件、覆盖和关联画布。编译到已有 SceneProject 和现有 SceneEval/rig/bake，不另建舞台表，不在画布复制物理世界。
- 同工作区多个画布显式关联同一舞台。镜头只选 camera_id、clip_duration_ms、scene_start_ms、scene_end_ms、fps 与摄影意图，切机位不重摆演员。支持反打重叠、倒放、停留；整数帧时长校验，毫秒↔秒转换明确，逐帧数据含 sceneTimes。
- 初始状态和事件支持条件、依赖、原子变化与左右手排他；同刻依赖排序，拒绝循环/未来依赖与无序重复写入。持物/伤势/特效的语义状态不等于 IK、碰撞或真实视觉效果。
- 来源绑定带 revision，人物 canonical_pack 与 character_ref 实体须一致，不混用不同表现世界；源包更新导致显式版本冲突。未绑定人物可以手工预演，不宣称身份生成已准备。
- 舞台保存行锁/base_version；外部白模脚本/覆盖/seed 有指纹。外部编辑后拒绝隐式覆盖，可明确“采用白模编辑器当前版本”。不兼容的几何、动作或引用报错，保留外部改动。
- 协议转换真实消费人物 height_m、spawn.scale，反向转换保留人偶身高。拒绝负缩放、缺身高、自动全景机位、被丢弃的摄影指令/接触字段；完整 root 运动轨只允许一条，作者需合并关键帧。

## Gemini 更新后的衔接与源码发现

用户提供的“157 passed / dry-run”属于集成前报告，本方没有重跑或独立确认，不能沿用为本批 QA_PASS。

1. app/stage/compile.py 的 low_angle/high_angle 分支没有为每镜初始化 cam_start_pos：作为首镜可能报未赋值，作为后镜会复用上一镜位置。已修正每镜初始化及高度。
2. 道具编译为 prefab=prop，但该预制件未注册；仅 SceneProtocol 结构通过不能证明运行时可消费。改为明确 box 代理，meta.source.proxy_props 保留代理身份；不把代理当真实道具模型。
3. 旧 Python state_at 线性插值与实际 S.moveTo 求值不同，多个位移指令还会覆盖前段。现在物理 state_at 和摄影规划取位都调用相同 SceneEval/rig。Beat 回放只保留语义姿态/特效；同演员多段位移暂拒绝，要求合并完整关键帧，避免伪称连续性。
4. 新 POST /production/stages/from-narrative：SceneStage + CoverageShot 编译输入 → 真实协议 → 来源/高度/时间校验 → 保存到版本化共享舞台。人物身高必须来自明确造型包或 heights_m；摄影轨已展开的 presets 不再重复执行。原始剧情舞台及未消费项保留在 metadata，持物/特效尚未自动映射为新事件或渲染挂点。
5. WS→CU→MS 不能一律尾帧像素接续。Gemini 的 complete_ski_film.py 仍将第二/三镜标 continuation，并直接继承上一镜首帧来源；它属于 Gemini 管线修复范围，本批没有改动。需要区分同机位连续分段和动作匹配剪辑：后者按共享边界状态、新机位构图生成新首帧，不能声称硬传尾帧保证身份、动量和物理真实。

## 接口

前缀 /api/v2/production/stages，独立 envelope schema=ainer.shared-stage/v0.1；旧 production/v0.1 不改版本，保留 kind=stage/coverage 的通用 resolver 仍未全面接通。

| 方法与路径 | 内容 |
| --- | --- |
| GET /?board_id= | 同工作区共享舞台摘要，limit 最大 200 |
| POST / | board_id，可选 title/duration_ms/fps；创建空舞台和编译项目 |
| POST /from-narrative | board_id、stage、shots、bindings、heights_m、fps、title；编译并持久化剧情舞台 |
| GET /{id}?board_id= | 协议、状态、事件、引用、覆盖、版本 |
| PUT /{id}?board_id= | 完整 StageContent + base_version；保存并同步白模 |
| POST /{id}/boards | board_id + base_version；显式关联另一画布 |
| GET /{id}/preview?board_id=&base_version= | 真正 SceneDoc，不提交任务 |
| POST /{id}/sample?board_id= | base_version/time_ms/camera_id；世界位姿、rig、相机与事件状态 |
| POST /{id}/coverages/{coverage}/sample?board_id= | base_version/clip_time_ms；时间映射后的状态 |
| POST /{id}/coverages/{coverage}/bake?board_id= | base_version；逐帧 Blender 数据、首中尾/事件取景报告与消费清单 |
| POST /{id}/adopt-projection?board_id= | base_version；明确采用外部白模版本 |

第 i 帧成片时间=i×1000/fps；世界时间=scene_start_ms+(scene_end_ms-scene_start_ms)×clip_time_ms/clip_duration_ms。预演导出包含首尾端点；未来剪辑负责去重，不能暗中重复边界帧。单次最多 4321 帧，超出需拆分。

事件 initial_state 为 instance_id→属性。物品持有使用 held_by 与 slot=left_hand/right_hand；changes/conditions 为 instance_id/key/value。身体左右不随画面变化。同刻重复写入需显式依赖或合为一次原子事件。

## 文件与检查范围

新增 Core：production/stage_schema.py、stage_state.py、stages.py，api/v2/shared_stages.py。
新增 Studio：production/stages.ts、SharedStageWorkspace.tsx、shared-stage.css，scene/state.ts。
有限集成：main.py、director/convert.py、scene3d/runner.mjs、scene/iife.ts、scene/bake.ts、canvas/chrome/TopBar.tsx。收到 Gemini 完成报告后，追加对 stage/compile.py 的物理采样委托与以上编译缺陷修正，没有改其测试。

- build:runtime 通过，运行时重建；npm run build 通过（TypeScript + Vite），保留原有 three 大包提醒。
- 7 个后端文件 AST 解析和独立 router 模块加载通过。新增 router 11 个接口；只证明语法/注册，不证明数据库事务或真实运行结果。
- 任务表 queued/running 均为 0 后保留正在运行进程的真实 CORE 配置优雅重载，无 Docker/模型任务。最终运行记录见 var/planA/shared-stage-deployment.json，日志 core-shared-stage-2026-10-09.log；其他客户端日志不属于本方测试证据。
- 源码摘要 source_batch4_shared_stage.json 冻结集成内容，不是作者隔离提交或 QA_PASS。没有重置、清理、暂存或提交其他代理改动。

## 独立验收队列与顺序

Gemini 先完成其当前缺陷/滑雪修复，再固定双方集成摘要，补验下面路径；Codex 按缺陷修本批文件，复验后接下一轮。服务重载集中交接点，不同时重启。

1. 真实自由画布新建共享舞台：空演员/道具/机位/轨/事件/覆盖，无自动作业；保存重开恢复同 ID/版本。
2. 两名不同身高演员、一个物体、两台机位、一条轨；同场景时刻换机位，世界位姿和 rig 相同，相机不同。比较浏览器、/sample、/bake、旧 /stage/state-at 的消费结果。
3. 重叠反打、倒放、停留、非整数毫秒帧时刻、整数帧拒绝；核对 sceneTimes、首中尾与真实输出，不能只检查 JSON 字段。
4. 单独首镜 low_angle/high_angle、真实道具代理、多段位移拒绝；旧 157 项测试基线需补真实 compile_scene/SceneEval 消费，mock probe 或 SceneProtocol.model_validate 不替代它。
5. 双画布/双标签页版本冲突、世界/时期错绑、源包更新、已删除实例/素材、跨工作区/小说范围。未保存状态切换保留，明确采用新版本。
6. 原子递交、身体左右手争用、同刻依赖/循环/未来事件/重复写、伤势状态持久；标注挂点/视觉特效尚未消费。
7. 白模编辑器外部拖动/保存→共享舞台拒绝隐式覆盖→明确采用→多个覆盖共用新站位。无法映射的原语/动作拒绝，不静默抹去改动。
8. from-narrative 真实导入→保存→多个覆盖→共享求值/数据导出；同时回归旧非共享白模、SceneProtocol、默认 bake 的 8n+1。新 sampleTimes 仅显式使用时改变时间采样。
9. 滑雪脚本改为正确动作匹配切镜后再运行真实模型，检查新景别首帧、动作相位、身份、原生声与实际拟音分轨，保留任务 ID/媒体路径/耗时；dry-run 不作质量通过。

## 仍待完成

通用 stage/coverage 画布节点引用与失效 DAG、跨场次 SequenceState、专业导演技能自动事件/覆盖编译、非人物素材直观绑定、完整轨道交互、IK/碰撞/挂点、自动摄影约束检查与修复、持久任务和最终视频适配仍待接入。

本批 /bake 真正返回 Blender 格式逐帧数据，但没有创建 DirectorJob 或视频；普通 Director 出片不会自动消费新 coverage 时间映射或事件。must_show/offscreen 目前只有报告，不是自动保证。新接入方须明确使用冻结 bake 与 consumption 清单；未经独立验收不宣称物理控制、真实声音质量或整体方案完成。
