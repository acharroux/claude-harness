"""Python port of tests/layer1/test-planner.bats"""

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

from tests.helpers.test_helper import HarnessTestCase
from harness.lib.utils import init_harness_state, HARNESS_STATE


def _mock_invoke(fixture_dir: str, scenario: str = "pass"):
    """Return a mock for invoke_claude that runs mock_claude.py."""
    import subprocess
    mock_script = str(_PROJECT / "tests" / "helpers" / "mock_claude.py")

    def _invoke(agent, prompt, max_turns=50, mcp_config=None):
        env = {
            **os.environ,
            "MOCK_CLAUDE_FIXTURE_DIR": fixture_dir,
            "MOCK_CLAUDE_SCENARIO": scenario,
        }
        subprocess.run(
            [sys.executable, mock_script, "--agent", agent, "-p", prompt],
            env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        return 0

    return _invoke


class PlannerTests(HarnessTestCase):
    """Port of tests/layer1/test-planner.bats."""

    def setUp(self):
        super().setUp()
        os.environ["MOCK_CLAUDE_SCENARIO"] = "pass"
        init_harness_state("Test project", "general")

    @patch("harness.lib.planner.invoke_claude")
    def _invoke_planner(self, mode, mock_invoke):
        from tests.helpers.test_helper import FIXTURE_DIR
        mock_invoke.side_effect = _mock_invoke(str(FIXTURE_DIR))
        from harness.lib.planner import invoke_planner
        return invoke_planner(mode)

    def test_returns_sprint_count(self):
        """invoke_planner: returns sprint count (2 for the 2-sprint fixture)."""
        self.assertEqual(self._invoke_planner("new"), 2)

    def test_creates_product_spec_md(self):
        """invoke_planner: creates product-spec.md."""
        self._invoke_planner("new")
        spec_path = Path(HARNESS_STATE) / "product-spec.md"
        self.assertTrue(spec_path.is_file())
        self.assertGreater(spec_path.stat().st_size, 0)

    def test_creates_sprint_plan_json(self):
        """invoke_planner: creates sprint-plan.json with .sprints array."""
        self._invoke_planner("new")
        plan_path = Path(HARNESS_STATE) / "sprint-plan.json"
        self.assertTrue(plan_path.is_file())
        self.assertIn("sprints", json.loads(plan_path.read_text(encoding="utf-8")))

    def test_logs_mock_invocation(self):
        """invoke_planner: logs mock invocation with agent=planner."""
        from tests.helpers.test_helper import FIXTURE_DIR

        log_calls = []
        with patch("harness.lib.planner.invoke_claude") as mock_invoke:
            def capture(agent, prompt, **kwargs):
                log_calls.append(agent)
                _mock_invoke(str(FIXTURE_DIR))(agent, prompt, **kwargs)
                return 0
            mock_invoke.side_effect = capture
            from harness.lib.planner import invoke_planner
            invoke_planner("new")

        self.assertIn("planner", log_calls)

    def test_extend_mode_prompt_contains_extend(self):
        """invoke_planner: extend mode prompt mentions 'extend'."""
        self.install_fixture("product-spec-minimal.md", f"{HARNESS_STATE}/product-spec.md")
        self.install_fixture("sprint-plan-2sprint.json", f"{HARNESS_STATE}/sprint-plan.json")
        self.install_fixture("handoff-initial.json", f"{HARNESS_STATE}/handoff.json")

        prompts = []
        with patch("harness.lib.planner.invoke_claude") as mock_invoke:
            from tests.helpers.test_helper import FIXTURE_DIR
            def capture(agent, prompt, **kwargs):
                prompts.append(prompt)
                _mock_invoke(str(FIXTURE_DIR))(agent, prompt, **kwargs)
                return 0
            mock_invoke.side_effect = capture
            from harness.lib.planner import invoke_planner
            invoke_planner("extend")

        self.assertTrue(any("extend" in p.lower() for p in prompts))


if __name__ == "__main__":
    unittest.main()
