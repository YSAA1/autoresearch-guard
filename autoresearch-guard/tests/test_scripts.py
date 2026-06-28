from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
HOOKS = PLUGIN_ROOT / "hooks"


class ScriptFlowTest(unittest.TestCase):
    def run_script(self, name: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def assert_ok(self, result: subprocess.CompletedProcess[str]) -> None:
        if result.returncode != 0:
            self.fail(f"command failed\nstdout={result.stdout}\nstderr={result.stderr}")

    def test_full_research_lifecycle(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            init = self.run_script(
                "arx_init.py",
                "--research-root",
                str(research),
                "--iteration-id",
                "demo-i1",
                "--title",
                "Demo",
                "--objective",
                "Check validation gain",
                "--hypothesis",
                "A deterministic smoke metric can pass a gate",
                cwd=cwd,
            )
            self.assert_ok(init)

            protocol = research / "current" / "protocol.lock.yaml"
            protocol.write_text(
                "locked: true\n"
                "allowed_splits:\n"
                "  - train\n"
                "  - validation\n"
                "forbidden_splits:\n"
                "  - test\n"
                "expected_metrics:\n"
                "  - oracle_top1_gain\n"
                "validation_gates:\n"
                "  -\n"
                "    metric: oracle_top1_gain\n"
                "    operator: '>'\n"
                "    value: 0\n"
                "    split: validation\n"
                "    aggregation: latest\n"
                "require_seed: true\n",
                encoding="utf-8",
            )

            compile_goal = self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(compile_goal)
            self.assertTrue((research / "current" / "active_goal.md").exists())

            record = self.run_script(
                "arx_record.py",
                "--research-root",
                str(research),
                "--iteration-id",
                "demo-i1",
                "--command",
                "python eval.py --split validation --seed 0",
                "--data-split",
                "validation",
                "--seed",
                "0",
                "--metric",
                "oracle_top1_gain=0.1",
                cwd=cwd,
            )
            self.assert_ok(record)

            audit = self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(audit)
            audit_text = (research / "current" / "audit_report.yaml").read_text(encoding="utf-8")
            self.assertIn("validation_gate_passed: true", audit_text)

            (research / "current" / "ai_evidence_review.md").write_text(
                "# AI Evidence Review\n\nEvidence supports continuing validation only.\n",
                encoding="utf-8",
            )
            (research / "current" / "decision.proposed.yaml").write_text(
                "decision: refine\nreason: validation gate passed but this remains validation-only evidence\nnext_goal_type: refine_experiment\nrequires_human: true\n",
                encoding="utf-8",
            )
            decide = self.run_script("arx_decide.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(decide)
            self.assertTrue((research / "current" / "decision.yaml").exists())

            status = self.run_script("arx_status.py", "--research-root", str(research), "--json", cwd=cwd)
            self.assert_ok(status)
            parsed = json.loads(status.stdout)
            self.assertEqual(parsed["iteration_id"], "demo-i1")
            self.assertTrue(parsed["protocol_locked"])

            archive = self.run_script("arx_archive.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(archive)
            self.assertFalse((research / "current").exists())
            self.assertTrue(any((research / "archive").iterdir()))

    def test_pre_tool_hook_blocks_forbidden_split(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            init = self.run_script(
                "arx_init.py",
                "--research-root",
                str(research),
                "--iteration-id",
                "hook-i1",
                cwd=cwd,
            )
            self.assert_ok(init)
            protocol = research / "current" / "protocol.lock.yaml"
            protocol.write_text("locked: true\nforbidden_splits:\n  - test\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOKS / "pre_tool_command_gate.py"),
                    "--cwd",
                    str(cwd),
                    "--command",
                    "python eval.py --split test",
                ],
                cwd=str(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("forbidden split", result.stdout)


if __name__ == "__main__":
    unittest.main()