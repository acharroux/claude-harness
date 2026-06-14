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
from pathlib import Path
from typing import Any, Optional

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
    """Read JSON from path; return None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _get_result(data: Any) -> str:
    """Extract the eval result string (lowercased) tolerating multiple field names."""
    if not isinstance(data, dict):
        return "unknown"
    for key in ("overallResult", "result", "verdict"):
        v = data.get(key)
        if isinstance(v, str) and v:
            return v.lower()
    return "unknown"


def _get_count(data: Any, *keys: str) -> int:
    """Extract an integer count tolerating multiple field names and nested keys."""
    if not isinstance(data, dict):
        return 0
    for key in keys:
        if "." in key:
            # Nested key like "score.passedCriteria"
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


def invoke_evaluator(sprint_num: int, attempt: int = 1) -> bool:
    """Invoke the evaluator agent for a sprint. Returns True on PASS, False on FAIL."""
    pad = sprint_pad(sprint_num)
    dir_path = Path(sprint_dir(sprint_num))

    log_info(f"Evaluator testing sprint {pad} (attempt {attempt})...")

    project_type = json_read(str(Path(HARNESS_STATE) / "config.json"), ".projectType")

    prompt = (
        f"Evaluate sprint {sprint_num}. Read the contract at "
        f"harness-state/sprints/sprint-{pad}/contract.json. "
        f"Read harness-state/handoff.json for git branch info and dev server "
        f"details. Use git diff to understand what changed. Start the dev server, "
        f"test every criterion, run regression tests if the contract specifies "
        f"regressionSprints, score the holistic dimensions for project type "
        f"'{project_type}'. Write your report to "
        f"harness-state/sprints/sprint-{pad}/eval-report.json and update status.json."
    )

    if project_type == "web-frontend" and file_exists(
        str(Path(HARNESS_STATE) / "design-spec.md")
    ):
        prompt += (
            " IMPORTANT: Read harness-state/design-spec.md and verify the "
            "implementation matches the design system. Design Quality and "
            "Originality scores are BLOCKING -- FAIL the sprint if Design "
            "Quality < 6 or Originality < 5."
        )

    mcp_config: Optional[str] = (
        ".mcp.json" if project_type == "web-frontend" and Path(".mcp.json").is_file()
        else None
    )

    if invoke_claude("evaluator", prompt, max_turns=100, mcp_config=mcp_config) != 0:
        log_error("Evaluator invocation failed")
        return False

    report_path = dir_path / "eval-report.json"
    if not file_exists(str(report_path)):
        log_error("Evaluator did not produce eval-report.json")
        return False

    report = _read_json(report_path)
    result = _get_result(report)
    pass_count = _get_count(report, "passCount", "pass_count", "score.passedCriteria", "score.passed")
    fail_count = _get_count(report, "failCount", "fail_count", "score.failedCriteria", "score.failed")
    blocking = _get_count(report, "blockingFailures", "blocking_failures", "score.blocking")

    if result in ("pass", "passed"):
        log_success(
            f"Sprint {pad} PASSED ({pass_count} pass, {fail_count} fail, {blocking} blocking)"
        )
        return True

    log_warn(f"Sprint {pad} FAILED ({pass_count} pass, {fail_count} fail, {blocking} blocking)")
    if isinstance(report, dict):
        log_warn(f"Summary: {str(report.get('summary', ''))[:300]}")
    return False


def invoke_regression() -> bool:
    """Run regression tests against all prior sprints. Returns True if all pass."""
    log_phase("REGRESSION TEST")

    project_type = json_read(str(Path(HARNESS_STATE) / "config.json"), ".projectType")
    mcp_config: Optional[str] = (
        ".mcp.json" if project_type == "web-frontend" and Path(".mcp.json").is_file()
        else None
    )

    prompt = (
        "Run regression tests. Read harness-state/regression/registry.json for "
        "all prior sprint criteria. For each sprint in the registry, load its "
        "contract and test the listed blocking criteria. Start the dev server and "
        "test the running application. Write results to "
        "harness-state/regression/last-run.json."
    )

    if invoke_claude("evaluator", prompt, max_turns=100, mcp_config=mcp_config) != 0:
        log_error("Regression test invocation failed")
        return False

    last_run_path = Path(HARNESS_STATE) / "regression" / "last-run.json"
    if file_exists(str(last_run_path)):
        data = _read_json(last_run_path)
        if isinstance(data, dict):
            total_pass = int(data.get("pass") or 0)
            total_fail = int(data.get("fail") or 0)
            if total_fail > 0:
                log_error(f"Regression FAILED: {total_pass} pass, {total_fail} fail")
                return False
            log_success(f"Regression PASSED: {total_pass} pass, {total_fail} fail")

    return True
