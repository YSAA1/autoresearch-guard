"""Independent cross-platform simulation for AutoResearch Guard Codex hooks.

These tests do not depend on the host OS being Windows. They simulate:
1. Unix `${PLUGIN_ROOT}` command templates
2. Windows `%PLUGIN_ROOT%` + backslash command templates
3. Launcher portability (`node` instead of `python` / `py -3`)
4. Python discovery when `python` is missing but `python3` (or ARX_PYTHON) remains
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOKS = PLUGIN_ROOT / "hooks"
SCRIPTS = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
NODE = shutil.which("node") or "node"


class HooksCrossPlatformSimulationTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is required for hook cross-platform simulation")

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.plugin_copy = self.root / "plugin install copy"
        shutil.copytree(PLUGIN_ROOT, self.plugin_copy)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def hook_env(self, *, path: str | None = None, arx_python: str | None = None) -> dict[str, str]:
        env = dict(os.environ)
        if arx_python is None:
            env["ARX_PYTHON"] = sys.executable
        elif arx_python:
            env["ARX_PYTHON"] = arx_python
        else:
            env.pop("ARX_PYTHON", None)
        if path is not None:
            env["PATH"] = path
        return env

    def load_manifest_hooks(self) -> list[dict[str, object]]:
        manifest = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
        hooks: list[dict[str, object]] = []
        for entries in manifest["hooks"].values():
            for entry in entries:
                hooks.extend(entry["hooks"])
        return hooks

    def substitute_unix(self, command: str, plugin_root: Path) -> str:
        return command.replace("${PLUGIN_ROOT}", str(plugin_root))

    def substitute_windows(self, command: str, plugin_root: Path) -> str:
        # Codex expands %PLUGIN_ROOT% on Windows; we simulate that here.
        expanded = command.replace("%PLUGIN_ROOT%", str(plugin_root))
        # On a non-Windows host, normalize separators so node can open the file while
        # still proving the manifest used Windows-style %PLUGIN_ROOT% and backslashes.
        if os.name != "nt":
            if not expanded.startswith("node "):
                raise AssertionError(f"expected node launcher, got: {expanded}")
            prefix, script = expanded.split(" ", 1)
            script = script.strip().strip('"').replace("\\", "/")
            return f'{prefix} "{script}"'
        return expanded

    def run_shell_hook(
        self,
        command: str,
        *,
        cwd: Path,
        payload: dict[str, object],
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            text=True,
            input=json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env or self.hook_env(),
        )

    def run_script(self, name: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def assert_ok(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def prepare_running_campaign(
        self,
        workspace: Path,
        iteration_id: str,
        session_id: str,
    ) -> Path:
        research = workspace / ".research"
        self.assert_ok(
            self.run_script(
                "arx_init.py",
                "--research-root",
                str(research),
                "--iteration-id",
                iteration_id,
                "--title",
                f"Iteration {iteration_id}",
                "--objective",
                "Cross-platform hook simulation",
                "--hypothesis",
                "Node-launched hooks work on Unix and Windows templates",
                "--enable-hooks",
                cwd=workspace,
            )
        )
        cur = research / "current"
        (cur / "hypothesis.yaml").write_text(
            f"iteration_id: {iteration_id}\n"
            f"title: Iteration {iteration_id}\n"
            "objective: Cross-platform hook simulation\n"
            "hypothesis: Node-launched hooks work on Unix and Windows templates\n"
            "rationale: simulation fixture\n"
            "expected_signal: score meets the validation gate\n"
            "evidence_basis: idea-1\n"
            "reuse_plan:\n"
            "  base: impl-1\n"
            "  build_new_reason: \"\"\n"
            "allowed_work:\n"
            "  - run validation fixtures\n"
            "forbidden_work:\n"
            "  - touch test split\n"
            "must_produce:\n"
            "  - evidence_ledger.jsonl\n"
            "  - audit_report.yaml\n"
            "  - ai_evidence_review.md\n"
            "  - decision.yaml\n",
            encoding="utf-8",
        )
        (cur / "protocol.lock.yaml").write_text(
            "locked: true\n"
            "allowed_splits:\n"
            "  - train\n"
            "  - validation\n"
            "forbidden_splits:\n"
            "  - test\n"
            "expected_metrics:\n"
            "  - score\n"
            "validation_gates:\n"
            "  - metric: score\n"
            "    operator: '>='\n"
            "    value: 0.5\n"
            "    split: validation\n"
            "    aggregation: latest\n"
            "baseline:\n"
            "  required: false\n"
            "require_seed: false\n"
            "spiral_budget:\n"
            "  max_failed_attempts: 3\n"
            "  max_flatline_count: 3\n"
            "  max_total_attempts: 32\n"
            "required_outputs:\n"
            "  - evidence_ledger.jsonl\n"
            "  - audit_report.yaml\n"
            "  - ai_evidence_review.md\n"
            "  - decision.yaml\n",
            encoding="utf-8",
        )
        (cur / "literature_review.md").write_text(
            "# Literature Review\n\n"
            "## Candidate ideas\n\n"
            "| idea_id | description | evidence | gap |\n"
            "| --- | --- | --- | --- |\n"
            "| idea-1 | deterministic validation | local fixture | scoped gap |\n\n"
            "## Existing implementations\n\n"
            "| impl_id | url | covered_capability | reuse_decision |\n"
            "| --- | --- | --- | --- |\n"
            "| impl-1 | local://offline-baseline | baseline | reuse |\n",
            encoding="utf-8",
        )
        (cur / "claim_boundary.yaml").write_text(
            "claims:\n"
            "  - claim_id: c1\n"
            "    statement: validation score meets the declared gate\n"
            "    support_level: supported\n",
            encoding="utf-8",
        )
        self.assert_ok(
            self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=workspace)
        )
        self.assert_ok(
            self.run_script(
                "arx_loop.py",
                "start",
                "--research-root",
                str(research),
                "--session-id",
                session_id,
                cwd=workspace,
            )
        )
        return research

    def test_manifest_uses_node_on_both_platforms_not_python_launchers(self) -> None:
        hooks = self.load_manifest_hooks()
        self.assertEqual(len(hooks), 2)
        for hook in hooks:
            command = str(hook["command"])
            windows = str(hook["commandWindows"])
            self.assertTrue(command.startswith("node "), command)
            self.assertTrue(windows.startswith("node "), windows)
            self.assertIn("${PLUGIN_ROOT}", command)
            self.assertIn("%PLUGIN_ROOT%", windows)
            self.assertNotIn("${PLUGIN_ROOT}", windows)
            self.assertIn("\\hooks\\", windows)
            self.assertNotIn("python", command.lower())
            self.assertNotIn("python", windows.lower())
            self.assertNotIn("py -3", windows.lower())

    def test_unix_and_windows_templates_resolve_to_same_scripts(self) -> None:
        hooks = self.load_manifest_hooks()
        for hook in hooks:
            unix_cmd = self.substitute_unix(str(hook["command"]), self.plugin_copy)
            win_cmd = self.substitute_windows(str(hook["commandWindows"]), self.plugin_copy)
            unix_script = unix_cmd.split(" ", 1)[1].strip().strip('"')
            win_script = win_cmd.split(" ", 1)[1].strip().strip('"')
            self.assertTrue(Path(unix_script).is_file(), unix_script)
            self.assertTrue(Path(win_script).is_file(), win_script)
            self.assertEqual(Path(unix_script).resolve(), Path(win_script).resolve())

    def test_simulated_unix_and_windows_commands_both_execute(self) -> None:
        hooks = self.load_manifest_hooks()
        session_hook = next(h for h in hooks if "session_recovery" in str(h["command"]))
        stop_hook = next(h for h in hooks if "stop_goal_guard" in str(h["command"]))
        report: list[str] = []

        # SessionStart is read-mostly; Unix/Windows can share one campaign.
        session_ws = self.root / "session-ws"
        session_ws.mkdir()
        self.prepare_running_campaign(session_ws, "xplat-i1", "owner-session")
        for label, builder in (
            ("unix", lambda h: self.substitute_unix(str(h["command"]), self.plugin_copy)),
            ("windows", lambda h: self.substitute_windows(str(h["commandWindows"]), self.plugin_copy)),
        ):
            command = builder(session_hook)
            result = self.run_shell_hook(
                command,
                cwd=session_ws,
                payload={
                    "session_id": "owner-session",
                    "turn_id": "resume-1",
                    "cwd": str(session_ws),
                    "hook_event_name": "SessionStart",
                    "source": "resume",
                },
            )
            self.assertEqual(
                result.returncode,
                0,
                f"{label}/session_recovery.js failed\ncmd={command}\nstdout={result.stdout}\nstderr={result.stderr}",
            )
            payload = json.loads(result.stdout)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn("xplat-i1", context)
            self.assertIn("arx_loop.py check", context)
            report.append(f"{label}/session_recovery.js: ok")

        # Stop mutates continuation budget; isolate each platform run.
        for label, builder in (
            ("unix", lambda h: self.substitute_unix(str(h["command"]), self.plugin_copy)),
            ("windows", lambda h: self.substitute_windows(str(h["commandWindows"]), self.plugin_copy)),
        ):
            stop_ws = self.root / f"stop-{label}-ws"
            stop_ws.mkdir()
            self.prepare_running_campaign(stop_ws, f"xplat-stop-{label}", "owner-session")
            command = builder(stop_hook)
            result = self.run_shell_hook(
                command,
                cwd=stop_ws,
                payload={
                    "session_id": "owner-session",
                    "turn_id": "stop-1",
                    "cwd": str(stop_ws),
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                },
            )
            self.assertEqual(
                result.returncode,
                0,
                f"{label}/stop_goal_guard.js failed\ncmd={command}\nstdout={result.stdout}\nstderr={result.stderr}",
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload.get("decision"), "block", payload)
            self.assertIn("AutoResearch Guard", str(payload.get("reason") or ""))
            report.append(f"{label}/stop_goal_guard.js: ok")

        self.assertEqual(
            report,
            [
                "unix/session_recovery.js: ok",
                "windows/session_recovery.js: ok",
                "unix/stop_goal_guard.js: ok",
                "windows/stop_goal_guard.js: ok",
            ],
        )

    def test_hooks_survive_when_python_launcher_missing_from_path(self) -> None:
        """Codex used to call `python`/`py -3` directly; those names may be absent.

        Simulate a PATH that has node + python3, but not `python` or `py`.
        """
        bin_dir = self.root / "fake-bin"
        bin_dir.mkdir()

        node_src = shutil.which("node")
        python3_src = shutil.which("python3") or sys.executable
        self.assertTrue(node_src)
        self.assertTrue(python3_src)

        os.symlink(node_src, bin_dir / "node")
        os.symlink(python3_src, bin_dir / "python3")

        # Intentionally do NOT provide `python` or `py`.
        path = f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"
        hook = next(h for h in self.load_manifest_hooks() if "stop_goal_guard" in str(h["command"]))

        for label, builder in (
            ("unix", lambda h: self.substitute_unix(str(h["command"]), self.plugin_copy)),
            ("windows", lambda h: self.substitute_windows(str(h["commandWindows"]), self.plugin_copy)),
        ):
            workspace = self.root / f"path-{label}-ws"
            workspace.mkdir()
            self.prepare_running_campaign(workspace, f"path-{label}", "path-owner")
            command = builder(hook)
            result = self.run_shell_hook(
                command,
                cwd=workspace,
                payload={
                    "session_id": "path-owner",
                    "turn_id": "stop-path",
                    "cwd": str(workspace),
                    "hook_event_name": "Stop",
                },
                env=self.hook_env(path=path, arx_python=""),
            )
            self.assertEqual(
                result.returncode,
                0,
                f"{label} failed without python/py on PATH\ncmd={command}\nstdout={result.stdout}\nstderr={result.stderr}",
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload.get("decision"), "block", payload)

    def test_arx_python_override_works_with_node_entry(self) -> None:
        wrapper = self.root / "python-wrapper"
        log = self.root / "python-wrapper.log"
        wrapper.write_text(
            "#!/bin/sh\n"
            f'echo "$# $*" >> "{log}"\n'
            f'exec "{sys.executable}" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

        self.prepare_running_campaign(self.workspace, "env-i1", "env-owner")
        command = self.substitute_unix(
            'node "${PLUGIN_ROOT}/hooks/session_recovery.js"',
            self.plugin_copy,
        )
        result = self.run_shell_hook(
            command,
            cwd=self.workspace,
            payload={
                "session_id": "env-owner",
                "cwd": str(self.workspace),
                "hook_event_name": "SessionStart",
            },
            env=self.hook_env(arx_python=str(wrapper)),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(log.exists(), "ARX_PYTHON wrapper was not invoked")
        self.assertIn("arx_bridge.py", log.read_text(encoding="utf-8"))
        payload = json.loads(result.stdout)
        self.assertIn("env-i1", payload["hookSpecificOutput"]["additionalContext"])

    def test_direct_node_invocation_matrix(self) -> None:
        """Bypass shell templates and prove both scripts accept Codex JSON on stdin."""
        self.prepare_running_campaign(self.workspace, "matrix-i1", "matrix-owner")
        cases = [
            (
                self.plugin_copy / "hooks" / "session_recovery.js",
                {
                    "session_id": "matrix-owner",
                    "cwd": str(self.workspace),
                    "hook_event_name": "SessionStart",
                },
                "session",
            ),
            (
                self.plugin_copy / "hooks" / "stop_goal_guard.js",
                {
                    "session_id": "matrix-owner",
                    "turn_id": "t1",
                    "cwd": str(self.workspace),
                    "hook_event_name": "Stop",
                },
                "stop",
            ),
        ]
        for script, payload, kind in cases:
            with self.subTest(script=script.name):
                result = subprocess.run(
                    [NODE, str(script)],
                    cwd=str(self.workspace),
                    text=True,
                    input=json.dumps(payload),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=self.hook_env(),
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                parsed = json.loads(result.stdout)
                if kind == "session":
                    self.assertIn("matrix-i1", parsed["hookSpecificOutput"]["additionalContext"])
                else:
                    self.assertEqual(parsed.get("decision"), "block", parsed)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HooksCrossPlatformSimulationTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("\n=== Cross-platform hook simulation summary ===")
    print(f"ran={result.testsRun} failures={len(result.failures)} errors={len(result.errors)}")
    if result.wasSuccessful():
        print("VERDICT: PASS")
        print("- Unix `${PLUGIN_ROOT}` and Windows `%PLUGIN_ROOT%\\...` templates both execute via node")
        print("- SessionStart injects recovery context; Stop returns decision=block on incomplete owner loops")
        print("- Hooks still work when `python`/`py` are absent from PATH (python3 discovery)")
        print("- ARX_PYTHON override and direct node stdin JSON protocol both work")
        return 0
    print("VERDICT: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
