#!/usr/bin/env python3
"""Hook: SubagentStop for evaluator.
Verifies the evaluator produced a valid eval report.
Exit 2 = block (send feedback to Claude), 0 = allow
"""

import json
import os
import sys
from pathlib import Path

HARNESS_STATE = os.environ.get("HARNESS_STATE", "harness-state")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _read_status(path: Path) -> str:
    return _read_json(path).get("status") or ""


def main() -> int:
    sys.stdin.read()  # consume hook input

    sprints_dir = Path(HARNESS_STATE) / "sprints"

    # Contract review mode: proposal exists but no contract yet
    for pattern in ("sprint-*", "fix-*", "refactor-*"):
        for d in sorted(sprints_dir.glob(pattern)):
            if not d.is_dir():
                continue
            if (d / "contract-proposal.json").is_file() and not (d / "contract.json").is_file():
                review = d / "contract-review.json"
                if not review.is_file():
                    print(
                        "Evaluator finished contract review but contract-review.json is missing.",
                        file=sys.stderr,
                    )
                    return 2
                data = _read_json(review)
                if not data.get("decision"):
                    print(
                        "contract-review.json is missing 'decision' field (must be 'accepted' or 'revise').",
                        file=sys.stderr,
                    )
                    return 2
                return 0

    # Sprint evaluation mode: find the sprint that's ready-for-eval
    eval_sprint: Path | None = None
    for pattern in ("sprint-*", "fix-*", "refactor-*"):
        for d in sorted(sprints_dir.glob(pattern)):
            if not d.is_dir():
                continue
            status_file = d / "status.json"
            if status_file.is_file() and _read_status(status_file) == "ready-for-eval":
                eval_sprint = d
                break
        if eval_sprint:
            break

    if eval_sprint is None:
        return 0

    # eval-report.json must exist
    report_path = eval_sprint / "eval-report.json"
    if not report_path.is_file():
        print(
            "Evaluator finished but eval-report.json is missing. Write your evaluation report.",
            file=sys.stderr,
        )
        return 2

    report = _read_json(report_path)

    # Must have a result field (tolerates overallResult / result / verdict)
    if not (report.get("overallResult") or report.get("result") or report.get("verdict")):
        print(
            "eval-report.json is missing result field (overallResult, result, or verdict).",
            file=sys.stderr,
        )
        return 2

    # Must have a results container (tolerates criteriaResults / features / score / results)
    if not (report.get("criteriaResults") is not None
            or report.get("features") is not None
            or report.get("score") is not None
            or report.get("results") is not None):
        print("eval-report.json is missing results data.", file=sys.stderr)
        return 2

    # Criteria count must match contract
    contract_path = eval_sprint / "contract.json"
    if contract_path.is_file():
        contract = _read_json(contract_path)
        contract_count = len(contract.get("criteria") or [])
        report_count = len(report.get("criteriaResults") or [])
        if contract_count > 0 and report_count < contract_count:
            print(
                f"eval-report.json has {report_count} criteria results but the contract has "
                f"{contract_count} criteria. Test ALL criteria.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
