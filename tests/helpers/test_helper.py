"""Shared test helpers for the Python harness test suite.

Mirrors the responsibilities of tests/helpers/test-helper.bash:
  - HarnessTestCase base class with isolated tempdir setUp / tearDown
  - install_fixture(name, dest)
  - init_test_repo()
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# tests/helpers/test_helper.py -> repo root is two levels up
_HELPER_DIR = Path(__file__).resolve().parent
PROJECT_DIR = _HELPER_DIR.parent.parent
FIXTURE_DIR = _HELPER_DIR / "fixtures"


class HarnessTestCase(unittest.TestCase):
    """Base class providing an isolated working dir per test."""

    HARNESS_STATE = "harness-state"

    def setUp(self) -> None:
        # Make harness sources importable
        if str(PROJECT_DIR) not in sys.path:
            sys.path.insert(0, str(PROJECT_DIR))

        self._original_cwd = os.getcwd()
        self.test_temp_dir = tempfile.mkdtemp(prefix="harness-test-")
        os.chdir(self.test_temp_dir)

        # Mirror bash test-helper exports
        self.harness_state = self.HARNESS_STATE
        os.environ["HARNESS_STATE"] = self.harness_state

        self.fixture_dir = str(FIXTURE_DIR)
        os.environ["MOCK_CLAUDE_FIXTURE_DIR"] = self.fixture_dir
        os.environ.setdefault("MOCK_CLAUDE_SCENARIO", "pass")

        self.mock_claude_log = os.path.join(self.test_temp_dir, "mock-claude.log")
        self.mock_claude_state_dir = os.path.join(self.test_temp_dir, "mock-state")
        os.environ["MOCK_CLAUDE_LOG"] = self.mock_claude_log
        os.environ["MOCK_CLAUDE_STATE_DIR"] = self.mock_claude_state_dir
        os.makedirs(self.mock_claude_state_dir, exist_ok=True)

        # Pre-create harness-state subdirs (mirrors bash setup)
        os.makedirs(os.path.join(self.harness_state, "sprints"), exist_ok=True)
        os.makedirs(os.path.join(self.harness_state, "regression"), exist_ok=True)

    def tearDown(self) -> None:
        try:
            os.chdir(self._original_cwd)
        except OSError:
            pass
        try:
            shutil.rmtree(self.test_temp_dir, ignore_errors=True)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Helpers (bash parity)
    # ------------------------------------------------------------------

    def install_fixture(self, fixture_name: str, dest: str) -> None:
        """Copy tests/helpers/fixtures/<fixture_name> to dest (creating parents)."""
        src = FIXTURE_DIR / fixture_name
        dest_path = Path(dest)
        if not dest_path.is_absolute():
            dest_path = Path(os.getcwd()) / dest_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(src), str(dest_path))

    def _git(self, args: list) -> None:
        """Run a git command in the test temp dir, raising on failure."""
        subprocess.run(
            args,
            cwd=self.test_temp_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def init_test_repo(self) -> None:
        """Initialize a git repo in the temp dir with an initial commit."""
        # `git init -b main` requires git ≥2.28; fall back to rename for older versions
        result = subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=self.test_temp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            self._git(["git", "init"])
            try:
                self._git(["git", "checkout", "-b", "main"])
            except subprocess.CalledProcessError:
                pass

        self._git(["git", "config", "user.email", "test@test.com"])
        self._git(["git", "config", "user.name", "Test"])

        (Path(self.test_temp_dir) / "README.md").write_text("initial\n", encoding="utf-8")
        os.makedirs(os.path.join(self.test_temp_dir, self.harness_state, "sprints"), exist_ok=True)
        os.makedirs(os.path.join(self.test_temp_dir, self.harness_state, "regression"), exist_ok=True)

        self._git(["git", "add", "README.md", self.harness_state])
        self._git(["git", "commit", "-q", "-m", "initial commit"])
