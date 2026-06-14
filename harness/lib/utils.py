"""Shared utilities for the harness orchestrator (Python port of harness/lib/utils.sh).

This module mirrors every function in utils.sh and uses only the Python 3.8+
standard library. State files written by these functions are byte-for-byte
compatible with the bash reference implementation.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HARNESS_STATE = "harness-state"

# ANSI color codes (matching utils.sh exactly)
_RED = "\033[0;31m"
_GREEN = "\033[0;32m"
_YELLOW = "\033[1;33m"
_BLUE = "\033[0;34m"
_CYAN = "\033[0;36m"
_NC = "\033[0m"

# Compiled once at import time
_TOKEN_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_-]*)|\[(\d+)\]|\["([^"]*)"\]|\[\'([^\']*)\'\]'
)


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _use_color() -> bool:
    """Return True when stderr is a TTY and NO_COLOR is unset."""
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stderr.isatty()
    except Exception:
        return False


def _emit(color: str, message: str) -> None:
    if _use_color():
        sys.stderr.write(f"{color}[harness]{_NC} {message}\n")
    else:
        sys.stderr.write(f"[harness] {message}\n")
    try:
        sys.stderr.flush()
    except OSError:
        pass


def log_info(message: str) -> None:
    _emit(_BLUE, message)


def log_success(message: str) -> None:
    _emit(_GREEN, message)


def log_warn(message: str) -> None:
    _emit(_YELLOW, message)


def log_error(message: str) -> None:
    _emit(_RED, message)


def log_phase(message: str) -> None:
    use_color = _use_color()
    sep = ("━" * 51) if use_color else ("-" * 51)
    sys.stderr.write("\n")
    if use_color:
        sys.stderr.write(f"{_CYAN}{sep}{_NC}\n")
        sys.stderr.write(f"{_CYAN}  [harness] {message}{_NC}\n")
        sys.stderr.write(f"{_CYAN}{sep}{_NC}\n")
    else:
        sys.stderr.write(f"{sep}\n")
        sys.stderr.write(f"  [harness] {message}\n")
        sys.stderr.write(f"{sep}\n")
    sys.stderr.write("\n")
    try:
        sys.stderr.flush()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def sprint_pad(n: Any) -> str:
    """Zero-pad sprint number to two digits (matches printf '%02d')."""
    return f"{int(n):02d}"


def sprint_dir(n: Any) -> str:
    """Return 'harness-state/sprints/sprint-NN' with forward slashes."""
    return f"{HARNESS_STATE}/sprints/sprint-{sprint_pad(n)}"


def slugify(s: str) -> str:
    """Slugify a string for use in branch names.

    Matches bash:  tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g'
                   | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//' | cut -c1-50
    """
    out = str(s).lower()
    out = re.sub(r"[^a-z0-9]", "-", out)
    out = re.sub(r"-+", "-", out)
    out = out.strip("-")
    return out[:50]


def file_exists(path: Any) -> bool:
    """True only when path exists, is a regular file, and has non-zero size."""
    try:
        p = Path(str(path))
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


def _walk_field(data: Any, field: str) -> Any:
    """Walk a jq-style dotted/index field expression and return a value.

    Supports: .foo, .foo.bar, .foo[0], .foo[0].bar, .foo["bar"]
    Returns None on missing key or out-of-range index.
    """
    expr = field.strip().lstrip(".")
    if not expr:
        return data

    cur = data
    pos = 0
    while pos < len(expr):
        if expr[pos] == ".":
            pos += 1
            continue
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            return None
        name, idx, qkey1, qkey2 = m.group(1), m.group(2), m.group(3), m.group(4)
        if name is not None:
            if not isinstance(cur, dict) or name not in cur:
                return None
            cur = cur[name]
        elif idx is not None:
            i = int(idx)
            if not isinstance(cur, list) or not (0 <= i < len(cur)):
                return None
            cur = cur[i]
        else:
            key = qkey1 if qkey1 is not None else qkey2
            if not isinstance(cur, dict) or key not in cur:
                return None
            cur = cur[key]
        pos = m.end()
    return cur


def json_read(filepath: Any, field: str) -> str:
    """Read a JSON field from a file using a jq-like field expression.

    Returns "" on missing file, parse error, or missing field.
    Never raises.
    """
    try:
        path = Path(str(filepath))
        if not path.is_file():
            return ""
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""

    try:
        value = _walk_field(data, field)
    except Exception:
        return ""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


# ---------------------------------------------------------------------------
# Time helper
# ---------------------------------------------------------------------------

def _now_utc_iso() -> str:
    """ISO-8601 UTC timestamp matching bash `date -u +"%Y-%m-%dT%H:%M:%SZ"`."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# State file initialization
# ---------------------------------------------------------------------------

def init_harness_state(prompt: str, project_type: str = "general") -> None:
    """Initialize harness-state/ with config, cost-log, registry, progress.md."""
    state = Path(HARNESS_STATE)
    (state / "regression").mkdir(parents=True, exist_ok=True)
    (state / "sprints").mkdir(parents=True, exist_ok=True)

    env = os.environ
    config = {
        "userPrompt": prompt,
        "projectType": project_type,
        "contextStrategy": env.get("CONTEXT_STRATEGY", "reset"),
        "model": env.get("MODEL", "opus"),
        "maxSprintAttempts": int(env.get("MAX_SPRINT_ATTEMPTS", "3")),
        "maxContractRounds": int(env.get("MAX_CONTRACT_ROUNDS", "3")),
        "costCapPerSprint": float(env.get("COST_CAP_PER_SPRINT", "25.00")),
        "totalCostCap": float(env.get("TOTAL_COST_CAP", "200.00")),
    }
    (state / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    (state / "cost-log.json").write_text(
        '{"invocations": [], "totalCost": 0}\n', encoding="utf-8"
    )
    (state / "regression" / "registry.json").write_text(
        '{"sprints": {}, "lastFullRun": null}\n', encoding="utf-8"
    )

    started = _now_utc_iso()
    progress = (
        "# Harness Progress Log\n"
        "\n"
        f"**Project**: {prompt}\n"
        f"**Started**: {started}\n"
        f"**Model**: {env.get('MODEL', 'opus')}\n"
        f"**Context strategy**: {env.get('CONTEXT_STRATEGY', 'reset')}\n"
        "\n"
        "---\n"
        "\n"
    )
    (state / "progress.md").write_text(progress, encoding="utf-8")


# ---------------------------------------------------------------------------
# Cost log
# ---------------------------------------------------------------------------

def _parse_tokens(output_json: str) -> tuple:
    """Extract (input_tokens, output_tokens) from claude output JSON string."""
    if not (isinstance(output_json, str) and output_json.strip()):
        return 0, 0
    try:
        parsed = json.loads(output_json)
        usage = parsed.get("usage") if isinstance(parsed, dict) else None
        if isinstance(usage, dict):
            return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    except (ValueError, TypeError):
        pass
    return 0, 0


def log_cost(role: str, sprint: Any, output_json: str) -> None:
    """Append a cost-log entry parsed from claude output JSON.

    Tolerates empty / non-JSON input — falls back to zero token counts.
    """
    input_tokens, output_tokens = _parse_tokens(output_json)

    cost_file = Path(HARNESS_STATE) / "cost-log.json"
    try:
        data = json.loads(cost_file.read_text(encoding="utf-8")) if cost_file.is_file() else {}
    except ValueError:
        data = {}
    if not isinstance(data.get("invocations"), list):
        data = {"invocations": [], "totalCost": 0}

    try:
        sprint_val: Any = int(sprint)
    except (TypeError, ValueError):
        sprint_val = sprint

    data["invocations"].append({
        "role": role,
        "sprint": sprint_val,
        "timestamp": _now_utc_iso(),
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
    })

    cost_file.parent.mkdir(parents=True, exist_ok=True)
    cost_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def check_cost_cap() -> None:
    """Emit an info notice referencing the cost log. No-op beyond logging."""
    log_info(f"Cost tracking: see {HARNESS_STATE}/cost-log.json for invocation details")


# ---------------------------------------------------------------------------
# Progress log
# ---------------------------------------------------------------------------

def update_progress(
    sprint_num: Any,
    status: str,
    attempt: Any = 1,
    merge_sha: str = "",
) -> None:
    """Append a sprint section to harness-state/progress.md."""
    sprint_plan_path = Path(HARNESS_STATE) / "sprint-plan.json"
    sprint_name = f"Sprint {int(sprint_num)}"
    if sprint_plan_path.is_file():
        try:
            plan = json.loads(sprint_plan_path.read_text(encoding="utf-8"))
            sprints_list = plan.get("sprints") if isinstance(plan, dict) else None
            idx = int(sprint_num) - 1
            if isinstance(sprints_list, list) and 0 <= idx < len(sprints_list):
                entry = sprints_list[idx]
                if isinstance(entry, dict):
                    sprint_name = entry.get("name") or entry.get("title") or sprint_name
        except (ValueError, OSError, TypeError):
            pass

    lines = [
        "",
        f"## Sprint {sprint_pad(sprint_num)}: {sprint_name}",
        "",
        f"- **Status**: {status}",
        f"- **Attempt**: {attempt}",
        f"- **Time**: {_now_utc_iso()}",
    ]
    if merge_sha:
        lines.append(f"- **Merge commit**: {merge_sha}")
    lines.append("")

    progress_path = Path(HARNESS_STATE) / "progress.md"
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with progress_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------

_DEFAULT_HANDOFF: dict = {
    "projectName": "",
    "completedSprints": [],
    "currentSprint": 1,
    "totalSprints": 0,
    "completedFeatures": [],
    "keyFiles": {},
    "techStack": {},
    "outstandingIssues": [],
    "devServerCommand": "",
    "devServerPort": 0,
    "git": {
        "harnessBranch": "",
        "latestTag": "",
        "latestMergeSha": "",
        "prNumbers": [],
    },
}


def update_handoff(
    sprint_num: Any,
    merge_sha: str = "",
    tag: str = "",
    harness_branch: Optional[str] = None,
) -> None:
    """Update harness-state/handoff.json after a sprint completes."""
    handoff_path = Path(HARNESS_STATE) / "handoff.json"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)

    if file_exists(str(handoff_path)):
        try:
            data = json.loads(handoff_path.read_text(encoding="utf-8"))
        except ValueError:
            data = copy.deepcopy(_DEFAULT_HANDOFF)
    else:
        data = copy.deepcopy(_DEFAULT_HANDOFF)

    if not isinstance(data, dict):
        data = copy.deepcopy(_DEFAULT_HANDOFF)

    data.setdefault("completedSprints", [])
    data.setdefault("git", {})
    if not isinstance(data["git"], dict):
        data["git"] = {}

    sprint_int = int(sprint_num)
    completed = data["completedSprints"] if isinstance(data["completedSprints"], list) else []
    completed.append(sprint_int)
    data["completedSprints"] = list(dict.fromkeys(completed))
    data["currentSprint"] = sprint_int + 1
    data["git"]["latestTag"] = tag
    data["git"]["latestMergeSha"] = merge_sha
    if harness_branch:
        data["git"]["harnessBranch"] = harness_branch

    handoff_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Regression registry
# ---------------------------------------------------------------------------

def update_regression_registry(sprint_num: Any) -> None:
    """Update regression registry from contract.json criteria.

    No-op (no error raised, no key added) when contract is missing.
    """
    contract_path = Path(sprint_dir(sprint_num)) / "contract.json"
    registry_path = Path(HARNESS_STATE) / "regression" / "registry.json"

    if not file_exists(str(contract_path)):
        return

    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return

    criteria_ids = [
        c["id"] for c in contract.get("criteria", []) or []
        if isinstance(c, dict) and "id" in c
    ]

    if registry_path.is_file():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except ValueError:
            registry = {"sprints": {}, "lastFullRun": None}
    else:
        registry = {"sprints": {}, "lastFullRun": None}

    if not isinstance(registry, dict):
        registry = {"sprints": {}, "lastFullRun": None}
    if not isinstance(registry.get("sprints"), dict):
        registry["sprints"] = {}

    registry["sprints"][str(int(sprint_num))] = {
        "criteria": criteria_ids,
        "contractPath": f"sprints/sprint-{sprint_pad(sprint_num)}/contract.json",
    }

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
