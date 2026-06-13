"""Python port of tests/layer1/test-contract.bats"""

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


class ContractNegotiationTests(HarnessTestCase):
    """Port of tests/layer1/test-contract.bats."""

    def _put_mock_on_path(self):
        helpers_dir = str(_PROJECT / "tests" / "helpers")
        os.environ["PATH"] = helpers_dir + os.pathsep + os.environ.get("PATH", "")

    def setUp(self):
        super().setUp()
        self._put_mock_on_path()
        os.environ["MOCK_CLAUDE_SCENARIO"] = "pass"
        os.environ["MAX_CONTRACT_ROUNDS"] = "3"
        init_harness_state("Test", "general")
        self.install_fixture("product-spec-minimal.md", f"{HARNESS_STATE}/product-spec.md")
        self.install_fixture("sprint-plan-2sprint.json", f"{HARNESS_STATE}/sprint-plan.json")
        self.install_fixture("handoff-initial.json", f"{HARNESS_STATE}/handoff.json")

    def _negotiate(self, sprint_num=1):
        from harness.lib import contract as contract_mod
        import importlib
        importlib.reload(contract_mod)
        return contract_mod.negotiate_contract(sprint_num)

    def test_creates_contract_json_on_acceptance(self):
        """negotiate_contract: creates contract.json on acceptance."""
        self._negotiate(1)
        contract_path = Path(f"{HARNESS_STATE}/sprints/sprint-01/contract.json")
        self.assertTrue(contract_path.is_file())

    def test_creates_proposal_and_review(self):
        """negotiate_contract: creates proposal and review files."""
        self._negotiate(1)
        self.assertTrue(Path(f"{HARNESS_STATE}/sprints/sprint-01/contract-proposal.json").is_file())
        self.assertTrue(Path(f"{HARNESS_STATE}/sprints/sprint-01/contract-review.json").is_file())

    def test_invokes_both_generator_and_evaluator(self):
        """negotiate_contract: invokes both generator and evaluator."""
        self._negotiate(1)
        log_text = Path(self.mock_claude_log).read_text(encoding="utf-8")
        self.assertIn("agent=generator", log_text)
        self.assertIn("agent=evaluator", log_text)

    def test_revise_then_accept_takes_two_rounds(self):
        """negotiate_contract: revise-then-accept scenario calls generator twice."""
        os.environ["MOCK_CLAUDE_SCENARIO"] = "revise-then-accept"
        self._negotiate(1)
        log_text = Path(self.mock_claude_log).read_text(encoding="utf-8")
        gen_count = log_text.count("agent=generator")
        self.assertEqual(gen_count, 2)

    def test_returns_true_on_success(self):
        """negotiate_contract: returns True (bash exit 0) on success."""
        result = self._negotiate(1)
        self.assertTrue(result)


class ContractToleranceTests(HarnessTestCase):
    """Unit tests for parse_decision and count_criteria tolerance helpers."""

    def setUp(self):
        super().setUp()

    def _parse_decision(self, data):
        from harness.lib.contract import parse_decision
        return parse_decision(data)

    def _is_accepted(self, data):
        from harness.lib.contract import is_accepted
        return is_accepted(data)

    def _count_criteria(self, data):
        from harness.lib.contract import count_criteria
        return count_criteria(data)

    # Decision tolerance
    def test_decision_accepted(self):
        self.assertTrue(self._is_accepted({"decision": "accepted"}))

    def test_decision_accept(self):
        self.assertTrue(self._is_accepted({"decision": "accept"}))

    def test_decision_approved(self):
        self.assertTrue(self._is_accepted({"decision": "approved"}))

    def test_decision_approve(self):
        self.assertTrue(self._is_accepted({"decision": "approve"}))

    def test_decision_review_verdict(self):
        self.assertTrue(self._is_accepted({"reviewVerdict": "accepted"}))

    def test_decision_verdict(self):
        self.assertTrue(self._is_accepted({"verdict": "accepted"}))

    def test_decision_case_insensitive(self):
        self.assertTrue(self._is_accepted({"decision": "ACCEPTED"}))

    def test_decision_unknown_is_rejected(self):
        self.assertFalse(self._is_accepted({"decision": "revise"}))

    # Criteria count tolerance
    def test_count_from_criteria_list(self):
        self.assertEqual(self._count_criteria({"criteria": [1, 2, 3]}), 3)

    def test_count_from_features_acceptanceCriteria(self):
        data = {"features": [{"acceptanceCriteria": [1, 2]}, {"acceptanceCriteria": [3]}]}
        self.assertEqual(self._count_criteria(data), 3)

    def test_count_from_flat_acceptanceCriteria(self):
        self.assertEqual(self._count_criteria({"acceptanceCriteria": [1, 2]}), 2)

    def test_count_empty_returns_zero(self):
        self.assertEqual(self._count_criteria({}), 0)


if __name__ == "__main__":
    unittest.main()
