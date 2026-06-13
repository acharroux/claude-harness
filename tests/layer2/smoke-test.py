#!/usr/bin/env python3
"""Layer 2: Smoke test with real Claude.
Builds a trivial project to verify end-to-end harness functionality.

Guard: Set HARNESS_SMOKE_TEST=1 to run (costs Claude usage ~$10-20)

Test artifacts are written to tests/tmp/smoke-<timestamp>/ (never %TMP%).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
TMP_BASE = PROJECT_DIR / "tests" / "tmp"


def _assert(results: list, desc: str, ok: bool) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"  {status}: {desc}")
    results.append((desc, ok))


def main() -> int:
    if os.environ.get("HARNESS_SMOKE_TEST") != "1":
        print("Set HARNESS_SMOKE_TEST=1 to run the smoke test.")
        print("This costs Claude usage (~$10-20).")
        return 0

    TMP_BASE.mkdir(parents=True, exist_ok=True)
    smoke_dir = TMP_BASE / f"smoke-{int(time.time())}"
    smoke_dir.mkdir()

    print("=== Smoke Test: Build a Hello World CLI ===")
    print(f"Working directory: {smoke_dir}")
    print()

    def _run(*args):
        return subprocess.run(list(args), cwd=str(smoke_dir),
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    _run("git", "init", "-q")
    _run("git", "config", "user.email", "test@test.com")
    _run("git", "config", "user.name", "Smoke Test")
    (smoke_dir / "README.md").write_text("# Smoke Test\n")
    _run("git", "add", "README.md")
    _run("git", "commit", "-q", "-m", "initial")

    shutil.copytree(str(PROJECT_DIR / "harness"), str(smoke_dir / "harness"))
    shutil.copytree(str(PROJECT_DIR / ".claude"), str(smoke_dir / ".claude"),
                    dirs_exist_ok=True)
    for name in (".mcp.json", "CLAUDE.md"):
        src = PROJECT_DIR / name
        if src.exists():
            shutil.copy(str(src), str(smoke_dir / name))

    print("Starting harness (this may take 10-30 minutes)...")
    log_path = smoke_dir / "smoke-output.log"
    start = time.time()

    with open(str(log_path), "w", encoding="utf-8") as log_fh:
        proc = subprocess.run(
            [
                sys.executable,
                str(smoke_dir / "harness" / "orchestrate.py"),
                "Build a hello world CLI tool in Python that prints 'Hello, NAME' "
                "when given a name argument and 'Hello, World' with no arguments",
                "--project-type", "cli-tool",
                "--max-cost", "50",
            ],
            cwd=str(smoke_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1800,
            env={**os.environ, "HARNESS_ROOT": str(smoke_dir)},
        )
        output = proc.stdout.decode(errors="replace")
        log_fh.write(output)
        print(output)

    elapsed = int(time.time() - start)
    print(f"\nElapsed: {elapsed // 60}m {elapsed % 60}s")

    print("\n=== Assertions ===")
    results: list = []
    hs = smoke_dir / "harness-state"

    spec = hs / "product-spec.md"
    _assert(results, "product-spec.md exists and is >100 bytes",
            spec.is_file() and spec.stat().st_size > 100)

    plan = hs / "sprint-plan.json"
    try:
        plan_data = json.loads(plan.read_text(encoding="utf-8"))
        _assert(results, "sprint-plan.json is valid JSON with sprints",
                len(plan_data.get("sprints") or []) > 0)
    except Exception:
        _assert(results, "sprint-plan.json is valid JSON with sprints", False)

    eval_reports = list((hs / "sprints").glob("*/eval-report.json")) if (hs / "sprints").is_dir() else []
    _assert(results, "At least one eval report exists", len(eval_reports) > 0)

    any_pass = any(
        (json.loads(r.read_text(encoding="utf-8")).get("overallResult") or
         json.loads(r.read_text(encoding="utf-8")).get("result") or "").upper() == "PASS"
        for r in eval_reports
        if r.is_file()
    )
    _assert(results, "At least one sprint PASS in eval reports", any_pass)

    tags = subprocess.run(["git", "tag"], cwd=str(smoke_dir),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _assert(results, "Harness git tag exists",
            any(t.startswith("harness/") for t in tags.stdout.decode().splitlines()))

    branches = subprocess.run(["git", "branch"], cwd=str(smoke_dir),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _assert(results, "Harness branch exists",
            any("harness/" in b for b in branches.stdout.decode().splitlines()))

    try:
        handoff = json.loads((hs / "handoff.json").read_text(encoding="utf-8"))
        _assert(results, "handoff.json has completedSprints",
                len(handoff.get("completedSprints") or []) > 0)
    except Exception:
        _assert(results, "handoff.json has completedSprints", False)

    _assert(results, "cost-log.json exists", (hs / "cost-log.json").is_file())

    try:
        progress = (hs / "progress.md").read_text(encoding="utf-8")
        _assert(results, "progress.md contains PASS", "PASS" in progress)
    except Exception:
        _assert(results, "progress.md contains PASS", False)

    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    print(f"Artifacts kept at: {smoke_dir}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
