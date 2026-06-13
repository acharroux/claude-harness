#!/usr/bin/env python3
"""CLI test runner for the Python harness test suite.

Usage:
    python tests/run-all.py [layer1|layer2|layer3|all]

layer1 runs Python unittest discovery under tests/layer1/.
layer2 / layer3 are bash-based and must be run directly:
    bash tests/run-all.sh layer2   (set HARNESS_SMOKE_TEST=1 first)
    bash tests/run-all.sh layer3   (set HARNESS_META_TEST=1 first)
"""

from __future__ import annotations

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


def run_layer2() -> int:
    sys.stderr.write(
        "[harness] layer2 is a bash smoke test — run it directly:\n"
        "  bash tests/run-all.sh layer2   (requires HARNESS_SMOKE_TEST=1)\n"
    )
    return 0


def run_layer3() -> int:
    sys.stderr.write(
        "[harness] layer3 is a bash meta test — run it directly:\n"
        "  bash tests/run-all.sh layer3   (requires HARNESS_META_TEST=1)\n"
    )
    return 0


def run_all() -> int:
    rc = run_layer1()
    if rc != 0:
        return rc
    run_layer2()
    run_layer3()
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
