# Plan A 第一批基线审计报告 (Baseline Audit Report)

**审计方**：Gemini (QA & Verification)  
**审计日期**：2026-10-09  
**契约基准**：`ainer.production/v0.1` (`planA_contracts.md`)  
**审计对象**：
- Codex 后端交付：`docs/studio/codex/handoff_batch1.md` 及相关后端实现
- Claude 前端交付：`docs/studio/claude/handoff_batch1.md` 与 UI 设计
- 存量测试套件与用户反馈问题 (#1 ~ #8)

---

## 1. 审计摘要与自动化验证结果

本审计在**严格内存隔离**环境下执行，**零写入生产 PostgreSQL 数据库**，零占用 GPU 算力。通过自定义 `IsolatedMockSession` 与 `FastAPI TestClient`，对全套契约与既有逻辑完成端到端自动化测试。

| 测试套件 | 验证范围 | 用例数 | 结果 | 耗时 |
|---|---|---|---|---|
| `test_planA_contracts_batch1.py` | R0/R1 生产契约、16格视图、别名映射、乐观锁、资源解析、缺项规划 | 12 | **全部通过 (12/12)** | 1.19s |
| `test_canvas_api.py` | 创作画布存储、版本锁、节点引用持久化、防死链校验 | 37 | **全部通过 (37/37)** | 0.82s |
| `test_stage_p0.py` | 舞台物理推断、动作表一致性、碰撞半径、特效表、镜头时间窗 | 20 | **全部通过 (20/20)** | 0.11s |
| `test_char_sheet.py` | 定妆照分层生成契约、裁剪居中、单格提示词纪律、后台异步状态 | 20 | **全部通过 (20/20)** | 1.11s |
| **合计** | **四套核心关联套件** | **89** | **全部通过 (89/89)** | **2.65s** |

> 自动化测试记录已归档至 `docs/studio/test_runs/batch1_latest.json`。

---

## 2. 对 Codex 第一批后端交付的独立复核

对照 `docs/studio/codex/handoff_batch1.md` 第 4 节 Codex 明确委托 Gemini 验证的 9 大重点，复核结果如下：

### 2.1 路由注册与 OpenAPI 规范 [通过]
- **源码入口**：`app/main.py` 挂载 `app/api/v2/production.py` 与 `char_sheet.py`。
- **验证事实**：8 个全新生产端点正确注册在 FastAPI 中，应用总路由数达 319 个；`app.openapi()` 成功生成合规 OpenAPI 3.x 文档，请求/响应 Model 字段无类型冲突或递归死循环。

### 2.2 正常与空白画布上下文 (`GET /production/context`) [通过]
- **正常画布**：绑定小说、章节、分镜计划的导演画布正确返回权威 `data.context`，包含 `schema_version="ainer.production/v0.1"`、`project_id`、`source_revision`。
- **自由画布**：无计划无小说的自由画布，正确返回实际 `board_id`，`project_id="board:{board_id}"`，`novel_id=None`，不使用 `null` 伪装画布存在。
- **归属冲突**：画布章节与分镜计划不一致、转译映射不属于当前小说时，严密抛出 409 `context_conflict`。
- **版本更新**：节点布局更改不会变更基础资产 revision；内容变化时 `source_revision` 稳定变更。

### 2.3 Purpose 枚举与重复过滤 (`PATCH /context`, `GET /canvases`) [通过]
- **用途枚举**：严格限制于 `assets`, `directing`, `finishing`, `general`；非法用途直接 422 拒绝。
- **重复过滤**：`GET /studio/canvases?purpose=assets&purpose=directing` 支持多参数并集过滤，先过滤后分页。
- **存量标签**：带有历史标签（如 `brainstorming_custom`）的画布，历史标签保留在 `scope.purpose`，生产用途降级为 `general` 并触发 `legacy_purpose` issue 提示。

### 2.4 资源解析逐项对齐与过期拦截 (`POST /production/resources:resolve`) [通过]
- **严格对齐**：输入 5 项 `refs`，返回体 `data.items` 严格等长（5 项）且索引一一对应。
- **逐项失败隔离**：当某一项视角缺失（`view_missing`）或版本过期（`revision_conflict`）时，该项标记为 `unresolved` 并附带具体 `issues`，其余有效项目正常 `resolved`，不破坏整体请求。
- **模式拦截**：传入 `mode="snapshot"` 报 422 `mode_not_implemented`；传入 `instance_id` 报 422 `instance_not_implemented`，严格符合阶段约束。

### 2.5 16 格标准包、残缺检测与别名映射 [通过]
- **完备包**：全量角色包返回 16 格 `views` 字典，`missing` 为空列表。
- **残缺包**：部分绑定的角色（如反派赵烈仅正脸），`views` 仅包含有效格，其余 15 格明确列入 `missing` 列表，供前端呈现警告。
- **别名映射 (CR-05)**：旧键 `expr_sorrow` 自动映射为契约权威键 `expr_sad`；`expr_happy` 映射为 `expr_laugh`。
- **遗留映射 (CR-06)**：`front` 映射全身 `body_front`，`profile_left` 映射 `body_side` 并记录侧向 `side="left"`，`bust` 映射 `face_front`，均带有 `status="legacy_mapped"` 或 `"legacy_approximate"`。

### 2.6 增量标准包绑定与安全锁 (`PATCH .../canonical-pack`) [通过]
- **增量保留**：绑定新单格时，既有格完全保留，不覆盖身份锚图。
- **时期锁定保护**：对 `locked=True` 的造型时期发起修改，强制抛出 409 `pack_locked`。
- **防作弊拦截**：同一素材 ID 绑定多个格抛出 422 `duplicate_view_asset`；拼版素材冒充单格抛出 422 `sheet_used_as_view`。

### 2.7 镜头视角偏好计算与无计划素材卡 (CR-01) [通过]
- **视角计算**：特写景别优先选面部（`face_*`），全景选全身（`body_*`）；右侧视角选中 `face_right` / `body_side`，严禁左侧镜像冒充；3/4 偏角返回 `None`，不冒充正侧面。
- **CR-01 落地**：`GET /stage/cards?board_id=...` 与 `?novel_id=...` 可以在无 `plan_id` 场景下直接拉取该范围内的角色与地点卡片。

### 2.8 缺项规划与节点使用位置扫描 [通过]
- **规划安全**：`POST /production/prepare` 只输出规划与缺失视图，当调用方传入 `submit=True` 时坚决返回 422 `submission_not_implemented` 拒绝。
- **使用扫描**：`GET /production/resources/{id}/usages` 精确扫描画布已存节点的 `data.ref`，并返回包含 `not_scanned` 的覆盖度声明，不虚假声称完整 DAG 索引。

---

## 3. 对 Claude 第一批交付与前端现状的审计

- **交付状态**：Claude 交付了 4 份文档（`README.md`, `batch1_design.md`, `batch1_requests.md`, `handoff_batch1.md`），在 `code/apps/ainer-studio/src/` **未写入代码**。
- **CR 请求达成情况**：
  - CR-01（无 plan 素材卡）：Codex 已实现，Gemini 已通过单元与接口测试。
  - CR-02（purpose 枚举与过滤）：Codex 已实现，测试通过。
  - CR-03（ResourceRef 解析）：Codex 已实现，测试通过。
  - CR-04（整包生成过渡）：char_sheet 路由已在 main 注册，测试通过。
  - CR-05（表情别名）：已在 canonical.py 中统一适配。
  - CR-06（旧键映射）：已在 canonical.py 落地。
  - CR-07（画布上下文）：`GET /production/context` 已可用。
  - CR-08（道具 0 数据）：确认当前数据库无 prop 实体，空状态规则生效。
- **结论**：Codex 后端能力已完全满足 Claude 第一批编码需求，Claude 可正式进入 `src/` 代码实现阶段。

---

## 4. 影视与媒体生成质量专项审计 (针对用户反馈 #1 ~ #8)

> **核心原则：禁止仅因任务成功就宣布成片合格！**  
> 后台 Job 跑完 `status="done"` 仅代表计算流程未中断，不等于画面符合影视规律与物理真实。

### 4.1 用户反馈现象与根因剖析

| 反馈编号 | 用户原述现象 | 根因审计分析 | 影响层级与责任人 |
|---|---|---|---|
| **#1 & #2** | 3D 白模画布打不开，没法控制或重新生成，场景静态不动 | 1. 前端 `studio?view=box` 页面未适配最新的 SceneStage 契约；<br>2. 3D 预演动作未挂接 MOTIONS 动画驱动，人物缺少骨骼绑定。 | **阻塞 (Claude UI & 3D 渲染)** |
| **#3 & #6** | 滑雪视频未调用本机 ml-stable-diffusion 或本地 LTX 2.5 MLX 接口 | 生成路由当前依赖外部或占位 pipeline，本地 MLX 适配层未被生产任务正式调用。 | **阻塞 (Codex 生成管线)** |
| **#4 & #5** | 15s 视频一次性跑出呆滞镜头，不符合物理规律；画面缺少特写、远景与运镜；应使用参考图/尾帧无限接力 | 1. 镜头覆盖严重缺位：未将 15s 动作拆解为 2-3 个镜头（全景进入 + 近景特写 + 反应镜）；<br>2. 视频生成未接入尾帧传递（Frame Conditioning），导致第二镜无法接续第一镜动势。 | **失败 (Codex 导演调度与生成管线)** |
| **#7** | LTX 2.5 支持声音，现有生成没有声音依据 | 现有视频管线仅产出静音 MP4，音频合成与音效推断（风声、滑雪刮雪声）未接入流水线。 | **阻塞 (Codex 音频管线)** |
| **#8** | 改造还有新建画布没有实现 | 前端新建画布流程未串接 `POST /studio/canvases` 的 purpose 选择弹窗与生产上下文初始化。 | **未实现 (Claude UI)** |

### 4.2 影视质量标准确立 (QA 质量通过红线)

后续批次中，影视成片必须满足以下硬性指标方可判定为「质量通过 (Quality Pass)」：
1. **分镜镜头数覆盖**：任何超过 5 秒的剧情动作，分镜计划必须包含 $\ge 2$ 个不同景别机位（例如：`ws` 建立环境 $\to$ `mcu` 动作 $\to$ `cu` 表情反应）。单镜头一次性跑 15 秒一票否决。
2. **尾帧动势连续性**：连续镜头切换时，后一镜头的起始关键帧必须与前一镜头的终止状态（人物朝向、服装、光影）在特征向量上相似度 $\ge 0.82$。
3. **物理世界合规**：滑雪等高速运动视频中，必须具备与速度匹配的粒子/雪花飞溅及摄像机跟随运镜，无逆物理形变与瞬移。
4. **定妆照一致性**：人物主体必须通过 `canonical-pack` 正脸或侧脸参考约束，与基准定妆照面部相似度 $\ge 0.85$。
