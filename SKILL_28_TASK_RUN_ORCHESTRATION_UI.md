# 28_TASK_RUN_ORCHESTRATION_UI.md
# Task / Run Orchestration UI（任务派发与运行中心 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义 Studio 的任务中心：
- 从 Chapter 发起 Task / Run
- 选择 persona / culture pack / 负载档位
- 展示流水线状态（01~22 + 14~20 + 21~22）
- 查看日志、失败原因、重试、局部重跑
- 通知（TG/Webhook）

---

## 1. Workflow Goal（目标）
1) 将 Chapter 转成 Task
2) Run 启动时冻结版本快照（config/kb/persona/culture/policy）
3) 按 pipeline DAG 执行并更新状态
4) 支持 rerun-shot（带 patch）
5) 展示 Worker 状态（CPU/GPU/队列）

---

## 2. Integration Points（接入点）
- 01~22：作为执行入口
- 25：取 provider+router policy，并冻结 snapshot
- 22/14：选择 persona
- 27：选择 culture pack
- 18：失败恢复策略
- 16：生成后质检 gate
- 29/30：产物归档与时间线更新

---

## 3. Definition of Done
- [ ] 可从 Chapter 创建 Task 并启动 Run
- [ ] 可展示 pipeline DAG 状态与产物
- [ ] 支持 rerun-shot / rerun-stage
