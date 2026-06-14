"""Python port of tests/layer1/test-generator.bats"""

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


class GeneratorTests(HarnessTestCase):
    """Port of tests/layer1/test-generator.bats."""

    def setUp(self):
        super().setUp()
        os.environ["MOCK_CLAUDE_SCENARIO"] = "pass"
        init_harness_state("Test", "general")
        os.makedirs(f"{HARNESS_STATE}/sprints/sprint-01", exist_ok=True)
        self.install_fixture("contract-sprint01.json",
                             f"{HARNESS_STATE}/sprints/sprint-01/contract.json")

    def _mock_generator_pass(self, agent, prompt, **kwargs):
        sprint_dir = f"{HARNESS_STATE}/sprints/sprint-01"
        self.install_fixture("status-ready-for-eval.json", f"{sprint_dir}/status.json")
        self.install_fixture("generator-log-sample.md", f"{sprint_dir}/generator-log.md")
        return 0

    def _mock_generator_blocked(self, agent, prompt, **kwargs):
        sprint_dir = f"{HARNESS_STATE}/sprints/sprint-01"
        self.install_fixture("status-blocked.json", f"{sprint_dir}/status.json")
        return 0

    def test_creates_status_json(self):
        """invoke_generator: creates status.json with ready-for-eval."""
        from harness.lib.generator import invoke_generator
        with patch("harness.lib.generator.invoke_claude", side_effect=self._mock_generator_pass):
            invoke_generator(1, 1)
        status_path = Path(f"{HARNESS_STATE}/sprints/sprint-01/status.json")
        self.assertTrue(status_path.is_file())
        self.assertEqual(
            json.loads(status_path.read_text(encoding="utf-8")).get("status"),
            "ready-for-eval",
        )

    def test_creates_generator_log_md(self):
        """invoke_generator: creates generator-log.md."""
        from harness.lib.generator import invoke_generator
        with patch("harness.lib.generator.invoke_claude", side_effect=self._mock_generator_pass):
            invoke_generator(1, 1)
        self.assertTrue(Path(f"{HARNESS_STATE}/sprints/sprint-01/generator-log.md").is_file())

    def test_returns_0_on_success(self):
        """invoke_generator: returns 0 on success."""
        from harness.lib.generator import invoke_generator
        with patch("harness.lib.generator.invoke_claude", side_effect=self._mock_generator_pass):
            rc = invoke_generator(1, 1)
        self.assertEqual(rc, 0)

    def test_returns_2_when_blocked(self):
        """invoke_generator: returns 2 when blocked (CRITICAL exit code!)."""
        from harness.lib.generator import invoke_generator
        with patch("harness.lib.generator.invoke_claude", side_effect=self._mock_generator_blocked):
            rc = invoke_generator(1, 1)
        self.assertEqual(rc, 2)

    def test_logs_invocation(self):
        """invoke_generator: invokes with agent='generator'."""
        agents_called = []
        def capture(agent, prompt, **kwargs):
            agents_called.append(agent)
            return self._mock_generator_pass(agent, prompt, **kwargs)

        from harness.lib.generator import invoke_generator
        with patch("harness.lib.generator.invoke_claude", side_effect=capture):
            invoke_generator(1, 1)
        self.assertIn("generator", agents_called)


if __name__ == "__main__":
    unittest.main()
