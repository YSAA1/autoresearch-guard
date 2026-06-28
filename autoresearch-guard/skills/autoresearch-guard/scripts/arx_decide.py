from __future__ import annotations

import argparse
from pathlib import Path

from arx_common import (
    ArxError,
    DECISIONS,
    add_common_args,
    current_dir,
    load_current_yaml,
    load_yaml,
    sha256_file,
    utc_now,
    write_yaml,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check and commit an AI-proposed research decision.")
    add_common_args(parser)
    parser.add_argument("--proposed", help="Path to proposed decision YAML; defaults to current/decision.proposed.yaml")
    parser.add_argument("--decision", choices=sorted(DECISIONS), help="Build a proposal from CLI fields")
    parser.add_argument("--reason", default="")
    parser.add_argument("--next-goal-type", default="")
    parser.add_argument("--requires-human", action="store_true")
    args = parser.parse_args()

    root = Path(args.research_root).resolve()
    cur = current_dir(root)
    if not cur.exists():
        raise ArxError(f"missing current directory: {cur}")

    audit_path = cur / "audit_report.yaml"
    if not audit_path.exists():
        raise ArxError("audit_report.yaml missing; run arx_audit.py first")
    audit = load_yaml(audit_path)

    if args.decision:
        proposal = {
            "decision": args.decision,
            "reason": args.reason,
            "next_goal_type": args.next_goal_type or args.decision,
            "requires_human": args.requires_human,
        }
    else:
        proposed_path = Path(args.proposed).resolve() if args.proposed else cur / "decision.proposed.yaml"
        if not proposed_path.exists():
            raise ArxError(f"missing proposed decision: {proposed_path}")
        proposal = load_yaml(proposed_path)

    decision = str(proposal.get("decision") or "")
    if decision not in DECISIONS:
        raise ArxError(f"invalid decision {decision}; expected one of {sorted(DECISIONS)}")
    if not proposal.get("reason"):
        raise ArxError("decision proposal must include reason")

    forbidden = {str(x) for x in (audit.get("forbidden_decisions") or [])}
    if decision in forbidden:
        raise ArxError(f"invalid decision: {decision} is forbidden by audit_report.yaml")

    committed = dict(proposal)
    committed["committed_at"] = utc_now()
    committed["audit_report"] = str(audit_path.resolve())
    committed["audit_digest"] = sha256_file(audit_path)
    write_yaml(cur / "decision.yaml", committed)
    print(f"Committed decision: {decision}")
    print(cur / "decision.yaml")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")