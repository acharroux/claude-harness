"""Sprint 12 — Pluggable audio adapter layer (OPT-IN, OFF by default).

Whisperdeep is a terminal game; tests run in CI without audio devices.
This module ships the *architecture* for an audio layer — a Protocol,
a silent default adapter, a recording test/debug adapter, and a
mapping from canonical event types to named cues — but DOES NOT ship
a real audio backend. Future sprints can add a winsound / playsound
backend without changing the public interface.

**Audio is OPT-IN and OFF by default.** ``Game.audio`` defaults to
``None``. The CLI flag ``--audio`` defaults to ``"null"`` (silent
:class:`NullAudioAdapter`). To get cue traces (for tests), pass
``--audio log`` and use ``--dump-audio PATH`` to write them as JSON.

Layering invariants:

* This module imports **only** stdlib + ``typing``.
* It does NOT import ``winsound``, ``playsound``, ``pyaudio``,
  ``pygame``, ``numpy``, ``requests``, ``urllib``, or any
  third-party / network library.
* It does NOT import :mod:`whisperdeep.llm`, :mod:`whisperdeep.render`,
  :mod:`whisperdeep.panel`, or :mod:`whisperdeep.whisperer`.
"""
from __future__ import annotations

from typing import Dict, List, Protocol, Tuple, runtime_checkable


# ---------------------------------------------------------------------------
# Cues
# ---------------------------------------------------------------------------

#: Tuple of canonical cue names. Cue strings outside this set may still
#: be played by adapters, but the EVENT_TO_CUE mapping is restricted to
#: this closed set.
CUES: Tuple[str, ...] = (
    "footstep",
    "bump",
    "descend",
    "ascend",
    "low_hp",
    "run_started",
    "run_ended",
    "epitaph",
    "first_sight",
)


#: Map canonical event-type strings to cue names. The set of source
#: events mirrors the canonical EVENT_TYPES (see :mod:`whisperdeep.events`)
#: but the mapping is intentionally NOT exhaustive — events without a
#: useful audio cue are simply absent and silently ignored at dispatch.
EVENT_TO_CUE: Dict[str, str] = {
    "run_started": "run_started",
    "run_ended": "run_ended",
    "descended": "descend",
    "low_hp": "low_hp",
    "epitaph": "epitaph",
    "first_sight": "first_sight",
    "killed_monster": "bump",
    "found_item": "first_sight",
}


# ---------------------------------------------------------------------------
# Adapter Protocol & implementations
# ---------------------------------------------------------------------------


@runtime_checkable
class AudioAdapter(Protocol):
    """Minimal audio-output Protocol.

    Implementations should treat unknown cue names as a documented no-op
    rather than raising.
    """

    def play(self, cue: str) -> None: ...

    def stop(self) -> None: ...


class NullAudioAdapter:
    """Silent default adapter. Both play and stop are no-ops."""

    name: str = "null"

    def play(self, cue: str) -> None:  # noqa: D401 -- short verb
        return None

    def stop(self) -> None:
        return None


class LogAudioAdapter:
    """Test/debug adapter. Records cue names to ``self.cues``."""

    name: str = "log"

    def __init__(self) -> None:
        self.cues: List[str] = []

    def play(self, cue: str) -> None:
        if isinstance(cue, str) and cue:
            self.cues.append(cue)

    def stop(self) -> None:
        # The log adapter does not maintain a notion of 'currently
        # playing'; stop is intentionally a no-op (tests assert against
        # the recorded cue list, not a playback state machine).
        return None


# ---------------------------------------------------------------------------
# Wiring helper
# ---------------------------------------------------------------------------


def cue_for_event(event_type: str) -> str:
    """Return the cue mapped from ``event_type``, or ``""`` if none.

    A returned ``""`` signals the dispatch layer to skip the cue. This
    keeps the dispatcher branch-free.
    """
    return EVENT_TO_CUE.get(event_type, "")


def make_adapter(choice: str) -> AudioAdapter:
    """Return a fresh :class:`AudioAdapter` for ``choice``.

    Choices: ``"null"`` (default — silent), ``"log"`` (recording).
    Unknown choices raise ``ValueError``.
    """
    if choice in ("null", "none", "off", "silent"):
        return NullAudioAdapter()
    if choice == "log":
        return LogAudioAdapter()
    raise ValueError(
        f"unknown audio choice: {choice!r}. Valid: null, log"
    )


__all__ = [
    "CUES",
    "EVENT_TO_CUE",
    "AudioAdapter",
    "NullAudioAdapter",
    "LogAudioAdapter",
    "cue_for_event",
    "make_adapter",
]
