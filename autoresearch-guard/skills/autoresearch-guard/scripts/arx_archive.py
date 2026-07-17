from __future__ import annotations

import argparse

from arx_common import (
    ArxError,
    add_common_args,
)
from arx_lifecycle import archive_current


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive completed AutoResearch Guard current state.")
    add_common_args(parser)
    parser.add_argument("--allow-incomplete", action="store_true", help="Archive even if closure files are incomplete")
    parser.add_argument("--reason", default="", help="Required reason for --allow-incomplete recovery archives")
    parser.add_argument("--label", default="", help="Optional archive label")
    args = parser.parse_args()

    destination = archive_current(
        args.research_root,
        allow_incomplete=args.allow_incomplete,
        reason=args.reason,
        label=args.label,
    )
    print(f"Archived current iteration to {destination}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")
