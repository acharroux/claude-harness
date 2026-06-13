"""Python port of tests/layer1/test-hooks.bats.

Drives existing bash hook scripts (harness/hooks/*.sh) via subprocess.
Skips entirely if bash is not available on this system.
Does NOT modify any hook scripts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent.parent
HOOKS_DIR = _PROJECT / "harness" / "hooks"

_BASH = shutil.which("bash")
_SKIP_MSG = "bash not available on this system"


def _run_hook(hook_name: str, cwd: str, env: dict) -> int:
    """Run a hook script and return its exit code."""
    hook_path = HOOKS_DIR / hook_name
    result = subprocess.run(
        [_BASH, str(hook_path)],
        input=b"",
        cwd=cwd,
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode


@unittest.skipIf(_BASH is None, _SKIP_MSG)
class OnGeneratorStopTests(unittest.TestCase):
    """Port of on-generator-stop.sh bats tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-hooks-test-")
        self.hs = os.path.join(self.tmp, "harness-state")
        os.makedirs(os.path.join(self.hs, "sprints"), exist_ok=True)
        os.makedirs(os.path.join(self.hs, "regression"), exist_ok=True)
        self.env = {"HARNESS_STATE": "harness-state"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sprint_dir(self):
        d = os.path.join(self.hs, "sprints", "sprint-01")
        os.makedirs(d, exist_ok=True)
        return d

    def _write(self, path, content):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_allows_ready_for_eval_with_log(self):
        """allows when status is ready-for-eval with log."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "status.json"), '{"status":"ready-for-eval","attempt":1}')
        self._write(os.path.join(d, "generator-log.md"), "# Log\n")
        self.assertEqual(_run_hook("on-generator-stop.sh", self.tmp, self.env), 0)

    def test_blocks_ready_for_eval_without_log(self):
        """blocks when ready-for-eval but log missing."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "status.json"), '{"status":"ready-for-eval","attempt":1}')
        self.assertEqual(_run_hook("on-generator-stop.sh", self.tmp, self.env), 2)

    def test_allows_blocked_status(self):
        """allows when status is blocked."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "status.json"), '{"status":"blocked","attempt":1}')
        self.assertEqual(_run_hook("on-generator-stop.sh", self.tmp, self.env), 0)

    def test_allows_no_active_sprint(self):
        """allows when no active sprint."""
        self.assertEqual(_run_hook("on-generator-stop.sh", self.tmp, self.env), 0)

    def test_blocks_active_status(self):
        """blocks when status is active (not ready-for-eval)."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "status.json"), '{"status":"active","attempt":1}')
        self.assertEqual(_run_hook("on-generator-stop.sh", self.tmp, self.env), 2)


@unittest.skipIf(_BASH is None, _SKIP_MSG)
class OnEvaluatorStopTests(unittest.TestCase):
    """Port of on-evaluator-stop.sh bats tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-hooks-test-")
        self.hs = os.path.join(self.tmp, "harness-state")
        os.makedirs(os.path.join(self.hs, "sprints"), exist_ok=True)
        self.env = {"HARNESS_STATE": "harness-state"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sprint_dir(self):
        d = os.path.join(self.hs, "sprints", "sprint-01")
        os.makedirs(d, exist_ok=True)
        return d

    def _write(self, path, content):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_allows_valid_eval_report(self):
        """allows valid eval report."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "status.json"), '{"status":"ready-for-eval","attempt":1}')
        self._write(os.path.join(d, "contract.json"),
                    '{"criteria":[{"id":"C1-01"},{"id":"C1-02"},{"id":"C1-03"}]}')
        self._write(os.path.join(d, "eval-report.json"),
                    '{"overallResult":"PASS","criteriaResults":[{"id":"C1-01","result":"PASS"},{"id":"C1-02","result":"PASS"},{"id":"C1-03","result":"PASS"}]}')
        self.assertEqual(_run_hook("on-evaluator-stop.sh", self.tmp, self.env), 0)

    def test_blocks_when_eval_report_missing(self):
        """blocks when eval report missing."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "status.json"), '{"status":"ready-for-eval","attempt":1}')
        self.assertEqual(_run_hook("on-evaluator-stop.sh", self.tmp, self.env), 2)

    def test_blocks_when_overallResult_missing(self):
        """blocks when overallResult missing."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "status.json"), '{"status":"ready-for-eval","attempt":1}')
        self._write(os.path.join(d, "eval-report.json"), '{"criteriaResults":[]}')
        self.assertEqual(_run_hook("on-evaluator-stop.sh", self.tmp, self.env), 2)

    def test_blocks_when_criteriaResults_missing(self):
        """blocks when criteriaResults missing."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "status.json"), '{"status":"ready-for-eval","attempt":1}')
        self._write(os.path.join(d, "eval-report.json"), '{"overallResult":"PASS"}')
        self.assertEqual(_run_hook("on-evaluator-stop.sh", self.tmp, self.env), 2)

    def test_blocks_when_criteria_count_mismatch(self):
        """blocks when criteria count mismatch."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "status.json"), '{"status":"ready-for-eval","attempt":1}')
        self._write(os.path.join(d, "contract.json"),
                    '{"criteria":[{"id":"C1-01"},{"id":"C1-02"},{"id":"C1-03"}]}')
        self._write(os.path.join(d, "eval-report.json"),
                    '{"overallResult":"PASS","criteriaResults":[{"id":"C1-01","result":"PASS"}]}')
        self.assertEqual(_run_hook("on-evaluator-stop.sh", self.tmp, self.env), 2)

    def test_allows_valid_contract_review(self):
        """allows valid contract review."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "contract-proposal.json"), '{"criteria":[]}')
        self._write(os.path.join(d, "contract-review.json"), '{"decision":"accepted","feedback":"OK"}')
        self.assertEqual(_run_hook("on-evaluator-stop.sh", self.tmp, self.env), 0)

    def test_blocks_contract_review_without_decision(self):
        """blocks contract review without decision."""
        d = self._sprint_dir()
        self._write(os.path.join(d, "contract-proposal.json"), '{"criteria":[]}')
        self._write(os.path.join(d, "contract-review.json"), '{"feedback":"needs work"}')
        self.assertEqual(_run_hook("on-evaluator-stop.sh", self.tmp, self.env), 2)


@unittest.skipIf(_BASH is None, _SKIP_MSG)
class OnStopTests(unittest.TestCase):
    """Port of on-stop.sh bats tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-hooks-test-")
        self.hs = os.path.join(self.tmp, "harness-state")
        os.makedirs(os.path.join(self.hs, "sprints"), exist_ok=True)
        self.env = {"HARNESS_STATE": "harness-state"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_allows_no_sprint_plan(self):
        """allows when no sprint plan exists."""
        self.assertEqual(_run_hook("on-stop.sh", self.tmp, self.env), 0)

    def test_allows_no_active_sprints(self):
        """allows when no active sprints."""
        self._write(os.path.join(self.hs, "sprint-plan.json"),
                    '{"sprints":[{"number":1}]}')
        self._write(os.path.join(self.hs, "sprints", "sprint-01", "status.json"),
                    '{"status":"pass","attempt":1}')
        self.assertEqual(_run_hook("on-stop.sh", self.tmp, self.env), 0)

    def test_blocks_when_sprint_is_active(self):
        """blocks when sprint is active."""
        self._write(os.path.join(self.hs, "sprint-plan.json"),
                    '{"sprints":[{"number":1}]}')
        self._write(os.path.join(self.hs, "sprints", "sprint-01", "status.json"),
                    '{"status":"active","attempt":1}')
        self.assertEqual(_run_hook("on-stop.sh", self.tmp, self.env), 2)

    def test_blocks_when_sprint_is_ready_for_eval(self):
        """blocks when sprint is ready-for-eval."""
        self._write(os.path.join(self.hs, "sprint-plan.json"),
                    '{"sprints":[{"number":1}]}')
        self._write(os.path.join(self.hs, "sprints", "sprint-01", "status.json"),
                    '{"status":"ready-for-eval","attempt":1}')
        self.assertEqual(_run_hook("on-stop.sh", self.tmp, self.env), 2)


if __name__ == "__main__":
    unittest.main()
