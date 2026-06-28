# 不重复造轮子 — Prior Art 调查

AutoResearch 优先复用现有实现，不重造轮子。任何方法在写入实验代码前，必须先调查 prior art：现有论文与现有仓库代码。

## 调查路径

### 论文搜索 — Semantic Scholar MCP

假定 `semantic-scholar` MCP 已配置（配置见 `workflow.md` 附录）。核心工具：

| 工具 | 用途 |
|------|------|
| `semantic_scholar_search_papers` | 关键词搜论文，按年份/引用/领域过滤 |
| `semantic_scholar_get_paper` | 取单篇元数据（支持 arXiv/DOI/S2 ID） |
| `semantic_scholar_references` | 该论文引用了哪些（向后遍历） |
| `semantic_scholar_citations` | 哪些论文引用该篇（向前遍历） |
| `semantic_scholar_recommendations` | 基于 seed 论文做 ML 推荐，找相邻工作 |

MCP 不可用时降级为内置 WebSearch 搜论文摘要与 arXiv 页。

### 现有实现搜索 — WebSearch

GitHub / 其他仓库用内置 WebSearch：
- `<method> implementation github`
- `<method> baseline code`
- `<benchmark> leaderboard repo`

## 记录到 literature_review.md

- `candidate_ideas`：每个附 S2 paperId / arXiv ID
- `existing_implementations`：每个附 name / url / covered_capability
- `gap_analysis`：现有工作 + 现有代码未覆盖处

## hypothesis.yaml 决策

```yaml
evidence_basis: <literature_review 中的 idea_id>
reuse_plan:
  base: <repo url 或 "build_new">
  build_new_reason: <仅当 base=build_new 时必填>
```

`arx_compile_goal.py` 确定性校验：`evidence_basis` 与 `reuse_plan.base` 非空；`base=build_new` 时 `build_new_reason` 非空。脚本不评新颖性，只查字段。

## build_new 何时合法

- 现有实现协议/许可证不允许复用
- 现有实现与新协议不兼容且改造量 > 重写
- 研究目的就是比较新实现与现有实现（需明说）

不合法的 build_new：未调查就重写、现有实现可用但嫌麻烦。
