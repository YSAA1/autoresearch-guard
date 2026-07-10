from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from arx_common import (
    ArxError,
    DECISIONS,
    archive_dir,
    append_jsonl,
    current_dir,
    listify,
    load_current_yaml,
    load_jsonl,
    load_yaml,
    parse_timestamp,
    read_text,
    research_lock,
    sha256_file,
    slug,
    utc_now,
    write_yaml,
)

STATE_VERSION = 2
PHASES = {"draft", "execution", "review", "closure", "archived"}
LOOP_STATUSES = {"idle", "armed", "running", "closing", "waiting_human", "aborted", "complete"}
CONTINUING_DECISIONS = {"proceed", "refine", "pivot"}

DEFAULT_LOOP_BUDGET = {
    "max_turns": 20,
    "max_attempts": 12,
    "max_consecutive_failures": 3,
    "max_flatline_count": 3,
    "max_no_progress_turns": 2,
    "max_stop_continuations": 1,
    "max_wall_time_minutes": 240,
}

AUDIT_INPUT_FILES = {
    "protocol": "protocol.lock.yaml",
    "hypothesis": "hypothesis.yaml",
    "blocked_actions": "blocked_actions.yaml",
    "claim_boundary": "claim_boundary.yaml",
    "evidence_ledger": "evidence_ledger.jsonl",
    "ai_evidence_review": "ai_evidence_review.md",
}

SNAPSHOT_FILES = {
    **AUDIT_INPUT_FILES,
    "active_goal": "active_goal.md",
    "audit_report": "audit_report.yaml",
    "decision_proposed": "decision.proposed.yaml",
    "decision": "decision.yaml",
    "next_goal": "next_goal.md",
}


def _file_digest(path: Path) -> str:
    return sha256_file(path) if path.exists() and path.is_file() else ""


def _state_digest(state: dict[str, Any]) -> str:
    encoded = json.dumps(
        state,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_loop() -> dict[str, Any]:
    return {
        "status": "idle",
        "owner_session_id": "",
        "started_at": "",
        "pause_reason": "",
        "resume_phase": "",
        "human_approved_at": "",
        "human_approved_audit_digest": "",
        "turns_seen": 0,
        "stop_continuations": 0,
        "no_progress_turns": 0,
        "last_turn_id": "",
        "last_progress_digest": "",
        "runtime_revision": 0,
        "recent_tool_use_ids": [],
        "budget": dict(DEFAULT_LOOP_BUDGET),
    }


def _normalize_state(root: Path, state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = dict(state)
    changed = False
    legacy_state = int(normalized.get("version") or 1) < STATE_VERSION
    if legacy_state:
        normalized["version"] = STATE_VERSION
        changed = True
    phase = str(normalized.get("phase") or "")
    if phase not in PHASES:
        cur = current_dir(root)
        if (cur / "decision.yaml").exists() or (cur / "audit_report.yaml").exists():
            # Legacy audit/decision files do not carry the v2 digest bundle.
            # Re-enter review so they can be rebuilt instead of treating them
            # as a valid closure.
            phase = "review"
        elif (cur / "active_goal.md").exists():
            phase = "execution"
        else:
            phase = "draft"
        normalized["phase"] = phase
        changed = True
    if not isinstance(normalized.get("revision"), int):
        normalized["revision"] = 0
        changed = True
    loop = normalized.get("loop")
    if not isinstance(loop, dict):
        loop = {}
        changed = True
    original_status = str(loop.get("status") or "")
    merged = _default_loop()
    merged.update(loop)
    if original_status not in LOOP_STATUSES or (legacy_state and phase != "draft" and original_status == "idle"):
        if phase == "execution":
            merged["status"] = "armed"
        elif phase in {"review", "closure"}:
            merged["status"] = "closing"
        elif phase == "archived":
            merged["status"] = "complete"
        else:
            merged["status"] = "idle"
    budget = merged.get("budget")
    if not isinstance(budget, dict):
        budget = {}
    merged_budget = dict(DEFAULT_LOOP_BUDGET)
    merged_budget.update(budget)
    merged["budget"] = merged_budget
    for key in ("turns_seen", "stop_continuations", "no_progress_turns", "runtime_revision"):
        try:
            merged[key] = int(merged.get(key) or 0)
        except (TypeError, ValueError):
            merged[key] = 0
    if not isinstance(merged.get("recent_tool_use_ids"), list):
        merged["recent_tool_use_ids"] = []
    if merged != loop:
        normalized["loop"] = merged
        changed = True
    if not isinstance(normalized.get("decision_digest"), str):
        normalized["decision_digest"] = ""
        changed = True
    elif "decision_digest" not in normalized:
        normalized["decision_digest"] = ""
        changed = True
    if not isinstance(normalized.get("audit_digest"), str):
        normalized["audit_digest"] = ""
        changed = True
    elif "audit_digest" not in normalized:
        normalized["audit_digest"] = ""
        changed = True
    return normalized, changed


def load_lifecycle_state(research_root: str | Path, *, persist_migration: bool = True) -> dict[str, Any]:
    root = Path(research_root).resolve()
    with research_lock(root):
        path = current_dir(root) / "state.yaml"
        if not path.exists():
            raise ArxError(f"missing lifecycle state: {path}")
        state = load_yaml(path)
        state, changed = _normalize_state(root, state)
        if changed and persist_migration:
            state["updated_at"] = utc_now()
            write_yaml(path, state)
        return state


def _write_state(root: Path, state: dict[str, Any], *, runtime_only: bool = False) -> dict[str, Any]:
    if runtime_only:
        loop = state.setdefault("loop", {})
        loop["runtime_revision"] = int(loop.get("runtime_revision") or 0) + 1
    else:
        state["revision"] = int(state.get("revision") or 0) + 1
    state["updated_at"] = utc_now()
    write_yaml(current_dir(root) / "state.yaml", state)
    return state


def record_event(
    research_root: str | Path,
    event: str,
    *,
    details: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> None:
    root = Path(research_root).resolve()
    with research_lock(root):
        state = state or load_lifecycle_state(root)
        append_jsonl(
            current_dir(root) / "events.jsonl",
            {
                "event_id": uuid.uuid4().hex,
                "timestamp": utc_now(),
                "event": event,
                "iteration_id": state.get("iteration_id", ""),
                "revision": state.get("revision", 0),
                "details": details or {},
            },
        )


def require_phase(research_root: str | Path, operation: str, allowed: set[str]) -> dict[str, Any]:
    state = load_lifecycle_state(research_root)
    phase = str(state.get("phase") or "")
    if phase not in allowed:
        raise ArxError(f"{operation} is not allowed in phase {phase}; expected one of {sorted(allowed)}")
    status = str((state.get("loop") or {}).get("status") or "")
    if status in {"aborted", "complete"}:
        raise ArxError(f"{operation} is not allowed while loop status is {status}")
    return state


def transition(
    research_root: str | Path,
    *,
    operation: str,
    allowed_phases: set[str],
    phase: str | None = None,
    status: str | None = None,
    reason: str = "",
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(research_root).resolve()
    with research_lock(root):
        state = require_phase(root, operation, allowed_phases)
        if phase is not None:
            if phase not in PHASES:
                raise ArxError(f"invalid lifecycle phase: {phase}")
            state["phase"] = phase
        loop = state.setdefault("loop", _default_loop())
        if status is not None:
            if status not in LOOP_STATUSES:
                raise ArxError(f"invalid loop status: {status}")
            loop["status"] = status
        for key, value in (updates or {}).items():
            if key.startswith("loop."):
                loop[key.split(".", 1)[1]] = value
            else:
                state[key] = value
        _write_state(root, state)
        record_event(root, f"transition.{operation}", details={"phase": state["phase"], "status": loop["status"], "reason": reason}, state=state)
        return state


def loop_budget_from_protocol(protocol: dict[str, Any]) -> dict[str, int]:
    configured = protocol.get("loop_budget") or {}
    if not isinstance(configured, dict):
        raise ArxError("protocol.lock.yaml loop_budget must be a mapping")
    legacy = protocol.get("spiral_budget") or {}
    if not isinstance(legacy, dict):
        legacy = {}
    merged: dict[str, Any] = dict(DEFAULT_LOOP_BUDGET)
    merged.update({key: value for key, value in legacy.items() if key in merged})
    if "max_failed_attempts" in legacy and "max_consecutive_failures" not in configured:
        merged["max_consecutive_failures"] = legacy["max_failed_attempts"]
    if "max_total_attempts" in legacy and "max_attempts" not in configured:
        merged["max_attempts"] = legacy["max_total_attempts"]
    merged.update(configured)
    result: dict[str, int] = {}
    for key, default in DEFAULT_LOOP_BUDGET.items():
        value = merged.get(key, default)
        if isinstance(value, bool):
            raise ArxError(f"loop_budget.{key} must be a positive integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ArxError(f"loop_budget.{key} must be a positive integer") from exc
        if parsed <= 0:
            raise ArxError(f"loop_budget.{key} must be greater than zero")
        result[key] = parsed
    return result


def configure_execution(
    research_root: str | Path,
    *,
    protocol_digest: str,
    compiled_at: str,
    protocol: dict[str, Any],
) -> dict[str, Any]:
    budget = loop_budget_from_protocol(protocol)
    return transition(
        research_root,
        operation="compile",
        allowed_phases={"draft"},
        phase="execution",
        status="armed",
        updates={
            "protocol_digest": protocol_digest,
            "audit_digest": "",
            "compiled_at": compiled_at,
            "decision_digest": "",
            "loop.owner_session_id": "",
            "loop.started_at": compiled_at,
            "loop.pause_reason": "",
            "loop.resume_phase": "",
            "loop.human_approved_at": "",
            "loop.human_approved_audit_digest": "",
            "loop.turns_seen": 0,
            "loop.stop_continuations": 0,
            "loop.no_progress_turns": 0,
            "loop.last_turn_id": "",
            "loop.last_progress_digest": "",
            "loop.budget": budget,
        },
    )


def claim_session(research_root: str | Path, session_id: str, *, reason: str) -> dict[str, Any]:
    if not session_id:
        return load_lifecycle_state(research_root)
    root = Path(research_root).resolve()
    with research_lock(root):
        state = require_phase(root, "claim-session", {"execution", "review", "closure"})
        loop = state.setdefault("loop", _default_loop())
        status = str(loop.get("status") or "")
        if status not in {"armed", "running", "closing"}:
            raise ArxError(f"session claim is not allowed while loop status is {status}")
        owner = str(loop.get("owner_session_id") or "")
        if owner and owner != session_id:
            raise ArxError(f"research iteration is owned by another session: {owner}")
        if owner == session_id:
            return state
        loop["owner_session_id"] = session_id
        loop["status"] = "running" if state.get("phase") == "execution" else "closing"
        if not loop.get("started_at"):
            loop["started_at"] = utc_now()
        _write_state(root, state)
        record_event(root, "loop.session_claimed", details={"session_id": session_id, "reason": reason}, state=state)
        return state


def mark_review(research_root: str | Path, *, audit_digest: str) -> dict[str, Any]:
    state = load_lifecycle_state(research_root)
    owner = str((state.get("loop") or {}).get("owner_session_id") or "")
    return transition(
        research_root,
        operation="audit",
        allowed_phases={"execution", "review"},
        phase="review",
        status="closing",
        updates={"loop.owner_session_id": owner, "audit_digest": audit_digest, "decision_digest": ""},
    )


def mark_closure(research_root: str | Path, *, decision_digest: str) -> dict[str, Any]:
    state = load_lifecycle_state(research_root)
    owner = str((state.get("loop") or {}).get("owner_session_id") or "")
    return transition(
        research_root,
        operation="decide",
        allowed_phases={"review"},
        phase="closure",
        status="closing",
        updates={"loop.owner_session_id": owner, "decision_digest": decision_digest},
    )


def pause_loop(research_root: str | Path, reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise ArxError("pause requires a non-empty reason")
    state = load_lifecycle_state(research_root)
    return transition(
        research_root,
        operation="pause",
        allowed_phases={"execution", "review", "closure"},
        status="waiting_human",
        reason=reason,
        updates={"loop.pause_reason": reason, "loop.resume_phase": state.get("phase", ""), "loop.owner_session_id": ""},
    )


def resume_loop(
    research_root: str | Path,
    reason: str,
    *,
    human_approved: bool = False,
    reopen_execution: bool = False,
) -> dict[str, Any]:
    if not reason.strip():
        raise ArxError("resume requires a non-empty reason")
    root = Path(research_root).resolve()
    with research_lock(root):
        state = load_lifecycle_state(root)
        loop = state.setdefault("loop", _default_loop())
        if str(loop.get("status") or "") not in {"waiting_human", "armed", "closing"}:
            raise ArxError(f"resume is not allowed while loop status is {loop.get('status')}")
        phase = str(state.get("phase") or "")
        approved_audit_digest = ""
        if human_approved:
            if str(loop.get("status") or "") != "waiting_human" or phase != "review":
                raise ArxError("--human-approved requires an explicit pause in review phase")
            audit = load_current_yaml(root, "audit_report.yaml")
            fresh, stale_inputs = audit_is_fresh(root, audit)
            if not fresh:
                raise ArxError(
                    "--human-approved requires a fresh audit; stale for: " + ", ".join(stale_inputs)
                )
            approved_audit_digest = _file_digest(current_dir(root) / "audit_report.yaml")
        if reopen_execution and phase == "review":
            state["phase"] = "execution"
            phase = "execution"
        loop["status"] = "armed" if phase == "execution" else "closing"
        loop["owner_session_id"] = ""
        loop["pause_reason"] = ""
        loop["no_progress_turns"] = 0
        loop["last_turn_id"] = ""
        loop["last_progress_digest"] = ""
        loop["human_approved_at"] = ""
        loop["human_approved_audit_digest"] = ""
        if human_approved:
            loop["human_approved_at"] = utc_now()
            loop["human_approved_audit_digest"] = approved_audit_digest
        _write_state(root, state)
        record_event(
            root,
            "transition.resume",
            details={"reason": reason, "human_approved": human_approved, "reopen_execution": reopen_execution},
            state=state,
        )
        return state


def abort_loop(research_root: str | Path, reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise ArxError("abort requires a non-empty reason")
    return transition(
        research_root,
        operation="abort",
        allowed_phases={"draft", "execution", "review", "closure"},
        status="aborted",
        reason=reason,
        updates={"loop.pause_reason": reason, "loop.owner_session_id": ""},
    )


def trip_budget_circuit_breaker(research_root: str | Path, reasons: list[str]) -> dict[str, Any]:
    if not reasons:
        return load_lifecycle_state(research_root)
    root = Path(research_root).resolve()
    with research_lock(root):
        state = load_lifecycle_state(root)
        loop = state.setdefault("loop", _default_loop())
        status = str(loop.get("status") or "")
        if status in {"waiting_human", "aborted", "complete", "idle"}:
            return state
        reason = "AutoResearch Guard paused the loop: " + ", ".join(reasons)
        loop["status"] = "waiting_human"
        loop["pause_reason"] = reason
        loop["resume_phase"] = state.get("phase", "")
        loop["owner_session_id"] = ""
        _write_state(root, state, runtime_only=True)
        record_event(root, "loop.circuit_breaker", details={"reasons": reasons}, state=state)
        return state


def audit_input_digests(research_root: str | Path) -> dict[str, str]:
    cur = current_dir(research_root)
    return {name: _file_digest(cur / filename) for name, filename in AUDIT_INPUT_FILES.items()}


def snapshot_digests(research_root: str | Path) -> dict[str, str]:
    root = Path(research_root).resolve()
    cur = current_dir(root)
    digests = {name: _file_digest(cur / filename) for name, filename in SNAPSHOT_FILES.items()}
    digests["retained_lessons"] = _file_digest(root / "lessons" / "retained_lessons.md")
    digests["anti_patterns"] = _file_digest(root / "lessons" / "anti_patterns.yaml")
    return digests


def progress_digest(research_root: str | Path) -> str:
    payload = json.dumps(snapshot_digests(research_root), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit_is_fresh(research_root: str | Path, audit: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    root = Path(research_root).resolve()
    audit = audit or load_current_yaml(root, "audit_report.yaml")
    expected = audit.get("input_digests") if isinstance(audit, dict) else None
    if not isinstance(expected, dict):
        return False, ["audit_report.yaml has no input_digests"]
    stale: list[str] = []
    try:
        version = int(audit.get("audit_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version != 2:
        stale.append("audit_version")
    state = load_lifecycle_state(root)
    audit_digest = _file_digest(current_dir(root) / "audit_report.yaml")
    if str(state.get("audit_digest") or "") != audit_digest:
        stale.append("audit_digest")
    if str(audit.get("iteration_id") or "") != str(state.get("iteration_id") or ""):
        stale.append("iteration_id")
    actual = audit_input_digests(root)
    stale.extend(name for name, digest in actual.items() if str(expected.get(name) or "") != digest)
    return not stale, stale


def decision_policy_errors(
    audit: dict[str, Any],
    proposal: dict[str, Any],
    state: dict[str, Any],
    *,
    audit_digest: str,
) -> list[str]:
    errors: list[str] = []
    decision = str(proposal.get("decision") or "")
    if decision not in DECISIONS:
        errors.append(f"invalid decision: {decision or '<missing>'}")
    if not str(proposal.get("reason") or "").strip():
        errors.append("decision reason is missing")
    forbidden = {str(item) for item in listify(audit.get("forbidden_decisions"))}
    if decision in forbidden:
        errors.append(f"decision {decision} is forbidden by the current audit")

    spiral = audit.get("spiral_risk") or {}
    spiral_level = str(spiral.get("level") or "none") if isinstance(spiral, dict) else "none"
    if spiral_level == "critical":
        if not str(proposal.get("spiral_response") or "").strip():
            errors.append("critical spiral requires a non-empty spiral_response")
        if decision == "proceed":
            loop = state.get("loop") or {}
            if proposal.get("requires_human") is not True:
                errors.append("critical proceed requires requires_human: true")
            if str(loop.get("human_approved_audit_digest") or "") != audit_digest:
                errors.append("critical proceed requires human approval bound to the current audit")
    return errors


def committed_decision_errors(
    research_root: str | Path,
    state: dict[str, Any],
    audit: dict[str, Any],
    decision: dict[str, Any],
) -> list[str]:
    root = Path(research_root).resolve()
    audit_digest = _file_digest(current_dir(root) / "audit_report.yaml")
    errors = decision_policy_errors(audit, decision, state, audit_digest=audit_digest)
    if not decision:
        return errors
    if parse_timestamp(decision.get("committed_at")) is None:
        errors.append("decision committed_at is missing or invalid")
    if str(decision.get("audit_digest") or "") != audit_digest:
        errors.append("decision audit_digest does not match the current audit")
    if decision.get("input_digests") != audit.get("input_digests"):
        errors.append("decision input_digests do not match the current audit")
    decision_digest = _file_digest(current_dir(root) / "decision.yaml")
    if str(state.get("decision_digest") or "") != decision_digest:
        errors.append("decision.yaml changed after it was committed")
    return list(dict.fromkeys(errors))


def _meaningful(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    text = read_text(path).strip()
    return bool(text) and "TBD by AI" not in text


def _entry_failed(entry: dict[str, Any]) -> bool:
    status = str(entry.get("status") or "").lower()
    try:
        exit_code = int(entry.get("exit_code") or 0)
    except (TypeError, ValueError):
        exit_code = 1
    return status in {"fail", "error"} or exit_code != 0


def _entries_for_iteration(root: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    entries = load_jsonl(current_dir(root) / "evidence_ledger.jsonl")
    iteration_id = str(state.get("iteration_id") or "")
    return [entry for entry in entries if str(entry.get("iteration_id") or "") == iteration_id]


def _lessons_record_iteration(root: Path, iteration_id: str) -> bool:
    anti = load_yaml(root / "lessons" / "anti_patterns.yaml")
    for item in listify(anti.get("anti_patterns")):
        if isinstance(item, dict) and str(item.get("iteration_id") or "") == iteration_id:
            return True
    return False


def tracked_metric_keys(protocol: dict[str, Any]) -> set[tuple[str, str]]:
    keys = {
        (str(gate.get("metric") or "").strip(), str(gate.get("split") or "validation").strip())
        for gate in listify(protocol.get("validation_gates"))
        if isinstance(gate, dict) and str(gate.get("metric") or "").strip()
    }
    if keys:
        return keys
    metrics = {str(item).strip() for item in listify(protocol.get("expected_metrics")) if str(item).strip()}
    splits = {str(item).strip() for item in listify(protocol.get("allowed_splits")) if str(item).strip()}
    if not splits:
        splits = {"validation"}
    return {(metric, split) for metric in metrics for split in splits}


def budget_snapshot(research_root: str | Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(research_root).resolve()
    state = state or load_lifecycle_state(root)
    loop = state.get("loop") or {}
    budget = dict(DEFAULT_LOOP_BUDGET)
    if isinstance(loop.get("budget"), dict):
        budget.update(loop["budget"])
    entries = [entry for entry in _entries_for_iteration(root, state) if str(entry.get("role") or "experiment") != "baseline"]
    attempts = len(entries)
    consecutive_failures = 0
    for entry in reversed(entries):
        if _entry_failed(entry):
            consecutive_failures += 1
        else:
            break
    flatline_count = 0
    protocol = load_current_yaml(root, "protocol.lock.yaml")
    tracked_metrics = tracked_metric_keys(protocol)
    metric_series: dict[tuple[str, str], list[float]] = {}
    for entry in entries:
        if _entry_failed(entry):
            continue
        for name, value in (entry.get("metrics") or {}).items():
            metric_name = str(name)
            metric_key = (metric_name, str(entry.get("data_split") or ""))
            if isinstance(value, (int, float)) and (not tracked_metrics or metric_key in tracked_metrics):
                metric_series.setdefault(metric_key, []).append(float(value))
    for values in metric_series.values():
        if not values:
            continue
        tail = 1
        for index in range(len(values) - 1, 0, -1):
            if abs(values[index] - values[index - 1]) < 1e-9:
                tail += 1
            else:
                break
        flatline_count = max(flatline_count, tail)
    turns = int(loop.get("turns_seen") or 0)
    no_progress = int(loop.get("no_progress_turns") or 0)
    elapsed_minutes = 0.0
    started = parse_timestamp(loop.get("started_at") or state.get("compiled_at"))
    if started is not None:
        elapsed_minutes = max(0.0, (dt.datetime.now(dt.timezone.utc) - started).total_seconds() / 60.0)
    exhausted: list[str] = []
    if attempts >= int(budget["max_attempts"]):
        exhausted.append("max_attempts")
    if consecutive_failures >= int(budget["max_consecutive_failures"]):
        exhausted.append("max_consecutive_failures")
    if flatline_count >= int(budget["max_flatline_count"]):
        exhausted.append("max_flatline_count")
    if turns >= int(budget["max_turns"]):
        exhausted.append("max_turns")
    if no_progress >= int(budget["max_no_progress_turns"]):
        exhausted.append("max_no_progress_turns")
    if elapsed_minutes >= int(budget["max_wall_time_minutes"]):
        exhausted.append("max_wall_time_minutes")
    return {
        "configured": budget,
        "used": {
            "attempts": attempts,
            "consecutive_failures": consecutive_failures,
            "flatline_count": flatline_count,
            "turns": turns,
            "no_progress_turns": no_progress,
            "wall_time_minutes": round(elapsed_minutes, 3),
            "stop_continuations": int(loop.get("stop_continuations") or 0),
        },
        "remaining": {
            "attempts": max(0, int(budget["max_attempts"]) - attempts),
            "turns": max(0, int(budget["max_turns"]) - turns),
            "no_progress_turns": max(0, int(budget["max_no_progress_turns"]) - no_progress),
            "stop_continuations": max(0, int(budget["max_stop_continuations"]) - int(loop.get("stop_continuations") or 0)),
        },
        "exhausted": exhausted,
    }


def evaluate_readiness(research_root: str | Path) -> dict[str, Any]:
    root = Path(research_root).resolve()
    with research_lock(root):
        state = load_lifecycle_state(root)
        cur = current_dir(root)
        loop = state.get("loop") or {}
        status = str(loop.get("status") or "")
        reasons: list[str] = []
        missing: list[str] = []
        stale: list[str] = []
        next_actions: list[str] = []

        if status == "waiting_human":
            reasons.append(str(loop.get("pause_reason") or "loop is waiting for human input"))
        if status == "aborted":
            reasons.append(str(loop.get("pause_reason") or "loop was aborted"))
        if state.get("phase") != "closure":
            reasons.append(f"phase is {state.get('phase')}, not closure")

        for name in ("evidence_ledger.jsonl", "audit_report.yaml", "ai_evidence_review.md", "decision.yaml"):
            if not _meaningful(cur / name):
                missing.append(name)
        entries = _entries_for_iteration(root, state)
        if not entries and "evidence_ledger.jsonl" not in missing:
            missing.append("evidence_ledger.jsonl")
        all_entries = load_jsonl(cur / "evidence_ledger.jsonl")
        if len(all_entries) != len(entries):
            reasons.append("evidence ledger contains records for another iteration")

        hypothesis = load_current_yaml(root, "hypothesis.yaml")
        if str(hypothesis.get("iteration_id") or "") != str(state.get("iteration_id") or ""):
            reasons.append("hypothesis iteration_id does not match canonical state")

        protocol = load_current_yaml(root, "protocol.lock.yaml")
        if protocol.get("locked") is not True:
            reasons.append("protocol is not locked")
        protocol_path = cur / "protocol.lock.yaml"
        if not protocol_path.exists() or str(state.get("protocol_digest") or "") != _file_digest(protocol_path):
            stale.append("protocol_digest")

        audit = load_current_yaml(root, "audit_report.yaml")
        fresh_audit, stale_inputs = audit_is_fresh(root, audit)
        if not fresh_audit:
            stale.extend(f"audit:{name}" for name in stale_inputs)

        decision = load_current_yaml(root, "decision.yaml")
        decision_name = str(decision.get("decision") or "")
        if decision:
            reasons.extend(
                f"decision: {error}"
                for error in committed_decision_errors(root, state, audit, decision)
            )

        iteration_id = str(state.get("iteration_id") or "")
        if any(_entry_failed(entry) for entry in entries) and not _lessons_record_iteration(root, iteration_id):
            missing.append("lessons/anti_patterns.yaml iteration entry")
        if decision_name in CONTINUING_DECISIONS and not _meaningful(cur / "next_goal.md"):
            missing.append("next_goal.md")

        missing = sorted(set(missing))
        stale = sorted(set(stale))
        reasons.extend(f"missing: {item}" for item in missing)
        reasons.extend(f"stale: {item}" for item in stale)
        if missing:
            next_actions.append("补齐缺失 closure 产物，然后重新运行 arx_audit.py")
        if stale:
            next_actions.append("重新运行 arx_audit.py，并重新提交 arx_decide.py")
        if state.get("phase") in {"draft", "execution"}:
            next_actions.append("完成 evidence 后运行 arx_audit.py")
        elif state.get("phase") == "review":
            next_actions.append("填写 ai_evidence_review.md，重新 audit，再运行 arx_decide.py")

        budget = budget_snapshot(root, state)
        ready = not reasons and not missing and not stale and decision_name in DECISIONS
        if ready:
            outcome = "achieved"
        elif budget["exhausted"]:
            progress_breakers = {
                "max_consecutive_failures",
                "max_flatline_count",
                "max_no_progress_turns",
            }
            exhausted = set(budget["exhausted"])
            outcome = "no_progress" if exhausted <= progress_breakers else "budget_exhausted"
            next_actions.insert(0, "预算或无进展熔断已触发；停止自动续跑并请求人工决定")
        elif status == "waiting_human":
            outcome = "blocked_requires_human"
        elif status == "aborted":
            outcome = "aborted"
        else:
            outcome = "incomplete"
        return {
            "ready": ready,
            "outcome": outcome,
            "phase": state.get("phase"),
            "status": status,
            "owner_session_id": str(loop.get("owner_session_id") or ""),
            "iteration_id": state.get("iteration_id"),
            "revision": state.get("revision"),
            "state_digest": _state_digest(state),
            "reasons": reasons,
            "missing": missing,
            "stale": stale,
            "next_actions": list(dict.fromkeys(next_actions)),
            "budget": budget,
            "requires_human": status == "waiting_human" or outcome in {"budget_exhausted", "no_progress"},
        }


def remember_tool_use(research_root: str | Path, tool_use_id: str) -> bool:
    if not tool_use_id:
        return True
    root = Path(research_root).resolve()
    with research_lock(root):
        state = load_lifecycle_state(root)
        loop = state.setdefault("loop", _default_loop())
        recent = [str(item) for item in listify(loop.get("recent_tool_use_ids"))]
        if tool_use_id in recent:
            return False
        recent.append(tool_use_id)
        loop["recent_tool_use_ids"] = recent[-32:]
        _write_state(root, state, runtime_only=True)
        return True


def observe_stop(research_root: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    root = Path(research_root).resolve()
    with research_lock(root):
        state = load_lifecycle_state(root)
        loop = state.setdefault("loop", _default_loop())
        readiness = evaluate_readiness(root)
        session_id = str(event.get("session_id") or "")
        owner = str(loop.get("owner_session_id") or "")
        status = str(loop.get("status") or "")

        if readiness["ready"]:
            return {"action": "allow", "readiness": readiness, "reason": "closure achieved"}
        if status in {"idle", "armed", "waiting_human", "aborted", "complete"}:
            return {"action": "allow", "readiness": readiness, "reason": f"loop status is {status}"}
        if not owner or not session_id or owner != session_id:
            return {"action": "allow", "readiness": readiness, "reason": "Stop event does not own this research loop"}
        if event.get("is_background_task") is True or listify(event.get("background_tasks")) or listify(event.get("session_crons")):
            return {"action": "allow", "readiness": readiness, "reason": "session has background work or scheduled wakeups"}

        turn_id = str(event.get("turn_id") or event.get("prompt_id") or "")
        digest = progress_digest(root)
        if turn_id and turn_id != str(loop.get("last_turn_id") or ""):
            loop["turns_seen"] = int(loop.get("turns_seen") or 0) + 1
            previous = str(loop.get("last_progress_digest") or "")
            if previous and previous == digest:
                loop["no_progress_turns"] = int(loop.get("no_progress_turns") or 0) + 1
            else:
                loop["no_progress_turns"] = 0
            loop["last_turn_id"] = turn_id
            loop["last_progress_digest"] = digest

        budget = budget_snapshot(root, state)
        if budget["exhausted"]:
            reason = "AutoResearch Guard paused the loop: " + ", ".join(budget["exhausted"])
            loop["status"] = "waiting_human"
            loop["pause_reason"] = reason
            loop["resume_phase"] = state.get("phase", "")
            loop["owner_session_id"] = ""
            _write_state(root, state, runtime_only=True)
            record_event(root, "loop.circuit_breaker", details={"reasons": budget["exhausted"]}, state=state)
            readiness = evaluate_readiness(root)
            return {"action": "halt", "readiness": readiness, "reason": reason}

        if event.get("stop_hook_active") is True:
            _write_state(root, state, runtime_only=True)
            record_event(root, "hook.stop_reentry_allowed", details={"turn_id": turn_id}, state=state)
            return {"action": "allow", "readiness": readiness, "reason": "Stop hook continuation is already active"}

        maximum = int((loop.get("budget") or {}).get("max_stop_continuations") or 1)
        if int(loop.get("stop_continuations") or 0) >= maximum:
            reason = "AutoResearch Guard paused the loop: max_stop_continuations"
            loop["status"] = "waiting_human"
            loop["pause_reason"] = reason
            loop["resume_phase"] = state.get("phase", "")
            loop["owner_session_id"] = ""
            _write_state(root, state, runtime_only=True)
            record_event(root, "loop.circuit_breaker", details={"reasons": ["max_stop_continuations"]}, state=state)
            readiness = evaluate_readiness(root)
            return {"action": "halt", "readiness": readiness, "reason": reason}

        loop["stop_continuations"] = int(loop.get("stop_continuations") or 0) + 1
        _write_state(root, state, runtime_only=True)
        record_event(root, "hook.stop_continue", details={"turn_id": turn_id, "state_digest": readiness["state_digest"]}, state=state)
        detail = "; ".join(readiness.get("reasons") or [])
        next_action = readiness["next_actions"][0] if readiness["next_actions"] else "运行 arx_loop.py check --json 并处理未完成项"
        return {
            "action": "continue",
            "readiness": readiness,
            "reason": f"AutoResearch Guard closure incomplete: {detail}. {next_action}",
        }


def _tree_digests(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): _file_digest(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "archive_manifest.yaml"
    }


def _archive_destination(root: Path, iteration_id: str) -> tuple[str, Path]:
    safe_iteration = slug(iteration_id)
    archive_id = (
        f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"{safe_iteration}-{uuid.uuid4().hex[:8]}"
    )
    destination = archive_dir(root) / archive_id
    if destination.exists():
        raise ArxError(f"archive destination already exists: {destination}")
    return archive_id, destination


def _raw_recovery_archive(root: Path, cur: Path, *, reason: str, label: str, error: Exception) -> Path:
    iteration_id = label.strip() or "recovery"
    try:
        raw_state = load_yaml(cur / "state.yaml")
        iteration_id = str(raw_state.get("iteration_id") or iteration_id)
    except Exception:
        pass
    archive_id, destination = _archive_destination(root, iteration_id)
    manifest = {
        "archive_version": 2,
        "archive_id": archive_id,
        "archived_at": utc_now(),
        "iteration_id": iteration_id,
        "allow_incomplete": True,
        "reason": reason,
        "outcome": "aborted",
        "recovery_error": f"{type(error).__name__}: {error}",
        "raw_snapshot_digests": _tree_digests(cur),
    }
    write_yaml(cur / "archive_manifest.yaml", manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cur), str(destination))
    return destination


def archive_current(
    research_root: str | Path,
    *,
    allow_incomplete: bool = False,
    reason: str = "",
    label: str = "",
) -> Path:
    root = Path(research_root).resolve()
    with research_lock(root):
        cur = current_dir(root)
        if not cur.exists():
            raise ArxError(f"missing current directory: {cur}")
        if allow_incomplete and not reason.strip():
            raise ArxError("--allow-incomplete requires a non-empty --reason")
        try:
            readiness = evaluate_readiness(root)
        except Exception as exc:
            if not allow_incomplete:
                raise
            return _raw_recovery_archive(root, cur, reason=reason, label=label, error=exc)
        if not readiness["ready"] and not allow_incomplete:
            detail = "; ".join(readiness["reasons"][:8]) or readiness["outcome"]
            raise ArxError(f"current iteration is not ready to archive: {detail}")

        state = load_lifecycle_state(root)
        iteration_id = str(state.get("iteration_id") or label or "iteration")
        original_state = copy.deepcopy(state)
        closure_snapshot = snapshot_digests(root)
        loop = state.setdefault("loop", _default_loop())
        state["phase"] = "archived"
        loop["status"] = "complete" if readiness["ready"] else "aborted"
        loop["owner_session_id"] = ""
        if reason:
            loop["pause_reason"] = reason
        archive_id, destination = _archive_destination(root, iteration_id)
        try:
            _write_state(root, state)
            record_event(
                root,
                "transition.archive",
                details={"outcome": readiness["outcome"], "reason": reason},
                state=state,
            )
            manifest = {
                "archive_version": 2,
                "archive_id": archive_id,
                "archived_at": utc_now(),
                "iteration_id": iteration_id,
                "allow_incomplete": allow_incomplete,
                "reason": reason,
                "outcome": readiness["outcome"] if readiness["ready"] else "aborted",
                "readiness": readiness,
                "snapshot_digests": closure_snapshot,
                "input_digests": (load_current_yaml(root, "audit_report.yaml").get("input_digests") or {}),
                "audit_digest": _file_digest(cur / "audit_report.yaml"),
                "decision_digest": _file_digest(cur / "decision.yaml"),
            }
            write_yaml(cur / "archive_manifest.yaml", manifest)
            if snapshot_digests(root) != closure_snapshot:
                raise ArxError("closure artifacts changed while archive was being prepared")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(cur), str(destination))
            return destination
        except Exception as exc:
            if cur.exists():
                try:
                    (cur / "archive_manifest.yaml").unlink(missing_ok=True)
                    write_yaml(cur / "state.yaml", original_state)
                    record_event(
                        root,
                        "transition.archive_failed",
                        details={"error": f"{type(exc).__name__}: {exc}"},
                        state=original_state,
                    )
                except Exception:
                    pass
            raise ArxError(f"archive failed before a complete move: {exc}") from exc
