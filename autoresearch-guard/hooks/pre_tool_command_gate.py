from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
COMMON = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
sys.path.insert(0, str(COMMON))

from arx_common import command_mentions_split, contains_pattern, current_dir, listify, load_current_yaml  # noqa: E402


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


def blocked_patterns(blocked: dict) -> list[tuple[str, str, str]]:
    rows = []
    for item in listify(blocked.get("blocked_actions")):
        if isinstance(item, dict):
            action = str(item.get("action_id") or item.get("name") or "blocked_action")
            reason = str(item.get("reason") or "blocked by protocol")
            for pattern in listify(item.get("patterns")):
                rows.append((action, reason, str(pattern)))
        else:
            rows.append((str(item), "blocked by protocol", str(item)))
    return rows


def blocks_protocol_write(command: str) -> bool:
    lower = command.lower()
    if "protocol.lock.yaml" not in lower:
        return False
    write_markers = ["set-content", "out-file", "add-content", "writealltext", "python", "node", "vim", "notepad", "code", ">"]
    return any(marker in lower for marker in write_markers)


def main() -> int:
    parser = argparse.ArgumentParser(description="拦截 AutoResearch Guard 的确定性命令违规。")
    parser.add_argument("--command", default="")
    parser.add_argument("--cwd", default="")
    args = parser.parse_args()
    payload = payload_from_stdin()
    command = args.command or command_from_payload(payload)
    cwd = Path(args.cwd or payload.get("cwd") or Path.cwd()).resolve()

    if not command:
        print(json.dumps({"allow": True, "reason": "no command found"}))
        return 0

    research_root = find_research_root(cwd)
    if research_root is None:
        print(json.dumps({"allow": True, "reason": "no .research/current found"}))
        return 0

    protocol = load_current_yaml(research_root, "protocol.lock.yaml")
    blocked = load_current_yaml(research_root, "blocked_actions.yaml")
    reasons = []

    for split in listify(protocol.get("forbidden_splits")):
        if command_mentions_split(command, str(split)):
            reasons.append(f"command touches forbidden split: {split}")

    for action, reason, pattern in blocked_patterns(blocked):
        if pattern and contains_pattern(command, pattern):
            reasons.append(f"command matches blocked action {action}: {reason}")

    if protocol.get("locked") is True and blocks_protocol_write(command):
        reasons.append("command appears to edit locked protocol.lock.yaml")

    if reasons:
        reason = "; ".join(reasons)
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                },
                ensure_ascii=True,
            )
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
