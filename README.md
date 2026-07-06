# AutoResearch Guard

AutoResearch Guard is a Codex plugin project for guarded research loops. It keeps AI research judgement in the main agent while scripts and hooks do deterministic work: create state files, compile constrained `/goal` text, record evidence, audit protocol violations, check decisions, show status, and archive completed iterations.

## Project Layout

```text
autoresearch-guard/
  .codex-plugin/plugin.json
  .mcp.json
  skills/autoresearch-guard/
    SKILL.md
    scripts/
    templates/
    references/
  hooks/
```

The plugin intentionally does not add a standalone CLI platform. Each script can be run directly with Python and is scoped to `.research/`.

Hooks 默认不启用。安装插件后，Codex 可能仍会加载插件级 hook 配置，但 hook 脚本会先检查 `.research/current/state.yaml` 的 `hooks_enabled`；只有值为 `true` 时才会拦截命令、提醒记录 evidence 或阻止结束。初始化时加 `--enable-hooks` 才会打开这组门禁。

## Local Smoke Flow

```powershell
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_init.py --research-root .research --iteration-id demo --title "Demo" --hypothesis "Demo hypothesis"
# 如果要启用插件 hooks，初始化时加 --enable-hooks。
# Edit .research\current\protocol.lock.yaml and set locked: true.
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_compile_goal.py --research-root .research
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_record.py --research-root .research --iteration-id demo --command "python eval.py --baseline --split validation --seed 0" --data-split validation --seed 0 --role baseline --metric oracle_top1_gain=0.00
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_record.py --research-root .research --iteration-id demo --command "python eval.py --split validation --seed 0" --data-split validation --seed 0 --metric oracle_top1_gain=0.02
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_audit.py --research-root .research
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_status.py --research-root .research
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_status.py --research-root .research --review
```

## Validation

```powershell
python C:\Users\shash\.codex\skills\.system\skill-creator\scripts\quick_validate.py autoresearch-guard\skills\autoresearch-guard
python C:\Users\shash\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py autoresearch-guard
python -m unittest discover -s autoresearch-guard\tests
```
