# Audit: Python Orchestration Scripts vs. Known Bug Patterns

Cross-check of `harness/orchestrate.py` and `harness/lib/*.py` against the 13 bug patterns
documented in `found-in-tests-system.md`.

---

## Status per pattern

| # | Pattern | Status in orchestration code |
|---|---------|------------------------------|
| 1 | Spurious `print()` (bash-ism) | ✅ Fixed — removed from `planner.py` |
| 2 | Dirty working tree on `git merge` | ⚠️ **BUG** — see below (`run_refactor`) |
| 3 | Swallowed git stderr | ✅ Fixed — `git.py _run()` logs stderr before raising |
| 4 | Pipe buffer deadlock | ✅ Not applicable — `invoke.py` uses `Popen` + line streaming, never `subprocess.run(stdout=PIPE)` for long output |
| 5 | `%TMP%` not executable | ✅ Not applicable — orchestration never calls `tempfile.mkdtemp()` |
| 6 | `pip install` leaking to active env | ✅ Not applicable — orchestration doesn't install packages |
| 7 | Mock claude leaking into real runs | ✅ Not applicable — orchestration only runs from CLI, never inside a test process |
| 8 | `copytree` infinite recursion | ✅ Not applicable — orchestration doesn't copy the project tree |
| 9 | `dest` pre-created before `copytree` | ✅ Not applicable |
| 10 | Log file inside git repo | ✅ Not applicable — orchestration writes harness-state/ which is gitignored |
| 11 | Env var not inherited on Windows cmd | ✅ Not applicable — orchestration reads its own args/env directly |
| 12 | POSIX path mangling passed to bash | ✅ Not applicable — orchestration calls git/gh directly via subprocess, not bash |
| 13 | Hooks requiring `jq` | ✅ Fixed — hooks rewritten in Python |

---

## Confirmed Bug

### B1 — Dirty working tree on `git merge` in `run_refactor()`

**File:** `harness/orchestrate.py` lines 625–631  
**Pattern:** Same as bug #2 from tests  
**Description:** `run_refactor()` does the same sequence that was broken in `merge_sprint()`:
```python
subprocess.run(["git", "checkout", harness_branch], ...)   # line 625
subprocess.run(["git", "merge", "--no-ff", sprint_branch, ...], ...)  # line 628
```
There is no `git add -A` + commit between the checkout and the merge. If the evaluator or
regression left any untracked or modified files on the harness branch, the merge will fail
with exit code 2 — silently, because `check=False` is used.

Additionally the merge failure is silent: `check=False` means no exception is raised and no
error is logged. The code falls through to `utils.log_error("Refactor failed regression")`,
which is misleading — the refactor may have succeeded but the merge failed for unrelated reasons.

**Fix:**
```python
# After checkout, clean the working tree before merging
subprocess.run(["git", "add", "-A"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
result = subprocess.run(["git", "diff", "--cached", "--quiet"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
if result.returncode != 0:
    subprocess.run(["git", "commit", "-q", "-m",
                    "harness(refactor): harness branch cleanup before merge"],
                   check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
# Then merge, with check=True and stderr logging
merge_result = subprocess.run(
    ["git", "merge", "--no-ff", sprint_branch, "-m", "harness(refactor): merge (PASS, full regression)"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
)
if merge_result.returncode != 0:
    utils.log_error(f"git merge failed: {merge_result.stderr.decode(errors='replace').strip()}")
    return 1
```

---

## Hardening Opportunities (not bugs, but worth fixing)

### H1 — `run_fix()` fix branch name uses `/` separator (not `-`)

**File:** `harness/orchestrate.py` line 531  
**Description:**
```python
sprint_branch = f"{harness_branch}/{fix_id}"
```
The bash reference uses `/` here too, but all other sprint branches use `-` as separator
(`{harness_branch}-sprint-NN`). This inconsistency is a minor naming issue, not a bug.
No fix needed unless you want consistent naming.

### H2 — `run_fix()` and `run_refactor()` bypass `git_mod.merge_sprint()`

**File:** `harness/orchestrate.py` lines 531–635  
**Description:** Instead of calling the hardened `git_mod.merge_sprint()` (which handles dirty
tree, logs stderr, tags, deletes branch), fix and refactor modes do their own raw
`subprocess.run(["git", "merge", ...])` calls. This means they miss all the protections added
to `merge_sprint()`. Centralising on `git_mod.merge_sprint()` would prevent divergence.

### H3 — `run_fix()` fix branch name doesn't match tag naming convention

**File:** `harness/orchestrate.py` line 549  
**Description:** The pass tag is `harness/{fix_id}/pass` and the branch is
`{harness_branch}/{fix_id}`. These are consistent with the bash reference but differ from the
sprint convention. Not a bug — just worth noting for documentation.

### H4 — No stderr logging for raw `subprocess.run` calls in `orchestrate.py`

**File:** `harness/orchestrate.py` — multiple git calls in `run_fix()`, `run_refactor()`, `run_resume()`  
**Description:** These calls use `check=False` and capture stderr but never log it on failure.
If a git command fails silently the harness may continue in a broken state.  
**Recommendation:** Use `git_mod._run()` (which logs stderr) or at minimum check returncode
and log stderr for any git operation that changes branch state.
