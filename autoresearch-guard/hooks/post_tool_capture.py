from __future__ import annotations

import argparse

from hook_runtime import additional_context, emit, find_research_root, likely_experiment, read_event, system_warning

from arx_lifecycle import claim_session, load_lifecycle_state, record_event, remember_tool_use


def main() -> int:
    parser = argparse.ArgumentParser(description="在实验类命令后发出幂等 evidence 提醒；本 hook 不自动记录证据。")
    parser.add_argument("--command", default="")
    parser.add_argument("--cwd", default="")
    args = parser.parse_args()
    event = read_event(cwd=args.cwd, command=args.command)
    if not event.command or not likely_experiment(event.command):
        return 0

    research_root = find_research_root(event.cwd)
    if research_root is None:
        return 0
    try:
        state = load_lifecycle_state(research_root)
        if state.get("hooks_enabled") is not True:
            return 0
        loop = state.get("loop") or {}
        owner = str(loop.get("owner_session_id") or "")
        if owner and event.session_id and owner != event.session_id:
            emit(system_warning(f"AutoResearch Guard ignored evidence reminder from non-owner session; owner={owner}"))
            return 0
        if not owner and event.session_id and state.get("phase") == "execution":
            state = claim_session(research_root, event.session_id, reason="PostToolUse experiment command")
        if not remember_tool_use(research_root, event.tool_use_id):
            return 0
        attempt_id = event.tool_use_id or "<stable-attempt-id>"
        message = (
            "AutoResearch Guard observed an experiment-like command. This hook did not capture evidence. "
            f"Inspect the tool result, then call arx_record.py with --attempt-id {attempt_id}; "
            "record exit status, split, seed, result digest and metrics before audit."
        )
        record_event(
            research_root,
            "hook.post_reminder",
            details={"session_id": event.session_id, "turn_id": event.turn_id, "tool_use_id": event.tool_use_id},
            state=state,
        )
        emit(additional_context("PostToolUse", message))
    except Exception as exc:
        emit(system_warning(f"AutoResearch Guard PostToolUse reminder failed open: {exc}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
