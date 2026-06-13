"""Sprint 10 tests: Chronicle Generator.

Covers C1..C18 of the sprint-10 contract:

* chronicle module imports (C1)
* chronicle Markdown structure / required sections (C2, C18)
* `epitaph` in EVENT_TYPES + pool size (C3)
* `Game.end_run` idempotency + safe-on-no-whisperer (C4)
* notable events ordering (C5)
* `write_chronicle` creates parent + writes file (C6)
* default chronicle path uniqueness + slug (C7)
* CLI `--name` / `--chronicle` integration (C8)
* determinism with fixed timestamp (C9)
* epitaph rendering convention + determinism (C10)
* edge cases / unicode / no-whisperer chronicle (C11)
* end-to-end whispers-vs-chronicle consistency (C12)
* layering invariants spot-check (C17)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from whisperdeep import chronicle as chronicle_module
from whisperdeep.chronicle import (
    DEFAULT_NAME,
    build_chronicle,
    default_chronicle_path,
    slugify_name,
    write_chronicle,
)
from whisperdeep.events import EVENT_TYPES, Event, EventBus, EventType
from whisperdeep.game import Game
from whisperdeep.llm import OfflineAdapter, get_prose_pool


FIXED_TS = "2026-06-12T00:00:00Z"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run_cli(*flags: str, env=None):
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "whisperdeep", *flags]
    e = os.environ.copy()
    if env:
        e.update(env)
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        e.pop(k, None)
    return subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        env=e,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# C1 — chronicle module imports
# ---------------------------------------------------------------------------


def test_c1_chronicle_module_imports():
    # The two main public functions are importable.
    assert callable(build_chronicle)
    assert callable(write_chronicle)
    # Default name + chronicle dir are exposed (helpful for documentation).
    assert isinstance(DEFAULT_NAME, str) and DEFAULT_NAME
    # Module docstring documents the four required sections.
    doc = chronicle_module.__doc__ or ""
    for section in ("Metadata", "Notable Events", "Epitaph"):
        assert section in doc, f"chronicle module docstring missing {section!r}"


# ---------------------------------------------------------------------------
# C3 — epitaph event + pool
# ---------------------------------------------------------------------------


def test_c3_epitaph_event_added_additive():
    assert "epitaph" in EVENT_TYPES
    assert EventType.EPITAPH.value == "epitaph"
    # Original seven Sprint-7 names still present.
    for name in (
        "run_started",
        "run_ended",
        "entered_room",
        "killed_monster",
        "low_hp",
        "found_item",
        "descended",
    ):
        assert name in EVENT_TYPES, f"{name} dropped from EVENT_TYPES"
    # Sprint 8 additions still present.
    assert "first_sight" in EVENT_TYPES
    assert "room_entered" in EVENT_TYPES


def test_c3_epitaph_pool_has_eight_entries():
    pool = get_prose_pool()
    assert "epitaph" in pool
    entries = pool["epitaph"]
    assert isinstance(entries, list)
    distinct = {e for e in entries if isinstance(e, str) and e}
    assert len(distinct) >= 8, f"epitaph pool has only {len(distinct)} distinct entries"
    # No regression on the prior canonical types.
    for name in (
        "run_started",
        "run_ended",
        "entered_room",
        "killed_monster",
        "low_hp",
        "found_item",
        "descended",
        "first_sight",
        "room_entered",
    ):
        assert len({e for e in pool[name] if e}) >= 8


# ---------------------------------------------------------------------------
# C4 — Game.end_run
# ---------------------------------------------------------------------------


def test_c4_end_run_publishes_run_ended_and_epitaph():
    game = Game.from_seed(seed=1, whisperer=True)
    before_count = len(game.whisperer.whispers)
    ok = game.end_run(cause="quit")
    assert ok is True
    types = [w.source_event_type for w in game.whisperer.whispers]
    assert "run_ended" in types
    assert "epitaph" in types
    assert len(game.whisperer.whispers) > before_count


def test_c4_end_run_is_idempotent():
    game = Game.from_seed(seed=1, whisperer=True)
    assert game.end_run() is True
    n1 = sum(1 for w in game.whisperer.whispers if w.source_event_type == "run_ended")
    e1 = sum(1 for w in game.whisperer.whispers if w.source_event_type == "epitaph")
    assert game.end_run() is False
    n2 = sum(1 for w in game.whisperer.whispers if w.source_event_type == "run_ended")
    e2 = sum(1 for w in game.whisperer.whispers if w.source_event_type == "epitaph")
    assert n1 == n2 and e1 == e2


def test_c4_end_run_safe_with_no_whisperer():
    game = Game.from_seed(seed=1, whisperer=False)
    assert game.events is None
    # Must not raise.
    result = game.end_run(cause="quit")
    assert result is False


# ---------------------------------------------------------------------------
# C2 / C18 — chronicle structure + metadata
# ---------------------------------------------------------------------------


def test_c2_build_chronicle_has_required_sections():
    game = Game.from_seed(seed=1, whisperer=True)
    game.observe_kind("skitterer", "monster")
    game.end_run("quit")
    md = build_chronicle(game, name="Mara", fixed_timestamp=FIXED_TS)
    assert isinstance(md, str) and md
    # H1 with 'Mara'.
    first_line = md.splitlines()[0]
    assert first_line.startswith("# ")
    assert "Mara" in first_line
    # The four required section headers (case-insensitive contains check).
    md_lower = md.lower()
    for header in ("## metadata", "## notable events", "## epitaph"):
        assert header in md_lower, f"missing header {header}"
    # Contains seed + adapter + fixed timestamp.
    assert "seed: 1" in md
    assert "adapter:" in md
    assert FIXED_TS in md


def test_c18_metadata_block_machine_readable():
    game = Game.from_seed(seed=7, whisperer=True)
    game.end_run("quit")
    md = build_chronicle(game, name="Mara", fixed_timestamp=FIXED_TS)
    # Bullet form for each required key.
    for key in ("seed", "name", "floors_reached", "turns", "adapter", "timestamp"):
        pattern = re.compile(rf"^- {key}: ", re.MULTILINE)
        assert pattern.search(md), f"metadata missing key {key!r}"
    # Specific values.
    assert "- seed: 7" in md
    assert "- name: Mara" in md
    assert f"- timestamp: {FIXED_TS}" in md
    # Metadata block sits BETWEEN H1 and the events section.
    h1_idx = md.index("# ")
    meta_idx = md.index("## Metadata")
    events_idx = md.index("## Notable Events")
    assert h1_idx < meta_idx < events_idx


def test_c18_default_timestamp_is_iso_z():
    game = Game.from_seed(seed=1, whisperer=True)
    game.end_run("quit")
    md = build_chronicle(game, name="Mara")
    # Timestamp line ends with 'Z'.
    line = next(
        l for l in md.splitlines() if l.startswith("- timestamp:")
    )
    ts = line.split(": ", 1)[1].strip()
    assert ts.endswith("Z")
    # Approx ISO-8601 shape: YYYY-MM-DDTHH:MM:SSZ
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts), ts


# ---------------------------------------------------------------------------
# C5 — notable events ordering
# ---------------------------------------------------------------------------


def test_c5_notable_events_chronological():
    game = Game.from_seed(seed=1, whisperer=True)
    game.observe_kind("goblin", "monster")
    # Force a descent to inject a 'descended' whisper.
    floor0 = game.floor
    if floor0.downstairs_pos is not None:
        game.teleport(*floor0.downstairs_pos)
        game.descend()
    game.end_run("quit")
    md = build_chronicle(game, name="Mara", fixed_timestamp=FIXED_TS)
    # Find the events section.
    events_section = md.split("## Notable Events", 1)[1].split("## Epitaph", 1)[0]
    # Pull the bullet types out in order.
    bullets = [l for l in events_section.splitlines() if l.startswith("- [")]
    types = []
    for b in bullets:
        m = re.match(r"- \[(\w+)@", b)
        if m:
            types.append(m.group(1))
    # run_started must come first; run_ended must come after descended.
    assert types[0] == "run_started"
    assert "descended" in types
    assert "run_ended" in types
    assert types.index("descended") < types.index("run_ended")
    # first_sight whisper for goblin appears.
    assert "first_sight" in types


# ---------------------------------------------------------------------------
# C6 — write_chronicle
# ---------------------------------------------------------------------------


def test_c6_write_chronicle_creates_parent_and_writes(tmp_path):
    game = Game.from_seed(seed=1, whisperer=True)
    game.end_run("quit")
    target = tmp_path / "nested" / "deeper" / "run.md"
    assert not target.parent.exists()
    returned = write_chronicle(
        game, str(target), name="Mara", fixed_timestamp=FIXED_TS
    )
    assert Path(returned).exists()
    assert target.exists()
    md_disk = target.read_text(encoding="utf-8")
    md_str = build_chronicle(game, name="Mara", fixed_timestamp=FIXED_TS)
    assert md_disk == md_str
    assert md_disk.startswith("# ")


def test_c6_write_chronicle_overwrites(tmp_path):
    game = Game.from_seed(seed=1, whisperer=True)
    game.end_run("quit")
    target = tmp_path / "run.md"
    write_chronicle(game, str(target), name="A", fixed_timestamp=FIXED_TS)
    write_chronicle(game, str(target), name="B", fixed_timestamp=FIXED_TS)
    text = target.read_text(encoding="utf-8")
    assert "# B" in text
    assert "# A " not in text


# ---------------------------------------------------------------------------
# C7 — default chronicle path
# ---------------------------------------------------------------------------


def test_c7_default_path_unique_per_seed_and_name(tmp_path):
    g1 = Game.from_seed(seed=1, whisperer=True)
    g2 = Game.from_seed(seed=2, whisperer=True)
    p1 = default_chronicle_path(g1, "Mara", root=str(tmp_path))
    p2 = default_chronicle_path(g2, "Mara", root=str(tmp_path))
    p3 = default_chronicle_path(g1, "Devon", root=str(tmp_path))
    assert p1 != p2  # seed differs
    assert p1 != p3  # name differs
    for p in (p1, p2, p3):
        assert "chronicles" in Path(p).parts
        assert p.endswith(".md")


def test_c7_slugify_name_safe():
    assert slugify_name("Mara the Lost") == "mara-the-lost"
    assert slugify_name("  ") == "unnamed"
    s = slugify_name("Mara/the\\Lost!")
    assert "/" not in s and "\\" not in s and "!" not in s
    assert s.islower()


# ---------------------------------------------------------------------------
# C8 — CLI integration
# ---------------------------------------------------------------------------


def test_c8_cli_help_lists_chronicle_flags():
    res = _run_cli("--help")
    assert res.returncode == 0
    out = res.stdout + res.stderr
    assert "--name" in out
    assert "--chronicle" in out


def test_c8_cli_chronicle_writes_file(tmp_path):
    target = tmp_path / "chronicle.md"
    res = _run_cli(
        "--seed", "1", "--headless",
        "--name", "Mara",
        "--chronicle", str(target),
        "--chronicle-fixed-timestamp", FIXED_TS,
    )
    assert res.returncode == 0, res.stderr
    assert target.exists()
    md = target.read_text(encoding="utf-8")
    assert md.startswith("# ")
    assert "Mara" in md
    assert "seed" in md and "1" in md


def test_c8_cli_no_chronicle_when_unset(tmp_path):
    # When --chronicle is not passed, no file is written under the temp dir.
    res = _run_cli("--seed", "1", "--headless")
    assert res.returncode == 0
    # Nothing further to check; we just ensure no crash without the flag.


# ---------------------------------------------------------------------------
# C9 — determinism
# ---------------------------------------------------------------------------


def test_c9_build_chronicle_byte_deterministic_for_same_seed():
    g1 = Game.from_seed(seed=11, whisperer=True)
    g1.end_run("quit")
    g2 = Game.from_seed(seed=11, whisperer=True)
    g2.end_run("quit")
    a = build_chronicle(g1, name="Mara", fixed_timestamp=FIXED_TS)
    b = build_chronicle(g2, name="Mara", fixed_timestamp=FIXED_TS)
    assert a == b


def test_c9_build_chronicle_differs_across_seeds():
    g1 = Game.from_seed(seed=11, whisperer=True)
    g1.end_run("quit")
    g2 = Game.from_seed(seed=12, whisperer=True)
    g2.end_run("quit")
    a = build_chronicle(g1, name="Mara", fixed_timestamp=FIXED_TS)
    b = build_chronicle(g2, name="Mara", fixed_timestamp=FIXED_TS)
    assert a != b


def test_c9_cli_chronicle_byte_deterministic(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    for target in (a, b):
        res = _run_cli(
            "--seed", "11", "--headless",
            "--name", "Mara",
            "--chronicle", str(target),
            "--chronicle-fixed-timestamp", FIXED_TS,
        )
        assert res.returncode == 0
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# C10 — epitaph rendering + determinism
# ---------------------------------------------------------------------------


def test_c10_epitaph_section_blockquote_from_pool():
    game = Game.from_seed(seed=11, whisperer=True)
    game.end_run("quit")
    md = build_chronicle(game, name="Mara", fixed_timestamp=FIXED_TS)
    # Find the epitaph section.
    section = md.split("## Epitaph", 1)[1]
    # First non-blank line begins with '> ' (Markdown blockquote).
    quoted = next(l for l in section.splitlines() if l.strip())
    assert quoted.startswith("> ")
    epitaph_text = quoted[2:].strip()
    pool = get_prose_pool()
    assert epitaph_text in pool["epitaph"]
    # The chronicle's epitaph equals the most-recent epitaph whisper text.
    last_ep = next(
        w for w in reversed(game.whisperer.whispers)
        if w.source_event_type == "epitaph"
    )
    assert last_ep.text == epitaph_text


def test_c10_epitaph_deterministic_across_runs():
    g1 = Game.from_seed(seed=11, whisperer=True)
    g1.end_run("quit")
    g2 = Game.from_seed(seed=11, whisperer=True)
    g2.end_run("quit")
    e1 = next(w for w in g1.whisperer.whispers if w.source_event_type == "epitaph")
    e2 = next(w for w in g2.whisperer.whispers if w.source_event_type == "epitaph")
    assert e1.text == e2.text


# ---------------------------------------------------------------------------
# C11 — edge cases
# ---------------------------------------------------------------------------


def test_c11_no_whisperer_chronicle_still_valid():
    game = Game.from_seed(seed=1, whisperer=False)
    md = build_chronicle(game, name="Mara", fixed_timestamp=FIXED_TS)
    assert isinstance(md, str) and md.startswith("# ")
    assert "Mara" in md
    # Some indication that no whispers were recorded.
    assert "no whispers" in md.lower()


def test_c11_chronicle_without_end_run():
    game = Game.from_seed(seed=1, whisperer=True)
    md = build_chronicle(game, name="Mara", fixed_timestamp=FIXED_TS)
    assert "## Epitaph" in md  # placeholder section still present
    # run_started whisper text appears.
    pool = get_prose_pool()
    assert any(entry in md for entry in pool["run_started"])


def test_c11_long_name_does_not_overflow():
    game = Game.from_seed(seed=1, whisperer=True)
    game.end_run("quit")
    long_name = "a very long name " * 5
    md = build_chronicle(game, name=long_name, fixed_timestamp=FIXED_TS)
    assert long_name.strip() in md


def test_c11_unicode_name_and_write(tmp_path):
    game = Game.from_seed(seed=1, whisperer=True)
    game.end_run("quit")
    name = "Marä Köld"
    md = build_chronicle(game, name=name, fixed_timestamp=FIXED_TS)
    assert name in md
    target = tmp_path / "uni.md"
    write_chronicle(game, str(target), name=name, fixed_timestamp=FIXED_TS)
    on_disk = target.read_text(encoding="utf-8")
    assert name in on_disk


# ---------------------------------------------------------------------------
# C12 — end-to-end whispers <-> chronicle consistency
# ---------------------------------------------------------------------------


def test_c12_chronicle_includes_dumped_whisper_texts(tmp_path):
    chron = tmp_path / "chr.md"
    dump = tmp_path / "wh.json"
    res = _run_cli(
        "--seed", "1", "--headless",
        "--name", "Mara",
        "--chronicle", str(chron),
        "--chronicle-fixed-timestamp", FIXED_TS,
        "--dump-whispers", str(dump),
    )
    assert res.returncode == 0
    whispers = json.loads(dump.read_text(encoding="utf-8"))
    assert isinstance(whispers, list) and whispers
    md = chron.read_text(encoding="utf-8")
    # Every whisper text shows up in the chronicle (or its source_event_type
    # is enumerated via the bullet prefix).
    for w in whispers:
        text = w["text"]
        et = w["source_event_type"]
        assert (text in md) or (f"[{et}@" in md), f"whisper {et!r} missing from chronicle"


# ---------------------------------------------------------------------------
# C13 — Sprint 8 regression spot checks
# ---------------------------------------------------------------------------


def test_c13_sprint8_event_types_superset():
    base = {
        "run_started", "run_ended", "entered_room", "killed_monster",
        "low_hp", "found_item", "descended", "first_sight", "room_entered",
    }
    assert base.issubset(set(EVENT_TYPES))


def test_c13_no_panel_dump_still_works(tmp_path):
    target = tmp_path / "wh.json"
    res = _run_cli(
        "--seed", "1", "--headless",
        "--no-panel",
        "--dump-whispers", str(target),
    )
    assert res.returncode == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data


# ---------------------------------------------------------------------------
# C14 — Sprint 7 / Sprint 1-2 regression spot checks
# ---------------------------------------------------------------------------


def test_c14_no_whisperer_byte_deterministic():
    a = _run_cli("--seed", "1", "--headless", "--no-whisperer")
    b = _run_cli("--seed", "1", "--headless", "--no-whisperer")
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout == b.stdout


def test_c14_glyphs_present_for_seed_1():
    # Sprint 11: pin the archetype to 'crypt' so the Sprint-1/2 default
    # glyphs are observable. (Without --archetype, seed=1 floor 0 picks
    # 'flooded_sewer' whose '=' / ',' overrides change the glyph set.)
    res = _run_cli(
        "--seed", "1", "--headless", "--no-whisperer", "--archetype", "crypt"
    )
    assert res.returncode == 0
    for glyph in ("#", ".", "@", ">"):
        assert glyph in res.stdout


# ---------------------------------------------------------------------------
# C17 — layering invariants
# ---------------------------------------------------------------------------


def test_c17_chronicle_does_not_import_llm_render_panel():
    src = Path(chronicle_module.__file__).read_text(encoding="utf-8")
    # Top-level imports must not touch llm / render / panel.
    forbidden = (
        "from .llm",
        "import whisperdeep.llm",
        "from .render",
        "import whisperdeep.render",
        "from .panel",
        "import whisperdeep.panel",
    )
    # Only inspect non-comment lines for safety.
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for f in forbidden:
            assert f not in stripped, f"chronicle.py forbidden import: {stripped!r}"


def test_c17_events_and_llm_do_not_import_chronicle():
    from whisperdeep import events as events_mod, llm as llm_mod
    forbidden = (
        "from .chronicle",
        "from whisperdeep.chronicle",
        "import whisperdeep.chronicle",
    )
    for mod in (events_mod, llm_mod):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                continue
            for f in forbidden:
                assert f not in stripped, f"{mod.__name__} imports chronicle: {stripped!r}"


def test_c17_game_does_not_top_level_import_chronicle():
    from whisperdeep import game as game_mod
    src = Path(game_mod.__file__).read_text(encoding="utf-8")
    # Top-level lines only (no leading whitespace).
    for line in src.splitlines():
        if line.startswith("from .chronicle") or line.startswith("import whisperdeep.chronicle"):
            pytest.fail(f"game.py top-level import of chronicle: {line!r}")
