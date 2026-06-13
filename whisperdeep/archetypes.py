"""Themed dungeon archetypes & palettes (Sprint 11).

Each *archetype* is a closed-set thematic flavour for a floor. It bundles:

* an ``id`` (machine name, e.g. ``"crypt"``) and ``name`` (display);
* a ``glyph_overrides`` mapping ``TileKind -> str`` that swaps the per-cell
  glyph used by the renderer (defaults from Sprint 1/2 are preserved when an
  override is absent);
* a ``palette`` descriptor: a mapping of role keys (``wall_fg``,
  ``floor_fg``, ``door_fg``, ``upstairs_fg``, ``downstairs_fg``,
  ``player_fg``, plus optional ``panel_fg`` / ``panel_bg``) to either a
  256-color xterm index (``int`` in ``[0, 255]``) OR a ``"#rrggbb"`` hex
  string;
* a ``prose_tag`` -- a short string that the Whisperer's offline prose pool
  is indexed by (e.g., ``room_entered.crypt``);
* a ``monster_pool`` -- a list of monster-kind strings flavour-appropriate
  to this archetype. Sprint 11 stores this as metadata only; actual
  spawning lands in Sprint 5 ('Monsters & AI').

Layering invariants (Sprint 11):

* This module imports **only** stdlib + ``typing`` + :mod:`whisperdeep.tiles`
  for ``TileKind``. It never imports from ``whisperdeep.llm``,
  ``whisperdeep.render``, ``whisperdeep.panel``, ``whisperdeep.chronicle``,
  or ``whisperdeep.whisperer``.
* The ``TileKind`` enum is unchanged from Sprint 1; archetypes only override
  the *glyph* that a tile renders as. Walkability and the kind-snapshot
  contract (``Floor.snapshot()``) are preserved.

Determinism: :func:`assign_archetype` is a pure function of
``(master_seed, floor_index)``; the same arguments always return the same
:class:`DungeonArchetype` instance from :data:`ARCHETYPES`.

ANSI is produced only on demand via :func:`palette_to_ansi`. The
:func:`whisperdeep.render.render_frame` helper continues to emit zero ESC
characters by default; callers wanting colour must use the new
:func:`whisperdeep.render.colorize_frame` helper (which delegates here).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from .tiles import TileKind


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


PaletteValue = Union[int, str]
PaletteMapping = Mapping[str, PaletteValue]
GlyphOverrides = Mapping[TileKind, str]


# Roles every archetype palette must define. Tests rely on these keys.
REQUIRED_PALETTE_KEYS: Tuple[str, ...] = (
    "wall_fg",
    "floor_fg",
    "door_fg",
    "upstairs_fg",
    "downstairs_fg",
    "player_fg",
)

# Player / stair glyphs are reserved across all archetypes -- they are
# the player's anchor and the navigation affordances. Archetypes MUST NOT
# override them; the renderer also enforces this defensively.
RESERVED_GLYPHS: Tuple[str, ...] = ("@", "<", ">")

# Sprint-1/2 default glyphs (recovered from tiles.py). Used by render
# helpers when an archetype does not override a kind, or when a Floor was
# defensively constructed without an archetype.
DEFAULT_GLYPHS: Dict[TileKind, str] = {
    TileKind.WALL: "#",
    TileKind.FLOOR: ".",
    TileKind.DOOR: "+",
    TileKind.UPSTAIRS: "<",
    TileKind.DOWNSTAIRS: ">",
}


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class DungeonArchetype:
    """Immutable thematic descriptor for a dungeon floor.

    Construct via the public registry; callers may construct one ad-hoc for
    tests / edge cases (see :func:`whisperdeep.archetypes.DungeonArchetype`).
    Frozen so two Floors sharing the same archetype share the same
    ``__hash__`` and survive identity-equality checks across the engine.
    """

    id: str
    name: str
    glyph_overrides: GlyphOverrides = field(default_factory=dict)
    palette: PaletteMapping = field(default_factory=dict)
    prose_tag: str = ""
    monster_pool: Tuple[str, ...] = field(default_factory=tuple)
    rare: bool = False
    weight: int = 10

    def glyph_for(self, kind: TileKind) -> str:
        """Return the glyph this archetype renders for ``kind``.

        Falls back to the Sprint-1/2 default when the archetype does not
        explicitly override ``kind``. Reserved kinds (UPSTAIRS, DOWNSTAIRS)
        are never substituted regardless of what an archetype says, so the
        movement affordances remain visually unambiguous.
        """
        if kind in (TileKind.UPSTAIRS, TileKind.DOWNSTAIRS):
            return DEFAULT_GLYPHS[kind]
        glyph = self.glyph_overrides.get(kind) if self.glyph_overrides else None
        if not glyph:
            return DEFAULT_GLYPHS.get(kind, "?")
        return glyph


# ---------------------------------------------------------------------------
# Built-in archetype registry
# ---------------------------------------------------------------------------


def _build_archetypes() -> Tuple[DungeonArchetype, ...]:
    """Construct the closed-set registry of Sprint-11 archetypes.

    The data lives in code (rather than a separate JSON resource) to keep
    the layering crisp and the import deterministic. A JSON companion is
    documented but optional; this implementation prefers a single source of
    truth.
    """
    return (
        DungeonArchetype(
            id="crypt",
            name="Crypt of Hollow Saints",
            glyph_overrides={
                TileKind.WALL: "#",
                TileKind.FLOOR: ".",
                TileKind.DOOR: "+",
            },
            palette={
                "wall_fg": 240,
                "floor_fg": 244,
                "door_fg": 178,
                "upstairs_fg": 252,
                "downstairs_fg": 252,
                "player_fg": "#f4d35e",
                "panel_fg": 250,
                "panel_bg": 234,
            },
            prose_tag="crypt",
            monster_pool=("ghoul", "wight", "crypt-rat", "tomb-spider"),
            weight=20,
        ),
        DungeonArchetype(
            id="flooded_sewer",
            name="The Flooded Sewer",
            glyph_overrides={
                TileKind.WALL: "=",
                TileKind.FLOOR: ",",
                TileKind.DOOR: "/",
            },
            palette={
                "wall_fg": 100,
                "floor_fg": 30,
                "door_fg": 94,
                "upstairs_fg": 252,
                "downstairs_fg": 252,
                "player_fg": "#f4d35e",
                "panel_fg": 250,
                "panel_bg": 234,
            },
            prose_tag="flooded_sewer",
            monster_pool=("sewer-toad", "drowned", "rust-eel", "leech"),
            weight=20,
        ),
        DungeonArchetype(
            id="mushroom_forest",
            name="The Mushroom Forest",
            glyph_overrides={
                TileKind.WALL: "%",
                TileKind.FLOOR: '"',
                TileKind.DOOR: "+",
            },
            palette={
                "wall_fg": 92,
                "floor_fg": 70,
                "door_fg": 130,
                "upstairs_fg": 252,
                "downstairs_fg": 252,
                "player_fg": "#f4d35e",
                "panel_fg": 250,
                "panel_bg": 234,
            },
            prose_tag="mushroom_forest",
            monster_pool=("spore-walker", "myconid", "fungal-rat", "mold-imp"),
            weight=20,
        ),
        DungeonArchetype(
            id="bone_library",
            name="The Bone Library",
            glyph_overrides={
                TileKind.WALL: ":",
                TileKind.FLOOR: ".",
                TileKind.DOOR: "I",
            },
            palette={
                "wall_fg": 230,
                "floor_fg": 223,
                "door_fg": 137,
                "upstairs_fg": 252,
                "downstairs_fg": 252,
                "player_fg": "#f4d35e",
                "panel_fg": 250,
                "panel_bg": 234,
            },
            prose_tag="bone_library",
            monster_pool=("scrivener", "bone-scribe", "ink-wraith", "vellum-moth"),
            weight=20,
        ),
        DungeonArchetype(
            id="whisperhall",
            name="The Whisperhall (rare)",
            glyph_overrides={
                TileKind.WALL: "&",
                TileKind.FLOOR: "`",
                TileKind.DOOR: "|",
            },
            palette={
                "wall_fg": 54,
                "floor_fg": 60,
                "door_fg": 207,
                "upstairs_fg": 252,
                "downstairs_fg": 252,
                "player_fg": "#f4d35e",
                "panel_fg": 207,
                "panel_bg": 17,
            },
            prose_tag="whisperhall",
            monster_pool=("echo", "listening-mouth", "name-eater", "stillness"),
            rare=True,
            weight=2,
        ),
    )


ARCHETYPES: Tuple[DungeonArchetype, ...] = _build_archetypes()
ARCHETYPE_BY_ID: Dict[str, DungeonArchetype] = {a.id: a for a in ARCHETYPES}

# The ids the contract names explicitly. Useful for documentation.
REQUIRED_IDS: Tuple[str, ...] = (
    "crypt",
    "flooded_sewer",
    "mushroom_forest",
    "bone_library",
)
SECRET_ID: str = "whisperhall"


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def get_archetype(archetype_id: str) -> DungeonArchetype:
    """Return the registered archetype with id ``archetype_id``.

    Raises :class:`KeyError` if no such archetype is registered.
    """
    try:
        return ARCHETYPE_BY_ID[archetype_id]
    except KeyError as exc:
        raise KeyError(
            f"Unknown archetype id: {archetype_id!r}. "
            f"Valid ids: {sorted(ARCHETYPE_BY_ID)}"
        ) from exc


def list_archetype_ids() -> Tuple[str, ...]:
    """Return the tuple of registered archetype ids in registration order."""
    return tuple(a.id for a in ARCHETYPES)


def assign_archetype(master_seed: int, floor_index: int) -> DungeonArchetype:
    """Deterministically pick an archetype for ``(master_seed, floor_index)``.

    The implementation hashes the pair via SHA-256 and uses the resulting
    integer to draw an archetype out of a weighted distribution. The same
    arguments always return the same archetype instance (object identity is
    stable across calls because ``ARCHETYPES`` is a frozen tuple of frozen
    dataclasses).

    Properties:

    * Pure / referentially transparent.
    * Diverse: a small sweep across ``floor_index`` for one ``master_seed``
      typically yields >= 2 distinct ids.
    * The rare archetype (low weight) is reachable on at least some
      ``(seed, floor)`` combination -- tests verify this on a small sweep.
    """
    if not isinstance(master_seed, int):
        master_seed = int(master_seed)
    if not isinstance(floor_index, int):
        floor_index = int(floor_index)
    digest = hashlib.sha256(
        f"whisperdeep:archetype:{master_seed}:{floor_index}".encode("utf-8")
    ).digest()
    # Use the first 8 bytes as a uint64 for the weighted draw. SHA-256 is
    # overkill but it's stdlib, deterministic across platforms, and avoids
    # any dependence on Python's hash() randomization.
    raw = int.from_bytes(digest[:8], "big", signed=False)
    weights = [max(1, a.weight) for a in ARCHETYPES]
    total = sum(weights)
    pick = raw % total
    cumulative = 0
    for arche, w in zip(ARCHETYPES, weights):
        cumulative += w
        if pick < cumulative:
            return arche
    # Pragma: unreachable because pick < total = sum(weights).
    return ARCHETYPES[-1]  # pragma: no cover


# ---------------------------------------------------------------------------
# Palette helpers
# ---------------------------------------------------------------------------


def _is_valid_xterm_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255


def _is_valid_hex(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX_RE.match(value))


def _hex_to_rgb(value: str) -> Tuple[int, int, int]:
    """Parse a ``"#rrggbb"`` string into ``(r, g, b)`` ints."""
    s = value.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def palette_value_to_ansi(value: Any) -> str:
    """Convert a single palette value to an ANSI SGR foreground sequence.

    Returns ``''`` (empty string) for unknown / invalid values rather than
    raising; callers should be tolerant. Integer values are emitted as
    256-color (``\\x1b[38;5;<n>m``); hex strings as truecolor
    (``\\x1b[38;2;<r>;<g>;<b>m``).
    """
    if _is_valid_xterm_index(value):
        return f"\x1b[38;5;{int(value)}m"
    if _is_valid_hex(value):
        r, g, b = _hex_to_rgb(value)  # type: ignore[arg-type]
        return f"\x1b[38;2;{r};{g};{b}m"
    return ""


def palette_to_ansi(palette: PaletteMapping, key: str) -> str:
    """Return an ANSI-foreground escape sequence for ``palette[key]``.

    * If ``palette`` is missing ``key``, returns ``''`` (empty).
    * If the value is not a recognized format (int 0-255 or
      ``"#rrggbb"``), returns ``''`` (empty).
    * Otherwise returns a string starting with ``\\x1b[`` and ending with
      ``m``.

    This helper is defensive on purpose: render code calls it on every
    cell and must NEVER raise just because a palette is missing a key.
    """
    if not isinstance(palette, Mapping):
        return ""
    if key not in palette:
        return ""
    return palette_value_to_ansi(palette[key])


ANSI_RESET: str = "\x1b[0m"


# Map a TileKind / role to the palette key used for its foreground colour.
# The render layer can pass a TileKind and let this helper select the right
# palette key without growing the public surface of TileKind.
_KIND_TO_PALETTE_KEY: Dict[TileKind, str] = {
    TileKind.WALL: "wall_fg",
    TileKind.FLOOR: "floor_fg",
    TileKind.DOOR: "door_fg",
    TileKind.UPSTAIRS: "upstairs_fg",
    TileKind.DOWNSTAIRS: "downstairs_fg",
}


def palette_key_for_kind(kind: TileKind) -> str:
    return _KIND_TO_PALETTE_KEY.get(kind, "")


# ---------------------------------------------------------------------------
# Validation (exposed for tests / docs)
# ---------------------------------------------------------------------------


def validate_archetype(arche: DungeonArchetype) -> None:
    """Raise ValueError if ``arche`` is malformed; otherwise return None.

    Checks that:
    * id and name are non-empty strings,
    * prose_tag is a non-empty string,
    * monster_pool has >= 3 distinct non-empty entries,
    * glyph_overrides maps TileKind keys to single-character strings,
    * none of the override values is one of the reserved glyphs,
    * palette has all required keys with valid 256/hex values.
    """
    if not isinstance(arche.id, str) or not arche.id:
        raise ValueError("archetype id must be a non-empty string")
    if not isinstance(arche.name, str) or not arche.name:
        raise ValueError(f"archetype {arche.id}: name must be a non-empty string")
    if not isinstance(arche.prose_tag, str) or not arche.prose_tag:
        raise ValueError(f"archetype {arche.id}: prose_tag must be a non-empty string")
    pool = list(arche.monster_pool)
    if len(set(pool)) < 3 or any((not isinstance(m, str)) or not m for m in pool):
        raise ValueError(
            f"archetype {arche.id}: monster_pool must have >= 3 distinct non-empty strings"
        )
    if arche.glyph_overrides:
        for k, v in arche.glyph_overrides.items():
            if not isinstance(k, TileKind):
                raise ValueError(
                    f"archetype {arche.id}: glyph_overrides keys must be TileKind"
                )
            if not isinstance(v, str) or len(v) != 1:
                raise ValueError(
                    f"archetype {arche.id}: glyph override for {k} must be exactly one character"
                )
            if v in RESERVED_GLYPHS:
                raise ValueError(
                    f"archetype {arche.id}: glyph override for {k} collides with reserved glyph {v!r}"
                )
    for key in REQUIRED_PALETTE_KEYS:
        if key not in arche.palette:
            raise ValueError(f"archetype {arche.id}: palette missing key {key!r}")
        v = arche.palette[key]
        if not (_is_valid_xterm_index(v) or _is_valid_hex(v)):
            raise ValueError(
                f"archetype {arche.id}: palette[{key!r}] must be int 0-255 or '#rrggbb'"
            )


# Validate the built-in registry at import time so a malformed archetype
# fails loudly rather than at first render.
for _a in ARCHETYPES:
    validate_archetype(_a)


# ---------------------------------------------------------------------------
# CLI helper -- summary lines for --list-archetypes
# ---------------------------------------------------------------------------


def archetype_summary_line(arche: DungeonArchetype) -> str:
    """Return a one-line human-readable summary used by ``--list-archetypes``."""
    overrides = " ".join(
        f"{k.value}={v}" for k, v in sorted(
            (arche.glyph_overrides or {}).items(), key=lambda kv: kv[0].value
        )
    )
    return (
        f"{arche.id:<18} | {arche.name:<30} | "
        f"glyphs: {overrides or '(defaults)':<28} | "
        f"monsters: {len(arche.monster_pool)}"
    )


__all__ = [
    "DungeonArchetype",
    "ARCHETYPES",
    "ARCHETYPE_BY_ID",
    "REQUIRED_IDS",
    "REQUIRED_PALETTE_KEYS",
    "RESERVED_GLYPHS",
    "DEFAULT_GLYPHS",
    "SECRET_ID",
    "ANSI_RESET",
    "get_archetype",
    "list_archetype_ids",
    "assign_archetype",
    "palette_to_ansi",
    "palette_value_to_ansi",
    "palette_key_for_kind",
    "validate_archetype",
    "archetype_summary_line",
]
