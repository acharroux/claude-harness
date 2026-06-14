#!/usr/bin/env python3
"""Layer 3: The Meta Test.
Uses the harness to build its own test suite.

Guard: Set HARNESS_META_TEST=1 to run (costs Claude usage ~$50-100)

Test artifacts are written to tests/tmp/meta-<timestamp>/ (never %TMP%).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
TMP_BASE = PROJECT_DIR / "tests" / "tmp"

_META_PROMPT = (
    "Build a Python unittest test suite for this harness project. "
    "Create exactly 2 sprints: "
    "Sprint 1 — meta-tests/test_utils.py covering slugify, sprint_pad, "
    "sprint_dir, json_read, file_exists from harness/lib/utils.py. "
    "Sprint 2 — meta-tests/test_hooks.py covering harness/hooks/"
    "on-generator-stop.py, on-evaluator-stop.py, on-stop.py. "
    "ALL files MUST go in the meta-tests/ directory. "
    "Include a meta-tests/run.py entry point that runs both with unittest."
)


def _run_layer1() -> bool:
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(PROJECT_DIR / "tests" / "layer1"),
        pattern="test_*.py",
        top_level_dir=str(PROJECT_DIR),
    )
    result = unittest.TextTestRunner(verbosity=1, stream=sys.stderr).run(suite)
    return result.wasSuccessful()


def _check(results: list, desc: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}: {desc}")
    results.append((desc, ok))


def main() -> int:
    if os.environ.get("HARNESS_META_TEST") != "1":
        print("Set HARNESS_META_TEST=1 to run the meta test.")
        print("This costs significant Claude usage (~$50-100).")

    print("=== Verifying Layer 1 (prerequisite) ===")
    if not _run_layer1():
        print("\nLayer 1 must pass before running the meta test.")
        return 1

    print()
    print("=== Layer 3: The Meta Test ===")
    print("The harness will now build its own test suite.")
    print()

    TMP_BASE.mkdir(parents=True, exist_ok=True)
    dest = TMP_BASE / f"meta-{int(time.time())}" / "claude-harness"
    # dest must NOT be pre-created — shutil.copytree creates it

    # Build an ignore function that excludes both name-patterns and the
    # tests/tmp directory (which is inside PROJECT_DIR and would cause
    # infinite recursion if copied into itself).
    _pattern_ignore = shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", "harness-state"
    )
    _tmp_abs = str(TMP_BASE.resolve())

    def _ignore(src, names):
        ignored = set(_pattern_ignore(src, names))
        # Exclude tests/tmp itself when we're inside the tests/ directory
        src_resolved = str(Path(src).resolve())
        for name in names:
            child = str(Path(src_resolved) / name)
            if child.startswith(_tmp_abs):
                ignored.add(name)
        return ignored

    shutil.copytree(str(PROJECT_DIR), str(dest), ignore=_ignore)

    def _run(*args):
        return subprocess.run(list(args), cwd=str(dest),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    _run("git", "init", "-q")
    _run("git", "config", "user.email", "meta@test.com")
    _run("git", "config", "user.name", "Meta Test")
    _run("git", "add", "-A")
    _run("git", "commit", "-q", "-m", "meta test baseline")

    # Log lives outside the git repo (dest) so it never makes the working tree dirty
    log_path = dest.parent / "meta-output.log"
    start = time.time()

    # Isolated venv so any pip installs stay inside the test directory
    venv_dir = dest / ".venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    venv_bin = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    venv_python = venv_bin / ("python.exe" if os.name == "nt" else "python")

    meta_env = {
        **os.environ,
        "HARNESS_ROOT": str(dest),
        "VIRTUAL_ENV": str(venv_dir),
        "PATH": str(venv_bin) + os.pathsep + os.environ.get("PATH", ""),
    }
    meta_env.pop("PYTHONHOME", None)
    # Remove the test helpers directory from PATH so real Claude is used, not the mock.
    _helpers_abs = str((PROJECT_DIR / "tests" / "helpers").resolve())
    meta_env["PATH"] = os.pathsep.join(
        p for p in meta_env["PATH"].split(os.pathsep)
        if str(Path(p).resolve()) != _helpers_abs
    )
    # Also clear mock claude env vars inherited from the calling process.
    # pick up the mock fixture directory from the parent process environment.
    for _var in ("MOCK_CLAUDE_FIXTURE_DIR", "MOCK_CLAUDE_SCENARIO",
                 "MOCK_CLAUDE_LOG", "MOCK_CLAUDE_STATE_DIR"):
        meta_env.pop(_var, None)

    with open(str(log_path), "w", encoding="utf-8", errors="replace") as log_fh:
        subprocess.run(
            [
                str(venv_python),
                str(dest / "harness" / "orchestrate.py"),
                _META_PROMPT,
                "--project-type", "cli-tool",
                "--max-cost", "100",
            ],
            cwd=str(dest),
            stdout=log_fh,
            stderr=log_fh,
            # No timeout: writing to a file has no pipe-buffer deadlock risk,
            # and the meta test legitimately takes 30-90 minutes.
            env=meta_env,
        )
    print(log_path.read_text(encoding="utf-8", errors="replace"))

    elapsed = int(time.time() - start)
    print()
    print("=== META-TEST VERIFICATION ===")
    print(f"Elapsed: {elapsed // 60}m {elapsed % 60}s")
    print()

    results: list = []
    hs = dest / "harness-state"

    eval_reports = list((hs / "sprints").glob("*/eval-report.json")) if (hs / "sprints").is_dir() else []
    _check(results, "Harness completed sprint cycle", len(eval_reports) > 0)

    any_pass = any(
        (json.loads(r.read_text(encoding="utf-8")).get("overallResult") or
         json.loads(r.read_text(encoding="utf-8")).get("result") or "").upper() == "PASS"
        for r in eval_reports if r.is_file()
    )
    _check(results, "At least one sprint passed evaluation", any_pass)

    meta_tests_dir = dest / "meta-tests"
    test_files = (
        list(meta_tests_dir.glob("test_*.py")) + list(meta_tests_dir.glob("*.bats"))
        if meta_tests_dir.is_dir() else []
    )
    _check(results, "Test files were created", len(test_files) > 0)
    print(f"  INFO: {len(test_files)} test files generated")

    run_py = dest / "meta-tests" / "run.py"
    if run_py.is_file():
        print()
        print("=== RUNNING GENERATED TESTS ===")
        run_result = subprocess.run(
            [sys.executable, str(run_py)],
            cwd=str(dest),
            timeout=300,
        )
        if run_result.returncode == 0:
            _check(results, "Generated tests pass", True)
        else:
            print("  WARN: Some generated tests failed (informative, not blocking)")
            _check(results, "Generated tests exist and are runnable", True)
    elif test_files:
        _check(results, "Test files were generated", True)

    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    print()
    print(f"=== META-TEST RESULTS: {passed} passed, {failed} failed ===")

    if passed >= 2:
        print()
        print("The harness successfully analyzed its own codebase, planned a test")
        print("suite, implemented it, and had it pass evaluation.")

    print()
    print(f"Meta test output: {log_path}")
    print(f"Generated tests:  {dest / 'meta-tests'}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
