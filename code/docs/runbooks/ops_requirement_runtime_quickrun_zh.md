# AinerOps 需求协商 / 运行时路由 / 快速试调用 使用说明

## 1. 功能入口

### 1.1 需求协商与自动对接
进入：Studio -> 开放接口接收 (Ops Bridge)

页面位置：
- `/studio/ops-bridge`
- 卡片名称：`Requirement Negotiation / Auto Integration`

### 1.2 运行时路由页
进入：Studio -> AI 路由与运行时路由

页面位置：
- `/studio/model-routing`
- 新增标签页：`⚡ 运行时路由`

---

## 2. 需求协商怎么用

在 Ops Bridge 页面中：

1. 选择 `能力类型`
   - 例如：`llm_structured`、`storyboard_t2i`、`video_t2v`、`tts`
2. 选择 `目标档位`
   - `basic` = 基础档
   - `standard` = 标准档
   - `advanced` = 高级档
3. 填写 `必需特性`
   - 可用逗号或换行分隔
4. 填写 `约束(JSON)`
   - 例如：
```json
{
  "max_latency_ms": 12000,
  "resolution": "1080p"
}
```
5. 填写 `偏好(JSON)`
   - 例如：
```json
{
  "prefer_connected": true
}
```
6. 点击 `一键自动对接`

系统会自动输出：
- `RequirementProfile`
- `RoutePlan`
- `GapReport`
- 集成版本记录

如果存在可用候选，会自动生成并保存一个新的对接版本；如果当前条件不足，则返回 Gap Report 供补齐能力。

---

## 3. 集成版本说明

自动对接成功后，页面下方会出现版本列表，包含：
- capability
- provider
- version
- status
- mapping_status
- created_at

可执行操作：
- `设主并写路由`
- `写入运行时路由`
- `快速试调用`
- `回滚到此版本`

### 3.1 设主并写路由
这是当前推荐的主操作。

点击后系统会自动执行两步：
1. 把该版本切为当前主版本（active）
2. 将该版本对应的 profile 写入运行时路由

适用场景：
- 新版本验证通过后正式切主
- 回滚后立即恢复线上路由

### 3.2 写入运行时路由
点击后，系统会把当前集成版本写入：
- `stage_routes`
- `feature_routes`
- `fallback_chain`

这样运行期就能直接按该版本进行路由。

### 3.3 回滚版本
点击 `回滚到此版本` 后：
- 当前同能力/同档位下其他版本会被归档
- 目标版本会重新变成 `active`

---

## 4. 运行时路由页怎么看

进入 `/studio/model-routing` 后，打开 `⚡ 运行时路由` 标签页。

页面会展示：

### 4.1 Stage Routes
当前运行时主路由映射。

### 4.2 Feature Routes / Fallback
当前按能力维度的路由映射和降级链。

### 4.3 协商结果 → 运行时路由表
每一行代表一个可用集成版本，显示：
- 能力类型
- 供应商 / Profile
- 运行时路由键
- mapping 状态
- 是否已写入运行时路由

支持按钮：
- `设主并写路由`
- `写入运行时路由`
- `快速试调用`

---

## 5. 快速试调用怎么用

有两种方式：

### 5.1 从 Ops Bridge 版本表直接点
在自动对接版本列表点击 `快速试调用`。

### 5.2 从运行时路由页执行
在 `⚡ 运行时路由` 标签页中：
1. 选择目标集成版本
2. 根据能力类型填写专属表单
   - `llm_structured`：`prompt` / `system prompt` / `max tokens`
   - `storyboard_t2i`：`image prompt` / `size` / `style/scene`
   - `video_t2v` / `video_i2v`：`video prompt` / `duration` / `fps` / `resolution`
   - `video_i2v` 额外支持：`image url`
   - `tts` 等：`text` / `voice` / `format`
   - `sfx` / `bgm`：`audio prompt` / `duration` / `format`
3. 如有需要，再填写 `补充参数(JSON)`
3. 点击 `快速运行 / 试调用`

示例输入：
```json
{
  "prompt": "生成一个简短连贯的测试样例",
  "scene": "rainy night alley"
}
```

返回结果包括：
- 选中的集成版本
- 对应运行时路由键
- 当前 profile 名称
- 结构化结果摘要面板
- 请求预览（request preview）
- 端点探测结果（probe）
- 真实调用请求摘要（live request）
- 真实调用响应摘要（live response）
- 最近一次路由决策记录 ID

说明：
- 现在 `quick-run` 会优先尝试真实请求
- 当前已优先支持：
   - `llm_structured`
   - `storyboard_t2i`
   - `tts` / `dialogue_tts` / `narration_tts`
   - `video_t2v` / `video_i2v`
   - `sfx` / `bgm`
- 若目标能力暂不支持真实请求，会自动退回到预览 + probe 模式
- 它依然不是完整生产流水线执行，而是“真实网关调用优先”的联调校验模式

---

## 6. 最近路由决策

运行时路由页现在会额外展示“按能力统计卡片”，每张卡片包含：
- 最近一段 quick-run 记录的成功率
- 最近一次 quick-run 的耗时
- 最近状态（成功 / 失败 / 暂无记录）
- 最近命中的 Provider 与时间

说明：
- 成功率基于最近保留的 quick-run 决策记录聚合得到
- 耗时优先显示真实请求耗时；若没有真实请求结果，则回退显示 probe 耗时
- 即使某个能力暂时还没有 quick-run 记录，也会在运行时路由页中展示“暂无记录”卡片

在运行时路由页底部会显示最近路由决策，便于排查：
- 什么时候触发
- 选了哪个 capability
- 走了哪个 provider/profile
- 探测是否成功
- 错误细节是什么

这部分适合做：
- 联调排障
- 供应商切换验证
- 路由回滚后的确认

---

## 7. 推荐操作顺序

推荐按以下顺序使用：

1. AinerOps 上报 provider facts
2. 在 Ops Bridge 中执行 `一键自动对接`
3. 检查是否生成 `RoutePlan`
4. 在版本表中点击 `写入运行时路由`
5. 点击 `快速试调用`
6. 到 `AI 路由与运行时路由` 页面确认：
   - stage routes
   - feature routes
   - fallback chain
   - recent decisions
7. 如果效果不理想，再用历史版本 `回滚`

---

## 8. 相关接口

### 需求协商
- `GET /api/v1/requirements/tiers`
- `GET /api/v1/requirements/schema`
- `POST /api/v1/ops/plan`

### 集成版本
- `GET /api/v1/ops/integrations`
- `POST /api/v1/ops/integrations/{integration_id}/rollback`

### 运行时路由
- `GET /api/v1/ops/runtime-routing`
- `POST /api/v1/ops/runtime-routing/apply`

### 快速试调用
- `POST /api/v1/ops/quick-run`

---

## 9. 注意事项

1. `快速试调用`默认做的是轻量探测，不等同于正式生产任务执行。
2. 如果 provider 未提供可探测 endpoint，probe 可能失败，但不一定代表后续完整接入绝对不可用。
3. `写入运行时路由`依赖自动对接时生成的内部 profile；如果 profile 不存在，需要重新生成自动对接版本。
4. 若同一能力存在多个版本，建议明确只保留一个主用 active 版本，避免人工理解混乱。
