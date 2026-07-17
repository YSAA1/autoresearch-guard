from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from arx_common import listify, load_current_yaml, parse_markdown_tables, read_text

CLAIM_LEVELS = {
    "exploratory": 0,
    "supported": 1,
    "verified": 2,
}

# Legacy aliases kept so older review tables still rank correctly.
CLAIM_LEVEL_ALIASES = {
    "validation": "supported",
    "test": "verified",
}

SOURCE_TYPES = {"academic", "web", "code", "community", "primary", "other"}
ADVERSARY_VERDICTS = {"survived", "refuted", "unverified"}
CONFLICT_RESOLUTIONS = {
    "unresolved",
    "accepted_a",
    "accepted_b",
    "deferred_human",
    "synthesized",
}

RESEARCH_PRODUCT_FILE = "research.yaml"


def normalize_claim_level(level: str) -> str:
    value = str(level or "").strip().lower()
    return CLAIM_LEVEL_ALIASES.get(value, value)


def claim_level_rank(level: str) -> int | None:
    return CLAIM_LEVELS.get(normalize_claim_level(level))


def _lookup(row: dict[str, Any], *keys: str) -> str:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def evidence_ref_resolvable(ref: str, *, base: Path) -> bool:
    text = str(ref or "").strip()
    if not text or text.lower() in {"none", "n/a", "na", "tbd"}:
        return False
    parts = re.split(r"[\s,;|]+", text)
    for part in parts:
        token = part.strip().strip("()[]<>\"'")
        if not token:
            continue
        if token.lower().startswith(("http://", "https://")):
            parsed = urlparse(token)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return True
            continue
        if token.startswith("ledger:"):
            return True
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = (base / candidate).resolve()
        if candidate.exists() and candidate.is_file():
            return True
    return False


def load_research(root: Path) -> dict[str, Any]:
    data = load_current_yaml(root, RESEARCH_PRODUCT_FILE)
    return data if isinstance(data, dict) else {}


def _load_claims(research: dict[str, Any]) -> list[dict[str, Any]]:
    claims = []
    for item in listify(research.get("claims")):
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("id") or "").strip()
        statement = str(item.get("statement") or "").strip()
        if not claim_id or not statement:
            continue
        claims.append(
            {
                "id": claim_id,
                "statement": statement,
                "falsifiable": item.get("falsifiable") is not False,
                "critical": item.get("critical") is True,
            }
        )
    return claims


def _load_gaps(research: dict[str, Any]) -> list[dict[str, Any]]:
    gaps = []
    for item in listify(research.get("gaps")):
        if not isinstance(item, dict):
            continue
        gap_id = str(item.get("id") or "").strip()
        question = str(item.get("question") or "").strip()
        if not gap_id or not question:
            continue
        gaps.append(
            {
                "id": gap_id,
                "question": question,
                "claim_ids": [str(x).strip() for x in listify(item.get("claim_ids")) if str(x).strip()],
                "critical": item.get("critical") is True,
                "status": str(item.get("status") or "open").strip().lower(),
            }
        )
    return gaps


def _load_sources(research: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for entry in listify(research.get("sources")):
        if not isinstance(entry, dict):
            continue
        source_id = str(entry.get("source_id") or entry.get("id") or "").strip()
        gap_id = str(entry.get("gap_id") or "").strip()
        source_type = str(entry.get("source_type") or "").strip().lower()
        url = str(entry.get("url") or entry.get("path") or "").strip()
        if not source_id or not gap_id or not source_type:
            continue
        rows.append(
            {
                "source_id": source_id,
                "gap_id": gap_id,
                "source_type": source_type,
                "url": url,
                "title": str(entry.get("title") or "").strip(),
            }
        )
    return rows


def _load_conflicts(research: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in listify(research.get("conflicts")):
        if not isinstance(item, dict):
            continue
        conflict_id = str(item.get("id") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not conflict_id or not summary:
            continue
        rows.append(
            {
                "id": conflict_id,
                "claim_id": str(item.get("claim_id") or "").strip(),
                "summary": summary,
                "resolution": str(item.get("resolution") or "unresolved").strip().lower(),
            }
        )
    return rows


def _load_adversary(research: dict[str, Any], root: Path) -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    for item in listify(research.get("adversary")):
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id") or item.get("id") or "").strip()
        verdict = str(item.get("verdict") or "").strip().lower()
        evidence = str(item.get("evidence") or "").strip()
        if not claim_id or not verdict:
            continue
        results[claim_id] = {"verdict": verdict, "evidence": evidence}
    # Legacy fallback: adversary.md table still accepted during migration.
    legacy = root / "current" / "adversary.md"
    if not results and legacy.exists():
        text = read_text(legacy)
        for row in parse_markdown_tables(text):
            claim_id = _lookup(row, "claim_id", "claim id", "id")
            verdict = _lookup(row, "verdict", "result", "裁决").lower()
            evidence = _lookup(row, "evidence", "证据")
            if not claim_id or not verdict:
                continue
            results[claim_id] = {"verdict": verdict, "evidence": evidence}
    return results


def evaluate_research_gates(research_root: str | Path) -> dict[str, Any]:
    root = Path(research_root).resolve()
    cur = root / "current"
    status: dict[str, Any] = {
        "required": True,
        "status": "fail",
        "blocks_verified": True,
        "blocks_promote": True,
        "errors": [],
        "warnings": [],
        "brief": {},
        "claims": [],
        "gaps": [],
        "source_coverage": {},
        "conflicts": [],
        "adversary": {},
        "counts": {},
    }
    errors: list[str] = []
    warnings: list[str] = []

    if not (cur / RESEARCH_PRODUCT_FILE).exists():
        status["errors"] = [f"missing research product: {RESEARCH_PRODUCT_FILE}"]
        status["counts"] = {"claims": 0, "gaps": 0, "sources": 0, "conflicts": 0, "adversary_rows": 0}
        return status

    research = load_research(root)
    question = str(research.get("question") or "").strip()
    success = str(research.get("success_criteria") or "").strip()
    target_level = normalize_claim_level(str(research.get("claim_level_target") or "exploratory"))
    if not question or question.lower().startswith("tbd"):
        errors.append("research.yaml question must be non-empty")
    if not success or success.lower().startswith("tbd"):
        errors.append("research.yaml success_criteria must be non-empty")
    if claim_level_rank(target_level) is None:
        errors.append(f"research.yaml claim_level_target is unknown: {target_level}")
        target_level = "exploratory"
    status["brief"] = {
        "question": question,
        "success_criteria": success,
        "claim_level_target": target_level,
        "non_goals": listify(research.get("non_goals")),
    }

    claims = _load_claims(research)
    falsifiable = [claim for claim in claims if claim["falsifiable"]]
    if not claims:
        errors.append("research.yaml needs at least one claim with id and statement")
    if not falsifiable:
        errors.append("research.yaml needs at least one falsifiable claim")
    status["claims"] = claims

    gaps = _load_gaps(research)
    if not gaps:
        errors.append("research.yaml needs at least one gap with id and question")
    claim_ids = {claim["id"] for claim in claims}
    for gap in gaps:
        unknown = [cid for cid in gap["claim_ids"] if cid not in claim_ids]
        if unknown:
            errors.append(f"gap {gap['id']} references unknown claim_ids: {', '.join(unknown)}")
    status["gaps"] = gaps

    sources = _load_sources(research)
    if not sources:
        errors.append("research.yaml needs at least one source row")
    coverage: dict[str, list[str]] = {}
    for source in sources:
        if source["source_type"] not in SOURCE_TYPES:
            errors.append(f"source {source['source_id']} has unknown source_type: {source['source_type']}")
        coverage.setdefault(source["gap_id"], [])
        if source["source_type"] not in coverage[source["gap_id"]]:
            coverage[source["gap_id"]].append(source["source_type"])
    status["source_coverage"] = coverage

    critical_gaps = [
        gap
        for gap in gaps
        if gap["critical"] or any(claim["id"] in gap["claim_ids"] and claim["critical"] for claim in claims)
    ]
    if not critical_gaps and gaps:
        critical_gaps = list(gaps)
    for gap in critical_gaps:
        types = coverage.get(gap["id"], [])
        if len(types) < 2:
            errors.append(
                f"gap {gap['id']} needs ≥2 independent source_types, found {len(types)}: {types or 'none'}"
            )

    conflicts = _load_conflicts(research)
    status["conflicts"] = conflicts
    unresolved = [item for item in conflicts if item["resolution"] == "unresolved"]
    invalid_resolution = [item for item in conflicts if item["resolution"] not in CONFLICT_RESOLUTIONS]
    for item in invalid_resolution:
        errors.append(f"conflict {item['id']} has unknown resolution: {item['resolution']}")
    if unresolved and claim_level_rank(target_level) >= claim_level_rank("supported"):
        errors.append(
            "research.yaml has unresolved conflicts; resolve or set deferred_human before supported/verified"
        )
    elif unresolved:
        warnings.append("research.yaml has unresolved conflicts")

    adversary = _load_adversary(research, root)
    status["adversary"] = adversary
    if not adversary:
        errors.append("research.yaml needs adversary verdicts for falsifiable claims")
    for claim in falsifiable:
        row = adversary.get(claim["id"])
        if row is None:
            errors.append(f"research.yaml adversary missing verdict for falsifiable claim {claim['id']}")
            continue
        if row["verdict"] not in ADVERSARY_VERDICTS:
            errors.append(f"research.yaml adversary claim {claim['id']} has unknown verdict: {row['verdict']}")
        if row["verdict"] == "refuted" and claim_level_rank(target_level) >= claim_level_rank("supported"):
            errors.append(f"claim {claim['id']} was refuted; cannot target {target_level}")

    status["counts"] = {
        "claims": len(claims),
        "gaps": len(gaps),
        "sources": len(sources),
        "conflicts": len(conflicts),
        "adversary_rows": len(adversary),
        "unresolved_conflicts": len(unresolved),
    }
    status["errors"] = sorted(set(errors))
    status["warnings"] = sorted(set(warnings))
    passed = not status["errors"]
    status["status"] = "pass" if passed else "fail"
    status["blocks_verified"] = not passed
    status["blocks_promote"] = not passed
    return status


def evaluate_verified_claims(
    review_text: str,
    research_status: dict[str, Any],
    *,
    base: Path,
) -> dict[str, Any]:
    """Deterministic checks for claim level == verified (existence/format + binding only)."""
    rows = [
        row
        for row in parse_markdown_tables(review_text)
        if _lookup(row, "claim_id", "claim id", "id") or "结论与证据" in str(row.get("_section") or "")
    ]
    result: dict[str, Any] = {
        "verified_claims": [],
        "unresolvable_evidence": [],
        "missing_adversary": [],
        "refuted_or_unverified": [],
        "unbound_claims": [],
        "status": "pass",
    }
    known_claims = {claim["id"] for claim in listify(research_status.get("claims"))}
    adversary = research_status.get("adversary") or {}
    for index, row in enumerate(rows, 1):
        claim_id = _lookup(row, "claim_id", "claim id", "id") or f"claim-{index}"
        level = normalize_claim_level(_lookup(row, "等级", "证据等级", "level", "evidence_level"))
        evidence = _lookup(row, "证据", "evidence")
        support = _lookup(row, "状态", "status").lower()
        if level != "verified":
            continue
        result["verified_claims"].append(claim_id)
        if support != "supported":
            result["unbound_claims"].append(claim_id)
            continue
        if known_claims and claim_id not in known_claims:
            result["unbound_claims"].append(claim_id)
        if not evidence_ref_resolvable(evidence, base=base):
            result["unresolvable_evidence"].append(claim_id)
        adv = adversary.get(claim_id)
        if adv is None:
            result["missing_adversary"].append(claim_id)
        elif adv.get("verdict") != "survived":
            result["refuted_or_unverified"].append(claim_id)
    blocked = any(
        result[key]
        for key in (
            "unresolvable_evidence",
            "missing_adversary",
            "refuted_or_unverified",
            "unbound_claims",
        )
    )
    if research_status.get("blocks_verified") and result["verified_claims"]:
        blocked = True
        result["research_gate_blocked"] = True
    result["status"] = "fail" if blocked else "pass"
    return result


def dump_research_gate_yaml(status: dict[str, Any]) -> dict[str, Any]:
    """Compact view for audit_report.yaml."""
    return {
        "status": status.get("status"),
        "blocks_verified": status.get("blocks_verified"),
        "blocks_promote": status.get("blocks_promote"),
        "errors": listify(status.get("errors")),
        "warnings": listify(status.get("warnings")),
        "counts": status.get("counts") or {},
        "claim_level_target": (status.get("brief") or {}).get("claim_level_target"),
        "source_coverage": status.get("source_coverage") or {},
    }
