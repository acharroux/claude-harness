# Python Code Cleaning Analysis

Static analysis of all Python scripts. No changes made — findings only.
Severity: **High** (correctness risk / major readability) | **Medium** (notable cleanup) | **Low** (minor style).
Line-length limit: 88 chars (Black standard).

---

## harness/orchestrate.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 26 | Type annotation | Medium | `from typing import List, Optional` — `List` is deprecated in 3.9+; `list` builtin is preferred | Remove `List` from import; use `list[str]` where needed |
| 196–219 | Dead code | Low | `_git_checkout` and `_git_checkout_new` helpers defined but only called once each — definition is fine but internal `from harness.lib import ...` duplicated in both bodies | Hoist the lazy imports to module level or accept the duplication |
| 355–356 | Routing through `subprocess.run` | Low | `git tag harness/plan` still calls `subprocess.run` directly instead of `git_mod._run()` | Use `git_mod._run(["git", "tag", "harness/plan"], check=False, capture=True)` |
| 374–388 | Swallowed exception | Medium | `except FileNotFoundError: utils.log_warn(...)` then continues — if claude is missing, README generation is silently skipped with a warn but the harness reports "All sprints passed!" | At minimum log clearly that README was not generated |
| 446 | Variable scope | High | `harness_branch` read at line 448 but may be `""` (empty string) if `json_read` returns nothing; the `if harness_branch:` guard means checkout is skipped but code continues using empty `harness_branch` string | Guard: `if not harness_branch: utils.log_error(...); return 1` |
| 479–483 | Exception swallowing | High | `except Exception: utils.log_warn(...)` on sprint runs in `run_extend` loses the traceback entirely | Use `utils.log_warn(f"Sprint {sprint_num} failed: {exc}")` to surface the cause |
| 656–680 | Duplicated sprint-count logic | Medium | `run_resume` re-implements sprint-plan loading (lines 663–680) that duplicates logic elsewhere | Extract `_total_sprints()` helper using `json_read` |
| Throughout | Import style | Low | `from typing import List, Optional` — `Optional` is fine for 3.8 compat, but mixing with `X \| None` style elsewhere is inconsistent | Decide on one style throughout; `Optional[X]` is clearest for 3.8 targets |

---

## harness/lib/utils.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 37–44 | Bare exception | Low | `_use_color()` catches all exceptions with `pass` — any import/attribute error is silently hidden | At minimum: `except Exception: return False` with a comment |
| 115 | Dead guard | Low | `if s is None: return ""` in `slugify` — parameter typed `str`, callers never pass None | Remove the None guard or annotate as `Optional[str]` |
| 133–178 | Complex regex parsing | Medium | `_walk_field` uses manual tokenizer with regex + position tracking; fragile and hard to follow | Pre-compile regexes as module constants; add a comment explaining the grammar being parsed |
| 204 | Inconsistent empty-value | Medium | `json_read` returns `""` for missing keys but comments say it tolerates `"null"` — these are different | Return `""` consistently and document; update tolerances in callers if needed |
| 270–288 | Nested try/except | Medium | `log_cost` has three levels of nesting to parse tokens; hard to follow | Extract `_parse_tokens(output_json)` returning `(input_tokens, output_tokens)` |
| 278–279 | Redundant initialization | Low | `input_tokens = 0; output_tokens = 0` set unconditionally then conditionally overwritten | Remove; let inner `try` block assign or default |
| 323 | Unused read | Low | `json_read(...)` result not used in `check_cost_cap` | Remove the call or assign to variable with explanation |
| 411 | JSON round-trip deep copy | Low | `json.loads(json.dumps(_DEFAULT_HANDOFF))` to deep-copy a dict | Use `import copy; copy.deepcopy(_DEFAULT_HANDOFF)` |
| 435–439 | Manual deduplication | Low | Loop to deduplicate `completedSprints` while preserving order | Replace with `list(dict.fromkeys(completed))` |

---

## harness/lib/invoke.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 22 | Unused import | Low | `from pathlib import Path` — `Path` not referenced anywhere in the file | Remove |
| 39 | Type annotation | Low | `List[str]` → use `list[str]` (Python 3.9+) | Change import and usage |
| 92–96 | Redundant isinstance check | Low | `isinstance(content, list)` checked, then immediately iterated — the check is correct but can be merged with the loop | `for block in (content if isinstance(content, list) else []):` |
| 130–132 | Bare `except Exception` | High | `_stream_stdout` swallows all errors silently via `pass` | Replace `pass` with `sys.stderr.write(f"[harness] stream error: {exc}\n")` |
| 180–184 | Defensive close | Low | `try: proc.stdout.close() except Exception: pass` — `close()` on a pipe rarely raises | Remove try/except; or narrow to `OSError` if truly needed |

---

## harness/lib/git.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 55–60 | Redundant `errors=` | Low | `errors="replace"` passed when `text=True` already defaults to `errors="replace"` in subprocess | Remove `errors="replace" if text else None` |
| 133 | Missing type hint | Low | `sprint_num` parameter has no type hint | `sprint_num: int` |
| 156 | Missing type hints | Low | `sprint_num` and `attempt` have no type hints | `sprint_num: int, attempt: int` |
| 167 + 170 | Redundant computation | Low | `sprint_pad(sprint_num)` called at line 167 (result stored) then called again at line 170 | Reuse the stored result |
| 310–311 | Line length | High | `gh pr create` call with all arguments inline exceeds 88 chars significantly | Break into multi-line list with one argument per line |
| 432–440 | Manual string parsing | Low | Extracts trailing number from a GitHub URL by iterating characters backwards | Replace with `re.search(r'/(\d+)$', url)` |

---

## harness/lib/planner.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 32–44 | Long string constants | Low | `_NEW_PROMPT` and `_EXTEND_PROMPT` are hard to read inline | No change required — they are clear enough as module constants |
| 47 | Missing return type | Low | `invoke_planner` missing `-> int` return type annotation | Add `-> int` |

---

## harness/lib/contract.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 39 | Inefficient membership test | Low | `_ACCEPT_VALUES` is a tuple; `in` on a tuple is O(n) vs O(1) for a set | `_ACCEPT_VALUES = frozenset(("accepted", "accept", "approved", "approve"))` |
| 52 | Missing return type | Low | `parse_decision` missing `-> str` | Add `-> str` |
| 67 | Missing return type | Low | `is_accepted` missing `-> bool` | Add `-> bool` |
| 72 | Missing return type | Low | `count_criteria` missing `-> int` | Add `-> int` |
| 108 | Missing return type | Low | `negotiate_contract` missing `-> bool` | Add `-> bool` |
| 117 | Unnecessary conversion | Low | `sprint_num_int = int(sprint_num)` — parameter should just be `sprint_num: int` | Type param as `int`, remove conversion |
| 144–149 | Long prompt string | Low | Generator prompt built with `+` concatenation across lines | Use implicit line continuation inside parens |

---

## harness/lib/generator.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 38 | Missing type hints | Low | `_build_prompt` parameters `eval_report_present: bool` typed but `sprint_num: int` not | Add `sprint_num: int` |
| 68 | `Any` type | Medium | `sprint_num: Any` should be `int` | Change to `sprint_num: int` and remove `int()` cast at line 79 |
| 79 | Redundant conversion | Low | `attempt = int(attempt)` when already typed as `int = 1` | Remove |

---

## harness/lib/evaluator.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 45 | Missing return type | Low | `_get_result` missing `-> str` | Add `-> str` |
| 55 | Missing return type | Low | `_get_count` missing `-> int` | Add `-> int` |
| 106, 168 | Style inconsistency | Low | `mcp_config: str \| None` uses PEP 604 union; rest of codebase uses `Optional[str]` | Use `Optional[str]` for consistency |
| 182–183 | Redundant fallback | Low | `int(data.get("pass", 0) or 0)` — the `or 0` is redundant when `.get` already defaults to `0` | `int(data.get("pass") or 0)` |

---

## harness/hooks/on-generator-stop.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 18 | Style inconsistency | Low | `Path \| None` should be `Optional[Path]` for consistency | Use `Optional[Path]` |
| 26–51 | Nested loops with break | Medium | Two nested loops + break to find active sprint; repeated in on-evaluator-stop.py | Extract `_find_active_sprint(patterns, harness_state)` shared helper (inside each file — cannot move between files) |
| 75–77 | Long condition | High | Commit message check `if "harness" in recent or "C0" in recent or "C1" in recent ...` is very long | Use `_HARNESS_PATTERNS = ("harness", "C0", "C1", ...) ` and `any(p in recent for p in _HARNESS_PATTERNS)` |

---

## harness/hooks/on-evaluator-stop.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 15 | Return type | Low | `_read_json` `-> dict` but can return `{}` on error — ambiguous | `-> dict` is fine; add a comment: `# returns {} on any error` |
| 22 | Missing return type | Low | `_read_status` missing `-> str` | Add `-> str` |
| 26–44 | Duplicated loop | Medium | Sprint-finding loop duplicates the one in on-generator-stop.py | Extract `_find_sprint_by_status(target_status, harness_state)` within this file |
| 54 | Style inconsistency | Low | `Path \| None` → `Optional[Path]` | Use `Optional[Path]` |
| 89–92 | Verbose None check | Medium | `if not (report.get("criteriaResults") is not None or ...)` is confusing | `if not any(report.get(k) is not None for k in ("criteriaResults", "features", "score", "results")):` |

---

## harness/hooks/on-stop.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 15 | Missing return type | Low | `_read_status` missing `-> str` | Add `-> str` |
| 34 | Defensive check | Low | `if not d.is_dir(): continue` inside `glob("sprint-*")` which only matches dirs | Add comment: `# glob may match symlinks on some systems` or remove check |

---

## tests/run-all.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 75 | Type annotation | Low | `argv: list` → `argv: list[str]` | Change |
| 20–21 | Unused variable | Low | `TESTS_DIR` defined but only used in `run_layer1`; could be local | Keep as module constant — it makes the paths clear |

---

## tests/helpers/test_helper.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 82 | Local function | Low | `_run` defined inside `init_test_repo` on each call | Move to class-level helper method |
| 92–103 | Repeated fallback | Medium | `git init -b main` with fallback for older git reproduced in multiple test files; only defined here once which is fine | Add `# older git fallback` comment to explain the try/except |

---

## tests/helpers/mock_claude.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 48 | Hardcoded devnull | Low | `"NUL"` hardcoded for Windows null device | Use `os.devnull` |
| 79 | Platform inconsistency | Low | `STATE_DIR` defaults to `/tmp/...` on Unix but `tempfile.gettempdir()` on Windows | Always use `Path(tempfile.gettempdir())` |
| 248 | Bare except | Medium | `except Exception as exc:` with no logging | Add `sys.stderr.write(f"mock-claude: routing error: {exc}\n")` |

---

## tests/layer1/test_utils.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| Throughout | Over-isolation | Low | Many test classes use `HarnessTestCase` isolation (tempdir + git) for pure function tests that never touch the filesystem | Pure function tests (slugify, sprint_pad, etc.) could use plain `unittest.TestCase` |

---

## tests/layer1/test_invoke.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 312–320 | Duplicated setup | Low | `_path_with_helpers` method resets PATH manually on each test — this is in `setUp` territory | Move to `setUp` or make it a contextmanager |

---

## tests/layer1/test_git.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 27–52 | Module-level helpers | Low | `_run_git`, `_current_branch`, `_branch_exists`, `_tags` defined at module level; pattern is readable and fine | No change needed |

---

## tests/layer1/test_planner.py, test_contract.py, test_generator.py, test_evaluator.py

| Category | Severity | Description | Suggestion |
|----------|----------|-------------|------------|
| Module reload pattern | Medium | All four files reload the module under test inside a helper method on every call: `importlib.reload(mod)`. This is needed to reset module-level state that caches the mock PATH, but it is fragile and slow. | Prefer `unittest.mock.patch("harness.lib.invoke.invoke_claude", ...)` to mock at the boundary instead of reloading the whole module |

---

## tests/layer1/test_hooks.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 51 | Missing type hint | Low | `_write` method: `content` has no type annotation (accepts `str` or `dict`) | `content: str \| dict` |
| 35 | Platform check | Low | `sys.executable or "python"` — `sys.executable` is never None at runtime; the `or` branch is dead code | Remove `or "python"` |

---

## tests/layer1/test_pipeline.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 38 | Magic number | Low | `timeout=120` hardcoded | `PIPELINE_TIMEOUT = 120` at module level |

---

## tests/layer2/smoke-test.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 88–91 | Brittle PATH filtering | High | String matching `"tests" not in p.lower() and "helpers" not in p.lower()` would strip any PATH entry containing the word "tests" (e.g. a system path like `/usr/lib/python-tests/`) | Use `Path(p).resolve()` and compare against known absolute paths |
| 109–114 | Complex nested any() | Medium | Two-pass `any()` to check eval reports reads each file twice | Read once into variable, check once |

---

## tests/layer3/meta-test.py

| Line(s) | Category | Severity | Description | Suggestion |
|---------|----------|----------|-------------|------------|
| 65–78 | Complex closure | Medium | `_ignore` closure inside `main()` does path resolution on every call from copytree | Move to module-level `_make_copy_ignore(tmp_base)` factory function |
| 110–114 | Brittle PATH filtering | High | Same issue as smoke-test.py — string matching on PATH entries | Use `Path(p).resolve()` comparison against known absolute paths |
| 127–136 | Long inline string | Low | Prompt string is 9 lines inline — hard to edit | Move to module-level `_META_PROMPT` constant |

---

## Cross-cutting patterns

| Category | Severity | Files affected | Description |
|----------|----------|----------------|-------------|
| `Optional` vs `X \| None` | Low | evaluator.py, hooks/*.py | PEP 604 union syntax used inconsistently; pick one style (suggest `Optional` for 3.8 compat) |
| `List` vs `list` | Low | orchestrate.py, invoke.py | `typing.List` vs builtin `list[X]`; prefer builtin for 3.9+ |
| Missing return type annotations | Low | planner.py, contract.py, generator.py, evaluator.py, hooks | Most public functions lack `->` return types |
| `importlib.reload` in tests | Medium | test_planner.py, test_contract.py, test_generator.py, test_evaluator.py | Fragile and slow; prefer `unittest.mock.patch` at the boundary |
