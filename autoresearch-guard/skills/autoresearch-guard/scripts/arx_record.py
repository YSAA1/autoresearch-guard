from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from arx_common import (
    ArxError,
    add_common_args,
    append_jsonl,
    current_dir,
    extract_dotted,
    load_json,
    parse_key_value,
    sha256_file,
    utc_now,
)


def parse_metric_from_json(items: list[str], result_data: Any) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ArxError(f"expected NAME=path.to.value, got {item}")
        name, dotted = item.split("=", 1)
        try:
            metrics[name.strip()] = extract_dotted(result_data, dotted.strip())
        except Exception as exc:
            raise ArxError(f"could not extract metric {name} from JSON path {dotted}") from exc
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Append deterministic evidence to evidence_ledger.jsonl.")
    add_common_args(parser)
    parser.add_argument("--iteration-id", required=True)
    parser.add_argument("--command", required=True, help="Exact command or operation that produced the evidence")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--data-split", default="validation")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--config-file")
    parser.add_argument("--result-file")
    parser.add_argument("--metric", action="append", default=[], help="Metric as KEY=VALUE, repeatable")
    parser.add_argument("--metric-from-json", action="append", default=[], help="Metric as NAME=path.to.value from --result-file JSON")
    parser.add_argument("--code-ref", default="unknown")
    parser.add_argument("--role", default="experiment", choices=["experiment", "baseline"], help="Evidence role for audit gates")
    parser.add_argument("--status", default="recorded", choices=["recorded", "pass", "fail", "error"])
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    root = Path(args.research_root).resolve()
    cur = current_dir(root)
    if not cur.exists():
        raise ArxError(f"missing current directory: {cur}")

    result_file = str(Path(args.result_file).resolve()) if args.result_file else ""
    result_digest = ""
    result_data = None
    if result_file:
        path = Path(result_file)
        if not path.exists():
            raise ArxError(f"result file does not exist: {path}")
        result_digest = sha256_file(path)
        if path.suffix.lower() == ".json":
            result_data = load_json(path)

    metrics = parse_key_value(args.metric)
    if args.metric_from_json:
        if result_data is None:
            raise ArxError("--metric-from-json requires --result-file pointing to a JSON file")
        metrics.update(parse_metric_from_json(args.metric_from_json, result_data))

    config_file = str(Path(args.config_file).resolve()) if args.config_file else ""
    config_digest = ""
    if config_file:
        path = Path(config_file)
        if not path.exists():
            raise ArxError(f"config file does not exist: {path}")
        config_digest = sha256_file(path)

    record = {
        "iteration_id": args.iteration_id,
        "timestamp": utc_now(),
        "command": args.command,
        "exit_code": args.exit_code,
        "data_split": args.data_split,
        "seed": args.seed,
        "config_file": config_file,
        "config_digest": config_digest,
        "result_file": result_file,
        "result_digest": result_digest,
        "metrics": metrics,
        "code_ref": args.code_ref,
        "role": args.role,
        "status": args.status,
        "notes": args.notes,
    }
    append_jsonl(cur / "evidence_ledger.jsonl", record)
    print(f"Recorded evidence for {args.iteration_id}: {len(metrics)} metric(s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArxError as exc:
        raise SystemExit(f"ERROR: {exc}")
