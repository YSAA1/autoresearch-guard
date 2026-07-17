# AutoResearch Guard

AutoResearch Guard 是一个 Codex 插件，用来约束可重复的研究循环。Codex 负责提出假设、解释证据和做研究决策；插件里的 Python 脚本负责状态迁移、证据台账、确定性审计、预算熔断和归档。

它不自己实现 agent runner。整个系统分三层：

```text
Codex agent turn      宿主内部的模型/工具循环
Codex Goal 模式       跨 turn 继续执行 active_goal.md
Research campaign     .research 中可恢复的研究状态、证据和决策
```

过去由 Stop hook 反复催促的做法容易形成死循环，也会误伤无关会话。现在 Goal 模式负责续跑，Stop hook 最多纠偏一次；插件用持久预算、owner session 和统一 readiness 判定决定何时停下。

## 项目结构

```text
autoresearch-guard/
├── .codex-plugin/plugin.json
├── .mcp.json
├── hooks/
│   ├── hooks.json
│   ├── hook_runtime.py
│   ├── session_recovery.py
│   └── stop_goal_guard.py
├── skills/autoresearch-guard/
│   ├── SKILL.md
│   ├── scripts/
│   ├── templates/
│   └── references/
└── tests/
```

本地 marketplace 定义在 `.agents/plugins/marketplace.json`。插件声明了两个可选研究 MCP：Semantic Scholar 和 arXiv。它们通过 `uvx` 启动，因此机器上需要安装 [uv](https://docs.astral.sh/uv/)。MCP 不可用时，文献阶段可以改用 Web 搜索。

## 状态机

每轮研究只有一个 `.research/current/`。主阶段固定为：

```text
draft -> execution -> review -> closure -> archived
```

控制状态与研究决策分开保存。常见状态有 `idle`、`armed`、`running`、`closing`、`waiting_human`、`aborted` 和 `complete`。`decision.yaml` 中的 `promote`、`refine`、`pivot`、`proceed` 或 `stop` 不会代替控制状态。

查看当前状态：

```bash
python autoresearch-guard/skills/autoresearch-guard/scripts/arx_loop.py check \
  --research-root .research --json
```

`ready: true`（即 `goal_ready`）才表示当前 iteration 可以归档。`check --json` 还会给出 `process_ready` / `outcome_ready`：流程齐了但 outcome 未达标时不得伪装成 `achieved`。预算耗尽、连续失败、指标长期不动和等待人工都会停止自动续跑，但不会冒充成功。

## 运行一轮研究

以下命令假设当前目录是要研究的项目根目录。

```bash
S=autoresearch-guard/skills/autoresearch-guard/scripts

python "$S/arx_init.py" \
  --research-root .research \
  --iteration-id demo-i1 \
  --title "Demo" \
  --objective "验证一个有界假设" \
  --hypothesis "候选方法应改善 validation 指标"
```

初始化后，先填写这些文件：

- `research.yaml`：问题、非目标、claim 等级目标、成功标准、claims、gaps、sources、conflicts、adversary。
- `outcome.yaml`：可检成功条件（与 `research.yaml.success_criteria` 一起构成 outcome gate）。
- `literature_review.md`：至少一个带 `idea_id` 的候选思路，以及一个现有实现。
- `hypothesis.yaml`：`evidence_basis` 要引用该 `idea_id`；`reuse_plan.base` 要引用现有实现，或填写 `build_new` 和理由。
- `protocol.lock.yaml`：填写划分、指标、门禁和预算，人工检查后设为 `locked: true`。
- `claim_boundary.yaml`：`max_claim_level` 为 `exploratory|supported|verified`。

单次搜索加自填报告不能归档，也不能把结论标成 `verified`。

未锁协议只能生成草稿，不会进入 execution：

```bash
python "$S/arx_compile_goal.py" --research-root .research --allow-unlocked
```

锁定后编译正式 Goal，再启动外层循环：

```bash
python "$S/arx_compile_goal.py" --research-root .research
python "$S/arx_loop.py" start --research-root .research --session-id manual-demo
```

把 `.research/current/active_goal.md` 交给 Codex Goal 模式。每个有意义的实验都用稳定的 `attempt_id` 记录；同一 id 和同一内容可安全重试，同一 id 对应不同内容会被拒绝。

```bash
python "$S/arx_record.py" \
  --research-root .research \
  --iteration-id demo-i1 \
  --attempt-id demo-validation-1 \
  --command "python eval.py --split validation --seed 0" \
  --data-split validation \
  --seed 0 \
  --status pass \
  --metric score=0.73
```

第一次审计会进入 review。填写 `ai_evidence_review.md` 的 claim support 表后要再审计一次。若要 `promote`：`prepare-review` 后由同会话 review subagent 写 `subagent_review.yaml`（主 agent 自填不能替代）。`verified` 只走 audit 格式门禁。Audit 和 decision 的文件 digest 都会写入 `state.yaml`；直接修改已提交产物会让 readiness 失败。

```bash
python "$S/arx_audit.py" --research-root .research
# 填写 .research/current/ai_evidence_review.md
python "$S/arx_audit.py" --research-root .research
python "$S/arx_loop.py" prepare-review --research-root .research
# review subagent -> subagent_review.yaml
python "$S/arx_status.py" --research-root .research --review
```

如果 review 后还要补实验，必须显式回到 execution：

```bash
python "$S/arx_loop.py" resume \
  --research-root .research \
  --reason "补充缺失证据" \
  --reopen-execution
```

提交决策。`refine`、`pivot` 和 `proceed` 等继续型决策还需要填写有意义的 `next_goal.md`。

```bash
python "$S/arx_decide.py" \
  --research-root .research \
  --decision refine \
  --reason "当前证据支持缩小范围后再验证"

# 填写 .research/current/next_goal.md
python "$S/arx_loop.py" check --research-root .research --require-ready
python "$S/arx_archive.py" --research-root .research
```

如果 audit 把 spiral 标为 critical，但人工仍决定 `proceed`，先暂停 review，再把批准绑定到当前 audit：

```bash
python "$S/arx_loop.py" pause \
  --research-root .research \
  --reason "等待人工检查 critical spiral"
python "$S/arx_loop.py" resume \
  --research-root .research \
  --reason "人工批准一次有界尝试" \
  --human-approved
```

也可以一步归档旧轮并初始化新轮。旧轮必须已经 ready：

```bash
python "$S/arx_init.py" \
  --research-root .research \
  --archive-existing \
  --iteration-id demo-i2 \
  --title "Demo I2"
```

`--force` 只用于恢复。它不会覆盖旧 `current/`，而是要求 `--force-reason`，先把未完成状态作为 recovery archive 保存。即使 `state.yaml` 缺失或损坏，原始文件和错误原因也会留在 recovery manifest 中。

## Hooks

Hooks 默认关闭。初始化时加 `--enable-hooks` 才会让当前 `.research` 使用它们；Codex 侧仍需 trust 对应 hook 配置。运行中可用 `arx_loop.py hooks --on|--off` 切换；不加开关则打印当前值。

Hook 查找 `.research` 时会从 cwd 向上走，但遇到独立项目边界（如 `.git`、`package.json`、`pyproject.toml`，或显式 `.arx-boundary`）且该层没有 campaign 时会停止，避免 monorepo 子包继承父级 hooks。

- `SessionStart` 读取当前状态并补充恢复上下文。
- `PreToolUse` 提前拦截禁用划分、blocked action、非 owner 实验，以及对锁定协议的 Bash、apply_patch、Edit 或 Write 修改。只读查看协议不会被当成修改。
- `PostToolUse` 只提醒调用 `arx_record.py`，不会把一次工具成功当成实验成功。
- `Stop` 只对 owner session 生效。首次未闭环可以返回一次 `decision: block`；`stop_hook_active: true`、非 owner、后台任务和等待人工都会放行。后续 turn 若已用完 continuation 总额，或预算熔断、内部错误发生，会返回 `continue: false`。

Hooks 不是安全边界。它们可能未启用、未 trust、超时，PreToolUse 也不能覆盖所有执行路径。最终门禁仍由 `arx_record.py`、`arx_audit.py`、`arx_decide.py` 和 `arx_archive.py` 重新检查。

## 验证

最短的可执行 smoke 会走过状态迁移、并发 ledger/audit、修改后的 audit/decision、owner hook、Stop 重入、预算熔断、raw recovery、归档失败恢复，以及含中文和空格的安装副本：

```bash
ARX_TEST_TMP=/tmp python -m unittest discover \
  -s autoresearch-guard/tests \
  -p 'test_loop_engineering.py' \
  -v
```

完整验证：

```bash
ARX_TEST_TMP=/tmp python -m unittest discover -s autoresearch-guard/tests -v
python "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" \
  autoresearch-guard/skills/autoresearch-guard
python "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/validate_plugin.py" \
  autoresearch-guard
```

设计边界、已实现保证和剩余限制见 [循环契约](autoresearch-guard/skills/autoresearch-guard/references/loop_contract.md)。
