#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
COMMON = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
sys.path.insert(0, str(COMMON))

from arx_harness import session_start_ritual_message
from arx_lifecycle import claim_session, evaluate_readiness, load_lifecycle_state, observe_stop


def _read_event() -> dict[str, Any]:
    text = sys.stdin.read().strip()
    if not text:
        return {}
    loaded = json.loads(text)
    if isinstance(loaded, dict):
        return loaded
    raise ValueError("hook bridge expects a JSON object on stdin")


def session_start(research_root: Path, event: dict[str, Any]) -> dict[str, Any]:
    state = load_lifecycle_state(research_root)
    if state.get("hooks_enabled") is not True:
        return {"skip": True}
    report = evaluate_readiness(research_root)
    owner = str((state.get("loop") or {}).get("owner_session_id") or "")
    session_id = str(event.get("session_id") or "")
    relation = "owner" if owner and owner == session_id else ("unbound" if not owner else "non-owner")
    message = session_start_ritual_message(research_root, report=report, relation=relation)
    return {"skip": False, "message": message}


def stop(
    research_root: Path,
    event: dict[str, Any],
    *,
    allow_incomplete: bool,
    cwd_provided: bool,
) -> dict[str, Any]:
    if allow_incomplete:
        return {"skip": True}

    state = load_lifecycle_state(research_root)
    if state.get("hooks_enabled") is not True:
        return {"skip": True}

    payload = dict(event)
    if cwd_provided and not payload.get("session_id"):
        owner = str((state.get("loop") or {}).get("owner_session_id") or "")
        diagnostic_session = owner or "manual-hook-probe"
        if not owner and state.get("phase") in {"execution", "review", "closure"}:
            state = claim_session(research_root, diagnostic_session, reason="manual Stop hook probe")
        payload["session_id"] = diagnostic_session
        payload.setdefault("turn_id", "manual-hook-probe-turn")

    verdict = observe_stop(research_root, payload)
    return {"skip": False, **verdict}


def main() -> int:
    parser = argparse.ArgumentParser(description="Node hook adapter bridge into AutoResearch Guard lifecycle.")
    parser.add_argument("op", choices=("session-start", "stop"))
    parser.add_argument("--research-root", required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--cwd-provided", action="store_true")
    args = parser.parse_args()

    research_root = Path(args.research_root).resolve()
    event = _read_event()
    if args.op == "session-start":
        result = session_start(research_root, event)
    else:
        result = stop(
            research_root,
            event,
            allow_incomplete=args.allow_incomplete,
            cwd_provided=args.cwd_provided,
        )
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
