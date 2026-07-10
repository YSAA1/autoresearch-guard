from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "autoresearch-guard" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from arx_core import research_root_for, status_report  # noqa: E402


def _event_cwd() -> Path:
    try:
        raw = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
        payload: Any = json.loads(raw) if raw else {}
    except (OSError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict) and payload.get("cwd"):
        return Path(str(payload["cwd"])).expanduser().resolve()
    return Path.cwd().resolve()


def main() -> int:
    root = research_root_for(_event_cwd())
    if not root.is_dir():
        return 0
    try:
        report, _status_code = status_report(root)
        if report["state"] == "idle":
            return 0
        session = report["session"] or {}
        goal = session.get("goal") or "未命名研究"
        message = (
            f"AutoResearch Guard：发现 {report['state']} 研究（目标：{goal}）。"
            "在修改研究状态前，请运行 arx status --json。"
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": message,
                    }
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        # SessionStart 只提供可选上下文。任何读取问题都不得影响宿主会话。
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
