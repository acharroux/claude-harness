"""Python port of tests/layer1/test-contract.bats"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, call

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from tests.helpers.test_helper import HarnessTestCase, FIXTURE_DIR
from harness.lib.utils import init_harness_state, HARNESS_STATE


class ContractNegotiationTests(HarnessTestCase):
    """Port of tests/layer1/test-contract.bats."""

    def setUp(self):
        super().setUp()
        os.environ["MOCK_CLAUDE_SCENARIO"] = "pass"
        os.environ["MAX_CONTRACT_ROUNDS"] = "3"
        init_harness_state("Test", "general")
        self.install_fixture("product-spec-minimal.md", f"{HARNESS_STATE}/product-spec.md")
        self.install_fixture("sprint-plan-2sprint.json", f"{HARNESS_STATE}/sprint-plan.json")
        self.install_fixture("handoff-initial.json", f"{HARNESS_STATE}/handoff.json")

    def _mock_evaluate(self, agent, prompt, **kwargs):
        """Simulate evaluator returning accepted contract review."""
        if agent == "evaluator":
            sprint_dir = f"{HARNESS_STATE}/sprints/sprint-01"
            os.makedirs(sprint_dir, exist_ok=True)
            self.install_fixture("contract-review-accepted.json",
                                 f"{sprint_dir}/contract-review.json")
        elif agent == "generator":
            sprint_dir = f"{HARNESS_STATE}/sprints/sprint-01"
            os.makedirs(sprint_dir, exist_ok=True)
            self.install_fixture("contract-proposal-valid.json",
                                 f"{sprint_dir}/contract-proposal.json")
        return 0

    def _mock_revise_then_accept(self, agent, prompt, **kwargs):
        """Simulate evaluator requesting revisions on first call, accepting on second."""
        sprint_dir = f"{HARNESS_STATE}/sprints/sprint-01"
        os.makedirs(sprint_dir, exist_ok=True)
        if agent == "generator":
            self.install_fixture("contract-proposal-valid.json",
                                 f"{sprint_dir}/contract-proposal.json")
        elif agent == "evaluator":
            # Count evaluator calls
            count_file = Path(self.test_temp_dir) / ".eval-count"
            count = int(count_file.read_text()) if count_file.exists() else 0
            count += 1
            count_file.write_text(str(count))
            if count <= 1:
                self.install_fixture("contract-review-revise.json",
                                     f"{sprint_dir}/contract-review.json")
            else:
                self.install_fixture("contract-review-accepted.json",
                                     f"{sprint_dir}/contract-review.json")
        return 0

    def test_creates_contract_json_on_acceptance(self):
        """negotiate_contract: creates contract.json on acceptance."""
        from harness.lib.contract import negotiate_contract
        with patch("harness.lib.contract.invoke_claude", side_effect=self._mock_evaluate):
            negotiate_contract(1)
        self.assertTrue(Path(f"{HARNESS_STATE}/sprints/sprint-01/contract.json").is_file())

    def test_creates_proposal_and_review(self):
        """negotiate_contract: creates proposal and review files."""
        from harness.lib.contract import negotiate_contract
        with patch("harness.lib.contract.invoke_claude", side_effect=self._mock_evaluate):
            negotiate_contract(1)
        self.assertTrue(Path(f"{HARNESS_STATE}/sprints/sprint-01/contract-proposal.json").is_file())
        self.assertTrue(Path(f"{HARNESS_STATE}/sprints/sprint-01/contract-review.json").is_file())

    def test_invokes_both_generator_and_evaluator(self):
        """negotiate_contract: invokes both generator and evaluator."""
        agents_called = []
        def capture(agent, prompt, **kwargs):
            agents_called.append(agent)
            return self._mock_evaluate(agent, prompt, **kwargs)

        from harness.lib.contract import negotiate_contract
        with patch("harness.lib.contract.invoke_claude", side_effect=capture):
            negotiate_contract(1)
        self.assertIn("generator", agents_called)
        self.assertIn("evaluator", agents_called)

    def test_revise_then_accept_takes_two_rounds(self):
        """negotiate_contract: revise-then-accept calls generator twice."""
        agents_called = []
        def capture(agent, prompt, **kwargs):
            agents_called.append(agent)
            return self._mock_revise_then_accept(agent, prompt, **kwargs)

        from harness.lib.contract import negotiate_contract
        with patch("harness.lib.contract.invoke_claude", side_effect=capture):
            negotiate_contract(1)
        self.assertEqual(agents_called.count("generator"), 2)

    def test_returns_true_on_success(self):
        """negotiate_contract: returns True on success."""
        from harness.lib.contract import negotiate_contract
        with patch("harness.lib.contract.invoke_claude", side_effect=self._mock_evaluate):
            result = negotiate_contract(1)
        self.assertTrue(result)


class ContractToleranceTests(HarnessTestCase):
    """Unit tests for parse_decision and count_criteria tolerance helpers."""

    def setUp(self):
        super().setUp()

    def test_decision_accepted(self):
        from harness.lib.contract import is_accepted
        self.assertTrue(is_accepted({"decision": "accepted"}))

    def test_decision_accept(self):
        from harness.lib.contract import is_accepted
        self.assertTrue(is_accepted({"decision": "accept"}))

    def test_decision_approved(self):
        from harness.lib.contract import is_accepted
        self.assertTrue(is_accepted({"decision": "approved"}))

    def test_decision_approve(self):
        from harness.lib.contract import is_accepted
        self.assertTrue(is_accepted({"decision": "approve"}))

    def test_decision_review_verdict(self):
        from harness.lib.contract import is_accepted
        self.assertTrue(is_accepted({"reviewVerdict": "accepted"}))

    def test_decision_verdict(self):
        from harness.lib.contract import is_accepted
        self.assertTrue(is_accepted({"verdict": "accepted"}))

    def test_decision_case_insensitive(self):
        from harness.lib.contract import is_accepted
        self.assertTrue(is_accepted({"decision": "ACCEPTED"}))

    def test_decision_unknown_is_rejected(self):
        from harness.lib.contract import is_accepted
        self.assertFalse(is_accepted({"decision": "revise"}))

    def test_count_from_criteria_list(self):
        from harness.lib.contract import count_criteria
        self.assertEqual(count_criteria({"criteria": [1, 2, 3]}), 3)

    def test_count_from_features_acceptanceCriteria(self):
        from harness.lib.contract import count_criteria
        data = {"features": [{"acceptanceCriteria": [1, 2]}, {"acceptanceCriteria": [3]}]}
        self.assertEqual(count_criteria(data), 3)

    def test_count_from_flat_acceptanceCriteria(self):
        from harness.lib.contract import count_criteria
        self.assertEqual(count_criteria({"acceptanceCriteria": [1, 2]}), 2)

    def test_count_empty_returns_zero(self):
        from harness.lib.contract import count_criteria
        self.assertEqual(count_criteria({}), 0)


if __name__ == "__main__":
    unittest.main()
