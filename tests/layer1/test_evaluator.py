"""Python port of tests/layer1/test-evaluator.bats"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from tests.helpers.test_helper import HarnessTestCase, FIXTURE_DIR
from harness.lib.utils import init_harness_state, HARNESS_STATE


class EvaluatorTests(HarnessTestCase):
    """Port of tests/layer1/test-evaluator.bats."""

    def setUp(self):
        super().setUp()
        os.environ["MOCK_CLAUDE_SCENARIO"] = "pass"
        init_harness_state("Test", "general")
        os.makedirs(f"{HARNESS_STATE}/sprints/sprint-01", exist_ok=True)
        self.install_fixture("contract-sprint01.json",
                             f"{HARNESS_STATE}/sprints/sprint-01/contract.json")
        self.install_fixture("handoff-initial.json", f"{HARNESS_STATE}/handoff.json")

    def _mock_eval_pass(self, agent, prompt, **kwargs):
        sprint_dir = f"{HARNESS_STATE}/sprints/sprint-01"
        self.install_fixture("eval-report-pass.json", f"{sprint_dir}/eval-report.json")
        Path(f"{sprint_dir}/status.json").write_text(
            '{"status":"pass","attempt":1}', encoding="utf-8"
        )
        return 0

    def _mock_eval_fail(self, agent, prompt, **kwargs):
        sprint_dir = f"{HARNESS_STATE}/sprints/sprint-01"
        self.install_fixture("eval-report-fail-blocking.json", f"{sprint_dir}/eval-report.json")
        Path(f"{sprint_dir}/status.json").write_text(
            '{"status":"fail","attempt":1}', encoding="utf-8"
        )
        return 0

    def _mock_regression_pass(self, agent, prompt, **kwargs):
        return 0

    def test_returns_true_on_pass(self):
        """invoke_evaluator: returns True on PASS."""
        from harness.lib.evaluator import invoke_evaluator
        with patch("harness.lib.evaluator.invoke_claude", side_effect=self._mock_eval_pass):
            self.assertTrue(invoke_evaluator(1, 1))

    def test_returns_false_on_fail(self):
        """invoke_evaluator: returns False on FAIL."""
        from harness.lib.evaluator import invoke_evaluator
        with patch("harness.lib.evaluator.invoke_claude", side_effect=self._mock_eval_fail):
            self.assertFalse(invoke_evaluator(1, 1))

    def test_creates_eval_report_json(self):
        """invoke_evaluator: creates eval-report.json with .overallResult."""
        from harness.lib.evaluator import invoke_evaluator
        with patch("harness.lib.evaluator.invoke_claude", side_effect=self._mock_eval_pass):
            invoke_evaluator(1, 1)
        report_path = Path(f"{HARNESS_STATE}/sprints/sprint-01/eval-report.json")
        self.assertTrue(report_path.is_file())
        self.assertIn("overallResult",
                      json.loads(report_path.read_text(encoding="utf-8")))

    def test_logs_invocation(self):
        """invoke_evaluator: invokes with agent='evaluator'."""
        agents_called = []
        def capture(agent, prompt, **kwargs):
            agents_called.append(agent)
            return self._mock_eval_pass(agent, prompt, **kwargs)

        from harness.lib.evaluator import invoke_evaluator
        with patch("harness.lib.evaluator.invoke_claude", side_effect=capture):
            invoke_evaluator(1, 1)
        self.assertIn("evaluator", agents_called)

    def test_regression_returns_true_on_pass(self):
        """invoke_regression: returns True when all pass."""
        from harness.lib.evaluator import invoke_regression
        with patch("harness.lib.evaluator.invoke_claude", side_effect=self._mock_regression_pass):
            self.assertTrue(invoke_regression())


class EvaluatorToleranceTests(HarnessTestCase):
    """Unit tests for field tolerance helpers in evaluator.py."""

    def setUp(self):
        super().setUp()

    def test_overallResult_field(self):
        from harness.lib.evaluator import _get_result
        self.assertEqual(_get_result({"overallResult": "PASS"}), "pass")

    def test_result_field(self):
        from harness.lib.evaluator import _get_result
        self.assertEqual(_get_result({"result": "pass"}), "pass")

    def test_verdict_field(self):
        from harness.lib.evaluator import _get_result
        self.assertEqual(_get_result({"verdict": "passed"}), "passed")

    def test_pass_case_insensitive(self):
        from harness.lib.evaluator import _get_result
        self.assertEqual(_get_result({"overallResult": "Pass"}), "pass")

    def test_pass_count_direct(self):
        from harness.lib.evaluator import _get_count
        self.assertEqual(_get_count({"passCount": 5}, "passCount", "pass_count"), 5)

    def test_pass_count_snake(self):
        from harness.lib.evaluator import _get_count
        self.assertEqual(_get_count({"pass_count": 3}, "passCount", "pass_count"), 3)

    def test_pass_count_score_nested(self):
        from harness.lib.evaluator import _get_count
        self.assertEqual(
            _get_count({"score": {"passedCriteria": 7}},
                       "passCount", "pass_count", "score.passedCriteria"),
            7,
        )

    def test_count_returns_zero_for_missing(self):
        from harness.lib.evaluator import _get_count
        self.assertEqual(_get_count({}, "passCount", "pass_count"), 0)


if __name__ == "__main__":
    unittest.main()
