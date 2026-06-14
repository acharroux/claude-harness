#!/usr/bin/env python3
"""Mock claude CLI for testing -- Python port of tests/helpers/claude.

Shadows the real `claude` binary when tests/helpers is on PATH (via the .cmd
shim on Windows or by being invoked directly via python).

Behavior mirrors the bash mock byte-for-byte where possible:
  - Reads MOCK_CLAUDE_FIXTURE_DIR (required), MOCK_CLAUDE_SCENARIO (default 'pass'),
    MOCK_CLAUDE_LOG (default os.devnull), MOCK_CLAUDE_STATE_DIR (default temp).
  - Increments call counters in STATE_DIR.
  - Routes by --agent value: planner copies fixtures into harness-state/,
    generator/evaluator copy fixtures into harness-state/sprints/sprint-NN/.
  - Always emits a usage_json line on stdout and exits 0.

Usage:
  python tests/helpers/mock_claude.py --agent NAME -p "PROMPT" [other flags ignored]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_count(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def _write_count(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{count}\n", encoding="utf-8")


def _append_log(log_path: str, line: str) -> None:
    """Append a line to log_path, tolerating os.devnull and missing dirs."""
    if Path(log_path).resolve() == Path(os.devnull).resolve():
        return
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="") as fh:
            fh.write(line + "\n")
    except OSError:
        # Mirror bash tolerance -- never crash on log failures.
        pass


def _parse_args(argv: list[str]) -> tuple[str, str]:
    """Extract --agent and -p values from argv, ignoring everything else."""
    agent = ""
    prompt = ""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--agent" and i + 1 < len(argv):
            agent = argv[i + 1]
            i += 2
        elif a == "-p" and i + 1 < len(argv):
            prompt = argv[i + 1]
            i += 2
        else:
            i += 1
    return agent, prompt


def _default_state_dir() -> str:
    """Return a platform-appropriate default state directory."""
    return os.path.join(tempfile.gettempdir(), "mock-claude-state")


def _extract_sprint_dir(prompt: str):
    """Return harness-state/sprints/sprint-NN if prompt mentions sprint-N or fix-N."""
    m = re.search(r"sprint-(\d+)", prompt)
    if m:
        num = int(m.group(1))
        return f"harness-state/sprints/sprint-{num:02d}"
    m = re.search(r"(fix-\d+)", prompt)
    if m:
        return f"harness-state/sprints/{m.group(1)}"
    return ""


def _copy_fixture(fixture_dir: str, name: str, dest: str) -> None:
    src = Path(fixture_dir) / name
    dst = Path(dest)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(src), str(dst))


def _usage_json() -> None:
    sys.stdout.write(
        '{"session_id":"mock-session","usage":{"input_tokens":1000,"output_tokens":500}}\n'
    )
    try:
        sys.stdout.flush()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

# Pre-compile case-insensitive grep patterns matching the bash mock.
_RE_PROPOSE_CONTRACT = re.compile(r"Propose.*contract|contract.*propos", re.IGNORECASE)
_RE_REVIEW_CONTRACT = re.compile(
    r"review.*contract|contract.*review|Review.*proposal", re.IGNORECASE
)
_RE_EVALUATE_SPRINT = re.compile(r"Evaluate sprint|Test sprint", re.IGNORECASE)
_RE_REGRESSION = re.compile(r"regression", re.IGNORECASE)


def _route(agent: str, prompt: str, scenario: str, sprint_dir: str,
           fixture_dir: str, state_dir: str) -> None:
    if agent == "planner":
        _copy_fixture(fixture_dir, "product-spec-minimal.md",
                      "harness-state/product-spec.md")
        _copy_fixture(fixture_dir, "sprint-plan-2sprint.json",
                      "harness-state/sprint-plan.json")
        return

    if agent == "generator":
        if _RE_PROPOSE_CONTRACT.search(prompt or ""):
            if sprint_dir:
                _copy_fixture(fixture_dir, "contract-proposal-valid.json",
                              f"{sprint_dir}/contract-proposal.json")
        else:
            if sprint_dir:
                if scenario == "fail-generator-blocked":
                    _copy_fixture(fixture_dir, "status-blocked.json",
                                  f"{sprint_dir}/status.json")
                else:
                    _copy_fixture(fixture_dir, "status-ready-for-eval.json",
                                  f"{sprint_dir}/status.json")
                    _copy_fixture(fixture_dir, "generator-log-sample.md",
                                  f"{sprint_dir}/generator-log.md")
        return

    if agent == "evaluator":
        if _RE_REVIEW_CONTRACT.search(prompt or ""):
            if sprint_dir:
                if scenario == "revise-then-accept":
                    eval_count_path = Path(state_dir) / "evaluator-count"
                    eval_count = _read_count(eval_count_path) or 1
                    if eval_count <= 1:
                        _copy_fixture(fixture_dir, "contract-review-revise.json",
                                      f"{sprint_dir}/contract-review.json")
                    else:
                        _copy_fixture(fixture_dir, "contract-review-accepted.json",
                                      f"{sprint_dir}/contract-review.json")
                else:
                    _copy_fixture(fixture_dir, "contract-review-accepted.json",
                                  f"{sprint_dir}/contract-review.json")
        elif _RE_EVALUATE_SPRINT.search(prompt or ""):
            if sprint_dir:
                if scenario == "fail-eval":
                    _copy_fixture(fixture_dir, "eval-report-fail-blocking.json",
                                  f"{sprint_dir}/eval-report.json")
                    Path(f"{sprint_dir}/status.json").write_text(
                        '{"status":"fail","attempt":1,"timestamp":"2026-01-01T00:00:00Z"}\n',
                        encoding="utf-8",
                    )
                else:
                    _copy_fixture(fixture_dir, "eval-report-pass.json",
                                  f"{sprint_dir}/eval-report.json")
                    Path(f"{sprint_dir}/status.json").write_text(
                        '{"status":"pass","attempt":1,"timestamp":"2026-01-01T00:00:00Z"}\n',
                        encoding="utf-8",
                    )
        elif _RE_REGRESSION.search(prompt or ""):
            if sprint_dir:
                if scenario == "fail-eval":
                    _copy_fixture(fixture_dir, "eval-report-fail-blocking.json",
                                  f"{sprint_dir}/eval-report.json")
                    Path(f"{sprint_dir}/status.json").write_text(
                        '{"status":"fail","attempt":1,"timestamp":"2026-01-01T00:00:00Z"}\n',
                        encoding="utf-8",
                    )
                else:
                    _copy_fixture(fixture_dir, "eval-report-pass.json",
                                  f"{sprint_dir}/eval-report.json")
                    Path(f"{sprint_dir}/status.json").write_text(
                        '{"status":"pass","attempt":1,"timestamp":"2026-01-01T00:00:00Z"}\n',
                        encoding="utf-8",
                    )
        return

    # Unknown agent: matches bash mock fallthrough
    sys.stderr.write(f"mock-claude: unknown agent '{agent}'\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv) -> int:
    fixture_dir = os.environ.get("MOCK_CLAUDE_FIXTURE_DIR")
    if not fixture_dir:
        sys.stderr.write("MOCK_CLAUDE_FIXTURE_DIR must be set\n")
        return 1

    scenario = os.environ.get("MOCK_CLAUDE_SCENARIO", "pass")
    log_path = os.environ.get("MOCK_CLAUDE_LOG", os.devnull)
    state_dir = os.environ.get("MOCK_CLAUDE_STATE_DIR", _default_state_dir())

    Path(state_dir).mkdir(parents=True, exist_ok=True)

    agent, prompt = _parse_args(list(argv[1:]))

    # Increment global call counter
    call_count_path = Path(state_dir) / "call-count"
    count = _read_count(call_count_path) + 1
    _write_count(call_count_path, count)

    # Per-agent counter
    agent_count_path = Path(state_dir) / f"{agent or 'unknown'}-count"
    agent_count = _read_count(agent_count_path) + 1
    _write_count(agent_count_path, agent_count)

    # Log invocation -- match bash format byte-for-byte
    prompt_head = (prompt or "")[:100]
    _append_log(log_path,
                f"call={count} agent={agent} scenario={scenario} prompt={prompt_head}")

    # Sprint dir extraction (mkdir -p like bash does)
    sprint_dir = _extract_sprint_dir(prompt or "")
    if sprint_dir:
        Path(sprint_dir).mkdir(parents=True, exist_ok=True)

    # Route
    try:
        _route(agent, prompt, scenario, sprint_dir, fixture_dir, state_dir)
    except Exception as exc:  # pragma: no cover -- defensive
        sys.stderr.write(f"mock-claude: routing error: {exc}\n")

    _usage_json()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
