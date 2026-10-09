# 第五批：共享舞台接入画布引用（2026-10-09）

## 状态与边界

源码、前端构建与后台静态导入已完成。未执行功能测试、浏览器验收、pytest、视频/GPU生成；验收仍由 Gemini 执行。预检时 Core PID 5599 有 1 个 queued/running GenTask，因此未重启。新后台接口尚待任务结束后加载，不能声称已在 8100 实测。部署记录：`var/planA/stage-references-deployment.json`。

## 实现

- 新画布类型 `stage` / `coverage` 与生产资源引用相连。文档只存版本引用、位置、标题；场景、站位、机位、时间与素材绑定仍从共享舞台读取。
- 共享舞台的「加入画布」及「镜头加入画布」自动复用已有相同版本节点。镜头入口创建舞台→镜头 control 边，并把有正面全身格的角色标准包显示为该格的真实版本引用、连 identity 边到舞台；可展示的道具/媒体连 ref 边。没有该格或媒体的绑定保留在舞台 dependencies 中，不制造图片占位代替素材。
- 新节点选中后按需读取真实 SceneDoc，遵守同屏实时视口预算、延迟加载 Three 和节点局部订阅。镜头首/中/尾按钮映射统一场景时间（支持逆向与静止覆盖），采用来源机位。
- 双击或按钮直接编辑来源舞台；失效引用仍允许进入来源修复。共享编辑器改为全局 overlay，编辑期间暂停画布快捷键，保留未保存修改保护。
- 生产解析器支持 stage / coverage；镜头 ID 为 `stage_id:coverage_id`（按首个冒号分割）。对每个舞台验证协议、投影与原子素材版本；改变角色包或外部白模后旧引用明确失败。禁止实例绑定另一个舞台/镜头，避免递归依赖环。
- 引用 revision 哈希包含舞台 ID、完整 StageContent 与所选 coverage；画布关联列表、投影元信息不纳入内容哈希，因此只关联另一个画布不会使内容引用失效。仍返回舞台行版本与舞台完整元数据 revision，以供编辑器并发控制。
- 「采用素材最新版本」沿用已有明确采用动作，适用于舞台/镜头；不自动重跑生成。原子绑定改变须先在舞台里明确重新绑定、保存。
- 同工作区资源 usages 查询覆盖自由与章节画布，只报告已保存 data.ref 的直接引用；它不是完整渲染/配方依赖索引。

## 契约增量

原 production/v0.1 与 shared-stage/v0.1 信封保持。

`POST /api/v2/production/stages/reference-preview`

`POST /api/v2/production/stages/reference-bake`

请求：`{board_id, ref: {kind: "stage" | "coverage", id, revision, mode: "reference"}}`。

preview 必须解析精确来源版本，返回 ref、resource 与真实 doc。bake 只接受 coverage，锁定舞台后验证引用，返回已映射机位/时间的 baked、sources、state_plan、control_revision、framing_reports 和 consumption。包含两端的逐帧规则沿用第四批；成片拼接仍须处理端点去重。它是可导出的真实预演控制包，没有提交视频任务。

资源结果额外含 stage_id、stage_version、stage_revision、coverage、coverages、dependencies；没有伪造 media.url。

## 防止生成时忽略控制

- 自由生成提交和服务端配方执行均检查连接的舞台/镜头（含上游分组和目标所在分组）。直接请求携带 stage/coverage production_ref 也阻止提交。
- 媒体生成器尚未消费这种控制时，返回 `stage_control_not_supported`；Dock 的直接上游场景显示明确禁用原因。不能连线后丢掉站位/运镜，却声称按导演控制生成。
- 独立图片/视频生产流程仍走其原有入口。此限制针对共享舞台控制，不表示既有白模或所有模型都没有控制能力。

## 静态与构建记录

8 个本批后台文件 AST 解析通过；导入 app.main 后共享舞台路由为 13 条（原 11 + 新 2），不是 HTTP 验收。Studio TypeScript/Vite 构建通过；保留原 Three 大包提示。

完整源码摘要见 `source_batch5_stage_canvas_refs.json`。未修改 Gemini 测试/矩阵、CR-09 物理推断实现或滑雪脚本；canvas_exec 仅新增共享控制检查，service 仅新增 stage/coverage 分支。

## 加载与验收顺序

1. Gemini 先完成当前生成任务；保持现有服务，不中断任务。任务结束后用当前 Core 配置加载本批后台，并检查启动状态。
2. 独立验收空白舞台加入空白自由画布、保存/重载/复制/删除节点；不能自动塞剧情或角色。
3. 同一舞台两个机位、两张自由画布及章节画布复用；验证坐标、机位、首中尾时刻、引用版本一致，关联画布不改变内容 revision。
4. 素材包修改、舞台修改、外部白模修改、源删除、非法世界/时期：旧引用失败且保留，明确修复来源后再采用；未保存舞台不能加入画布。
5. 缺 body_front 的标准包仍保留原始绑定；已有的独立正面格与道具资产连线正确；同版本节点复用，源视图不复制成假素材。
6. reference-preview/reference-bake 严格版本拒绝、同刻事件/逆向/静止时间映射、边界、机位和来源哈希；端点去重与最终音画不属此导出完成范围。
7. 自由生成/配方执行：直接舞台控制、分组嵌套控制、目标分组控制都不允许忽略；旧缓存不能掩盖新连接的控制，显式请求也不能绕过检查。
8. 然后推进冻结控制包→真实 Blender/Union 控制消费→图像与视频模型；用能力支持与真实产物验证，仍不可承诺 100% 物理一致性。

## 后续未完成

共享控制包到最终视频的真实消费、持物/特效渲染、IK/碰撞、专业导演自动编译与剪辑/音画完整联动仍未完成。用户可以手工自由搭画布与共享舞台，不需要先接受 AI 分镜。
