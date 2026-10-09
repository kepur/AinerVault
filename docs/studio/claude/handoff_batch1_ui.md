# Claude 第一批 UI 实现交接

日期：2026-10-09。提交方：Claude。接收方：Codex（集成）、Gemini（测试）。
前序：`handoff_batch1.md`（设计交付，无代码）。本文是**代码交付**。

## 1. 基线与前提

| 项 | 实际情况 |
|---|---|
| BASE_READY | 仍**未发布**。用户指示「继续修界面」，Codex 交接 §3 也写明「Claude 可先实现有源码的路径」，据此开始编码 |
| 依据契约 | `ainer.production/v0.1`，CR-01…CR-08 按 Codex 裁定实现 |
| 工作目录 | 共享目录，无 worktree；未执行任何 git 操作 |
| 服务 | **本方启动了 core（8100）与确认 vite（5174）**，用于对真实接口联调。启动即加载了 Codex 未验证的 SOURCE_BATCH1 |

## 2. 改动文件（全部在 Claude 写区）

新增：

- `src/production/api.ts` —— 生产契约客户端（信封 `{schema_version,data,issues}`、ResourceRef、16 格常量、char-sheets 过渡接口）
- `src/production/CanonicalSheet.tsx` —— 16 格三分区组件
- `src/production/useWorldProfile.ts` —— 目标世界解析（context 优先，退到小说映射）
- `src/production/production.css` —— 以上样式

修改：

- `src/Nav.tsx` —— 改为 A/B/C/D 两级导航
- `src/ctx.ts` —— 增加 `stage`、`project`；`project` 参与级联，`stage` **不**参与
- `src/Root.tsx` —— 跳转时写入 `stage`（3 行）
- `src/library/Characters.tsx` —— 增加「定妆照 16 格」页签
- `src/styles.css` —— 追加两级导航样式

未动：任何后端文件、`admin.html`、迁移、网关、测试、他方文档。

## 3. 完成项（已在真实数据上看到）

### 3.1 16 格标准定妆照

接 `GET /api/v2/production/entities/{id}/canonical-pack`。真实结果与设计预期完全一致：

- 李爽（`we_01M1NJRP0ZZ48NWVXQ6BGJNSNX`）显示 **4/16 格，含 2 格近似映射**。
- 三分区并排：全身三视图（3）、面部四视图（2×2）、九宫格表情（3×3），与参考图 03 结构一致。
- `legacy_mapped`（front→body_front）用灰色「旧键」角标；`legacy_approximate`（bust→face_front、profile_left→body_side）用**橙色「近似」角标 + 橙色边框**，两者视觉可分。
- 12 格缺失显示虚线框 + 标准键名，不放占位图。9 格表情全空。
- 拼版单独标注「展示与导出用」「镜头请引用上面的单格，不要用这张」。
- issues 按 code 合并计数（`legacy_view_mapped ×4`），不逐条刷屏。

### 3.2 A/B/C/D 两级导航

- 阶段行：A 故事与世界 ↗ / B 素材与场景 / C 导演与分镜 / D 成片与剪辑 ↗ / 后台 ↗。
- 面板行：阶段内的现有视图（B：角色库、风格广场；C：分镜画布、创作画布、3D-BOX）。
- A 与 D 本批无前端面板，**直接链到后台**并标 ↗，不做空壳页假装已有。
- **实测切阶段不丢上下文**：B（`view=characters&novel=…`）→ C，`novel` 保留，自动写入 `stage=c&view=canvas`。
- 旧深链兼容：不带 `stage` 的链接由 `stageOfView()` 反推阶段。

### 3.3 整包生成入口

按 CR-04 裁定接 `POST /api/v2/studio/char-sheets`（真实端点），按钮文案为「整包生成（缺 12 格）」，提示明写「不能单格补建，整包重出约 10 分钟」，点击前 `confirm` 一次。**本方未点击，未提交任何生成任务。**

### 3.4 按裁定隐藏的能力

CR-03 裁定后端只支持 `mode=reference`，无历史存储。因此**快照、派生、历史回退完全没有出现在 UI 上**，不是灰按钮而是不存在。`viewRef()` 只产出 `mode: "reference"`。

## 4. 验证情况

| 项 | 结果 |
|---|---|
| `npx tsc --noEmit` | 零报错 |
| `npm run build` | 通过，320ms；canvas 块 243KB |
| Codex SOURCE_BATCH1 首次运行 | `/production/context`、`/canonical-pack` **首次真实调用即通过**，返回完整 ProductionContext |
| 真实数据渲染 | 已截图确认（见 §3.1） |

**没做**：未跑测试、未提交生成任务、未写库、未占 GPU、未使用付费端点。真实质量评估归 Gemini。

## 5. 已知缺口

1. 资产抽屉（`AssetsDrawer.tsx`）尚未改造为引用单格——下一批。
2. B/C 画布首页与 purpose 过滤创建流程——下一批。
3. `admin.html` 按 A/B/C/D 重排——下一批。
4. 角色卡列表上的「4/16」就绪度角标——下一批（现在只有详情页有）。
5. `physical` 在 canonical-pack 返回 `{"source":"missing"}`，但 `stage/cards` 能推断出身高体型。两处不一致，见 §7 的 CR-09。

## 6. 给 Gemini 的验证要点

1. **16 格的正确形态是大面积缺失**。李爽应为 4/16、2 格橙色近似角标、9 格表情全空。看到满格判缺陷。
2. 近似映射与精确映射必须视觉可分（橙 vs 灰）。
3. 切阶段后 `novel/chapter/plan/canvas` 不得丢失。
4. 不带 `stage=` 的旧链接应落在正确阶段。
5. 「整包生成」会真的占 GPU，请在隔离环境点。
6. core 由本方启动，加载的是 Codex 未验证源码；若需干净环境请协调重启。

## 7. 新增变更请求

**CR-09 `canonical-pack` 的 `physical` 为空**：`GET /canonical-pack` 返回 `physical: {"source": "missing"}`，但 `app/stage/cards.py` 的 `infer_physical()` 能从外貌描写推断出身高体型（李爽 1.62 stout、高个少年 1.80 lanky，本会话早前实测）。两个接口对同一事实给出不同答案，违反契约 §1「同一份真实对象」。请 Codex 让 canonical-pack 复用同一推断，或说明两者语义差异。UI 暂不显示该字段。
