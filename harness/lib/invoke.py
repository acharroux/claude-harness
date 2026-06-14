"""Python port of harness/lib/invoke.sh.

Wraps `claude -p` invocations with real-time progress display, parsed from the
`stream-json` NDJSON output the CLI emits when run with --output-format stream-json.

Public API:
    invoke_claude(agent, prompt, max_turns=50, mcp_config=None) -> int

The function spawns the `claude` binary (resolved via shutil.which so test
PATH-shims are honored), streams its stdout line-by-line, parses each line as
JSON, and writes short progress decorations to stderr. Malformed JSON lines are
silently skipped. Returns the subprocess exit code unchanged.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import IO, Optional


# ANSI dim grey, matching invoke.sh
_DIM = "\033[0;90m"
_NC = "\033[0m"


def _build_argv(
    claude_path: str,
    agent: str,
    prompt: str,
    max_turns: int,
    mcp_config: Optional[str],
) -> list[str]:
    """Construct the argv list passed to subprocess.Popen."""
    argv: list[str] = [
        claude_path,
        "-p", prompt,
        "--agent", agent,
        "--max-turns", str(max_turns),
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--verbose",
    ]

    # Honor HARNESS_ROOT/.claude/settings.json if present, like invoke.sh does.
    harness_root = os.environ.get("HARNESS_ROOT")
    if harness_root:
        settings_path = Path(harness_root) / ".claude" / "settings.json"
        if settings_path.is_file():
            argv += ["--settings", str(settings_path)]

    if mcp_config:
        argv += ["--mcp-config", str(mcp_config)]

    return argv


def _preview_for_input(tool_input: object) -> str:
    """Return a short display string for a tool_use input dict."""
    if isinstance(tool_input, dict):
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and cmd:
            return cmd[:80]
        fp = tool_input.get("file_path")
        if isinstance(fp, str) and fp:
            return fp
        pat = tool_input.get("pattern")
        if isinstance(pat, str) and pat:
            return pat
    return str(tool_input)[:60]


def _emit_progress(line: str) -> None:
    """Parse one NDJSON line and write any progress decoration to stderr."""
    try:
        record = json.loads(line)
    except (ValueError, TypeError):
        # Malformed JSON: tolerate silently, matching the bash `|| continue`.
        return
    if not isinstance(record, dict):
        return

    msg_type = record.get("type")

    if msg_type == "assistant":
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        # Some streams put `content` directly on the record
        if not isinstance(content, list):
            content = record.get("content")
        for block in (content if isinstance(content, list) else []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name") or ""
            preview = _preview_for_input(block.get("input"))
            sys.stderr.write(f"  {_DIM}▸ {name}: {preview}{_NC}\n")
        try:
            sys.stderr.flush()
        except OSError:
            pass

    elif msg_type == "result":
        cost = record.get("total_cost_usd")
        if cost is None or cost == "null":
            return
        sys.stderr.write(f"  {_DIM}  Cost: ${cost}{_NC}\n")
        try:
            sys.stderr.flush()
        except OSError:
            pass


def _stream_stdout(stdout: Optional[IO[str]]) -> None:
    """Iterate the subprocess stdout stream, dispatching to _emit_progress."""
    if stdout is None:
        return
    try:
        for raw in stdout:
            if raw:
                _emit_progress(raw.rstrip("\r\n"))
    except Exception as exc:
        sys.stderr.write(f"[harness] stream error: {exc}\n")


def invoke_claude(
    agent: str,
    prompt: str,
    max_turns: int = 50,
    mcp_config: Optional[str] = None,
) -> int:
    """Invoke `claude -p` with streaming progress display.

    Returns the subprocess exit code (0 on success).
    Raises FileNotFoundError if the `claude` binary is not on PATH.
    """
    claude_path = shutil.which("claude")
    if claude_path is None:
        raise FileNotFoundError(
            "claude executable not found on PATH. "
            "Install the Claude CLI or add a PATH shim (tests/helpers)."
        )

    argv = _build_argv(claude_path, agent, prompt, max_turns, mcp_config)

    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        _stream_stdout(proc.stdout)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        rc = proc.wait()

    return rc
