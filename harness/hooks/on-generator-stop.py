#!/usr/bin/env python3
"""Hook: SubagentStop for generator.
Verifies the generator produced required output files.
Exit 2 = block (send feedback to Claude), 0 = allow
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

HARNESS_STATE = os.environ.get("HARNESS_STATE", "harness-state")

# Patterns in recent commit messages that indicate harness convention
_HARNESS_PATTERNS = ("harness", "C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9")


def _read_status(path: Path) -> str:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("status") or ""
    except (OSError, ValueError, AttributeError):
        return ""


def _find_active_sprint() -> Optional[Path]:
    """Return the first sprint directory with an active/blocked/pending status."""
    sprints_dir = Path(HARNESS_STATE) / "sprints"
    for pattern in ("sprint-*", "fix-*", "refactor-*"):
        for d in sorted(sprints_dir.glob(pattern)):
            if not d.is_dir():
                continue
            status_file = d / "status.json"
            if status_file.is_file():
                if _read_status(status_file) in ("ready-for-eval", "active", "blocked"):
                    return d
            # Contract negotiation phase: proposal exists but no contract yet
            if (d / "contract-proposal.json").is_file() and not (d / "contract.json").is_file():
                return d
    return None


def main() -> int:
    sys.stdin.read()  # consume hook input

    active_sprint = _find_active_sprint()
    if active_sprint is None:
        return 0

    status_file = active_sprint / "status.json"
    if status_file.is_file():
        status = _read_status(status_file)
        if status not in ("ready-for-eval", "blocked"):
            print(
                f"Generator finished but status is '{status}', not 'ready-for-eval' or 'blocked'. "
                "Did you forget to update status.json?",
                file=sys.stderr,
            )
            return 2
        if status == "ready-for-eval" and not (active_sprint / "generator-log.md").is_file():
            print(
                "Generator marked ready-for-eval but generator-log.md is missing. "
                "Write your work log before completing.",
                file=sys.stderr,
            )
            return 2

    # Warn (non-blocking) if recent commits don't follow harness convention
    try:
        recent = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
        ).stdout.decode(errors="replace")
        if recent and not any(p in recent for p in _HARNESS_PATTERNS):
            print(
                "Warning: recent commits don't follow harness convention "
                "(harness(sprint-NN): desc [C-ID])",
                file=sys.stderr,
            )
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
