# hub.P1.C3 独立复核报告（非作者复核 hub.P1.C2）
角色：verifier；负责人：muse-spark-x7q2（非 C2 作者 opencode-7k2q）；时间：2026-10-15
任务状态：reported；结论：建议 accept（仅 CPU 合同范围）；依据：hub.P1.C2 报告、review_standard_v0.md（hub.P1.C1）、review_record_v0.schema.json
输入身份：标准 6ae005b5…dfc71e；schema 818c2f58…b966266；review_contract.py 4d46ce53…869bcfd（与 C2 evidence 一致，未改）；作者测试 677b7c2d…01fd28a8c；本探针 eb079f9a…bc086210b4
修改文件：仅 reports/V-production-review-contract/（probe_counterexamples.py、probe.jsonl、evidence.json、report.md、metrics.json）；未改源码
实际执行：`TMPDIR=/tmp/hub-p1-c3-verify .venv/bin/python -m pytest tests/test_production_review_contract.py -q -p no:cacheprovider` → 29 passed（基线）；`PYTHONPATH=code/apps/ainer-core .venv/bin/python reports/V-production-review-contract/probe_counterexamples.py` → exit 0，12/12 hold；文件写入只用新临时根与报告目录；纯 CPU，未导入 MLX/ORT/模型，未读媒体/DB，未安装依赖，未提交推送
验证结果：正例对照 4/4 通过（issue/verdict/comparison/choice 有效输入均 []）；7 个新反例（作者 29 测试未覆盖）全部按预期错误码被拒：N1 same_take、N2 hard_constraints_skipped、N3 wrong_reviewer、N4 unknown_selection、N5 missing_evidence（硬 unverified+总体 pass）、N6 stale_media（sha 不一致）、N7 lock_violation（false+paths 矛盾）；变异敏感性：恒过桩下坏 verdict 漏网、恢复后重现 blocker_overridden，探针非空转；源码无 `open(`/sqlite/MLX/ORT/SQLAlchemy` 导入（只读 grep，与作者断言一致方向）
产物：本目录 report.md、metrics.json、evidence.json、probe_counterexamples.py、probe.jsonl
失败与限制：未跑全量 ainer-core 套件（超出范围）；无真实盲评成片可核（C1 亦记无）；未做跨仓 E2E；ruff 在 hub .venv 无模块未跑（探针单文件、风格与仓内一致，_contract 侧 ruff 已在 AWZ 侧通过，不混为一谈）
交回统筹：CPU 合同范围成立，建议 accept hub.P1.C2；晋升/真实审片/消费者链路仍未验证，不自动外推；参数 {} 照用
