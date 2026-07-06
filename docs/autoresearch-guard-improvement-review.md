# AutoResearch Guard 改进方案 review

日期：2026-06-30

## 先纠偏

你刚才指出的问题是准确的：上一版把“降低心智负担”写成了主目标，这会跑偏。

这次改回正确关系：

```text
主目标：让自动研究更可靠，避免自嗨式研究。
约束条件：实现这个目标时，不能把人工 review 变成看一堆 YAML 和状态文件。
```

所以，“少文件、低负担”不是目的。真正目的还是 AutoResearch Guard 最开始要解决的那些问题：

- 没查 prior art 就开始写实验。
- 没查现有实现，重复造轮子。
- baseline 没复现，就声称有改进。
- 实验协议中途漂移，指标和数据划分被悄悄改掉。
- validation 证据不够，却写出 test/generalization 级别的结论。
- 连续失败还继续局部调参，进入死胡同循环。
- 最后人看到一堆 agent 输出，却不知道该不该继续、refine、pivot、promote 或 stop。

低心智负担只解决最后的“人怎么看”问题，不能替代前面的研究质量门禁。

## 最初目标应该这样表述

AutoResearch Guard 要做的不是“帮 agent 多写几个记录文件”，而是给自动研究加一套可审计的研究门禁。

每一轮研究结束时，它应该能回答 6 个问题：

1. 这个想法来自哪里？是否绑定到论文、项目或已有失败经验？
2. 现有实现查过了吗？为什么复用、改造，或者必须重写？
3. baseline 跑了吗？当前结果是不是确实超过 baseline？
4. 实验是不是按锁定协议产生的？有没有改指标、污染 test、选择性记录结果？
5. 结论有没有越界？证据只能支撑 validation，就不能写成泛化成功。
6. 连续失败时有没有触发死胡同判断？是否该 refine、pivot、abandon，而不是继续乱试？

这 6 个问题是主线。

## 调研结论怎么支持这个主线

上一轮全网调研和补充调研可以合并成一句话：

```text
AutoResearch 的趋势是让 agent 跑完整研究循环，但最大风险不是“自动化不够”，而是“自动化之后更难判断它有没有跑偏”。
```

几个信号很明确：

- [AutoR](https://github.com/AutoX-AI-Labs/AutoR)、[Daybreak AutoResearch](https://github.com/1dZb1/Daybreak-AutoResearch)、[AutoResearch-AI](https://github.com/vukrosic/autoresearch-ai) 都在把研究流程自动化，说明这个方向成立。
- [The AI Scientist](https://arxiv.org/abs/2408.06292)、[AI Scientist v2](https://arxiv.org/abs/2504.08066)、[Agent Laboratory](https://agentlaboratory.github.io/)、[Kosmos](https://arxiv.org/abs/2511.02824)、[ScientistOne](https://scientist-one.github.io/) 这类系统都把 idea、literature、experiment、paper 写作串起来，但也暴露出评估、复现、结论边界和人工监督问题。
- [AgentClick](https://arxiv.org/html/2604.16520)、[Overseeing Agents Without Constant Oversight](https://arxiv.org/pdf/2602.16844)、[Human-in-the-Loop pattern](https://www.agentpatternscatalog.org/patterns/human-in-the-loop/)、[Artifact Pyramid](https://www.groktop.us/artifact-pyramid-progressive-disclosure/) 说明另一个问题：如果把所有 trace、YAML、日志都丢给人，监督会失效。

所以方案必须同时满足两件事：

```text
研究门禁要更硬。
人工入口要更轻。
```

缺前者，自动研究会自嗨。缺后者，人会被 review 负担拖垮。

## 新方案的核心结构

把系统分成两层：

```text
第一层：研究质量门禁，给机器读，必须严格。
第二层：人工决策入口，给人读，必须压缩。
```

第一层负责保证研究没跑偏。第二层只负责让人快速知道“能不能继续”。

这不是弱化护栏，而是把护栏放回机器该做的位置。

## 第一层：研究质量门禁

### 门禁 1：prior art 和已有实现绑定

要解决的问题：

自动研究最容易从一个看似新颖的想法开始，但其实可能已有论文做过，或者 GitHub 上已有实现。

要做的改进：

- `literature_review.md` 必须包含候选想法、相关论文、已有实现。
- `hypothesis.yaml.evidence_basis` 必须能回指到 `literature_review.md` 中的证据。
- `hypothesis.yaml.reuse_plan.base` 必须说明复用哪个实现；如果选择 `build_new`，必须写清楚为什么不能复用。
- `arx_compile_goal.py` 负责确定性检查，缺证据就不生成 active goal。

这里的重点不是“少一个 `prior_art.yaml`”，而是：

```text
任何研究假设都必须带来源。
任何新实现都必须解释为什么不是重复造轮子。
```

文件形式可以先用结构化 Markdown 表格，因为它对人可读；如果实现证明 Markdown 解析太脆，可以生成机器私有索引，但不能把人工 review 变成看索引文件。

### 门禁 2：baseline-first

要解决的问题：

没有 baseline，agent 很容易把随机波动、数据清洗副作用、或者弱对照当成研究进展。

要做的改进：

- `protocol.lock.yaml` 明确 baseline 命令、指标和通过条件。
- `evidence_ledger.jsonl` 必须有 `role=baseline` 的记录。
- `arx_audit.py` 检查当前最佳结果是否真的超过 baseline。
- baseline 缺失时，禁止 `promote`。

人最终看到的可以只是一行：

```text
baseline：红灯，原因是协议要求 baseline，但 ledger 没有 baseline 记录。
```

但机器底层检查必须存在。

### 门禁 3：协议锁定和证据完整性

要解决的问题：

自动研究跑久了以后，最危险的是目标漂移：改 metric、换 split、补跑挑结果、把 validation 说成 test。

现有 Guard 已经有这些基础：

- `protocol.lock.yaml`
- `blocked_actions.yaml`
- `evidence_ledger.jsonl`
- `audit_report.yaml`
- `pre_tool_command_gate`
- `arx_audit.py`

要加强的点：

- 锁定协议后，实验记录必须晚于 `compiled_at`。
- ledger 每条证据必须能对上协议 digest。
- forbidden split、blocked action、validation gate 失败都要进入 audit。
- 这些违规必须影响后续 decision gate，而不是只写在报告里。

### 门禁 4：claim boundary

要解决的问题：

agent 很容易用弱证据写强结论。比如只在 validation 上变好，却写“泛化能力提升”；只跑了一个 seed，却写“稳定提升”。

要做的改进：

- 继续保留 `claim_boundary.yaml` 的边界作用。
- `ai_evidence_review.md` 增加结构化 claim 表。
- 每个 claim 标清楚证据来源和可支持等级。
- unsupported claim、prohibited claim、越界 claim 不能进入 `promote`。

示例：

```md
| claim_id | 结论 | 证据等级 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| c1 | validation 上优于 baseline | validation | ledger:run-3 | supported |
| c2 | 方法能泛化到 test | test | none | unsupported |
```

这里的目标不是新增 `claims.yaml`，而是防止结论越界。

### 门禁 5：死胡同和螺旋检测

要解决的问题：

自动研究失败时，agent 往往会继续微调局部参数，形成“跑更多实验但信息量越来越低”的循环。

现有 Guard 已经有 `spiral_risk`，要继续强化：

- 连续失败、低信息增益、重复 blocked pattern 时，`arx_audit.py` 给出 `spiral_risk`。
- `spiral_risk=critical` 时，`decision.proposed.yaml` 必须有 `spiral_response`。
- critical 时默认禁止 `proceed`，除非明确人工确认并解释为什么不是死胡同。

这部分是最初目标的重要组成，不应该被“降低心智负担”盖住。

## 第二层：人工决策入口

有了上面的门禁之后，才谈低心智负担。

人不应该逐个打开这些文件：

- `hypothesis.yaml`
- `protocol.lock.yaml`
- `evidence_ledger.jsonl`
- `audit_report.yaml`
- `ai_evidence_review.md`
- `decision.proposed.yaml`
- `decision.yaml`

更不应该再额外手动审：

- `prior_art.yaml`
- `claims.yaml`
- `recovery.yaml`
- `heartbeat.yaml`

所以需要一个压缩入口：

```text
.research/current/review_packet.md
```

或者：

```bash
python autoresearch-guard/skills/autoresearch-guard/scripts/arx_status.py --research-root .research --review
```

它只回答：

```text
本轮是否可以继续？
应该 proceed、refine、pivot、promote，还是 stop？
哪些门禁红灯？
哪些风险只是黄灯？
如果要下钻，证据在哪个文件哪一段？
```

示例：

```text
结论：黄灯，建议 refine

红灯：
- 无

黄灯：
- spiral risk = caution，连续 2 次 validation 无提升
- 预算还剩 1 次实验

绿灯：
- prior art 已绑定
- 已有实现复用理由完整
- baseline 已复现
- protocol digest 匹配
- claim 没有越界

建议下一步：
- 继续 refine
- 下一轮只改数据清洗，不改模型结构

下钻：
- prior art：literature_review.md
- baseline 证据：evidence_ledger.jsonl
- 完整审计：audit_report.yaml
```

这部分的作用是降低审查成本，但它服务于研究门禁，不替代研究门禁。

## 和上一版的关键差别

上一版的问题：

```text
叙事重心 = 少文件、低心智负担
```

这会让人误以为我们是在做一个“更清爽的状态面板”。

现在修正为：

```text
叙事重心 = 更强的研究质量门禁
交互约束 = 人只看一个压缩后的决策入口
```

也就是说：

- 不因为低负担而删掉 prior art gate。
- 不因为低负担而降低 baseline 要求。
- 不因为低负担而放过 claim 越界。
- 不因为低负担而弱化 spiral detection。
- 只是避免把这些门禁的内部账本全部推给人看。

## 文件策略

文件策略应该服从研究质量，而不是反过来。

我建议的规则：

1. 人写或读的文件，尽量少，且必须有清晰语义。
2. 机器需要的结构化数据，可以来自现有文件，也可以由脚本生成。
3. 生成的机器索引不要变成人工 review 入口。
4. 如果 Markdown 表格解析太脆，就允许生成 `.derived` 或 audit 内部结构，但人默认仍只看 `review_packet.md`。
5. 是否新增文件，要看它能不能加强门禁，而不是看“少文件”这个表面指标。

所以暂缓新增这些人工可见文件：

- `prior_art.yaml`
- `claims.yaml`
- `recovery.yaml`
- `heartbeat.yaml`

但这不等于永远不能有机器生成文件。如果为了稳定校验必须有，可以生成，只是不把它们设计成人要逐项审核的材料。

## 推荐实施顺序

第一批不要只做 review packet。第一批应该交付“门禁加强 + 压缩展示”。

### P0：先补研究质量硬门禁

1. 强化 `literature_review.md` 模板：必须有 candidate idea、paper evidence、existing implementation、reuse decision。
2. 强化 `arx_compile_goal.py`：检查 `evidence_basis` 和 `reuse_plan` 能回指到文献/实现证据。
3. 增加 baseline-first audit：baseline 缺失或未超过 baseline 时禁止 `promote`。
4. 增加 claim support 检查：unsupported/prohibited claim 阻断 `promote`。
5. 增加协议时间检查：实验记录不能早于 compiled protocol。

验收标准：

- 没有 prior art，不能进入 active goal。
- 没有 reuse/build_new 理由，不能进入 active goal。
- 没有 baseline，不能 promote。
- 证据越界，不能 promote。
- 协议漂移，不能 promote。

### P0 同批：增加 review packet

同一批里加 `review_packet.md` 或 `arx_status.py --review`。

它不是主功能，而是把上面的门禁结果翻译成人能快速判断的格式。

验收标准：

- 人打开一个入口就能看到红黄绿灯。
- 每个红灯都能下钻到原始证据。
- review packet 不改变研究状态，只做汇总。

### P1：强化死胡同决策

1. 保留并加强 `spiral_risk`。
2. critical 时必须有 `spiral_response`。
3. 连续低信息实验时，review packet 明确建议 refine、pivot 或 abandon。
4. critical 且仍要 proceed 时，必须显式人工确认。

验收标准：

- agent 不能在 critical spiral 下无解释继续跑。
- 死胡同信号进入 decision gate，而不是只出现在报告里。

### P2：再考虑 recovery 和更细预算

`recovery.yaml`、`heartbeat.yaml` 先不做，不是因为它们没价值，而是因为它们不是第一批最关键门禁。

等 P0/P1 跑通后，再看是否需要：

- 自动回滚建议。
- 更细的预算和心跳。
- 失败后的 recovery plan。

## 需要你 review 的问题

这次应该让你 review 的不是“要不要低心智负担”，而是这些研究门禁是否符合最初目标：

1. 没有 prior art / existing implementation 证据时，是否直接阻断 active goal？
2. `build_new` 是否必须写明为什么不能复用现有实现？
3. baseline 缺失时，是否必须禁止 `promote`？
4. validation 没过但有探索价值时，是否允许 `refine`，但禁止 `promote`？
5. unsupported 或 prohibited claim 是否必须红灯？
6. `spiral_risk=critical` 时，是否默认禁止 `proceed`？
7. 人工入口是否统一成 `review_packet.md`，其余细节只作为下钻证据？

## 我现在推荐的决定

我建议把计划命名为：

```text
AutoResearch Guard 研究质量门禁增强
```

而不是：

```text
少文件版 AutoResearch Guard
```

第一批真正要做的是：

- prior art / existing implementation gate
- reuse / build_new gate
- baseline-first gate
- protocol/evidence integrity gate
- claim boundary gate
- review packet

其中前五个是目标，最后一个是降低人工负担的入口。

这样才不会丢掉最初目标：让自动研究能跑，但不能乱跑；能探索，但不能自证；能总结，但不能把弱证据写成强结论。
