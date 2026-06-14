#!/usr/bin/env python3
"""Harness Orchestrator -- Python port of harness/orchestrate.sh.

Coordinates the Planner-Generator-Evaluator pipeline for building software
through structured sprint cycles with context resets.

Usage:
    python harness/orchestrate.py "Build a kanban board" [options]
    python harness/orchestrate.py --extend "Add collaboration features"
    python harness/orchestrate.py --fix "Cards vanish on rapid drag"
    python harness/orchestrate.py --refactor "Extract state into Zustand"
    python harness/orchestrate.py --resume --from-sprint 4
    python harness/orchestrate.py --regression
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# HARNESS_ROOT bootstrap
# ---------------------------------------------------------------------------

# harness/orchestrate.py -> HARNESS_ROOT is the parent of "harness/" dir
SCRIPT_DIR = Path(__file__).resolve().parent
HARNESS_ROOT = SCRIPT_DIR.parent

# Export for downstream modules (invoke.py honors HARNESS_ROOT for --settings)
os.environ["HARNESS_ROOT"] = str(HARNESS_ROOT)

# Ensure repo root is importable so `from harness.lib...` works whatever the cwd
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))


# ---------------------------------------------------------------------------
# Defaults (mirroring orchestrate.sh)
# ---------------------------------------------------------------------------

MAX_SPRINT_ATTEMPTS = 3
MAX_CONTRACT_ROUNDS = 3
DEFAULT_PROJECT_TYPE = "general"
DEFAULT_CONTEXT_STRATEGY = "reset"
DEFAULT_MODEL = "opus"
DEFAULT_TOTAL_COST_CAP = 200.0
DEFAULT_COST_CAP_PER_SPRINT = 25.0
DEFAULT_FROM_SPRINT = 1


# ---------------------------------------------------------------------------
# .claude staging
# ---------------------------------------------------------------------------

def _copy_no_clobber(src_dir: Path, dst_dir: Path) -> None:
    """Recursively copy src_dir into dst_dir, never overwriting existing files."""
    if not src_dir.is_dir():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for entry in src_dir.iterdir():
        target = dst_dir / entry.name
        if entry.is_dir():
            _copy_no_clobber(entry, target)
        else:
            if not target.exists():
                shutil.copyfile(str(entry), str(target))


def stage_claude_assets(cwd: Optional[Path] = None) -> None:
    """Copy {HARNESS_ROOT}/.claude/{agents,skills} into cwd/.claude/ no-clobber.

    Also appends '.claude/agents/' and '.claude/skills/' to cwd/.gitignore if
    those entries are not already present.
    """
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    src_root = HARNESS_ROOT / ".claude"
    if not src_root.is_dir():
        return

    dst_root = cwd / ".claude"
    dst_root.mkdir(parents=True, exist_ok=True)

    src_agents = src_root / "agents"
    src_skills = src_root / "skills"
    if src_agents.is_dir():
        _copy_no_clobber(src_agents, dst_root / "agents")
    if src_skills.is_dir():
        _copy_no_clobber(src_skills, dst_root / "skills")

    gitignore = cwd / ".gitignore"
    existing = ""
    if gitignore.is_file():
        try:
            existing = gitignore.read_text(encoding="utf-8")
        except OSError:
            existing = ""

    if ".claude/agents/" not in existing:
        block = (
            "\n# Harness infrastructure (not project code)\n"
            ".claude/agents/\n"
            ".claude/skills/\n"
        )
        try:
            with gitignore.open("a", encoding="utf-8") as fh:
                fh.write(block)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrate.py",
        description=(
            "Harness orchestrator: Planner -> Generator -> Evaluator pipeline. "
            "Default mode is 'new' when a prompt is provided."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "user_prompt",
        nargs="?",
        default=None,
        help="Project description (used in mode=new).",
    )

    parser.add_argument("--extend", dest="extend", default=None,
                        metavar="PROMPT",
                        help="Extend existing project with new features.")
    parser.add_argument("--fix", dest="fix", default=None,
                        metavar="DESCRIPTION",
                        help="Fix a specific bug in an existing project.")
    parser.add_argument("--refactor", dest="refactor", default=None,
                        metavar="DESC",
                        help="Refactor without behavior change.")
    parser.add_argument("--regression", action="store_true",
                        help="Run regression tests across all prior sprints.")
    parser.add_argument("--resume", action="store_true",
                        help="Resume an in-progress harness session.")

    parser.add_argument("--project-type", dest="project_type",
                        default=DEFAULT_PROJECT_TYPE,
                        help="web-frontend|backend-api|cli-tool|general "
                             f"(default: {DEFAULT_PROJECT_TYPE}).")
    parser.add_argument("--context-strategy", dest="context_strategy",
                        default=DEFAULT_CONTEXT_STRATEGY,
                        help=f"reset|compact (default: {DEFAULT_CONTEXT_STRATEGY}).")
    parser.add_argument("--model", dest="model",
                        default=DEFAULT_MODEL,
                        help=f"opus|sonnet (default: {DEFAULT_MODEL}).")
    parser.add_argument("--max-cost", dest="max_cost",
                        type=float, default=DEFAULT_TOTAL_COST_CAP,
                        help=f"Total cost cap in USD (default: {DEFAULT_TOTAL_COST_CAP}).")
    parser.add_argument("--from-sprint", dest="from_sprint",
                        type=int, default=DEFAULT_FROM_SPRINT,
                        help="Start/resume from sprint N (default: 1).")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Show resolved configuration and exit without "
                             "invoking claude or modifying state.")

    return parser


def resolve_mode(args: argparse.Namespace) -> tuple:
    """Resolve (mode, prompt) tuple from parsed args.

    Mirrors orchestrate.sh's last-flag-wins precedence:
      regression > resume > refactor > fix > extend > new
    """
    if args.regression:
        return "regression", ""
    if args.resume:
        return "resume", ""
    if args.refactor is not None:
        return "refactor", args.refactor
    if args.fix is not None:
        return "fix", args.fix
    if args.extend is not None:
        return "extend", args.extend
    return "new", (args.user_prompt or "")


# ---------------------------------------------------------------------------
# Sprint loop
# ---------------------------------------------------------------------------

def _git_checkout(branch: str) -> None:
    """Checkout a branch, logging stderr on failure (never raises)."""
    from harness.lib import git as _git_mod
    try:
        _git_mod._run(["git", "checkout", branch], check=True, capture=True)
    except Exception as exc:
        from harness.lib import utils as _utils
        _utils.log_warn(f"git checkout {branch} failed: {exc}")


def _git_checkout_new(branch: str, base: str) -> None:
    """Create and checkout a new branch from base, logging stderr on failure."""
    from harness.lib import git as _git_mod
    try:
        _git_mod._run(["git", "checkout", "-b", branch, base],
                      check=True, capture=True)
    except Exception as exc:
        from harness.lib import utils as _utils
        _utils.log_warn(f"git checkout -b {branch} {base} failed: {exc}")

def _run_sprint(sprint_num: int, harness_branch: str) -> int:
    """Run a single sprint: contract -> generator -> evaluator with retries.

    Returns
    -------
    0 on PASS, 1 if all attempts failed, 2 if generator reported 'blocked'.
    """
    # Imports kept inside to avoid heavy imports during --help parsing
    from harness.lib import contract as contract_mod
    from harness.lib import evaluator as evaluator_mod
    from harness.lib import generator as generator_mod
    from harness.lib import git as git_mod
    from harness.lib import utils

    pad = utils.sprint_pad(sprint_num)
    dir_path = Path(utils.sprint_dir(sprint_num))

    # Read sprint name from plan
    plan_path = Path(utils.HARNESS_STATE) / "sprint-plan.json"
    sprint_name = f"Sprint {sprint_num}"
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            sprints_list = plan.get("sprints") if isinstance(plan, dict) else None
            idx = int(sprint_num) - 1
            if isinstance(sprints_list, list) and 0 <= idx < len(sprints_list):
                entry = sprints_list[idx]
                if isinstance(entry, dict):
                    sprint_name = (
                        entry.get("name") or entry.get("title") or sprint_name
                    )
        except (ValueError, OSError, TypeError):
            pass

    utils.log_phase(f"SPRINT {pad}: {sprint_name}")

    dir_path.mkdir(parents=True, exist_ok=True)

    # Contract negotiation (if no contract exists)
    contract_path = dir_path / "contract.json"
    if not utils.file_exists(str(contract_path)):
        contract_mod.negotiate_contract(sprint_num)
        git_mod.commit_harness_state(f"harness(contract): sprint-{pad} agreed")
    else:
        utils.log_info("Contract already exists, skipping negotiation")

    # Implementation + evaluation loop
    max_attempts = MAX_SPRINT_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        utils.log_info(f"Attempt {attempt}/{max_attempts}")

        git_mod.create_sprint_branch(harness_branch, sprint_num)

        # Generator implements
        rc = generator_mod.invoke_generator(sprint_num, attempt)
        if rc == generator_mod.EXIT_BLOCKED:
            utils.log_error("Generator is blocked. Aborting sprint.")
            git_mod.fail_sprint_attempt(harness_branch, sprint_num, attempt)
            return 2
        if rc != 0:
            git_mod.fail_sprint_attempt(harness_branch, sprint_num, attempt)
            continue

        # Evaluator tests
        if evaluator_mod.invoke_evaluator(sprint_num, attempt):
            # PASS: merge, tag, handoff
            merge_sha = git_mod.merge_sprint(harness_branch, sprint_num, attempt)
            tag = f"harness/sprint-{pad}/pass"

            utils.update_handoff(sprint_num, merge_sha, tag, harness_branch)
            utils.update_progress(sprint_num, "PASS", attempt, merge_sha)
            utils.update_regression_registry(sprint_num)
            git_mod.commit_harness_state(f"harness(eval): sprint-{pad} PASS")

            utils.log_success(
                f"Sprint {pad} PASSED on attempt {attempt}"
            )
            return 0
        else:
            # FAIL: tag, delete branch, retry
            git_mod.fail_sprint_attempt(harness_branch, sprint_num, attempt)
            utils.update_progress(sprint_num, "FAIL", attempt)
            utils.log_warn(f"Sprint {pad} failed on attempt {attempt}")

    utils.log_error(f"Sprint {pad} failed all {max_attempts} attempts")
    utils.update_progress(sprint_num, "FAILED (all attempts exhausted)", max_attempts)
    git_mod.commit_harness_state(f"harness(eval): sprint-{pad} FAILED")
    return 1


# ---------------------------------------------------------------------------
# Mode: new
# ---------------------------------------------------------------------------

def run_new_build(prompt: str, project_type: str, context_strategy: str,
                  model: str, total_cost_cap: float, from_sprint: int) -> int:
    """Entry point for mode=new. Mirrors run_new_build() in orchestrate.sh."""
    from harness.lib import git as git_mod
    from harness.lib import invoke as invoke_mod
    from harness.lib import planner as planner_mod
    from harness.lib import utils

    project_slug = utils.slugify(prompt)

    utils.log_phase("HARNESS: NEW BUILD")
    utils.log_info(f"Project: {prompt}")
    utils.log_info(f"Slug: {project_slug}")
    utils.log_info(f"Type: {project_type}")
    utils.log_info(f"Model: {model}")
    utils.log_info(f"Context strategy: {context_strategy}")

    # Auto-init git repo if not present
    if not _is_git_repo():
        utils.log_info("No git repo found. Initializing...")
        _git_auto_init(project_slug)

    # Push config into env so init_harness_state picks it up
    os.environ["CONTEXT_STRATEGY"] = context_strategy
    os.environ["MODEL"] = model
    os.environ["TOTAL_COST_CAP"] = str(total_cost_cap)

    utils.init_harness_state(prompt, project_type)

    harness_branch = git_mod.create_harness_branch(project_slug)

    # Initialize handoff.json with harness branch
    state_dir = Path(utils.HARNESS_STATE)
    state_dir.mkdir(parents=True, exist_ok=True)
    handoff = {
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
            "harnessBranch": harness_branch,
            "latestTag": "",
            "latestMergeSha": "",
            "prNumbers": [],
        },
    }
    (state_dir / "handoff.json").write_text(
        json.dumps(handoff, indent=2) + "\n", encoding="utf-8"
    )

    git_mod.commit_harness_state(f"harness: initialize state for {project_slug}")

    # Plan
    sprint_count = planner_mod.invoke_planner("new")
    git_mod.commit_harness_state("harness(plan): product spec and sprint plan")
    git_mod._run(["git", "tag", "harness/plan"], check=False, capture=True)

    utils.log_info(f"Sprint plan: {sprint_count} sprints")

    failed_sprints = 0
    for sprint_num in range(from_sprint, sprint_count + 1):
        rc = _run_sprint(sprint_num, harness_branch)
        if rc != 0:
            failed_sprints += 1
            utils.log_warn(
                f"Sprint {sprint_num} failed. Continuing to next sprint."
            )
        utils.check_cost_cap()

    # Generate README on full success
    if failed_sprints == 0:
        utils.log_info("Generating README...")
        try:
            invoke_mod.invoke_claude(
                "generator",
                (
                    "Read harness-state/product-spec.md for the product vision and "
                    "features. Read harness-state/handoff.json for the tech stack and "
                    "dev server command. Read harness-state/progress.md for what was "
                    "built across sprints. Write a comprehensive README.md for this "
                    "project covering: what it is, features, how to install and run "
                    "(dev + build), tech stack, and project structure. Do NOT mention "
                    "the harness or sprint process -- write it as a normal project README."
                ),
                max_turns=30,
            )
        except FileNotFoundError:
            utils.log_warn("claude CLI not found -- skipping README generation")

        git_mod._run(["git", "add", "README.md"], check=False, capture=True)
        git_mod.commit_harness_state("harness: generate README.md")

    utils.log_phase("HARNESS COMPLETE")

    pr_body = git_mod.generate_pr_body()
    git_mod.create_pr(harness_branch, project_slug, pr_body)

    if failed_sprints > 0:
        utils.log_warn(
            f"{failed_sprints} sprint(s) failed. "
            f"Review harness-state/progress.md for details."
        )
        return 1

    utils.log_success("All sprints passed!")
    return 0


# ---------------------------------------------------------------------------
# Mode: extend
# ---------------------------------------------------------------------------

def run_extend(prompt: str) -> int:
    from harness.lib import git as git_mod
    from harness.lib import planner as planner_mod
    from harness.lib import utils

    utils.log_phase("HARNESS: EXTEND")
    utils.log_info(f"New features: {prompt}")

    config_path = Path(utils.HARNESS_STATE) / "config.json"
    if not utils.file_exists(str(config_path)):
        utils.log_error("No existing harness state found. Run a new build first.")
        return 1

    handoff_path = Path(utils.HARNESS_STATE) / "handoff.json"
    harness_branch = utils.json_read(str(handoff_path), ".git.harnessBranch")
    if harness_branch:
        _git_checkout(harness_branch)

    # Update config with new prompt
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        cfg["userPrompt"] = prompt
        config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        pass

    # Count completed sprints (those with a passing eval report)
    completed_sprints = 0
    sprints_root = Path(utils.HARNESS_STATE) / "sprints"
    if sprints_root.is_dir():
        for d in sorted(sprints_root.glob("sprint-*")):
            if not d.is_dir():
                continue
            result = utils.json_read(str(d / "eval-report.json"), ".overallResult")
            if result == "PASS":
                completed_sprints += 1

    total_sprints = planner_mod.invoke_planner("extend")
    git_mod.commit_harness_state("harness(plan): extend with new features")

    new_start = completed_sprints + 1
    sprint_count = total_sprints - completed_sprints
    utils.log_info(
        f"Added {sprint_count} new sprints ({new_start}-{total_sprints})"
    )

    for sprint_num in range(new_start, total_sprints + 1):
        try:
            _run_sprint(sprint_num, harness_branch)
        except Exception as exc:
            utils.log_warn(f"Sprint {sprint_num} raised: {exc}")
        utils.check_cost_cap()

    utils.log_phase("EXTEND COMPLETE")
    pr_body = git_mod.generate_pr_body()
    slug = utils.slugify(prompt)
    git_mod.create_pr(harness_branch, f"extend-{slug}", pr_body)
    return 0


# ---------------------------------------------------------------------------
# Mode: fix
# ---------------------------------------------------------------------------

def run_fix(prompt: str) -> int:
    from harness.lib import evaluator as evaluator_mod
    from harness.lib import git as git_mod
    from harness.lib import invoke as invoke_mod
    from harness.lib import utils

    utils.log_phase("HARNESS: FIX")
    utils.log_info(f"Bug: {prompt}")

    config_path = Path(utils.HARNESS_STATE) / "config.json"
    if not utils.file_exists(str(config_path)):
        utils.log_error("No existing harness state found.")
        return 1

    handoff_path = Path(utils.HARNESS_STATE) / "handoff.json"
    harness_branch = utils.json_read(str(handoff_path), ".git.harnessBranch")
    if harness_branch:
        _git_checkout(harness_branch)

    issue_number = git_mod.create_issue(
        f"Bug: {prompt}",
        f"## Reported behavior\n{prompt}\n\n## Harness tracking\n"
        f"Automated fix via harness.",
    )

    # Determine fix sprint number
    sprints_root = Path(utils.HARNESS_STATE) / "sprints"
    sprints_root.mkdir(parents=True, exist_ok=True)
    fix_count = sum(1 for p in sprints_root.iterdir()
                    if p.is_dir() and p.name.startswith("fix-"))
    fix_id = f"fix-{fix_count + 1:03d}"
    fix_dir = sprints_root / fix_id
    fix_dir.mkdir(parents=True, exist_ok=True)

    # Generate fix contract
    utils.log_info("Generating fix contract...")
    try:
        invoke_mod.invoke_claude(
            "generator",
            (
                f"Create a fix contract for this bug: {prompt}. Write a surgical "
                f"contract with criteria that verify the fix AND regression criteria "
                f"from related sprints. Write to "
                f"harness-state/sprints/{fix_id}/contract.json."
            ),
            max_turns=30,
        )
    except FileNotFoundError:
        utils.log_error("claude CLI not found")
        return 1

    sprint_branch = f"{harness_branch}/{fix_id}"
    _git_checkout_new(sprint_branch, harness_branch)

    invoke_mod.invoke_claude(
        "generator",
        (
            f"Fix this bug: {prompt}. Read the contract at "
            f"harness-state/sprints/{fix_id}/contract.json. Write your log to "
            f"harness-state/sprints/{fix_id}/generator-log.md. Set status to "
            f"ready-for-eval."
        ),
        max_turns=100,
    )

    if evaluator_mod.invoke_evaluator(fix_id, 1):
        git_mod.merge_named_branch(
            harness_branch, sprint_branch,
            f"harness({fix_id}): fix verified",
            f"harness/{fix_id}/pass",
        )
        utils.update_regression_registry(fix_id)
        git_mod.commit_harness_state(f"harness({fix_id}): fix verified")
        git_mod.create_fix_pr(sprint_branch, harness_branch, fix_id, prompt,
                              issue_number)
        utils.log_success("Fix verified -- PR created")
        return 0

    utils.log_error(
        f"Fix did not pass evaluation. See {fix_dir.as_posix()}/eval-report.json"
    )
    return 1


# ---------------------------------------------------------------------------
# Mode: refactor
# ---------------------------------------------------------------------------

def run_refactor(prompt: str) -> int:
    from harness.lib import evaluator as evaluator_mod
    from harness.lib import invoke as invoke_mod
    from harness.lib import git as git_mod
    from harness.lib import utils

    utils.log_phase("HARNESS: REFACTOR")
    utils.log_info(f"Refactor: {prompt}")

    handoff_path = Path(utils.HARNESS_STATE) / "handoff.json"
    harness_branch = utils.json_read(str(handoff_path), ".git.harnessBranch")
    if harness_branch:
        _git_checkout(harness_branch)

    utils.log_info("Running pre-refactor regression baseline...")
    try:
        evaluator_mod.invoke_regression()
    except Exception:
        utils.log_warn("Pre-refactor regression had failures")

    ref_dir = Path(utils.HARNESS_STATE) / "sprints" / "refactor-001"
    ref_dir.mkdir(parents=True, exist_ok=True)

    try:
        invoke_mod.invoke_claude(
            "generator",
            (
                f"Create a refactor contract: {prompt}. This must not change any "
                f"behavior. Include ALL prior sprint criteria as regression tests. "
                f"Write to harness-state/sprints/refactor-001/contract.json."
            ),
            max_turns=30,
        )
    except FileNotFoundError:
        utils.log_error("claude CLI not found")
        return 1

    sprint_branch = f"{harness_branch}/refactor-001"
    _git_checkout_new(sprint_branch, harness_branch)

    invoke_mod.invoke_claude(
        "generator",
        (
            f"Implement this refactor: {prompt}. Read the contract at "
            f"harness-state/sprints/refactor-001/contract.json. Behavior MUST "
            f"NOT change. Write log to "
            f"harness-state/sprints/refactor-001/generator-log.md."
        ),
        max_turns=200,
    )

    if (evaluator_mod.invoke_evaluator("refactor-001", 1)
            and evaluator_mod.invoke_regression()):
        git_mod.merge_named_branch(
            harness_branch, sprint_branch,
            "harness(refactor): merge (PASS, full regression)",
            "harness/refactor-001/pass",
        )
        git_mod.commit_harness_state(
            "harness(refactor): verified with full regression"
        )
        utils.log_success("Refactor complete with full regression pass")
        return 0

    utils.log_error("Refactor failed regression. See eval reports.")
    return 1


# ---------------------------------------------------------------------------
# Mode: resume
# ---------------------------------------------------------------------------

def run_resume(from_sprint: int) -> int:
    from harness.lib import git as git_mod
    from harness.lib import utils

    utils.log_phase(f"HARNESS: RESUME from sprint {from_sprint}")

    handoff_path = Path(utils.HARNESS_STATE) / "handoff.json"
    if not utils.file_exists(str(handoff_path)):
        utils.log_error("No handoff.json found -- nothing to resume.")
        return 1

    harness_branch = utils.json_read(str(handoff_path), ".git.harnessBranch")
    if harness_branch:
        _git_checkout(harness_branch)

    plan_path = Path(utils.HARNESS_STATE) / "sprint-plan.json"
    total_str = utils.json_read(str(plan_path), ".sprints | length")
    total_sprints = 0
    if total_str:
        try:
            total_sprints = int(total_str)
        except ValueError:
            total_sprints = 0
    if total_sprints == 0 and plan_path.is_file():
        try:
            data = json.loads(plan_path.read_text(encoding="utf-8"))
            sprints = data.get("sprints") if isinstance(data, dict) else None
            total_sprints = len(sprints) if isinstance(sprints, list) else 0
        except (OSError, ValueError):
            total_sprints = 0

    for sprint_num in range(from_sprint, total_sprints + 1):
        try:
            _run_sprint(sprint_num, harness_branch)
        except Exception as exc:
            utils.log_warn(f"Sprint {sprint_num} raised: {exc}")
        utils.check_cost_cap()

    utils.log_phase("RESUME COMPLETE")

    pr_body = git_mod.generate_pr_body()
    config_path = Path(utils.HARNESS_STATE) / "config.json"
    user_prompt = utils.json_read(str(config_path), ".userPrompt")
    git_mod.create_pr(harness_branch, utils.slugify(user_prompt), pr_body)
    return 0


# ---------------------------------------------------------------------------
# git auto-init helpers
# ---------------------------------------------------------------------------

def _is_git_repo() -> bool:
    cp = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return cp.returncode == 0


def _git_auto_init(project_slug: str) -> None:
    """Initialize a git repo with main branch and an initial commit."""
    subprocess.run(["git", "init", "-q", "-b", "main"],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    email = os.environ.get("GIT_EMAIL", "harness@claude-harness.dev")
    name = os.environ.get("GIT_NAME", "Claude Harness")
    subprocess.run(["git", "config", "user.email", email],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.name", name],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    Path("README.md").write_text(f"# {project_slug}\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "commit", "-q", "-m", "initial commit"],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _print_dry_run(mode: str, prompt: str, project_type: str,
                   context_strategy: str, model: str,
                   total_cost_cap: float) -> None:
    """Mirror bash dry-run output but emit to stdout (so tests can capture)."""
    sys.stdout.write("[harness] DRY RUN -- would execute mode: " + mode + "\n")
    sys.stdout.write(f"[harness] Prompt: {prompt}\n")
    sys.stdout.write(
        f"[harness] Config: type={project_type} strategy={context_strategy} "
        f"model={model} maxcost={total_cost_cap}\n"
    )
    try:
        sys.stdout.flush()
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    mode, prompt = resolve_mode(args)

    # Validate mode=new requires prompt
    if mode == "new" and not prompt:
        parser.error(
            "a project description is required for mode=new "
            "(positional prompt or one of --extend/--fix/--refactor/--resume/--regression)"
        )

    # DRY RUN: report and exit before any side effects
    if args.dry_run:
        _print_dry_run(
            mode, prompt, args.project_type, args.context_strategy,
            args.model, args.max_cost,
        )
        return 0

    # Stage .claude/ assets into cwd (no-clobber). Only for non-dry-run.
    stage_claude_assets()

    start_time = time.time()

    if mode == "new":
        rc = run_new_build(
            prompt=prompt,
            project_type=args.project_type,
            context_strategy=args.context_strategy,
            model=args.model,
            total_cost_cap=args.max_cost,
            from_sprint=args.from_sprint,
        )
    elif mode == "extend":
        rc = run_extend(prompt)
    elif mode == "fix":
        rc = run_fix(prompt)
    elif mode == "refactor":
        rc = run_refactor(prompt)
    elif mode == "resume":
        rc = run_resume(args.from_sprint)
    elif mode == "regression":
        from harness.lib import evaluator as evaluator_mod
        rc = 0 if evaluator_mod.invoke_regression() else 1
    else:
        sys.stderr.write(f"[harness] Unknown mode: {mode}\n")
        return 1

    duration = int(time.time() - start_time)
    hours = duration // 3600
    minutes = (duration % 3600) // 60

    from harness.lib import utils
    utils.log_phase("DONE")
    utils.log_info(f"Total time: {hours}h {minutes}m")
    utils.log_info(f"Cost log: {utils.HARNESS_STATE}/cost-log.json")
    utils.log_info(f"Progress: {utils.HARNESS_STATE}/progress.md")

    return rc


if __name__ == "__main__":
    sys.exit(main())
