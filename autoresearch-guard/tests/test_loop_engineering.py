from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "skills" / "autoresearch-guard" / "scripts"
HOOKS = PLUGIN_ROOT / "hooks"
NODE = shutil.which("node") or "node"


class LoopEngineeringContractTest(unittest.TestCase):
    """End-to-end contracts for the public loop scripts and Codex hooks."""

    maxDiff = None

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def hook_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["ARX_PYTHON"] = sys.executable
        return env

    def run_script(
        self,
        name: str,
        *args: str,
        cwd: Path | None = None,
        stdin: dict[str, Any] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            cwd=str(cwd or self.workspace),
            text=True,
            input=json.dumps(stdin) if stdin is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def run_hook(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        cwd: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
        script = name if name.endswith(".js") else name.replace(".py", ".js")
        result = subprocess.run(
            [NODE, str(HOOKS / script)],
            cwd=str(cwd or self.workspace),
            text=True,
            input=json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.hook_env(),
        )
        output = json.loads(result.stdout) if result.stdout.strip() else None
        return result, output

    def find_research_root(self, cwd: Path) -> Path | None:
        result = subprocess.run(
            [NODE, str(HOOKS / "hook_runtime.js"), "--find-root", str(cwd)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.hook_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = result.stdout.strip()
        return Path(text) if text else None

    def assert_ok(self, result: subprocess.CompletedProcess[str]) -> None:
        if result.returncode != 0:
            self.fail(
                "command failed\n"
                f"returncode={result.returncode}\n"
                f"stdout={result.stdout}\n"
                f"stderr={result.stderr}"
            )

    def assert_rejected(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(
            result.returncode,
            0,
            f"command unexpectedly succeeded\nstdout={result.stdout}\nstderr={result.stderr}",
        )

    def research_root(self, workspace: Path | None = None) -> Path:
        return (workspace or self.workspace) / ".research"

    def init_iteration(
        self,
        iteration_id: str,
        *,
        workspace: Path | None = None,
        enable_hooks: bool = False,
        extra: tuple[str, ...] = (),
    ) -> Path:
        cwd = workspace or self.workspace
        cwd.mkdir(parents=True, exist_ok=True)
        research = self.research_root(cwd)
        args = [
            "--research-root",
            str(research),
            "--iteration-id",
            iteration_id,
            "--title",
            f"Iteration {iteration_id}",
            "--objective",
            "Exercise the deterministic loop contract",
            "--hypothesis",
            "A recorded validation score should satisfy the declared gate",
        ]
        if enable_hooks:
            args.append("--enable-hooks")
        args.extend(extra)
        self.assert_ok(self.run_script("arx_init.py", *args, cwd=cwd))
        return research

    def write_compilable_fixture(
        self,
        research: Path,
        iteration_id: str,
        *,
        locked: bool = True,
        max_failed_attempts: int = 3,
        max_flatline_count: int = 3,
        gate_value: float = 0.5,
    ) -> None:
        cur = research / "current"
        (cur / "hypothesis.yaml").write_text(
            f"iteration_id: {iteration_id}\n"
            f"title: Iteration {iteration_id}\n"
            "objective: Exercise the deterministic loop contract\n"
            "hypothesis: A recorded validation score should satisfy the declared gate\n"
            "rationale: deterministic fixture\n"
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
            f"locked: {str(locked).lower()}\n"
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
            f"    value: {gate_value}\n"
            "    split: validation\n"
            "    aggregation: latest\n"
            "baseline:\n"
            "  required: false\n"
            "require_seed: false\n"
            "spiral_budget:\n"
            f"  max_failed_attempts: {max_failed_attempts}\n"
            f"  max_flatline_count: {max_flatline_count}\n"
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
        self.write_research_products(research, claim_id="c1")
        (cur / "ai_evidence_review.md").write_text(
            "# AI 证据审查\n\n"
            "## 结论与证据\n\n"
            "| claim_id | 结论 | 等级 | 证据 | 状态 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| c1 | validation score meets the declared gate | supported | ledger:attempt | supported |\n",
            encoding="utf-8",
        )
        (cur / "next_goal.md").write_text(
            "# Next Goal\n\nInvestigate the next bounded validation question.\n",
            encoding="utf-8",
        )

    def write_research_products(
        self,
        research: Path,
        *,
        claim_id: str = "c1",
        claim_level_target: str = "supported",
        adversary_verdict: str = "survived",
    ) -> None:
        cur = research / "current"
        (cur / "research.yaml").write_text(
            "question: Does the declared validation gate hold for this fixture?\n"
            "non_goals:\n"
            "  - production deployment\n"
            f"claim_level_target: {claim_level_target}\n"
            "success_criteria: Gate passes with recorded evidence and multi-source coverage\n"
            "claims:\n"
            f"  - id: {claim_id}\n"
            "    statement: The recorded validation score satisfies the protocol gate\n"
            "    falsifiable: true\n"
            "    critical: true\n"
            "gaps:\n"
            "  - id: G1\n"
            "    question: What independent sources and runs support the gate claim?\n"
            f"    claim_ids: [{claim_id}]\n"
            "    critical: true\n"
            "    status: closed\n"
            "sources:\n"
            "  - id: S1\n"
            "    gap_id: G1\n"
            "    source_type: academic\n"
            "    url: https://arxiv.org/abs/1234.5678\n"
            "    title: Prior art note\n"
            "  - id: S2\n"
            "    gap_id: G1\n"
            "    source_type: code\n"
            "    url: https://github.com/example/baseline\n"
            "    title: Baseline implementation\n"
            "conflicts: []\n"
            "adversary:\n"
            f"  - claim_id: {claim_id}\n"
            f"    verdict: {adversary_verdict}\n"
            "    evidence: https://example.test/counter\n",
            encoding="utf-8",
        )

    def compile_goal(self, research: Path, *, allow_unlocked: bool = False, cwd: Path | None = None) -> None:
        args = ["--research-root", str(research)]
        if allow_unlocked:
            args.append("--allow-unlocked")
        self.assert_ok(self.run_script("arx_compile_goal.py", *args, cwd=cwd))


    def write_subagent_review(self, research: Path, *, verdict: str = "pass") -> None:
        audit = research / "current" / "audit_report.yaml"
        digest = ""
        if audit.exists():
            import hashlib

            digest = hashlib.sha256(audit.read_bytes()).hexdigest()
        (research / "current" / "subagent_review.yaml").write_text(
            f"verdict: {verdict}\n"
            "failed_checks: []\n"
            f"bound_audit_digest: {digest}\n"
            "reviewer_role: subagent\n"
            "reviewed_at: 2026-07-17T00:00:00Z\n",
            encoding="utf-8",
        )

    def loop_check(self, research: Path, *, cwd: Path | None = None) -> dict[str, Any]:
        result = self.run_script(
            "arx_loop.py",
            "check",
            "--research-root",
            str(research),
            "--json",
            cwd=cwd,
        )
        self.assert_ok(result)
        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, dict)
        return payload

    @staticmethod
    def loop_fields(payload: dict[str, Any]) -> tuple[Any, Any, Any]:
        state = payload.get("state") if isinstance(payload.get("state"), dict) else payload
        loop = state.get("loop") if isinstance(state.get("loop"), dict) else payload.get("loop", {})
        phase = state.get("phase") or payload.get("phase")
        status = loop.get("status") or state.get("status") or payload.get("status")
        owner = loop.get("owner_session_id") or state.get("owner_session_id") or payload.get("owner_session_id")
        return phase, status, owner

    def start_loop(self, research: Path, session_id: str = "owner-session", *, cwd: Path | None = None) -> None:
        result = self.run_script(
            "arx_loop.py",
            "start",
            "--research-root",
            str(research),
            "--session-id",
            session_id,
            cwd=cwd,
        )
        self.assert_ok(result)
        phase, status, owner = self.loop_fields(self.loop_check(research, cwd=cwd))
        self.assertEqual(phase, "execution")
        self.assertEqual(status, "running")
        self.assertEqual(owner, session_id)

    def record(
        self,
        research: Path,
        iteration_id: str,
        attempt_id: str,
        *,
        score: float = 0.7,
        status: str = "pass",
        exit_code: int = 0,
        command: str | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_script(
            "arx_record.py",
            "--research-root",
            str(research),
            "--iteration-id",
            iteration_id,
            "--attempt-id",
            attempt_id,
            "--command",
            command or f"python eval.py --split validation --attempt {attempt_id}",
            "--exit-code",
            str(exit_code),
            "--data-split",
            "validation",
            "--metric",
            f"score={score}",
            "--status",
            status,
            cwd=cwd,
        )

    def audit(self, research: Path, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return self.run_script("arx_audit.py", "--research-root", str(research), cwd=cwd)

    def decide(
        self,
        research: Path,
        decision: str = "refine",
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_script(
            "arx_decide.py",
            "--research-root",
            str(research),
            "--decision",
            decision,
            "--reason",
            "The deterministic audit supports this bounded decision",
            "--next-goal-type",
            "refine_experiment" if decision != "stop" else "stop",
            cwd=cwd,
        )

    @staticmethod
    def is_block(output: dict[str, Any] | None) -> bool:
        if not output:
            return False
        specific = output.get("hookSpecificOutput")
        nested = specific if isinstance(specific, dict) else {}
        return (output.get("decision") or nested.get("decision")) == "block"

    @staticmethod
    def permission_decision(output: dict[str, Any] | None) -> str | None:
        if not output:
            return None
        specific = output.get("hookSpecificOutput")
        nested = specific if isinstance(specific, dict) else {}
        value = output.get("permissionDecision") or nested.get("permissionDecision")
        return str(value) if value is not None else None

    def stop_payload(
        self,
        cwd: Path,
        session_id: str,
        *,
        stop_hook_active: bool = False,
        **extra: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": session_id,
            "turn_id": "turn-1",
            "cwd": str(cwd),
            "hook_event_name": "Stop",
            "stop_hook_active": stop_hook_active,
        }
        payload.update(extra)
        return payload

    def test_state_v2_and_draft_compile_cannot_arm_execution(self) -> None:
        locked_workspace = self.workspace / "locked"
        locked = self.init_iteration("locked-i1", workspace=locked_workspace)
        state_text = (locked / "current" / "state.yaml").read_text(encoding="utf-8")
        self.assertIn("version: 2", state_text)
        phase, status, _owner = self.loop_fields(self.loop_check(locked, cwd=locked_workspace))
        self.assertEqual((phase, status), ("draft", "idle"))

        self.write_compilable_fixture(locked, "locked-i1", locked=True)
        self.compile_goal(locked, cwd=locked_workspace)
        phase, status, _owner = self.loop_fields(self.loop_check(locked, cwd=locked_workspace))
        self.assertEqual((phase, status), ("execution", "armed"))

        draft_workspace = self.workspace / "draft"
        draft = self.init_iteration("draft-i1", workspace=draft_workspace)
        self.write_compilable_fixture(draft, "draft-i1", locked=False)
        result = self.run_script(
            "arx_compile_goal.py",
            "--research-root",
            str(draft),
            "--allow-unlocked",
            cwd=draft_workspace,
        )
        self.assert_ok(result)
        phase, status, _owner = self.loop_fields(self.loop_check(draft, cwd=draft_workspace))
        self.assertEqual((phase, status), ("draft", "idle"))
        goal_candidates = list((draft / "current").glob("*goal*.md"))
        self.assertTrue(goal_candidates, "--allow-unlocked must still produce a draft goal artifact")
        draft_description = "\n".join(
            [result.stdout, *(f"{path.name}\n{path.read_text(encoding='utf-8')}" for path in goal_candidates)]
        ).lower()
        self.assertIn("draft", draft_description)

    def test_compile_rejects_state_hypothesis_iteration_split(self) -> None:
        research = self.init_iteration("state-i1")
        self.write_compilable_fixture(research, "hypothesis-i9", locked=True)
        result = self.run_script("arx_compile_goal.py", "--research-root", str(research))
        self.assert_rejected(result)
        self.assertIn("iteration", result.stderr.lower())
        phase, status, _owner = self.loop_fields(self.loop_check(research))
        self.assertEqual((phase, status), ("draft", "idle"))

    def test_record_identity_terminal_freeze_and_failed_evidence_gate(self) -> None:
        research = self.init_iteration("record-i1")
        self.write_compilable_fixture(research, "record-i1", locked=True)
        self.compile_goal(research)
        self.start_loop(research)

        mismatch = self.record(research, "wrong-i9", "wrong-attempt")
        self.assert_rejected(mismatch)

        failed = self.record(
            research,
            "record-i1",
            "failed-attempt",
            score=0.99,
            status="fail",
            exit_code=1,
        )
        self.assert_ok(failed)
        self.audit(research)
        report = (research / "current" / "audit_report.yaml").read_text(encoding="utf-8").lower()
        self.assertNotIn("validation_gate_passed: true", report)
        promote = self.decide(research, "promote")
        self.assert_rejected(promote)

        terminal_workspace = self.workspace / "terminal"
        terminal = self.init_iteration("terminal-i1", workspace=terminal_workspace)
        self.write_compilable_fixture(terminal, "terminal-i1", locked=True)
        self.compile_goal(terminal, cwd=terminal_workspace)
        self.start_loop(terminal, cwd=terminal_workspace)
        self.assert_ok(self.record(terminal, "terminal-i1", "good-attempt", cwd=terminal_workspace))
        self.assert_ok(self.audit(terminal, cwd=terminal_workspace))
        self.assert_ok(self.decide(terminal, "refine", cwd=terminal_workspace))
        after_decision = self.record(
            terminal,
            "terminal-i1",
            "late-attempt",
            cwd=terminal_workspace,
        )
        self.assert_rejected(after_decision)

    def test_stale_audit_bundle_rejects_decision_and_archive(self) -> None:
        research = self.init_iteration("digest-i1")
        self.write_compilable_fixture(research, "digest-i1", locked=True)
        self.compile_goal(research)
        self.start_loop(research)
        self.assert_ok(self.record(research, "digest-i1", "digest-attempt"))
        self.assert_ok(self.audit(research))

        audit_path = research / "current" / "audit_report.yaml"
        audit_text = audit_path.read_text(encoding="utf-8")
        self.assertIn("input_digests", audit_text)

        audit_path.write_text(audit_text + "\n# tampered after audit\n", encoding="utf-8")
        tampered_audit_decision = self.decide(research, "stop")
        self.assert_rejected(tampered_audit_decision)
        self.assert_ok(self.audit(research))

        review_path = research / "current" / "ai_evidence_review.md"
        review_path.write_text(review_path.read_text(encoding="utf-8") + "\nMutated after audit.\n", encoding="utf-8")
        stale_decision = self.decide(research, "stop")
        self.assert_rejected(stale_decision)

        self.assert_ok(self.audit(research))
        self.assert_ok(self.decide(research, "stop"))
        decision_text = (research / "current" / "decision.yaml").read_text(encoding="utf-8")
        self.assertIn("audit_digest", decision_text)

        review_path.write_text(review_path.read_text(encoding="utf-8") + "\nMutated after decision.\n", encoding="utf-8")
        stale_archive = self.run_script("arx_archive.py", "--research-root", str(research))
        self.assert_rejected(stale_archive)
        self.assertTrue((research / "current").exists(), "stale state must not be moved into archive")

    def test_audit_holds_root_lock_for_the_entire_snapshot(self) -> None:
        research = self.init_iteration("locked-audit-i1")
        self.write_compilable_fixture(research, "locked-audit-i1", locked=True)
        self.compile_goal(research)
        self.start_loop(research)
        self.assert_ok(self.record(research, "locked-audit-i1", "before-audit"))

        sys.path.insert(0, str(SCRIPTS))
        import arx_audit as audit_module

        original_evaluate_gates = audit_module.evaluate_gates
        late_processes: list[subprocess.Popen[str]] = []
        completed_during_audit: list[bool] = []

        def race_record(protocol: dict[str, Any], entries: list[dict[str, Any]]) -> Any:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPTS / "arx_record.py"),
                    "--research-root",
                    str(research),
                    "--iteration-id",
                    "locked-audit-i1",
                    "--attempt-id",
                    "late-test-split",
                    "--command",
                    "python eval.py --split test",
                    "--data-split",
                    "test",
                    "--metric",
                    "score=0.99",
                ],
                cwd=str(self.workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            late_processes.append(process)
            try:
                process.wait(timeout=0.4)
                completed_during_audit.append(True)
            except subprocess.TimeoutExpired:
                completed_during_audit.append(False)
            return original_evaluate_gates(protocol, entries)

        audit_module.evaluate_gates = race_record
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(audit_module.audit_current(research), 0)
        finally:
            audit_module.evaluate_gates = original_evaluate_gates
            sys.path.remove(str(SCRIPTS))
        self.assertEqual(completed_during_audit, [False])
        stdout, stderr = late_processes[0].communicate(timeout=5)
        self.assertNotEqual(late_processes[0].returncode, 0, stdout + stderr)
        ledger = research / "current" / "evidence_ledger.jsonl"
        self.assertEqual(len([line for line in ledger.read_text(encoding="utf-8").splitlines() if line]), 1)

    def test_decision_tamper_cannot_bypass_audit_or_archive(self) -> None:
        research = self.init_iteration("decision-tamper-i1")
        self.write_compilable_fixture(research, "decision-tamper-i1", locked=True)
        self.compile_goal(research)
        self.start_loop(research)
        self.assert_ok(self.record(research, "decision-tamper-i1", "below-gate", score=0.1))
        self.assert_ok(self.audit(research))
        self.assert_ok(self.decide(research, "stop"))

        decision = research / "current" / "decision.yaml"
        decision.write_text(
            decision.read_text(encoding="utf-8").replace("decision: stop", "decision: promote", 1),
            encoding="utf-8",
        )
        report = self.loop_check(research)
        self.assertFalse(report["ready"])
        self.assertTrue(any("decision" in reason.lower() for reason in report["reasons"]))
        archive = self.run_script("arx_archive.py", "--research-root", str(research))
        self.assert_rejected(archive)

    def test_decide_requires_completed_review_and_fresh_claim_audit(self) -> None:
        research = self.init_iteration("review-gate-i1")
        self.write_compilable_fixture(research, "review-gate-i1", locked=True)
        (research / "current" / "ai_evidence_review.md").write_text(
            "# AI 证据审查\n\nTBD by AI\n",
            encoding="utf-8",
        )
        self.compile_goal(research)
        self.start_loop(research)
        self.assert_ok(self.record(research, "review-gate-i1", "review-attempt"))
        self.assert_ok(self.audit(research))
        early = self.decide(research, "stop")
        self.assert_rejected(early)
        self.assertIn("review", early.stderr.lower())

    def test_critical_proceed_requires_paused_approval_for_current_audit(self) -> None:
        research = self.init_iteration("approval-i1")
        self.write_compilable_fixture(
            research,
            "approval-i1",
            locked=True,
            max_failed_attempts=1,
            gate_value=1.0,
        )
        self.compile_goal(research)
        self.start_loop(research)
        self.assert_ok(
            self.record(
                research,
                "approval-i1",
                "approval-failure",
                status="fail",
                exit_code=1,
            )
        )
        self.assert_ok(self.audit(research))

        early_approval = self.run_script(
            "arx_loop.py",
            "resume",
            "--research-root",
            str(research),
            "--reason",
            "Premature approval",
            "--human-approved",
        )
        self.assert_rejected(early_approval)

        self.assert_ok(
            self.run_script(
                "arx_loop.py",
                "pause",
                "--research-root",
                str(research),
                "--reason",
                "Review critical spiral with a human",
            )
        )
        self.assert_ok(
            self.run_script(
                "arx_loop.py",
                "resume",
                "--research-root",
                str(research),
                "--reason",
                "Human approved one bounded proceed",
                "--human-approved",
            )
        )
        (research / "current" / "decision.proposed.yaml").write_text(
            "decision: proceed\n"
            "reason: A human approved one bounded follow-up\n"
            "requires_human: true\n"
            "spiral_response: One controlled attempt will test the identified failure mode\n",
            encoding="utf-8",
        )
        self.assert_ok(self.run_script("arx_decide.py", "--research-root", str(research)))

    def test_record_attempt_id_is_idempotent_and_jsonl_is_concurrency_safe(self) -> None:
        research = self.init_iteration("concurrent-i1")
        self.write_compilable_fixture(research, "concurrent-i1", locked=True)
        self.compile_goal(research)
        self.start_loop(research)

        first = self.record(research, "concurrent-i1", "stable-attempt", score=0.61)
        duplicate = self.record(research, "concurrent-i1", "stable-attempt", score=0.61)
        self.assert_ok(first)
        self.assert_ok(duplicate)
        ledger = research / "current" / "evidence_ledger.jsonl"
        entries = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(entries), 1, "an identical attempt retry must not append a duplicate")

        conflict = self.record(research, "concurrent-i1", "stable-attempt", score=0.62)
        self.assert_rejected(conflict)

        processes: list[subprocess.Popen[str]] = []
        for index in range(8):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(SCRIPTS / "arx_record.py"),
                        "--research-root",
                        str(research),
                        "--iteration-id",
                        "concurrent-i1",
                        "--attempt-id",
                        f"parallel-{index}",
                        "--command",
                        f"python eval.py --split validation --attempt parallel-{index}",
                        "--data-split",
                        "validation",
                        "--metric",
                        "score=0.7",
                        "--status",
                        "pass",
                    ],
                    cwd=str(self.workspace),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        results = [process.communicate() + (process.returncode,) for process in processes]
        for stdout, stderr, returncode in results:
            self.assertEqual(returncode, 0, f"parallel record failed\nstdout={stdout}\nstderr={stderr}")

        lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        parsed = [json.loads(line) for line in lines]
        self.assertEqual(len(parsed), 9)
        self.assertEqual(len({entry["attempt_id"] for entry in parsed}), 9)

    def test_stop_hook_is_owner_scoped_reentry_safe_and_waiting_human_safe(self) -> None:
        research = self.init_iteration("stop-i1", enable_hooks=True)
        self.write_compilable_fixture(research, "stop-i1", locked=True)
        self.compile_goal(research)
        self.start_loop(research, "owner-session")

        first_result, first_output = self.run_hook(
            "stop_goal_guard.js",
            self.stop_payload(self.workspace, "owner-session"),
        )
        self.assert_ok(first_result)
        self.assertTrue(self.is_block(first_output), first_output)

        reentry_result, reentry_output = self.run_hook(
            "stop_goal_guard.js",
            self.stop_payload(self.workspace, "owner-session", stop_hook_active=True),
        )
        self.assert_ok(reentry_result)
        self.assertFalse(self.is_block(reentry_output), reentry_output)

        other_result, other_output = self.run_hook(
            "stop_goal_guard.js",
            self.stop_payload(self.workspace, "other-session"),
        )
        self.assert_ok(other_result)
        self.assertFalse(self.is_block(other_output), other_output)

        background_result, background_output = self.run_hook(
            "stop_goal_guard.js",
            self.stop_payload(
                self.workspace,
                "owner-session",
                is_background_task=True,
                agent_type="background",
            ),
        )
        self.assert_ok(background_result)
        self.assertFalse(self.is_block(background_output), background_output)

        pause = self.run_script(
            "arx_loop.py",
            "pause",
            "--research-root",
            str(research),
            "--reason",
            "A human decision is required",
        )
        self.assert_ok(pause)
        _phase, status, _owner = self.loop_fields(self.loop_check(research))
        self.assertEqual(status, "waiting_human")
        waiting_result, waiting_output = self.run_hook(
            "stop_goal_guard.js",
            self.stop_payload(self.workspace, "owner-session"),
        )
        self.assert_ok(waiting_result)
        self.assertFalse(self.is_block(waiting_output), waiting_output)

    def test_stop_hook_budget_and_flatline_are_hard_stops(self) -> None:
        cases = [
            ("failed-budget", 1, 9, [("failed-1", 0.9, "fail", 1)]),
            (
                "flatline-budget",
                9,
                2,
                [
                    ("flat-1", 0.4, "pass", 0),
                    ("flat-2", 0.4, "pass", 0),
                ],
            ),
        ]
        for name, max_failed, max_flatline, attempts in cases:
            with self.subTest(name=name):
                workspace = self.workspace / name
                research = self.init_iteration(name, workspace=workspace, enable_hooks=True)
                self.write_compilable_fixture(
                    research,
                    name,
                    locked=True,
                    max_failed_attempts=max_failed,
                    max_flatline_count=max_flatline,
                    gate_value=1.0,
                )
                self.compile_goal(research, cwd=workspace)
                self.start_loop(research, "budget-owner", cwd=workspace)
                for attempt_id, score, status, exit_code in attempts:
                    self.assert_ok(
                        self.record(
                            research,
                            name,
                            attempt_id,
                            score=score,
                            status=status,
                            exit_code=exit_code,
                            cwd=workspace,
                        )
                    )
                stop_result, stop_output = self.run_hook(
                    "stop_goal_guard.js",
                    self.stop_payload(workspace, "budget-owner"),
                    cwd=workspace,
                )
                self.assert_ok(stop_result)
                self.assertIsNotNone(stop_output)
                self.assertIs(stop_output.get("continue"), False, stop_output)
                self.assertFalse(self.is_block(stop_output), stop_output)
                report = self.loop_check(research, cwd=workspace)
                self.assertEqual(report["outcome"], "no_progress")
                self.assertTrue(report["budget"]["exhausted"])

    def test_budget_outcome_does_not_depend_on_hooks(self) -> None:
        research = self.init_iteration("no-hook-budget")
        self.write_compilable_fixture(
            research,
            "no-hook-budget",
            locked=True,
            max_failed_attempts=1,
            gate_value=1.0,
        )
        self.compile_goal(research)
        self.start_loop(research)
        self.assert_ok(
            self.record(
                research,
                "no-hook-budget",
                "failed-once",
                status="fail",
                exit_code=1,
            )
        )
        report = self.loop_check(research)
        self.assertEqual(report["outcome"], "no_progress")
        self.assertEqual(report["status"], "waiting_human")
        self.assertIn("max_consecutive_failures", report["budget"]["exhausted"])

    def test_flatline_budget_tracks_declared_gate_metrics_only(self) -> None:
        research = self.init_iteration("tracked-flatline")
        self.write_compilable_fixture(
            research,
            "tracked-flatline",
            locked=True,
            max_flatline_count=2,
        )
        self.compile_goal(research)
        self.start_loop(research)
        for index, score in enumerate((0.6, 0.7), 1):
            result = self.run_script(
                "arx_record.py",
                "--research-root",
                str(research),
                "--iteration-id",
                "tracked-flatline",
                "--attempt-id",
                f"tracked-{index}",
                "--command",
                f"python eval.py --split validation --run {index}",
                "--data-split",
                "validation",
                "--metric",
                f"score={score}",
                "--metric",
                "aux_constant=1.0",
                            )
            self.assert_ok(result)
        for index in (3, 4):
            result = self.run_script(
                "arx_record.py",
                "--research-root",
                str(research),
                "--iteration-id",
                "tracked-flatline",
                "--attempt-id",
                f"train-flat-{index}",
                "--command",
                f"python eval.py --split train --run {index}",
                "--data-split",
                "train",
                "--metric",
                "score=0.5",
                            )
            self.assert_ok(result)
        report = self.loop_check(research)
        self.assertNotIn("max_flatline_count", report["budget"]["exhausted"])
        self.assertEqual(report["outcome"], "incomplete")

    def test_stop_continuation_budget_halts_on_a_later_turn(self) -> None:
        research = self.init_iteration("stop-cap-i1", enable_hooks=True)
        self.write_compilable_fixture(research, "stop-cap-i1", locked=True)
        self.compile_goal(research)
        self.start_loop(research, "owner-session")

        first_result, first_output = self.run_hook(
            "stop_goal_guard.js",
            self.stop_payload(self.workspace, "owner-session"),
        )
        self.assert_ok(first_result)
        self.assertTrue(self.is_block(first_output), first_output)

        reentry_result, _reentry_output = self.run_hook(
            "stop_goal_guard.js",
            self.stop_payload(self.workspace, "owner-session", stop_hook_active=True),
        )
        self.assert_ok(reentry_result)

        later_payload = self.stop_payload(self.workspace, "owner-session")
        later_payload["turn_id"] = "turn-2"
        later_result, later_output = self.run_hook("stop_goal_guard.js", later_payload)
        self.assert_ok(later_result)
        self.assertIs(later_output.get("continue"), False, later_output)
        report = self.loop_check(research)
        self.assertEqual(report["status"], "waiting_human")

        self.assert_ok(
            self.run_script(
                "arx_loop.py",
                "resume",
                "--research-root",
                str(research),
                "--reason",
                "Resume without granting another Stop continuation",
            )
        )
        self.start_loop(research, "owner-session")
        third_payload = self.stop_payload(self.workspace, "owner-session")
        third_payload["turn_id"] = "turn-3"
        third_result, third_output = self.run_hook("stop_goal_guard.js", third_payload)
        self.assert_ok(third_result)
        self.assertIs(third_output.get("continue"), False, third_output)
        self.assertFalse(self.is_block(third_output), third_output)


    def test_init_archive_existing_and_force_use_safe_archive_transitions(self) -> None:
        incomplete_workspace = self.workspace / "incomplete"
        incomplete = self.init_iteration("old-incomplete", workspace=incomplete_workspace)
        marker = incomplete / "current" / "old-marker.txt"
        marker.write_text("must survive rejected archive-existing\n", encoding="utf-8")
        rejected = self.run_script(
            "arx_init.py",
            "--research-root",
            str(incomplete),
            "--iteration-id",
            "new-i1",
            "--archive-existing",
            cwd=incomplete_workspace,
        )
        self.assert_rejected(rejected)
        self.assertTrue(marker.exists())
        self.assertFalse(any((incomplete / "archive").iterdir()))

        closed_workspace = self.workspace / "closed"
        closed = self.init_iteration("old-closed", workspace=closed_workspace)
        self.write_compilable_fixture(closed, "old-closed", locked=True)
        self.compile_goal(closed, cwd=closed_workspace)
        self.start_loop(closed, "closed-owner", cwd=closed_workspace)
        self.assert_ok(self.record(closed, "old-closed", "closed-attempt", cwd=closed_workspace))
        self.assert_ok(self.audit(closed, cwd=closed_workspace))
        self.assert_ok(self.decide(closed, "stop", cwd=closed_workspace))
        rollover = self.run_script(
            "arx_init.py",
            "--research-root",
            str(closed),
            "--iteration-id",
            "new-closed",
            "--archive-existing",
            cwd=closed_workspace,
        )
        self.assert_ok(rollover)
        manifests = list((closed / "archive").glob("*/archive_manifest.yaml"))
        self.assertEqual(len(manifests), 1)
        manifest_text = manifests[0].read_text(encoding="utf-8")
        self.assertIn("input_digests", manifest_text)
        self.assertIn("audit_digest", manifest_text)
        self.assertIn("outcome", manifest_text)
        phase, status, _owner = self.loop_fields(self.loop_check(closed, cwd=closed_workspace))
        self.assertEqual((phase, status), ("draft", "idle"))

        force_workspace = self.workspace / "force"
        forced = self.init_iteration("force-old", workspace=force_workspace)
        stale = forced / "current" / "decision.yaml"
        stale.write_text("decision: stale-old-decision\n", encoding="utf-8")
        stale_only = forced / "current" / "stale-only.txt"
        stale_only.write_text("old iteration marker\n", encoding="utf-8")
        missing_reason = self.run_script(
            "arx_init.py",
            "--research-root",
            str(forced),
            "--iteration-id",
            "force-new",
            "--force",
            cwd=force_workspace,
        )
        self.assert_rejected(missing_reason)
        self.assertEqual(stale.read_text(encoding="utf-8"), "decision: stale-old-decision\n")

        recovered = self.run_script(
            "arx_init.py",
            "--research-root",
            str(forced),
            "--iteration-id",
            "force-new",
            "--force",
            "--force-reason",
            "Recover an interrupted loop fixture",
            cwd=force_workspace,
        )
        self.assert_ok(recovered)
        self.assertFalse((forced / "current" / "decision.yaml").exists())
        self.assertFalse((forced / "current" / "stale-only.txt").exists())
        recovery_manifests = list((forced / "archive").glob("*/archive_manifest.yaml"))
        self.assertEqual(len(recovery_manifests), 1)
        recovery_text = recovery_manifests[0].read_text(encoding="utf-8").lower()
        self.assertIn("outcome", recovery_text)
        self.assertIn("recover an interrupted loop fixture", recovery_text)

    def test_force_recovery_archives_current_without_a_readable_state(self) -> None:
        workspace = self.workspace / "raw-recovery"
        research = workspace / ".research"
        current = research / "current"
        current.mkdir(parents=True)
        (current / "partial.txt").write_text("survives recovery\n", encoding="utf-8")

        result = self.run_script(
            "arx_init.py",
            "--research-root",
            str(research),
            "--iteration-id",
            "recovered-i2",
            "--force",
            "--force-reason",
            "Recover a partial current without state",
            cwd=workspace,
        )
        self.assert_ok(result)
        archives = list((research / "archive").glob("*"))
        self.assertEqual(len(archives), 1)
        self.assertTrue((archives[0] / "partial.txt").exists())
        manifest = (archives[0] / "archive_manifest.yaml").read_text(encoding="utf-8")
        self.assertIn("recovery_error", manifest)
        self.assertTrue((research / "current" / "state.yaml").exists())

    def test_archive_move_failure_restores_closure_state(self) -> None:
        research = self.init_iteration("archive-failure-i1")
        self.write_compilable_fixture(research, "archive-failure-i1", locked=True)
        self.compile_goal(research)
        self.start_loop(research)
        self.assert_ok(self.record(research, "archive-failure-i1", "archive-ready"))
        self.assert_ok(self.audit(research))
        self.assert_ok(self.decide(research, "stop"))

        sys.path.insert(0, str(SCRIPTS))
        import arx_lifecycle as lifecycle_module

        original_move = lifecycle_module.shutil.move

        def fail_move(_source: str, _destination: str) -> None:
            raise OSError("injected move failure")

        lifecycle_module.shutil.move = fail_move
        try:
            with self.assertRaises(lifecycle_module.ArxError):
                lifecycle_module.archive_current(research)
        finally:
            lifecycle_module.shutil.move = original_move
            sys.path.remove(str(SCRIPTS))

        report = self.loop_check(research)
        self.assertTrue(report["ready"], report)
        self.assertEqual((report["phase"], report["status"]), ("closure", "closing"))
        self.assertFalse((research / "current" / "archive_manifest.yaml").exists())

    def test_v1_compiled_state_migrates_to_a_startable_state(self) -> None:
        research = self.init_iteration("legacy-i1")
        self.write_compilable_fixture(research, "legacy-i1", locked=True)
        self.compile_goal(research)
        (research / "current" / "state.yaml").write_text(
            "version: 1\n"
            "iteration_id: legacy-i1\n"
            "created_at: 2026-07-10T00:00:00Z\n"
            "updated_at: 2026-07-10T00:00:00Z\n"
            "hooks_enabled: false\n"
            "human_gate_required: true\n",
            encoding="utf-8",
        )
        report = self.loop_check(research)
        self.assertEqual((report["phase"], report["status"]), ("execution", "armed"))
        self.start_loop(research, "legacy-owner")

    def test_yaml_fallback_round_trips_empty_runtime_collections(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        import arx_common as common_module

        original_yaml = common_module._yaml
        common_module._yaml = None
        payload = {
            "version": 2,
            "loop": {"budget": {}},
            "events": [],
        }
        try:
            encoded = common_module.dump_yaml(payload)
            self.assertEqual(common_module.parse_simple_yaml(encoded), payload)
        finally:
            common_module._yaml = original_yaml
            sys.path.remove(str(SCRIPTS))

    def test_session_start_and_hooks_run_from_a_unicode_install_copy(self) -> None:
        project = self.workspace / "项目 空格"
        research = self.init_iteration("copy-i1", workspace=project, enable_hooks=True)
        self.write_compilable_fixture(research, "copy-i1", locked=True)
        self.compile_goal(research, cwd=project)
        self.start_loop(research, "copy-owner", cwd=project)

        installed = self.workspace / "插件 安装副本"
        shutil.copytree(PLUGIN_ROOT, installed)

        def installed_hook(name: str, payload: dict[str, Any]) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
            completed = subprocess.run(
                [NODE, str(installed / "hooks" / name)],
                cwd=str(project),
                text=True,
                input=json.dumps(payload),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.hook_env(),
            )
            parsed = json.loads(completed.stdout) if completed.stdout.strip() else None
            return completed, parsed

        result, payload = installed_hook(
            "session_recovery.js",
            {
                "session_id": "copy-owner",
                "turn_id": "resume-turn",
                "cwd": str(project),
                "hook_event_name": "SessionStart",
                "source": "resume",
            },
        )
        self.assert_ok(result)
        self.assertIn("additionalContext", payload["hookSpecificOutput"])
        self.assertIn("copy-i1", payload["hookSpecificOutput"]["additionalContext"])

        stop_result, stop_payload = installed_hook(
            "stop_goal_guard.js",
            {
                "session_id": "copy-owner",
                "turn_id": "stop-turn",
                "cwd": str(project),
                "hook_event_name": "Stop",
                "stop_hook_active": False,
            },
        )
        self.assert_ok(stop_result)
        self.assertTrue(self.is_block(stop_payload), stop_payload)

    def test_find_research_root_stops_at_nested_project_boundary(self) -> None:
        mono = self.workspace / "mono"
        pkg_a = mono / "pkg-a"
        pkg_b = mono / "pkg-b"
        nested = pkg_a / "src"
        nested.mkdir(parents=True)
        pkg_b.mkdir(parents=True)
        (mono / ".research" / "current").mkdir(parents=True)
        (pkg_a / ".research" / "current").mkdir(parents=True)
        (pkg_a / "package.json").write_text("{}", encoding="utf-8")
        (pkg_b / "package.json").write_text("{}", encoding="utf-8")
        (mono / "pyproject.toml").write_text("[project]\nname='mono'\n", encoding="utf-8")

        self.assertEqual(self.find_research_root(nested), pkg_a / ".research")
        self.assertIsNone(self.find_research_root(pkg_b))
        self.assertEqual(self.find_research_root(mono), mono / ".research")

        orphan = self.workspace / "orphan-pkg"
        orphan.mkdir()
        (orphan / ".arx-boundary").write_text("", encoding="utf-8")
        (self.workspace / ".research" / "current").mkdir(parents=True)
        self.assertIsNone(self.find_research_root(orphan))

    def test_hooks_cli_toggles_and_nested_package_does_not_inherit_parent(self) -> None:
        mono = self.workspace / "mono-hooks"
        child = mono / "services" / "api"
        child.mkdir(parents=True)
        research = self.init_iteration("mono-i1", workspace=mono, enable_hooks=True)
        (child / "package.json").write_text('{"name":"api"}', encoding="utf-8")

        status = self.run_script(
            "arx_loop.py",
            "hooks",
            "--research-root",
            str(research),
            "--json",
            cwd=mono,
        )
        self.assert_ok(status)
        self.assertTrue(json.loads(status.stdout)["hooks_enabled"])

        self.assertEqual(self.find_research_root(child), None)
        self.assertEqual(self.find_research_root(mono), research)

        off = self.run_script(
            "arx_loop.py",
            "hooks",
            "--off",
            "--research-root",
            str(research),
            cwd=mono,
        )
        self.assert_ok(off)
        self.assertIn("disabled", off.stdout.lower())
        status = self.run_script(
            "arx_loop.py",
            "hooks",
            "--research-root",
            str(research),
            "--json",
            cwd=mono,
        )
        self.assert_ok(status)
        self.assertFalse(json.loads(status.stdout)["hooks_enabled"])


    def test_prepare_review_and_subagent_gate_for_promote(self) -> None:
        research = self.init_iteration("review-i1")
        self.write_compilable_fixture(research, "review-i1", locked=True)
        self.compile_goal(research)
        self.start_loop(research)
        self.assert_ok(self.record(research, "review-i1", "attempt-1"))
        self.assert_ok(self.audit(research))
        promote = self.decide(research, "promote")
        self.assert_rejected(promote)
        self.assertTrue(
            "subagent" in promote.stderr.lower() or "forbidden" in promote.stderr.lower(),
            promote.stderr,
        )

        prep = self.run_script(
            "arx_loop.py",
            "prepare-review",
            "--research-root",
            str(research),
            "--json",
        )
        self.assert_ok(prep)
        self.assertTrue((research / "current" / "review_pack" / "REVIEW_INSTRUCTIONS.md").exists())
        self.write_subagent_review(research, verdict="pass")
        # Re-audit so claim support stays fresh, then rebind review to new digest.
        self.assert_ok(self.audit(research))
        self.write_subagent_review(research, verdict="pass")
        self.assert_ok(self.decide(research, "promote"))
        check = self.loop_check(research)
        self.assertTrue(check.get("process_ready"))
        self.assertTrue(check.get("outcome_ready"))
        self.assertTrue(check.get("goal_ready"))
        self.assertEqual(check.get("outcome"), "achieved")

    def test_session_start_recovery_mentions_state(self) -> None:
        research = self.init_iteration("ritual-i1", enable_hooks=True)
        self.write_compilable_fixture(research, "ritual-i1", locked=True)
        self.compile_goal(research)
        result, output = self.run_hook(
            "session_recovery.js",
            {
                "session_id": "s1",
                "cwd": str(self.workspace),
                "hook_event_name": "SessionStart",
            },
        )
        self.assert_ok(result)
        self.assertIsNotNone(output)
        context = str(output)
        self.assertIn("ritual-i1", context)
        self.assertIn("arx_loop.py check", context)


if __name__ == "__main__":
    unittest.main()
