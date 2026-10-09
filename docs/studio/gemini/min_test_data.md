# Plan A 最小测试数据规范 (Minimum Test Dataset)

**制定方**：Gemini (QA & Verification)  
**契约版本**：`ainer.production/v0.1`  
**环境保障**：纯内存隔离（Isolated Mock / In-Memory），**零写入生产 PostgreSQL 数据库**，零消耗 GPU 算力。

---

## 1. 核心设计原则

1. **测试隔离性（Strict Isolation）**：所有测试用例使用 `scripts/planA_qa/min_test_fixtures.py` 中定义的内存夹具；严禁在真实开发数据库（`ainer_dev`）中插桩或修改存量数据。
2. **三梯队覆盖（Three-Tier Coverage）**：
   - **模拟测试 (Mock/Contract Unit)**：验证数据结构、字段约束、枚举值、404/409/422 错误Envelope。
   - **真实路径验证 (Real API / Integration)**：验证路由可达性、参数注入、乐观锁并发控制、多表关联一致性。
   - **质量通过 (Quality Pass)**：明确区分「任务成功/HTTP 200」与「视觉/艺术质量合格」，建立成片验收指标，禁止仅因任务成功就宣布合格。
3. **闭环完整性（Minimum Completeness）**：涵盖角色、造型时期、16格视图、道具、场景地标、分镜时间线与4类画布。

---

## 2. 实体与资产定义 (Entities & Assets)

### 2.1 角色定义 (3 Characters)

| 实体 ID | 姓名 | 设定类型 | 时期 (Epochs) | 视角覆盖情况 | 物理推断 (Physical) | 验证重点 |
|---|---|---|---|---|---|---|
| `ent_cheng_mo_01` | 陈默 | 主角 | `ep_cm_uniform_01` (校服，未锁定)<br>`ep_cm_coat_02` (大衣，已锁定) | 16 格全部齐备，含独立拼版与身份锚图 | 1.78m, `slim`, `right`, source=`user` | 完备包解析、锁定时期防篡改、乐观锁并发修改 |
| `ent_zhao_lie_01` | 赵烈 | 反派 | `ep_zl_base_01` (赛车服，未锁定) | 仅正脸 `face_front`，其余 15 格缺失 | 1.85m, `athletic`, source=`inferred` | 缺项规划 (`prepare`)、缺失格清单 (`missing`) |
| `ent_lin_xiaoyu_01` | 林小雨 | 配角 | `ep_lxy_legacy_01` (默认) | 包含旧版键 `front`、`bust` 及别名 `expr_sorrow` | 1.60m, `average`, source=`default` | CR-05 别名转换 (`expr_sorrow` $\to$ `expr_sad`)、CR-06 遗留格映射 |

### 2.2 16 格定妆照标准与映射测试

```
标准 16 格视图 (VIEW_KEYS):
├── 全身 3 格: body_front, body_back, body_side
├── 面部 4 格: face_front, face_left, face_right, face_back
└── 表情 9 格: expr_joy, expr_anger, expr_sad, expr_laugh, expr_surprise,
              expr_fear, expr_think, expr_disgust, expr_doubt
```

**别名兼容表 (ALIASES)**：
- `expr_sorrow` $\to$ `expr_sad`
- `expr_happy` $\to$ `expr_laugh`

**遗留键映射表 (LEGACY_VIEWS)**：
- `front` $\to$ `body_front` (status: `legacy_mapped`)
- `back` $\to$ `body_back` (status: `legacy_mapped`)
- `profile_left` $\to$ `body_side` (status: `legacy_approximate`, side: `left`)
- `bust` $\to$ `face_front` (status: `legacy_approximate`, side: `front`)

### 2.3 道具与地点 (Props & Locations)

- **道具 1**：`ent_prop_ski_pole_01` (碳纤维滑雪杖)，尺寸 `[0.05, 1.25, 0.05]` 米，持有人 `ent_cheng_mo_01`，插槽 `hand_right`。
- **道具 2**：`ent_prop_locker_key_01` (储物柜铜钥匙)，用于室内场景交互。
- **CR-08 规则验证**：真实库道具实体数为 0 时，API 必须如实返回空列表，UI 呈现引导空状态，禁止返回伪造假数据。
- **地点 1**：`ent_loc_ski_resort_01` (长白山野雪赛道)，地标：`slope_top` `[0.0, 10.0]`，`cabin_door` `[-5.0, 0.0]`。
- **地点 2**：`ent_loc_corridor_01` (滑雪学校更衣室走廊)，地标：`lockers_left` `[-1.5, 0.0]`，`exit_door` `[2.0, 5.0]`。

---

## 3. 剧情、舞台与分镜时间线 (NarrativeIR & Stage)

- **剧本 ID**：`doc_plana_min_01`，指纹 `fp_sdoc_01_hash`。
- **分镜计划 ID**：`sp_plana_min_01`，转译 ID `wt_plana_trans_01`，表现世界 `wp_plana_modern_01`。
- **舞台推演数据 (`SceneStage`)**：
  - 场景：`sc_01`
  - 时长：`6.0s` (6000ms)
  - 角色演员：`p1` (陈默), `p2` (赵烈)
  - 道具分配：`money` (由 `p1` 携带)
  - 动作节拍 (Beats)：
    1. `[0, 2]`: `p2` 执行 `walk_to` 逼近，`p1` 执行 `back_against` 靠向储物柜。
    2. `[2, 3]`: `p2` 执行 `slap` (接触类动作，距离 $\le 0.5$m)，触发面部受击特效。
- **镜头覆盖 (`CoverageShot`)**：
  - 镜 1 (`sh_01`): `[0, 2000]`ms，景别 `ws` (全景)，建立地理与对抗关系。
  - 镜 2 (`sh_02`): `[2000, 4500]`ms，景别 `mcu` (中近景)，冲突爆发。
  - 镜 3 (`sh_03`): `[4500, 6000]`ms，景别 `cu` (特写)，面部表情反应。

---

## 4. 画布配置矩阵 (Canvases)

| 画布 ID | 用途 (Purpose) | 关联关系 | 节点内容 | 验证目标 |
|---|---|---|---|---|
| `brd_plana_assets_01` | `assets` | 绑定小说 `nv_01`，章节 `ch_01`，无分镜计划 | 空节点 | CR-01 无计划素材卡提取、素材库加载 |
| `brd_plana_directing_01` | `directing` | 绑定分镜计划 `sp_01`，剧本 `doc_01` | 包含 `node_cm_01` (引用陈默正脸视图) | 导演台上下文、节点引用使用位置扫描 (`usages`) |
| `brd_plana_free_01` | `general` | 自由画布，无关联小说与计划 | 空节点 | 自由画布上下文获取（保留实际 board_id，不伪造 null） |
| `brd_plana_legacy_01` | 存量标签 | 带有历史标签 `brainstorming_custom` | 空节点 | CR-02 存量用途标签兼容与保留 |

---

## 5. 夹具代码引用

所有数据在 `scripts/planA_qa/min_test_fixtures.py` 中以 Python 代码形式精确封装，并提供 `IsolatedMockSession` 模拟 SQLAlchemy 读写操作。测试套件可直接通过：

```python
from scripts.planA_qa.min_test_fixtures import create_isolated_mock_db
```
获得即开即用的隔离上下文。
