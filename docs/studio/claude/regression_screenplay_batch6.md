# 退回 Codex：第六批 screenplay.py 删除 6 个公开函数，60 个测试失败

日期：2026-10-11。发现方：Claude。责任方：Codex（`app/pipelines/` 属 Codex 写区）。
提交：`5ab7eaf`（已如实提交，避免第六批工作丢失；不代表可用）。

## 现象

`code/apps/ainer-core/app/pipelines/screenplay.py` 由 **523 行改写为 306 行**，以下 6 个公开函数被整体删除：

| 函数 | 被谁依赖 |
|---|---|
| `split_speech` | test_screenplay（14 处） |
| `script_asides` | test_screenplay（11 处，import 失败） |
| `clamp_shot_ms` | test_screenplay（6 处） |
| `split_action` | test_screenplay（5 处） |
| `translation_junk` | test_screenplay（4 处） |
| `is_visible_change` | test_screenplay、test_cut、test_crew |

## 判定依据

1. 不是搬家：`grep -rn "^def split_speech\|^def script_asides\|^def clamp_shot_ms\|^def is_visible_change" app/` 全库零命中。
2. 不是旧账：`git show HEAD~1:…/screenplay.py | grep -c` → 6 个全在；工作树 → 0 个。
3. 不是测试过时：这几个测试文件均为已跟踪的既有测试，本批未改。

## 影响

```
1708 passed, 60 failed, 22 skipped, 10 errors
```

- 60 失败全部由本回归引起（test_screenplay 57 / test_cut 2 / test_crew 1）。
- 10 errors 是 `test_stage_canvas_refs.py` 连不上 Postgres，属环境问题，与本批无关。

## 建议处理

旧实现可从 `git show 1adda8c:code/apps/ainer-core/app/pipelines/screenplay.py` 取回。三种选择：

1. 把 6 个函数补回新版 screenplay.py（新旧能力并存）；
2. 若已被新实现取代，给出等价入口并同步更新三个测试文件；
3. 若确认废弃，说明理由并删除对应测试——但不能让测试与实现长期不一致。

本方不代改：`app/pipelines/` 属 Codex 写区（`planA_agents.md` §2）。

## 顺带修正

`tsconfig.tsbuildinfo`（TS 增量构建缓存）被 `1adda8c` 误带进仓库，本次已 `git rm --cached` 并加入 `.gitignore`。
