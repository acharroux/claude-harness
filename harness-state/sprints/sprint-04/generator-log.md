# Sprint 4 Generator Log: Phase Modules

## What was built

Sprint 4 implements the four phase modules as Python ports of their bash counterparts.

### harness/lib/planner.py
- `invoke_planner(mode="new"|"extend")` — calls invoke_claude with planner agent
- Verifies product-spec.md and sprint-plan.json are produced
- Checks for design-spec.md on web-frontend projects
- Returns sprint count

### harness/lib/contract.py
- `negotiate_contract(sprint_num)` — up to MAX_CONTRACT_ROUNDS rounds
- `parse_decision(data)` — tolerates .decision / .reviewVerdict / .verdict
- `is_accepted(data)` — accepted/accept/approved/approve (case-insensitive)
- `count_criteria(data)` — .criteria / .features[].acceptanceCriteria / .acceptanceCriteria / 0
- Max-rounds fallback: accepts latest proposal

### harness/lib/generator.py
- `invoke_generator(sprint_num, attempt=1)` — calls invoke_claude with generator agent
- Returns 0 (success), 1 (failure), 2 (blocked — load-bearing exit code)
- Retry-aware prompt when attempt > 1 and eval-report exists
- Design-spec injection when design-spec.md present

### harness/lib/evaluator.py
- `invoke_evaluator(sprint_num, attempt=1)` — returns True (PASS) or False (FAIL)
- `invoke_regression()` — runs regression, returns True if all pass
- Result tolerance: overallResult / result / verdict (case-insensitive pass/passed)
- Count tolerance: passCount / pass_count / score.passedCriteria / score.passed
- MCP config for web-frontend projects

### Test files
- tests/layer1/test_planner.py — 5 tests (port of test-planner.bats)
- tests/layer1/test_contract.py — 13 tests (port of test-contract.bats + tolerance unit tests)
- tests/layer1/test_generator.py — 5 tests (port of test-generator.bats, includes blocked=2)
- tests/layer1/test_evaluator.py — 13 tests (port of test-evaluator.bats + tolerance unit tests)

## Test results
`python tests/run-all.py layer1` — 117 tests OK
