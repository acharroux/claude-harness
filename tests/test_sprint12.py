"""Sprint 12 — Polish: keybinds, audio, leaderboard, badges, run summary.

Each ``test_*`` function exercises a documented Sprint-12 surface;
together they cover all of C1..C15 and feed C17.

These tests must NOT make network calls or open audio devices. They
must NOT require API keys.
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import whisperdeep
from whisperdeep import (
    audio as audio_module,
    cli as cli_module,
    keybinds as keybinds_module,
    leaderboard as leaderboard_module,
    summary as summary_module,
)
from whisperdeep.game import Game


PKG_ROOT = Path(whisperdeep.__file__).parent
BADGE_RE = re.compile(
    r"^WHISPERDEEP seed=\d+ floors=\d+ turns=\d+ archetype=\w+ v1 [0-9a-f]{6}$"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(*args, expect_zero=True, env=None):
    """Run python -m whisperdeep with args; return (rc, stdout, stderr)."""
    cmd = [sys.executable, "-m", "whisperdeep", *args]
    proc_env = dict(os.environ)
    if env:
        proc_env.update(env)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        env=proc_env,
    )
    if expect_zero:
        assert proc.returncode == 0, (
            f"command failed: {cmd}\nstdout=\n{proc.stdout}\nstderr=\n{proc.stderr}"
        )
    return proc.returncode, proc.stdout, proc.stderr


def _module_imports(path):
    """Return a set of imported top-level module names from a .py file."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


# ===========================================================================
# C1 — keybinds module structure
# ===========================================================================


def test_keybinds_module_imports_and_exposes_api():
    """C1: keybinds.py exposes COMMANDS, KeyBindings, load/save, format_help_overlay."""
    assert isinstance(keybinds_module.COMMANDS, tuple)
    for cmd in [
        "move_west", "move_east", "move_north", "move_south",
        "move_nw", "move_ne", "move_sw", "move_se",
        "wait", "descend", "ascend", "quit", "help",
    ]:
        assert cmd in keybinds_module.COMMANDS
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    assert callable(kb.bind)
    assert callable(kb.unbind)
    assert callable(kb.command_for)
    assert callable(kb.keys_for)
    # Defaults cover vi-keys + stairs + wait + quit + help.
    assert kb.command_for("h") == "move_west"
    assert kb.command_for("l") == "move_east"
    assert kb.command_for("k") == "move_north"
    assert kb.command_for("j") == "move_south"
    assert kb.command_for("y") == "move_nw"
    assert kb.command_for("u") == "move_ne"
    assert kb.command_for("b") == "move_sw"
    assert kb.command_for("n") == "move_se"
    assert kb.command_for(".") == "wait"
    assert kb.command_for(">") == "descend"
    assert kb.command_for("<") == "ascend"
    assert kb.command_for("q") == "quit"
    assert kb.command_for("?") == "help"


def test_keybinds_layering_no_disallowed_imports():
    """C1/C19: keybinds.py imports only stdlib + typing."""
    imports = _module_imports(PKG_ROOT / "keybinds.py")
    forbidden = {"llm", "render", "panel", "whisperer"}
    # We're checking module names; relative imports show up as the
    # imported submodule (e.g. 'from .llm import' -> module 'llm').
    assert not (imports & forbidden), f"forbidden imports: {imports & forbidden}"


# ===========================================================================
# C2 — keybinds JSON round-trip
# ===========================================================================


def test_keybinds_json_round_trip(tmp_path):
    """C2: save/load round-trip preserves bindings."""
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    kb.bind("move_west", "a")
    p = tmp_path / "keys.json"
    keybinds_module.save_keybindings(kb, str(p))
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert "bindings" in raw
    assert raw["bindings"].get("a") == "move_west"
    loaded = keybinds_module.load_keybindings(str(p))
    assert loaded.command_for("a") == "move_west"


def test_keybinds_load_missing_returns_defaults(tmp_path):
    """C2: loading a non-existent path returns DEFAULTS without raising."""
    nonexistent = tmp_path / "does_not_exist.json"
    kb = keybinds_module.load_keybindings(str(nonexistent))
    assert kb.command_for("h") == "move_west"


def test_keybinds_load_malformed_raises(tmp_path):
    """C2: malformed JSON raises ValueError."""
    p = tmp_path / "bad.json"
    p.write_text("{not valid", encoding="utf-8")
    with pytest.raises(ValueError):
        keybinds_module.load_keybindings(str(p))


def test_keybinds_load_unknown_command_raises(tmp_path):
    """C2: unknown command names raise ValueError mentioning the bad entry."""
    p = tmp_path / "bad-cmd.json"
    p.write_text(json.dumps({"bindings": {"a": "not_a_real_command"}}))
    with pytest.raises(ValueError) as excinfo:
        keybinds_module.load_keybindings(str(p))
    assert "not_a_real_command" in str(excinfo.value)


# ===========================================================================
# C3 — help overlay
# ===========================================================================


def test_format_help_overlay_lists_commands():
    """C3: format_help_overlay enumerates all COMMANDS."""
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    text = keybinds_module.format_help_overlay(kb)
    assert isinstance(text, str)
    assert "\n" in text
    for cmd in keybinds_module.COMMANDS:
        assert cmd in text
    assert "h" in text  # default key for move_west
    assert "\x1b" not in text  # plain ASCII (no ANSI)
    # First non-empty line is a clear header.
    first_line = next(ln for ln in text.splitlines() if ln.strip())
    assert first_line.startswith(("#", "=", "Whisperdeep"))


def test_print_help_overlay_cli():
    """C3: --print-help-overlay prints overlay and exits 0."""
    rc, out, err = _run_cli("--print-help-overlay")
    assert rc == 0
    assert "move_west" in out
    assert "quit" in out


# ===========================================================================
# C4 — --keys / --list-bindings
# ===========================================================================


def test_cli_help_lists_keys_and_list_bindings():
    """C4: --help mentions both --keys and --list-bindings."""
    rc, out, err = _run_cli("--help")
    assert rc == 0
    assert "--keys" in out
    assert "--list-bindings" in out


def test_list_bindings_subprocess(tmp_path):
    """C4: --list-bindings prints all command names."""
    rc, out, err = _run_cli("--list-bindings")
    assert rc == 0
    for cmd in keybinds_module.COMMANDS:
        assert cmd in out


def test_keys_path_loads_custom_bindings(tmp_path):
    """C4: --keys PATH loads custom bindings."""
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    kb.bind("move_west", "a")
    p = tmp_path / "keys.json"
    keybinds_module.save_keybindings(kb, str(p))
    rc, out, err = _run_cli("--keys", str(p), "--list-bindings")
    assert rc == 0
    # The custom binding 'a' should appear in the output for move_west.
    move_west_line = next(
        ln for ln in out.splitlines() if ln.startswith("move_west")
    )
    assert "a" in move_west_line


def test_keys_path_invalid_command_fails(tmp_path):
    """C4: --keys with unknown command name exits non-zero with clear error."""
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"bindings": {"a": "fly_to_the_moon"}}))
    rc, out, err = _run_cli("--keys", str(p), "--list-bindings", expect_zero=False)
    assert rc != 0
    assert "fly_to_the_moon" in err


# ===========================================================================
# C5 — audio module structure
# ===========================================================================


def test_audio_module_exposes_api():
    """C5: audio.py exposes AudioAdapter + Null + Log + CUES + EVENT_TO_CUE."""
    assert isinstance(audio_module.CUES, tuple)
    for cue in [
        "footstep", "bump", "descend", "ascend",
        "low_hp", "run_started", "run_ended", "epitaph", "first_sight",
    ]:
        assert cue in audio_module.CUES
    assert isinstance(audio_module.EVENT_TO_CUE, dict)
    for ev in ["descended", "run_started", "run_ended", "epitaph",
               "first_sight", "low_hp"]:
        assert ev in audio_module.EVENT_TO_CUE
        assert audio_module.EVENT_TO_CUE[ev] in audio_module.CUES
    null = audio_module.NullAudioAdapter()
    null.play("footstep")
    null.stop()
    log = audio_module.LogAudioAdapter()
    log.play("footstep")
    log.play("descend")
    assert log.cues == ["footstep", "descend"]


def test_audio_layering_no_backend_libs():
    """C5/C19: audio.py imports no audio backends or network libs."""
    imports = _module_imports(PKG_ROOT / "audio.py")
    forbidden = {
        "winsound", "playsound", "pyaudio", "pygame", "numpy",
        "requests", "urllib", "llm", "render", "panel", "whisperer",
    }
    assert not (imports & forbidden), (
        f"forbidden imports: {imports & forbidden}"
    )


def test_audio_module_docstring_documents_opt_in():
    """C5: module docstring mentions OPT-IN / OFF-by-default."""
    text = (PKG_ROOT / "audio.py").read_text(encoding="utf-8")
    # Cheap check: docstring should mention OPT-IN and "OFF by default".
    assert "OPT-IN" in text or "opt-in" in text.lower()
    assert "OFF by default" in text or "off by default" in text.lower()


# ===========================================================================
# C6 — Audio CLI integration
# ===========================================================================


def test_audio_cli_help_lists_audio_flags():
    rc, out, err = _run_cli("--help")
    assert "--audio" in out
    assert "--dump-audio" in out
    assert "null" in out and "log" in out


def test_audio_log_dump_writes_cues(tmp_path):
    """C6: --audio log + --dump-audio writes recorded cues."""
    cues_path = tmp_path / "cues.json"
    rc, out, err = _run_cli(
        "--seed", "1", "--headless",
        "--audio", "log",
        "--dump-audio", str(cues_path),
    )
    assert rc == 0
    assert cues_path.exists()
    data = json.loads(cues_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) >= 1
    for entry in data:
        assert entry in audio_module.CUES


def test_audio_null_dump_writes_empty(tmp_path):
    """C6/C15: --audio null + --dump-audio writes []."""
    cues_path = tmp_path / "cues2.json"
    rc, out, err = _run_cli(
        "--seed", "1", "--headless",
        "--audio", "null",
        "--dump-audio", str(cues_path),
    )
    assert rc == 0
    data = json.loads(cues_path.read_text(encoding="utf-8"))
    assert data == []


def test_game_audio_attribute_run_ended_epitaph_cues():
    """C6: Game with LogAudioAdapter records run_ended + epitaph cues on end_run."""
    log = audio_module.LogAudioAdapter()
    game = Game.from_seed(seed=1, whisperer=True, adapter="offline", audio=log)
    log.cues.clear()
    ended = game.end_run(cause="quit")
    assert ended is True
    assert "run_ended" in log.cues
    assert "epitaph" in log.cues


# ===========================================================================
# C7 — leaderboard module structure
# ===========================================================================


def test_leaderboard_module_exposes_api():
    assert callable(leaderboard_module.score_for)
    assert callable(leaderboard_module.read_leaderboard)
    assert callable(leaderboard_module.append_entry)
    assert callable(leaderboard_module.build_entry)
    assert callable(leaderboard_module.stable_seed_from_string)


def test_score_for_formula():
    """C7: score_for returns floors_reached*100 + turns."""
    g = Game.from_seed(seed=1, whisperer=False)
    assert leaderboard_module.score_for(g) == 1 * 100 + 0
    g.turns = 17
    g.max_floor_reached = 2
    assert leaderboard_module.score_for(g) == 3 * 100 + 17


def test_stable_seed_from_string_deterministic_in_subprocess():
    """C7: stable_seed_from_string is process-stable."""
    a = leaderboard_module.stable_seed_from_string("hello")
    b = leaderboard_module.stable_seed_from_string("hello")
    assert a == b
    proc = subprocess.run(
        [sys.executable, "-c",
         "from whisperdeep.leaderboard import stable_seed_from_string;"
         " print(stable_seed_from_string('hello'))"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0
    assert int(proc.stdout.strip()) == a


def test_leaderboard_layering():
    """C7/C19: leaderboard.py imports only stdlib + typing + game/archetypes (TYPE_CHECKING)."""
    imports = _module_imports(PKG_ROOT / "leaderboard.py")
    forbidden = {"llm", "render", "panel", "whisperer"}
    assert not (imports & forbidden)


# ===========================================================================
# C8 — leaderboard persistence
# ===========================================================================


def test_leaderboard_read_missing_returns_empty(tmp_path):
    p = tmp_path / "missing.json"
    assert leaderboard_module.read_leaderboard(str(p)) == []


def test_leaderboard_append_and_read(tmp_path):
    p = tmp_path / "lb.json"
    for i in range(3):
        entry = {
            "seed": i, "name": f"P{i}", "floors_reached": 1, "turns": 0,
            "score": 100 - i, "archetype": "x",
            "timestamp": f"2026-06-12T00:00:0{i}Z",
        }
        leaderboard_module.append_entry(str(p), entry)
    out = leaderboard_module.read_leaderboard(str(p))
    assert len(out) == 3
    for e in out:
        for k in ("seed", "name", "floors_reached", "turns", "score",
                  "archetype", "timestamp"):
            assert k in e


def test_leaderboard_caps_at_50(tmp_path):
    p = tmp_path / "lb.json"
    for i in range(60):
        entry = {
            "seed": i, "name": "P", "floors_reached": 1, "turns": 0,
            "score": 60 - i, "archetype": "x",
            "timestamp": f"2026-06-12T00:00:00Z",
        }
        leaderboard_module.append_entry(str(p), entry)
    out = leaderboard_module.read_leaderboard(str(p))
    assert len(out) == 50
    # Sorted by score desc.
    scores = [e["score"] for e in out]
    assert scores == sorted(scores, reverse=True)


def test_leaderboard_sort_ties_timestamp_asc(tmp_path):
    p = tmp_path / "lb.json"
    a = {"seed": 1, "name": "A", "floors_reached": 1, "turns": 0,
         "score": 100, "archetype": "x", "timestamp": "2026-06-12T00:00:01Z"}
    b = {"seed": 2, "name": "B", "floors_reached": 1, "turns": 0,
         "score": 100, "archetype": "x", "timestamp": "2026-06-12T00:00:00Z"}
    leaderboard_module.append_entry(str(p), a)
    leaderboard_module.append_entry(str(p), b)
    out = leaderboard_module.read_leaderboard(str(p))
    # Tie on score; older timestamp first.
    assert out[0]["timestamp"] == "2026-06-12T00:00:00Z"


def test_leaderboard_malformed_returns_empty(tmp_path):
    p = tmp_path / "lb.json"
    p.write_text("{not json", encoding="utf-8")
    assert leaderboard_module.read_leaderboard(str(p)) == []
    p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert leaderboard_module.read_leaderboard(str(p)) == []


# ===========================================================================
# C9 — leaderboard CLI integration
# ===========================================================================


def test_leaderboard_cli_help_lists_flags():
    rc, out, err = _run_cli("--help")
    assert "--leaderboard" in out
    assert "--no-leaderboard" in out
    assert "--print-leaderboard" in out
    assert "--leaderboard-fixed-timestamp" in out


def test_leaderboard_chronicle_run_appends_entry(tmp_path):
    lb = tmp_path / "lb.json"
    chronicle = tmp_path / "c.md"
    rc, _, _ = _run_cli(
        "--seed", "1", "--headless", "--name", "Mara",
        "--chronicle", str(chronicle),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--leaderboard", str(lb),
        "--leaderboard-fixed-timestamp", "2026-06-12T00:00:00Z",
    )
    assert rc == 0
    assert lb.exists()
    entries = json.loads(lb.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["seed"] == 1
    assert entries[0]["name"] == "Mara"
    # Run a second time with a different seed.
    rc2, _, _ = _run_cli(
        "--seed", "2", "--headless", "--name", "Mara",
        "--chronicle", str(chronicle),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:01Z",
        "--leaderboard", str(lb),
        "--leaderboard-fixed-timestamp", "2026-06-12T00:00:01Z",
    )
    assert rc2 == 0
    entries = json.loads(lb.read_text(encoding="utf-8"))
    assert len(entries) == 2


def test_leaderboard_no_leaderboard_suppresses(tmp_path):
    lb = tmp_path / "lb.json"
    chronicle = tmp_path / "c.md"
    rc, _, _ = _run_cli(
        "--seed", "1", "--headless", "--name", "Mara",
        "--chronicle", str(chronicle),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--leaderboard", str(lb),
        "--no-leaderboard",
    )
    assert rc == 0
    assert not lb.exists()


def test_print_leaderboard_cli(tmp_path):
    lb = tmp_path / "lb.json"
    chronicle = tmp_path / "c.md"
    _run_cli(
        "--seed", "1", "--headless", "--name", "Mara",
        "--chronicle", str(chronicle),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--leaderboard", str(lb),
        "--leaderboard-fixed-timestamp", "2026-06-12T00:00:00Z",
    )
    rc, out, _ = _run_cli("--print-leaderboard", "--leaderboard", str(lb))
    assert rc == 0
    assert "Mara" in out


def test_print_leaderboard_missing_path(tmp_path):
    missing = tmp_path / "no.json"
    rc, out, _ = _run_cli("--print-leaderboard", "--leaderboard", str(missing))
    assert rc == 0
    # Documented "no leaderboard yet" line OR empty.
    # Our implementation prints a parenthetical line; allow either.
    assert "no leaderboard" in out.lower() or out.strip() == ""


# ===========================================================================
# C10 — daily seed + seed-string
# ===========================================================================


def test_cli_help_mentions_daily_and_seed_string():
    rc, out, _ = _run_cli("--help")
    assert "--daily" in out
    assert "--daily-date" in out
    assert "--seed-string" in out


def test_daily_date_deterministic():
    """C10: --daily --daily-date pins the seed; output is reproducible."""
    args = ["--daily", "--daily-date", "2026-06-12",
            "--headless", "--no-whisperer"]
    rc1, out1, _ = _run_cli(*args)
    rc2, out2, _ = _run_cli(*args)
    assert rc1 == 0 and rc2 == 0
    assert out1 == out2


def test_seed_string_deterministic():
    """C10: --seed-string is reproducible across processes."""
    args = ["--seed-string", "whispergrove",
            "--headless", "--no-whisperer"]
    rc1, out1, _ = _run_cli(*args)
    rc2, out2, _ = _run_cli(*args)
    assert rc1 == 0
    assert out1 == out2


def test_seed_and_daily_conflict():
    rc, _, err = _run_cli("--seed", "1", "--daily", "--headless",
                          expect_zero=False)
    assert rc != 0
    assert "exclusive" in err.lower() or "conflict" in err.lower() or "--seed" in err


def test_seed_and_seed_string_conflict():
    rc, _, err = _run_cli("--seed", "1", "--seed-string", "x", "--headless",
                          expect_zero=False)
    assert rc != 0


def test_different_seed_strings_produce_different_output():
    _, a, _ = _run_cli("--seed-string", "alpha",
                       "--headless", "--no-whisperer")
    _, b, _ = _run_cli("--seed-string", "beta",
                       "--headless", "--no-whisperer")
    assert a != b


# ===========================================================================
# C11 — badge
# ===========================================================================


def test_build_badge_format():
    g = Game.from_seed(seed=1, whisperer=False)
    badge = summary_module.build_badge(g)
    assert badge.startswith("WHISPERDEEP ")
    assert BADGE_RE.match(badge), f"badge does not match regex: {badge!r}"


def test_build_badge_checksum_reversible():
    """C11: <CHK> is the first 6 hex chars of sha256 of the prefix."""
    import hashlib
    g = Game.from_seed(seed=1, whisperer=False)
    badge = summary_module.build_badge(g)
    prefix, chk = badge.rsplit(" ", 1)
    expected = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:6]
    assert chk == expected


def test_print_badge_cli():
    rc, out, _ = _run_cli("--seed", "1", "--headless", "--print-badge")
    assert rc == 0
    assert "WHISPERDEEP seed=1" in out


def test_chronicle_writes_sibling_badge(tmp_path):
    chronicle = tmp_path / "c.md"
    _run_cli(
        "--seed", "1", "--headless", "--name", "Mara",
        "--chronicle", str(chronicle),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--no-leaderboard",
    )
    badge_path = tmp_path / "c.md.badge.txt"
    assert badge_path.exists()
    line = badge_path.read_text(encoding="utf-8").strip()
    assert BADGE_RE.match(line)


def test_chronicle_no_badge_suppresses(tmp_path):
    chronicle = tmp_path / "c.md"
    _run_cli(
        "--seed", "1", "--headless", "--name", "Mara",
        "--chronicle", str(chronicle),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--no-leaderboard", "--no-badge",
    )
    badge_path = tmp_path / "c.md.badge.txt"
    assert not badge_path.exists()


def test_badge_seeds_differ():
    g1 = Game.from_seed(seed=1, whisperer=False)
    g2 = Game.from_seed(seed=2, whisperer=False)
    assert summary_module.build_badge(g1) != summary_module.build_badge(g2)


# ===========================================================================
# C12 — run summary
# ===========================================================================


def test_build_run_summary_format():
    g = Game.from_seed(seed=1, whisperer=False)
    text = summary_module.build_run_summary(
        g, name="Mara", fixed_timestamp="2026-06-12T00:00:00Z"
    )
    assert "Mara" in text
    assert "seed" in text
    assert "1" in text
    assert "score" in text
    # Embedded badge must match the regex on its own line.
    badge_lines = [
        ln.split(":", 1)[1].strip()
        for ln in text.splitlines()
        if ln.startswith("badge")
    ]
    assert badge_lines, "summary must include a badge line"
    assert BADGE_RE.match(badge_lines[0])
    # Header.
    assert text.splitlines()[0].strip().startswith("==")


def test_summary_cli_help_lists_flags():
    rc, out, _ = _run_cli("--help")
    assert "--summary" in out
    assert "--no-summary" in out


def test_summary_subprocess_deterministic(tmp_path):
    args = [
        "--seed", "1", "--headless", "--summary", "--name", "Mara",
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--no-leaderboard",
    ]
    rc1, out1, _ = _run_cli(*args)
    rc2, out2, _ = _run_cli(*args)
    # Extract the summary block (from BADGE_HEADER onwards).
    def _extract(s):
        idx = s.find("== Run Summary ==")
        assert idx >= 0
        return s[idx:]
    assert _extract(out1) == _extract(out2)


def test_summary_no_summary_suppresses():
    rc, out, _ = _run_cli(
        "--seed", "1", "--headless", "--no-summary",
    )
    assert rc == 0
    assert "== Run Summary ==" not in out


def test_summary_seeds_differ():
    g1 = Game.from_seed(seed=1, whisperer=False)
    g2 = Game.from_seed(seed=2, whisperer=False)
    s1 = summary_module.build_run_summary(g1, name="X", fixed_timestamp="t")
    s2 = summary_module.build_run_summary(g2, name="X", fixed_timestamp="t")
    assert s1 != s2


# ===========================================================================
# C13 — interactive loop dispatcher / `:`-commands
# ===========================================================================


def test_dispatch_command_movement():
    """C13: dispatch_command resolves a key to a movement."""
    g = Game.from_seed(seed=1, whisperer=False)
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    start_turn = g.turns
    result = cli_module.dispatch_command(g, kb, "h")
    assert result in ("moved", "blocked")
    assert g.turns == start_turn + 1


def test_dispatch_command_quit():
    g = Game.from_seed(seed=1, whisperer=False)
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    assert cli_module.dispatch_command(g, kb, "q") == "quit"
    assert cli_module.dispatch_command(g, kb, ":quit") == "quit"


def test_dispatch_command_help():
    g = Game.from_seed(seed=1, whisperer=False)
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    assert cli_module.dispatch_command(g, kb, "?") == "help"
    assert cli_module.dispatch_command(g, kb, ":help") == "help"
    assert cli_module.dispatch_command(g, kb, ":bindings") == "help"


def test_dispatch_command_descend_ascend():
    """C13: :descend / :ascend invoke Game.descend/ascend semantics."""
    g = Game.from_seed(seed=1, whisperer=False)
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    # Player not on stairs -> no-stairs.
    assert cli_module.dispatch_command(g, kb, ":descend") in ("descended", "no-stairs")
    # Force the player onto downstairs and try again.
    floor = g.floor
    pos = floor.downstairs_pos
    if pos is not None:
        g.player.x, g.player.y = pos
        result = cli_module.dispatch_command(g, kb, ":descend")
        assert result == "descended"


def test_dispatch_command_unknown_does_not_advance():
    g = Game.from_seed(seed=1, whisperer=False)
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    start_turn = g.turns
    result = cli_module.dispatch_command(g, kb, ":foo_bar")
    assert result.startswith("unknown")
    assert g.turns == start_turn


def test_dispatch_command_wait_advances_turn():
    g = Game.from_seed(seed=1, whisperer=False)
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    start_turn = g.turns
    result = cli_module.dispatch_command(g, kb, ".")
    assert result == "waited"
    assert g.turns == start_turn + 1


def test_dispatch_command_bind_at_runtime():
    g = Game.from_seed(seed=1, whisperer=False)
    kb = keybinds_module.KeyBindings.DEFAULTS_KB()
    result = cli_module.dispatch_command(g, kb, ":bind move_west a")
    assert result == "rebound"
    assert kb.command_for("a") == "move_west"


# ===========================================================================
# C14 — determinism
# ===========================================================================


def test_determinism_seed_no_whisperer():
    args = ["--seed", "1", "--headless", "--no-whisperer"]
    _, a, _ = _run_cli(*args)
    _, b, _ = _run_cli(*args)
    assert a == b


def test_determinism_seed_whisperer():
    args = ["--seed", "11", "--headless"]
    _, a, _ = _run_cli(*args)
    _, b, _ = _run_cli(*args)
    assert a == b


def test_determinism_chronicle_leaderboard_badge(tmp_path):
    """C14: chronicle.md, badge.txt, leaderboard entry are byte-deterministic."""
    out_dir = tmp_path
    args1 = [
        "--seed", "1", "--headless", "--name", "Mara",
        "--chronicle", str(out_dir / "a.md"),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--leaderboard", str(out_dir / "lb_a.json"),
        "--leaderboard-fixed-timestamp", "2026-06-12T00:00:00Z",
    ]
    args2 = [
        "--seed", "1", "--headless", "--name", "Mara",
        "--chronicle", str(out_dir / "b.md"),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--leaderboard", str(out_dir / "lb_b.json"),
        "--leaderboard-fixed-timestamp", "2026-06-12T00:00:00Z",
    ]
    _run_cli(*args1)
    _run_cli(*args2)
    assert (out_dir / "a.md").read_bytes() == (out_dir / "b.md").read_bytes()
    assert (
        (out_dir / "a.md.badge.txt").read_bytes()
        == (out_dir / "b.md.badge.txt").read_bytes()
    )
    assert (
        json.loads((out_dir / "lb_a.json").read_text(encoding="utf-8"))
        == json.loads((out_dir / "lb_b.json").read_text(encoding="utf-8"))
    )


def test_determinism_seed_string():
    args = ["--seed-string", "whispergrove",
            "--headless", "--no-whisperer"]
    _, a, _ = _run_cli(*args)
    _, b, _ = _run_cli(*args)
    assert a == b


def test_determinism_daily_date():
    args = ["--daily", "--daily-date", "2026-06-12",
            "--headless", "--no-whisperer"]
    _, a, _ = _run_cli(*args)
    _, b, _ = _run_cli(*args)
    assert a == b


def test_determinism_different_seeds_differ():
    _, a, _ = _run_cli("--seed", "1", "--headless", "--no-whisperer")
    _, b, _ = _run_cli("--seed", "2", "--headless", "--no-whisperer")
    assert a != b


# ===========================================================================
# C15 — robustness / edge cases
# ===========================================================================


def test_build_badge_with_no_archetype_falls_back():
    """C15: Game with floor.archetype=None still builds a valid badge."""
    g = Game.from_seed(seed=1, whisperer=False)
    g.world.get_floor(0).archetype = None
    badge = summary_module.build_badge(g)
    assert BADGE_RE.match(badge)
    assert "archetype=unknown" in badge


def test_seed_string_empty_rejected():
    rc, _, err = _run_cli("--seed-string", "", "--headless",
                          expect_zero=False)
    assert rc != 0
    assert "non-empty" in err or "empty" in err


def test_load_keybindings_duplicate_keys_last_wins(tmp_path):
    """C15: duplicate keys in JSON resolve last-wins (json.loads default)."""
    p = tmp_path / "dup.json"
    # JSON spec: if duplicate keys, json.loads keeps the last value.
    p.write_text(
        '{"bindings": {"h": "move_east", "h": "move_west"}}',
        encoding="utf-8",
    )
    kb = keybinds_module.load_keybindings(str(p))
    assert kb.command_for("h") == "move_west"


def test_audio_log_dump_no_whisperer_writes_empty(tmp_path):
    """C15: --audio log + --no-whisperer + --dump-audio writes [] (no bus)."""
    cues = tmp_path / "cues.json"
    rc, _, _ = _run_cli(
        "--seed", "1", "--headless", "--no-whisperer",
        "--audio", "log", "--dump-audio", str(cues),
    )
    assert rc == 0
    data = json.loads(cues.read_text(encoding="utf-8"))
    assert data == []


def test_build_badge_no_whisperer():
    """C15: build_badge works on a Game built with whisperer=False."""
    g = Game.from_seed(seed=3, whisperer=False)
    badge = summary_module.build_badge(g)
    assert BADGE_RE.match(badge)


# ===========================================================================
# C19 — layering invariants
# ===========================================================================


def test_summary_module_layering():
    imports = _module_imports(PKG_ROOT / "summary.py")
    forbidden = {"llm", "render", "panel", "whisperer"}
    assert not (imports & forbidden)


def test_events_does_not_import_new_modules():
    imports = _module_imports(PKG_ROOT / "events.py")
    forbidden = {"keybinds", "audio", "leaderboard", "summary"}
    assert not (imports & forbidden)


def test_llm_does_not_import_new_modules():
    imports = _module_imports(PKG_ROOT / "llm.py")
    forbidden = {"keybinds", "audio", "leaderboard", "summary"}
    assert not (imports & forbidden)


def test_event_types_unchanged_from_sprint11():
    from whisperdeep.events import EVENT_TYPES
    assert set(EVENT_TYPES) == {
        "run_started", "run_ended", "entered_room", "killed_monster",
        "low_hp", "found_item", "descended", "first_sight",
        "room_entered", "epitaph",
    }


def test_tilekind_unchanged():
    from whisperdeep.tiles import TileKind
    assert len(list(TileKind)) == 5


# ===========================================================================
# C20 — end-to-end smoke
# ===========================================================================


def test_end_to_end_smoke_full_sprint12_surface(tmp_path):
    """C20: a single full-fidelity Sprint-12 run produces every artifact."""
    keys_path = tmp_path / "keys.json"
    keybinds_module.save_keybindings(
        keybinds_module.KeyBindings.DEFAULTS_KB(), str(keys_path)
    )
    chronicle = tmp_path / "c.md"
    lb = tmp_path / "lb.json"
    cues = tmp_path / "cues.json"
    args = [
        "--seed", "7", "--headless", "--name", "Mara",
        "--chronicle", str(chronicle),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--leaderboard", str(lb),
        "--leaderboard-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--audio", "log", "--dump-audio", str(cues),
        "--summary", "--keys", str(keys_path),
    ]
    rc, out, _ = _run_cli(*args)
    assert rc == 0
    assert chronicle.exists()
    text = chronicle.read_text(encoding="utf-8")
    assert text.startswith("#")
    assert "Mara" in text
    assert "seed: 7" in text
    badge_path = Path(str(chronicle) + ".badge.txt")
    assert badge_path.exists()
    badge_line = badge_path.read_text(encoding="utf-8").strip()
    assert BADGE_RE.match(badge_line)
    assert "seed=7" in badge_line
    entries = json.loads(lb.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["seed"] == 7
    assert entries[0]["name"] == "Mara"
    cue_data = json.loads(cues.read_text(encoding="utf-8"))
    assert isinstance(cue_data, list)
    assert len(cue_data) >= 1
    assert "== Run Summary ==" in out
    # Re-run with --seed 8 -> two entries.
    args2 = list(args)
    args2[1] = "8"
    rc2, _, _ = _run_cli(*args2)
    assert rc2 == 0
    entries = json.loads(lb.read_text(encoding="utf-8"))
    assert len(entries) == 2
    scores = [e["score"] for e in entries]
    assert scores == sorted(scores, reverse=True)


# ===========================================================================
# C16 regression smoke: prior CLI flags still work
# ===========================================================================


def test_prior_flags_still_work_archetype():
    rc, out, _ = _run_cli(
        "--seed", "1", "--headless", "--no-whisperer",
        "--archetype", "crypt",
    )
    assert rc == 0


def test_list_archetypes_still_works():
    rc, out, _ = _run_cli("--list-archetypes")
    assert rc == 0
    assert len(out.splitlines()) >= 5


def test_chronicle_still_works(tmp_path):
    chronicle = tmp_path / "c.md"
    rc, _, _ = _run_cli(
        "--seed", "1", "--headless", "--name", "Mara",
        "--chronicle", str(chronicle),
        "--chronicle-fixed-timestamp", "2026-06-12T00:00:00Z",
        "--no-leaderboard",
    )
    assert rc == 0
    text = chronicle.read_text(encoding="utf-8")
    assert text.startswith("#")
    assert "Mara" in text
    assert "seed: 1" in text
