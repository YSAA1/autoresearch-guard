# 死胡同检测（spiral_risk）

脚本数确定性信号触发 `spiral_risk`，AI 在 `ai_evidence_review.md` 决定是否真死胡同。脚本不判科学性，只报信号。

## 信号（确定性可算）

阈值由 `protocol.lock.yaml.spiral_budget` 声明，缺省用默认。

| 信号 | 计算 | 默认阈值 |
|------|------|----------|
| `same_hypothesis_attempts` | 同 `iteration_id` 下 ledger 中 `status: fail` 或 `exit_code != 0` 的记录数 | ≥ `max_failed_attempts`（默认 3） |
| `metric_flatline` | 同一 metric 跨记录变化幅度 < 1e-9 的连续/累计条数 | ≥ `max_flatline_count`（默认 3） |
| `no_signal_streak` | `ai_evidence_review.md` 文本中 `no_signal` 标签出现次数 | ≥ 2 |
| `repeated_blocked_actions` | 同一 blocked_action pattern 在 ledger 命令中匹配次数 | ≥ 3 |

## 等级

- `none`：无信号
- `caution`：1 个信号
- `critical`：≥2 个信号，或 `same_hypothesis_attempts` 达上限

## 输出

`audit_report.yaml` 新增字段：

```yaml
spiral_risk:
  level: none | caution | critical
  signals: [same_hypothesis_attempts, ...]
  counts:
    same_hypothesis_attempts: 3
    metric_flatline: 0
    no_signal_streak: 0
    repeated_blocked_actions: 0
```

## escape gate（arx_decide.py）

- `level: critical`：
  - `decision.proposed.yaml` 必须含非空 `spiral_response`（解释为何不是死胡同，或确认 abandon/pivot 理由）
  - 缺 `spiral_response` → 拒绝提交
  - `decision: proceed` 在 critical 时**禁止**（除非 `spiral_response` 反驳 + `requires_human: true`）
- `level: caution`：仅警告，不阻断

## AI 职责

脚本只报信号。是否真死胡同、是否 abandon/pivot，由 AI 在 `ai_evidence_review.md` 的「死胡同评估」节判定，并在 `decision.proposed.yaml.spiral_response` 写明。`failure_taxonomy.md` 的 `death_spiral` / `local_minimum_trap` 标签供 AI 引用。
