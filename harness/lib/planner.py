"""Python port of harness/lib/planner.sh.

Provides invoke_planner(mode='new') which calls the planner agent via
invoke_claude and verifies that product-spec.md and sprint-plan.json were
produced.

Public API:
    invoke_planner(mode: str = 'new') -> int

Returns the number of sprints declared in sprint-plan.json. Raises RuntimeError
on failure (mirroring the bash early-return on missing outputs / invalid JSON).
"""

from __future__ import annotations

import json
from pathlib import Path

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
)


_NEW_PROMPT = (
    "Read harness-state/config.json for the user prompt and project type. "
    "Produce a comprehensive product spec in harness-state/product-spec.md "
    "and sprint decomposition in harness-state/sprint-plan.json."
)

_EXTEND_PROMPT = (
    "You are extending an existing project. Read harness-state/product-spec.md, "
    "harness-state/handoff.json, and harness-state/sprint-plan.json to understand "
    "what exists. Then read harness-state/config.json for the new feature request. "
    "Design additive sprints that build on the existing architecture. APPEND to "
    "product-spec.md and ADD new sprints to sprint-plan.json."
)


def invoke_planner(mode: str = "new") -> int:
    """Invoke the planner agent and return the produced sprint count.

    Parameters
    ----------
    mode : "new" (default) or "extend".

    Returns
    -------
    int -- the number of entries in sprint-plan.json's `sprints` array.

    Raises
    ------
    RuntimeError on any of: claude invocation failed, missing outputs, or
    sprint-plan.json that cannot be parsed.
    """
    log_phase(f"PLANNER PHASE ({mode})")

    prompt = _EXTEND_PROMPT if mode == "extend" else _NEW_PROMPT

    log_info("Invoking planner...")
    rc = invoke_claude("planner", prompt, max_turns=50)
    if rc != 0:
        log_error("Planner invocation failed")
        raise RuntimeError(f"planner invocation exited with code {rc}")

    spec_path = Path(HARNESS_STATE) / "product-spec.md"
    plan_path = Path(HARNESS_STATE) / "sprint-plan.json"

    if not file_exists(str(spec_path)):
        log_error("Planner did not produce product-spec.md")
        raise RuntimeError("missing product-spec.md")

    if not file_exists(str(plan_path)):
        log_error("Planner did not produce sprint-plan.json")
        raise RuntimeError("missing sprint-plan.json")

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log_error("sprint-plan.json is not valid JSON")
        raise RuntimeError("sprint-plan.json is not valid JSON") from exc

    sprints = plan.get("sprints") if isinstance(plan, dict) else None
    sprint_count = len(sprints) if isinstance(sprints, list) else 0

    # Web-frontend projects expect a design-spec.md alongside the spec
    project_type = json_read(str(Path(HARNESS_STATE) / "config.json"), ".projectType")
    if project_type == "web-frontend":
        design_path = Path(HARNESS_STATE) / "design-spec.md"
        if file_exists(str(design_path)):
            log_success("Design spec produced for web-frontend project")
        else:
            log_warn("Planner did not produce design-spec.md for web-frontend project")

    log_success(f"Planner produced spec with {sprint_count} sprints")
    # Match bash: emit count to stdout (so callers reading stdout see it)
    print(sprint_count)
    return sprint_count
