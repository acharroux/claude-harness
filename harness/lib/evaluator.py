"""Python port of harness/lib/evaluator.sh.

Provides:
  invoke_evaluator(sprint_num, attempt=1) -> bool   (True=PASS, False=FAIL)
  invoke_regression()                               -> bool   (True=all pass)

Field-name tolerance mirrors evaluator.sh EXACTLY:
  result   : .overallResult | .result | .verdict   (case-insensitive pass/passed)
  pass ct  : .passCount | .pass_count | .score.passedCriteria | .score.passed
  fail ct  : .failCount | .fail_count | .score.failedCriteria | .score.failed
  blocking : .blockingFailures | .blocking_failures | .score.blocking
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from harness.lib.invoke import invoke_claude
from harness.lib.utils import (
    HARNESS_STATE,
    file_exists,
    json_read,
    log_error,
    log_info,
    log_phase,
    log_success,
    log_warn,
    sprint_dir,
    sprint_pad,
)


def _read_json(path: Path) -> Any:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _get_result(data: Any) -> str:
    if not isinstance(data, dict):
        return "unknown"
    for key in ("overallResult", "result", "verdict"):
        v = data.get(key)
        if isinstance(v, str) and v:
            return v.lower()
    return "unknown"


def _get_count(data: Any, *keys: str) -> int:
    if not isinstance(data, dict):
        return 0
    for key in keys:
        if "." in key:
            outer, inner = key.split(".", 1)
            sub = data.get(outer)
            if isinstance(sub, dict):
                v = sub.get(inner)
                if isinstance(v, int):
                    return v
        else:
            v = data.get(key)
            if isinstance(v, int):
                return v
    return 0


def invoke_evaluator(sprint_num: Any, attempt: int = 1) -> bool:
    """Invoke evaluator agent for a sprint. Returns True on PASS, False on FAIL."""
    sprint_num_int = int(sprint_num)
    attempt = int(attempt)
    pad = sprint_pad(sprint_num_int)
    dir_path = Path(sprint_dir(sprint_num_int))

    log_info(f"Evaluator testing sprint {pad} (attempt {attempt})...")

    project_type = json_read(
        str(Path(HARNESS_STATE) / "config.json"), ".projectType"
    )

    prompt = (
        f"Evaluate sprint {sprint_num_int}. Read the contract at "
        f"harness-state/sprints/sprint-{pad}/contract.json. "
        f"Read harness-state/handoff.json for git branch info and dev server "
        f"details. Use git diff to understand what changed. Start the dev server, "
        f"test every criterion, run regression tests if the contract specifies "
        f"regressionSprints, score the holistic dimensions for project type "
        f"'{project_type}'. Write your report to "
        f"harness-state/sprints/sprint-{pad}/eval-report.json and update status.json."
    )

    design_spec_path = Path(HARNESS_STATE) / "design-spec.md"
    if project_type == "web-frontend" and file_exists(str(design_spec_path)):
        prompt += (
            " IMPORTANT: Read harness-state/design-spec.md and verify the "
            "implementation matches the design system. Design Quality and "
            "Originality scores are BLOCKING -- FAIL the sprint if Design "
            "Quality < 6 or Originality < 5."
        )

    mcp_config: str | None = None
    if project_type == "web-frontend" and Path(".mcp.json").is_file():
        mcp_config = ".mcp.json"

    rc = invoke_claude("evaluator", prompt, max_turns=100, mcp_config=mcp_config)
    if rc != 0:
        log_error("Evaluator invocation failed")
        return False

    report_path = dir_path / "eval-report.json"
    if not file_exists(str(report_path)):
        log_error("Evaluator did not produce eval-report.json")
        return False

    report = _read_json(report_path)
    result = _get_result(report)

    pass_count = _get_count(
        report, "passCount", "pass_count", "score.passedCriteria", "score.passed"
    )
    fail_count = _get_count(
        report, "failCount", "fail_count", "score.failedCriteria", "score.failed"
    )
    blocking = _get_count(
        report, "blockingFailures", "blocking_failures", "score.blocking"
    )

    if result in ("pass", "passed"):
        log_success(
            f"Sprint {pad} PASSED ({pass_count} pass, {fail_count} fail, "
            f"{blocking} blocking)"
        )
        return True
    else:
        log_warn(
            f"Sprint {pad} FAILED ({pass_count} pass, {fail_count} fail, "
            f"{blocking} blocking)"
        )
        summary = ""
        if isinstance(report, dict):
            summary = str(report.get("summary", ""))[:300]
        log_warn(f"Summary: {summary}")
        return False


def invoke_regression() -> bool:
    """Run regression tests against all prior sprints. Returns True if all pass."""
    log_phase("REGRESSION TEST")

    project_type = json_read(
        str(Path(HARNESS_STATE) / "config.json"), ".projectType"
    )

    prompt = (
        "Run regression tests. Read harness-state/regression/registry.json for "
        "all prior sprint criteria. For each sprint in the registry, load its "
        "contract and test the listed blocking criteria. Start the dev server and "
        "test the running application. Write results to "
        "harness-state/regression/last-run.json."
    )

    mcp_config: str | None = None
    if project_type == "web-frontend" and Path(".mcp.json").is_file():
        mcp_config = ".mcp.json"

    rc = invoke_claude("evaluator", prompt, max_turns=100, mcp_config=mcp_config)
    if rc != 0:
        log_error("Regression test invocation failed")
        return False

    last_run_path = Path(HARNESS_STATE) / "regression" / "last-run.json"
    if file_exists(str(last_run_path)):
        data = _read_json(last_run_path)
        total_pass = 0
        total_fail = 0
        if isinstance(data, dict):
            total_pass = int(data.get("pass", 0) or 0)
            total_fail = int(data.get("fail", 0) or 0)
        if total_fail > 0:
            log_error(f"Regression FAILED: {total_pass} pass, {total_fail} fail")
            return False
        log_success(f"Regression PASSED: {total_pass} pass, {total_fail} fail")

    return True
