"""Unit tests for harness/lib/git.py.

Ports tests/layer1/test-git.bats. Each bats `@test` has a corresponding
`test_*` method. Every test runs in an isolated tempdir initialized as a
fresh git repo via HarnessTestCase.init_test_repo().
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

# Make project root importable
_HERE = Path(__file__).resolve().parent
PROJECT_ROOT = _HERE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.helpers.test_helper import HarnessTestCase  # noqa: E402

from harness.lib import git as git_mod  # noqa: E402


def _run_git(*args, cwd=None, check=False):
    """Helper: run a git command capturing stdout."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _current_branch(cwd=None) -> str:
    cp = _run_git("branch", "--show-current", cwd=cwd)
    return (cp.stdout or "").strip()


def _branch_exists(name: str, cwd=None) -> bool:
    return _run_git("rev-parse", "--verify", name, cwd=cwd).returncode == 0


def _tags(cwd=None) -> str:
    return _run_git("tag", cwd=cwd).stdout or ""


# ---------------------------------------------------------------------------
# create_harness_branch
# ---------------------------------------------------------------------------

class TestCreateHarnessBranch(HarnessTestCase):
    """C3-03, C3-04: harness branch creation + idempotence."""

    def setUp(self):
        super().setUp()
        self.init_test_repo()

    def test_creates_branch(self):
        """create_harness_branch returns 'harness/<slug>' and checks it out."""
        result = git_mod.create_harness_branch("test-project")
        self.assertEqual(result, "harness/test-project")
        self.assertEqual(_current_branch(), "harness/test-project")

    def test_idempotent(self):
        """Calling twice (with a checkout main in between) does not fail."""
        git_mod.create_harness_branch("test-project")
        # Switch back to main, then call again
        _run_git("checkout", "main", check=True)
        # Must not raise
        result = git_mod.create_harness_branch("test-project")
        self.assertEqual(result, "harness/test-project")
        self.assertEqual(_current_branch(), "harness/test-project")


# ---------------------------------------------------------------------------
# create_sprint_branch
# ---------------------------------------------------------------------------

class TestCreateSprintBranch(HarnessTestCase):
    """C3-05, C3-06, C3-16: sprint branch creation, cleanup, padding."""

    def setUp(self):
        super().setUp()
        self.init_test_repo()

    def test_creates_sprint_branch(self):
        """Returns '<harness_branch>-sprint-01' and checks out."""
        git_mod.create_harness_branch("test-project")
        result = git_mod.create_sprint_branch("harness/test-project", 1)
        self.assertEqual(result, "harness/test-project-sprint-01")
        self.assertEqual(_current_branch(), "harness/test-project-sprint-01")

    def test_cleans_up_existing_branch(self):
        """A pre-existing sprint branch with stale work is wiped."""
        git_mod.create_harness_branch("test-project")
        # Create a stale sprint branch with a committed file
        _run_git("checkout", "-b", "harness/test-project-sprint-01", check=True)
        old_path = Path(self.test_temp_dir) / "old.txt"
        old_path.write_text("old work\n", encoding="utf-8")
        _run_git("add", "old.txt", check=True)
        _run_git("commit", "-q", "-m", "old", check=True)
        # Switch back to harness branch
        _run_git("checkout", "harness/test-project", check=True)

        # Recreate the sprint branch -- old work must be gone
        result = git_mod.create_sprint_branch("harness/test-project", 1)
        self.assertEqual(result, "harness/test-project-sprint-01")
        self.assertFalse(old_path.exists(), "old.txt should be wiped")

    def test_sprint_number_zero_padded_two_digits(self):
        """Sprint 9 -> 'sprint-09' (C3-16 padding)."""
        git_mod.create_harness_branch("p")
        result = git_mod.create_sprint_branch("harness/p", 9)
        self.assertEqual(result, "harness/p-sprint-09")


# ---------------------------------------------------------------------------
# merge_sprint
# ---------------------------------------------------------------------------

class TestMergeSprint(HarnessTestCase):
    """C3-07, C3-08, C3-09, C3-16: merge commit, tag, branch deletion."""

    def setUp(self):
        super().setUp()
        self.init_test_repo()

    def _setup_sprint_with_commit(self, sprint_num=1):
        git_mod.create_harness_branch("test-project")
        sprint_branch = git_mod.create_sprint_branch("harness/test-project", sprint_num)
        f = Path(self.test_temp_dir) / "sprint.txt"
        f.write_text("sprint work\n", encoding="utf-8")
        _run_git("add", "sprint.txt", check=True)
        _run_git(
            "commit", "-q", "-m",
            f"harness(sprint-0{sprint_num}): add feature [C1-01]",
            check=True,
        )
        return sprint_branch

    def test_creates_merge_commit(self):
        self._setup_sprint_with_commit(1)
        merge_sha = git_mod.merge_sprint("harness/test-project", 1, 1)

        self.assertEqual(_current_branch(), "harness/test-project")
        log = _run_git("--no-pager", "log", "--oneline").stdout or ""
        self.assertIn("merge", log.lower())
        self.assertTrue(merge_sha)
        # SHA should be 40-char hex
        self.assertEqual(len(merge_sha), 40)
        self.assertTrue(all(c in "0123456789abcdef" for c in merge_sha))
        # And match HEAD
        head = (_run_git("rev-parse", "HEAD").stdout or "").strip()
        self.assertEqual(merge_sha, head)
        # Merge commit message must match canonical form
        msg = (_run_git("log", "-1", "--pretty=%B").stdout or "").strip()
        self.assertEqual(
            msg, "harness(sprint-01): merge (PASS, attempt 1)"
        )

    def test_creates_tag(self):
        self._setup_sprint_with_commit(1)
        git_mod.merge_sprint("harness/test-project", 1, 1)
        self.assertIn("harness/sprint-01/pass", _tags())

    def test_deletes_sprint_branch(self):
        self._setup_sprint_with_commit(1)
        git_mod.merge_sprint("harness/test-project", 1, 1)
        self.assertFalse(_branch_exists("harness/test-project-sprint-01"))

    def test_padding_in_tag_for_single_digit_sprint(self):
        """Sprint 9 yields tag 'harness/sprint-09/pass' (C3-16)."""
        self._setup_sprint_with_commit(9)
        git_mod.merge_sprint("harness/test-project", 9, 1)
        self.assertIn("harness/sprint-09/pass", _tags())


# ---------------------------------------------------------------------------
# fail_sprint_attempt
# ---------------------------------------------------------------------------

class TestFailSprintAttempt(HarnessTestCase):
    """C3-10, C3-11, C3-12: fail tag, branch deletion, dirty-tree handling."""

    def setUp(self):
        super().setUp()
        self.init_test_repo()

    def _setup_failed_sprint(self):
        git_mod.create_harness_branch("test-project")
        git_mod.create_sprint_branch("harness/test-project", 1)
        f = Path(self.test_temp_dir) / "f.txt"
        f.write_text("failed work\n", encoding="utf-8")
        _run_git("add", "f.txt", check=True)
        _run_git("commit", "-q", "-m", "failed attempt", check=True)

    def test_tags_the_attempt(self):
        self._setup_failed_sprint()
        git_mod.fail_sprint_attempt("harness/test-project", 1, 1)
        self.assertIn("harness/sprint-01/attempt-1", _tags())

    def test_deletes_sprint_branch(self):
        self._setup_failed_sprint()
        git_mod.fail_sprint_attempt("harness/test-project", 1, 1)
        self.assertFalse(_branch_exists("harness/test-project-sprint-01"))

    def test_returns_to_harness_branch(self):
        self._setup_failed_sprint()
        git_mod.fail_sprint_attempt("harness/test-project", 1, 1)
        self.assertEqual(_current_branch(), "harness/test-project")

    def test_handles_dirty_working_tree(self):
        """Uncommitted changes are stashed (and dropped) so checkout succeeds.

        C3-12: matches bash `git stash -q; git checkout; git stash drop -q`.
        """
        git_mod.create_harness_branch("test-project")
        git_mod.create_sprint_branch("harness/test-project", 1)
        # Commit a base file
        base = Path(self.test_temp_dir) / "base.txt"
        base.write_text("base\n", encoding="utf-8")
        _run_git("add", "base.txt", check=True)
        _run_git("commit", "-q", "-m", "base", check=True)
        # Now create UNCOMMITTED dirt
        base.write_text("dirty modification\n", encoding="utf-8")
        # Must not raise
        git_mod.fail_sprint_attempt("harness/test-project", 1, 1)
        self.assertEqual(_current_branch(), "harness/test-project")


# ---------------------------------------------------------------------------
# commit_harness_state
# ---------------------------------------------------------------------------

class TestCommitHarnessState(HarnessTestCase):
    """C3-13, C3-14: commits when changes exist, no-op when clean."""

    def setUp(self):
        super().setUp()
        self.init_test_repo()

    def test_commits_changes(self):
        progress = Path(self.test_temp_dir) / self.harness_state / "progress.md"
        progress.write_text("state data\n", encoding="utf-8")

        git_mod.commit_harness_state("harness: test commit")

        log = _run_git("log", "--oneline", "-1").stdout or ""
        self.assertIn("harness: test commit", log)

    def test_noop_when_clean(self):
        """Clean repo -> no exception, no new commit."""
        before = (_run_git("rev-parse", "HEAD").stdout or "").strip()
        # Must not raise
        git_mod.commit_harness_state("harness: nothing to commit")
        after = (_run_git("rev-parse", "HEAD").stdout or "").strip()
        self.assertEqual(before, after, "no new commit should be created")


# ---------------------------------------------------------------------------
# generate_pr_body
# ---------------------------------------------------------------------------

class TestGeneratePrBody(HarnessTestCase):
    """C3-15: PR body contains sprint table and PASS status."""

    def setUp(self):
        super().setUp()
        self.init_test_repo()

    def test_contains_sprint_table(self):
        self.install_fixture(
            "config-general.json",
            f"{self.harness_state}/config.json",
        )
        self.install_fixture(
            "sprint-plan-2sprint.json",
            f"{self.harness_state}/sprint-plan.json",
        )
        os.makedirs(
            os.path.join(self.harness_state, "sprints", "sprint-01"),
            exist_ok=True,
        )
        self.install_fixture(
            "eval-report-pass.json",
            f"{self.harness_state}/sprints/sprint-01/eval-report.json",
        )

        body = git_mod.generate_pr_body()
        self.assertIn("Sprint", body)
        self.assertIn("PASS", body)


# ---------------------------------------------------------------------------
# Graceful degradation (no gh / no origin)
# ---------------------------------------------------------------------------

class TestGracefulDegradation(HarnessTestCase):
    """C3-17: create_pr / create_fix_pr / create_issue safe without remote."""

    def setUp(self):
        super().setUp()
        self.init_test_repo()
        # Confirm no origin remote in our isolated repo
        self.assertFalse(
            _run_git("remote", "get-url", "origin").returncode == 0,
            "test repo should have no origin remote",
        )

    def test_create_pr_no_remote_does_not_raise(self):
        # Must not raise even though gh may exist; because origin is missing.
        try:
            git_mod.create_pr("harness/x", "x", "body")
        except Exception as exc:  # pragma: no cover
            self.fail(f"create_pr raised: {exc!r}")

    def test_create_fix_pr_no_remote_does_not_raise(self):
        try:
            git_mod.create_fix_pr(
                "fix/x", "main", "fix-1", "bug description", ""
            )
        except Exception as exc:  # pragma: no cover
            self.fail(f"create_fix_pr raised: {exc!r}")

    def test_create_issue_no_remote_returns_empty_string(self):
        try:
            result = git_mod.create_issue("title", "body")
        except Exception as exc:  # pragma: no cover
            self.fail(f"create_issue raised: {exc!r}")
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
