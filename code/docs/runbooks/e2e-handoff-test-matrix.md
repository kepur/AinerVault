# E2E Handoff Test Matrix（P0）

## 1. 目标
- 为“其他 AI/团队交替实现”提供统一验收基线。
- 覆盖主链路、失败链路、幂等链路、告警链路。

## 2. 用例矩阵

| ID | 前置条件 | 输入 | 期望事件序列（摘要） | 期望数据状态 | 通过标准 | 阻断级别 |
|---|---|---|---|---|---|---|
| E2E-001 | 用户已创建 | 登录请求 | auth.login.succeeded | 会话有效 | 返回200且会话可用 | Blocker |
| E2E-002 | 项目存在 | 提交 task | task.submitted -> run.created | execution_request/run 创建 | run 进入 queued/running | Blocker |
| E2E-003 | run 已创建 | 触发规划 | run.stage.changed(plan) -> plan.shot.generated | shot_plan 入库 | shot_plan 有效且非空 | Blocker |
| E2E-004 | 规划完成 | 触发路由 | route.decision.made -> job.created | jobs 入库 | worker_type/model_profile 有值 | Blocker |
| E2E-005 | GPU worker 在线 | 消费 job | job.claimed -> job.succeeded（细节：worker.video.completed） | artifact(shot_video) 入库 | 产物可访问且 checksum 有值 | Blocker |
| E2E-006 | audio worker 在线 | 音频任务 | job.claimed -> job.succeeded（细节：worker.audio.completed） | artifact(audio) 入库 | timeline 可合并 | High |
| E2E-007 | composer 在线 | 合成任务 | compose.started -> compose.completed -> artifact.published | final_video 产物入库 | 可下载播放 | Blocker |
| E2E-008 | run 失败注入 | 强制报错 | job.failed -> run.failed -> error.recorded | error_code/trace_id 完整 | 失败归因可追踪 | Blocker |
| E2E-009 | 幂等键重复 | 重复提交 task | task.submitted（1次有效） | 不产生重复 run/job | 冲突返回可解释错误 | High |
| E2E-010 | 重复消费模拟 | 重放同 event | job.succeeded（幂等一次） | 状态不回退/不重复写 | 去重生效 | High |
| E2E-011 | 告警系统在线 | 队列堆积注入 | alert.triggered | observer 告警记录 | 告警在阈值内触发 | Medium |
| E2E-012 | RAG recipe 生效 | prompt planner 调用 | plan.prompt.generated | prompt 记录 kb_version/recipe_id | 检索注入内容符合过滤条件 | High |

## 3. 验收门禁
- Blocker 用例全部通过才可上线。
- High 通过率需 >= 95%。
- 失败用例必须有 `error_code` 与可回滚结论。

## 4. 执行记录模板
- 执行人：
- 环境：DEV-MOCK / DEV-REMOTE-GPU / PROD-STAGE
- 版本：
- 用例通过率：
- Blocker 失败项：
- 处理结论：Go / No-Go
