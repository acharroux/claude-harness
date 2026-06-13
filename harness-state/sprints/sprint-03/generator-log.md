# Sprint 03 Generator Log

## Summary

Ported `harness/lib/git.sh` to `harness/lib/git.py` (subprocess-based, stdlib only)
and `tests/layer1/test-git.bats` to `tests/layer1/test_git.py` (unittest with
HarnessTestCase, isolated temp git repos).

## Files Created

- `harness/lib/git.py` -- 9 public functions: `create_harness_branch`,
  `create_sprint_branch`, `merge_sprint`, `fail_sprint_attempt`,
  `commit_harness_state`, `create_pr`, `create_fix_pr`, `create_issue`,
  `generate_pr_body`. All use `subprocess.run` for git/gh invocations. Imports
  are stdlib-only (`json`, `os`, `shutil`, `subprocess`, `pathlib`, `typing`)
  plus the local `harness.lib.utils`.

- `tests/layer1/test_git.py` -- 19 test methods across 7 TestCase classes,
  each subclassing `HarnessTestCase` and using `init_test_repo()` for
  isolation. Covers all 13 bats scenarios plus extra coverage for two-digit
  padding (sprint 9) and graceful degradation when no `gh` / no `origin`.

## Naming Parity (Bash <-> Python)

All naming preserved byte-for-byte from the bash reference:

| Concept              | Format                                   |
|----------------------|------------------------------------------|
| Harness branch       | `harness/<slug>`                         |
| Sprint branch        | `<harness_branch>-sprint-NN`             |
| Pass tag             | `harness/sprint-NN/pass`                 |
| Fail tag             | `harness/sprint-NN/attempt-K`            |
| Merge commit message | `harness(sprint-NN): merge (PASS, attempt K)` |
| Evaluator artifacts  | `harness(sprint-NN): evaluator artifacts` |

## Behavior Notes

- `create_harness_branch` resolves the base via
  `git symbolic-ref refs/remotes/origin/HEAD`, falling back to current branch
  then `main`, mirroring the bash logic. Idempotent: re-checks-out an existing
  branch when `git checkout -b` fails.

- `merge_sprint` first commits any uncommitted artifacts on the sprint branch
  (`git add -A` + `git diff --cached --quiet || git commit`), then performs
  `git merge --no-ff` with the canonical PASS message, tags, and deletes the
  sprint branch.

- `fail_sprint_attempt` matches the bash sequence:
  `git stash -q`, `git checkout`, `git stash drop -q`, `git branch -D`. Each
  stash invocation is run with `check=False` so an empty-stash state on
  Windows does not break the flow.

- `commit_harness_state` runs `git add` (untracked) and `git add -u`
  (modifications/deletions) on `harness-state/`, then commits only when the
  staged set is non-empty -- no empty-commit footgun.

- `create_pr` / `create_fix_pr` / `create_issue` short-circuit with a
  `log_warn` when `shutil.which('gh')` returns None or `git remote get-url
  origin` fails. `create_issue` returns `""` on any short-circuit or non-zero
  `gh issue create`.

- `generate_pr_body` reads `config.json`, `sprint-plan.json`, and per-sprint
  `eval-report.json` (via `json_read`) and renders the Markdown sprint-table
  block. Uses `int()` summation for the criteria column instead of jq's
  `.passCount + .failCount`.

## Test Coverage

Bats scenario -> Python test mapping:

| bats @test                                     | python test_method                          |
|------------------------------------------------|---------------------------------------------|
| create_harness_branch: creates branch          | TestCreateHarnessBranch.test_creates_branch |
| create_harness_branch: idempotent              | TestCreateHarnessBranch.test_idempotent     |
| create_sprint_branch: creates sprint branch    | TestCreateSprintBranch.test_creates_sprint_branch |
| create_sprint_branch: cleans up existing       | TestCreateSprintBranch.test_cleans_up_existing_branch |
| merge_sprint: creates merge commit             | TestMergeSprint.test_creates_merge_commit   |
| merge_sprint: creates tag                      | TestMergeSprint.test_creates_tag            |
| merge_sprint: deletes sprint branch            | TestMergeSprint.test_deletes_sprint_branch  |
| fail_sprint_attempt: tags the attempt          | TestFailSprintAttempt.test_tags_the_attempt |
| fail_sprint_attempt: deletes sprint branch     | TestFailSprintAttempt.test_deletes_sprint_branch |
| fail_sprint_attempt: returns to harness branch | TestFailSprintAttempt.test_returns_to_harness_branch |
| commit_harness_state: commits changes          | TestCommitHarnessState.test_commits_changes |
| commit_harness_state: no-op when clean         | TestCommitHarnessState.test_noop_when_clean |
| generate_pr_body: contains sprint table        | TestGeneratePrBody.test_contains_sprint_table |

Plus: `test_sprint_number_zero_padded_two_digits`,
`test_padding_in_tag_for_single_digit_sprint`,
`test_handles_dirty_working_tree`, and three graceful-degradation tests for
`create_pr`, `create_fix_pr`, `create_issue`.

## Test Results

```
$ python -m unittest tests.layer1.test_git
...................
Ran 19 tests in 22.8s -- OK

$ python -m unittest tests.layer1.test_utils tests.layer1.test_invoke
..........................................................
Ran 58 tests in 1.2s -- OK   (regression Sprints 1+2 unaffected)

$ python tests/run-all.py layer1
Ran 77 tests in 23.7s -- OK
```

## Constraints Verified

- No `.sh` / `.ps1` modifications: `git diff harness/sprint-02/pass --
  '*.sh' '*.ps1'` is empty.
- `git.py` imports: `__future__`, `json`, `os`, `shutil`, `subprocess`,
  `pathlib.Path`, `typing.List`, `typing.Optional`, plus `harness.lib.utils`
  symbols. No third-party packages.

## Criteria Coverage

C3-01 through C3-23: all addressed; see `test_git.py` for the per-criterion
assertions and `git.py` for the implementation.
