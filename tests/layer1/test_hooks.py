"""Tests for the Python hook scripts (harness/hooks/*.py).

Drives on-generator-stop.py, on-evaluator-stop.py, and on-stop.py directly
via subprocess. No bash or jq required.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent.parent
HOOKS_DIR = _PROJECT / "harness" / "hooks"


def _run_hook(hook_name: str, cwd: str, env=None) -> int:
    hook_path = HOOKS_DIR / hook_name
    python = sys.executable or "python"
    result = subprocess.run(
        [python, str(hook_path)],
        input=b"",
        cwd=cwd,
        env={**os.environ, "HARNESS_STATE": "harness-state", **(env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode


class HookTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-hooks-test-")
        self.hs = os.path.join(self.tmp, "harness-state")
        os.makedirs(os.path.join(self.hs, "sprints"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sprint_dir(self, name="sprint-01"):
        d = os.path.join(self.hs, "sprints", name)
        os.makedirs(d, exist_ok=True)
        return d

    def _write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))

    def run_hook(self, name):
        return _run_hook(name, self.tmp)


class OnGeneratorStopTests(HookTestBase):

    def test_allows_ready_for_eval_with_log(self):
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "ready-for-eval", "attempt": 1})
        self._write(f"{d}/generator-log.md", "# Log\n")
        self.assertEqual(self.run_hook("on-generator-stop.py"), 0)

    def test_blocks_ready_for_eval_without_log(self):
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "ready-for-eval", "attempt": 1})
        self.assertEqual(self.run_hook("on-generator-stop.py"), 2)

    def test_allows_blocked_status(self):
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "blocked", "attempt": 1})
        self.assertEqual(self.run_hook("on-generator-stop.py"), 0)

    def test_allows_no_active_sprint(self):
        self.assertEqual(self.run_hook("on-generator-stop.py"), 0)

    def test_blocks_active_status(self):
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "active", "attempt": 1})
        self.assertEqual(self.run_hook("on-generator-stop.py"), 2)

    def test_allows_contract_negotiation_phase(self):
        """No status.json yet, but contract-proposal.json exists — allow."""
        d = self._sprint_dir()
        self._write(f"{d}/contract-proposal.json", {"criteria": []})
        self.assertEqual(self.run_hook("on-generator-stop.py"), 0)


class OnEvaluatorStopTests(HookTestBase):

    def test_allows_valid_eval_report(self):
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "ready-for-eval", "attempt": 1})
        self._write(f"{d}/contract.json", {"criteria": [{"id": "C1"}, {"id": "C2"}, {"id": "C3"}]})
        self._write(f"{d}/eval-report.json", {
            "overallResult": "PASS",
            "criteriaResults": [{"id": "C1", "result": "PASS"}, {"id": "C2", "result": "PASS"}, {"id": "C3", "result": "PASS"}]
        })
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 0)

    def test_blocks_when_eval_report_missing(self):
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "ready-for-eval", "attempt": 1})
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 2)

    def test_blocks_when_overallResult_missing(self):
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "ready-for-eval", "attempt": 1})
        self._write(f"{d}/eval-report.json", {"criteriaResults": []})
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 2)

    def test_blocks_when_criteriaResults_missing(self):
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "ready-for-eval", "attempt": 1})
        self._write(f"{d}/eval-report.json", {"overallResult": "PASS"})
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 2)

    def test_blocks_when_criteria_count_mismatch(self):
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "ready-for-eval", "attempt": 1})
        self._write(f"{d}/contract.json", {"criteria": [{"id": "C1"}, {"id": "C2"}, {"id": "C3"}]})
        self._write(f"{d}/eval-report.json", {
            "overallResult": "PASS",
            "criteriaResults": [{"id": "C1", "result": "PASS"}]
        })
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 2)

    def test_allows_valid_contract_review(self):
        d = self._sprint_dir()
        self._write(f"{d}/contract-proposal.json", {"criteria": []})
        self._write(f"{d}/contract-review.json", {"decision": "accepted", "feedback": "OK"})
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 0)

    def test_blocks_contract_review_without_decision(self):
        d = self._sprint_dir()
        self._write(f"{d}/contract-proposal.json", {"criteria": []})
        self._write(f"{d}/contract-review.json", {"feedback": "needs work"})
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 2)

    def test_blocks_contract_review_missing_file(self):
        d = self._sprint_dir()
        self._write(f"{d}/contract-proposal.json", {"criteria": []})
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 2)

    def test_allows_no_active_sprint(self):
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 0)

    def test_tolerates_result_field_name(self):
        """Tolerates .result instead of .overallResult."""
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "ready-for-eval", "attempt": 1})
        self._write(f"{d}/eval-report.json", {
            "result": "PASS",
            "criteriaResults": [{"id": "C1", "result": "PASS"}]
        })
        self.assertEqual(self.run_hook("on-evaluator-stop.py"), 0)


class OnStopTests(HookTestBase):

    def test_allows_no_sprint_plan(self):
        self.assertEqual(self.run_hook("on-stop.py"), 0)

    def test_allows_no_active_sprints(self):
        self._write(f"{self.hs}/sprint-plan.json", {"sprints": [{"number": 1}]})
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "pass", "attempt": 1})
        self.assertEqual(self.run_hook("on-stop.py"), 0)

    def test_blocks_when_sprint_is_active(self):
        self._write(f"{self.hs}/sprint-plan.json", {"sprints": [{"number": 1}]})
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "active", "attempt": 1})
        self.assertEqual(self.run_hook("on-stop.py"), 2)

    def test_blocks_when_sprint_is_ready_for_eval(self):
        self._write(f"{self.hs}/sprint-plan.json", {"sprints": [{"number": 1}]})
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "ready-for-eval", "attempt": 1})
        self.assertEqual(self.run_hook("on-stop.py"), 2)

    def test_blocks_when_sprint_is_negotiating(self):
        self._write(f"{self.hs}/sprint-plan.json", {"sprints": [{"number": 1}]})
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "negotiating", "attempt": 1})
        self.assertEqual(self.run_hook("on-stop.py"), 2)

    def test_allows_completed_sprint(self):
        self._write(f"{self.hs}/sprint-plan.json", {"sprints": [{"number": 1}]})
        d = self._sprint_dir()
        self._write(f"{d}/status.json", {"status": "eval-pass", "attempt": 1})
        self.assertEqual(self.run_hook("on-stop.py"), 0)


if __name__ == "__main__":
    unittest.main()
