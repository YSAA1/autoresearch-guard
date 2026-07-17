from __future__ import annotations

import argparse

from hook_runtime import emit, find_research_root, read_event, system_warning

from arx_lifecycle import claim_session, load_lifecycle_state, observe_stop


def main() -> int:
    parser = argparse.ArgumentParser(description="把 Codex Stop 事件适配为有界的 AutoResearch Guard closure 决策。")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--allow-incomplete", action="store_true", help="Diagnostic escape hatch: allow this Stop without changing state")
    args = parser.parse_args()
    event = read_event(cwd=args.cwd)
    research_root = find_research_root(event.cwd)
    if research_root is None or args.allow_incomplete:
        return 0

    try:
        state = load_lifecycle_state(research_root)
        if state.get("hooks_enabled") is not True:
            return 0

        payload = dict(event.payload)
        if args.cwd and not event.session_id:
            owner = str((state.get("loop") or {}).get("owner_session_id") or "")
            diagnostic_session = owner or "manual-hook-probe"
            if not owner and state.get("phase") in {"execution", "review", "closure"}:
                state = claim_session(research_root, diagnostic_session, reason="manual Stop hook probe")
            payload["session_id"] = diagnostic_session
            payload.setdefault("turn_id", "manual-hook-probe-turn")

        verdict = observe_stop(research_root, payload)
        action = verdict.get("action")
        if action == "continue":
            emit({"decision": "block", "reason": str(verdict.get("reason") or "AutoResearch Guard closure is incomplete")})
        elif action == "halt":
            emit(system_warning(str(verdict.get("reason") or "AutoResearch Guard paused the loop"), stop=True))
        elif action == "allow":
            readiness = verdict.get("readiness") or {}
            if readiness.get("outcome") in {"blocked_requires_human", "aborted"}:
                emit(system_warning(str(verdict.get("reason") or readiness.get("outcome"))))
    except Exception as exc:
        emit(system_warning(f"AutoResearch Guard Stop check failed; the loop was stopped safely: {exc}", stop=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
