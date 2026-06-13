#!/usr/bin/env python3
"""CLI test runner for the Python harness test suite.

Usage:
    python tests/run-all.py [layer1|layer2|layer3|all]

layer1 runs Python unittest discovery under tests/layer1/.
layer2 / layer3 delegate to the existing shell scripts where bash is available;
on Windows-without-bash they print an informative skip message and return 0.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

VALID_LAYERS = ("layer1", "layer2", "layer3", "all")


def _print_usage() -> None:
    sys.stderr.write(
        "Usage: python tests/run-all.py [layer1|layer2|layer3|all]\n"
    )


def run_layer1() -> int:
    """Discover and run unittest tests under tests/layer1/."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(TESTS_DIR / "layer1"),
        pattern="test_*.py",
        top_level_dir=str(REPO_ROOT),
    )
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stderr)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def _delegate_to_bash(script_name: str) -> int:
    """Delegate layer2/layer3 to the existing bash runner if available."""
    bash = shutil.which("bash")
    script = TESTS_DIR / script_name
    if bash is None or not script.is_file():
        sys.stderr.write(
            f"[harness] {script_name} not run: bash unavailable on this host.\n"
            f"[harness] Skipping (Sprint 5 will fully wire this layer).\n"
        )
        return 0
    proc = subprocess.run(
        [bash, str(script)],
        cwd=str(REPO_ROOT),
    )
    return proc.returncode


def run_layer2() -> int:
    return _delegate_to_bash("run-all.sh")


def run_layer3() -> int:
    return _delegate_to_bash("run-all.sh")


def run_all() -> int:
    rc = run_layer1()
    if rc != 0:
        return rc
    # layer2 / layer3 are wired in Sprint 5; surface a skip but don't fail
    rc2 = run_layer2()
    if rc2 != 0:
        return rc2
    return 0


def main(argv: list) -> int:
    if len(argv) < 2:
        _print_usage()
        return 2
    layer = argv[1].strip().lower()
    if layer not in VALID_LAYERS:
        sys.stderr.write(f"[harness] Unknown layer: {layer!r}\n")
        _print_usage()
        return 2

    if layer == "layer1":
        return run_layer1()
    if layer == "layer2":
        return run_layer2()
    if layer == "layer3":
        return run_layer3()
    return run_all()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
