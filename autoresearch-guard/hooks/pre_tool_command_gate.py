from __future__ import annotations

import argparse

from hook_runtime import (
    deny,
    emit,
    find_research_root,
    likely_experiment,
    mutates_locked_protocol,
    read_event,
    starts_loop,
)

from arx_common import contains_pattern, listify, load_current_yaml
from arx_lifecycle import claim_session, load_lifecycle_state, record_event


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


def command_mentions_split(command: str, split: str) -> bool:
    from arx_common import command_mentions_split as shared_check

    return shared_check(command, split)


def main() -> int:
    parser = argparse.ArgumentParser(description="拦截 AutoResearch Guard 的确定性命令违规。")
    parser.add_argument("--command", default="")
    parser.add_argument("--cwd", default="")
    args = parser.parse_args()
    event = read_event(cwd=args.cwd, command=args.command)
    if not event.command:
        return 0

    research_root = find_research_root(event.cwd)
    if research_root is None:
        return 0

    is_shell = event.tool_name.lower() == "bash"
    experiment = is_shell and likely_experiment(event.command)
    try:
        state = load_lifecycle_state(research_root)
    except Exception as exc:
        if experiment or mutates_locked_protocol(event):
            emit(deny(f"AutoResearch Guard state is unreadable; refusing a research mutation: {exc}"))
        return 0
    if state.get("hooks_enabled") is not True:
        return 0

    try:
        protocol = load_current_yaml(research_root, "protocol.lock.yaml")
        blocked = load_current_yaml(research_root, "blocked_actions.yaml")
    except Exception as exc:
        if experiment or mutates_locked_protocol(event):
            emit(deny(f"AutoResearch Guard policy is unreadable; refusing a research mutation: {exc}"))
        return 0
    reasons: list[str] = []

    for split in listify(protocol.get("forbidden_splits")):
        if command_mentions_split(event.command, str(split)):
            reasons.append(f"command touches forbidden split: {split}")

    for action, reason, pattern in blocked_patterns(blocked):
        if pattern and contains_pattern(event.command, pattern):
            reasons.append(f"command matches blocked action {action}: {reason}")

    if protocol.get("locked") is True and mutates_locked_protocol(event):
        reasons.append("command attempts to edit locked protocol.lock.yaml")

    phase = str(state.get("phase") or "")
    loop = state.get("loop") or {}
    status = str(loop.get("status") or "")
    owner = str(loop.get("owner_session_id") or "")
    claims_loop = is_shell and starts_loop(event.command)
    if claims_loop and (phase != "execution" or status not in {"armed", "running"}):
        reasons.append(f"loop start is only allowed from execution/armed, current state is {phase}/{status}")
    if experiment and phase != "execution":
        reasons.append(f"experiment commands are only allowed in execution phase, current phase is {phase}")
    if experiment and status not in {"armed", "running"}:
        reasons.append(f"experiment commands are blocked while loop status is {status}")
    if (experiment or claims_loop) and owner and event.session_id and owner != event.session_id:
        reasons.append(f"research loop is owned by another session: {owner}")

    if reasons:
        reason = "; ".join(dict.fromkeys(reasons))
        emit(deny(reason))
        try:
            record_event(
                research_root,
                "hook.pre_denied",
                details={"session_id": event.session_id, "turn_id": event.turn_id, "tool_use_id": event.tool_use_id, "reason": reason},
                state=state,
            )
        except Exception:
            # A logging failure must not turn a deterministic deny into an
            # unstructured hook crash.
            pass
        return 0

    if (experiment or claims_loop) and event.session_id and not owner:
        try:
            claim_session(research_root, event.session_id, reason="PreToolUse research command")
        except Exception as exc:
            emit(deny(f"research owner claim failed: {exc}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
