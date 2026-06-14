# Bugs Found in the Python Test System

Historical record of all bugs discovered while debugging `tests/layer2/smoke-test.py` and
`tests/layer3/meta-test.py` after the Python rewrite. Listed in discovery order.

---

## 1. Spurious `print()` in planner.py (bash-ism)

**File:** `harness/lib/planner.py`  
**Description:** `invoke_planner()` ended with `print(sprint_count)` — a leftover from the
bash port where the caller captured stdout to get the sprint count. In Python the return value
is used directly, so the print polluted the test output with a stray `4`.  
**Fix:** Removed `print(sprint_count)`.

---

## 2. Dirty working tree on `git merge` in `merge_sprint()`

**File:** `harness/lib/git.py` — `merge_sprint()`  
**Description:** After committing evaluator artifacts on the sprint branch and checking out the
harness branch, leftover untracked/modified files on the harness branch made the working tree
dirty. `git merge --no-ff` then failed with exit code 2.  
**Fix:** Added a second `git add -A` + conditional commit after `git checkout harness_branch`
to clean the harness branch before merging.

---

## 3. Swallowed git stderr on failure

**File:** `harness/lib/git.py` — `_run()`  
**Description:** `subprocess.run()` captured stderr but never surfaced it when the command
failed. Errors like "Your local changes would be overwritten by checkout" were invisible,
making debugging extremely difficult.  
**Fix:** Before raising `CalledProcessError`, log stderr to `sys.stderr`.

---

## 4. Windows pipe buffer deadlock (timeout)

**Files:** `tests/layer2/smoke-test.py`, `tests/layer3/meta-test.py`  
**Description:** `subprocess.run(..., stdout=subprocess.PIPE)` on a long-running process fills
the OS pipe buffer (~64 KB). The child blocks trying to write; the parent blocks waiting for
the process to finish → Python's `timeout=` fires.  
**Fix:** Write output directly to an open file handle (`stdout=log_fh, stderr=log_fh`). No
pipe buffer, no deadlock.

---

## 5. `%TMP%` not executable on enterprise Windows

**Files:** `tests/layer2/smoke-test.py`, `tests/layer3/meta-test.py`  
**Description:** `tempfile.mkdtemp()` creates directories under `%TMP%` (`C:\Users\...\AppData\Local\Temp`).
On enterprise laptops with security policies, executables (`.exe`, `.cmd`) in `%TMP%` are blocked.
The generated project's `hello.exe` was installed to a user Scripts directory instead.  
**Fix:** Use `tests/tmp/smoke-<timestamp>/` and `tests/tmp/meta-<timestamp>/` under the project
root, which is not subject to the restriction. Added `tests/tmp/smoke-*/` and `tests/tmp/meta-*/`
to `.gitignore`.

---

## 6. `pip install` leaking into active Python environment

**Files:** `tests/layer2/smoke-test.py`, `tests/layer3/meta-test.py`  
**Description:** The generated project ran `pip install -e .` which installed into whatever
Python environment was currently active (e.g. a user Scripts directory). This pollutes the
global environment and violates test isolation.  
**Fix:** Create a `.venv` inside the test directory before running the orchestrator. Set
`VIRTUAL_ENV` and prepend the venv's `Scripts/` to `PATH` in the subprocess environment.

---

## 7. Mock claude leaking into layer3 real-Claude runs

**File:** `tests/layer3/meta-test.py`  
**Description:** Layer1 tests set `MOCK_CLAUDE_FIXTURE_DIR`, `MOCK_CLAUDE_SCENARIO` etc. and
add `tests/helpers/` to `PATH`. When layer3 ran next (in the same process via `run-all.py`),
those values were still in `os.environ`, causing the copied harness to use the mock instead of
real Claude. Sprints "passed" instantly using fixture files, but no real code was generated.  
**Fix:** Explicitly pop all `MOCK_CLAUDE_*` env vars and strip any `tests/helpers` entries from
`PATH` in the environment dict passed to the meta-test subprocess.

---

## 8. `copytree` infinite recursion — `tests/tmp/` inside project

**File:** `tests/layer3/meta-test.py`  
**Description:** `tests/tmp/` is inside `PROJECT_DIR`. When `shutil.copytree(PROJECT_DIR, dest)`
ran, it tried to copy `tests/tmp/` into itself, recursing until hitting Python's recursion limit.  
**Fix:** Custom ignore function that resolves both the source and each child to absolute paths
and excludes any child whose resolved path starts with `tests/tmp/`'s resolved path.

---

## 9. `dest` pre-created before `copytree`

**File:** `tests/layer3/meta-test.py`  
**Description:** `dest.mkdir(parents=True)` was called before `shutil.copytree(src, dest)`.
`copytree` requires the destination to not exist; it creates it itself. Result: `FileExistsError`.  
**Fix:** Remove `dest.mkdir()` — let `copytree` create `dest`.

---

## 10. Log file inside git repo making working tree dirty

**File:** `tests/layer3/meta-test.py`  
**Description:** `meta-output.log` was written inside `dest` (the cloned git repo). The log
file was continuously written during the harness run. Even after being committed on a sprint
branch, new writes made it dirty again, causing `git checkout harness_branch` to fail with
"Your local changes would be overwritten".  
**Fix:** Write `meta-output.log` to `dest.parent/` (one level up, outside the git repo).

---

## 11. `HARNESS_SMOKE/META_TEST` env var not inherited by subprocess on Windows cmd

**Files:** `tests/layer2/smoke-test.py`, `tests/layer3/meta-test.py`, `tests/run-all.py`  
**Description:** `set HARNESS_META_TEST=1 && python tests/run-all.py layer3` — on Windows cmd
the `&&` form does not reliably export the variable into the Python subprocess. The guard check
inside the bash script never saw it.  
**Fix:** Move the guard check into `run-all.py` itself (Python sees the env var correctly from
cmd `set`). The Python guard runs before any subprocess is spawned.

---

## 12. POSIX path mangling on Windows when calling bash

**File:** `tests/run-all.py`  
**Description:** Passing a Windows absolute path (`C:\SAPDevelop\...`) to Git Bash caused
"No such file or directory" because bash interpreted the backslashes and drive letter incorrectly.  
**Fix:** Use `script.relative_to(REPO_ROOT).as_posix()` to pass a relative forward-slash path,
with `cwd=REPO_ROOT` so bash resolves it correctly.

---

## 13. Hooks requiring `jq` (not available on Windows)

**Files:** `harness/hooks/on-generator-stop.sh`, `on-evaluator-stop.sh`, `on-stop.sh`  
**Description:** All three bash hooks used `jq` to parse JSON from status/eval files. `jq` is
not installed on Windows by default, causing exit code 127 ("command not found") for all hook tests.  
**Fix:** Rewrote all three hooks as Python scripts (`*.py`) using Python's built-in `json` module.
Updated `settings.json` to point to the `.py` hooks. Updated `test_hooks.py` to drive the Python
hooks directly (no bash or jq required).
