# AutoResearch Guard 工作流

`.research/current/` 是当前 iteration 的唯一工作目录。跨轮经验放在 `.research/lessons/`，归档放在 `.research/archive/`。不要把临时状态写进插件安装目录或只留在对话里。

## 目录

```text
.research/
├── .arx.lock
├── current/
│   ├── state.yaml
│   ├── events.jsonl
│   ├── research.yaml
│   ├── literature_review.md
│   ├── hypothesis.yaml
│   ├── protocol.lock.yaml
│   ├── blocked_actions.yaml
│   ├── claim_boundary.yaml
│   ├── active_goal.draft.md       # 可选；未锁协议的草稿
│   ├── active_goal.md             # 正式编译后生成
│   ├── evidence_ledger.jsonl
│   ├── audit_report.yaml
│   ├── ai_evidence_review.md
│   ├── decision.proposed.yaml
│   ├── decision.yaml
│   ├── next_goal.md
│   └── archive_manifest.yaml      # 归档前生成
├── lessons/
│   ├── retained_lessons.md
│   └── anti_patterns.yaml
└── archive/
    └── <timestamp>-<iteration>-<suffix>/
```

## 状态机

`state.yaml` 同时保存研究阶段和循环控制状态。两者不要混用。

阶段只有五个：

```text
draft -> execution -> review -> closure -> archived
```

| 动作 | 允许的起点 | 结果 |
|---|---|---|
| `arx_init.py` | 没有 current，或先安全归档旧 current | `draft/idle` |
| `arx_compile_goal.py --allow-unlocked` | `draft` 且协议未锁 | 保持 `draft/idle`，只写草稿 |
| `arx_compile_goal.py` | `draft` 且协议已锁 | `execution/armed` |
| `arx_loop.py start` | `execution/armed` | `execution/running` |
| `arx_record.py` | `execution/armed|running` | 阶段不变 |
| `arx_audit.py` | `execution|review` | `review/closing` |
| `arx_loop.py resume --reopen-execution` | `review/closing|waiting_human` | `execution/armed` |
| `arx_decide.py` | `review` 且 audit 为最新 | `closure/closing` |
| `arx_loop.py pause` | `execution|review|closure` | `waiting_human`，释放 owner |
| `arx_loop.py abort` | `draft|execution|review|closure` | `aborted`，释放 owner |
| `arx_archive.py` | readiness 为 ready | 移到 archive，归档状态为 `archived/complete` |

脚本会拒绝逆序操作。decision 后不能再记录 evidence；要补证据，必须在 decision 前从 review 显式回到 execution。

## 一轮研究

### 1. 初始化和 prior art

```bash
python scripts/arx_init.py \
  --research-root .research \
  --iteration-id EXP-I1 \
  --title "实验 I1"
```


用队列声明唯一 next item：

```bash
python scripts/arx_loop.py queue --enqueue --id w1 --kind attempt \
  --acceptance "Record one validation attempt that meets the gate" \
  --research-root .research
python scripts/arx_loop.py queue --claim --id w1 --research-root .research
```

### 2. 假设和协议

填写 `hypothesis.yaml`：

- `iteration_id` 必须和 `state.yaml` 一致。
- `evidence_basis` 引用文献表中的 `idea_id`。
- `reuse_plan.base` 引用实现表中的 id/url，或使用 `build_new` 并写理由。
- `allowed_work`、`forbidden_work` 和 `must_produce` 要具体。

填写 `protocol.lock.yaml`：

- allowed/forbidden splits；
- expected metrics 和 validation gates；
- baseline 规则；
- seed 要求；
- `loop_budget` 和兼容旧配置的 `spiral_budget`；
- required outputs。

需要先看 Goal 文本时运行：

```bash
python scripts/arx_compile_goal.py --research-root .research --allow-unlocked
```

这只写 `active_goal.draft.md`。人工检查并把 `locked` 设为 `true` 后，正式编译：

```bash
python scripts/arx_compile_goal.py --research-root .research
python scripts/arx_loop.py smoke --research-root .research
python scripts/arx_loop.py start --research-root .research --session-id <session-id>
```

正式编译把 protocol digest 和预算写入 `state.yaml`，并进入 `execution/armed`（要求恰好 1 条 `in_progress`）。`smoke` 写入新鲜度事件；`start`/`record` 默认要求干净 git（`.research` 外无脏文件）或显式 `--allow-dirty`。`start` 可以显式绑定 owner；启用 hooks 时，首次 loop 或实验命令也能认领当前 Codex session。

### 3. 实验和 evidence

每次有意义的实验使用一个稳定 `attempt_id`：

```bash
python scripts/arx_record.py \
  --research-root .research \
  --iteration-id EXP-I1 \
  --attempt-id exp-i1-seed0 \
  --command "python eval.py --split validation --seed 0" \
  --data-split validation \
  --seed 0 \
  --status pass \
  --metric score=0.72
```

记录 baseline 时加 `--role baseline`。失败时填写真实 `--exit-code`、`--status fail|error`，并用 `--failure-tag` 写结构化标签。失败 evidence 会留在 ledger 供诊断，但不会进入 validation gate 或 baseline 的成功值计算。

相同 attempt id 和相同语义内容再次提交是 no-op；同一个 id 对应不同内容会报冲突。每条记录保存 canonical iteration、protocol digest 和 state revision。`arx_record.py` 在 root lock 内重查 phase、loop status 和协议，避免 pause/audit 与 record 交错。

### 4. Audit 和 review

```bash
python scripts/arx_audit.py --research-root .research
```

审计会：

- 只接纳当前 iteration 的记录；foreign 记录会成为违规。
- 检查协议是否锁定、digest 是否与 compile 时一致、记录是否晚于 compile。
- 检查 split、seed、result/config digest、blocked actions 和 expected metrics。
- 只用成功的非 baseline evidence 计算 validation gates。
- 单独检查 baseline 和 claim support。
- 根据连续失败、声明门禁 metric 的尾部平线、结构化 `no_signal` 和重复 blocked action 计算 `spiral_risk`。
- 在同一个 root lock 内读取 ledger、计算门禁、写入输入 digests 和 audit，再进入 `review/closing`。并发 record 要等 audit 完成，随后会因 phase 已变化而被拒绝。
- 把生成的 audit digest 写入 canonical state。直接修改 `audit_report.yaml` 后，decision 会拒绝它。

接着填写 `ai_evidence_review.md`。claim 表至少包括：

```markdown
| claim_id | 结论 | 等级 | 证据 | 状态 |
|---|---|---|---|---|
| c1 | 当前 validation 结果支持继续验证 | validation | ledger:attempt-id | supported |
```

填写后必须再次运行 audit。否则 review digest 已变化，`arx_decide.py` 会把旧报告视为 stale。

对 `verified` 或准备 `promote` 时，还要走同会话 subagent 验收（不能用人手另开 Codex session，也不能用主 agent 自填 review 替代）：

```bash
python scripts/arx_loop.py prepare-review --research-root .research
# spawn review subagent：只读 .research/current/review_pack/，写出 subagent_review.yaml
# verdict=pass，bound_audit_digest=当前 audit，reviewer_role=subagent
```

如果审查发现还缺实验：

```bash
python scripts/arx_loop.py resume \
  --research-root .research \
  --reason "补充缺失证据" \
  --reopen-execution
```

补完 evidence 后重新 audit 和 review。

### 5. Decision 和 closure

可以填写 `decision.proposed.yaml`，也可以直接用命令行：

```bash
python scripts/arx_decide.py \
  --research-root .research \
  --decision refine \
  --reason "指标改善，但证据仍只到 validation 等级"
```

`arx_decide.py` 会检查 state 锚定的 fresh audit、已填写的 claim 表、`forbidden_decisions` 和 spiral escape gate。提交后把 decision digest 写入 canonical state，再进入 `closure/closing`，此时 evidence 冻结。直接修改 `decision.yaml` 会让 readiness 和 archive 失败。

Critical spiral 下若仍要 `proceed`，先暂停 review，再记录针对当前 audit 的人工批准：

```bash
python scripts/arx_loop.py pause \
  --research-root .research \
  --reason "等待人工检查 critical spiral"
python scripts/arx_loop.py resume \
  --research-root .research \
  --reason "人工批准一次有界尝试" \
  --human-approved
```

`--human-approved` 不能在 armed/closing 状态下提前写入，也不能复用到另一个 audit。

closure 的共同条件：

- 当前阶段是 `closure`。
- `evidence_ledger.jsonl` 至少有一条属于本轮的记录。
- `audit_report.yaml`、`ai_evidence_review.md` 和 `decision.yaml` 有意义且不是占位。
- protocol 仍锁定，digest 未漂移。
- audit 的输入 digests 与当前 protocol、hypothesis、blocked actions、claim boundary、ledger 和 AI review 一致；audit 文件 digest 与 state 中的锚点一致。
- decision 的 `audit_digest`、`input_digests`、forbidden decision 检查和 critical gate 仍有效；decision 文件 digest 与 state 中的锚点一致。
- 本轮有失败时，`lessons/anti_patterns.yaml` 有本轮 `iteration_id` 的条目。
- decision 为 `proceed`、`refine` 或 `pivot` 时，`next_goal.md` 已替换占位内容。

统一检查：

```bash
python scripts/arx_loop.py check --research-root .research --json
python scripts/arx_loop.py check --research-root .research --require-ready
```

若预算或无进展阈值已触发，`arx_loop.py check` 会把 loop 置为 `waiting_human`、释放 owner，并返回 `budget_exhausted` 或 `no_progress`。这条规则不依赖 hooks 是否启用。

只有 `ready: true` 才能正常归档：

```bash
python scripts/arx_archive.py --research-root .research
```

## 归档和下一轮

### 继续下一轮

1. 填好当前轮的 `next_goal.md`。
2. 把可复用经验追加到 `lessons/`。
3. 运行 `arx_archive.py`，或在初始化下一轮时使用 `--archive-existing`。
4. 根据上一轮 `next_goal.md` 明确传入新一轮 id、objective 和 hypothesis。初始化器不会替你解释或复制下一轮科学假设。

```bash
python scripts/arx_init.py \
  --research-root .research \
  --archive-existing \
  --iteration-id EXP-I2 \
  --title "实验 I2" \
  --objective "上一轮 next_goal.md 中的有界目标"
```

### 结束研究

decision 为 `stop` 或 `promote` 时不要求 `next_goal.md`。补齐 lessons 和 closure 产物后直接归档。

### 恢复未完成状态

`--force` 不会覆盖旧目录。它先把旧 current 归档为 `allow_incomplete: true`，并在 manifest 记录原因。即使 `state.yaml` 缺失或无法解析，也会保存原始文件 digest 和解析错误：

```bash
python scripts/arx_init.py \
  --research-root .research \
  --force \
  --force-reason "恢复中断且无法继续的 iteration" \
  --iteration-id RECOVERY-I2
```

这是人工恢复入口，不是普通 rollover。当前实现没有多文件事务 journal；异常中断后要先检查 `state.yaml`、`events.jsonl`、archive manifest 和目录结构，再决定继续还是 recovery archive。正常 archive 的目录移动若在进程内报错，会恢复 closure state；进程被强杀仍需人工检查。

## 文件职责

| 文件 | 主要写入者 | 确定性用途 |
|---|---|---|
| `state.yaml` | lifecycle 脚本和 hooks | canonical iteration、phase、revision、owner、预算、运行计数，以及 audit/decision digest 锚点。 |
| `events.jsonl` | lifecycle 脚本和 hooks | 状态迁移、attempt 和 hook 判定的结构化事件。 |
| `literature_review.md` | AI | compile 检查被引用的 idea 和现有实现。 |
| `hypothesis.yaml` | AI | compile 检查必填字段、prior art 和 reuse 绑定；audit digest 输入。 |
| `protocol.lock.yaml` | AI/人工 | compile、record 和 audit 的协议来源；锁定后不应修改。 |
| `blocked_actions.yaml` | AI/人工 | audit 检查是否触碰禁用动作。 |
| `claim_boundary.yaml` | AI/人工 | active goal 和 claim support 门禁。 |
| `active_goal.md` | compile 脚本 | Codex Goal 模式的当前目标、边界和停止条件。 |
| `evidence_ledger.jsonl` | `arx_record.py` | 带 iteration/protocol/revision 的幂等 evidence 台账；audit 和预算的输入。 |
| `audit_report.yaml` | `arx_audit.py` | 门禁、spiral 信号、输入 digests 和 forbidden decisions；文件 digest 锚定在 state。 |
| `ai_evidence_review.md` | AI | 科学解释与 claim support 表；audit digest 输入。 |
| `decision.yaml` | `arx_decide.py` | 研究决策、audit digest 和输入 digests；文件 digest 锚定在 state。 |
| `next_goal.md` | AI | 继续型 decision 的下一轮目标说明。 |
| `archive_manifest.yaml` | archive 逻辑 | readiness、snapshot digests、audit digest、outcome 和恢复原因。 |

## Owner 和 hooks

Owner 是 Codex 会话协调机制，不是操作系统权限边界。

- `arx_loop.py start --session-id` 可以原子认领空 owner；Stop hook 仅在诊断探测时可能认领。
- 非 owner 的 Stop 直接放行。
- pause、abort 和预算熔断会释放 owner。
- 直接在 hooks 之外运行脚本时，脚本无法知道调用者的 Codex session。真正的最终门禁来自 phase、digest、attempt id、文件锁和 readiness。

Hooks 默认关闭。`arx_init.py --enable-hooks` 只打开当前状态的开关；之后可用 `arx_loop.py hooks --on|--off` 切换（不加开关则打印当前值）。Codex 侧仍要 trust `hooks/hooks.json`。修改 hooks 后需重启 Codex，并重新 trust 变化后的条目。

Hook 从 cwd 向上查找 `.research/current`。若先遇到独立项目边界（`.git`、`package.json`、`pyproject.toml`、`Cargo.toml`、`go.mod`，或显式 `.arx-boundary`）且该层没有 campaign，则停止上溯，不继承祖先目录的 hooks。研究包内的子目录（无独立项目边界）仍可命中本包 `.research`。

Hook 配置使用插件约定路径 `hooks/hooks.json`。当前本地 plugin validator 不接受 manifest 的显式 `hooks` 字段，因此 `.codex-plugin/plugin.json` 不重复声明该路径。

`${PLUGIN_ROOT}` 指向插件安装副本。Hooks 由 `node` 启动（Unix/Windows 命令分别为 `node "${PLUGIN_ROOT}/..."` 与 `node "%PLUGIN_ROOT%\\..."`）。生命周期仍经 `arx_bridge.py` 调用；可用 `ARX_PYTHON` 指定 Python 解释器。不要把 hook 路径写成相对项目 cwd。

## 研究 MCP

插件通过 `.codex-plugin/plugin.json` 的 `mcpServers` 指向根目录 `.mcp.json`。当前声明：

```json
{
  "mcpServers": {
    "arxiv": {
      "command": "uvx",
      "args": ["arxiv-mcp-server"],
      "startup_timeout_sec": 20
    },
    "semantic-scholar": {
      "command": "uvx",
      "args": ["s2-mcp-server"],
      "startup_timeout_sec": 20
    }
  }
}
```

前置依赖是 `uv`。`SEMANTIC_SCHOLAR_API_KEY` 可选，用于提高 API 速率额度。MCP 被禁用或启动失败时，Literature 阶段可以用 Web 搜索论文摘要、arXiv 页面和 GitHub 实现，但仍要把链接写进 `literature_review.md`。
