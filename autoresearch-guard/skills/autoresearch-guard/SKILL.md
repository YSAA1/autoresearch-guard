---
name: autoresearch-guard
description: 在任何领域的研究、调研、实验、代码分析或资料整理需要可恢复状态和诚实收口时使用。先自由推进；只有用户或模型要声明 verified 结论时，才锁定验证契约并记录检查证据。
---

# AutoResearch Guard

以下的 `arx` 是 `python <本 Skill 目录>/scripts/arx.py`。状态保存在 `.research/`；若从子目录运行，会复用最近祖先已有的 `.research/`。

## 进入任务时

先运行：

```bash
arx status --json
```

- `idle`：运行 `arx start --goal "..."`。
- `active`：继续当前研究。不要为了满足插件而制造报告、实验或额外文件。
- `paused`：根据暂停原因决定 `arx resume`、`arx finish`，或继续等待。
- `legacy`：告诉用户发现旧状态。只有确认旧内容应保留时，运行 `arx start --goal "..." --archive-legacy`。
- `corrupt`：停止写入，先检查 `status` 给出的原因。

## 研究过程保持自由

研究判断属于模型和用户：选资料、定方法、判断证据是否可信、解释失败、决定下一步。可以使用插件级的 arXiv 和 Semantic Scholar MCP，也可以使用其他来源；MCP 不可用不能阻断任务。

不要引入固定阶段、尝试次数、预算、baseline、split、seed 或自动续跑。反复失败或没有新信息时，优先用 `inconclusive` 或 `blocked` 诚实收口。

## 需要声明 verified 时

先自行写一份 JSON 验证契约，再冻结它：

```bash
arx verify lock --file verification.json
```

契约只能有 `claim` 和 `checks`。每个 check 需要唯一的 `id`、通过条件 `criterion`、检查方式 `method` 和所需证据 `evidence_required`。详细形状见 [references/verification.md](references/verification.md)。

每完成一项检查后记录结果：

```bash
arx verify record --check CHECK_ID --verdict pass \
  --evidence REF... --reason "为什么这个结果成立"
```

`pass` 至少需要一条证据；`fail` 和 `unknown` 也必须写原因。相同结果可以安全重试。若契约要变，使用 `--revise` 创建新版本，不要直接编辑 `vNNN.json`。

只有当前版本的每一项检查最新结果都是 `pass`，才允许：

```bash
arx finish --outcome verified --summary "..."
```

CLI 只检查字段、冻结摘要和结果是否齐全，不替你判断证据真假或结论是否合理。

## 收口

所有收口都需要 summary：

```bash
arx finish --outcome unverified --summary "..."
arx finish --outcome inconclusive --summary "..."
arx finish --outcome stopped --summary "..."
arx finish --outcome blocked --summary "..."
```

成功后 `current` 自动归档。`pause --reason "..."` 与 `resume` 适合短暂中断；它们不是第二套研究循环。

## 约束

- 不要把工具退出码、模型自述或空泛说明当作证据。
- 不要直接修改锁定验证文件。摘要漂移会拒绝新的 record 和 `verified` 收口。
- SessionStart Hook 只读提示，不是门禁。最终状态以 CLI 为准。
