# Whisperdeep

A roguelike with a living dungeon master.

This is the game built sprint-by-sprint inside this repository by the
Planner–Generator–Evaluator harness. The harness tooling itself lives in
`harness/` and is documented in [the top-level README](../README.md).

> **Status — Sprint 7: Whisperer Adapter & Event Bus.** The dungeon now
> raises in-game events on a structured event bus, a *Whisperer* service
> consumes those events and produces 1-3 sentence "whispers" via a
> pluggable LLM adapter, and a hard token-budget guardrail forces a
> graceful degrade to a deterministic offline prose pool when the budget
> is exhausted or a network call fails. **Sprint 7 is plumbing only —
> whispers are NOT yet rendered inside the dungeon frame.** The visible
> ASCII output of `--headless` runs is byte-identical to the pre-Whisperer
> Sprint-2 frame for the same seed (modulo a single opt-in
> `# whisperer: <adapter>` banner line). The Whisperer panel UI lands in
> Sprint 8.

---

## Quick start

Whisperdeep targets **Python 3.11+**. From the repository root:

```sh
python -m whisperdeep --seed 1
```

Headless mode (prints the initial frame and exits) — useful for snapshot tests
and CI:

```sh
python -m whisperdeep --seed 1 --headless
```

## Glyph legend

The renderer uses a strict ASCII glyph set:

| Glyph | Meaning              |
| :---: | :------------------- |
| `#`   | wall (impassable)    |
| `.`   | floor (walkable)     |
| `+`   | door (walkable)      |
| `<`   | upstairs             |
| `>`   | downstairs           |
| `@`   | the player           |

Walls block movement; bumping into a wall is a no-op. Doors are walkable.
Stairs are walkable too; press `>` on a downstairs tile or `<` on an
upstairs tile to actually change floor.

## Controls (interactive mode)

| Key      | Action                              |
| :------: | :---------------------------------- |
| h/j/k/l  | move west / south / north / east    |
| y/u/b/n  | move diagonally (NW/NE/SW/SE)       |
| `.`      | wait one turn                       |
| `>`      | descend stairs (when on `>`)        |
| `<`      | ascend stairs (when on `<`)         |
| q        | quit                                |

## Dungeon generator

The generator (`whisperdeep.generator`) is a deterministic
rooms-and-corridors algorithm. Given a `(width, height, seed)` triple it
always produces the same floor.

```python
from whisperdeep.generator import generate
floor = generate(width=80, height=40, seed=12345)
```

### Multi-floor worlds

A `World` packages together a dungeon of several floors:

```python
from whisperdeep.world import World
world = World(master_seed=999, num_floors=3, width=80, height=40)
```

Each floor's seed is derived from the master seed plus its index, so a
single master seed reproduces the entire dungeon.

## The Whisperer (Sprint 7)

The Whisperer is Whisperdeep's signature LLM-driven dungeon master. Sprint
7 ships its plumbing in four cleanly separated layers:

1. an in-game **Event Bus** the rest of the engine publishes to;
2. a provider-agnostic **LLM Adapter** abstraction with offline / null /
   real-provider implementations;
3. the **Whisperer service** that consumes events, queries the adapter,
   and records whispers;
4. a **token-budget guardrail** that degrades to the offline prose pool
   when the budget is exhausted or the primary adapter fails.

### Sprint 7 is plumbing only

Whispers produced in Sprint 7 are **not** displayed in the dungeon frame.
They live in `game.whisperer.whispers` and can be dumped to JSON via
`--dump-whispers PATH`. Rendering whispers in the game UI is Sprint 8.

### Canonical event types

The bus accepts a closed set of event-type strings, exposed both as the
`EventType` enum and the `EVENT_TYPES` tuple:

| Event type        | Fires when                                                     |
| ----------------- | -------------------------------------------------------------- |
| `run_started`     | A new game/run is constructed.                                 |
| `run_ended`       | A run terminates (death, victory, quit).                       |
| `entered_room`    | The player walks into a previously-unvisited room.             |
| `killed_monster`  | A monster's HP reaches zero from the player's actions.         |
| `low_hp`          | The player crosses a low-HP threshold.                         |
| `found_item`      | An item is added to the player's inventory.                    |
| `descended`       | The player descends a staircase to a deeper floor.             |

Sprint 7 wires the Game to publish at least `run_started` (on
construction with whispering enabled) and `descended` (on `Game.descend()`).
Other events become live as their upstream features land in later
sprints; tests publish them directly in the meantime.

### Adapters

| Adapter             | Source / behavior                                        | Env var              |
| ------------------- | -------------------------------------------------------- | -------------------- |
| `NullAdapter`       | Always returns the empty string and zero tokens.         | —                    |
| `OfflineAdapter`    | Deterministic prose drawn from `prose_pool.json`.        | —                    |
| `AnthropicAdapter`  | Real Claude API (stubbed in Sprint 7; lazy SDK import).  | `ANTHROPIC_API_KEY`  |
| `OpenAIAdapter`     | Real OpenAI API (stubbed in Sprint 7; lazy SDK import).  | `OPENAI_API_KEY`     |

All adapters implement the abstract `LLMAdapter.complete(prompt, *,
max_tokens, event_type=None)` method and return an `AdapterResult(text,
tokens, adapter_name, fallback)`. Real-provider adapters raise
`LLMUnavailable` when their API key (or SDK) is missing — this never
crashes import.

### Token-budget guardrail and fallback

Each `Whisperer` accepts a `budget` (default: 10,000 estimated tokens). The
Whisperer accumulates `tokens_used` after every successful primary-adapter
call. When `tokens_used >= budget`:

* subsequent whispers are served from the **fallback adapter** (an
  `OfflineAdapter`) and marked `fallback=True`;
* fallback whispers consume **zero** further chargeable tokens;
* the game is never silenced — whispers continue to flow with prose drawn
  from the offline pool.

Adapter failures (any exception, including `LLMUnavailable` and network
errors) are caught: the failure is recorded in `whisperer.failure_count`
and on the per-whisper `error_reason` field, the whisper is served from
the fallback pool with `fallback=True`, and processing continues. The
Whisperer never re-raises out of its event handler.

### Whisper-rate throttle

To prevent runaway cost from spammy events (e.g. a teleport firing 50
`entered_room` events on the same player turn), the Whisperer caps
whispers-per-turn at `DEFAULT_PER_TURN_CAP = 3` and coalesces consecutive
same-type events on the same turn into a single whisper. Pass
`per_turn_cap=N` to the constructor to change the cap.

### Fallback prose pool

The pool ships at `whisperdeep/prose_pool.json` with **9 distinct
entries per canonical event type (63 total)**, well above the contract's
8-per-type / 56-total floor. Each entry is a 1-3 sentence atmospheric
string drawn from the type's pool when the OfflineAdapter is hinted with
that event type.

### CLI flags

| Flag                        | Default     | Meaning                                                              |
| --------------------------- | :---------: | -------------------------------------------------------------------- |
| `--seed N`                  | `1`         | Master seed for dungeon generation. Same seed → same dungeon.        |
| `--width N`                 | `80`        | Floor width in tiles.                                                |
| `--height N`                | `40`        | Floor height in tiles.                                               |
| `--floors N`                | `3`         | Number of dungeon floors.                                            |
| `--headless`                | off         | Print the initial frame and exit (no input loop).                    |
| `--whisperer NAME`          | `offline`   | Adapter: `offline` / `null` / `anthropic` / `openai`.                |
| `--no-whisperer`            | off         | Disable the Whisperer entirely (no bus, no banner, no events).       |
| `--whisper-budget N`        | (built-in)  | Override the Whisperer's token budget.                               |
| `--dump-whispers PATH`      | (none)      | Write the whisper log to PATH as a JSON array.                       |

The default headless run uses the offline adapter and never makes network
calls. The only stdout difference between a default run and a
`--no-whisperer` run is a single banner line of the form
`# whisperer: <adapter>` printed before the dungeon frame; the dungeon
glyph rows themselves are byte-identical.

### Determinism

Two `python -m whisperdeep --seed N --headless --dump-whispers PATH`
invocations with the same seed (offline adapter) write identical whisper
sequences to disk — same prose, same source-event metadata, same order.
Different seeds produce different sequences. Real-provider adapters are
NOT expected to be deterministic.

### Layering

The Sprint 7 modules respect strict layering invariants so the Whisperer
remains pluggable:

* `whisperdeep.events` imports nothing from `whisperer` or `llm`.
* `whisperdeep.llm` imports nothing from `game` / `world` / `floor` /
  `render`.
* `whisperdeep.whisperer` imports `events` and the `LLMAdapter` ABC, but
  not the concrete real-provider classes.
* `whisperdeep.game` imports `events` (so it can publish), but
  `whisperer` and `llm` are imported lazily inside `Game.from_seed` —
  Game-side gameplay never imports a concrete adapter.

## Tests

```sh
pytest tests/
```

Sprint 7 ships `tests/test_sprint07.py` with 22 new test functions
covering: event-bus pub/sub and ordering, the canonical event-type
registry, event immutability, OfflineAdapter pool size and content,
OfflineAdapter determinism, auto-whisper from the bus with full
metadata, budget exhaustion forcing fallback, adapter-failure
resilience, Game wiring of `run_started` / `descended`, real-provider
adapters raising `LLMUnavailable` without an API key, end-to-end
whisper-dump determinism across processes, CLI flag plumbing, the
"frame is byte-identical modulo banner" invariant, the per-turn whisper
throttle, and layering / no-network grep checks. The full repository
suite passes with **no API keys set and no network access**.

## Project layout

```
whisperdeep/
  __init__.py
  __main__.py             # `python -m whisperdeep`
  cli.py                  # argument parsing and entry points
  tiles.py                # Tile + TileKind, glyph legend
  floor.py                # Floor (2D grid) and Room
  generator.py            # DungeonGenerator — rooms and corridors
  world.py                # multi-floor World
  entity.py               # Entity / Player
  game.py                 # Game state, movement, descend/ascend, event publishing
  render.py               # ASCII frame renderer
  events.py               # EventBus + Event + EVENT_TYPES (Sprint 7)
  llm.py                  # LLMAdapter ABC + Null/Offline/Anthropic/OpenAI (Sprint 7)
  whisperer.py            # Whisperer service (Sprint 7)
  adapter_factory.py      # CLI flag → adapter (Sprint 7)
  prose_pool.json         # fallback prose pool, >= 8 entries per event type
tests/
  test_generator.py       # generator unit tests
  test_game.py            # game/movement/CLI tests
  test_sprint01.py        # sprint 1 explicit contract
  test_sprint07.py        # sprint 7 contract: bus, adapters, whisperer, CLI
```
