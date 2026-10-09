# Codex 第一批：统一素材与画布后端

日期：2026-10-09。契约：ainer.production/v0.1。收件方：Claude UI、Gemini QA。

状态是**源码已写入，未运行验证**。没有启动/重启服务、测试、构建、实际生成、写库或迁移，也没有 Git 提交、切分支或暂存别人文件。API_READY/QA_PASS 尚未发布。现有 main 工作区已有他人未提交更改，本批保持按文件归属并行；不能将当前 HEAD 当成包含所有源码的共同基线。

后续更新：Gemini已提交第一批模拟/关联测试报告；自由画布语义依照用户最新要求已修改，见 [第二批交接](handoff_batch2_free_canvas.md)。本文下述「无小说仅共享媒体」等第一批限制已由第二批修正，UI与QA以新版说明为准。

## 1. 本方文件

- 新增 `app/production/{schema,canonical,service}.py` 与 `app/api/v2/production.py`。
- 小范围修改 `app/main.py` 注册 production 与既有 char_sheet 路由。
- 修改 `app/api/v2/canvas.py` 的用途、列表过滤、生产引用结构校验与创建归属校验。
- 修改 `app/api/v2/stage.py` 支持无 plan 的 board/novel 素材卡查询。
- 修改 `app/stage/cards.py` 的单格 ID 读取、`app/stage/schema.py` 的 inferred 来源。
- 修改 `app/pipelines/identity.py` 的标准单格选择、右侧视角选择；保留其他既有作者修改。
- 修改 `app/pipelines/char_sheet.py` 返回单格的标准 `view_key`，保留旧 `key`。

以上 app 路径均相对 `code/apps/ainer-core/`。未修改前端、admin.html、测试或 Claude/Gemini 目录。

## 2. Claude 可以开始接的部分

以 `GET /production/context?board_id=...` 返回的 **data.context** 为权威。生产接口响应统一 `{schema_version,data,issues}`；旧 studio/stage 接口保持各自原有响应形状。

| 操作 | 源码入口 |
|---|---|
| B/C 创建画布 | `POST /studio/canvases`，purpose仅四种；无 plan 可传 novel_id 创建素材画布 |
| B/C 列表 | `GET /studio/canvases?purpose=assets&purpose=directing`；重复值并集、先过滤后 limit |
| 生产上下文 | `GET /production/context?board_id=...`；自由画布仍需要实际 board_id，不拿 null 伪装存在 |
| 用途/表现世界/返回定位 | `PATCH /production/canvases/{id}/context`，base_version 乐观锁；返回新 board_version |
| 无计划素材卡 | `GET /stage/cards?board_id=...` 或 `?novel_id=...&world_profile_id=...`；plan_id 旧行为保留，三者只能选一个 |
| 资源选择 | `GET /production/resources?board_id=...&kind=entity|asset|audio&offset=0&limit=50` |
| 标准包 | `GET /production/entities/{entity_id}/canonical-pack?world_profile_id=...&epoch_id=...`；无章且多时期时必须选时期 |
| 引用解析 | `POST /production/resources:resolve`；data.items 与输入refs严格对齐；逐项缺失/冲突，不吞掉 |
| 标准包发布 | `PATCH /production/entities/{entity_id}/canonical-pack`，见下方 |
| 缺项规划 | `POST /production/prepare`；仅规划，返回真实缺项/阻塞、原 return_slot；没有生成任务 |
| 使用位置 | `GET /production/resources/{id}/usages?board_id=...&revision=...`；仅已存节点引用，coverage列明未扫描范围 |

路径均以 `/api/v2` 为前缀。第二批已允许没有novel的自由画布从同workspace引用已有实体/媒体，并保留原来源；不自动绑定整书。明确书/世界的画布继续执行归属一致性检查。独立项目实体容器与跨书资产采用仍属于后续工作。

标准包发布请求：

```json
{
  "epoch_id": "实际时期ID",
  "base_revision": "GET包返回的revision",
  "views": {"body_front": "实际AssetID", "face_front": "实际AssetID"},
  "sheet_asset_id": "可选拼版AssetID"
}
```

PATCH为增量绑定；未改格保留，不覆盖身份锚，不改全书实体。锁定时期拒绝改写；错误世界/小说/类型、同一素材冒充多个格、拼版冒充单格、旧revision均拒绝。绑定状态为 bound_unreviewed，不代表视觉审核通过。

`canonical-pack.data.views[key]` 提供 **id、revision、asset_id、asset_revision、media、status、legacy_key**。创建标准引用用这个 **id/revision**，不要使用 asset_revision：

```json
{
  "kind": "canonical_view",
  "id": "实际epoch_id:face_front",
  "revision": "该格revision",
  "binding": {"entity_id": "实际实体ID", "world_profile_id": "实际世界ID", "epoch_id": "实际时期ID", "view_key": "face_front"},
  "mode": "reference"
}
```

此批只支持 reference。发现时可不传revision；解析后才能保存新生产节点。资源变化保持旧引用并显示 revision_conflict，由用户选择采用新版本。尚未存历史对象，因此**隐藏/禁用快照、派生、历史回退操作**并说明能力待接，不冒充「已固定当前图」。旧 entity_view 文档仍能保存，但尚无自动历史升级；打开时保留旧形状，显式转换时从实际包选择新ref。

## 3. CR-01…CR-08 裁定

| 请求 | 裁定 |
|---|---|
| CR-01 | board_id/novel_id 无plan素材卡已写；独立project_id入口未实现。无世界/多个时期返回具体缺项，不静默选第1章 |
| CR-02 | 新请求purpose枚举化；重复purpose查询过滤已写。存量不写库回填：plan/scene默认directing、custom默认general；原自由标签留在scope |
| CR-03 | 新ResourceRef解析/保存已写；自动旧引用升级、snapshot/derived和历史存储未实现。UI先实现明确版本reference；其余不要求先做假功能 |
| CR-04 | 接受明确标注「整包生成」的过渡方案。prepare当前仅规划；单格补建/完成回原槽位未实现。既有char-sheets路由原来未在main注册，本批注册；运行仍待QA |
| CR-05 | 标准契约expr_sad/expr_laugh为准。char_sheet保留旧key，同时后端增加标准view_key；标准包/binder做权威别名适配，UI无需自建别名表 |
| CR-06 | front/back映射全身格；profile_left/bust为近似映射，均记录来源状态；三分之四不冒充正侧面，sheet只展示，不左右翻转 |
| CR-07 | context源码已写；保存/查询的自由画布需要实际board_id。读取顶层data.context，不由UI推断 |
| CR-08 | 不造道具数据。列表读取真实实体；没有实体即为空。QA实际查数据后区分「无数据」「未实现」「失败」 |

Claude可先实现上述有源码的路径与真实缺项界面，不必被后续能力的空缺阻塞全部UI编码。请通过本方目录提新字段需求，不改Codex后端文件。

## 4. Gemini 独立验证重点

本方没有运行以下检查，由Gemini设计与执行。服务生命周期会恢复旧任务；请先由集成方协调启停，避免普通导入或启动测试意外重跑生产任务。真实生成/GPU调度与现有服务写库另约交接，先用隔离库验证接口。

1. 新路由导入/注册、请求模型/OpenAPI兼容；源文件存在不等于接口已运行。
2. 正常与空白画布上下文；小说/章/计划/世界归属冲突；有源时内容改变revision变化，节点布局不改变资源版本。
3. purpose默认与重复过滤、非法值422、分页筛选顺序、存量标签保留。
4. 每项resolver失败保留位置；过期revision、错entity/epoch/world、missing、未实现mode、instance均明确报出。
5. 16格缺项、旧键映射、别名、单格revision与resolver一致、拼版不当单格。
6. PATCH包增量不丢旧格、基于当前revision、时期行锁、锁定拒绝、错资产/重复图拒绝、失败rollback。
7. 绑定后Stage cards通过Asset ID取图；identity参考函数选择同一格；右侧不冒充左侧；后续实际生成消费者另行验证。
8. char-sheets返回标准view_key，旧key不变；任务内存态/重启局限仍保留，不宣布持久化完成。
9. prepare没有提交任务，submit=true拒绝；使用位置只报实际保存节点，不宣称完整DAG索引。

## 5. 尚未完成

R0/R1仍缺自动单格生成与结果采用、旧引用升级、历史快照/派生存储、完整消费索引与失效传播、独立无小说实体项目容器。R2的共享舞台状态、时间、运镜、物理/剧情编译尚未开始。本批是把已有角色/时期/单格与画布接起来的源码增量，不代表整套系统修复完成。
