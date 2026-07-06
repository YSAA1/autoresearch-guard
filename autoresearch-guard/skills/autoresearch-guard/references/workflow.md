# AutoResearch Guard 工作流

单一活跃迭代状态在 `.research/current/`。跨迭代记忆在 `.research/lessons/`。已完成迭代在 `.research/archive/`。

## 目录

```text
.research/
├── current/                  # 当前迭代（单一活跃源）
│   ├── literature_review.md  # 文献 + 现有实现搜索（不重复造轮子）
│   ├── hypothesis.yaml       # 含 evidence_basis + reuse_plan
│   ├── protocol.lock.yaml    # 含 spiral_budget
│   ├── active_goal.md
│   ├── evidence_ledger.jsonl
│   ├── audit_report.yaml     # 含 spiral_risk
│   ├── ai_evidence_review.md
│   ├── decision.proposed.yaml
│   ├── decision.yaml
│   ├── next_goal.md
│   ├── state.yaml
│   ├── blocked_actions.yaml
│   └── claim_boundary.yaml
├── lessons/                  # 跨迭代经验（长期保留）
│   ├── retained_lessons.md
│   └── anti_patterns.yaml
└── archive/                  # 已归档迭代
```

## 循环

与 `SKILL.md` 步骤一一对应。

| 步 | 动作 | 完成条件 |
|----|------|----------|
| 1 | 阅读 `lessons/`（若存在） | 已吸收 retained lessons 与 anti-patterns |
| 2 | S2 MCP / arXiv MCP 搜论文 + WebSearch 搜现有实现，编写 `literature_review.md` | ≥1 candidate_idea + ≥1 existing_implementation，每个有证据链接 |
| 3 | AI 编写 `hypothesis.yaml`，含 `evidence_basis` 与 `reuse_plan` | 必填字段已填 |
| 4 | AI 编写 `protocol.lock.yaml`（含 `spiral_budget`）；人工设 `locked: true` | 协议已锁定 |
| 5 | `arx_compile_goal.py` 校验 prior art / reuse 绑定并渲染 `active_goal.md` | goal 已生成；`state.yaml` 含 `protocol_digest` 与 `compiled_at` |
| 6 | 将 `active_goal.md` 用作 `/goal` 正文 | — |
| 7 | 在 `/goal` 内做研究，优先复用 `reuse_plan.base` 指定实现 | — |
| 8 | 每次有意义实验后 `arx_record.py`；baseline 证据用 `--role baseline` | `evidence_ledger.jsonl` 有记录 |
| 9 | `arx_audit.py`（含 baseline、claim support、`spiral_risk`） | `audit_report.yaml` 已写出（有违规时 exit 1，报告仍生成） |
| 10 | AI 编写 `ai_evidence_review.md` 的「结论与证据」claim 表；`spiral_risk` 非 none 时含「死胡同评估」节 | 无 `TBD by AI` |
| 11 | 重新运行 `arx_audit.py`，然后 AI 编写 `decision.proposed.yaml`；critical 时含 `spiral_response` | audit 已包含 claim support；proposal 含 `decision` 与 `reason` |
| 12 | `arx_decide.py`（escape gate） | `decision.yaml` 已提交 |
| 13 | **closure**：更新 `lessons/`（有失败时强制）；编写 `next_goal.md`；或 `arx_archive.py` | 见「Closure 与迭代衔接」 |

## Closure 与迭代衔接

`stop_goal_guard` 只在 `.research/current/state.yaml` 的 `hooks_enabled: true` 时生效。启用后，它与 `arx_archive` 共用核心 closure 清单：

- `evidence_ledger.jsonl`（至少一条记录）
- `audit_report.yaml`
- `ai_evidence_review.md`（有意义内容，不含 `TBD by AI`）
- `decision.yaml`

**失败时额外必填**：`anti_patterns.yaml` 含本轮 `iteration_id` 字符串的新条目（确定性检查，强制反哺防再犯）。

`next_goal.md` 不在硬性 closure 清单内，但步骤 13 要求处理。

### 步骤 13 分支

**继续下一轮（refine / pivot / proceed）**

1. AI 将本轮要点写入 `next_goal.md`（替换 init 占位）。
2. AI 更新 `lessons/retained_lessons.md` 与 `lessons/anti_patterns.yaml`（追加，不覆盖；失败时强制）。
3. 运行 `arx_archive.py` 归档当前 `current/`。
4. 运行 `arx_init.py --archive-existing --iteration-id <新 id>`，用 `next_goal.md` 作为新 `hypothesis.yaml` 输入依据。

**结束研究（stop）**

1. 更新 `lessons/`（同上）。
2. 运行 `arx_archive.py`；无需 `next_goal.md` 或新一轮 init。

## 文件职责

| 文件 | 创建者 | 读者 | 写入者 | 脚本强制 |
|------|--------|------|--------|----------|
| `literature_review.md` | `arx_init` 占位 | compile、AI | 步骤 2 AI | compile 校验被引用 |
| `lessons/retained_lessons.md` | `arx_init` 空壳 | 步骤 1 | 步骤 13 AI | 否 |
| `lessons/anti_patterns.yaml` | `arx_init` 空壳 | 步骤 1 | 步骤 13 AI | 失败时 closure 强制含本轮 id |
| `state.yaml` | `arx_init` | 审计、status、hook | `arx_compile_goal` 更新 digest 与 compiled_at；初始化时写入 `hooks_enabled` | digest + 时间线 + hook 开关 |
| `hypothesis.yaml` | `arx_init` 模板 | 全流程 | 步骤 3 AI | compile 校验必填 + reuse 字段 |
| `protocol.lock.yaml` | `arx_init` 模板 | 全流程 | 步骤 4 AI；锁定后 hook 拦截写入 | 锁定后 hook + 审计 digest |
| `blocked_actions.yaml` | `arx_init` | goal、审计、hook | AI（锁定前） | hook + 审计 |
| `claim_boundary.yaml` | `arx_init` | goal、status | AI | 否（仅编入 goal） |
| `active_goal.md` | `arx_compile_goal` | Codex `/goal` | 脚本 | 否 |
| `evidence_ledger.jsonl` | `arx_init` 空文件 | 审计、closure | `arx_record` | closure 要求非空；baseline role 可审计 |
| `audit_report.yaml` | `arx_audit` | decide、status | `arx_audit` | closure 要求存在；禁非法 promote |
| `ai_evidence_review.md` | `arx_init` 占位 | closure、audit 扫 claim 表 | 步骤 10 AI | closure 要求有意义；claim 表影响 promote |
| `decision.proposed.yaml` | AI 手写 | `arx_decide` | 步骤 11 AI | — |
| `decision.yaml` | `arx_decide` | archive、status | `arx_decide` | closure 要求存在 |
| `next_goal.md` | `arx_init` 占位 | 下一轮 init | 步骤 13 AI | 否 |

## 执行 vs 建议

| 机制 | 强制内容 | 不强制 |
|------|----------|--------|
| `arx_compile_goal` | hypothesis 必填字段 + `evidence_basis` 必须匹配 `idea_id` + `reuse_plan.base` 必须匹配实现表（`build_new` 需 reason） | 新颖性、reuse 合理性 |
| `arx_audit` | 证据完整性、协议 digest、协议时间线、baseline、划分污染、blocked actions、validation gates、claim support 表；`spiral_risk` 信号；违规禁 `promote` | 论断措辞的科学真实性、是否真死胡同 |
| `arx_decide` | `decision` 合法性、`forbidden_decisions`；critical 时要求 `spiral_response` 且禁 proceed（除非反驳 + `requires_human`） | `requires_human` 的实际人工确认 |
| `pre_tool_command_gate` | `hooks_enabled: true` 时检查 forbidden splits、blocked patterns、锁定后 protocol 写入 | 锁定后修改 hypothesis / claim_boundary |
| `stop_goal_guard` | `hooks_enabled: true` 时检查 closure 四件套 + 非空 ledger；失败时 lessons 含本轮 id | `next_goal.md`、成功时 lessons |
| AI + 人工 | 科学判断、失败归因、死胡同判定、论断措辞、lessons 内容、reuse 决策 | — |

`arx_record` 的 `--iteration-id` 应与 `hypothesis.yaml` 一致；脚本不交叉校验，由 AI 保证。baseline 记录必须显式使用 `--role baseline`，否则会被当作普通实验记录。

## 不变量

脚本可以拒绝非法状态。它们不得选择研究方向，不得判定是否真死胡同。

## 附录：研究 MCP

### 插件已捆绑声明

插件通过 `.codex-plugin/plugin.json` 的 `"mcpServers": "./.mcp.json"` 声明，`.mcp.json` 位于插件根：

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

安装插件后，Codex 自动发现并启动 `arxiv` 与 `semantic-scholar` MCP server。`semantic-scholar` 覆盖论文元数据、引用图、推荐；`arxiv` 用于需要 arXiv 原文或全文证据的场景。用户可在 `~/.codex/config.toml` 控制开关与工具策略：

```toml
[plugins."autoresearch-guard".mcp_servers.arxiv]
enabled = true
default_tools_approval_mode = "prompt"

[plugins."autoresearch-guard".mcp_servers.semantic-scholar]
enabled = true
default_tools_approval_mode = "prompt"
enabled_tools = ["semantic_scholar_search_papers", "semantic_scholar_get_paper", "semantic_scholar_references", "semantic_scholar_citations", "semantic_scholar_recommendations"]
```

### 前置依赖

- `uv`（Astral）：提供 `uvx`。安装见 https://docs.astral.sh/uv/ 或 `pip install uv`。
- 可选 `SEMANTIC_SCHOLAR_API_KEY`：设为环境变量以提升 API 速率限制。无 key 时 server 以限速模式运行。`uvx s2-mcp-server` 进程会继承宿主环境变量。
- `arxiv-mcp-server` 默认用本地存储缓存下载论文；插件只声明启动命令，不声明用户机器上的固定绝对路径。

### 核心工具

Semantic Scholar：`semantic_scholar_search_papers`、`semantic_scholar_get_paper`、`semantic_scholar_references`、`semantic_scholar_citations`、`semantic_scholar_recommendations`。

arXiv：搜索、下载、读取已下载论文等工具，具体名称以 `arxiv-mcp-server` 当前版本暴露的 MCP tools 为准。

### 降级

MCP server 启动失败或被禁用时，Literature 阶段降级为 WebSearch 搜论文摘要与 arXiv 页；`existing_implementations` 始终用 WebSearch 搜 GitHub。

## Hooks 附录

Hooks 是项目级 opt-in，不是安装即启用。`arx_init.py` 默认写入 `hooks_enabled: false`；只有运行 `arx_init.py --enable-hooks ...`，或人工把 `.research/current/state.yaml` 改为 `hooks_enabled: true` 后，下面这些 hook 才会执行门禁逻辑。未启用时它们必须 exit 0 且 stdout 为空。

`hooks/hooks.json` 中的 command 必须使用 Codex 内联变量 `${PLUGIN_ROOT}`，指向插件安装目录（cache 或 marketplace 副本）。不要用 `$PLUGIN_ROOT`（PowerShell 会当成空环境变量）、不要用 `./hooks/...`（会从项目 cwd 解析，找不到脚本）。

示例：

```json
"command": "python \"${PLUGIN_ROOT}/hooks/pre_tool_command_gate.py\""
```

Windows 上用 `python` 而非 `python3`。修改 `hooks.json` 后需重启 Codex，并在 `/hooks` 里重新 trust 该 hook 条目（hash 会变）。

PreToolUse 允许通过时：**exit 0 且 stdout 为空**（或只输出带 `hookSpecificOutput.additionalContext` 的合法 JSON）。不要输出 `{"allow": true}` 等自定义字段，Codex 会报 `invalid pre-tool-use JSON output`。拦截时用 `hookSpecificOutput.permissionDecision: "deny"` 或顶层 `decision: "block"`。
