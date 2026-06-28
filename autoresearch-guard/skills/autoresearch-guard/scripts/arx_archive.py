from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from arx_common import ArxError, add_common_args, archive_dir, current_dir, load_current_yaml, slug, utc_now, write_yaml

REQUIRED_COMPLETE = [
    "evidence_ledger.jsonl",
    "audit_report.yaml",
    "ai_evidence_review.md",
    "decision.yaml",
]


def meaningful(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return False
    if "TBD by AI" in text:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive completed AutoResearch Guard current state.")
    add_common_args(parser)
    parser.add_argument("--allow-incomplete", action="store_true", help="Archive even if closure files are incomplete")
    parser.add_argument("--label", default="", help="Optional archive label")
    args = parser.parse_args()

    root = Path(args.research_root).resolve()
    cur = current_dir(root)
    if not cur.exists():
        raise ArxError(f"missing current directory: {cur}")

    missing = [name for name in REQUIRED_COMPLETE if not meaningful(cur / name)]
    if missing and not args.allow_incomplete:
        raise ArxError(f"current iteration is incomplete; missing meaningful files: {', '.join(missing)}")

    hypothesis = load_current_yaml(root, "hypothesis.yaml")
    iteration_id = str(hypothesis.get("iteration_id") or args.label or "iteration")
    timestamp = utc_now().replace(":", "").replace("-", "")
    dest = archive_dir(root) / f"{timestamp}-{slug(iteration_id)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cur), str(dest))
    write_yaml(dest / "archive_manifest.yaml", {
        "archived_at": utc_now(),
        "iteration_id": iteration_id,
        "allow_incomplete": args.allow_incomplete,
        "missing_at_archive": missing,
    })
    print(f"Archived current iteration to {dest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")