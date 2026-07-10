from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
ARX = SCRIPTS / "arx.py"
HOOKS = PLUGIN_ROOT / "hooks"

sys.path.insert(0, str(SCRIPTS))


class ArxCliTest(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(os.environ.get("ARX_TEST_TMP", tempfile.gettempdir()))
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.cwd = Path(self.temporary.name)
        self.research = self.cwd / ".research"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_arx(self, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ARX), *arguments],
            cwd=cwd or self.cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def assert_ok(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, f"stdout={result.stdout}\nstderr={result.stderr}")

    def assert_rejected(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 2, f"stdout={result.stdout}\nstderr={result.stderr}")

    def status(self) -> dict[str, object]:
        result = self.run_arx("status", "--json")
        self.assert_ok(result)
        report = json.loads(result.stdout)
        self.assertEqual(
            set(report),
            {"state", "session", "verification", "can_finish_verified", "reasons", "next_actions"},
        )
        return report

    def write_contract(self, name: str, checks: list[dict[str, str]] | None = None) -> Path:
        path = self.cwd / name
        path.write_text(
            json.dumps(
                {
                    "claim": "本轮结论有足够证据支持",
                    "checks": checks
                    or [
                        {
                            "id": "source-check",
                            "criterion": "来源覆盖结论的核心事实",
                            "method": "核对来源和笔记",
                            "evidence_required": "可访问的来源链接",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def start(self, goal: str = "比较两个方案") -> None:
        self.assert_ok(self.run_arx("start", "--goal", goal))

    def lock(self, contract: Path, *extra: str) -> None:
        self.assert_ok(self.run_arx("verify", "lock", "--file", str(contract), *extra))

    def record(
        self,
        check_id: str,
        verdict: str,
        evidence: list[str] | None = None,
        reason: str = "检查完成",
    ) -> subprocess.CompletedProcess[str]:
        command = ["verify", "record", "--check", check_id, "--verdict", verdict]
        if evidence is not None:
            command.extend(["--evidence", *evidence])
        command.extend(["--reason", reason])
        return self.run_arx(*command)

    def test_status_and_start_create_only_minimal_v3_state(self) -> None:
        idle = self.status()
        self.assertEqual(idle["state"], "idle")
        self.assertIsNone(idle["session"])

        self.start("整理现有实现的行为")
        active = self.status()
        self.assertEqual(active["state"], "active")
        session = active["session"]
        self.assertIsInstance(session, dict)
        self.assertEqual(session["goal"], "整理现有实现的行为")
        self.assertEqual(session["schema_version"], 3)
        self.assertEqual((self.research / "current" / "session.json").exists(), True)
        self.assertEqual((self.research / "current" / "verifications").is_dir(), True)
        self.assertFalse((self.research / "current" / "state.yaml").exists())
        self.assert_rejected(self.run_arx("start", "--goal", "不能覆盖当前研究"))

    def test_verified_path_locks_contract_records_evidence_and_archives(self) -> None:
        self.start()
        contract = self.write_contract(
            "contract.json",
            [
                {
                    "id": "sources",
                    "criterion": "关键说法都有来源",
                    "method": "逐项核对",
                    "evidence_required": "来源 URL",
                },
                {
                    "id": "artifact",
                    "criterion": "代码行为已复现",
                    "method": "运行测试",
                    "evidence_required": "测试产物路径",
                },
            ],
        )
        self.lock(contract)
        self.assert_ok(self.record("sources", "pass", ["https://example.test/note"], "来源已核对"))
        self.assert_ok(self.record("artifact", "pass", ["tests/report.txt"], "测试通过"))

        ready = self.status()
        self.assertTrue(ready["can_finish_verified"])
        self.assert_ok(
            self.run_arx(
                "finish",
                "--outcome",
                "verified",
                "--summary",
                "两项检查都已有可追溯证据。",
            )
        )
        self.assertFalse((self.research / "current").exists())
        archives = list((self.research / "archive").iterdir())
        self.assertEqual(len(archives), 1)
        archived_session = json.loads((archives[0] / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(archived_session["status"], "finished")
        self.assertEqual(archived_session["outcome"], "verified")
        self.assertEqual(self.status()["state"], "idle")

    def test_unverified_finish_needs_no_contract(self) -> None:
        self.start()
        self.assert_rejected(self.run_arx("finish", "--outcome", "unverified", "--summary", " "))
        self.assert_ok(
            self.run_arx(
                "finish",
                "--outcome",
                "unverified",
                "--summary",
                "只完成了探索性记录，尚未建立验证契约。",
            )
        )
        archive = next((self.research / "archive").iterdir())
        session = json.loads((archive / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(session["outcome"], "unverified")

    def test_nested_directory_uses_the_nearest_existing_research_root(self) -> None:
        self.start("从子目录继续同一项研究")
        child = self.cwd / "nested" / "work"
        child.mkdir(parents=True)
        status = self.run_arx("status", "--json", cwd=child)
        self.assert_ok(status)
        report = json.loads(status.stdout)
        self.assertEqual(report["state"], "active")
        self.assertEqual(report["session"]["goal"], "从子目录继续同一项研究")
        hook = subprocess.run(
            [sys.executable, str(HOOKS / "session_recovery.py")],
            cwd=child,
            input=json.dumps({"cwd": str(child)}, ensure_ascii=False),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(hook.returncode, 0, hook.stderr)
        self.assertIn("active", hook.stdout)
        self.assert_rejected(self.run_arx("start", "--goal", "不能产生第二个状态", cwd=child))
        self.assertFalse((child / ".research").exists())

    def test_contract_and_verified_gate_reject_incomplete_or_invalid_evidence(self) -> None:
        self.start()
        invalid = self.cwd / "invalid.json"
        invalid.write_text('{"claim": "x", "checks": []}', encoding="utf-8")
        self.assert_rejected(self.run_arx("verify", "lock", "--file", str(invalid)))

        contract = self.write_contract("contract.json")
        self.lock(contract)
        self.assert_rejected(self.run_arx("verify", "lock", "--file", str(contract)))
        self.assert_rejected(self.record("missing", "pass", ["ref"], "不存在的检查"))
        self.assert_rejected(self.record("source-check", "pass", [], "缺少证据"))
        self.assert_rejected(self.run_arx("finish", "--outcome", "verified", "--summary", "尚未记录结果"))

        self.assert_ok(self.record("source-check", "unknown", reason="来源仍在确认"))
        self.assert_rejected(self.run_arx("finish", "--outcome", "verified", "--summary", "未知不能验证"))
        self.assert_ok(self.record("source-check", "fail", reason="证据不支持原说法"))
        self.assert_rejected(self.run_arx("finish", "--outcome", "verified", "--summary", "失败不能验证"))
        self.assert_ok(self.record("source-check", "pass", ["research/source.md"], "补充证据后通过"))
        self.assert_ok(self.run_arx("finish", "--outcome", "verified", "--summary", "最终检查通过"))

    def test_record_is_idempotent_and_latest_verdict_wins(self) -> None:
        self.start()
        self.lock(self.write_contract("contract.json"))
        first = self.record("source-check", "pass", ["evidence/a"], "第一次通过")
        self.assert_ok(first)
        duplicate = self.record("source-check", "pass", ["evidence/a"], "第一次通过")
        self.assert_ok(duplicate)
        self.assertIn("no-op", duplicate.stdout)
        verification = json.loads(
            (self.research / "current" / "verifications" / "v001.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(verification["results"]), 1)

        self.assert_ok(self.record("source-check", "fail", reason="复核发现来源不够"))
        self.assertFalse(self.status()["can_finish_verified"])
        self.assert_ok(self.record("source-check", "pass", ["evidence/b"], "补齐来源后通过"))
        self.assertTrue(self.status()["can_finish_verified"])

    def test_revise_preserves_old_contract_but_old_evidence_does_not_support_new_one(self) -> None:
        self.start()
        self.lock(self.write_contract("v1.json"))
        self.assert_ok(self.record("source-check", "pass", ["source/v1"], "v1 通过"))
        self.assertTrue(self.status()["can_finish_verified"])

        v2 = self.write_contract(
            "v2.json",
            [
                {
                    "id": "new-check",
                    "criterion": "新版结论满足更严格条件",
                    "method": "复核新产物",
                    "evidence_required": "新产物引用",
                }
            ],
        )
        self.lock(v2, "--revise")
        self.assertTrue((self.research / "current" / "verifications" / "v001.json").exists())
        v2_state = json.loads(
            (self.research / "current" / "verifications" / "v002.json").read_text(encoding="utf-8")
        )
        self.assertEqual(v2_state["supersedes"], 1)
        self.assertFalse(self.status()["can_finish_verified"])
        self.assert_rejected(self.run_arx("finish", "--outcome", "verified", "--summary", "旧证据不适用"))
        self.assert_ok(self.record("new-check", "pass", ["artifact/v2"], "v2 通过"))
        self.assertTrue(self.status()["can_finish_verified"])

    def test_pause_resume_and_contract_drift_behave_honestly(self) -> None:
        self.start()
        self.lock(self.write_contract("contract.json"))
        self.assert_ok(self.run_arx("pause", "--reason", "等待外部资料"))
        self.assertEqual(self.status()["state"], "paused")
        self.assert_rejected(self.record("source-check", "pass", ["source/a"], "暂停时不能记录"))
        self.assert_ok(self.run_arx("resume"))
        self.assert_ok(self.record("source-check", "pass", ["source/a"], "先记录一条结果"))

        verification_path = self.research / "current" / "verifications" / "v001.json"
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        verification["contract"]["claim"] = "被直接修改的契约"
        verification_path.write_text(json.dumps(verification), encoding="utf-8")
        record = self.record("source-check", "pass", ["source/b"], "漂移后不应写入")
        self.assertEqual(record.returncode, 1, record.stderr)
        verified = self.run_arx("finish", "--outcome", "verified", "--summary", "漂移不能验证")
        self.assertEqual(verified.returncode, 1, verified.stderr)
        self.assert_ok(self.run_arx("finish", "--outcome", "inconclusive", "--summary", "契约被外部修改，不能验证。"))

    def test_legacy_state_is_reported_and_archived_without_migration(self) -> None:
        legacy = self.research / "current"
        legacy.mkdir(parents=True)
        legacy_state = "version: 1\nphase: execution\n"
        (legacy / "state.yaml").write_text(legacy_state, encoding="utf-8")
        (legacy / "evidence_ledger.jsonl").write_text('{"old": true}\n', encoding="utf-8")

        report = self.status()
        self.assertEqual(report["state"], "legacy")
        self.assert_rejected(self.run_arx("start", "--goal", "新研究"))
        self.assert_ok(self.run_arx("start", "--goal", "新研究", "--archive-legacy"))
        archive = next((self.research / "archive").iterdir())
        self.assertEqual((archive / "state.yaml").read_text(encoding="utf-8"), legacy_state)
        manifest = json.loads((archive / "legacy-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["kind"], "legacy")
        self.assertEqual(self.status()["state"], "active")

    def test_concurrent_records_do_not_drop_distinct_results(self) -> None:
        self.start()
        self.lock(self.write_contract("contract.json"))

        def add_result(index: int) -> subprocess.CompletedProcess[str]:
            return self.record(
                "source-check",
                "pass",
                [f"evidence/{index}"],
                f"并发记录 {index}",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(add_result, range(8)))
        for result in results:
            self.assert_ok(result)
        verification = json.loads(
            (self.research / "current" / "verifications" / "v001.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(verification["results"]), 8)

    def test_finish_rolls_back_if_the_archive_move_fails(self) -> None:
        import arx_core

        root = self.research
        arx_core.start_session(root, "测试归档回滚")
        original_replace = arx_core.os.replace

        def fail_current_move(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            if Path(source) == root / "current":
                raise OSError("simulated archive failure")
            original_replace(source, destination)

        with mock.patch.object(arx_core.os, "replace", side_effect=fail_current_move):
            with self.assertRaises(arx_core.ArxIoError):
                arx_core.finish_session(root, "unverified", "归档写入失败时应恢复")

        restored = json.loads((root / "current" / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(restored["status"], "active")
        archive = arx_core.finish_session(root, "unverified", "第二次归档成功")
        self.assertTrue(archive.is_dir())

    def test_only_read_only_session_hook_remains_and_runs_from_unicode_install_path(self) -> None:
        hooks_manifest = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(set(hooks_manifest["hooks"]), {"SessionStart"})
        configured = hooks_manifest["hooks"]["SessionStart"][0]["hooks"][0]
        self.assertIn("session_recovery.py", configured["command"])
        self.assertNotIn("continue", configured["command"])

        empty = self.cwd / "empty"
        empty.mkdir()
        empty_result = subprocess.run(
            [sys.executable, str(HOOKS / "session_recovery.py")],
            cwd=empty,
            input=json.dumps({"cwd": str(empty)}, ensure_ascii=False),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(empty_result.returncode, 0, empty_result.stderr)
        self.assertEqual(empty_result.stdout, "")

        self.start()
        before = (self.research / "current" / "session.json").read_bytes()
        installed = self.cwd / "插件 安装副本"
        shutil.copytree(PLUGIN_ROOT, installed)
        payload = json.dumps({"cwd": str(self.cwd)}, ensure_ascii=False)
        result = subprocess.run(
            [sys.executable, str(installed / "hooks" / "session_recovery.py")],
            cwd=self.cwd,
            input=payload,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        rendered = json.dumps(output, ensure_ascii=False)
        self.assertIn("SessionStart", rendered)
        self.assertIn("arx status --json", rendered)
        self.assertNotIn("continue", rendered)
        self.assertNotIn("deny", rendered)
        self.assertEqual((self.research / "current" / "session.json").read_bytes(), before)

    def test_plugin_keeps_optional_mcp_but_removes_old_workflow_files(self) -> None:
        manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "0.3.0")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertTrue((PLUGIN_ROOT / ".mcp.json").exists())
        for old_script in (
            "arx_init.py",
            "arx_compile_goal.py",
            "arx_record.py",
            "arx_audit.py",
            "arx_decide.py",
            "arx_status.py",
            "arx_archive.py",
            "arx_lifecycle.py",
            "arx_loop.py",
            "arx_common.py",
        ):
            self.assertFalse((SCRIPTS / old_script).exists(), old_script)
        self.assertFalse((PLUGIN_ROOT / "skills" / "autoresearch-guard" / "templates").exists())
        for old_hook in ("pre_tool_command_gate.py", "post_tool_capture.py", "stop_goal_guard.py", "hook_runtime.py"):
            self.assertFalse((HOOKS / old_hook).exists(), old_hook)


if __name__ == "__main__":
    unittest.main()
