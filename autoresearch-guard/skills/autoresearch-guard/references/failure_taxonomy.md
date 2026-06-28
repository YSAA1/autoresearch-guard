# 失败分类

在 `ai_evidence_review.md` 中解释研究失败模式时使用以下标签。仅 AI 与人工分配；脚本不校验标签是否出自本表（但 `spiral_risk` 会字符串匹配 `no_signal` / `low_information_gain` 做计数）。

- `no_signal`：验证指标未朝预期方向变化。
- `label_mismatch`：训练或排序目标与所测目标不一致。
- `proposal_headroom_low`：候选集无法暴露足够改进空间。
- `baseline_too_strong`：所选 baseline 已覆盖可用增益。
- `metric_misaligned`：所选指标奖励的行为无法支撑研究论断。
- `budget_insufficient`：实验在种子数、训练步数、数据或搜索预算上统计功效不足。
- `implementation_bug`：观测证据指向代码或数据处理缺陷。
- `protocol_violation`：因违反协议，证据无法支撑结论。
- `test_contamination`：在人工门禁前使用了测试数据或测试标签。
- `low_information_gain`：重复相同动作难以区分假设。
- `death_spiral`：连续失败且无法跳出局部调参，需考虑 abandon/pivot。
- `local_minimum_trap`：指标在小区间内反复震荡，无实质改进。
