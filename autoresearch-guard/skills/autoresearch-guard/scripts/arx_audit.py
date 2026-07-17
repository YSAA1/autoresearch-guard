from __future__ import annotations

import argparse
import operator
from pathlib import Path
from statistics import mean
from typing import Any

from arx_common import (
    ArxError,
    add_common_args,
    command_mentions_split,
    contains_pattern,
    current_dir,
    listify,
    load_current_yaml,
    load_jsonl,
    parse_markdown_tables,
    parse_timestamp,
    read_text,
    research_lock,
    sha256_file,
    utc_now,
    write_yaml,
)
from arx_lifecycle import (
    audit_input_digests,
    budget_snapshot,
    mark_review,
    require_phase,
    tracked_metric_keys,
)
from arx_harness import subagent_review_errors
from arx_research import (
    claim_level_rank,
    dump_research_gate_yaml,
    evaluate_research_gates,
    evaluate_verified_claims,
    normalize_claim_level,
)

OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def blocked_patterns(blocked: dict[str, Any]) -> list[tuple[str, str, str]]:
    patterns: list[tuple[str, str, str]] = []
    for item in listify(blocked.get("blocked_actions")):
        if isinstance(item, dict):
            action = str(item.get("action_id") or item.get("name") or "blocked_action")
            reason = str(item.get("reason") or "blocked by protocol")
            for pattern in listify(item.get("patterns")):
                patterns.append((action, reason, str(pattern)))
        else:
            patterns.append((str(item), "blocked by protocol", str(item)))
    return patterns


def metric_values(entries: list[dict[str, Any]], metric: str, split: str | None) -> list[float]:
    values: list[float] = []
    for entry in entries:
        if split and entry.get("data_split") != split:
            continue
        metrics = entry.get("metrics") or {}
        if metric not in metrics:
            continue
        value = metrics[metric]
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def aggregate(values: list[float], mode: str) -> float:
    if not values:
        raise ArxError("cannot aggregate empty metric values")
    if mode == "latest":
        return values[-1]
    if mode == "min":
        return min(values)
    if mode == "max":
        return max(values)
    if mode == "mean":
        return mean(values)
    raise ArxError(f"unknown aggregation: {mode}")


def compute_spiral_risk(
    entries: list[dict[str, Any]],
    blocked: list[tuple[str, str, str]],
    budget: dict[str, Any],
    tracked_metrics: set[tuple[str, str]],
) -> dict[str, Any]:
    max_failed = int(budget.get("max_consecutive_failures") or budget.get("max_failed_attempts") or 3)
    max_flat = int(budget.get("max_flatline_count") or 3)

    failed = 0
    for entry in reversed(entries):
        if str(entry.get("role") or "experiment") == "baseline":
            continue
        if str(entry.get("status") or "").lower() in {"fail", "error"} or int(entry.get("exit_code") or 0) != 0:
            failed += 1
        else:
            break

    flatline_count = 0
    by_metric: dict[tuple[str, str], list[float]] = {}
    for e in entries:
        if str(e.get("role") or "experiment") == "baseline":
            continue
        if str(e.get("status") or "").lower() in {"fail", "error"} or int(e.get("exit_code") or 0) != 0:
            continue
        metrics = e.get("metrics") or {}
        for name, value in metrics.items():
            metric_name = str(name)
            metric_key = (metric_name, str(e.get("data_split") or ""))
            if isinstance(value, (int, float)) and (not tracked_metrics or metric_key in tracked_metrics):
                by_metric.setdefault(metric_key, []).append(float(value))
    for values in by_metric.values():
        if values:
            tail = 1
            for index in range(len(values) - 1, 0, -1):
                if abs(values[index] - values[index - 1]) < 1e-9:
                    tail += 1
                else:
                    break
            flatline_count = max(flatline_count, tail)

    no_signal_streak = 0
    for entry in reversed(entries):
        tags = {str(tag).strip().lower() for tag in listify(entry.get("failure_tags"))}
        if "no_signal" in tags:
            no_signal_streak += 1
        else:
            break

    blocked_counts: dict[str, int] = {}
    for action, _reason, pattern in blocked:
        if not pattern:
            continue
        hits = sum(1 for e in entries if contains_pattern(str(e.get("command") or ""), pattern))
        if hits:
            blocked_counts[action] = hits
    repeated_blocked = max(blocked_counts.values()) if blocked_counts else 0

    signals: list[str] = []
    if failed >= max_failed:
        signals.append("same_hypothesis_attempts")
    if flatline_count >= max_flat:
        signals.append("metric_flatline")
    if no_signal_streak >= 2:
        signals.append("no_signal_streak")
    if repeated_blocked >= 3:
        signals.append("repeated_blocked_actions")

    if len(signals) >= 2 or (failed >= max_failed and max_failed > 0):
        level = "critical"
    elif signals:
        level = "caution"
    else:
        level = "none"

    return {
        "level": level,
        "signals": signals,
        "counts": {
            "same_hypothesis_attempts": failed,
            "metric_flatline": flatline_count,
            "no_signal_streak": no_signal_streak,
            "repeated_blocked_actions": repeated_blocked,
        },
    }


def evaluate_gates(protocol: dict[str, Any], entries: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]], list[str]]:
    gates = listify(protocol.get("validation_gates"))
    if not gates:
        return False, [], ["no validation_gates configured"]
    results: list[dict[str, Any]] = []
    unknowns: list[str] = []
    all_pass = True
    for gate in gates:
        if not isinstance(gate, dict):
            unknowns.append(f"gate is not a mapping: {gate}")
            all_pass = False
            continue
        metric = str(gate.get("metric") or "")
        op = str(gate.get("operator") or ">=")
        split = str(gate.get("split") or "validation")
        aggregation = str(gate.get("aggregation") or "latest")
        threshold = gate.get("value")
        if not metric or op not in OPS or threshold is None:
            unknowns.append(f"invalid gate definition: {gate}")
            all_pass = False
            continue
        values = metric_values(entries, metric, split)
        if not values:
            unknowns.append(f"no values for metric {metric} on split {split}")
            all_pass = False
            results.append({"metric": metric, "status": "unknown", "reason": "missing metric values"})
            continue
        observed = aggregate(values, aggregation)
        passed = OPS[op](observed, float(threshold))
        all_pass = all_pass and passed
        results.append({
            "metric": metric,
            "split": split,
            "aggregation": aggregation,
            "operator": op,
            "threshold": threshold,
            "observed": observed,
            "status": "pass" if passed else "fail",
        })
    return all_pass, results, unknowns


def evaluate_baseline(protocol: dict[str, Any], entries: list[dict[str, Any]]) -> tuple[dict[str, Any], bool, list[str]]:
    baseline = protocol.get("baseline") or {}
    if not isinstance(baseline, dict) or baseline.get("required") is not True:
        return {"required": False, "status": "not_required"}, False, []

    metric = str(baseline.get("metric") or "")
    split = str(baseline.get("split") or "validation")
    aggregation = str(baseline.get("aggregation") or "max")
    min_delta = float(baseline.get("min_delta") or 0)
    higher_is_better = baseline.get("higher_is_better") is not False
    status: dict[str, Any] = {
        "required": True,
        "metric": metric,
        "split": split,
        "aggregation": aggregation,
        "min_delta": min_delta,
        "higher_is_better": higher_is_better,
    }
    unknowns: list[str] = []
    if not metric:
        status["status"] = "invalid_config"
        unknowns.append("baseline.metric is required when baseline.required is true")
        return status, True, unknowns

    baseline_entries = [entry for entry in entries if str(entry.get("role") or "") == "baseline"]
    experiment_entries = [entry for entry in entries if str(entry.get("role") or "experiment") != "baseline"]
    if not baseline_entries:
        status["status"] = "missing_required_baseline"
        return status, True, unknowns

    baseline_values = metric_values(baseline_entries, metric, split)
    if not baseline_values:
        status["status"] = "missing_baseline_metric"
        unknowns.append(f"no baseline values for metric {metric} on split {split}")
        return status, True, unknowns

    observed_values = metric_values(experiment_entries, metric, split)
    if not observed_values:
        status["status"] = "missing_experiment_metric"
        unknowns.append(f"no experiment values for metric {metric} on split {split}")
        return status, True, unknowns

    baseline_value = aggregate(baseline_values, aggregation)
    observed_value = aggregate(observed_values, aggregation)
    required_value = baseline_value + min_delta if higher_is_better else baseline_value - min_delta
    passed = observed_value >= required_value if higher_is_better else observed_value <= required_value
    status.update({
        "baseline": baseline_value,
        "observed": observed_value,
        "required_value": required_value,
        "status": "pass" if passed else "failed_baseline_comparison",
    })
    return status, not passed, unknowns


def _lookup(row: dict[str, str], *names: str) -> str:
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return value.strip()
    return ""


def evaluate_claim_support(review_text: str, claim_boundary: dict[str, Any]) -> tuple[dict[str, Any], bool, list[str]]:
    rows = [
        row for row in parse_markdown_tables(review_text)
        if _lookup(row, "claim_id", "claim id", "id") or "结论与证据" in str(row.get("_section") or "")
    ]
    status: dict[str, Any] = {
        "required": True,
        "status": "not_reviewed",
        "claims_checked": 0,
        "unsupported_claims": [],
        "prohibited_claims": [],
        "boundary_violations": [],
        "malformed_claims": [],
    }
    unknowns: list[str] = []
    if not rows:
        unknowns.append("ai_evidence_review.md has no claim support table")
        return status, True, unknowns

    max_level = normalize_claim_level(str(claim_boundary.get("max_claim_level") or "exploratory"))
    max_rank = claim_level_rank(max_level)
    if max_rank is None:
        unknowns.append(f"claim_boundary.yaml max_claim_level is unknown: {max_level}")
        max_rank = -1

    status["claims_checked"] = len(rows)
    for index, row in enumerate(rows, 1):
        claim_id = _lookup(row, "claim_id", "claim id", "id") or f"claim-{index}"
        conclusion = _lookup(row, "结论", "claim", "conclusion")
        level = normalize_claim_level(_lookup(row, "等级", "证据等级", "level", "evidence_level"))
        evidence = _lookup(row, "证据", "evidence")
        support = _lookup(row, "状态", "status").lower()
        if not conclusion or not level or not support:
            status["malformed_claims"].append(claim_id)
            continue
        if support == "unsupported":
            status["unsupported_claims"].append(claim_id)
        elif support == "prohibited":
            status["prohibited_claims"].append(claim_id)
        elif support != "supported":
            status["malformed_claims"].append(claim_id)
        if support == "supported" and evidence.lower() in {"", "none", "n/a", "na"}:
            status["unsupported_claims"].append(claim_id)
        rank = claim_level_rank(level)
        if rank is None:
            status["malformed_claims"].append(claim_id)
        elif rank > max_rank:
            status["boundary_violations"].append(claim_id)

    blocks = any(status[key] for key in ("unsupported_claims", "prohibited_claims", "boundary_violations", "malformed_claims"))
    status["status"] = "fail" if blocks else "pass"
    return status, blocks, unknowns


def run_audit(root: Path, cur: Path) -> int:
    if not cur.exists():
        raise ArxError(f"missing current directory: {cur}")
    require_phase(root, "audit", {"execution", "review"})
    input_digests_before = audit_input_digests(root)

    state = load_current_yaml(root, "state.yaml")
    protocol = load_current_yaml(root, "protocol.lock.yaml")
    blocked = load_current_yaml(root, "blocked_actions.yaml")
    hypothesis = load_current_yaml(root, "hypothesis.yaml")
    claim_boundary = load_current_yaml(root, "claim_boundary.yaml")
    all_entries = load_jsonl(cur / "evidence_ledger.jsonl")
    iteration_id = str(state.get("iteration_id") or "")
    foreign_entries = [
        entry for entry in all_entries
        if str(entry.get("iteration_id") or "") != iteration_id
    ]
    entries = [
        entry for entry in all_entries
        if str(entry.get("iteration_id") or "") == iteration_id
    ]

    violations: list[str] = []
    unknowns: list[str] = []
    evidence_violations: list[str] = []
    protocol_violations: list[str] = []
    test_contamination = False

    if str(hypothesis.get("iteration_id") or "") != iteration_id:
        protocol_violations.append("hypothesis.yaml iteration_id differs from canonical state")

    if not entries:
        evidence_violations.append("evidence_ledger.jsonl has no records")
    if foreign_entries:
        evidence_violations.append(
            f"evidence_ledger.jsonl contains {len(foreign_entries)} record(s) for another iteration"
        )

    protocol_path = cur / "protocol.lock.yaml"
    expected_digest = state.get("protocol_digest")
    actual_digest = sha256_file(protocol_path) if protocol_path.exists() else ""
    if protocol.get("locked") is not True:
        protocol_violations.append("protocol.lock.yaml is not locked")
    if expected_digest and actual_digest != expected_digest:
        protocol_violations.append("protocol.lock.yaml digest differs from compiled goal state")
    elif not expected_digest:
        unknowns.append("state.yaml has no protocol_digest; run arx_compile_goal.py")
    compiled_at = state.get("compiled_at")
    compiled_dt = parse_timestamp(compiled_at)
    if not compiled_at:
        unknowns.append("state.yaml has no compiled_at; run arx_compile_goal.py")
    elif compiled_dt is None:
        unknowns.append("state.yaml compiled_at is not a valid timestamp")

    allowed_splits = [str(x) for x in listify(protocol.get("allowed_splits"))]
    forbidden_splits = [str(x) for x in listify(protocol.get("forbidden_splits"))]
    expected_metrics = [str(x) for x in listify(protocol.get("expected_metrics"))]
    require_seed = protocol.get("require_seed") is True
    blocked = blocked_patterns(blocked)

    for index, entry in enumerate(entries, 1):
        command = str(entry.get("command") or "")
        data_split = str(entry.get("data_split") or "")
        metrics = entry.get("metrics") or {}
        if not command:
            evidence_violations.append(f"record {index} missing command")
        if str(entry.get("protocol_digest") or "") != str(expected_digest or ""):
            protocol_violations.append(f"record {index} protocol_digest differs from compiled state")
        entry_dt = parse_timestamp(entry.get("timestamp"))
        if compiled_dt and entry_dt and entry_dt < compiled_dt:
            protocol_violations.append(f"record {index} predates compiled protocol")
        elif compiled_dt and entry_dt is None:
            evidence_violations.append(f"record {index} missing valid timestamp")
        if require_seed and entry.get("seed") is None:
            evidence_violations.append(f"record {index} missing seed")
        if allowed_splits and data_split and data_split not in allowed_splits and data_split not in forbidden_splits:
            protocol_violations.append(f"record {index} uses split outside allowed_splits: {data_split}")
        for split in forbidden_splits:
            if data_split == split or command_mentions_split(command, split):
                test_contamination = True
                protocol_violations.append(f"record {index} touches forbidden split: {split}")
        for metric in expected_metrics:
            if metric not in metrics:
                evidence_violations.append(f"record {index} missing expected metric: {metric}")
        result_file = entry.get("result_file") or ""
        result_digest = entry.get("result_digest") or ""
        if result_file:
            path = Path(result_file)
            if not path.exists():
                evidence_violations.append(f"record {index} result_file missing: {result_file}")
            elif result_digest and sha256_file(path) != result_digest:
                evidence_violations.append(f"record {index} result_file digest changed: {result_file}")
        config_file = entry.get("config_file") or ""
        config_digest = entry.get("config_digest") or ""
        if config_file:
            path = Path(config_file)
            if not path.exists():
                evidence_violations.append(f"record {index} config_file missing: {config_file}")
            elif config_digest and sha256_file(path) != config_digest:
                evidence_violations.append(f"record {index} config_file digest changed: {config_file}")
        for action, reason, pattern in blocked:
            if pattern and contains_pattern(command, pattern):
                protocol_violations.append(f"record {index} ran blocked action {action}: {reason}")

    successful_entries = [
        entry for entry in entries
        if str(entry.get("status") or "").lower() not in {"fail", "error"}
        and int(entry.get("exit_code") or 0) == 0
    ]
    successful_experiments = [
        entry for entry in successful_entries
        if str(entry.get("role") or "experiment") != "baseline"
    ]
    gate_passed, gate_results, gate_unknowns = evaluate_gates(protocol, successful_experiments)
    unknowns.extend(gate_unknowns)
    baseline_status, baseline_blocks_promote, baseline_unknowns = evaluate_baseline(protocol, successful_entries)
    unknowns.extend(baseline_unknowns)

    violations.extend(evidence_violations)
    violations.extend(protocol_violations)
    evidence_valid = bool(entries) and not evidence_violations
    protocol_violation = bool(protocol_violations)

    review_path = cur / "ai_evidence_review.md"
    review_text = read_text(review_path) if review_path.exists() else ""
    claim_support_status, claim_blocks_promote, claim_unknowns = evaluate_claim_support(review_text, claim_boundary)
    unknowns.extend(claim_unknowns)
    research_status = evaluate_research_gates(root)
    verified_claim_status = evaluate_verified_claims(review_text, research_status, base=cur)
    research_blocks_promote = bool(research_status.get("blocks_promote"))
    verified_blocks_promote = verified_claim_status.get("status") == "fail"
    blocked_for_spiral = blocked_patterns(load_current_yaml(root, "blocked_actions.yaml"))
    spiral_budget = dict(protocol.get("spiral_budget") or {})
    if isinstance(protocol.get("loop_budget"), dict):
        spiral_budget.update(protocol["loop_budget"])
    spiral_risk = compute_spiral_risk(
        entries,
        blocked_for_spiral,
        spiral_budget,
        tracked_metric_keys(protocol),
    )
    loop_budget = budget_snapshot(root, state)
    if loop_budget.get("exhausted"):
        spiral_risk = dict(spiral_risk)
        spiral_risk["level"] = "critical"
        spiral_risk["signals"] = sorted(set(listify(spiral_risk.get("signals")) + [f"budget:{name}" for name in loop_budget["exhausted"]]))

    forbidden_decisions: list[str] = []
    if not evidence_valid or protocol_violation or test_contamination or not gate_passed:
        forbidden_decisions.append("promote")
    if baseline_blocks_promote:
        forbidden_decisions.append("promote")
    if claim_blocks_promote:
        forbidden_decisions.append("promote")
    if research_blocks_promote:
        forbidden_decisions.append("promote")
    if verified_blocks_promote:
        forbidden_decisions.append("promote")
    if spiral_risk.get("level") == "critical":
        forbidden_decisions.append("promote")
    # Promote always requires a same-session subagent review bound to the current audit.
    if not (cur / "subagent_review.yaml").exists():
        forbidden_decisions.append("promote")
        unknowns.append("subagent_review.yaml required before promote (run prepare-review + review subagent)")
    elif (cur / "audit_report.yaml").exists():
        review_errs = subagent_review_errors(
            root,
            required=True,
            audit_digest=sha256_file(cur / "audit_report.yaml"),
        )
        if review_errs:
            forbidden_decisions.append("promote")
            unknowns.extend(review_errs)
    forbidden_decisions = sorted(set(forbidden_decisions))

    input_digests_after = audit_input_digests(root)
    if input_digests_after != input_digests_before:
        changed = sorted(
            name
            for name in set(input_digests_before) | set(input_digests_after)
            if input_digests_before.get(name) != input_digests_after.get(name)
        )
        raise ArxError("audit inputs changed while the snapshot was evaluated: " + ", ".join(changed))

    report = {
        "audit_version": 3,
        "timestamp": utc_now(),
        "iteration_id": iteration_id,
        "evidence_valid": evidence_valid,
        "protocol_violation": protocol_violation,
        "test_contamination": test_contamination,
        "validation_gate_passed": gate_passed,
        "baseline_status": baseline_status,
        "claim_support_status": claim_support_status,
        "research_gate_status": dump_research_gate_yaml(research_status),
        "verified_claim_status": verified_claim_status,
        "spiral_risk": spiral_risk,
        "forbidden_decisions": forbidden_decisions,
        "gate_results": gate_results,
        "violations": violations,
        "unknowns": unknowns,
        "evidence_records": len(entries),
        "protocol_digest": actual_digest,
        "input_digests": input_digests_before,
        "loop_budget": loop_budget,
    }
    audit_path = cur / "audit_report.yaml"
    write_yaml(audit_path, report)
    if audit_input_digests(root) != input_digests_before:
        audit_path.unlink(missing_ok=True)
        raise ArxError("audit inputs changed while audit_report.yaml was being committed; rerun audit")
    mark_review(root, audit_digest=sha256_file(audit_path))
    print(f"Audit wrote {cur / 'audit_report.yaml'}")
    print(f"evidence_valid={evidence_valid} protocol_violation={protocol_violation} validation_gate_passed={gate_passed} spiral_risk={spiral_risk.get('level')}")
    if violations:
        print("violations:")
        for violation in violations:
            print(f"- {violation}")
    return 0 if evidence_valid and not protocol_violation else 1


def audit_current(research_root: str | Path) -> int:
    root = Path(research_root).resolve()
    cur = current_dir(root)
    with research_lock(root):
        return run_audit(root, cur)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic audit for current research evidence.")
    add_common_args(parser)
    args = parser.parse_args()

    return audit_current(args.research_root)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")
