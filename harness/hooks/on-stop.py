#!/usr/bin/env python3
"""Hook: Stop.
Checks for premature completion when sprints are still pending.
Exit 2 = block (send feedback to Claude), 0 = allow
"""

import json
import os
import sys
from pathlib import Path


HARNESS_STATE = os.environ.get("HARNESS_STATE", "harness-state")


def _read_status(path: Path) -> str:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("status") or ""
    except (OSError, ValueError, AttributeError):
        return ""


def main() -> int:
    sys.stdin.read()  # consume hook input

    if not (Path(HARNESS_STATE) / "sprint-plan.json").is_file():
        return 0

    for d in sorted((Path(HARNESS_STATE) / "sprints").glob("sprint-*")):
        if not d.is_dir():
            continue
        status_file = d / "status.json"
        if not status_file.is_file():
            continue
        status = _read_status(status_file)
        if status in ("active", "negotiating"):
            print(
                f"{d.name} is still {status}. Complete the current sprint before stopping.",
                file=sys.stderr,
            )
            return 2
        if status == "ready-for-eval":
            print(
                f"{d.name} is ready for evaluation but hasn't been evaluated yet. "
                "Run the evaluator before stopping.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
