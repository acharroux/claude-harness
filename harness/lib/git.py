"""Python port of harness/lib/git.sh.

Wraps git and gh CLI invocations via subprocess. All branch and tag names
mirror the bash reference byte-for-byte:

    Harness branch: harness/<slug>
    Sprint branch:  <harness_branch>-sprint-NN  (zero-padded to width 2)
    Pass tag:       harness/sprint-NN/pass
    Fail tag:       harness/sprint-NN/attempt-K
    Merge commit:   harness(sprint-NN): merge (PASS, attempt K)

The PR/issue helpers degrade gracefully when `gh` is missing or no `origin`
remote is configured, returning without raising.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from harness.lib.utils import (
    HARNESS_STATE,
    file_exists,
    json_read,
    log_info,
    log_success,
    log_warn,
    sprint_dir,
    sprint_pad,
)


# ---------------------------------------------------------------------------
# Internal subprocess helpers
# ---------------------------------------------------------------------------

def _run(
    args: List[str],
    *,
    check: bool = True,
    capture: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """Run a subprocess and return the CompletedProcess.

    By default captures stdout/stderr and raises CalledProcessError on non-zero
    exit. When check=True and the process fails, stderr is logged before raising
    so the error is visible in harness output.
    """
    result = subprocess.run(
        args,
        check=False,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if stderr:
            import sys
            print(f"[git error] {' '.join(args)}\n{stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, args,
                                            result.stdout, result.stderr)
    return result


def _git_ok(*args: str) -> bool:
    """Run a git command and return True iff exit code is zero."""
    cp = _run(["git", *args], check=False, capture=True)
    return cp.returncode == 0


def _git_out(*args: str) -> str:
    """Return git stdout (stripped) or empty string on failure."""
    cp = _run(["git", *args], check=False, capture=True)
    if cp.returncode != 0:
        return ""
    return (cp.stdout or "").strip()


def _has_remote_origin() -> bool:
    return _git_ok("remote", "get-url", "origin")


def _has_gh() -> bool:
    return shutil.which("gh") is not None


def _resolve_default_base_branch() -> str:
    """Return the default branch on origin (e.g., 'main') or 'main' as fallback."""
    sym = _git_out("symbolic-ref", "refs/remotes/origin/HEAD")
    if sym.startswith("refs/remotes/origin/"):
        return sym[len("refs/remotes/origin/"):]
    return "main"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_harness_branch(project_slug: str) -> str:
    """Create (or check out) the harness branch for the given project slug.

    Returns the branch name 'harness/<slug>'. Idempotent: if the branch already
    exists, this re-checks-it-out without error.
    """
    harness_branch = f"harness/{project_slug}"

    base_branch = _resolve_default_base_branch()
    if not _git_ok("rev-parse", "--verify", base_branch):
        current = _git_out("branch", "--show-current")
        base_branch = current if current else "main"

    log_info(f"Creating harness branch: {harness_branch} from {base_branch}")

    create = _run(
        ["git", "checkout", "-b", harness_branch, base_branch],
        check=False,
        capture=True,
    )
    if create.returncode != 0:
        _run(["git", "checkout", harness_branch], check=True, capture=True)

    return harness_branch


def create_sprint_branch(harness_branch: str, sprint_num) -> str:
    """Create a fresh sprint branch from the harness branch.

    Returns '<harness_branch>-sprint-NN'. Any existing branch with the same
    name is force-deleted first so the new branch always starts clean from the
    harness branch tip.
    """
    sprint_branch = f"{harness_branch}-sprint-{sprint_pad(sprint_num)}"

    log_info(f"Creating sprint branch: {sprint_branch}")

    if _git_ok("rev-parse", "--verify", sprint_branch):
        _run(["git", "branch", "-D", sprint_branch], check=False, capture=True)

    _run(
        ["git", "checkout", "-b", sprint_branch, harness_branch],
        check=True,
        capture=True,
    )

    return sprint_branch


def merge_sprint(harness_branch: str, sprint_num, attempt) -> str:
    """Merge the sprint branch back into the harness branch on PASS.

    Returns the merge commit SHA. Performs (in order):
      1. Stage and commit any uncommitted evaluator artifacts on the sprint
         branch.
      2. Checkout harness_branch.
      3. `git merge --no-ff` with the canonical PASS message.
      4. Tag the merge commit with `harness/sprint-NN/pass`.
      5. Delete the merged sprint branch.
    """
    sprint_pad_str = sprint_pad(sprint_num)
    sprint_branch = f"{harness_branch}-sprint-{sprint_pad_str}"

    log_info(f"Merging sprint {sprint_pad_str} to {harness_branch}")

    # Commit any evaluator artifacts left on the sprint branch
    _run(["git", "add", "-A"], check=False, capture=True)
    if not _git_ok("diff", "--cached", "--quiet"):
        _run(
            ["git", "commit", "-q",
             "-m", f"harness(sprint-{sprint_pad_str}): evaluator artifacts"],
            check=False, capture=True,
        )

    _run(["git", "checkout", harness_branch], check=True, capture=True)

    # Clean any leftover untracked or modified files so the merge is clean
    _run(["git", "add", "-A"], check=False, capture=True)
    if not _git_ok("diff", "--cached", "--quiet"):
        _run(
            ["git", "commit", "-q",
             "-m", f"harness(sprint-{sprint_pad_str}): harness branch cleanup before merge"],
            check=False, capture=True,
        )

    merge_msg = f"harness(sprint-{sprint_pad_str}): merge (PASS, attempt {attempt})"
    _run(
        ["git", "merge", "--no-ff", sprint_branch, "-m", merge_msg],
        check=True,
        capture=True,
    )

    merge_sha = _git_out("rev-parse", "HEAD")

    tag = f"harness/sprint-{sprint_pad_str}/pass"
    _run(["git", "tag", tag], check=True, capture=True)
    log_success(f"Tagged: {tag}")

    _run(["git", "branch", "-d", sprint_branch], check=False, capture=True)

    return merge_sha


def fail_sprint_attempt(harness_branch: str, sprint_num, attempt) -> None:
    """Tag a failed sprint attempt and switch back to the harness branch.

    Stashes any uncommitted changes (so the failed evaluator artifacts don't
    block the checkout), drops the stash, and force-deletes the sprint branch.
    """
    sprint_pad_str = sprint_pad(sprint_num)
    sprint_branch = f"{harness_branch}-sprint-{sprint_pad_str}"

    tag = f"harness/sprint-{sprint_pad_str}/attempt-{attempt}"
    _run(["git", "tag", tag], check=False, capture=True)
    log_warn(f"Tagged failed attempt: {tag}")

    # Stash dirty tree, switch, drop the stash. Tolerate empty stash on Windows.
    _run(["git", "stash", "-q"], check=False, capture=True)
    _run(["git", "checkout", harness_branch], check=True, capture=True)
    _run(["git", "stash", "drop", "-q"], check=False, capture=True)

    _run(["git", "branch", "-D", sprint_branch], check=False, capture=True)


def commit_harness_state(message: str) -> None:
    """Stage and commit the harness-state directory.

    No-op when there are no changes (does not create an empty commit).
    """
    state_dir = HARNESS_STATE

    _run(["git", "add", f"{state_dir}/"], check=False, capture=True)
    _run(["git", "add", "-u", f"{state_dir}/"], check=False, capture=True)

    if _git_ok("diff", "--cached", "--quiet"):
        log_info("No harness-state changes to commit")
        return

    _run(["git", "commit", "-m", message], check=True, capture=True)


def create_pr(harness_branch: str, project_slug: str, pr_body: str) -> None:
    """Push the harness branch and open a PR via gh, or warn and return.

    Never raises: missing gh or missing origin remote results in a logged
    warning and an early return.
    """
    if not _has_gh():
        log_warn("gh CLI not found -- skipping PR creation")
        log_info(f"Harness branch ready: {harness_branch}")
        log_info("Create PR manually: git push && gh pr create")
        return

    if not _has_remote_origin():
        log_warn("No git remote configured -- skipping PR creation")
        log_info(f"Harness branch ready: {harness_branch}")
        return

    log_info("Pushing harness branch and creating PR...")
    _run(["git", "push", "-u", "origin", harness_branch], check=True, capture=True)

    base_branch = _resolve_default_base_branch()

    pr_title = f"harness: {project_slug}"
    if len(pr_title) > 256:
        pr_title = pr_title[:253] + "..."

    _run(
        [
            "gh", "pr", "create",
            "--base", base_branch,
            "--head", harness_branch,
            "--title", pr_title,
            "--body", pr_body,
        ],
        check=False,
        capture=True,
    )


def create_fix_pr(
    fix_branch: str,
    base_branch: str,
    fix_id: str,
    bug_description: str,
    issue_number: str = "",
) -> None:
    """Push a fix branch and open a PR via gh, or warn and return.

    Falls back to the default origin branch if the requested base_branch does
    not exist on the remote. Never raises.
    """
    if not _has_gh():
        log_warn("gh CLI not found -- skipping PR creation")
        log_info(f"Fix branch ready: {fix_branch}")
        log_info("Create PR manually: git push && gh pr create")
        return

    if not _has_remote_origin():
        log_warn("No git remote configured -- skipping PR creation")
        log_info(f"Fix branch ready: {fix_branch}")
        return

    ls = _run(
        ["git", "ls-remote", "--heads", "origin", base_branch],
        check=False,
        capture=True,
    )
    if ls.returncode != 0 or not (ls.stdout and ls.stdout.strip()):
        fallback = _resolve_default_base_branch()
        log_warn(
            f"Base branch '{base_branch}' not found on remote, "
            f"falling back to '{fallback}'"
        )
        base_branch = fallback

    log_info("Pushing fix branch and creating PR...")
    _run(["git", "push", "-u", "origin", fix_branch], check=False, capture=True)
    _run(
        ["git", "push", "origin", f"harness/{fix_id}/pass"],
        check=False,
        capture=True,
    )

    issue_ref = f"Fixes #{issue_number}" if issue_number else ""

    pr_body = (
        f"## Fix: {fix_id}\n"
        f"\n"
        f"### Bug\n"
        f"{bug_description}\n"
        f"\n"
        f"### Verification\n"
        f"- Fix evaluated and passed all criteria\n"
        f"- Regression registry updated\n"
        f"{issue_ref}\n"
        f"\n"
        f"---\n"
        f"Built with the [Planner-Generator-Evaluator Harness]"
        f"(https://www.anthropic.com/engineering/harness-design-long-running-apps)"
    )

    pr_title = f"harness({fix_id}): {bug_description[:50]}"

    _run(
        [
            "gh", "pr", "create",
            "--base", base_branch,
            "--head", fix_branch,
            "--title", pr_title,
            "--body", pr_body,
        ],
        check=False,
        capture=True,
    )


def create_issue(title: str, body: str) -> str:
    """Create a GitHub issue via gh and return the issue number as a string.

    Returns "" when gh is unavailable, no origin remote is configured, or the
    gh invocation fails. Never raises.
    """
    if not _has_gh():
        log_warn("gh CLI not found -- skipping issue creation")
        return ""

    if not _has_remote_origin():
        log_warn("No git remote configured -- skipping issue creation")
        return ""

    cp = _run(
        [
            "gh", "issue", "create",
            "--title", title,
            "--body", body,
            "--label", "harness-fix,bug",
        ],
        check=False,
        capture=True,
    )
    if cp.returncode != 0:
        log_warn("Failed to create issue")
        return ""

    issue_url = (cp.stdout or "").strip()
    # Extract trailing digits from the URL (e.g., /issues/42 -> 42)
    digits = ""
    for ch in reversed(issue_url):
        if ch.isdigit():
            digits = ch + digits
        else:
            if digits:
                break
    return digits


def generate_pr_body() -> str:
    """Build the markdown PR body from harness-state files.

    Reads:
      - harness-state/config.json for project name and config metadata
      - harness-state/sprint-plan.json for sprint table rows
      - harness-state/sprints/sprint-NN/eval-report.json for per-sprint status
    """
    config_path = f"{HARNESS_STATE}/config.json"
    plan_path = f"{HARNESS_STATE}/sprint-plan.json"

    project_name = json_read(config_path, ".userPrompt")[:80]

    sprint_count_str = json_read(plan_path, ".sprints | length")
    sprint_count = 0
    if sprint_count_str:
        try:
            sprint_count = int(sprint_count_str)
        except ValueError:
            sprint_count = 0
    if sprint_count == 0:
        try:
            with open(plan_path, "r", encoding="utf-8") as fh:
                plan = json.load(fh)
            sprints_list = plan.get("sprints") if isinstance(plan, dict) else None
            if isinstance(sprints_list, list):
                sprint_count = len(sprints_list)
        except (OSError, ValueError):
            sprint_count = 0

    rows: List[str] = []
    for i in range(1, sprint_count + 1):
        d = sprint_dir(i)
        name = json_read(plan_path, f".sprints[{i - 1}].name")
        status = "pending"
        criteria = "-"
        pass_count = "-"
        fail_count = "-"
        attempts = "-"

        eval_path = f"{d}/eval-report.json"
        if file_exists(eval_path):
            status = json_read(eval_path, ".overallResult") or "pending"
            pc = json_read(eval_path, ".passCount")
            fc = json_read(eval_path, ".failCount")
            try:
                criteria = str(int(pc) + int(fc))
            except (TypeError, ValueError):
                criteria = "-"
            pass_count = pc or "-"
            fail_count = fc or "-"
            attempts = json_read(eval_path, ".attempt") or "-"

        rows.append(
            f"| {sprint_pad(i)} | {name} | {status} | "
            f"{criteria} | {pass_count} | {fail_count} | {attempts} | - |"
        )

    sprint_rows_block = "\n".join(rows)

    model = json_read(config_path, ".model")
    context_strategy = json_read(config_path, ".contextStrategy")
    project_type = json_read(config_path, ".projectType")

    body = (
        f"## Harness: {project_name}\n"
        f"\n"
        f"### Sprint Results\n"
        f"\n"
        f"| Sprint | Name | Status | Criteria | Pass | Fail | Attempts | Cost |\n"
        f"|--------|------|--------|----------|------|------|----------|------|\n"
        f"{sprint_rows_block}\n"
        f"\n"
        f"### Configuration\n"
        f"- Model: {model}\n"
        f"- Context strategy: {context_strategy}\n"
        f"- Project type: {project_type}\n"
        f"\n"
        f"---\n"
        f"Built with the [Planner-Generator-Evaluator Harness]"
        f"(https://www.anthropic.com/engineering/harness-design-long-running-apps)\n"
    )
    return body
