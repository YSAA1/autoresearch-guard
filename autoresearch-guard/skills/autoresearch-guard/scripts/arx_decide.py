from __future__ import annotations

import argparse
from pathlib import Path

from arx_common import (
    ArxError,
    DECISIONS,
    add_common_args,
    current_dir,
    load_yaml,
    read_text,
    research_lock,
    sha256_file,
    utc_now,
    write_yaml,
)
from arx_lifecycle import audit_is_fresh, decision_policy_errors, mark_closure, require_phase
from arx_harness import requires_subagent_review, subagent_review_errors


def run_decide(root: Path, cur: Path, args: argparse.Namespace) -> int:
    if not cur.exists():
        raise ArxError(f"missing current directory: {cur}")
    state = require_phase(root, "decide", {"review"})

    audit_path = cur / "audit_report.yaml"
    if not audit_path.exists():
        raise ArxError("audit_report.yaml missing; run arx_audit.py first")
    audit = load_yaml(audit_path)
    fresh, stale_inputs = audit_is_fresh(root, audit)
    if not fresh:
        raise ArxError(
            "audit_report.yaml is stale for: " + ", ".join(stale_inputs) + "; rerun arx_audit.py"
        )

    review_path = cur / "ai_evidence_review.md"
    review_text = read_text(review_path).strip() if review_path.exists() else ""
    claim_status = audit.get("claim_support_status") or {}
    if not review_text or "TBD by AI" in review_text or int(claim_status.get("claims_checked") or 0) <= 0:
        raise ArxError(
            "ai_evidence_review.md is incomplete; finish the review and claim table, then rerun arx_audit.py"
        )

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

    audit_digest = sha256_file(audit_path)
    if str(state.get("audit_digest") or "") != audit_digest:
        raise ArxError("audit_report.yaml changed after audit; rerun arx_audit.py")
    policy_errors = decision_policy_errors(audit, proposal, state, audit_digest=audit_digest)
    if policy_errors:
        raise ArxError("invalid decision proposal: " + "; ".join(policy_errors))
    decision = str(proposal.get("decision") or "")
    if requires_subagent_review(root, decision=decision, audit=audit):
        review_errors = subagent_review_errors(root, required=True, audit_digest=audit_digest)
        if review_errors:
            raise ArxError(
                "subagent review required for promote (ai_evidence_review.md cannot substitute): "
                + "; ".join(review_errors)
            )

    committed = dict(proposal)
    committed["committed_at"] = utc_now()
    committed["audit_report"] = "audit_report.yaml"
    committed["audit_digest"] = audit_digest
    committed["input_digests"] = audit.get("input_digests") or {}
    decision_path = cur / "decision.yaml"
    write_yaml(decision_path, committed)
    mark_closure(root, decision_digest=sha256_file(decision_path))
    print(f"Committed decision: {decision}")
    print(cur / "decision.yaml")
    return 0


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
    with research_lock(root):
        return run_decide(root, cur, args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")
