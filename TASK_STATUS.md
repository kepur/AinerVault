# AinerHub 任务状态（v2 主线）

> 更新：2026-10-13（分支 `feat/world-greybox-pipeline`）。旧版 2026-04 的 v1 SKILL 表已作废：v1（`ainern2d-*`、RabbitMQ DAG）自 2026-08-26 起冻结，见 `START_HERE_FOR_AGENTS.md`。历史内容见 git `babf49f:TASK_STATUS.md`。

## 1. 主线与服务

| 服务 | 端口 | 位置 | 状态 |
|---|---|---|---|
| ainer-core（FastAPI，v2） | 8100 | `code/apps/ainer-core` | 运行 |
| ainer-studio（画布前端） | 5174 | `code/apps/ainer-studio` | 运行 |
| 模型网关 + ComfyUI（LTX 2.5 MLX、Layout/Union IC-LoRA、MMAudio） | 7999 | `/Users/mac/Code_Start/ml-stable-diffusion/ai-studio` | 运行 |
| 动态漫画执行层 comic_engine（`comic.render_shot`） | 8190 | `/Users/mac/AinerWorkFlow/AiComicStudio` | 运行 |
| Postgres(pgvector) | 5432 | Docker `ainer-dev-postgres-1` | 运行 |

启动/停止：`scripts/start_ainer.sh` / `scripts/stop_ainer.sh`。

## 2. Plan A 进度（`planA.md` / `planA.review.md`）

| 批次 | 提交 | 内容 | 状态 |
|---|---|---|---|
| 1 | `1adda8c` | 生产契约、16 格定妆照、A/B/C/D 导航 | 完成 |
| 2–5 | 见 `docs/studio/codex/handoff_batch2–5` | 自由画布、单人、共享舞台（StageContent/Coverage/replay）、舞台画布引用 | 代码落地；共享舞台 UI 闭环与稳定出片**未验证** |
| 6 | `5ab7eaf` | 剧本设定器、世界观深度转译、480p 极速默认 | **有回归**（见下） |
| review | `planA.review.md` | 要求 NarrativeIR、转场拆分、生成尾帧不当世界事实 | NarrativeIR 未做 |

### 已知回归（未修）
- `6fb5138` 记录：`app/pipelines/screenplay.py` 第六批删除 `split_speech / script_asides / clamp_shot_ms / split_action / translation_junk / is_visible_change`，导致 test_screenplay/test_cut/test_crew 共 60 项失败。截至 `babf49f` 仍未修（6 个函数仍缺失）。处理建议见 `docs/studio/claude/regression_screenplay_batch6.md`。归属 Codex 写区，本次重构不动它。

## 3. 动态漫画出片现状（AiComicStudio）
- 第一章 20 镜预览：`AiComicStudio/var/chapter-01/preview-twenty-v3/twenty-shots-dialogue8.mp4`（88.3 s，640×384，含音轨），`approval.json` 范围为“前 20 镜预览，非整章发布”。
- 路由与参数：`dialogue_a2v` 4fps、`layer_foley` 8fps、`ltx25_action` 8/12fps、`ltx25_layout` 8/12fps；画质档 compact 384×256 / preview 640×384（`comic_engine/shots.py`）。这些参数在本次重构中保持不变。
- 不足：`ltx25_layout` 的白模是“按首帧站位拼方块”的屏幕投影，没有 3D 世界、没有骨架；每镜各自摆位，跨镜站位/朝向不保证一致。

## 4. 当前进行中：世界白模闭环重构（本分支）
设计：`docs/studio/world_greybox_pipeline.md`。

| 步骤 | 内容 | 状态 |
|---|---|---|
| R1 | TASK_STATUS 与闭环设计文档 | 完成 |
| R2 | 空间 World DB（区域/chunk/地标/通路/资产实例/带出处事实/章节 delta/版本）+ API + 测试 | 完成（世界库+delta API+测试；LLM 章节 delta 只出提案需人工确认） |
| R3 | render_shot 复用整场单次表演；Blender 加载 world chunk + 共享表演逐机位渲染；标准人形骨架；碰撞/可达检查回灌 | 完成（仅在开关打开时生效：feature flag world_greybox_enabled 默认关 + 小说/章节/制作/计划/镜头级开关；默认 render_shot 行为不变，有测试） |
| R4 | 第一章 20 镜走新闭环重跑 + 逐镜 QA 闸门 + 合成成片 | 完成（通用可续跑作业 /api/v2/world-greybox + Studio World/Greybox 面板；QA 不过的镜头自动回退原管线镜头；见 docs/studio/world_greybox_pipeline.md） |

## 5. 未做 / 后续
- NarrativeIR 事件层；WorldDelta 由 LLM 按章节自动提议（当前为结构 + 手工/脚本提议）。
- 打斗动作外部服务（GVHMR/InterMask）与重定向。
- UE5 单向导出（`director/ue_worker` 仍为 mock，开关关）。

## R5 — dialogue two-pass anchor route A/B (2026-10-13)

Route: `dialogue_route="two_pass_anchors"` (opt-in, needs `dialogue_greybox`; `world_greybox_enabled` stays false). Gateway runs a greybox IC-LoRA pre-pass,
pulls anchor frames every 8 frames (≈1 s at 8 fps), then runs a2v driven by the retimed Codex voice. The face card first frame, 384×256 @ 8 fps and duration are kept.
Shots 2/8/13/15 × anchor_strength_mid 0.4/0.6/0.8 × {native a2v mouth, + Rhubarb cel mouth}. Gateway reported `via=anchors` (pipeline a2v_control_anchored).

**Verdict: not adopted on any shot.** 0/24 candidates passed. Face sharpness fell 2–20×, CLIP identity dropped from ~0.86 to 0.49–0.72, and lip-sync corr came in below Codex.
The cause is in the gateway: its pre-pass runs from the prompt alone, without the first frame or reference, so the mid anchors (even at 0.4) bring in a different, photoreal person.
The face card only survives frame 0. The dialogue greybox clay is also a back/OTS framing, not a face close-up, so "matching the greybox" competes with the face-safe close-up.
Fix needed upstream: condition the pre-pass on first_frame (or reference_sheet), or derive anchors by warping the face card. Re-test with the same harness after that.

Harness: `python code/apps/ainer-core/scripts/world_dialogue_twopass_ab.py <run_dir> --shots 2,8,13,15 --mids 0.6,0.4,0.8` (resumable, DB-free).
Results: `var/world_greybox/runs/wpr_01M4SXHWJKKKH7JZZMKQTPPBP6/ab_2p/metrics_table.md`, sheets `var/world_greybox/runs/wpr_01M4SXHWJKKKH7JZZMKQTPPBP6/ab_2p/shotNN_mXX_codex_vs_2p.png`, side-by-side `var/world_greybox/runs/wpr_01M4SXHWJKKKH7JZZMKQTPPBP6/ab_2p/shotNN_mXX_sbs.mp4`.
