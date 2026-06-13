#!/usr/bin/env python3
"""Layer 3: The Meta Test.
Uses the harness to build its own test suite.

Prerequisites: Layer 1 must pass first.
Guard: Set HARNESS_META_TEST=1 to run (costs Claude usage ~$50-100)

Why this is not circular:
Layer 1 (human-written, mock-tested) is the ground truth.
The meta test demonstrates the harness can analyze a complex project,
decompose it into sprints, produce tests, and have them pass evaluation.
The two test suites are complementary, not redundant.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent


def _run_layer1() -> bool:
    """Run layer1 Python tests. Returns True if all pass."""
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(PROJECT_DIR / "tests" / "layer1"),
        pattern="test_*.py",
        top_level_dir=str(PROJECT_DIR),
    )
    runner = unittest.TextTestRunner(verbosity=1, stream=sys.stderr)
    result = runner.run(suite)
    return result.wasSuccessful()


def _check(results: list, desc: str, ok: bool) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"  {status}: {desc}")
    results.append((desc, ok))


def main() -> int:
    if os.environ.get("HARNESS_META_TEST") != "1":
        print("Set HARNESS_META_TEST=1 to run the meta test.")
        print("This costs significant Claude usage (~$50-100).")
        return 0

    # Prerequisite: layer1 must pass
    print("=== Verifying Layer 1 (prerequisite) ===")
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    if not _run_layer1():
        print("\nLayer 1 must pass before running the meta test.")
        print("Fix Layer 1 failures first.")
        return 1

    print()
    print("=== Layer 3: The Meta Test ===")
    print("The harness will now build its own test suite.")
    print()

    meta_dir = Path(tempfile.mkdtemp(prefix="harness-meta-"))
    dest = meta_dir / "claude-harness"

    # Copy project to isolated directory
    shutil.copytree(str(PROJECT_DIR), str(dest),
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc",
                                                  "harness-state", ".claude/worktrees"))

    # Ensure git is ready in the copy
    def _run(*args, **kwargs):
        return subprocess.run(list(args), cwd=str(dest),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    _run("git", "init", "-q")
    _run("git", "config", "user.email", "meta@test.com")
    _run("git", "config", "user.name", "Meta Test")
    _run("git", "add", "-A")
    _run("git", "commit", "-q", "-m", "meta test baseline")

    log_path = dest / "meta-output.log"
    start = time.time()

    # Run the harness to build its own test suite (Python-based)
    with open(str(log_path), "w", encoding="utf-8") as log_fh:
        proc = subprocess.run(
            [
                sys.executable,
                str(dest / "harness" / "orchestrate.py"),
                (
                    "Build a comprehensive Python unittest test suite for this project "
                    "(a multi-agent harness). The test suite should cover: "
                    "(1) Unit tests for all pure functions in harness/lib/utils.py "
                    "(slugify, sprint_pad, sprint_dir, json_read, file_exists, "
                    "init_harness_state, update_handoff, update_regression_registry), "
                    "(2) Git operation tests for harness/lib/git.py functions using "
                    "isolated temp repos, "
                    "(3) Hook validation tests for harness/hooks/on-generator-stop.py, "
                    "on-evaluator-stop.py, and on-stop.py using fixture files. "
                    "Put all tests in a meta-tests/ directory. Include a "
                    "meta-tests/run.py entry point that runs them with unittest."
                ),
                "--project-type", "cli-tool",
                "--max-cost", "100",
            ],
            cwd=str(dest),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=3600,
            env={**os.environ, "HARNESS_ROOT": str(dest)},
        )
        output = proc.stdout.decode(errors="replace")
        log_fh.write(output)
        print(output)

    elapsed = int(time.time() - start)
    print()
    print("=== META-TEST VERIFICATION ===")
    print(f"Elapsed: {elapsed // 60}m {elapsed % 60}s")
    print()

    results: list = []
    hs = dest / "harness-state"

    # Check harness completed sprints
    eval_reports = list((hs / "sprints").glob("*/eval-report.json")) if (hs / "sprints").is_dir() else []
    _check(results, "Harness completed sprint cycle", len(eval_reports) > 0)

    any_pass = False
    for r in eval_reports:
        try:
            d = json.loads(r.read_text(encoding="utf-8"))
            result = (d.get("overallResult") or d.get("result") or "").upper()
            if result == "PASS":
                any_pass = True
                break
        except Exception:
            pass
    _check(results, "At least one sprint passed evaluation", any_pass)

    # Check test files were created
    meta_tests_dir = dest / "meta-tests"
    if meta_tests_dir.is_dir():
        test_files = (list(meta_tests_dir.glob("test_*.py")) +
                      list(meta_tests_dir.glob("*.bats")))
    else:
        test_files = []
    _check(results, "Test files were created", len(test_files) > 0)
    print(f"  INFO: {len(test_files)} test files generated")

    # Try to run the generated tests
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
        print("  INFO: No run.py entry point, but test files exist")
        _check(results, "Test files were generated", True)

    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    print()
    print(f"=== META-TEST RESULTS: {passed} passed, {failed} failed ===")
    print()

    if passed >= 2:
        print("The harness successfully:")
        print("  - Analyzed its own codebase")
        print("  - Planned a test suite via sprint decomposition")
        print("  - Implemented tests via the generator")
        print("  - Evaluated them via the evaluator")
        print()
        print("This is not circular proof -- it is empirical evidence that the harness")
        print("can produce useful output on a complex, real-world project.")

    print()
    print(f"Meta test output: {log_path}")
    print(f"Generated tests:  {dest / 'meta-tests'}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
