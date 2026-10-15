# hub.P1.D2 执行报告（deepseek-q5t8，2026-10-15）

角色：二级执行；负责人：deepseek-q5t8；任务状态：reported；实验状态：纯 CPU 工程完成（无模型运行）
任务依据：hub.P1.D2 任务卡（前置 hub.P1.D1 r3 accepted、hub.P1.D4 r3 accepted）、D-011；参数 v0 照用未改。

## 摘要
- 交付 `performance_contract.py`：request / response / error 三类记录的纯函数语义校验与候选曲线检查；不写执行器、渲染、角色包。
- 复用 D1 r3 schema 且未改一个字节（SHA 与 `D1-r3/identities.json` 一致，测试逐项断言枚举零漂移）。
- 覆盖：120Hz↔输出 fps 精确换算、预备/到位/停留/回落严格递增且落在任务区间、keyframe 有序/无重复/全覆盖、值有限且单位·维度·值域合法、别名展开后的部位唯一写者、锁定项（含换名字绕锁）、旧版本绑定、音频时钟与未对齐口型、unknown_controller、pending:D5 必 unsupported、changed_past。
- ones/twos/threes 只约束姿态轨并按视频帧换算（24fps twos = 10 tick），不把一拍二写成每 2 tick；口型走音频 sample 网格，不随渲染降频。
- 控制器注册只认显式传入的 fixture 能力表：缺表即 unknown_controller；真实 D5 未完时占位永远 unsupported，能力表也不能把 `pending:D5/` 登记为 executable。
- 测试 106 passed（exit 0，新临时根 `/tmp/hub-p1-d2-vR7yCD`）；邻近模块回归 135 passed。
- 独立交叉核对：26 例对比 D1 JSON Schema（Draft 2020-12，jsonschema 4.26.0）→ 0 假绿、0 标准例被误拒；`--failure-control` 注入假绿后抓到 12/12（两个真实退出码见日志）。
- 三版本例子（suspense/comedy/dry）语义通过但 `executable` 全为 False：曲线仍是 pending_D5 / unsupported，未宣称结构通过即可执行。
- 27 项反例矩阵全部按预期码拒绝：相同部位双写、换别名/换控制器名绕锁、NaN/±Inf、负·零时长、逆序/空段阶段、24Hz 冒充 120Hz、请求-响应帧率偷换、未对齐音频写口型、占位被执行、量纲/维度/值域、旧版本、已执行区间、非法 Pointer。
- 仅改文件范围内三个位置；未安装依赖、未渲染、未下载、未提交推送、未写生产库/RunStore/关联项目。
- 未验证：真实音频与对齐产物、角色包 D5 控制面、渲染、E2E、全量套件、API 消费者接入、性能基准。
- 任务卡列出的 `AGENTS.md`/`README.md` 在 AinerHub_IDEA 不存在（与 hub.P1.C2 记录一致），改读 `START_HERE_FOR_AGENTS.md`、`TASK_STATUS.md` 与前置设计文档。
- 待一级决定：①v0 无优先级与混合权重字段，同优先级重叠一律 control_conflict，blend 仅在显式登记规则+输入时放行；若要优先级/权重需 D1 修订 schema。②错误记录自身形状缺陷只能落十码兜底 `unsupported_action`，若要有专门码需 D1 增枚举。本实现未改 schema 绕过任何失败。

## 交付（文件范围内）
- `code/apps/ainer-core/app/production/performance_contract.py`（新建，60327 B，`bbb2c2ab8b18c45f65219e5abe7f7770dbd9ce3ae0c497f71e5fadfa825acf4c`）
- `code/apps/ainer-core/tests/test_production_performance_contract.py`（新建，51010 B，106 passed，`bc643c2714bf2bdd2afb5baa13f20120f88e116cc00c22cf744a525cfe995a5b`）
- `reports/P1-D2/`：report.md、metrics.json、evidence.json、schema-alignment.json(+log)、schema-alignment-failure-control.json(+log)、pytest-p1d2.log、check_schema_alignment.py、collect_evidence.py

## 验证（实际命令与身份）
- `TMPDIR=/tmp/hub-p1-d2-vR7yCD PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_production_performance_contract.py -q` → 106 passed，exit 0（`reports/P1-D2/pytest-p1d2.log`）。
- `PYTHONDONTWRITEBYTECODE=1 /Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/P1-D2/check_schema_alignment.py` → 26 例，0 假绿，RESULT: PASS，exit 0；`--failure-control` → 抓到 12/12 假绿，exit 0。
- 回归：`pytest tests/test_production_review_contract.py tests/test_production_chain.py tests/test_performance.py -q` → 135 passed，exit 0（未改动这些模块）。
- 输入身份（只读）：schema `34aba041…d23c`（27505 B）、文档 `73c3e889…3946`（8725 B）；r2 归档 `c8ce4696…bec5` / `39d1743a…f15ff` 字节不变，原失败与证据保留。
- 反例矩阵与正例控制逐项见 `evidence.json`（counterexamples 27/27、positive_controls 4）；`evidence.json` SHA `47e284e251d64ff9bad8ac9ecb89f6da54fe3014ed11dd0ad169dda9450f4000`。

## 未实现 / 未验证边界（fail-closed 口径）
- `executable` 为真需同时满足：绑定可核对、已执行区间显式传入、控制器由显式能力表登记 executable、部位别名已登记、无冲突/锁/越界/时钟问题；真实 D5 未完成的数据必为 False。
- 结构层有意把 sim_hz、intensity 范围、lock/error path 语法、pending 执行状态让给语义层，以给出精确 D1 码；12 条差异逐条记在 `schema-alignment.json → divergences`（其中 5 条 structural-deferred、7 条 D2 语义更严）。
- 24Hz 冒充 120Hz 只能靠 sim_hz 常量与请求/响应 render_fps 一致性检出；不从曲线形状反推源 fps（无证据不猜）。
- 未做：阈值/过门线（D1 未登记，不编造）、真实音频对齐、D5 控制面、渲染、跨仓 E2E、全量套件。

## 失败与限制
- 无测试失败；未跑全量 ainer-core 套件（超出文件范围，部分用例需要服务/数据库），仅邻近 135 项回归。
- 未删除、未覆盖任何既有文件；未改冻结参数与门；未提交/推送。

## 交回统筹
- 请安排后接非作者复核，重点核对：别名展开的锁判定与唯一写者口径、blend 放行条件、结构层→十码映射表（尤其兜底 `unsupported_action`）。
- 若确认需要优先级/混合权重字段或专门的记录形状错误码，请走 D1 修订；本实现不放宽、不绕过。
