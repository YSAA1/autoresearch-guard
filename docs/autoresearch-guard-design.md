# AutoResearch Guard 的设计

## 目的

研究没有通用的固定流程。查论文、调试代码、做产品比较和整理现场记录，所需的步骤都不同。插件不试图把这些工作塞进同一个状态机。

它只处理两个容易出问题的地方：研究是否还能恢复，以及 `verified` 这个词是否有明确含义。

## 分工

Skill 和模型负责研究本身：选择方法、找资料、判断证据、解释失败、决定继续还是停下。

`arx` 负责少量可确定的事情：保存 session、冻结验证契约、追加结果、检测契约漂移、自动归档。它不评判领域结论，也不检查证据内容是不是真的。

插件级 MCP 是信息来源，不是流程依赖。当前配置包含 arXiv 和 Semantic Scholar；不可用时可以换来源。

## 状态

每个项目只有一个 `.research/current/`。其中的 `session.json` 只有 `active`、`paused`、`finished` 三种状态。正常 finish 后 current 会移动到 archive，因此用户通常只会看到前两种。

验证文件单独按版本保存。直接改动锁定内容会让摘要不匹配，CLI 会拒绝新的结果和 `verified` 收口。想修订检查清单时要建新版本，避免把旧证据说成支持新结论。

## 收口规则

研究可以随时以 `unverified`、`inconclusive`、`stopped` 或 `blocked` 结束，只要写清 summary。

`verified` 是唯一的严格结局：当前契约所有检查的最新结果都必须是 `pass`，每条 pass 都要有 evidence。这样既不干扰探索，又能让强结论留下可以复查的边界。

## 可靠性边界

所有写入持有根目录锁，并使用同目录临时文件、fsync 和原子替换。归档移动失败时，finish 会恢复移动前的 session，之后可以重试。

旧版 `state.yaml` 不做语义迁移。用户可以用 `start --archive-legacy` 原样归档它，再开始一项新研究。

SessionStart Hook 只读取状态并提醒运行 `arx status --json`。它不写状态，不拦截工具，也不触发自动续跑。
