from __future__ import annotations

from hook_runtime import additional_context, emit, find_research_root, read_event, system_warning

from arx_lifecycle import evaluate_readiness, load_lifecycle_state


def main() -> int:
    event = read_event()
    research_root = find_research_root(event.cwd)
    if research_root is None:
        return 0
    try:
        state = load_lifecycle_state(research_root)
        if state.get("hooks_enabled") is not True:
            return 0
        report = evaluate_readiness(research_root)
        owner = str((state.get("loop") or {}).get("owner_session_id") or "")
        relation = "owner" if owner and owner == event.session_id else ("unbound" if not owner else "non-owner")
        next_action = (report.get("next_actions") or ["run arx_loop.py check --json"])[0]
        message = (
            f"AutoResearch Guard recovery state: iteration={report.get('iteration_id')}; "
            f"phase={report.get('phase')}; status={report.get('status')}; outcome={report.get('outcome')}; "
            f"session_relation={relation}; state_digest={report.get('state_digest')}; next={next_action}. "
            "Read .research/current/state.yaml and run arx_loop.py check --json before changing research state."
        )
        emit(additional_context("SessionStart", message))
    except Exception as exc:
        emit(system_warning(f"AutoResearch Guard recovery context could not be loaded: {exc}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
