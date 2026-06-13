"""Unit tests for harness/lib/invoke.py and tests/helpers/mock_claude.py.

Layer-1 tests run with stdlib unittest. They cover:
  - argv construction (basic, with HARNESS_ROOT settings, with mcp_config)
  - claude-not-found behavior
  - exit-code propagation
  - NDJSON streaming including malformed lines
  - tool_use progress decorations to stderr
  - cost line decorations to stderr
  - PATH shim resolution (claude.cmd / mock_claude.py)
  - mock_claude end-to-end through subprocess
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make project root importable
_HERE = Path(__file__).resolve().parent
PROJECT_ROOT = _HERE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.helpers.test_helper import HarnessTestCase, FIXTURE_DIR  # noqa: E402

from harness.lib import invoke as invoke_mod  # noqa: E402


HELPERS_DIR = PROJECT_ROOT / "tests" / "helpers"
MOCK_CLAUDE_PY = HELPERS_DIR / "mock_claude.py"


# ---------------------------------------------------------------------------
# Fake subprocess plumbing
# ---------------------------------------------------------------------------

class _FakePopen:
    """Minimal stand-in for subprocess.Popen used to capture argv and supply
    a canned stdout stream + exit code."""

    captured_argv = None  # class-level capture for the most recent call

    def __init__(self, argv, *, stdout_lines=None, returncode=0,
                 stdout=None, stderr=None, bufsize=None,
                 text=None, encoding=None, errors=None):
        type(self).captured_argv = list(argv)
        self._returncode = returncode
        if stdout_lines is None:
            stdout_lines = []
        self.stdout = io.StringIO("\n".join(stdout_lines) + ("\n" if stdout_lines else ""))

    def wait(self):
        return self._returncode


def _make_popen_factory(stdout_lines=None, returncode=0):
    def factory(argv, **kwargs):
        return _FakePopen(argv, stdout_lines=stdout_lines, returncode=returncode, **kwargs)
    return factory


# ---------------------------------------------------------------------------
# Tests for invoke.py
# ---------------------------------------------------------------------------

class TestInvokeArgv(HarnessTestCase):
    """C2-02, C2-03, C2-04: argv construction."""

    def setUp(self):
        super().setUp()
        # Pretend claude is on PATH at /fake/claude regardless of host
        self._which_patcher = mock.patch.object(
            invoke_mod.shutil, "which", return_value="/fake/claude"
        )
        self._which_patcher.start()
        # Ensure HARNESS_ROOT is unset unless a test sets it
        self._saved_root = os.environ.pop("HARNESS_ROOT", None)

    def tearDown(self):
        self._which_patcher.stop()
        if self._saved_root is not None:
            os.environ["HARNESS_ROOT"] = self._saved_root
        super().tearDown()

    def test_basic_argv(self):
        """argv contains every required flag (C2-02)."""
        with mock.patch.object(invoke_mod.subprocess, "Popen",
                               side_effect=_make_popen_factory()):
            rc = invoke_mod.invoke_claude(
                agent="planner", prompt="hello", max_turns=10
            )
        self.assertEqual(rc, 0)
        argv = _FakePopen.captured_argv
        self.assertIsNotNone(argv)
        # First element is the resolved binary path
        self.assertEqual(argv[0], "/fake/claude")
        # Required pairs
        self.assertEqual(argv[argv.index("-p") + 1], "hello")
        self.assertEqual(argv[argv.index("--agent") + 1], "planner")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "10")
        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", argv)
        # Each flag exactly once
        for flag in ("-p", "--agent", "--max-turns", "--output-format",
                     "--dangerously-skip-permissions", "--verbose"):
            self.assertEqual(argv.count(flag), 1, f"flag {flag} appears {argv.count(flag)} times")

    def test_argv_with_settings_present(self):
        """When HARNESS_ROOT/.claude/settings.json exists, --settings is added (C2-03a)."""
        root = tempfile.mkdtemp(prefix="harness-root-")
        try:
            settings_dir = Path(root) / ".claude"
            settings_dir.mkdir(parents=True)
            settings_path = settings_dir / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")

            os.environ["HARNESS_ROOT"] = root
            with mock.patch.object(invoke_mod.subprocess, "Popen",
                                   side_effect=_make_popen_factory()):
                invoke_mod.invoke_claude(agent="planner", prompt="x")
            argv = _FakePopen.captured_argv
            self.assertIn("--settings", argv)
            self.assertEqual(argv[argv.index("--settings") + 1], str(settings_path))
        finally:
            os.environ.pop("HARNESS_ROOT", None)
            shutil.rmtree(root, ignore_errors=True)

    def test_argv_without_settings(self):
        """When no settings file, --settings is absent (C2-03b)."""
        root = tempfile.mkdtemp(prefix="harness-root-")
        try:
            os.environ["HARNESS_ROOT"] = root
            with mock.patch.object(invoke_mod.subprocess, "Popen",
                                   side_effect=_make_popen_factory()):
                invoke_mod.invoke_claude(agent="planner", prompt="x")
            argv = _FakePopen.captured_argv
            self.assertNotIn("--settings", argv)
        finally:
            os.environ.pop("HARNESS_ROOT", None)
            shutil.rmtree(root, ignore_errors=True)

    def test_argv_with_mcp_config(self):
        """mcp_config -> --mcp-config in argv (C2-04a)."""
        with mock.patch.object(invoke_mod.subprocess, "Popen",
                               side_effect=_make_popen_factory()):
            invoke_mod.invoke_claude(
                agent="planner", prompt="x", mcp_config="/tmp/mcp.json"
            )
        argv = _FakePopen.captured_argv
        self.assertIn("--mcp-config", argv)
        self.assertEqual(argv[argv.index("--mcp-config") + 1], "/tmp/mcp.json")

    def test_argv_without_mcp_config(self):
        """mcp_config=None -> --mcp-config absent (C2-04b)."""
        with mock.patch.object(invoke_mod.subprocess, "Popen",
                               side_effect=_make_popen_factory()):
            invoke_mod.invoke_claude(agent="planner", prompt="x", mcp_config=None)
        argv = _FakePopen.captured_argv
        self.assertNotIn("--mcp-config", argv)


class TestInvokeBinaryResolution(HarnessTestCase):
    """C2-05: claude not found should raise a clear error."""

    def test_claude_not_on_path_raises(self):
        with mock.patch.object(invoke_mod.shutil, "which", return_value=None):
            with self.assertRaises(FileNotFoundError) as ctx:
                invoke_mod.invoke_claude(agent="planner", prompt="x")
            self.assertIn("claude", str(ctx.exception).lower())


class TestInvokeExitCode(HarnessTestCase):
    """C2-06: exit code propagation."""

    def setUp(self):
        super().setUp()
        self._which_patcher = mock.patch.object(
            invoke_mod.shutil, "which", return_value="/fake/claude"
        )
        self._which_patcher.start()

    def tearDown(self):
        self._which_patcher.stop()
        super().tearDown()

    def test_exit_zero(self):
        with mock.patch.object(invoke_mod.subprocess, "Popen",
                               side_effect=_make_popen_factory(returncode=0)):
            rc = invoke_mod.invoke_claude(agent="planner", prompt="x")
        self.assertEqual(rc, 0)

    def test_exit_nonzero(self):
        with mock.patch.object(invoke_mod.subprocess, "Popen",
                               side_effect=_make_popen_factory(returncode=7)):
            rc = invoke_mod.invoke_claude(agent="planner", prompt="x")
        self.assertEqual(rc, 7)


class TestInvokeStreaming(HarnessTestCase):
    """C2-07, C2-08, C2-09, C2-10: NDJSON streaming + progress display."""

    def setUp(self):
        super().setUp()
        self._which_patcher = mock.patch.object(
            invoke_mod.shutil, "which", return_value="/fake/claude"
        )
        self._which_patcher.start()

    def tearDown(self):
        self._which_patcher.stop()
        super().tearDown()

    def _run_with_lines(self, lines):
        """Invoke with fake stdout and capture stderr."""
        captured_stderr = io.StringIO()
        with mock.patch.object(invoke_mod.subprocess, "Popen",
                               side_effect=_make_popen_factory(stdout_lines=lines)):
            with mock.patch.object(sys, "stderr", captured_stderr):
                rc = invoke_mod.invoke_claude(agent="planner", prompt="x")
        return rc, captured_stderr.getvalue()

    def test_malformed_lines_are_skipped(self):
        """Malformed JSON lines do not raise (C2-07)."""
        lines = [
            '{"type":"system"}',
            'this is not json {{{',
            '{"type":"result","total_cost_usd":0.01}',
        ]
        rc, _ = self._run_with_lines(lines)
        self.assertEqual(rc, 0)

    def test_tool_use_progress_to_stderr(self):
        """tool_use blocks produce a stderr line with name + preview (C2-08)."""
        record = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": "ls"}},
                ],
            },
        }
        rc, err = self._run_with_lines([json.dumps(record)])
        self.assertEqual(rc, 0)
        self.assertIn("Bash", err)
        self.assertIn("ls", err)

    def test_cost_line_to_stderr(self):
        """result records with total_cost_usd produce a Cost: line (C2-09)."""
        record = {"type": "result", "total_cost_usd": 0.0123}
        rc, err = self._run_with_lines([json.dumps(record)])
        self.assertEqual(rc, 0)
        self.assertIn("Cost:", err)
        self.assertIn("0.0123", err)

    def test_progress_only_in_stderr_not_stdout(self):
        """Progress decorations confined to stderr (C2-10)."""
        record = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": "echo hi"}},
                ],
            },
        }
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with mock.patch.object(invoke_mod.subprocess, "Popen",
                               side_effect=_make_popen_factory(stdout_lines=[json.dumps(record)])):
            with mock.patch.object(sys, "stdout", captured_stdout):
                with mock.patch.object(sys, "stderr", captured_stderr):
                    rc = invoke_mod.invoke_claude(agent="planner", prompt="x")
        self.assertEqual(rc, 0)
        self.assertIn("Bash", captured_stderr.getvalue())
        self.assertNotIn("Bash", captured_stdout.getvalue())

    def test_file_path_preview(self):
        """tool_use input with file_path gets that as preview."""
        record = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Read",
                     "input": {"file_path": "/etc/hosts"}},
                ],
            },
        }
        rc, err = self._run_with_lines([json.dumps(record)])
        self.assertEqual(rc, 0)
        self.assertIn("Read", err)
        self.assertIn("/etc/hosts", err)


# ---------------------------------------------------------------------------
# Tests for the mock_claude.py PATH shim and end-to-end behavior
# ---------------------------------------------------------------------------

class TestMockClaudeShim(HarnessTestCase):
    """C2-11, C2-15, C2-16, C2-17: mock_claude.py runs as a script and as `claude`."""

    def _path_with_helpers(self):
        """Return an environment dict with tests/helpers prepended to PATH."""
        env = os.environ.copy()
        env["PATH"] = str(HELPERS_DIR) + os.pathsep + env.get("PATH", "")
        env["MOCK_CLAUDE_FIXTURE_DIR"] = str(FIXTURE_DIR)
        env["MOCK_CLAUDE_SCENARIO"] = "pass"
        env["MOCK_CLAUDE_LOG"] = self.mock_claude_log
        env["MOCK_CLAUDE_STATE_DIR"] = self.mock_claude_state_dir
        return env

    def test_mock_claude_py_exists_with_shebang(self):
        """C2-11: mock_claude.py exists and starts with a python shebang."""
        self.assertTrue(MOCK_CLAUDE_PY.is_file(), f"missing: {MOCK_CLAUDE_PY}")
        first = MOCK_CLAUDE_PY.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(first.startswith("#!"), f"no shebang: {first!r}")
        self.assertIn("python", first.lower())

    def test_mock_claude_errors_without_fixture_dir(self):
        """C2-11: missing MOCK_CLAUDE_FIXTURE_DIR yields non-zero exit."""
        env = os.environ.copy()
        env.pop("MOCK_CLAUDE_FIXTURE_DIR", None)
        proc = subprocess.run(
            [sys.executable, str(MOCK_CLAUDE_PY), "--agent", "planner", "-p", "x"],
            env=env, cwd=self.test_temp_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_mock_claude_planner_routing(self):
        """C2-12: planner copies product-spec + sprint-plan fixtures."""
        env = self._path_with_helpers()
        proc = subprocess.run(
            [sys.executable, str(MOCK_CLAUDE_PY), "--agent", "planner",
             "-p", "Build a thing"],
            env=env, cwd=self.test_temp_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        spec = Path(self.test_temp_dir) / "harness-state" / "product-spec.md"
        plan = Path(self.test_temp_dir) / "harness-state" / "sprint-plan.json"
        self.assertTrue(spec.is_file())
        self.assertTrue(plan.is_file())
        # Bytes match fixtures
        self.assertEqual(
            spec.read_bytes(),
            (FIXTURE_DIR / "product-spec-minimal.md").read_bytes(),
        )
        self.assertEqual(
            plan.read_bytes(),
            (FIXTURE_DIR / "sprint-plan-2sprint.json").read_bytes(),
        )

    def test_mock_claude_generator_propose_contract(self):
        """C2-13: 'Propose contract' branch writes contract-proposal.json."""
        env = self._path_with_helpers()
        proc = subprocess.run(
            [sys.executable, str(MOCK_CLAUDE_PY), "--agent", "generator",
             "-p", "Propose contract for sprint-01"],
            env=env, cwd=self.test_temp_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proposal = (Path(self.test_temp_dir) / "harness-state" / "sprints"
                    / "sprint-01" / "contract-proposal.json")
        self.assertTrue(proposal.is_file())

    def test_mock_claude_generator_implement(self):
        """C2-13: implementation branch writes status.json (ready-for-eval)."""
        env = self._path_with_helpers()
        proc = subprocess.run(
            [sys.executable, str(MOCK_CLAUDE_PY), "--agent", "generator",
             "-p", "Implement sprint-01"],
            env=env, cwd=self.test_temp_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = (Path(self.test_temp_dir) / "harness-state" / "sprints"
                  / "sprint-01" / "status.json")
        self.assertTrue(status.is_file())
        data = json.loads(status.read_text(encoding="utf-8"))
        self.assertEqual(data.get("status"), "ready-for-eval")

    def test_mock_claude_generator_blocked_scenario(self):
        """C2-13: fail-generator-blocked scenario writes status='blocked'."""
        env = self._path_with_helpers()
        env["MOCK_CLAUDE_SCENARIO"] = "fail-generator-blocked"
        proc = subprocess.run(
            [sys.executable, str(MOCK_CLAUDE_PY), "--agent", "generator",
             "-p", "Implement sprint-01"],
            env=env, cwd=self.test_temp_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status = (Path(self.test_temp_dir) / "harness-state" / "sprints"
                  / "sprint-01" / "status.json")
        self.assertTrue(status.is_file())
        data = json.loads(status.read_text(encoding="utf-8"))
        self.assertEqual(data.get("status"), "blocked")

    def test_mock_claude_logs_and_counters(self):
        """C2-15: log lines and call-count files are produced."""
        env = self._path_with_helpers()
        for agent in ("planner", "generator", "evaluator"):
            subprocess.run(
                [sys.executable, str(MOCK_CLAUDE_PY), "--agent", agent,
                 "-p", "Implement sprint-01"],
                env=env, cwd=self.test_temp_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=True,
            )
        log_text = Path(self.mock_claude_log).read_text(encoding="utf-8")
        log_lines = [ln for ln in log_text.splitlines() if ln.strip()]
        self.assertEqual(len(log_lines), 3, log_text)
        for ln in log_lines:
            self.assertTrue(ln.startswith("call="))
            self.assertIn("agent=", ln)
            self.assertIn("scenario=", ln)
        call_count = Path(self.mock_claude_state_dir) / "call-count"
        self.assertEqual(call_count.read_text(encoding="utf-8").strip(), "3")
        for agent in ("planner", "generator", "evaluator"):
            ac = Path(self.mock_claude_state_dir) / f"{agent}-count"
            self.assertEqual(ac.read_text(encoding="utf-8").strip(), "1")

    def test_mock_claude_emits_usage_json(self):
        """C2-16: stdout has a parseable JSON object with session_id and usage."""
        env = self._path_with_helpers()
        proc = subprocess.run(
            [sys.executable, str(MOCK_CLAUDE_PY), "--agent", "planner",
             "-p", "x"],
            env=env, cwd=self.test_temp_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 0)
        # Find a JSON line on stdout
        stdout = proc.stdout.decode("utf-8")
        found = False
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and "session_id" in obj and "usage" in obj:
                self.assertIn("input_tokens", obj["usage"])
                self.assertIn("output_tokens", obj["usage"])
                found = True
                break
        self.assertTrue(found, f"no usage JSON line in stdout: {stdout!r}")

    def test_path_shim_resolves_claude(self):
        """C2-17: putting tests/helpers on PATH makes shutil.which('claude') work."""
        saved_path = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = str(HELPERS_DIR) + os.pathsep + saved_path
            resolved = shutil.which("claude")
            self.assertIsNotNone(
                resolved,
                f"claude not resolved with PATH including {HELPERS_DIR}",
            )
        finally:
            os.environ["PATH"] = saved_path

    def test_claude_cmd_shim_present_on_windows(self):
        """C2-17: tests/helpers/claude.cmd exists and forwards %* to mock_claude.py."""
        cmd = HELPERS_DIR / "claude.cmd"
        self.assertTrue(cmd.is_file())
        text = cmd.read_text(encoding="utf-8")
        self.assertIn("python", text.lower())
        self.assertIn("mock_claude.py", text)
        self.assertIn("%*", text)


if __name__ == "__main__":
    unittest.main()
