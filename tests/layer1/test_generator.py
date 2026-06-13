"""Python port of tests/layer1/test-generator.bats"""

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


class GeneratorTests(HarnessTestCase):
    """Port of tests/layer1/test-generator.bats."""

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

    def _invoke_generator(self, sprint_num=1, attempt=1):
        from harness.lib import generator as gen_mod
        import importlib
        importlib.reload(gen_mod)
        return gen_mod.invoke_generator(sprint_num, attempt)

    def test_creates_status_json(self):
        """invoke_generator: creates status.json with ready-for-eval."""
        self._invoke_generator(1, 1)
        status_path = Path(f"{HARNESS_STATE}/sprints/sprint-01/status.json")
        self.assertTrue(status_path.is_file())
        data = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(data.get("status"), "ready-for-eval")

    def test_creates_generator_log_md(self):
        """invoke_generator: creates generator-log.md."""
        self._invoke_generator(1, 1)
        log_path = Path(f"{HARNESS_STATE}/sprints/sprint-01/generator-log.md")
        self.assertTrue(log_path.is_file())

    def test_returns_0_on_success(self):
        """invoke_generator: returns 0 on success."""
        rc = self._invoke_generator(1, 1)
        self.assertEqual(rc, 0)

    def test_returns_2_when_blocked(self):
        """invoke_generator: returns 2 when blocked (CRITICAL exit code!)."""
        os.environ["MOCK_CLAUDE_SCENARIO"] = "fail-generator-blocked"
        rc = self._invoke_generator(1, 1)
        self.assertEqual(rc, 2)

    def test_logs_invocation(self):
        """invoke_generator: logs invocation with agent=generator."""
        self._invoke_generator(1, 1)
        log_text = Path(self.mock_claude_log).read_text(encoding="utf-8")
        self.assertIn("agent=generator", log_text)


if __name__ == "__main__":
    unittest.main()
