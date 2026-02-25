# Deployment Topology（DEV + PROD 双环境）

## 1. 目标
- DEV：在 Mac 本地可完整跑通控制面与中间件。
- PROD：两台服务器落地，CPU 承载控制面+数据面，GPU 承载执行面。
- 保障：可观测、可回滚、可扩展、可隔离。

## 2. 环境分层

### 2.1 DEV（Mac）
- 运行：`studio-api`、`worker-hub`、`composer`（可选）、`postgres`、`redis`、`rabbitmq`、`minio`、`nginx`（可选）。
- 执行策略：
	- `DEV-MOCK`：video/audio/lipsync 使用本地 mock worker。
	- `DEV-REMOTE-GPU`：本地控制面 + 远端 GPU worker 真实执行。

### 2.2 PROD（线上）
- CPU 服务器：控制面 + 数据面 + 网关 + 中间件。
- GPU 服务器：执行面 worker + 推理服务（ComfyUI/TTS/I2V）。

## 3. 服务器与容器分配

### 3.1 CPU 服务器（控制面 + 数据面）
- `ainern2d-studio-api`（gateway/orchestrator/planner/entity-core/model-router/observer 初期可合体）
- `ainern2d-worker-hub`
- `ainern2d-composer`
- `postgres`（含 pgvector）
- `redis`
- `rabbitmq`
- `minio`
- `nginx`
- `prometheus` / `grafana`（P1 建议）

### 3.2 GPU 服务器（执行面）
- `ainern2d-worker-runtime:video`
- `ainern2d-worker-runtime:audio`
- `ainern2d-worker-runtime:lipsync`
- `ainern2d-worker-runtime:llm`（如需 GPU 推理）
- `comfyui` / 其他模型推理容器
- `dcgm-exporter`（P1 建议）

## 4. 关键流量路径
1. 用户请求进入 `nginx` -> `studio-api`。
2. `orchestrator/model-router` 生成任务并写入 `rabbitmq`。
3. GPU worker 从 `rabbitmq` 拉取任务执行。
4. 产物上传 `minio`，结果事件回发 `rabbitmq`。
5. `worker-hub/orchestrator` 回写状态至 `postgres`。
6. `composer` 读取产物并生成最终导出。
7. `studio-api` 返回发布状态，`observer` 聚合指标/告警。

## 5. 网络与安全
- 对公网仅暴露：`80/443`（`nginx`）。
- 内部组件（`postgres/redis/rabbitmq/minio/worker`）仅内网访问。
- CPU 与 GPU 机器建议通过 `WireGuard/Tailscale/VPC 内网` 互联。
- 访问控制：
	- 服务间使用服务账号与最小权限。
	- 生产环境禁用数据库公网访问。
	- 对象存储使用短期签名 URL。

## 6. Docker Compose 拆分建议
- `docker-compose.dev.yml`：Mac 本地全链路（支持 mock）。
- `docker-compose.cpu.yml`：CPU 服务器控制+数据面。
- `docker-compose.gpu.yml`：GPU 服务器执行面。

## 7. 扩展策略
- 当 `orchestrator/planner/entity-core` 负载上升，优先从 `studio-api` 拆分服务。
- 当 GPU 队列积压持续高于阈值（见 P1），横向扩展 GPU worker 副本。
- 当 RAG 检索时延超阈值，独立 `asset-knowledge/rag-service`。

## 8. 运行阈值（初始建议）
- `run` 成功率 < 95%：触发 P1 告警。
- `rabbitmq` 队列积压 > 2,000 条持续 10 分钟：触发扩容。
- GPU 利用率 > 92% 持续 15 分钟：触发降级或扩容。
- 端到端 P95 时延 > 180s：触发根因排查。

## 9. 发布与回滚
- 发布顺序：CPU 控制面 -> GPU 执行面。
- 回滚顺序：GPU 执行面 -> CPU 控制面。
- 保留最近 3 个稳定镜像标签用于快速回退。
