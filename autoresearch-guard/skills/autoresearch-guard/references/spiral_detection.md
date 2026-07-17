# 死胡同检测（spiral_risk）

脚本用确定性信号计算 `spiral_risk`，AI 在 `ai_evidence_review.md` 判断是否真的进入死胡同。脚本不解释科学原因。

## 信号（确定性可算）

阈值由 `protocol.lock.yaml.spiral_budget` 声明，缺省用默认。

| 信号 | 计算 | 默认阈值 |
|------|------|----------|
| `same_hypothesis_attempts` | 当前 iteration 的非 baseline 记录中，从尾部开始连续 `status: fail|error` 或 `exit_code != 0` 的数量 | ≥ `max_consecutive_failures`；兼容旧字段 `max_failed_attempts`（默认 3） |
| `metric_flatline` | 成功的非 baseline 记录中，validation gate（没有 gate 时用 expected metrics）的同一 metric/split 在尾部连续变化小于 `1e-9` 的数量 | ≥ `max_flatline_count`（默认 3） |
| `no_signal_streak` | ledger 尾部连续包含结构化 `failure_tags: [no_signal]` 的记录数 | ≥ 2 |
| `repeated_blocked_actions` | 同一 blocked_action pattern 在 ledger 命令中匹配次数 | ≥ 3 |

失败记录不会参与 metric flatline。只改文字、时间戳或文件顺序也不会产生新的 metric 进展。

## 等级

- `none`：无信号
- `caution`：1 个信号
- `critical`：至少两个信号，或连续失败达到上限

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
  - `decision: proceed` 还必须设置 `requires_human: true`；先在 review 阶段执行 `arx_loop.py pause --reason "等待人工检查"`，再执行 `arx_loop.py resume --human-approved --reason "..."`，把批准绑定到当前 audit digest
- `level: caution`：仅警告，不阻断

## AI 职责

脚本只报信号。是否真死胡同、是否 stop/pivot/refine，由 AI 与人工在 `ai_evidence_review.md` 的「死胡同评估」节判断，并在 `decision.proposed.yaml.spiral_response` 写明。`failure_taxonomy.md` 的 `death_spiral` / `local_minimum_trap` 标签可用于解释。

`loop_budget` 还会把连续失败、尾部平线和连续无进展变成 Stop 熔断条件。触发后循环进入 `waiting_human`，readiness 输出 `no_progress`；它不会靠 Stop hook 继续盲试。
