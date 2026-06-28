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
    read_text,
    sha256_file,
    utc_now,
    write_yaml,
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
    review_text: str,
    blocked: list[tuple[str, str, str]],
    budget: dict[str, Any],
) -> dict[str, Any]:
    max_failed = int(budget.get("max_failed_attempts") or 3)
    max_flat = int(budget.get("max_flatline_count") or 3)

    failed = sum(
        1 for e in entries
        if str(e.get("status") or "") == "fail" or int(e.get("exit_code") or 0) != 0
    )

    flatline_count = 0
    by_metric: dict[str, list[float]] = {}
    for e in entries:
        metrics = e.get("metrics") or {}
        for name, value in metrics.items():
            if isinstance(value, (int, float)):
                by_metric.setdefault(str(name), []).append(float(value))
    for values in by_metric.values():
        if len(values) >= max_flat:
            flat = all(abs(values[i] - values[i - 1]) < 1e-9 for i in range(1, len(values)))
            if flat:
                flatline_count = max(flatline_count, len(values))

    no_signal_streak = review_text.lower().count("no_signal")

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic audit for current research evidence.")
    add_common_args(parser)
    args = parser.parse_args()

    root = Path(args.research_root).resolve()
    cur = current_dir(root)
    if not cur.exists():
        raise ArxError(f"missing current directory: {cur}")

    state = load_current_yaml(root, "state.yaml")
    protocol = load_current_yaml(root, "protocol.lock.yaml")
    blocked = load_current_yaml(root, "blocked_actions.yaml")
    hypothesis = load_current_yaml(root, "hypothesis.yaml")
    entries = load_jsonl(cur / "evidence_ledger.jsonl")

    checks: list[dict[str, Any]] = []
    violations: list[str] = []
    unknowns: list[str] = []
    evidence_violations: list[str] = []
    protocol_violations: list[str] = []
    test_contamination = False

    if not entries:
        evidence_violations.append("evidence_ledger.jsonl has no records")

    protocol_path = cur / "protocol.lock.yaml"
    expected_digest = state.get("protocol_digest")
    actual_digest = sha256_file(protocol_path) if protocol_path.exists() else ""
    if expected_digest and actual_digest != expected_digest:
        protocol_violations.append("protocol.lock.yaml digest differs from compiled goal state")
    elif not expected_digest:
        unknowns.append("state.yaml has no protocol_digest; run arx_compile_goal.py")

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

    gate_passed, gate_results, gate_unknowns = evaluate_gates(protocol, entries)
    unknowns.extend(gate_unknowns)

    violations.extend(evidence_violations)
    violations.extend(protocol_violations)
    evidence_valid = bool(entries) and not evidence_violations
    protocol_violation = bool(protocol_violations)

    review_path = cur / "ai_evidence_review.md"
    review_text = read_text(review_path) if review_path.exists() else ""
    blocked_for_spiral = blocked_patterns(load_current_yaml(root, "blocked_actions.yaml"))
    spiral_budget = protocol.get("spiral_budget") or {}
    spiral_risk = compute_spiral_risk(entries, review_text, blocked_for_spiral, spiral_budget)

    forbidden_decisions: list[str] = []
    if not evidence_valid or protocol_violation or test_contamination or not gate_passed:
        forbidden_decisions.append("promote")
    if spiral_risk.get("level") == "critical":
        forbidden_decisions.append("promote")

    report = {
        "audit_version": 1,
        "timestamp": utc_now(),
        "iteration_id": hypothesis.get("iteration_id", state.get("iteration_id", "")),
        "evidence_valid": evidence_valid,
        "protocol_violation": protocol_violation,
        "test_contamination": test_contamination,
        "validation_gate_passed": gate_passed,
        "spiral_risk": spiral_risk,
        "forbidden_decisions": forbidden_decisions,
        "checks": checks,
        "gate_results": gate_results,
        "violations": violations,
        "unknowns": unknowns,
        "evidence_records": len(entries),
        "protocol_digest": actual_digest,
    }
    write_yaml(cur / "audit_report.yaml", report)
    print(f"Audit wrote {cur / 'audit_report.yaml'}")
    print(f"evidence_valid={evidence_valid} protocol_violation={protocol_violation} validation_gate_passed={gate_passed} spiral_risk={spiral_risk.get('level')}")
    if violations:
        print("violations:")
        for violation in violations:
            print(f"- {violation}")
    return 0 if evidence_valid and not protocol_violation else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")