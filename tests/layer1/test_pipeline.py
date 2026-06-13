"""End-to-end integration test for the Python harness orchestrator.

Drives orchestrate.py's run_new_build() (or equivalent) through a complete
two-sprint pipeline using mock claude, then asserts the expected artifacts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from tests.helpers.test_helper import HarnessTestCase, FIXTURE_DIR


class PipelineIntegrationTest(HarnessTestCase):
    """Full 2-sprint pipeline using mock claude."""

    def _put_mock_on_path(self):
        helpers_dir = str(_PROJECT / "tests" / "helpers")
        os.environ["PATH"] = helpers_dir + os.pathsep + os.environ.get("PATH", "")

    def setUp(self):
        super().setUp()
        self._put_mock_on_path()
        os.environ["MOCK_CLAUDE_SCENARIO"] = "pass"
        os.environ["HARNESS_ROOT"] = str(_PROJECT)
        # Ensure harness is importable from the temp cwd
        if str(_PROJECT) not in sys.path:
            sys.path.insert(0, str(_PROJECT))
        self.init_test_repo()

    def _run_orchestrator(self, prompt="Build a test project"):
        """Run orchestrate.py as a subprocess in the temp dir."""
        result = subprocess.run(
            [
                sys.executable,
                str(_PROJECT / "harness" / "orchestrate.py"),
                prompt,
                "--project-type", "general",
                "--model", "opus",
                "--max-cost", "200",
            ],
            cwd=self.test_temp_dir,
            env={**os.environ, "HARNESS_ROOT": str(_PROJECT)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        return result

    def test_pipeline_creates_product_spec(self):
        """Full pipeline: product-spec.md is created."""
        result = self._run_orchestrator()
        spec = Path(self.test_temp_dir) / "harness-state" / "product-spec.md"
        self.assertTrue(
            spec.is_file(),
            f"product-spec.md missing. stderr: {result.stderr.decode('utf-8', errors='replace')[-500:]}"
        )

    def test_pipeline_creates_sprint_plan(self):
        """Full pipeline: sprint-plan.json is created."""
        self._run_orchestrator()
        plan = Path(self.test_temp_dir) / "harness-state" / "sprint-plan.json"
        self.assertTrue(plan.is_file())
        data = json.loads(plan.read_text(encoding="utf-8"))
        self.assertIn("sprints", data)

    def test_pipeline_creates_sprint01_eval_report(self):
        """Full pipeline: sprint-01 eval-report.json is created."""
        self._run_orchestrator()
        report = Path(self.test_temp_dir) / "harness-state" / "sprints" / "sprint-01" / "eval-report.json"
        self.assertTrue(report.is_file(), "sprint-01 eval-report.json missing")

    def test_pipeline_creates_sprint02_eval_report(self):
        """Full pipeline: sprint-02 eval-report.json is created (2-sprint fixture)."""
        self._run_orchestrator()
        report = Path(self.test_temp_dir) / "harness-state" / "sprints" / "sprint-02" / "eval-report.json"
        self.assertTrue(report.is_file(), "sprint-02 eval-report.json missing")

    def test_pipeline_handoff_has_completed_sprints(self):
        """Full pipeline: handoff.json completedSprints includes [1, 2]."""
        self._run_orchestrator()
        handoff = Path(self.test_temp_dir) / "harness-state" / "handoff.json"
        self.assertTrue(handoff.is_file())
        data = json.loads(handoff.read_text(encoding="utf-8"))
        completed = data.get("completedSprints", [])
        self.assertIn(1, completed)
        self.assertIn(2, completed)

    def test_pipeline_creates_cost_log(self):
        """Full pipeline: cost-log.json is created."""
        self._run_orchestrator()
        cost_log = Path(self.test_temp_dir) / "harness-state" / "cost-log.json"
        self.assertTrue(cost_log.is_file())

    def test_pipeline_creates_sprint01_pass_tag(self):
        """Full pipeline: git tag harness/sprint-01/pass exists."""
        self._run_orchestrator()
        result = subprocess.run(
            ["git", "tag", "-l", "harness/sprint-01/pass"],
            cwd=self.test_temp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        tags = result.stdout.decode().strip()
        self.assertEqual(tags, "harness/sprint-01/pass",
                         "Expected tag harness/sprint-01/pass not found")

    def test_dry_run_exits_zero(self):
        """--dry-run exits 0 without running any claude calls."""
        result = subprocess.run(
            [sys.executable, str(_PROJECT / "harness" / "orchestrate.py"),
             "Build something", "--dry-run"],
            cwd=self.test_temp_dir,
            env={**os.environ, "HARNESS_ROOT": str(_PROJECT)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
