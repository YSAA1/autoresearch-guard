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

from arx_common import append_jsonl, current_dir, utc_now  # noqa: E402


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
    parser = argparse.ArgumentParser(description="Capture command metadata and remind evidence recording.")
    parser.add_argument("--command", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--exit-code", type=int, default=None)
    parser.add_argument("--log-path", default="")
    args = parser.parse_args()
    payload = payload_from_stdin()
    command = args.command or str(payload.get("command") or payload.get("cmd") or "")
    cwd = Path(args.cwd or payload.get("cwd") or Path.cwd()).resolve()
    exit_code = args.exit_code if args.exit_code is not None else payload.get("exit_code")

    research_root = find_research_root(cwd)
    if research_root is None or not command:
        return 0

    record = {
        "timestamp": utc_now(),
        "command": command,
        "cwd": str(cwd),
        "exit_code": exit_code,
        "log_path": args.log_path or payload.get("log_path") or "",
        "result_hints": result_hints(command),
    }
    append_jsonl(current_dir(research_root) / "tool_capture.jsonl", record)
    if likely_experiment(command):
        print("AutoResearch Guard: experiment-like command detected. Record deterministic evidence with arx_record.py before ending the goal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())