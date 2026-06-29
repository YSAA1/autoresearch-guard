from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
COMMON = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
sys.path.insert(0, str(COMMON))

from arx_common import current_dir, load_current_yaml, load_jsonl, read_text  # noqa: E402

REQUIRED = ["audit_report.yaml", "ai_evidence_review.md", "decision.yaml"]


def find_research_root(cwd: Path) -> Path | None:
    for path in [cwd, *cwd.parents]:
        if (path / ".research" / "current").exists():
            return path / ".research"
    return None


def meaningful(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8").strip()
    return bool(text) and "TBD by AI" not in text


def has_failures(entries: list[dict]) -> bool:
    return any(str(e.get("status") or "") == "fail" or int(e.get("exit_code") or 0) != 0 for e in entries)


def lessons_updated_for_iteration(research_root: Path, iteration_id: str) -> bool:
    anti = research_root / "lessons" / "anti_patterns.yaml"
    if not anti.exists():
        return False
    return iteration_id in read_text(anti)


def main() -> int:
    parser = argparse.ArgumentParser(description="在缺少闭环产物时阻止结束受控 /goal。")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    cwd = Path(args.cwd or Path.cwd()).resolve()
    research_root = find_research_root(cwd)
    if research_root is None:
        return 0

    cur = current_dir(research_root)
    missing = [name for name in REQUIRED if not meaningful(cur / name)]
    entries = load_jsonl(cur / "evidence_ledger.jsonl")
    if not entries:
        missing.append("evidence_ledger.jsonl")

    if has_failures(entries) and not args.allow_incomplete:
        hypothesis = load_current_yaml(research_root, "hypothesis.yaml")
        iteration_id = str(hypothesis.get("iteration_id") or "")
        if iteration_id and not lessons_updated_for_iteration(research_root, iteration_id):
            missing.append("anti_patterns.yaml (含本轮 iteration_id 的失败经验)")

    if missing:
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": "AutoResearch Guard closure is incomplete: " + ", ".join(missing),
                },
                ensure_ascii=True,
            )
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
