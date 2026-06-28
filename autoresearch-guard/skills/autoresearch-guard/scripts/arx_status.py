from __future__ import annotations

import argparse
import json
from pathlib import Path

from arx_common import add_common_args, current_dir, latest_entry, listify, load_current_yaml, load_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Show current AutoResearch Guard status.")
    add_common_args(parser)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.research_root).resolve()
    cur = current_dir(root)
    state = load_current_yaml(root, "state.yaml")
    hypothesis = load_current_yaml(root, "hypothesis.yaml")
    protocol = load_current_yaml(root, "protocol.lock.yaml")
    blocked = load_current_yaml(root, "blocked_actions.yaml")
    claim = load_current_yaml(root, "claim_boundary.yaml")
    audit = load_current_yaml(root, "audit_report.yaml")
    decision = load_current_yaml(root, "decision.yaml")
    entries = load_jsonl(cur / "evidence_ledger.jsonl") if cur.exists() else []

    status = {
        "research_root": str(root),
        "current_exists": cur.exists(),
        "iteration_id": hypothesis.get("iteration_id") or state.get("iteration_id"),
        "state": state.get("status"),
        "objective": hypothesis.get("objective"),
        "protocol_locked": protocol.get("locked") is True,
        "protocol_digest": state.get("protocol_digest"),
        "evidence_records": len(entries),
        "latest_evidence": latest_entry(entries),
        "audit": {
            "exists": bool(audit),
            "evidence_valid": audit.get("evidence_valid"),
            "protocol_violation": audit.get("protocol_violation"),
            "test_contamination": audit.get("test_contamination"),
            "validation_gate_passed": audit.get("validation_gate_passed"),
            "forbidden_decisions": audit.get("forbidden_decisions"),
        },
        "decision": decision.get("decision"),
        "blocked_actions": listify(blocked.get("blocked_actions")),
        "max_claim_level": claim.get("max_claim_level"),
        "requires_human_gate": state.get("human_gate_required"),
    }

    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=True, sort_keys=True))
    else:
        print(f"AutoResearch Guard status: {status['iteration_id']}")
        print(f"- current: {status['current_exists']} ({cur})")
        print(f"- state: {status['state']}")
        print(f"- objective: {status['objective']}")
        print(f"- protocol locked: {status['protocol_locked']}")
        print(f"- evidence records: {status['evidence_records']}")
        print(f"- audit evidence_valid: {status['audit']['evidence_valid']}")
        print(f"- audit validation_gate_passed: {status['audit']['validation_gate_passed']}")
        print(f"- decision: {status['decision']}")
        print(f"- max claim level: {status['max_claim_level']}")
        print(f"- human gate required: {status['requires_human_gate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())