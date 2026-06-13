"""Python port of harness/lib/generator.sh.

Provides invoke_generator(sprint_num, attempt=1) which invokes the generator
agent and verifies it produced a status.json. Returns:
  0 on success ('ready-for-eval' or any non-blocked status)
  1 on invocation failure
  2 when status.json reports 'blocked' (matches bash `return 2`).

Public API:
    invoke_generator(sprint_num, attempt: int = 1) -> int
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.lib.invoke import invoke_claude
from harness.lib.utils import (
    HARNESS_STATE,
    file_exists,
    json_read,
    log_error,
    log_info,
    log_success,
    log_warn,
    sprint_dir,
    sprint_pad,
)


# Exit codes (mirroring bash semantics)
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2


def _build_prompt(sprint_num: int, attempt: int, eval_report_present: bool,
                  design_spec_present: bool) -> str:
    pad = sprint_pad(sprint_num)
    prompt = (
        f"Implement sprint {sprint_num}. Read the contract at "
        f"harness-state/sprints/sprint-{pad}/contract.json. "
        f"Read harness-state/handoff.json for current project state and "
        f"harness-state/progress.md for history."
    )
    if attempt > 1 and eval_report_present:
        prompt += (
            f" This is retry attempt {attempt}. Read the evaluator's failure "
            f"report at harness-state/sprints/sprint-{pad}/eval-report.json "
            f"and fix every blocking failure."
        )
    if design_spec_present:
        prompt += (
            " IMPORTANT: Read harness-state/design-spec.md and follow the "
            "design system exactly -- colors, typography, spacing, component "
            "patterns. Do not use library defaults."
        )
    prompt += (
        f" When done, write your work log to "
        f"harness-state/sprints/sprint-{pad}/generator-log.md and set "
        f"harness-state/sprints/sprint-{pad}/status.json to "
        f'{{"status": "ready-for-eval", "attempt": {attempt}}}.'
    )
    return prompt


def invoke_generator(sprint_num: Any, attempt: int = 1) -> int:
    """Invoke the generator agent for the given sprint.

    Returns
    -------
    0  -- generator completed and status.json says ready-for-eval (or other
          non-blocked value).
    1  -- claude invocation failed or status.json missing.
    2  -- generator reported status='blocked'.
    """
    sprint_num_int = int(sprint_num)
    attempt = int(attempt)
    pad = sprint_pad(sprint_num_int)
    dir_path = Path(sprint_dir(sprint_num_int))

    log_info(
        f"Generator implementing sprint {pad} (attempt {attempt})..."
    )

    eval_report_path = dir_path / "eval-report.json"
    design_spec_path = Path(HARNESS_STATE) / "design-spec.md"

    prompt = _build_prompt(
        sprint_num=sprint_num_int,
        attempt=attempt,
        eval_report_present=file_exists(str(eval_report_path)),
        design_spec_present=file_exists(str(design_spec_path)),
    )

    rc = invoke_claude("generator", prompt, max_turns=200)
    if rc != 0:
        log_error("Generator invocation failed")
        return EXIT_FAIL

    status_path = dir_path / "status.json"
    if not file_exists(str(status_path)):
        log_error("Generator did not produce status.json")
        return EXIT_FAIL

    status = json_read(str(status_path), ".status")

    if status == "blocked":
        log_error(
            f"Generator is blocked. See {dir_path.as_posix()}/generator-log.md"
        )
        return EXIT_BLOCKED

    if status != "ready-for-eval":
        log_warn(
            f"Generator status is '{status}', expected 'ready-for-eval'"
        )

    log_success(
        f"Generator completed sprint {pad} (attempt {attempt})"
    )
    return EXIT_OK
