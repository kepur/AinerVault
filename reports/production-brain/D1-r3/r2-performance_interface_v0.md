# 角色表演接口 v0（hub.P1.D1）

状态：Codex 设计草案 r2，2026-10-15，待独立复审；无控制编译器/运行实现。schema只定义输入和候选输出的结构，不能证明某个角色包已支持。依据D-011/D-012、制作计划J1、DillonGoo拆解与审片C1。

## 输入与时间

输入使用 request_id，binding 对象包含 plan_id/plan_revision/beat_id/event_id、world_id/world_version/scene_id/scene_revision、take_id/actor_id/character_ref/sim_hz/render_fps；其余字段为 intent/intensity/target_ref/start_tick/duration_ticks/locks/audio_ref。字段名以配套 schema 为准。意图词表可扩展，首批如surprised/hesitant/composed_but_shaken/deadpan；字符串出现不表示已经实现映射。

sim_hz固定120，tick区间左闭右开。视频帧、音频sample与tick通过显式fps/sample_rate及offset换算；口型以锁定的实际音频为基准，不能为了让表情峰值好看静默伸缩音频。缺音频/对齐结果时mouth标unsupported，不合成假成功。

## 输出曲线与控制面

输出是同一take中的候选控制轨，按gaze / facial_unit / mouth / head_pose / body_pose / gesture / secondary_motion分通道。每轨记录controller_ref、部位、值域/单位、起始值、完整keyframes、预备/到位/停留/回落的tick边界、采样节奏、插值、控制权和实际映射状态。所有阶段边界有序且在任务区间内；不使用仅有hold/release而缺到位的隐式曲线。

角色包v2尚待awz.P3.D5：所有控制器名使用`pending:D5/...`，映射状态pending_D5、执行状态unsupported；不能把占位曲线回填为已执行。D5给出合法控制器/范围后才能生成可执行绑定。美术二次运动覆盖不得修改权威碰撞、世界位置或事件；需要身体移动/接触则转world变更，保持持久身份与take谱系。

节奏ones/twos/threes基于声明的输出fps：姿态轨按1/2/3个视频帧保持取样，时间锚点仍是120Hz tick；音频/口型和世界运行不跟着降频。不能把“一拍二”硬写成每2tick更新。

## 同一谱系与当前可用字段

| 内容 | 现有格式 | v0适配边界 |
|---|---|---|
| 高层意图/节拍 | 制作计划performance.takes/actors/intents、NarrativeIR引用 | 意图映射未实现，不另建叙事事件权威 |
| 台词/表情/注视 | AWZ awz.performance/v0 lines/expressions/gaze | 只能降到现行枚举和实际支持字段；不能向extra-forbid对象塞新控制器 |
| 动作和特效 | Hub SceneStage.beats.do/effects、WorldPerformance.tracks | 由适配器映射已存在动作，未知动作返回unsupported；不能把现成state_at称为AWZ权威运行已接通 |
| 镜头覆盖 | CoverageShot.stage/window、WorldTake.performance_id | 引用同一表演take，不复制世界事实；新表演产生新take，旧媒体保留 |
| 角色控制面 | AWZ角色包v2 D5 | 尚未注册；pending占位不可执行 |

以上是提议连接，尚无跨仓E2E验证。现有表演轨不支持的FACS单元/手势宏等逐项回报，不以近似映射隐瞒限制。

## 单一控制者

每个(actor,部位/通道,时间区间)只接受一名生效控制者，输出记录 owner.kind、owner.id、owner.authorization_ref；有效区间是该轨 phases.start_tick 到 phases.end_tick 的左闭右开区间。用户手调锁定项最高约束；导演指令、角色运行策略、将来世界脑都只能在明确让出的范围提出候选。同优先级重叠、部位别名重叠和未知优先级返回control_conflict，不按最后写入者胜出。需要混合时显式登记单一blend控制者及输入权重/合成规则，未定义就拒绝；不得靠两个直接写同一骨骼的轨道假称混合。

控制权切换创建新提案/版本，从当前实际姿态衔接；不得更改已经执行/播出的区间。出错维持已验证安全姿态或返回unsupported，不猜动作。锁定项和角色身份不得被强度参数改写。

## 三种表演候选（同一书包变大象事件）

以下是设计例子，120Hz、24fps、每个任务0–600tick；动作强度/时长仅为例子，未登记为科学门或渲染预算。事件和世界引用相同，不同表演为三个新take。实际音频未给，mouth均unsupported。

| take/意图 | 视线与表情/姿态候选 | 预备→到位→停留→回落tick | 节奏 |
|---|---|---|---|
| suspense / hesitant | 先看书包，再缓慢转头，眉部紧张、身体微收；不改真实站位 | 0–60→60–180→180–420→420–600 | twos |
| comedy / surprised | 先维持普通神态，再看见大象，眼/头快速double-take与手势 | 0–180→180–240→240–360→360–600 | ones |
| dry / deadpan | 看大象后维持平静，延后一个微小眼动；不自动创造台词或走位 | 0–120→120–180→180–540→540–600 | threes |

三例所有controller_ref均为pending:D5，曲线只是计划，不代表角色执行成功。实际候选数/渲染/模型预算另行登记。

## 可检查信号与错误

执行数据核：视线在节拍内转向合法对象、阶段边界/保持时长、表情峰值与实际音频重音的偏差、同一部位写者唯一、身份/锁定项不变、实际位置/接触和动作类型。阈值必须来自用户/预登记或具体任务，缺阈值写未验证；不在本稿编造过门线。视觉审片再判表情是否可读、动作是否生硬、幽默或悬疑是否有效。

错误至少包括unknown_actor、stale_revision、invalid_time_curve、unknown_controller、out_of_range、missing_audio_alignment、lock_conflict、control_conflict、unsupported_action、changed_past；路径化回报并保留原提案，零静默修正。需要结合世界改变的表演经统一变更信封预览，不在本接口直接写World DB。

后续：D5冻结控制面→实现计划到已有轨的适配器→非作者对抗复核（重叠写者/单位混淆/越界/占位被执行/坏音频/过期版本）→固定音频与角色的有界片段→消费者独立审片。当前仅文档/schema，未渲染、未训练、未改其他已有文件。

## r2 音频身份、错误记录与语义层边界

`audio_ref=null` 明确表示没有实际音频。非空必须是对象，完整给出 asset_ref、原字节 sha256、sample_rate、anchor_tick、offset_samples 和 alignment.status。音频时钟定义为 `sample(tick)=offset_samples+(tick-anchor_tick)*sample_rate/120`；offset_samples 可为负数，表示预卷或音频尚未开始。此式保留有理数，不静默取整或改速；实际消费者须登记统一的取样边界规则，尚未登记就不得宣称已完成口型时钟适配。

alignment.status 仅为 aligned/pending/failed；aligned 必须同时给出真实对齐产物 ref 与 sha256，且语义层核对音频身份和相同时间基准。pending/failed、无音频、不可解析身份或对齐失败，mouth 都 unsupported，返回 missing_audio_alignment；不得用填充字段假称完成。示例 fixture 的摘要为合成占位，只演示结构，不表示真实音频或运行授权。

独立 `record_kind=error` 记录带 request_id 和非空 errors 数组；每项有 code、JSON Pointer path、message。十个 code 为 unknown_actor、stale_revision、invalid_time_curve、unknown_controller、out_of_range、missing_audio_alignment、lock_conflict、control_conflict、unsupported_action、changed_past。错误记录不写任何世界或表演状态，不返回成功曲线；原提案保留。消费者必须校验与原请求关联。

配套 schema 只检查结构、枚举与局部条件。以下为 D2 语义校验器必须 fail-closed 的合同要求，当前设计没有实现这些校验：所有数值有限；阶段边界依序且在请求区间内；keyframes tick 有序且无重复并覆盖完整轨区间（允许末端边界值）；单位和向量维度符合已登记控制器；每个实际部位（含别名展开）同一区间只一名控制者；锁定项、已执行区间和请求/响应绑定一致；每个 mouth 轨有可信音频和 aligned 产物；pending_D5 轨永不 executable。缺控制器注册/别名或世界实际状态时记 unsupported/未验证，不因结构通过而放行执行。ones/twos/threes 只约束姿态呈现，不降低音频或世界时钟。

r1 原字节归档于 reports/production-brain/D1-r2/r1-*，r2 仅补设计合同，不授权音频生成、表演执行、渲染或模型运行。
