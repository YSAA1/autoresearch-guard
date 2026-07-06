from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
COMMON = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
sys.path.insert(0, str(COMMON))

from arx_common import research_hooks_enabled  # noqa: E402


def payload_from_stdin() -> dict:
    if sys.stdin.isatty():
        return {}
    text = sys.stdin.read().strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"command": text}


def command_from_payload(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        command = tool_input.get("command")
        if command:
            return str(command)
    return str(payload.get("command") or payload.get("cmd") or "")


def find_research_root(cwd: Path) -> Path | None:
    for path in [cwd, *cwd.parents]:
        if (path / ".research" / "current").exists():
            return path / ".research"
    return None


def likely_experiment(command: str) -> bool:
    lower = command.lower()
    return any(token in lower for token in ["eval", "train", "experiment", "validation", "--split", "metrics", "result"])


def result_hints(command: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_./\\-]+(?:metrics|result)[A-Za-z0-9_./\\-]*\.json", command)


def main() -> int:
    parser = argparse.ArgumentParser(description="捕获命令元数据并提醒记录证据。")
    parser.add_argument("--command", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--exit-code", type=int, default=None)
    parser.add_argument("--log-path", default="")
    args = parser.parse_args()
    payload = payload_from_stdin()
    command = args.command or command_from_payload(payload)
    cwd = Path(args.cwd or payload.get("cwd") or Path.cwd()).resolve()
    exit_code = args.exit_code if args.exit_code is not None else payload.get("exit_code")

    research_root = find_research_root(cwd)
    if research_root is None or not command:
        return 0
    if not research_hooks_enabled(research_root):
        return 0

    if likely_experiment(command):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": "AutoResearch Guard detected an experiment-like command. Before ending the goal, record deterministic evidence with arx_record.py.",
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
