from __future__ import annotations

import json
import re
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
            # Codex passes tool-specific input. apply_patch uses a patch body,
            # while Edit/Write expose a path plus replacement/content fields.
            # Fold those fields into one inspection string so the protocol gate
            # does not depend on a Bash-shaped payload.
            inspection_fields = (
                "file_path",
                "path",
                "patch",
                "input",
                "old_string",
                "new_string",
                "content",
                "text",
            )
            parts = [str(tool_input[key]) for key in inspection_fields if tool_input.get(key) is not None]
            if parts:
                return "\n".join(parts)
        return str(self.payload.get("command") or self.payload.get("cmd") or "")

    @property
    def stop_hook_active(self) -> bool:
        return self.payload.get("stop_hook_active") is True


def read_event(*, cwd: str = "", command: str = "") -> HookEvent:
    payload: dict[str, Any] = {}
    if not sys.stdin.isatty():
        text = sys.stdin.read().strip()
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


def find_research_root(cwd: Path) -> Path | None:
    for path in [cwd, *cwd.parents]:
        if (path / ".research" / "current").exists():
            return path / ".research"
    return None


def likely_experiment(command: str) -> bool:
    lower = command.lower()
    patterns = (
        r"(?<![\w.-])[\w./\\-]*(?:train|eval|evaluate|benchmark|experiment)[\w.-]*\.(?:py|sh|ps1)\b",
        r"(?:^|[;&|]\s*)make\s+(?:train|eval|evaluate|benchmark|experiment)\b",
        r"(?:^|[;&|]\s*)(?:train|eval|evaluate|benchmark)\b",
    )
    return any(re.search(pattern, lower) is not None for pattern in patterns)


def starts_loop(command: str) -> bool:
    normalized = re.sub(r"\s+", " ", command.lower())
    return "arx_loop.py" in normalized and re.search(r"\barx_loop\.py(?:\"|'|\s)+start\b", normalized) is not None


def touches_protocol(command: str) -> bool:
    return "protocol.lock.yaml" in command.lower()


def mutates_locked_protocol(event: HookEvent) -> bool:
    if not touches_protocol(event.command):
        return False
    tool_name = event.tool_name.lower()
    if tool_name in {"apply_patch", "edit", "write"}:
        return True
    lower = event.command.lower()
    protocol = r"[^\s;&|]*protocol\.lock\.yaml"
    mutation_patterns = (
        rf"(?:^|\s)(?:>>?|\d>>?)\s*[\"']?{protocol}",
        rf"\b(?:rm|unlink|truncate)\b[^\n;&|]*{protocol}",
        rf"\b(?:set-content|out-file|add-content)\b[^\n;&|]*{protocol}",
        rf"\btee\b[^\n;&|]*{protocol}",
        rf"\bdd\b[^\n;&|]*\bof=[\"']?{protocol}",
        rf"\bsed\b[^\n;&|]*\s-i(?:\s|[.\"'])[^\n;&|]*{protocol}",
        rf"\bperl\b[^\n;&|]*\s-pi[^\n;&|]*{protocol}",
        rf"\b(?:cp|mv|install)\b[^\n;&|]*\s[\"']?{protocol}[\"']?\s*$",
    )
    return any(re.search(pattern, lower) is not None for pattern in mutation_patterns)


def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


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
