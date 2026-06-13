"""Sprint 11 tests: Themed Archetypes & Palettes.

Covers C1..C17 of the sprint-11 contract:

* archetypes module imports + types (C1)
* >= 5 archetypes with required ids + glyph_overrides shape (C2)
* assign_archetype determinism + diversity + secret reachable (C3)
* World/Floor.archetype assignment (C4)
* glyph variant rendering + walkability preserved (C5)
* determinism across processes (C6)
* palette descriptor shape + ANSI opt-in (C7)
* archetype-flavoured prose pool (C8)
* whisper records carry archetype (C9)
* Floor snapshot kind/glyph distinction (C10)
* CLI --archetype / --list-archetypes (C11)
* edge-case empty/None archetype (C12)
* regression of prior sprints (C13/C14)
* tests count >= 14 (C15)
* documentation present (C16) -- covered separately by manual review,
  but we sanity-check the docs file mentions Sprint 11.
* layering invariants (C17)
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import whisperdeep.archetypes as archetypes_module
from whisperdeep import archetypes as arch_pub
from whisperdeep.archetypes import (
    ARCHETYPES,
    ARCHETYPE_BY_ID,
    DEFAULT_GLYPHS,
    DungeonArchetype,
    REQUIRED_IDS,
    REQUIRED_PALETTE_KEYS,
    RESERVED_GLYPHS,
    SECRET_ID,
    archetype_summary_line,
    assign_archetype,
    get_archetype,
    palette_to_ansi,
)
from whisperdeep.events import EVENT_TYPES, Event, EventBus
from whisperdeep.floor import Floor
from whisperdeep.game import Game
from whisperdeep.llm import OfflineAdapter, get_prose_pool
from whisperdeep.render import (
    colorize_frame,
    render_floor,
    render_floor_glyphs,
    render_frame,
)
from whisperdeep.tiles import TileKind
from whisperdeep.world import World


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run_cli(*flags: str, env=None, timeout: int = 60):
    cmd = [sys.executable, "-m", "whisperdeep", *flags]
    e = os.environ.copy()
    if env:
        e.update(env)
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        e.pop(k, None)
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=e,
        timeout=timeout,
    )


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


# ---------------------------------------------------------------------------
# C1 — module imports & layering
# ---------------------------------------------------------------------------


def test_c1_archetypes_module_imports_and_types():
    assert callable(get_archetype)
    assert callable(assign_archetype)
    assert isinstance(ARCHETYPES, tuple) and len(ARCHETYPES) >= 5
    sample = ARCHETYPES[0]
    assert isinstance(sample, DungeonArchetype)
    for field_name in (
        "id",
        "name",
        "glyph_overrides",
        "palette",
        "prose_tag",
        "monster_pool",
    ):
        assert hasattr(sample, field_name)


def test_c17_layering_archetypes_imports_only_stdlib_typing_and_tiles():
    """archetypes.py must NOT import llm / render / panel / chronicle / whisperer."""
    src = (REPO_ROOT / "whisperdeep" / "archetypes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"llm", "render", "panel", "chronicle", "whisperer"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            # whisperdeep.<x> or .<x> from same package
            tail = mod.split(".")[-1]
            assert tail not in forbidden, f"forbidden import: {mod}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                tail = alias.name.split(".")[-1]
                if alias.name.startswith("whisperdeep."):
                    assert tail not in forbidden, f"forbidden import: {alias.name}"


# ---------------------------------------------------------------------------
# C2 — five+ archetypes with required ids
# ---------------------------------------------------------------------------


def test_c2_required_archetype_ids_registered():
    ids = {a.id for a in ARCHETYPES}
    required = {"crypt", "flooded_sewer", "mushroom_forest", "bone_library"}
    assert required.issubset(ids), f"missing required ids: {required - ids}"
    assert len(ids) >= 5


def test_c2_each_archetype_has_required_fields():
    for a in ARCHETYPES:
        assert isinstance(a.name, str) and a.name
        assert isinstance(a.prose_tag, str) and a.prose_tag
        pool = list(a.monster_pool)
        assert len(pool) >= 3
        assert len(set(pool)) == len(pool), f"duplicate monster in {a.id}"
        assert all(isinstance(m, str) and m for m in pool)
        # glyph_overrides overrides at least one of WALL/FLOOR/DOOR
        keys = set(a.glyph_overrides.keys())
        assert keys & {TileKind.WALL, TileKind.FLOOR, TileKind.DOOR}, (
            f"archetype {a.id} overrides none of WALL/FLOOR/DOOR"
        )
        # all override values are exactly one character and not reserved
        for k, v in a.glyph_overrides.items():
            assert isinstance(v, str) and len(v) == 1
            assert v not in RESERVED_GLYPHS, (
                f"archetype {a.id}: override {k}={v!r} collides with reserved glyph"
            )


# ---------------------------------------------------------------------------
# C3 — assign_archetype determinism + diversity
# ---------------------------------------------------------------------------


def test_c3_assign_archetype_is_deterministic():
    a = assign_archetype(1, 0)
    b = assign_archetype(1, 0)
    assert a.id == b.id
    # also verify object identity (since ARCHETYPES is a frozen tuple)
    assert a is b


def test_c3_floor_index_varies_yields_diverse_archetypes():
    ids = {assign_archetype(42, f).id for f in range(8)}
    assert len(ids) >= 2


def test_c3_master_seed_varies_yields_diverse_archetypes():
    ids = {assign_archetype(s, 0).id for s in range(1, 51)}
    assert len(ids) >= 3
    # every returned id must be in the registered set
    for s in range(1, 51):
        a = assign_archetype(s, 0)
        assert a.id in ARCHETYPE_BY_ID
        assert a is not None


def test_c3_secret_archetype_reachable():
    """The secret/rare archetype must be reachable across a small sweep."""
    found = False
    for s in range(1, 200):
        for f in range(0, 8):
            if assign_archetype(s, f).id == SECRET_ID:
                found = True
                break
        if found:
            break
    assert found, f"secret archetype {SECRET_ID!r} not reachable in seed/floor sweep"


# ---------------------------------------------------------------------------
# C4 — Floor.archetype assignment
# ---------------------------------------------------------------------------


def test_c4_world_get_floor_assigns_archetype():
    world = World(master_seed=1, num_floors=3)
    for i in range(3):
        floor = world.get_floor(i)
        assert isinstance(floor.archetype, DungeonArchetype)
        assert floor.archetype.id == assign_archetype(1, i).id


def test_c4_floor_archetype_is_stable_across_calls():
    world = World(master_seed=1, num_floors=3)
    f1 = world.get_floor(0)
    f2 = world.get_floor(0)
    assert f1 is f2
    assert f1.archetype is f2.archetype


def test_c4_existing_floor_api_intact():
    world = World(master_seed=1, num_floors=3)
    f = world.get_floor(0)
    assert hasattr(f, "rooms")
    assert callable(f.walkable_tiles)
    assert callable(f.snapshot)
    assert callable(f.in_bounds)
    assert hasattr(f, "upstairs_pos")
    assert hasattr(f, "downstairs_pos")
    assert isinstance(f.width, int) and isinstance(f.height, int)
    assert hasattr(f, "seed")
    snap = f.snapshot()
    assert isinstance(snap, tuple)
    assert all(isinstance(row, tuple) for row in snap)
    # snapshot should be made of TileKind value strings
    valid_kinds = {tk.value for tk in TileKind}
    flat = {cell for row in snap for cell in row}
    assert flat.issubset(valid_kinds)


# ---------------------------------------------------------------------------
# C5 — glyph variants render + walkability preserved
# ---------------------------------------------------------------------------


def _seed_with_overridden_wall():
    """Find a master_seed where floor 0 has a non-'#' WALL override."""
    for s in range(1, 100):
        a = assign_archetype(s, 0)
        if a.glyph_overrides.get(TileKind.WALL, "#") != "#":
            return s, a
    raise RuntimeError("could not find a seed with overridden WALL")


def test_c5_glyph_variant_renders_in_frame():
    s, archetype = _seed_with_overridden_wall()
    variant_wall = archetype.glyph_overrides[TileKind.WALL]
    game = Game.from_seed(seed=s, whisperer=False)
    frame = render_frame(game)
    assert variant_wall in frame
    # Original '#' should not appear (since override is non-'#').
    assert "#" not in frame
    # Player glyph still present.
    assert "@" in frame


def test_c5_walkability_preserved_under_glyph_overrides():
    s, _ = _seed_with_overridden_wall()
    game = Game.from_seed(seed=s, whisperer=False)
    floor = game.floor
    for y in range(floor.height):
        for x in range(floor.width):
            tile = floor.get(x, y)
            # Variant walls remain non-walkable; variant floors / doors walkable.
            if tile.kind == TileKind.WALL:
                assert tile.walkable is False
            elif tile.kind in (TileKind.FLOOR, TileKind.DOOR, TileKind.UPSTAIRS, TileKind.DOWNSTAIRS):
                assert tile.walkable is True


def test_c5_player_and_stairs_glyphs_are_reserved_across_archetypes():
    for a in ARCHETYPES:
        # No override may use the reserved glyphs (already validated by
        # validate_archetype, but assert here too as a contract check).
        for v in a.glyph_overrides.values():
            assert v not in RESERVED_GLYPHS
        # glyph_for never substitutes upstairs/downstairs.
        assert a.glyph_for(TileKind.UPSTAIRS) == "<"
        assert a.glyph_for(TileKind.DOWNSTAIRS) == ">"


# ---------------------------------------------------------------------------
# C6 — determinism across processes
# ---------------------------------------------------------------------------


def test_c6_same_seed_byte_identical_no_whisperer():
    a = _run_cli("--seed", "1", "--headless", "--no-whisperer")
    b = _run_cli("--seed", "1", "--headless", "--no-whisperer")
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout == b.stdout


def test_c6_different_seed_different_output_no_whisperer():
    a = _run_cli("--seed", "1", "--headless", "--no-whisperer")
    b = _run_cli("--seed", "2", "--headless", "--no-whisperer")
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout != b.stdout


def test_c6_same_seed_byte_identical_with_whisperer():
    a = _run_cli("--seed", "11", "--headless")
    b = _run_cli("--seed", "11", "--headless")
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout == b.stdout


def test_c6_chronicle_byte_identical_with_fixed_timestamp(tmp_path):
    a_path = tmp_path / "a.md"
    b_path = tmp_path / "b.md"
    fixed_ts = "2026-06-12T00:00:00Z"
    ra = _run_cli(
        "--seed", "11",
        "--headless",
        "--chronicle", str(a_path),
        "--chronicle-fixed-timestamp", fixed_ts,
    )
    rb = _run_cli(
        "--seed", "11",
        "--headless",
        "--chronicle", str(b_path),
        "--chronicle-fixed-timestamp", fixed_ts,
    )
    assert ra.returncode == 0 and rb.returncode == 0
    assert a_path.exists() and b_path.exists()
    assert a_path.read_bytes() == b_path.read_bytes()
    # Different seeds should differ.
    c_path = tmp_path / "c.md"
    rc = _run_cli(
        "--seed", "12",
        "--headless",
        "--chronicle", str(c_path),
        "--chronicle-fixed-timestamp", fixed_ts,
    )
    assert rc.returncode == 0 and c_path.exists()
    assert a_path.read_bytes() != c_path.read_bytes()


# ---------------------------------------------------------------------------
# C7 — palette descriptor + ANSI opt-in
# ---------------------------------------------------------------------------


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_c7_each_palette_has_required_keys_and_valid_values():
    for a in ARCHETYPES:
        for key in REQUIRED_PALETTE_KEYS:
            assert key in a.palette, f"{a.id} missing palette key {key}"
            v = a.palette[key]
            ok = (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255) or (
                isinstance(v, str) and bool(_HEX_RE.match(v))
            )
            assert ok, f"{a.id}.palette[{key}] = {v!r} is not valid"


def test_c7_palette_to_ansi_returns_escape_or_empty():
    a = ARCHETYPES[0]
    seq = palette_to_ansi(a.palette, "wall_fg")
    assert seq == "" or (seq.startswith("\x1b") and seq.endswith("m"))
    # unknown key returns empty
    assert palette_to_ansi(a.palette, "this_key_does_not_exist") == ""


def test_c7_render_frame_emits_no_ansi_by_default():
    game = Game.from_seed(seed=1, whisperer=False)
    frame = render_frame(game)
    assert "\x1b" not in frame


def test_c7_colorize_frame_emits_ansi_and_strips_to_render_frame():
    game = Game.from_seed(seed=1, whisperer=False)
    plain = render_frame(game)
    coloured = colorize_frame(game)
    assert "\x1b" in coloured
    # Stripping ANSI must give the same text (modulo no other changes).
    assert _strip_ansi(coloured) == plain


# ---------------------------------------------------------------------------
# C8 — archetype-tagged prose pool
# ---------------------------------------------------------------------------


def test_c8_pool_has_archetype_tagged_entries_per_archetype():
    pool = get_prose_pool()
    for a in ARCHETYPES:
        room_key = f"room_entered.{a.id}"
        first_key = f"first_sight.{a.id}"
        assert room_key in pool, f"missing pool key {room_key}"
        assert first_key in pool, f"missing pool key {first_key}"
        assert len(set(pool[room_key])) >= 4, (
            f"{room_key}: need >= 4 distinct entries"
        )
        assert len(set(pool[first_key])) >= 4, (
            f"{first_key}: need >= 4 distinct entries"
        )
        for entry in pool[room_key]:
            assert isinstance(entry, str) and entry
        for entry in pool[first_key]:
            assert isinstance(entry, str) and entry


def test_c8_generic_pools_not_regressed():
    pool = get_prose_pool()
    for key in (
        "room_entered",
        "first_sight",
        "run_started",
        "run_ended",
        "descended",
        "killed_monster",
        "low_hp",
        "found_item",
        "entered_room",
        "epitaph",
    ):
        assert key in pool, f"missing generic pool {key!r}"
        assert len(set(pool[key])) >= 8, f"{key} pool regressed below 8 entries"


def test_c8_archetype_aware_selection_for_room_entered():
    """Force two different archetypes; spawn-room whisper should differ
    according to the archetype tag."""
    g_crypt = Game.from_seed(seed=1, whisperer=True, forced_archetype="crypt")
    g_mush = Game.from_seed(seed=1, whisperer=True, forced_archetype="mushroom_forest")
    pool = get_prose_pool()
    crypt_entries = set(pool["room_entered.crypt"])
    mush_entries = set(pool["room_entered.mushroom_forest"])

    def first_room_text(g):
        for w in g.whisperer.dump():
            if w["source_event_type"] == "room_entered":
                return w["text"]
        return None

    crypt_text = first_room_text(g_crypt)
    mush_text = first_room_text(g_mush)
    assert crypt_text in crypt_entries
    assert mush_text in mush_entries
    assert crypt_text != mush_text


# ---------------------------------------------------------------------------
# C9 — whispers carry archetype id
# ---------------------------------------------------------------------------


def test_c9_whispers_carry_archetype_field():
    g = Game.from_seed(seed=1, whisperer=True)
    g.observe_kind("skitterer")
    dump = g.whisperer.dump()
    assert dump, "expected at least one whisper"
    for w in dump:
        assert "archetype" in w
        # When source_floor is known, archetype must equal the floor's archetype id.
        sf = w.get("source_floor")
        if sf is not None:
            expected = g.world.get_floor(sf).archetype.id
            assert w["archetype"] == expected, (
                f"whisper archetype mismatch: {w['archetype']!r} vs {expected!r} for floor {sf}"
            )


def test_c9_dump_whispers_cli_carries_archetype(tmp_path):
    out_path = tmp_path / "whispers.json"
    res = _run_cli(
        "--seed", "1",
        "--headless",
        "--dump-whispers", str(out_path),
    )
    assert res.returncode == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data
    for w in data:
        assert "archetype" in w


# ---------------------------------------------------------------------------
# C10 — Floor snapshot kind/glyph distinction
# ---------------------------------------------------------------------------


def test_c10_floor_snapshot_kinds_unchanged():
    world = World(master_seed=1, num_floors=3)
    f = world.get_floor(0)
    snap = f.snapshot()
    valid_kinds = {tk.value for tk in TileKind}
    for row in snap:
        for cell in row:
            assert cell in valid_kinds


def test_c10_snapshot_glyphs_reflects_overrides():
    s, archetype = _seed_with_overridden_wall()
    world = World(master_seed=s, num_floors=3)
    f = world.get_floor(0)
    snap = f.snapshot()
    glyph_snap = f.snapshot_glyphs()
    # Same shape.
    assert len(snap) == len(glyph_snap)
    for r1, r2 in zip(snap, glyph_snap):
        assert len(r1) == len(r2)
    # Glyph snapshot uses single-character strings.
    flat = {c for row in glyph_snap for c in row}
    assert all(isinstance(c, str) and len(c) == 1 for c in flat)
    variant_wall = archetype.glyph_overrides[TileKind.WALL]
    # Variant wall should appear at least once.
    assert any(variant_wall in row for row in glyph_snap)
    # render_floor_glyphs (top-level helper) returns the same shape.
    via_helper = render_floor_glyphs(f)
    assert via_helper == glyph_snap


def test_c10_render_floor_uses_overrides():
    s, archetype = _seed_with_overridden_wall()
    world = World(master_seed=s, num_floors=3)
    f = world.get_floor(0)
    rendered = render_floor(f)
    variant_wall = archetype.glyph_overrides[TileKind.WALL]
    assert variant_wall in rendered


# ---------------------------------------------------------------------------
# C11 — CLI flags
# ---------------------------------------------------------------------------


def test_c11_help_mentions_new_flags():
    res = _run_cli("--help")
    assert res.returncode == 0
    assert "--archetype" in res.stdout
    assert "--list-archetypes" in res.stdout


def test_c11_list_archetypes_prints_all():
    res = _run_cli("--list-archetypes")
    assert res.returncode == 0
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert len(lines) >= 5
    for required_id in ("crypt", "flooded_sewer", "mushroom_forest", "bone_library", SECRET_ID):
        assert any(required_id in ln for ln in lines), f"missing id {required_id} in --list-archetypes"


def test_c11_archetype_force_changes_glyphs():
    crypt_a = get_archetype("crypt")
    mush_a = get_archetype("mushroom_forest")
    crypt_wall = crypt_a.glyph_overrides[TileKind.WALL]
    mush_wall = mush_a.glyph_overrides[TileKind.WALL]
    res_c = _run_cli("--seed", "1", "--headless", "--no-whisperer", "--archetype", "crypt")
    res_m = _run_cli("--seed", "1", "--headless", "--no-whisperer", "--archetype", "mushroom_forest")
    assert res_c.returncode == 0
    assert res_m.returncode == 0
    assert crypt_wall in res_c.stdout
    assert mush_wall in res_m.stdout
    if crypt_wall != mush_wall:
        assert mush_wall not in res_c.stdout or crypt_wall not in res_m.stdout


def test_c11_unknown_archetype_id_errors():
    res = _run_cli(
        "--seed", "1",
        "--headless",
        "--archetype", "not_a_real_archetype",
    )
    assert res.returncode != 0
    msg = (res.stderr or "") + (res.stdout or "")
    assert "not_a_real_archetype" in msg
    # The error message should hint at the valid ids (the easiest hint is to
    # mention any of them or point at --list-archetypes).
    assert (
        "--list-archetypes" in msg
        or "crypt" in msg
        or "Valid ids" in msg
    )


# ---------------------------------------------------------------------------
# C12 — edge cases
# ---------------------------------------------------------------------------


def test_c12_empty_glyph_overrides_falls_back_to_defaults():
    test_arche = DungeonArchetype(
        id="_test_empty",
        name="Test Empty",
        glyph_overrides={},
        palette={
            "wall_fg": 240, "floor_fg": 244, "door_fg": 178,
            "upstairs_fg": 252, "downstairs_fg": 252, "player_fg": 230,
        },
        prose_tag="_test",
        monster_pool=("a", "b", "c"),
    )
    f = Floor(20, 5)
    # Punch in some kinds explicitly.
    from whisperdeep import tiles as tile_mod
    f.set(1, 1, tile_mod.floor())
    f.set(2, 1, tile_mod.door())
    f.archetype = test_arche
    rendered = render_floor(f)
    rows = rendered.split("\n")
    assert rows[0][0] == "#"  # default wall
    assert rows[1][1] == "."  # default floor
    assert rows[1][2] == "+"  # default door


def test_c12_partial_overrides_only_door():
    test_arche = DungeonArchetype(
        id="_test_door_only",
        name="Test Door-Only",
        glyph_overrides={TileKind.DOOR: "/"},
        palette={
            "wall_fg": 240, "floor_fg": 244, "door_fg": 178,
            "upstairs_fg": 252, "downstairs_fg": 252, "player_fg": 230,
        },
        prose_tag="_test",
        monster_pool=("a", "b", "c"),
    )
    f = Floor(20, 5)
    from whisperdeep import tiles as tile_mod
    f.set(1, 1, tile_mod.floor())
    f.set(2, 1, tile_mod.door())
    f.archetype = test_arche
    rendered = render_floor(f)
    rows = rendered.split("\n")
    assert rows[0][0] == "#"  # default wall (not overridden)
    assert rows[1][1] == "."  # default floor (not overridden)
    assert rows[1][2] == "/"  # overridden door


def test_c12_palette_to_ansi_unknown_key_returns_empty_string():
    a = ARCHETYPES[0]
    assert palette_to_ansi(a.palette, "totally_made_up_key") == ""
    # Mapping with a bogus value also yields empty rather than raising.
    assert palette_to_ansi({"wall_fg": "not-a-hex"}, "wall_fg") == ""


def test_c12_floor_with_no_archetype_renders_with_defaults():
    f = Floor(20, 5)
    from whisperdeep import tiles as tile_mod
    f.set(1, 1, tile_mod.floor())
    f.set(2, 1, tile_mod.door())
    # archetype intentionally None.
    assert f.archetype is None
    rendered = render_floor(f)
    rows = rendered.split("\n")
    assert rows[0][0] == "#"
    assert rows[1][1] == "."
    assert rows[1][2] == "+"


# ---------------------------------------------------------------------------
# C13 — regression of prior sprints
# ---------------------------------------------------------------------------


def test_c13_event_types_superset_preserved():
    required = {
        "run_started", "run_ended", "entered_room", "killed_monster",
        "low_hp", "found_item", "descended", "first_sight", "room_entered",
        "epitaph",
    }
    assert required.issubset(set(EVENT_TYPES))


def test_c13_no_whisperer_path_still_works():
    res = _run_cli("--seed", "1", "--headless", "--no-whisperer")
    assert res.returncode == 0
    assert "@" in res.stdout


# ---------------------------------------------------------------------------
# C16 — documentation sanity check
# ---------------------------------------------------------------------------


def test_c16_docs_mention_sprint_11_and_archetypes():
    docs = (REPO_ROOT / "docs" / "whisperdeep.md").read_text(encoding="utf-8")
    # Sprint 11 banner / status section.
    assert "Sprint 11" in docs
    # Archetypes & Palettes section.
    assert "Archetypes" in docs and "Palette" in docs
    # All five required ids documented.
    for required_id in ("crypt", "flooded_sewer", "mushroom_forest", "bone_library", SECRET_ID):
        assert required_id in docs
    # New CLI flags documented.
    assert "--archetype" in docs
    assert "--list-archetypes" in docs
    # Determinism guarantee + colour-opt-in note.
    assert "deterministic" in docs.lower() or "determinism" in docs.lower()
    assert "colorize_frame" in docs
