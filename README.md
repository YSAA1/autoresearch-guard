# AutoResearch Guard

AutoResearch Guard 是一个 Codex 插件，帮你把研究过程收得干净一点。

研究怎么推进，不由插件规定。你可以查资料、跑代码、读仓库、写报告，或者先停下来想清楚。只有当你要把结论标为 `verified` 时，插件才要求一份冻结的检查清单，以及每项检查的通过证据。

插件级 MCP 已配置 arXiv 和 Semantic Scholar。它们只是可选的信息来源，不能用时照样可以研究。

## 使用方式

文档里的 `arx` 指这个脚本：

```bash
python <skill-root>/scripts/arx.py
```

在要研究的项目根目录运行。它会把最小状态放在 `.research/`。
如果从子目录运行，`arx` 会复用最近祖先目录已有的 `.research/`；找不到时才在当前目录创建新的状态。

```bash
# 先看有没有未结束的研究
arx status --json

# 开始一项新研究
arx start --goal "比较两种缓存失效策略"

# 自由完成调研、实验、代码修改或笔记整理

# 如果需要严谨地声明结论，先锁定一份检查清单
arx verify lock --file verification.json
arx verify record --check sources --verdict pass \
  --evidence notes/sources.md --reason "关键说法已逐项核对"

# 不需要验证也可以诚实结束
arx finish --outcome unverified --summary "完成了探索性比较，尚未做完整验证。"
```

`finish` 会自动把当前研究移到 `.research/archive/`，因此不需要单独的 archive 命令。

## 验证契约

模型或研究者在 lock 前自行设计检查。CLI 只接受下面这个 JSON 形状：

```json
{
  "claim": "缓存策略 A 更适合当前服务",
  "checks": [
    {
      "id": "load-test",
      "criterion": "目标负载下 p95 延迟不回退",
      "method": "运行基准测试并比较报告",
      "evidence_required": "基准报告路径或链接"
    }
  ]
}
```

检查 ID 必须唯一，所有字段都要有内容。契约锁定后不能被直接修改；想改变它时使用 `arx verify lock --file NEW.json --revise`。新版本不会继承旧版本的结果。

每个 `pass` 都至少要有一条 `--evidence`，每个结果都要说明 `--reason`。同一条结果重复提交是 no-op；有不同内容的新结果会保留历史，最新结果决定该检查当前是否通过。

只有当前契约的所有检查最新结果都是 `pass`，下面这条命令才会成功：

```bash
arx finish --outcome verified --summary "所有约定检查均已通过。"
```

其他结局不要求验证契约，但都必须写 summary：`unverified`、`inconclusive`、`stopped`、`blocked`。

## 状态与恢复

```text
.research/
├── .arx.lock
├── current/
│   ├── session.json
│   └── verifications/v001.json
└── archive/<timestamp>-<session-id>/
```

`pause --reason` 和 `resume` 只改变研究是否可继续记录验证结果。`status --json` 固定输出 `state`、`session`、`verification`、`can_finish_verified`、`reasons` 和 `next_actions`。

如果目录里仍是旧版的 `state.yaml`，CLI 会报告 `legacy`，不会猜测如何迁移。确认后运行：

```bash
arx start --goal "新的研究目标" --archive-legacy
```

旧 `current` 会原样归档，并附一份简短 manifest。

## Hook

插件只注册一个只读的 `SessionStart` Hook。它发现 `.research` 后提示运行 `arx status --json`，不会拦截工具、自动续跑、写状态，或阻止会话结束。

设计说明见 [docs/autoresearch-guard-design.md](docs/autoresearch-guard-design.md)。
