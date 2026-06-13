"""Sprint 12 — Keybindings registry & help-overlay formatter.

This module provides a small, dependency-free registry mapping
**named commands** (e.g. ``move_west``, ``descend``, ``quit``) to one
or more **input keys** (single-character keys like ``h``, ``>``, ``?``,
or ANSI arrow-key escape sequences like ``"\\x1b[A"``). It also
provides JSON load/save helpers and a plain-text help-overlay
formatter.

The registry is consumed by the interactive CLI loop so that players
can rebind keys via ``--keys PATH`` (or the ``WHISPERDEEP_KEYS``
environment variable) without code changes.

Layering invariants:

* This module imports **only** stdlib + ``typing``.
* It does NOT import :mod:`whisperdeep.llm`, :mod:`whisperdeep.render`,
  :mod:`whisperdeep.panel`, or :mod:`whisperdeep.whisperer`.

Documented behaviour:

* Loading a non-existent path returns the DEFAULT bindings without
  raising.
* Loading a malformed JSON file raises :class:`ValueError`.
* Loading a JSON file that references unknown command names raises
  :class:`ValueError` naming the offending entry.
* Duplicate keys in a bindings dict are resolved last-wins (this is
  the natural JSON behaviour: `json.loads` keeps the last value when
  parsing duplicate object keys).

Audio is OPT-IN and OFF by default; this module is unrelated to
audio. See :mod:`whisperdeep.audio` for the audio-adapter layer.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Canonical command names
# ---------------------------------------------------------------------------

#: Tuple of all canonical command names supported by Whisperdeep's
#: interactive loop. Configuration files referencing any other command
#: name are rejected with a ``ValueError`` mentioning the bad entry.
COMMANDS: Tuple[str, ...] = (
    "move_west",
    "move_east",
    "move_north",
    "move_south",
    "move_nw",
    "move_ne",
    "move_sw",
    "move_se",
    "wait",
    "descend",
    "ascend",
    "quit",
    "help",
    "redraw",
    "summary",
    "bindings",
)


_COMMAND_SET = frozenset(COMMANDS)


# Default key->command mapping. Includes both vi-keys (h/j/k/l + y/u/b/n)
# AND the ANSI arrow-key escape sequences so the existing terminal
# input loop keeps working out of the box.
_DEFAULT_BINDINGS: Dict[str, str] = {
    # vi cardinal moves
    "h": "move_west",
    "l": "move_east",
    "k": "move_north",
    "j": "move_south",
    # vi diagonals
    "y": "move_nw",
    "u": "move_ne",
    "b": "move_sw",
    "n": "move_se",
    # arrow-key escape sequences (ANSI / xterm)
    "\x1b[D": "move_west",
    "\x1b[C": "move_east",
    "\x1b[A": "move_north",
    "\x1b[B": "move_south",
    # stairs / wait / quit / help
    ".": "wait",
    ">": "descend",
    "<": "ascend",
    "q": "quit",
    "?": "help",
    # optional
    "\x0c": "redraw",  # Ctrl-L
}


@dataclass
class KeyBindings:
    """A keybindings registry mapping keys to canonical command names.

    Public mutators (``bind`` / ``unbind``) raise :class:`ValueError` for
    unknown command names so a typo never silently no-ops.
    """

    mapping: Dict[str, str] = field(default_factory=dict)

    # ---- factory --------------------------------------------------------
    @classmethod
    def DEFAULTS_KB(cls) -> "KeyBindings":
        """Return a fresh KeyBindings populated with the default mapping."""
        return cls(mapping=dict(_DEFAULT_BINDINGS))

    @classmethod
    def from_mapping(cls, mapping: Dict[str, str]) -> "KeyBindings":
        kb = cls(mapping={})
        for k, v in mapping.items():
            kb.bind(v, k)
        return kb

    # DEFAULTS as a class-level property-like view returning a copy.
    @classmethod
    @property
    def DEFAULTS(cls) -> Dict[str, str]:  # type: ignore[misc]
        # Note: classmethod+property is supported on 3.9..3.11 via this idiom
        # but is removed on some 3.12 stable revisions. We expose
        # DEFAULTS_KB() (a method) as the canonical access path; this attr
        # remains as a forgiving copy.
        return dict(_DEFAULT_BINDINGS)

    # ---- core API -------------------------------------------------------
    def bind(self, command: str, key: str) -> None:
        """Bind ``key`` to ``command``. Raises ValueError for unknown commands."""
        if command not in _COMMAND_SET:
            raise ValueError(
                f"unknown command: {command!r}. "
                f"Valid commands: {', '.join(COMMANDS)}"
            )
        if not isinstance(key, str) or key == "":
            raise ValueError("key must be a non-empty string")
        self.mapping[key] = command

    def unbind(self, key: str) -> None:
        """Remove the binding for ``key`` (no-op if not bound)."""
        self.mapping.pop(key, None)

    def command_for(self, key: str) -> Optional[str]:
        """Return the command bound to ``key``, or None if unbound."""
        return self.mapping.get(key)

    def keys_for(self, command: str) -> Tuple[str, ...]:
        """Return all keys bound to ``command`` (sorted for determinism)."""
        return tuple(sorted(k for k, v in self.mapping.items() if v == command))

    def to_dict(self) -> Dict[str, str]:
        return dict(self.mapping)


# Expose DEFAULTS as a module-level dict for tests and tooling that just
# want the mapping without instantiating.
DEFAULTS: Dict[str, str] = dict(_DEFAULT_BINDINGS)


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def _resolve_path(path: Optional[str]) -> Optional[str]:
    if path is None:
        env = os.environ.get("WHISPERDEEP_KEYS")
        if env:
            return env
        return None
    return path


def load_keybindings(path: Optional[str] = None) -> KeyBindings:
    """Load a KeyBindings from ``path`` (or ``$WHISPERDEEP_KEYS``).

    Returns a default KeyBindings when the path is missing entirely or
    when the file does not exist on disk. Malformed JSON raises
    :class:`ValueError`. Files referencing unknown command names raise
    :class:`ValueError` naming the offending entry.
    """
    p = _resolve_path(path)
    if p is None:
        return KeyBindings.DEFAULTS_KB()
    if not os.path.exists(p):
        return KeyBindings.DEFAULTS_KB()
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"keybindings file {p!r} is not valid JSON: {exc}")
    bindings = data.get("bindings") if isinstance(data, dict) else None
    if not isinstance(bindings, dict):
        raise ValueError(
            f"keybindings file {p!r} has no top-level 'bindings' object"
        )
    kb = KeyBindings(mapping={})
    for key, command in bindings.items():
        if not isinstance(command, str):
            raise ValueError(
                f"keybindings file {p!r}: binding for key {key!r} is not a string"
            )
        if command not in _COMMAND_SET:
            raise ValueError(
                f"keybindings file {p!r}: unknown command name {command!r} for key {key!r}"
            )
        kb.mapping[key] = command
    return kb


def save_keybindings(kb: KeyBindings, path: str) -> str:
    """Write ``kb`` to ``path`` as a JSON object with a ``bindings`` key."""
    payload = {"bindings": dict(kb.mapping), "version": 1}
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return path


# ---------------------------------------------------------------------------
# Help-overlay formatter
# ---------------------------------------------------------------------------


def _display_key(k: str) -> str:
    """Return a printable representation for a key string.

    Bare printable keys are returned as-is. ANSI escape sequences and
    other non-printable strings are replaced with a documented
    placeholder (``<ESC[A>`` etc.) so the output stays plain ASCII.
    """
    if not k:
        return "''"
    if k == "\x1b[A":
        return "<Up>"
    if k == "\x1b[B":
        return "<Down>"
    if k == "\x1b[C":
        return "<Right>"
    if k == "\x1b[D":
        return "<Left>"
    if k == "\x0c":
        return "<Ctrl-L>"
    if k == " ":
        return "<Space>"
    if any(ord(c) < 0x20 or ord(c) > 0x7e for c in k):
        return "<" + k.encode("unicode_escape").decode("ascii") + ">"
    return k


def format_help_overlay(kb: KeyBindings) -> str:
    """Return a multi-line plain-text help overlay listing all commands.

    The output is plain ASCII (no ANSI escapes), starts with a clear
    header line, and lists every command in :data:`COMMANDS` along with
    every key bound to it (or ``(unbound)`` if no key maps to it).
    """
    lines: List[str] = []
    lines.append("# Whisperdeep keybindings")
    lines.append("=" * 40)
    width = max(len(c) for c in COMMANDS) + 2
    for cmd in COMMANDS:
        keys = kb.keys_for(cmd)
        if keys:
            shown = ", ".join(_display_key(k) for k in keys)
        else:
            shown = "(unbound)"
        lines.append(f"  {cmd:<{width}} {shown}")
    lines.append("")
    lines.append("Type ':help' or '?' in-game to see this overlay.")
    lines.append("Use ':bind <command> <key>' to rebind at runtime.")
    return "\n".join(lines)


__all__ = [
    "COMMANDS",
    "DEFAULTS",
    "KeyBindings",
    "load_keybindings",
    "save_keybindings",
    "format_help_overlay",
]
