# AinerOps -> AinerN2D 对接规范（V3，工业版）

本规范覆盖旧版，目标是把“部署侧”和“业务侧”彻底解耦：

- `AinerOps` 只负责部署与原始能力上报。
- `AinerN2D` 负责适配（本地中间层自动映射）。
- 上报模型会自动进入本地“接入模型列表（Provider目录）”，可在模型行直接执行 `AI自动接入` 与 `测试`。

## 1. 架构边界

### 1.1 AinerOps 职责（只上报，不适配业务）

- 部署模型服务/中间件，维护健康心跳。
- 上报原始信息：
  - 地址：`endpoint_base_url`
  - 协议：`protocol`
  - 文档：`openapi_url` / `detail_doc_url`
  - 原始能力：`features`, `constraints`, `adapter_spec`, `health`

### 1.2 AinerN2D 职责（本地适配）

- 接收上报并落库。
- 自动分析文档并映射到本地 canonical 键值。
- 自动写入本地 Provider 目录（接入模型列表）。
- 在模型列表行内执行：
  - `AI自动接入`（自动匹配+映射重算）
  - `测试`（连通性检测）

## 2. 鉴权与 Token（90天）

Token 来源：

- Studio 页面：`模型与路由 -> 开放接口接收 (Ops Bridge)`
- API：
  - `GET /api/v1/ops-bridge/token`
  - `POST /api/v1/ops-bridge/token/reveal`
  - `POST /api/v1/ops-bridge/token/regenerate`

规则：

- 固定有效期 `90 天`。
- 仅“重新生成”时旧 token 立即失效。
- 上报 Header：

```http
X-AinerOps-Token: <ops_token>
```

## 3. 上报接口（AinerOps 必接）

Endpoint：

- `POST /api/v1/ops-bridge/report`

请求体（标准）：

```json
{
  "tenant_id": "default",
  "project_id": "default",
  "provider_key": "tts-fishspeech-01",
  "provider_name": "FishSpeech Local",
  "capability_type": "tts",
  "endpoint_base_url": "http://10.0.0.21:9008",
  "protocol": "http+json",
  "openapi_url": "http://10.0.0.21:9008/openapi.json",
  "model_catalog": ["fishspeech-v1"],
  "features": {
    "speaker": true,
    "emotion": true,
    "sentence_ts": true
  },
  "constraints": {
    "max_text_len": 1200,
    "qps": 8
  },
  "health": {
    "status": "up",
    "latency_ms": 190
  },
  "adapter_spec": {
    "request_required": ["text", "voice", "lang"],
    "response_required": ["audio", "duration"]
  },
  "metadata": {
    "detail_doc_url": "http://10.0.0.21:9008/docs",
    "deployed_by": "ainerops"
  }
}
```

最小必填：

- `tenant_id`, `project_id`
- `provider_key`, `provider_name`
- `capability_type`
- `protocol`
- `endpoint_base_url`
- `openapi_url` 或 `metadata.detail_doc_url` 至少一个

返回（示例）：

```json
{
  "report_id": "ops_pr_xxx",
  "provider_key": "tts-fishspeech-01",
  "capability_type": "tts",
  "capability_tier": "medium",
  "integration_status": "capability_gap",
  "matched_provider_id": "provider_xxx",
  "meets_minimum": true,
  "adapter_gap_features": [],
  "mapping_status": "partial",
  "mapping_confidence": 0.78,
  "mapping_gaps": ["response:audio_url"]
}
```

## 4. 上报即入“接入模型列表”规则

从 V3 开始，Studio 侧行为为：

1. 上报到 `/ops-bridge/report` 成功后，系统会尝试匹配现有 Provider。
2. 若未匹配，会自动创建本地 Provider（写入 `model_providers`）。
3. 因此 AinerOps 上报的模型会直接出现在“接入模型列表目录”。

说明：

- 这是 Studio 侧动作，AinerOps 无需额外适配业务模型表结构。
- 同一个 provider_key 重复上报会做幂等更新，不会无限新增。

## 5. 模型列表行级操作（前端）

Provider 列表每行支持：

- `AI自动接入`：
  - 触发 `/api/v1/ops-bridge/providers/{report_id}/auto-bind`
  - 动作包括：文档抓取、字段映射、覆盖率计算、状态重算
- `测试`：
  - 触发 `/api/v1/ops-bridge/providers/{report_id}/test`
  - 动作包括：endpoint 与健康/文档链接联通检测

页面应显示：

- 映射状态：`mapped/partial/failed/pending`
- 覆盖率：request/response/feature
- 联通状态：`联通/不联通/未测试`

## 6. 中间层映射策略（Studio 内部）

Studio 中间层使用以下输入做自动映射：

- 上报 `adapter_spec`
- 上报 `features`
- 文档（`openapi_url`，失败时使用关键词降级解析）

输出：

- `mapping_status`
- `mapping_confidence`
- `request_coverage`
- `response_coverage`
- `feature_coverage`
- `mapping_gaps`

业务系统只消费 canonical 字段，不直接消费厂商私有字段。

## 7. capability_type（当前支持）

- `llm_structured`
- `storyboard_t2i`
- `video_t2v`
- `video_i2v`
- `lipsync`
- `tts`
- `dialogue_tts`
- `narration_tts`
- `sfx`
- `ambience`
- `aux`
- `bgm`
- `subtitle`

可用别名会自动归一化（如 `llm -> llm_structured`）。

## 8. 复杂模型文档要求（强制建议）

简单模型：只给 `openapi_url` 可接入。  
复杂模型（强制建议提供 detail 文档）：

- 多阶段任务（异步提交+轮询+回调）
- TTS/SFX/BGM 带分段与时间戳
- 视频模型含 i2v/t2v/keyframe/参考图混合输入

复杂模型请提供：

- `metadata.detail_doc_url`
- `sample_request`
- `sample_response`
- 错误码说明（重试/不可重试）

## 9. 幂等与心跳

- Upsert Key：
  - `(tenant_id, project_id, provider_key, capability_type)`
- 推荐频率：
  - 部署完成后立即上报一次
  - 心跳每 `30~60秒` 更新 `health`

## 10. 错误码与排查

- `401 invalid ops ingress token`：Token 错误/过期/失效
- `400 unsupported capability_type`：能力类型不支持
- `500 relation ... does not exist`：数据库未迁移（执行 Alembic）

---

一句话：

`AinerOps 只上报原始信息；AinerN2D 本地中间层负责自动映射、自动入库到接入模型列表、并提供行级自动接入与测试。`
