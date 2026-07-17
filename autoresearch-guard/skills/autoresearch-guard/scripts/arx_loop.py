from __future__ import annotations

import argparse
import json
from pathlib import Path

from arx_common import ArxError, add_common_args
from arx_harness import prepare_review_pack
from arx_lifecycle import (
    abort_loop,
    claim_session,
    evaluate_readiness,
    load_lifecycle_state,
    pause_loop,
    resume_loop,
    set_hooks_enabled,
    trip_budget_circuit_breaker,
    transition,
)


def render_human(report: dict) -> str:
    lines = [
        f"AutoResearch Guard loop: {report['iteration_id']}",
        f"- outcome: {report['outcome']}",
        f"- phase/status: {report['phase']}/{report['status']}",
        f"- process_ready: {str(report.get('process_ready')).lower()}",
        f"- outcome_ready: {str(report.get('outcome_ready')).lower()}",
        f"- goal_ready/ready: {str(report.get('goal_ready', report.get('ready'))).lower()}",
        f"- state digest: {report['state_digest']}",
    ]
    for reason in report.get("reasons") or []:
        lines.append(f"- reason: {reason}")
    for action in report.get("next_actions") or []:
        lines.append(f"- next: {action}")
    budget = report.get("budget") or {}
    lines.append(f"- budget remaining: {json.dumps(budget.get('remaining') or {}, ensure_ascii=False, sort_keys=True)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="控制并检查 AutoResearch Guard 的外层研究循环。")
    parser.add_argument(
        "action",
        choices=[
            "check",
            "start",
            "pause",
            "resume",
            "abort",
            "hooks",
            "prepare-review",
        ],
    )
    add_common_args(parser)
    parser.add_argument("--json", action="store_true", help="输出结构化 loop verdict")
    parser.add_argument("--require-ready", action="store_true", help="check 未达到 closure 时返回非零")
    parser.add_argument("--session-id", default="", help="显式绑定 owner session")
    parser.add_argument("--reason", default="", help="pause/resume/abort 的原因")
    parser.add_argument("--human-approved", action="store_true", help="记录本次 resume 经过人工 checkpoint")
    parser.add_argument("--reopen-execution", action="store_true", help="从 review 显式回到 execution 以补充 evidence")
    parser.add_argument("--on", action="store_true", help="hooks action: 为当前 .research 打开 hooks")
    parser.add_argument("--off", action="store_true", help="hooks action: 为当前 .research 关闭 hooks")
    args = parser.parse_args()

    if args.action == "hooks":
        if args.on and args.off:
            raise ArxError("hooks action accepts either --on or --off, not both")
        if not args.on and not args.off:
            state = load_lifecycle_state(args.research_root)
            enabled = state.get("hooks_enabled") is True
            payload = {
                "iteration_id": state.get("iteration_id"),
                "phase": state.get("phase"),
                "status": (state.get("loop") or {}).get("status"),
                "hooks_enabled": enabled,
            }
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(
                    f"Hooks {'enabled' if enabled else 'disabled'} for "
                    f"{payload['iteration_id']} ({payload['phase']}/{payload['status']})"
                )
            return 0
        state = set_hooks_enabled(args.research_root, enabled=args.on)
        enabled = state.get("hooks_enabled") is True
        print(
            f"Hooks {'enabled' if enabled else 'disabled'} for "
            f"{state.get('iteration_id')} ({state.get('phase')}/{(state.get('loop') or {}).get('status')})"
        )
        return 0

    if args.action == "prepare-review":
        manifest = prepare_review_pack(args.research_root)
        if args.json:
            print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print(f"Prepared review pack at {manifest.get('pack_dir')}")
            print(f"bound_audit_digest={manifest.get('bound_audit_digest')}")
            print("Spawn a same-session review subagent with only review_pack/ inputs.")
        return 0

    if args.action == "start":
        if args.session_id:
            state = claim_session(args.research_root, args.session_id, reason="arx_loop start")
        else:
            current = load_lifecycle_state(args.research_root)
            current_status = str((current.get("loop") or {}).get("status") or "")
            if current.get("phase") != "execution" or current_status not in {"armed", "running"}:
                raise ArxError(
                    f"start is only allowed from execution/armed or execution/running, got "
                    f"{current.get('phase')}/{current_status}"
                )
            owner = str((current.get("loop") or {}).get("owner_session_id") or "")
            state = transition(
                args.research_root,
                operation="start",
                allowed_phases={"execution"},
                phase="execution",
                status="running",
                updates={
                    "loop.owner_session_id": owner,
                    "loop.pause_reason": "",
                    "loop.no_progress_turns": 0,
                },
            )
        print(f"Loop started: {state.get('iteration_id')} owner={(state.get('loop') or {}).get('owner_session_id') or 'unbound'}")
        return 0
    if args.action == "pause":
        state = pause_loop(args.research_root, args.reason)
        print(f"Loop paused: {(state.get('loop') or {}).get('pause_reason')}")
        return 0
    if args.action == "resume":
        state = resume_loop(
            args.research_root,
            args.reason,
            human_approved=args.human_approved,
            reopen_execution=args.reopen_execution,
        )
        print(f"Loop resumed: {state.get('phase')}/{(state.get('loop') or {}).get('status')}")
        return 0
    if args.action == "abort":
        state = abort_loop(args.research_root, args.reason)
        print(f"Loop aborted: {(state.get('loop') or {}).get('pause_reason')}")
        return 0

    report = evaluate_readiness(args.research_root)
    if not report["ready"] and (report.get("budget") or {}).get("exhausted"):
        trip_budget_circuit_breaker(args.research_root, list(report["budget"]["exhausted"]))
        report = evaluate_readiness(args.research_root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(render_human(report), end="")
    return 2 if args.require_ready and not report["ready"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")
