# Product Spec: **Whisperdeep** — A Roguelike with a Living Dungeon Master

## 1. Product Overview

**Whisperdeep** is a turn-based, terminal-rendered roguelike where you descend through a
procedurally generated dungeon — but the dungeon itself is *alive*. A "Whisperer" (an AI
dungeon master, powered by an LLM) watches your every move, narrates the world in
atmospheric prose, names the monsters you've never seen before, and quietly bends the
rules of generation to make your story interesting. Beat a boss without taking damage?
The Whisperer might whisper rumors of you to the next floor's denizens, and they will
prepare. Fail spectacularly? Your death becomes a legend the next run remembers.

The game is for players who love the tactical depth of classic roguelikes (NetHack,
DCSS, Caves of Qud) but find pure procedural generation cold and repetitive. Whisperdeep
keeps the punishing turn-based combat and permadeath, but layers on emergent storytelling
so every run feels like a campaign with a thoughtful GM rather than a random walk through
RNG. Runs are 1-3 hours; the meta-layer (the Whisperer's memory) persists across deaths.

Why it matters: most "AI in games" today is gimmicky chat NPCs. Whisperdeep treats the
LLM as a *director*, not an actor — it shapes pacing, names, lore, and dramatic beats,
while the deterministic core (combat, movement, items) stays sharp, debuggable, and fair.
The result is a game that can't be replicated by traditional procgen alone.

## 2. Target Users

### Persona 1: **The Roguelike Veteran** ("Mara, 34, software engineer")
- **Goal**: Wants tactical depth, permadeath stakes, and replayability she can sink 200 hours into.
- **Pain point**: After a few dozen runs of any roguelike, the procedural seams show — the same room shapes, the same monster placements, the same loot curves.
- **What Whisperdeep gives her**: A director that notices her patterns and pushes back. The dungeon learns.

### Persona 2: **The Narrative Curious** ("Devon, 22, lit student")
- **Goal**: Wants stories. Plays Disco Elysium, Sunless Sea, Wildermyth.
- **Pain point**: Traditional roguelikes are too mechanically opaque; the "story" is just a body count.
- **What Whisperdeep gives him**: Atmospheric whisper-prose, named monsters with motives, a death log that reads like dark fantasy fiction.

### Persona 3: **The Lunch-Break Player** ("Sam, 41, designer")
- **Goal**: A 30-90 minute session of crunchy decisions, no fluff.
- **Pain point**: Modern games demand long onboarding; classic roguelikes demand a wiki.
- **What Whisperdeep gives him**: ASCII clarity, keyboard-driven flow, a Whisperer that explains the world as it goes — no manual required.

## 3. Feature Specification

### Tier 1 — Core (must exist for the game to be playable)

#### F1. Turn-based grid world & movement
Player and entities occupy tiles on a 2D grid; time advances one tick per player action.
- **Why**: The bedrock of the genre. Tactics emerge from positioning.
- **Behaviors**: 8-directional movement, bump-to-attack, wait-in-place, line-of-sight FOV.
- **Depends on**: nothing.

#### F2. Procedural dungeon generation
Multi-floor dungeons with rooms, corridors, doors, stairs, and themed level archetypes
(crypt, flooded sewer, mushroom forest, library of bone, etc.).
- **Why**: Every run is structurally fresh.
- **Behaviors**: Seedable generator; each floor has an archetype that affects palette, monster pool, and loot tables.
- **Depends on**: F1.

#### F3. Combat & damage system
Stats (HP, attack, defense, speed), weapons, armor, status effects (poison, burning, slowed, blessed).
- **Why**: The decision space.
- **Behaviors**: Deterministic with seeded RNG; damage formulas are transparent and inspectable in a log.
- **Depends on**: F1.

#### F4. Items & inventory
Weapons, armor, consumables (potions, scrolls), keys, quest items. Identification mechanic
(unknown potions until tasted/read).
- **Why**: Core loot loop and risk/reward.
- **Behaviors**: Pickup, drop, equip, use, throw. Limited inventory slots force trade-offs.
- **Depends on**: F1, F3.

#### F5. Monsters with behaviors
Diverse enemies with simple but distinct AIs (chaser, ambusher, ranged, summoner, fleeing-when-hurt).
- **Why**: The world needs to push back.
- **Behaviors**: Each monster has a behavior tree or simple state machine; FOV-driven aggro.
- **Depends on**: F1, F3.

#### F6. Permadeath & run lifecycle
A run ends when the player dies; a new run starts with a fresh dungeon.
- **Why**: Stakes.
- **Behaviors**: Death screen with run summary, cause of death, floors reached. Save & quit mid-run; one save slot to prevent save-scumming.
- **Depends on**: F1.

### Tier 2 — Distinctive (the soul of Whisperdeep)

#### F7. The Whisperer — AI Dungeon Master
An LLM-backed narrator that observes game events and emits short atmospheric prose,
monster names, room descriptions, and item flavor.
- **Why**: This is the game's signature. Without it, Whisperdeep is just another roguelike.
- **Behaviors**:
  - Subscribes to a structured event stream (entered_room, killed_monster, low_hp, found_item, descended).
  - Emits 1-3 sentence whispers in a designated UI panel.
  - Names previously-unnamed monsters and items the first time the player sees them ("you sense this is a *Knell-Eyed Verger*").
  - Operates with a strict token/cost budget per run; degrades gracefully to a pre-written prose pool when offline or rate-limited.
- **Depends on**: F1-F6 (needs game events to react to).

#### F8. Director-mode procgen nudging
The Whisperer can request, within constrained parameters, soft nudges to generation:
slightly more healing on a floor where the player is wounded, a thematically resonant
miniboss when the player has been on a kill streak.
- **Why**: This is what makes the dungeon feel *alive* rather than indifferent.
- **Behaviors**: Director can only choose from predefined nudge templates (no arbitrary world mutation). Every nudge is logged; the player can disable director mode for "pure" runs.
- **Depends on**: F2, F7.

#### F9. Run chronicle & death legends
Every run produces a Whisperer-authored chronicle (Markdown) saved to a `chronicles/` folder.
Notable deaths become "legends" referenced by the Whisperer in future runs.
- **Why**: Persistence of narrative across permadeath. Players love showing these off.
- **Behaviors**: Auto-generated at run end; player can name their character; chronicle includes key events, the death scene, and a final whispered epitaph.
- **Depends on**: F6, F7.

#### F10. Persistent meta-memory
A small knowledge store the Whisperer references across runs: the player's previous deaths,
named recurring NPCs, chosen pronouns/character traits.
- **Why**: Continuity. The Whisperer remembers you.
- **Behaviors**: A file-backed memory (e.g., JSON) summarizing prior runs; included in the LLM's context. Bounded size; old entries are summarized down.
- **Depends on**: F7, F9.

### Tier 3 — Polish & depth

#### F11. ASCII / Unicode rendering with palettes
Crisp terminal rendering with thematic color palettes per dungeon archetype.
- **Why**: A roguelike's aesthetic is its terminal. Make it gorgeous.
- **Behaviors**: 256-color or truecolor; configurable glyph set (ASCII-pure or rich Unicode); per-archetype palette swap.
- **Depends on**: F1, F2.

#### F12. Keybinding & command system
Vi-keys, arrow-keys, and a `:`-command prompt for power users.
- **Why**: Roguelike players have strong opinions; respect them.
- **Behaviors**: Rebindable keys via config file; in-game help overlay (`?`).
- **Depends on**: F1.

#### F13. Sound & ambient audio (optional, terminal-friendly)
Subtle ambient drones and one-shot SFX (footstep, hit, descent), gated behind a flag for
pure-terminal purists.
- **Why**: Mood.
- **Behaviors**: Off by default; opt in via config. No music — only ambience and tactile feedback.
- **Depends on**: F1.

#### F14. Daily seed & shareable runs
A daily seed everyone plays the same; shareable seed strings.
- **Why**: Community and replayability.
- **Behaviors**: `--seed` and `--daily` flags; leaderboard file (local first, optionally synced).
- **Depends on**: F2, F6.

## 4. Visual Design Language

Whisperdeep is **not** a flashy game. It is a terminal game, and that constraint is a
gift. The aesthetic should evoke:

- **Candlelit medieval manuscript meets terminal hacker.** Think `htop` rendered onto
  vellum. Glyphs are the art. Color is sparse and meaningful.
- **Palette**: deep desaturated backgrounds (charcoal, ink-black, faded parchment beige),
  with a few accent colors per archetype (bone-white, blood-rust, mushroom-violet,
  drowned-cyan). Never bright. Never neon. The Whisperer's prose panel uses a warm
  off-white on near-black, like ink on candle-warmed paper.
- **Typography**: monospace, always. The HUD uses box-drawing characters (`╔═╗ ║ ╚═╝`)
  but sparingly — most of the screen is the dungeon glyphs and breathing room.
- **Personality**: melancholic, reverent, slightly archaic. The Whisperer never says
  "Awesome!" or "Loading..." — it says "the floor remembers your weight" and
  "the dark exhales."
- **What we explicitly avoid**: emoji-heavy UI, gradient anything, "modern terminal app"
  CLI patterns with rounded boxes and rainbow spinners (this is not a developer tool),
  sci-fi blue holograms, generic fantasy purples. No `ASCII art splash screen with
  glowing border`. The title screen is one line of text and a blinking cursor.

## 5. Technical Architecture (High-Level)

- **Language**: Python 3.11+ (rich ecosystem for terminal games, easy LLM integration).
- **Rendering**: a terminal UI library suitable for grid games (e.g., the `tcod` family
  or equivalent). Choice deferred to the implementing sprint.
- **LLM integration**: provider-agnostic adapter (Anthropic / OpenAI / local) with a
  hard interface so the rest of the game doesn't depend on which model. Pluggable.
- **Persistence**: plain files — JSON for save state and meta-memory, Markdown for
  chronicles. No database needed.
- **Determinism**: a single seeded RNG threaded through all generation; the Whisperer's
  nudges are logged so any run can be (mostly) reproduced.

### Entity model (informal)

- **World** has many **Floors**.
- **Floor** has a grid of **Tiles**, many **Entities**, an archetype, and a generation seed.
- **Entity** is the base for **Player**, **Monster**, **Item**, **Feature** (door, stairs, altar).
- **Run** has a player, a world, an event log, and a chronicle.
- **MetaMemory** persists across runs: prior chronicles' summaries, recurring legends.
- **Whisperer** consumes events, queries an LLM adapter, returns whispers and (optionally)
  director nudges.

## 6. Sprint Decomposition

Twelve sprints. Sprints 1-6 are the playable core; 7-9 add the Whisperer; 10-12 polish.

1. **Foundation & Grid World** — project scaffold, entity/tile/grid types, a player who can move on an empty floor, ASCII render loop. *low*
2. **Dungeon Generation v1** — rooms-and-corridors generator, doors, stairs, multi-floor descent. *medium*
3. **FOV, Combat & Stats** — line-of-sight, fog-of-war, HP/attack/defense, bump-to-attack, damage log. *medium*
4. **Items & Inventory** — pickup/drop/equip/use, weapons, armor, potions, scrolls, identification. *medium*
5. **Monsters & AI** — monster definitions, spawn tables, 4-5 distinct AI behaviors, FOV-based aggro. *medium*
6. **Run Lifecycle** — death, save/load (single slot), run summary screen, daily/seeded runs. *low*
7. **Whisperer Adapter & Event Bus** — LLM adapter interface, in-game event stream, fallback prose pool, cost/token budget guardrails. *medium*
8. **Whispers in Play** — the Whisperer panel UI, monster/item naming on first sight, atmospheric room prose. *medium*
9. **Director Nudges & Meta-Memory** — predefined nudge templates the director can select; cross-run JSON memory; legends referenced in later runs. *high*
10. **Chronicle Generator** — end-of-run Markdown chronicle, epitaph, optional player-named characters. *low*
11. **Themed Archetypes & Palettes** — 4-5 dungeon archetypes (crypt, sewer, mushroom forest, bone library, plus one secret), per-archetype monster pools and color palettes. *medium*
12. **Polish: Keybinds, Help, Sound, Leaderboard** — rebindable keys, `?` help overlay, opt-in ambient audio, local leaderboard, README & shareable run badges. *medium*
