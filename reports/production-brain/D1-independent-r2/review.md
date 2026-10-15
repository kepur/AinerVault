# hub.P1.D4 — D1 r2 独立复审

审查者：`codex-design-review-20261015`；二级独立审查角色，未参与 D1 r1/r2 设计或实现。D1 live 历史作者为 `codex`，不是本审查 agent。模型版本未知；自报 code/math，benchmarks 空。

**建议：reject，限一处 JSON Pointer 错误位置合同的小修。** 原 r1 的音频、错误响应和 owner 不一致已闭合；不因未实现 D2 或真实执行而新增本轮设计门。

## 结论与范围

| 项目 | 结论 | 证据/边界 |
|---|---|---|
| r2/原稿身份 | 成立 | 当前两文件与作者 identities.json 完全匹配；r1 归档与 S3 原 SHA 匹配。 |
| 音频结构 | 成立 | audio_ref 为 null 或完整对象；asset_ref/sha256/sample_rate/anchor_tick/offset_samples/alignment 必填；aligned 必须有 ref 和 sha256。负 offset 合法。 |
| 音频时钟公式 | 成立，限文档与有理数算术 | 44100Hz、anchor=120、offset=-2205：tick 120→-2205，121→-3675/2，126→0，240→41895；不做静默舍入。24fps twos=10tick。未执行实际消费者。 |
| 十种错误码/错误分支 | 成立 | 每码有独立正例；未知码、空 errors、缺字段、错误分支混入成功曲线均拒绝。错误记录只能关联 request_id，关联真实性仍需消费者。 |
| owner 命名及区间 | 成立，限合同 | 文档 owner.kind/id/authorization_ref 与 schema 一致；区间取 phases.start_tick/end_tick 左闭右开。缺 owner 字段/旧 owner_id/额外区间字段拒绝。唯一控制者依赖 D2。 |
| pending D5 不可执行 | 成立，限结构与规范 | pending_D5 强制 pending:D5 前缀、unsupported 和原因；candidate/实执行状态不可由 pending 通过。registered 也拒绝 pending 前缀。真实注册表缺失时仍须语义 fail-closed。 |
| 缺/坏音频 mouth | 成立，限规范；实际拒绝未验证 | 文档明确无音频/pending/failed/假身份均 mouth unsupported + missing_audio_alignment；结构可接受单独 registered mouth candidate，跨请求关联交 D2，未伪称 schema 保证。 |
| 时间/控制/状态语义边界 | 成立，限责任划分；实现未验证 | 文档列出阶段顺序、完整 keyframes、有限值、单位维度、别名控制冲突、锁定/过去区间、绑定与真实音频等 D2 职责；独立探针证实结构单独不能拦这些。 |
| errors[].path 真正为 JSON Pointer | **不成立** | 文档第63行称 JSON Pointer，schema 第615–618行仅 ^(/|$)，接受 /bad~2escape 和 /bad~。见下面唯一打回项。 |
| 实际音频、控制编译、角色表演、渲染、GPU、E2E | 未验证 | 本轮没有运行这些；fixture 摘要是合成值，不能证明素材存在。 |

## 唯一打回项：错误位置的非法转义被放行

文件 `docs/v2/production_brain/performance_interface_v0.schema.json` 第615–618行的 path 规则只检查开头的 `/` 或空字符串，未约束 JSON Pointer token 内的 `~` 只能形成 `~0` / `~1`。合法空根、普通路径与合法转义应保留；`/bad~2escape`、`/bad~` 必须拒绝。当前两个负例都被接受（4/6符合预期、2失败，真实退出码1），使路径化问题记录无法按所声明的合同可靠解释。

请作者只补这一处局部语法约束和回归；不要把它移交为未声明的运行时假设，也不要放宽原样例。审查者没有改 schema。新 SHA 完成后可仅复核这处及其相邻错误分支，原94项证据继续保留。

## 实际检查

使用 AWZ 既有 Python 与 `jsonschema 4.26.0`，未安装包、未导入产品/模型模块。Draft202012 schema 元校验成功；94/94 结构检查符合预期（28正例、66负例；其中86项独立构造，另8项为原样例回归），6项身份/命名/导入检查与5项纯算术核对成功。

另有11个明确记录的结构/语义边界探针（含非JSON的Python NaN对象探针）；它们展示 schema 接受，不是 D2 通过。NaN 探针不是有效 JSON 数据或执行授权。非法 Pointer 另由独立失败回归计作真实缺口。

故意失败控制在合法请求上翻转预期，真实 exit=1；正常脚本真实 exit=0。最初 shell 的末尾是日志展示，没有单独捕获脚本退出码，因此保留 initial-* 后只重复一次捕获 exit；未重跑或改写任何作者旧证据。安装环境没有 json-pointer FormatChecker，未把未知 format 的默认放行当成证据；局部转义检查见 pointer-lexical-check.json。

完整 argv/cwd/env/returncode 见 `commands.json`。复现命令（工作目录 `/Users/mac/AinerWorkFlow/AinerHub_IDEA`）：

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/production-brain/D1-independent-r2/independent_review.py
PYTHONDONTWRITEBYTECODE=1 /Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/production-brain/D1-independent-r2/independent_review.py --failure-control
PYTHONDONTWRITEBYTECODE=1 /Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/production-brain/D1-independent-r2/pointer_contract_check.py
```

预期退出分别为0、1、1（最后一个是当前真实缺陷）。后两个原始失败输出均保留，不把它们改写成通过。

## 输入身份（自动读取）

- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/docs/v2/production_brain/performance_interface_v0.schema.json`：`c8ce4696a960294de7731d7956a7c3e373eef4b2232e909354dc30230b8bbec5`，27487 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/docs/v2/production_brain/performance_interface_v0.md`：`39d1743a69685408775971bbdb6633c2c6357e90aa781c1ac21a3f4678df15ff`，8496 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-r2/r1-performance_interface_v0.md`：`e251d79c42e4152a284e9d2249d5684248fc21b2c76b7b0d21a616595df70591`，5976 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-r2/r1-performance_interface_v0.schema.json`：`2e3b6546ccb74c068e25cee8d7fb8532973ef98765ff8e21135fcbb64fd97676`，22210 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-r2/report.md`：`c11ee98e6b3d876d16c58a567f2b1343a8d0d4f92034086003bf6d46e1c7f7ef`，626 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-r2/identities.json`：`fe6882f110e0fe207cc837bae2247b557df1ffb93d970d89598d67b0202163ac`，445 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-r2/structure-checks.json`：`41476d16f389d18881ffa2ab8fbc9fdcf5cead9478bd6176f070b394edb26179`，1063 bytes。
- `/Users/mac/AinerWorkFlow/AinerRelay/reports/V-tier1-design-bundle-20261015/grokbot-k7q2-review.md`：`02bb6c29a1e9e540a97e1ce2daba075450b1f14d9138df039843c0bbe60bee3f`，6856 bytes。

任务卡与 live 作者/状态已保存为 `hub.P1.D4.live.json`、`hub.P1.D1.live.json`、`relay.P2.S3.live.json`。脚本/结果等报告身份见 `artifact-identities.json`。

只在本目录新增证据；未改合同/产品源码/既有报告，未导入MLX/PyTorch，未模型/GPU/下载/安装/付费/提交/推送/删除，也没有执行真实表演或写生产产品状态。Relay领取、心跳和本报告提交属于本任务行政记录。
