from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
COMMON = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
sys.path.insert(0, str(COMMON))


@dataclass(frozen=True)
class HookEvent:
    payload: dict[str, Any]

    @property
    def session_id(self) -> str:
        return str(self.payload.get("session_id") or "")

    @property
    def turn_id(self) -> str:
        return str(self.payload.get("turn_id") or self.payload.get("prompt_id") or "")

    @property
    def tool_use_id(self) -> str:
        return str(self.payload.get("tool_use_id") or "")

    @property
    def tool_name(self) -> str:
        return str(self.payload.get("tool_name") or "")

    @property
    def cwd(self) -> Path:
        return Path(str(self.payload.get("cwd") or Path.cwd())).resolve()

    @property
    def command(self) -> str:
        tool_input = self.payload.get("tool_input")
        if isinstance(tool_input, dict):
            command = tool_input.get("command")
            if command:
                return str(command)
        return str(self.payload.get("command") or self.payload.get("cmd") or "")

    @property
    def stop_hook_active(self) -> bool:
        return self.payload.get("stop_hook_active") is True


def _stdin_payload_text(*, command: str = "") -> str:
    """Read Codex JSON from stdin without hanging CLI/tests that leave stdin open."""
    if sys.stdin.isatty():
        return ""
    # Prefer a non-blocking peek so subprocess tests without input= do not hang.
    try:
        import select

        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return ""
    except (ImportError, OSError, ValueError):
        if command:
            return ""
    return sys.stdin.read().strip()


def read_event(*, cwd: str = "", command: str = "") -> HookEvent:
    payload: dict[str, Any] = {}
    text = _stdin_payload_text(command=command)
    if text:
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = {"command": text, "malformed_input": True}
        if isinstance(loaded, dict):
            payload.update(loaded)
    if cwd:
        payload["cwd"] = cwd
    if command:
        payload.setdefault("tool_name", "Bash")
        payload["tool_input"] = {"command": command}
    return HookEvent(payload)


# Stop upward search at these markers so a package without .research does not
# inherit an ancestor campaign's hooks.
PROJECT_BOUNDARY_MARKERS = (
    ".git",
    ".arx-boundary",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "composer.json",
    "Gemfile",
    "mix.exs",
)


def is_project_boundary(path: Path) -> bool:
    return any((path / name).exists() for name in PROJECT_BOUNDARY_MARKERS)


def find_research_root(cwd: Path) -> Path | None:
    resolved = Path(cwd).resolve()
    for path in [resolved, *resolved.parents]:
        if (path / ".research" / "current").exists():
            return path / ".research"
        if is_project_boundary(path):
            return None
    return None


def additional_context(event_name: str, message: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": message,
        }
    }


def system_warning(message: str, *, stop: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"systemMessage": message}
    if stop:
        payload.update({"continue": False, "stopReason": message})
    return payload


def emit(payload: dict[str, Any] | None) -> None:
    if payload:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
