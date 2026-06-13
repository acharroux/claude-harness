#!/usr/bin/env python3
"""CLI test runner for the Python harness test suite.

Usage:
    python tests/run-all.py [layer1|layer2|layer3|all]

layer1  — unit + integration tests with mocked Claude (fast, free)
layer2  — smoke test with real Claude (~$10-20, set HARNESS_SMOKE_TEST=1)
layer3  — meta test, harness builds its own suite (~$50-100, set HARNESS_META_TEST=1)
all     — layer1, then layer2, then layer3
"""

from __future__ import annotations

import importlib.util
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


def _run_script(script_path: Path) -> int:
    """Load and run a layer script's main() function in-process."""
    spec = importlib.util.spec_from_file_location("_layer_script", str(script_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main()


def run_layer2() -> int:
    return _run_script(TESTS_DIR / "layer2" / "smoke-test.py")


def run_layer3() -> int:
    return _run_script(TESTS_DIR / "layer3" / "meta-test.py")


def run_all() -> int:
    rc = run_layer1()
    if rc != 0:
        return rc
    rc = run_layer2()
    if rc != 0:
        return rc
    return run_layer3()


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
