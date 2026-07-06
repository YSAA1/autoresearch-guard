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

    def test_hooks_manifest_commands_run_from_plugin_root(self) -> None:
        hooks_manifest = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
        hooks = []
        for entries in hooks_manifest["hooks"].values():
            for entry in entries:
                hooks.extend(entry["hooks"])

        self.assertEqual(len(hooks), 3)
        fake_project = PLUGIN_ROOT.parent
        for hook in hooks:
            command = hook["command"]
            self.assertIn("${PLUGIN_ROOT}", command)
            self.assertIn("commandWindows", hook)
            self.assertIn("%PLUGIN_ROOT%", hook["commandWindows"])
            self.assertNotIn("${PLUGIN_ROOT}", hook["commandWindows"])
            substituted = command.replace("${PLUGIN_ROOT}", str(PLUGIN_ROOT))
            result = subprocess.run(
                substituted,
                shell=True,
                cwd=str(fake_project),
                text=True,
                input="{}",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"{substituted}\nstdout={result.stdout}\nstderr={result.stderr}",
            )
            if result.stdout.strip():
                payload = json.loads(result.stdout)
                self.assertNotIn("allow", payload)

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
            (research / "current" / "literature_review.md").write_text(
                "# Literature Review\n\n"
                "## 候选创新点\n\n"
                "| idea_id | 描述 | 证据链接 | gap |\n"
                "| --- | --- | --- | --- |\n"
                "| idea-1 | Use a deterministic smoke metric | https://arxiv.org/abs/1234.5678 | scoped gap |\n\n"
                "## 现有实现（不重复造轮子）\n\n"
                "| impl_id | url | covered_capability | reuse_decision |\n"
                "| --- | --- | --- | --- |\n"
                "| impl-1 | https://github.com/example/baseline | baseline | reuse |\n",
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
            self.assertFalse(parsed["hooks_enabled"])

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
                "--enable-hooks",
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
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("forbidden split", result.stdout)
            self.assertIn("permissionDecision", result.stdout)

    def test_hooks_disabled_by_default_do_not_act(self) -> None:
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
                "hook-off-i1",
                cwd=cwd,
            )
            self.assert_ok(init)
            state = (research / "current" / "state.yaml").read_text(encoding="utf-8")
            self.assertIn("hooks_enabled: false", state)
            (research / "current" / "protocol.lock.yaml").write_text(
                "locked: true\nforbidden_splits:\n  - test\n",
                encoding="utf-8",
            )

            pre = subprocess.run(
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
            self.assertEqual(pre.returncode, 0, pre.stdout + pre.stderr)
            self.assertEqual(pre.stdout.strip(), "")

            post = subprocess.run(
                [
                    sys.executable,
                    str(HOOKS / "post_tool_capture.py"),
                    "--cwd",
                    str(cwd),
                    "--command",
                    "python eval.py --split validation --metrics result.json",
                ],
                cwd=str(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(post.returncode, 0, post.stdout + post.stderr)
            self.assertEqual(post.stdout.strip(), "")

            stop = subprocess.run(
                [sys.executable, str(HOOKS / "stop_goal_guard.py"), "--cwd", str(cwd)],
                cwd=str(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(stop.returncode, 0, stop.stdout + stop.stderr)
            self.assertEqual(stop.stdout.strip(), "")

    def test_post_tool_hook_reminds_when_enabled(self) -> None:
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
                "hook-post-i1",
                "--enable-hooks",
                cwd=cwd,
            )
            self.assert_ok(init)
            state = (research / "current" / "state.yaml").read_text(encoding="utf-8")
            self.assertIn("hooks_enabled: true", state)
            result = subprocess.run(
                [
                    sys.executable,
                    str(HOOKS / "post_tool_capture.py"),
                    "--cwd",
                    str(cwd),
                    "--command",
                    "python eval.py --split validation --metrics result.json",
                ],
                cwd=str(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("additionalContext", result.stdout)
            self.assertIn("arx_record.py", result.stdout)

    def _init_base(self, research: Path, cwd: Path, iteration_id: str = "t-i1", enable_hooks: bool = False) -> None:
        args = [
            "--research-root",
            str(research),
            "--iteration-id",
            iteration_id,
        ]
        if enable_hooks:
            args.append("--enable-hooks")
        init = self.run_script(
            "arx_init.py",
            *args,
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
        (research / "current" / "literature_review.md").write_text(
            "# Literature Review\n\n"
            "## 候选创新点\n\n"
            "| idea_id | 描述 | 证据链接 | gap |\n"
            "| --- | --- | --- | --- |\n"
            "| idea-1 | Smoke idea | https://arxiv.org/abs/1234.5678 | scoped gap |\n\n"
            "## 现有实现（不重复造轮子）\n\n"
            "| impl_id | url | covered_capability | reuse_decision |\n"
            "| --- | --- | --- | --- |\n"
            "| impl-1 | https://github.com/example/repo | baseline | reuse |\n",
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

    def test_compile_requires_prior_art_and_reuse_traceability(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd)
            (research / "current" / "literature_review.md").write_text(
                "# Literature Review\n\n"
                "## 候选创新点\n\n"
                "| idea_id | 描述 | 证据链接 | gap |\n"
                "| --- | --- | --- | --- |\n"
                "| idea-1 | Use a deterministic smoke metric | https://arxiv.org/abs/1234.5678 | scoped gap |\n\n"
                "## 现有实现（不重复造轮子）\n\n"
                "| impl_id | url | covered_capability | reuse_decision |\n"
                "| --- | --- | --- | --- |\n"
                "| impl-1 | https://github.com/example/repo | baseline | reuse |\n",
                encoding="utf-8",
            )

            ok = self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(ok)

            hypothesis = research / "current" / "hypothesis.yaml"
            hypothesis.write_text(
                "iteration_id: t-i1\nobjective: o\nhypothesis: h\n"
                "evidence_basis: missing-idea\n"
                "reuse_plan:\n  base: https://github.com/example/repo\n  build_new_reason: \"\"\n",
                encoding="utf-8",
            )
            missing_idea = self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            self.assertNotEqual(missing_idea.returncode, 0, missing_idea.stdout + missing_idea.stderr)
            self.assertIn("evidence_basis", missing_idea.stderr)

            hypothesis.write_text(
                "iteration_id: t-i1\nobjective: o\nhypothesis: h\n"
                "evidence_basis: idea-1\n"
                "reuse_plan:\n  base: https://github.com/example/missing\n  build_new_reason: \"\"\n",
                encoding="utf-8",
            )
            missing_impl = self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd)
            self.assertNotEqual(missing_impl.returncode, 0, missing_impl.stdout + missing_impl.stderr)
            self.assertIn("reuse_plan.base", missing_impl.stderr)

    def test_audit_forbids_promote_when_required_baseline_is_missing(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "base-i1")
            (research / "current" / "protocol.lock.yaml").write_text(
                "locked: true\n"
                "allowed_splits:\n  - validation\n"
                "forbidden_splits:\n  - test\n"
                "expected_metrics:\n  - score\n"
                "validation_gates:\n"
                "  -\n"
                "    metric: score\n"
                "    operator: '>='\n"
                "    value: 0.5\n"
                "    split: validation\n"
                "    aggregation: latest\n"
                "require_seed: false\n"
                "baseline:\n"
                "  required: true\n"
                "  metric: score\n"
                "  split: validation\n"
                "  aggregation: max\n"
                "  min_delta: 0.0\n"
                "  higher_is_better: true\n",
                encoding="utf-8",
            )
            self.assert_ok(self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd))
            self.assert_ok(self.run_script(
                "arx_record.py",
                "--research-root", str(research),
                "--iteration-id", "base-i1",
                "--command", "python eval.py --split validation",
                "--data-split", "validation",
                "--metric", "score=0.7",
                cwd=cwd,
            ))

            audit = self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(audit)
            report = (research / "current" / "audit_report.yaml").read_text(encoding="utf-8")
            self.assertIn("baseline_status:", report)
            self.assertIn("status: missing_required_baseline", report)
            self.assertIn("- promote", report)

    def test_audit_compares_experiment_against_baseline(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "compare-i1")
            (research / "current" / "protocol.lock.yaml").write_text(
                "locked: true\n"
                "allowed_splits:\n  - validation\n"
                "forbidden_splits:\n  - test\n"
                "expected_metrics:\n  - score\n"
                "validation_gates:\n"
                "  -\n"
                "    metric: score\n"
                "    operator: '>='\n"
                "    value: 0.5\n"
                "    split: validation\n"
                "    aggregation: latest\n"
                "require_seed: false\n"
                "baseline:\n"
                "  required: true\n"
                "  metric: score\n"
                "  split: validation\n"
                "  aggregation: max\n"
                "  min_delta: 0.0\n"
                "  higher_is_better: true\n",
                encoding="utf-8",
            )
            self.assert_ok(self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd))
            self.assert_ok(self.run_script(
                "arx_record.py",
                "--research-root", str(research),
                "--iteration-id", "compare-i1",
                "--command", "python eval.py --baseline --split validation",
                "--data-split", "validation",
                "--metric", "score=0.8",
                "--role", "baseline",
                cwd=cwd,
            ))
            self.assert_ok(self.run_script(
                "arx_record.py",
                "--research-root", str(research),
                "--iteration-id", "compare-i1",
                "--command", "python eval.py --split validation",
                "--data-split", "validation",
                "--metric", "score=0.7",
                cwd=cwd,
            ))

            audit = self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(audit)
            report = (research / "current" / "audit_report.yaml").read_text(encoding="utf-8")
            self.assertIn("status: failed_baseline_comparison", report)
            self.assertIn("- promote", report)

            self.assert_ok(self.run_script(
                "arx_record.py",
                "--research-root", str(research),
                "--iteration-id", "compare-i1",
                "--command", "python eval.py --split validation --better",
                "--data-split", "validation",
                "--metric", "score=0.9",
                cwd=cwd,
            ))
            (research / "current" / "ai_evidence_review.md").write_text(
                "# AI 证据审查\n\n"
                "## 结论与证据\n\n"
                "| claim_id | 结论 | 等级 | 证据 | 状态 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| c1 | validation 上优于 baseline | validation | ledger:run-2 | supported |\n",
                encoding="utf-8",
            )
            audit2 = self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(audit2)
            report2 = (research / "current" / "audit_report.yaml").read_text(encoding="utf-8")
            self.assertIn("baseline_status:", report2)
            self.assertIn("status: pass", report2)
            self.assertIn("forbidden_decisions: []", report2)

    def test_audit_forbids_promote_for_unsupported_claim(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "claim-i1")
            (research / "current" / "protocol.lock.yaml").write_text(
                "locked: true\n"
                "allowed_splits:\n  - validation\n"
                "forbidden_splits:\n  - test\n"
                "expected_metrics:\n  - score\n"
                "validation_gates:\n"
                "  -\n"
                "    metric: score\n"
                "    operator: '>='\n"
                "    value: 0.5\n"
                "    split: validation\n"
                "    aggregation: latest\n"
                "require_seed: false\n",
                encoding="utf-8",
            )
            self.assert_ok(self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd))
            self.assert_ok(self.run_script(
                "arx_record.py",
                "--research-root", str(research),
                "--iteration-id", "claim-i1",
                "--command", "python eval.py --split validation",
                "--data-split", "validation",
                "--metric", "score=0.7",
                cwd=cwd,
            ))
            (research / "current" / "ai_evidence_review.md").write_text(
                "# AI 证据审查\n\n"
                "## 结论与证据\n\n"
                "| claim_id | 结论 | 等级 | 证据 | 状态 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| c1 | 方法可推广到 test | test | none | unsupported |\n",
                encoding="utf-8",
            )

            audit = self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(audit)
            report = (research / "current" / "audit_report.yaml").read_text(encoding="utf-8")
            self.assertIn("claim_support_status:", report)
            self.assertIn("status: fail", report)
            self.assertIn("unsupported_claims:", report)
            self.assertIn("- promote", report)

    def test_audit_forbids_promote_for_prohibited_or_boundary_claim(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "boundary-i1")
            (research / "current" / "protocol.lock.yaml").write_text(
                "locked: true\n"
                "allowed_splits:\n  - validation\n"
                "forbidden_splits:\n  - test\n"
                "expected_metrics:\n  - score\n"
                "validation_gates:\n"
                "  -\n"
                "    metric: score\n"
                "    operator: '>='\n"
                "    value: 0.5\n"
                "    split: validation\n"
                "    aggregation: latest\n"
                "require_seed: false\n",
                encoding="utf-8",
            )
            self.assert_ok(self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd))
            self.assert_ok(self.run_script(
                "arx_record.py",
                "--research-root", str(research),
                "--iteration-id", "boundary-i1",
                "--command", "python eval.py --split validation",
                "--data-split", "validation",
                "--metric", "score=0.7",
                cwd=cwd,
            ))
            (research / "current" / "ai_evidence_review.md").write_text(
                "# AI 证据审查\n\n"
                "## 结论与证据\n\n"
                "| claim_id | 结论 | 等级 | 证据 | 状态 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| c1 | validation 上优于 baseline | validation | ledger:run-1 | supported |\n"
                "| c2 | 可推广到 test | test | ledger:run-1 | prohibited |\n",
                encoding="utf-8",
            )

            audit = self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            self.assert_ok(audit)
            report = (research / "current" / "audit_report.yaml").read_text(encoding="utf-8")
            self.assertIn("prohibited_claims:", report)
            self.assertIn("boundary_violations:", report)
            self.assertIn("- c2", report)
            self.assertIn("- promote", report)

    def test_audit_rejects_records_before_compiled_protocol(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "time-i1")
            (research / "current" / "protocol.lock.yaml").write_text(
                "locked: true\n"
                "allowed_splits:\n  - validation\n"
                "forbidden_splits:\n  - test\n"
                "expected_metrics:\n  - score\n"
                "validation_gates:\n"
                "  -\n"
                "    metric: score\n"
                "    operator: '>='\n"
                "    value: 0.5\n"
                "    split: validation\n"
                "    aggregation: latest\n"
                "require_seed: false\n",
                encoding="utf-8",
            )
            self.assert_ok(self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd))
            self.assert_ok(self.run_script(
                "arx_record.py",
                "--research-root", str(research),
                "--iteration-id", "time-i1",
                "--command", "python eval.py --split validation",
                "--data-split", "validation",
                "--metric", "score=0.7",
                cwd=cwd,
            ))
            state = research / "current" / "state.yaml"
            state.write_text(
                state.read_text(encoding="utf-8") + "compiled_at: 2999-01-01T00:00:00Z\n",
                encoding="utf-8",
            )

            audit = self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)
            self.assertNotEqual(audit.returncode, 0, audit.stdout + audit.stderr)
            report = (research / "current" / "audit_report.yaml").read_text(encoding="utf-8")
            self.assertIn("protocol_violation: true", report)
            self.assertIn("record 1 predates compiled protocol", report)

    def test_status_review_renders_gate_packet(self) -> None:
        test_tmp_root = Path(os.environ.get("ARX_TEST_TMP", "C:/tmp"))
        test_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(test_tmp_root)) as tmp:
            cwd = Path(tmp)
            research = cwd / ".research"
            self._init_base(research, cwd, "review-i1")
            (research / "current" / "protocol.lock.yaml").write_text(
                "locked: true\n"
                "allowed_splits:\n  - validation\n"
                "forbidden_splits:\n  - test\n"
                "expected_metrics:\n  - score\n"
                "validation_gates:\n"
                "  -\n"
                "    metric: score\n"
                "    operator: '>='\n"
                "    value: 0.5\n"
                "    split: validation\n"
                "    aggregation: latest\n"
                "require_seed: false\n",
                encoding="utf-8",
            )
            self.assert_ok(self.run_script("arx_compile_goal.py", "--research-root", str(research), cwd=cwd))
            self.assert_ok(self.run_script(
                "arx_record.py",
                "--research-root", str(research),
                "--iteration-id", "review-i1",
                "--command", "python eval.py --split validation",
                "--data-split", "validation",
                "--metric", "score=0.7",
                cwd=cwd,
            ))
            (research / "current" / "ai_evidence_review.md").write_text(
                "# AI 证据审查\n\n"
                "## 结论与证据\n\n"
                "| claim_id | 结论 | 等级 | 证据 | 状态 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| c1 | validation 上有正向信号 | validation | ledger:run-1 | supported |\n",
                encoding="utf-8",
            )
            self.assert_ok(self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd))

            review = self.run_script("arx_status.py", "--research-root", str(research), "--review", cwd=cwd)
            self.assert_ok(review)
            self.assertIn("AutoResearch Guard review packet", review.stdout)
            self.assertIn("结论：绿灯", review.stdout)
            self.assertIn("prior art：绿灯", review.stdout)
            self.assertIn("validation gate：绿灯", review.stdout)
            self.assertIn("claim support：绿灯", review.stdout)
            self.assertIn("下钻", review.stdout)

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
            self._init_base(research, cwd, "fail-i1", enable_hooks=True)
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
            self.assertEqual(guard.returncode, 0, guard.stdout + guard.stderr)
            self.assertIn("anti_patterns.yaml", guard.stdout)
            self.assertIn('"decision": "block"', guard.stdout)
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
