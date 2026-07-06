# AutoResearch Guard 代码变更简要说明

日期：2026-06-30

## 这次解决的问题

这次代码改动把 AutoResearch Guard 的主线拉回“研究质量门禁”：

- compile 前必须证明假设来自 prior art。
- reuse/build_new 决策必须可追踪。
- baseline 缺失或未超过 baseline 时不能 promote。
- 实验证据不能早于已编译协议。
- unsupported/prohibited/越界 claim 不能 promote。
- 用户可以通过 `arx_status.py --review` 看一份压缩的红黄绿 review packet。

低心智负担只是展示层约束；底层门禁仍然更严格。

## 代码层面改动

### Compile 门禁

- 新增 Markdown 表格解析能力。
- `arx_compile_goal.py` 现在会读取 `literature_review.md`：
  - `hypothesis.yaml.evidence_basis` 必须匹配候选创新点表的 `idea_id`。
  - `reuse_plan.base` 必须匹配现有实现表的 `impl_id` 或 `url`。
  - `base: build_new` 仍必须填写 `build_new_reason`。
- compile 成功时写入 `state.yaml.compiled_at`，供后续时间线审计使用。

### Evidence / Audit 门禁

- `arx_record.py` 新增 `--role` 参数，支持 `experiment` 和 `baseline`。
- `arx_audit.py` 新增 baseline gate：
  - 协议要求 baseline 时，没有 baseline 记录会阻断 `promote`。
  - 实验指标未超过 baseline 时阻断 `promote`。
- `arx_audit.py` 新增协议时间线检查：
  - ledger 记录早于 `compiled_at` 时标记协议违规。
- `arx_audit.py` 新增 claim support gate：
  - 解析 `ai_evidence_review.md` 的「结论与证据」表。
  - `unsupported`、`prohibited`、缺证据 supported claim、超过 `max_claim_level` 的 claim 都会阻断 `promote`。

### Review Packet

- `arx_status.py` 新增 `--review`。
- 输出一份人类可读的红黄绿 packet：
  - prior art
  - baseline
  - protocol integrity
  - validation gate
  - claim support
  - spiral risk
- JSON status 仍保留，并补充 baseline、claim、spiral 的结构化状态。

### 模板和文档

- `literature_review.md` 模板改为固定表格，便于人写、机器查。
- `ai_evidence_review.md` 模板新增 claim 表。
- `protocol.lock.yaml` 模板新增 baseline 配置区。
- README、workflow、prior art、claim level 文档已同步当前行为。

### Plugin manifest

- 移除了 plugin manifest 中当前 validator 不接受的 `hooks` 字段。
- `hooks/hooks.json` 仍保留，相关 hook 行为仍由测试覆盖。

## 验证

已通过：

```bash
python -m unittest discover -s autoresearch-guard/tests
python /home/ssy/.codex/skills/.system/skill-creator/scripts/quick_validate.py autoresearch-guard/skills/autoresearch-guard
python /home/ssy/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py autoresearch-guard
```

当前覆盖的新增行为：

- prior art / reuse traceability。
- baseline missing 和 baseline comparison。
- 协议编译时间线。
- unsupported/prohibited/boundary claim。
- `arx_status.py --review` review packet。
