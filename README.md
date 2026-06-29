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

## Local Smoke Flow

```powershell
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_init.py --research-root .research --iteration-id demo --title "Demo" --hypothesis "Demo hypothesis"
# Edit .research\current\protocol.lock.yaml and set locked: true.
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_compile_goal.py --research-root .research
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_record.py --research-root .research --iteration-id demo --command "python eval.py --split validation --seed 0" --data-split validation --seed 0 --metric oracle_top1_gain=0.02
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_audit.py --research-root .research
python autoresearch-guard\skills\autoresearch-guard\scripts\arx_status.py --research-root .research
```

## Validation

```powershell
python C:\Users\shash\.codex\skills\.system\skill-creator\scripts\quick_validate.py autoresearch-guard\skills\autoresearch-guard
python C:\Users\shash\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py autoresearch-guard
python -m unittest discover -s autoresearch-guard\tests
```
