from __future__ import annotations

import argparse
from pathlib import Path

from arx_common import (
    ArxError,
    add_common_args,
    archive_dir,
    current_dir,
    lessons_dir,
    markdown_list,
    render_template,
    research_lock,
    template_dir,
    utc_now,
    write_text,
)
from arx_lifecycle import archive_current


def yaml_dq_content(value: str) -> str:
    return value.replace("\\", "\\\\").replace(chr(34), "\\" + chr(34))


def render(name: str, context: dict[str, str]) -> str:
    return render_template(template_dir() / name, context)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize .research state for AutoResearch Guard.")
    add_common_args(parser)
    parser.add_argument("--iteration-id", required=True, help="Stable iteration id, for example DOVE-H3-I2")
    parser.add_argument("--title", default="Research iteration", help="Human title for hypothesis.yaml")
    parser.add_argument("--objective", default="TBD by AI", help="Initial objective placeholder or AI-authored objective")
    parser.add_argument("--hypothesis", default="TBD by AI", help="Initial hypothesis placeholder or AI-authored hypothesis")
    parser.add_argument("--archive-existing", action="store_true", help="Archive a ready current iteration before initializing")
    parser.add_argument("--force", action="store_true", help="Recovery mode: archive an incomplete current iteration instead of overwriting it")
    parser.add_argument("--force-reason", default="", help="Required recovery reason when --force archives incomplete state")
    parser.add_argument("--enable-hooks", action="store_true", help="Enable AutoResearch Guard hooks for this .research state")
    args = parser.parse_args()

    root = Path(args.research_root).resolve()
    cur = current_dir(root)
    archive = archive_dir(root)
    lessons = lessons_dir(root)
    if args.archive_existing and args.force:
        raise ArxError("use either --archive-existing or --force, not both")

    with research_lock(root):
        if cur.exists() and any(cur.iterdir()):
            if args.archive_existing:
                archive_current(root)
            elif args.force:
                if not args.force_reason.strip():
                    raise ArxError("--force requires --force-reason; existing state will be recovery-archived")
                archive_current(root, allow_incomplete=True, reason=args.force_reason)
            else:
                raise ArxError(f"{cur} already exists; use --archive-existing for a closed loop or --force with --force-reason for recovery")

        timestamp = utc_now()
        cur.mkdir(parents=True, exist_ok=True)
        lessons.mkdir(parents=True, exist_ok=True)
        archive.mkdir(parents=True, exist_ok=True)

        context = {
            "iteration_id": yaml_dq_content(args.iteration_id),
            "timestamp": yaml_dq_content(timestamp),
            "research_root": yaml_dq_content(str(root)),
            "title": yaml_dq_content(args.title),
            "objective": yaml_dq_content(args.objective),
            "hypothesis": yaml_dq_content(args.hypothesis),
            "hooks_enabled": "true" if args.enable_hooks else "false",
        }

        files = {
            "state.yaml": render("state.yaml.j2", context),
            "hypothesis.yaml": render("hypothesis.yaml.j2", context),
            "protocol.lock.yaml": render("protocol.yaml.j2", context),
            "blocked_actions.yaml": render("blocked_actions.yaml.j2", context),
            "claim_boundary.yaml": render("claim_boundary.yaml.j2", context),
            "literature_review.md": render("literature_review.md.j2", context),
            "ai_evidence_review.md": render("ai_evidence_review.md.j2", context),
            "next_goal.md": "# Next Goal\n\nTBD by AI after decision.yaml is committed.\n",
            "evidence_ledger.jsonl": "",
            "events.jsonl": "",
        }

        for name, content in files.items():
            write_text(cur / name, content)

        retained = lessons / "retained_lessons.md"
        if not retained.exists():
            write_text(retained, "# Retained Lessons\n\n")
        anti = lessons / "anti_patterns.yaml"
        if not anti.exists():
            write_text(anti, "anti_patterns: []\n")

    created = markdown_list(sorted(files))
    print(f"Initialized AutoResearch Guard state at {root}")
    print(created)
    print("Protocol starts unlocked. --allow-unlocked only renders active_goal.draft.md; it cannot arm execution.")
    print(f"Hooks enabled: {str(args.enable_hooks).lower()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")
