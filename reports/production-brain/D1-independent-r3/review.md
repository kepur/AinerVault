# hub.P1.D4 — D1 r3 局部独立补核

**建议：accept，限设计/schema 合同。** D1 r2 唯一未闭合的 JSON Pointer 转义缺口已关闭。r2 的94项原结构证据继续有效并保留，本轮没有重跑。D2语义实现、实际音频、角色表演、渲染与E2E仍未验证。

审查者：`codex-design-review-20261015`，不是 D1 r1/r2/r3 的作者或实现者；D1 live 作者仍为 `codex`。本轮只在 `reports/production-brain/D1-independent-r3/` 新增证据。live 旧 D4 prompt 曾仍指向 r2；本次范围依据统筹明确的 r3 补核派工，不改原 r2 目录。

## 成立

- 当前 schema/document SHA 均与 D1 r3 作者登记匹配。r2 归档两文件与 r2 独立审查时记录的输入 SHA 完全相同。
- JSON 递归差异只有 `/oneOf/2/properties/errors/items/properties/path/pattern` 一叶，从 `^(/|$)` 收紧为 `^(?:/(?:[^~/]|~[01])*)*$`。将这一串恢复后，schema 全文与 r2 逐字节相同；没有触及音频、十错误码、owner 或 D5 条件。
- 文档只有 r2→r3 状态标记和新增 Pointer 说明/归档指针，其他 r2 合同逐字节不变。精确 diff 见 `document-diff.patch`。
- 原6例全部通过，原先错误放行的 `/bad~2escape`、`/bad~` 均已拒绝；空根、普通路径和 `~0/~1` 合法转义保留。
- 另26个边界通过：空 token/重复分隔符、`~01`/`~10`/组合合法转义、Unicode/换行/空字符/backslash token，以及非法转义、尾部孤立 `~`、URI fragment、无前导斜线与非字符串等。预期由独立 token scanner 判定，没有照抄 schema 正则当作 oracle。
- 相邻错误合同5例仍拒绝：未知码、缺 path、缺 message、空 errors、错误记录混入成功 curves。
- 共32/32 Pointer检查、5/5相邻检查、10/10身份/精确差异检查通过；Draft202012元校验通过，正常脚本真实 exit=0。故意翻转根路径的预期后真实 exit=1，原始失败输出保留。
- r2 独立证据目录原25项 manifest 文件全部匹配；目录在本轮执行前后文件集合、大小与SHA一致。旧94与原2个失败结果均未覆盖。

## 未验证边界

本轮没有重跑94项、真实素材读取、音频适配、mouth拒绝语义、阶段/别名/唯一控制者等D2实现、控制执行、模型、GPU或渲染。r2报告里“结构成立/语义未验证”的区分原样保留。本次验收建议不等于放行执行或获得运行授权。

## 精确命令与证据

工作目录 `/Users/mac/AinerWorkFlow/AinerHub_IDEA`。使用 AWZ 既有 `.venv` 的 `jsonschema 4.26.0`，未安装包、未导入产品或MLX/PyTorch。

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/production-brain/D1-independent-r3/check_pointer_revision.py
PYTHONDONTWRITEBYTECODE=1 /Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/production-brain/D1-independent-r3/check_pointer_revision.py --failure-control
```

预期退出0、1，实际一致。完整命令/退出和原始输出：`commands.json`、`run.log`、`failure-control.log`。输入身份和逐例：`results.json`。唯一schema差异：`schema-diff.json`。旧证据身份：`r2-evidence-unchanged.json`。

## 输入完整身份（自动读取）

- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/docs/v2/production_brain/performance_interface_v0.schema.json`：`34aba041558ecbc279ca84d2e846c76ee2334dd621433c086e9b150640b7d23c`，27505 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/docs/v2/production_brain/performance_interface_v0.md`：`73c3e88952e50f9e720ac2f80debe2915884a014f8498177e94de6c9ff039946`，8725 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-r3/r2-performance_interface_v0.schema.json`：`c8ce4696a960294de7731d7956a7c3e373eef4b2232e909354dc30230b8bbec5`，27487 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-r3/r2-performance_interface_v0.md`：`39d1743a69685408775971bbdb6633c2c6357e90aa781c1ac21a3f4678df15ff`，8496 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-r3/identities.json`：`e95e95c0aae3f9cc61f6122e8bc7ce69fed420c09ba4f72f4c6dfe1a529add85`，406 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-independent-r2/results.json`：`5a9b64161839af575527bdd67e3b6f3fa61d78982a5de028e30c885974f67a9d`，79948 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-independent-r2/pointer-contract-results.json`：`c6a79299fa35bc4eb85ad86979c6cd9d9301b890f3ccb0d771c60fe90f55bfa6`，2697 bytes。
- `/Users/mac/AinerWorkFlow/AinerHub_IDEA/reports/production-brain/D1-independent-r2/artifact-identities.json`：`aa3fc3cea75e22e7800734d2aa4cbeaa2fe568cb2d260bb40de2769177757c55`，5697 bytes。

零GPU、下载、安装、付费、产品生产操作、提交、推送或删除；未修改作者合同及任何原证据。已交回统筹作最终行政验收，不自动 accept，不 next。
