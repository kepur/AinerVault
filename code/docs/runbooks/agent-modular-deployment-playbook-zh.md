# Agent Modular Deployment Playbook（可拆分部署）

## 1. 目标
- 给 Agent 一份可直接执行的部署规范，支持“整栈部署”和“按模块拆分部署”。
- 保持运行时契约稳定：`run/job/stage/event/artifact` 不因拆分而变化。

## 2. 当前服务拓扑（来自 `code/docker-compose.yml`）

### 2.1 基础设施层（可独立集群）
- `postgres`（5432）
- `rabbitmq`（5672 / 15672）
- `redis`（6379）
- `minio`（9000 / 9001）

### 2.2 控制面 / 执行面
- `studio-api`（8000）: 主 API、编排入口、Ops Bridge 接口
- `studio-web`（5173）: 工作台前端
- `worker-hub`（8010）: 异步任务分发/聚合
- `composer`（8020）: 合成/后处理
- `nginx`（80）: 反向代理（可选）

## 3. 模块拆分矩阵

| 模块 | 可单独部署 | 最低依赖 | 典型用途 |
|---|---|---|---|
| 基础设施（PG/RabbitMQ/Redis/MinIO） | 是 | 无 | 所有上层服务公共依赖 |
| Studio API | 是 | postgres, redis（建议）, rabbitmq（异步链路） | 业务 API、Ops Bridge、配置中心 |
| Studio Web | 是 | studio-api | 仅 UI 工作台 |
| Worker Hub | 是 | postgres, rabbitmq | 任务分发与状态聚合 |
| Composer | 是 | postgres, rabbitmq, minio | 渲染合成链路 |
| Nginx | 是 | studio-api / worker-hub / composer / studio-web | 单入口网关 |

## 4. 推荐的分阶段部署形态

## 4.1 形态 A：控制面最小可用（先调通 UI + API + Ops Bridge）
- 适用：先验证登录、配置、Ops Bridge 上报、项目/模型管理。

```bash
cd code
docker compose up -d postgres redis rabbitmq minio
docker compose up -d studio-api studio-web
```

验收：
- `http://localhost:5173`
- `curl -fsS http://localhost:8000/healthz`

## 4.2 形态 B：异步执行链路（在 A 基础上扩容）
- 适用：开始跑 run/job、轨道任务、异步调度。

```bash
cd code
docker compose up -d worker-hub composer
```

验收：
- `curl -fsS http://localhost:8010/healthz`
- `curl -fsS http://localhost:8020/healthz`

## 4.3 形态 C：全栈本地（开发联调）

```bash
cd code
docker compose up -d
```

## 4.4 形态 D：模块抽离到不同机器（生产/准生产）
- 常见拆法：
  - 机器 1：`studio-api + studio-web`
  - 机器 2：`worker-hub + composer`
  - 机器 3：`postgres + rabbitmq + redis + minio`
- 核心要求：所有服务改为“外部地址配置”，不要再用容器内服务名。

## 5. 模块抽离时必须统一的环境变量

至少统一以下变量（见 `code/.env.example`）：
- `DATABASE_URL`
- `RABBITMQ_URL`
- `REDIS_URL`
- `S3_ENDPOINT`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_BUCKET`

说明：
- 同机同 compose 可用服务名（如 `postgres`）。
- 跨机器必须改成可路由地址（IP/域名）。

## 6. 数据库迁移（每次升级必做）

```bash
cd code
docker compose exec studio-api sh -lc "cd /workspace/apps && python -m alembic upgrade head"
```

如果做发布门禁，建议补一轮回归：
- `upgrade -> downgrade -> upgrade`（在预发库执行）

## 7. Agent 部署检查清单（上线前）

1. `studio-api`、`worker-hub`、`composer` 的 `/healthz` 全绿。  
2. `studio-web` 能访问并可调用 API（无跨域/代理错误）。  
3. Alembic 已到 `head`。  
4. RabbitMQ/Redis/MinIO 可连通。  
5. 异步链路验证：创建一个最小 run，观察 `job.succeeded/job.failed` 事件闭环。  
6. Ops Bridge 验证：`POST /api/v1/ops-bridge/report` 成功并可在模型列表看到上报记录。  

## 8. 回滚策略（模块化）

- 代码回滚：仅回滚变更模块镜像（不要整栈回滚）。
- DB 回滚：只在确认兼容时做迁移回退；优先“前向修复”。
- 运行降级：
  - 若 `worker-hub/composer` 异常，保留 `studio-api/web` 提供配置与只读能力。
  - 若 `studio-web` 异常，保留 `studio-api` 供自动化/脚本调用。

## 9. 与架构契约的一致性要求

拆分部署不改变以下规则：
- 仅 orchestrator 推进主阶段状态。
- `worker.*.completed` 仅执行明细，不替代主状态。
- 所有写链路必须带：`tenant_id/project_id/trace_id/correlation_id/idempotency_key`。

参考权威：
- `ainer_contracts.md`
- `ainer_event_types.md`
- `code/docs/architecture/stage-enum-authority.md`
- `code/docs/architecture/service-api-contracts.md`
- `code/docs/architecture/queue-topics-and-retry-policy.md`

---

一句话给 Agent：

先上 `A(控制面)`，再上 `B(执行面)`；每拆一个模块都先改依赖地址、跑 healthz、跑最小 run 闭环。
