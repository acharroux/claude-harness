"""Python port of tests/layer1/test-evaluator.bats"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from tests.helpers.test_helper import HarnessTestCase
from harness.lib.utils import init_harness_state, HARNESS_STATE


class EvaluatorTests(HarnessTestCase):
    """Port of tests/layer1/test-evaluator.bats."""

    def _put_mock_on_path(self):
        helpers_dir = str(_PROJECT / "tests" / "helpers")
        os.environ["PATH"] = helpers_dir + os.pathsep + os.environ.get("PATH", "")

    def setUp(self):
        super().setUp()
        self._put_mock_on_path()
        os.environ["MOCK_CLAUDE_SCENARIO"] = "pass"
        init_harness_state("Test", "general")
        os.makedirs(f"{HARNESS_STATE}/sprints/sprint-01", exist_ok=True)
        self.install_fixture("contract-sprint01.json", f"{HARNESS_STATE}/sprints/sprint-01/contract.json")
        self.install_fixture("handoff-initial.json", f"{HARNESS_STATE}/handoff.json")

    def _invoke_evaluator(self, sprint_num=1, attempt=1):
        from harness.lib import evaluator as eval_mod
        import importlib
        importlib.reload(eval_mod)
        return eval_mod.invoke_evaluator(sprint_num, attempt)

    def _invoke_regression(self):
        from harness.lib import evaluator as eval_mod
        import importlib
        importlib.reload(eval_mod)
        return eval_mod.invoke_regression()

    def test_returns_true_on_pass(self):
        """invoke_evaluator: returns True (bash exit 0) on PASS."""
        result = self._invoke_evaluator(1, 1)
        self.assertTrue(result)

    def test_returns_false_on_fail(self):
        """invoke_evaluator: returns False (bash exit 1) on FAIL."""
        os.environ["MOCK_CLAUDE_SCENARIO"] = "fail-eval"
        result = self._invoke_evaluator(1, 1)
        self.assertFalse(result)

    def test_creates_eval_report_json(self):
        """invoke_evaluator: creates eval-report.json with .overallResult."""
        self._invoke_evaluator(1, 1)
        report_path = Path(f"{HARNESS_STATE}/sprints/sprint-01/eval-report.json")
        self.assertTrue(report_path.is_file())
        data = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIn("overallResult", data)

    def test_logs_invocation(self):
        """invoke_evaluator: logs invocation with agent=evaluator."""
        self._invoke_evaluator(1, 1)
        log_text = Path(self.mock_claude_log).read_text(encoding="utf-8")
        self.assertIn("agent=evaluator", log_text)

    def test_regression_returns_true_on_pass(self):
        """invoke_regression: returns True when all pass."""
        result = self._invoke_regression()
        self.assertTrue(result)


class EvaluatorToleranceTests(HarnessTestCase):
    """Unit tests for field tolerance helpers in evaluator.py."""

    def _get_result(self, data):
        from harness.lib.evaluator import _get_result
        return _get_result(data)

    def _get_count(self, data, *keys):
        from harness.lib.evaluator import _get_count
        return _get_count(data, *keys)

    def test_overallResult_field(self):
        self.assertEqual(self._get_result({"overallResult": "PASS"}), "pass")

    def test_result_field(self):
        self.assertEqual(self._get_result({"result": "pass"}), "pass")

    def test_verdict_field(self):
        self.assertEqual(self._get_result({"verdict": "passed"}), "passed")

    def test_pass_case_insensitive(self):
        self.assertEqual(self._get_result({"overallResult": "Pass"}), "pass")

    def test_pass_count_direct(self):
        self.assertEqual(self._get_count({"passCount": 5}, "passCount", "pass_count"), 5)

    def test_pass_count_snake(self):
        self.assertEqual(self._get_count({"pass_count": 3}, "passCount", "pass_count"), 3)

    def test_pass_count_score_nested(self):
        self.assertEqual(
            self._get_count({"score": {"passedCriteria": 7}}, "passCount", "pass_count", "score.passedCriteria"),
            7,
        )

    def test_count_returns_zero_for_missing(self):
        self.assertEqual(self._get_count({}, "passCount", "pass_count"), 0)


if __name__ == "__main__":
    unittest.main()
