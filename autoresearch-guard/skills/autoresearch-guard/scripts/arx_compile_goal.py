from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from arx_common import (
    ArxError,
    add_common_args,
    current_dir,
    listify,
    load_current_yaml,
    markdown_list,
    render_template,
    sha256_file,
    template_dir,
    update_state,
    write_text,
)


def blocked_lines(blocked: dict[str, Any]) -> list[str]:
    rows = []
    for item in listify(blocked.get("blocked_actions")):
        if isinstance(item, dict):
            action = item.get("action_id") or item.get("name") or "blocked_action"
            reason = item.get("reason") or "no reason recorded"
            patterns = ", ".join(str(p) for p in listify(item.get("patterns")))
            rows.append(f"{action}: {reason}; patterns: {patterns or 'none'}")
        else:
            rows.append(str(item))
    return rows


def gate_lines(protocol: dict[str, Any]) -> list[str]:
    rows = []
    for gate in listify(protocol.get("validation_gates")):
        if isinstance(gate, dict):
            metric = gate.get("metric", "metric")
            operator = gate.get("operator", ">=")
            value = gate.get("value", "TBD")
            split = gate.get("split", "validation")
            aggregation = gate.get("aggregation", "latest")
            rows.append(f"{aggregation}({metric}) on {split} {operator} {value}")
        else:
            rows.append(str(gate))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile AI-authored research state into active_goal.md.")
    add_common_args(parser)
    parser.add_argument("--allow-unlocked", action="store_true", help="Allow draft goal compilation before human protocol lock")
    args = parser.parse_args()

    root = Path(args.research_root).resolve()
    cur = current_dir(root)
    if not cur.exists():
        raise ArxError(f"missing current directory: {cur}")

    hypothesis = load_current_yaml(root, "hypothesis.yaml")
    protocol = load_current_yaml(root, "protocol.lock.yaml")
    blocked = load_current_yaml(root, "blocked_actions.yaml")
    claim = load_current_yaml(root, "claim_boundary.yaml")

    if not args.allow_unlocked and protocol.get("locked") is not True:
        raise ArxError("protocol.lock.yaml is not locked; set locked: true after human review")

    for field in ["iteration_id", "objective", "hypothesis"]:
        if not hypothesis.get(field):
            raise ArxError(f"hypothesis.yaml missing required field: {field}")

    protocol_path = cur / "protocol.lock.yaml"
    digest = sha256_file(protocol_path)
    update_state(root, protocol_digest=digest)

    context = {
        "iteration_id": hypothesis.get("iteration_id", ""),
        "objective": hypothesis.get("objective", ""),
        "hypothesis": hypothesis.get("hypothesis", ""),
        "protocol_digest": digest,
        "allowed_splits": ", ".join(str(x) for x in listify(protocol.get("allowed_splits"))) or "none",
        "forbidden_splits": ", ".join(str(x) for x in listify(protocol.get("forbidden_splits"))) or "none",
        "allowed_work_lines": markdown_list(listify(hypothesis.get("allowed_work"))),
        "forbidden_work_lines": markdown_list(listify(hypothesis.get("forbidden_work"))),
        "blocked_action_lines": markdown_list(blocked_lines(blocked)),
        "max_claim_level": claim.get("max_claim_level", "exploratory"),
        "forbidden_claims": ", ".join(str(x) for x in listify(claim.get("forbidden_claims"))) or "none",
        "must_produce_lines": markdown_list(listify(hypothesis.get("must_produce")) or listify(protocol.get("required_outputs"))),
        "validation_gate_lines": markdown_list(gate_lines(protocol)),
    }

    output = render_template(template_dir() / "active_goal.md.j2", context)
    write_text(cur / "active_goal.md", output)
    print(f"Wrote {cur / 'active_goal.md'}")
    print(f"Protocol digest: {digest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")