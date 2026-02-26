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
| E2E-013 | persona pack 已发布 | 提交带 persona 的任务 | persona.resolved -> run.stage.changed(plan) | run 绑定 persona_pack_version_id | 输出风格一致且可追溯 | High |
| E2E-014 | creative policy 激活 | 提交策略约束任务 | policy.stack.built -> route.decision.made | run 绑定 policy_stack_id | 违规策略被拒绝并有 error_code | Blocker |
| E2E-015 | critic suite 可用 | 渲染完成后触发评审 | critic.evaluation.completed | critic_evaluations 入库 | gate_decision 生效 | High |
| E2E-016 | recovery policy 生效 | 注入执行失败 | recovery.degradation.applied -> job.retry.scheduled | recovery_executions 入库 | 降级链符合策略矩阵 | Blocker |
| E2E-017 | A/B 实验在线 | 分流同类任务 | experiment.run.completed | experiment_observations 入库 | arm 分流比例符合配置 | High |
| E2E-018 | compute budget 可用 | 高成本分镜任务 | shot.compute_budget.generated | shot_compute_budgets 入库 | 超预算任务触发降级 | High |
| E2E-019 | DSL compiler 可用 | 下发视频任务 | shot.dsl.compiled -> job.created | shot_dsl_compilations 入库 | backend 编译结果可执行 | Blocker |
| E2E-020 | RAG 反馈闭环在线 | 提交差评反馈并审核通过 | feedback.event.created -> proposal.approved -> kb.rollout.promoted | kb_version/rollout_records 更新 | 新版本对后续 run 生效 | Blocker |
| E2E-021 | continuity 预览链在线 | 提交实体多角度预览并审批 | entity.registry.resolved -> preview.variant.generated -> preview.variant.approved | entity_continuity_profiles/entity_preview_variants 入库 | 审批后锁定 continuity anchor | Blocker |
| E2E-022 | persona dataset/index 在线 | 发布 persona 绑定并执行预览召回 | persona.dataset.bound -> persona.index.bound -> persona.runtime.manifested | persona_*_bindings/persona_runtime_manifests 入库 | 10/15/17 可消费同一 persona runtime manifest | Blocker |

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
