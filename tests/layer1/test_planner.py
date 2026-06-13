"""Python port of tests/layer1/test-planner.bats"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is importable
_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from tests.helpers.test_helper import HarnessTestCase
from harness.lib.utils import init_harness_state, HARNESS_STATE


class PlannerTests(HarnessTestCase):
    """Port of tests/layer1/test-planner.bats — uses mock claude via PATH."""

    def _put_mock_on_path(self):
        helpers_dir = str(_PROJECT / "tests" / "helpers")
        os.environ["PATH"] = helpers_dir + os.pathsep + os.environ.get("PATH", "")

    def setUp(self):
        super().setUp()
        self._put_mock_on_path()
        os.environ["MOCK_CLAUDE_SCENARIO"] = "pass"
        init_harness_state("Test project", "general")

    def _invoke_planner(self, mode="new"):
        from harness.lib import planner as planner_mod
        import importlib
        importlib.reload(planner_mod)
        return planner_mod.invoke_planner(mode)

    def test_returns_sprint_count(self):
        """invoke_planner: returns sprint count (2 for the 2-sprint fixture)."""
        count = self._invoke_planner("new")
        self.assertEqual(count, 2)

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
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertIn("sprints", plan)

    def test_logs_mock_invocation(self):
        """invoke_planner: logs mock invocation with agent=planner."""
        self._invoke_planner("new")
        log_text = Path(self.mock_claude_log).read_text(encoding="utf-8")
        self.assertIn("agent=planner", log_text)

    def test_extend_mode_prompt_contains_extend(self):
        """invoke_planner: extend mode passes prompt mentioning 'extend'."""
        # Pre-install product-spec and sprint-plan so extend mode has something to read
        self.install_fixture("product-spec-minimal.md", f"{HARNESS_STATE}/product-spec.md")
        self.install_fixture("sprint-plan-2sprint.json", f"{HARNESS_STATE}/sprint-plan.json")
        self.install_fixture("handoff-initial.json", f"{HARNESS_STATE}/handoff.json")
        self._invoke_planner("extend")
        log_text = Path(self.mock_claude_log).read_text(encoding="utf-8")
        self.assertIn("extend", log_text.lower())


if __name__ == "__main__":
    unittest.main()
