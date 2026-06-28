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

            hypothesis = research / "current" / "hypothesis.yaml"
            hypothesis.write_text(
                "iteration_id: demo-i1\n"
                "title: Demo\n"
                "objective: Check validation gain\n"
                "hypothesis: A deterministic smoke metric can pass a gate\n"
                "rationale: smoke\n"
                "expected_signal: gain > 0\n"
                "evidence_basis: idea-1\n"
                "reuse_plan:\n"
                "  base: https://github.com/example/baseline\n"
                "  build_new_reason: \"\"\n"
                "allowed_work: []\n"
                "forbidden_work: []\n"
                "must_produce:\n"
                "  - evidence_ledger.jsonl\n"
                "  - audit_report.yaml\n"
                "  - ai_evidence_review.md\n"
                "  - decision.yaml\n",
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

    def _init_base(self, research: Path, cwd: Path, iteration_id: str = "t-i1") -> None:
        init = self.run_script(
            "arx_init.py",
            "--research-root",
            str(research),
            "--iteration-id",
            iteration_id,
            cwd=cwd,
        )
        self.assert_ok(init)
        (research / "current" / "hypothesis.yaml").write_text(
            f"iteration_id: {iteration_id}\n"
            "title: T\n"
            "objective: o\n"
            "hypothesis: h\n"
            "rationale: r\n"
            "expected_signal: s\n"
            "evidence_basis: idea-1\n"
            "reuse_plan:\n"
            "  base: https://github.com/example/repo\n"
            "  build_new_reason: \"\"\n"
            "allowed_work: []\n"
            "forbidden_work: []\n"
            "must_produce: []\n",
            encoding="utf-8",
        )
        (research / "current" / "protocol.lock.yaml").write_text(
            "locked: true\n"
            "allowed_splits:\n  - train\n  - validation\n"
            "forbidden_splits:\n  - test\n"
            "expected_metrics: []\n"
            "validation_gates: []\n"
            "require_seed: false\n"
            "spiral_budget:\n  max_failed_attempts: 3\n  max_flatline_count: 3\n",
            encoding="utf-8",
        )

    def test_reuse_plan_required_for_compile(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd)
            # build_new without reason -> rejected
            (research / "current" / "hypothesis.yaml").write_text(
                "iteration_id: t-i1\nobjective: o\nhypothesis: h\n"
                "evidence_basis: idea-1\n"
                "reuse_plan:\n  base: build_new\n  build_new_reason: \"\"\n",
                encoding="utf-8",
            )
            bad = self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            self.assertNotEqual(bad.returncode, 0, bad.stdout + bad.stderr)
            self.assertIn("build_new_reason", bad.stderr)
            # missing evidence_basis -> rejected
            (research / "current" / "hypothesis.yaml").write_text(
                "iteration_id: t-i1\nobjective: o\nhypothesis: h\n"
                "evidence_basis: \"\"\n"
                "reuse_plan:\n  base: https://github.com/example/repo\n  build_new_reason: \"\"\n",
                encoding="utf-8",
            )
            bad2 = self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            self.assertNotEqual(bad2.returncode, 0, bad2.stdout + bad2.stderr)
            self.assertIn("evidence_basis", bad2.stderr)

    def test_spiral_risk_detection(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "spiral-i1")
            self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            for i in range(3):
                rec = self.run_script(
                    "arx_record.py",
                    "--research-root", str(research),
                    "--iteration-id", "spiral-i1",
                    "--command", f"python eval.py --run {i}",
                    "--data-split", "validation",
                    "--exit-code", "1",
                    "--status", "fail",
                    cwd=cwd,
                )
                self.assert_ok(rec)
            audit = self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            report = (research / "current" / "audit_report.yaml").read_text(encoding="utf-8")
            self.assertIn("spiral_risk:", report)
            self.assertIn("level: critical", report)
            self.assertIn("same_hypothesis_attempts", report)

    def test_escape_gate_blocks_proceed(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "esc-i1")
            self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            for i in range(3):
                self.run_script(
                    "arx_record.py",
                    "--research-root", str(research),
                    "--iteration-id", "esc-i1",
                    "--command", f"python eval.py --run {i}",
                    "--data-split", "validation",
                    "--exit-code", "1",
                    "--status", "fail",
                    cwd=cwd,
                )
            self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            (research / "current" / "ai_evidence_review.md").write_text(
                "# Review\n\nno_signal observed.\n", encoding="utf-8",
            )
            # proceed without spiral_response -> rejected
            (research / "current" / "decision.proposed.yaml").write_text(
                "decision: proceed\nreason: try again\n", encoding="utf-8",
            )
            bad = self.run_script("arx_decide.py", "--research-root", str(research), cwd=cwd)
            self.assertNotEqual(bad.returncode, 0, bad.stdout + bad.stderr)
            self.assertIn("spiral_response", bad.stderr)
            # pivot with spiral_response -> accepted
            (research / "current" / "decision.proposed.yaml").write_text(
                "decision: pivot\nreason: stuck\nspiral_response: abandoning approach, repeated failures\n",
                encoding="utf-8",
            )
            good = self.run_script("arx_decide.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(good)
            self.assertTrue((research / "current" / "decision.yaml").exists())

    def test_lessons_required_on_failure(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "fail-i1")
            self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            self.run_script(
                "arx_record.py",
                "--research-root", str(research),
                "--iteration-id", "fail-i1",
                "--command", "python eval.py",
                "--data-split", "validation",
                "--exit-code", "1",
                "--status", "fail",
                cwd=cwd,
            )
            self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            (research / "current" / "ai_evidence_review.md").write_text(
                "# Review\n\nimplementation_bug.\n", encoding="utf-8",
            )
            (research / "current" / "decision.proposed.yaml").write_text(
                "decision: stop\nreason: done\nspiral_response: none\n", encoding="utf-8",
            )
            self.run_script("arx_decide.py", "--research-root", str(research), cwd=cwd)
            # guard should block: lessons not updated
            guard = subprocess.run(
                [sys.executable, str(HOOKS / "stop_goal_guard.py"), "--cwd", str(cwd)],
                cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertEqual(guard.returncode, 2, guard.stdout + guard.stderr)
            self.assertIn("anti_patterns.yaml", guard.stdout)
            # update lessons -> guard passes
            (research / "lessons" / "anti_patterns.yaml").write_text(
                "anti_patterns:\n  - iteration_id: fail-i1\n    tag: implementation_bug\n",
                encoding="utf-8",
            )
            guard2 = subprocess.run(
                [sys.executable, str(HOOKS / "stop_goal_guard.py"), "--cwd", str(cwd)],
                cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertEqual(guard2.returncode, 0, guard2.stdout + guard2.stderr)

    def test_subtraction_regression(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "sub-i1")
            # deleted templates should not exist
            templates = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "templates"
            self.assertFalse((templates / "audit_report.yaml.j2").exists())
            self.assertFalse((templates / "evidence_record.json.j2").exists())
            self.assertFalse((templates / "decision.yaml.j2").exists())
            # init should create literature_review.md and ai_evidence_review.md
            self.assertTrue((research / "current" / "literature_review.md").exists())
            self.assertTrue((research / "current" / "ai_evidence_review.md").exists())
            # post_tool_capture should not create tool_capture.jsonl
            subprocess.run(
                [sys.executable, str(HOOKS / "post_tool_capture.py"),
                 "--cwd", str(cwd), "--command", "python eval.py --split validation"],
                cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertFalse((research / "current" / "tool_capture.jsonl").exists())
            # full flow still works
            self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            self.assertTrue((research / "current" / "active_goal.md").exists())


if __name__ == "__main__":
    unittest.main()