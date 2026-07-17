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
    parse_markdown_tables,
    read_text,
    render_template,
    research_lock,
    sha256_file,
    template_dir,
    utc_now,
    write_text,
)
from arx_lifecycle import configure_execution, loop_budget_from_protocol, require_phase


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


def budget_lines(protocol: dict[str, Any]) -> list[str]:
    budget = loop_budget_from_protocol(protocol)
    return [f"{name}: {value}" for name, value in budget.items()]


def _lookup(row: dict[str, str], *names: str) -> str:
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return value.strip()
    return ""


def literature_trace_sets(text: str) -> tuple[set[str], set[str]]:
    idea_ids: set[str] = set()
    implementation_refs: set[str] = set()
    for row in parse_markdown_tables(text):
        section = str(row.get("_section") or "").lower()
        idea_id = _lookup(row, "idea_id", "idea id", "id")
        if idea_id and ("候选" in section or "idea" in section or "innovation" in section):
            idea_ids.add(idea_id)

        is_implementation = (
            "实现" in section
            or "implementation" in section
            or bool(_lookup(row, "impl_id", "implementation_id", "reuse_decision", "covered_capability"))
        )
        if is_implementation:
            for name in ("impl_id", "implementation_id", "name", "url"):
                value = _lookup(row, name)
                if value:
                    implementation_refs.add(value)
    return idea_ids, implementation_refs


def validate_literature_trace(cur: Path, hypothesis: dict[str, Any], reuse_base: str) -> None:
    literature_path = cur / "literature_review.md"
    literature_text = read_text(literature_path) if literature_path.exists() else ""
    idea_ids, implementation_refs = literature_trace_sets(literature_text)

    if not idea_ids:
        raise ArxError("literature_review.md missing candidate idea table with idea_id")
    evidence_items = [str(item).strip() for item in listify(hypothesis.get("evidence_basis")) if str(item).strip()]
    missing_evidence = [item for item in evidence_items if item not in idea_ids]
    if missing_evidence:
        raise ArxError(
            "hypothesis.yaml evidence_basis must reference literature_review.md idea_id: "
            + ", ".join(missing_evidence)
        )

    if reuse_base != "build_new":
        if not implementation_refs:
            raise ArxError("literature_review.md missing existing implementation table")
        if reuse_base not in implementation_refs:
            raise ArxError("hypothesis.yaml reuse_plan.base must reference literature_review.md implementation id or url")


def run_compile(root: Path, cur: Path, *, allow_unlocked: bool) -> int:
    if not cur.exists():
        raise ArxError(f"missing current directory: {cur}")
    state = require_phase(root, "compile", {"draft"})

    hypothesis = load_current_yaml(root, "hypothesis.yaml")
    protocol = load_current_yaml(root, "protocol.lock.yaml")
    blocked = load_current_yaml(root, "blocked_actions.yaml")
    claim = load_current_yaml(root, "claim_boundary.yaml")

    if not allow_unlocked and protocol.get("locked") is not True:
        raise ArxError("protocol.lock.yaml is not locked; set locked: true after human review")

    for field in ["iteration_id", "objective", "hypothesis", "evidence_basis"]:
        if not hypothesis.get(field):
            raise ArxError(f"hypothesis.yaml missing required field: {field}")
    if str(hypothesis.get("iteration_id") or "") != str(state.get("iteration_id") or ""):
        raise ArxError(
            "hypothesis.yaml iteration_id must match canonical state.yaml iteration_id: "
            f"{hypothesis.get('iteration_id')} != {state.get('iteration_id')}"
        )

    reuse = hypothesis.get("reuse_plan") or {}
    if not isinstance(reuse, dict):
        raise ArxError("hypothesis.yaml reuse_plan must be a mapping")
    reuse_base = str(reuse.get("base") or "").strip()
    if not reuse_base:
        raise ArxError("hypothesis.yaml reuse_plan.base is required (repo url or 'build_new')")
    if reuse_base == "build_new" and not str(reuse.get("build_new_reason") or "").strip():
        raise ArxError("hypothesis.yaml reuse_plan.build_new_reason is required when base == build_new")
    validate_literature_trace(cur, hypothesis, reuse_base)

    protocol_path = cur / "protocol.lock.yaml"
    digest = sha256_file(protocol_path)
    compiled_at = utc_now()

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
        "loop_budget_lines": markdown_list(budget_lines(protocol)),
    }

    output = render_template(template_dir() / "active_goal.md.j2", context)
    if allow_unlocked and protocol.get("locked") is not True:
        draft = cur / "active_goal.draft.md"
        write_text(draft, "<!-- DRAFT: protocol is not locked; this file cannot arm execution. -->\n\n" + output)
        print(f"Wrote draft goal {draft}; lifecycle remains draft/idle")
        return 0

    with research_lock(root):
        goal_path = cur / "active_goal.md"
        write_text(goal_path, output)
        configure_execution(root, protocol_digest=digest, compiled_at=compiled_at, protocol=protocol)
    print(f"Wrote {goal_path}")
    print(f"Protocol digest: {digest}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile AI-authored research state into active_goal.md.")
    add_common_args(parser)
    parser.add_argument("--allow-unlocked", action="store_true", help="Render active_goal.draft.md without arming execution")
    args = parser.parse_args()

    root = Path(args.research_root).resolve()
    cur = current_dir(root)
    with research_lock(root):
        return run_compile(root, cur, allow_unlocked=args.allow_unlocked)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")
