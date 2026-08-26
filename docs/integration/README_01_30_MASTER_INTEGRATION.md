# README_01_30_MASTER_INTEGRATION.md
# 01~30 总接入说明：把 01~22 流水线接入 Studio

## 关键结论
- 01~22 是后端生成流水线与工业增强层（你已具备）
- 23~30 是产品层（Studio/Admin/NLE/Config/Task/Asset），把流水线变成可用产品

## 推荐主链（Run 执行顺序）
1. 24 Chapter -> raw_input
2. 28 创建 Task/Run（冻结快照：25/11/12/14/22/27/15/19）
3. Run DAG（建议顺序）
   - 01 -> 02 -> 03 -> 04 -> 21 -> 05 -> 06 -> 07 -> 08 -> 14 -> 15 -> 19 -> 09 -> 10 -> 20 -> 渲染执行 -> 16 -> 18（按需）-> 13（进化/可选）
4. 29 归档所有产物
5. 30 时间线显示 06/09/10/20，并支持 patch -> 28 rerun-shot
6. 26/22 用于导演A/B/C数据集与索引管理；27 用于 culture pack 管理；25 用于API与模型路由。

## 23~30 与 01~22 的接入映射（最关键）
- 24 -> (01/02/03)：章节预览规划
- 28 -> 全链路执行（01~22+14~20+21~22）
- 29 <- 接收并归档 06/08/09/10/20 产物 + 21 anchors
- 30 <- 以 06 timeline_final 为基准，叠加 09 render plan、10 prompt plan、20 compiled bundle
- 25 -> 为所有阶段提供 provider+router policy，并在 Run 启动时冻结 snapshot
- 26 -> 统一管理 11/12/14/22（RAG+Persona）
- 27 -> 统一管理 culture packs，并供 02/07/10 使用

## MVP（从 0 到能用）
Phase 1：24 + 25(最少1 provider) + 28 + 29 + 30(只读+patch重试) -> 可闭环
Phase 2：26 + 27 + 11/12/22 -> 导演A/B/C + RAG进化
Phase 3：16/18/17 -> 工业质检门 + 自动恢复 + A/B推荐
