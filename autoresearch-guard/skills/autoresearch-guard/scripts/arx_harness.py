from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from arx_common import (
    ArxError,
    listify,
    load_jsonl,
    load_yaml,
    parse_markdown_tables,
    read_text,
    sha256_file,
    utc_now,
    write_text,
    write_yaml,
)
from arx_research import (
    claim_level_rank,
    evaluate_research_gates,
    load_research,
    normalize_claim_level,
)

REVIEW_PACK_FILES = (
    "audit_report.yaml",
    "research.yaml",
    "hypothesis.yaml",
    "protocol.lock.yaml",
    "claim_boundary.yaml",
    "ai_evidence_review.md",
    "literature_review.md",
)


def _cur(research_root: str | Path) -> Path:
    return Path(research_root).resolve() / "current"


def default_outcome() -> dict[str, Any]:
    return {
        "version": 1,
        "checks": [
            {"id": "brief_success_criteria", "type": "brief_success_criteria"},
            {"id": "research_gates_pass", "type": "research_gates_pass"},
            {"id": "no_unresolved_conflicts", "type": "no_unresolved_conflicts"},
            {"id": "critical_claims_supported", "type": "critical_claims_supported"},
            {"id": "adversary_survived", "type": "adversary_survived"},
        ],
    }


def ensure_harness_files(research_root: str | Path, *, iteration_id: str) -> None:
    del iteration_id  # retained for call-site compatibility
    cur = _cur(research_root)
    write_yaml(cur / "outcome.yaml", default_outcome())


def load_outcome_spec(research_root: str | Path) -> dict[str, Any]:
    path = _cur(research_root) / "outcome.yaml"
    if not path.exists():
        return default_outcome()
    data = load_yaml(path)
    checks = [item for item in listify(data.get("checks")) if isinstance(item, dict)]
    return {"version": int(data.get("version") or 1), "checks": checks or default_outcome()["checks"]}


def _review_claim_rows(research_root: str | Path) -> list[dict[str, str]]:
    path = _cur(research_root) / "ai_evidence_review.md"
    if not path.exists():
        return []
    rows = []
    for row in parse_markdown_tables(read_text(path)):
        claim_id = str(row.get("claim_id") or row.get("claim id") or row.get("id") or "").strip()
        if not claim_id:
            lowered = {str(k).strip().lower(): str(v).strip() for k, v in row.items()}
            claim_id = lowered.get("claim_id") or lowered.get("id") or ""
            for key, value in lowered.items():
                if "claim" in key and value:
                    claim_id = value
                    break
        status = ""
        level = ""
        for key, value in row.items():
            key_l = str(key).strip().lower()
            val = str(value).strip()
            if key_l in {"状态", "status"}:
                status = val.lower()
            if key_l in {"等级", "证据等级", "level", "evidence_level"}:
                level = normalize_claim_level(val)
        if not claim_id:
            continue
        rows.append({"claim_id": claim_id, "status": status, "level": level})
    return rows


def evaluate_outcome(research_root: str | Path) -> dict[str, Any]:
    root = Path(research_root).resolve()
    research_doc = load_research(root) if (_cur(root) / "research.yaml").exists() else {}
    research = evaluate_research_gates(root)
    review_rows = _review_claim_rows(root)
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    brief_success = str(research_doc.get("success_criteria") or "").strip()
    target = normalize_claim_level(str(research_doc.get("claim_level_target") or "exploratory"))

    for check in load_outcome_spec(root).get("checks") or []:
        check_id = str(check.get("id") or check.get("type") or "check").strip()
        check_type = str(check.get("type") or "").strip()
        ok = False
        detail = ""
        if check_type == "brief_success_criteria":
            ok = bool(brief_success) and not brief_success.lower().startswith("tbd")
            detail = brief_success[:160] if brief_success else "missing success_criteria"
        elif check_type == "research_gates_pass":
            ok = research.get("status") == "pass"
            detail = "; ".join(listify(research.get("errors"))[:4]) or "research gates pass"
        elif check_type == "no_unresolved_conflicts":
            unresolved = int((research.get("counts") or {}).get("unresolved_conflicts") or 0)
            if claim_level_rank(target) is not None and claim_level_rank(target) >= claim_level_rank("supported"):
                ok = unresolved == 0
                detail = f"unresolved_conflicts={unresolved}"
            else:
                ok = True
                detail = f"exploratory allows unresolved conflicts ({unresolved})"
        elif check_type == "critical_claims_supported":
            claims = [item for item in listify(research.get("claims")) if isinstance(item, dict)]
            critical = [item for item in claims if item.get("critical") is True] or claims
            if not critical:
                ok = False
                detail = "no claims defined"
            elif not review_rows:
                ok = False
                detail = "ai_evidence_review.md has no claim table yet"
            else:
                supported = {row["claim_id"] for row in review_rows if row["status"] == "supported"}
                missing = [str(item.get("id")) for item in critical if str(item.get("id")) not in supported]
                ok = not missing
                detail = "all critical claims supported" if ok else "unsupported: " + ", ".join(missing)
        elif check_type == "adversary_survived":
            adversary = research.get("adversary") or {}
            claims = [
                item
                for item in listify(research.get("claims"))
                if isinstance(item, dict) and item.get("falsifiable") is not False
            ]
            missing = []
            for claim in claims:
                row = adversary.get(str(claim.get("id")))
                if not row or row.get("verdict") != "survived":
                    missing.append(str(claim.get("id")))
            ok = not missing
            detail = "all falsifiable claims survived" if ok else "not survived: " + ", ".join(missing)
        else:
            ok = False
            detail = f"unknown outcome check type: {check_type or '<missing>'}"
        results.append({"id": check_id, "type": check_type, "ok": ok, "detail": detail})
        if not ok:
            failures.append(f"outcome:{check_id}: {detail}")

    return {
        "ready": not failures,
        "failures": failures,
        "checks": results,
        "success_criteria": brief_success,
        "claim_level_target": target,
    }


def prepare_review_pack(research_root: str | Path) -> dict[str, Any]:
    root = Path(research_root).resolve()
    cur = _cur(root)
    audit_path = cur / "audit_report.yaml"
    if not audit_path.exists():
        raise ArxError("prepare-review requires audit_report.yaml; run arx_audit.py first")
    audit_digest = sha256_file(audit_path)
    pack_dir = cur / "review_pack"
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in REVIEW_PACK_FILES:
        src = cur / name
        if not src.exists():
            continue
        shutil.copy2(src, pack_dir / name)
        copied.append(name)
    ledger = load_jsonl(cur / "evidence_ledger.jsonl")
    excerpt = ledger[-20:]
    write_text(
        pack_dir / "evidence_ledger_excerpt.jsonl",
        "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in excerpt),
    )
    if "evidence_ledger_excerpt.jsonl" not in copied:
        copied.append("evidence_ledger_excerpt.jsonl")
    instructions = (
        "# Review subagent instructions\n\n"
        "You are a same-session review subagent. Do not read parent chat history or transcripts.\n"
        "Only read files under this `review_pack/` directory.\n\n"
        "Tasks:\n"
        "1. Check claim↔evidence resolvability, multi-source coverage, unresolved conflicts, adversary pass.\n"
        "2. Write `../subagent_review.yaml` (one directory up, in current/) with:\n"
        "   - verdict: pass|fail|inconclusive\n"
        "   - failed_checks: []\n"
        f"   - bound_audit_digest: {audit_digest}\n"
        "   - reviewer_role: subagent\n"
        "   - reviewed_at: ISO-8601 UTC\n"
        "3. Do not run experiments, edit protocol, or write decision.yaml.\n"
    )
    write_text(pack_dir / "REVIEW_INSTRUCTIONS.md", instructions)
    manifest = {
        "prepared_at": utc_now(),
        "bound_audit_digest": audit_digest,
        "files": sorted(set(copied + ["REVIEW_INSTRUCTIONS.md"])),
        "pack_dir": str(pack_dir),
    }
    write_yaml(pack_dir / "manifest.yaml", manifest)
    from arx_lifecycle import record_event

    record_event(
        root,
        "harness.prepare_review",
        details={"bound_audit_digest": audit_digest, "files": manifest["files"]},
    )
    return manifest


def load_subagent_review(research_root: str | Path) -> dict[str, Any]:
    path = _cur(research_root) / "subagent_review.yaml"
    if not path.exists():
        return {}
    data = load_yaml(path)
    return data if isinstance(data, dict) else {}


def subagent_review_errors(
    research_root: str | Path,
    *,
    required: bool,
    audit_digest: str = "",
) -> list[str]:
    if not required:
        return []
    review = load_subagent_review(research_root)
    if not review:
        return [
            "subagent_review.yaml missing; run arx_loop.py prepare-review and have a review "
            "subagent write the verdict (ai_evidence_review.md cannot substitute)"
        ]
    errors: list[str] = []
    verdict = str(review.get("verdict") or "").strip().lower()
    if verdict != "pass":
        failed = listify(review.get("failed_checks"))
        detail = ", ".join(str(item) for item in failed) if failed else verdict or "missing"
        errors.append(f"subagent_review verdict is not pass ({detail})")
    role = str(review.get("reviewer_role") or "").strip().lower()
    if role and role != "subagent":
        errors.append(f"subagent_review reviewer_role must be subagent, got {role}")
    elif not role:
        errors.append("subagent_review reviewer_role must be subagent")
    bound = str(review.get("bound_audit_digest") or "").strip()
    expected = audit_digest or sha256_file(_cur(research_root) / "audit_report.yaml")
    if not bound:
        errors.append("subagent_review bound_audit_digest is missing")
    elif bound != expected:
        errors.append("subagent_review bound_audit_digest does not match current audit_digest")
    from arx_common import parse_timestamp

    reviewed_at = parse_timestamp(review.get("reviewed_at"))
    if reviewed_at is None:
        errors.append("subagent_review reviewed_at is missing or invalid")
    return errors


def requires_subagent_review(
    research_root: str | Path,
    *,
    decision: str = "",
    audit: dict[str, Any] | None = None,
) -> bool:
    """Hard gate only for promote. verified claims are advisory (audit still checks format)."""
    del research_root, audit
    return str(decision or "").strip().lower() == "promote"


def session_start_ritual_message(
    research_root: str | Path,
    *,
    report: dict[str, Any],
    relation: str,
) -> str:
    del research_root
    next_actions = list(report.get("next_actions") or [])
    missing = list(report.get("missing") or [])
    reasons = list(report.get("reasons") or [])
    lines = [
        "AutoResearch Guard recovery context:",
        (
            f"iteration={report.get('iteration_id')}; phase={report.get('phase')}; "
            f"status={report.get('status')}; outcome={report.get('outcome')}; "
            f"process_ready={report.get('process_ready')}; outcome_ready={report.get('outcome_ready')}; "
            f"goal_ready={report.get('goal_ready')}; session_relation={relation}; "
            f"state_digest={report.get('state_digest')}."
        ),
        "Run `arx_loop.py check --json` before declaring progress or closing the goal.",
    ]
    if reasons:
        lines.append("Why incomplete: " + "; ".join(reasons[:4]))
    if missing:
        lines.append("Missing: " + ", ".join(missing[:6]))
    if next_actions:
        lines.append("Next action: " + str(next_actions[0]))
    return " ".join(lines)
