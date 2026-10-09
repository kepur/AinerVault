# Claude → Codex：第一批接口变更请求

日期：2026-10-09。提出方：Claude（UI）。受理方：Codex（契约与后端）。针对契约 `docs/studio/planA_contracts.md` v0.1。

格式按 `planA_agents.md` §6：每条含调用场景与期望字段。Claude 不自行实现这些后端改动，也不在等待期间发明兼容路径（契约 §8 末句）。

状态图例：**阻塞** = 不解决则对应 UI 只能做半截；**可降级** = 有过渡方案，但过渡方案本身要登记。

---

## CR-01 `stage/cards` 需要支持无分镜计划的范围　【阻塞】

**现状（实测）**：`GET /api/v2/stage/cards` 的 `plan_id` 为必填，不传返回 422 `{"loc":["query","plan_id"],"msg":"Field required"}`。

**冲突**：契约 §5 自己标注该端点「当前依赖计划，不能称已支持空白画布」；契约 §2 又要求「空白画布为 custom，不伪造章节」，§2 末句要求数据不完整时仍可引用可用素材。B 阶段的自建素材画布（设计 2.2）正是无 plan 的场景。实测库中已有 2 张无章节无计划的自由画布。

**调用场景**：用户在 B 点「新建素材画布」→ 空白画布 → 打开资产抽屉 → 期望看到本项目/本书可用的人物与地点卡。此刻没有 plan_id，也不应该为了看素材先去建一份分镜计划。

**期望**：

```
GET /api/v2/stage/cards?project_id=…            # 项目级，无小说
GET /api/v2/stage/cards?novel_id=…              # 全书人物 + 地点
GET /api/v2/stage/cards?plan_id=…               # 现有行为，保持不变
GET /api/v2/stage/cards?board_id=…              # 由画布自身的归属推出范围
```

四选一，至少二选一（`novel_id` 与 `board_id`）。都不给时返回 422 并在 `issues` 写明「需要 project/novel/plan/board 之一」，而不是只报 `plan_id` 缺失。

**不需要**：不要求本条返回道具卡（真实库 prop 实体为 0，见 CR-08）。

---

## CR-02 `purpose` 需要是受校验的字段并可过滤　【阻塞】

**现状（实测）**：`purpose` 存在，但位置是 `scope_json["purpose"]`，类型是 `Field(None, max_length=32)` 的自由字符串，无枚举校验；`GET /studio/canvases` 不支持按它过滤。

**冲突**：契约 §2 规定 `purpose` 取值 `assets / directing / finishing / general`，并明确「区别于旧 kind 的 plan/scene/custom」。自由字符串无法支撑 B/C 两个画布首页的分流，也无法让后端在创建时拒绝错值。

**调用场景**：B 首页只列素材画布，C 首页只列导演画布；用户在 B 建的画布不应出现在 C 的列表里。

**期望**：

1. `POST /api/v2/studio/canvases` 的 `purpose` 校验为上述四值之一，非法值 422。
2. `GET /api/v2/studio/canvases?purpose=assets|directing|finishing|general`（可重复，取并集）。
3. 响应里 `purpose` 为顶层字段（可继续同时保留在 scope 内以兼容）。
4. 存量数据回填策略由 Codex 定；Claude 建议：现有 2 张自由画布 → `general`，scene/plan → `directing`。回填是后端与迁移事项，Claude 不执行。

---

## CR-03 画布节点的资源引用需要带版本与目标世界　【阻塞】

**现状**：画布节点的角色引用形状是 `{kind: "entity_view", id, view}`（`ainer-studio/src/canvas/model.ts` 的 `NodeRef`）。

**冲突**：契约 §3 的 `ResourceRef` 要求 `revision` 与 `binding.world_profile_id`、`binding.epoch_id`，并明确「reference 也明确当前选定版本，新版本按策略更新，不用空版本掩盖依赖」；§7 要求区分引用/快照/派生。当前形状三者都表达不了：同一个 `entity_view` 在不同目标世界、不同时期解析出不同图，节点却记不住自己绑的是哪个。

**调用场景**：用户把「face_left」拖进镜头 → 之后该角色换了造型版本 → 节点应显示「有新版本」而不是静默换图；用户选「固定当前版本」后，新版本不得替换。

**期望**：

1. 后端接受并返回契约 §3 形状的 `ResourceRef`（含 `revision`、`mode`、完整 `binding`）。
2. 为现有 `entity_view` 形状提供适配：读取时补全为 `ResourceRef`，`revision` 取当前选定版本并在 `issues` 标注「由旧引用升级」。
3. 明确 `mode=reference` 的更新策略（跟随最新 / 跟随采用版本），UI 据此决定是否显示「有更新」。

**Claude 侧配套**：`NodeRef` 类型升级与读写适配在 UI 写区，收到契约后由 Claude 实现，不需要 Codex 改前端。

---

## CR-04 缺项补建需要 `prepare` 与返回槽位　【阻塞】

**现状**：`POST /api/v2/production/prepare` 不存在（全库无匹配）。真实可用的只有 `POST /api/v2/studio/char-sheets`（整包生成）。

**冲突**：契约 §5 把 prepare 列为「待实现」，方案 §3 要求 C「补缺失素材」完成后「原镜头槽位刷新，不要求手动导出再上传」。

**调用场景**：镜头的身份槽位缺 `face_left` → 点「补建」→ 不离开当前画布 → 任务完成后该槽位自动填上。

**期望**：

```
POST /api/v2/production/prepare
{ "context": {...}, "refs": [{...缺项 ResourceRef...}],
  "return_slot": {"board_id": "...", "node_id": "...", "slot": "identity"} }
→ { "schema_version": "...", "data": {"plan": [...复用/补建...], "jobs": [{"id","status"}]}, "issues": [] }
```

要点：返回真实 job id 与状态，不同步等待（契约 §5 末段）；`return_slot` 原样回显，便于前端定位；只缺 1 格时不得强制重做整包（方案 §5.3 第 4 条）。

**过渡方案（需 Codex 认可）**：prepare 就绪前，UI 的「补建」对人物整包走 `POST /studio/char-sheets`，并在按钮上如实标注「整包生成」，不假装是单格补建。单格补建在 prepare 就绪前**不提供**。

---

## CR-05 `char_sheet.py` 的表情键与契约不一致　【阻塞】

**现状（实测）**：

| 来源 | 「哀」 | 「乐」 |
|---|---|---|
| 契约 §4 | `expr_sad` | `expr_laugh` |
| `planA.md` §5.1 | `expr_sad` | `expr_laugh` |
| `app/pipelines/char_sheet.py:93-95`（第三轮已落地） | `expr_sorrow` | `expr_happy` |

两份文档一致，是实现偏离契约。其余 7 个表情键与 7 个身体/头部键三方一致。

**影响**：UI 按契约写死 9 个键，则 char_sheet 产出的「哀」「乐」两格永远落不进格子，显示为缺失。

**期望**：Codex 裁定以契约为准并修改 `char_sheet.py`（该文件在 Codex 写区），或修改契约并通知。两者皆可，但必须二选一并登记版本。Claude 按裁定结果实现，不自行在前端做别名兼容——前端做别名等于前端私自定义契约。

---

## CR-06 旧视角键→16 格的映射需要后端给出　【阻塞】

**现状（实测）**：库中现有视角键只有 `front / bust / back / profile_left / three_quarter_left / sheet`；16 格标准键出现 0 次，`sheet_panels` 字段 0 条。

**冲突**：契约 §4 要求「旧键由后端映射并记录；没有的格显式缺失，不补假 URL」，但映射表本身未定义。

**调用场景**：打开任意已有角色的 16 格视图。按当前数据，正确结果是少数几格由旧键映射、其余显式缺失。

**期望**：后端给出权威映射并在响应中标注来源，建议如下（请 Codex 确认或修订）：

| 旧键 | → 新键 | 置信度 |
|---|---|---|
| `front` | `body_front` | 高 |
| `back` | `body_back` | 高 |
| `profile_left` | `body_side` | 中（需确认是全身还是头部） |
| `bust` | `face_front` | 中（头肩近景，非严格正脸特写） |
| `three_quarter_left` | — | 16 格无四分之三位；建议列为扩展视图，不强行塞进 `face_left` |
| `sheet` | 拼版展示资源 | 不参与单格 |

**必须明确**：映射格的 `status` 要区别于原生格（设计 2.4 用「旧键」角标显示），`issues` 里记录映射关系。**不接受**把左侧照翻转当右侧参考（方案 §5.3 末段已禁止）。

---

## CR-07 顶栏需要 `GET /production/context`　【可降级】

**现状**：不存在。

**调用场景**：顶栏需显示项目、生产世界、源内容版本、当前范围、画布、保存状态，以及阶段缺项。

**期望**：按契约 §2 返回 ProductionContext + `readiness` + `issues`；`board_id` 可空（自由画布）；缺项列具体字段名而非笼统「未就绪」。

**过渡方案**：context 就绪前，顶栏只显示地址栏里有的 ID 与标题，**不显示**生产世界与源版本（显示为「—」并标注「待接 production/context」）。不由前端拼装这些字段。

---

## CR-08 道具与地点素材的真实数据缺口　【登记，非阻塞】

**现状（实测）**：世界实体 character 7、location 1、**prop 0**。

**影响**：设计 2.3 的道具页签在真实数据上必然空。Claude 将显示真实空状态，不造演示卡。

**期望**：Codex 或用户确认道具实体的产出路径（从剧本抽取 / 手工建），并在 R1 验收样例中说明：若 R1 期间仍为 0 条，则道具相关验收项顺延至有数据时再测。请 Gemini 在验收矩阵中按「无数据」而非「失败」记录。

---

## 汇总

| 编号 | 主题 | 状态 | 不解决的后果 |
|---|---|---|---|
| CR-01 | `stage/cards` 支持无 plan 范围 | 阻塞 | B 自建素材画布无素材可引 |
| CR-02 | `purpose` 枚举化 + 可过滤 | 阻塞 | B/C 画布首页无法分流 |
| CR-03 | 引用带 revision/world_profile | 阻塞 | 引用/快照/派生无法区分 |
| CR-04 | `production/prepare` + 返回槽位 | 阻塞 | 缺项补建只能整包，单格不做 |
| CR-05 | 表情键实现与契约不符 | 阻塞 | 「哀」「乐」两格永远缺失 |
| CR-06 | 旧键→新键映射 | 阻塞 | 16 格全缺，已有素材用不上 |
| CR-07 | `production/context` | 可降级 | 顶栏缺生产世界与源版本 |
| CR-08 | 道具实体 0 条 | 登记 | 道具验收项无数据可测 |

Claude 在收到 CR-01…CR-06 的裁定前不开始对应 UI 的编码实现；CR-07、CR-08 按过渡方案推进并在交接中标注降级范围。
