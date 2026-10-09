# 第二批交接：自由空白画布修正

日期：2026-10-09。原因：用户再次明确新建是自己从零自由搭建，不能强制选故事、模板、用途或小说。执行顺序见 [三方执行顺序](../planA_execution_order.md)。

## 1. 后端源码增量

- `POST /api/v2/studio/canvases` 新增 `blank:boolean`，默认为false以保留旧调用。**Claude的新建默认分支必须显式发送true**。
- blank:true时创建真实空文档 `{schema:"ainer.board/v1",nodes:[],edges:[],hidden:[],viewport:{x:0,y:0,zoom:1}}`，初始version=1。不提交生成任务。
- 名字允许省略，默认「空白画布」。小说、章、用途均可省略。blank不能携带plan_id、shot_ids、scene_ids，不继承自动分镜图；用户需要素材或镜头时逐项添加引用。
- 所有初次保存必须使用创建响应的version，不能写死0。现有blank:false创建行为保持版本0兼容。
- 纯空白生产上下文不因没有小说/世界而报context_incomplete；readiness新增editing、story_source、world_binding；unbound是未选来源，不是编辑错误。
- 无小说的资源选择器列出同workspace的真实实体/资产/音频，保留原novel_id与来源。没有新建实体，也不把素材所属小说自动绑定给画布。
- 无小说画布解析reference允许来自同workspace的其他书资源。标准包/视图引用需明确entity_id、epoch_id、world_profile_id和view_key（单格）；保留原造型/世界而不猜第1章。已有明确小说/世界的画布仍校验归属与一致性。

本批只改`app/api/v2/canvas.py`、`app/api/v2/production.py`、`app/production/service.py`和Codex所有的方案文档。没有修改Claude或Gemini文件。未运行测试、构建、服务重启、生成、迁移或生产写库。

## 2. Claude当前最高优先级

最低创建请求：

```json
{"blank":true,"source":"user"}
```

可选title、purpose（默认general）、novel_id/chapter_id。默认创建不发送这些来源字段，不能自动带地址栏当前plan_id。B/C入口可以默认分类，但不能把用途选择变成创建门槛或节点类型限制。

1. `NewCanvasModal`默认空白；移除默认故事/照片门槛，模板/AI规划为主动点击功能，创建不调用idea/生成接口。
2. `createCanvas`增加blank参数并区分独立空白与主动「从当前章节/所选镜头创建」。默认空白不继承chapter/plan。
3. 更新客户端请求类型和创建后的文档保存，用返回的`b.version`；AI主动规划路径仍可保存其明确创建的图。
4. TopBar各「新建空白」入口遵守同一行为，不能另一路仍传chapter:true自动挂plan。
5. 载入已保存的空文档不追加自动角色/分镜/模板；用户随后添加的内容保存重开必须保留。
6. 资产抽屉在无plan/novel时用`GET /production/resources?board_id=...&kind=entity|asset|audio`，素材卡显示来源；标准格再查询canonical-pack；不要用plan的cast为空推断库里无素材。
7. 节点/连线编辑不自动生成；运行由用户显式发起。循环/能力不支持在执行时清晰报问题，不影响草稿保存。

## 3. Gemini用例变更

新接口未运行验证，第一批89个模拟/关联测试结果不覆盖此增量。保留原报告，新增新版本验证记录，不能直接沿用QA_PASS。

- 创建blank，无小说/章/计划/模型输入，得到实际空文档与version1；初次保存用响应version，重开0节点0线。
- 带plan_id或镜头范围的blank拒绝，非blank旧分镜入口保持原行为；同版本409与重复保存检查。
- 在真实浏览器从用户点击「新建」开始，确认默认空白，无强制purpose/template/idea，手工放文字/图片/视频/音频/分组/连线，保存重开。
- 空白画布选已有书的人物/素材能返回真实ResourceRef；保留原ID/时期/世界，不自动绑定整书、不新造同名人物。错workspace拒绝；有明确书/世界的画布仍拒绝不一致引用。
- 引用缺视图、旧revision、坏绑定报真实问题；没有小说不应全局禁用编辑/上传。
- 创建/添加/连线/保存期间不存在新增LLM/GPU生成任务；不在生产库写测试数据。
- PostgreSQL筛选、事务/锁与浏览器路径分别记录；MockSession通过只能说明模拟层，不当成真实数据库或UI证明。

## 4. 仍未完成的范围

跨画布子画布节点及其资源级绑定/返回、独立项目实体容器、自动单格补建、历史快照/派生、完整消费索引、全量舞台/导演功能仍需要后续轮次。本批开放资源引用不等同上述能力已完成。
