"""Python port of harness/lib/contract.sh.

Iterative contract negotiation: the generator agent proposes a contract, the
evaluator agent reviews it. Up to MAX_CONTRACT_ROUNDS rounds. On acceptance the
proposal is copied to contract.json. On exhaustion the latest proposal is also
copied (matching the bash final fallback).

Public API:
    negotiate_contract(sprint_num: int) -> bool

Tolerances mirror contract.sh exactly:
  - decision field can be .decision, .reviewVerdict, or .verdict
  - accepted values: 'accepted', 'accept', 'approved', 'approve' (case-insensitive)
  - criteria-count shapes: .criteria, .features[].acceptanceCriteria,
    .features[].criteria, flat .acceptanceCriteria, else 0
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from harness.lib.invoke import invoke_claude
from harness.lib.utils import (
    file_exists,
    log_error,
    log_info,
    log_phase,
    log_success,
    log_warn,
    sprint_dir,
    sprint_pad,
)


# frozenset gives O(1) membership test
_ACCEPT_VALUES: frozenset[str] = frozenset(("accepted", "accept", "approved", "approve"))


def _read_json(path: Path) -> Any:
    """Read JSON from path; return None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def parse_decision(review_data: Any) -> str:
    """Extract the decision string (lowercased) from a review object.

    Tolerates .decision, .reviewVerdict, .verdict. Returns 'unknown' when none present.
    """
    if not isinstance(review_data, dict):
        return "unknown"
    for key in ("decision", "reviewVerdict", "verdict"):
        v = review_data.get(key)
        if isinstance(v, str) and v:
            return v.lower()
    return "unknown"


def is_accepted(review_data: Any) -> bool:
    """Return True iff the review's decision is one of the accepted variants."""
    return parse_decision(review_data) in _ACCEPT_VALUES


def count_criteria(proposal_data: Any) -> int:
    """Compute the criteria count from a proposal object.

    Mirrors the jq cascade in contract.sh:
      if .criteria          -> len(.criteria)
      elif .features        -> sum(len(f.acceptanceCriteria // f.criteria // []))
      elif .acceptanceCriteria -> len(.acceptanceCriteria)
      else 0
    """
    if not isinstance(proposal_data, dict):
        return 0

    criteria = proposal_data.get("criteria")
    if isinstance(criteria, list):
        return len(criteria)

    features = proposal_data.get("features")
    if isinstance(features, list):
        total = 0
        for f in features:
            if not isinstance(f, dict):
                continue
            ac = f.get("acceptanceCriteria")
            if not isinstance(ac, list):
                ac = f.get("criteria")
            if isinstance(ac, list):
                total += len(ac)
        return total

    flat = proposal_data.get("acceptanceCriteria")
    return len(flat) if isinstance(flat, list) else 0


def negotiate_contract(sprint_num: int) -> bool:
    """Run contract negotiation rounds for the given sprint number.

    Returns True on success (contract.json written). Returns False only when a
    claude invocation fails and we could not progress.
    """
    pad = sprint_pad(sprint_num)
    dir_path = Path(sprint_dir(sprint_num))
    proposal_path = dir_path / "contract-proposal.json"
    review_path = dir_path / "contract-review.json"
    contract_path = dir_path / "contract.json"

    try:
        max_rounds = int(os.environ.get("MAX_CONTRACT_ROUNDS", "3"))
    except ValueError:
        max_rounds = 3

    log_phase(f"CONTRACT NEGOTIATION — Sprint {pad}")
    dir_path.mkdir(parents=True, exist_ok=True)

    for round_idx in range(1, max_rounds + 1):
        log_info(f"Round {round_idx}/{max_rounds}")

        # ---- Generator proposes ------------------------------------------------
        log_info("Generator proposing contract...")
        gen_prompt = (
            f"Propose a sprint contract for sprint {sprint_num}. "
            f"Read harness-state/product-spec.md and harness-state/sprint-plan.json "
            f"for context. Read harness-state/handoff.json for current state. "
            f"Write your proposal to "
            f"harness-state/sprints/sprint-{pad}/contract-proposal.json."
        )
        if round_idx > 1:
            gen_prompt += (
                f" The evaluator has provided feedback in "
                f"harness-state/sprints/sprint-{pad}/contract-review.json. "
                f"Address all feedback in your revised proposal."
            )

        if invoke_claude("generator", gen_prompt, max_turns=30) != 0:
            log_error("Generator contract proposal failed")
            return False
        if not file_exists(str(proposal_path)):
            log_error("Generator did not produce contract-proposal.json")
            return False

        proposal_data = _read_json(proposal_path)
        criteria_count = count_criteria(proposal_data)
        log_info(f"Proposal: {criteria_count} criteria")

        # ---- Evaluator reviews -------------------------------------------------
        log_info("Evaluator reviewing contract...")
        eval_prompt = (
            f"Review the sprint contract proposal at "
            f"harness-state/sprints/sprint-{pad}/contract-proposal.json. "
            f"Check that criteria are testable, complete, and cover the sprint's "
            f"features from the sprint plan. Write your review to "
            f"harness-state/sprints/sprint-{pad}/contract-review.json."
        )
        if invoke_claude("evaluator", eval_prompt, max_turns=30) != 0:
            log_error("Evaluator contract review failed")
            return False
        if not file_exists(str(review_path)):
            log_error("Evaluator did not produce contract-review.json")
            return False

        review_data = _read_json(review_path)
        if is_accepted(review_data):
            shutil.copyfile(str(proposal_path), str(contract_path))
            log_success(f"Contract agreed (round {round_idx}, {criteria_count} criteria)")
            return True

        feedback = "no feedback provided"
        if isinstance(review_data, dict):
            for key in ("feedback", "verdictReason", "reason", "comments"):
                v = review_data.get(key)
                if isinstance(v, str) and v:
                    feedback = v
                    break
        log_warn(f"Evaluator requested revisions: {feedback[:200]}")

    # Max rounds reached — accept the latest proposal
    log_warn("Max negotiation rounds reached. Accepting latest proposal.")
    if file_exists(str(proposal_path)):
        shutil.copyfile(str(proposal_path), str(contract_path))
    return True
