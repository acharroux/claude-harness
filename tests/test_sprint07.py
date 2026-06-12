"""Sprint 7 tests: Whisperer Adapter & Event Bus.

Covers C1..C22 of the sprint-07 contract. Tests are intentionally
network-free; real-provider adapters are exercised only via env-var-cleared
monkeypatches that assert ``LLMUnavailable`` is raised before any network
call could happen.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List

import pytest

# Layer imports under test -- all must succeed at module import time.
from whisperdeep import events as events_module
from whisperdeep.events import EVENT_TYPES, Event, EventBus, EventType, WILDCARD
from whisperdeep.llm import (
    AdapterResult,
    AnthropicAdapter,
    LLMAdapter,
    LLMUnavailable,
    NullAdapter,
    OfflineAdapter,
    OpenAIAdapter,
    get_prose_pool,
)
from whisperdeep.whisperer import (
    DEFAULT_PER_TURN_CAP,
    Whisper,
    Whisperer,
)


# Helper: a counting test-double adapter.
class CountingAdapter(LLMAdapter):
    name = "counting"

    def __init__(self, tokens_per_call: int = 5) -> None:
        self.calls = 0
        self.tokens_per_call = tokens_per_call

    def complete(self, prompt, *, max_tokens=64, event_type=None):
        self.calls += 1
        return AdapterResult(
            text=f"counting:{self.calls}",
            tokens=self.tokens_per_call,
            adapter_name=self.name,
        )


class FlakyAdapter(LLMAdapter):
    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt, *, max_tokens=64, event_type=None):
        self.calls += 1
        raise RuntimeError("boom")


class FixedTokenAdapter(LLMAdapter):
    """Returns non-empty text and a configured token count per call."""

    name = "fixed"

    def __init__(self, tokens_per_call: int = 20) -> None:
        self.tokens_per_call = tokens_per_call
        self.calls = 0

    def complete(self, prompt, *, max_tokens=64, event_type=None):
        self.calls += 1
        return AdapterResult(
            text=f"fixed-call-{self.calls}",
            tokens=self.tokens_per_call,
            adapter_name=self.name,
        )


# =============================================================================
# C1, C4: event-bus module + canonical event types
# =============================================================================


def test_event_bus_module_exposes_required_surface():
    # C1: module is importable and exposes EventBus, Event, publish/subscribe.
    assert hasattr(events_module, "EventBus")
    assert hasattr(events_module, "Event")
    bus = EventBus()
    assert callable(getattr(bus, "publish"))
    assert callable(getattr(bus, "subscribe"))
    # Aliases mentioned in the contract: emit/on.
    assert callable(getattr(bus, "emit"))
    assert callable(getattr(bus, "on"))


def test_canonical_event_types_exposed_and_iterable():
    # C4: the seven canonical event names are exposed and iterable.
    required = {
        "run_started",
        "run_ended",
        "entered_room",
        "killed_monster",
        "low_hp",
        "found_item",
        "descended",
    }
    assert required.issubset(set(EVENT_TYPES))
    # Iterable in a stable way.
    listed = list(EVENT_TYPES)
    assert len(listed) >= 7
    # Enum form also exposed.
    enum_values = {et.value for et in EventType}
    assert required.issubset(enum_values)


# =============================================================================
# C2: Event immutability + required fields
# =============================================================================


def test_event_immutability_and_required_fields():
    e = Event(type="entered_room", payload={"room_id": 3}, turn=12, floor=0)
    assert e.type == "entered_room"
    assert e.turn == 12
    assert e.floor == 0
    assert e.payload["room_id"] == 3
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        e.turn = 99  # type: ignore[misc]


# =============================================================================
# C3: subscribers + ordering
# =============================================================================


def test_subscribers_receive_targeted_and_wildcard_events_in_order():
    bus = EventBus()
    calls: List[str] = []

    def a(ev):
        calls.append(f"A:{ev.type}")

    def b(ev):
        calls.append(f"B:{ev.type}")

    def c(ev):
        calls.append(f"C:{ev.type}")

    bus.subscribe("killed_monster", a)
    bus.subscribe("entered_room", b)
    bus.subscribe(WILDCARD, c)

    bus.publish(Event(type="killed_monster", turn=1))
    assert calls == ["A:killed_monster", "C:killed_monster"]
    # A came before C: that matches subscription order.

    bus.publish(Event(type="entered_room", turn=2))
    assert calls == [
        "A:killed_monster",
        "C:killed_monster",
        "B:entered_room",
        "C:entered_room",
    ]
    # A still fired only once; B fired exactly once; C fired twice.
    assert sum(1 for x in calls if x.startswith("A:")) == 1
    assert sum(1 for x in calls if x.startswith("B:")) == 1
    assert sum(1 for x in calls if x.startswith("C:")) == 2


# =============================================================================
# C5: Whisperer module + constructor surface
# =============================================================================


def test_whisperer_module_constructor_accepts_adapter_and_exposes_whispers():
    wh = Whisperer(adapter=NullAdapter())
    assert hasattr(wh, "whispers")
    assert isinstance(wh.whispers, list)
    assert callable(wh.get_whispers)
    assert wh.get_whispers() == []


# =============================================================================
# C6: LLM adapter ABC + Null + Offline
# =============================================================================


def test_llm_adapter_abc_and_concrete_adapters_present():
    # Abstract instantiation should fail.
    with pytest.raises(TypeError):
        LLMAdapter()  # type: ignore[abstract]
    null = NullAdapter()
    res = null.complete("anything", max_tokens=10)
    assert isinstance(res, AdapterResult)
    assert res.text == ""
    assert res.tokens == 0
    off = OfflineAdapter(seed=1)
    res2 = off.complete("anything", max_tokens=10, event_type="entered_room")
    assert isinstance(res2.text, str) and res2.text
    assert res2.tokens >= 0
    assert res2.adapter_name == "offline"


# =============================================================================
# C7: real-provider adapter + missing key
# =============================================================================


def test_real_provider_adapter_raises_llm_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = AnthropicAdapter()
    with pytest.raises(LLMUnavailable) as exc_info:
        a.complete("hi", max_tokens=8)
    assert "ANTHROPIC_API_KEY" in str(exc_info.value)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    o = OpenAIAdapter()
    with pytest.raises(LLMUnavailable) as exc_info_o:
        o.complete("hi", max_tokens=8)
    assert "OPENAI_API_KEY" in str(exc_info_o.value)


# =============================================================================
# C8: pool size + content
# =============================================================================


def test_offline_pool_has_at_least_eight_distinct_entries_per_event_type():
    pool = get_prose_pool()
    canonical = {
        "run_started",
        "run_ended",
        "entered_room",
        "killed_monster",
        "low_hp",
        "found_item",
        "descended",
    }
    total = 0
    for et in canonical:
        assert et in pool, f"pool missing event type {et}"
        entries = pool[et]
        # Distinct + non-empty + >= 8.
        assert len(set(entries)) >= 8, f"{et}: only {len(set(entries))} distinct entries"
        for s in entries:
            assert isinstance(s, str) and s.strip(), f"{et}: empty/blank entry"
        total += len(set(entries))
    assert total >= 56

    # Each event type, hinted via OfflineAdapter, must yield a non-empty
    # string drawn from that type's pool.
    adapter = OfflineAdapter(seed=7)
    for et in canonical:
        res = adapter.complete("p", max_tokens=64, event_type=et)
        assert res.text, f"empty whisper for {et}"
        assert res.text in pool[et], f"whisper for {et} not from its pool"


# =============================================================================
# C9: determinism
# =============================================================================


def test_offline_adapter_determinism_same_seed_identical_diff_seed_differs():
    types = ["entered_room", "killed_monster", "entered_room", "low_hp", "descended"]
    a = OfflineAdapter(seed=42)
    seq_a = [a.complete("p", max_tokens=32, event_type=t).text for t in types]
    b = OfflineAdapter(seed=42)
    seq_b = [b.complete("p", max_tokens=32, event_type=t).text for t in types]
    assert seq_a == seq_b
    c = OfflineAdapter(seed=43)
    seq_c = [c.complete("p", max_tokens=32, event_type=t).text for t in types]
    # At least one element must differ when seeds differ.
    assert any(x != y for x, y in zip(seq_a, seq_c)), \
        f"seed 42 and 43 produced identical sequences: {seq_a}"


# =============================================================================
# C10: auto-whisper from bus with full metadata
# =============================================================================


def test_whisperer_produces_whispers_from_bus_with_full_metadata():
    bus = EventBus()
    wh = Whisperer(adapter=OfflineAdapter(seed=1), bus=bus)
    bus.publish(Event(type="killed_monster", payload={"name": "goblin"}, turn=5, floor=0))
    assert len(wh.whispers) == 1
    w = wh.whispers[0]
    assert isinstance(w.text, str) and w.text
    assert w.source_event_type == "killed_monster"
    assert w.source_turn == 5
    assert w.source_floor == 0
    assert isinstance(w.adapter_name, str) and w.adapter_name
    assert isinstance(w.fallback, bool)
    bus.publish(Event(type="entered_room", turn=6, floor=0))
    bus.publish(Event(type="low_hp", turn=7, floor=0))
    assert len(wh.whispers) == 3


# =============================================================================
# C11: budget exhaustion -> fallback
# =============================================================================


def test_budget_exhaustion_forces_fallback_but_whispers_keep_flowing():
    # Tiny budget, primary reports 20 tokens per call.
    primary = FixedTokenAdapter(tokens_per_call=20)
    bus = EventBus()
    wh = Whisperer(
        adapter=primary,
        bus=bus,
        budget=30,
        fallback_adapter=OfflineAdapter(seed=99),
        per_turn_cap=10,  # raise cap so the test isn't gated by throttling
    )
    # Five distinct turns so per-turn coalescing doesn't drop events.
    for turn in range(5):
        bus.publish(Event(type="entered_room", turn=turn, floor=0))
    assert len(wh.whispers) == 5
    pre_cap = [w for w in wh.whispers if not w.fallback]
    post_cap = [w for w in wh.whispers if w.fallback]
    assert len(pre_cap) >= 1
    assert len(post_cap) >= 1
    # Whispers continue producing non-empty text.
    for w in wh.whispers:
        assert isinstance(w.text, str) and w.text
    # Token counter does not increase past budget + last pre-cap call.
    # Two pre-cap calls each spending 20 tokens => 40 (>= budget 30); after
    # that, fallback adapter contributes 0 tokens, so tokens_used should
    # stay at 40.
    assert wh.tokens_used <= 30 + 20
    # Sanity: the post-cap whispers came from the fallback adapter.
    for w in post_cap:
        assert w.adapter_name == "offline"


# =============================================================================
# C12: adapter failure resilience
# =============================================================================


def test_flaky_adapter_does_not_crash_event_loop():
    bus = EventBus()
    flaky = FlakyAdapter()
    wh = Whisperer(
        adapter=flaky,
        bus=bus,
        fallback_adapter=OfflineAdapter(seed=3),
        per_turn_cap=10,
    )
    # First publish must NOT raise.
    bus.publish(Event(type="entered_room", turn=1, floor=0))
    assert len(wh.whispers) == 1
    w = wh.whispers[0]
    assert w.text  # non-empty
    assert w.fallback is True
    assert wh.failure_count >= 1
    assert w.error_reason and "RuntimeError" in w.error_reason
    # Loop continues.
    bus.publish(Event(type="killed_monster", turn=2, floor=0))
    assert len(wh.whispers) == 2
    assert wh.whispers[1].fallback is True


# =============================================================================
# C13: Game wiring publishes run_started + descended
# =============================================================================


def test_game_wiring_publishes_run_started_and_descended():
    from whisperdeep.game import Game

    g = Game.from_seed(seed=1, whisperer=True)
    assert g.events is not None
    assert g.whisperer is not None
    # run_started is the first whisper.
    assert len(g.whisperer.whispers) >= 1
    first = g.whisperer.whispers[0]
    assert first.source_event_type == "run_started"

    # Place player on downstairs and call descend.
    floor0 = g.floor
    assert floor0.downstairs_pos is not None, "test seed must produce a downstairs"
    g.player.x, g.player.y = floor0.downstairs_pos
    pre = len(g.whisperer.whispers)
    ok = g.descend()
    assert ok is True
    descended_whispers = [
        w for w in g.whisperer.whispers if w.source_event_type == "descended"
    ]
    assert len(descended_whispers) >= 1
    assert len(g.whisperer.whispers) > pre

    # Opt-out: no events / no whisperer.
    g2 = Game.from_seed(seed=1, whisperer=False)
    assert g2.events is None
    assert g2.whisperer is None


# =============================================================================
# C14, C15: CLI flags + frame is unchanged modulo banner
# =============================================================================


def _run_cli(*flags: str, env=None):
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "whisperdeep", *flags]
    e = os.environ.copy()
    if env:
        e.update(env)
    # Strip API keys to be safe.
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


def test_cli_help_documents_whisperer_flags():
    r = _run_cli("--help")
    assert r.returncode == 0
    assert "--whisperer" in r.stdout
    assert "--no-whisperer" in r.stdout
    assert "--dump-whispers" in r.stdout


def test_cli_default_run_uses_offline_and_succeeds():
    r = _run_cli("--seed", "1", "--headless")
    assert r.returncode == 0, r.stderr
    assert "# whisperer: offline" in r.stdout


def test_cli_no_whisperer_and_null_produce_clean_exits():
    r1 = _run_cli("--seed", "1", "--headless", "--no-whisperer")
    assert r1.returncode == 0
    # No banner line.
    assert "# whisperer:" not in r1.stdout
    r2 = _run_cli("--seed", "1", "--headless", "--whisperer", "null")
    assert r2.returncode == 0
    assert "# whisperer: null" in r2.stdout
    # No prose strings appear in null output beyond the banner + glyphs.
    pool = get_prose_pool()
    for entries in pool.values():
        for entry in entries:
            assert entry not in r2.stdout, "null adapter leaked prose"


def test_dungeon_frame_unchanged_modulo_banner():
    # Sprint 7's "plumbing-only" invariant (default == no-whisperer modulo
    # banner) was superseded in Sprint 8: the default --headless run now
    # composes a whisper panel to the right of the grid. The Sprint-7
    # GUARANTEE that the underlying dungeon GRID is unchanged still holds
    # — we extract it from the composite output's left-hand columns and
    # compare against the --no-whisperer output.
    a = _run_cli("--seed", "1", "--headless", "--no-whisperer").stdout
    b = _run_cli("--seed", "1", "--headless").stdout
    # Strip the leading banner line from b.
    assert b.startswith("# whisperer: offline\n")
    b_stripped = b[len("# whisperer: offline\n"):]
    a_rows = a.rstrip("\n").split("\n")
    b_rows = b_stripped.rstrip("\n").split("\n")
    # Sprint 8 default: each composite row begins with the grid row,
    # followed by a two-space gutter and the panel content. The grid rows
    # in b_stripped therefore match a's rows as a prefix.
    assert len(a_rows) == len(b_rows), (
        f"row count differs: {len(a_rows)} vs {len(b_rows)}"
    )
    for ar, br in zip(a_rows, b_rows):
        assert br.startswith(ar), (
            "grid row not preserved as a prefix in composite output"
        )
    # The grid-only output never carries the offline pool's prose.
    pool = get_prose_pool()
    for entries in pool.values():
        for entry in entries:
            assert entry not in a, "no-whisperer output leaked prose"
    # The composite output's panel CARRIES whisper prose by Sprint 8
    # design; the precise substring assertion is exercised by the
    # Sprint-8 test_sprint08.py suite (C5). This Sprint-7 regression test
    # only guarantees the dungeon grid is preserved (above).


# =============================================================================
# C16: dump-whispers determinism across processes
# =============================================================================


def test_whisper_dump_is_deterministic_across_processes(tmp_path):
    p1 = tmp_path / "w1.json"
    p2 = tmp_path / "w2.json"
    r1 = _run_cli("--seed", "5", "--headless", "--dump-whispers", str(p1))
    r2 = _run_cli("--seed", "5", "--headless", "--dump-whispers", str(p2))
    assert r1.returncode == 0
    assert r2.returncode == 0
    j1 = json.loads(p1.read_text(encoding="utf-8"))
    j2 = json.loads(p2.read_text(encoding="utf-8"))
    # Compare element-wise on text + source_event_type + turn + floor.
    keys = ("text", "source_event_type", "source_turn", "source_floor")
    assert [tuple(w[k] for k in keys) for w in j1] == [
        tuple(w[k] for k in keys) for w in j2
    ]
    # Each entry has fallback (bool) and adapter_name.
    for w in j1:
        assert isinstance(w["fallback"], bool)
        assert isinstance(w["adapter_name"], str) and w["adapter_name"]

    # Different seed -> different sequence.
    p3 = tmp_path / "w3.json"
    r3 = _run_cli("--seed", "6", "--headless", "--dump-whispers", str(p3))
    assert r3.returncode == 0
    j3 = json.loads(p3.read_text(encoding="utf-8"))
    if j1 and j3:
        seq1 = [tuple(w[k] for k in keys) for w in j1]
        seq3 = [tuple(w[k] for k in keys) for w in j3]
        # Allow length differences; require at least one mismatch in the
        # overlap.
        overlap_eq = all(a == b for a, b in zip(seq1, seq3)) and len(seq1) == len(seq3)
        assert not overlap_eq, "seeds 5 and 6 produced identical whisper sequences"


# =============================================================================
# C17: no network in tests + no network in offline/null adapters
# =============================================================================


def test_no_network_imports_in_offline_or_null_adapter_source():
    # OfflineAdapter and NullAdapter source must not reference network libs.
    from whisperdeep import llm as llm_module

    src = Path(llm_module.__file__).read_text(encoding="utf-8")
    # Crude but effective: split the file at AnthropicAdapter / OpenAIAdapter
    # and inspect everything BEFORE that split (which contains Null +
    # Offline).
    cut = src.find("class AnthropicAdapter")
    pre = src[:cut]
    for needle in ("requests", "httpx", "urllib.request", "socket.create_connection"):
        assert needle not in pre, f"network ref {needle!r} found in offline/null section"
    # The `anthropic` and `openai` SDK names are allowed only inside
    # AnthropicAdapter / OpenAIAdapter (post-cut).
    assert "import anthropic" not in pre
    assert "import openai" not in pre


def test_pytest_suite_does_not_import_network_modules_at_top_level():
    here = Path(__file__).resolve().parent
    sprint07 = here / "test_sprint07.py"
    src = sprint07.read_text(encoding="utf-8")
    # Top-level (import statements outside of functions/classes) must not
    # import any of these. Crude heuristic: scan the part of the file before
    # the first def/class.
    head_split = re.search(r"^(?:def |class )", src, re.MULTILINE)
    head = src[: head_split.start()] if head_split else src
    for needle in ("requests", "httpx", "urllib.request", "anthropic", "openai", "socket"):
        # Allow sub-strings (e.g. 'anthropic' in a comment) as long as
        # there's no `import` statement.
        assert not re.search(rf"^\s*import\s+{needle}\b", head, re.MULTILINE), \
            f"top-level import of {needle}"
        assert not re.search(rf"^\s*from\s+{needle}\b", head, re.MULTILINE), \
            f"top-level from-import of {needle}"


# =============================================================================
# C22: per-turn whisper-rate throttle
# =============================================================================


def test_whisperer_caps_whispers_per_turn_with_spammy_events():
    bus = EventBus()
    counter = CountingAdapter()
    wh = Whisperer(adapter=counter, bus=bus, per_turn_cap=DEFAULT_PER_TURN_CAP)
    for _ in range(50):
        bus.publish(Event(type="entered_room", turn=1, floor=0))
    # Coalescing on (turn=1, type='entered_room') means only 1 whisper.
    assert counter.calls <= DEFAULT_PER_TURN_CAP
    assert len(wh.whispers) <= DEFAULT_PER_TURN_CAP

    # Mix of types on same turn: per-turn cap still respected.
    counter2 = CountingAdapter()
    bus2 = EventBus()
    wh2 = Whisperer(adapter=counter2, bus=bus2, per_turn_cap=DEFAULT_PER_TURN_CAP)
    for et in ["entered_room", "killed_monster", "low_hp", "found_item",
               "descended", "run_started", "run_ended"]:
        for _ in range(3):
            bus2.publish(Event(type=et, turn=2, floor=0))
    assert counter2.calls <= DEFAULT_PER_TURN_CAP
    assert len(wh2.whispers) <= DEFAULT_PER_TURN_CAP


# =============================================================================
# C21: layering invariants (Whisperer doesn't know about real providers,
# events module doesn't know about whisperer/llm, llm doesn't know about
# game/world/floor/render)
# =============================================================================


def test_layering_invariants_via_source_grep():
    from whisperdeep import events as events_mod
    from whisperdeep import llm as llm_mod
    from whisperdeep import whisperer as whisperer_mod
    from whisperdeep import game as game_mod

    events_src = Path(events_mod.__file__).read_text(encoding="utf-8")
    llm_src = Path(llm_mod.__file__).read_text(encoding="utf-8")
    whisperer_src = Path(whisperer_mod.__file__).read_text(encoding="utf-8")
    game_src = Path(game_mod.__file__).read_text(encoding="utf-8")

    # llm.py: no game/world/floor/render imports.
    for needle in (
        "from whisperdeep.game",
        "from whisperdeep.world",
        "from whisperdeep.floor",
        "from whisperdeep.render",
    ):
        assert needle not in llm_src, f"{needle} found in llm.py"

    # events.py: no whisperer or llm imports.
    assert "from whisperdeep.whisperer" not in events_src
    assert "from whisperdeep.llm" not in events_src
    assert "from .whisperer" not in events_src
    assert "from .llm" not in events_src

    # whisperer.py: no concrete real-provider class imports.
    assert "AnthropicAdapter" not in whisperer_src
    assert "OpenAIAdapter" not in whisperer_src

    # game.py: imports events module but not whisperer or llm at module
    # top level. Lazy imports inside Game.from_seed are allowed.
    head = game_src.split("class Game", 1)[0]
    assert "from .events" in head or "from whisperdeep.events" in head
    assert "from .whisperer" not in head
    assert "from whisperdeep.whisperer" not in head
    assert "from .llm" not in head
    assert "from whisperdeep.llm" not in head
    assert "from .adapter_factory" not in head
    assert "from whisperdeep.adapter_factory" not in head
