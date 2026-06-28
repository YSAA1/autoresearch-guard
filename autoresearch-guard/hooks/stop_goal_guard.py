from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
COMMON = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
sys.path.insert(0, str(COMMON))

from arx_common import current_dir, load_jsonl  # noqa: E402

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Prevent ending guarded /goal with incomplete closure artifacts.")
    parser.add_argument("--cwd", default="")
    args = parser.parse_args()
    cwd = Path(args.cwd or Path.cwd()).resolve()
    research_root = find_research_root(cwd)
    if research_root is None:
        print(json.dumps({"complete": True, "reason": "no .research/current found"}))
        return 0

    cur = current_dir(research_root)
    missing = [name for name in REQUIRED if not meaningful(cur / name)]
    if not load_jsonl(cur / "evidence_ledger.jsonl"):
        missing.append("evidence_ledger.jsonl")
    if missing:
        print(json.dumps({"complete": False, "missing": missing}, ensure_ascii=True))
        return 2
    print(json.dumps({"complete": True, "reason": "guarded research closure artifacts present"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())