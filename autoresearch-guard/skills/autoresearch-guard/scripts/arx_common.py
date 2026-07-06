from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml as _yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _yaml = None


DECISIONS = {"proceed", "refine", "pivot", "stop", "promote"}
PROMOTE_BLOCKERS = {"evidence", "protocol", "test", "gate", "blocked_action"}


class ArxError(RuntimeError):
    pass


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> _dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return value or "iteration"


def as_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def current_dir(research_root: str | Path) -> Path:
    return as_path(research_root) / "current"


def lessons_dir(research_root: str | Path) -> Path:
    return as_path(research_root) / "lessons"


def archive_dir(research_root: str | Path) -> Path:
    return as_path(research_root) / "archive"


def script_root() -> Path:
    return Path(__file__).resolve().parent


def skill_root() -> Path:
    return script_root().parent


def template_dir() -> Path:
    return skill_root() / "templates"


def ensure_current(research_root: str | Path) -> Path:
    cur = current_dir(research_root)
    if not cur.exists():
        raise ArxError(f"missing current research directory: {cur}")
    return cur


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: str | Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def append_text(path: str | Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except Exception:
            return value
    try:
        if re.fullmatch(r"[-+]?\d+", value):
            return int(value)
        if re.fullmatch(r"[-+]?(\d+\.\d*|\d*\.\d+)([eE][-+]?\d+)?", value):
            return float(value)
    except Exception:
        pass
    return value


def _format_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or text.startswith(("{", "[")) or ":" in text or "#" in text or text.strip() != text:
        return json.dumps(text, ensure_ascii=True)
    return text


def _clean_yaml_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))
    return lines


def _is_list_line(content: str) -> bool:
    return content == "-" or content.startswith("- ")


def _list_content(content: str) -> str:
    return "" if content == "-" else content[2:].strip()


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    if lines[index][0] < indent:
        return {}, index

    is_list = lines[index][0] == indent and _is_list_line(lines[index][1])
    if is_list:
        items: list[Any] = []
        while index < len(lines) and lines[index][0] == indent and _is_list_line(lines[index][1]):
            content = _list_content(lines[index][1])
            index += 1
            if content == "":
                value, index = _parse_block(lines, index, indent + 2)
                items.append(value)
            elif ":" in content:
                key, raw_value = content.split(":", 1)
                item: dict[str, Any] = {}
                if raw_value.strip():
                    item[key.strip()] = _parse_scalar(raw_value.strip())
                else:
                    value, index = _parse_block(lines, index, indent + 2)
                    item[key.strip()] = value
                if index < len(lines) and lines[index][0] > indent:
                    extra, index = _parse_block(lines, index, indent + 2)
                    if isinstance(extra, dict):
                        item.update(extra)
                items.append(item)
            else:
                items.append(_parse_scalar(content))
        return items, index

    data: dict[str, Any] = {}
    while index < len(lines) and lines[index][0] == indent and not _is_list_line(lines[index][1]):
        content = lines[index][1]
        if ":" not in content:
            raise ArxError(f"invalid yaml line: {content}")
        key, raw_value = content.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        index += 1
        if raw_value:
            data[key] = _parse_scalar(raw_value)
        elif index < len(lines) and lines[index][0] > indent:
            value, index = _parse_block(lines, index, lines[index][0])
            data[key] = value
        else:
            data[key] = ""
    return data, index


def parse_simple_yaml(text: str) -> Any:
    lines = _clean_yaml_lines(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ArxError("could not parse complete yaml document")
    return value


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    text = read_text(path)
    if _yaml is not None:
        loaded = _yaml.safe_load(text) or {}
    else:
        loaded = parse_simple_yaml(text) or {}
    if not isinstance(loaded, dict):
        raise ArxError(f"expected mapping in {path}")
    return loaded


def _dump_yaml(value: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.extend(_dump_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_format_scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{pad}[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.extend(_dump_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}- {_format_scalar(item)}")
        return lines
    return [f"{pad}{_format_scalar(value)}"]


def dump_yaml(data: dict[str, Any]) -> str:
    return "\n".join(_dump_yaml(data)) + "\n"


def write_yaml(path: str | Path, data: dict[str, Any]) -> None:
    if _yaml is not None:
        text = _yaml.safe_dump(data, sort_keys=False, allow_unicode=False)
    else:
        text = dump_yaml(data)
    write_text(path, text)


def load_json(path: str | Path) -> Any:
    return json.loads(read_text(path))


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArxError(f"invalid jsonl at {path}:{line_no}: {exc}") from exc
        if not isinstance(item, dict):
            raise ArxError(f"jsonl row is not an object at {path}:{line_no}")
        rows.append(item)
    return rows


def append_jsonl(path: str | Path, item: dict[str, Any]) -> None:
    append_text(path, json.dumps(item, ensure_ascii=True, sort_keys=True) + "\n")


def render_template(path: str | Path, context: dict[str, Any]) -> str:
    text = read_text(path)
    try:
        from jinja2 import Template  # type: ignore
    except Exception:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            return str(context.get(key, ""))
        return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replace, text)
    return Template(text).render(**context)


def listify(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def markdown_list(values: Iterable[Any], empty: str = "- none") -> str:
    values = list(values)
    if not values:
        return empty
    return "\n".join(f"- {v}" for v in values)


def _split_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_markdown_separator(line: str) -> bool:
    cells = _split_markdown_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def parse_markdown_tables(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines = text.splitlines()
    section = ""
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
            index += 1
            continue
        if (
            stripped.startswith("|")
            and index + 1 < len(lines)
            and lines[index + 1].strip().startswith("|")
            and _is_markdown_separator(lines[index + 1])
        ):
            headers = _split_markdown_table_row(stripped)
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = _split_markdown_table_row(lines[index])
                item = {headers[i]: cells[i] if i < len(cells) else "" for i in range(len(headers))}
                item["_section"] = section
                rows.append(item)
                index += 1
            continue
        index += 1
    return rows


def extract_dotted(data: Any, path: str) -> Any:
    value = data
    for part in path.split("."):
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list):
            value = value[int(part)]
        else:
            raise KeyError(path)
    return value


def parse_key_value(values: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in values:
        if "=" not in item:
            raise ArxError(f"expected KEY=VALUE, got {item}")
        key, value = item.split("=", 1)
        parsed[key.strip()] = _parse_scalar(value.strip())
    return parsed


def update_state(research_root: str | Path, **updates: Any) -> dict[str, Any]:
    path = current_dir(research_root) / "state.yaml"
    state = load_yaml(path)
    state.update(updates)
    state["updated_at"] = utc_now()
    write_yaml(path, state)
    return state


def latest_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    return entries[-1] if entries else None


def command_mentions_split(command: str, split: str) -> bool:
    split = re.escape(split.lower())
    command = command.lower()
    patterns = [
        rf"--split\s+{split}\b",
        rf"--split={split}\b",
        rf"split\s*=\s*{split}\b",
        rf"/{split}/",
        rf"\\{split}\\",
    ]
    return any(re.search(pattern, command) for pattern in patterns)


def contains_pattern(command: str, pattern: str) -> bool:
    return pattern.lower() in command.lower()


def load_current_yaml(research_root: str | Path, name: str) -> dict[str, Any]:
    return load_yaml(current_dir(research_root) / name)


def research_hooks_enabled(research_root: str | Path) -> bool:
    try:
        state = load_current_yaml(research_root, "state.yaml")
    except Exception:
        return False
    return state.get("hooks_enabled") is True


def fail(message: str, code: int = 1) -> None:
    raise SystemExit(f"ERROR: {message}")


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--research-root", default=".research", help="Research root directory, default .research")
