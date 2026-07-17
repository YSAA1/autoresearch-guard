from __future__ import annotations

import argparse
import json
from pathlib import Path

from arx_common import add_common_args, current_dir, latest_entry, listify, load_current_yaml, load_jsonl
from arx_lifecycle import evaluate_readiness, load_lifecycle_state


def light_for_baseline(status: dict) -> str:
    value = str(status.get("status") or "not_required")
    if value in {"pass", "not_required"}:
        return "绿灯"
    if value in {"missing_required_baseline", "failed_baseline_comparison", "missing_baseline_metric", "missing_experiment_metric", "invalid_config"}:
        return "红灯"
    return "黄灯"


def light_for_claim(status: dict) -> str:
    value = str(status.get("status") or "not_reviewed")
    if value == "pass":
        return "绿灯"
    if value in {"fail", "not_reviewed"}:
        return "红灯"
    return "黄灯"


def light_for_spiral(status: dict) -> str:
    level = str(status.get("level") or "none")
    if level == "none":
        return "绿灯"
    if level == "critical":
        return "红灯"
    return "黄灯"


def render_review_packet(status: dict) -> str:
    audit = status["audit"]
    lines: list[str] = ["# AutoResearch Guard review packet", ""]
    loop = status.get("loop") or {}
    lines.append(
        f"循环：{loop.get('phase')}/{loop.get('status')}；outcome={loop.get('outcome')}；ready={str(loop.get('ready')).lower()}"
    )
    lines.append("")

    gates: list[tuple[str, str, str]] = []
    gates.append((
        "prior art",
        "绿灯" if status.get("active_goal_exists") else "红灯",
        "active_goal 已生成" if status.get("active_goal_exists") else "尚未通过 compile gate",
    ))
    gates.append((
        "baseline",
        light_for_baseline(audit.get("baseline_status") or {}),
        str((audit.get("baseline_status") or {}).get("status") or "not_required"),
    ))
    protocol_ok = not audit.get("protocol_violation") and not audit.get("test_contamination")
    gates.append((
        "protocol integrity",
        "绿灯" if protocol_ok else "红灯",
        "无协议违规" if protocol_ok else "存在协议违规或 test contamination",
    ))
    gates.append((
        "validation gate",
        "绿灯" if audit.get("validation_gate_passed") is True else "红灯",
        "通过" if audit.get("validation_gate_passed") is True else "未通过或未知",
    ))
    gates.append((
        "claim support",
        light_for_claim(audit.get("claim_support_status") or {}),
        str((audit.get("claim_support_status") or {}).get("status") or "not_reviewed"),
    ))
    gates.append((
        "spiral risk",
        light_for_spiral(audit.get("spiral_risk") or {}),
        str((audit.get("spiral_risk") or {}).get("level") or "none"),
    ))

    lights = [light for _name, light, _detail in gates]
    if "红灯" in lights:
        conclusion = "红灯，不能 promote；先修红灯或选择 refine/pivot/stop"
    elif "黄灯" in lights:
        conclusion = "黄灯，可以继续但需要人工确认风险"
    else:
        conclusion = "绿灯，门禁通过；promote 仍需人工确认"
    lines.append(f"结论：{conclusion}")
    lines.append("")
    lines.append("## 门禁")
    for name, light, detail in gates:
        lines.append(f"- {name}：{light}（{detail}）")

    forbidden = audit.get("forbidden_decisions") or []
    lines.append("")
    lines.append("## 决策")
    lines.append(f"- forbidden decisions：{', '.join(forbidden) if forbidden else 'none'}")
    lines.append(f"- current decision：{status.get('decision') or 'none'}")

    lines.append("")
    lines.append("## 下钻")
    lines.append("- prior art：literature_review.md")
    lines.append("- baseline / evidence：evidence_ledger.jsonl")
    lines.append("- audit：audit_report.yaml")
    lines.append("- claim support：ai_evidence_review.md")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Show current AutoResearch Guard status.")
    add_common_args(parser)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--review", action="store_true", help="Render a human review packet with gate lights")
    args = parser.parse_args()

    root = Path(args.research_root).resolve()
    cur = current_dir(root)
    state = load_lifecycle_state(root) if cur.exists() else {}
    hypothesis = load_current_yaml(root, "hypothesis.yaml")
    protocol = load_current_yaml(root, "protocol.lock.yaml")
    blocked = load_current_yaml(root, "blocked_actions.yaml")
    claim = load_current_yaml(root, "claim_boundary.yaml")
    audit = load_current_yaml(root, "audit_report.yaml")
    decision = load_current_yaml(root, "decision.yaml")
    entries = load_jsonl(cur / "evidence_ledger.jsonl") if cur.exists() else []
    loop_report = evaluate_readiness(root) if cur.exists() else {
        "ready": False,
        "outcome": "no_current",
        "phase": "none",
        "status": "idle",
        "owner_session_id": "",
        "reasons": ["no current iteration"],
        "next_actions": ["run arx_init.py"],
        "budget": {},
    }

    status = {
        "research_root": str(root),
        "current_exists": cur.exists(),
        "iteration_id": hypothesis.get("iteration_id") or state.get("iteration_id"),
        "state": state.get("phase"),
        "phase": state.get("phase"),
        "revision": state.get("revision"),
        "objective": hypothesis.get("objective"),
        "protocol_locked": protocol.get("locked") is True,
        "hooks_enabled": state.get("hooks_enabled") is True,
        "protocol_digest": state.get("protocol_digest"),
        "active_goal_exists": (cur / "active_goal.md").exists(),
        "evidence_records": len(entries),
        "latest_evidence": latest_entry(entries),
        "audit": {
            "exists": bool(audit),
            "evidence_valid": audit.get("evidence_valid"),
            "protocol_violation": audit.get("protocol_violation"),
            "test_contamination": audit.get("test_contamination"),
            "validation_gate_passed": audit.get("validation_gate_passed"),
            "baseline_status": audit.get("baseline_status"),
            "claim_support_status": audit.get("claim_support_status"),
            "spiral_risk": audit.get("spiral_risk"),
            "forbidden_decisions": audit.get("forbidden_decisions"),
        },
        "decision": decision.get("decision"),
        "blocked_actions": listify(blocked.get("blocked_actions")),
        "max_claim_level": claim.get("max_claim_level"),
        "requires_human_gate": state.get("human_gate_required"),
        "loop": loop_report,
    }

    if args.review:
        print(render_review_packet(status), end="")
    elif args.json:
        print(json.dumps(status, indent=2, ensure_ascii=True, sort_keys=True))
    else:
        print(f"AutoResearch Guard status: {status['iteration_id']}")
        print(f"- current: {status['current_exists']} ({cur})")
        print(f"- state: {status['state']}")
        print(f"- loop: {status['loop']['status']} ({status['loop']['outcome']})")
        print(f"- owner session: {status['loop'].get('owner_session_id') or 'unbound'}")
        print(f"- ready: {status['loop']['ready']}")
        print(f"- objective: {status['objective']}")
        print(f"- protocol locked: {status['protocol_locked']}")
        print(f"- hooks enabled: {status['hooks_enabled']}")
        print(f"- evidence records: {status['evidence_records']}")
        print(f"- audit evidence_valid: {status['audit']['evidence_valid']}")
        print(f"- audit validation_gate_passed: {status['audit']['validation_gate_passed']}")
        print(f"- decision: {status['decision']}")
        print(f"- max claim level: {status['max_claim_level']}")
        print(f"- human gate required: {status['requires_human_gate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
