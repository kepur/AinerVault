# Studio Web API Mapping

## 1. 页面到后端映射

| 页面动作 | API | 触发事件 | 权限 | 失败码 |
|---|---|---|---|---|
| 登录 | `POST /api/v1/auth/login` | `auth.login.succeeded/failed` | 公共 | `AUTH-VALIDATION-001` |
| 提交任务 | `POST /api/v1/tasks` | `task.submitted` | editor+ | `REQ-IDEMPOTENCY-001` |
| 查看运行状态 | `GET /api/v1/runs/{run_id}` | - | viewer+ | `AUTH-FORBIDDEN-002` |
| 重试失败任务 | `POST /api/v1/tasks/{run_id}/retry` | `job.retry.scheduled` | editor+ | `ORCH-STATE-001` |
| 发布产物 | `POST /api/v1/runs/{run_id}/publish` | `artifact.published` | editor+ | `COMPOSE-FFMPEG-001` |
| 预览实体列表 | `GET /api/v1/runs/{run_id}/preview/entities` | - | viewer+ | `REQ-VALIDATION-001` |
| 生成多角度预览 | `POST /api/v1/runs/{run_id}/preview/entities/{entity_id}/generate` | `job.dispatch` | editor+ | `REQ-VALIDATION-001` |
| 审核预览变体 | `POST /api/v1/preview/variants/{variant_id}/review` | `job.dispatch` (regenerate) | editor+ | `REQ-VALIDATION-001` |
| 固定人物音色绑定 | `PUT /api/v1/projects/{project_id}/entities/{entity_id}/voice-binding` | - | editor+ | `REQ-VALIDATION-001` |

## 2. 前端约束
- 所有写操作必须传 `idempotency_key`。
- 前端禁止直接调用 worker/composer 内部接口。
- 运行详情页必须显示 `trace_id` 与 `error_code`。

## 3. 调试定位
- 先查 `run_id`，再按 `trace_id` 拉 observer 事件链。
